# Source packages

`tradingagents/` contains the shared analysis, evidence, data-quality gate,
debate, usage-ledger, reporting, backtest and comparison implementation.
`cli/` contains the existing command-line interface. `tradingagents_web/`
contains the WebUI entry point and presentation layer. These are the canonical
packages under `src/`; there is no duplicate root implementation. Packaging
and pytest path setup are defined in the repository-root `pyproject.toml`.

## Standalone simulated trading

`trading/` contains the simulated models, clock, audit, portfolio, persistence,
executor, approval gate, pipeline, backtest, runtime and inspection CLI.
`safety/` contains deterministic rules and the only execution gateway.
Subsystem tests live under `test/offline/trading/` and `test/live/trading/`.
The analysis core and CLI retain their existing packages; no real broker path
or new WebUI execution endpoint is introduced by importing this subsystem.
