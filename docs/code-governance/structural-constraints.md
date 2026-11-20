# Structural Constraints

These constraints govern the structure of the CS5351 feature code. They keep the
module layout consistent with the rest of `tradingagents/` and preserve the
upstream conventions.

## Source tree (authoritative, do not relocate or duplicate)

- Canonical main-system source trees: `tradingagents/` and `cli/`.
- Canonical tests: `tests/`.
- The approved simulated-trading subsystem is an independent source tree under
  `src/trading/` and `src/safety/`; its tests live under `tests/trading/`.
  This exception is explicitly approved and must not be read as a general
  invitation to duplicate or relocate the main-system trees.
- The old `test/offline/` and `test/live/` directories are pointer READMEs only;
  they contain no test code.

## New package boundaries

- `tradingagents/evidence/` — the deterministic Data Quality Gate core. It is
  pure and LLM-free; no module in it calls a network or an LLM.
- `tradingagents/debate/` — the dynamic debate-termination package. The
  `evaluator.py` is pure; the LangGraph node factory is the only module that
  reads/writes `AgentState`.
- `src/trading/` — the independent simulated-trading subsystem: models, clocks,
  audit, portfolio, persistence, executor, approval gate, pipeline, backtest,
  runtime, and standalone CLI.
- `src/safety/` — deterministic safety rules and the sole safety-engine gateway.
  No module outside `src/safety/engine.py` may import the executor.

## Cross-package rules

- `tradingagents/graph/data_quality_gate.py` orchestrates the evidence package
  and writes only JSON-safe dicts/lists/strings into `AgentState` (never frozen
  dataclasses).
- `tradingagents/debate/evaluator_node.py` wraps the pure evaluator and reads
  the gate manifest / turn state off `AgentState`.
- Router path maps (`DEBATE_PATH_MAP`, `DEBATE_EVALUATOR_PATH_MAP`) must be
  complete so a fall-through return can never hit a missing edge (#1088).

## Test tree

- All tests live under `tests/`.
- Main-system test modules are named per the module they exercise
  (e.g. `tests/test_debate_evaluator.py`, `tests/test_data_quality_gate_graph.py`).
- Simulated-trading tests live under `tests/trading/`; the live smoke test is
  under `tests/trading/live/` and is opt-in via `RUN_LIVE_TRADING_TESTS=1`.
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
- No unapproved `src/` or `test/` code tree; only the approved `src/trading/`, `src/safety/`, and `tests/trading/` paths are exceptions.
- No LLM/network call inside `evidence` or `debate` pure modules.
- No import of a private package across the gate/debate boundary without a
  documented reason.
- No untraced module/function (see the trace rule above).