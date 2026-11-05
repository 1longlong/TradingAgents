# TradingAgents WebUI Evaluation Logbook

Status: **Approved for documentation by the human owner on 2026-11-05.** This logbook records evaluation activity. It separates planned checks from executed results. It is not product test evidence and does not claim implementation.

## 2026-11-05 — Requirements and architecture drafting

Scope: translate the confirmed requirements discussion into draft governance artifacts.

Artifacts: `docs/req/requirements.yaml` (26 requirements, 69 criteria), `architecture-blueprint.md`, ADR-001, invariants, trace matrix, risk list, runtime policies, memory design, option ledger, evaluation table, evaluation logbook, plus review/debt/AI-use records.

Outcome: drafts written. No product code, tests, dependencies, CI, commits, or live calls.

## 2026-11-05 — Design approval and decision recording

Scope: the human owner approved the presented architecture (TypeScript + React + UI technology, with delegated backend/transport/packaging decisions) and authorized updating the blueprint, ADRs, and applicable architecture records.

Decisions recorded:

- Backend: FastAPI + Uvicorn, single worker, loopback only.
- Transport: SSE.
- Frontend: React 19 + TypeScript + Vite + Tailwind + shadcn/Radix + Lucide.
- Client state: Zustand + TanStack Query; forms: React Hook Form + Zod.
- Markdown: react-markdown + remark-gfm + rehype-sanitize.
- i18n: react-i18next; English default, Chinese switch.
- Package: `src/tradingagents_web/`; `[web]` extra; `tradingagents-web` and `python -m`.
- History: read-only hash-id projection; no database.
- Downloads: complete Markdown + zip of existing artifacts.
- Run controls: single active run; analysis cancellation; **no backtest cancellation**.
- Preferences: read `cli_prefs.json`; do not write it.
- Security: loopback, no auth, Host/Origin/CSRF/CSP, server-only keys, no paths, sanitized rendering.

No architecture experiment was executed in this entry.

## Evaluation plan

The plan is in `docs/architecture/evaluation-table.md` (EVAL-01 to EVAL-10). Status: **all planned, none executed**.

Planned items:

1. Dependency/license/advisory review for FastAPI, Uvicorn, and npm packages.
2. Backend contract tests with a fake graph runner.
3. Security tests: Host/Origin/CSRF, traversal, secret scan, XSS.
4. Event latency p95 on loopback.
5. Wheel contents and clean-install health check.
6. Playwright browser matrix.
7. Existing offline regression and CLI smoke.
8. Artifact parity with the CLI layout.
9. Backtest summary parity and live-log isolation.
10. Frontend type drift and i18n key parity.

## Actual results

Only the checks below were executed. Everything else is unrun.

| Check | Method | Result | Date |
| --- | --- | --- | --- |
| Requirements YAML syntax and duplicate keys | Local Node `yaml` parser with `uniqueKeys: true` | Passed: 26 requirements parsed | 2026-11-05 |
| Registry shape, IDs, enums, thresholds, invariant rules | Local targeted validator mirroring the schema and gate | Passed: 26 requirements, 69 unique criteria | 2026-11-05 |
| Source/architecture/invariant references and dependency cycles | Same local validator | Passed | 2026-11-05 |
| Blueprint anchor resolution | Local script over `architecture_refs` | Passed: all anchors resolve | 2026-11-05 |
| Official schema gate | `python -m test.ci_gates schema` | **Not run**: `PyYAML`, `jsonschema`, `json5` absent | 2026-11-05 |
| Architecture experiments EVAL-01…EVAL-10 | — | **Not run** | 2026-11-05 |
| Product tests at drafting time | — | **Not run**: no implementation; see the iteration-1 execution entry below | 2026-11-05 |
| Live model/data tests | — | **Not run**: no authorization | 2026-11-05 |

The local validator is not a substitute for the official gate. No architecture, packaging, browser, latency, or security claim is supported by these results.

## 2026-11-05 — Iteration-1 test execution

Environment: Python 3.14.3, repo-local `.venv`; `pip install -e '.[dev]' fastapi uvicorn httpx`. The `[web]` extra does not exist yet, so equivalent test packages were installed directly; `pyproject.toml` was unchanged.

| Check | Command | Result |
| --- | --- | --- |
| New WebUI tests | `pytest test/offline/test_web_*.py` | **5 passed, 13 failed, 40 errors**; all failures/errors are `EXPECTED-UNIMPLEMENTED` |
| Passing WebUI subset | `test_web_contracts.py` | 5 core/CLI compatibility tests passed |
| Official schema gate | `python -m test.ci_gates schema` | PASS |
| Official structure gate | `python -m test.ci_gates structure` | PASS |
| CLI/reporting compatibility | `pytest test_cli_commands.py test_reporting.py` | 14 passed |
| Import smoke | `python -c 'import tradingagents, cli.main'` | OK |
| Ruff on new test files | `ruff check test/offline/test_web_*.py test/offline/web_fixture_app.py` | All checks passed |
| Existing regression excluding new WebUI tests | `pytest --disable-socket --allow-unix-socket` with four ignores | **984 passed, 4 failed, 2 skipped, 88 subtests passed** |

Classification:

- **Expected unimplemented:** 13 failures + 40 errors, all from `require_web()`/`require_frontend_file()` because `tradingagents_web` and frontend files do not exist. These are not skips and are not passing evidence.
- **Historical failures:** the 4 regression failures are the documented baseline failures (`test/live/test_no_data_handling.py::...`, three `test/offline/test_ohlcv_cache_freshness.py` tests). No new regression was introduced.
- **Test defects:** none identified in this execution. Contract assumptions in the test report remain subject to review.

Not run: architecture experiments EVAL-01…EVAL-10, Playwright browser execution, frontend Vitest, packaging/clean install, full mypy, Bandit, and live model/data calls.

## 2026-11-06 — Iteration-1 implementation verification

Environment: Python 3.14.3, repo-local `.venv`; Node 24.13.0 / npm 11.6.2.

| Check | Command | Result |
| --- | --- | --- |
| WebUI tests | `pytest test/offline/test_web_*.py` | **58 passed** |
| Full regression | `pytest --disable-socket --allow-unix-socket` | **1042 passed, 4 failed, 2 skipped, 88 subtests passed** |
| Schema gate | `python -m test.ci_gates schema` | PASS |
| Structure gate | `python -m test.ci_gates structure` | PASS |
| Web package types | `mypy src/tradingagents_web` | Success, no issues |
| Web package/tests lint | `ruff check ...` | All checks passed |
| CLI/reporting compatibility | `pytest test_cli_commands.py test_reporting.py` | 14 passed |
| Frontend lint | `npm run lint` | PASS |
| Frontend typecheck | `npm run typecheck` | PASS |
| Frontend build | `npm run build` | PASS; output in `src/tradingagents_web/static/` |
| Frontend audit | `npm audit --json` | 0 vulnerabilities |
| Wheel inspection | `pip wheel . --no-deps` + `unzip -l` | `tradingagents_web/static/index.html` and `tradingagents-web` entry point present |
| Static/API smoke | TestClient with built static | `/`, `/history`, `/api/health`, `/api/history` → 200 |

Classification:

- **Passing:** all 58 Iteration-1 tests, schema/structure gates, new-package mypy, ruff, frontend lint/typecheck/build, audit, wheel contents, and static/API smoke.
- **Historical failures:** the 4 full-regression failures are the documented baseline failures; no new regression.
- **Not run:** Playwright browser execution, frontend Vitest (no test files yet), clean install in a fresh environment, full mypy, Bandit, pip-audit, live model/data calls.
- **Residual gaps:** behavioral i18n report-language independence, browser matrix execution, and runtime XSS remain unverified beyond static contracts. The Iteration-1 implementation received a human review **APPROVE** on 2026-11-06; requirements statuses remain `draft`, and the approval is not a separate requirements-verification verdict.

## 2026-11-06 — Iteration-2 implementation verification

| Check | Command | Result |
| --- | --- | --- |
| WebUI backend suite | `pytest test/offline/test_web_*.py` | **113 passed** |
| Full regression | `pytest --disable-socket --allow-unix-socket` | **1097 passed, 4 historical failures, 2 skipped, 88 subtests** |
| Schema/structure gates | `python -m test.ci_gates schema`, `structure` | PASS |
| Web package types/lint | `mypy src/tradingagents_web`; `ruff check ...` | PASS |
| Frontend Vitest | `npm run test` | **10 passed (4 files)** |
| Frontend lint/typecheck/build | `npm run lint`, `npm run typecheck`, `npm run build` | PASS |
| Frontend audit | `npm audit --json` | **0 vulnerabilities** |
| Wheel inspection | `pip wheel . --no-deps`; inspect archive | new Iteration-2 modules and static assets present |

Classification:

- **Passing:** the Iteration-2 backend and frontend tests, the complete regression except the four documented historical failures, schema/structure, new-package mypy/ruff, frontend checks, audit, and wheel contents.
- **Historical failures:** the four documented baseline failures remain; no new regression.
- **Not run:** Playwright browser execution, the real `GraphRunner` path against a live model/data provider, clean install, full mypy, Bandit, pip-audit, and live tests.
- **Residual gaps:** the real analysis path has not been exercised with credentials; requirements statuses remain `draft`; no separate requirements-verification verdict has been issued.

## Decisions and open items

Resolved for documentation: framework, transport, frontend stack, UI library, package path, history source, key handling, cancellation policy, downloads, preferences.

Still required before implementation:

1. Dependency/license/advisory approval.
2. `[test-plan-approved]` on a test-only revision.
3. `[safety-approved]` for the new entry point.
4. `[governance-approved]` for `pyproject.toml` and CI changes.
5. Official schema/structure/lint/type/dependency/security checks in an approved environment.
6. Concrete test nodes and fixtures.
7. Any live-test authorization before live verification.
8. Permission-model and blueprint review records.

## Historical context

The four inherited baseline failures and the mypy/Bandit findings in `docs/bug-diary.md` and `docs/debt-register.md` remain open. They are not repaired, waived, or reclassified by these documents.
