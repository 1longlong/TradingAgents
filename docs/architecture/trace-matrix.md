# TradingAgents WebUI Trace Matrix

Status: **Approved for documentation by the human owner on 2026-11-05.** Iteration 1 is implemented. Execution on 2026-11-06 produced **58 passed** for the WebUI suite; full regression produced **1042 passed, 4 historical failures, 2 skipped, 88 subtests passed**. The `Evidence status` column remains conservative: passing local tests do not replace a human verification verdict. Behavioral frontend gaps (browser execution, runtime XSS, i18n report-language independence) remain. The module paths are the approved ownership paths from `architecture-blueprint.md` Section 7; see `docs/architecture/evaluation-logbook.md`.

Legend:
- **Module**: primary implementation owner.
- **Planned test**: the node expected to provide the machine check.
- **Monitor**: the runtime signal a reviewer or operator can inspect.
- **Evidence status**: `planned` unless an actual result is recorded in `docs/architecture/evaluation-logbook.md`.

## Requirements to modules and tests

| Requirement | Module | Planned test | Monitor | Evidence status |
| --- | --- | --- | --- | --- |
| REQ-WEB-001 | `api/config.py`, `api/runs.py`, `models/requests.py`, `frontend/src/pages/NewAnalysis` | `test/offline/test_web_wizard.py` | Run request validation; env-locked fields | planned |
| REQ-WEB-002 | `runtime/coordinator.py`, `runtime/projector.py`, `frontend/src/pages/LiveRun` | `test/offline/test_web_events.py` | Event sequence; statuses; stats | planned |
| REQ-WEB-003 | `runtime/coordinator.py`, `api/runs.py`, `frontend/src/pages/NewAnalysis` | `test/offline/test_web_runs.py` | Checkpoint flag; clear audit line | planned |
| REQ-WEB-004 | `api/runs.py`, `models/requests.py`, `frontend/src/components/PortfolioEditor` | `test/offline/test_web_portfolio.py` | Portfolio fingerprint; three-state label | planned |
| REQ-WEB-005 | `runtime/coordinator.py`, `api/runs.py` | `test/offline/test_web_runs.py` | `cancelled`; no decision entry; checkpoint present | planned |
| REQ-WEB-006 | `runtime/coordinator.py`, `api/runs.py` | `test/offline/test_web_runs.py` | 409 conflict; single active run | planned |
| REQ-WEB-007 | `runtime/coordinator.py`, `runtime/event_buffer.py`, `frontend/src/hooks/useRunStream` | `test/offline/test_web_events.py` | Snapshot + replay; reconnect | planned |
| REQ-WEB-008 | `artifacts/readers.py`, `frontend/src/pages/Report` | `test/offline/test_web_reporting.py` | I–V sections; REVIEW warning; wall times | planned |
| REQ-WEB-009 | `runtime/artifacts_writer.py`, `artifacts/downloads.py`, `api/history.py` | `test/offline/test_web_reporting.py` | Run directory layout; downloads | planned |
| REQ-WEB-010 | `artifacts/index.py`, `artifacts/readers.py`, `api/history.py` | `test/offline/test_web_history.py` | History sources; no writes | planned |
| REQ-WEB-011 | `runtime/backtest_runner.py`, `api/backtests.py` | `test/offline/test_web_backtest.py` | Summary fields; isolated log | planned |
| REQ-WEB-012 | `api/announcements.py`, `frontend/src/components/Announcements` | `test/offline/test_web_announcements.py` | Fallback; acknowledgement gate | planned |
| REQ-WEB-013 | `api/config.py`, `security.py`, `models/responses.py` | `test/offline/test_web_security.py` | Key status; no key value | planned |
| REQ-WEB-014 | `frontend/src/i18n`, `frontend/src/components/LanguageSwitch` | `test/offline/test_web_frontend_contract.py` | UI language; report language | planned |
| REQ-WEB-020 | `settings.py`, `security.py` | `test/offline/test_web_security.py` | Bind address; Host/Origin checks | planned |
| REQ-WEB-021 | `frontend/`, `playwright.config.ts` | `test/offline/test_web_frontend_contract.py` | Browser matrix | planned |
| REQ-WEB-022 | `runtime/event_buffer.py`, `runtime/projector.py` | `test/offline/test_web_events.py` | Event latency; sequence gaps | planned |
| REQ-WEB-023 | `security.py`, `errors.py`, `models/responses.py` | `test/offline/test_web_security.py` | Redaction; response scan | planned |
| REQ-WEB-024 | `artifacts/index.py`, `security.py` | `test/offline/test_web_security.py` | Identifier resolution; traversal rejection | planned |
| REQ-WEB-025 | `frontend/src/components/Markdown.tsx`, `security.py` | `test/offline/test_web_security.py` | Escaped output; blocked schemes | planned |
| REQ-WEB-026 | `src/tradingagents_web/`, `test/offline/test_web_contracts.py` | `test/offline/test_web_contracts.py`, `test/offline/test_cli_commands.py` | Structural gate; CLI contract | planned |
| REQ-WEB-027 | `src/tradingagents_web/`, route inventory | `test/offline/test_web_contracts.py` | No prompt/vendor/execution changes | planned |
| REQ-WEB-028 | `api/runs.py`, `runtime/coordinator.py` | `test/offline/test_web_portfolio.py`, `test/offline/test_web_contracts.py` | Portfolio fingerprint; REVIEW | planned |
| REQ-WEB-029 | `runtime/coordinator.py` | `test/offline/test_web_runs.py` | Single run; cancellation audit | planned |
| REQ-WEB-030 | `runtime/backtest_runner.py`, `artifacts/index.py` | `test/offline/test_web_backtest.py`, `test/offline/test_web_history.py` | Isolated log; read-only history | planned |
| REQ-WEB-031 | `security.py`, `frontend/src/components/Markdown.tsx` | `test/offline/test_web_security.py` | No execution; escaped content | planned |

## Invariant coverage

| Invariant | Enforcement module | Planned violation test | Evidence status |
| --- | --- | --- | --- |
| INV-WEB-001 | Package boundary; `test_web_contracts.py` | `test/offline/test_web_contracts.py::test_core_and_cli_surface_unchanged` | planned |
| INV-WEB-002 | Route inventory; no execution API | `test/offline/test_web_security.py::test_no_execution_endpoint_exists` | planned |
| INV-WEB-003 | `api/config.py`, `models/responses.py`, `errors.py` | `test/offline/test_web_security.py::test_secrets_never_serialized` | planned |
| INV-WEB-004 | `artifacts/index.py`, `models/responses.py` | `test/offline/test_web_security.py::test_responses_contain_no_filesystem_paths` | planned |
| INV-WEB-005 | `api/runs.py`, `artifacts/index.py` | `test/offline/test_web_security.py::test_path_traversal_is_rejected` | planned |
| INV-WEB-006 | `models/requests.py`, `api/runs.py` | `test/offline/test_web_portfolio.py::test_three_portfolio_states_remain_distinct` | planned |
| INV-WEB-007 | `runtime/coordinator.py`, `frontend/src/pages/Report` | `test/offline/test_web_contracts.py::test_review_is_not_hold` | planned |
| INV-WEB-008 | `runtime/backtest_runner.py` | `test/offline/test_web_backtest.py::test_backtest_does_not_touch_live_memory` | planned |
| INV-WEB-009 | `runtime/coordinator.py` | `test/offline/test_web_runs.py::test_second_run_is_rejected` | planned |
| INV-WEB-010 | `runtime/coordinator.py` | `test/offline/test_web_runs.py::test_cancel_preserves_checkpoint_and_writes_no_decision` | planned |
| INV-WEB-011 | `artifacts/index.py`, `artifacts/readers.py` | `test/offline/test_web_history.py::test_history_endpoints_are_read_only` | planned |
| INV-WEB-012 | `frontend/src/components/Markdown.tsx`, `security.py` | `test/offline/test_web_security.py::test_untrusted_content_is_escaped` | planned |
| INV-WEB-013 | `settings.py`, `security.py` | `test/offline/test_web_security.py::test_non_loopback_host_header_is_rejected` | planned |
| INV-WEB-014 | `api/backtests.py`, `runtime/projector.py` | `test/offline/test_web_backtest.py::test_no_backtest_cancel_route`, `test/offline/test_web_events.py::test_no_fabricated_agent_error_status` | planned |
| INV-WEB-015 | `app.py`, `cli.py`, packaging test | `test/offline/test_web_contracts.py::test_missing_static_assets_fail_loudly` | planned |

## Test suites by layer

| Suite | Command (planned) | Purpose | Status |
| --- | --- | --- | --- |
| Backend offline | `python -m pytest -q test/offline/test_web_*.py` | API, runtime, security, artifacts, backtest | not implemented |
| Existing regression | `python -m pytest -q test/offline --disable-socket --allow-unix-socket` | Prove no regression | not run for this change |
| Frontend unit | `npm run test -- --run` | Store, hooks, components, i18n | not implemented |
| Frontend build | `npm run build` | Typecheck and assets | not run |
| E2E | `npm run e2e` | Chromium/Firefox/WebKit flows | not implemented |
| Packaging | build wheel + clean install + `/api/health` | Static assets and entry point | not run |
| Live | `python -m pytest -q test/live/test_web_live.py` | Real model/data path | not authorized |

## Traceability rules

1. Every new or modified web module or function cites its requirement and invariant IDs in its module or function documentation.
2. Every acceptance criterion in `docs/req/requirements.yaml` has at least one planned test node here.
3. Every invariant has a test that fails when the invariant is violated.
4. A changed requirement or test plan needs a new human review before dependent implementation.
5. This matrix is updated in the same change as the code or test it maps.
6. `planned` never means `passing`; only `docs/architecture/evaluation-logbook.md` records executed results.
