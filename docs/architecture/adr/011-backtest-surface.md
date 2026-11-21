# ADR-011: Backtest Surface and Isolation

- Status: **Implemented under the user-approved Iteration-3 plan; architecture review pending.**
- Date: 2026-11-06
- Related requirements: `REQ-WEB-006`, `REQ-WEB-011`, `REQ-WEB-027`, `REQ-WEB-030`
- Related invariants: `INV-WEB-008`, `INV-WEB-009`, `INV-WEB-011`, `INV-WEB-014`
- Related ADRs: ADR-005, ADR-007
- Related blueprint: `architecture-blueprint.md` Sections 6.2, 6.5, 6.6, 8.6, 9

## Context

`run_backtest` is synchronous and has no cancellation hook. It writes an
isolated `results_dir/backtest/<run_id>/trading_memory.md`, while the live
decision memory must stay untouched. The WebUI needs launch, status, summary,
log download, and read-only history without adding a second execution engine or
new analysis capability.

## Decision

1. **Reuse the core.** The web layer calls `iter_grid`, `run_backtest`, and
   `summarize`; it does not reimplement grid generation or scoring.
2. **Single slot.** A backtest and an analysis share the coordinator's
   single-active-run slot. A second request returns `409`.
3. **Isolation.** The wrapper passes the live `results_dir` to
   `run_backtest` (so the core owns the run directory) and points
   `memory_log_path` at the backtest run directory. The live decision log is
   never opened for writing.
4. **Identity.** The browser-facing run id is a `bt_<hex>` identifier. A
   client-supplied `run_id` is validated with `safe_ticker_component` and
   forwarded to the core for resume; otherwise the core chooses its timestamp
   id, matching CLI behaviour.
5. **No cancellation.** No cancel route or UI control exists. The UI states
   that a backtest runs to completion and can be resumed with `run_id`.
6. **Summary.** Responses expose resolved, pending, unscored, per-rating
   count/hit rate/mean alpha, holding window, failures, settlement failures,
   and a log artifact id. They never expose `log_path`.
7. **Read-only history.** `GET /api/backtests` scans existing backtest
   directories and merges process-memory records. No deletion or mutation
   endpoint exists. The log is downloadable through the existing artifact-id
   download path with `kind=log`.

## Consequences

- Backtests use the existing semantics and artifacts, but can occupy the only
  run slot for a long time.
- The browser never receives a filesystem path.
- A backtest cannot be stopped through the WebUI.
- After a process restart, a completed backtest is discoverable by its on-disk
  id; the browser-facing `bt_` id is retained only for the process lifetime
  when no client `run_id` was supplied.

## Alternatives considered

1. Separate backtest worker pool — rejected; adds concurrency and memory-write
   risk the core does not support.
2. Fake cancellation flag — rejected; it would claim a stop that did not
   happen.
3. New backtest database or queue — rejected; no new persistence is approved.
4. Reimplementing summary calculations — rejected; `summarize` is
   authoritative.
