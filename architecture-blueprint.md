# Integrated core and WebUI records

The canonical layout is `src/` and `test/`. The core records below describe the
release data-quality gate, evidence, debate, usage ledger and output guards;
the WebUI records describe the presentation extension over that core. Existing
requirement and invariant IDs remain scoped to their original modules. An
unqualified core ADR number refers to the release ADR with its descriptive
filename; a WebUI ADR number refers to the WebUI ADR with its descriptive
filename. Both sets remain present. Historical approvals retain their original
scope and do not approve this merge or a new feature. Verification results are
historical unless explicitly identified as a merged-tree run.

## Release core

# Architecture Blueprint — Master Constraint / Design Document

This is the master design document for the CS5351 course project. It states the
hard constraints, the module layout, the two feature implementations, and the
non-functional contract that governs every change. It is authoritative for
design intent; the machine-readable PRD lives in `docs/req/requirements.yaml`,
and traceability lives in `docs/architecture/trace-matrix.md`.

## Repository context

- This is a downstream fork of the upstream `TradingAgents` framework (v0.5.0).
- Canonical source trees are `src/tradingagents/` and `src/cli/`. Tests live in `test/offline/`.
  External-service tests live under `test/live/`. These are real code/test
  trees in this branch, and their READMEs describe the migrated layout.
- The upstream product guide is preserved in `README.md`; the CS5351 overlay is
  a clearly separated appended section.
- The delivered tree also contains the token-observability work: a per-run
  observability collector, structured-output/Single-Pass paths, the batch-macro
  switch, the Finnhub-only news scope, per-run memory isolation, and the archived
  benchmark/freeze apparatus (`scripts/token_benchmark.py`, `scripts/c3_*.py`,
  `token_benchmarks/**`). Its token-observability decisions are ADR-013 through
  ADR-018; the independent simulated-trading decision is ADR-019, and the PR #5
  error-handling integration is ADR-012. These decisions and their requirements
  are the `FR-ANL-*`, `FR-OBS-*`, `FR-HAR-*`, `FR-CAM-*` and `NFR-VER-*`
  families in `docs/req/requirements.yaml`.

## Hard constraints (authoritative)

1. **Determinism.** The evidence gate and the debate evaluator must be pure and
   LLM-free. Identical inputs must yield identical outputs regardless of
   insertion order, clock, or environment. The only injected time value is the
   ISO-8601 `decided_at`, which is validated; when absent a deterministic UTC
   `YYYY-MM-DDTHH:MM:SSZ` string is used.
2. **Fail closed.** An internal error or missing evidence must never look like a
   clean `normal` run. The gate converts any exception into a `blocked` decision
   and the evaluator routes to `summarize`/`insufficient_evidence`.
3. **Point-in-time integrity.** Every dated data path must be evaluated "as of"
   the requested trade date. No future data (look-ahead) may reach a decision.
   This predates the gate work and is a preserved upstream invariant.
4. **Auditability.** Every gate verdict and debate decision carries a stable
   reason code set, a policy version, critical evidence IDs, and a human-readable
   reason; the debate evaluator emits an explicit decision trace.
5. **Budget safety.** Debate termination must reserve budget for the summary so a
   run never exhausts tokens/time/calls mid-debate and fails to produce a report.
6. **Backward compatibility.** New config groups must default to safe values and
   preserve the legacy fixed-round routing when `debate_termination.enabled` is
   `False` or when the gate decides `normal`/`degraded`.
7. **Offline testability.** No unit test may require network or a paid LLM. All
   live/vendor paths are `@pytest.mark.integration` and opt-in.
8. **Secret safety.** No API key, token, or `Bearer`/`sk-` string may appear in
   committed files.

## Phase 1–3B + Phase 4A scope (implemented)

- **Phase 1 (analysis):** read-only repository analysis; requirements frozen.
- **Phase 2 (contract):** evidence model + deterministic gate core (models,
  adapter, validate, policy, quality, gate); decimal-math cleanup.
- **Phase 3A (gate graph integration):** `data_quality_gate` node + router and
  the structured gate-aware `AgentState` fields.
- **Phase 3B (dynamic debate termination):** `debate` package (config, models,
  turn, budget, evidence_manifest, state, evaluator, evaluator_node) plus the
  researchers' verdict gate and the research-manager hold contract.
- **Stage 3 (exact-claim validation, ADR-010):** additive `debate/claims.py` +
  `evidence/origin.py` validate a typed exact claim's date role / value / unit /
  scale against the cited record and typed origin metadata; a valid cited ID no
  longer launders a wrong exact date/value/unit into new evidence, factual
  conflicts, or trusted output. Implemented + offline-verified (NOT human
  acceptance).
- **Stage 4 (degraded-run confidence cap 0.60, ADR-011):** additive
  `debate/confidence_policy.py` caps explicit confidence-labelled numerics on a
  degraded run across debate turns/stances, the evaluator snapshot, the RM/Trader/
  PM typed+prose decisions (typed numeric capped on its exact raw value BEFORE the
  lossy 2dp render), and a shared post-gate state-input sanitizer that caps a
  per-read COPY of the persisted analyst reports / plans / debate+risk histories
  and turn/stance numerics before every post-gate prompt (direct GraphSetup +
  SQLite resume); the API and CLI resume paths run the same fail-closed sanitizer
  first; the report writer and memory log use the effective value. Implemented +
  offline-verified (fresh 2026-11-11 run: cap tests 110 passed, full strict-offline
  2154 passed / 0 sockets; logbook 082; NOT human acceptance).

### Token-observability delivery (implemented; retrospective documentation)

Delivered 2026-10-20 → 2026-11-16 on the personal token-observability line and merged
into this tree. It is documented retrospectively: the requirement IDs and ADRs below
did not exist while the code was being written.

- **Observability and attribution** — `tradingagents/observability.py`
  (FR-OBS-001/003/004, FR-ANL-004; ADR-013).
- **Structured output and Single-Pass** — `tradingagents/agents/utils/structured.py`
  (FR-ANL-003/005; ADR-014, ADR-018).
- **Batch macro** — `tradingagents/agents/utils/macro_data_tools.py` (FR-ANL-006;
  ADR-015).
- **Finnhub-only news** — `tradingagents/dataflows/{finnhub_news,news_merge,news_relevance,news_status}.py`
  (FR-ANL-008; ADR-016).
- **Per-run memory isolation** — experiment harness only (FR-ANL-009; ADR-017).
- **Measurement harness, spend contract, freeze** — `scripts/run_token_benchmark.sh`,
  `scripts/token_benchmark.py`, `scripts/c3_*.py`, `token_benchmarks/**`
  (FR-HAR-001/002/003, FR-CAM-001).
- **Verification of record** — the recorded suite and three independent audits
  (NFR-VER-001/002).

The measured V2/V3 batch numbers are recorded telemetry from those campaigns, not re-run
during this integration. The V3 factorial is **exploratory** (n=1 per cell): the
single-pass point estimate was −19,589 tokens/run (−8.96 %) and the batch-macro point
estimate was −17,702 tokens/run, which fell to about −695 when the environment-degraded
R01 was excluded. None of these is a production performance claim.

### Evidence package (`tradingagents/evidence/`)

### Evidence package (`src/tradingagents/evidence/`)
| Module | Responsibility |
| --- | --- |
| `models.py` | Typed, deterministic, JSON-safe dataclasses (`EvidenceRecord`, `SourceAttempt`, `ValidationResult`, `EvidenceGroupQuality`, `GateDecision`) plus enums and the `quantize_decimal` helper. |
| `adapter.py` | Truthful `StructuredSnapshot` → `EvidenceRecord` adaption and stable evidence-ID generation. |
| `validate.py` | Five deterministic validation classes (completeness, format, freshness, look-ahead, cross-source consistency). |
| `policy.py` | Deterministic `Decimal`-threshold policy objects (`MarketPolicy`, `MarketRecordPolicy`, `MetricTolerance`). |
| `quality.py` | Per-record precedence and per-category aggregation. |
| `gate.py` | `GateDecision` generation with injected `decided_at`; precedence `blocked` > `degraded` > `normal`. |
| `origin.py` | ADR-010 versioned, evidence-ID-keyed typed origin metadata (distinct target/observation/availability/timestamp date roles + unit/currency/scale), kept out of the 20 locked record fields. |

### Debate package (`src/tradingagents/debate/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | Validated `debate_termination` config group; `enabled=False` reproduces fixed-round baseline. |
| `models.py` | `DebateTurn`, `ConflictRecord`, `StanceSnapshot`, `RoundMetrics`, `BudgetState`, `RoutingDecision`, etc. |
| `evidence_manifest.py` | Valid-new-evidence rules against the gate manifest (citation allowlist). |
| `claims.py` | ADR-010 deterministic exact-claim validation (date role/value/unit/scale) against the record + typed origin metadata. |
| `budget.py` | Deterministic usage estimation / accounting; whole-run aggregation; summary admission. |
| `usage_ledger.py` | ADR-009 durable run-scoped SQLite reservation/settlement ledger (strict resume, atomic admission). |
| `usage_capture.py` | ADR-009 run-scoped instrumented model-call capture binding. |
| `researcher_accounting.py` | ADR-009 researcher + summary reservation/settlement glue. |
| `turn.py` | Structured `DEBATE_METADATA` parsing with a best-effort prose fallback; parse failure never extends the debate. |
| `state.py` | Debate-state mutation helpers (researcher side). |
| `evaluator.py` | Pure `evaluate_round` decision rules (authoritative ordering in its module docstring). |
| `evaluator_node.py` | LangGraph Debate Evaluator node factory reading gate manifest / turn state off `AgentState`. |

### Graph integration

- `src/tradingagents/graph/data_quality_gate.py` — dependency-injectable gate node.
- `src/tradingagents/graph/conditional_logic.py` — routers including
  `should_continue_after_data_gate`.
- `src/tradingagents/graph/setup.py` — registers the gate node and evaluator node;
  complete `DEBATE_PATH_MAP` / `DEBATE_EVALUATOR_PATH_MAP` to avoid router
  fall-through crashes.
- `src/tradingagents/agents/researchers/{bull,bear}_researcher.py`,
  `src/tradingagents/agents/managers/research_manager.py`,
  `src/tradingagents/agents/utils/agent_states.py` — verdict gate, citation
  allowlist enforcement, hold contract, and gate-aware state fields.
- `tradingagents/graph/evidence_tool_node.py` — `EvidenceCapturingAnalystNode` and
  `EvidenceCapturingToolNode`, which persist captured vendor evidence at the
  analyst/tool checkpoint (ADR-008).
- **Wrapper composition (verified 2026-11-21).** `GraphSetup` registers each tool node as
  `attrib_tool_round(agent_id, EvidenceCapturingToolNode(tool_node))`
  (`tradingagents/graph/setup.py`). The attribution wrapper is outermost and records one
  tool round per graph tool-node invocation; the evidence wrapper delegates to the inner
  `ToolNode` and does not increment tool-round accounting. The single-pass
  `run_data_tools` path records one round per non-empty batch
  (`INV-25`). Do not re-order these wrappers without re-running the round-count tests.
- `tradingagents/agents/utils/s2_context.py` — typed S2 side channels routed into Bull,
  Bear and the three risk-debate prompts. `s2_downstream` has no OFF implementation; the
  switch verifier refuses to run it as `False` rather than pretending an off-arm exists.
- **Usage settlement (ADR-009).** Structured/single-pass outbound calls are wrapped at
  the transport boundary by `UsageSettlementHandler`; N outbound attempts settle as N
  invocations, never nested or doubled. Parsing, sanitising and rendering happen after
  settlement, so a downstream failure cannot turn a known usage into an unknown-cost
  record.

## Non-functional requirements (NFR) — summary

Referenced by ID; full list in `docs/req/requirements.yaml`:

- `NFR-DET-001` determinism, `NFR-FC-001` fail-closed, `NFR-PIT-001`
  point-in-time integrity, `NFR-AUD-001` auditability, `NFR-BUD-001` budget
  safety, `NFR-BC-001` backward compatibility, `NFR-OFF-001` offline
  testability, `NFR-SEC-001` secret safety.
- Token-observability delivery: `FR-ANL-001…010` (analysis pipeline, typed reports,
  attribution, Single-Pass, batch macro, vendor acquisition), `FR-OBS-001…005`
  (token accounting, usage verdict, tool-round/component accounting, Single-Pass
  settlement, telemetry selection), `FR-HAR-001…003` (measurement harness, freeze
  reproducibility, paid-run spend contract), `FR-CAM-001` (campaign accept/revert),
  `NFR-VER-001…002` (executed verification and independent audit).

## Phase 4A (implemented, approved with limitations)

- **Phase 4A — deterministic offline baseline comparison (NFR-CMP-*):** a pure,
  LLM-free, network-free comparison model/runner (`src/tradingagents/comparison/`)
  that contrasts the legacy fixed-round debate-termination baseline with the
  dynamic policy over identical scripted case identity and turn sequences
  (`scripts/run_phase4a_comparison.py`). Completed and human-approved with
  limitations (WANG Yiwen 60536848, 2026-10-23): results are deterministic
  offline scripted fixtures, not live-provider measurements; the full offline
  suite is not completely green (three known date-sensitive cache failures
  remain); human traceability scores remain `pending`; no production thresholds
  were tuned.


## Token observability and attribution (FR-OBS-001/002/003/004, FR-ANL-004)

`tradingagents/observability.py` is a per-run collector, not a logger. Its contract:

- **Scope model.** `AttributionContext` is a `ContextVar` with exactly one of `agent`
  (set by `attrib_agent_node`), `system` (set by `system_component_scoped`; the only
  shipped component is `pre_graph_reflector`), or `none`. An agent id cannot be used as
  a system component and vice versa.
- **Accounting rule.** A provider call that did not report a usage field is recorded
  `null`; the missing field is counted in `calls_missing_*` and is never added as zero
  (`INV-15`). Run totals are the sum of agent buckets, system-component buckets and the
  unattributed bucket (`INV-16`).
- **Measured-run invalidation.** A `none` event, a non-true `attribution_complete`, an
  attribution summary that does not sum to the call count, an event sum that differs from
  the run total, or a replay that disagrees is `INCOMPLETE`/`MISMATCH` in
  `scripts/token_benchmark.py`; only `VALID` is a measured sample (`FR-OBS-002`). The
  product graph does not abort on `none`; the harness voids the sample (`INV-17`,
  PARTIAL).
- **Artifact.** One atomic JSON per run, unique by `telemetry_run_id`, written with
  `os.replace`; a persistence failure is logged and never fails the analysis.
- **Privacy.** No content fields exist to serialise; the preserved raw usage blob is
  sanitised (`INV-27`).

## Structured output and Single-Pass finalisation (FR-ANL-003/005)

There are two distinct mechanisms and they are not interchangeable:

1. **Whole-turn structured output** (`invoke_structured_or_freetext`) — used by Research
   Manager, Trader, Portfolio Manager and Sentiment Analyst. On failure it retries once as
   free text and returns `None` for the typed object.
2. **Terminal analyst finalisation** — the three tool-loop analysts cannot carry a schema
   on every turn. RC1 uses `finalize_analyst_report` (a second call over the finished
   loop); CAND-01's `finalize_single_pass` binds the schema as an extra tool on the call
   that would have written prose.

Fallback rules: a fallback may return free text but the parsed object is `None`
(`INV-26`); a retry never replays a dangling `tool_call` and keeps the analyst system
prompt (`INV-18`); protocol markup never reaches a report — it is recovered or replaced by
an explicit unavailable sentence (`INV-19`). `single_pass_finalization_enabled` defaults
to `False` and has no effect unless `structured_analyst_output_enabled` is true
(`INV-22`). Accounting for these calls is settled once per outbound attempt (ADR-009).

## Batch-macro switch (FR-ANL-006)

`batch_macro_enabled` (default `True`) controls whether the news analyst binds
`get_macro_indicators_batch` and advertises it. When off, the tool is removed from both
the analyst and the news `ToolNode`, while the single-series `get_macro_indicators`
remains available (`INV-23`). The switch is read once at graph construction; the run
spec's value is verified against the graph by `tradingagents/graph/switch_verification.py`.
The V3 factorial's batch-macro effect is exploratory and not robust (−17,702 tokens/run;
about −695 excluding the environment-degraded R01; n=1 per cell).

## Finnhub-only news provenance (FR-ANL-008)

The shipped configuration routes company news to `get_news_finnhub_only`; the global-news
route answers `CONFIG_DISABLED`; a Finnhub outage is never rescued by GDELT. The GDELT
adapter remains in the tree but is not reachable from the configured route. News
publication times are normalised to UTC and filtered against an exclusive upper bound
(`INV-24`, merged `INV-3`); undated articles are excluded in historical mode; a single
article's relevance is decided by provenance (`news_status.py`, `news_relevance.py`), not
by model prose. Evidence capture records the source attempt on every path that asked the
provider, including the ones that raise.

## Memory: product decision log vs per-run experiment isolation (FR-ANL-009)

Two different memory behaviours coexist and must not be conflated:

- **Product decision log** — the Release behaviour: one append-only log per memory path;
  `record_decision` tags the blocked-run hold; the log is part of the product semantics.
- **Experiment isolation** — harness-only: `scripts/token_benchmark.py` copies one
  registered snapshot into each run's attempt directory, hashes it into `config_sha256`,
  refuses a missing/changed/modified copy before spending, and marks a changed baseline
  after the run as `memory_snapshot_modified` (`INV-20`). A generic `propagate()` run or
  the CLI `measure` path still uses the shared host memory log; the isolation guarantee
  applies to registered experiment runs, not to every invocation.

The pre-graph reflector is a provider call outside every graph node; it is attributed to
`system:pre_graph_reflector`, never to an analyst (`INV-17`).

## Measurement harness, spend contract and reproducibility (FR-HAR-001/002/003, FR-CAM-001)

- **One command.** `scripts/run_token_benchmark.sh` resolves the repository from any
  working directory, defaults to the fixed benchmark ticker/trade date, supports a
  credential-free dry-run, and archives every attempt.
- **Freeze binding.** A measured batch is reproducible from commit + annotated tag +
  freeze record + per-file `MANIFEST.sha256` + per-run `config_sha256`. The verifier
  recomputes every digest and refuses a drifted tree; tags are local, and a dirty tree can
  fail a freeze check even when the code is correct (`INV-21`).
- **Spend contract.** A paid run is admitted only under an explicit budget contract: a
  null cap means unlimited **only** with `budget_mode="uncapped_authorized"`; missing
  protocol, malformed block, missing mode and non-integer cap are distinct refusals;
  unknown spend is `unknown`, never zero; reserved tokens count toward a real cap
  (`FR-HAR-003`). This is a separate enforcement point from the debate summary reserve.
- **Campaign discipline.** Each optimisation round is research → hypothesis → offline
  analysis → implementation → tests → real multi-run measurement → quality assessment →
  explicit accept or revert (`FR-CAM-001`). A reverted round leaves no accepted code.

## Verification of record (NFR-VER-001/002)

The delivered evidence is an executed offline suite plus three independent read-only
audits, not a prose claim. Recorded at the token-observability commit `50b2ca3`: 2,227
passed, 4 known failed, 2 skipped, 319 subtests; a `.env`-free run of the deliverable:
2,233 passed, 0 failed, 2 skipped, 319 subtests; three independent audits PASS. A known
failure is named with its cause and never removed by weakening an assertion. During the
D1/D2 integration the merged-tree full suite is **NOT_RUN** while unrelated D4–D9
documentation conflicts remain; this is stated, not hidden.

## Integration seams and single-source rules

Five accounting/observability scopes coexist. They answer different questions and are
never interchangeable:

| Scope | Enforcer | What it measures | Not to be used for |
| --- | --- | --- | --- |
| Debate budget | `tradingagents/debate/budget.py` | debate optional calls vs `max_calls/max_tokens/max_time` + summary reserve | whole-run spend |
| Durable ledger | `tradingagents/debate/usage_ledger.py` | per-run reservation/settlement across resume | agent attribution |
| Paid-run spend contract | `tradingagents/budget_guard.py` + `scripts/token_benchmark.py` | known spend vs an explicit cap | debate admission |
| Per-agent telemetry | `tradingagents/observability.py` | run-wide calls/tokens by agent/system/none | budget enforcement |
| Report provenance | `tradingagents/report_artifacts.py` | debate-scoped measured/estimated labels | run-wide totals (they are `null`) |

Rules that follow from this:

1. `run_summary.json` is not a substitute for telemetry and vice versa (see "Permissions
   and observability").
2. One outbound call settles once (ADR-009); the telemetry callback also records it. Both
   views must reconcile by identity, not by summing them together.
3. Evidence capture and tool-round attribution are independent wrappers; one graph tool
   invocation yields one capture flush and one round.
4. The simulated-trading subsystem is downstream of the graph and makes no provider call;
   do not instrument it as an LLM consumer.

## Appendix A — Delivered multi-agent pipeline reference

The shipped graph (Release topology, unchanged by the token-observability work):

```
START
  → Market Analyst ⇄ tools_market → Msg Clear Market
  → Sentiment Analyst → Msg Clear Sentiment        (no tools bound; data prefetched)
  → News Analyst ⇄ tools_news → Msg Clear News
  → Fundamentals Analyst ⇄ tools_fundamentals → Msg Clear Fundamentals
  → Data Quality Gate
  → Bull Researcher ⇄ Bear Researcher            (debate rounds; evaluator after each)
  → Research Manager
  → Trader
  → Aggressive ⇄ Conservative ⇄ Neutral Analyst   (risk rounds)
  → Portfolio Manager
  → END
```

- Analyst selection is `("market", "social", "news", "fundamentals")` by default; the
  execution plan supports subsets and preserves order.
- Each analyst routes to its own `ToolNode` when the last message has `tool_calls`,
  otherwise to its message-clear node; debate and risk routers use complete path maps so a
  fall-through speaker label cannot produce a missing edge.
- Round counts are configuration (`max_debate_rounds`, `max_risk_discuss_rounds`).
- State channels: `market_report`, `market_report_obj`, `sentiment_report`, `news_report`,
  `fundamentals_report`, `fundamentals_report_obj`, `investment_debate_state`,
  `investment_plan`, `trader_investment_plan`, `risk_debate_state`,
  `final_trade_decision`, plus `trade_date`, `instrument_context`, `past_context` and
  `portfolio_context`.
- The simulated-trading subsystem runs only after `final_trade_decision` and never
  modifies the graph.


## Authority boundaries (advice vs. authority)

The system produces **advice**; it never has **authority** to trade, commit, or
change governance on its own.

| Actor | Authority | Boundary |
| --- | --- | --- |
| Human (WANG Yiwen, 60536848) | Ultimate: scope, safety, git, network, approvals | Owns `.opencode/rules.md` (human-only) and every phase/review decision |
| OpenCode | Read/analyze/implement within the active authorized scope | May suggest; must stop and ask on any denied action |
| Runtime graph (gate/evaluator/agents) | Emits a verdict/recommendation within deterministic rules | Cannot override a blocked verdict downstream (FR-DQG-006) |

Advice is never promoted to authority by an AI: human decisions cannot be
inferred, authored, or backfilled by an agent (see `Prompt.md`, ADR-004).

## End-to-end workflow and change controls

1. **Read instructions first** (`AGENTS.md`, this blueprint, `invariants.md`,
   `trace-matrix.md`, `pyproject.toml`, `test/conftest.py`).
2. **Plan first** — output a traceable execution plan (scope, interfaces, tests,
   steps, risks) and **STOP for human approval** before any feature code/test edit
   (`prompts/prompt_v1.3.yaml`).
3. **Implement** only the approved, in-scope requirement.
4. **Verify** with the offline deterministic suite + validator + Ruff +
   `git diff --check`; record exact outcomes.
5. **Record** AI use (`docs/ai-use-log.yaml`) and human review
   (`docs/review-memo.md`); update the trace matrix in the same change.
6. **Human review at every phase boundary**; a phase without a recorded human
   decision is not complete.

Safety-critical changes (gate/evaluator/output-guard/fail-closed/budget
semantics, permission boundaries, prompts) require an **ADR + explicit human
approval** before merge (see `docs/code-governance/structural-constraints.md`).
Scope, safety, or plan changes trigger **reapproval**.

## Permissions and observability

- **Permissions:** a role-by-path, deny-by-default whitelist is specified in
  `docs/architecture/permission-model.md` (Human/Planner/Builder/Verifier) and a
  machine-readable **proposal** (not active) ships in
  `docs/code-governance/agent-permissions-proposal.yaml`. The **existing shipped**
  `.opencode/permissions.jsonc` is unchanged this turn, but its existence is not
  proof it is loaded/enforced: **loading/enforcement is unverified** (RISK-006 /
  DEBT-004). JSON-parses ≠ config-enforced.
- **Observability (report artifacts):** the runtime emits a gate summary
  (`0_quality/gate_summary.md`), evidence manifest (`0_quality/evidence_manifest.json`),
  debate trace (`2_research/debate_trace.json`), and run summary (`run_summary.json`),
  plus a decision trace in `AgentState`. A per-requirement runtime/audit-monitor mapping
  (real hooks vs. planned) is recorded in the trace matrix.
- **Observability (token telemetry, personal delivery):** `tradingagents/observability.py`
  writes one atomic telemetry artifact per run at
  `<results_dir>/<safe_ticker>/<date>/telemetry/<run_id>.json` (schema 2), finalised by
  `finalize_observability_run` on the CLI success and failure paths. It records counts,
  sizes, hashes, ids, model/provider names and sanitised usage only — never prompt,
  message, tool-result, news or memory content (`INV-27`).
- **Two usage views are deliberately not merged.** `run_summary.json`'s
  `usage_provenance` is **debate-scoped** and reports `total_run_calls` / `tool_calls` as
  `null`; the telemetry artifact is the **run-wide** source. The report writer does not
  read the collector (`tradingagents/report_artifacts.py` imports no observability
  module), so `run_summary.json` does **not** contain every telemetry value. Treat them
  as two artifacts with two scopes; never sum or equate them.

## Governance context design (PROPOSED — not implemented)

A layered, deterministic context-assembly design — immutable safety layer,
human-governance layer, stable ADR/invariant layer, task-plan layer, working
evidence layer, history layer — with a 131072-token school-context design budget,
proposed compaction thresholds, keep/drop rules, a provenance-preserving summary
schema, and critical-constraint re-injection after compaction/restart is
specified in `docs/architecture/adr/004-governance-context-design.proposed.md`.
It is **PROPOSED only**: no runtime assembly/compaction code exists, none is
enforced, and INV-14 is marked unverified. The existing `max_tokens` /
`reserved_summary_tokens` govern model *output*, not the context window.

## Out of scope

- **Phase 4B** (live-provider benchmarking) is not started and is not designed
  here; it remains prohibited without separate explicit human authorization.
- **Production threshold tuning** is not in scope and remains prohibited without
  separate explicit human authorization.
- No new data vendors, no new LLM providers, no UI/feature work beyond the two
  requested improvements and the approved Phase 4A offline comparison.
- No relocation or duplication of source trees.

## Open / uncertain items

Marked `TODO` in `docs/debt-register.md` and `docs/architecture/risk-list.md`.
The student identity is **confirmed** as WANG Yiwen (CS5351 ID 60536848); the
identity risk is resolved (RISK-004 / DEBT-005). Remaining open items include:
the OpenCode `permissions.jsonc` schema/enforcement against the installed
OpenCode version (RISK-006 / DEBT-004); the degraded confidence ceiling
(DEBT-014 — now implemented as ADR-011 Stage 4, 0.60 engineering ceiling,
offline-verified, awaiting independent OpenCode review + human acceptance);
automatic optional adapters (DEBT-015 / RISK-015); and the live-run
budget-accounting basis and claim-date semantics found on 2026-11-06 (DEBT-021 /
DEBT-022 / RISK-020 / RISK-021). This is **not** claimed to be the "only
remaining uncertainty"; the earlier single-item framing was stale and is
corrected here.

## WebUI extension

# TradingAgents WebUI Architecture Blueprint

Status: **Architecture decisions approved for documentation by the human owner on 2026-11-05.** Iterations 1–3 are implemented under conversation approvals; implementation review, safety/governance markers, and dependency approval remain pending. The selected stack is recorded in ADR-001 through ADR-012.

Owner: human project owner. Prepared by the Docs role on 2026-11-05.

## 1. Authority and scope

This blueprint is subordinate to `AGENTS.md`, `Prompt.md`, `.agent/rules.md`, `.opencode/rules.md`, and `docs/code-governance/structural-constraints.md`. It extends the TradingAgents v0.5.0 baseline at commit `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f` on branch `feature/webui`. It does not replace the baseline, the CLI, the Python API, or any existing business rule.

The WebUI is a **local, single-user, single-active-run presentation layer**. It displays and orchestrates capabilities that already exist. It must not add analysis capability, data sources, model providers, trading behaviour, agent logic, or persistence.

<a id="goals"></a>
## 2. Goals

1. Expose the complete CLI analysis workflow through a browser: the eight selection steps, live run view, completion summary, and full I–V report.
2. Preserve every deterministic boundary already enforced by the core and CLI: ticker and path validation, analysis-date limits, rating integrity, portfolio semantics, point-in-time data access, memory isolation, and checkpoint behaviour.
3. Keep `src/tradingagents/` and `src/cli/` unchanged. The WebUI calls existing public Python interfaces, reads existing artifacts, and preserves CLI report formats. Web-only lifecycle metadata accompanies isolated Web run artifacts.
4. Provide read-only history over existing artifacts without a database or a retention change.
5. Expose the existing backtest capability with the same parameters and result semantics as the CLI.
6. Keep provider keys server-side. The browser never receives keys or server filesystem paths.
7. Support Chinese/English UI switching, independent of the report output language.
8. Keep the browser, HTTP surface, event stream, and frontend build isolated from the core.

<a id="non-goals"></a>
## 3. Non-goals

- Trading execution, order placement, position changes, or brokerage integration.
- New data vendors, model providers, model catalogues, prompts, agents, or rating rules.
- Multi-user accounts, tenants, billing, quotas, or authentication.
- New databases, message queues, caches, or cross-process run persistence.
- Cloud deployment, container orchestration, domain/TLS provisioning, or release automation.
- PDF or Word export; native mobile applications.
- Multi-ticker batch analysis outside the existing backtest command.
- Cross-run comparison, scoring dashboards, or backtest charts in the first release.
- Any change to CLI arguments, defaults, output, exit codes, or core behaviour.

## 4. Baseline code facts that constrain the design

| Fact | Evidence | Consequence |
| --- | --- | --- |
| Core configuration is a module-level singleton | `src/tradingagents/dataflows/config.py` (`_config`, `set_config`) | Two graphs with different configs must not run concurrently in one process. |
| The CLI message buffer is a module-level singleton | `src/cli/main.py` (`message_buffer = MessageBuffer()`) | The web layer owns its own run state and does not reuse this object. |
| The CLI streams the graph directly | `src/cli/main.py` (`run_analysis`, `graph.graph.stream`) | The CLI stream path is the behavioural reference for live updates. |
| `propagate()` writes a state log | `src/tradingagents/graph/trading_graph.py` (`_log_state`) | API-style runs may have `full_states_log_*.json`; CLI-style runs do not. |
| Decision memory is read-modify-write with atomic replacement | `src/tradingagents/agents/utils/memory.py` | Concurrent writers are not proven safe; the single-run rule protects the log. |
| Checkpoints are per-ticker SQLite databases | `src/tradingagents/graph/checkpointer.py` | A run can resume only when checkpointing was enabled and the process is available. |
| Report serialization is shared | `src/tradingagents/reporting.py` (`write_report_tree`) | The web layer calls this writer; it does not reimplement section layout. |
| Path safety is deterministic | `src/tradingagents/dataflows/utils.py` (`safe_ticker_component`) | The web layer reuses it for every ticker/run-id path component. |
| Rating extraction is deterministic | `src/tradingagents/agents/utils/rating.py` | The web layer does not infer or repair a rating. |
| Portfolio states are distinct | `src/tradingagents/portfolio.py` | No portfolio, an empty book, and a populated book are three different inputs. |
| Backtest is synchronous and has no cancellation hook | `src/tradingagents/backtest.py` (`run_backtest`) | The web layer does not pretend to cancel a backtest. |
| Stats and wall-time helpers exist | `src/cli/stats_handler.py`, `src/tradingagents/graph/analyst_execution.py` | The web layer reuses them for live statistics and timing. |

## 5. System context

```
Browser: React 19 + TypeScript + Vite SPA
  |  same-origin REST (JSON)
  |  same-origin SSE (text/event-stream)
  v
FastAPI + Uvicorn (single worker, 127.0.0.1)
  |-- Security middleware: Host / Origin / CSRF / CSP / size limit
  |-- Configuration projection (read-only)
  |-- Run coordinator (single active run, worker thread bridge)
  |-- Event projection and bounded SSE buffer
  |-- Artifact read model (hash identifiers, read-only)
  |-- Backtest surface
  v
Existing public Python interfaces and on-disk artifacts
  |-- TradingAgentsGraph (public methods)
  |-- run_backtest / summarize
  |-- write_report_tree
  |-- TradingMemoryLog (through existing graph methods)
  |-- results_dir, checkpoint directory, CLI preferences
```

The browser never imports Python, never receives a server path, and never receives a secret. The core and CLI never import the web layer.

## 6. Logical components

<a id="w1-entry-and-parameter-surface"></a>
### 6.1 W1 — Entry and parameter surface

Owned by `src/tradingagents_web/api/config.py`, `api/runs.py`, `models/requests.py`, and the frontend wizard.

Responsibility: render the eight selection steps, validate inputs, and submit a run request.

Inputs: ticker, analysis date, output language, analyst selection, research depth, provider and endpoint, quick/deep model, provider thinking parameters, checkpoint flag, portfolio JSON, and the announcement acknowledgement.

Outputs: a validated run request or a field-level error.

Rules:
- Validation mirrors the CLI and core rules; the core remains authoritative.
- The provider/API-key step displays `configured / not_configured / not_required` from the server environment and never accepts a key.
- Provider and quick/deep models are preselected from server defaults and remain editable in Web analysis. Other environment-locked settings remain read-only with their source; see the model-defaults refinement.
- Crypto detection filters out the fundamentals analyst, matching `filter_analysts_for_asset_type`.
- The request accepts only the allowlisted fields; the client cannot submit a config dictionary or a filesystem path.

Failure modes: invalid ticker, future date, no analyst, unknown provider/model, invalid portfolio, missing server key (allowed to start, fails at the first provider call).

<a id="w2-run-coordinator"></a>
### 6.2 W2 — Run coordinator

Owned by `src/tradingagents_web/runtime/coordinator.py`, `runtime/graph_runner.py`, and `runtime/artifacts_writer.py`.

Responsibility: own the lifecycle of the single active analysis run.

Inputs: a validated run request.
Outputs: a run record, an ordered event sequence, and final artifacts.

Ownership:
- Creates one fresh `TradingAgentsGraph` per run.
- Calls `create_run_state`, `begin_checkpoint`, `checkpoint_input`, `graph.stream`, `record_decision`, `clear_checkpoint_on_success`, `end_checkpoint`, `process_signal`, and `write_report_tree`.
- Owns cancellation, completion, failure, and reattachment.
- Holds the run record and event buffer in process memory only.
- Runs the synchronous graph stream in a single-worker `ThreadPoolExecutor`; events are pushed back with `loop.call_soon_threadsafe`.

Rules:
- At most one run may be active. A second submission is rejected with `409 conflict`.
- A browser disconnect does not cancel the run.
- Cancellation stops consuming, writes no decision entry, clears no checkpoint, ends the checkpoint scope in `finally`, and keeps artifacts already written.
- The coordinator never fabricates a rating. It reads the deterministic signal and surfaces `REVIEW`.
- The coordinator does not write `full_states_log_*.json`; it follows the CLI stream path.

<a id="w3-configuration-projection"></a>
### 6.3 W3 — Configuration projection

Owned by `src/tradingagents_web/api/config.py` and `runtime/config_projection.py`.

Rules:
- Reads `DEFAULT_CONFIG`, `TRADINGAGENTS_*` environment overrides, the provider table, the model catalogue, and `~/.tradingagents/cli_prefs.json`.
- Never writes the core configuration singleton except indirectly through `TradingAgentsGraph`, which the existing code already does.
- Environment precedence is displayed, not re-implemented differently.
- The CLI preferences file is read-only. Web runs do not write it.
- Responses exclude `project_dir`, `results_dir`, `data_cache_dir`, `memory_log_path`, and any credential value.
- `backend_url` is redacted of userinfo before display.

<a id="w4-event-projection"></a>
### 6.4 W4 — Event projection

Owned by `src/tradingagents_web/runtime/projector.py`, `runtime/event_buffer.py`, and `models/events.py`.

Event envelope: `run_id`, `seq`, `timestamp`, `type`, `payload`.

Required event types:

| Type | Payload (minimum) |
| --- | --- |
| `run.preparing` | ticker, trade_date |
| `run.started` | ticker, trade_date, asset_type, analysts, depth, provider, models, checkpoint flag |
| `run.resumed` | checkpoint step |
| `agent.status` | agent, status in {pending, in_progress, completed} |
| `message` | timestamp, message type, content |
| `tool_call` | timestamp, tool name, arguments |
| `report.section` | section key, title, content |
| `stats` | agents, llm calls, tool calls, tokens in/out, reports, elapsed |
| `run.completed` | signal, review flag, wall times, artifact ids, warnings |
| `run.failed` | category, safe message, correlation id |
| `run.cancelled` | cancelled_at |
| `snapshot` | current state, last_seq |
| `backtest.progress` | optional, cells done/expected |
| `backtest.completed` | structured summary |

Rules:
- Events are ordered by `seq`; reattachment replays from the last sequence.
- The stream is one-way. Client actions use REST endpoints.
- Payloads contain no secrets, absolute paths, stack traces, or raw credentials.
- The buffer is bounded by count and approximate bytes; an overflow sends a snapshot.
- Each subscriber has a bounded queue; a slow subscriber is dropped to snapshot mode.
- Heartbeat is an SSE comment every 15 seconds.

<a id="w5-artifact-read-model"></a>
### 6.5 W5 — Artifact read model

Owned by `src/tradingagents_web/artifacts/index.py`, `artifacts/readers.py`, and `artifacts/downloads.py`.

Sources:
- Legacy CLI run directory: `<results_dir>/<ticker>/<date>/` with `message_tool.log` and `reports/*.md`; the Web layer never rewrites it.
- Web run directory: `<results_dir>/web_runs/<run_id>/`, with the same message/section report formats and a `run.json` lifecycle sidecar. Each run has its own directory, including repeated analyses of the same ticker/date. The sidecar is artifact metadata, not an index database or cross-process task recovery mechanism.
- API-style state log: `<results_dir>/<ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json` when present.
- Saved report tree: `<results_dir>/reports/<ticker>_<timestamp>/` with `1_analysts` … `5_portfolio` and `complete_report.md`.
- Backtest run: `<results_dir>/backtest/<run_id>/` and its `trading_memory.md`.
- Decision memory: `~/.tradingagents/memory/trading_memory.md`, read-only.

Rules:
- Read-only. No deletion, rotation, migration, or index database.
- `artifact_id = sha256(relative_path)[:16]`; the server builds the id-to-path map on scan and never persists it.
- Every identifier resolves through a validated root allowlist and `safe_ticker_component`.
- Missing optional artifacts are reported as absent, not synthesized.
- History works for CLI-style runs that lack `full_states_log_*.json`.
- Scan limits: at most 500 runs, 50 per page, bounded report size.

<a id="w6-backtest-surface"></a>
### 6.6 W6 — Backtest surface

Owned by `src/tradingagents_web/api/backtests.py` and `runtime/backtest_runner.py`.

Rules:
- Parameters mirror the CLI: tickers, start, end, every, analysts, asset type, portfolio, run id.
- The summary mirrors `summarize(...)`: resolved, pending, unscored, per-rating count/hit rate/mean alpha, holding window, failures, settlement failures.
- The response does not include `log_path`; it includes an artifact id for the log.
- Backtest and live analysis remain isolated. The web layer does not point a backtest at the live memory log.
- A backtest is a run for the single-active-run rule.
- **Backtest cancellation is not offered.** `run_backtest` has no cancellation hook; the UI must not claim otherwise. Analysis cancellation is unaffected. A backtest can be resumed with `run_id` after an interruption.

<a id="w7-security-boundary"></a>
### 6.7 W7 — Security boundary

Owned by `src/tradingagents_web/security.py`, `errors.py`, and the frontend renderer. The full permission matrix is in `docs/architecture/permission-model.md`.

1. **Network**: bind to `127.0.0.1` only. Reject non-loopback `Host` headers. No authentication by confirmed scope; loopback, Host, Origin, and CSRF checks are mandatory compensating controls.
2. **Secrets**: provider keys come only from the server environment. The browser receives status only. Errors and events are redacted.
3. **Paths**: the browser receives artifact identifiers, not filesystem paths. Resolution uses `safe_ticker_component` and a root allowlist.
4. **Untrusted content**: model output, tool output, announcements, and artifact text are data. Render as escaped text or a sanitized Markdown subset. No raw HTML, no script execution, no `javascript:` or `data:` links, no server-side template evaluation.
5. **Requests**: state-changing requests require a CSRF token and a same-origin signal; no wildcard CORS. Body size is bounded.
6. **Files**: no generic file browser, upload-to-server-path, or download-by-path endpoint. Portfolio uploads are read as text, validated, and discarded.
7. **Logging**: no keys, cookies, authorization headers, absolute paths, or third-party prompt content.
8. **Headers**: CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `frame-ancestors 'none'`.

<a id="w8-frontend"></a>
### 6.8 W8 — Frontend

Owned by `src/tradingagents_web/frontend/` (source) and `src/tradingagents_web/static/` (build output).

Stack: React 19, TypeScript strict, Vite, Tailwind CSS, shadcn/ui (Radix primitives), Lucide, Zustand, TanStack Query, React Router, react-i18next, React Hook Form + Zod, react-markdown + remark-gfm + rehype-sanitize.

Rules:
- UI state derives from server events and snapshots; the frontend does not compute ratings or business decisions.
- The live view mirrors the TUI information set and adds a section switcher and full-content detail drawer.
- The report view mirrors sections I–V and the complete report.
- History and backtest views are read-only.
- Chinese/English strings are UI-only; report content follows the existing output-language setting.
- The app reconnects with a snapshot and an SSE `after_seq`.
- No raw HTML, no `dangerouslySetInnerHTML` for untrusted content, no external images by default.

## 7. Module ownership and dependency direction

<a id="proposed-ownership-paths"></a>
### 7.1 Ownership paths (approved for documentation)

| Element | Path | Owns |
| --- | --- | --- |
| Web package | `src/tradingagents_web/` | Presentation-only package; never imported by core or CLI. |
| App and entry | `app.py`, `cli.py`, `settings.py` | App factory, argparse/uvicorn, limits. |
| Security | `security.py`, `errors.py` | Host/Origin/CSRF/CSP, error taxonomy, redaction. |
| API | `api/session.py`, `api/config.py`, `api/announcements.py`, `api/runs.py`, `api/history.py`, `api/backtests.py` | HTTP contracts and validation. |
| Runtime | `runtime/coordinator.py`, `graph_runner.py`, `backtest_runner.py`, `projector.py`, `event_buffer.py`, `artifacts_writer.py` | Run lifecycle, thread bridge, events, artifact writes. |
| Artifacts | `artifacts/index.py`, `readers.py`, `downloads.py` | Read-only scan, parsing, downloads. |
| Models | `models/requests.py`, `responses.py`, `events.py` | Pydantic request/response/event schemas. |
| Frontend source | `frontend/` | React/TS source, i18n, tests. |
| Build output | `static/` | Generated assets; not committed. |
| Offline tests | `test/offline/test_web_*.py` | Deterministic contract/security/behavior tests. |
| Live tests | `test/live/test_web_live.py` | Requires external-service and cost authorization. |

### 7.2 Dependency direction

| From | To | Allowed | Notes |
| --- | --- | --- | --- |
| `tradingagents_web` | `tradingagents` | Yes | Public core interfaces only for business semantics. |
| `tradingagents_web` | `cli` | Yes, restricted | Reuse provider/model/prefs/stats helpers; no CLI global state mutation. |
| `tradingagents` | `tradingagents_web` | **No** | Core must not depend on presentation. |
| `cli` | `tradingagents_web` | **No** | CLI must not depend on presentation. |
| Frontend | `/api` | Yes | No direct Python, filesystem, or provider access. |
| `tradingagents_web` | DB/MQ/broker | **No** | No new persistence or messaging. |

## 8. Interface contracts

<a id="run-request"></a>
### 8.1 Run request

`POST /api/runs` accepts:

```json
{
  "client_request_id": "uuid",
  "ticker": "NVDA",
  "trade_date": "2026-11-05",
  "asset_type": "stock",
  "output_language": "English",
  "analysts": ["market", "social", "news", "fundamentals"],
  "research_depth": 1,
  "llm_provider": "openai",
  "backend_url": null,
  "quick_think_llm": "gpt-5.6-luna",
  "deep_think_llm": "gpt-5.6",
  "google_thinking_level": null,
  "openai_reasoning_effort": null,
  "anthropic_effort": null,
  "checkpoint": false,
  "portfolio_json": null
}
```

Validation:
- Ticker: CLI charset/length rules, then canonicalization.
- Date: `YYYY-MM-DD`, not in the future.
- Analysts: at least one known key; crypto excludes fundamentals.
- Depth: one of 1, 3, 5.
- Provider/model: resolve through the existing provider/catalogue code.
- Portfolio: validated by `PortfolioContext`; three states preserved.
- No client-supplied filesystem path or config dictionary is accepted.
- `client_request_id` deduplicates double submits within the active run.

Success: `201` with `{run_id, status, started_at}`. Conflict: `409`.

<a id="run-state"></a>
### 8.2 Run state

States: `idle`, `starting`, `running`, `cancelling`, `completed`, `failed`, `cancelled`.

Only one run may be in `starting`, `running`, or `cancelling`.

Run record: `run_id`, effective request fields, `status`, `started_at`, `finished_at`, `last_seq`, `signal`, `review`, `artifact_id`, `warnings`, a safe correlated error, report sections, the last 500 messages/tools, agent statuses, counters, and execution phase. Snapshot content and its event cursor are captured under the same lock.

`GET /api/runs/{run_id}` returns the snapshot; `GET /api/runs/{run_id}/events` returns SSE.

<a id="cancellation"></a>
### 8.3 Cancellation

1. Set the cancellation event.
2. Stop consuming the graph stream at the next chunk boundary.
3. End the checkpoint scope in `finally`.
4. Do not call `record_decision`.
5. Do not call `clear_checkpoint_on_success`.
6. Keep artifacts already written.
7. Mark `cancelled` and publish `run.cancelled`.

If checkpointing was disabled, the run cannot be resumed. If enabled, the existing checkpoint remains for the existing resume path. If the worker does not finish within 30 seconds, return `cancelling`; the single-run slot remains occupied until the worker exits.

<a id="reattachment"></a>
### 8.4 Reattachment

- The run continues while the server process lives.
- The client gets a snapshot, then connects to SSE with `after_seq`.
- The server replays the buffer or sends a snapshot if the sequence is too old.
- After a server restart the active run is gone; on-disk artifacts and checkpoints may remain for CLI/API paths. Cross-process recovery is out of scope.

<a id="report-artifact-contract"></a>
### 8.5 Report and artifact contract

- `write_report_tree` remains the only report-layout writer.
- Web runs use isolated `results_dir/web_runs/<run_id>/` directories; legacy CLI paths remain unchanged.
- The runtime artifact writer mirrors the CLI's `message_tool.log` and `reports/<section>.md` writes.
- On successful completion the coordinator auto-saves the complete report tree to `results_dir/reports/<ticker>_<timestamp>_<run_id>/`, retaining the existing report-tree format while preventing same-second collisions.
- Downloads resolve an artifact id server-side; `kind=complete|archive|section`.
- The complete Markdown report and a zip of existing report artifacts are the supported downloads. No PDF/Word.
- A report-save failure produces `run.completed` with `warnings: ["report_save_failed"]`; it does not rewrite the analysis result.

<a id="history-contract"></a>
### 8.6 History contract

- Read-only projection over the sources in Section 6.5.
- History item identified by a stable hash artifact id.
- Missing fields are shown as absent.
- No delete, rename, move, retention change, or index write.
- No server path is returned.

<a id="error-taxonomy"></a>
### 8.7 Error taxonomy

| Category | Meaning | Client behaviour |
| --- | --- | --- |
| `validation` | A request field is invalid | Show field errors; do not start |
| `conflict` | A run is already active | Explain and offer to view the active run |
| `not_found` | Run or artifact id does not resolve | Show a safe not-found message |
| `config` | Provider/model/key configuration is unusable | Show the safe configuration error |
| `upstream` | Data vendor or model provider failed | Show a safe retryable message; preserve the run record |
| `storage` | Artifact write/read failed | Show a safe storage message; do not expose paths |
| `cancelled` | The user cancelled | Show the cancellation state |
| `internal` | Unexpected failure | Show a generic message with a correlation id |

HTTP mapping: `422 validation`, `409 conflict`, `404 not_found`, `403 security`, `413 size`, `502 upstream`, `500 storage/internal`.

<a id="state-ownership-and-concurrency"></a>
## 9. State ownership and concurrency

| State | Owner | Storage | Lifetime | Writers | Readers |
| --- | --- | --- | --- | --- | --- |
| Active run record | `RunCoordinator` | Process memory | Until server exit or 5 min after terminal state | Coordinator only | API, SSE |
| Event sequence | `EventBuffer` | Bounded process memory | Run + 5 min | Projector only | SSE subscribers |
| Graph/checkpoint | `TradingAgentsGraph` | Core objects + SQLite | Run / existing checkpoint | Worker thread | Coordinator |
| Decision log | `TradingMemoryLog` via graph | Markdown file | Persistent | Graph only | History read model |
| Run artifacts | `RunArtifactWriter` | Existing `results_dir` layout | Persistent | Worker thread | History read model |
| History index | `ArtifactIndex` | Process memory cache | 5 s TTL | Scan only | History API |
| UI state | Zustand store | Browser memory | Tab lifetime | Frontend | Frontend |
| CLI preferences | `cli.prefs` | `~/.tradingagents/cli_prefs.json` | Persistent | CLI only | Config projection |

- One process, one active run, one worker thread. This is the synchronization mechanism for the global configuration, decision log, and checkpoint database.
- The artifact read model never writes.
- Introducing concurrent runs requires per-run configuration isolation, a serialized or owned decision-log writer, per-run artifact namespaces, and a lost-update test. This blueprint does not authorize that change.

<a id="deterministic-boundaries-preserved"></a>
## 10. Deterministic boundaries preserved

The web layer calls, not reimplements:

- `_validate_trade_date` and the core date rules.
- `safe_ticker_component` for every path component.
- `PortfolioContext` validation and fingerprinting.
- `extract_rating` / `parse_rating` and the `REVIEW` sentinel.
- `write_report_tree` for report layout.
- `TradingMemoryLog` through the graph's existing methods.
- `run_backtest` and `summarize` for backtest semantics.

The web layer never:

- Converts `REVIEW` to `Hold` or to a trade.
- Treats an absent portfolio as a flat book.
- Reads the live memory log from a backtest.
- Bypasses point-in-time filters.
- Accepts a ticker, run id, or path the core would reject.
- Exposes a provider key or server filesystem path.

## 11. Security and permission boundary

The full matrix is `docs/architecture/permission-model.md`. Summary:

- Loopback-only listener; no authentication; Host/Origin/CSRF/CSP compensating controls.
- Server-only provider keys; status-only UI.
- Artifact identifiers, not paths; root allowlist.
- Untrusted content sanitized; no raw HTML; URL scheme allowlist.
- No trading or position-changing endpoint.
- Destructive checkpoint clear requires explicit confirmation and is disabled during a run.
- History is read-only.
- Errors and logs are redacted.

## 12. Deployment, build, and packaging

- Python 3.10+; `pip install -e '.[dev,web]'`.
- Frontend: Node 22 LTS, npm, `npm ci`, `npm run build`.
- Build output: `src/tradingagents_web/static/`; not committed.
- Runtime entry: `tradingagents-web --port 8000` or `python -m tradingagents_web --port 8000`.
- Uvicorn single worker; `--host` restricted to `127.0.0.1`.
- `pyproject.toml` changes needed: `[web]` optional dependencies, `tradingagents-web` script, `package-data` for static assets. These require human governance review through the normal review process.
- If `static/index.html` is missing, the server starts in API-only mode and reports a clear build instruction; it does not serve a broken UI.
- No container, cloud, domain, TLS, or orchestration work.
- Existing `results_dir`, `data_cache_dir`, and `memory_log_path` defaults apply. The web layer does not write `.env`.

## 13. Failure handling and recovery

| Failure | Run state | Decision log | Checkpoint | Artifacts | Client |
| --- | --- | --- | --- | --- | --- |
| Invalid request | none | unchanged | unchanged | none | 422 field errors |
| Active run conflict | existing run unchanged | unchanged | unchanged | unchanged | 409 with active run id |
| Model/data upstream error | `failed` | not written | preserved | partial kept | `run.failed upstream` |
| Worker exception | `failed` | not written | preserved | partial kept | `run.failed internal` |
| Analysis cancellation | `cancelled` | not written | preserved | partial kept | `run.cancelled` |
| Report save failure | `completed` + warning | written | cleared as normal | sections + message log kept; report tree may be absent | `run.completed` with warning |
| SSE buffer overflow | run continues | unchanged | unchanged | unchanged | `snapshot`, then live |
| Browser disconnect | run continues | unchanged | unchanged | unchanged | reattach or snapshot |
| Server restart | lost | persistent file intact | persistent DB intact | persistent | "run no longer available" |
| Artifact id invalid | no run | unchanged | unchanged | unchanged | 404 safe |
| Checkpoint clear during run | run continues | unchanged | not cleared | unchanged | 409 |
| Backtest long run | `running` until return | backtest log only | n/a | backtest dir | progress/summary; no cancel |

## 14. Verification plan versus actual results

### 14.1 Planned verification

- Structural: source layout, dependency direction, permissions, lint, types, dependency audit.
- Contract: request validation, event envelope, cancellation, reattachment, artifact ids, error taxonomy, provider/model parity.
- Regression: all existing offline tests; CLI help and import smoke checks.
- Negative: every feature has at least one invalid-input or forbidden-action test.
- Invariant: each `INV-WEB-*` has a violating test.
- Security: secret redaction, path traversal, Host/Origin/CSRF, untrusted rendering, size limits.
- Packaging: wheel contains static assets; clean install health check.
- Frontend: Vitest/RTL, MSW, Playwright on Chromium/Firefox/WebKit.
- Live: only with explicit external-service and cost authorization.

### 14.2 Actual results

**No product test, architecture spike, latency benchmark, browser matrix, dependency audit, packaging smoke test, or live test has been executed for this design.** The only executed checks are the documentation validations recorded in `docs/architecture/evaluation-logbook.md`. Planned results must not be reported as passing evidence.

## 15. Approval gates

Current CI policy (2026-11-21, ADR-012-error-handling-merge-integration.md):
GitHub branch protection owns human merge approval. CI does not demand special
review markers or a historical test-only commit. Plan/test agreement, safety
ADRs and authentic decision records remain development process requirements.
Absent/empty base semantic policy reports NOT RUN without blocking; partial or
invalid configuration and configured evaluation failures block. A green CI run
does not certify human approval or unrun model-quality evaluation.

Before product implementation:

1. Requirements registry and this blueprint reviewed; the design was approved for documentation on 2026-11-05, but the written artifacts need a review record.
2. Test plan and concrete test nodes reviewed and agreed with the human owner, with the scope/version recorded authentically.
3. ADR-001 through ADR-007 reviewed; the new entry point needs human safety review.
4. Dependency additions (`fastapi`, `uvicorn`, frontend npm packages) reviewed and approved.
5. `pyproject.toml` and CI changes receive human governance review through the normal review process.
6. Official `python -m test.ci_gates schema`, `structure`, lint, type, dependency, and security checks run in an environment with dev dependencies.
7. No implementation begins while a required approval or material is missing.

## 16. Traceability

The requirement-to-module-to-test mapping is in `docs/architecture/trace-matrix.md`. Invariants are in `docs/architecture/invariants.md`. Decisions are in `docs/architecture/adr/021-choice.md` through `007-run-controls.md`. Permissions, memory, runtime policies, risks, options, and evaluation records are in the corresponding documents under `docs/architecture/`.

### W9 Audit and offline comparison read projections

The user requested the missing WebUI interfaces on 2026-11-20 (scope version
`web-projections-20261120-v1` in the review memo). Existing report/identity,
redaction, path, advisory-output and core-isolation invariants remain binding.

| Ownership | Contract |
| --- | --- |
| `src/tradingagents_web/artifacts/audit.py` | Read only the four canonical audit families under an indexed analysis root; bounded regular-file reads, no symlink traversal, sanitized JSON/text and explicit per-family availability |
| `src/tradingagents_web/api/audit.py` | `GET /api/history/{artifact_id}/audit`, `GET /api/runs/{run_id}/audit`, `GET /api/history/{artifact_id}/audit/artifacts/{kind}` with optional download disposition; no browser-supplied path |
| `src/tradingagents_web/api/comparisons.py` | `GET /api/comparisons`, `GET /api/comparisons/{case_id}`, `GET /api/comparisons/{case_id}/download`; controlled existing cases only, optional existing dynamic case identity, core pairing and serialization |
| Existing Web run writer/coordinator | Preserve canonical core audit outputs next to the corresponding Web artifact and record allowlisted effective presentation metadata; no second core writer or computation |
| Existing frontend ownership | Audit/comparison views consume projections; server artifacts and pure core replay remain authoritative |

Audit JSON has a versioned projection envelope, canonical family keys,
complete/partial/absent artifact availability, nullable data and per-family
issues. Missing/invalid data is not a normal gate, zero cost or empty successful
report. Downloads use the same safe reader and redaction as previews. The total
response budget uses existing Web settings. Unknown IDs/families return 404;
oversized artifacts return 413; malformed JSON is surfaced as invalid.

Comparisons are deterministic scripted offline replays, not live benchmarks or
financial backtests. D/E/F are representative cases; G is a separate input-
exhaustion regression. Both actual identities pass the existing core pairing
check before a report/download is returned. Identity mismatch returns 422 without
savings/score output. No HTTP operation modifies human rubric scores or runs a
provider. Replaying does not consume the active analysis slot or write memory.

Run-local JSON copies may additionally carry `web_context` with existing origin
metadata, source-attempt descriptors and conflict lifecycle identifiers. Fields
are allowlisted; raw arguments, prompts and claim prose are excluded. The core
saved report tree and its serializer remain unchanged. Audit cutoff eligibility
uses the existing core manifest helper, never a saved folder's timestamp.
Cross-artifact identity/verdict disagreement is visible and suppresses eligible
IDs in this presentation; it does not rewrite a core decision. A run-ID query
uses the coordinator's lifecycle status so unfinished audits can be refreshed.

## Simulated trading subsystem

The simulated trading subsystem is a separate, deterministic layer invoked after
the graph produces `final_trade_decision`.

```text
Graph final_state
  -> decision_from_final_state()   direction only; LLM quantities/prices ignored
  -> SizingPolicy                  deterministic quantity, hard cap, 6dp
  -> SafetyEngine                  SR-01..SR-10, then AP-01/AP-02
  -> HumanApprovalGate             only for PENDING_APPROVAL
  -> SimulatedExecutor             engine-issued provenance authorization only
  -> Portfolio + AuditLog          atomic fill and append-only evidence
```

Key boundaries:

- `src/trading/` contains the simulated portfolio, clocks, audit, persistence,
  executor, approval gate, pipeline, backtest, runtime, and standalone CLI.
- `src/safety/` contains the deterministic rules and the sole engine gateway.
- `src/trading/backtest.py` provides a weekday calendar, mock/real decision
  providers, mock/historical quote providers, and a resumable `BacktestRunner`.
- `src/trading/runtime.py` is the composition root; `src/trading/cli.py` only
  inspects or resets persisted state.
- The subsystem has no real broker path. `test/live/trading/` validates a
  three-day opt-in run against the real graph and historical quotes while
  keeping execution simulated.
- Trading requirement IDs are `FR-TRD-*`, `INV-TRD-*`, and `NFR-TRD-*`.


- **Phase 4B** (live-provider benchmarking) was not part of the Release scope and
  remains prohibited by default. The token-observability delivery later ran paid 16-run
  campaigns under dated, run-specific human authorizations recorded in
  `docs/ai-use-log.yaml` (V2/V3, 2026-11-15/16). Those authorizations are run-specific:
  they do not authorize a new benchmark, a different provider, or production threshold
  tuning.
- **Production threshold tuning** is not in scope and remains prohibited without
  separate explicit human authorization. The measured token deltas are exploratory
  (n=1 per cell) and are not production thresholds.
- **No additional LLM providers or UI/feature work** beyond the approved scope. The
  delivered tree does contain the approved personal data adapters: Finnhub company news,
  a disabled GDELT path, FRED macro access, and the existing Alpha Vantage/Yahoo
  market/fundamentals vendors. The earlier blanket "no new data vendors" statement is
  superseded by that approved scope; it is not a claim that the tree has no such
  adapters.
- No relocation or duplication of the main-system source trees.
- No real broker execution or unattended live-trading loop.

The subsystem is imported as a standalone capability. This merge adds no WebUI
execution endpoint, changes no advisory analysis semantics, and does not import
the release branch's incompatible ACL schema. Test paths follow the existing
merged `test/offline/` and `test/live/` layout. Historical subsystem approvals and
results retain their original scope; merged-tree verification is recorded in
the review memo and evaluation logbook.
### W10 Local startup modes

Marked `TODO` in `docs/debt-register.md` and `docs/architecture/risk-list.md`.
The student identity is **confirmed** as WANG Yiwen (CS5351 ID 60536848); the
identity risk is resolved (RISK-004 / DEBT-005). Remaining open items include:
the OpenCode `permissions.jsonc` schema/enforcement against the installed
OpenCode version (RISK-006 / DEBT-004); the degraded confidence ceiling
(DEBT-014 — now implemented as ADR-011 Stage 4, 0.60 engineering ceiling,
offline-verified, awaiting independent Codex review + human acceptance);
automatic optional adapters (DEBT-015 / RISK-015); and the live-run
budget-accounting basis and claim-date semantics found on 2026-11-06 (DEBT-021 /
DEBT-022 / RISK-020 / RISK-021). This is **not** claimed to be the "only
remaining uncertainty"; the earlier single-item framing was stale and is
corrected here.

Token-observability residuals (personal risk register, renumbered `RISK-036…RISK-049`
in `docs/architecture/risk-list.md`): missing/contradictory provider usage
(`RISK-041`), per-run memory isolation applies to the harness not to generic runs
(`RISK-040`), freeze/spec paths may not reproduce in another checkout (`RISK-045`),
decision quality has no ground truth (`RISK-046`), the provider endpoint is not in
`config_sha256` (`RISK-047`), generic/CLI runs bypass the harness gates (`RISK-048`),
and the recorded test results were red at `50b2ca3` (`RISK-049`). The personal
governance documents' own debt IDs were renumbered during the D4 integration and are
now `DEBT-042…DEBT-051` in `docs/debt-register.md`; cite those IDs from this blueprint.

The user approved `web-startup-20261120-v1` on 2026-11-20. Existing `cli.py` owns
argument parsing and static serving; `launcher.py` owns frontend prerequisites,
port checks, readiness and owned-child supervision. `--dev` starts a single-worker
backend plus loopback-only Vite; `/api` proxies to the selected backend port.
`--build` runs the existing build then serves static files from the backend.
The default command still serves previously built assets. No tool installs
packages, kills unrelated listeners, runs an analysis or changes core behavior.
Ctrl+C/failure cleans up children; `--open` waits for service readiness. These
modes use current dependencies and the native source tree, not the ignored demo.
References: REQ-WEB-020/023/026/027, ADR-002/003 frontend-stack,
INV-WEB-001/003/013/014/015.


### W8/W4 stage-based activity presentation

Under the user's `web-activity-20261120-v1` request, W4 may add optional `stage`
and `speaker` fields to existing public message/tool payloads. The projector
owns classification of emitted public messages and appended research/risk
histories. It excludes non-text reasoning blocks and private audit transcripts.
W8 owns `frontend/src/utils/runActivity.ts` (presentation stage grouping) and
`components/RunActivity.tsx` (progress tabs, bounded activity and stage reports).
The four groups follow actual analyst, research, trader and risk state; the
final assessment belongs to risk review. The view follows newly entered stages
and permits manual review without changing execution. Replayed snapshots retain
stage metadata; unassigned legacy messages remain accessible in All activity.
Run activity stays visible after completion, cancellation or failure. Existing
redaction, event sequencing, report authority and terminal semantics are retained.
References: REQ-WEB-002/007/021, ADR-002-backend-framework-and-transport,
ADR-003-frontend-stack, INV-WEB-001/003/012/014. Final human acceptance is pending.


### W8 English/Chinese interface localization

Under `web-i18n-20261120-v1`, retain existing i18next and reactive component
subscriptions. Existing `frontend/src/i18n/index.ts` owns the normalized locale,
local preference and document language; new `i18n/ui.ts` owns UI text lookup
and subscriptions, with explicit interpolation and English fallback. Existing
English/Chinese JSON files own matching interface catalogues. Frontend views
and date formatters localize presentation only; canonical field values, routes,
REVIEW/ratings, report output language, source/model/tool content and SSE identity
remain authoritative and unchanged. The workspace exposes language switching
on desktop/mobile without resetting forms or runs. No backend translation
service, dependency or runtime prompt is introduced. REQ-WEB-014/021, ADR-003,
INV-WEB-001/003/007/012/014. Final human acceptance remains pending.


### W1/W3 per-analysis debate settings and recovery identity

Under `web-debate-settings-20261120-v1`, existing request/config/run modules
project a strictly allowlisted subset of the core DebateTerminationConfig.
New runtime/debate_policy.py owns merge/precedence/public projection while the
core resolver owns policy validation. No paths, manifest/trace selectors or
arbitrary configuration are accepted from the browser. Resolved root/nested
round caps agree; existing environment locks remain authoritative. Snapshots and
run metadata record normalized public debate settings and independent risk caps.

New runtime/analysis_graph.py subclasses the existing core graph solely to
extend its checkpoint signature with a fingerprint for nondefault termination
policies. All graph execution, evidence, ledger, cancellation and decisions stay
in core methods. Default policies keep legacy identities; custom policies have
distinct recovery identities even if only a convergence threshold changes.
GraphRunner retains its existing factory injection point for offline tests.

Frontend components/DebateSettings.tsx and utils/debateSettings.ts own typed
controls, translated labels and form feedback; the existing wizard/client owns
submission/drafts and the live/history views show effective settings. Quick
presets retain coupled round behavior until risk rounds are explicitly edited;
locked values are shown read-only. Budgets are debate-scoped and admission may
use estimates; these controls do not promise an analysis-wide monetary cap.
REQ-WEB-001/003/013/014, FR-DDT-004, ADR-001-choice/007-run-controls and
INV-WEB-001/003/006/009/010/012/014 apply. Final human acceptance pending.

The existing artifacts/index.py projects validated recorded policy without
applying current environment defaults to historical runs. Missing or malformed
legacy settings stay absent. The runs router returns the standard validation
envelope for malformed typed inputs without echoing submitted values, including
nonfinite JSON numbers that cannot safely be serialized in default error detail.


## TUI capability parity — 2026-11-20

Scope/test plan: web-tui-parity-20261120-v1. The user approved the preceding
capability audit recommendations, excluding language expansion and simulated
trading. Implement individual role status, analyst timing and real report counts,
positive-integer custom backtest spacing, and OpenRouter discovery/refresh.
Keep credentials and CLI preferences server-owned; no new preference writes,
core/CLI/safety/trading changes, dependencies, deployment or Git operations.
REQ-WEB-001/002/006/007/013/014/021; INV-WEB-001/003/006/007/012/014;
ADR-001-choice, ADR-003-frontend-stack and ADR-007-run-controls apply.

Ownership: existing WebUI runtime projector/graph_runner/coordinator, new
runtime/model_catalog.py for bounded cached public-model discovery, config API
and app composition; existing frontend run store/activity/utilities, wizard/model
client, backtest interval control and bilingual labels; focused tests under
existing offline/frontend/e2e trees and existing architecture/process records.
No new language options or simulated-trading integration. Individual statuses
come from observed graph node lifecycle/output, with aggregate team events
retained. Completed reports require their finalizing node and content, not
interim debate text. Timings cover observed current-process work; restored
historical stages are not assigned fabricated durations. Existing snapshots
carry added stats and times without lifecycle/idempotency changes.

OpenRouter uses its fixed public models URL without credentials or client URLs,
filtered to validated text model IDs/names, newest mainstream shortlist matching
TUI, with bounded response/time, application-local TTL and refresh coalescing.
Failures produce a safe warning with cached/custom-ID fallback; arbitrary model
IDs remain accepted. No live discovery/model requests run in verification.

Prior tests: per-role/repeated turns, default empty states, blocked/partial and
resumed runs; exact report finalization counts and injected-clock analyst times;
real core offline runner stats/snapshots; reconnect preservation and stage filters
with new risk roles; custom intervals including invalid zero/fractional inputs;
OpenRouter sorting/filtering/deduplication, cache/refresh, HTTP/malformed/oversize
failure and redaction, no calls for other providers; manual IDs and refresh
preserve draft inputs with stale-response guards. Run full isolated offline,
frontend lint/types/tests/build, local Chromium and schema/permissions/whitespace.
Direct scope authorization is recorded; no separate test-file review or final
human acceptance is asserted.


## Simulated-trading WebUI integration — 2026-11-21

Plan/test version: web-simulation-20261121-v1. Human source: current user request
for corresponding simulated-trading frontend, followed by explicit selection
"frontend and necessary interfaces, integrate the existing simulated core".
The user requires a single final verification phase after implementation; do not
run iterative tests during development. This direct instruction authorizes this
bounded integration; no independent test-file review or final acceptance is
asserted. Preserve all prior working changes and feature/webui.

Requirements: FR-TRD-001..006, INV-TRD-001..003, NFR-TRD-001 and
REQ-WEB-001/006/007/013/014/021/023. Existing core statuses/IDs and historical
approval scope are unchanged. ADR-001-simulated-trading-system.md and
ADR-001-choice.md/003-frontend-stack.md/007-run-controls.md receive this Web
composition refinement. No trading/safety/core/CLI logic is modified.

Ownership/allowlist: new Web runtime simulation.py and simulation_jobs.py,
models/simulation_requests.py, api/simulation.py; existing app/coordinator and
security route-prefix integration; new frontend api/simulationClient.ts,
pages/SimulationPage.tsx, pages/Simulation/* view components and utility/types;
existing app/nav/styles/catalogues, README, package inclusion in pyproject.toml
for the already-existing trading/safety packages, focused offline/frontend/
Chromium tests and current architecture/process records. No dependency added,
credential/environment-template/prompt/rule/permission edit, broker, automatic
live trading, release or Git operation.

Contracts: fixed server-owned results_dir/simulated_trading namespace, Decimal
strings for money/quantity, no submitted filesystem paths/config/execution
permissions. Explicit initialize/reset with confirmation; reset preserves audit.
Use existing pipeline for completed advisory report -> deterministic sizing ->
safety evaluation -> simulated fill or issued human approval. Caller supplies
an explicitly labeled scenario quote with aware timestamp; no LLM price or size
is accepted. Approval requires reason/name plus an issued in-memory request,
matching portfolio version, unexpired approval and still-fresh quote; only the
core engine can execute. Reject repeated/mismatched/stale decisions; public
idempotency receipts persist, but pending approvals cannot survive process
restart and must be reevaluated. State/audit corruption or uncertain execution
persistence blocks further mutations. All public reads redact paths/secrets.

One per-process manager and advisory filesystem ownership lock prevent another
Web process using the same simulation namespace. All mutating transactions use
the existing coordinator single-active slot. Background simulation backtests
retain the slot through completion, expose polling/reload and offer no fake
cancellation. Each job owns separate state/audit/cursor and immutable parameters;
resume requires matching parameters/config. Existing BacktestRunner owns daily
advancement, core providers own decisions/quotes. Deterministic rows and real
analysis/historical quote modes are explicitly distinct. Without a synchronous
human callback, pending approvals in walk-forward runs remain unexecuted and are
counted, matching core behavior; account approvals belong to the interactive
account flow. No unattended approval or fabricated fills/equity curves.

Prior tests (written before the final run): initialize/account Decimal values,
reset audit retention/confirmation/version, completed-report selection, approved/
pending/rejected/no-action outcomes, explicit human approve/deny/expiry/staleness,
no bypass/duplicate execution, restart receipts and pending invalidation, audit/
state tampering and path escape, single-slot conflict, offline scenario walk-
forward/resume/isolation and source/date validation, protected import boundary;
frontend tabs/forms/negative validation/empty-error states, confirmation and
manual approval, canonical requests and no unsupported cancel/broker controls;
local Chromium account/approval/backtest/audit plus previous suites. Run all
network-isolated offline tests, frontend lint/types/tests/build, local Chromium,
schema/permissions/whitespace together only after implementation. No real
provider calls or user runtime-state access in verification.


## Web model defaults refinement — 2026-11-21

web-model-defaults-20261121-v1 and ADR-001-choice.md supersede the W1 blanket
lock description for provider and quick/deep model selection: environment values
preselect editable analysis controls, explicit run choices win, and omission or
backtests use server defaults. Budget/round and other unrelated locks remain.
The configuration projection separates env_defaults from env_locks without
exposing credentials or endpoint paths. Provider switching cannot carry another
provider's models, endpoint or thinking settings. Draft model choices record
only a non-secret provider/model baseline; stale defaults invalidate selection
fields. Public routes and core/CLI ownership and behavior stay unchanged.


## Backtest per-date progress — 2026-11-21

web-backtest-progress-20261121-v1 / ADR-007-run-controls.md assigns generic optional
loop observation to existing core backtest.py, and presentation state to new
tradingagents_web.runtime.backtest_progress. The runner scopes observation to its
worker context; coordinator owns synchronization/lifetime. Existing backtest GET
adds bounded progress paging (cells_offset/cells_limit), retaining old fields and
launch inputs. New frontend pages/Backtest/BacktestProgress.tsx renders truthful
cell/settlement status and elapsed time. The core stays independent of Web/HTTP;
public backtest signature/results, CLI, memory and analysis semantics remain.


## Release error-handling integration — 2026-11-21

Local release 9a08e08 is integrated under ADR-012-error-handling-merge-integration.md.
The canonical src/ and test/ layout remains. New release modules keep their
original ownership: agents/utils/tool_governance.py handles model/tool binding;
dataflows/retry_session.py and vendor_breaker.py handle bounded vendor attempts
and breaker state; graph/*_governance.py, *_tool_governance.py and
sentiment_prefetch.py own opt-in analyst orchestration; graph/run_identity.py
owns versioned execution digests; tradingagents/file_io.py owns atomic file
replacement. These paths are relative to src/tradingagents/ and introduce no
presentation dependency into core. WebUI inherits the release behavior through
its existing graph adapter. The public run_backtest signature/results and the
existing read-only progress observer are retained. No safety/trading/CLI source,
Web interface contract, runtime prompt or dependency change is added by conflict
resolution. Evidence on previous heads remains historical; merged-tree results
are recorded separately in the evaluation logbook.


## CI type/security contract maintenance — 2026-11-21

ADR-012-error-handling-merge-integration.md records the user-authorized complete
type/security repair and its negative-test strategy. Existing modules retain
ownership; dataflows/utils.py additionally owns the shared HTTPS feed opener,
and dataflows/reddit.py owns hardened bounded Atom XML parsing via declared
defusedxml. Safety/portfolio/audit edits are annotations only. Existing graph,
provider, evidence, budget, rating, memory, checkpoint and CLI behavior remains
covered by the complete regressions. The conflict-state adapter now obeys the
existing two-value core/denials-output contract instead of unpacking three values.
No new core implementation, framework, dependency policy exemption, permission,
trading policy or deterministic acceptance threshold is introduced. All CI gates
remain active and genuine review/semantic evidence is still required.
