# ADR-023: Frontend Stack and UI Technology

- Status: **Accepted for documentation** by the human owner on 2026-11-05. Dependency approval is still required.
- Date: 2026-11-05
- Related requirements: `REQ-WEB-001`, `REQ-WEB-002`, `REQ-WEB-008`, `REQ-WEB-014`, `REQ-WEB-021`, `REQ-WEB-025`
- Related ADRs: ADR-002
- Related blueprint: `architecture-blueprint.md` Sections 6.8, 8, 12

## Context

The user explicitly selected TypeScript, React, and a suitable UI technology. The interface must cover an eight-step wizard, a live event-driven run view, a large Markdown report, read-only history, a backtest form, announcements, bilingual UI, and strict untrusted-content rendering. It is a desktop-first local SPA served from the same origin as the API.

## Decision

1. **React 19 + TypeScript strict**, built with **Vite** as a single-page application.
2. **Tailwind CSS + shadcn/ui (Radix primitives) + Lucide** for components and icons.
3. **Zustand** for active-run state; **TanStack Query** for server data (config, announcements, history, backtests).
4. **React Router** for routes.
5. **React Hook Form + Zod** for wizard validation; the backend remains authoritative.
6. **react-i18next** with `en.json` and `zh.json`; default English, Chinese switch.
7. **react-markdown + remark-gfm + rehype-sanitize** for untrusted Markdown; no raw HTML.
8. **Vitest + React Testing Library + MSW** for component tests; **Playwright** for Chromium, Firefox, and WebKit.
9. **openapi-typescript** generated client types, checked in CI for drift.

## Consequences

### Positive

- The stack matches the user's explicit selection and the project's TypeScript requirement.
- Vite keeps the build simple; no SSR or second Node server is needed.
- Radix primitives provide keyboard and focus behavior without a heavy design system.
- Zustand is sufficient for one active run; TanStack Query handles read-mostly data.
- Sanitized Markdown and a strict CSP reduce XSS risk.

### Negative / costs

- The npm dependency tree is larger than a server-rendered template approach and needs audit.
- Two state layers require clear ownership: Zustand for live run state, Query for server data.
- A build step is required before packaging the Python wheel.
- i18n adds a key-completeness test and translation maintenance.
- shadcn/ui components are copied into the repository and must be reviewed like product code.

### Risks and mitigations

- **Dependency/supply-chain risk.** Lockfile, audit, license review, minimal package set.
- **Contract drift.** Generate types from OpenAPI and fail CI on drift.
- **XSS.** No raw HTML; sanitize Markdown; CSP; block unsafe URL schemes.
- **State duplication.** Zustand owns only the live run; Query owns server data; the backend is authoritative.
- **Build absence.** Runtime checks for `static/index.html`; CI packaging test.

## Alternatives considered

1. **Server-rendered templates + minimal JavaScript** — smaller dependency surface, but weaker for the live event view and report navigation.
2. **Next.js** — SSR and a Node server add deployment and state complexity without a confirmed need.
3. **MUI/Ant Design** — comprehensive but heavy and opinionated; shadcn/Radix gives more control.
4. **Redux Toolkit** — more ceremony than needed for one active run.
5. **Plain CSS** — faster initially, but Tailwind tokens and Radix components improve consistency and accessibility.
6. **No i18n library** — a custom dictionary is possible for two languages, but pluralization, interpolation, and key checking are better served by react-i18next.

## Addendum — local Vite development mode, 2026-11-20

The user approved one-command `--dev` / `--build` startup in
`web-startup-20261120-v1`. Vite is an owned loopback-only development process;
its `/api` proxy uses the launcher's validated backend port and never a remote
backend URL. Frontend HMR is development-only; backend run transport remains
SSE and the API retains one worker. Backend changes require restarting the
launcher. Built/static operation still needs only the Python service. This adds
no dependency, production Node service, deployment step or frontend feature.


## Addendum — stage-based live activity, 2026-11-20

The user's `web-activity-20261120-v1` request replaces the oversized live-run
hero and explanatory banner with a compact activity workspace. Its progress
labels are keyboard-accessible tabs for four actual graph groups: analyst team,
research debate, trading plan and risk review/final assessment. New stage entry
selects the corresponding tab without moving focus; same-stage updates retain
manual selection. Each tab shows its own recorded messages and available report
sections. All activity retains legacy messages without stage provenance.

Use existing SSE messages, tool calls, agent statuses and reports. Optional
stage/speaker metadata is presentation-only. Public text and existing debate
histories are rendered without exposing private reasoning blocks. Messages
remain visible in terminal snapshots. Long content expands on demand; scrolling
older messages pauses following. Completed runs offer a separate complete-report
view to avoid duplicating reports. Dependencies, ratings, agent logic, run
lifecycle, privacy/redaction and cancellation contracts are unchanged.


## Addendum — English/Chinese interface, 2026-11-20

The user requested `web-i18n-20261120-v1`. Reuse existing i18next and
react-i18next; add a workspace namespace to the existing English/Chinese JSON
resources. `i18n/ui.ts` performs local lookup with explicit interpolation,
English fallback and reactive subscriptions. Source phrases are literal keys
with separators disabled; persisted locale input is normalized to en/zh.
Document language and date formatting follow the selected interface locale.
Local storage failure does not prevent switching.

The top bar, settings and wizard footer expose the same accessible control.
Language changes do not remount routes, reset drafts, restart runs, change API
query identities or reconnect SSE. Form options retain explicit canonical
values; ratings and REVIEW retain their original domain identity. Shared
Markdown localizes its table-region label, while report/decision/reflection
content, tool messages and artifact previews remain source data. Known generated
history titles and holding-window labels have presentation-only formatters;
custom values remain untouched. No translation service, dependency, backend
endpoint or runtime-prompt change is introduced. Final human acceptance pending.

## Addendum — per-analysis debate controls, 2026-11-20

For web-debate-settings-20261120-v1, use a collapsed native details section in
the existing Research setup step. Public policy defaults come from the config
endpoint; never duplicate core defaults in the browser. Group controls into
round limits, convergence thresholds and debate budgets/reserves. Keep fixed
mode thresholds editable with an explicit scope note. Present environment locks
with native disabled controls. Preserve independent risk rounds after explicit
editing and restore only typed, allowlisted draft policy fields. Use the existing
linked error summary and inline translated errors; opening an error link expands
the section and focuses its field. Selected settings appear in the review step;
normalized effective settings appear in live and saved reports. Historical runs
without settings are not assigned current defaults. Native details and numeric
inputs retain keyboard behavior; two columns become one on narrow screens.


## TUI parity refinement — 2026-11-20

Under web-tui-parity-20261120-v1, extend existing events/snapshots and controls
for observed role status, analyst timing, finalized reports and custom backtest
spacing. New runtime/model_catalog.py owns bounded, application-cached public
OpenRouter discovery; config API adds optional refresh and safe stale/custom-ID
fallback. Keep core algorithms, CLI, credentials/preferences, language options
and simulated trading unchanged. See the blueprint/review memo for contracts
and prior negative-test strategy.


## Web integration refinement — 2026-11-21

The user explicitly authorizes web-simulation-20261121-v1: frontend and necessary
interfaces around the existing deterministic simulated-trading core. The
blueprint/review memo define the bounded API, ownership, persistence, single-slot
coordination, human-approval and negative-test contracts. Core models, clocks,
sizing, pipeline, engine-issued authorization, audit chain and state store remain
authoritative; no broker, safety/core rewrite or automatic human approval is
introduced. Pending approval objects remain process-owned and cannot be restored
from client JSON. Only one final verification phase is requested.


## Information hierarchy refinement — 2026-11-21

The user authorizes web-ui-simplify-20261121-v1 to reduce nonessential information
and duplicate navigation. This updates the presentation of existing features,
not their requirements, routing contracts or stack. The overview prioritizes
latest/recent research; secondary counters and diagnostic policy/identity data
use accessible native disclosures. Error, partial/REVIEW, pending approval,
financial-input/source limitations and destructive confirmations remain explicit.
Existing demo geometry is historical reference where this new simplification
changes content. Backend and deterministic business authority are unchanged.
