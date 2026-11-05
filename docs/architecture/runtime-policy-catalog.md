# TradingAgents WebUI Runtime Policy Catalog

Status: **Approved for documentation by the human owner on 2026-11-05.** These policies describe required runtime behaviour. No policy below is implemented. Each names an enforcement module and a fallback.

## WEB-POLICY-001 — Loopback-only listener

Trigger: server start.
Rule: bind `127.0.0.1` only; reject non-loopback `Host`; no wildcard CORS.
Enforcement: `settings.py`, `security.py`.
Fallback: refuse to start on a non-loopback address.

## WEB-POLICY-002 — Single active run

Trigger: a new analysis or backtest request.
Rule: if a run is `starting`, `running`, or `cancelling`, return `409` with the active run id. No queue.
Enforcement: `runtime/coordinator.py`.
Fallback: return the active run id so the client can reattach.

## WEB-POLICY-003 — Process-lifetime run state

Trigger: browser disconnect, refresh, or network loss.
Rule: continue the run; allow reattachment from the last sequence within the process lifetime. A restart loses the run.
Enforcement: `runtime/coordinator.py`, `runtime/event_buffer.py`.
Fallback: show "run no longer available"; on-disk artifacts and checkpoints remain.

## WEB-POLICY-004 — Analysis cancellation

Trigger: a same-origin cancel request for the active analysis.
Rule: set the cancel event; stop at the next chunk; do not call `record_decision`; do not call `clear_checkpoint_on_success`; `end_checkpoint()` in `finally`; keep partial artifacts; publish `run.cancelled`.
Enforcement: `runtime/coordinator.py`.
Fallback: if the worker does not stop in 30 s, report `cancelling` and keep the slot until it exits.

## WEB-POLICY-005 — Checkpoint controls

Trigger: checkpoint toggle or clear-all.
Rule: the toggle affects the next run only. Clear-all requires `{"confirm": "CLEAR"}` and is rejected while a run is active. Clear-all calls `clear_all_checkpoints`.
Enforcement: `api/runs.py`, `runtime/coordinator.py`.
Fallback: reject the clear, report the count cleared, never expose a path.

## WEB-POLICY-006 — Server-only provider keys

Trigger: configuration display or run start.
Rule: read keys only from the server environment; return `configured / not_configured / not_required`; never accept, store, return, log, or export a key. A missing key does not block start; the first provider call fails safely.
Enforcement: `api/config.py`, `models/responses.py`, `errors.py`.
Fallback: show a safe configuration error; keep the run record.

## WEB-POLICY-007 — Deterministic identifiers

Trigger: any ticker, run id, artifact id, or path component from a client.
Rule: validate with existing rules before filesystem use; reject absolute paths, `..`, backslashes, and values outside the allowlist.
Enforcement: `api/runs.py`, `artifacts/index.py`.
Fallback: reject; never widen the path.

## WEB-POLICY-008 — Artifact ids, not paths

Trigger: any response referencing an artifact.
Rule: return `sha256(relative_path)[:16]`; resolve server-side through a 5 s in-memory map; omit path fields.
Enforcement: `artifacts/index.py`, `models/responses.py`.
Fallback: omit the artifact and return a safe not-found.

## WEB-POLICY-009 — Read-only history

Trigger: history or backtest-history request.
Rule: read only; no delete, rename, move, rotation, migration, or index write.
Enforcement: `artifacts/index.py`, `artifacts/readers.py`, `api/history.py`.
Fallback: reject any mutating request.

## WEB-POLICY-010 — Backtest isolation

Trigger: backtest request.
Rule: use the backtest's own run directory and memory log; never read or write the live decision log. A backtest occupies the single-run slot.
Enforcement: `runtime/backtest_runner.py`.
Fallback: abort and report the isolation failure.

## WEB-POLICY-011 — Announcement handling

Trigger: page load or refresh.
Rule: fetch server-side; on failure use the CLI fallback; `require_attention=true` blocks until acknowledged; render as untrusted text.
Enforcement: `api/announcements.py`, `frontend/src/components/Announcements`.
Fallback: show the fallback link and do not block.

## WEB-POLICY-012 — Untrusted rendering

Trigger: model output, tool output, announcements, artifact text, portfolio text.
Rule: escaped text or sanitized Markdown; no raw HTML; no script; no `javascript:`/`data:` links; no server-side template evaluation.
Enforcement: `frontend/src/components/Markdown.tsx`, `security.py`.
Fallback: plain text.

## WEB-POLICY-013 — Error redaction

Trigger: any validation, upstream, storage, or internal error.
Rule: return category, safe message, correlation id; redact keys, tokens, cookies, authorization headers, paths, and stack traces.
Enforcement: `errors.py`, `security.py`.
Fallback: generic internal error with a correlation id.

## WEB-POLICY-014 — Bounded event buffer

Trigger: event publication or subscription.
Rule: bounded buffer (10,000 events or 8 MB), bounded subscriber queue (1,000), snapshot fallback, heartbeat every 15 s.
Enforcement: `runtime/event_buffer.py`.
Fallback: drop the subscriber to snapshot mode; keep the run alive.

## WEB-POLICY-015 — No execution authority

Trigger: any rating, report, or model output.
Rule: display only; no order/position endpoint; no brokerage dependency.
Enforcement: route inventory, `api/`.
Fallback: remove the endpoint or control.

## WEB-POLICY-016 — Honest run state

Trigger: completion, failure, cancellation.
Rule: derive state from actual stream completion and artifact writes; show partial artifacts as partial; do not report an unreadable rating as a position.
Enforcement: `runtime/coordinator.py`, `frontend/src/pages/Report`.
Fallback: show failed/review and preserve raw decision text.

## WEB-POLICY-017 — Backtest has no cancel control

Trigger: a backtest is running.
Rule: do not expose a cancel route or button. State that the backtest runs to completion and can be resumed with `run_id`.
Enforcement: `api/backtests.py`, `frontend/src/pages/Backtest`.
Fallback: remove any misleading control.

## WEB-POLICY-018 — Same-origin state-changing requests

Trigger: POST/DELETE from the browser.
Rule: require the per-process `X-CSRF-Token`; if `Origin` is present it must match the loopback origin; reject cross-origin; no wildcard CORS.
Enforcement: `security.py`.
Fallback: 403 with a safe message.

## WEB-POLICY-019 — Static asset presence

Trigger: server start.
Rule: if `static/index.html` is missing, start in API-only mode with a clear build instruction; never serve a broken UI silently.
Enforcement: `app.py`, `cli.py`.
Fallback: API-only mode; CI packaging test fails.

## WEB-POLICY-020 — Run artifact writing

Trigger: analysis run.
Rule: write `message_tool.log` and `reports/<section>.md` in the CLI layout; auto-save the complete tree on success; keep partial artifacts on cancel/failure; do not write `full_states_log`.
Enforcement: `runtime/artifacts_writer.py`.
Fallback: emit `storage` warning; keep the analysis result and partial artifacts.
