# src/ — deliverable mapping for D8

The authoritative project slide lists `src/`, `test/offline/`, and `test/live/`.
This inherited repository does **not** use a `src/` code tree. The canonical
source trees are:

- `tradingagents/` — the library package (agents, dataflows, evidence, debate,
  graph, llm_clients, backtest, portfolio, reporting, default_config).
- `cli/` — the command-line interface package.

This `src/README.md` maps the slide deliverable **D8** onto the real trees. **No
source is duplicated or relocated into `src/`.**

## Mapping D8 to the canonical source value

| Slide deliverable | Canonical location in this repo |
| --- | --- |
| Application/library source | `tradingagents/` |
| Command-line interface | `cli/` |
| Graph / LangGraph workflow | `tradingagents/graph/` |
| Data Quality Gate (feature) | `tradingagents/evidence/`, `tradingagents/graph/data_quality_gate.py` |
| Dynamic debate termination (feature) | `tradingagents/debate/` |

## Why no `src/` code tree

The repository was inherited with `tradingagents/` + `cli/` as its package
roots (see `pyproject.toml` `[tool.setuptools.packages.find]`). Introducing a
`src/` package tree would require relocating or duplicating source, which is
explicitly out of scope and risks breaking the importable package name
`tradingagents`. Therefore `src/` exists only as a documentation pointer.

## Cleanup note (removed)

An empty placeholder directory (`src/README-placeholder`) was removed during
creation; it was not needed and is gone.