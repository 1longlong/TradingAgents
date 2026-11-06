# Permission Model

Status: Implemented (Step 14).

Machine-readable source: `.opencode/permissions.jsonc`. This document mirrors
that file and records the human gates used during implementation.

## Defaults

- Default read: **false**
- Default write: **false**
- Enforcement: CI enabled; violations block the change.

## Readable Paths

- `AGENTS.md`, `Prompt.md`, `baseline.md`, `architecture-blueprint.md`
- `docs/**`
- `src/**`
- `test/**`

## Writable Paths

- `src/trading/**`
- `src/safety/**`
- `test/offline/**`
- `test/live/**`
- `docs/ai-use-log.yaml`

## Read-Only Paths

- `docs/**` is read-only by default, including `docs/architecture/**`,
  `docs/code-governance/**`, and `docs/req/**`.
- The Step 14 architecture/governance documents were written only after explicit
  human authorization; the machine-readable permission file still marks
  `docs/**` read-only for normal operation.
- `AGENTS.md`, `Prompt.md`, and the governance files outside `docs/` remain
  read-only to the agent.

## Frozen Paths

- `tradingagents/agents/**`
- `tradingagents/graph/**`
- `tradingagents/dataflows/**`
- `tradingagents/llm_clients/**`
- `.opencode/rules.md`
- `.agent/rules.md`

The frozen main CLI (`cli/main.py`) was not modified. Inspection/reset lives in
the standalone `src/trading/cli.py` entry point instead.

## Safety Gate

Guard `safety-write-requires-approval`:

- Trigger: write to `src/safety/**`
- Required before write:
  - `human_approval`
  - `architecture_decision`

The human owner granted both for the safety-engine implementation. The safety
engine is the authoritative gatekeeper: it runs SR-01..SR-10, applies AP-01 and
AP-02, owns the provenance token, and is the only module that calls the
simulated executor.

## Operational Constraints

- No real broker API.
- No broker SDKs, network clients, or `tradingagents.dataflows` imports in the
  subsystem.
- No direct wall-clock access outside `src/trading/clock.py`.
- Audit entries are append-only.
- Portfolio reset follows the audited `StateStore.reset()` path and never
  truncates the audit log.
- Live tests require both `RUN_LIVE_TRADING_TESTS=1` and a configured provider
  key; otherwise they are skipped.
