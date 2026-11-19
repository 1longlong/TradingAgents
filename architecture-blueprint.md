# TradingAgents WebUI Architecture Blueprint

Status: **Architecture decisions approved for documentation by the human owner on 2026-11-05.** Iterations 1–3 are implemented under conversation approvals; implementation review, safety/governance markers, and dependency approval remain pending. The selected stack is recorded in ADR-001 through ADR-012.

Owner: human project owner. Prepared by the Docs role on 2026-11-05.

## 1. Authority and scope

This blueprint is subordinate to `AGENTS.md`, `Prompt.md`, `.agent/rules.md`, `.opencode/rules.md`, and `docs/code-governance/structural-constraints.md`. It extends the TradingAgents v0.5.0 baseline at commit `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f` on branch `feature/webui`. It does not replace the baseline, the CLI, the Python API, or any existing business rule.

The WebUI is a **local, single-user, single-active-run presentation layer**. It displays and orchestrates capabilities that already exist. It must not add analysis capability, data sources, model providers, trading behaviour, agent logic, or persistence.

<a id="goals"></a>
## 2. Goals

1. Expose the complete CLI analysis workflow through a browser: the eight selection steps, live run view, completion summary, and full I–V report.
2. Preserve every deterministic boundary already enforced by the core and CLI: ticker and path validation, analysis-date limits, rating integrity, portfolio semantics, point-in-time data access, memory isolation, and checkpoint behaviour.
3. Keep `src/tradingagents/` and `src/cli/` unchanged. The WebUI calls existing public Python interfaces, reads existing artifacts, and preserves CLI report formats. Web-only lifecycle metadata accompanies isolated Web run artifacts.
4. Provide read-only history over existing artifacts without a database or a retention change.
5. Expose the existing backtest capability with the same parameters and result semantics as the CLI.
6. Keep provider keys server-side. The browser never receives keys or server filesystem paths.
7. Support Chinese/English UI switching, independent of the report output language.
8. Keep the browser, HTTP surface, event stream, and frontend build isolated from the core.

<a id="non-goals"></a>
## 3. Non-goals

- Trading execution, order placement, position changes, or brokerage integration.
- New data vendors, model providers, model catalogues, prompts, agents, or rating rules.
- Multi-user accounts, tenants, billing, quotas, or authentication.
- New databases, message queues, caches, or cross-process run persistence.
- Cloud deployment, container orchestration, domain/TLS provisioning, or release automation.
- PDF or Word export; native mobile applications.
- Multi-ticker batch analysis outside the existing backtest command.
- Cross-run comparison, scoring dashboards, or backtest charts in the first release.
- Any change to CLI arguments, defaults, output, exit codes, or core behaviour.

## 4. Baseline code facts that constrain the design

| Fact | Evidence | Consequence |
| --- | --- | --- |
| Core configuration is a module-level singleton | `src/tradingagents/dataflows/config.py` (`_config`, `set_config`) | Two graphs with different configs must not run concurrently in one process. |
| The CLI message buffer is a module-level singleton | `src/cli/main.py` (`message_buffer = MessageBuffer()`) | The web layer owns its own run state and does not reuse this object. |
| The CLI streams the graph directly | `src/cli/main.py` (`run_analysis`, `graph.graph.stream`) | The CLI stream path is the behavioural reference for live updates. |
| `propagate()` writes a state log | `src/tradingagents/graph/trading_graph.py` (`_log_state`) | API-style runs may have `full_states_log_*.json`; CLI-style runs do not. |
| Decision memory is read-modify-write with atomic replacement | `src/tradingagents/agents/utils/memory.py` | Concurrent writers are not proven safe; the single-run rule protects the log. |
| Checkpoints are per-ticker SQLite databases | `src/tradingagents/graph/checkpointer.py` | A run can resume only when checkpointing was enabled and the process is available. |
| Report serialization is shared | `src/tradingagents/reporting.py` (`write_report_tree`) | The web layer calls this writer; it does not reimplement section layout. |
| Path safety is deterministic | `src/tradingagents/dataflows/utils.py` (`safe_ticker_component`) | The web layer reuses it for every ticker/run-id path component. |
| Rating extraction is deterministic | `src/tradingagents/agents/utils/rating.py` | The web layer does not infer or repair a rating. |
| Portfolio states are distinct | `src/tradingagents/portfolio.py` | No portfolio, an empty book, and a populated book are three different inputs. |
| Backtest is synchronous and has no cancellation hook | `src/tradingagents/backtest.py` (`run_backtest`) | The web layer does not pretend to cancel a backtest. |
| Stats and wall-time helpers exist | `src/cli/stats_handler.py`, `src/tradingagents/graph/analyst_execution.py` | The web layer reuses them for live statistics and timing. |

## 5. System context

```
Browser: React 19 + TypeScript + Vite SPA
  |  same-origin REST (JSON)
  |  same-origin SSE (text/event-stream)
  v
FastAPI + Uvicorn (single worker, 127.0.0.1)
  |-- Security middleware: Host / Origin / CSRF / CSP / size limit
  |-- Configuration projection (read-only)
  |-- Run coordinator (single active run, worker thread bridge)
  |-- Event projection and bounded SSE buffer
  |-- Artifact read model (hash identifiers, read-only)
  |-- Backtest surface
  v
Existing public Python interfaces and on-disk artifacts
  |-- TradingAgentsGraph (public methods)
  |-- run_backtest / summarize
  |-- write_report_tree
  |-- TradingMemoryLog (through existing graph methods)
  |-- results_dir, checkpoint directory, CLI preferences
```

The browser never imports Python, never receives a server path, and never receives a secret. The core and CLI never import the web layer.

## 6. Logical components

<a id="w1-entry-and-parameter-surface"></a>
### 6.1 W1 — Entry and parameter surface

Owned by `src/tradingagents_web/api/config.py`, `api/runs.py`, `models/requests.py`, and the frontend wizard.

Responsibility: render the eight selection steps, validate inputs, and submit a run request.

Inputs: ticker, analysis date, output language, analyst selection, research depth, provider and endpoint, quick/deep model, provider thinking parameters, checkpoint flag, portfolio JSON, and the announcement acknowledgement.

Outputs: a validated run request or a field-level error.

Rules:
- Validation mirrors the CLI and core rules; the core remains authoritative.
- The provider/API-key step displays `configured / not_configured / not_required` from the server environment and never accepts a key.
- Environment-locked values are shown as locked with their source, matching the CLI's "from environment" messages.
- Crypto detection filters out the fundamentals analyst, matching `filter_analysts_for_asset_type`.
- The request accepts only the allowlisted fields; the client cannot submit a config dictionary or a filesystem path.

Failure modes: invalid ticker, future date, no analyst, unknown provider/model, invalid portfolio, missing server key (allowed to start, fails at the first provider call).

<a id="w2-run-coordinator"></a>
### 6.2 W2 — Run coordinator

Owned by `src/tradingagents_web/runtime/coordinator.py`, `runtime/graph_runner.py`, and `runtime/artifacts_writer.py`.

Responsibility: own the lifecycle of the single active analysis run.

Inputs: a validated run request.
Outputs: a run record, an ordered event sequence, and final artifacts.

Ownership:
- Creates one fresh `TradingAgentsGraph` per run.
- Calls `create_run_state`, `begin_checkpoint`, `checkpoint_input`, `graph.stream`, `record_decision`, `clear_checkpoint_on_success`, `end_checkpoint`, `process_signal`, and `write_report_tree`.
- Owns cancellation, completion, failure, and reattachment.
- Holds the run record and event buffer in process memory only.
- Runs the synchronous graph stream in a single-worker `ThreadPoolExecutor`; events are pushed back with `loop.call_soon_threadsafe`.

Rules:
- At most one run may be active. A second submission is rejected with `409 conflict`.
- A browser disconnect does not cancel the run.
- Cancellation stops consuming, writes no decision entry, clears no checkpoint, ends the checkpoint scope in `finally`, and keeps artifacts already written.
- The coordinator never fabricates a rating. It reads the deterministic signal and surfaces `REVIEW`.
- The coordinator does not write `full_states_log_*.json`; it follows the CLI stream path.

<a id="w3-configuration-projection"></a>
### 6.3 W3 — Configuration projection

Owned by `src/tradingagents_web/api/config.py` and `runtime/config_projection.py`.

Rules:
- Reads `DEFAULT_CONFIG`, `TRADINGAGENTS_*` environment overrides, the provider table, the model catalogue, and `~/.tradingagents/cli_prefs.json`.
- Never writes the core configuration singleton except indirectly through `TradingAgentsGraph`, which the existing code already does.
- Environment precedence is displayed, not re-implemented differently.
- The CLI preferences file is read-only. Web runs do not write it.
- Responses exclude `project_dir`, `results_dir`, `data_cache_dir`, `memory_log_path`, and any credential value.
- `backend_url` is redacted of userinfo before display.

<a id="w4-event-projection"></a>
### 6.4 W4 — Event projection

Owned by `src/tradingagents_web/runtime/projector.py`, `runtime/event_buffer.py`, and `models/events.py`.

Event envelope: `run_id`, `seq`, `timestamp`, `type`, `payload`.

Required event types:

| Type | Payload (minimum) |
| --- | --- |
| `run.preparing` | ticker, trade_date |
| `run.started` | ticker, trade_date, asset_type, analysts, depth, provider, models, checkpoint flag |
| `run.resumed` | checkpoint step |
| `agent.status` | agent, status in {pending, in_progress, completed} |
| `message` | timestamp, message type, content |
| `tool_call` | timestamp, tool name, arguments |
| `report.section` | section key, title, content |
| `stats` | agents, llm calls, tool calls, tokens in/out, reports, elapsed |
| `run.completed` | signal, review flag, wall times, artifact ids, warnings |
| `run.failed` | category, safe message, correlation id |
| `run.cancelled` | cancelled_at |
| `snapshot` | current state, last_seq |
| `backtest.progress` | optional, cells done/expected |
| `backtest.completed` | structured summary |

Rules:
- Events are ordered by `seq`; reattachment replays from the last sequence.
- The stream is one-way. Client actions use REST endpoints.
- Payloads contain no secrets, absolute paths, stack traces, or raw credentials.
- The buffer is bounded by count and approximate bytes; an overflow sends a snapshot.
- Each subscriber has a bounded queue; a slow subscriber is dropped to snapshot mode.
- Heartbeat is an SSE comment every 15 seconds.

<a id="w5-artifact-read-model"></a>
### 6.5 W5 — Artifact read model

Owned by `src/tradingagents_web/artifacts/index.py`, `artifacts/readers.py`, and `artifacts/downloads.py`.

Sources:
- Legacy CLI run directory: `<results_dir>/<ticker>/<date>/` with `message_tool.log` and `reports/*.md`; the Web layer never rewrites it.
- Web run directory: `<results_dir>/web_runs/<run_id>/`, with the same message/section report formats and a `run.json` lifecycle sidecar. Each run has its own directory, including repeated analyses of the same ticker/date. The sidecar is artifact metadata, not an index database or cross-process task recovery mechanism.
- API-style state log: `<results_dir>/<ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json` when present.
- Saved report tree: `<results_dir>/reports/<ticker>_<timestamp>/` with `1_analysts` … `5_portfolio` and `complete_report.md`.
- Backtest run: `<results_dir>/backtest/<run_id>/` and its `trading_memory.md`.
- Decision memory: `~/.tradingagents/memory/trading_memory.md`, read-only.

Rules:
- Read-only. No deletion, rotation, migration, or index database.
- `artifact_id = sha256(relative_path)[:16]`; the server builds the id-to-path map on scan and never persists it.
- Every identifier resolves through a validated root allowlist and `safe_ticker_component`.
- Missing optional artifacts are reported as absent, not synthesized.
- History works for CLI-style runs that lack `full_states_log_*.json`.
- Scan limits: at most 500 runs, 50 per page, bounded report size.

<a id="w6-backtest-surface"></a>
### 6.6 W6 — Backtest surface

Owned by `src/tradingagents_web/api/backtests.py` and `runtime/backtest_runner.py`.

Rules:
- Parameters mirror the CLI: tickers, start, end, every, analysts, asset type, portfolio, run id.
- The summary mirrors `summarize(...)`: resolved, pending, unscored, per-rating count/hit rate/mean alpha, holding window, failures, settlement failures.
- The response does not include `log_path`; it includes an artifact id for the log.
- Backtest and live analysis remain isolated. The web layer does not point a backtest at the live memory log.
- A backtest is a run for the single-active-run rule.
- **Backtest cancellation is not offered.** `run_backtest` has no cancellation hook; the UI must not claim otherwise. Analysis cancellation is unaffected. A backtest can be resumed with `run_id` after an interruption.

<a id="w7-security-boundary"></a>
### 6.7 W7 — Security boundary

Owned by `src/tradingagents_web/security.py`, `errors.py`, and the frontend renderer. The full permission matrix is in `docs/architecture/permission-model.md`.

1. **Network**: bind to `127.0.0.1` only. Reject non-loopback `Host` headers. No authentication by confirmed scope; loopback, Host, Origin, and CSRF checks are mandatory compensating controls.
2. **Secrets**: provider keys come only from the server environment. The browser receives status only. Errors and events are redacted.
3. **Paths**: the browser receives artifact identifiers, not filesystem paths. Resolution uses `safe_ticker_component` and a root allowlist.
4. **Untrusted content**: model output, tool output, announcements, and artifact text are data. Render as escaped text or a sanitized Markdown subset. No raw HTML, no script execution, no `javascript:` or `data:` links, no server-side template evaluation.
5. **Requests**: state-changing requests require a CSRF token and a same-origin signal; no wildcard CORS. Body size is bounded.
6. **Files**: no generic file browser, upload-to-server-path, or download-by-path endpoint. Portfolio uploads are read as text, validated, and discarded.
7. **Logging**: no keys, cookies, authorization headers, absolute paths, or third-party prompt content.
8. **Headers**: CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `frame-ancestors 'none'`.

<a id="w8-frontend"></a>
### 6.8 W8 — Frontend

Owned by `src/tradingagents_web/frontend/` (source) and `src/tradingagents_web/static/` (build output).

Stack: React 19, TypeScript strict, Vite, Tailwind CSS, shadcn/ui (Radix primitives), Lucide, Zustand, TanStack Query, React Router, react-i18next, React Hook Form + Zod, react-markdown + remark-gfm + rehype-sanitize.

Rules:
- UI state derives from server events and snapshots; the frontend does not compute ratings or business decisions.
- The live view mirrors the TUI information set and adds a section switcher and full-content detail drawer.
- The report view mirrors sections I–V and the complete report.
- History and backtest views are read-only.
- Chinese/English strings are UI-only; report content follows the existing output-language setting.
- The app reconnects with a snapshot and an SSE `after_seq`.
- No raw HTML, no `dangerouslySetInnerHTML` for untrusted content, no external images by default.

## 7. Module ownership and dependency direction

<a id="proposed-ownership-paths"></a>
### 7.1 Ownership paths (approved for documentation)

| Element | Path | Owns |
| --- | --- | --- |
| Web package | `src/tradingagents_web/` | Presentation-only package; never imported by core or CLI. |
| App and entry | `app.py`, `cli.py`, `settings.py` | App factory, argparse/uvicorn, limits. |
| Security | `security.py`, `errors.py` | Host/Origin/CSRF/CSP, error taxonomy, redaction. |
| API | `api/session.py`, `api/config.py`, `api/announcements.py`, `api/runs.py`, `api/history.py`, `api/backtests.py` | HTTP contracts and validation. |
| Runtime | `runtime/coordinator.py`, `graph_runner.py`, `backtest_runner.py`, `projector.py`, `event_buffer.py`, `artifacts_writer.py` | Run lifecycle, thread bridge, events, artifact writes. |
| Artifacts | `artifacts/index.py`, `readers.py`, `downloads.py` | Read-only scan, parsing, downloads. |
| Models | `models/requests.py`, `responses.py`, `events.py` | Pydantic request/response/event schemas. |
| Frontend source | `frontend/` | React/TS source, i18n, tests. |
| Build output | `static/` | Generated assets; not committed. |
| Offline tests | `test/offline/test_web_*.py` | Deterministic contract/security/behavior tests. |
| Live tests | `test/live/test_web_live.py` | Requires external-service and cost authorization. |

### 7.2 Dependency direction

| From | To | Allowed | Notes |
| --- | --- | --- | --- |
| `tradingagents_web` | `tradingagents` | Yes | Public core interfaces only for business semantics. |
| `tradingagents_web` | `cli` | Yes, restricted | Reuse provider/model/prefs/stats helpers; no CLI global state mutation. |
| `tradingagents` | `tradingagents_web` | **No** | Core must not depend on presentation. |
| `cli` | `tradingagents_web` | **No** | CLI must not depend on presentation. |
| Frontend | `/api` | Yes | No direct Python, filesystem, or provider access. |
| `tradingagents_web` | DB/MQ/broker | **No** | No new persistence or messaging. |

## 8. Interface contracts

<a id="run-request"></a>
### 8.1 Run request

`POST /api/runs` accepts:

```json
{
  "client_request_id": "uuid",
  "ticker": "NVDA",
  "trade_date": "2026-11-05",
  "asset_type": "stock",
  "output_language": "English",
  "analysts": ["market", "social", "news", "fundamentals"],
  "research_depth": 1,
  "llm_provider": "openai",
  "backend_url": null,
  "quick_think_llm": "gpt-5.6-luna",
  "deep_think_llm": "gpt-5.6",
  "google_thinking_level": null,
  "openai_reasoning_effort": null,
  "anthropic_effort": null,
  "checkpoint": false,
  "portfolio_json": null
}
```

Validation:
- Ticker: CLI charset/length rules, then canonicalization.
- Date: `YYYY-MM-DD`, not in the future.
- Analysts: at least one known key; crypto excludes fundamentals.
- Depth: one of 1, 3, 5.
- Provider/model: resolve through the existing provider/catalogue code.
- Portfolio: validated by `PortfolioContext`; three states preserved.
- No client-supplied filesystem path or config dictionary is accepted.
- `client_request_id` deduplicates double submits within the active run.

Success: `201` with `{run_id, status, started_at}`. Conflict: `409`.

<a id="run-state"></a>
### 8.2 Run state

States: `idle`, `starting`, `running`, `cancelling`, `completed`, `failed`, `cancelled`.

Only one run may be in `starting`, `running`, or `cancelling`.

Run record: `run_id`, effective request fields, `status`, `started_at`, `finished_at`, `last_seq`, `signal`, `review`, `artifact_id`, `warnings`, a safe correlated error, report sections, the last 500 messages/tools, agent statuses, counters, and execution phase. Snapshot content and its event cursor are captured under the same lock.

`GET /api/runs/{run_id}` returns the snapshot; `GET /api/runs/{run_id}/events` returns SSE.

<a id="cancellation"></a>
### 8.3 Cancellation

1. Set the cancellation event.
2. Stop consuming the graph stream at the next chunk boundary.
3. End the checkpoint scope in `finally`.
4. Do not call `record_decision`.
5. Do not call `clear_checkpoint_on_success`.
6. Keep artifacts already written.
7. Mark `cancelled` and publish `run.cancelled`.

If checkpointing was disabled, the run cannot be resumed. If enabled, the existing checkpoint remains for the existing resume path. If the worker does not finish within 30 seconds, return `cancelling`; the single-run slot remains occupied until the worker exits.

<a id="reattachment"></a>
### 8.4 Reattachment

- The run continues while the server process lives.
- The client gets a snapshot, then connects to SSE with `after_seq`.
- The server replays the buffer or sends a snapshot if the sequence is too old.
- After a server restart the active run is gone; on-disk artifacts and checkpoints may remain for CLI/API paths. Cross-process recovery is out of scope.

<a id="report-artifact-contract"></a>
### 8.5 Report and artifact contract

- `write_report_tree` remains the only report-layout writer.
- Web runs use isolated `results_dir/web_runs/<run_id>/` directories; legacy CLI paths remain unchanged.
- The runtime artifact writer mirrors the CLI's `message_tool.log` and `reports/<section>.md` writes.
- On successful completion the coordinator auto-saves the complete report tree to `results_dir/reports/<ticker>_<timestamp>_<run_id>/`, retaining the existing report-tree format while preventing same-second collisions.
- Downloads resolve an artifact id server-side; `kind=complete|archive|section`.
- The complete Markdown report and a zip of existing report artifacts are the supported downloads. No PDF/Word.
- A report-save failure produces `run.completed` with `warnings: ["report_save_failed"]`; it does not rewrite the analysis result.

<a id="history-contract"></a>
### 8.6 History contract

- Read-only projection over the sources in Section 6.5.
- History item identified by a stable hash artifact id.
- Missing fields are shown as absent.
- No delete, rename, move, retention change, or index write.
- No server path is returned.

<a id="error-taxonomy"></a>
### 8.7 Error taxonomy

| Category | Meaning | Client behaviour |
| --- | --- | --- |
| `validation` | A request field is invalid | Show field errors; do not start |
| `conflict` | A run is already active | Explain and offer to view the active run |
| `not_found` | Run or artifact id does not resolve | Show a safe not-found message |
| `config` | Provider/model/key configuration is unusable | Show the safe configuration error |
| `upstream` | Data vendor or model provider failed | Show a safe retryable message; preserve the run record |
| `storage` | Artifact write/read failed | Show a safe storage message; do not expose paths |
| `cancelled` | The user cancelled | Show the cancellation state |
| `internal` | Unexpected failure | Show a generic message with a correlation id |

HTTP mapping: `422 validation`, `409 conflict`, `404 not_found`, `403 security`, `413 size`, `502 upstream`, `500 storage/internal`.

<a id="state-ownership-and-concurrency"></a>
## 9. State ownership and concurrency

| State | Owner | Storage | Lifetime | Writers | Readers |
| --- | --- | --- | --- | --- | --- |
| Active run record | `RunCoordinator` | Process memory | Until server exit or 5 min after terminal state | Coordinator only | API, SSE |
| Event sequence | `EventBuffer` | Bounded process memory | Run + 5 min | Projector only | SSE subscribers |
| Graph/checkpoint | `TradingAgentsGraph` | Core objects + SQLite | Run / existing checkpoint | Worker thread | Coordinator |
| Decision log | `TradingMemoryLog` via graph | Markdown file | Persistent | Graph only | History read model |
| Run artifacts | `RunArtifactWriter` | Existing `results_dir` layout | Persistent | Worker thread | History read model |
| History index | `ArtifactIndex` | Process memory cache | 5 s TTL | Scan only | History API |
| UI state | Zustand store | Browser memory | Tab lifetime | Frontend | Frontend |
| CLI preferences | `cli.prefs` | `~/.tradingagents/cli_prefs.json` | Persistent | CLI only | Config projection |

- One process, one active run, one worker thread. This is the synchronization mechanism for the global configuration, decision log, and checkpoint database.
- The artifact read model never writes.
- Introducing concurrent runs requires per-run configuration isolation, a serialized or owned decision-log writer, per-run artifact namespaces, and a lost-update test. This blueprint does not authorize that change.

<a id="deterministic-boundaries-preserved"></a>
## 10. Deterministic boundaries preserved

The web layer calls, not reimplements:

- `_validate_trade_date` and the core date rules.
- `safe_ticker_component` for every path component.
- `PortfolioContext` validation and fingerprinting.
- `extract_rating` / `parse_rating` and the `REVIEW` sentinel.
- `write_report_tree` for report layout.
- `TradingMemoryLog` through the graph's existing methods.
- `run_backtest` and `summarize` for backtest semantics.

The web layer never:

- Converts `REVIEW` to `Hold` or to a trade.
- Treats an absent portfolio as a flat book.
- Reads the live memory log from a backtest.
- Bypasses point-in-time filters.
- Accepts a ticker, run id, or path the core would reject.
- Exposes a provider key or server filesystem path.

## 11. Security and permission boundary

The full matrix is `docs/architecture/permission-model.md`. Summary:

- Loopback-only listener; no authentication; Host/Origin/CSRF/CSP compensating controls.
- Server-only provider keys; status-only UI.
- Artifact identifiers, not paths; root allowlist.
- Untrusted content sanitized; no raw HTML; URL scheme allowlist.
- No trading or position-changing endpoint.
- Destructive checkpoint clear requires explicit confirmation and is disabled during a run.
- History is read-only.
- Errors and logs are redacted.

## 12. Deployment, build, and packaging

- Python 3.10+; `pip install -e '.[dev,web]'`.
- Frontend: Node 22 LTS, npm, `npm ci`, `npm run build`.
- Build output: `src/tradingagents_web/static/`; not committed.
- Runtime entry: `tradingagents-web --port 8000` or `python -m tradingagents_web --port 8000`.
- Uvicorn single worker; `--host` restricted to `127.0.0.1`.
- `pyproject.toml` changes needed: `[web]` optional dependencies, `tradingagents-web` script, `package-data` for static assets. These require `[governance-approved]`.
- If `static/index.html` is missing, the server starts in API-only mode and reports a clear build instruction; it does not serve a broken UI.
- No container, cloud, domain, TLS, or orchestration work.
- Existing `results_dir`, `data_cache_dir`, and `memory_log_path` defaults apply. The web layer does not write `.env`.

## 13. Failure handling and recovery

| Failure | Run state | Decision log | Checkpoint | Artifacts | Client |
| --- | --- | --- | --- | --- | --- |
| Invalid request | none | unchanged | unchanged | none | 422 field errors |
| Active run conflict | existing run unchanged | unchanged | unchanged | unchanged | 409 with active run id |
| Model/data upstream error | `failed` | not written | preserved | partial kept | `run.failed upstream` |
| Worker exception | `failed` | not written | preserved | partial kept | `run.failed internal` |
| Analysis cancellation | `cancelled` | not written | preserved | partial kept | `run.cancelled` |
| Report save failure | `completed` + warning | written | cleared as normal | sections + message log kept; report tree may be absent | `run.completed` with warning |
| SSE buffer overflow | run continues | unchanged | unchanged | unchanged | `snapshot`, then live |
| Browser disconnect | run continues | unchanged | unchanged | unchanged | reattach or snapshot |
| Server restart | lost | persistent file intact | persistent DB intact | persistent | "run no longer available" |
| Artifact id invalid | no run | unchanged | unchanged | unchanged | 404 safe |
| Checkpoint clear during run | run continues | unchanged | not cleared | unchanged | 409 |
| Backtest long run | `running` until return | backtest log only | n/a | backtest dir | progress/summary; no cancel |

## 14. Verification plan versus actual results

### 14.1 Planned verification

- Structural: source layout, dependency direction, permissions, lint, types, dependency audit.
- Contract: request validation, event envelope, cancellation, reattachment, artifact ids, error taxonomy, provider/model parity.
- Regression: all existing offline tests; CLI help and import smoke checks.
- Negative: every feature has at least one invalid-input or forbidden-action test.
- Invariant: each `INV-WEB-*` has a violating test.
- Security: secret redaction, path traversal, Host/Origin/CSRF, untrusted rendering, size limits.
- Packaging: wheel contains static assets; clean install health check.
- Frontend: Vitest/RTL, MSW, Playwright on Chromium/Firefox/WebKit.
- Live: only with explicit external-service and cost authorization.

### 14.2 Actual results

**No product test, architecture spike, latency benchmark, browser matrix, dependency audit, packaging smoke test, or live test has been executed for this design.** The only executed checks are the documentation validations recorded in `docs/architecture/evaluation-logbook.md`. Planned results must not be reported as passing evidence.

## 15. Approval gates

Before product implementation:

1. Requirements registry and this blueprint reviewed; the design was approved for documentation on 2026-11-05, but the written artifacts need a review record.
2. Test plan and concrete test nodes approved via `[test-plan-approved]` on a test-only revision.
3. ADR-001 through ADR-007 reviewed; the new entry point needs `[safety-approved]` on the final head.
4. Dependency additions (`fastapi`, `uvicorn`, frontend npm packages) reviewed and approved.
5. `pyproject.toml` and CI changes approved via `[governance-approved]`.
6. Official `python -m test.ci_gates schema`, `structure`, lint, type, dependency, and security checks run in an environment with dev dependencies.
7. No implementation begins while a required approval or material is missing.

## 16. Traceability

The requirement-to-module-to-test mapping is in `docs/architecture/trace-matrix.md`. Invariants are in `docs/architecture/invariants.md`. Decisions are in `docs/architecture/adr/001-choice.md` through `007-run-controls.md`. Permissions, memory, runtime policies, risks, options, and evaluation records are in the corresponding documents under `docs/architecture/`.
