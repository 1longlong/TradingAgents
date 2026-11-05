# TradingAgents WebUI Memory and State Design

Status: **Approved for documentation by the human owner on 2026-11-05.** This document records the approved state ownership. It does not authorize implementation.

## 1. State inventory

| State | Owner | Storage | Lifetime | Writers | Readers |
| --- | --- | --- | --- | --- | --- |
| Active run record | `runtime/coordinator.py` (`RunCoordinator`) | Process memory | Until server exit or 5 min after terminal state | Coordinator | API, SSE |
| Event sequence | `runtime/event_buffer.py` (`EventBuffer`) | Bounded process memory | Run + 5 min | Projector | SSE subscribers |
| Graph instance | Worker thread | Python objects | Run | Worker | Coordinator |
| Checkpoints | `TradingAgentsGraph` / `checkpointer` | Per-ticker SQLite | Existing persistence | Graph | Graph / CLI |
| Decision log | `TradingMemoryLog` via graph | Markdown | Persistent | Graph only | History reader |
| Run artifacts | `runtime/artifacts_writer.py` | Existing `results_dir` layout | Persistent | Worker | History reader |
| History index cache | `artifacts/index.py` | Process memory | 5 s TTL | Scan | History API |
| CLI preferences | `cli.prefs` | `~/.tradingagents/cli_prefs.json` | Persistent | CLI only | Config projection |
| UI state | Zustand / TanStack Query | Browser memory | Tab lifetime | Frontend | Frontend |

No state is stored in a new database, message queue, or external cache.

## 2. Existing decision memory

`src/tradingagents/agents/utils/memory.py`:

- Append-only Markdown, default `~/.tradingagents/memory/trading_memory.md`.
- `store_decision()` appends a pending entry with `[date | ticker | rating | pending]`.
- Settlement replaces the tag with raw return, alpha, holding window, and `resolved:<date>`, then appends a reflection.
- Writes use a temp file plus `os.replace()`; this prevents torn files, not lost updates.
- `get_past_context(..., as_of=...)` enforces the point-in-time filter.
- `memory_log_max_entries` optionally prunes resolved entries; pending entries are never pruned.

The web layer writes through the graph's existing methods only. It never appends to the decision log directly.

## 3. Existing checkpoints

- Per-ticker SQLite under `<data_cache_dir>/checkpoints/<TICKER>.db`.
- `thread_id(ticker, date, signature)` includes analyst selection, debate/risk rounds, asset type, and portfolio fingerprint.
- Success clears the run's checkpoint; failure and cancellation leave it.
- `clear_all_checkpoints()` removes `.db`, `-wal`, and `-shm`.

The web layer toggles `checkpoint_enabled`, reports resume/fresh from the run event, and exposes clear-all with confirmation. It does not compute checkpoint signatures independently.

## 4. Existing CLI preferences

- `~/.tradingagents/cli_prefs.json` contains stable last-run choices.
- The web layer reads it for prefill only.
- **Web runs do not write it.** Web UI preferences (language, theme, last wizard values) live in browser `localStorage`.
- Unreadable preferences mean no defaults, never an error.

## 5. In-memory run state

`RunRecord` minimum fields:

- `run_id`: server-generated, safe component.
- Request: ticker, trade date, asset type, analysts, depth, provider, models, output language, checkpoint flag, portfolio fingerprint.
- Lifecycle: `status`, `started_at`, `finished_at`, `last_seq`.
- Result: signal, review flag, artifact ids, warnings, safe error category.
- Worker: future, cancel event, thread identity (diagnostic only, not exposed).

`EventBuffer`:

- Monotonic `seq`, event type, timestamp, payload.
- Bounded by count (10,000) and approximate bytes (8 MB), whichever is reached first.
- Per-subscriber bounded queue (1,000 events); overflow drops the subscriber to snapshot mode.
- Retained 5 minutes after terminal state for reattachment.

## 6. Thread bridge

- The graph stream is synchronous and may block on model calls.
- The coordinator runs it in a single-worker `ThreadPoolExecutor`.
- Events are published with `loop.call_soon_threadsafe(queue.put_nowait, event)`.
- The cancellation flag is a `threading.Event`, checked between chunks.
- `graph.end_checkpoint()` runs in the worker's `finally`.
- The asyncio side never calls the synchronous stream directly.

## 7. Artifact writing

`runtime/artifacts_writer.py` mirrors the CLI's file layout without reimplementing business logic:

- `results_dir/<ticker>/<date>/message_tool.log`: `HH:MM:SS [Type] content` and `HH:MM:SS [Tool Call] name(args)`.
- `results_dir/<ticker>/<date>/reports/<section>.md`: section key filenames, matching the CLI.
- On success: `write_report_tree(final_state, ticker, results_dir/reports/<ticker>_<timestamp>/)`.
- On cancel/failure: keep the partial message log and section files; no complete report is synthesized.
- No `full_states_log_*.json` is written by the web stream path.

## 8. Concurrency and write ownership

One process, one active run, one worker. This protects:

- the process-global configuration in `src/tradingagents/dataflows/config.py`;
- the read-modify-write decision log;
- checkpoint databases;
- the event buffer and artifact writer.

A second submission is rejected with `409`. There is no queue. Concurrent runs would require per-run configuration isolation, a serialized or owned decision-log writer, per-run artifact namespaces, and a lost-update test; that is outside this design.

## 9. Cancellation and failure

| Event | Decision log | Checkpoint | Artifacts | Run state |
| --- | --- | --- | --- | --- |
| Cancel analysis | not written | preserved | partial kept | `cancelled` |
| Worker failure | not written | preserved | partial kept | `failed` |
| Report save failure | written (analysis completed) | cleared as normal | sections + message log; report tree may be absent | `completed` + warning |
| Browser disconnect | unchanged | unchanged | unchanged | continues |
| Server restart | unchanged | unchanged | unchanged | active run lost |

A retry is a new run with a new request. The web layer never infers an outcome from a failed run.

## 10. Point-in-time and retention

- Analysis-date validation remains in the core.
- `as_of` past-lesson filtering remains in `create_run_state`.
- Backtests keep their own log and date grid.
- History reads stored artifacts and does not reconstruct unrecorded outcomes.
- Decision-memory rotation remains the existing configuration; the web exposes no deletion or rotation.
- Checkpoint clear is the only destructive web control.

## 11. Recovery boundaries

- Browser disconnect does not affect memory or checkpoints.
- Server restart loses the in-memory run record and event buffer.
- Decision log, run artifacts, and checkpoints remain on disk.
- The CLI/API can resume a checkpointed run; the web does not claim cross-process recovery.
