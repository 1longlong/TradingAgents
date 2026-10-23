# Verification and Blocking Constraints

## 1. Prior tests and human gates

Humans must approve the iteration plan and test strategy before product implementation. Test files written first must also receive review before product implementation begins. Record the reviewer, time, plan/test version or commit, and scope. Reference the existing `docs/review-memo.md` or corresponding `transcripts/` session location; do not add an approval directory.

Only humans issue approval decisions. Changes to approved requirements, interfaces, safety boundaries, or test standards require a revision and approval of the affected scope. Do not request the same valid approval again.

## 2. Three verification tiers

| Tier | Required checks | Decision |
| --- | --- | --- |
| Structural | Installation/imports, source layout, dependencies, public interfaces, permissions, architecture fitness, lint, types, and dependency checks | Block structural or permission violations |
| Regression | Current and all previous suites; CLI, Python API, and packaging compatibility | Require all checks to pass; any regression blocks |
| Behavioral | Requirement acceptance metrics, invariants, negative inputs, failure handling, and fixed-set quality thresholds when models are involved | Meet approved thresholds; safety violations must be zero |

Verify may run approved checks and report results, but must not alter implementation, remove assertions, relax thresholds, or convert failures into skip/xfail. Return findings to Build and verify the repair.

## 3. Test design and isolation

- Each `fit_criteria` entry needs at least one effective test or machine check. Each invariant needs a test that fails when the invariant is violated.
- Each new feature needs at least one negative test. Assert observable behavior; do not generate expected results directly from implementation internals. Cover boundaries, errors, and recovery as required.
- New or modified tests must reference actual `REQ-*` / `INV-*` IDs in docstrings or comments and link their test nodes in the trace matrix. Pytest uses strict markers; register any new marker before using it.
- `test/offline/` must not depend on real networks, models, credentials, or user data. Use local fixtures, substitutes, and temporary directories. Dummy keys and a `unit` marker do not prove offline isolation.
- `test/live/` includes real model/data-source calls or network probes. Check current authorization, credentials, and cost limits before execution. Report missing conditions as unrun/skipped checks. Required live checks remain release blockers until completed.
- Do not leak credentials in test output or write to real user decision logs or checkpoints. Explicitly pass temporary cache, results, and memory paths.
- Do not fix unrelated defects as a side effect of WebUI development. If a blocker must be repaired first, submit that scope, tests, and necessary architecture approval explicitly.

## 4. Existing commands

Use Python >=3.10 in an approved isolated environment and install `pip install -e '.[dev]'` first. Dependency installation requires network/write access; do not assume that access is authorized.

```bash
python -m ruff check .
python -m mypy src
python -m pip check
python -m test.ci_gates dependencies
python -m bandit -r src -ll
python -m test.ci_gates schema
python -m test.ci_gates structure
python -m pytest -q test/offline
python -m pytest -q test/live
python -m pytest -q
python -c 'import tradingagents, cli.main; print("import OK")'
tradingagents --help
```

Real API tests can incur costs. The full-suite pytest command includes live tests and needs the same conditions. Use the current environment's entry points; do not hardcode a developer's temporary interpreter path. Verify clean installation with `pip install .` followed by imports in a fresh environment. Confirm that the package includes `cli/static/welcome.txt`.

`pyproject.toml` now declares the data validators, mypy, pip-audit, Bandit, and pytest-socket in the dev extra. Mypy checks all `src/`, including untyped function bodies; missing third-party stubs are tolerated but application type errors are not suppressed. Bandit scans the complete source at medium severity and above. The dependency helper audits exact installed name/version pins with pip-audit, excluding only this editable application and rejecting other editable dependencies. It does not rebuild or re-resolve the environment. Advisory-service failures do not count as a pass. Baseline findings must be repaired explicitly rather than suppressed.

Run CI-equivalent regression with `python -m pytest -q --disable-socket --allow-unix-socket`. This collects the complete suite while preventing real network calls. Credential-dependent tests may skip, which does not verify live API requirements. Actual live verification requires a separately authorized environment and evidence before those requirements are declared verified. Pytest-socket blocks Python socket calls; it is not an OS firewall for native extensions or subprocesses. Strong no-egress enforcement still belongs to the execution sandbox. Do not supply provider secrets to PR tests.

## 5. Requirements schema and semantic checks

`docs/req/req-schema.json` uses JSON Schema Draft 2020-12. Safely load YAML into JSON-compatible data before validation. The schema constrains nonempty registries, unknown fields, types, priorities, sources, and acceptance contracts. Invariants are `must`; their criteria use `unit: violations`, `comparison: eq`, and `threshold: 0`. Priority `wont` requires status `deferred`.

`test/ci_gates.py` additionally rejects duplicate YAML keys, duplicate requirement/criterion IDs, unknown/cyclic dependencies, missing explicit source/architecture/invariant references, path escapes, and missing evidence files for implemented/verified requirements. Complete requirement-to-module/test/monitor coverage and actual metric implementations still require design-specific validation and review. A schema does not run commands or verify human approval. Never execute arbitrary registry `command` values directly.

`requirements.yaml` remains empty. The schema gate intentionally blocks until requirements are recorded; do not create fictional requirements to make it green. Validator tools and the executable schema check are now included in dev dependencies and CI.

## 6. Required CI blocking gates

| Gate | Required before merge |
| --- | --- |
| Prior test approval | Verifiable test approval predates implementation and covers the current change version |
| Static analysis | Lint, type, and dependency checks on every commit; contract, security, API-surface, and permission checks on safety-relevant pull requests |
| Schema | YAML passes the schema and necessary semantic checks |
| Semantic evaluation | Every prompt/model change replays the same fixed evaluation set against approved quality/safety thresholds; failures block release |
| Regression | All previous suites pass with zero regressions |
| AI-use log | Code/prompt changes update `docs/ai-use-log.yaml` meaningfully; touching its timestamp is insufficient |

`.github/workflows/ci.yml` now runs on pushes to all branches, PR updates, review submissions/edits/dismissals, and manual dispatch. The `blocking-gate` aggregation fails if any prerequisite fails, is cancelled, or is skipped. No `continue-on-error` or automatic baseline waiver is used. A read-only GitHub token is limited to the review-check step; provider credentials are not exposed to PR code, and `pull_request_target` is not used.

Only PR/review events publish the merge-required `blocking-gate` status. Push and manual events report `branch-checks` and do not claim PR approval, so their results cannot satisfy the required merge gate or overwrite its review verdict. Require only the PR aggregation as the stable merge check.

Configure branch protection/rulesets separately to require `blocking-gate`, human PR review, and stale-review dismissal on every integration branch. Do not permit direct pushes or reviewer bypass for protected safety/governance changes. Protect workflow/checker modifications through human review. No remote setting is implied by a local YAML file, and merge-queue integration is not configured.

Review markers, identity checks, chronology binding, first-adoption limits, and final-head approval rules are defined in `docs/review-memo.md`. Git timestamps cannot prove when private work began. Public API/contract compatibility is checked by the fixed contract suite and full regression; safety changes require an ADR and current-head review, not an invented claim of complete automatic API-surface equivalence.

AI-use records must add a new meaningful entry covering the exact changed code/prompt/tooling paths. Existing entries or a timestamp-only edit are insufficient. Review and log checks compare canonical source paths so the approved mechanical root-to-src relocation is not mistaken for a new product implementation.

For runtime prompt/model changes, the semantic gate reads `[tool.tradingagents.ci.semantic_evaluation]` from the PR base. That approved policy must specify `evaluator`, `dataset`, and numeric `thresholds`. The evaluator and dataset must already exist unchanged on that base. The evaluator runs against candidate `src/`, outside the checkout, with Python socket calls disabled and credential-like environment variables removed. A fresh report must contain the exact dataset SHA-256, sample count, and every required metric.

The approved evaluator accepts `--dataset PATH --output PATH`; its dataset is a nonempty JSON list. Its JSON report contains `dataset_sha256`, `sample_count`, and `metrics`. Thresholds specify `comparison` (`eq`, `lte`, `gte`) and a finite numeric `threshold`. Missing evaluators, altered datasets, empty reports, nonfinite metrics, and failed thresholds block the change. No real semantic evaluator or product quality thresholds have been invented during preparation; the policy remains empty and such changes will be blocked until a separately reviewed policy is established. Fixed prompt-contract tests are additional checks, not a substitute for model-quality evaluation.

## 7. Baseline failures and honest reporting

The 2026-10-23 layout-migration verification returned 942 passed, 4 failed, 2 skipped, and 88 subtests passed for both the migrated branch and untouched release in the same temporary environment. The migrated failure locations were:

- `test/live/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache`
- `test/offline/test_ohlcv_cache_freshness.py::test_current_day_cache_past_ttl_is_not_fresh`
- `test/offline/test_ohlcv_cache_freshness.py::test_a_download_from_an_earlier_day_is_not_fresh`
- `test/offline/test_ohlcv_cache_freshness.py::test_load_ohlcv_refetches_stale_same_day_cache`

This is historical evidence, not a guarantee of current state. Record the environment and results each iteration. Existing failures are not passes or automatic exemptions. Do not hide them or weaken assertions; unresolved failures prevent a fully passing or merge-ready verdict.

Review records cover specification and architecture alignment, code/test quality, operational metadata, security, and efficiency. A human issues the final `APPROVE`, `CHANGES REQUIRED`, or `REJECT` decision.
