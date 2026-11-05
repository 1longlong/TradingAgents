# ADR-001: Simulated Trading System

Status: Accepted.

## Context

TradingAgents produces advisory portfolio decisions, but an LLM output must not
be able to move money or bypass deterministic controls. The subsystem needs a
trade path that is auditable, replayable, and safe to run against historical
data without contacting a broker. It also needs a live mode that can inspect and
reset persisted state without modifying the frozen graph.

## Decision

1. **Simulated execution only.** `SimulatedExecutor` applies fills to an
   in-process `Portfolio`. There is no broker client, order router, or real
   execution path. Market access is limited to read-only historical quotes in
   opt-in live tests.
2. **Deterministic authority.** LLM text is adapted to direction only.
   `SizingPolicy` computes quantity; `src/safety/rules.py` and
   `SafetyEngine` decide APPROVED, PENDING_APPROVAL, REJECTED, or NO_ACTION.
   LLM quantities and prices are discarded.
3. **Module-private provenance token for INV-02.** `SafetyEngine` owns a
   module-private `_ProvenanceToken` instance and issues an
   `_AuthorizedExecution` carrying it. `SimulatedExecutor.execute()` verifies
   the exact token object and raises `ExecutionNotAuthorizedError` otherwise.
   A plain `ExecutionAuthorization` cannot execute. The AST structural test
   additionally enforces that only `src/safety/engine.py` imports the executor.
4. **Separate live and simulated clocks.** `SystemClock` returns the current
   wall-clock instant for live inspection. `SimulationClock` is pinned to a
   simulated market close in `America/New_York`; SR-03 compares quote dates to
   the simulated date in simulation mode instead of elapsed wall-clock time.
   Wall-clock calls outside `src/trading/clock.py` are rejected by the AST test.
5. **Atomic JSON persistence.** `StateStore` serialises portfolio state and an
   optional `BacktestCursor` to JSON using Decimal strings. Saves write a
   temporary file in the same directory, `fsync`, then `os.replace`. Loads fail
   closed on corruption. Reset preserves the append-only audit log and appends
   `STATE_RESET`.

## Consequences

- Trade decisions are replayable and testable offline with Decimal arithmetic.
- A compromised or mistaken LLM cannot choose its own quantity, bypass a hard
  rule, or call the executor directly without the engine token.
- The provenance token is a Python module-private convention, not a defence
  against arbitrary in-process code that deliberately imports private names;
  the static import boundary provides a second check for normal code paths.
- Persisted state is deliberately independent of the append-only audit log:
  reset removes portfolio state but never truncates history.
- There is no real market execution, so live tests validate orchestration and
  audit integrity rather than broker behaviour.
