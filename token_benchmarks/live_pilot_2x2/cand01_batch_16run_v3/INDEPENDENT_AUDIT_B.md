# Independent Audit B — harness, protocol and specs

**Auditor:** independent read-only Subagent.
**Candidate audited:** `6e66dca` (tree `3119b075`); delta re-check on `f19d6ed` (tree `5f6640ac`).
**Verdict:** **PASS_WITH_FINDINGS** — the two blockers found on `afa0fc6` were
fixed on `6e66dca`; the residuals were fixed on `f19d6ed`.

## Verified on the candidate

* 16 registrations, each with `memory.mode=per_run_snapshot_copy`,
  `baseline_relpath`, and a `baseline_sha256` equal to the actual file; 16
  distinct `config_sha256`.
* Protocol hash table == `CONFIG_HASH_MANIFEST.csv` == recomputed registration
  hashes (16/16); `SWITCH_MATRIX.csv` == registration switches ==
  `RUN_MANIFEST_TEMPLATE.csv`; `EXECUTION_ORDER.txt` matches seed 20261114.
* No per-run `code_state.json` tracked; attempt dirs/summaries gitignored, so a
  paid run cannot dirty the certified tree.
* Generator `--check`: `OK: 38 artefacts reproduce; 1 differ only in volatile`.
* Switch plumbing traced to `setup.py` and `switch_verification`; consumed
  switches verified by the real graph in the offline rehearsal.
* Pre-spend refusals are real: snapshot missing/changed, copy missing/modified/
  ==baseline/outside-attempt, missing memory block, hash mismatch, wrong arm,
  pre-freeze.

## Blockers found on `afa0fc6` (fixed on `6e66dca`)

1. `SUPPORTED_EXPERIMENT_SCHEMAS=(1,2)` rejected every V3 registration.
2. `_preflight_gate` compared the attempt-specialised memory block against the
   3-field registration, refusing every legitimate V3 spec.
3. A doctored registration (drop `memory` + `protocol_version`, rehash) produced
   a memory-less spec that was accepted. Fixed by reading the batch contract and
   refusing a missing block explicitly.

## Residuals (fixed on `f19d6ed`)

| Finding | Severity | Resolution |
| --- | --- | --- |
| M1 generic-child path: stripped spec runs DEFAULT_CONFIG (AB) with the shared log | medium | a registered run without its definition is refused by the gate; the arm matrix reads the active batch |
| M2 baseline kept NVDA but excluded AAPL; NVDA was experiment-generated | medium | empty symmetric baseline, documented |
| L1 arm authority hardcoded to V2 | low | reads the active batch's `SWITCH_MATRIX.csv` |
| L2 `spec_body_sha256` not cross-root stable | low | docstring corrected (host path is part of the body) |
| L3 endpoint not hashed | low | protocol limitation recorded |
| L4 stale generator docstring | low | corrected |
| L5 readiness claimed audits PASS | low | corrected to the actual verdicts |

**Delta re-check on `f19d6ed`: BLOCKING — the stripped-spec refusal claimed in the
commit message was not implemented.** Clause added: `_preflight_gate` now refuses
a spec that claims a registered Run ID without `config_sha256`/`switches`/
`registration_dir` (+`memory` when the batch declares isolation); regression test
added.

**Final re-check on `c30700c` (tree `6082e2cf`): PASS.** Refused with the env
unset (V2 matrix) and with the real V3 batch; 16 specs/config hashes/protocol
table/`SWITCH_MATRIX` consistent; every registration carries
`baseline_sha256=e3b0c442…b855`; the protocol states the empty baseline; generator
`--check` reproduces. Residual (non-blocking): the operator must pin
`TRADINGAGENTS_C3_BATCH`; the runbook does.
