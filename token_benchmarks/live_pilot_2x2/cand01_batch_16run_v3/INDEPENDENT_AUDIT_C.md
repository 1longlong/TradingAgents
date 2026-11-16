# Independent Audit C — usage, telemetry and security

**Auditor:** independent read-only Subagent.
**Candidate audited:** `6e66dca` (tree `3119b075`); delta re-check on `f19d6ed` (tree `5f6640ac`).
**Verdict:** **PASS_WITH_FINDINGS** — the two medium findings were fixed before
the freeze.

## Verified

* `run_totals` = agents (incl. unattributed) + system components; the
  `attribution` summary closes (agent/system/unattributed calls and tokens);
  an unattributed event forces `attribution_complete=false` and an INVALID
  verdict.
* Missing provider usage is `null`, never `0` at run level; partial omission is
  counted and flagged and the sample is invalid.
* Budget: `uncapped_authorized` requires `max_total_tokens=null`; missing,
  malformed and unreadable states are distinct.
* A modified baseline invalidates (`memory_snapshot_modified`).
* Security/history: `.env` untracked and never read; no key in the diff;
  `rc1`, `c3-final-freeze`, `2e62ccb`, `72ae0f8`, 3 stashes and the main
  worktree unchanged; 0 paid provider calls.
* Full suite on the candidate: 2204 passed, 2 pre-existing failures, 2 skipped,
  319 subtests; baseline 2163/2/2/319 → 0 new failures.

## Findings and resolution (in `f19d6ed`)

| Finding | Severity | Resolution |
| --- | --- | --- |
| MEDIUM-1 no `memory_state.json` ⇒ still valid | medium | `INVALID_MEMORY_STATE_MISSING` on both paths; regression test |
| MEDIUM-2 U-1 trusted the aggregate flag; a `none` event + tampered flag stayed valid | medium | event-level `none` check, `attribution_complete is True`, summary-vs-call-count cross-check; tampered-flag regression test |
| LOW-1 a system event's `agent_id` is the `unattributed` sentinel | low | correct by `attribution_type`/`component_id`; documented |
| LOW-2 per-agent missing totals → 0 | low | flagged as `token_totals_are_lower_bound`, excluded from valid means |
| LOW-3 committed docs had stale counts | low | updated to the real numbers |
| LOW-4 budget fallback merges unreadable/malformed on a non-frozen path | low | pre-existing; recorded |

**Delta re-check on `f19d6ed`: PASS.** Tampered-flag payload → INCOMPLETE; missing memory_state.json → `memory_state_missing`; 233 focused tests pass.
