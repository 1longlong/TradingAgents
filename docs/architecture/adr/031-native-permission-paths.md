# ADR-031: Native OpenCode path matching without broader permissions

- Scope: submission-fix-v1, 2026-11-24; the human explicitly approved fixing
  protected permission-file path compatibility while retaining existing rights.
- Requirements: NFR-SEC-001, REQ-WEB-026; no business/runtime permission change.

## Context

Native OpenCode 1.18.29 successfully loads the V1 configuration, but actual
Read calls did not match repository-relative allowlist entries. A loopback-only
scripted provider and synthetic files reproduced the denial. Configuration
parsing and our policy simulator alone were insufficient evidence.

## Decision

Bind native Read/Edit whitelist paths to the canonical project root at launch,
using TRADINGAGENTS_PERMISSION_ROOT and V1 configuration substitution.
Native diagnostics show that the matching resource is the canonical absolute
path with its initial slash removed; preserve that normalization at launch. Preserve
the ordered deny/ask/allow actions, secret denials, external-directory denial,
protected paths, role boundaries and command allowlists. Glob matches a query
and grep matches a regular expression, so their rules must not be path-prefixed.
Never use an unrestricted **/AGENTS.md exception or allow all outside paths.

Probe the installed native runtime in a temporary canonical directory with a
local deterministic OpenAI-compatible transport. No real model, credential or
user data is used. Test allowed reads, denied synthetic .env reads, allowed
Build/Docs writes, denied Plan/Verify editing and protected-path approval.
Record actual results and any remaining mismatch rather than declaring success
from JSON parsing. The host sandbox remains independent of project permissions.

## Alternatives

- Broad **/filename allows: rejected; they expand the allowlist beyond the root.
- Enabling external-directory access: rejected; it weakens containment.
- Silently treating all native denials as a successful safety check: rejected;
  required project reads must also work.

## Consequences

The launch command must set a correct canonical root. Missing/incorrect binding
must fail closed; no access is inferred from the user's home or another checkout.
Native probes are bounded evidence for this runtime/version, not a universal
sandbox proof. Revalidate after upgrades. Reopen on a path-escape/symlink finding
or native request-format change. Failure fallback: stop native editing, retain
denials and correct the explicit binding through human review.
