# Incident — legacy launcher executed during Plan C3 verification

**When:** 2026-11-15 22:48:28 +0800 (14:48:28 UTC)
**Where:** `/tmp/opencode/planC2_wt` (branch `exp/cand01-batch-v2`)
**Trigger:** the operator (the agent) ran `bash scripts/campaign_ablation_launch.sh`
in order to *test* that Audit B finding **B-09** was fixed (the launcher must
refuse). The test invoked the real launcher, which had no opt-in guard.

## What actually ran

The launcher started `scripts/campaign_ablation_round.py --rounds 5` via
`setsid`. The log recorded:

```
round 1: all arms already valid, skipping
round 2: all arms already valid, skipping
...
round 5: all arms already valid, skipping
```

Because all four arms already held `valid=5 / target=5` from the November 2026
campaign, the runner skipped every round. It then re-derived the four
`summary.{json,csv,md}` / `summary_agents.csv` files for arms C0 / A / B / AB of
`20261106_195007_NVDA_2026-09-23_macro_s2_*` and appended a run block to
`logs/campaign_full.log`.

## Paid LLM calls: none

**Zero paid calls.** Verified by three independent facts:

1. The runner printed `all arms already valid, skipping` for all five rounds;
   it never spawned `_run-single`.
2. `ps` shows no campaign or `_run-single` process, at the time or since.
3. **No file under any `runs/` directory was modified today.** Every arm's
   `code_state.json` and `experiment.json` still carry their November mtimes,
   and no new attempt directory exists.

## Damage assessment

| Item | Status |
| --- | --- |
| Paid calls | **0** |
| New attempt dirs | **0** |
| `runs/` telemetry (historical) | **untouched** — newest file predates 2026-11-15 |
| `summary.json` ×4 | regenerated; schema envelope changed v1→v2 (the V2 harness), **per-run token / status / timestamp data identical** |
| `logs/campaign_full.log` | **appended** (one run block). Preserved, not scrubbed |
| `logs/campaign_full.pid` | rewritten |
| Tracked files | unaffected (these measurement dirs are untracked evidence) |
| `cand01_batch_16run_v2` | untouched |

The per-run comparison was made against the same campaign's copies in the
main repository: for all four arms the tuples
`(run_index, status, total_tokens, input_tokens, output_tokens, timestamp)`
are **identical**. Only `schema_version` and harness-added envelope fields
differ, which is the recorded consequence of the V1→V2 migration, not
corruption. `measured_valid` remains 5/5 everywhere.

## Root cause

The launcher is a money-spending entry point with no dry-run mode and, after the
B-09 fix, no guard at all. Deriving `REPO_ROOT` from the script's own location
correctly fixed the *wrong-tree* half of B-09, but the natural way to verify
that fix was to execute the script — so the verification itself became a live
invocation.

## Corrective action

`scripts/campaign_ablation_launch.sh` now **refuses by default** and requires
`CAMPAIGN_ABLATION_I_MEAN_IT=yes`. A verification invocation is therefore free,
and a real one is deliberate. `tests/test_c3_regressions.py::
test_legacy_launcher_refuses_without_explicit_opt_in` runs the script and
asserts it refuses, so this path is exercised without spending anything.

## Review note

The failure was the operator's, not the harness's. It is recorded here, in the
C3 final report, and in the audit trail rather than being hidden or the log
being edited to look as though it never happened. The cost was zero; the lesson
— never test a money-spending entry point by running it — is the point.
