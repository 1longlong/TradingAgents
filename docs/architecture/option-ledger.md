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
