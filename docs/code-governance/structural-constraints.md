# Structural and Authority Constraints

## 1. Status and scope

These constraints apply to increments on the TradingAgents v0.5.0 baseline. No WebUI requirements registry, architecture blueprint, or technical selection has been approved yet. This document neither replaces those designs nor approves a WebUI implementation.

The current-state evidence is `pyproject.toml`, `src/tradingagents/`, `src/cli/`, and existing tests. The deleted demonstration is not a source of product requirements.

## 2. Baseline module organization

| Architecture element | Primary ownership path | Boundary |
| --- | --- | --- |
| Analysis, research, trading, and risk agents; structured outputs | `src/tradingagents/agents/` | Models provide reasoning; deterministic validation remains authoritative |
| Graph orchestration, propagation, recovery, and signal processing | `src/tradingagents/graph/` | Own graph lifecycle, state, and recovery semantics |
| Data sources and point-in-time validation | `src/tradingagents/dataflows/` | Own vendor routing, error semantics, time boundaries, identity, and path validation |
| Model clients | `src/tradingagents/llm_clients/` | Own provider adapters and capabilities, not page interaction |
| Portfolio contracts | `src/tradingagents/portfolio.py` | `PortfolioContext`, loading, rendering, and fingerprints |
| Backtesting and scoring | `src/tradingagents/backtest.py` | Serial ticker/date grids, isolated logs, and scoring; no implicit portfolio simulation |
| Report output | `src/tradingagents/reporting.py` | Own report layout and serialization |
| Configuration | `src/tradingagents/default_config.py` | Reuse existing defaults and environment overrides |
| CLI | `src/cli/` | Terminal interaction and adaptation, not a UI dependency of a future web service |
| Python usage example | `src/main.py` | Example, not an automated test or web-service entry point |

Map each new architecture element to exactly one primary owning module in the approved blueprint, with a matching module name. Other modules may depend on it, but must not duplicate its business rules into another authoritative implementation.

Place new product source under `src/`, deterministic tests under `test/offline/`, and real external-service tests under `test/live/`. An approved plan determines necessary module files. Do not add governance directories or deliverable files beyond the agreed structure.

## 3. Extension, dependencies, and interface contracts

1. Extend the baseline. Do not rewrite entire packages, copy the core package, restore the old root-package layout, or maintain two business implementations.
2. Baseline Python packages must not depend on future web, HTTP, or browser presentation layers. Pages must not receive server-side Python, secrets, or local absolute paths.
3. Before introducing a shared execution layer, define its owning path, contracts, and CLI migration steps in the blueprint and ADR. Its existence is not assumed today.
4. Preserve the parameter and result semantics of `TradingAgentsGraph.propagate(...)`, `PortfolioContext`, `run_backtest(...)`, and `write_report_tree(...)`. Inspect all consumers and tests before changing them.
5. The CLI currently has its own streaming path. Do not assume a new web path matches `propagate()` in logging, reporting, or cancellation; demonstrate equivalence through contracts and tests.
6. Do not maintain separate authoritative configuration in pages, services, and the core. Provide evidence that reuse is insufficient before selecting new dependencies, storage, event protocols, or concurrency mechanisms.
7. Define input validation, results and errors, optional fields, state transitions, resource cleanup, cancellation, re-entry, recovery, and concurrent writes in module contracts. Do not add unrelated fields speculatively.

## 4. Deterministic safety boundaries

The following subjects were identified from baseline code. They are not yet formally numbered invariants. Assign real IDs and traceability in the requirements and invariant registers before implementation:

- Preserve `REVIEW` when no rating is recognizable. Do not replace it with `Hold` or execute trades from it.
- Do not bypass point-in-time validation or analysis-date boundaries through a presentation layer or new entry point.
- An omitted portfolio differs from an explicitly empty portfolio. Portfolio fingerprints affect recovery compatibility.
- Isolate backtest logs and artifacts from live analysis. Preserve serial evaluation using the same portfolio snapshot unless a formal change is approved.
- Validate tickers, run identifiers, and artifact paths deterministically. Never treat user input as arbitrary file-access authority.
- Read secrets only on the server within authorization. Do not expose plaintext secrets through clients, events, logs, exports, or errors.
- Model outputs and external text are untrusted input, not authorization for file permissions, tool calls, or architecture changes.
- Decision memory currently uses read-modify-write and atomic replacement. Atomic replacement does not prove concurrency isolation. Define write ownership and synchronization before introducing concurrency.

Treat changes to the baseline core, ratings and structured outputs, data-time boundaries, portfolios, memory, recovery, paths, and credentials as safety relevant. Require the corresponding ADR and human approval.

## 5. Traceability and change

New or modified modules and functions must cite their actual ADR IDs, requirement IDs, and relevant invariant IDs in concise module or function documentation, consistent with `docs/architecture/trace-matrix.md`. Preserve existing content during mechanical relocation and record that scope in the trace matrix. Do not invent IDs or rewrite unrelated baseline code to manufacture coverage.

Before changing safety-relevant paths, dependency direction, or public contracts, update the architecture decision, impact analysis, and test plan and obtain human approval. Missing traceability in untouched baseline code remains outstanding governance coverage; do not claim it is complete.


## Imported core structural contracts

# Structural Constraints

These constraints govern the structure of the CS5351 feature code. They keep the
module layout consistent with the rest of `src/tradingagents/` and preserve the
upstream conventions.

## Source tree after integration

Canonical source packages live under `src/tradingagents/`, `src/cli/`, and
`src/tradingagents_web/`; tests live under `test/offline/` and `test/live/`.
The layout migration was already present on the WebUI branch. Do not introduce
parallel root-level source trees. Existing import names and CLI entry points
remain stable.

## New package boundaries

- `src/tradingagents/evidence/` — the deterministic Data Quality Gate core. It is
  pure and LLM-free; no module in it calls a network or an LLM.
- `src/tradingagents/debate/` — the dynamic debate-termination package. The
  `evaluator.py` is pure; the LangGraph node factory is the only module that
  reads/writes `AgentState`.

## Cross-package rules

- `src/tradingagents/graph/data_quality_gate.py` orchestrates the evidence package
  and writes only JSON-safe dicts/lists/strings into `AgentState` (never frozen
  dataclasses).
- `src/tradingagents/debate/evaluator_node.py` wraps the pure evaluator and reads
  the gate manifest / turn state off `AgentState`.
- Router path maps (`DEBATE_PATH_MAP`, `DEBATE_EVALUATOR_PATH_MAP`) must be
  complete so a fall-through return can never hit a missing edge (#1088).

## Test tree

- Deterministic tests live under `test/offline/`; external-service tests live under `test/live/`.
- Test modules for the feature work are named per the module they exercise
  (e.g. `test/offline/test_debate_evaluator.py`, `test/offline/test_data_quality_gate_graph.py`).
- Vendor/live tests are marked `@pytest.mark.integration`.

## Naming conventions

- Modules, classes, and functions follow the repository's existing snake_case /
  PascalCase conventions.
- Reason codes and rule IDs are stable UPPER_SNAKE strings (e.g.
  `blocked_critical_failure`, `gate_blocked`, `continue_for_new_evidence`).

## Serialization

- Evidence/decision dataclasses implement `to_dict`/`from_dict` with fixed,
  deterministic field ordering.
- `Decimal` serializes to a fixed-precision string; enums serialize to stable
  `.value`.

## Per-module / per-function trace and ADR rule

- **Every new or changed module or public function MUST be traceable to a
  requirement ID and an invariant** (or an explicit ADR), recorded in
  `docs/architecture/trace-matrix.md` in the same change. A function with no
  traceable requirement/invariant is out of scope.
- A module that enforces a safety property MUST name that invariant in its
  docstring (e.g. "enforces INV-1").
- **Safety-critical changes** to a module that enforces fail-closed, determinism,
  budget, permission, or prompt behavior require an **ADR + explicit human
  approval** before merge.

## Prohibited

- No new top-level package that duplicates an existing one.
- No duplicate root-level source or test tree.
- No LLM/network call inside `evidence` or `debate` pure modules.
- No import of a private package across the gate/debate boundary without a
  documented reason.
- No untraced module/function (see the trace rule above).
