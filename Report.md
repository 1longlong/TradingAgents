# Report.md — Phase Progress Report and Student Reflection

> **Status label (preliminary / not final):**
> This is the **first version** of the process report. It deliberately separates
> **completed evidence** from **planned work**, includes a preliminary student
> reflection, and **does not claim submission, demo, or Phase 4 completion**.

## 1. Project summary

The project extends the downstream `TradingAgents` framework with two
deterministic, governance-driven improvements:

1. **Deterministic Data Quality Gate** — a pure, LLM-free node that validates the
   verified market snapshot before the Bull/Bear debate and fails closed on
   missing or low-quality evidence.
2. **Dynamic, evidence-aware debate termination** — a deterministic Debate
   Evaluator that stops the debate on evidence/model-conflict staleness or
   budget exhaustion rather than always running a fixed number of rounds.

## 2. Completed evidence (verified)

This section reports only work whose evidence was observed. See
`docs/architecture/evaluation-logbook.md` and `docs/architecture/evaluation-table.md`
for per-command outcomes.

### Phase 1 — Analysis

- Read-only analysis of the repository; requirements frozen.
- Deliverable: frozen requirements in `docs/req/requirements.yaml` (v1.0
  read-only prompt `prompts/prompt_v1.0.yaml`).
- Human review recorded in `docs/review-memo.md`.

### Phase 2 — Contract / deterministic gate core

- Implemented the typed, JSON-safe evidence model and the deterministic gate
  core under `tradingagents/evidence/` (models, adapter, validate, policy,
  quality, gate).
- Decimal-math cleanup applied (quantized `Decimal`, no float noise).
- Human review recorded.

### Phase 3A — Gate graph integration

- Added the dependency-injectable `data_quality_gate` node and the gate-aware
  router (`should_continue_after_data_gate`).
- Added gate-aware structured `AgentState` fields.
- Human review recorded.

### Phase 3B — Dynamic debate termination

- Implemented the `tradingagents/debate/` package (config, models, turn, budget,
  evidence_manifest, state, evaluator, evaluator_node).
- Researchers' verdict gate and research-manager hold contract enforced
  (citation allowlist from the gate manifest).
- Human review recorded.

### Phase 3B — Deterministic ConflictRecord runtime lifecycle (FR-DDT-005)

- Added a pure, LLM-free conflict tracker (`tradingagents/debate/conflicts.py`)
  that creates, observes (deduplicates/merges), resolves, and escalates
  `ConflictRecord` objects derived **only** from the structured
  `conflict_assertions` a `DebateTurn` carries (parsed by `turn.py` from the
  `DEBATE_METADATA` `conflict_a` marker).
- Conflict IDs are deterministic SHA-1 digests of `(normalized topic, kind)`;
  evidence validation fails closed (an unknown/Low/future evidence ID never
  creates a conflict, and a re-observation citing such an ID drops the open
  conflict); empty evidence on a new factual/interpretive conflict does not
  create it; a turn with no assertions contributes no conflict; action-only
  disagreement is tracked but never blocks termination; malformed
  assertions/state are skipped, never guessed.
- The evaluator node persists the derived conflicts plus a safe, structured,
  prose-free `ConflictSummary` (resolution/escalation notes and an authoritative
  open-blocking count) to debate state, and the Research Manager injects that
  summary safely (empty when no tracked conflict).
- Human review requested (see `docs/review-memo.md`).

### Stage 2 — Multi-category gate + report artifacts

- Extended the gate with a deterministic multi-category engine
  (`tradingagents/evidence/multi_category_gate.py`) that evaluates the one
  critical market group plus the optional categories (fundamentals, news,
  sentiment). Optional categories without a trustworthy structured source
  produce an explicit deterministic unavailable/insufficient result (stable
  reason codes; no fabricated source/date/unit; no analyst-prose parsing) and
  may degrade — but never block — under a versioned multi-category policy,
  while a missing/blocked market category always fails closed to `blocked`.
- Added the shared deterministic, redacted report artifacts
  (`tradingagents/report_artifacts.py`) wired into the CLI/API report writer
  (`tradingagents/reporting.py`, reached by both the CLI and
  `TradingAgentsGraph.save_reports`): `0_quality/evidence_manifest.json`,
  `0_quality/gate_summary.md`, `2_research/debate_trace.json`,
  `run_summary.json`, and concise `Data Quality` / `Run Summary` sections in
  `complete_report.md`. Output is derived only from structured run state, never
  analyst prose, and every value is passed through secret redaction. Absent
  gate/debate state yields safe defaults, not invented values.
- **Scoping note:** the multi-category gate is proven at the engine + test level
  (`test_stage2_multicategory_gate.py`) and the report artifacts at the shared
  writer level (`test_report_artifacts_stage2.py`; `test_reporting.py`). **The
  multi-category engine is now the runtime graph default.** The LangGraph gate
  node (`create_data_quality_gate_node`) delegates to
  `evaluate_multi_category_gate`, evaluating the critical market category plus
  the optional categories. Trustworthy structured optional-category evidence
  enters **only** through the explicit `data_quality_optional_evidence` state
  contract (a mapping of category -> serialized `EvidenceGroupQuality` dict) —
  never parsed from analyst prose; an absent optional category yields a
  deterministic unavailable/insufficient result that degrades under the
  versioned policy. The market category stays fail-closed. Legacy public state
  keys, routing behavior, deterministic run IDs, and node-factory injection are
  preserved, and the evidence layer no longer imports the graph package
  (circular-import removed; shared market-record construction lives in the
  evidence adapter). RISK-009 / DEBT-009 are resolved.

### Phase 4A — Deterministic offline baseline comparison (NFR-CMP-*)

- Added a pure, LLM-free, network-free **comparison model/runner**
  (`tradingagents/comparison/`): typed/validated schemas, explicit metric
  formulas, a fail-closed replay/aggregation runner, a deterministic JSON +
  Markdown report writer, and representative scripted fixtures (scenarios
  D / E / F).
- **Apples-to-apples:** both strategies are replayed over the identical case
  identity `(ticker, target_date, evidence_snapshot_id, policy_version)` and
  identical scripted Bull/Bear turns. A mismatch, missing partner, or duplicate
  fails closed with `PairingError`.
- **Derived metrics:** evidence-citation coverage from **valid** cited evidence
  IDs (filtered through the manifest allowlist), false-strong-conclusion rate from
  an explicit `strong_conclusion` flag plus the gate/quality outcome (never from
  prose), measured-vs-estimated separation via the `estimated` flag, and
  zero-denominator safety (returns `None`, never fabricates).
- **Scenario outcomes (scripted, offline):** D — dynamic stops early on
  `no_new_evidence`; E — dynamic **extends** to absorb a new High/Medium
  evidence ID; F — dynamic **genuinely stops on `budget_exhausted`** (rule 2),
  preserving the summary reserve (9000 + 8000 <= 20000) and never exceeding the
  hard cap (the fixed baseline spends 27000 > 20000).
- **Correction round (Phase 4A human review, 2026-10-22 → 2026-10-23):**
  implemented before approval. A `SCORED` traceability result requires exactly
  four non-null scores in `TRACEABILITY_DIMENSIONS` order (missing/extra/null/
  reordered sets fail closed); a scripted input that simply runs out of rounds
  is recorded as `input_exhausted` and is **never** a dynamic-policy early stop;
  and the actual deterministic `stop_reason` is preserved end-to-end (per-case
  result, per-case + aggregate JSON, and the Markdown per-case + aggregate
  tables). Regression coverage added; **73 focused comparison tests pass** (was
  47).
- **Human traceability** is a documented rubric with human-entered scores;
  every case is reported `pending` until a human scores it. No human
  traceability scores were entered by this change.
- A `scripts/run_phase4a_comparison.py` replays the scripted fixtures and writes
  `evaluation-output/comparison_results.json` +
  `evaluation-output/comparison_report.md`.
- **Honest status (Phase 4A):** the numbers are deterministic **offline scripted
  fixtures**, **not** live-provider measurements; they cannot support a
  production-grade performance claim. Human traceability is **pending a human
  score**. **No production thresholds were tuned** (fixtures use test-pinned
  policy knobs, policy version `1.0`). Phase 4B is not begun; no live providers
  are used; nothing is committed or pushed.
- Human review requested (see `docs/review-memo.md`).

### Verification evidence (observed)

- **ConflictRecord runtime lifecycle** (this task): a deterministic tracker plus
  evaluator-node and research-manager integration is implemented and verified.
  `tests/test_debate_conflicts.py`: **39 passed**; the
  conflict/debate/graph/Stage-2 relevant suite: **490 passed** (logbook 046).
- **Runtime multi-category gate integration** (prior task): the LangGraph default
  gate node now uses the multi-category engine. New graph-level tests prove
  normal/degraded/blocked routing, structured optional-evidence handling, absent
  optional evidence (degrades, never fabricates), legacy compatibility,
  point-in-time rejection, and deterministic serialization. The exact command is
  recorded in `docs/architecture/evaluation-logbook.md` (entry 043).
- Stage-2 relevant suite, current working tree: **442 passed** across the gate,
  the debate evaluator, budget, config, evidence manifest, debate graph/turn,
  evidence models, structured validator, researchers' verdict gate, the
  research-manager hold contract, the Stage 2 multi-category gate
  (`test_stage2_multicategory_gate.py`: 26 passed), and the Stage 2 report
  artifacts (`test_report_artifacts_stage2.py`: 16 passed). The exact command
  is recorded in `docs/architecture/evaluation-logbook.md` (entry 043).
- **Phase 4A comparison** (this task): `tests/test_comparison_runner.py` +
  `tests/test_comparison_schemas.py` = **47 passed** (17 runner + 30 schemas);
  `scripts/run_phase4a_comparison.py` wrote 3 scripted cases to
  `evaluation-output/` — entry 049. Scenario F budget-exhaustion route verified
  by decision trace (`gate_blocked` inactive, `budget` active;
  route=SUMMARIZE, stop_reason=BUDGET_EXHAUSTED) — entry 050. Governance
  validator, governance tests, Ruff, and `git diff --check` clean — entry 051.
- **Phase 4A correction round** (human review, 2026-10-22 → 2026-10-23): the
  four requested corrections were implemented and verified — strict four-non-null
  `SCORED` traceability validation in `TRACEABILITY_DIMENSIONS` order;
  `input_exhausted` distinct from a dynamic early stop; actual `stop_reason`
  preserved in results, JSON/aggregates, and Markdown; regression coverage
  added. **73 focused comparison tests pass** (was 47); the comparison script
  regenerated `evaluation-output/` preserving the actual stop reasons (entry
  054). Human traceability scores remain pending.
- **Phase 4A narrow fail-closed correction** (short re-review, 2026-10-23): a
  `CaseResult` carrying a contradictory `strategy`/`early_stopped`/`stop_reason`
  combination (e.g. a `FIXED` result claiming an early stop, or an
  `early_stopped == True` dynamic result with an empty / `input_exhausted` /
  `max_rounds_reached` / unknown stop reason) is now rejected at construction in
  `CaseResult.__post_init__`, reusing the single `_DYNAMIC_STOP_REASONS`
  allowlist, so an inconsistent result can never reach the aggregate or report.
  **90 focused comparison tests pass** (was 73); governance validator PASS (34/34,
  no secrets); governance scaffold tests 16 passed; Ruff (full repo) clean;
  `git diff --check` clean (entry 055). Human traceability scores remain pending.
- **Phase 4A reporting-gap fix** (independent review): the aggregate/report now
  visibly preserves the estimated-vs-measured usage provenance
  (`CaseAggregate.tool_usage_estimated`, `fixed/dynamic_estimated_cases`) and
  includes tool-call counts (per case + aggregate) in both JSON and Markdown;
  an estimated value is never presented as measured. Verification is entry 053.
- Full offline suite after Phase 4A integration (re-run, current tree): **3
  failed, 1432 passed, 2 skipped, 88 subtests**, all three failures the
  pre-existing date-sensitive cache tests (entry 052; the network-reachability
  baseline did not fail on this run).
- Full offline suite after the Phase 4A correction round (re-run, current tree):
  **4 failed, 1463 passed, 2 skipped, 22 warnings, 88 subtests**, all four the
  documented pre-existing baselines (3 date-sensitive cache tests +
  the network-reachability baseline), with **no new regression** (entry 054).
- Full offline suite (current tree, re-run): **3 failed, 1391 passed, 2 skipped,
  88 subtests**, with the pre-existing date-sensitive cache failures (logbook
  047). A prior re-run (logbook 044) additionally showed 1
  network-reachability baseline failure. Ruff on changed files,
  `git diff --check`, the governance validator, and the governance scaffold
  tests all clean — entry 048.

### Verification evidence (provided, not re-run in this environment)

The task supplied the following verification outcomes that were observed in the
sandbox/prior runs. They are recorded as evidence of record but are **not
re-claimed as a fully-green full suite here**:

- OpenCode-related suite: **420 passed**.
- Independent full offline suite in the sandbox: **1275 passed, 1 skipped,
  1 deselected, 88 subtests**, with **three known date-sensitive cache failures**
  and **one network-reachability-dependent baseline failure**.
- An earlier OpenCode environment saw **1276 passed** with **only the three
  date-sensitive cache failures**.

> This figure is recorded verbatim (it is part of the known evidence
> supplied for this deliverable). It is **not** reproducible from the
> default offline run in the current environment, and it is **not** claimed
> as a green full suite. See `docs/architecture/risk-list.md` and
> `docs/debt-register.md`. The current working tree yields **490 passed** for
> the conflict/debate/graph/Stage-2 relevant subset (re-run by this task, entry
> 046).

## 3. Known risks / debt (not hidden)

- **Date-sensitive cache failures** in a small number of tests (see
  `tests/test_ohlcv_cache_freshness.py`-adjacent and `tests/test_date_boundaries.py`
  families). They depend on the current clock, so a "green" result is not
  reproducible across days.
- **Vendor reachability dependence** in one baseline test; in a sandbox without
  network reachability that single baseline can fail even though the code is
  correct.
- **Real-provider paths** are exercised only by mocks/stubs/LiveTest in the
  offline suite; no paid/vendor call is made by the deterministic tests.
- **Conflict lifecycle subtlety** — the deterministic tracker's evidence
  validation, dedup/merge, and resolve/escalate ordering is subtle and easy to
  mis-order; it is mitigated by targeted tests (`tests/test_debate_conflicts.py`)
  and fail-closed evidence validation (RISK-011).
- **Student identity** — now confirmed as **WANG Yiwen**, CS5351 student ID
  **60536848** (`transcripts/60536848-WANG-Yiwen.md`). The transcript was
  initially created under a provisional identity slug and has been finalized.
- **Uncommitted / unpushed work** — all Phase 1–3B and Stage 2 code, tests, and
  documentation are uncommitted on `feature/data-quality-debate-control`.
- **OpenCode permission schema uncertainty** — see `docs/debt-register.md`.
- **Phase 4A results are scripted offline fixtures, not live-provider
  measurements** — they cannot support a production-grade performance claim;
  human traceability is pending a human score; no production thresholds were
  tuned. This is stated in `evaluation-output/comparison_report.md` and in the
  Phase 4A section above. The Phase 4A human review is recorded as **Approved
  with limitations** (WANG Yiwen 60536848, 2026-10-23; `docs/review-memo.md`,
  logbook 056): the fail-closed correction and short re-review were accepted,
  subject to the recorded limitations (offline-only verification, the full suite
  is not completely green due to the known date-sensitive cache failures, human
  traceability scores remain `pending`, and no final production threshold tuning
  was performed). The prior **Changes requested** decision is retained verbatim
  as historical audit evidence.

## 4. Planned work (not yet done)

- Resolve the OpenCode permission schema uncertainty once exact schema can be
  verified against the installed OpenCode version.
- Decide on date-sensitive cache tests (stabilize or document as known) and the
  network-reachability-dependent baseline.
- **Phase 4A** — deterministic offline baseline-comparison infrastructure is
  implemented and verified as scripted fixtures (see the Phase 4A section
  above). **Phase 4B** (e.g. production threshold tuning, live-provider
  benchmarking) is **not started**, and no production thresholds were tuned. Any
  future Phase 4B or live-provider work requires explicit, separate authorization.
- No submission, demo, or grading claim is made or implied by this document.

## 5. Preliminary student reflection (v1, to be expanded)

*This is a preliminary draft and will be revised before submission.*

The two improvements were chosen because both are *deterministic* and
*offline-testable*, which made them a good fit for demonstrating rigor under
governance constraints rather than only relying on vendor/LLM call quality. The
Data Quality Gate forces the system to fail closed: a low-quality dataset can
no longer quietly reach a full-strength debate. That single property (no
`normal` on error or missing evidence) was the most instructive design decision.

The dynamic debate termination introduces a subtle tension: the whole point of
reduce-cost is to stop early, but the evaluator must never stop so early that it
has not reserved enough budget to summarize the debate. Encoding those two rules
(a reserve for summary, and a no-new-evidence patience) as explicit,
deterministic, configurable rules was more valuable than a hand-tuned heuristic.

Looking ahead, the largest open risk is not the code but the verification record:
date-sensitive and network-reachability-dependent tests mean that "the suite is
green" is only meaningful on a specific day and network. The honest position,
recorded throughout this scaffold, is to state the exact observed outcomes and
the known failures rather than claim a blanket pass.