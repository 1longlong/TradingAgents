# ADR-008 — Automatic Structured Optional-Evidence Ingestion and Source-Attempt Lifecycle

- **Status:** Proposed (Stage 1 implementation complete in the working tree;
  offline verification run; independent review pending; human acceptance NOT
  claimed). Plan + test cases for the four-item repair were explicitly approved
  by WANG Yiwen (60536848) in the controlling conversation on 2026-11-11; that
  approval authorizes the plan and the test cases ONLY, and is not a final human
  acceptance. Only Stage 1 (this ADR) is implemented; Stages 2–4 are NOT.
- **Date:** 2026-11-11
- **Deciders:** CS5351 project (student); coding-agent (OpenCode Builder);
  human review required before acceptance
- **Trace:** `FR-DQG-004` (multi-category gate engine), `FR-DQG-005` (report
  artifacts), `FR-DDT-002` (evidence manifest / citation allowlist),
  `NFR-PIT-001` (point-in-time), `NFR-AUD-001` (auditability),
  `NFR-DET-001` (determinism), `NFR-BC-001` (backward compatibility),
  `INV-1`/`INV-3`/`INV-4`/`INV-6`/`INV-8`. No new requirement ID is invented:
  this ADR replaces formerly-deferred scope (DEBT-015 / RISK-015) with
  approved-and-in-progress implementation under the existing IDs.

## Context

The Stage 2 multi-category gate (**FR-DQG-004**) evaluates a critical `market`
category plus the optional categories (`fundamentals`, `news`, `sentiment`).
Today the optional categories enter **only** through a manually-populated
`data_quality_optional_evidence` state mapping, whose values are
already-graded `EvidenceGroupQuality` dicts. Nothing produces that mapping in
the real analyst → gate path, so every optional category is truthfully reported
as unavailable and the gate is always degraded (DEBT-015 / RISK-015). A reader
could mistake "engine supports optionals" for "optionals are wired".

Worse, the manual contract accepts a caller-claimed `quality_status` verbatim,
so a test (or a future caller) could inject `High` without any vendor record
behind it. That is incompatible with the invariant that a run never trusts a
model-written or claimed grade (**INV-1**, **INV-6**).

The three optional categories do have genuine structured vendor returns in the
normal default vendor paths:

- **fundamentals**: SEC EDGAR company-facts JSON (filed dates preserved), and
  the already-structured Alpha Vantage `OVERVIEW`/statement JSON.
- **news**: Yahoo (`yf.Ticker.get_news`, `yf.Search`) and Alpha Vantage
  `NEWS_SENTIMENT` original article objects with published date / url /
  provider lineage.
- **sentiment**: StockTwits messages (source-native `entities.sentiment.basic`
  Bullish/Bearish label) and Reddit Atom posts (no native label).

These are exactly the vendors `route_to_vendor` selects by default. A truthful
ingestion path must adapt those source-origin records — never analyst prose.

## Decision

### A. Typed request/run-scoped side channel (never a global cache)

Add `tradingagents/evidence/ingest.py` holding a **typed request/run-scoped
collector** (`StructuredEvidenceCollector`). It is created per run, held in a
`ContextVar` (so concurrent runs in one process cannot see each other's
records), and never a module-level mutable cache. It accumulates, per run:

- captured `EvidenceRecord` objects (constructible → validated at the gate);
- captured `SourceAttempt` objects for each real configured source attempt, each
  wrapped in a versioned `AttemptEnvelope` carrying an explicit per-run
  `attempt_index` so two genuinely distinct attempts that share every structural
  field (e.g. `started_at=None`) are **both** kept, while a re-sync of the same
  index on resume is a no-op;
- a separate, explicitly **non-attempt** `not_attempted` metadata list for
  configured-but-unoperated feeds (these never enter the attempt ledger and never
  count toward any source count).

**Durability (not just a ContextVar).** LangChain's tool executor copies the
context into worker threads, so `ContextVar` capture reaches the tools, and the
message-clear node later in the same invocation is not required for durability
because the flush happens **at the tool-node boundary itself**. A compiled
`StateGraph` graph node is a plain function with LangGraph's injected
`(state, config, runtime)` signature; `EvidenceCapturingToolNode` wraps a
`ToolNode`, calls `inner.invoke(state, config, runtime=runtime)`, and merges the
collector's captured set into the returned state delta. LangGraph thus
checkpoints the captured evidence with the tool node's own state update (right
after the tool node), and the analyst→tools→analyst loop cannot lose it. A
resumed run re-seeds the collector from that persisted state
(`use_collector(..., prior_state=...)`) and the gate reads the durable
`data_quality_ingested_evidence` / `data_quality_source_attempt_envelopes` state
channels as well as the live collector. This is proven by an actual compiled
graph with `interrupt_after=["tools"]` and a real saver close + graph rebuild +
`invoke(None, cfg)` resume.

### B. Capture happens on source-origin data, before prose formatting

The **default-path vendor functions** that the analyst tools already call
(`get_news_yfinance`, `get_global_news_yfinance`, the Alpha Vantage news /
fundamentals adapters, the **default yfinance** statement functions
(`get_balance_sheet`/`get_cashflow`/`get_income_statement`),
`fetch_stocktwits_messages`, `fetch_reddit_posts`, and a new SEC-facts structure
accessor) capture typed origin records into the active collector **before** they
build their public Markdown/plaintext strings. The public return types and prose
are unchanged (NFR-BC-001): capture is a side effect, never a replacement.

The default yfinance statement path carries only a fiscal **period end** and no
filing date, so those records are captured **undated** (`observed_at=None`, the
period end kept only as lineage in `source_ref`) and are honestly Low — a filing
date is never invented. Alpha Vantage statement rows likewise carry no filing
date and are captured undated; the vendor's **reported currency**
(`reportedCurrency`) is preserved and never hardcoded to USD.

Key separation of concerns:

- `tradingagents/evidence/vendor_adapters.py` (new) turns a vendor's **original
  record** into an `EvidenceRecord` plus per-record `ValidationResult`s. It is
  the honest adapter layer: it never reads prose, never invents a source/date/
  unit (including currency), and records `unsupported`/`malformed`/`empty`
  explicitly for a vendor return that carries no usable structure.
- `tradingagents/dataflows/evidence_capture.py` (new) is the dataflow-side bridge
  that builds those typed records and records the attempts. Capture helpers never
  raise into the public tool (a malformed value is skipped, and the tool's return
  value is unchanged).
- A `SourceAttempt` is emitted for every **actually operated** source attempt
  (success / empty / unconfigured / rate-limited / error / unsupported). The
  router (`route_to_vendor`) records each operated-but-unsuccessful vendor
  attempt (failure / rate-limit / not-configured / no-data) in fallback order
  with a short sanitized classification, and the dataflow adapter records the
  authoritative success attempt **with** the data, so a success is never
  double-counted. No attempt is emitted for a feed the run never attempted
  (configured-but-unreached feeds go only to the `not_attempted` metadata).

### C. Gate merges captured records into category groups + manifest

`create_data_quality_gate_node` now, in addition to the manual
`data_quality_optional_evidence` contract, reads the run's captured typed
records and:

1. validates each record with the per-category deterministic validator;
2. aggregates per-category `EvidenceGroupQuality` (using the real records, the
   same quality precedence as market). The category's own `CategoryPolicy`
   (which supplies `min_independent_sources`) is resolved for the group
   aggregation; the separate `MarketPolicy` is used only for per-record
   classification — the two policies are never conflated;
3. merges those records into `data_quality_evidence_records` (so the manifest,
   citation allowlist, researcher path and saved report see them) and merges
   their per-record validations into `data_quality_validation_results`;
4. records each excluded (future/malformed/undated) record's id so the gate
   prunes it from persisted ingest state — an excluded record can never be
   resurrected as decisive evidence on a later resume;
5. exports the source-attempt ledger in a JSON-safe, documented envelope
   (`data_quality_source_attempts`, the bare 7-field view) for the report
   artifacts, while the durable envelope channel
   (`data_quality_source_attempt_envelopes`) keeps the explicit `attempt_index`.

The manual contract stays compatible but is **weakest**: a manually supplied
group with no captured records behind it can **never** self-assert High/Medium —
a claimed grade is clamped to Low with reason `manual_group_without_records`. It
can only ever *lower* effective optional quality; captured-and-validated records
are authoritative.

The critical `market` block still dominates: a blocked market category blocks
regardless of any optional evidence.

### D. Per-category deterministic validation (never the OHLCV schema)

- Fundamentals require a **filed / available-by** date and an as-of check
  (`filed <= target_date`); a fiscal period-end alone is not availability. A
  late filing (filed after target) is excluded/downgraded, never decisive. A
  vendor with only a period end (default yfinance, Alpha Vantage) yields an
  undated record that is excluded (honestly Low), never given an invented date.
- News requires a **published date**; a missing/malformed/future/bool/non-string
  date cannot be assumed equal to target/retrieval time. Future-published items
  are excluded.
- Sentiment uses source-native labels where present (StockTwits
  Bullish/Bearish); Reddit posts with no native label are recorded as
  **unlabeled** evidence, never assigned an invented sentiment value.
- Numeric fields are validated only where a category genuinely implies a
  numeric (e.g. a fundamental amount); qualitative news/sentiment rows are not
  forced through the OHLCV numeric schema. A NaN/inf/bool/malformed amount is
  never stored as a magnitude (it becomes `None`).
- Deduplication / independence: records carry content **lineage**; Yahoo
  syndication of one article, duplicate filings, or repeated posts are collapsed
  so `independent_source_count` reflects distinct **valid eligible lineages**
  only — never provider wrapper names and never invalid/excluded rows. News/post
  counts are explicitly **not** independent corroboration of a financial claim,
  so an optional category is never graded above Medium.

### D2. Per-record optional classification is fail-closed

`evaluate_optional_record_quality` classifies an optional record from its own
per-category validator results (never the market OHLCV rule, which would mark
every text record's `None` value unusable):

- any `FAIL` -> `Blocked`;
- the category's mandatory checks (`optional.completeness.required_fields`,
  `optional.freshness.publication_date`) must be PRESENT and PASS — an empty
  result set or an all-`NOT_APPLICABLE` set is `Blocked` (incomplete/unknown
  validation never becomes Medium);
- any `WARNING` (with mandatory PASS) -> `Low`;
- otherwise -> `Medium`.

A fundamentals amount-like metric (revenue, net income, total assets, ...) with a
missing/NaN/bool/non-finite magnitude FAILS the amount check; a genuinely text
fundamental fact uses a separate schema (amount check NOT_APPLICABLE).

### D3. Production state, resume identity, concurrency, tombstones

- The durable ingest channels are declared on the **production `AgentState`**
  (`data_quality_ingested_evidence`, `data_quality_source_attempt_envelopes`,
  `data_quality_ingest_metadata`, `data_quality_not_attempted_feeds`,
  `data_quality_dropped_evidence_ids`). An undeclared state key would be silently
  discarded by LangGraph checkpointing, so the graph-integration test builds the
  compiled graph on the production schema, not a divergent custom one.
- On resume, the collector is seeded from the checkpoint state **before** any new
  tool/analyst call, so a new attempt gets a monotonic index after the saved one
  (both kept exactly once). Seeding is identity/schema guarded: a persisted state
  naming a different symbol/target-date/schema version is quarantined (records and
  attempts not adopted) and the current identity is kept.
- Attempt-index allocation and record/attempt mutation are guarded by a lock, so
  concurrent LangChain tool worker threads sharing one collector cannot collide.
- Excluded records are dropped **and tombstoned** in
  `data_quality_dropped_evidence_ids`; `merge_into_state` removes any id
  tombstoned on either side, so a prune-then-union (or a later resume) can never
  resurrect an excluded record as evidence.

### E. Non-goals / explicit safety stops
- No LLM extraction, no analyst-prose parsing, no trusting model-written
  `EvidenceRecord`s, no invented source dates/units/grades.
- No new external provider, no new paid call. Vendor adapters consume the same
  returns the tools already fetch.
- No production threshold tuning and no Phase 4B work.
- The degraded numeric confidence cap (stage 3 item of the approved sequence,
  DEBT-014) and the claim-date/value/unit semantic check (DEBT-022) and durable
  cross-resume budget accounting (DEBT-021) are **out of scope for this ADR**
  and were not implemented here.

## Consequences

- Positive: optional categories are actually populated from real vendor
  structure in the normal path; the manifest / allowlist / report carry
  optional evidence with explicit provenance and attempt outcomes; truthful
  degradation is preserved when a vendor has no structured return.
- Positive: manual injection cannot fabricate a high grade.
- Negative/cost: vendor functions gain a typed side effect and the gate node
  gains a merge step; both must be deterministic and JSON-safe, and the
  source-attempt ledger must be redacted.
- Risk: capturing a wrong shape could over-grade a category. Mitigated by
  per-category validation, explicit unsupported/malformed outcomes, and
  negative tests that pin fail-closed behavior.

## Verification (this ADR's implementation)

Tests (approved test cases) drive a raw vendor fixture through the **real tool
invocation** to the analyst/clear-message boundary and the real gate to the
manifest / allowlist / researcher / report, without manually injecting optional
groups, for fundamentals / news / sentiment; plus normal / degraded / blocked
routing, optional-missing degradation and market-block dominance, malformed /
missing / wrong-shape / NaN / non-string / bool / future-published / late-filed
inputs, deterministic shuffled order, duplicate/syndication lineage,
attempts only for real attempts, and two-symbol / two-date / concurrent-run /
repeated-checkpoint isolation. All tests are socket-disabled and use mocked
vendors/models. Negative tests carry stable requirement IDs.

See `docs/architecture/evaluation-logbook.md`, `docs/architecture/trace-matrix.md`,
`docs/debt-register.md`, `docs/architecture/risk-list.md`,
`docs/ai-use-log.yaml`, and `docs/review-memo.md` for the recorded evidence,
status changes and remaining gaps.
