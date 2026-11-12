# Review Memo — Human Review Record

Each project phase requires an explicit recorded human review before it is
declared complete. A phase without a recorded review is **not** claimed
complete. Reviews are recorded here; AI-tool use is recorded separately in
`docs/ai-use-log.yaml`.

## Current status (as of 2026-11-11)

- **CURRENT (2026-11-11):** all four approved repair items (Stages 1-4:
  ADR-008 automatic structured evidence ingestion, ADR-009 durable run-scoped
  usage ledger, ADR-010 exact claim validation, ADR-011 degraded-run confidence
  cap 0.60) are **implemented and offline-verified in the dirty working tree** on
  branch `feature/data-quality-debate-control`, HEAD `5ecea91` unchanged (no
  commit/push). Current full strict-offline suite: **2154 passed, 1 skipped, 1
  deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts**; Ruff
  clean; governance validator PASS (43/43); `git diff --check` clean (logbook
  082). There is **no current live-provider run, no remote-CI-green claim, no
  human signoff/acceptance, and no commit/push**. **Independent AI verification
  (Codex, 2026-11-11): CONFIRMED offline** — 107 focused cap tests passed; full
  strict-offline 2154 passed / 1 skipped / 1 deselected / 22 warnings / 88
  subtests / 0 forbidden socket attempts; Ruff clean; governance validator PASS
  (43/43); `git diff --check` clean; HEAD `5ecea91` unchanged and frozen files
  unchanged. This is an independent AI technical verification, **NOT** human
  acceptance and **NOT** a remote-CI/live claim. Any older four-baseline-failure /
  live-run claims elsewhere in this file are HISTORICAL, source-specific evidence
  for earlier snapshots and are superseded by this current status; they are
  retained for audit, not deleted.

- **Publication authorization (2026-11-11, not merge or completion acceptance).**
  WANG Yiwen explicitly requested committing and pushing the verified repair to
  `feature/data-quality-debate-control`, updating existing Draft PR #2 and
  triggering CI. The remote feature branch was fetched with zero divergence.
  Independent local results are recorded in logbook 078 / AUL-040; publication
  preflight is AUL-041. Remote CI success must be checked after the push and is
  not inferred from local passes. No merge is authorized or performed.

- **2026-11-11 scoped CI/baseline repair (plan/test authorization only, NOT
  human acceptance).** WANG Yiwen explicitly approved this round's repair plan
  AND test cases in the controlling conversation on 2026-11-11. This authorized
  the Builder to implement the scoped maintenance (validator subset-fallback
  schema-version fix, TZ-stable cache fixtures, socket-free no-data tests). It is
  the human approval of the PLAN and TESTS, not a completion acceptance of the
  implemented change; later human review remains pending. Outcome recorded in
  logbook 078 / AUL-040 / ADR-006; remote GitHub CI was not re-run (push not
  authorized). The four former baseline failures are resolved offline (full
  strict-offline suite 1844 passed, 0 socket attempts); the historical figures
  below are preserved as history.

  **INDEPENDENT Codex verification of this repair (2026-11-11; AI technical
  evidence, NOT remote-green and NOT human acceptance):** focused three modules
  **76 passed / 0 socket attempts**; forced-no-jsonschema governance **52 passed,
  6 skipped / 0 attempts**; full strict offline **1844 passed, 1 skipped, 1
  deselected, 22 warnings, 88 subtests / 0 attempts**; full strict suite with
  `jsonschema` hidden via a `find_spec` simulation **1838 passed, 7 skipped, 1
  deselected, 22 warnings, 88 subtests / 0 attempts**; separate
  `TZ=UTC`/`Asia/Hong_Kong`/`America/New_York` runs of the cache+no-data modules
  each **18 passed / 0 attempts**; Ruff, validator **43/43**, and `git diff
  --check` pass. This confirms the offline repair and the zero-socket guarantee;
  it is not a claim of green remote CI or human acceptance.

- **LATEST final-commit live verification (supersedes the earlier absence of a
  post-follow-up full-workflow run; NOT human acceptance).** At the human's
  explicit request, Codex reran the actual school model on committed source
  `bda6e3a135976bcdb66f84e02ebda666167177e2`, with a clean starting tree and
  matching 214-file source/test fingerprints before and after execution.
  Both bounded workflows completed: 25 application calls, 219496 reported
  tokens, zero output truncations, retries disabled. D1 used real analysts and
  vendors, gate `degraded`, both Bull/Bear invoked, one complete round, stop
  `max_rounds_reached`; debate accounting was 31.924532042001374 measured seconds
  and 31120 provider tokens (27066 input + 4054 output). D2 used the explicit
  empty-critical-market fixture, real gate and real downstream model nodes:
  zero Bull/Bear calls, Hold at manager/trader/portfolio/final/memory, no
  executable blocked Trader sizing. D1/D2 checks passed 21/21; nine additional
  default-quarantine checks passed, including actual file persistence, run
  identity, non-authoritative labeling and exclusion of raw narrative from
  trusted manager/report/memory text. See logbook 077 / AUL-039 and external
  backup `2026-11-10-final-commit-school-live-hkmbgkqj/`.
  This is selected-case live evidence, not exhaustive testing: D2 is synthetic
  missing evidence, not a live-vendor outage; UNKNOWN/legacy adversarial states,
  malformed-state handling and failed-node resume remain separately scoped
  offline/untested limitations. The four known baseline failures remain.
  Only verification documentation changed after the run; no feature/test edits,
  new commit/push, PR, merge, or human acceptance occurred in this rerun.

- **CURRENT DISPOSITION (supersedes the pre-repair bullets below for these
  specific figures; NOT human acceptance).** The DEBT-021/033 measured-budget +
  participation repair (ADR-007), including the follow-up unknown/quarantine/
  malformed fixes, is implemented and independently verified on the FINAL tree:
  **644 focused offline tests passed (2 warnings)**, 0 forbidden socket
  attempts, **25/25** external boundary probes (now including the UNKNOWN
  adversary, default quarantine + run identity, and malformed unhashable-speaker
  cases); canonical `scripts/validate/strict_offline_harness.py` **1822 passed /
  4 SAME known baseline failures / 1 skipped / 1 deselected / 22 warnings / 88
  subtests / 1 intercepted baseline socket attempt (no connection)**;
  Ruff/governance 42/42/diff clean (logbook 076, AUL-037). Bounded real
  school-model validation **completed on the frozen PRE-FOLLOWUP tree** (25
  application calls, 228,903 gateway tokens, 0 retries): D2 = a **narrow
  controlled-fixture blocked-path proof** (real gate + real downstream nodes;
  zero Bull/Bear invokes; Hold throughout; participation `data_quality_blocked`)
  — **not** exhaustive and **not** live-vendor blocked proof; D1 = real-vendor
  run with Bull+Bear invoked, one complete round, stop `max_rounds_reached`,
  measured + provider usage (logbook 074, AUL-035). The follow-up branches were
  **offline-only** verified — there was **no second live run** and no claim the
  old 214-file fingerprint is unchanged after the follow-up. **Human final
  acceptance remains PENDING.** At verification completion these changes were
  local and uncommitted/unpushed. The human has subsequently authorized their
  commit and push to `feature/data-quality-debate-control` only (AUL-038);
  consult Git history and remote verification for publication completion.
  This authorization is NOT final feature acceptance, PR creation, or a release
  merge. Remaining limits stay OPEN:
  failed-checkpoint/cross-resume hard-budget accounting unsolved; all-agent
  production usage totals untracked; degraded confidence cap (DEBT-014) and
  optional adapters (DEBT-015/RISK-015) open; the suite is **NOT all-green**.
- **Follow-up (2026-11-10, OFFLINE ONLY; logbook 075, AUL-036):** three
  approved-plan deviations were corrected — the deterministic trusted
  partial-debate template + quarantine now apply to **partial OR unknown/legacy**
  (incl. blocked, Hold re-pinned); the quarantine path is resolved via
  `resolve_audit_paths` so the real graph persists under `results_dir`/identity
  without an explicit override; malformed structured state (list-valued speaker
  / non-mapping turns) fails closed to unverified instead of raising. Fresh
  OFFLINE evidence (independent): 644 focused passed / 25/25 probes;
  full strict offline 1822 passed / 4 SAME baseline failures / 1 skipped / 1
  deselected / 88 subtests; Ruff/governance 42/42/diff clean (logbook 076,
  AUL-037; the earlier inline 392 was the pre-independent count). The D1/D2 live
  results apply to the **frozen pre-follow-up** tree and are **not** re-claimed
  for these follow-up branches (no live audit-file-persistence claim; no second
  live run; no claim the 214-file fingerprint is unchanged after follow-up).
  Human acceptance remains PENDING; changes remain UNCOMMITTED/UNPUSHED.

- **HISTORICAL / PRE-REPAIR (retained for provenance; superseded above for its
  counts and "live blocked-path OPEN" phrasing).** The earlier feature-branch
  checkpoint publication note below was recorded before the repair: at that time
  the full offline pre-push recheck reported 1768 passed / 4 known failures / 1
  skipped / 1 deselected / 1 intercepted socket attempt, and the live
  blocked-path verification was open. It remains an accurate record of that
  checkpoint's authorization (a preliminary backup, **not** acceptance); it does
  not describe the CURRENT tree.

- **Feature-branch checkpoint publication authorized (not acceptance).** The
  human explicitly requested committing/pushing the current work to
  `feature/data-quality-debate-control` as a preliminary backup. This does not
  approve the pending budget/participation repair plan, final feature acceptance,
  a PR, or a release merge. DEBT-021/033 and the live blocked-path verification
  remain open. The current full offline pre-push recheck still reports 1768
  passed, four known failures, one skipped, one deselected and one intercepted
  socket attempt; no all-green claim is made.

- **2026-11-10 human approval is PLAN + TESTS ONLY (not acceptance).** The human
  explicitly approved the November 10 repair plan and its test cases
  (“批准本轮修复计划和测试用例”). This authorizes the two repair batches (the first
  batch's guard/report/validator fixes + this second documentation/traceability
  batch) to proceed; it is **NOT** acceptance of the fixes. **Final human
  acceptance remains PENDING.** (The approved plan has since been implemented and
  verified — see the CURRENT DISPOSITION above and logbook 074 — which is still
  not acceptance.)
- **Present AI technical checks (2026-11-10, NOT human approval):**
  - First batch (F1): `tests/test_output_guard.py` 197 passed; report-artifact and
    shared-ID regressions; strict offline 4 failed / 1743 passed (logbook 070).
  - This doc/traceability batch (D1): validator PASS (42/42, no secrets);
    governance 48 passed; mapped+focused 1000 passed; strict-offline count-and-fail
    harness **4 failed / 1768 passed / 1 skipped / 1 deselected** — the SAME four
    known baselines (3 date-sensitive `test_ohlcv_cache_freshness` +
    `test_no_data_handling` empty-download). Ruff clean; diff-check clean
    (logbook 071).
- **Unresolved / must not be hidden (2026-11-10):** the **4 known baseline
  failures** remain (RISK-001/RISK-002) and the NFR-OFF-001 count-and-fail harness
  observes **1 intercepted vendor-reachability socket attempt** (no connection
  made) from the existing `test_no_data_handling` baseline, so **NFR-OFF-001 stays
  PARTIAL/OPEN**; the suite is **NOT all-green**. No baseline test/CI/waiver was
  modified.
- **Independent Codex AI verification (HISTORICAL / PRE-REPAIR, logbook 072; the
  "583 passed / 1768 passed" figures are superseded by the CURRENT DISPOSITION
  above; NOT human acceptance):** 14-file focused suite **583 passed / 2
  warnings**; validator **42/42 PASS** + no secret hits; independent boundary
  **39/39**; **440** negative schema mutations rejected; actual
  `strict_offline_harness.py` run **4 failed / 1768 passed / 1 skipped / 1
  deselected** with the same **1** intercepted baseline attempt; Ruff clean;
  `git diff --check` clean. This was the pre-repair recorded result and is AI
  technical verification only.
- **User-authorized school-model live run (2026-11-10, Codex; docs-only record;
  NOT human acceptance; logbook 073 — HISTORICAL / PRE-REPAIR; superseded for its
  "0 complete rounds / DEBT-021 OPEN" status by the CURRENT DISPOSITION / logbook
  074):** measured by external callbacks, **16
  application model calls / 170,665 gateway-reported tokens / 0 truncations**
  (excludes OpenCode documentation-tool inference); final and report textual
  signal both **Overweight**. The live Gate was **DEGRADED, not blocked**, so
  `blocked_signal_is_hold = true` is **VACUOUS** and is **not** live proof of the
  blocked path. The run ended with **0 complete Bull/Bear rounds**. The report
  honestly leaves `total_run_calls`/input/output/tool_calls **null** and reports
  only debate-only **estimated** usage (1 call / 15,183 tokens / 2,024.4 s).
  **DEBT-021 remains OPEN**: Bull actual **19.70 s / 16,931 tokens** vs estimated
  **2,024.4 s / 15,183**; the pre-call guard correctly refused Bear but the
  inflated time estimate stopped it **prematurely** (Bear node visited, **0 actual
  Bear calls**, `bear_history` empty; `budget_exhausted`). The actual runtime did
  **not** exceed 600 s — only the faulty estimate did. Optional
  fundamentals/news/sentiment remain `unavailable_no_structured_source`
  (DEBT-015/RISK-015, **not fixed**); a supplemental **offline** boundary rerun
  passed 39/39 and is **not** a live blocked-path test. **Final human acceptance
  remains PENDING**; no approval/score/reflection is recorded here.
- **2026-10-23 human approvals remain historical for their reviewed scope.**
  The human-authored decisions for Stage 2 (runtime multi-category gate), the
  ConflictRecord / dynamic debate termination work, and Phase 4A
  (approved with limitations) stand for the scope reviewed on those dates and are
  **not** re-opened by this note.
- **2026-11-06 guard/budget/audit maintenance fixes are technically verified and
  await explicit human review.** The blocked final-output guard (FR-DQG-006), the
  pre-call budget guard (including the second-review reserve + estimated
  next-call-cost boundary), and the audit-export corrections (per-evidence
  validations; run-summary identity/quality/usage provenance; ambiguous-identity
  handling) were implemented and verified by operator/AI technical verification
  only. **No human approval has been recorded for these changes**, and no
  traceability scores were entered.
- **Operator/AI technical verification of the stricter fully offline suite
  (2026-11-06):** with `socket.socket.connect` patched to raise
  `OSError('Network disabled for offline verification')` and run as
  `pytest -q -p no:cacheprovider -m "not integration"`, the observed result was
  **4 failed, 1577 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
  passed** (logbook 064). The four failures are the known Yahoo
  reachability/exception-type baseline
  (`tests/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache`)
  plus the three known date-sensitive cache tests
  (`tests/test_ohlcv_cache_freshness.py`). This is recorded **separately** from
  the earlier 3-failure run under different connectivity conditions; neither run
  is claimed all-green. This is operator/AI technical evidence, **not** a human
  approval.

### 2026-11-12 — Explicit human publication authorization (not feature acceptance)

The human requested: push the current reviewed work to GitHub and a PR. This
authorizes committing the accumulated in-scope Stage 1-4 maintenance and
verified-span repair, pushing to `feature/data-quality-debate-control`, and
updating the existing open PR #2 with base `release`. It does not authorize
merging, new live product calls, or recording final human feature acceptance.
Existing pending acceptance decisions and live-verification limitations remain
visible. Raw session backups and live-run artifacts remain in
`/Users/wangyiwen/OpenCodeRecords/TradingAgents/`, outside the repository.
- Still open and explicitly **not** resolved: the degraded-run numeric
  confidence-ceiling policy (DEBT-014) and the automatic multi-category
  data adapters / full source-attempt lifecycle (DEBT-015 / RISK-015). See
  `docs/debt-register.md` and `docs/architecture/risk-list.md`.
- **2026-11-06 independent recheck findings 1/2/3 fixes are technically verified
  and await explicit human review (not a human approval).** An independent AI
  recheck reproduced three defects on the maintenance tree; all three are fixed
  and regression-tested offline (logbook 065): (1) blocked-signal escape for
  alternative rating headers (`Rating：Buy`, `Final rating: Buy`) — the guard now
  aligns with the rating parser and the final signal boundary is gate-aware;
  (2) real gate -> manifest -> debate quality propagation — each record's own
  classification/reasons/validations are applied before serialization; (3) the
  `Hold`/prose separator is preserved. Focused affected suite **480 passed**;
  strict fully offline suite (socket disabled) **4 failed / 1621 passed / 1
  skipped / 1 deselected** — the same known 3 date-sensitive cache tests plus the
  known Yahoo reachability baseline; no new regression; not claimed all-green.
  **No human approval and no traceability score is recorded for these changes.**
- **Operator recheck (2026-11-06, technical feedback — not a human approval):** a
  residual was reproduced in the current guard (fullwidth labels/values and
  arbitrarily prefixed labels still parsed as Buy on the plain textual signal,
  contradicting the Hold tag in the report/memory body). Corrected narrowly by
  canonicalising every parser-recognized labelled rating line via the shared parser
  recognition; focused suite **480 passed**, strict offline suite **4 failed / 1621
  passed** (same known baselines, logbook 066). `cli/main.py` is byte-identical to
  HEAD (no CLI change). These fixes remain **awaiting explicit human review**; no
  human approval or traceability score is recorded.
- **Operator executable-instruction maintenance (2026-11-06, technical feedback —
  not a human approval):** executable directional instructions survived a blocked
  gate in the stored intermediate plans (fullwidth headers/sizing, explained
  `FINAL TRANSACTION PROPOSAL: BUY because ...` markers, long descriptors), and a
  first regex attempt caused catastrophic backtracking; a quoted/narrative rating
  mention could also override the pinned Hold. All corrected with one shared linear
  recognizer that pins every decision field to Hold, neutralises blocked sizing and
  explained markers, preserves rationale/quoted alternatives, and makes
  `extract_rating` honour the structural decision. `tests/test_output_guard.py`
  **130 passed**; focused affected suite **520 passed**; strict offline suite
  **4 failed / 1661 passed** (same known baselines, logbook 067). `cli/main.py`
  unchanged; the CLI state-passing gap, DEBT-014 and DEBT-015/RISK-015 remain
  **OPEN**. These fixes remain **awaiting explicit human review**; no human
  approval or traceability score is recorded.
- **2026-11-06 authorized school-model live verification (AI technical evidence,
  NOT human approval):** NVDA / 2026-11-05, `CS5351/DeepSeek-V4-Flash`, 18 calls
  / 202,622 reported tokens, gate **degraded**, signal **Overweight**. Two OPEN,
  unfixed issues were found and recorded, not resolved: budget accounting uses
  estimates not provider usage (Bear refused, 0 complete rounds; RISK-021 /
  DEBT-021) and a valid cited ID did not prevent a wrong claim date (RISK-020 /
  DEBT-022). The run was degraded, not blocked; live integration is not
  all-bug-proof (RISK-023). A deterministic counterfactual replay of saved
  outputs is not an additional live run.
- **2026-11-06 documentation/requirements revision (this turn):** documentation
  and requirements-schema maintenance only (PRD block, structured fit criteria,
  invariant register, proposed ADR-004, permission proposal, human-only rules
  proposal, CI gate matrix, prompt v1.3). **No source, tests, CI, or active
  configuration changed.** This revision is **NOT human-approved** and awaits
  review; no traceability score is recorded.
- **Factual status:** base commit `8abea81` is pushed to
  `origin/feature/data-quality-debate-control`; the 2026-11-06 maintenance and
  this revision are **uncommitted** (not newly pushed). Phase 4B and production
  tuning were **not** performed.


## Phase 1 — Analysis

- **Status:** Reviewed and approved to proceed to contract.
- **Reviewer:** Human (project) with coding-agent support.
- **Date:** 2026-10-19
- **Decision:** Requirements frozen; no further analysis in scope.
- **Notes:** The inherited TradingAgents fork was analyzed read-only; candidate
  improvements identified (deterministic Data Quality Gate; dynamic
  evidence-aware debate termination).

## Phase 2 — Contract (evidence + deterministic gate core)

- **Status:** Reviewed and approved to proceed to graph integration.
- **Reviewer:** Human (project) with coding-agent support.
- **Date:** 2026-10-20
- **Decision:** Evidence model and deterministic gate core accepted.
- **Notes:** Decimal-math cleanup accepted; serialization kept acyclic.

## Phase 3A — Gate graph integration

- **Status:** Reviewed; proceed to Phase 3B.
- **Reviewer:** Human (project) with coding-agent support.
- **Date:** 2026-10-21
- **Decision:** Gate node and router accepted.
- **Notes:** Fail-closed routing and deterministic identifiers validated by the
  targeted tests.

## Phase 3B — Dynamic debate termination

- **Status:** Review requested; human/Codex review performed; verification
  recorded.
- **Reviewer:** Human (project) with Codex review.
- **Date:** 2026-10-21
- **Decision:** Implementation accepted with corrections applied (see
  `docs/bug-diary.md`).
- **Notes:** Debate-focused suite 333 passed (current tree). Known
  date-sensitive and network-reachability failures recorded, not hidden. Full
  suite is **not** claimed fully green.

## Stage 2 — Multi-category gate + report artifacts

- **Status:** Review requested; verification recorded; **not claimed complete
  without an explicit human sign-off** for this phase.
- **Reviewer:** Human (project) with coding-agent support.
- **Date:** 2026-10-21
- **Decision:** Stage 2 multi-category gate engine and shared redacted report
  artifacts verified at the engine + shared-writer level.
- **Notes:** `tests/test_stage2_multicategory_gate.py` (26 passed) and
  `tests/test_report_artifacts_stage2.py` (16 passed); Stage-2 relevant suite
  402 passed (entry 040 in `docs/architecture/evaluation-logbook.md`). The
  multi-category engine is **not** the runtime graph default (RISK-009 /
  DEBT-009) and is documented honestly. No Phase 4 or runtime ConflictRecord
  automation was implemented.

### Stage 2 — Runtime multi-category gate integration (follow-up)

- **Status:** Implemented and verified at the engine + graph level; **still
  requires explicit human sign-off** to mark the Stage 2 phase complete.
- **Reviewer:** Human (project) with coding-agent support.
- **Date:** 2026-10-21
- **Decision:** The runtime LangGraph default now delegates to
  `evaluate_multi_category_gate` (market + fundamentals + news + sentiment).
  RISK-009 / DEBT-009 **resolved**.
- **Notes:**
  - `create_data_quality_gate_node` uses the multi-category engine by default;
    optional-category evidence enters **only** through the explicit
    `data_quality_optional_evidence` contract (never parsed from analyst prose;
    an absent optional category yields a deterministic
    unavailable/insufficient result that degrades under the policy).
  - Market stays fail-closed; legacy public state keys, routing behavior,
    deterministic run IDs, and node-factory injection are preserved. The
    evidence layer no longer imports the graph package (circular-import
    eliminated; shared market-record construction lives in the evidence adapter).
  - New graph-level tests prove normal/degraded/blocked routing, structured
    optional-evidence handling, absent optional evidence, legacy compatibility,
    point-in-time rejection, and deterministic serialization.
  - Verification: Stage-2 relevant suite 442 passed (entry 043), full offline
    suite 4 known baseline failures unchanged (entry 044), Ruff + `git diff
    --check` + governance validator clean (entry 045).

## Open / not yet reviewed — HISTORICAL (superseded 2026-11-06)

> **Historical / superseded.** This section recorded the state as of
> 2026-10-21, before later reviews. It is retained verbatim for audit history and
> is **not** the current status. For current status see the "Current status (as
> of 2026-11-06)" section at the top: Stage 2 and the later phases received
> 2026-10-22/2026-10-23 human decisions for their reviewed scope, and the
> 2026-11-06 maintenance fixes await explicit human review.

- ~~**Verification of the full offline suite** is not claimed as a clean green
  run in this environment (see `docs/architecture/risk-list.md`).~~
- ~~**Stage 2 full completion** is not claimed until an explicit human review
  sign-off is recorded for the Stage 2 phase (runtime integration implemented;
  RISK-009 / DEBT-009 resolved, but the phase sign-off is still pending).~~
- ~~**No submission, demo, or Phase 4** decision has been recorded or made.~~

## ConflictRecord runtime lifecycle (FR-DDT-005) — review requested

- **Status:** Implemented and verified at the tracker + evaluator-node +
  research-manager level; **requires explicit human sign-off** (Phase 3B
  conflict surface).
- **Reviewer:** Human (project) with coding-agent support.
- **Date:** 2026-10-21
- **Decision:** A pure, LLM-free conflict tracker (`tradingagents/debate/conflicts.py`)
  now creates, observes (deduplicates/merges), resolves, and escalates
  `ConflictRecord` objects derived **only** from the structured
  `conflict_assertions` a `DebateTurn` carries (parsed from `DEBATE_METADATA`
  `conflict_a`). This **supersedes** the earlier Stage-2 note that runtime
  ConflictRecord automation was out of scope.
- **Notes:**
  - Deterministic conflict IDs from `(normalized topic, kind)` (INV-5).
  - Evidence validation fails closed: an unknown/Low/future evidence ID never
    creates a conflict, and a re-observation citing such an ID drops the
    previously-open conflict. Empty evidence on a new factual/interpretive
    conflict does not create it; a turn with no assertions contributes no
    conflict. Action-only disagreement is tracked (Research Manager can weigh
    it) but never blocks termination. Malformed assertions/state are skipped,
    never guessed.
  - The evaluator node persists the derived conflicts plus a safe, structured,
    prose-free `ConflictSummary` (resolution/escalation notes and an
    authoritative open-blocking count) to debate state; the Research Manager
    injects it safely (empty when no tracked conflict).
  - Verification: `tests/test_debate_conflicts.py` 39 passed; the
    conflict/debate/graph/Stage-2 relevant suite 490 passed (entry 046); full
    offline suite 3 date-sensitive baseline failures unchanged (entry 047);
    Ruff + `git diff --check` + governance validator + governance tests clean
    (entry 048).

## Phase 4A — Deterministic offline baseline comparison (NFR-CMP-*) — review requested

- **Status:** Implemented and verified at the comparison-model, runner, and
  report level; **requires explicit human sign-off**. This is Phase 4A only; no
  Phase 4B, no production threshold tuning, no live-provider run, no commit/push.
- **Reviewer:** Human (project) with coding-agent support.
- **Date:** 2026-10-21
- **Decision:** A pure, LLM-free, network-free comparison model/runner
  (`tradingagents/comparison/`) contrasts the legacy fixed-round baseline with
  the dynamic policy over **identical** scripted case identity
  `(ticker, target_date, evidence_snapshot_id, policy_version)` and identical
  scripted Bull/Bear turns. Any identity mismatch, missing strategy partner, or
  duplicate result fails closed with `PairingError`; comparison metrics are
  derived from explicit formulas with zero-denominator safety; human
  traceability stays `pending` until a human scores it.
- **Notes:**
  - `replay_scripted_case` replays each scenario through the pure
    `evaluate_round` rules; `pair_and_aggregate` fails closed on any unequal
    footing. `_valid_cited_ids` **filters the cited ID union through the
    manifest allowlist** (`is_valid_new_evidence`), so only valid new evidence
    counts toward coverage.
  - Scenario D stops early on `no_new_evidence`; scenario E **extends** the
    debate for a new High/Medium evidence ID; scenario F **genuinely stops on
    `budget_exhausted`** (rule 2), preserving the summary reserve
    (9000 + 8000 <= 20000) and never exceeding the hard cap (the fixed baseline
    spends 27000 > 20000). Verified by the decision trace (`gate_blocked`
    inactive, `budget` active; route=SUMMARIZE, stop_reason=BUDGET_EXHAUSTED).
  - The Markdown report asserts an honest scope disclaimer (offline scripted,
    **not** a live-provider result, no final tuning, traceability pending).
  - Verification: `tests/test_comparison_runner.py` +
    `tests/test_comparison_schemas.py` = **47 passed**; comparison script wrote
    3 scripted cases to `evaluation-output/` (entry 049); scenario-F budget-route
    check (entry 050); governance validator, governance tests, Ruff, and
    `git diff --check` clean (entry 051). Full offline suite recorded
    separately (entry 052) with the pre-existing date-sensitive cache failures.
  - **Reporting-gap fix (independent review, entry 053):** the aggregate/report
    now visibly preserves the estimated-vs-measured usage provenance
    (`CaseAggregate.tool_usage_estimated`, `fixed/dynamic_estimated_cases`) and
    includes tool-call counts (per case + aggregate) in both JSON and Markdown.
    An estimated value is never presented as measured.
  - **Honest status:** the Phase 4A numbers are deterministic **offline scripted
    fixtures**, not live-provider measurements; they cannot support a
    production-grade performance claim. Human traceability is **pending a human
    score**. **No production thresholds were tuned.**

---

# Human Review Decisions — WANG Yiwen

Reviewer record (human decision, not an AI-generated approval).

- **Human reviewer:** WANG Yiwen
- **Student ID:** 60536848
- **Review date:** 2026-10-22

## 1. Stage 2 — Runtime multi-category data-quality gate integration

- **Status:** **Approved with limitations.** Phase-level human sign-off
  recorded; run may proceed but accepts the listed limitations.
- **Reviewer:** WANG Yiwen (Student ID 60536848)
- **Date:** 2026-10-22
- **Decision:** Approved with limitations.
- **Evidence personally reviewed:**
  - 87 focused data-quality gate tests passed.
  - Normal, degraded, and blocked routing were verified.
  - Missing or malformed critical market evidence fails closed.
  - A blocked market gate skips the Bull/Bear debate and routes to the Research
    Manager.
  - Missing optional-category evidence degrades the decision and is not
    fabricated.
  - Structured optional evidence is accepted only through the explicit
    `data_quality_optional_evidence` contract.
  - Future or point-in-time-invalid evidence is rejected.
  - Governance validation, Ruff, and `git diff --check` passed.
- **Accepted limitations:**
  - The current runtime has the structured optional-evidence input contract, but
    the existing analyst prose is not automatically converted into that
    contract.
  - When structured fundamentals, news, or sentiment evidence is absent, those
    categories remain explicitly unavailable and the run degrades.
  - This review covers deterministic offline behavior, not a live data-vendor
    run.

## 2. ConflictRecord runtime lifecycle and dynamic debate termination

- **Status:** **Approved with limitations.** Phase-level human sign-off
  recorded; run may proceed but accepts the listed limitations.
- **Reviewer:** WANG Yiwen (Student ID 60536848)
- **Date:** 2026-10-22
- **Decision:** Approved with limitations.
- **Evidence personally reviewed:**
  - 118 focused debate and conflict tests passed.
  - Scenario D stopped after round 1 with `no_new_evidence`.
  - Scenario E continued for valid new evidence and reached the configured round
    cap.
  - Scenario F stopped after round 1 with `budget_exhausted` while preserving
    the summary reserve.
  - Deterministic conflict creation, stable IDs, deduplication, resolution,
    escalation, malformed-input rejection, future/Low/unknown evidence
    rejection, and action-only non-blocking behavior were verified.
  - The Research Manager receives a structured conflict summary.
  - Governance validation, Ruff, and `git diff --check` passed.
- **Accepted limitations:**
  - The verification uses deterministic offline structured debate turns.
  - A live LLM may omit or produce malformed `DEBATE_METADATA`; the system
    intentionally handles this fail-closed.
  - No live-provider performance benchmark or final production-threshold tuning
    has been performed.

## 3. Phase 4A — Deterministic offline baseline comparison

- **Status:** **Changes requested.** Phase 4A is **not** approved and is **not
  complete**. Do not mark Phase 4A approved or complete.
- **Reviewer:** WANG Yiwen (Student ID 60536848)
- **Date:** 2026-10-22
- **Decision:** Changes requested. Do not mark Phase 4A approved or complete.
- **Evidence personally reviewed:**
  - 47 comparison tests passed.
  - Cases D, E, and F use identical case identity for the fixed and dynamic
    strategies.
  - The generated results are honestly labeled estimated and offline.
  - Dynamic totals were 5 rounds, 10 LLM calls, and 19,500 estimated tokens
    versus 9 rounds, 18 calls, and 41,500 estimated tokens for the fixed
    baseline.
  - The false-strong-conclusion rate remained 0.6667 for both strategies, so no
    conclusion-quality improvement is claimed.
- **Required corrections:**
  - A scored traceability result must require exactly four non-null scores in
    `TRACEABILITY_DIMENSIONS` order.
  - A short scripted input that simply runs out of rounds must not be mislabeled
    as a dynamic policy early stop.
  - The machine-readable and Markdown comparison outputs should preserve the
    actual dynamic stop reason so the decision is auditable.
  - Add regression tests for these corrections.
  - Human traceability scores must remain `pending` until the corrections are
    reviewed.
- **Full-suite status:**
  - 1437 passed, 2 skipped, and 4 known baseline failures remained.
  - Three failures are date-sensitive cache tests.
  - One failure is the existing Yahoo network-reachability/exception-type
    baseline.
  - Do not describe the full suite as completely green.

### Phase 4A — Correction round implemented, pending re-review (2026-10-23)

- **Status:** **Changes requested / corrections implemented / pending human
  re-review.** The Phase 4A decision above stands — Phase 4A is **not** approved
  and is **not** complete. The four required corrections were implemented and
  verified; a human must re-review before any approval may be recorded.
- **Reviewer:** WANG Yiwen (Student ID 60536848) — re-review pending.
- **Date:** 2026-10-23 (correction round)
- **Corrections implemented and verified:**
  - **Strict four-score traceability validation.** A `CaseResult` with
    `traceability_status == SCORED` requires exactly four non-null scores, one
    per `TRACEABILITY_DIMENSIONS` dimension, in `TRACEABILITY_DIMENSIONS` order;
    a missing, extra, null, duplicate, or reordered dimension set fails closed
    (raises) rather than silently mis-reporting a rating
    (`CaseResult.__post_init__`, `traceability_scores_for_dimensions`).
  - **`input_exhausted` distinct from a dynamic early stop.** A short scripted
    input that simply runs out of rounds (no non-`continue` policy decision) is
    recorded as `stop_reason == input_exhausted` and `early_stopped == False`,
    never mislabelled as a dynamic-policy early stop (Scenario G /
    `case_input_exhaustion`).
  - **Actual `stop_reason` preserved.** The real deterministic stop reason is
    preserved in the `CaseResult`, the per-case + aggregate `CaseAggregate`/JSON,
    and the Markdown per-case + aggregate tables
    (`fixed/dynamic_stop_reasons`). `max_rounds_reached` (hard cap) is not an
    early stop; `input_exhausted` is not a policy decision.
  - **Regression coverage.** `tests/test_comparison_schemas.py` and
    `tests/test_comparison_runner.py` extended; **73 focused comparison tests
    pass** (was 47).
- **Verification (this round):**
  - Focused comparison tests: **73 passed in 0.41s**.
  - Governance validator: PASS (34/34 artifacts, no secrets); governance
    scaffold tests: 16 passed; Ruff (full repo): clean; `git diff --check`:
    clean (logbook 054).
  - Full offline suite: **4 failed, 1463 passed, 2 skipped, 22 warnings, 88
    subtests** — all four are the documented pre-existing baselines (3
    date-sensitive cache tests + the network-reachability baseline), **no new
    regression**. Not claimed fully green (logbook 054).
- **Human traceability scores remain `pending`** — no scores were entered.

### Phase 4A — Narrow fail-closed correction (short re-review, 2026-10-23)

- **Status:** **Changes requested / narrow correction implemented / pending human
  re-review.** The Phase 4A decision stands — Phase 4A is **not** approved and is
  **not** complete. A second, narrow correction was implemented and verified; a
  human must re-review before any approval may be recorded.
- **Reviewer:** WANG Yiwen (Student ID 60536848) — re-review pending.
- **Date:** 2026-10-23 (narrow correction round)
- **Correction implemented:** `CaseResult.__post_init__` now **fails closed** on
  a contradictory `strategy` / `early_stopped` / `stop_reason` combination, which
  previously could be constructed and propagated into the aggregate and reports:
  - `StrategyKey.FIXED` must never be `early_stopped == True` (a fixed-round
    baseline is, by construction, never an early stop).
  - `early_stopped == True` is permitted only for `StrategyKey.DYNAMIC` **and**
    only when `stop_reason` is a recognized genuine dynamic early-stop reason
    (reusing the existing `_DYNAMIC_STOP_REASONS` allowlist — no duplicate). A
    `stop_reason` of `""` (empty), `input_exhausted`, `max_rounds_reached`, or
    any unknown reason is rejected when `early_stopped == True`.
  - Because the fix rejects at construction, a contradictory result can never
    reach `compute_case_aggregate` / `pair_and_aggregate` / the report writer, so
    `early_stop_rate` and the "yes"/"no" early-stop label can never render one.
- **Verification (this round, logbook 055):**
  - Focused comparison tests: **90 passed in 0.46s** (was 73), covering direct
    construction, `from_dict`/JSON deserialization, aggregate/report propagation
    (an inconsistent result cannot be accepted or rendered), and that valid
    genuine dynamic early stops and fixed/non-early / input-exhaustion results
    still work.
  - Contradictory examples now fail closed (verified directly): a `FIXED` result
    with `early_stopped=True`, and an early-stopped DYNAMIC result with an empty /
    `input_exhausted` / `max_rounds_reached` / unknown stop reason all raise.
  - Governance validator: PASS (34/34 artifacts, no secrets); governance scaffold
    tests: 16 passed; Ruff (full repo): clean; `git diff --check`: clean.
  - Full offline suite: **3 failed, 1481 passed, 2 skipped, 22 warnings, 88
    subtests** — all three are the documented pre-existing date-sensitive cache
    tests (RISK-001); the network-reachability baseline (RISK-002) did not fail
    on this run (consistent with prior re-runs). **No new regression**. Not
    claimed fully green.
- **Human traceability scores remain `pending`** — no scores were entered.

### Phase 4A — Post-correction human review decision (2026-10-23)

- **Status:** **Approved with limitations.** This is the current Phase 4A
  decision. It **supersedes** the prior **"Changes requested"** decision for the
  purpose of the current phase status; the earlier "Changes requested" decision
  and the intervening correction rounds above are retained verbatim as
  historical audit evidence and are **not deleted**.
- **Reviewer:** WANG Yiwen (Student ID 60536848) — explicit human-authored
  approval.
- **Date:** 2026-10-23
- **Decision:** **Approved with limitations.** The Phase 4A fail-closed
  correction and the short re-review were reviewed and accepted. Phase 4A
  approval is subject to the accepted limitations below; the full offline suite
  is not claimed completely green.
- **Evidence reviewed and accepted:**
  - `CaseResult` now enforces fail-closed consistency among `strategy`,
    `early_stopped`, and `stop_reason`.
  - The `FIXED` strategy cannot set `early_stopped == True`.
  - A dynamic `early_stopped == True` rejects `input_exhausted`,
    `max_rounds_reached`, an empty, and any unknown stop reason, while accepting
    only the existing legitimate dynamic stop reasons.
  - Regression coverage includes direct construction, JSON / `from_dict`
    deserialization, and aggregate/report propagation.
  - 90 focused comparison tests passed.
  - Explicit adversarial checks rejected all contradictory combinations and
    accepted a genuine dynamic `budget_exhausted` early stop.
  - Governance validator passed (34/34 artifacts, no secrets); governance
    scaffold tests passed (16); full-repository Ruff passed; `git diff --check`
    passed.
  - Full offline suite result after the correction: **1481 passed, 2 skipped, 3
    known date-sensitive cache failures, 22 warnings, 88 subtests**. The suite
    is **not completely green**. The previously variable network-reachability
    baseline passed in this run.
- **Accepted limitations:**
  1. Verification is deterministic and offline; it does not include a
     live-provider performance benchmark.
  2. Three known date-sensitive cache failures remain, so the full suite must
     not be described as completely green.
  3. Human traceability scores remain `pending` and must not be invented or
     entered.
  4. Final production threshold tuning has not been performed.
## 2026-11-10 — November 10 repair batch (AI technical; human acceptance PENDING)

**Authorization:** The human explicitly authorized the repair plan and its test
cases (“批准本轮修复计划和测试用例”, 2026-11-10). This is **plan/test
authorization only, NOT acceptance** of the resulting fixes. Final human
acceptance remains pending.

**Scope (F1):** three reproduced defects fixed with failing regression tests
first, on branch `feature/data-quality-debate-control`, base HEAD `8abea81`,
preserving all pre-existing dirty work:
- `output_guard.py` executable multiline / unsupported-format containment,
  including the boundary variants and the two in-progress-review rounds and the
  final F1 blockers (same-line executable sizing/price tail; `**Strong Buy**`).
- `report_artifacts._validation_map` present-`{id: []}` override.
- `validate_requirements.py` shared duplicate-ID uniqueness across both entry
  paths.

**Independent in-progress review rounds (AI/operator, NOT human approval):**
1. Blank physical line between label and value; direction+explanation value;
   split sizing; quoted/negated rationale; long repeated direction-token lines.
2. `Action:` newline `- Buy` / `1. Buy` survival; unsafe blanket keyword/quote
   immunity; discarded `Buy because ...` explanation.
3. Final F1 blockers: `Action: Buy 100 shares at $100 ...` keeping the executable
   tail; `**Strong Buy**` surviving as a directive.

Each round's boundary tests were observed failing before the correction, then
passing. See ADR-005 (PROPOSED), `docs/bug-diary.md`, and logbook 070.

**Verification (offline, deterministic):** `tests/test_output_guard.py` 197
passed; strict fully offline suite (socket disabled) **4 failed / 1743 passed /
1 skipped / 1 deselected** — the same four known baselines
(`test_no_data_handling` empty-download + 3 date-sensitive
`test_ohlcv_cache_freshness`); no new regression; **NOT all-green**. Ruff clean;
governance validator PASS (35/35, no secrets); `git diff --check` clean.

**Decision:** Awaiting independent review and later human acceptance. No human
score, CI enforcement, active permission enforcement, or acceptance is claimed.
F1 feature changes stop here; documentation/traceability consistency is deferred
to the separately approved next batch.

## 2026-11-10 — Documentation/traceability consistency batch (AI technical; human acceptance PENDING)

**Authorization:** the same human-approved repair plan (“批准本轮修复计划和测试用例”,
2026-11-10) — plan/test authorization only, **NOT acceptance**. This is the
second half (docs/traceability), with **no feature rewrites**; the first batch's
guard/report/validator fixes are preserved.

**Scope (D1):**
- `verification-constraints.md`: three tiers Structural/Regression/Behavioral;
  offline-vs-live is a separate evidence axis (not a tier, not live proof).
- ACCURATE `Traceability:` tags added to all 29 mapped test files + deterministic
  governance regressions (`TestMappedTestTraceability`) that resolve tags against
  the registry/invariants and require each requirement's OWN ID; INV-11/12/14
  stay honest.
- `permission-model.md` aligned with `agent-permissions-proposal.yaml` (builder
  edit allowlist; planner execute intent vs expressible deny-all documented as a
  gap). Proposal only; active config/.github/pyproject untouched; enforcement NOT
  claimed.
- Requirements validator: narrow dangling-reference validation on both paths;
  forced-fallback regressions that actually force the fallback (patch
  `_detect_jsonschema`, spy the fallback, real validator raises if reached,
  non-string/malformed IDs); combined entry point documented.
- Validator inventory includes prompt v1.3, ADR-004/005, and the proposals
  (presence/parse only). NFR-OFF-001 uses a count-and-fail harness; one
  intercepted vendor-reachability attempt from the existing
  `test_no_data_handling` baseline is observed, so NFR-OFF-001 stays
  PARTIAL/OPEN (no connection made; baseline/CI/waivers not modified).
  structural-constraints acknowledges src/test pointer dirs; course layout still
  needs human confirmation.

**Verification (offline, deterministic):** validator PASS (42/42, no secrets);
governance 48 passed; mapped+focused 1000 passed; strict-offline count-and-fail
harness 4 failed / 1768 passed / 1 skipped / 1 deselected (same 4 known
baselines) with 1 intercepted attempt (NFR-OFF-001 PARTIAL/OPEN); Ruff clean;
`git diff --check` clean (logbook 071).

**Independent Codex AI verification of the CURRENT files (HISTORICAL /
PRE-REPAIR; logbook 072, NOT human acceptance — superseded by the CURRENT
DISPOSITION at the top and logbook 074):** 14-file focused suite 583 passed / 2
warnings; validator 42/42 PASS + no secret hits; independent boundary 39/39;
440 negative schema mutations rejected; actual `scripts/validate/
strict_offline_harness.py` run 4 failed / 1768 passed / 1 skipped / 1 deselected
with the same 1 intercepted baseline attempt; Ruff clean; `git diff --check`
clean. Earlier in-batch intermediate runs are kept historical; the 583/1768
figures describe the pre-repair tree, not the current one.

**Decision (HISTORICAL / PRE-REPAIR, logbook 071/072):** Awaiting independent
review and later human acceptance. No human
score, CI enforcement, permission enforcement, or acceptance is claimed. All
missing CI/permission enforcement and human scores/team materials stay PENDING;
existing live-budget/claim-date/confidence-cap/optional-adapter/CLI/audit debts
stay OPEN.

## 2026-11-10 — DEBT-021/033 repair (budget accounting + participation truth)

**Scope (implementation present; NOT accepted):** ADR-007 measured-clock budget
accounting, deterministic participation truth, SAFE PARTIAL-DEBATE manager
template, sanitized failure ledger, report/JSON/markdown participation and
per-field usage provenance. No feature beyond the approved plan; no
dependencies/CI/active-permissions/human-rules change; no commit/push/PR.

**Verification (offline + bounded live, AI; NOT human acceptance — PRE-FOLLOWUP
counts; superseded by the CURRENT DISPOSITION / logbook 076):**
Inline implementation focused suite 387 passed. Codex independent re-run of the
then-current frozen PRE-FOLLOWUP tree: 639 focused offline tests passed, 0
forbidden socket attempts, 19/19 external boundary probes; full canonical
`scripts/validate/strict_offline_harness.py` 1817 passed, 4 SAME known baseline
failures (3 date-sensitive OHLCV cache + 1 intercepted baseline network),
1 skipped, 1 deselected, 88 subtests, 1 intercepted baseline socket
attempt (no connection); Ruff/governance 42/42/diff clean; code fingerprint of
214 files unchanged across the live verification (this fingerprint statement
applies to the PRE-FOLLOWUP tree only, not the final post-followup tree).

Bounded real school-model validation COMPLETED (Codex; guarded at 32 requests /
250000 observed tokens / 4096 output-per-call / 120 s per request / 1200 s wall;
25 actual application calls, 228903 reported gateway tokens, 0 retries, no
trades, no threshold tuning). Evidence backup:
`/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-10-school-budget-attribution-lahiq22h/`.
- **D2 (blocked, controlled fixture):** empty critical-market-record fixture at
  the REAL gate boundary + synthetic market analyst report (clearly NOT
  live-vendor data), then REAL school RM/Trader/risk/Portfolio nodes: 6 real
  calls, Gate blocked, zero Bull/Bear invokes, Hold at RM/Trader/Portfolio/
  final/memory, no executable blocked Trader sizing, report bodies agree,
  participation explicitly `data_quality_blocked`; 14/14 checks. This is a
  NARROW controlled-fixture blocked-path proof, not exhaustive/live-vendor
  blocked proof.
- **D1 (degraded, real vendors NVDA 2026-11-05):** Gate degraded, Bull+Bear
  invoked, one complete round, stop `max_rounds_reached` (NOT premature
  `budget_exhausted`); production `debate_usage` 2 calls / 34744 tokens
  (30902 in + 3842 out) / 34.056785748922266 s / estimated false /
  tokens_source provider / seconds_source measured / transport_attempts null
  (honest); independent callback elapsed 14.38+19.67 s and gateway totals match;
  report/state/participation/stop consistency 7/7.
- A first HARNESS-SETUP attempt aborted (`AttributeError` in the synthetic
  analyst message shape) BEFORE ANY model calls (calls=0); the harness was fixed
  and the original artifact retained. It is a harness-setup fault, not a product
  failure or a retry of a failed product call.

**Decision:** The current implementation is technically verified offline and by
the bounded live scenarios, PENDING human acceptance. This is NOT full-suite
green (4 known baseline failures remain) and NOT a claim of final feature
completeness. Remaining limits stay explicit: failed-checkpoint/cross-resume
hard-budget accounting is unsolved; all-agent production usage totals are
untracked in the product (external harness has a full-run meter only); the
degraded confidence cap, optional-category adapters, claim-date semantics and
other open debts remain OPEN. No human score/approval is claimed or invented;
no prior signatures are changed.

## 2026-11-11 — ADR-008 Stage 1 (automatic structured optional-evidence ingestion)

- **Authorization:** WANG Yiwen (60536848) explicitly approved the four-item
  repair plan AND test cases in the controlling conversation, with degraded
  confidence cap 0.60 (2026-11-11). This authorizes the plan/tests ONLY; it is
  NOT a final human acceptance. Stages 2–4 were authorized in principle but only
  **Stage 1** is implemented in this change.
- **What was built (Stage 1 only):** typed run-scoped evidence collector; honest
  vendor-origin adapters (fundamentals/news/sentiment); dataflow capture bridge
  wired into the real default vendor paths (SEC facts + default yfinance/AV
  statements; Yahoo/AV news; StockTwits/Reddit sentiment); durable capture at the
  tool AND analyst boundaries on the production `AgentState`; gate merge into
  manifest/allowlist/report; source-attempt lifecycle (versioned per-run
  `attempt_index`, thread-safe, sanitized, no fabricated attempts, separate
  `not_attempted` metadata); manual-grade clamping; fail-closed per-category
  classifier; lineage-based independence; explicit tombstone pruning on resume.
- **Verification (offline, re-run):** `tests/test_structured_evidence_ingestion.py`
  53 passed; full strict-offline suite 1897 passed, 1 skipped, 1 deselected, 22
  warnings, 88 subtests, 0 forbidden socket attempts; `ruff check .` clean;
  governance validator PASS (43/43); `git diff --check` clean (logbook 079).
- **Decision / status:** Stage 1 is **technically verified offline** and awaits
  **independent reviewer (Codex) verification** and **later explicit human
  acceptance**. No human approval is claimed or invented; no prior signatures are
  changed. Not a remote-CI-green claim (push not authorized). Not a live-vendor
  proof. Stages 2–4 are NOT implemented; residual gaps recorded (DEBT-015,
  DEBT-035; RISK-015).

## 2026-11-11 — Stage 2 (ADR-009) implemented; independent review + human acceptance PENDING

- **Human authorization (in-controlling-plan approval):** WANG Yiwen (60536848)
  explicitly approved ALL FOUR repair items (plan + test cases, degraded
  confidence cap 0.60) on 2026-11-11. This authorizes implementation and is NOT a
  final human acceptance of any item. No reapproval was required to implement the
  items sequentially; only **Stage 2** was implemented in this change.
- **What was built (Stage 2 only):** durable run-scoped SQLite usage ledger
  (`tradingagents/debate/usage_ledger.py`) with reservation-before-call /
  settlement-after and idempotent resume reconciliation; a run-scoped usage
  capture (`usage_capture.py`) with globally unique invocation ids and a unified
  instrumented model call; researcher/summary accounting glue
  (`researcher_accounting.py`); a distinct summary admission
  (`can_afford_summary`) that consumes the reserve without a second optional
  estimate and requires a call slot; atomic full-policy admission inside a
  `BEGIN IMMEDIATE` transaction; reporting-only whole-run usage aggregation across
  all phases (`aggregate_whole_run_usage`) with completeness + reserved-unconfirmed;
  per-side provenance and provider conflict originals preserved; state channels
  `run_id`/`whole_run_usage`/`usage_ledger_path` on the production `AgentState`;
  report + CLI wiring. Stage 1 (ADR-008) dirty work preserved.
- **Verification (offline, re-run):** `tests/test_durable_usage_ledger.py` 33
  passed; `tests/test_whole_run_usage.py` 10 passed; full strict-offline suite
  1940 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden
  socket attempts; `ruff check .` clean; governance validator PASS (43/43);
  `git diff --check` clean (logbook 080).
- **Decision / status:** Stage 2 is **technically verified offline** and awaits
  **independent reviewer (Codex) verification** and **later explicit human
  acceptance**. No human approval is claimed or invented; prior signed decisions
  are preserved unchanged. Not a remote-CI-green claim (push not authorized); not a
  live-provider/live-concurrency proof. Stage 3 (claim date/value/unit) and Stage 4
  (degraded confidence cap 0.60) are NOT implemented. Residual gaps recorded
  (DEBT-021/DEBT-036; RISK-020/RISK-029).

## 2026-11-11 — Stage 3 exact claim date/value/unit validation (ADR-010)

- **Human authorization (controlling-plan approval):** WANG Yiwen (60536848)
  approved ALL FOUR repair items (plan + test cases, degraded confidence cap 0.60)
  on 2026-11-11. This authorizes implementation and the approved test cases; it is
  NOT a final human acceptance of any item. No reapproval was required to implement
  Stage 3 within that plan.
- **What was built (Stage 3 only):** typed origin metadata (`evidence/origin.py`,
  versioned, evidence-ID-keyed, distinct date roles + unit/currency/scale, locked
  fields unchanged); typed exact-claim envelope + conservative parser
  (`debate/models.py`, `debate/turn.py`); pure deterministic `validate_claim`
  (`debate/claims.py`); runtime consumption in the evaluator (no new evidence on a
  wrong claim), conflict lifecycle (no factual conflict on a wrong claim), the
  Research Manager (verified/rejected/unverified summary), and the trusted
  plan/trader/final-decision redaction (no global Hold); report export. Stage 1
  (ADR-008) and Stage 2 (ADR-009) dirty work preserved.
- **Verification (offline, re-run):** `tests/test_exact_claim_validation.py` 47
  passed; `tests/test_exact_claim_runtime.py` 9 passed; full strict-offline suite
  2044 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden
  socket attempts; `ruff check .` clean; governance validator PASS (43/43);
  `git diff --check` clean (logbook 081). Verifier early feedback (malformed scale
  never → 1; reject int/ambiguous dates; timestamp instant comparison) implemented
  and covered.
- **Decision / status:** Stage 3 is **technically verified offline** and awaits
  **independent reviewer (Codex) verification** and **later explicit human
  acceptance**. No human approval is claimed or invented; prior signed decisions are
  preserved unchanged. Not a remote-CI-green claim (push not authorized); not a
  live-provider proof. Only typed exact claims and common inline exact prose are
  validated; arbitrary NL semantics are not claimed proven. Stage 4 (degraded
  confidence cap 0.60, DEBT-014) is NOT started. Residual gaps recorded (DEBT-022;
  RISK-020).

### 2026-11-11 — Stage 3 independent review fixes (same implementation approval; NOT final acceptance)

- **Reviewer findings addressed (code):** (1) an invalid exact claim no longer ERASES an
  open/escalated conflict — the attempted observation/resolve/escalate is rejected and
  the prior record + history are KEPT with an auditable denial (no manufactured
  convergence). (2) A turn supports MULTIPLE typed claims; a valid ID with a correct
  claim cannot launder a second wrong claim or a mismatching co-cited ID (per-claim
  coverage, all-support consistency, no first-claim-wins). (3) `enforce_trusted_boundary`
  now freshly extracts and validates EACH boundary's OWN exact prose (RM, Trader,
  Portfolio, memory, every report section) at clause/assertion granularity against the
  state manifest/origin — not just previously-rejected strings — with empty rejected
  list, per-clause recommendation handling, all assertions per line, and bounded
  multi-line date/value/citation association; raw Bull/Bear transcripts are marked
  NON-AUTHORITATIVE. (4) Dimension semantics for ALL numeric claims (money/shares/
  percent/ratio) require a known matching dimension on both sides; missing unit/scale
  never silently corroborates; `record.value_normalized` is BASE units and the claim
  magnitude is normalized by its own declared scale (base↔millions equivalence both
  ways via the real SEC producer path); explicit multiplier never invents a missing
  record scale; origin/record/requested target must all agree. (5) The default market
  adapter's `native_quote_currency` is genuinely unknown → an exact monetary claim on
  the real default market path is honestly `unverified` (no ticker→USD assumption, no
  approved network call); a separate labelled known-currency fixture and the real SEC
  USD path prove the verification path.
- **Verification (offline, re-run):** `tests/test_exact_claim_validation.py` 73 passed;
  `tests/test_exact_claim_runtime.py` 30 passed; full strict-offline suite 2044 passed,
  1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts;
  `ruff check .` clean; governance validator PASS (43/43); `git diff --check` clean.
- **Status:** still **technically verified offline**; independent Codex review of the
  final tree and explicit human acceptance remain pending. NOT remote-green; NOT live.
  Stage 4 (cap 0.60) NOT started.

### 2026-11-11 — Stage 4 (ADR-011 degraded-run confidence cap 0.60): implementation + offline verification (NOT final acceptance)

- **Scope:** implemented under the WANG Yiwen 2026-11-11 four-item plan + test
  approval (cap 0.60); plan/tests authorization ONLY, not final acceptance. HEAD
  5ecea91 unchanged; Stages 1-3 dirty work preserved. No commit/push.
- **Implemented:** pure `tradingagents/debate/confidence_policy.py`; debate
  turn/stance numeric + readable cap; evaluator; RM/Trader/PM typed numeric (exact
  raw precision, capped BEFORE the lossy 2dp render) + prose; post-gate
  state-input sanitizer (`sanitize_state_inputs` + `with_sanitized_state`) capping
  analyst reports / plans / debate+risk histories AND turn/stance numerics on a
  per-read copy before every post-gate prompt; API and CLI fail-closed resume
  sanitizers (CLI streams `graph.graph.stream` directly); report writer independent
  recompute + merged per-section/per-turn audit into a sanitized artifact copy;
  memory log effective decision.
- **Verification (fresh, offline):** cap tests 110 passed / 0 sockets; full
  strict-offline 2154 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0
  sockets; `ruff check .` clean; governance validator PASS (43/43); `git diff
  --check` clean (logbook 082).
- **Decision / status:** Stage 4 is **technically verified offline** and awaits
  **independent reviewer (Codex) verification** and **later explicit human
  acceptance**. No human approval is claimed or invented. Not a remote-CI-green
  claim (push not authorized); not a live-provider proof. 0.60 is an engineering
  ceiling, not a calibrated probability/accuracy claim nor production threshold
  tuning; `blocked` Hold discipline preserved. Residual gaps: DEBT-014 (awaiting
  human acceptance), DEBT-015 (exchange-holiday calendar, researcher char-estimate
  usage, append-only event types/audit_incomplete fallback), RISK-014.

### 2026-11-11 — Two confirmed live-run defect repairs (Defect-1 origin, Defect-2 structured usage): implementation + offline verification (NOT final acceptance)

- **Scope:** implemented under WANG Yiwen's explicit approval of this round's
  execution plan AND test cases (Chinese: "批准这两项修复计划和测试用例",
  2026-11-11). Plan/test authorization and IMPLEMENTATION approval ONLY — NOT
  final human acceptance. HEAD 5ecea91 unchanged; all dirty Stage 1-4 work
  preserved (no reset/stash/revert). No dependency/CI/permission/human-only-rule
  edits; no secrets; no live/vendor/model calls (any additional product live-model
  budget was explicitly declined after 223,827 tokens).
- **Defect-1 (ADR-010 amendment):** the gate's authoritative origin map is merged
  AFTER ingestion persistence (a collector's empty-for-market origin delta no
  longer overwrites it). Real captured-origin conflicts fail closed via the
  DECLARED `data_quality_origin_conflicted_ids` channel (no first/last-wins, no
  derived re-trust, no resurrection of pruned/tombstoned ids); `origin_records_from_state`
  drops conflicted ids at the single read choke point; conflict seeding is
  unconditional from persisted state (no-collector / direct SQLite resume /
  imported report state safe). Frozen 20/7 record fields unchanged.
- **Defect-2 (ADR-009 amendment):** structured-output calls bind `include_raw=True`
  where supported (same single call); usage settles from the RAW `AIMessage` while
  the parsed typed object is rendered/capped; a binding-only fallback (no extra
  model call) keeps legacy typed providers typed+estimated (no free-text
  downgrade); settlement precedes parse/sanitize/render failures so known raw
  usage is never recorded as unknown; unknown transport stays unknown; `mixed` is
  an AGGREGATE/report-only label (never per-call; not in the durable-ledger
  allowed sources) and never omits known tokens.
- **Verification (fresh, offline):** `tests/test_gate_origin_authority.py` 18
  passed; `tests/test_structured_raw_usage.py` 18 passed; full strict-offline
  2190 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 sockets
  (baseline 2154 + 36); `ruff check .` clean; governance validator PASS (43/43);
  `git diff --check` clean.
- **Decision / status:** both fixes are **technically verified offline** and await
  **independent Codex verification** and **later explicit human acceptance**. The
  prior incomplete 2026-11-11 school-model live run is NOT relabelled as a fixed
  live proof; both fixes remain offline-only until a separately authorized future
  live verification. No human acceptance is claimed or invented. Not a
  remote-CI-green claim (push not authorized).

### 2026-11-11 — Independent Codex technical review of the two live-finding repairs: COMPLETED (NOT human acceptance; NOT a live retest)

- **Scope:** independent AI (Codex) technical verification of the repaired tree for
  the two confirmed live-run defects (Defect-1 origin authority, Defect-2 structured
  raw usage) and the scoped no-resurrection tombstone edge. Documentation-only sync;
  no source/test changes, no product/vendor/model calls, no Git mutations.
- **Independent results (Codex, on this tree):** full strict-offline **2190 passed,
  1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts**;
  focused two new files **36 passed, 0 sockets** (18 origin + 18 structured); Ruff
  clean; governance validator **43/43 PASS** including the likely-secret scan;
  `git diff --check` clean; HEAD remains `5ecea91`; frozen governance/CI/dependency
  files untouched.
- **Independently rerun reproduction (stale-map + state-tombstone):**
  `gate_retrusted=False`, `direct_consumer_retrusted=False` (previously True/True).
- **Logs (Codex):** `/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-11-live-findings-repair-independent-full-offline.log`
  and `.../2026-11-11-live-findings-repair-independent-focused.log`.
- **Status:** independent AI technical review is **COMPLETE** and the earlier
  independent OFFLINE metadata replay remains **OFFLINE only** — neither is a live
  retest nor a relabel of the historical incomplete live run or its stage reviews.
  **Explicit human acceptance and a separately authorized live retest remain
  pending.** No human approval is claimed or invented.

### 2026-11-12 — Two-defect repair (price-boundary + standalone typed claims): IMPLEMENTED + offline-verified (NOT human acceptance; NOT a live retest)

- **Authorization:** human WANG Yiwen approved this round's CORRECTED plan AND test
  cases on 2026-11-12 (implementation approval ONLY, NOT final acceptance), per
  `/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-12-price-claim-repair-plan-only.md`
  (original plan overridden by its Correction 1/2/3). Builder (OpenCode; Codex
  independent verifier). Branch `feature/data-quality-debate-control`, HEAD
  `5ecea91` unchanged; dirty Stage 1–4 work preserved; no commit/push/PR; no
  reset/revert/stash; no dependencies/CI/permissions/prompt/human-only file edits;
  no subagents; no product live LLM/vendor calls.
- **Defect 1 (ADR-011 amendment):** the live Trader/report price corruption
  (`$204.38` → `$204.unknown`) is fixed by structural numeric/sentence boundaries
  (no trailing-period absorption; terminators are boundaries not connectors;
  CRLF soft-wrap still binds; currency/sign/date/path-glued numerics excluded).
  Bare `204.38 confidence` remains invalid/quarantined; genuine forms still cap to
  0.60. `tests/test_confidence_boundary.py` 49 passed.
- **Defect 2 (ADR-010 amendment):** the 8 out-of-marker Bear typed lines are now
  recovered by a shared strict extractor into the same date/value/unit/origin
  validation (never trusted; wrong/unknown/future/Low/foreign rejected); fenced
  (incl. unclosed) and quoted examples are never admitted; `role`/`date_role`
  contradictions are unparseable; additive honest coverage is serialized in
  `DebateTurn`/`claim_validation_summary`/`debate_trace.json`, consumed at
  `enforce_trusted_boundary`, and survives a real SQLite resume; frozen
  EvidenceRecord(20)/SourceAttempt(7) unchanged. `tests/test_standalone_claims.py`
  40 passed.
- **Verification (offline):** focused new files 89 passed; related regressions 376
  and broader debate/report/guard/memory/researcher suite 425 passed; full
  strict-offline **2279 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests,
  0 forbidden socket attempts**; Ruff (changed source) clean; governance validator
  **43/43 PASS**; YAML/JSON parse OK; `git diff --check` clean.
- **Status:** IMPLEMENTED and technically verified offline; awaiting **independent
  Codex review** and **later explicit human acceptance**. The preserved 2026-11-11
  live evidence is unchanged and is NOT relabelled as post-fix live proof. No human
  acceptance is claimed or invented.

### 2026-11-12 — Two-defect repair FINAL (post verifier feedback): offline-verified (NOT human acceptance; NOT a live retest)

Independent verifier feedback (within the approved shared-contract/quoted/fence
scope) was incorporated on the final tree: CRLF soft-wrap + date/sign/path
preservation (ADR-011); a single shared strict typed-claim grammar for canonical
AND standalone claims; a single whole-document fence/quote-aware walk used by the
turn parser and the trusted output boundary; opener-length fence matching (shorter
fence never closes a longer one); a narrow explicit `Example:` block exclusion;
no-manifest boundary redaction of explicit typed lines (ordinary prose no-op); and
real Trader-node + `record_decision`/memory tests plus a resumed-evaluator
coverage/verified assertion and malformed/rejected not-stored checks.

- **Final counts:** `tests/test_confidence_boundary.py` 51 + `tests/test_standalone_claims.py`
  49 = 100; related regressions 755 passed; full strict-offline **2290 passed, 1
  skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts**;
  Ruff clean; governance 43/43 PASS; YAML/JSON OK; `git diff --check` clean.
- **Status:** IMPLEMENTED + offline-verified; awaits independent Codex review and
  later explicit human acceptance. Not a live retest; preserved 2026-11-11 live
  evidence unchanged and not relabelled. Branch `feature/data-quality-debate-control`,
  HEAD `5ecea91` unchanged; no commit/push/PR.

### 2026-11-12 — Independent Codex technical review of the two-defect repair: COMPLETE (NOT human acceptance; NOT a live retest)

Independent AI (Codex) technical verification of the final repair tree is complete.
Documentation-only sync; no source/test changes, no product/vendor/model calls, no
Git mutations.

- **Independent results:** full strict-offline **2290 passed, 1 skipped, 1
  deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts**; Ruff clean;
  governance validator **43/43 PASS** including the artifact likely-secret scan;
  `git diff --check` clean; frozen governance/CI/dependency paths unchanged; HEAD
  `5ecea91` unchanged.
- **Independent OFFLINE replay of the actual prior-school Bear text** (no new
  product calls): all 8 claims now recovered — **1 verified (volume), 5 rejected
  (unknown optional evidence), 2 unverified (price currency/unit genuinely
  unknown)**. This is honest, non-empty validation; it is **NOT** all-8-verified
  and does not assert the optional-evidence records are valid.
- Independently confirmed: the exact historical price case (`$204.38.` byte-for-
  byte, no quarantine); LF and CRLF suffix soft-wraps; date/currency/sign/path
  preservation; invalid bare `204.38 confidence` still quarantined; long/unclosed
  fences and explicit `Example:` blocks excluded; conflicting canonical/outside
  `role`/`date_role` aliases unparseable.
- Independently confirmed at REAL boundaries: the ACTUAL `create_trader`, report
  writer, and production `record_decision`/`TradingMemoryLog` **with the real
  `_is_blocked_state` (no method override)** preserved `$204.38.` and capped a
  genuine `0.95`; a rejected wrong-volume claim was **not** stored in memory.
- **Saved evidence:** `/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-12-price-claim-independent-replay.json`
  and directory `.../2026-11-12-price-claim-independent-mnca0llp`; full log
  `.../2026-11-12-price-claim-independent-full-offline.log`.
- **Status:** independent AI technical review is **COMPLETE**; **explicit human
  acceptance remains pending.** The old real live run remains **historical bug
  evidence only** and is **NEVER** relabelled as post-fix live proof. No human
  approval is claimed or invented.

### 2026-11-12 — Verified-span repair (residual false-redaction): IMPLEMENTED + offline-verified (NOT human acceptance; NOT a live rerun)

- **Authorization:** human WANG Yiwen approved this round's plan AND test cases on
  2026-11-12 (implementation approval ONLY). Builder (OpenCode); Codex independent
  verifier. Branch `feature/data-quality-debate-control`, HEAD `5ecea91` unchanged;
  no commit/push/PR; no frozen/config/dependency/schema edits; no live calls.
- **Defect:** a CORRECT long-decimal typed claim (`value=306127800.0000000000`,
  `unit=shares`) that strictly VALIDATED as verified was then re-redacted by the
  generic prose scanner (24-char nearest-unit window) — evidence loss, not bad-claim
  acceptance. Historical bug evidence from the 2026-11-12 school run; no rerun.
- **Fix:** occurrence-exact PER-TOKEN authority of a verified typed ClaimRecord's own
  `date=`/`value=` token spans (both prose passes; a verified token is never erased
  and an unauthorized span is always blanked independent of heuristic pairing, with
  the unprotected partner still checked/redacted);
  one shared fence/Example walk for standalone + canonical; no window enlargement,
  no whole-line skip, no grammar widening; unparseable mixed line fails closed.
  Mid-review corrections: occurrence-exact (not whole-line first match) so a later
  verified sibling cannot authorize an earlier rejected one (mixed same-ID both
  orders tested); canonical uses the shared fence/Example/blockquote exclusion walk
  (fenced/Example/quoted canonical not protected; direct zero-occurrence assertions);
  equivalent numeric forms and SUPPORTED format variants (uppercase `DATE=`/`VALUE=`,
  spaced `date = ...`, canonical backticked `claim=`) protected via raw-segment
  offsets using the strict parser's `key.strip().lower()` (no grammar expansion);
  memory tests use the real `_is_blocked_state`.
- **Verification:** `tests/test_verified_span_boundary.py` 77 passed; related
  regressions 716 passed; full strict-offline **2367 passed, 1 skipped, 1 deselected,
  22 warnings, 88 subtests, 0 socket attempts**; Ruff clean; governance 43/43 PASS;
  YAML/JSON OK; `git diff --check` clean.
- **Status:** IMPLEMENTED + offline-verified; awaits independent Codex review and
  later explicit human acceptance. Prior 26-call / 202,941-token run remains
  historical bug evidence, not post-fix live proof.

### 2026-11-12 — Independent Codex FINAL technical review of the verified-span repair: COMPLETE (NOT human acceptance; NOT a live rerun)

- **Scope:** independent AI (Codex) technical review of the repaired verified-span
  source/test hashes on covered OFFLINE scope. Documentation/comment sync only; no
  behaviour/test change; no new product live call; no Git mutation.
- **Independent results (supplied):** full strict-offline **2367 passed, 1 skipped
  (optional `langchain_aws` absent), 1 deselected, 22 warnings, 88 subtests, 0
  socket attempts**; focused specified **8 modules = 556 passed / 0 sockets** (a
  DIFFERENT subset from the builder's 716 related suite — counts not conflated);
  `ruff check .` clean; governance **43/43 PASS**; `git diff --check` clean.
- **Independent exhaustive format check:** **4320 cases** (720 field orders × 6
  formats, including duplicate canonical) all preserved correctly / 0 sockets.
- **Independent replay of the SAVED real school response:** `long-value-independent-replay.json`
  has **19 TOTAL checks INCLUDING the 5 equivalent numeric variants, all 19 true**
  (not a separate 17+5 split) / 0 sockets. Real `write_report_tree` (trader +
  complete) and real `record_decision`/`TradingMemoryLog` preserve the correct long
  typed line while future-dated and unknown-ID claims are removed.
- **Evidence saved (outside repo):** `long-value-independent-full-offline.log`,
  `long-value-independent-focused.log`, `long-value-format-results.json`,
  `long-value-independent-replay.json`; actual report/memory artifacts under
  `2026-11-12-long-value-independent-fsd_ad80/`.
- **Authority semantics correction recorded:** final protection is PER VERIFIED TOKEN
  OCCURRENCE, not heuristic date↔value pair membership; an unprotected partner is
  still checked/redacted; no whole-line bypass. Stale source/doc/test comments that
  described "exempt only when date+value belong to ONE pair" were corrected.
- **Status:** independent technical review **COMPLETE**; **explicit human final
  acceptance and any post-fix live retest remain PENDING.** The prior 26-call /
  202,941-token school run remains historical bug evidence only and is NOT relabelled
  as post-fix live proof. This record is independent technical review, NOT AI/human
  approval.
