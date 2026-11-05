# AGENTS.md

## Project

This repository is a governed extension of TradingAgents.
The goal is to add a simulated trading subsystem on top of the existing multi-agent analysis pipeline.

Core principles:
- LLM outputs are advisory.
- The deterministic rule engine is authoritative.
- All trade execution is simulated. No real broker API is used.
- Every approved trade must update simulated positions and cash.
- Every decision and rule evaluation must be written to an append-only audit log.

## Read Order

1. AGENTS.md
2. Prompt.md
3. architecture-blueprint.md
4. docs/architecture/adr/001-simulated-trading-system.md
5. docs/architecture/invariants.md
6. docs/architecture/permission-model.md
7. docs/architecture/trace-matrix.md
8. docs/code-governance/structural-constraints.md
9. docs/code-governance/verification-constraints.md
10. docs/req/requirements.yaml

## Allowed Changes

Writable paths:
- src/trading/**
- src/safety/**
- test/offline/**
- test/live/**
- docs/ai-use-log.yaml

Read-only paths:
- AGENTS.md
- Prompt.md
- docs/architecture/**
- docs/code-governance/**
- docs/req/**
- .opencode/**
- .agent/**

Frozen paths:
- tradingagents/agents/**
- tradingagents/graph/**
- tradingagents/dataflows/**
- tradingagents/llm_clients/**

## Module Organization

Expected modules:
- src/safety/rules.py: deterministic safety rules
- src/safety/engine.py: rule engine entry point
- src/trading/executor.py: simulated order execution
- src/trading/portfolio.py: positions, cash, cost, PnL
- src/trading/audit.py: append-only audit log
- src/trading/models.py: shared data models

## Required Behavior

- Read AGENTS.md first.
- Produce an execution plan before writing any code.
- Stop for human approval before generating code.
- Every new feature must have at least one negative test.
- Every invariant must have at least one test that fails when the invariant is violated.
- Update docs/ai-use-log.yaml whenever code or prompts change.
- If a requirement is ambiguous, ask the human instead of assuming.

## Team Collaboration

- Governance files are maintained by one owner only:
  - AGENTS.md, Prompt.md, .opencode/rules.md, .opencode/permissions.jsonc
- Requirements IDs are pre-allocated per member. Do not reuse IDs from another member's range.
- Code modules are owned per member. Do not modify another member's module without a PR and review.
- Every PR must reference the requirement ID it implements and pass all CI gates.
- Merge conflicts in governance files must be resolved by the governance owner, not by the agent.
