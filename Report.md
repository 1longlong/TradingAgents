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
  policy knobs, policy version `1.0`). Phase 4B (live-provider benchmarking /
  production tuning) is **not performed**.
- Human review decision (historical): Phase 4A is **approved with limitations**
  (WANG Yiwen 60536848, 2026-10-23; `docs/review-memo.md`).

### Blocked final-output enforcement (2026-11-06 review finding 1)

- A 2026-11-06 independent offline review reproduced an end-to-end defect: with
  missing critical market data the real gate returned `blocked`, the graph
  correctly skipped Bull/Bear and the Research Manager rewrote its recommendation
  to Hold, but Trader -> risk debate -> Portfolio Manager still carried a
  synthetic noncompliant model Buy into `final_trade_decision`, and
  `SignalProcessor` returned Buy. The blocked verdict was not authoritative at the
  output boundary (design sections 3.6/7.3).
- **Fix:** a single deterministic, LLM-free guard
  (`tradingagents/agents/utils/output_guard.py`) reads the gate state
  fail-closed (missing/malformed/inconsistent -> `blocked`) and pins only the
  decision field (Recommendation / Rating / Action) to Hold on blocked runs, for
  both structured and free-text output, preserving the rationale,
  evidence-insufficient explanation and recovery conditions. It is wired into the
  Research Manager (replacing the prior duplicated coercion), the Trader, and the
  Portfolio Manager. No numeric confidence ceiling was invented (review finding 4
  remains open and recorded). The adversarial Buy fixtures are deterministic
  enforcement tests, not a measured live incident.
- **Verification:** the independent-review demo now yields `final_signal` = Hold
  (was Buy); `tests/test_output_guard.py` **47 passed**, affected suite **294
  passed**; full offline suite **3 failed / 1528 passed** (the 3 known
  date-sensitive cache tests, pre-existing, no new regression; not claimed
  green) — logbook 058.

### Maintenance corrections (2026-11-06 operator technical review)

The operator technical review (not a human phase approval) confirmed the primary
blocked-to-Buy escape was fixed and requested narrow corrections, which are
complete:

- **Guard edge cases (logbook 059):** the guard now pins *every* recognized
  decision header (Recommendation/Rating/Action) and *every* `FINAL TRANSACTION
  PROPOSAL` marker, regardless of whether a primary header exists, with Markdown
  bullet/heading/value markup tolerated around the decision field only (rationale
  prose is never rewritten); a documented narrow rule neutralises a blocked
  Trader's executable entry/stop/position sizing while keeping the quoted
  rationale. `tests/test_output_guard.py` **55 passed**; idempotence preserved.
- **Pre-call budget guards (logbook 060, finding 2):** a conservative admission
  guard runs before every Bull/Bear, so `max_calls=1` executes exactly one debate
  call and skips safely to the Research Manager with `budget_exhausted` for the
  incomplete round; the summary reserve stays reachable; `enabled=False` keeps the
  legacy fixed-round baseline. Usage remains an honest estimate, not a physical
  provider bound. `tests/test_debate_precall_budget.py` **14 passed**.
- **Audit exports (logbook 061, finding 3):** `evidence_manifest.json` associates
  each record's validations by `evidence_id` and exports the separate
  `validation_results_by_evidence_id` map; `run_summary.json` adds
  `run_id`/`asset_type`/`snapshot_id` (null when unavailable), `quality_counts`,
  and `usage_provenance` (debate calls separate from total-run calls; unmeasured
  tool/input-output counts explicit `None`, never fabricated).
  `tests/test_report_artifacts_audit.py` **12 passed**.
- **Second review corrections (logbook 063):** (1) the pre-call guard's token/time
  check now requires remaining >= reserved summary **plus the estimated next-call
  cost**, not merely the reserve (a remaining-equals-reserve case was wrongly
  admitted); exact token/time boundaries are tested before the first Bull and
  before Bear, and the check is honestly labelled `estimated` /
  `debate_calls_only` (the call limit is debate calls, not total-run budget).
  (2) Audit export now prefers a present authoritative map entry but otherwise
  preserves a record's own embedded validations instead of overwriting them with
  `[]`, with deterministic ordering; disagreeing `run_id`/`snapshot_id` is marked
  ambiguous (null + flag) rather than silently choosing a first identity, and the
  false claim that the adapter mints `snapshot_id` was removed (null until a real
  snapshot identity is recorded). `tests/test_debate_precall_budget.py` **22
  passed**, `tests/test_report_artifacts_audit.py` **20 passed**.
- **Verification (logbook 062/063):** full offline suite **3 failed / 1578 passed**
  (the 3 known date-sensitive cache tests; not claimed green), Ruff clean,
  governance validator PASS, `git diff --check` clean.
- **Operator/AI technical verification (logbook 064, not a human approval):**
  464 focused tests passed in 1.82s; the offline demo returns
  `final_signal=Hold` on the blocked adversarial-model run; `max_calls=1` gives
  `actual_debate_calls=1`; evidence validation counts export as `[7,7,7,7,6]`;
  Ruff, governance validator (35/35, no likely secrets) and `git diff --check`
  pass. A stricter fully offline run (socket.connect disabled,
  `-m "not integration"`) observed **4 failed / 1577 passed / 1 skipped / 1
  deselected** — the 3 known date-sensitive cache tests plus the known Yahoo
  reachability/exception-type baseline. This is recorded **separately** from the
  earlier 3-failure run under different connectivity conditions; neither run is
  all-green.
- **Status:** the 2026-10-23 human approvals remain historical for their reviewed
  scope. The 2026-11-06 guard/budget/audit maintenance fixes are technically
  verified and **await explicit human review** — no human approval is recorded
  for them and no traceability scores were entered.
- **Still open (not hidden):** review finding 4 (degraded confidence ceiling is
  not a validated numeric cap; DEBT-014) and broader original-design item 5
  (automatic multi-category adapters / full source-attempt lifecycle;
  DEBT-015/RISK-015) — explicitly out of scope for these maintenance milestones.

### Independent recheck 2026-11-06 (findings 1, 2, 3 fixed; awaiting human review)

A second, independent AI technical recheck (not a human approval) reproduced
three further defects on the maintenance tree; all three are now fixed and
regression-tested offline:

- **Finding 1 (High) — blocked verdict could still become a final Buy for
  alternative rating headers.** `Rating：Buy` (fullwidth colon) and
  `Final rating: Buy` escaped because the guard anchored labels while
  `extract_rating` NFKC-normalized and searched within a line, taking the last
  rating. The guard now recognizes the same header grammar the extractor reads
  (fullwidth colon, prefixed labels such as "Final rating", unicode dashes,
  repeated/trailing alternative labels); additionally the final signal boundary is
  gate-aware (`SignalProcessor.process_signal(text, state)` returns Hold on a
  blocked run) and the memory log records Hold for a blocked run. Complete-graph
  regressions (`Rating：Buy`, `Final rating: Buy`, separator cases) end Hold.
- **Finding 2 (High) — real gate -> manifest -> debate quality propagation was
  broken.** `evaluate_multi_category_gate` discarded the aggregator's per-record
  status map and serialized the provisional adapter records
  (`Low`/`unvalidated`), so a normal/Medium gate run produced empty
  `EvidenceManifest.valid_ids`, an empty allowlist, and round-1 `no_new_evidence`.
  Each record's own classification/reasons/validations are now applied before
  serialization (never a blanket promotion from the group rating).
  `tests/test_gate_debate_integration.py` proves, through the *real* gate node,
  that a cited+linked Medium/High ID counts as new while genuine Low/Blocked/future
  evidence does not, and that report `quality_counts` reflect Medium, not five Low.
- **Finding 3 (Medium) — guard concatenated Hold with following prose.**
  `Rating: Buy because ...` became `Rating: Holdbecause ...` (final signal
  REVIEW). The semantic whitespace separator and markdown boundary are now
  preserved across every decision-field variant; guarded output is idempotent and
  parses to Hold.
- **Verification:** `tests/test_output_guard.py` **90 passed**;
  `tests/test_gate_debate_integration.py` **9 passed**; focused affected suite
  **480 passed**; strict fully offline suite (socket.connect disabled,
  `-m "not integration"`) **4 failed / 1621 passed / 1 skipped / 1 deselected /
  88 subtests** — the *same* 3 known date-sensitive cache tests plus the known
  Yahoo reachability baseline; no new regression; not claimed all-green. Ruff
  clean; governance validator PASS (35/35, no secrets); `git diff --check` clean
  (logbook 065).
- **Operator recheck (2026-11-06, technical feedback, not a human approval):** a
  residual was reproduced in the current guard — fullwidth labels/values
  (`Ｒａｔｉｎｇ：Ｂｕｙ`) and arbitrarily prefixed labels
  (`My final overall investment rating: Buy`) still parsed as Buy on the plain
  textual signal, so the saved report/decision text and memory DECISION body could
  contradict the Hold tag even though the structured signal was Hold. The previous
  claim that the guard and parser share the same grammar was **false** (bounded
  descriptor count, only the fullwidth colon handled). Corrected narrowly: the
  guard now canonicalises every parser-recognized labelled rating line to
  `**Rating**: Hold` using the rating parser's own shared NFKC/label recognition
  (not a finite prefix list), preserving the natural-language tail as
  non-executable explanation and staying idempotent. Fullwidth/prefixed/repeated/
  trailing labels and full-graph report+memory tag/body consistency are covered;
  normal/degraded behavior is unchanged and no policy/optional adapter changed.
  `cli/main.py` is byte-identical to HEAD — there is **no CLI change** in this
  tree (the signal hook is `TradingAgentsGraph.process_signal(curr_state)`).
  Focused suite **480 passed**; strict offline suite **4 failed / 1621 passed**
  (same baselines; logbook 066). This remains **awaiting explicit human review**.

- **Operator executable-instruction maintenance (2026-11-06, technical, not a
  human approval):** on the current tree a blocked run with a fake model returning
  `Ａｃｔｉｏｎ：Ｂｕｙ / Entry Price：100 / Stop Loss：95 / Position Sizing：20% /
  FINAL TRANSACTION PROPOSAL: BUY because momentum improved` had `**Action**: Hold`
  prepended but left all four executable lines intact; long/fullwidth
  `Recommendation` headers and explained proposal markers behaved the same. Fixed
  with one shared **linear** recognizer
  (`rating.decision_header`/`_split_header`: NFKC-first, arbitrary plain
  descriptor with no cap, required separator, single-word value; blockquotes and
  narrative mentions excluded) used by the guard. Every decision field is pinned
  to `**<Label>**: Hold`; a blocked Trader's fullwidth entry/stop/sizing fields
  become `not applicable`; an explained proposal marker becomes
  `FINAL TRANSACTION PROPOSAL: **HOLD**` with the tail kept. Rationale, quoted
  alternatives and recovery conditions are preserved, the operation is idempotent
  and fast on long prose, and `extract_rating` now honours the structural decision
  over quoted/narrative mentions so the plain signal, report and memory agree.
  `cli/main.py` unchanged. `tests/test_output_guard.py` **130 passed**; focused
  affected suite **520 passed**; strict offline suite **4 failed / 1661 passed**
  (same baselines; logbook 067). Corrected in-pass interruptions: a catastrophic
  backtracking regex, an empty-tail/cap design, and the parser/guard disagreement.
  This remains **awaiting explicit human review**.

- **Scope integrity:** Phase 4A scripted numbers remain labelled scripted and are
  **not** presented as proof of runtime integration; finding 2 is proven by the
  real-gate integration test, not by the scripted fixtures. The prior
  guard/budget/audit changes are preserved. These fixes **await explicit human
  review** — no human approval or traceability score is recorded for them. The
  CLI state-passing hardening gap, the degraded confidence ceiling (DEBT-014) and
  automatic optional-category adapters (DEBT-015/RISK-015) remain explicitly OPEN;
  no numeric policy was invented.

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

### Live verification (2026-11-06, authorized; AI technical evidence, NOT human approval)

- **Scope:** one authorized end-to-end school-model run against
  `https://llm.cs.cityu.edu.hk/v1`, model `CS5351/DeepSeek-V4-Flash`, ticker
  **NVDA**, target date **2026-11-05**, using real public data tools + the real
  gate/managers/Trader/risk. Credentials stayed in memory only; not written.
- **Result:** 18 successful model calls, **202,622 gateway-reported tokens**; no
  model HTTP error, no truncation; final gate **degraded**; final (state-aware and
  textual) signal **Overweight**. A first harness attempt (18 calls / 178,453
  tokens) failed only because the local streaming harness omitted `graph.ticker`
  before logging — a **harness error, not a project bug**; the corrected rerun
  totals **36 calls / 381,075 reported tokens** (retry cost not hidden).
- **Market evidence:** five market records, `observed_at=2026-11-04`,
  `target_date=2026-11-05`, all **Medium** (each validated 7/7/7/7/6); optional
  fundamentals/news/sentiment all **Low/unavailable** → degraded (not fabricated
  normal). This is honest, not a bug.
- **OPEN issues found (NOT fixed; source unchanged):**
  1. **Budget accounting basis (RISK-021 / DEBT-021):** researchers pass no
     actual latency/usage; the budget recorded **2,171.77 s estimated** for a Bull
     call whose actual latency was **12.72 s**, and 16,289 estimated vs 18,058
     reported tokens. The estimate exhausted the 600 s debate budget, so Bear was
     refused with `budget_exhausted` and **0 complete Bull/Bear rounds** ran.
  2. **Claim-date semantics (RISK-020 / DEBT-022):** Bull correctly cited the
     valid close evidence ID but relabelled the Nov-4 close (200.13) as Nov-5 in
     prose/metadata; the allowlist validates eligibility, not claim-date truth.
- **Counterfactual blocked replay (deterministic, offline):** the saved live
  Research Manager / Trader / Portfolio Manager outputs were fed through the
  blocked guard; all primary decisions became Hold and sizing became
  not-applicable. This is a **replay of saved outputs, NOT an additional live run**
  and NOT a live blocked-path proof.
- **Not all-bug-proof:** the live gate was **degraded, not blocked**; the normal
  multi-round path and a real blocked-path live run were **not** exercised live.
  A completed-round live check and a blocked-path live check require separate
  explicit authorization (RISK-023).
- **Existing open items unchanged:** degraded confidence ceiling (DEBT-014),
  automatic optional adapters (DEBT-015/RISK-015), and the CLI state-passing gap
  remain OPEN.

### Documentation / requirements revision (2026-11-06, documentation-only)

- Extended `docs/req/req-schema.json` and `docs/req/requirements.yaml` with a
  product/PRD block, per-requirement structured `fit_criterion` (metric /
  operator / threshold / unit / verification / applicability / status),
  `priority_rationale`, `tradeoff`, `origin`, and `category`; added an explicit
  `deferred_scope` (Won't/deferred) block. All 22 IDs and historical `type`
  values are preserved (schema_version advanced to v1.1, additive).
- Expanded the invariant register, added proposed ADR-004 (governance context
  design, not implemented), a role-by-path deny-by-default permission model + a
  non-active machine-readable proposal, a human-only rules proposal, a CI gate
  matrix (document only), and authoritative prompt **v1.3** (plan-first STOP).
- This revision is **documentation-only**: no source, tests, CI, or active
  configuration were changed; it is **not human-approved** and awaits review.

### Documentation / traceability consistency batch (2026-11-10, documentation-only)

- Three verification **tiers** are now Structural / Regression / Behavioral;
  offline-vs-live is a **separate evidence axis** (never a substitute tier, never
  live proof). `docs/code-governance/verification-constraints.md`.
- All 29 requirement-mapped test files now carry an accurate `Traceability:`
  declaration of their own FR/NFR ID; deterministic governance regressions resolve
  those tags against the registry/invariants and require each requirement's own
  ID. The 22 requirement IDs are unchanged; INV-11/12/14 stay honest (unmapped /
  proposed).
- The role-by-path permission model, its non-active machine-readable proposal, the
  validator (narrow dangling-reference resolution + true forced-fallback
  regressions), the required-artifact/YAML inventory (prompt v1.3, ADR-004/005,
  the proposals), and the NFR-OFF-001 count-and-fail harness were synchronized.
  The proposal remains **inactive**; no active permission, CI, `.github/**`,
  `pyproject.toml`, or `.opencode/**` config was changed, and actual enforcement is
  **UNVERIFIED** and not claimed.
- This batch is **documentation/traceability-only** (plus deterministic test and
  validator additions); it is technically verified offline (validator PASS 42/42;
  governance 48 passed; mapped+focused 1000 passed; strict-offline 4 failed / 1768
  passed with 1 intercepted attempt) and **awaits human acceptance**. Independent
  Codex verification of the current files recorded the same final result (see
  logbook 072).

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
- **Feature-branch checkpoint (2026-11-10)** — the human authorized committing
  and pushing the existing maintenance/documentation work to
  `feature/data-quality-debate-control` as work in progress. This is not final
  human acceptance, a PR, or authorization to merge into release. Earlier
  uncommitted/not-pushed statements describe pre-checkpoint snapshots; Git
  history and the remote branch are the authority for publication status.
  The new measured-budget/partial-debate-attribution repair plan and its live
  blocked-path verification remain proposed and unimplemented.
- **2026-11-10 repair batches (plan + tests human-approved; acceptance PENDING,
  technical only)** — the first batch fixed three reproduced defects (blocked
  multiline executable containment in the output guard, present-empty
  authoritative validation override in report artifacts, and shared duplicate-ID
  uniqueness across the validator's real and fallback paths; the second batch is
  documentation/traceability consistency). The strict-offline count-and-fail
  harness observes the **same 4 known baseline failures** (3 date-sensitive
  `test_ohlcv_cache_freshness` + the `test_no_data_handling` vendor-reachability
  baseline) and **1 intercepted outbound socket attempt** (no connection made)
  from that baseline, so **NFR-OFF-001 stays PARTIAL/OPEN** (DEBT-002/RISK-002)
  and the suite is **not all-green**. No baseline test/CI/waiver was modified; no
  human acceptance, CI enforcement, permission enforcement, traceability score, or
  green-suite claim is made.
- **OpenCode permission schema / enforcement uncertainty** — the installed
  binary is `1.18.25`; the SDK static type shape and the broad `.opencode/
  permissions.jsonc` are recorded, but **load/enforcement is UNVERIFIED** (a
  benign probe is still pending). See `docs/debt-register.md` DEBT-004/DEBT-027.
- **Live-verification findings (2026-11-06, OPEN, not fixed)** — budget
  accounting uses estimates not provider usage (Bear refused, 0 complete rounds;
  RISK-021/DEBT-021) and a cited valid ID did not prevent a wrong claim date
  (RISK-020/DEBT-022). The run was degraded (not blocked); live integration is
  not all-bug-proof. See §"Live verification" below.
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
