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
  - Playwright E2E was not executed (browser binaries and a fake-backend harness are not configured).
  - The real `GraphRunner` path was not exercised against a live model/data provider; automated tests use `FakeGraphRunner`. Live tests require separate credentials/cost authorization.
  - Clean install in a fresh environment, full mypy, Bandit, and pip-audit were not run.
  - Requirements registry statuses remain `draft`; no separate requirements-verification verdict is claimed.
- Test-version delta: the approved test hash `de2193180ffd42f17e13f6adb9c2b223fb38de85663ca1432873c248db0cdfca` changed to `542fc400fb2541fb1f25220791dc5eb41873280dc940b132d48064b345660cb1` after two test-support fixes during implementation: `parse_sse` now flushes the final SSE frame, and `_collect_events` stops on a `data:` line instead of the preceding `event:` line. No assertion was weakened. This test delta requires review.
- No commit, push, merge, deployment, or remote setting change was performed.
