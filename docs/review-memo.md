# Integrated branch records

Both branch histories are retained below. Dates, result counts, approval scopes,
and unresolved items belong to the recorded execution, not this merge. Commands
in release history use the former root-level layout; their current equivalents
use `src/`, `test/offline/`, and `test/live/`. No historical result is a fresh
verification of the merged tree.

## WebUI branch records

# Review Memo

## Preparation review — 2026-10-24

- Scope authorized by the user: development environment, document/permission workflow, transcript preservation, and repository CI blocking gates. At that stage, Git commits, pushes, merges, deployment, and product implementation were excluded.
- Source baseline: `release` at `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`; preparation branch: `feature/webui`.
- Existing migration and governance work is retained. No WebUI framework, product requirements, architecture decision, or quality threshold is invented.
- Implementation scope: developer dependencies/configuration, existing governance and record files, `test/ci_gates.py`, `test/offline/test_ci_gates.py`, and `.github/workflows/ci.yml`.
- Verification strategy: positive and negative gate tests; native configuration validation in a temporary project; actual schema/structure checks; lint, full-source type checks, dependency checks, and network-isolated regression. Do not turn baseline failures into passes.
- Plan/test approval evidence: the current conversation authorizes this preparation task. It is not a GitHub `[test-plan-approved]`, `[safety-approved]`, or `[governance-approved]` review, and it must not be represented as one.
- Human review status: pending. No final human verdict has been issued.

## Per-pull-request record format

For each real PR, append its URL, base/head commits, reviewer identity, review time, and scope. Cover requirements and architecture alignment, code and test quality, security, efficiency, operational metadata, actual commands/results, exceptions, and unresolved blockers. Record the actual human verdict: `APPROVE`, `CHANGES REQUIRED`, or `REJECT`. An agent recommendation must be identified separately.

## GitHub review protocol

Use a tests/design-only PR commit before product implementation. After reviewing the exact tests, requirements, and nonempty blueprint, a human collaborator with write/maintain/admin permission submits a `COMMENTED` review containing an explicit `[test-plan-approved]` decision. This dedicated test-plan decision is separate from merge approval and survives automatic dismissal of stale code approvals. An undismissed `APPROVED` review with the marker also qualifies, but is unsuitable for durable plan evidence when stale-review dismissal is enabled. Preserve that commit in history. Product implementation commits follow the plan decision; the bound tests, requirements, and blueprint must remain unchanged. A changed test/plan needs a new approved test-only revision before dependent implementation. Remove the marker to revoke the plan decision; dismissed reviews do not qualify.

For safety-relevant changes, update an ADR with `Context`, `Decision`, and `Consequences`, then obtain a human `[safety-approved]` approval on the final head. Changes to CI, permission/rule files, gate code, schema, or developer configuration need `[governance-approved]` on the final head. One real approval may contain both markers when the reviewer has assessed both scopes. Self-approval and bots do not qualify; an outstanding trusted request for changes blocks.

The gate verifies Git ancestry, exact reviewed content, server review records, and recorded commit chronology. It cannot prove when private or uncommitted coding began; Git timestamps and editable review bodies are not tamper-proof attestations. Trusted reviewers must submit plan markers before implementation rather than adding them retrospectively. Human oversight and protected branches remain necessary. Do not forge timestamps or review markers.

## First CI adoption

The existing base branch does not contain these new checks. Their first introduction requires explicit human inspection of the workflow and checker themselves. Subsequent changes are also protected by current-head governance review. This repository cannot protect its own unmerged workflow from every hostile edit; require the stable `blocking-gate` check and human review through GitHub rulesets/branch protection before relying on enforcement.

## Local verification evidence — 2026-10-24

- Environment used for these historical checks: Python 3.12.14 in an ignored `.venv`, subsequently removed during cleanup.
- Gate tests: 42 passed with real network disabled. Ruff, dependency consistency, permissions, and structural checks passed.
- Complete regression with Python sockets disabled: 984 passed, 4 inherited failures, 2 skipped, 88 subtests passed.
- Full-source mypy: 202 errors in 27 files (84 source files checked). These existing application findings were not suppressed or repaired by this preparation change.
- Bandit at medium severity and above: 5 findings; these require human triage, not an assumption that every result is exploitable.
- Schema gate correctly blocks the empty requirements registry. No product requirements were invented.
- Workflow syntax/expressions passed actionlint 1.7.12. Native OpenCode accepted the configuration and all four roles in a temporary project. A freshly built wheel installed into a clean temporary environment, imported outside the repository, and retained the CLI resource and working help command.
- Dependency audit passed for 122 exact installed third-party versions; only this local application was excluded. No other editable dependencies are accepted.
- Hosted workflow, real reviewer approvals, and live model/data API behavior have not been exercised by these local checks.
- Read-only GitHub inspection: default branch `release`, repository public, current account has admin permission, no rulesets. Existing release protection enforces admins, one human review, stale-review dismissal, last-push approval, and code-owner review; required-status-check contexts are empty. Remote settings have not been modified.

## Cleanup and commit authorization — 2026-10-24

- The user explicitly requested cleanup of generated intermediate files and caches, followed by one Git commit, and instructed that this preparation work does not need further tests.
- Removed local virtual environments, Python and tool caches, editable-install metadata, temporary build outputs, and task-specific temporary reports. Removed the verbose dependency inventory from this memo; the concise historical results above remain historical evidence.
- Retained source and CI implementation files, existing tests, governance documents, and intentional empty requirements/design placeholders. Preserved the existing deletion of `CHANGELOG.md` and removed its stale references.
- No tests were run for this cleanup. No new passing-check or human-review verdict is claimed. Commit authorization does not imply final governance approval.
- Push, merge, deployment, product development, and remote repository settings remain outside this cleanup scope.

## Requirements and architecture drafting — 2026-11-05

- Scope authorized by the user: discuss WebUI requirements in batches, then enter the Docs phase and write project documents in English. Product implementation, tests, commits, pushes, merges, deployments, dependency installation, and live API calls were not authorized.
- Confirmed product baseline: local single-user WebUI on `127.0.0.1` without authentication; one active run at a time; coexist with an unchanged CLI and core; complete eight-step wizard; live progress, messages, tools, statistics, and full I–V report; read-only history over existing artifacts; backtest launch and results; checkpoint controls; portfolio JSON by paste or upload; cancellation with CLI-equivalent semantics; server-only provider keys; announcements with TUI parity; Chinese/English UI.
- Explicit exclusions: new data sources/models, agent or prompt changes, trading execution, multi-user/tenancy/billing, new databases or message queues, cloud/container deployment, PDF/Word export, native mobile, multi-ticker analysis outside backtest, cross-run comparison/scoring, and any change to CLI or core behavior.
- Artifacts created: `docs/req/requirements.yaml` (26 draft requirements, 69 acceptance criteria), `architecture-blueprint.md`, `docs/architecture/adr/001-choice.md`, `docs/architecture/invariants.md`, `docs/architecture/trace-matrix.md`, `docs/architecture/risk-list.md`, `docs/architecture/runtime-policy-catalog.md`, `docs/architecture/memory-design.md`, `docs/architecture/option-ledger.md`, `docs/architecture/evaluation-table.md`, and `docs/architecture/evaluation-logbook.md`. `README.md` was updated to point to the draft documents and to state that drafts do not authorize implementation.
- Validation performed: local YAML parsing with duplicate-key detection and a targeted validator mirroring the schema and gate rules passed (26 requirements, 69 unique criteria). The official `python -m test.ci_gates schema` was not run because the host lacks `PyYAML`, `jsonschema`, and `json5`; dependency installation was not authorized. No product tests or live tests were run.
- Human approval status: the user confirmed the discussion baseline and authorized this Docs phase in the current conversation. The written artifacts themselves have not received a review verdict. No `[test-plan-approved]`, `[safety-approved]`, or `[governance-approved]` review is claimed.
- Open decisions: web framework, event transport, frontend stack, final package path, default UI language, preference-file writes, backtest cancellation, download packaging, and the event-latency target.
- No implementation, dependency change, CI change, commit, push, or remote setting change was performed in this phase.

## Design approval and decision recording — 2026-11-05

- Human decision: the user approved the architecture design presented in the current conversation, including TypeScript + React + UI technology and the delegated backend, transport, packaging, history, security, and run-control choices. This approval covers documentation only; it is not a GitHub `[safety-approved]`, `[test-plan-approved]`, or `[governance-approved]` review.
- Approved decisions: FastAPI + Uvicorn single worker; SSE; React 19 + TypeScript + Vite; Tailwind + shadcn/Radix + Lucide; Zustand + TanStack Query; React Hook Form + Zod; react-markdown + rehype-sanitize; react-i18next with English default and Chinese switch; `src/tradingagents_web/` with `[web]` extra and `tradingagents-web` entry point; in-memory single run; read-only hash-id history; complete Markdown + zip downloads; analysis cancellation only; no backtest cancellation; loopback without authentication with Host/Origin/CSRF/CSP controls; server-only keys; no server paths.
- Artifacts updated: `architecture-blueprint.md`, `docs/architecture/adr/001-choice.md` (updated), `docs/architecture/adr/002-backend-framework-and-transport.md` through `007-run-controls.md` (new), `docs/architecture/invariants.md` (001–015), `docs/architecture/trace-matrix.md`, `docs/architecture/permission-model.md` (filled), `docs/architecture/memory-design.md`, `docs/architecture/runtime-policy-catalog.md`, `docs/architecture/option-ledger.md`, `docs/architecture/risk-list.md`, `docs/architecture/evaluation-table.md`, `docs/architecture/evaluation-logbook.md`, `docs/debt-register.md`, `README.md`, and `docs/ai-use-log.yaml`.
- Validation performed: the requirements registry was unchanged; its earlier local YAML and targeted schema/gate-equivalent checks remain the only executed validation. Blueprint architecture anchors were checked locally and resolve. No architecture experiment, product test, packaging test, browser test, latency measurement, dependency audit, or live call was executed. The official `python -m test.ci_gates schema`, structure, lint, type, dependency, and security checks remain unrun because the host lacks the dev dependencies.
- Planned versus actual: `docs/architecture/evaluation-table.md` lists EVAL-01 through EVAL-10 as planned; `docs/architecture/evaluation-logbook.md` records only the executed documentation checks. No planned result is reported as passing.
- Remaining before implementation:
  1. A concrete test plan with implemented test nodes and fixtures, approved via `[test-plan-approved]` on a test-only revision.
  2. Current-head `[safety-approved]` for the new web entry point (ADR-001 through ADR-007).
  3. Current-head `[governance-approved]` for `pyproject.toml`, CI, dependency, packaging, and permission changes.
  4. Dependency, license, and advisory approval for FastAPI, Uvicorn, and the npm dependency tree.
  5. Official schema, structure, lint, type, dependency, and security checks in an approved environment.
  6. Human review of the filled permission model and the blueprint as written artifacts.
  7. Live-test authorization before any live model/data verification.
- No implementation, dependency installation, `pyproject.toml` change, CI change, commit, push, merge, deployment, or remote setting change was performed.

## Iteration-1 test plan review request — 2026-11-05

- Scope: read-only WebUI history and report browser. Requirements: `REQ-WEB-010`, `014`, `020`, `021`, `023`, `024`, `025`, `026` (18 acceptance criteria). Deferred: analysis runs, SSE, cancellation, checkpoints, portfolio, backtest launch, config/wizard, key input.
- Test files written: `test/offline/web_fixture_app.py`, `test/offline/test_web_history.py`, `test/offline/test_web_security.py`, `test/offline/test_web_contracts.py`, `test/offline/test_web_frontend_contract.py`.
- Test design: normal history/report/download flows; invalid IDs and traversal; missing/partial/malformed artifacts; loopback/Host/CORS/CSP; secret redaction; no server paths; read-only mutations; no execution route; core/CLI signature and import compatibility; i18n and frontend static contracts.
- Execution status at the time of the review request: **not run**. The host lacked `pytest`, `fastapi`, `httpx`, and a runnable `tradingagents` test environment; dependency installation had not yet been authorized. Only a Python AST syntax check was executed on the five test files.
- Expected failure class while product code is absent: `EXPECTED-UNIMPLEMENTED` from the test helper. These are expected, not passing, not skipped, and not test defects.
- Coverage gaps requiring the frontend harness: behavioral i18n report-language independence (`FC-WEB-014-02`), browser execution (`FC-WEB-021-01`), and runtime XSS/sanitization (`FC-WEB-025-01/02`) currently have static contract checks only. They must not be marked verified until Playwright/Vitest execute them.
- GitHub test-plan approval: **none is claimed.** To record a real `[test-plan-approved]`, commit and push this exact test-only revision (tests plus the unchanged requirements and blueprint), then have a trusted human reviewer submit a review containing `[test-plan-approved]` on that commit before any implementation commit. The reviewer decision is human-owned; this memo is only a request for review.
- At the time of this review request, no product code, dependency installation, commit, push, merge, deployment, or remote setting change had been performed.

## Iteration-1 test version approval — 2026-11-05

- Reviewer: human project owner, in the current conversation.
- Time: 2026-11-05.
- Scope: the iteration-1 read-only history/report test version identified by content hash `0923433e9108ab8c6a2ce3f7e8505e8b8efc1b5b8848825c83df923b2c47b9e7` (five files under `test/offline/`), covering `REQ-WEB-010`, `014`, `020`, `021`, `023`, `024`, `025`, `026`.
- Verdict: **APPROVE** for this test version only.
- Limits: this is a conversation approval, not a GitHub `[test-plan-approved]` review, not approval to install dependencies, and not approval to start product implementation. At the time of this approval the test version had not been executed; a separate authorization was later given to install test dependencies and run it.
- Remaining gates: dependency/license/advisory approval; a real GitHub `[test-plan-approved]` on a committed test-only revision if CI gating is used; `[safety-approved]` for the web entry point; `[governance-approved]` for `pyproject.toml`/CI/packaging.
- No commit, push, or product implementation was performed at this stage.

## Iteration-1 test execution — 2026-11-05

- Authorization: the user authorized creating `.venv`, installing test dependencies, and executing the approved test version.
- Environment: Python 3.14.3; repo-local `.venv`; `pip install -e '.[dev]' fastapi uvicorn httpx`. The `[web]` extra does not exist yet, so the equivalent runtime/test packages were installed directly. `pyproject.toml` was not changed.
- New WebUI tests: **5 passed, 13 failed, 40 errors** in 11.36 s. All 13 failures and 40 errors are `EXPECTED-UNIMPLEMENTED` (`tradingagents_web` or frontend files absent). No unexpected failure or test defect was observed. The 5 passes are the core/CLI compatibility checks in `test_web_contracts.py`.
- Official gates: `python -m test.ci_gates schema` **PASS**; `python -m test.ci_gates structure` **PASS**.
- Existing compatibility: `test/offline/test_cli_commands.py` + `test/offline/test_reporting.py` **14 passed**; import smoke **OK**; ruff on the five new test files **passed**.
- Existing regression (all tests excluding the four new WebUI test files): **984 passed, 4 failed, 2 skipped, 88 subtests passed**. The 4 failures are the documented historical baseline failures (`test/live/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache`; three `test/offline/test_ohlcv_cache_freshness.py` tests). No new regression was introduced.
- Not run: architecture experiments EVAL-01 through EVAL-10; Playwright browser execution; frontend Vitest; packaging/clean install; full mypy; Bandit; live model/data calls.
- No product code was implemented; no commit, push, merge, deployment, or remote setting change was performed.

## Iteration-1 implementation — 2026-11-06

- Authorization: the user instructed the agent to start implementing Iteration 1 after approving the architecture and test version.
- Scope implemented: read-only WebUI history/report browser only. No analysis runs, SSE, cancellation, checkpoints, portfolio, backtest launch, config/wizard, or key input.
- Backend: `src/tradingagents_web/` with FastAPI app factory, loopback/Host/CSP middleware, safe error payloads, artifact index/readers/downloads, health and history APIs, CLI entry point.
- Frontend: React 19 + TypeScript + Vite source under `src/tradingagents_web/frontend/`, i18n catalogues, sanitized Markdown, history/detail pages, browser matrix, Playwright config. Build output goes to `src/tradingagents_web/static/` and is ignored by Git.
- Packaging: `pyproject.toml` adds the `[web]` extra, `tradingagents-web` entry point, `httpx` to dev, and `tradingagents_web/static/**` package data. `.gitignore` ignores frontend `node_modules`, generated `static/`, and Playwright outputs.
- Verification (Python 3.14.3, repo-local `.venv`):
  - WebUI tests: **58 passed**.
  - Full regression: **1042 passed, 4 failed, 2 skipped, 88 subtests passed**. The 4 failures are the documented historical baseline failures; no new regression.
  - `test.ci_gates schema` and `structure`: **PASS**.
  - `mypy src/tradingagents_web`: **Success, no issues**.
  - `ruff` on the new package and tests: **All checks passed**.
  - CLI/reporting compatibility: **14 passed**; import smoke: **OK**.
  - Frontend `npm run lint`, `npm run typecheck`, `npm run build`: **PASS**.
  - `npm audit`: **0 vulnerabilities** after upgrading Vitest and overriding minimatch.
  - Wheel inspection: `tradingagents_web/static/index.html` and the `tradingagents-web` console script are present.
  - Static/API smoke: `/`, `/history`, `/api/health`, `/api/history` return **200**.
- Deviations and unfinished items:
  - Local verification uses Python 3.14.3, outside the CI 3.10–3.13 matrix; CI execution is pending.
  - Frontend Vitest and Playwright browser execution are not implemented/run; behavioral i18n report-language independence, browser matrix, and runtime XSS criteria remain unverified.
  - Clean-install in a fresh environment and full mypy/Bandit/pip-audit checks are not run.
  - Requirements statuses remain `draft`; the implementation review verdict is recorded below.
- No commit, push, merge, deployment, or remote setting change was performed.

## Iteration-1 implementation approval — 2026-11-06

- Reviewer: human project owner, in the current conversation.
- Time: 2026-11-06.
- Scope: the Iteration-1 read-only history/report implementation, including the `src/tradingagents_web/` backend, React/TypeScript frontend, `pyproject.toml`/`.gitignore` changes, tests, and verification evidence described above.
- Verdict: **APPROVE** for the Iteration-1 implementation.
- Evidence accepted: WebUI tests 58 passed; full regression 1042 passed with 4 documented historical failures; schema/structure gates passed; new-package mypy and ruff passed; frontend lint/typecheck/build passed; npm audit 0; wheel contains static assets and the `tradingagents-web` entry point.
- Limits: this is a conversation approval, not a GitHub `[safety-approved]`, `[governance-approved]`, or `[test-plan-approved]` review. The frontend Vitest/Playwright behavioral gaps, clean-install check, CI 3.10–3.13 run, full mypy/Bandit/pip-audit, and live tests remain open. Requirements registry statuses remain `draft`; no separate requirements-verification verdict is claimed.
- No commit, push, merge, deployment, or remote setting change was performed.

## Iteration-2 test version review request — 2026-11-06

- Scope: merged Iteration-2 (run control plane + wizard/live UI). Requirements: `REQ-WEB-001`–`009`, `013`, `014`, `020`–`029`, `031`; deferred: `REQ-WEB-011` (backtest), `REQ-WEB-012` (announcements), `REQ-WEB-030` (backtest isolation).
- Test version hash: `de2193180ffd42f17e13f6adb9c2b223fb38de85663ca1432873c248db0cdfca`.
- Backend test files: `test/offline/web_fixture_app.py`, `test_web_config.py`, `test_web_runs.py`, `test_web_events.py`, `test_web_portfolio.py`, `test_web_checkpoints.py`, `test_web_reporting.py`, plus extended `test_web_security.py` and `test_web_contracts.py`.
- Frontend test files: `frontend/vitest.config.ts`, `frontend/src/test-setup.ts`, `frontend/tests/i18n.test.ts`, `markdown-sanitize.test.tsx`, `wizard-validation.test.ts`, `run-store.test.ts`, `frontend/e2e/run.spec.ts`.
- Backend execution (Python 3.14.3, `.venv`): **15 failed, 30 passed, 40 errors**. All 15 failures and 40 errors are `EXPECTED-UNIMPLEMENTED` because the Iteration-2 `tradingagents_web.api.*` / `runtime.*` modules do not exist. The 30 passes include existing Iteration-1 security/history/contract tests; the separate Iteration-1 suite remains **58 passed**.
- Frontend execution (`vitest`, jsdom): **4 tests passed, 2 suites failed to resolve**. The two failures are `EXPECTED-UNIMPLEMENTED` (`src/pages/NewAnalysis/validation` and `src/stores/runStore` do not exist). `i18n.test.ts` and `markdown-sanitize.test.tsx` pass. `npm run lint` passes.
- Test defect found and fixed during execution: the Markdown script test originally placed `<script>...</script>safe text` in one HTML block, so the safe text was sanitized with it. The test now uses a separate paragraph; the sanitizer assertion was not weakened.
- Not run: Playwright E2E (browser binaries/implementation absent), real model/data calls, live tests.
- Coverage: normal/failure/permission/CSRF/CLI–Python compatibility are represented in the test files. Full behavioral acceptance cannot pass until Iteration-2 product code exists.
- GitHub test-plan approval: **none is claimed.** To record a real `[test-plan-approved]`, commit and push this exact test-only revision, then have a trusted human reviewer submit a review containing `[test-plan-approved]` on that commit before implementation. The reviewer decision is human-owned.
- No product code, commit, push, merge, deployment, or remote setting change was performed.

## Iteration-2 implementation — 2026-11-06

- Authorization: the user approved the merged Iteration-2 plan and test version and instructed implementation to proceed.
- Scope implemented: eight-step analysis wizard, server-side config projection and key status, portfolio validation, checkpoint toggle/clear, single-run coordinator, SSE live view, cancellation, reattachment, run artifacts, completed report, and history integration. Backtest launch and announcements remain deferred.
- Backend: `api/session.py`, `api/config.py`, `api/portfolio.py`, `api/checkpoints.py`, `api/runs.py`, `runtime/coordinator.py`, `graph_runner.py`, `projector.py`, `event_buffer.py`, `artifacts_writer.py`, and request models. CSRF is now active for start/cancel/portfolio/checkpoint POSTs; unknown POST routes still return 404/405.
- Frontend: wizard, validation module, run store, run API client, live-run page, new-analysis route, navigation link, and expanded i18n/UI strings. Added `zustand` and its lockfile entries.
- Verification (Python 3.14.3; Node 24.13.0):
  - WebUI backend suite: **113 passed**.
  - Full regression: **1097 passed, 4 failed, 2 skipped, 88 subtests passed**. The 4 failures are the documented historical baseline failures.
  - `test.ci_gates schema` and `structure`: **PASS**.
  - `mypy src/tradingagents_web`: **Success**; `ruff`: **All checks passed**.
  - Frontend Vitest: **10 passed** (4 files); `npm run typecheck`, `npm run lint`, `npm run build`: **PASS**.
  - `npm audit`: **0 vulnerabilities**.
  - Wheel includes the new Iteration-2 modules and built static assets.
- Deviations / not run:
  - Playwright E2E was not executed at the time of implementation verification; the Chromium E2E follow-up is recorded below.
  - The real `GraphRunner` path was not exercised against a live model/data provider; automated tests use `FakeGraphRunner`. Live tests require separate credentials/cost authorization.
  - Clean install in a fresh environment, full mypy, Bandit, and pip-audit were not run.
  - Requirements registry statuses remain `draft`; no separate requirements-verification verdict is claimed.
- Test-version delta: the approved test hash `de2193180ffd42f17e13f6adb9c2b223fb38de85663ca1432873c248db0cdfca` changed to `542fc400fb2541fb1f25220791dc5eb41873280dc940b132d48064b345660cb1` after two test-support fixes during implementation: `parse_sse` now flushes the final SSE frame, and `_collect_events` stops on a `data:` line instead of the preceding `event:` line. No assertion was weakened. This test delta requires review.
- No commit, push, merge, deployment, or remote setting change was performed.

## Iteration-2 Chromium E2E — 2026-11-06

- User instruction: use Chromium only; do not use Firefox or WebKit.
- Added `test/offline/web_e2e_server.py` (fake-backend FastAPI server with `E2ERunner`), Playwright `webServer` configuration, and `e2e/run.spec.ts` covering history, wizard → live → completed report, and cancel.
- Fixed the live page's SSE handling: custom SSE event types were previously ignored by `onmessage`; the page now subscribes per event type and closes the stream on a terminal event.
- Result: **4/4 Chromium E2E passed** in 7.9 s. Chromium uses the installed Google Chrome channel rather than a downloaded Playwright browser.
- Supporting checks: frontend Vitest **10 passed**, typecheck/lint/build passed, `npm audit` **0 vulnerabilities**.
- Not run by instruction: Firefox and WebKit E2E. The browser matrix remains partially verified.
- Not run: real GraphRunner/live model/data path, clean install, full mypy/Bandit/pip-audit.
- No commit, push, merge, deployment, or remote setting change was performed.

## Iteration-3 test version review request — 2026-11-06

- Scope: `REQ-WEB-011` (backtest launch/results), `REQ-WEB-012` (announcements), and `REQ-WEB-030` (backtest/live isolation and read-only history). No product code was implemented.
- Authorization: the user approved the Iteration-3 plan and test plan in the current conversation and instructed test-first work.
- Test version hash: `18f712b9148496d5a61f4ba25b620b257f23a44e37f1694c6971385d19cf308f`.
- Hash method: SHA-256 over the 12 changed/new test files, sorted by repository path, hashing `path`, NUL, file bytes, NUL for each file. This method is stated explicitly because earlier hashes were recorded without a reproducible command.
- Backend files: `test/offline/web_fixture_app.py`, `test_web_backtest.py`, `test_web_announcements.py`, `test_web_contracts.py`, `test_web_security.py`.
- Frontend files: `tests/iteration3-support.ts`, `backtest-validation.test.ts`, `backtest-summary.test.tsx`, `announcements.test.tsx`, `backtest-i18n.test.ts`, `e2e/backtest.spec.ts`, `e2e/announcements.spec.ts`.
- Backend execution (Python 3.14.3, `.venv`): **113 passed, 6 failed, 28 errors** for `test/offline/test_web_*.py`. All 34 new failed/error items are `EXPECTED-UNIMPLEMENTED` because `tradingagents_web.api.backtests`, `api.announcements`, `models.backtest_requests`, and `runtime.backtest_runner` do not exist. No unexpected failure or test defect was observed.
- Frontend execution (`vitest`, jsdom): **10 passed, 15 failed**. All 15 failures are `EXPECTED-UNIMPLEMENTED`: the backtest validation/summary/announcement components and the new i18n keys are absent. The 10 existing Iteration-1/2 frontend tests still pass.
- Chromium Playwright: **4 passed, 2 failed**. The two new specs report `EXPECTED-UNIMPLEMENTED` because `/api/backtests` and `/api/announcements` return 404. The four existing history/wizard/cancel specs still pass.
- Static checks: Python compileall and ruff on the changed test files **passed**; frontend ESLint on `tests` and `e2e` **passed**.
- Test coverage added: CLI-equivalent backtest parameters, summary fields, log artifact download, `run_id` resume, single-slot conflict with analysis, isolated live memory, failure isolation, no backtest cancel route, read-only backtest history, invalid requests, CSRF/Origin enforcement, secret/path redaction, announcement success/fallback/malformed payload/cache/no-path, unsafe announcement rendering, frontend validation, summary rendering, no cancel control, blocking acknowledgement, and i18n key presence.
- Not run: full regression (the new suites intentionally fail until implementation), real `run_backtest` model/data calls, real announcement network calls, Firefox/WebKit, clean install, full mypy/Bandit/pip-audit.
- GitHub test-plan approval: **not claimed**. The local test revision is frozen for human review; implementation must not begin until this test version is approved.
- No product code was implemented. The test-only revision is committed locally and has not been pushed; no merge, deployment, or remote setting change was performed.

## Iteration-3 implementation — 2026-11-06

- Authorization: the user approved the Iteration-3 plan and the test version in the current conversation.
- Scope implemented: backtest launch/status/summary/log download, read-only backtest history, shared single-run slot with analysis, server-side announcements with fallback/cache, blocking announcement acknowledgement, and frontend Backtest/Announcements pages.
- Backend modules: `api/backtests.py`, `api/announcements.py`, `runtime/backtest_runner.py`, `models/backtest_requests.py`; coordinator extended with `BacktestRecord` and shared-slot `start_backtest`; history download extended with `kind=log`; CSRF covers `/api/backtests`.
- Frontend: `BacktestPage`, `BacktestRunPage`, `Backtest/validation.ts`, `Backtest/BacktestSummary.tsx`, `Announcements.tsx`, `api/backtestClient.ts`, routes, history link, and i18n strings. No new npm dependency was added.
- Verification (Python 3.14.3; Node 24.13.0):
  - WebUI backend suite: **147 passed**.
  - Frontend Vitest: **25 passed** (8 files).
  - Chromium Playwright E2E: **6 passed** (history, announcements, backtest, wizard/live/report, cancel).
  - Full regression: **1131 passed, 4 historical failures, 2 skipped, 88 subtests passed**. The 4 failures are the documented historical baseline failures.
  - `test.ci_gates schema` and `structure`: **PASS**.
  - `mypy src/tradingagents_web`: **Success, 31 source files**; `ruff`: **All checks passed**.
  - Frontend typecheck, lint, and build: **PASS**; `npm audit`: **0 vulnerabilities**.
  - CLI help/import smoke: **PASS**.
  - Wheel includes the new backtest/announcement modules and built static assets.
- Test-version delta: only `test/offline/web_e2e_server.py` changed during implementation (+46 lines) to add fake backtest and announcement providers for the already-approved E2E specs. No test assertion was changed; the frozen 12-file hash `18f712b9148496d5a61f4ba25b620b257f23a44e37f1694c6971385d19cf308f` remains unchanged.
- E2E fix: the English label for the history section was changed from "Backtest history" to "Past sweeps" because the approved locator `getByRole("heading", { name: /backtest/i })` is strict-mode and matched two headings. No test was weakened.
- Not run: real `run_backtest` model/data calls, real announcement network calls, Firefox/WebKit, clean install, full mypy/Bandit/pip-audit, GitHub review markers.
- Startup help/banner text was corrected after implementation to describe analysis, backtest, and history instead of the Iteration-1 read-only wording.
- No push, merge, deployment, or remote setting change was performed.


## Analysis-path repair authorization — 2026-11-06

- The user requested a read-only investigation of basic WebUI analysis, then explicitly authorized the proposed repairs after confirming that original CLI/core functionality must remain unchanged.
- Product-code allowlist: `src/tradingagents_web/`. Supporting changes cover Web tests, architecture refinement, traceability, bug records, and actual AI-use/verification evidence. No original core/CLI source, dependencies, CI rules, or credentials are modified.
- Scope: effective configuration and provider/model selection; complete snapshots/SSE recovery; safe visible failures and correlated redacted logs; artifact initialization cleanup; isolated per-run reports; real graph progress and resume state.
- Test changes retain assertions; two existing artifact-path expectations now point to the isolated Web run directory. The offline integration test uses actual GraphRunner, TradingAgentsGraph, LangGraph, memory and report writers, replacing only model/identity-provider boundaries. Browser tests also retain existing assertions and add reload verification.
- The user explicitly authorized local Chromium browser verification after automatic approval initially applied the earlier preparation-only no-test instruction. No live model/data smoke, Git commit, push, merge, or deployment is authorized by that approval.
- Final human review and GitHub review markers remain pending. Requirements retain their existing approval/status records.


## Real API failure follow-up — 2026-11-06

The user supplied a real-run traceback for `c_6c77fd7723f2`. The direct exception is Yahoo Finance throttling in the market tool, rather than an LLM-authentication error. Continuing the authorized Web-only repair, the error mapper now distinguishes this condition and typed market-data failures from other execution errors. No original CLI/core behavior, vendor policy, retry budget, credentials, or external-service configuration is changed. Validation uses an actual tool-calling core graph with isolated fake provider boundaries. Live provider calls remain unrun; resolving actual Yahoo throttling requires data-source recovery or an explicitly chosen existing vendor configuration.

The user subsequently confirmed that no alternative vendor key is available and chose to continue using Yahoo Finance. Keep the existing vendor selection and retry policy; do not add implicit fallbacks or background live requests.


## Release core records (79103c3)

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
  (OpenCode, 2026-11-11): CONFIRMED offline** — 107 focused cap tests passed; full
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

  **INDEPENDENT OpenCode verification of this repair (2026-11-11; AI technical
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
  explicit request, OpenCode reran the actual school model on committed source
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
- **Independent OpenCode AI verification (HISTORICAL / PRE-REPAIR, logbook 072; the
  "583 passed / 1768 passed" figures are superseded by the CURRENT DISPOSITION
  above; NOT human acceptance):** 14-file focused suite **583 passed / 2
  warnings**; validator **42/42 PASS** + no secret hits; independent boundary
  **39/39**; **440** negative schema mutations rejected; actual
  `strict_offline_harness.py` run **4 failed / 1768 passed / 1 skipped / 1
  deselected** with the same **1** intercepted baseline attempt; Ruff clean;
  `git diff --check` clean. This was the pre-repair recorded result and is AI
  technical verification only.
- **User-authorized school-model live run (2026-11-10, OpenCode; docs-only record;
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

- **Status:** Review requested; human/OpenCode review performed; verification
  recorded.
- **Reviewer:** Human (project) with OpenCode review.
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

**Independent OpenCode AI verification of the CURRENT files (HISTORICAL /
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
Inline implementation focused suite 387 passed. OpenCode independent re-run of the
then-current frozen PRE-FOLLOWUP tree: 639 focused offline tests passed, 0
forbidden socket attempts, 19/19 external boundary probes; full canonical
`scripts/validate/strict_offline_harness.py` 1817 passed, 4 SAME known baseline
failures (3 date-sensitive OHLCV cache + 1 intercepted baseline network),
1 skipped, 1 deselected, 88 subtests, 1 intercepted baseline socket
attempt (no connection); Ruff/governance 42/42/diff clean; code fingerprint of
214 files unchanged across the live verification (this fingerprint statement
applies to the PRE-FOLLOWUP tree only, not the final post-followup tree).

Bounded real school-model validation COMPLETED (OpenCode; guarded at 32 requests /
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
  **independent reviewer (OpenCode) verification** and **later explicit human
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
  **independent reviewer (OpenCode) verification** and **later explicit human
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
  **independent reviewer (OpenCode) verification** and **later explicit human
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
- **Status:** still **technically verified offline**; independent OpenCode review of the
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
  **independent reviewer (OpenCode) verification** and **later explicit human
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
  **independent OpenCode verification** and **later explicit human acceptance**. The
  prior incomplete 2026-11-11 school-model live run is NOT relabelled as a fixed
  live proof; both fixes remain offline-only until a separately authorized future
  live verification. No human acceptance is claimed or invented. Not a
  remote-CI-green claim (push not authorized).

### 2026-11-11 — Independent OpenCode technical review of the two live-finding repairs: COMPLETED (NOT human acceptance; NOT a live retest)

- **Scope:** independent AI (OpenCode) technical verification of the repaired tree for
  the two confirmed live-run defects (Defect-1 origin authority, Defect-2 structured
  raw usage) and the scoped no-resurrection tombstone edge. Documentation-only sync;
  no source/test changes, no product/vendor/model calls, no Git mutations.
- **Independent results (OpenCode, on this tree):** full strict-offline **2190 passed,
  1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts**;
  focused two new files **36 passed, 0 sockets** (18 origin + 18 structured); Ruff
  clean; governance validator **43/43 PASS** including the likely-secret scan;
  `git diff --check` clean; HEAD remains `5ecea91`; frozen governance/CI/dependency
  files untouched.
- **Independently rerun reproduction (stale-map + state-tombstone):**
  `gate_retrusted=False`, `direct_consumer_retrusted=False` (previously True/True).
- **Logs (OpenCode):** `/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-11-live-findings-repair-independent-full-offline.log`
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
  (original plan overridden by its Correction 1/2/3). Builder (OpenCode; OpenCode
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
  OpenCode review** and **later explicit human acceptance**. The preserved 2026-11-11
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
- **Status:** IMPLEMENTED + offline-verified; awaits independent OpenCode review and
  later explicit human acceptance. Not a live retest; preserved 2026-11-11 live
  evidence unchanged and not relabelled. Branch `feature/data-quality-debate-control`,
  HEAD `5ecea91` unchanged; no commit/push/PR.

### 2026-11-12 — Independent OpenCode technical review of the two-defect repair: COMPLETE (NOT human acceptance; NOT a live retest)

Independent AI (OpenCode) technical verification of the final repair tree is complete.
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
  2026-11-12 (implementation approval ONLY). Builder (OpenCode); OpenCode independent
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
- **Status:** IMPLEMENTED + offline-verified; awaits independent OpenCode review and
  later explicit human acceptance. Prior 26-call / 202,941-token run remains
  historical bug evidence, not post-fix live proof.

### 2026-11-12 — Independent OpenCode FINAL technical review of the verified-span repair: COMPLETE (NOT human acceptance; NOT a live rerun)

- **Scope:** independent AI (OpenCode) technical review of the repaired verified-span
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

### 2026-11-12 — Python 3.10 CI repair: human PLAN/TEST approval + builder implementation report

- **Human decision (recorded):** the human explicitly approved this round's Python
  3.10 repair plan AND test cases ("批准本轮 Python 3.10 修复计划和测试用例"). This is
  implementation approval only — **NOT final human feature acceptance.**
- **Scope implemented (baseline `668b46a`, clean `feature/data-quality-debate-control`):**
  - `tradingagents/evidence/policy.py` — narrow `to_date` repair: a
    `_normalize_terminal_utc_z` helper guarded by a date+time-shape regex
    (`^\\d{4}-\\d{2}-\\d{2}.(?:\\d{2}|.*[0-9])Z$`, at least an hour component, so
    HH-only/HH:MM/HH:MM:SS/fractions all match) plus `_OFFSET_BEFORE_Z` (excludes a
    pre-existing offset before the `Z`) replaces only a legitimate terminal uppercase
    `Z` with `+00:00`; the final `datetime.fromisoformat` remains authoritative.
    Date-only `Z`, repeated `ZZ`, `zZ`/`Zz`, `+00:00Z`, and malformed dates/times are
    **not** rewritten; the raw parser behavior is retained (not universal rejection —
    native 3.12 natively accepts raw `...zZ`, native 3.9 rejects it); terminal lowercase
    `z` and repeated uppercase `ZZ` tested rejection still holds; offsets keep
    calendar-date semantics; legacy
    non-`Z` numeric/compact `to_date` behavior is preserved per interpreter
    (unchanged by this repair; compact `YYYYMMDD` acceptance expanded in 3.11, and
    the observed 3.12 acceptance is historical baseline only).
  - `tests/test_policy_to_date_python310.py` (new, additive) — 39 tests: `Z`≡`+00:00`
    ≡calendar date; separator variants (`T`, space, `Z`); time-granularity variants
    (HH-only/HH:MM/HH:MM:SS/fraction); date/datetime/offset unchanged; negatives
    (date-only `Z`, `ZZ`, `Zz`, `+00:00Z`, `z`, malformed, empty, None);
    **helper-boundary regression** proving malformed repeated/lowercase-`Z`/
    offset-before-`Z` suffixes are not rewritten; legitimate terminal-`Z` helper
    rewrites; interpreter-native parity for non-terminal-`Z` forms (`20260510`,
    `...zZ`); legacy numeric/compact **per-interpreter parity** with the unpatched
    native parser (bool rejected universally); deterministic pre-3.11 simulation
    (incl. HH-only/HH:MM); `_iso_date` numeric/bool boundary; real mocked StockTwits
    `fetch → capture → gate` (Medium/native-label/allowlist/privacy); future
    terminal-`Z` source rejection as `lookahead`.
- **Independent native old-parser findings (fixed):** an independent review extracted
  the production guard/helper/`to_date` AST and ran it under the local stdlib
  **Python 3.9.25** (a real older parser, NOT project 3.10 and not a 3.10 proof). It
  found (1) the original `...Z$` guard rewrote malformed `...ZZ` into `...Z+00:00`,
  which 3.9 accepted; and (2) a follow-up `\d{2}.*[0-9]Z` tightening rejected the
  supported HH-only/HH:MM shapes. The final guard keeps the two-hour-digit minimum
  with the pre-`Z` digit as a separate alternative so HH-only/HH:MM/HH:MM:SS/fractions
  normalize while `ZZ`/`zZ`/`+00:00Z` are not rewritten. Re-running the extracted
  production code on 3.9.25 (22-case accepted/rejected matrix) gave **0 failures**.
- **Verification outcomes:** new tests 39 passed; the two original CI-failing tests
  pass under the pre-3.11 simulation (2 passed / 0 sockets); focused/regression 191
  passed; `test_structured_evidence_ingestion.py` 53 passed; full strict-offline
  **2406 passed / 1 skipped / 1 deselected / 22 warnings / 88 subtests / 0 socket
  attempts**; `ruff check .` clean; governance **43/43 PASS**; `git diff --check`
  clean plus separate untracked-file whitespace check clean.
- **Limitations:** the pre-3.11 behavior is proven by a deterministic simulation plus
  extracted production-code execution under local Python 3.9.25 (a real older parser,
  never labelled 3.10 proof), not an actual Python 3.10 run; no 3.10 runtime is
  installed and none was authorized.

### 2026-11-12 — Independent OpenCode technical verification (COMPLETE) + `zZ` wording correction

- **Status:** independent OpenCode technical verification of the CURRENT covered offline
  scope is **COMPLETE**. This is **offline technical evidence only**, NOT a live/3.10
  CI proof and NOT human acceptance. Human plan+test approval remains
  **implementation-only**.
- **Independent results (supplied; recorded, not re-guessed):**
  - full strict-offline → **2406 passed / 1 skipped / 1 deselected / 22 warnings / 88
    subtests / 0 forbidden socket attempts**;
  - focused **5-module** subset (`test_policy_to_date_python310.py` +
    `test_structured_evidence_ingestion.py` + `test_market_evidence_gate.py` +
    `test_exact_claim_validation.py` + `test_debate_evidence_manifest.py`) → **240
    passed / 0 sockets** (a **different subset** than the builder's 191; not conflated);
  - the exact original 2 CI tests under the simulated pre-3.11 terminal-`Z` restriction
    → **2 passed / 0 sockets**;
  - extracted actual production helper+`to_date` AST with real **Python 3.9.25** stdlib →
    **22/22 checks pass**; same 22-case probe on **3.12.7** passes (NOT actual 3.10 or
    full-project 3.9 proof);
  - `ruff check .` clean; governance **43/43 PASS**; `git diff --check` clean; new
    untracked test file separately checked (trailing whitespace / extra EOF blank /
    secrets) → clean; SHA verification confirms the tested behavior; frozen files
    unchanged.
- **Honest `zZ` wording (docs-only correction):** the original **unmodified** 3.12
  `policy.to_date("2026-05-10T12:00:00zZ")` **already returns 2026-05-10**, whereas
  native 3.9 rejects it. The current helper leaves `zZ` unchanged, preserving that
  interpreter-native legacy behavior; **no new rejection was introduced in source** and
  `zZ` is **not** claimed globally rejected. Accurate claim: "malformed suffix is not
  rewritten and raw parser behavior is retained", with native-3.9 rejection documented
  specifically. Terminal lowercase `z` and repeated uppercase `ZZ` tested rejection
  still holds. The independent 22-case probe records `zZ` as **NATIVE PARITY**, not
  universal `None`.
- **Artifacts (backed up outside repo to
  `/Users/wangyiwen/OpenCodeRecords/TradingAgents`):** `python310-independent-full-offline.log`,
  `python310-independent-focused.log`, `python310-original-ci-simulation.log`,
  `python310-native39-date-checks.json`, `python310-native312-date-checks.json`.
- **Still pending:** explicit final **HUMAN acceptance** and the **actual new remote
  Python 3.10 CI** (no push authorized). No commit/push/new PR/merge/product live call.

## Local release merge — 2026-11-19 (human decision pending)

- Human instruction in the current conversation: merge local `release` into
  the current WebUI branch, resolve understandable conflicts, and ask at the end
  about conflicts requiring a decision. This authorizes this integration work;
  it is not a final acceptance or a GitHub review marker.
- Source heads: `feature/webui` at `1fc6727`, `release` at `79103c3`.
- Original conflicts: 78 file-location conflicts and 27 content conflicts.
  Location conflicts retain the established `src/` and `test/offline/` layout.
  Of the content conflicts, 25 are resolved; the two registry/schema files remain
  explicitly unmerged pending the decision below. No merge commit or push.
- All 123 release core/CLI files were compared by Git blob hash at their new
  paths: identical. Integration edits are limited to the Web streaming adapter,
  related deterministic tests, path-sensitive script/tests and governance merging.
- Both branch histories, original requirement/invariant identifiers and ADR
  files are retained. Overlapping numeric ADR prefixes are qualified by core vs
  WebUI and descriptive filename. Historical results/approvals are not current
  merged-tree results/approvals.
- The existing V1 default-deny OpenCode permissions are retained without new
  grants. The stronger WebUI `blocking-gate` is retained and also depends on the
  imported release governance-validation job; no check is waived.
- AI-log histories are retained in the existing entries envelope. The release
  reused AUL-020/021/022 for different events; date-qualified imported keys retain
  `original_id`, dates, scopes and review decisions. Tool display names are
  normalized to OpenCode under the existing human instruction; original release
  provenance remains available at `79103c3`.
- `.agents/` and `demo/` remain local, untracked and unstaged. They are not merge
  deliverables. No original frontend, demo, credential file or actual user data
  was read or changed for this integration.

### Actual verification

Commands ran with dotenv loading disabled, temporary test state and no real
provider calls. The main offline run also removed credential/provider variables
from the child environment and disabled sockets. Initial real-graph tests
attempted a market-data lookup after the release gate was added; that attempt
failed in the restricted environment. The test was repaired by supplying fixed
OHLCV at the I/O boundary while retaining the actual gate.

- Initial compatibility: `python -m pytest -q test/offline
  --ignore=test/offline/test_governance_scaffold.py
  --ignore=test/offline/test_ci_gates.py --disable-socket --allow-unix-socket
  -p no:cacheprovider --tb=short`: **2503 passed, 1 failed, 1 skipped**, 88
  subtests. The failure was the old Web real-graph fixture missing gate data.
- Final same command: **2508 passed, 1 skipped**, 88 subtests; **9.79 s**.
  The optional `langchain_aws` dependency was absent; its test skipped.
- `python -m pytest -q test/offline/test_ci_gates.py -k 'not schema and not
  registry and not distinct_objects' --disable-socket --allow-unix-socket
  -p no:cacheprovider --tb=short`: **33 passed, 10 deselected**, **0.35 s**.
  The deselected cases depend on the unresolved registry/schema.
- An earlier broader gate selection produced **51 passed, 2 failed, 8
  deselected**; the two failures were registry-ID tests parsing conflict markers
  in the deliberately unresolved JSON Schema. These are blockers, not passes.
- `python -m ruff check --no-cache src test scripts --output-format=concise`:
  **PASS** after two local import-order corrections.
- Workflow YAML, ten jobs, aggregate dependency on `governance-validation`, V1
  default-deny policy and unique imported AI-log keys: **PASS**. Core dependency
  direction, canonical layout and permission checks also passed in a clean
  temporary tree excluding local untracked directories.
- `git diff --check HEAD`: reports conflict markers only in the two unresolved
  requirements/schema files. Full governance validation and full-suite collection
  are **blocked/not passing** until these files are resolved.
- Live tests, paid APIs, remote GitHub CI and merge-commit creation: **not run**.

### Requirements/schema decision

Both files are newly authored on both branches and have incompatible formats:

| Aspect | WebUI branch | Release branch |
| --- | --- | --- |
| Entries | 26 | 22 |
| Identifiers | REQ-WEB-* | FR-DQG-*, FR-DDT-*, NFR-* |
| Type/priority | functional/invariant/etc.; must/should/etc. | Feature/NonFunctional; Must/Should/Could |
| Acceptance | fit_criteria list, IDs, verification contracts | fit_criterion object, threshold type, applicability and evidence status |
| Product scope | project purpose/scope/baseline | separate product PRD, stakeholder/success/tradeoff blocks |
| Schema/checker | test/ci_gates.py | scripts/validate/validate_requirements.py |

Recommended resolution for human review: use one consolidated format based on
the current WebUI registry, extend it to retain release's structured PRD and
acceptance/status information, preserve all 48 entries and original IDs, and
update both validators and their tests together. Do not drop a branch, silently
upgrade approval/verification status, or disable a checker. The alternative is
to use the release format as the base and migrate the 26 WebUI entries while
retaining their criterion IDs, dependencies, source and invariant references.
No choice has been recorded as approved; the files remain unmerged.

## Unified registry decision and completion — 2026-11-19

- Reviewer: current user in this conversation; no identity is inferred from the
  imported student's historical records. Date: 2026-11-19; exact message time is
  not exposed by the host.
- Decision: the user accepted the recommended resolution in the preceding
  "Requirements/schema decision" proposal: consolidate on the existing WebUI
  format, preserve all core/WebUI IDs and evidence, and update both validators.
  The current reply authorizes that integration work and completion of the
  original local merge request. It is not a fabricated final feature acceptance,
  safety approval marker or remote PR review.
- The earlier pending decision above is now superseded. Both conflicted files
  use canonical format 1.1 with **48 original requirements and 91 criteria**.
  The 26 WebUI entries are unchanged and remain draft; 22 core entries retain
  original title/type/status/origin metadata, tradeoffs, source/design/test
  mappings and evidence. `Implemented` becomes `implemented`, not `verified`.
- The release PRD is retained and extended with WebUI scope. Obsolete release
  scope deferrals remain under `product.historical_scope`; existing inherited
  implementations and the authorized layout are not called unimplemented.
- Each original core single criterion becomes a `fit_criteria` item with a
  deterministic criterion ID. Its typed threshold, applicability, verification
  explanation and evidence status are preserved. Zero-tolerance invariant units
  normalize to violations; their original descriptive units are retained.
  Historical evidence is explicitly scoped and cannot certify a newly verified
  requirement. No tests or YAML commands are automatically executed by validators.
- Both validator entry points enforce the canonical contract. The retained
  optional fallback covers only the schema's supported vocabulary and rejects
  unknown validation keywords. Real Draft 2020-12 remains the CI validator.
- The incoming regex-only JSONC parser damaged quoted `src/**` globs in the
  retained V1 permission file. A string-aware comment parser fixes this without
  widening permissions. Duplicate YAML keys and missing YAML support fail closed.
- Source integrity is pinned independently: the original 26 WebUI entries match
  SHA-256 `81df24e4f42a2cca59cea01cd194f28bea282a3d44d65d90ae5457ac6251a12b`;
  reconstructing all original core requirement fields after layout/tool-label
  normalization matches `0a85468de7021dd8826190089ed1e0b399a14616a8d2d211f81c9311adfac02b`.
  These prove migration fidelity, not runtime quality or human acceptance.
- `python -m test.ci_gates schema`: PASS. `python
  scripts/validate/validate_requirements.py`: PASS, 43/43 required artifacts,
  no likely secrets in the explicitly scanned artifact list.
- `python -m test.ci_gates permissions`: PASS. `python -m ruff check --no-cache
  src test scripts --output-format=concise`: PASS. Core/CLI/WebUI imports and both
  `python -m cli.main --help` and `python -m tradingagents_web --help`: PASS.
- After the first canonical conversion the scoped checks reported 5 failures:
  three existing diagnostic-case expectations plus the historical 22-ID count
  and singular criterion-field access. The diagnostics and format assumptions
  were updated while preserving negative checks; the final focused run reports
  **116 passed in 7.42 s**. An earlier complete offline run reports **2623 passed,
  1 skipped**, 88 subtests; the final complete run is **2624 passed, 1 skipped**,
  88 subtests, 23 warnings, **16.58 s**, with no offline suites excluded. See the
  fresh logbook entry for its exact command and environment.
- No real provider API, live benchmark, new dependency, push or remote CI run is
  claimed. `.agents/` and `demo/` remain local/untracked and outside the merge.

## Demo-based workspace UI replication — 2026-11-20

- User instruction: use `demo/` as the visual and interaction baseline, copy its layout/colour/type/spacing into `src/tradingagents_web/frontend/`, keep `demo/` unchanged, connect only real backend capabilities, and do not modify backend APIs, `src/tradingagents/`, or `src/cli/` without approval.
- Implemented a production React shell matching the demo: persistent sidebar, topbar search/announcements/settings, paper/dark themes, responsive mobile navigation, keyboard shortcuts, and the demo's warm-paper/pine-green visual language.
- Rebuilt Overview, Analysis history, Report detail, Backtest, Live Run, New Analysis, Decision journal, and announcement surfaces against existing APIs. Removed the demo preview-state selector and all sample report/backtest/progress fixtures from the production path.
- Added `src/styles/workspace.css` copied from `demo/styles.css`; no redesign of colours, type, spacing, or component shapes.
- Real data connections: `/api/history`, `/api/history/{id}`, `/api/backtests`, `/api/runs`, `/api/runs/{id}`, `/api/runs/{id}/events`, `/api/config`, `/api/config/models`, `/api/portfolio/validate`, `/api/checkpoints/clear`, and `/api/announcements`.
- Removed fixture-only company names/sectors and invented audit/comparison data. Available history metadata renders `Not recorded` when the backend does not supply it.
- Research audit and Policy comparison remain explicit interface-gap pages. The core capabilities exist but no WebUI read projection is exposed; the pages list the minimum required endpoints and do not render sample audit/comparison data.
- Frontend file-upload control reads portfolio JSON locally and fills the existing validation/submit path; no server-path upload capability was added.
- E2E fake server now sets a dummy `OPENAI_API_KEY` so its fixture secret is exercised by the real response-redaction layer instead of appearing in a screenshot.
- Verification:
  - WebUI backend suite: **165 passed**.
  - Frontend Vitest: **30 passed (9 files)**.
  - Chromium Playwright E2E: **6 passed**.
  - Offline regression: **2624 passed, 1 skipped, 88 subtests passed**.
  - `npm run typecheck`, `npm run lint`, `npm run build`: **PASS**; `npm audit`: **0 vulnerabilities**.
  - `ci_gates schema`: **PASS**. `ci_gates structure`: **BLOCKED** by the untracked `demo/` directory (`Unexpected obsolete source directory: demo`), which the user instructed to keep unchanged.
  - `mypy src/tradingagents_web`: **1 pre-existing error** in `runtime/graph_runner.py` (`UsageCapture` has no attribute `debate_config`); not introduced by this UI change and not repaired in scope.
  - Full suite including live tests: **1 failed** (`test_deepseek_live.py` attempted a network call while sockets were disabled). Reported as a live/network execution condition, not a UI regression.
- Deviations from the demo: the 8-step analysis panel preserves the existing tested CLI-parity flow instead of the demo's 3-step sample sheet; audit/comparison use explicit gap pages; fixture-only company metadata and sample charts are not fabricated.
- No backend route, core module, CLI module, dependency, commit, push, merge, or deployment change was made.

## Workspace visual-parity correction — 2026-11-20

- Scope source: the current user's direct instruction to inspect the integrated
  frontend against `demo/` and correct supported visual/interaction differences.
  This continues the preceding UI migration, not a new backend feature or final
  human acceptance. Existing user changes are retained.
- Plan and verification scope: frontend components, routes, styles, API clients,
  frontend tests, and these process/trace records. Compare matching viewport
  geometry and screenshots; exercise real local APIs through temporary fake
  runners; retain negative input, missing-artifact and privacy checks. No new
  dependency, backend route, core/CLI behavior, deployment or commit.
- Replaced the eight-step standalone form with the reference three-step modal
  sheet over the existing workspace. Added explicit stock/crypto selection,
  supported endpoint/thinking inputs, environment locks, local portfolio file
  selection, server validation, safe drafts and active-task handling.
- Matched the brand mark, header, reference table columns/filters, report cards,
  team markers, pipeline, running activity filter/counters, completed report,
  backtest form/results, decision/outcome/reflection dialog and settings flows.
  Tailwind theme/utilities remain; its conflicting preflight is excluded.
- History pagination is fully consumed before totals/filter/sort. A combined
  report is a fallback instead of a duplicate of individual sections. Missing
  ratings/counters stay absent; downloads depend on actual artifact availability.
  Read-only history metadata not exposed by the API remains `Not recorded`.
- The reference's sample content, simulated timings, preview switches and mock
  audit/comparison results are not production features. Audit/comparison remain
  unavailable because the current WebUI lacks their projections; no new routes
  were added. Existing translation catalogs are retained; the reference
  presentation and newly introduced text are English.
- Fresh verification: frontend **33 passed**, Chromium **10 passed**, lint,
  typecheck and production build **PASS**. The browser checks include desktop
  shell/sheet geometry within **0.75 CSS px**, all three steps, API completion and
  cancellation, backtests, downloads, journal dialogs, settings, privacy, both
  themes at 375/768/1024/1512px, landscape and reduced motion.
- Full network-isolated offline suite: **2624 passed, 1 skipped, 88 subtests**,
  52 warnings, 17.04 s. Optional `langchain_aws` is absent. Schema and permissions
  gates pass. Structure remains blocked by the intentionally retained `demo/`;
  no directory was deleted and no governance rule was weakened.
- Initial frontend tests failed on the old step selectors and duplicated chart
  labels. Initial browser runs also exposed obsolete selectors, animation during
  geometry measurement and selection of newly created records instead of the
  fixed missing-report fixture. These failures were corrected with explicit
  reference interactions, table-scoped assertions, reduced motion and stable
  fixture selection. Final checks above are actual reruns, not waived failures.
- Port 8000 was already occupied. Tests used an independently created temporary
  fixture server on 127.0.0.1:8008 and a temporary test configuration; the existing
  service was not stopped or reused. An approval-service connection interruption
  was retried through the same review mechanism. No real provider was called.
- The production build retains its bundle-size advisory. Real API calls,
  Firefox/WebKit, remote CI and final human acceptance are not claimed.

- Follow-up formatting and `git diff --check` pass. A broad scan still flags four
  untouched frontend files (listed in the logbook); unrelated formatting was
  left intact. The temporary fixture server has been stopped. Existing port-8000
  and prototype services were not stopped.

## Missing WebUI projections — scope and contract, 2026-11-20

The current user explicitly requested completing the backend interfaces missing
from the preceding UI integration. This authorizes the previously identified
read projections and their necessary frontend integration. It does not authorize
core/CLI changes, strategy tuning, arbitrary uploads, paid calls, deployment or
Git actions. This record is the implementation/test scope, not final human
acceptance or a fabricated independent test-review decision.

Plan version: `web-projections-20261120-v1`.

- Add bounded read-only audit endpoints for indexed analysis artifacts and live
  Web run identities, and allowlisted JSON/Markdown artifact preview/download.
  Return complete/partial/absent availability independently of usage completeness.
  Missing historical data remains absent; invalid JSON is explicitly invalid.
- Retain the four core audit families next to new Web run artifacts, using the
  existing shared report writer. Expose only safe effective run metadata, never
  endpoint credentials, portfolios, filesystem paths or checkpoint fingerprints.
- Add a catalog, per-case comparison and JSON download over the existing pure
  comparison runner and its controlled D/E/F fixtures plus G regression. Pairing
  uses actual core identities; selecting a different existing dynamic case must
  fail pairing. No client scripts, arbitrary result upload, model/data call,
  permanent report write or production budget tuning is introduced.
- Replace the audit/comparison unavailable pages with the unchanged demo layout
  bound to these APIs. The replay control refetches an actual deterministic
  server replay. Estimated data stays labelled; human rubric scores stay pending.
- Allowed implementation: `src/tradingagents_web/api/`, `artifacts/`, existing
  run writer/coordinator, application router registration, and frontend clients,
  pages/components/types; tests under `test/offline/` and frontend test folders.
  Maintain existing blueprint/ADR/trace/process records. No new dependencies.
- Prior verification strategy: core-writer fixtures and socket-isolated tests
  for real artifact shape, partial/legacy/invalid/oversized data, symlink/path
  escapes, secret/path redaction, stable run-local artifact association, safe
  metadata, unchanged core/CLI; exact D/E/F/G runner outcomes, mismatch refusal,
  invalid IDs and read-only replay/download; frontend negative states, filtering,
  provenance, budget/usage separation, previews/downloads and browser flows.
  Run previous frontend and complete offline suites without weakening assertions.


### Implementation evidence — `web-projections-20261120-v1`

Added the planned audit and comparison routes and replaced the two unavailable
pages with production API bindings in the reference layout. History/live report
links select the correct audit identity. Overview can display a recorded audit
summary. New run records preserve effective analyst/provider/model/depth/language
metadata; legacy records remain unspecified. The four run-local artifact copies
retain only structured origin/source-attempt/conflict descriptors in an optional
`web_context`, with explicit field allowlists and redaction. No core serializer,
algorithm, CLI, dependency or demo file changed.

Audit availability is separate from usage completeness. Invalid or contradictory
artifacts do not become successful empty audits. A saved folder date is never
used as an invented historical analysis cutoff. Run-ID audit responses retain
the coordinator's actual lifecycle for refresh. Comparison pairing delegates
to the real core identity check; G remains input exhaustion rather than an early
stop. Exports contain actual deterministic results, with human scores pending.

Verification: 2649 offline tests passed, 1 optional-dependency skip and 88
subtests passed; frontend 37 passed; Chromium 12 passed. Source/test/script lint,
frontend lint/typecheck/build, schema/permissions validators and diff whitespace
checks passed. See the evaluation logbook for initial corrections, the existing
mypy error, retained-demo structure blocker, local skill-script lint failures
and build-size advisory. No live-service or final human acceptance claim.
The temporary browser server uses isolated fixtures with environment credentials
excluded; existing port-8000 and demo services are outside this verification.

## Local commit and release synchronization authorization — 2026-11-20

The current user explicitly requested a local commit of the existing workspace,
excluding `.agents/` and `demo/` from version control, followed by pulling remote
`release` into local `release` and merging local `release` into `feature/webui`.
Both excluded directories were untracked before staging; root ignore entries
preserve their local contents without adding them to the index. The change does
not alter product behavior or require another product test run. Existing test
results and blockers above retain their actual scope. No push, deployment or
independent/final implementation acceptance is authorized by this Git operation.


## Release synchronization and conflict resolution — 2026-11-20

The user explicitly requested the local commit, remote release pull and merge
into `feature/webui`, then authorized resolving understandable conflicts and
confirmed continuing. The feature snapshot was committed as `b896308`; local
`release` fast-forwarded from `79103c3` to `24adf97`. This record describes merge
resolution, not independent implementation review or new acceptance of business
or safety changes.

Resolution decisions:

- Preserve both implementations: existing core/CLI/WebUI source is unchanged
  from `b896308`; imported `src/trading/` and `src/safety/` are byte-identical to
  `24adf97`. The new subsystem remains standalone, with no new WebUI execution
  endpoint or real broker path.
- Retain the canonical source/test layout. Incoming `tests/trading/` moves into
  `test/offline/trading/`; its opt-in live smoke moves to `test/live/trading/`.
  Adjust root/path constants and documentation only. Add package markers for
  offline/live tests to avoid shadowing the production `trading` package and
  colliding with existing test module names.
- Keep the existing schema 1.1 registry and validator protections. Preserve the
  original 48 entries without any object changes and import the ten TRD entries
  with original IDs, statements, tradeoffs, thresholds, status and historical
  evidence. Retain zero-tolerance invariants and the 100% rejection threshold;
  historical evidence is not promoted to current verification. Both validation
  paths reject weakened TRD invariants and evidence upgrades.
- Retain working V1 OpenCode permissions and the feature CI blocking gates,
  rather than replacing them with release's incompatible configuration format.
  Add the safety-module approval ask guard and explicit baseline-document read;
  preserve secret restrictions and plan/test/ADR gates. Merge subsystem rules,
  invariants, trace rows and distinct historical AI-use entries without claiming
  a new human approval.
- Keep `.agents/` and `demo/` ignored and untracked. Neither is deleted or
  incorporated into the merge.

Validation on the merged tree: socket-isolated offline suite **2896 passed,
1 optional AWS dependency skip, 88 subtests passed**; imported subsystem tests
contribute 244 cases. Frontend lint/typecheck and **37 unit tests** pass; schema,
permissions, the standalone registry validator, source/test/script lint and diff
whitespace checks pass. The original 48 entries and imported source byte parity
were checked explicitly. Browser tests were not rerun for this Git merge; WebUI
source is unchanged from its previously browser-verified snapshot. No live tests
or providers were run. Existing local demo structure/type-check limitations
remain as previously recorded; no gate was weakened to conceal them.

Initial merge checks exposed registry priority casing, a missing schema scope,
test-package shadowing and a trace-tag matcher limited to the old namespaces.
Those integration issues were corrected without changing business algorithms or
removing assertions. Final human feature acceptance remains pending.

## One-command WebUI startup — 2026-11-20

Scope/test plan: `web-startup-20261120-v1`. The current user approved the proposed
`--dev --open` and `--build --open` modes and explicitly requested README updates.
This is operational startup tooling over the existing WebUI, not a change to
analysis, trading, permissions or credentials. No independent test review or
final feature acceptance is claimed.

- Extend the existing CLI; keep default static-serving behavior. Development
  supervises one single-worker backend and local Vite, with automatic proxy-port
  propagation. Build mode runs the existing frontend build before serving static
  assets. Node/npm dependencies must already be installed; do not install them.
- Validate loopback host, distinct/ranged ports, source/dependency prerequisites
  and port availability. Refuse occupied ports without stopping other processes.
  Readiness checks use local health/Vite endpoints only; open the browser only
  after readiness. Exiting/interruption/startup failure stops owned processes.
- Ownership: existing `cli.py`, new `launcher.py` under the WebUI package,
  existing Vite configuration, README and existing architecture/process records.
  No dependency, lockfile, Docker, CI, permission, runtime-prompt or core/CLI change.
- Prior verification strategy: deterministic tests for exclusive flags, default
  behavior, invalid hosts/ports, missing tools/source/dependencies, failed build,
  child startup/exit/timeout/interruption and cleanup, browser readiness ordering,
  custom proxy ports; real local fixture-only process checks where authorized.
  Run source lint, frontend lint/types/build/tests and the complete offline suite.


### Implementation/verification — `web-startup-20261120-v1`

The existing module/installed command now supports `--dev --open` and
`--build --open`; `--frontend-port` customizes the development listener and
`--port` automatically controls its API proxy. Mode flags are exclusive and
non-loopback/invalid/duplicate or occupied ports fail before process startup.
Missing frontend source/tools/dependencies return actionable instructions and
are never installed automatically. The current interpreter starts the backend;
only owned child groups are stopped, including npm descendants. Startup waits
for direct health, the Vite client and proxied health before opening a browser.
Build failure never starts stale assets; default API-only/missing-static behavior
is retained. Frontend HMR is enabled; backend edits require restarting.

Validation: startup contracts 24 passed; full offline 2920 passed, 1 optional AWS
skip, 88 subtests; frontend 37 passed plus lint/types/build; scoped startup mypy
and source/test/script lint pass. Final Chromium E2E: 12 passed.
Actual marked, isolated-fixture smoke exercised both CLI modes and Ctrl+C cleanup, with no provider calls or real runtime data.
The evaluation logbook records initial harness corrections and evidence limits.
README, blueprint/ADRs and traceability are updated; core/CLI/trading, dependencies,
permission rules, ignored local directories and Git history remain unchanged.


## OpenCode documentation naming — 2026-11-20

The current user explicitly requested using OpenCode consistently for development
agent names across project documentation, including AI-use tool labels. This is
an editorial naming normalization, not evidence of a new tool session, execution,
contribution or review. Existing dates, outcomes, authorship responsibilities,
approval scopes and verification results remain unchanged. Historical prompt
role labels are included at the user's request; their binding rules, phases,
versions and human gates are unchanged. Product analyst/research/risk agent
names and model-provider identifiers retain their business meanings.

The change covers the entry-point title, README, blueprint actor label, tool
manifest, proposed governance ADR, prompt role wording and AI-use labels. Existing
uncommitted startup implementation is preserved. No product tests are needed for
this documentation-only change; YAML/JSON schema parsing and whitespace checks
are used. Ignored third-party skills and the standalone demo are not rewritten.


## Stage-based live activity — 2026-11-20

Scope/test strategy: `web-activity-20261120-v1`, requested directly by the
current user: show TUI-like process messages, prioritize Run activity, remove
excess prose, and automatically show each new stage with clickable progress
tabs for reviewing earlier stages. These instructions authorize this bounded
presentation change; no separate test-version review or final acceptance is
asserted.

- REQ-WEB-002/007/021; ADR-002-backend-framework-and-transport and
  ADR-003-frontend-stack; INV-WEB-001/003/012/014.
- Ownership: existing WebUI projector and run store, new frontend
  `components/RunActivity.tsx` and `utils/runActivity.ts`, LiveRunPage and
  index.css, focused offline/frontend/Chromium tests, existing process records.
- Four real stages: analysts, research debate, trading plan, risk review/final
  assessment. Tabs show recorded messages/reports and actual statuses; pending
  stages show an empty state. New stage entry selects its tab without moving
  keyboard focus. Older snapshots keep unassigned messages in All activity.
- Add optional stage/speaker metadata to existing message/tool events; retain
  replay, sequence checks, redaction, bounded buffers and terminal snapshots.
  Extract public text blocks only; project existing debate histories without
  publishing private reasoning metadata or inventing intermediate conclusions.
- Prior checks: stage transitions/auto-selection, manual and keyboard switching,
  pending/absent data, per-stage messages/reports, terminal recovery, safe text
  rendering, message classification/deduplication and history deltas; full
  offline regression, frontend lint/types/tests/build and local fake-run E2E.
- No core/CLI/trading/safety, dependency, credential, permission, runtime-prompt,
  provider-call, Git or deployment change. Existing working changes are retained.


### Implementation and verification — `web-activity-20261120-v1`

Run activity is now directly below essential run context and error banners.
Four progress tabs follow actual graph-stage entry and show each stage's public
messages, tool calls/results and report sections; manual/keyboard review remains
available. No recorded output is treated as execution authority or a fabricated
agent status. Existing public Bull/Bear/risk histories are included. Non-text
reasoning blocks are excluded, and existing coordinator redaction remains the
serialization boundary. Activity survives failure/cancellation/completion and
snapshot recovery; unknown historical provenance stays in All activity.

Long messages expand on demand, older-message scrolling pauses following, and
completed runs can switch to the existing complete report without duplicate
content. Oversized live cards and redundant explanatory banners are removed
from the live page only; overview/history reference layouts are retained.

Actual checks: offline 2927 passed, one optional-dependency skip, 88 subtests;
frontend 44 passed plus lint/types/build; final fresh-fixture Chromium 13 passed;
Ruff, scoped projector mypy, schema, permission and whitespace checks pass.
Structure remains blocked by the existing ignored demo directory. The evaluation
logbook records initial defects, test-harness timing/state corrections and
verification limits. Core/CLI/trading/safety and existing unrelated working
changes are preserved. No commit or final human acceptance has been recorded.


## Report table containment — 2026-11-20

Scope/test strategy: `web-report-table-20261120-v1`, directly requested by the
user after a screenshot showed a report table extending beneath the contents
sidebar. Limit changes to the shared Markdown renderer, scoped report CSS and
frontend tests, plus these existing process records. REQ-WEB-009/021, ADR-003,
INV-WEB-001/012/014 apply. Override inherited nowrap/last-column sizing only
inside Markdown, allow cell wrapping and give each table an accessible local
horizontal scroll container. Preserve table semantics, all content and existing
sanitization. Verify long text, many columns and unsafe markup; check desktop
sidebar containment and mobile page width/scrolling in Chromium, then run the
existing frontend and offline suites. No dependency, API, core, CLI, business
logic, credential, permission or Git change. No separate test-version review
or final human acceptance is asserted.


Implementation/verification: the report-only wrapper and CSS contain wide tables
without clipping content or changing sanitization. Frontend 46 passed plus
lint/types/build; fresh-fixture Chromium 14 passed; complete offline 2927 passed
with one optional AWS skip and 88 subtests; schema/whitespace checks pass.
Sidebar containment and horizontal keyboard scrolling are checked at desktop,
portrait and landscape widths. All earlier working changes remain present.
No Git commit or final human acceptance is recorded.


## English/Chinese interface — 2026-11-20

Scope/test strategy: `web-i18n-20261120-v1`, directly requested by the user.
REQ-WEB-014/021, ADR-003, INV-WEB-001/003/007/012/014 apply. Reuse existing
i18next/react-i18next with English and Simplified Chinese catalogues, a visible
workspace language control, persisted preference, document language and localized
dates. Cover navigation/settings/help, overview/history/reports/journal, wizard
labels/validation, activity/stages, audit/comparison and backtest controls.
Preserve canonical API values, ratings/REVIEW, report output language, model/tool
content, form drafts and active-run connections. No automatic report translation.

Ownership: existing frontend app/components/pages, utilities and i18n files;
new `i18n/ui.ts` helper within the established frontend directory; frontend
unit/Chromium tests and existing process/architecture records. No dependency,
backend, core/CLI, prompt, credentials, permission or Git change. Translation
catalogues contain Chinese under this explicit localization authorization;
code/comments/process prose remain English. Prior checks: key and interpolation
parity, no missing visible-string translations, switch/persistence/invalid saved
locale and storage failure, document language/date locale, dynamic stage/status
labels, wizard validation, canonical submitted values and unchanged report/tool
content; English regression plus Chinese responsive browser flows and offline
regression. No separate test-version review or final acceptance is asserted.


### Implementation/verification — `web-i18n-20261120-v1`

Implemented English/Chinese controls in the top bar, settings and analysis
wizard footer; persisted preference, HTML language and date formatting; matching
workspace catalogues and reactive localization throughout navigation, forms,
validation, activity, history, reports, journal, audit/comparison and backtests.
Explicit form option values, request payloads, report output language, ratings,
source Markdown/tool messages, drafts and active connections remain authoritative.
Known generated titles/windows localize only their display; custom values stay raw.
README, blueprint, ADR and traceability reflect the implementation.

Final checks: frontend 51 passed with lint/types/build; fresh-fixture Chromium
18 passed, including a single SSE connection through a live language switch;
full offline 2927 passed, one optional AWS skip and 88 subtests; schema,
permissions and whitespace checks pass. Existing ignored demo structure block
and Vite chunk warning remain. The evaluation logbook records initial issues,
corrections and browser/provider limits. Prior working changes remain intact.
No commit or final human acceptance is asserted.


## Per-analysis debate settings — 2026-11-20

Scope/test strategy: `web-debate-settings-20261120-v1`. The current user
explicitly requested implementing the previously described integration on
feature/webui: real-run fixed/dynamic mode, independent round caps, termination
thresholds, debate budgets/reserves and effective-configuration display. This
direct instruction authorizes the bounded integration; no independent test-file
review, GitHub approval marker or final acceptance is asserted.

Requirements: REQ-WEB-001/003/013/014, FR-DDT-004; invariants INV-WEB-001/003/
006/009/010/012/014 and core budget/compatibility rules. Ownership is restricted
to WebUI request models, config/run endpoints, runtime projection/coordinator/
writer, the existing graph adapter, new runtime/debate_policy.py and
runtime/analysis_graph.py, frontend wizard/client/locale resources, new
components/DebateSettings.tsx and utils/debateSettings.ts, focused offline/
frontend/Chromium tests and existing architecture/process records. No core/CLI/
trading/safety, dependency, permission, prompt, deployment or Git change.

Contract: accept an optional strictly typed allowlisted debate_termination
object and optional max_risk_discuss_rounds. Internal manifest/trace fields and
unknown keys are rejected. Reuse the core resolver for ranges/cross-constraints.
Preserve legacy research_depth mapping when advanced settings are absent.
Precedence for debate cap: environment lock, explicit nested cap, explicit legacy
depth, server defaults; risk cap: environment lock, explicit risk cap, legacy
depth, server default. Synchronize resolved root/nested debate caps before graph
construction. Return/persist only normalized public fields, not arbitrary config.
No mutation of DEFAULT_CONFIG or CLI preferences.

Recovery boundary: the core checkpoint signature covers rounds/analysts/assets/
portfolio but not all termination thresholds. The Web-only graph subclass will
reuse the core signature and append a deterministic policy fingerprint only
when non-cap debate settings differ from core defaults. Default policies retain
the original checkpoint identity; changed custom policies cannot resume each
other or a legacy/default checkpoint. Existing ledger checks remain in place.
No core execution/decision/budget algorithm is copied or weakened.

Prior verification: omitted/default/fixed/dynamic/custom/partial settings, strict
types, bool-as-number, NaN/Inf, cross-constraint and unknown/internal-key negative
cases; both environment locks and priority conflicts; normalized snapshots/
metadata/config immutability, cancellation/idempotency and core-graph forwarding;
checkpoint signature stability/isolation including threshold-only differences;
bilingual wizard edits, presets, independent risk rounds, safe draft restoration,
validation, canonical POST fields and effective policy reload/history display.
Run affected suites, complete socket-disabled offline regression, frontend
lint/types/tests/build and fresh local-fixture Chromium regression. Real provider
calls, monetary-cost claims and changes to scripted comparison cases are excluded.


### Implementation/verification — `web-debate-settings-20261120-v1`

Implemented the approved real-run integration in the existing WebUI. The wizard
now supports fixed/dynamic mode, independent round caps, thresholds and debate
budgets/reserves; effective settings persist through run snapshots and saved
reports. Strict public validation, environment precedence, legacy depth mapping,
read-only history projection and Web-only custom-policy checkpoint isolation
preserve core contracts. README, blueprint, ADR addenda and traceability are
updated. No protected core/CLI/trading/safety or dependency changes belong to
this iteration; prior working changes remain intact.

Frontend 57 passed with lint/types/build; fresh offline-fixture Chromium 21
passed; full network-isolated offline 2979 passed, one optional AWS skip and
88 subtests. Scoped mypy (six modules), Ruff, schema, permissions and whitespace
pass. The ignored demo structure block and Vite chunk warning remain. Initial
test-reference and browser assertion-type failures plus verification limits are
recorded in the evaluation logbook. No live-provider, commit, final human review
or CI approval claim is made.


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


### Implementation/verification — web-tui-parity-20261120-v1

Completed on 2026-11-21 after the authorized capability-parity scope began on
2026-11-20. Individual role events, selected-analyst timing, real report/agent
counts and reconnect preservation are integrated in the existing run view.
OpenRouter discovery/refresh preserves manual IDs and safely falls back to
cached/manual suggestions. Backtest interval input supports any positive whole
number. README, blueprint/ADRs and traceability are updated; prior working
changes remain intact. No language expansion, simulated trading, credential or
CLI preference writes, core/CLI changes, dependency changes or Git action.

Actual evidence: offline 2991 passed with one optional AWS skip/88 subtests;
frontend 59 passed with lint/types/build; Chromium 23 passed on a fresh fixture.
Ruff and five scoped mypy modules pass. graph_runner retains its pre-existing
UsageCapture.debate_config type error; ignored demo still blocks structure.
Initial test/fixture corrections and evidence limits are in the evaluation
logbook. No final human review or complete CI approval is claimed.


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

Implementation evidence: four bilingual simulation views and necessary Web
interfaces now compose the existing runtime, pipeline, approval gate, engine,
portfolio, audit and BacktestRunner. Packaging includes the existing trading
and safety packages; those source trees and CLI/core source remain unchanged.
Completed-cursor resume validates the original cursor and returns zero new
work, preserving the saved portfolio and avoiding duplicate execution.

Closing verification: offline 3025 passed / 3 failed / 1 optional skip; frontend
63 passed / 3 failed; Chromium 26 passed on the corrected tree. New failures
were corrected from the first logs without rerunning either unit suite, under
the user's single-final-run instruction. The unchanged-core determinism failure
remains open. Ruff, scoped mypy, ESLint, TypeScript/build, schema, permissions
and whitespace pass. Detailed commands, failure distinctions and limitations
are recorded in the evaluation logbook. Real providers were not called. These
are implementation results, not independent review or human acceptance. No Git
operation was performed.


## Frontend information simplification — 2026-11-21

Iteration: web-ui-simplify-20261121-v1. Direct user authorization: simplify
nonessential descriptions, displays, statistics and unnecessary navigation
throughout the frontend. Preserve current working changes and all capabilities,
backend contracts, warning/error states, human approvals and destructive-action
confirmations. No core, server, dependencies, permissions or Git changes.

Plan: focus the overview on latest/recent research; remove decorative copy,
placeholder company facts and duplicated summary/navigation blocks; reduce
history columns; disclose run counters, account rules and detailed comparison
identity/rubric on demand. Retain completed/partial/failed/REVIEW distinctions,
quote/source limitations, cost disclosure, money/holdings, pending/rejected
outcomes and failure reasons. Selecting a comparison case already runs replay;
keep its explicit refresh but remove duplicate case selector cards. Completed
simulation runs should not invite a no-work resume; interrupted/failed runs
retain resume. Routes, deep links, filtering, downloads and stage tabs remain.

Scope: existing frontend pages/components/app shell/styles/locales and affected
frontend tests/e2e; README and current ADR/trace/evaluation/AI-use records.
No new implementation modules. Existing REQ-WEB-001/002/006/007/008/010/011/
014/021 and FR-TRD-001..006 remain unchanged. Current instruction supersedes
prior strict demo geometry for the simplified surfaces.

Verification strategy before edits: use existing validation, approval, stage,
localization and browser tests, adapting only intentional presentation changes;
assert removed clutter is absent, diagnostic details are collapsed but accessible,
failed/pending states remain visible, deep links work and completed simulations
have no resume action. Run suites once in the closing phase with isolated local
fixtures, plus build/lint/types and document checks. No live providers or user
runtime data. This records direct authorization, not a separate human test-file
review or final acceptance.


Closing evidence for web-ui-simplify-20261121-v1: existing frontend surfaces are
simplified; preset comparison moves from the sidebar into help diagnostics.
Business APIs and protected source trees remain unchanged. Offline 3028 and
frontend 66 passed; Chromium 24 passed / 3 failed. Two stale presentation
selectors were corrected; the third case encountered a task conflict after the
first failure. No suite rerun is claimed. Lint/types/build and document checks
pass. Failure evidence and the optional screenshot approval-transport limitation
are recorded in the evaluation logbook. No merge-ready verdict or final human
acceptance is asserted.


## Backtest failure diagnostics — 2026-11-21

Iteration: web-backtest-errors-20261121-v1. Human source: reported backtest failure,
then confirmation that the server prints no traceback and screenshot of NVDA,
2026-10-21 through 2026-11-20, interval 7. Those inputs produce five valid grid
dates; the screenshot cannot establish the runtime exception. Read-only code
inspection confirms the coordinator discards every backtest exception without
logging it and returns a fixed internal-error sentence. No root cause such as
Yahoo throttling or wrong provider is claimed established.

Bounded repair plan: reuse existing redacted error classification/logging for
backtests, give backtest failures the correct task name, show the correlation ID
in the existing failure banner, and identify missing server API-key configuration
without exposing exception text. Keep all current analysis error behavior and
single-active lease release. Do not change core backtesting, model selection,
credentials, data vendors, public launch inputs, trading safety or dependencies.
Relevant REQ-WEB-006/011/013 and INV-WEB-003/014; ADR-007-run-controls.md owns the
lifecycle refinement. Allowlisted existing paths: Web errors/coordinator,
backtest display components/locales, README, existing backtest/analysis tests and current
ADR/trace/evaluation/AI-use/bug records.

Prior verification design: inject internal/config/authentication/rate-limit
failures through the real API/coordinator; assert categorized error and matching
server correlation, traceback presence with secret redaction, absence of private paths and raw
exception payload in the client, live-memory preservation, slot release and
subsequent run success. Browser failure fixture must show the same safe message
and correlation in place. Run each full offline/frontend suite once after the
repair; no live provider calls or real environment files. Direct user context
authorizes diagnosis and this bounded fix, not a fabricated test-file review or
final human acceptance.


Closing evidence for web-backtest-errors-20261121-v1: categorized/correlated
server and frontend diagnostics are implemented and verified offline. Offline
3034 passed / 1 optional skip / 88 subtests; frontend 66 and Chromium 28 passed.
Static/build/schema/whitespace pass; chunk warning remains. The user's original
exception is not recoverable from the old generic response and requires a new
run after restart. No core semantics, configured models, CLI, trading safety,
credentials or real services were changed or invoked. This is diagnostic repair
evidence, not proof that the user's underlying provider issue is resolved.


## Model environment defaults — 2026-11-21

Iteration: web-model-defaults-20261121-v1. Human source: current correction that
the provider variable should be a default and the analysis dropdown should
preselect it. Prior context explicitly identifies provider and quick/deep models
as the fields whose forced locking prevents selection. The user also confirmed
actual official DeepSeek usage; no remaining provider-routing failure is asserted.

Plan: make those three non-secret model-selection environment fields defaults
in the WebUI, allow explicit per-analysis overrides, and keep backtests on server
defaults. Add non-secret env_defaults provenance alongside existing env_locks;
retain environment enforcement for budget/rounds, checkpoint, language and other
unrelated settings. Preserve server-owned credentials. When the provider changes,
never inherit the prior provider's model IDs, endpoint or thinking options. The
caller supplies both new model IDs; an omitted provider reuses server defaults.
The configured endpoint remains authoritative for the server-default provider;
other selected providers use their own default or an explicit existing endpoint
override. This prevents sending another provider's credential to the default
provider's endpoint. No new provider, endpoint capability or credential input.

Frontend initialization: configured model defaults preselect the form ahead of
CLI preferences; explicit retry setup remains effective. Drafts retain chosen
models only while their recorded server-model-default baseline still matches;
legacy/stale model drafts cannot silently replace newly configured defaults.
Other draft fields and privacy boundaries remain. Switching back to the default
provider restores its configured models. Existing risk/budget locks still apply.

Ownership: existing Web api/config.py, api/runs.py, api/backtests.py, frontend
runClient/NewAnalysisPage/locales, existing offline analysis/backtest tests and
frontend/browser tests; README, blueprint, ADR-001-choice.md, current trace,
evaluation, review, bug and AI-use records. No core/CLI/safety/trading source,
real .env/keys, dependencies, prompts, permissions, Git or live-service actions.
Existing REQ-WEB-001/003/005/011/013 and INV-WEB-001/003/006/014 apply. Refine
existing architecture statements that previously treated every model variable
as a lock; retain original requirement IDs/status and historical evidence.

Prior verification design: API default projection and omitted request values;
explicit provider/models accepted despite environment defaults; wrong/missing
models on provider switch rejected; endpoint/thinking isolation and no secret
exposure; unchanged budget/language/checkpoint enforcement; backtest defaults
and no mutation of shared DEFAULT_CONFIG. Frontend configured preselection over
stale preferences/drafts, editable selection and returning models, private draft
persistence and canonical submission; Chromium real POST plus negative existing
validation. Run each offline/frontend/browser suite once after implementation,
with temporary data and no real model or market calls. Current direct correction
authorizes this bounded change, not an independent test-file review or final
human acceptance. The registry's legacy test_web_wizard.py reference is absent;
its draft status remains unchanged and current tests provide scoped evidence.


Closing evidence for web-model-defaults-20261121-v1: implementation follows the
bounded plan. Provider/model selection is editable end to end, default provenance
is public without secrets, backtests keep defaults, and provider-specific
endpoint/thinking fields do not cross providers. Offline 3040 passed / 1 optional
skip / 88 subtests; frontend 68 and Chromium 29 passed. Ruff, scoped mypy,
ESLint, TypeScript/build and document checks pass; chunk warning remains.
No core/CLI/safety/trading source changes, real key/environment access, live
providers or Git operation. Current human instruction is the authorization;
independent review and final acceptance have not been fabricated.


## Backtest per-date progress — 2026-11-21

Iteration: web-backtest-progress-20261121-v1. Direct human scope: add frontend
per-date progress so a long backtest does not appear stuck. The user changed the
model alias independently; the capability-table repair is not included.

Necessary integration: core run_backtest has no start/finish callback. Add an
optional, context-scoped, read-only observer in existing src/tradingagents/
backtest.py; publish initializing, cell started/completed/failed/skipped and
settlement started/completed/failed facts around the existing serial calls.
Preserve run_backtest arguments/results, propagation, exception handling,
settlement, memory paths, ordering, CLI behavior and budgets. No Web/HTTP import
in core, no global graph monkeypatch or duplicate backtest implementation.
Observer exceptions are isolated from business execution, and context cleanup
must occur on failure. This small core observability extension is necessary to
fulfill the current request and is covered by ADR-007-run-controls.md before
editing; no safety/trading/agent strategy changes or live calls are authorized.

Web ownership: new runtime/backtest_progress.py owns presentation progress state
under the existing BacktestRecord lock, snapshots and transition validation.
Existing runner/coordinator/API bridge real events and show summarization/terminal
phases. A paginated progress slice on GET /api/backtests/{run_id} uses optional
cells_offset/cells_limit; omitted offset follows the current cell, limits bound
returned detail. Counts distinguish success, failure and resume skips. Analysis
completion is separate from settlement/final completion. Public progress never
contains exception text, credentials, model messages or paths. Page refresh uses
the current process record; legacy disk artifacts have no invented progress.

Frontend ownership: new pages/Backtest/BacktestProgress.tsx and existing backtest
page/client/locales/styles render native progress, current ticker/date/elapsed,
per-date statuses and in-place pagination/follow controls. No ETA, simulated
percentage, new route, cancellation or extra navigation. Existing layout and
bilingual UI remain. Existing request defaults, models and core scoring stay.
Allowlist includes the above files, existing core/backtest/Web tests and local
fixture, README, blueprint and existing ADR/trace/review/evaluation/bug/AI-use
records. No dependencies, permissions, prompts, real .env/user state or Git work.

Requirements: REQ-WEB-006/007/011/021/026, INV-WEB-003/009/014 and current core
compatibility contracts. Existing IDs/status remain unchanged. Prior verification
scope: real core loop with fake graph barriers proves started snapshots before a
cell finishes, terminal/skip/failure facts, settlement phase, unchanged output/
order/memory and observer exception/context isolation; Web snapshots validate
unknown/duplicate events, concurrent poll consistency, pagination bounds and
refresh; frontend/browser actual progress at runtime, failed/skipped distinctions,
100% cell completion while still settling, bilingual/mobile layout and no fake
history progress or cancellation. Run each full offline/frontend/browser suite
once after implementation, isolated from real providers. Direct request is the
bounded implementation authorization, not independent test-file review or final
human acceptance.


Closing evidence for web-backtest-progress-20261121-v1: the implementation and
verification completed before interruption; this record is now closed under the
user's explicit commit/push instruction. Offline 3046 / 1 optional skip / 88
subtests, frontend 71 passed; initial Chromium 26 passed / 4 failed, followed by
four passing focused cases after the actual narrow-layout correction. All
original assertions remain. Desktop/mobile visual review completed. Ruff,
four scoped Web mypy modules, ESLint and build pass; explicit core mypy retains
two unchanged summarize optional-float errors. Historical broader type/structure
limits and chunk warning remain, so no complete CI/merge-ready verdict is made.

Publication scope is all current authorized feature/webui changes, retaining
ignored .agents/demo, real environment files, dependencies and generated output
outside Git. The user explicitly requested local commit and remote push; no
force push, merge, deployment or invented review approval is authorized.
