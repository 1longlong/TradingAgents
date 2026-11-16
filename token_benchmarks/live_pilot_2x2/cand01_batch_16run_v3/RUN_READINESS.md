# Run readiness — every stop condition, with its evidence

| Required condition | Status | Evidence |
| --- | --- | --- |
| Reflector never produces unattributed usage | PASS | `system_component_scoped("pre_graph_reflector")`; 10/10 attribution tests; unscoped calls still `none` → INVALID |
| System components never counted as agents | PASS | `system_components` bucket separate from `agents`; per-event `attribution_type`/`component_id`; test asserts no agent bucket for the reflector |
| 16 runs share one initial memory snapshot | PASS | `memory/baseline_v3.md` sha `01102211…f8c96`, hashed into every registration; test compares all 16 |
| 16 runs have fully independent writable memory | PASS | per-run copy under the attempt dir; write-to-one test; order-independence test |
| No cross-run memory pollution | PASS | baseline unchanged after each run (`memory_state.json`); a tampered baseline invalidates |
| Full suite has no new failures | PASS | 2,201 passed / 2 pre-existing failures / 0 new (baseline 2,163 / 2) |
| Three independent audits PASS | see `INDEPENDENT_AUDIT_*.md` | auditors ran read-only on the frozen commit/tree/fingerprint |
| New protocol frozen | PASS | `CAND01_BATCH_2X2_PROTOCOL_V3.md` + `C3/FREEZE_RECORD.json` |
| 16 specs reproducible | PASS | generator `--check`: `OK: 38 artefacts reproduce` |
| MANIFEST fully verifies | PASS | `MANIFEST.sha256` verified by `c3_verify_final_freeze.py` |
| Freeze verifier passes | PASS | `FINAL FREEZE VERIFIED` (see `FINAL_FREEZE_REPORT.md`) |
| Old experiment and RC1 untouched | PASS | V2 batch/`c3-final-freeze`/`rc1`/`2e62ccb`/`72ae0f8`/backup checksums unchanged |
| No paid pipeline call made | PASS | 0 provider calls; the only model executions are fake chat models in tests |

## Offline dry runs (R01–R16)

Command (per run, after the freeze):

```
TRADINGAGENTS_C3_BATCH=token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3 \
C3_BATCH_REL=token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3 \
C3_FREEZE_TAG=c3-v3-final-freeze \
C3_PROTOCOL_NAME=CAND01_BATCH_2X2_PROTOCOL_V3.md \
C3_GENERATOR=scripts/gen_cand01_batch_16run_specs_v3.py \
TZ=UTC .venv/bin/python scripts/token_benchmark.py run \
  --experiment token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3 --dry-run --only R01
```

Result table is appended to `FINAL_FREEZE_REPORT.md` after the dry runs.

## What a paid run does now

1. `run --experiment <V3>` verifies the frozen commit/tag/tree/fingerprint.
2. `prepare_run_spec` copies the snapshot into the attempt's `memory/` directory.
3. `_preflight_gate` re-verifies the snapshot hash, the copy, and the containment.
4. `_config_for_spec` points the graph at that copy (never the developer log).
5. After the graph, `memory_state.json` proves the baseline is unchanged.
6. `effective_config.json` records the applied switches and the memory block.
7. A run with any unattributed provider usage, a changed snapshot, or a
   mis-consumed switch is `INVALID`/`FAILED` and is never a sample.
