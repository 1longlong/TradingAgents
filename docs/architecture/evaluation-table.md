# TradingAgents WebUI Architecture Evaluation Table

Status: **Approved for documentation by the human owner on 2026-11-05.** This document separates the **evaluation plan** from **actual results**. Planned checks are not results. Iteration-1 verification has been executed; rows record their actual status.

## 1. Evaluation plan

| ID | Evaluation | Method | Environment | Pass criterion | Status |
| --- | --- | --- | --- | --- | --- |
| EVAL-01 | Dependency and license review | Inspect `fastapi`, `uvicorn`, and npm lockfile; run advisory audit | Approved dev/CI environment | No unapproved license; no unresolved high/critical advisory | Partially run: npm audit 0; pip-audit and license review pending |
| EVAL-02 | Backend contract | pytest + httpx/TestClient with fake graph runner | Offline, temp dirs | All API/event/error contracts pass | Executed: 58 passed |
| EVAL-03 | Security boundary | Host/Origin/CSRF, path traversal, secret scan, XSS payloads | Offline | Zero violations in the defined suite | Executed: 58 passed (backend/static contract suite) |
| EVAL-04 | Event latency | Local harness publishing N events; measure p95 delivery | Loopback, no model calls | p95 ≤ 1000 ms; no sequence gaps | Not run: no SSE in Iteration 1 |
| EVAL-05 | Packaging | Build wheel; inspect contents; install in clean venv; health check | Clean temp environment | `static/index.html` present; `/api/health` succeeds | Partially run: wheel contents verified; clean install pending |
| EVAL-06 | Browser matrix | Playwright on Chromium/Firefox/WebKit | Desktop, latest two stable majors | Core flows pass; no console errors | Not run: browser binaries/harness not executed |
| EVAL-07 | CLI/core regression | Existing offline suite + CLI help/import | Network-isolated | No new regression; inherited failures reported honestly | Executed: 1042 passed, 4 historical failures |
| EVAL-08 | Artifact parity | Compare web-written `message_tool.log`/section files with CLI layout | Temp `results_dir` | Same names and formats; no `full_states_log` | Partially run: read-only fixtures use CLI/API formats; write parity belongs to the run iteration |
| EVAL-09 | Backtest parity | Compare structured summary fields with `summarize()` | Fake/temp backtest | All fields match; live log untouched | Partially run: read-only summary test passed; launch/isolation not exercised |
| EVAL-10 | Frontend contract | `tsc --noEmit`, OpenAPI type drift, i18n key parity | CI | No drift; no missing keys | Partially run: typecheck/build/lint passed; Vitest/Playwright and OpenAPI generation pending |

## 2. Decision rationale (qualitative, not measured)

| Decision | Selected | Main alternative | Rationale |
| --- | --- | --- | --- |
| Backend | FastAPI + Uvicorn | Starlette-only; Flask; Django | Pydantic/OpenAPI/async/SSE fit the Python stack; single worker preserves the run model. |
| Transport | SSE | WebSocket; long polling | One-way events; built-in browser reconnection; less lifecycle code. |
| Frontend | React 19 + TS + Vite | Next.js; templates | Explicit user selection; SPA needs no SSR or second server. |
| UI | Tailwind + shadcn/Radix | MUI/Ant Design | Accessible primitives with controllable styling and no heavy lock-in. |
| Client state | Zustand + TanStack Query | Redux Toolkit | One active run needs a small store; server data benefits from query caching. |
| Run state | In-memory single run | File journal; database | Fits the confirmed process-lifetime reattachment and avoids new storage. |
| History | Read-only hash-id projection | Index database; raw paths | No second source of truth; no path leakage. |
| Keys | Server environment only | Browser input | Avoids transmitting plaintext credentials to a client. |
| Cancellation | Analysis only; backtest no-cancel | Fake backtest cancel | `run_backtest` has no hook; honest controls. |
| Downloads | Complete Markdown + zip | PDF/Word | Uses existing artifacts; no new renderer. |

These are design judgments, not benchmark results. They do not replace EVAL-01 through EVAL-10.

## 3. Actual results (executed checks only)

| Check | Method | Result | Date |
| --- | --- | --- | --- |
| Requirements YAML syntax and duplicate keys | Local Node `yaml` parser with `uniqueKeys: true` | Passed: 26 requirements parsed | 2026-11-05 |
| Requirements shape/IDs/enums/thresholds/invariant rules | Local targeted validator mirroring `req-schema.json` and `test/ci_gates.py` | Passed: 26 requirements, 69 unique criteria | 2026-11-05 |
| Source/architecture/invariant references and dependency cycles | Same local validator | Passed | 2026-11-05 |
| Blueprint anchor resolution | Local script over `architecture_refs` | Passed: all anchors resolve | 2026-11-05 |
| Official `python -m test.ci_gates schema` | Project entry point in `.venv` | **PASS** | 2026-11-05 |
| Official `python -m test.ci_gates structure` | Project entry point in `.venv` | **PASS** | 2026-11-05 |
| WebUI backend suite (Iteration 1 + 2) | `pytest test/offline/test_web_*.py` | **113 passed** | 2026-11-06 |
| CLI/reporting compatibility | `pytest test_cli_commands.py test_reporting.py` | **14 passed** | 2026-11-06 |
| Import smoke, web mypy, and ruff | `python -c ...`; `mypy src/tradingagents_web`; `ruff check ...` | **PASS** | 2026-11-06 |
| Full regression | `pytest --disable-socket --allow-unix-socket` | **1097 passed, 4 historical failures, 2 skipped, 88 subtests** | 2026-11-06 |
| Frontend Vitest | `npm run test` | **10 passed (4 files)** | 2026-11-06 |
| Frontend lint/typecheck/build | `npm run lint`, `npm run typecheck`, `npm run build` | **PASS** | 2026-11-06 |
| Frontend dependency audit | `npm audit --json` | **0 vulnerabilities** | 2026-11-06 |
| Wheel packaging | `pip wheel . --no-deps`; inspect archive | **new Iteration-2 modules and built static assets present** | 2026-11-06 |
| Static/API smoke | TestClient with built static | **/, /history, /api/health, /api/history → 200** | 2026-11-06 |
| Architecture experiments EVAL-01 to EVAL-10 | — | **Not run** | 2026-11-05 |
| Playwright Chromium E2E | `npm run e2e` | **4 passed** (history, wizard/live/report, cancel) | 2026-11-06 |
| Playwright Firefox/WebKit | — | **Not run**: excluded by user instruction | 2026-11-06 |
| Real GraphRunner/live model path | — | **Not run**: requires credentials/cost authorization | 2026-11-06 |

The documentation validation above does not verify the architecture, the runtime, packaging, latency, browsers, or dependencies. It only checks the written registry.

## 4. Not evaluated

- FastAPI/Uvicorn dependency and advisory status.
- npm dependency tree, license, and bundle size.
- Event latency and buffer behavior under load.
- SSE reconnection and snapshot behavior in real browsers.
- Clean install in a fresh environment (wheel contents were verified).
- Browser matrix.
- Backtest long-run behavior and memory growth.
- Security middleware under a production server (TestClient coverage exists).
- Any model or data-provider call.

## 5. Rules

1. A planned check is never reported as passing.
2. Results include method, environment, date, and exact output; no estimated scores.
3. Failed checks remain failures; they are not converted to skips or waivers.
4. Architecture changes require updating this table and the logbook.
5. Only `docs/architecture/evaluation-logbook.md` may record executed results.
