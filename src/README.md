# src/ — simulated trading subsystem

`src/trading/` and `src/safety/` are the approved independent simulated-trading
subsystem. The canonical upstream source trees remain `tradingagents/` and
`cli/`; this subsystem is additive and is invoked after graph output.

- `src/trading/` — models, clocks, audit, portfolio, persistence, executor,
  approval gate, pipeline, backtest, runtime, and standalone CLI.
- `src/safety/` — deterministic rules and the safety engine.
- `tests/trading/` — the subsystem's canonical tests.

No upstream source is duplicated or relocated here. The subsystem has no real
broker path.
