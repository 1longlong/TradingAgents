# Application source

All production packages live in this directory. The public imports and installed
CLI commands remain stable. There is no duplicate root source tree.

| Package | Responsibility |
| --- | --- |
| `tradingagents/` | Analysis agents, evidence, deterministic data-quality and output guards, debate, usage, memory, recovery, reports and scoring backtests. |
| `cli/` | Existing Typer/Rich interface and preferences. |
| `tradingagents_web/` | FastAPI runtime/API and bilingual React frontend over the shared core. |
| `trading/` | Independent deterministic simulated accounts, portfolios, approval flow, audit and walk-forward execution. |
| `safety/` | Safety rules and the sole simulated-executor gateway. |

`pyproject.toml` discovers packages under `src/`. Tests are real files in
`test/offline/` and `test/live/`; they are not pointers into a root `tests/` tree.
Real broker execution is outside this project. See the root README and
`architecture-blueprint.md` for installation, ownership and contracts.
