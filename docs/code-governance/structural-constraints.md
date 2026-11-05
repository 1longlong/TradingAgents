# Structural Constraints

Status: Implemented (Step 14).

## Module Layout

```text
src/safety/
  __init__.py      public rule exports
  rules.py         SR-01..SR-10 hard rules, AP-01/AP-02 policies
  engine.py        evaluate/approve/execute state machine, provenance issuer

src/trading/
  __init__.py      public model/clock exports
  models.py        enums, frozen dataclasses, errors, FeeModel, SafetyConfig
  clock.py         Clock protocol, SystemClock, SimulationClock
  audit.py         append-only JSONL audit, hash chain, .head anchor
  portfolio.py     cash, positions, cost basis, PnL, BANKRUPT state
  persistence.py   atomic StateStore, BacktestCursor
  executor.py      SimulatedExecutor, execution auditing
  approval.py      HumanApprovalGate
  pipeline.py      graph adapter, SizingPolicy, TradingPipeline
  backtest.py      calendar, decision/quote providers, BacktestRunner
  runtime.py       RuntimeConfig, TradingRuntime, build_runtime
  cli.py           standalone inspect/reset CLI
```

Each architectural element maps to exactly one module. Tests live under
`test/offline/` (deterministic) or `test/live/` (opt-in network/LLM).

## Dependency Direction

```text
models            -> (no internal dependency)
clock             -> (no internal dependency)
audit             -> models, clock
portfolio         -> models, clock
persistence       -> models, clock, audit, portfolio
executor          -> models, clock, audit, portfolio
rules             -> models
engine            -> models, clock, rules, audit, portfolio, executor
approval          -> models, clock, audit
pipeline          -> models, clock, safety.engine, approval, portfolio,
                     tradingagents.agents.utils.rating (read-only)
backtest          -> models, clock, safety.engine, persistence, pipeline,
                     portfolio, tradingagents.portfolio (read-only)
runtime           -> models, clock, safety.engine, approval, audit,
                     persistence, pipeline, portfolio
cli               -> models, clock, runtime
```

Rules for new code:

1. `models` and `clock` must not import higher-level trading modules.
2. Only `src/safety/engine.py` may import or call `src/trading/executor.py`.
3. `pipeline`, `backtest`, `runtime`, and `cli` must not import the executor.
4. `rules.py` must not perform I/O; it receives a `RuleContext`.
5. No module under `src/trading/` or `src/safety/` may import a network client,
   broker SDK, or `tradingagents.dataflows`. The only permitted `tradingagents`
   imports are read-only adapters (`agents.utils.rating`, `portfolio`, and, in
   opt-in live tests only, dataflows for historical quotes).
6. No direct `datetime.now()`/`time.time()` call may appear outside
   `src/trading/clock.py`. All components receive a clock/callable.
7. Audit writes go through `AuditLog`; no module may edit or delete an existing
   audit entry. The `.head` file is metadata, not an event stream.
8. `StateStore` is the only persistence boundary. It may restore a portfolio
   into an existing instance so the engine/executor keep the same live object;
   business logic must not mutate another portfolio's private state.

## Executable Enforcement

`test/offline/test_structure.py` parses every Python file under `src/trading/`
and `src/safety/` with `ast` and asserts:

- `trading.executor` is imported only by `src/safety/engine.py`;
- no direct wall-clock call occurs outside `clock.py`;
- no banned network/broker import appears.

`test/offline/test_invariants.py` and `test/offline/test_negative.py` verify the
runtime consequences of these boundaries, including forged authorization and
audit tampering.
