# ADR-022: Backend Framework and Event Transport

- Status: **Accepted for documentation** by the human owner on 2026-11-05. Dependency approval is still required.
- Related requirements: `REQ-WEB-002`, `REQ-WEB-006`, `REQ-WEB-007`, `REQ-WEB-020`, `REQ-WEB-022`, `REQ-WEB-026`
- Related ADRs: ADR-001, ADR-007
- Related blueprint: `architecture-blueprint.md` Sections 5–8

## Context

The web layer needs HTTP request validation, a single-process lifecycle, ordered server-to-client progress events, cancellation, reattachment, and strong security middleware. The existing project is Python 3.10+, Pydantic-based, and already uses synchronous LangGraph streaming. The browser only needs server-to-client events; all client actions can be normal REST requests.

The repository has no approved web framework or event transport. The user approved a TypeScript/React frontend and delegated the remaining choices; this ADR records the selected backend and transport.

## Decision

1. **FastAPI + Uvicorn**, single worker, bound to `127.0.0.1`.
2. **SSE (Server-Sent Events)** for run events, using `StreamingResponse` and `text/event-stream`.
3. **Synchronous graph execution in a single-worker `ThreadPoolExecutor`**, with `loop.call_soon_threadsafe` to publish events to the asyncio side.
4. **REST endpoints** for session, config, announcements, runs, history, and backtests.
5. **No WebSocket, message broker, background worker service, or external queue.**
6. **OpenAPI-generated TypeScript types** to keep the backend and frontend contracts aligned.

## Consequences

### Positive

- FastAPI's Pydantic validation matches the existing model style.
- OpenAPI provides a machine-readable contract and generated frontend types.
- SSE is simpler than WebSocket for one-way events and gives `EventSource` automatic reconnection.
- A single Uvicorn worker preserves the single-run safety model and avoids cross-process state.
- No broker or worker infrastructure is needed.

### Negative / costs

- New Python dependencies (`fastapi`, `uvicorn`) require dependency, license, and advisory review.
- SSE requires heartbeat, buffering, and snapshot handling.
- The synchronous graph stream must be bridged into the event loop carefully.
- Uvicorn must enforce one worker; horizontal scaling is explicitly out of scope.
- Reverse proxies would need buffering disabled, but the confirmed deployment is direct loopback.

### Risks and mitigations

- **Blocking the event loop.** Run the graph in a worker thread; never call the synchronous stream on the event loop.
- **Event loss.** Use monotonic `seq`, bounded buffers, and snapshot fallback.
- **Slow clients.** Use bounded subscriber queues; drop to snapshot mode.
- **Framework dependency risk.** Add the dependency only after approval; pin and audit; keep the core free of FastAPI imports.

## Alternatives considered

1. **Starlette without FastAPI** — lighter, but manual validation and error models add code.
2. **Flask/WSGI** — synchronous model and weaker streaming ergonomics.
3. **Django** — too heavy for a local single-user presentation layer.
4. **WebSocket** — bidirectional framing and lifecycle complexity with no confirmed need.
5. **Long polling** — higher overhead and less immediate updates.
6. **A separate Node server** — adds a second runtime and deployment surface; the SPA is served by FastAPI instead.

## Addendum — existing-core audit/comparison projections

Scope follows the current user's request to fill the previously identified WebUI
interface gaps (`web-projections-20261120-v1`). This retains FastAPI, same-origin
loopback controls and the core/presentation dependency boundary; no dependency
or transport change is selected. Final implementation acceptance remains pending.

Add synchronous GET projections for bounded canonical audit families and the
existing pure scripted comparison runner, as specified under W9 in the blueprint.
File reads resolve an opaque indexed artifact ID into a fixed filename allowlist,
check the configured result boundary, and use no-follow regular-file descriptor
reads. Responses redact exact server secrets, credential-looking strings,
absolute filesystem locations and noncanonical path mappings. No user-supplied
path, executable input, arbitrary case upload or provider call is accepted.

The comparison catalog is fixed by the existing core fixture factories. The
service uses core replay, identity pairing and `to_dict()` rather than copying
formulas. A different dynamic catalog case exercises real identity rejection;
it cannot be turned into a successful comparison by the frontend. GET replay
is stateless, bounded and network-free, so it neither needs a mutation endpoint
nor weakens the existing CSRF protected-route set.

References: REQ-WEB-008/009/010/013/023/024/027, NFR-AUD-001,
NFR-CMP-001/002/003, INV-WEB-001/003/004/005/011/012/014 and INV-9/10.

## Addendum — local development launcher

Under the user's `web-startup-20261120-v1` authorization, add supervised local
startup modes to the existing entry point. The backend remains one Uvicorn worker
on loopback. Development uses existing Vite as a second owned process and proxies
API requests; the normal/build modes retain same-origin static serving. Keep
security middleware unchanged, propagate only the chosen loopback proxy port,
refuse occupied ports and close owned child groups on failure/interruption.
Open the browser only after readiness. No network dependency installation or
provider call belongs to launcher startup. This selects no new dependency or
production transport; final human acceptance remains pending.
