# Integrated core and WebUI records

The canonical layout is `src/` and `test/`. The core records below describe the
release data-quality gate, evidence, debate, usage ledger and output guards;
the WebUI records describe the presentation extension over that core. Existing
requirement and invariant IDs remain scoped to their original modules. An
unqualified core ADR number refers to the release ADR with its descriptive
filename; a WebUI ADR number refers to the WebUI ADR with its descriptive
filename. Both sets remain present. Historical approvals retain their original
scope and do not approve this merge or a new feature. Verification results are
historical unless explicitly identified as a merged-tree run.

## Release core

# Option Ledger — Alternative Designs and Why We Chose What We Did

Each row records an alternative we considered, why we did not take it, and the
decision we took. The decision columns are stable IDs; the gate and evaluator
ADRs are the authoritative decision records.

## Data Quality Gate

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DQG-ALT-1 | LLM-based quality judge (prompt an LLM to score data quality) | Non-deterministic, requires an LLM call, not offline-testable, costly, hard to audit a verdict. | Deterministic, LLM-free gate (`FR-DQG-001`). |
| DQG-ALT-2 | Inline `SourceAttempt` nested inside `EvidenceRecord` | Breaks acyclic serialization; hard to round-trip JSON; violates INV-4. | Separate `SourceAttempt` record (7 fields), never embedded. |
| DQG-ALT-3 | Float math for normalized financial values | Float noise breaks deterministic comparisons and point-in-time reproducibility. | `Decimal` (quantized via `quantize_decimal`). |
| DQG-ALT-4 | Gate raises the whole run on any low quality | Too aggressive; blocks runs a human would tolerate (degraded). | Tiered verdicts `blocked > degraded > normal` (`FR-DQG-002`). |
| DQG-ALT-5 | Random `run_id` for evidence IDs | Breaks reproducibility; evidence differs per run. | `run_id` derived from `(trade_date, normalized symbol)` (`FR-DQG-003`). |
| DQG-ALT-6 | Gate writes frozen dataclasses into AgentState | Not checkpoint/JSON serializable; LangGraph state is dicts. | Write serialized `to_dict()` forms only (`FR-DQG-001`). |

## Dynamic debate termination

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DDT-ALT-1 | Always run a fixed `max_debate_rounds` (upstream default) | Wastes tokens/turns after convergence or no-new-evidence; no summary reserve guarantee. | Dynamic, evidence-aware evaluator (`FR-DDT-001`). |
| DDT-ALT-2 | LLM-judged "is the debate over?" | Non-deterministic, adds cost and an extra LLM call, not auditable deterministically. | Deterministic `evaluate_round` rule ordering (`FR-DDT-001`). |
| DDT-ALT-3 | Prose-only turn metadata parsed opportunistically | Unreliable; a missed stance could extend or shorten debate arbitrarily. | Structured `DEBATE_METADATA` marker with a best-effort prose fallback; a parse failure contributes zero new evidence and cannot extend the debate (`FR-DDT-002`). |
| DDT-ALT-4 | No summary reserve; rely on wall-clock only | A run could exhaust budget mid-debate and lose its report. | Explicit summary tokens/time reserve + hard max tokens/time/calls (`FR-DDT-003`). |
| DDT-ALT-5 | Break upstream by defaulting to dynamic always | Regresses legacy behavior and default `pytest -q`. | `debate_termination.enabled` default; `False` reproduces fixed-round routing (`FR-DDT-004`). |
| DDT-ALT-6 | Incomplete router path map relying on fall-through | A fall-through could hit a missing edge and crash LangGraph (#1088). | Complete `DEBATE_PATH_MAP` / `DEBATE_EVALUATOR_PATH_MAP` (`FR-DDT-001`). |

## Documentation / delivery

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DOC-ALT-1 | Duplicate source into `src/` to match the slide | Duplicates code, risk of drift, out of scope. | Map the slide layout onto `src/tradingagents/` + `src/cli/` via `src/README.md` and `test/*/README.md`. |
| DOC-ALT-2 | Claim a green full suite | False; known date-sensitive and network-reachability failures remain. | Record exact observed outcomes and note failures (`evaluation-logbook.md`, `risk-list.md`). |

## WebUI extension

# TradingAgents WebUI Option Ledger

Status: **Approved for documentation by the human owner on 2026-11-05.** "Approved" means the decision is accepted for documentation. It does not authorize implementation or dependency installation. "Rejected" records a reason, not a permanent prohibition.

| ID | Decision area | Option | Status | Rationale |
| --- | --- | --- | --- | --- |
| OL-001 | Deployment | Local loopback, single user, no authentication | Approved | Confirmed minimum assumption; smallest security and operational surface. |
| OL-002 | Deployment | LAN access with a shared password | Deferred | Requires session and credential handling not confirmed by the user. |
| OL-003 | Deployment | Public multi-user with accounts | Out of scope | Requires auth, tenancy, quotas, and audit. |
| OL-004 | Run concurrency | One active run per process | Approved | Matches the global configuration and non-concurrent memory writer. |
| OL-005 | Run concurrency | Serial queue | Deferred | Adds a scheduler without a confirmed need. |
| OL-006 | Run concurrency | Parallel runs | Rejected for this iteration | Requires core configuration isolation and memory write ownership. |
| OL-007 | Run state | In-memory run record and bounded event buffer | Approved | Satisfies process-lifetime reattachment without new storage. |
| OL-008 | Run state | File-backed run journal | Deferred | Adds a persistence format and cleanup policy. |
| OL-009 | Run state | Database or message queue | Rejected | Explicitly excluded; second source of truth and new dependency. |
| OL-010 | History | Read-only projection over existing artifacts | Approved | Confirmed; no new index or retention policy. |
| OL-011 | History | New index database | Rejected | Duplicates artifact state and requires storage approval. |
| OL-012 | History | Current-session-only history | Rejected | Confirmed history must read existing artifacts. |
| OL-013 | Provider keys | Server environment only | Approved | Avoids transmitting plaintext keys to the browser. |
| OL-014 | Provider keys | Browser input kept in process memory | Rejected | Still transmits plaintext credentials into a client surface. |
| OL-015 | Provider keys | Browser input written to `.env` | Rejected | Highest risk; lets a web request mutate credentials on disk. |
| OL-016 | Analysis cancellation | Stop, no decision entry, no checkpoint clear, keep partial artifacts | Approved | Matches CLI `Ctrl-C` semantics. |
| OL-017 | Analysis cancellation | Stop and delete partial artifacts | Rejected | Destroys useful partial reports and diverges from the CLI. |
| OL-018 | Analysis cancellation | Stop client updates only, let the run continue | Rejected | Makes "cancel" misleading. |
| OL-019 | Package location | `src/tradingagents_web/` | Approved | Included by the existing `tradingagents*` pattern; keeps presentation out of the core tree. |
| OL-020 | Package location | `src/tradingagents/web/` | Rejected | The structural check forbids presentation framework imports under the core. |
| OL-021 | Package location | `src/webui/` | Rejected for this iteration | Requires a packaging include change and governance approval. |
| OL-022 | Backend framework | FastAPI + Uvicorn | Approved | Pydantic validation, OpenAPI, async, SSE, and single-worker lifecycle fit the existing Python stack. |
| OL-023 | Backend framework | Starlette only | Rejected | Manual validation and error models add code without a confirmed benefit. |
| OL-024 | Backend framework | Flask/WSGI | Rejected | Synchronous model and weaker streaming ergonomics. |
| OL-025 | Backend framework | Django | Rejected | Too heavy for a local single-user presentation layer. |
| OL-026 | Event transport | SSE | Approved | One-way server-to-client; `EventSource` reconnection; simpler than WebSocket. |
| OL-027 | Event transport | WebSocket | Rejected | Bidirectional framing/lifecycle with no confirmed need. |
| OL-028 | Event transport | Long polling | Rejected | Higher request overhead and less immediate updates. |
| OL-029 | Frontend framework | React 19 + TypeScript + Vite | Approved | Explicit user selection; SPA is sufficient; no SSR/Node server. |
| OL-030 | Frontend framework | Server-rendered templates + minimal JS | Rejected | Weaker for the live event view and report navigation. |
| OL-031 | UI technology | Tailwind + shadcn/ui (Radix) + Lucide | Approved | Accessible primitives, controllable styling, no heavy design-system lock-in. |
| OL-032 | UI technology | MUI / Ant Design | Rejected | Comprehensive but heavy and opinionated for this local tool. |
| OL-033 | Client state | Zustand + TanStack Query | Approved | Zustand for one active run; Query for config/history/backtests. |
| OL-034 | Client state | Redux Toolkit | Rejected | More ceremony than needed for one active run. |
| OL-035 | Forms | React Hook Form + Zod | Approved | Step-level validation with a clear schema; backend remains authoritative. |
| OL-036 | Markdown | react-markdown + remark-gfm + rehype-sanitize | Approved | Untrusted content requires a sanitizer and no raw HTML. |
| OL-037 | i18n | react-i18next, English default, Chinese switch | Approved | Two-language catalogue with key-completeness testing; report language stays separate. |
| OL-038 | Testing | pytest + Vitest/RTL/MSW + Playwright | Approved | Backend contract/security, component behavior, real-browser flows. |
| OL-039 | Authentication | None, loopback-only | Approved | Compensated by Host/Origin/CSRF/CSP. |
| OL-040 | Authentication | Reverse-proxy authentication | Deferred | No confirmed proxy or identity provider. |
| OL-041 | Downloads | Complete Markdown + zip of existing artifacts | Approved | Matches existing artifacts; no new export format. |
| OL-042 | Downloads | PDF/Word export | Rejected for this iteration | Out of scope; adds rendering dependencies. |
| OL-043 | Backtest control | Launch/view only; no cancel | Approved | `run_backtest` has no cancellation hook; no fake control. |
| OL-044 | Backtest control | Cancel with a flag | Rejected | Would report a stop that did not occur. |
| OL-045 | Preferences | Read CLI prefs; do not write them | Approved | Avoids surprising CLI state changes; web UI prefs live in localStorage. |
| OL-046 | Preferences | Web writes `cli_prefs.json` | Rejected | Cross-entry-point state mutation without a confirmed need. |
| OL-047 | Event latency | p95 ≤ 1000 ms on loopback | Approved for documentation | Baseline is the TUI's 4 fps refresh; to be measured in the planned evaluation. |
| OL-048 | Charts | Tables only in v1 | Approved | Matches the confirmed result view; charts are a later display enhancement. |

## Decision record

The selected stack is recorded in ADR-001 through ADR-007. Dependency approval is separate: the ledger approves the design direction, not the installation or pinning of packages.

## Remaining approval work

- Dependency, license, and advisory review for FastAPI, Uvicorn, and the npm tree.
- `[governance-approved]` for `pyproject.toml` and CI changes.
- `[safety-approved]` for the new entry point.
- `[test-plan-approved]` for the concrete test plan.
