# Evaluation Table — Verification Summary

This document has two parts. **Part I** is the architecture-candidate comparison
(why this architecture was chosen against alternatives and drivers). **Part II**
is the verification-results table. Verification relies on
`docs/architecture/evaluation-logbook.md` for the exact commands and outcomes.
`Re-run` means executed in the current environment; `Supplied` means the outcome
was provided to this task and was not re-run here.

## Part I — Architecture candidate comparison

The selected architecture is described in `architecture-blueprint.md` (two
deterministic components: a Data Quality Gate and an evidence-aware debate
terminator). This comparison evaluates main candidates against the project's
drivers. **No fabricated numeric scores are used**: each cell is a qualitative
judgement tied to a driver, and measured performance is not claimed.

Drivers (D1–D7):

- **D1 Determinism** — same input → same output; offline-verifiable.
- **D2 Fail-closed safety** — missing/error cannot look like a clean normal run.
- **D3 Backward compatibility** — disabled feature reproduces legacy routing.
- **D4 Auditability** — reason codes, policy version, evidence IDs, trace.
- **D5 Budget safety** — never lose the summary report mid-debate.
- **D6 Testability/effort** — provable with offline deterministic tests.
- **D7 Point-in-time integrity** — no look-ahead leakage.

| Candidate | D1 Determinism | D2 Fail-closed | D3 Backward-compat | D4 Auditability | D5 Budget | D6 Effort | D7 PIT | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A. Deterministic gate + rule-based termination (selected)** | Inherent (pure) | Native (exception→blocked) | `enabled=False` retains legacy | Full trace, stable codes | Explicit reserve + pre-call guard | Offline-testable | As-of boundary preserved | **Selected** |
| B. LLM-judged gate / termination | Poor (nondeterministic) | Cannot guarantee | Risky default change | Opaque reasoning | Unbounded cost risk | Cannot regression-test offline | No new risk to PIT | Rejected (violates D1/D2/D4/D6) |
| C. Fixed-round with no gate | Native | No gate → no fail-closed on data quality | N/A (baseline) | Limited (no gate trace) | No reserve → can lose report | Simple | PIT preserved by upstream | Rejected (fails D2/D5; this is the DQG/Dynamic baseline) |
| D. Best-effort accounting, wall-clock only | Native | Partial | Compatible | Partial | Can overspend one call | Testable | Unchanged | Rejected (fails D5 guarantee) |
| E. Relocate code into `src/` to match slide layout | N/A | N/A | Breaks users | N/A | N/A | High (drift risk) | N/A | Rejected (out of scope; mapping retained as exception) |

Selection rationale: Candidate A is the only one that satisfies the determinism,
fail-closed, auditability, and budget guarantees simultaneously while remaining
offline-testable and backward-compatible. The measured evidence for A is the
offline test suite (Part II); **no live-performance advantage is claimed** — the
Phase 4A comparison is scripted fixtures, not a live benchmark.

Known weaknesses of A (honest, not hidden): (i) budget is enforced against
*estimated* usage, and the 2026-11-06 live run showed the estimate exhausted the
time budget before Bear (`DEBT-021`); (ii) an allowlist does not validate a
claim's date semantics (`DEBT-022`); (iii) automatic optional-category adapters
are limited (`DEBT-015`). These are open defects in an otherwise sound
architecture, not reasons to pick B/C/D/E.

## Part II — Verification results

| Area | Command / scope | Result (observed) | Source | Status |
| --- | --- | --- | --- | --- |
| ConflictRecord runtime lifecycle | `pytest tests/test_debate_conflicts.py` | 39 passed in 0.53s | Re-run | Pass (expected) |
| Conflict/debate/graph/Stage-2 relevant suite | `pytest` on gate + debate + evidence + conflicts + stage2 multi-category gate + report artifacts + governance tests | 490 passed in 1.82s | Re-run | Pass (expected) |
| Debate-focused subset | `pytest` on gate + debate + evidence tests | 333 passed in 1.00s | Re-run | Pass (expected) |
| Stage-2 relevant suite | `pytest` on gate + debate + evidence + stage2 multi-category gate + report artifacts + governance tests | 442 passed in 1.99s | Re-run | Pass (expected) |
| Stage 2 multi-category gate | `pytest tests/test_stage2_multicategory_gate.py` | 26 passed | Re-run | Pass (expected) |
| Stage 2 report artifacts | `pytest tests/test_report_artifacts_stage2.py` | 16 passed | Re-run | Pass (expected) |
| OpenCode-related suite | `pytest` (OpenCode-derived scope) | 420 passed | Supplied | Pass (expected) |
| Full offline suite (sandbox) | `pytest -q` | 1275 passed, 1 skipped, 1 deselected, 88 subtests; 3 date-sensitive failures, 1 network-reachability baseline failure | Supplied | Partial |
| Full offline suite (current tree) | `pytest -q` | 1391 passed, 2 skipped, 88 subtests; 3 failed (date-sensitive cache tests) | Re-run | Partial |
| Full offline suite (current tree, Phase 4A) | `pytest tests/ -q` | 1432 passed, 2 skipped, 88 subtests; 3 failed (date-sensitive cache tests) | Re-run | Partial |
| Full offline suite (current tree, prior) | `pytest -q` | 1342 passed, 2 skipped, 88 subtests; 4 failed (3 date-sensitive cache tests, 1 network-reachability baseline) | Re-run | Partial |
| Full offline suite (earlier OpenCode env) | `pytest -q` | 1276 passed; 3 date-sensitive failures | Supplied | Partial |
| PIT / look-ahead tests | point-in-time focused tests | Pass within offline suite; re-run date-sensitive | Re-run / Supplied | Partial |
| Doc/schema validation | `scripts/validate/validate_requirements.py` | 34/34 artifacts present; JSON/JSONC/YAML parse OK; requirements pass the REAL draft-2020-12 schema (jsonschema); no secrets | Re-run | Pass |
| Governance unit tests | `pytest tests/test_governance_scaffold.py` | 16 passed | Re-run | Pass |
| Ruff lint | `ruff check .` | All checks passed (full repo) | Re-run | Pass |
| Diff whitespace | `git diff --check` | No whitespace errors (tracked + intent-to-add) | Re-run | Pass |
| CI workflow structure | YAML parse of `.github/workflows/ci.yml` | Parses OK; governance job installs jsonschema + PyYAML and enforces the real schema offline | Re-run | Pass |
| Phase 4A comparison unit tests | `pytest tests/test_comparison_runner.py tests/test_comparison_schemas.py` | 47 passed in 0.40s (17 runner + 30 schemas) | Re-run | Pass (expected) |
| Phase 4A correction round (focused comparison tests) | `pytest tests/test_comparison_runner.py tests/test_comparison_schemas.py` | 73 passed in 0.41s (was 47; strict four-score traceability, input_exhaustion-not-an-early-stop, stop-reason preservation, regression coverage) | Re-run | Pass (expected) |
| Phase 4A correction round (final verification) | `validate_requirements.py` + `pytest tests/test_governance_scaffold.py` + `ruff check .` + `git diff --check` | validator PASS (34/34, no secrets); governance 16 passed; Ruff clean (full repo); diff-check clean | Re-run | Pass (expected) |
| Full offline suite (current tree, Phase 4A correction round) | `pytest tests/ -q` | 1463 passed, 2 skipped, 22 warnings, 88 subtests; 4 failed (3 date-sensitive cache tests + 1 network-reachability baseline) — pre-existing, NO new regression | Re-run | Partial |
| Phase 4A comparison script | `python scripts/run_phase4a_comparison.py` | 3 scripted cases written to `evaluation-output/` (comparison_results.json + comparison_report.md) | Re-run | Pass (expected) |
| Phase 4A reporting-gap fix (independent review) | `pytest` comparison tests + comparison script + governance validator + governance tests + `ruff check .` + `git diff --check` | 47 comparison tests passed; script wrote 3 cases; validator PASS; governance 16 passed; Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Phase 4A scenario F budget route | `evaluate_round(...)` on `case_budget_protection()` | route=SUMMARIZE, stop_reason=BUDGET_EXHAUSTED; reserve preserved (9000+8000 <= 20000; fixed spends 27000 > 20000) | Re-run | Pass (expected) |
| Phase 4A governance | `validate_requirements.py` + `pytest tests/test_governance_scaffold.py` + `ruff check` + `git diff --check` | PASS; 16 passed; ruff clean; diff-check clean | Re-run | Pass (expected) |
| Phase 4A narrow fail-closed correction (focused comparison tests) | `pytest tests/test_comparison_runner.py tests/test_comparison_schemas.py` | 90 passed in 0.46s (was 73; fail-closed strategy/early_stopped/stop_reason consistency via `_DYNAMIC_STOP_REASONS`) | Re-run | Pass (expected) |
| Phase 4A narrow fail-closed correction (governance + verification) | `validate_requirements.py` + `pytest tests/test_governance_scaffold.py` + `ruff check .` + `git diff --check` | validator PASS (34/34, no secrets); governance 16 passed; Ruff clean (full repo); diff-check clean | Re-run | Pass (expected) |
| Full offline suite (current tree, Phase 4A narrow fail-closed correction) | `pytest tests/ -q` | 1481 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (date-sensitive cache tests, RISK-001; network baseline RISK-002 did not fail this run) — pre-existing, NO new regression | Re-run | Partial |
| Phase 4A human review decision (post-correction) | human review recorded in `docs/review-memo.md` (WANG Yiwen 60536848, 2026-10-23) | Approved with limitations; subject to the four recorded limitations (offline only, cache baselines remain, traceability pending, no production threshold tuning). Full suite not claimed green. | Re-run | Approved with limitations |
| Blocked final-output guard (review finding 1) | `pytest tests/test_output_guard.py` | 47 passed in 0.48s (structured + free-text, full graph with real blocked gate, missing/malformed gate state, normal/degraded preserved, report + final signal, legacy normal checkpoint) | Re-run | Pass (expected) |
| Blocked final-output guard (affected suite) | `pytest` gate + debate + report + structured + rating + PM + output-guard tests | 294 passed in 1.67s | Re-run | Pass (expected) |
| Blocked final-output guard (independent review demo) | `tradingagents_offline_demo.py` | `final_signal` = Hold (was Buy); manager recommendation still Hold | Re-run | Pass (expected) |
| Full offline suite (current tree, blocked final-output guard) | `pytest -q -p no:cacheprovider` | 1528 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (known date-sensitive cache tests, RISK-001) — pre-existing, NO new regression | Re-run | Partial |
| Blocked final-output guard (governance) | `validate_requirements.py` + `ruff check` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |

## Interpretation

- The **Conflict/debate/graph/Stage-2 relevant suite is clean (490 passed,
  offline)**, including the deterministic ConflictRecord runtime lifecycle
  (`tests/test_debate_conflicts.py`: 39 passed). This is the strongest claim
  this scaffold makes.
- **Phase 4A correction round** (human review) implemented and verified: 73
  focused comparison tests passed; the actual dynamic stop reason is preserved
  in results, JSON/aggregates, and Markdown; a scripted input that runs out of
  rounds is `input_exhausted` (never a dynamic early stop); a `SCORED`
  traceability result requires exactly four non-null scores in
  `TRACEABILITY_DIMENSIONS` order.
- **Phase 4A narrow fail-closed correction** (short re-review) implemented and
  verified: `CaseResult.__post_init__` rejects a contradictory
  `strategy`/`early_stopped`/`stop_reason` combination — a `FIXED` result is
  never early-stopped, and an `early_stopped == True` dynamic result must carry
  a genuine `_DYNAMIC_STOP_REASONS` reason (empty / `input_exhausted` /
  `max_rounds_reached` / unknown are rejected). 90 focused comparison tests
  passed (was 73); the aggregate/report can no longer accept or render an
  inconsistent result.
- **Phase 4A human review decision (post-correction): Approved with
  limitations** (entry 056, `docs/review-memo.md`, WANG Yiwen 60536848,
  2026-10-23). This supersedes the prior "Changes requested" decision for the
  current status (the prior decision and correction-round records are retained
  as historical audit evidence). Human traceability scores remain `pending`, and
  the full offline suite is not claimed completely green.
- The **full offline suite is not claimed fully green** because of the known
  date-sensitive cache failures and the network-reachability-dependent baseline
  failure. The narrow-correction re-run (logbook 055) shows **1481 passed, 2
  skipped, 3 known date-sensitive baseline failures** (the network baseline did
  not fail on this run) with no new regression. They are recorded, not hidden.
- Doc/schema validation outcomes are recorded above and in
  `docs/architecture/evaluation-logbook.md` (entries 035-039, 051, 054, 056).| Guard edge cases (operator review) | `pytest tests/test_output_guard.py` | 55 passed (was 47; compatibility marker without header, repeated headers, markup tolerance, blocked sizing, idempotence) | Re-run | Pass (expected) |
| Guard edge cases (affected suite) | `pytest` output-guard + hold-contract + structured + memory-log | 184 passed | Re-run | Pass (expected) |
| Pre-call budget guards (review finding 2) | `pytest tests/test_debate_precall_budget.py` | 14 passed (max_calls=1 runs exactly one call; zero capacity refused; disabled compatibility; reserve preserved; incomplete-round skip) | Re-run | Pass (expected) |
| Pre-call budget (debate suite) | `pytest` pre-call + budget + graph + evaluator + config + turn + manifest + opening | 171 passed | Re-run | Pass (expected) |
| Audit exports (review finding 3) | `pytest tests/test_report_artifacts_audit.py` | 12 passed (per-evidence association, separate map, legacy empty, redaction, identity/quality/usage provenance, deterministic roundtrip) | Re-run | Pass (expected) |
| Full offline suite (current tree, maintenance corrections) | `pytest -q -p no:cacheprovider` | 1562 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (known date-sensitive cache tests, RISK-001) — pre-existing, NO new regression | Re-run | Partial |
| Maintenance corrections (governance) | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Second review — budget reserve+estimate boundary | `pytest tests/test_debate_precall_budget.py` | 22 passed (reserve-only refusal; reserve+estimate token & second exact boundaries; before-first-Bull and before-Bear graph boundaries; estimate_basis/scope tracing) | Re-run | Pass (expected) |
| Second review — audit compatibility | `pytest tests/test_report_artifacts_audit.py` | 20 passed (legacy embedded-only preserved; authoritative map overrides; shuffled-map determinism; ambiguous identity flagged; snapshot_id null by default) | Re-run | Pass (expected) |
| Full offline suite (current tree, second review) | `pytest -q -p no:cacheprovider` | 1578 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (known date-sensitive cache tests, RISK-001) — pre-existing, NO new regression | Re-run | Partial |
| Second review (governance) | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Stricter fully offline suite (operator/AI technical verification, socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError('Network disabled for offline verification')` | 1577 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (3 date-sensitive cache tests + known Yahoo reachability/exception-type baseline) — pre-existing, NO new regression; recorded separately from the 3-failure run, neither claimed all-green | Supplied (operator-verified) | Partial |
| Operator/AI technical verification summary | 464 focused tests + offline demo + Ruff + governance validator + `git diff --check` | 464 focused passed in 1.82s; demo `final_signal=Hold`, `max_calls=1` -> 1 debate call, validation counts [7,7,7,7,6]; validator PASS (35/35, no secrets); Ruff clean; diff-check clean. Technical verification only, NOT a human approval. | Supplied (operator-verified) | Pass (technical) |
| Recheck 2026-11-06 — finding 1/3 (output guard) | `pytest tests/test_output_guard.py` | 90 passed (fullwidth colon/labels/values, arbitrarily prefixed labels, unicode dashes, repeated/trailing alternative headers, separator preservation, idempotence, shared parser canonicalisation, complete-graph report+memory tag/body consistency, signal-boundary gate awareness) | Re-run | Pass (expected) |
| Recheck 2026-11-06 — finding 2 (real gate->debate) | `pytest tests/test_gate_debate_integration.py` | 9 passed (real gate node -> per-record Medium/High; manifest/allowlist valid IDs; report quality_counts Medium; cited+linked real ID counts as new; Low/Blocked/future do not) | Re-run | Pass (expected) |
| Recheck 2026-11-06 — focused affected suite | `pytest` output-guard + integration + gate graph + debate + manifest + evaluator + turn + verdict gate + memory + signal + rating + audit + reporting + pre-call | 480 passed | Re-run | Pass (expected) |
| Recheck 2026-11-06 — strict fully offline suite (socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError(...)` | 1621 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (same 3 date-sensitive cache tests + known Yahoo reachability baseline) — pre-existing, NO new regression; not claimed all-green | Re-run | Partial |
| Recheck 2026-11-06 — governance | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Operator executable-instruction maintenance 2026-11-06 (output guard) | `pytest tests/test_output_guard.py` | 130 passed (fullwidth label/value + sizing separators, arbitrary/long prefixes, repeated/trailing labels, proposal `BUY because ...`, Markdown wrapping, rationale/recovery/quoted-alternative preservation, idempotence, long-line performance, full blocked graph stored plans + saved report) | Re-run | Pass (expected) |
| Operator executable-instruction maintenance 2026-11-06 (focused affected suite) | `pytest` output-guard + integration + gate graph + debate + manifest + evaluator + turn + verdict gate + memory + signal + rating + audit + stage2 + pre-call + structured + hold-contract + cli-decision-log | 520 passed | Re-run | Pass (expected) |
| Operator executable-instruction maintenance 2026-11-06 (strict fully offline suite, socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError(...)` | 1661 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (same 3 date-sensitive cache tests + known Yahoo reachability baseline) — pre-existing, NO new regression; not claimed all-green | Re-run | Partial |
| Operator executable-instruction maintenance 2026-11-06 (governance) | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Documentation/requirements revision 2026-11-06 (schema + PRD + register + prompt v1.3) | `validate_requirements.py` + `pytest tests/test_governance_scaffold.py` + Draft202012 negative-mutation probes + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); governance 16 passed; 0 baseline schema errors and all negative mutations rejected; Ruff clean; diff-check clean | Re-run | Pass (expected; doc-only, awaits human review) |
| Independent operator recheck 2026-11-06 (docs revision) | `verify_governance_docs.py` + `pytest tests/test_governance_scaffold.py` + strict socket-disabled suite | 22/22 real-schema positive; 440 mutations rejected; all new YAML parse; 22 trace monitor rows; governance 16 passed; strict offline 4 failed / 1661 passed / 1 skipped / 1 deselected (same 4 known baselines, not green) | Supplied (operator-verified) + Re-run | Partial (technical; known baselines remain) |
| November 10 repair batch — defect 1 output guard multiline containment | `pytest tests/test_output_guard.py` | 219 passed across guard+audit+governance at first review; re-run after the second in-progress review: guard suite 197 passed, guard+audit+governance incl. 24 multiline + 14 boundary + 15 second-review boundary (bulleted/numbered `- Buy`/`1. Buy` direct + fake-Trader, live command with `earlier`/quote keyword still contained, structural quoted/negated rationale preserved, direction+explanation tail kept, split sizing, long repeated direction-token linear time, LF/CRLF/fullwidth/Markdown, full blocked graph/report/memory) | Re-run | Pass (expected; 4 known baselines remain; awaits human acceptance) |
| November 10 repair batch — defect 2 empty-map override | `pytest tests/test_report_artifacts_audit.py` | present `{id: []}` overrides stale embedded passed checks; absent keeps legacy fallback; nonempty override, no cross-ID leak, deterministic order, redaction, helper + saved artifact | Re-run | Pass (expected) |
| November 10 repair batch — defect 3 shared ID uniqueness | `pytest tests/test_governance_scaffold.py` | real-jsonschema + forced-fallback both reject duplicate IDs with differing objects; valid 22-ID registry passes; malformed rows no crash | Re-run | Pass (expected) |
| November 10 repair batch — strict fully offline suite (socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError(...)` | 1743 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (same 3 date-sensitive cache tests + known no-data/Yahoo-reachability baseline) — pre-existing, NO new regression; not claimed all-green | Re-run | Partial |
| November 10 repair batch — governance | `validate_requirements.py` + `ruff check` (changed files) + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| November 10 doc/traceability consistency batch — governance/traceability | `validate_requirements.py` + `pytest tests/test_governance_scaffold.py` + mapped 29-file suite + strict-offline count-and-fail harness + `ruff check` + `git diff --check` | validator PASS (42/42, no secrets); governance 48 passed; mapped+focused 1000 passed; strict-offline 4 failed / 1768 passed / 1 skipped / 1 deselected (same 4 known baselines) with 1 intercepted vendor-reachability attempt (NFR-OFF-001 PARTIAL/OPEN, no connection made); Ruff clean; diff-check clean | Re-run | Partial (technical; 4 known baselines + 1 intercepted attempt remain; awaits human acceptance) |
| November 10 doc/traceability batch — independent Codex AI verification (current final) | 14-file focused suite + validator + boundary + 440 schema mutations + strict-offline harness + Ruff + diff-check | 14-file focused 583 passed / 2 warnings; validator 42/42 PASS + no secret hits; boundary 39/39; 440 negative schema mutations rejected; strict-offline 4 failed / 1768 passed / 1 skipped / 1 deselected / 22 warnings / 88 subtests with 1 intercepted vendor-reachability attempt (NFR-OFF-001 PARTIAL/OPEN, no connection made); Ruff clean; diff-check clean | Supplied (independent Codex AI) | Partial (technical; 4 known baselines + 1 intercepted attempt remain; NOT human acceptance) |
| November 10 school-model live end-to-end run (NVDA 2026-11-05, recorded by Codex; documentation-only record) | existing `live_school_verification.py`; endpoint llm.cs.cityu.edu.hk CS5351/DeepSeek-V4-Flash; full existing graph | 16 app model calls, gateway total 170,665 tokens, 0 truncations; final+textual signal Overweight; Gate DEGRADED (not blocked) so `blocked_signal_is_hold=true` is VACUOUS not live blocked proof; 5 market evidence records / 5 validation IDs all matching the authoritative map; Medium count 5; stop_reason preserved; usage total_run null / debate-only estimated 1 call / 15183 tokens / 2024.4 s. DEBT-021 confirmed OPEN: Bull actual 19.70 s / 16,931 tokens vs estimated 2,024.4 s / 15,183; Bear node visited but 0 actual Bear calls, bear_history empty, budget_exhausted (faulty estimate, actual runtime NOT > 600 s). Optional categories still unavailable_no_structured_source (DEBT-015/RISK-015, NOT fixed). Supplemental existing offline boundary 39/39 passed (OFFLINE only). | Supplied (Codex external live verification; docs-only record — NOT re-run here, NOT human acceptance) | Partial (live DEGRADED, 0 complete rounds; DEBT-021 + optional adapters OPEN; blocked/normal live paths not exercised; final acceptance PENDING) |
