# Integrated core and WebUI records

The canonical layout is `src/` and `test/`. The core records below describe the
release data-quality gate, evidence, debate, usage ledger and output guards;
the WebUI records describe the presentation extension over that core. Existing
requirement and invariant IDs remain scoped to their original modules. An
unqualified core ADR number refers to the release ADR with its descriptive
filename; a WebUI ADR number refers to the WebUI ADR with its descriptive
filename. Both sets remain present. Historical approvals retain their original
scope and do not approve this merge or a new feature. Verification results are
historical unless explicitly identified as a merged-tree run.

## Release core

# Memory Design Notes

Scope: this document records how the CS5351 feature work interacts with the
"memory" of the system — the point-in-time integrity of stored dated data, the
state carried through the graph, the decision/memory log, and the persistence,
ownership, retention, privacy, and cross-session/version behavior of that
memory. It is a design note; the upstream product memory design lives upstream.

## 1. Point-in-time integrity for dated data

The framework evaluates every dated data path "as of" the requested trade date.
A stored object (OHLCV cache entry, FRED macro series, news article, social
post, decision-log memory row) is read and validated with an `as_of` boundary so
no future data is used. This is preserved from upstream.

- `src/tradingagents/dataflows/market_data_validator.py` — the verified snapshot
  builder applies the `as_of` boundary when it builds `StructuredSnapshot`.
- `src/tradingagents/evidence/validate.py` — the deterministic look-ahead validation
  class rejects any evidence whose timestamp is after the requested date.
- **Gap (recorded, not hidden):** an allowlist/citation check verifies record
  *eligibility*, not the *semantic truth* of a claim's date. The 2026-11-06 live
  run produced a Bull claim that relabelled a Nov-4 close (observed_at
  `2026-11-04`) as Nov-5 while citing the valid close ID (`RISK-020` /
  `DEBT-022`, OPEN, not fixed).

## 2. Gate-aware state carried through the graph

The Data Quality Gate node writes only JSON-safe fields into `AgentState`:

- `data_quality_verdict` — `normal` / `degraded` / `blocked`.
- `data_quality_evidence_records` — the serialized `EvidenceRecord` list.
- `data_quality_validation_results` — the serialized `ValidationResult` list.
- `data_quality_group_statuses` — the serialized `EvidenceGroupQuality` list.
- `data_quality_gate_decision` — the serialized `GateDecision`.
- `data_quality_context` — human-readable context.
- `data_quality_error` — populated only on a fail-closed internal error.

The router `should_continue_after_data_gate` reads these fields to decide whether
to proceed to the Bull Researcher (`normal`/`degraded`) or route straight to the
Research Manager (`blocked` / missing / malformed gate state). This is a
deliberate fail-closed design: malformed or missing gate state cannot proceed to
a full-strength debate.

## 3. Debate turn state

`src/tradingagents/debate/state.py` mutates debate state on the researcher side; the
evaluator node reads the gate manifest (evidence records) and the accumulated
turn state off `AgentState` to produce a `RoutingDecision`. The `run_id` used
for evidence IDs is derived from `(trade_date, normalized symbol)`, so the
"memory" of a given run is reproducible for the same symbol/date.

## 4. Decision / memory log and blocked-run hold tagging

The upstream memory-log row write is **no longer unchanged** — the CS5351 work
changed it, and the earlier "unchanged" claim was stale. Concretely
(`src/tradingagents/agents/utils/memory.py`):

- `TradingMemoryLog(...).record_pending(..., blocked: bool = False)` now takes a
  structured `blocked` flag. On a blocked run the row tag is forced to
  `Hold` (`HOLD if blocked else parse_rating(...)`) so the memory log agrees with
  the authoritative final signal, regardless of how the decision text rendered
  (`FR-DQG-006`).
- The decision body is still the (guarded) final trade decision text; the guard
  (`src/tradingagents/agents/utils/output_guard.py`) pins executable decision fields
  to Hold while preserving rationale as non-executable prose.
- This behavior is covered by `test/offline/test_memory_log.py` and
  `test/offline/test_output_guard.py`.
- **Ownership / access:** the memory log is written only by the owning user's
  session into a local file (default path resolved by config); it is not a
  shared or multi-tenant store. There is no cross-user read path in this
  codebase.
- **Retention / deletion / privacy (current state, not invented policy):**
  entries are append-only and idempotency-guarded by
  `[trade_date | ticker | rating | pending]`; there is **no** automatic
  retention window, redaction pass over stored bodies, or deletion API in this
  codebase. Because the body can contain model-produced prose, the log should be
  treated as potentially sensitive local data. A concrete retention/deletion and
  redaction policy is a **human/team decision that has not been made**; it is
  recorded as pending, not fabricated here.
- **Cross-session / version handling:** the log records a `pending` tag with no
  embedded schema version; a later scoring/version change must tolerate older
  rows by treating unknown fields/tags conservatively (do not rewrite history).
  `run_id` reproducibility across sessions depends on `(trade_date, normalized
  symbol)` only, so the same symbol/date is comparable across sessions; the log
  does not persist provider/model version, so cross-version comparisons are
  best-effort and unverified.

## 5. Relation to upstream memory / decision log

The upstream memory-log / decision-log row writes and the Trader price grounding
are otherwise preserved; look-ahead fixes on the memory log (from upstream
v0.4.0/v0.5.0) remain. The only CS5351 change to persistence is the blocked-run
`Hold` tag described in §4. The Graph checkpoint/resume machinery is inherited
and unchanged; its JSON-safety relies on the gate writing only serialized
dict/list/string forms (§2).


## WebUI extension

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
