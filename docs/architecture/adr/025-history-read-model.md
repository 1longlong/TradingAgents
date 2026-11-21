# ADR-025: Read-Only History and Artifact Identifiers

- Status: **Accepted for documentation** by the human owner on 2026-11-05.
- Date: 2026-11-05
- Related requirements: `REQ-WEB-009`, `REQ-WEB-010`, `REQ-WEB-024`, `REQ-WEB-030`
- Related invariants: `INV-WEB-004`, `INV-WEB-005`, `INV-WEB-011`
- Related ADRs: ADR-001, ADR-006
- Related blueprint: `architecture-blueprint.md` Sections 6.5, 8.5, 8.6

## Context

The CLI and API already write run artifacts in several places: per-run directories, API-style state logs, manually saved report trees, and backtest run directories. The decision memory is a separate Markdown log. The user selected read-only history over existing artifacts and explicitly excluded a new database or message queue. The browser must not receive server filesystem paths.

## Decision

1. **History is a read-only projection** over existing artifacts. No delete, rename, move, rotation, migration, or index database.
2. **Artifact identifier: `sha256(canonical_relative_path)[:16]`.** The server builds the id-to-path map during a scan and keeps it in a short-lived in-memory cache (5 s TTL). Nothing is persisted.
3. **Resolution:** decode the id through the map; reject unknown ids. The resolved path must stay under an allowlisted root and pass `safe_ticker_component` for every user-derived component.
4. **Sources:** run directories, saved report trees, backtest runs, and the decision memory. API-style `full_states_log_*.json` is optional.
5. **Downloads:** `kind=complete` serves `complete_report.md` when present; `kind=archive` streams an in-memory zip of existing report files; `kind=section` serves an allowlisted section. The server does not synthesize a complete report that does not exist.
6. **No server paths in responses.** Responses include ticker, date, source, status, rating, review flag, timestamps, section ids, and artifact ids.
7. **Limits:** at most 500 runs per scan, 50 per page, bounded report size, and no unbounded log reads.

## Consequences

### Positive

- No second source of truth and no database migration.
- Existing CLI/API artifacts become browsable without copying them.
- Hash ids avoid exposing host paths.
- Read-only design eliminates most destructive failure modes.
- Works for CLI-style runs that lack a state log.

### Negative / costs

- Every history request may need a directory scan; the cache mitigates but does not eliminate cost.
- Hash ids are not human-readable; the UI must display ticker/date metadata.
- Artifacts written by different paths have different shapes; readers must handle missing fields.
- Downloads cannot reconstruct a report tree that was never saved.
- The cache must be invalidated on mtime/size change.

### Risks and mitigations

- **Path traversal.** Never accept paths; map ids; validate roots; reject `..`, absolute paths, backslashes.
- **Large directories.** Scan limits and pagination.
- **Partial runs.** Derive status from explicit artifacts; show partial, never synthesize.
- **Stale cache.** TTL plus mtime/size checks.
- **Zip memory.** Bound total archive size; stream to the client; reject oversized sets.

## Alternatives considered

1. New index database — rejected; second source of truth, new dependency, storage approval.
2. Current-session-only history — rejected; confirmed requirement reads existing artifacts.
3. Base64 of the path as the id — rejected; reversible encoding still leaks path structure.
4. Raw relative paths in responses — rejected; violates the no-path boundary.
5. Reconstructing reports from `full_states_log` — rejected for CLI-style runs that lack it; no synthesis.
