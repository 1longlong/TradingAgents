# ADR-020: Announcements and Untrusted External Content

- Status: **Implemented under the user-approved Iteration-3 plan; architecture review pending.**
- Date: 2026-11-06
- Related requirements: `REQ-WEB-012`, `REQ-WEB-020`, `REQ-WEB-023`, `REQ-WEB-024`, `REQ-WEB-025`
- Related invariants: `INV-WEB-012`, `INV-WEB-013`
- Related ADRs: ADR-006
- Related blueprint: `architecture-blueprint.md` Sections 6.1, 6.7, 8

## Context

The CLI fetches announcements at startup and prints a fallback when the request
fails. The WebUI must preserve that advisory behaviour without letting external
text become executable content or block a run on a failed request.

## Decision

1. **Server-side fetch.** The browser calls `GET /api/announcements`; the
   server calls the existing `cli.announcements.fetch_announcements`.
2. **Timeout and fallback.** The request uses a short timeout. Any exception,
   malformed payload, or empty list returns the existing fallback URL text with
   `require_attention: false`.
3. **Cache.** Successful and fallback payloads are cached in process memory for
   60 seconds. No external text is persisted.
4. **Attention flag.** `require_attention: true` is forwarded. The frontend
   shows a blocking dialog until the user acknowledges it; the server does not
   create a session or persist the acknowledgement.
5. **Untrusted rendering.** Announcement strings are rendered as text nodes.
   The component does not use `dangerouslySetInnerHTML`; HTML tags in upstream
   text remain inert.
6. **No secrets or paths.** The response contains only announcement strings and
   the attention flag.

## Consequences

- A failed announcement service cannot prevent a run.
- Upstream markup is shown literally instead of being interpreted.
- The acknowledgement is per browser mount, not a durable user preference.
- The server performs one external request per cache window.

## Alternatives considered

1. Browser-side fetch — rejected; it exposes the endpoint to client policy and
   complicates timeout/fallback parity.
2. Markdown rendering of announcements — rejected; a plain-text boundary is
   smaller and safer.
3. Persisting acknowledgement — rejected; no new storage or session feature is
   approved.
