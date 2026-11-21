# Architecture Blueprint — Master Constraint / Design Document

This is the master design document for the CS5351 course project. It states the
hard constraints, the module layout, the two feature implementations, and the
non-functional contract that governs every change. It is authoritative for
design intent; the machine-readable PRD lives in `docs/req/requirements.yaml`,
and traceability lives in `docs/architecture/trace-matrix.md`.

## Repository context

- This is a downstream fork of the upstream `TradingAgents` framework (v0.5.0).
- Canonical main-system source trees are `tradingagents/` and `cli/`; canonical
  tests are under `tests/`.
- The approved independent simulated-trading subsystem lives in
  `src/trading/` and `src/safety/`; its canonical tests live under
  `tests/trading/`. It is invoked after graph output and does not modify the
  frozen main-system trees.
- The old `test/offline/` and `test/live/` directories are pointer READMEs only;
  their code and tests were migrated into `tests/trading/`.
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

| Module | Responsibility |
| --- | --- |
| `models.py` | Typed, deterministic, JSON-safe dataclasses (`EvidenceRecord`, `SourceAttempt`, `ValidationResult`, `EvidenceGroupQuality`, `GateDecision`) plus enums and the `quantize_decimal` helper. |
| `adapter.py` | Truthful `StructuredSnapshot` → `EvidenceRecord` adaption and stable evidence-ID generation. |
| `validate.py` | Five deterministic validation classes (completeness, format, freshness, look-ahead, cross-source consistency). |
| `policy.py` | Deterministic `Decimal`-threshold policy objects (`MarketPolicy`, `MarketRecordPolicy`, `MetricTolerance`). |
| `quality.py` | Per-record precedence and per-category aggregation. |
| `gate.py` | `GateDecision` generation with injected `decided_at`; precedence `blocked` > `degraded` > `normal`. |
| `origin.py` | ADR-010 versioned, evidence-ID-keyed typed origin metadata (distinct target/observation/availability/timestamp date roles + unit/currency/scale), kept out of the 20 locked record fields. |

### Debate package (`tradingagents/debate/`)

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

- `tradingagents/graph/data_quality_gate.py` — dependency-injectable gate node.
- `tradingagents/graph/conditional_logic.py` — routers including
  `should_continue_after_data_gate`.
- `tradingagents/graph/setup.py` — registers the gate node and evaluator node;
  complete `DEBATE_PATH_MAP` / `DEBATE_EVALUATOR_PATH_MAP` to avoid router
  fall-through crashes.
- `tradingagents/agents/researchers/{bull,bear}_researcher.py`,
  `tradingagents/agents/managers/research_manager.py`,
  `tradingagents/agents/utils/agent_states.py` — verdict gate, citation
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
  LLM-free, network-free comparison model/runner (`tradingagents/comparison/`)
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
| Coding agent (OpenCode/Codex) | Read/analyze/implement within the active authorized scope | May suggest; must stop and ask on any denied action |
| Runtime graph (gate/evaluator/agents) | Emits a verdict/recommendation within deterministic rules | Cannot override a blocked verdict downstream (FR-DQG-006) |

Advice is never promoted to authority by an AI: human decisions cannot be
inferred, authored, or backfilled by an agent (see `Prompt.md`, ADR-004).

## End-to-end workflow and change controls

1. **Read instructions first** (`AGENTS.md`, this blueprint, `invariants.md`,
   `trace-matrix.md`, `pyproject.toml`, `tests/conftest.py`).
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
- The subsystem has no real broker path. `tests/trading/live/` validates a
  three-day opt-in run against the real graph and historical quotes while
  keeping execution simulated.
- Trading requirement IDs are `FR-TRD-*`, `INV-TRD-*`, and `NFR-TRD-*`.

## Out of scope

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

## Open / uncertain items

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