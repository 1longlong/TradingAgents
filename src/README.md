# src/ — simulated trading subsystem and source-layout map

# Source packages
`tradingagents/` contains the shared analysis, evidence, data-quality gate,
debate, usage-ledger, reporting, backtest and comparison implementation.
`cli/` contains the existing command-line interface. `tradingagents_web/`
contains the WebUI entry point and presentation layer. These are the canonical
packages under `src/`; there is no duplicate root implementation. Packaging
and pytest path setup are defined in the repository-root `pyproject.toml`.

## Standalone simulated trading

No upstream source is duplicated or relocated here. The subsystem has no real
broker path and never places a real order.

## Source-layout map (course slide concepts → real paths)

The course slide deck refers to a `src/` source directory. This repository keeps
the inherited upstream layout for the product: the main application is in
`tradingagents/`, the command-line entry points are in `cli/`, and tests are in
`tests/`. `src/trading/` and `src/safety/` are the approved **additive** subsystem
above — they are real source trees, not pointers, and they are not a copy of the
product.

| Course slide concept | Real path | What it contains |
| --- | --- | --- |
| Application / graph | `tradingagents/graph/` | Graph construction, propagation, routing, reflection, and the trading graph. |
| Agents | `tradingagents/agents/` | Analysts, researchers, managers, trader, risk debators, and portfolio manager. |
| Data layer | `tradingagents/dataflows/` | Vendor adapters, point-in-time handling, routers, caches, and news scope. |
| Observability | `tradingagents/observability.py` | Run metrics collector, callback handler, attribution scopes, telemetry schema. |
| Evidence / debate packages | `tradingagents/evidence/`, `tradingagents/debate/` | Deterministic gate core and dynamic debate termination. |
| Simulated trading subsystem | `src/trading/`, `src/safety/` | Approved additive subsystem (see above). |
| LLM clients | `tradingagents/llm_clients/` | Provider clients, model catalog, and retry behavior. |
| Configuration | `tradingagents/default_config.py` | Defaults and `TRADINGAGENTS_*` environment overlay. |
| CLI | `cli/` | Typer app, interactive selections, display, and remembered preferences. |
| Entry point | `main.py` | Convenience launcher that delegates to the CLI. |
| Tests | `tests/` | Canonical offline suite; `tests/trading/` is the subsystem's tree. |

## Why the product is not duplicated into `src/`

- A copy would be a second source of truth; fixes could land in one tree and not
  the other.
- A symlink is invisible to Windows checkouts and to packaging metadata.
- `pyproject.toml` packages `tradingagents*` and `cli*`; adding a duplicate tree
  would require a packaging change with no functional benefit.

The simulated-trading subsystem is the one approved exception: it is a separate,
deterministic layer with its own tree and tests, and it does not modify
`tradingagents/` or `cli/main.py`.

The corresponding test-side pointers are in [`test/offline/README.md`](../test/offline/README.md)
and [`test/live/README.md`](../test/live/README.md).

`trading/` contains the simulated models, clock, audit, portfolio, persistence,
executor, approval gate, pipeline, backtest, runtime and inspection CLI.
`safety/` contains deterministic rules and the only execution gateway.
Subsystem tests live under `test/offline/trading/` and `test/live/trading/`.
The analysis core and CLI retain their existing packages; no real broker path
or new WebUI execution endpoint is introduced by importing this subsystem.
