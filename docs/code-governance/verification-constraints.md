# Verification and Blocking Constraints

## 1. Prior tests and human gates

Humans must approve the iteration plan and test strategy before product implementation. Test files written first must also receive review before product implementation begins. Record the reviewer, time, plan/test version or commit, and scope. Reference the existing `docs/review-memo.md` or corresponding `transcripts/` session location; do not add an approval directory.

Only humans issue approval decisions. Changes to approved requirements, interfaces, safety boundaries, or test standards require a revision and approval of the affected scope. Do not request the same valid approval again.

Plan/test agreement is a development process requirement and can be recorded in the actual conversation or review memo. CI does not require a test-only commit, special review markers, or reconstruct historical approval chronology. GitHub branch protection owns human merge review, as revised in ADR-012-error-handling-merge-integration.md on 2026-11-21. This policy supersedes contradictory review-marker requirements in historical records below.

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

The unified registry uses format 1.1: 22 release core requirements plus 26
unchanged WebUI requirements, with all original IDs. Core acceptance metadata,
PRD, structured tradeoffs and source/test mappings are retained. Historical
criterion status is labeled `historical-release` and cannot justify changing a
requirement to newly `verified`. Core `Implemented` normalizes to `implemented`;
WebUI `draft` remains `draft`.

Both `python -m test.ci_gates schema` and
`python scripts/validate/validate_requirements.py` validate this registry. They
share canonical identity/dependency/evidence-scope semantics. The second entry
point also checks required artifacts, JSONC and secrets; JSONC comment handling
must preserve quoted globs and URLs. YAML duplicate keys and missing YAML support
fail closed. The real Draft 2020-12 validator is installed in CI. The explicitly
reported local fallback implements only the repository schema vocabulary and
rejects unsupported validation keywords; it never runs registry commands.

## 6. Required CI blocking gates

| Gate | Required before merge |
| --- | --- |
| Human merge review | GitHub branch protection enforces human approval; CI does not duplicate review history or special-marker checks |
| Static analysis | Lint, type, and dependency checks on every commit; contract, security, API-surface, and permission checks on safety-relevant pull requests |
| Schema | YAML passes the schema and necessary semantic checks |
| Semantic evaluation | For prompt/model changes, absent/empty base policy reports NOT RUN; invalid/partial policies and configured evaluation failures block |
| Regression | All previous suites pass with zero regressions |
| AI-use log | Code/prompt changes update `docs/ai-use-log.yaml` meaningfully; touching its timestamp is insufficient |

`.github/workflows/ci.yml` runs on pushes to all branches, PR updates, review submissions/edits/dismissals, and manual dispatch. The `blocking-gate` aggregation fails if any prerequisite fails, is cancelled, or is skipped. No `continue-on-error` or automatic baseline waiver is used. Unconfigured semantic evaluation completes its job with an explicit NOT RUN notice, not a model-quality pass. The former review API step and its `pull-requests: read` permission are removed; provider credentials are not exposed to PR code, and `pull_request_target` is not used.

Only PR/review events publish the merge-required `blocking-gate` status. Push and manual events report `branch-checks` and do not claim PR approval, so their results cannot satisfy the required merge gate or overwrite its review verdict. Require only the PR aggregation as the stable merge check.

Configure branch protection/rulesets separately to require `blocking-gate`, human PR review, and stale-review dismissal on every integration branch. Do not permit direct pushes or reviewer bypass for protected safety/governance changes. Protect workflow/checker modifications through human review. No remote setting is implied by a local YAML file, and merge-queue integration is not configured.

Use ordinary GitHub reviews under the configured branch protection instead of special markers or CI chronology checks. The current protocol and historical records are in `docs/review-memo.md`. Public API/contract compatibility is checked by the fixed contract suite and full regression; safety changes require an ADR and human review, not an invented claim of complete automatic API-surface equivalence. The compatibility `approval` command prints this ownership notice only; exit status zero is not approval evidence.

AI-use records must add a new meaningful entry covering the exact changed code/prompt/tooling paths. Existing entries or a timestamp-only edit are insufficient. Log checks compare canonical source paths so the approved mechanical root-to-src relocation is not mistaken for a new product implementation.

For runtime prompt/model changes, the semantic gate reads `[tool.tradingagents.ci.semantic_evaluation]` from the PR base. That approved policy must specify `evaluator`, `dataset`, and numeric `thresholds`. The evaluator and dataset must already exist unchanged on that base. The evaluator runs against candidate `src/`, outside the checkout, with Python socket calls disabled and credential-like environment variables removed. A fresh report must contain the exact dataset SHA-256, sample count, and every required metric.

An absent or empty base policy reports NOT RUN without blocking. A partial or invalid policy blocks; changes without runtime prompt/model impact report NOT REQUIRED. No real semantic evaluator or product quality thresholds have been invented, and the current policy remains empty. Establish a real evaluator and dataset in a separately reviewed base change before relying on model-quality evaluation.

The configured evaluator accepts `--dataset PATH --output PATH`; its dataset is a nonempty JSON list. Its JSON report contains `dataset_sha256`, `sample_count`, and `metrics`. Thresholds specify `comparison` (`eq`, `lte`, `gte`) and a finite numeric `threshold`. Configured but missing evaluators, altered datasets, empty reports, nonfinite metrics, and failed thresholds still block the change. Candidate policy edits cannot disable evaluation already configured on the base. Fixed prompt-contract tests are additional checks, not a substitute for model-quality evaluation.

## 7. Baseline failures and honest reporting

The 2026-10-23 layout-migration verification returned 942 passed, 4 failed, 2 skipped, and 88 subtests passed for both the migrated branch and untouched release in the same temporary environment. The migrated failure locations were:

- `test/live/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache`
- `test/offline/test_ohlcv_cache_freshness.py::test_current_day_cache_past_ttl_is_not_fresh`
- `test/offline/test_ohlcv_cache_freshness.py::test_a_download_from_an_earlier_day_is_not_fresh`
- `test/offline/test_ohlcv_cache_freshness.py::test_load_ohlcv_refetches_stale_same_day_cache`

This is historical evidence, not a guarantee of current state. Record the environment and results each iteration. Existing failures are not passes or automatic exemptions. Do not hide them or weaken assertions; unresolved failures prevent a fully passing or merge-ready verdict.

Review records cover specification and architecture alignment, code/test quality, operational metadata, security, and efficiency. A human issues the final `APPROVE`, `CHANGES REQUIRED`, or `REJECT` decision.


## Imported core verification contracts

The following contracts supplement the WebUI gates. Historical baseline and CI
observations refer to their recorded execution. Both schema checkers validate the unified registry; neither may be removed or
weakened to conceal an incompatible requirement or missing evidence.

# Verification Constraints

This document defines how code changes must be verified before finishing. It
applies to every agent and to human edits. The verification of record is the
offline deterministic suite (see `docs/architecture/evaluation-logbook.md`).

## Default verification procedure

1. **Read the governance docs first**: `AGENTS.md`,
   `architecture-blueprint.md`, `docs/architecture/invariants.md`,
   `docs/architecture/trace-matrix.md`, and `pyproject.toml`.
2. **Run the offline deterministic tests** that cover the change. The debate
   and gate tests must be included when the change touches the feature work.
3. **Run Ruff** (`ruff check .`) if Python source is modified. The repo's
   `pyproject.toml` selects a specific rule set; the whole-repo formatter
   adoption is intentionally deferred, so do **not** mass-format files.
4. **Validate the requirement/schema artifacts** if they changed
   (`scripts/validate/validate_requirements.py` against `docs/req/req-schema.json`).
5. **Update the trace matrix** (`docs/architecture/trace-matrix.md`) with any
   new/changed requirement ID in the same change.

## Constraint: networks and paid APIs

- The default `pytest -q` run must require **no** network and **no** paid LLM.
- Any test that needs a vendor/Live path MUST be marked `@pytest.mark.integration`
  and be opt-in. `test/live/README.md` documents this.

## Constraint: never claim a green suite dishonestly

- Do not claim a fully-green full suite when known date-sensitive cache failures
  or a network-reachability-dependent baseline failure remain.
- Record exact outcomes and the producing command in
  `docs/architecture/evaluation-logbook.md`.

## Constraint: secrets

- Never read, print, copy, commit, or transmit API keys, tokens, or
  `Bearer`/`sk-` strings.
- Never write a real secret into a committed file; use `.env.example`
  placeholders only.
- Before finishing, scan new/modified files for likely secrets without printing
  the secret values. The deterministic scan (`scripts/validate/scan_secrets.py`
  or equivalent) reports only the presence/location of a match, not its value.

## Constraint: fail closed on missing evidence

- If a required verification or decision is missing, mark it `TODO` with an
  owner/action and record it in `docs/debt-register.md` and
  `docs/architecture/risk-list.md`. Do not invent it.

## Constraint: human review at phase boundaries

- Each phase (analysis, contract, implementation, verification) requires an
  explicit recorded human review in `docs/review-memo.md` before proceeding.

## Constraint: every fit criterion has a test; negative tests required

- Every requirement's `fit_criterion` in `docs/req/requirements.yaml` MUST name a
  verification command/test that exists; a criterion with no real check is
  labelled `pending`, never claimed `verified`.
- Every feature/requirement change MUST add at least one **negative** test that
  pins the fail-closed / invariant-violating behavior (e.g. a malformed input
  that must be rejected, a future-dated record that must be dropped). A positive
  test alone is insufficient.
- Requirement/invariant IDs MUST appear in the tests that verify them (in the
  test module docstring, a comment, or the test name) so traceability is
  mechanically checkable.

## Constraint: three-tier verification model

A change is verified at up to three tiers, and the claim must state which tier
it is making. The three tiers are:

1. **Structural** — files parse, the schema validates, `ruff`, and
   `git diff --check`. This proves *shape*, not behavior.
2. **Regression** — the change does not break previously-passing behavior: the
   focused regressions plus the offline deterministic suite still pass on the
   covered path. This proves *no regression on the covered path*, not that new
   behavior is correct.
3. **Behavioral** — deterministic unit/integration tests demonstrate the new
   behavior itself on the covered (mocked/injected) path, including the required
   negative / fail-closed cases. This proves behavior on the covered path only.

A structural PASS is **never** reported as regression proof; a regression PASS is
**never** reported as behavioral proof; and none of the three tiers proves live
behavior (see the separate evidence axis below).

### Separate evidence axis: offline vs. live (NOT a tier)

**Offline vs. live is a separate evidence axis, never a substitute tier and never
a proof of live behavior.** Every command above runs offline and deterministically
(no network, no paid LLM). A **live / runtime** end-to-end run is a distinct
evidence source that sits on the `live` end of this axis: it is opt-in,
`@pytest.mark.integration`-marked, and separately authorized. Only a real live run
(the `live` end of the axis) can evidence live behavior; no structural, regression,
or behavioral *offline* PASS may be relabelled as live proof. Conversely, a live
run does not replace the offline tiers — both are reported, keep their own names,
and offline success is never claimed as live success.

In short: **tier** (Structural / Regression / Behavioral) describes *what kind*
of claim is being made; **axis** (offline / live) describes *where* the evidence
was collected. Do not conflate them.

## Constraint: document-only changes

- Documentation/governance changes must still parse (JSON/JSONC/YAML) and pass
  `git diff --check`. They do not require the offline Python test suite unless
  they touch Python/behavior.

## Simulated trading subsystem verification

The independent subsystem is verified with the canonical `test/offline/trading/` tree:

```bash
pytest test/offline/trading -q
```

The live 3-day smoke test is opt-in and must never run in the default suite:

```bash
RUN_LIVE_TRADING_TESTS=1 pytest test/live/trading -q -s
```

The unified requirements registry is validated with:

```bash
python scripts/validate/validate_requirements.py
```

Trading tests must remain deterministic and offline by default; the live fixture
sets the yfinance proxy only while the opt-in test executes and restores it after.
