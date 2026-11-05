# TradingAgents WebUI Invariants

Status: **Approved for documentation by the human owner on 2026-11-05.** These invariants extend the baseline safety boundaries to the web presentation layer. The violation tests are planned; **none has been executed**. A planned test is not passing evidence.

## INV-WEB-001 — Core and CLI behaviour is unchanged

Statement: Adding the WebUI must not change the observable behaviour, arguments, defaults, output, exit codes, imports, or public contracts of `src/tradingagents/` or `src/cli/`.

Enforcement: `src/tradingagents_web/` is a sibling package. `tradingagents` and `cli` never import it. `test/offline/test_web_contracts.py` compares the exposed surface; the existing regression suite runs unchanged.

Violation test: `test/offline/test_web_contracts.py::test_core_and_cli_surface_unchanged` (planned).

Fallback: Revert the web change; do not modify the core or CLI to accommodate presentation needs.

## INV-WEB-002 — Model output is advisory, never execution authority

Statement: No web control, event, report, or model response may place an order, change a position, or be treated as an instruction to execute a trade. The final rating remains an analysis output.

Enforcement: No execution route exists in `api/`; no brokerage dependency; ratings are rendered only.

Violation test: `test/offline/test_web_security.py::test_no_execution_endpoint_exists` (planned).

Fallback: Remove the offending endpoint or control; keep the rating advisory.

## INV-WEB-003 — Secrets remain server-side

Statement: Provider keys, tokens, authorization headers, cookies, and credential-like values must never appear in browser responses, events, logs, reports, downloads, errors, or snapshots.

Enforcement: `api/config.py` returns key status only; `models/responses.py` uses explicit fields; `errors.py` redacts; `security.py` scans serialized payloads.

Violation test: `test/offline/test_web_security.py::test_secrets_never_serialized` (planned).

Fallback: Remove the leaking field, rotate the credential if exposed, and add a regression test.

## INV-WEB-004 — No server filesystem path reaches the browser

Statement: Browser-visible payloads contain artifact identifiers, never absolute or repository-relative filesystem paths.

Enforcement: `artifacts/index.py` returns hash ids; `artifacts/downloads.py` resolves ids server-side; response models omit path fields.

Violation test: `test/offline/test_web_security.py::test_responses_contain_no_filesystem_paths` (planned).

Fallback: Replace the path with an identifier and re-run the security tests.

## INV-WEB-005 — Path and identifier validation remains deterministic

Statement: Every ticker, run identifier, artifact identifier, and path component derived from user input is validated by the existing deterministic rules before filesystem use. User input never grants file-access authority.

Enforcement: `api/runs.py` uses `safe_ticker_component`; `artifacts/index.py` uses a root allowlist; unknown artifact ids are rejected.

Violation test: `test/offline/test_web_security.py::test_path_traversal_is_rejected` (planned).

Fallback: Reject the request; do not fall back to a broader path.

## INV-WEB-006 — Portfolio states remain distinct

Statement: An omitted portfolio, an explicitly empty book, and a populated book remain three different inputs across the web layer, the graph, checkpoint signatures, and stored artifacts.

Enforcement: `models/requests.py` distinguishes `null` from `{"positions": []}`; `api/runs.py` uses `PortfolioContext.model_validate`; the coordinator passes the object to the graph.

Violation test: `test/offline/test_web_portfolio.py::test_three_portfolio_states_remain_distinct` (planned).

Fallback: Reject the request rather than coercing an absent portfolio to flat.

## INV-WEB-007 — REVIEW is not Hold and not a position

Statement: When the final decision has no recognizable rating, the web layer displays and records `REVIEW`. It must not substitute `Hold`, a tradeable signal, or a fabricated rating.

Enforcement: `runtime/coordinator.py` calls `process_signal`; `is_review` drives the banner; no alternate parser exists.

Violation test: `test/offline/test_web_contracts.py::test_review_is_not_hold` (planned).

Fallback: Show the review warning and retain the raw decision text.

## INV-WEB-008 — Backtest and live artifacts stay isolated

Statement: A backtest uses its own run directory and memory log; it never reads or writes the live decision log, and live analysis never reads backtest artifacts as past context.

Enforcement: `runtime/backtest_runner.py` calls `run_backtest` with its isolated config; the artifact index treats backtest roots separately.

Violation test: `test/offline/test_web_backtest.py::test_backtest_does_not_touch_live_memory` (planned).

Fallback: Abort the backtest; report the isolation failure.

## INV-WEB-009 — At most one active run; no concurrent writes

Statement: At most one analysis or backtest is active in the server process. No concurrent writes to the decision log, checkpoints, or shared core configuration may occur.

Enforcement: `runtime/coordinator.py` holds a single-run lock and one worker; a second request receives `409`.

Violation test: `test/offline/test_web_runs.py::test_second_run_is_rejected` (planned).

Fallback: Reject the second request; do not queue silently.

## INV-WEB-010 — Cancellation never records a decision or clears a checkpoint

Statement: Cancelling an analysis stops execution and preserves the existing checkpoint when checkpointing was enabled. It must not write a decision-log entry and must not clear a checkpoint.

Enforcement: `runtime/coordinator.py` sets the cancel event, skips `record_decision` and `clear_checkpoint_on_success`, and calls `end_checkpoint()` in `finally`.

Violation test: `test/offline/test_web_runs.py::test_cancel_preserves_checkpoint_and_writes_no_decision` (planned).

Fallback: Mark the run cancelled; do not retry automatically.

## INV-WEB-011 — History is read-only

Statement: History and backtest-history views never delete, rename, move, rotate, or rewrite existing artifacts. They do not create an index database.

Enforcement: `artifacts/index.py` and `artifacts/readers.py` expose reads only; no mutating route exists.

Violation test: `test/offline/test_web_history.py::test_history_endpoints_are_read_only` (planned).

Fallback: Remove the mutating capability and restore the artifact from a backup if needed.

## INV-WEB-012 — Untrusted content is data, not authority or code

Statement: Model output, tool output, announcements, artifact text, and user-provided portfolio text are rendered as data. They cannot execute scripts, issue server-side requests, change permissions, or alter architecture.

Enforcement: `frontend/src/components/Markdown.tsx` uses `react-markdown` + `rehype-sanitize`; no raw HTML; URL scheme allowlist; CSP.

Violation test: `test/offline/test_web_security.py::test_untrusted_content_is_escaped` (planned).

Fallback: Render as plain text and remove the unsafe rendering path.

## INV-WEB-013 — The presentation boundary is loopback and same-origin

Statement: The server binds only to `127.0.0.1`, rejects non-loopback `Host` headers, rejects cross-origin state-changing requests, and does not enable wildcard CORS.

Enforcement: `settings.py` rejects non-loopback bind; `security.py` implements Host/Origin/CSRF/CSP middleware.

Violation test: `test/offline/test_web_security.py::test_non_loopback_host_header_is_rejected` and `::test_cross_origin_post_is_rejected` (planned).

Fallback: Refuse to start or reject the request; do not widen the listener.

## INV-WEB-014 — Controls reflect actual capabilities

Statement: The UI and API must not present a control that the backend cannot honor. In particular, a backtest is not presented as cancellable, and the UI does not emit an `error` agent status that the underlying stream never produces.

Enforcement: `api/backtests.py` has no cancel route; `runtime/projector.py` emits only statuses the stream supports; import progress is derived from actual cells.

Violation test: `test/offline/test_web_backtest.py::test_no_backtest_cancel_route` and `test/offline/test_web_events.py::test_no_fabricated_agent_error_status` (planned).

Fallback: Remove the misleading control or label; show the real state.

## INV-WEB-015 — Missing build assets fail loudly

Statement: If the frontend build is absent, the server starts in API-only mode and reports a clear build instruction. It must not serve a broken or stale UI silently.

Enforcement: `app.py` checks `static/index.html`; `cli.py` prints the build prerequisite; CI packaging test asserts the wheel contains the file.

Violation test: `test/offline/test_web_contracts.py::test_missing_static_assets_fail_loudly` (planned).

Fallback: Stop with a clear error, or run API-only with an explicit warning.

## Verification status

Iterations 1 and 2 are implemented; Iteration 1 received a human implementation review **APPROVE** on 2026-11-06. The WebUI backend suite executes **113 passed**, frontend Vitest **10 passed**, and the full regression is **1097 passed, 4 historical failures, 2 skipped, 88 subtests passed**. This covers the backend/security/path/history/run-control invariants exercised by the suite. Playwright browser execution and the real GraphRunner/live model path remain unrun. Requirements statuses remain `draft`; the approval is for Iteration-1 implementation, not a separate requirements-verification verdict. The execution record is in `docs/architecture/evaluation-logbook.md`.
