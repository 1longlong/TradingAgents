# Evaluation Table — Verification Summary

This is a concise table summarizing verification. It relies on
`docs/architecture/evaluation-logbook.md` for the exact commands and outcomes.
`Re-run` means executed in the current environment; `Supplied` means the outcome
was provided to this task and was not re-run here.

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
  `docs/architecture/evaluation-logbook.md` (entries 035-039, 051, 054, 056).