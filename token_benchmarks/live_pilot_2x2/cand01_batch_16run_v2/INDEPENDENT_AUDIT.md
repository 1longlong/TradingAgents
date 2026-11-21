# Independent Audit — CAND-01 × Batch-Macro 2×2 (final freeze)

Three independent auditors, each a separate agent session with its own context,
audited the same worktree read-only. They were given a scope and a tree
fingerprint, not a conclusion, and were required to execute code rather than read
intent. **No auditor modified the worktree** (each stated so, and the fingerprint
was unchanged across their runs).

| Round | Tree under audit | Result |
| --- | --- | --- |
| 1 | pre-freeze candidate | interrupted (concurrent editing by the author); superseded |
| 2 | commit `af4568…`, fingerprint `e8fa269b…` | A PASS; C PASS on code with a release-state blocker; B NOT_READY with two High and one Medium finding |
| 3 | commit `2f2f424…`, fingerprint `9abc92c1…` | A PASS (0 findings); C PASS (2 Low residuals); B NOT_READY only on the pending metadata step |
| 3b | commits `e2b0d4a…` / `1406b37…` | all three re-confirmed the delta |

**Final audited code:** commit `1406b37901b708fdf41116507fcd881549121812`, tree
`83903d87555fe77d8adafe71435c60d1b252551c`, code fingerprint
`03c76db655f594170b313fbd61d0613f92236f776e8e177cefa55b45f250743e`
(`working-tree-sha256-v2`, 253 files, clean).

The release-metadata commit that follows this file changes only `c3/`,
`MANIFEST.sha256` and this report — all excluded from the code fingerprint — so
the code that ships is exactly the code audited. The auditors verified that
exclusion in a clone before the final commit.

---

## 1. Round-3 verdicts on the final code

| Auditor | Scope | Verdict | Findings |
| --- | --- | --- | --- |
| A | CAND-01, news path, PIT, F1/F2/F3/PF-01 | **PASS** | 0 (one unreachable-path Info: `create_news_analyst(structured=False, single_pass=True)`, gated out by `GraphSetup`'s AND) |
| B | Harness, 16 specs, switch delivery, freeze mechanism | **PASS** on code; B-1 = the pending metadata step | 0 code findings after remediation |
| C | Usage, budget, telemetry, freeze integrity, safety | **PASS** | 2 Low residuals, both fixed and re-confirmed |

Round-3 confirmations on `1406b37`: A `469 passed + 142 subtests`; B `335
passed` and `MANIFEST 103/103`; C `334 passed`. Fingerprints identical at start
and end for all three.

## 2. Round-2 findings and their remediation

| ID | Severity | Finding | Fix | Re-verified |
| --- | --- | --- | --- | --- |
| C2 | Critical | the freeze writer emitted prose after the SHA on `Commit at write time`; the gate passed the whole string to `git merge-base --is-ancestor`, which exits 128 — every gate run would have failed after the re-seal | the gate parses the first token; a regression test reproduces the old failure mode | B, round 3 (git argv is the bare SHA) |
| H1 | High | `spec_body_sha256` did not exclude `registration_dir`/`switches_source`, so the digest recorded in `effective_config.json` differed from the released spec for **16/16** runs while the verifier self-passed | both implementations exclude the machine/provenance fields; a test builds the child spec for all 16 runs and requires its digest to equal the released spec's | B, round 3 (16/16 equal) |
| H2 | High | the docstring claimed `FREEZE_HISTORY.jsonl` is tracked and inside the fingerprint; it is ignored, so the append-only claim as written was false | the docstring is corrected; the annotated tag is named as the load-bearing anchor, and the verifier requires `HEAD == record.commit == tag commit == first designation`, so a history-only rewrite achieves nothing | B, round 3 |
| M1 | Medium | the gate had no path containment: a self-consistent rehashed copy of R01 in `/tmp` passed the spec-hash, arm and news checks | `check_spec_location` requires `specs/<run_id>_<ticker>_<arm>` | B, round 3 (copy refused, real directory accepted) |
| L1 | Low | `--expected-commit` replaced the frozen reference instead of restating it | the flag must equal the recorded reference | B, round 3 |
| L2 | Low | `--skip-network` could be used on a paid run and still printed "safe to spend" | requires `C3_I_MEAN_TO_SKIP_NETWORK=yes` and prints "OFFLINE ONLY — not authorisation to spend" | B, round 3 |
| F2/F3/F4/F5 | Low/Info | malformed event containers aborted summarisation; a missing-usage run reported a known telemetry total; re-summarisation could label an unusable contract "uncapped"; three recorded digests were never recomputed | container guards; unknown total is `None`; an unusable contract renders as invalid; the verifier recomputes all recorded digests | C, round 3 and 3b |

## 3. Round-3 findings and their remediation

| ID | Severity | Finding | Fix | Re-verified |
| --- | --- | --- | --- | --- |
| R3-01 | Low | a *non-container* `llm_call_events` (`42`, `1.5`, `true`, dict) still raised in `event_counts` after the replay was guarded | the same guard in `extract_run_metrics`; a test covers all four types end-to-end | C, final confirmation (`valid=False`, no raise, count 0) |
| R3-02 | Low | an invalid run whose budget contract was unusable still rendered as "uncapped" | the label says "contract unusable (<state>) — invalid" | C, final confirmation |
| L-1/L-2/L-3 | Low/Info | a historical sentence still claimed the history was tracked; the gate docstring contradicted `--skip-network`; `verify(root)` used module-level paths | all three corrected; `verify()` derives every path from `root` | B, final confirmation |

## 4. What the auditors verified positively (executed, not read)

* **CAND-01** present, default off, gated by `single_pass AND structured`; all
  three analyst factories forward it; RC1's two-call path intact.
* **PF-01**: availability is a pure function of tool provenance; no text/regex
  decision on model output; the pinning test fails 41 tests when the defect is
  reintroduced.
* **F1/F2/F3(a)/F3(b)** present and tested, including a real compiled-graph test
  for tool-message write-back.
* **Finnhub-only**: GDELT unreachable from the executed path (including when
  Finnhub fails), global news `CONFIG_DISABLED` with zero fetch, all 16 specs
  carry the frozen scope.
* **PIT**: undated and next-day articles rejected; a cutoff is applied even with
  an empty `trade_date`.
* **U-1** by execution: `VALID`/`MISSING`/`INCOMPLETE`/`MISMATCH` all hit; a
  replay disagreement voids the run; unknown totals are `null`, never `0`; no
  inconsistent payload could be made valid.
* **U-2**: every malformed budget state is a distinct refusal; no artificial
  ceiling; all 16 registrations are `uncapped_authorized`/`null`.
* **Telemetry**: raw usage preserved and bounded, content-free; negatives
  rejected and counted; completeness derived from counts; no double counting;
  `on_llm_start` carries real prompts.
* **Specs**: `--check` reproduces 53 artefacts; `config_sha256` independently
  recomputed for all 16; protocol §5 == `CONFIG_HASH_MANIFEST` ==
  `RUN_MANIFEST_TEMPLATE` == `SWITCH_MATRIX` == registrations.
* **Switch delivery end-to-end**: a real graph built per arm consumed exactly
  the declared arm; `s2_downstream=false` refused; a copied run directory
  refused.
* **Freeze**: no self-referential hash; an ancestor designation cannot pass; one
  commit after the designation is refused; the tag, record and history must
  agree with `HEAD`.
* **Safety**: no `.env` or secret tracked; `.env` absent from the worktree;
  protected objects intact (tag `rc1` → `9948bf8…`, commits `72ae0f8…` and
  `2e62ccb…`, the three stashes).

## 5. Limits of this audit (stated, not hidden)

* No full `pytest` suite (out of scope this round); no network probes; no paid
  call, no Pipeline, no R01–R16.
* The certification artefacts (`FROZEN_COMMIT`, `FREEZE_RECORD.json`,
  `FREEZE_HISTORY.jsonl`, the tag) cannot exist before the commit they name;
  their behaviour was verified by code, unit tests and a full simulation in a
  clone, and is re-verified live immediately after the freeze.
* Residual threat model (B, R-1): a coordinated local rewrite of *all* untracked
  release metadata plus re-creation of the tag is detectable only against an
  external record of the tag object SHA. That SHA is published in
  `c3/FINAL_FREEZE_REPORT.md` and in the operator's hand-off; no purely local
  scheme can do better, because a commit cannot contain its own hash.
* The `tests/test_cli_prefs.py` `.env`-coupling (pre-existing at RC1) is not
  exercised here; the full-suite round must classify it.
