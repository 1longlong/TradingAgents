# ADR-027: Single-Run Slot, Cancellation, Reattachment, and Backtest Controls

- Status: **Accepted for documentation** by the human owner on 2026-11-05.
- Date: 2026-11-05
- Related requirements: `REQ-WEB-003`, `REQ-WEB-005`, `REQ-WEB-006`, `REQ-WEB-007`, `REQ-WEB-011`, `REQ-WEB-029`, `REQ-WEB-030`
- Related invariants: `INV-WEB-008`, `INV-WEB-009`, `INV-WEB-010`, `INV-WEB-014`
- Related ADRs: ADR-001, ADR-002
- Related blueprint: `architecture-blueprint.md` Sections 6.2, 6.6, 8.2–8.4, 9, 13

## Context

The core exposes a synchronous graph stream and a synchronous `run_backtest`. It has no cancellation hook inside `run_backtest`, and its configuration and decision log are not proven safe under concurrent writers. The confirmed scope is one active run, analysis cancellation with CLI-equivalent semantics, process-lifetime reattachment, and backtest launch/view. The UI must not present a capability the core does not have.

## Decision

1. **One active run per process.** The coordinator admits one analysis or backtest; a second request receives `409` with the active run id. There is no queue.
2. **Worker-thread execution.** The synchronous graph stream runs in a single-worker `ThreadPoolExecutor`; events return through `loop.call_soon_threadsafe`.
3. **Analysis cancellation.** Set a `threading.Event`; stop at the next chunk boundary; do not call `record_decision`; do not call `clear_checkpoint_on_success`; call `end_checkpoint()` in `finally`; keep partial artifacts; publish `run.cancelled`.
4. **Cancellation timeout.** If the worker does not stop within 30 seconds, mark the run `cancelling`; the slot remains occupied until the worker exits. Do not kill the thread.
5. **Reattachment.** The client fetches a snapshot and reconnects to SSE with `after_seq`. The server replays buffered events or sends a snapshot. Process restart loses the active run.
6. **Backtest has no cancel button.** `run_backtest` has no cooperative cancellation hook. The UI states that the backtest runs to completion and can be resumed with `run_id` after an interruption.
7. **Checkpoint clear.** Requires explicit `{"confirm": "CLEAR"}` and is rejected during an active run.
8. **Honest states.** Do not emit an `error` agent status (the CLI never sets it). Failures are run-level `run.failed`; REVIEW is a review state, not a position.

## Consequences

### Positive

- No unproven concurrent writers.
- Cancellation semantics match the CLI's actual `Ctrl-C` behavior.
- Reattachment survives browser reloads without new storage.
- The UI does not promise backtest cancellation that cannot be delivered.
- The single-run slot is easy to reason about and test.

### Negative / costs

- No parallel analyses.
- Cancellation can take up to the current model call to take effect.
- A hung provider call can occupy the slot for a long time; the 30-second timeout only reports `cancelling`.
- Backtests may run for a long time without a stop control.
- Reattachment is lost on server restart.

### Risks and mitigations

- **Stuck worker.** Show `cancelling`, keep the slot, log the state; do not spawn a second run.
- **User expects backtest cancel.** Explicit UI copy; no disabled-looking control that pretends to work.
- **Race between cancel and completion.** Use a single state transition under the coordinator lock; completion wins only if it occurred before cancellation was observed.
- **SSE reconnect storms.** Heartbeat, bounded queue, and a short retry delay.
- **Restart confusion.** Health/snapshot returns "run no longer available"; artifacts remain.

## Alternatives considered

1. Serial queue — deferred; adds a scheduler without confirmed need.
2. Parallel runs — rejected; requires core configuration isolation and memory write ownership.
3. Kill the worker thread — rejected; Python cannot safely kill threads, and it could corrupt checkpoints.
4. Wrap `run_backtest` with a fake cancel flag — rejected; it would report a stop that did not happen.
5. Persist run state to disk — deferred; new storage and recovery design.


## Addendum — custom debate-policy checkpoint identity, 2026-11-20

The user requested real-run debate configuration in web-debate-settings-20261120-v1.
Core recovery identity includes round caps but omits convergence thresholds; the
ledger additionally guards accounting parameters. Threshold-only policy changes
therefore require a WebUI recovery boundary. Use a Web-only core-graph subclass
that calls the existing _run_signature and appends a deterministic fingerprint
for nondefault policies. Compare normalized policy fields excluding the round
cap (already present in the core signature); include the full normalized policy
in the fingerprint when needed. Keep the original signature for default policy
settings at any valid legacy depth. No core signature, checkpoint store, graph
algorithm or CLI/Python contract is changed. Existing ledger checks and cleanup
remain authoritative. Verify default parity, fixed/dynamic separation, every
threshold/budget difference and unchanged portfolio/round isolation before use.


## Web integration refinement — 2026-11-21

The user explicitly authorizes web-simulation-20261121-v1: frontend and necessary
interfaces around the existing deterministic simulated-trading core. The
blueprint/review memo define the bounded API, ownership, persistence, single-slot
coordination, human-approval and negative-test contracts. Core models, clocks,
sizing, pipeline, engine-issued authorization, audit chain and state store remain
authoritative; no broker, safety/core rewrite or automatic human approval is
introduced. Pending approval objects remain process-owned and cannot be restored
from client JSON. Only one final verification phase is requested.


## Backtest error diagnostics refinement — 2026-11-21

web-backtest-errors-20261121-v1 closes a diagnostic gap: backtest exceptions must
use the same redacted server traceback and correlated safe categories as analysis
exceptions. The failure banner shows that correlation. Task labels distinguish
backtests from analyses; missing provider-key configuration is reported safely.
No model selection, data-vendor fallback, core cell semantics, credentials or
execution permissions change. Server defaults remain the backtest configuration;
analysis-wizard choices are not implicitly copied. A displayed generic failure
alone cannot establish its runtime cause.


## Per-date backtest observation — 2026-11-21

web-backtest-progress-20261121-v1 implements the user's per-date progress request.
A context-scoped optional observer in core backtest.py reports facts immediately
around existing serial analysis/settlement calls. It adds no public run_backtest
argument, result change, UI dependency, cancellation or memory write. Default
execution has no observer; observer exceptions cannot change business results.
The Web runner subscribes only in its worker context and releases the observer
on exit. No graph-class monkeypatching or second backtest loop is permitted.

runtime/backtest_progress.py owns only Web presentation state under the existing
record lock. Counts distinguish completed, failed and skipped cells; current
identity must belong to the validated requested grid. Duplicate/out-of-order or
unknown events cannot invent completion. The snapshot returns bounded paginated
cell details, timestamps and elapsed time without raw errors or credentials.
Cell processing at 100% does not mean settlement/summarization is complete.
The original slot remains held until the actual worker exits. Browser reload
reattaches to process state; old disk summaries do not gain inferred per-cell
status. No restart persistence, ETA or cancellation is promised.
