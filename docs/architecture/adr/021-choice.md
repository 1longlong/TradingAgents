# ADR-021: Web Entry Point, Module Boundary, and Run-State Ownership

- Status: **Accepted for documentation** by the human owner on 2026-11-05. Applicable plan, test, safety and governance changes require human review. The 2026-11-21 policy revision in ADR-012-error-handling-merge-integration.md delegates merge approval to GitHub branch protection without special markers or test-only commit chronology.
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


## Analysis-path repair refinement

The user authorized repairing the reviewed WebUI defects while preserving the core and CLI. Final review remains pending; this is not a GitHub review-marker approval.

Web analyses now write `results_dir/web_runs/<run_id>/` rather than sharing a ticker/date directory with earlier runs or the CLI. Existing report formats are retained. A small atomic `run.json` sidecar records identity, analysis date, and lifecycle status. The read-only artifact scanner accepts this additional source while retaining all legacy readers. Interrupted nonterminal sidecars appear as partial artifacts after a restart; they do not restore active tasks. Saved report trees append the run ID to the existing timestamp-based filename.

A complete, consistent display snapshot accompanies the SSE cursor. Expired cursors receive a snapshot; terminal snapshots need no new stream. Server execution limits remain authoritative; provider/model selection follows the model-defaults refinement below. Correlated failure details are safe for the browser, while diagnostics are redacted on the server. The single-run slot stays owned until worker cleanup finishes.

These refinements avoid stale mixed reports and missing reload results without modifying `src/cli/` or `src/tradingagents/`, adding a database, or changing business analysis semantics.


## Addendum — real-run debate configuration

The user authorized web-debate-settings-20261120-v1 on feature/webui. Extend the
existing WebUI request surface with a typed optional debate_termination subset
and independent risk-round cap. The core resolver validates effective policy;
WebUI code only merges defaults/requests/environment locks and projects public
fields. Environment round locks outrank per-run overrides. Effective caps are
synchronized before creating the core graph. Default/legacy calls retain their
meaning and no arbitrary config/path/state selectors are accepted. Record public
effective settings in snapshots and existing per-run metadata. See ADR-007's
addendum for the necessary Web-only checkpoint-identity extension. No dependency,
core algorithm, provider, live benchmark, trading operation or release is added.


## TUI parity refinement

Under web-tui-parity-20261120-v1, extend existing events/snapshots and controls
for observed role status, analyst timing, finalized reports and custom backtest
spacing. New runtime/model_catalog.py owns bounded, application-cached public
OpenRouter discovery; config API adds optional refresh and safe stale/custom-ID
fallback. Keep core algorithms, CLI, credentials/preferences, language options
and simulated trading unchanged. See the blueprint/review memo for contracts
and prior negative-test strategy.


## Web integration refinement

The user explicitly authorizes web-simulation-20261121-v1: frontend and necessary
interfaces around the existing deterministic simulated-trading core. The
blueprint/review memo define the bounded API, ownership, persistence, single-slot
coordination, human-approval and negative-test contracts. Core models, clocks,
sizing, pipeline, engine-issued authorization, audit chain and state store remain
authoritative; no broker, safety/core rewrite or automatic human approval is
introduced. Pending approval objects remain process-owned and cannot be restored
from client JSON. Only one final verification phase is requested.


## Model defaults refinement

The user authorizes web-model-defaults-20261121-v1. In Web analysis only,
TRADINGAGENTS_LLM_PROVIDER, TRADINGAGENTS_QUICK_THINK_LLM and
TRADINGAGENTS_DEEP_THINK_LLM are non-secret defaults, preselected but editable.
Explicit analysis choices override those defaults. Omission and backtests retain
server defaults. Other existing environment locks, core/CLI behavior and
server-owned credentials remain unchanged. This supersedes prior blanket
environment-precedence statements only for those three selection fields.

Provider-dependent values are scoped to their configured provider. Switching
requires both model IDs and clears inherited endpoint/thinking values; an
explicit endpoint may use the existing override capability. A configured server
endpoint remains authoritative when using that same server-default provider.
No provider's credential is inferred from model name or sent to an inherited
endpoint belonging to another provider. UI source labels distinguish editable
defaults from enforced risk/round/other settings. Draft model selections are
bound to a non-secret server provider/model baseline; changed defaults invalidate
stale selection fields without persisting endpoints, credentials or portfolios.
