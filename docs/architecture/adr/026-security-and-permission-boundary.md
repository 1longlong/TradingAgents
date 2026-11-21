# ADR-026: Security and Permission Boundary

- Status: **Accepted for documentation** by the human owner on 2026-11-05. Implementation requires applicable human safety review; dependency/CI/packaging changes require human governance review. Under the 2026-11-21 revision in ADR-012-error-handling-merge-integration.md, merge reviews use GitHub branch protection without special markers. Runtime security boundaries remain unchanged.
- Date: 2026-11-05
- Related requirements: `REQ-WEB-013`, `REQ-WEB-020`, `REQ-WEB-023`, `REQ-WEB-024`, `REQ-WEB-025`, `REQ-WEB-031`
- Related invariants: `INV-WEB-002`, `INV-WEB-003`, `INV-WEB-004`, `INV-WEB-005`, `INV-WEB-012`, `INV-WEB-013`
- Related blueprint: `architecture-blueprint.md` Sections 6.7, 11
- Permission matrix: `docs/architecture/permission-model.md`

## Context

The confirmed deployment is a local single-user WebUI on `127.0.0.1` with no authentication. The web layer can start paid model calls, read analysis artifacts, clear checkpoints, and display untrusted model output. A localhost service without compensating controls is still reachable by malicious web pages, DNS rebinding, or another local process. Provider keys must never reach the browser, and the browser must not receive server paths.

## Decision

1. **Loopback-only listener.** Bind `127.0.0.1`; reject non-loopback `Host` headers; no wildcard CORS.
2. **No authentication, with compensating controls.** Same-origin checks, a per-process CSRF token for state-changing requests, `Sec-Fetch-Site`/`Origin` validation, and a strict CSP.
3. **Server-only provider keys.** Keys come from environment variables. The API returns `configured / not_configured / not_required`; it never accepts, stores, logs, or returns a key. Missing keys do not block a run; the first provider call fails safely.
4. **No server paths in the browser.** History and downloads use hash artifact ids resolved server-side.
5. **Untrusted rendering.** React renders text by default; Markdown uses `rehype-sanitize`; raw HTML is disabled; links are limited to `http`/`https`; external images are blocked by default.
6. **Bounded requests.** Total request body limit 1 MB; portfolio JSON limit 256 KB; SSE subscriber queues and event buffers are bounded.
7. **Error redaction.** A central error mapper returns a category, safe message, and correlation id; stack traces and paths stay in redacted server logs.
8. **No execution authority.** No endpoint places orders or changes positions; ratings are display-only.
9. **Destructive actions.** Clearing all checkpoints requires `{"confirm": "CLEAR"}` and is rejected while a run is active.

## Consequences

### Positive

- The credential surface stays on the server.
- CSRF/Host/Origin checks compensate for the absence of authentication on loopback.
- Artifact ids and redaction prevent path and secret leakage.
- Sanitized rendering and CSP reduce XSS risk.
- Bounded buffers prevent memory exhaustion.

### Negative / costs

- CSRF and Host/Origin middleware add request-path complexity.
- No authentication means the service must not be exposed beyond loopback; this is a hard operational constraint.
- Sanitization may reject some rich Markdown features.
- Redaction can make debugging harder; correlation ids and redacted logs mitigate.
- External images in reports are blocked, which may reduce fidelity.

### Risks and mitigations

- **DNS rebinding / malicious page.** Host allowlist, Origin checks, CSRF token, no CORS.
- **Secret leakage.** Allowlisted serialization, response scans, redaction tests.
- **Path traversal.** Hash ids, root allowlist, `safe_ticker_component`.
- **XSS.** Sanitizer, no raw HTML, CSP, URL scheme allowlist.
- **Local process access.** Loopback is not an OS sandbox; document that other local processes can reach the port and keep no secrets in responses.
- **Misconfigured bind.** Startup refuses non-loopback addresses.

## Alternatives considered

1. Add login/password — deferred; not confirmed and adds session/credential handling.
2. Bind `0.0.0.0` with no auth — rejected; exposes runs and artifacts to the network.
3. Store keys in browser storage — rejected; plaintext credentials in a client surface.
4. Accept server paths for downloads — rejected; path traversal and host-layout disclosure.
5. Raw HTML report rendering — rejected; model output is untrusted.
