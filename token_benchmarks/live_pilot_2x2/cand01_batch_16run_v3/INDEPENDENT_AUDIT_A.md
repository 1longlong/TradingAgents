# Independent Audit A — product code and memory

**Auditor:** independent read-only Subagent (separate context, no write access).
**Candidate audited:** `6e66dca` (tree `3119b075`); delta re-check on `f19d6ed` (tree `5f6640ac`).
**Verdict:** **PASS_WITH_FINDINGS** — all findings fixed before the freeze.

## Verified

* `AttributionContext` is a `ContextVar`; `agent_scoped` / `system_component_scoped`
  nest and restore on success, exception and cancellation; a call in a fresh OS
  thread sees `none` and therefore invalidates the run (fail closed).
* The reflector wraps only `invoke`; `git diff 15270b1 -- reflection.py` is the
  import plus the context manager. Prompt text, model, temperature and return
  logic are byte-identical.
* Telemetry: buckets are separate, `run_totals` sums agents + system components
  + unattributed, the `attribution` summary closes, `attribution_complete`
  requires zero unattributed, schema 2.
* Memory: per-run copy under its own attempt dir, baseline read-only and
  hash-pinned, copy != baseline, containment enforced, order independence
  proven with the product's own `_resolve_pending_entries`.
* No product business logic changed by the isolation (`_config_for_spec` only
  supplies the run's `memory_log_path` before construction).

## Findings and resolution

| Finding | Severity | Resolution in `f19d6ed` |
| --- | --- | --- |
| R1 worktree dirty during audit | release blocker | the doc edits were committed; final tree clean |
| M1 memory evidence fail-open (no `memory_state.json` ⇒ still valid) | medium | `INVALID_MEMORY_STATE_MISSING` on both the run and re-summarize paths; regression test |
| A1 scope API accepts an agent id as a system component | low | `system_component_scoped` rejects agent ids; `agent_scoped` rejects declared system components |
| A2 harness trusts the attribution self-report | low | U-1 requires `attribution_complete is True`, rejects `attribution_type="none"` events, cross-checks the summary |
| M2 baseline provenance asymmetric (NVDA kept, AAPL excluded) | medium | baseline is now empty and symmetric; both entries documented as experiment-generated (`empty_baseline/empty_reason`) |
| M3 generic (non-registered) specs still use the shared log | info | pre-existing `measure` path, outside the 16 runs; documented |

**Delta re-check on `f19d6ed` (and the stripped-spec guard): PASS.** M1, A1, A2, M2 and L1 verified real by direct probes; 33 focused tests pass.
