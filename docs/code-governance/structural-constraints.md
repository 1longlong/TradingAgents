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

---

## Personal delivery structural constraints (SC-01…SC-23)

The Release structural rules above (source-tree ownership, package boundaries,
cross-package rules, test tree, naming, serialization, trace/ADR rule) remain normative.
The personal delivery recorded its own constraints as `SC-01…SC-23`. They are additive and
use a distinct identifier series; where they restate a Release rule, the Release rule
govers. `src/trading/` and `src/safety/` are real source trees, not pointer directories;
only `test/offline/` and `test/live/` are pointer READMEs.

Status: **established 2026-11-19** for the CS5351 final-submission tree (base
commit `50b2ca3`). These constraints describe the repository as it actually is,
not an idealized layout. A constraint marked `DOCUMENTED_ONLY` has no mechanical
check; a constraint marked `NOT_VERIFIED` has a claimed mechanism whose
effectiveness was not confirmed here.

Canonical trees:

- product code: `tradingagents/` (package) and `cli/` (console entry point);
- tests: `tests/`;
- experiment artifacts: `token_benchmarks/`;
- governance/documentation: `docs/` plus the root `AGENTS.md`,
  `architecture-blueprint.md`, and `Prompt.md`;
- operational tooling: `scripts/`.

### 1. Layout and relocation

| ID | Constraint | Rationale | Check | Status |
| --- | --- | --- | --- | --- |
| SC-01 | `tradingagents/` and `cli/` are the only product source trees. | `pyproject.toml` packages them (`include = ["tradingagents*", "cli*"]`); imports and tests assume these paths. | `git ls-files 'tradingagents/**/*.py' 'cli/**/*.py'`; `python -c "import tradingagents, cli.main"` | `ENFORCED` by packaging/imports |
| SC-02 | Do not move, rename, or duplicate the source tree without written instructor approval. | Paths appear in tests, scripts, benchmark specs, and evidence; a move silently breaks frozen references. | Manual review of `git diff --stat`; CI clean-install import | `DOCUMENTED_ONLY` |
| SC-03 | `src/` is a layout pointer only, not a second source tree. | The course slide layout names `src/`, but the implementation lives in `tradingagents/` + `cli/`; duplicating it would fork the code. | `find src -type f -not -name 'README.md'` (no product code) | `DOCUMENTED_ONLY` |
| SC-04 | `test/offline/` and `test/live/` are layout pointers only. | Offline tests already live in `tests/`; live tests are `tests/` modules marked `@pytest.mark.integration`. | `find test -type f -not -name 'README.md'`; `pytest --collect-only` uses `testpaths = ["tests"]` | `DOCUMENTED_ONLY` |
| SC-05 | All Python tests live under `tests/`, named `test_*.py`. | `pyproject.toml` sets `testpaths = ["tests"]`; CI runs `pytest -q` from the root. | `git ls-files 'tests/test_*.py'`; a test outside `tests/` is not collected | `ENFORCED` by pytest config |
| SC-06 | No new top-level package that duplicates an existing one. | Duplicate trees drift and confuse imports; the package list is declarative. | Review `pyproject.toml` `[tool.setuptools.packages.find]` and the diff | `DOCUMENTED_ONLY` |

### 2. Import and dependency boundaries

These are enforced by convention and review, not by an import-linter rule.

| ID | Constraint | Rationale | Check | Status |
| --- | --- | --- | --- | --- |
| SC-07 | `tradingagents.dataflows/` must not import `tradingagents.agents`, `tradingagents.graph`, or `cli`. | Dataflows is the bottom layer (vendors, dates, validation); a back-edge would create cycles and couple transport to orchestration. | `grep -rn '^from tradingagents\.\(agents\|graph\)\|^import tradingagents\.\(agents\|graph\)' tradingagents/dataflows` → empty | `ENFORCED` by convention (grep is clean) |
| SC-08 | `tradingagents.agents/` must not import `tradingagents.graph`. | Agents are graph nodes; the graph imports agents, not the reverse. | `grep -rn '^from tradingagents\.graph\|^import tradingagents\.graph' tradingagents/agents` → empty | `ENFORCED` by convention (grep is clean) |
| SC-09 | Product code (`tradingagents/`) must not import `cli` or `scripts`. | `cli` and `scripts` are consumers; product code must stay importable headlessly. | `grep -rn '^from cli\|^import cli\|^from scripts\|^import scripts' tradingagents` → empty | `ENFORCED` by convention (grep is clean) |
| SC-10 | `scripts/` may import `tradingagents`; product code may not import `scripts`. | Scripts are operational tooling, not a library surface. | Same grep as SC-09 plus review of new imports | `DOCUMENTED_ONLY` |
| SC-11 | Runtime dependencies are declared in `pyproject.toml`; no undeclared imports and no new dependency without approval. | CI's clean-install smoke test catches undeclared runtime deps. | `pip install . && python -c "import tradingagents, cli.main"`; review of `dependencies` | `ENFORCED_BY_CI` |
| SC-12 | Optional/provider-specific dependencies stay in optional extras (e.g. `bedrock`). | Keeps the base install offline-capable and lean. | Review `pyproject.toml`; `tests/test_bedrock_provider.py` skips when absent | `DOCUMENTED_ONLY` |
| SC-13 | No network or LLM call from pure helper modules; network access stays in dataflow/vendor modules and provider clients. | Determinism and testability; the offline suite must not dial out. | Review; `tests/conftest.py` vendor-block fixtures | `DOCUMENTED_ONLY` |

### 3. Frozen artifacts

| ID | Constraint | Rationale | Check | Status |
| --- | --- | --- | --- | --- |
| SC-14 | `token_benchmarks/**/specs/**` and the batch `MANIFEST.sha256` are immutable once registered. | They are the pre-registered experiment definition; editing them invalidates published comparisons. | `cd token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3 && sha256sum -c MANIFEST.sha256` (55 entries) | `ENFORCED_BY_TOOL` |
| SC-15 | The V3 `EXPERIMENT_PROTOCOL_V3.md` and `CAND01_BATCH_2X2_PROTOCOL_V3.md`, `CONFIG_HASH_MANIFEST.csv`, memory baselines, and freeze/attestation records are immutable. | They record what was registered and audited; silent edits are indistinguishable from tampering. | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/MANIFEST.sha256`; `scripts/c3_verify_protocol_freeze.py`; `tests/test_c3_final_freeze.py` | `ENFORCED_BY_TOOL` |
| SC-16 | Release tags `rc1`, `c3-final-freeze`, `c3-v3-final-freeze`, `cand01-v3-final-remediation` must not be moved or deleted. | Tags anchor which tree the evidence describes. | `git tag --list`; tags are not recreated by a normal commit | `DOCUMENTED_ONLY` |
| SC-17 | Generated artifacts are not hand-edited; regeneration goes through the owning script with authorization. | The generator and the delivered bytes must agree; hand edits make `--check` lie. | Re-run the generator in `--check` mode; compare `code_state.json`/spec hashes | `DOCUMENTED_ONLY` (path-dependent; see verification doc) |
| SC-18 | Do not commit run outputs, caches, or credentials into `token_benchmarks/`. | Evidence must be reproducible and non-secret; large/volatile outputs should stay untracked. | `git status --porcelain`; review of new files | `DOCUMENTED_ONLY` |

### 4. Files, naming, and serialization

| ID | Constraint | Rationale | Check | Status |
| --- | --- | --- | --- | --- |
| SC-19 | New text/data files should stay under 1 MiB; do not add new binary artifacts (images, archives, datasets) without approval. | Keeps review and clone cheap; existing `assets/*.png` predate this rule. | `find . -path ./.git -prune -o -path ./.venv -prune -o -type f -size +1M -print` → empty today | `DOCUMENTED_ONLY` |
| SC-20 | Python naming: `snake_case` modules/functions, `PascalCase` classes, `UPPER_SNAKE` constants and reason codes. | Matches the existing package; stable reason codes are consumed downstream. | `ruff check` (naming subset) plus review | `DOCUMENTED_ONLY` |
| SC-21 | Test modules are `tests/test_<subject>.py` and test functions are `test_<behavior>`. | Discoverability and traceability to the module under test. | `git ls-files 'tests/test_*.py'` | `ENFORCED` by pytest discovery |
| SC-22 | JSON/schema artifacts use stable, sorted keys and explicit schema versions; do not silently change a schema version. | Frozen specs and summaries are compared byte-for-byte; version bumps are reviewable events. | Review; benchmark validator (`scripts/token_benchmark.py validate`) | `DOCUMENTED_ONLY` |
| SC-23 | Documentation paths referenced from `AGENTS.md`, `Prompt.md`, and the rules files must exist. | Dead links make the governance unverifiable. | The path-existence script in `docs/code-governance/verification-constraints.md` §4 (manual; the submission validator checks required artifacts and trace paths, not this rule) | `DOCUMENTED_ONLY` |

### 5. Directory ownership

- `tradingagents/**` — product behavior; changes need tests and a behavior-level
  rationale.
- `cli/**` — user interface only; no business logic that belongs in the package.
- `tests/**` — verification; tests may be strengthened, never weakened to pass.
- `token_benchmarks/**` — frozen evidence; additions follow the protocol and
  require authorization.
- `docs/**`, `AGENTS.md`, `Prompt.md`, `.opencode/**`, `.agent/**` — governance;
  edits are themselves changes to the rules and need review.
- `scripts/**` — operational tooling; prefer a new script over an in-place
  behavior change to a frozen one.

### 6. Current verified state (2026-11-19)

- Product import boundary greps (SC-07/08/09) return no matches.
- `sha256sum -c MANIFEST.sha256` in the V3 batch verifies all 55 entries.
- No tracked file exceeds 1 MiB; the only binaries are existing
  `assets/*.png` images.
- `docs/` is populated by the final-submission documentation set; the canonical
  source and test trees were unchanged from `50b2ca3` **on the personal submission branch**.
  In the merged integration worktree the main-system trees contain both branches' work;
  that is expected and is not a structural violation.

## Imported simulated-trading boundaries

- `src/trading/` owns simulated models, clocks, audit, portfolio, persistence,
  executor, approval, pipeline, backtest, runtime and standalone inspection CLI.
- `src/safety/` owns deterministic rules and the sole safety engine gateway.
  Only `src/safety/engine.py` may import `trading.executor`; preserve that AST-
  checked boundary. New safety edits require explicit human approval and an ADR.
- Offline subsystem tests live in `test/offline/trading/`; the separately
  authorized live smoke test lives in `test/live/trading/`. Do not duplicate
  them under a root `tests/` tree or relocate the existing core/WebUI suites.
- Importing the subsystem adds no broker capability or WebUI execution route.
