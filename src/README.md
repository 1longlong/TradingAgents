# `src/` — source-layout map (no code lives here)

The course slide deck refers to a `src/` source directory. This repository keeps
the inherited upstream layout instead: the product code is in `tradingagents/`
and the command-line entry points are in `cli/`. **There is no `src/` source
tree, no copy, and no symlink**, because duplicating the tree would create a
second, drifting copy of the code and would violate the no-relocation
constraint.

This file is a pointer, not a package. Nothing imports it.

## Where the code actually is

| Course slide concept | Real path | What it contains |
| --- | --- | --- |
| Application / graph | `tradingagents/graph/` | Graph construction, propagation, routing, reflection, and the trading graph. |
| Agents | `tradingagents/agents/` | Analysts, researchers, managers, trader, risk debators, and portfolio manager. |
| Data layer | `tradingagents/dataflows/` | Vendor adapters, point-in-time handling, routers, caches, and news scope. |
| Observability | `tradingagents/observability.py` | Run metrics collector, callback handler, attribution scopes, telemetry schema. |
| LLM clients | `tradingagents/llm_clients/` | Provider clients, model catalog, and retry behavior. |
| Configuration | `tradingagents/default_config.py` | Defaults and `TRADINGAGENTS_*` environment overlay. |
| CLI | `cli/` | Typer app, interactive selections, display, and remembered preferences. |
| Entry point | `main.py` | Convenience launcher that delegates to the CLI. |

## Why not duplicate into `src/`

- A copy would be a second source of truth; fixes could land in one tree and not
  the other.
- A symlink is invisible to Windows checkouts and to packaging metadata.
- `pyproject.toml` packages `tradingagents*` and `cli*`; adding `src/` would
  require a packaging change with no functional benefit.

The corresponding test-side pointers are in [`test/offline/README.md`](../test/offline/README.md)
and [`test/live/README.md`](../test/live/README.md).
