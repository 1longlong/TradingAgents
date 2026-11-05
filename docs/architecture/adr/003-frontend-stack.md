# ADR-003: Frontend Stack and UI Technology

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
