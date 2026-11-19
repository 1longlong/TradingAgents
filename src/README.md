# Source packages

`tradingagents/` contains the shared analysis, evidence, data-quality gate,
debate, usage-ledger, reporting, backtest and comparison implementation.
`cli/` contains the existing command-line interface. `tradingagents_web/`
contains the WebUI entry point and presentation layer. These are the canonical
packages under `src/`; there is no duplicate root implementation. Packaging
and pytest path setup are defined in the repository-root `pyproject.toml`.
