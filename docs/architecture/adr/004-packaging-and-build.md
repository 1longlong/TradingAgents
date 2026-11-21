# ADR-004: Package Boundary, Build Pipeline, and Packaging

- Status: **Accepted for documentation** by the human owner on 2026-11-05. `pyproject.toml` and CI changes require human governance review. Under the 2026-11-21 revision in ADR-012-error-handling-merge-integration.md, merge reviews use GitHub branch protection without special markers.
- Date: 2026-11-05
- Related requirements: `REQ-WEB-026`, `REQ-WEB-009`
- Related invariants: `INV-WEB-001`, `INV-WEB-015`
- Related ADRs: ADR-001, ADR-002, ADR-003
- Related blueprint: `architecture-blueprint.md` Sections 7, 12

## Context

The existing setuptools configuration uses `where = ["src"]` and `include = ["tradingagents*", "cli*"]`, with console script `tradingagents = "cli.main:app"`. The WebUI must be installable without changing the core or CLI, must not be imported by them, and must ship its built frontend assets in the wheel. The frontend is a Vite SPA with a separate npm dependency tree.

Adding a web package inside `src/tradingagents/` would violate the structural rule that the core must not import presentation frameworks. A top-level `web/` directory would fall outside the approved `src/` source layout.

## Decision

1. **Package path: `src/tradingagents_web/`.** It matches the existing `tradingagents*` include pattern and stays outside the core package.
2. **Optional dependencies: `[project.optional-dependencies].web`.** `pip install -e '.[dev,web]'` installs FastAPI and Uvicorn; the core install stays lean.
3. **Entry points: `tradingagents-web = "tradingagents_web.cli:main"` and `python -m tradingagents_web`.** The existing `tradingagents` command is unchanged.
4. **Frontend source: `src/tradingagents_web/frontend/`.** Vite builds to `src/tradingagents_web/static/`.
5. **Build output is generated, not committed.** CI builds the frontend before packaging. Local development uses the Vite dev server with an `/api` proxy.
6. **Package data includes `tradingagents_web/static/**`.** The wheel ships `index.html`, hashed JS/CSS, and fonts. The `frontend/` source is not part of the wheel.
7. **Runtime check.** If `static/index.html` is missing, the server starts in API-only mode and prints a clear build instruction; it does not serve a broken UI.
8. **No setup.py build hook that downloads Node or npm packages.** The build step is explicit and reproducible.

## Consequences

### Positive

- The core package and CLI entry point remain untouched.
- The web dependency set is optional.
- The wheel contains only built assets, not the frontend toolchain.
- The package path is included without changing the setuptools include patterns.

### Negative / costs

- A source install without a frontend build has no UI until `npm run build` is run.
- CI must install Node, cache npm, build, and then package.
- `pyproject.toml` changes (extra, script, package data) need governance approval.
- The wheel build depends on the frontend build order; the CI pipeline must enforce it.
- Static assets increase wheel size.

### Risks and mitigations

- **Missing assets in wheel.** CI inspects the wheel for `static/index.html` and runs a clean-install health check.
- **Build drift.** Build from a locked `package-lock.json`; fail on `npm ci` mismatch.
- **Packaging collision.** The package name `tradingagents_web` is distinct from `tradingagents` and `cli`; the structural gate checks for duplicate logical sources.
- **Node version drift.** Pin Node 22 LTS in CI and document it.

## Alternatives considered

1. `src/tradingagents/web/` — rejected; the structural check forbids presentation framework imports under the core.
2. Top-level `web/` — rejected; product source belongs under `src/`.
3. Commit built assets — rejected; generated artifacts drift and bloat history.
4. Build the frontend from a setuptools hook — rejected; hidden network/toolchain dependency.
5. Separate frontend service — rejected; adds a second process and origin/CORS complexity.


### PR #7 CI dependency correction — 2026-11-21

Under the existing optional-dependency decision, regression, full-source static
analysis and architecture/security jobs install `.[dev,web]`. The previous
`.[dev]` omitted FastAPI and stopped the four regression matrices at collection.
No dependency is added or upgraded. The core-only clean-install job remains
`pip install .` and retains its import/resource/CLI checks. No gate or threshold
is disabled. Human governance review of workflow changes remains required.
