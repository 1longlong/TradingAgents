# ADR-001: Web Entry Point, Module Boundary, and Run-State Ownership

- Status: **Accepted for documentation** by the human owner on 2026-11-05. Implementation requires `[safety-approved]`, `[test-plan-approved]`, and `[governance-approved]` where applicable.
- Date: 2026-11-05
- Baseline: TradingAgents v0.5.0, commit `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`
- Related requirements: `REQ-WEB-001` to `REQ-WEB-014`, `REQ-WEB-020` to `REQ-WEB-031`
- Related invariants: `INV-WEB-001` to `INV-WEB-015`
- Related blueprint: `architecture-blueprint.md`

## Context

TradingAgents exposes one interactive entry point: the Typer/Rich CLI in `src/cli/`, backed by the Python API in `src/tradingagents/`. The project owner approved a local, single-user WebUI that displays every capability already visible in the TUI without adding analysis capability, data sources, models, agent logic, or trading behavior. `src/tradingagents/` and `src/cli/` must remain unchanged.

Three facts make entry-point and state ownership safety-relevant:

1. `src/tradingagents/dataflows/config.py` stores configuration in a process-global singleton. Two graphs with different configurations cannot safely run concurrently in one process.
2. `src/tradingagents/agents/utils/memory.py` updates the decision log with read-modify-write plus atomic replacement. Atomic replacement prevents torn files, not lost updates.
3. The CLI owns a module-level `message_buffer` singleton and streams the graph directly. The CLI stream path is the behavioural reference, but its buffer cannot serve the web layer.

## Decision

1. **Presentation-only package.** Add `src/tradingagents_web/`. It may import `tradingagents` and restricted `cli` helpers; neither `src/tradingagents/` nor `src/cli/` may import it.
2. **One in-process run coordinator.** The coordinator owns the single active analysis or backtest, creates one fresh `TradingAgentsGraph` per run, consumes its stream in a single-worker thread, and publishes a bounded event sequence. A second submission is rejected with `409`.
3. **Reuse existing public methods.** The coordinator calls `create_run_state`, `begin_checkpoint`, `checkpoint_input`, `graph.stream`, `record_decision`, `clear_checkpoint_on_success`, `end_checkpoint`, `process_signal`, `write_report_tree`, `run_backtest`, and `summarize`.
4. **In-memory run state.** A browser disconnect does not cancel the run; reattachment works within the server process lifetime. A process restart loses the active run; on-disk artifacts and checkpoints remain.
5. **Read-only history.** History reads existing run directories, saved report trees, backtest runs, and the decision memory. It creates no database, index, or retention policy.
6. **Untrusted browser.** Loopback-only binding, Host/Origin/CSRF checks, no provider keys, no server paths, and sanitized rendering.
7. **Server-only keys.** The web layer displays configured/not-configured status and never accepts, persists, or returns a key.
8. **CLI-equivalent cancellation.** Cancellation stops the stream, writes no decision, clears no checkpoint, and keeps partial artifacts.

## Consequences

### Positive

- Core and CLI behavior, tests, and consumers remain unchanged.
- The single-run rule avoids unproven concurrency in global configuration and memory writes.
- Reusing existing writers and validators avoids a second report format and a second rating parser.
- Read-only history adds discoverability without storage.
- Server-only keys and loopback binding keep the credential and network surface small.

### Negative / costs

- No parallel analyses; a second request is rejected.
- A server restart loses active runs; recovery remains a CLI/API capability.
- The web UI cannot perform the CLI's interactive key prompt.
- The event buffer, snapshot logic, and thread bridge add lifecycle complexity.
- A sanitizer and strict identifier layer are required.

### Risks and mitigations

- **Localhost is not a complete boundary.** Use loopback binding, Host/Origin checks, CSRF, no wildcard CORS, and no secrets in responses.
- **Event loss.** Use monotonic sequence numbers and snapshot fallback.
- **Path traversal.** Never accept paths; resolve hash identifiers through an allowlist.
- **Model output injection.** Escape or sanitize all untrusted content.
- **Core drift.** Use the structural gate and a core/CLI contract test.

## Alternatives considered

1. Run the web layer inside `src/tradingagents/` — rejected: the structural check forbids presentation imports there.
2. Reuse `propagate()` only — rejected as the sole path: live display needs streamed chunks.
3. Add a database for run state and history — rejected: second source of truth and new storage.
4. Allow concurrent runs with per-run configuration — rejected: requires core changes outside scope.
5. Accept API keys in the browser — rejected: transmits plaintext credentials into a client surface.
