# Evaluation logbook

**Purpose.** A chronological record of the measurement and remediation events
that produced the CAND-01 evidence. Each entry states the date/commit, the
command or source, the result, whether the result was **Re-run** in this
checkout or **Supplied** from the recorded evidence, and the evidence path.

**Conventions**

* **Re-run** — the command was executed while preparing this submission; the
  output is quoted from that execution.
* **Supplied** — the result is taken from a recorded report/ledger; it was not
  independently re-executed here.
* **NOT_VERIFIED** — the number or mechanism is asserted by a source that is not
  present in the delivered tree, or could not be checked in this environment.
* Dates are the event date where the evidence records one, otherwise the commit
  date. All token counts are provider-reported totals; cached input is a subset
  of input and is not added again.
* The local `.worktrees/...` evidence is intentionally untracked. It is cited as
  **(local)** and is not part of `50b2ca3`.

---

## 1. Chronological entries

### LOG-001 — 2026-11-02 — `baseline_v1` configuration record

| Field | Value |
| --- | --- |
| Commit | `866133d` (ancestor of `rc1`) |
| Command/source | `token_benchmarks/baseline_v1/notes.md`, `experiment.json` |
| Result | 5-run NVDA / 2026-09-23 configuration; observability-only baseline. The notes state that raw `runs/` and `summary.*` are absent, so the numbers cannot be re-derived from this tree. |
| Status | Supplied |
| Evidence | `token_benchmarks/baseline_v1/notes.md`; `token_benchmarks/baseline_v1/experiment.json` |
| Verification | The configuration exists; the 5-run result is **NOT_VERIFIED** in the delivered tree. |

### LOG-002 — 2026-11-02 — pre-RC1 Stage 1 (report dedupe)

| Field | Value |
| --- | --- |
| Commit | `866133d` |
| Command/source | Local measurement directory `20261102_131354_NVDA_2026-09-23_stage1_dedup` (source workspace, not this checkout); campaign `stage_comparison.csv` **(local)** |
| Result | 5/5 valid; mean 191,760 tokens vs S0 237,706 (−19.3%). The campaign's audit says the run-level delta over-attributes to dedupe; prompt-byte evidence is the cleaner mechanism. |
| Status | Supplied |
| Evidence | **(local)** measurement directory and `token_benchmarks/optimization_campaigns/20261103_campaign/`; neither is tracked in `50b2ca3`. |
| Verification | **NOT_VERIFIED** for the submitted tree. Do not use as delivered evidence. |

### LOG-003 — 2026-11-02 — pre-RC1 Stage 2 (structured one-shot)

| Field | Value |
| --- | --- |
| Commit | `866133d` |
| Command/source | Local measurement directory `20261102_141110_NVDA_2026-09-23_stage2_structured` (source workspace, not this checkout); campaign `stage_comparison.csv` **(local)** |
| Result | 5/5 valid; mean 180,462 tokens, −5.9% vs Stage 1. |
| Status | Supplied |
| Evidence | **(local)**; not tracked in `50b2ca3`. |
| Verification | **NOT_VERIFIED** for the submitted tree. |

### LOG-004 — 2026-11-13 — RC1 eight-run NVDA 2x2 pilot

| Field | Value |
| --- | --- |
| Commit | `9948bf8` (branch `feature/token-observability`, clean) |
| Command/source | Re-summed raw telemetry under `token_benchmarks/live_pilot_2x2/20261113_122951_NVDA_2026-09-23_live_{A,AB,B,C0}/runs/run_0{1,2}/attempt_01/` **(local)** |
| Result | 8 attempts / 8 valid; 1,685,450 tokens; 160 LLM calls; 221 tool calls. Four arms, two runs each, all `attempt_01`. |
| Status | Re-run (sums recomputed from local telemetry) |
| Evidence | The four `20261113_122951_…` directories; `code_state.json` records `9948bf8`, clean tree. Not tracked in `50b2ca3`. |
| Verification | The sums are verified locally; the raw run files are **NOT_VERIFIED** in the delivered tree. This batch is not used for the V3 factorial. |

### LOG-005 — 2026-11-15 — V2 registration (no paid run)

| Field | Value |
| --- | --- |
| Commit | Protocolled at `15270b1`; V2.1 amendment |
| Command/source | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/CAND01_BATCH_2X2_PROTOCOL_V2.md`; generator `scripts/gen_cand01_batch_16run_specs_v2.py` |
| Result | 16 pre-registered specs with 16 distinct `config_sha256`; documented hash algorithm; 0 paid calls under the protocol at registration. The protocol records that generator `--check` reproduced 53 artefacts and 16 volatile files. |
| Status | Supplied |
| Evidence | V2 protocol §§5–7, §14; `CONFIG_HASH_MANIFEST.csv`; `SWITCH_MATRIX.csv`; `EXECUTION_ORDER.txt` |
| Verification | In this checkout `--check` reports `SPEC DRIFT DETECTED` on the 16 `spec.json` files and `RUN_MANIFEST_TEMPLATE.csv` because of absolute `experiment_root` paths. The registration bytes exist; the **reproduction check is NOT_VERIFIED** here (see RISK-010). |

### LOG-006 — 2026-11-16 — V2 paid execution and halt

| Field | Value |
| --- | --- |
| Commit | `15270b1` (tag `c3-final-freeze`) |
| Command/source | Local `RUN_LEDGER.csv`, `EXECUTIVE_SUMMARY_CN.md`, `EXPERIMENT_LIMITATIONS.md` **(local)**; canonical result record |
| Result | 7 attempts: 5 valid, 1 environment failure, 1 invalid. 1,463,791 tokens total; 1,109,645 valid + 354,146 failed. NVDA cells B 205,581 / AB 339,738 / C0 191,233 / CC 192,406. AAPL/C0 valid 180,687. |
| Status | Supplied |
| Evidence | **(local)** `.worktrees/final_run_20261116/`; V2 halt report and protocol are tracked. |
| Verification | The canonical numbers are consistent with the local ledger (7 rows; sums 1,109,645 + 354,146 = 1,463,791). Raw telemetry is **NOT_VERIFIED** in the delivered tree. |

### LOG-007 — 2026-11-16 — V3 freeze and audits

| Field | Value |
| --- | --- |
| Commit | `e3b5cca` (tag `c3-v3-final-freeze`) |
| Command/source | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/TEST_RESULTS.md`, `INDEPENDENT_AUDIT_A/B/C.md` |
| Result | 2,209 passed / 2 failed / 2 skipped / 319 subtests at the candidate; 46 new attribution/memory/V3-infra tests; three audits returned `PASS_WITH_FINDINGS` and the findings were fixed before the freeze. Failures were the two pre-existing `cli_prefs` environment-coupled tests. |
| Status | Supplied |
| Evidence | V3 `TEST_RESULTS.md`; three V3 audit files; V3 protocol §11 |
| Verification | The test counts are the recorded output; not re-run on the frozen worktree here. |

### LOG-008 — 2026-11-16 — V3 paid execution

| Field | Value |
| --- | --- |
| Commit | `e3b5cca` |
| Command/source | Local `FINAL_EXPERIMENT_REPORT_V3.md`, `RUN_LEDGER_V3.csv`, `analysis_summary_v3.json` **(local)**; canonical result record |
| Result | 18 attempts: 15 valid, 1 invalid run (R12, two attempts), plus R02 attempt 01 (environment failure). 3,067,669 tokens total: 3,002,579 valid (input 2,549,258 + output 453,321) + 65,090 failed. Valid calls: 298 LLM / 432 tool. |
| Status | Supplied |
| Evidence | **(local)** `.worktrees/v3_runs_20261116/`; V3 protocol and audits are tracked. |
| Verification | The valid totals close exactly; R12 is excluded from all means. Raw telemetry is **NOT_VERIFIED** in the delivered tree. |

### LOG-009 — 2026-11-16 — R12 (JPM/CC) provider 400, both attempts

| Field | Value |
| --- | --- |
| Commit | `e3b5cca` |
| Command/source | Local `R12_PROVIDER_ERROR_DIAGNOSIS.md`, `runner_report.json` for both attempts **(local)** |
| Result | Attempt 01: 31,176 tokens; attempt 02: 31,390 tokens. Both: 3 of 4 recorded LLM calls carry usage; the 5th provider request — the free-text retry — returns HTTP 400 `invalid_request_error`: an assistant `tool_calls` message is followed by insufficient `tool_messages`. Both attempts remain invalid; no third retry. |
| Status | Supplied |
| Evidence | **(local)** V3 R12 raw attempts; `R12_FALLBACK_FIX.md` (tracked) describes the fix |
| Verification | The 31,176 / 31,390 totals and both 400s are in the local runner reports. |

### LOG-010 — 2026-11-16 — V3 factorial analysis and sensitivity

| Field | Value |
| --- | --- |
| Commit | `e3b5cca` |
| Command/source | Local `FACTORIAL_ANALYSIS.md`, `analysis_tables/FACTORIAL.csv`, `SENSITIVITY.csv`, `INDEPENDENT_RECALCULATION.md` **(local)** |
| Result | Balanced three-block means: batch −17,702; single-pass −19,589; interaction −10,611. Per block NVDA −51,716 / −8,907 / −9,789; AAPL +1,612 / −16,390 / +307; XOM −3,002 / −33,472 / −22,351. Sensitivity: exclude R07/R14 → NVDA only, single −8,907; exclude R01 → batch −695, single −24,931. n = 1 per cell; exploratory. |
| Status | Supplied (recalculated by the local `recalc.py`) |
| Evidence | **(local)** `.worktrees/v3_analysis_review_20261116/` |
| Verification | The values agree across `FACTORIAL.csv`, the report, and the independent recalculation. |

### LOG-011 — 2026-11-16 — final remediation and re-audit

| Field | Value |
| --- | --- |
| Commit | `e0ea1b0` (code) + `8536274`, `e9eed04`, `51edd41`, `eaeebab` (audit follow-ups), `53938db` (record), `50b2ca3` (release metadata ignore) |
| Command/source | `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`, `INDEPENDENT_AUDIT.md`, `REGRESSION_AUDIT.md` |
| Result | 20 new tests in `tests/test_final_remediation.py`; full suite `2,227 passed / 4 known failed / 2 skipped / 319 subtests`; 0 new failures; three independent audits `PASS`; pre-fix probe detected 4/4 defects and 0/4 after. The 4 known failures are the two V3 absolute-path infra tests and the two `cli_prefs` environment-coupled tests. |
| Status | Supplied |
| Evidence | Tracked `token_benchmarks/final_remediation_20261116/`; `tests/test_final_remediation.py` |
| Verification | The 20 remediation tests were re-run here and pass. The full-suite count is the recorded output; see LOG-012 for the local re-run caveat. |

### LOG-012 — 2026-11-19 — current-checkout re-run (packaging state)

| Field | Value |
| --- | --- |
| Commit | `50b2ca3` plus concurrent, the submission branch's test-isolation changes |
| Command/source | `TZ=UTC .venv/bin/python -m pytest -q` from the submission worktree |
| Result | `2,233 passed, 0 failed, 2 skipped, 319 subtests` (2,235 collected). Re-verified after the D7 portability/isolation patch from a .env-free working directory (cwd outside the repository): same result, exit 0. This is the submission-branch measurement, not a `50b2ca3` re-measurement. The published commit keeps its recorded 2,227/4 result (LOG-011); the four failures are fixed by test isolation only, with the strict spec/manifest assertions intact. |
| Status | Re-run |
| Evidence | Command output in this session; `docs/code-governance/verification-constraints.md` records the clean-tree caveat. |
| Verification | The run is real but **not comparable** to LOG-011. The committed record remains LOG-011; the difference is disclosed, not averaged. |

---

## 2. Defect lineage (canonical fixes)

| Defect | Fix commit | Evidence |
| --- | --- | --- |
| PF-01: news source classified from the tool result, not the model's words | `7832a90` | `tests/test_cand01_news_positive_path.py`; V2 `INDEPENDENT_AUDIT.md` |
| F1/F2/F3: trade-date precedence, one telemetry event per ending, legal terminal routing / no tool replay | fixes landed across the CAND-01 remediation; F3 final at `72ae0f8` | `tests/test_cand01_single_pass_finalization.py` classes `TradeDatePrecedenceTest`, `TelemetryLifecycleTest`, `TerminalMessageRoutingTest`, `CompiledGraphLoopTest`; local audit **(local)** |
| U-1 usage completeness / U-2 budget contract | `6057b52` | `tests/test_c3_final_freeze.py` (`TestUsageVerdict`, `TestBudgetContract`); `tradingagents/budget_guard.py` |
| Reflector attribution + per-run memory isolation | `afa0fc6` | `tests/test_system_attribution.py`; `tests/test_memory_isolation.py`; V3 protocol §1 |
| R12 fallback replay / DSML markup / single-pass `tool_rounds` | `e0ea1b0`, `e9eed04`, `51edd41`, `eaeebab` | `tests/test_final_remediation.py`; `token_benchmarks/final_remediation_20261116/` |

These commits are in the delivered history. The defects they close are described
in the V2/V3 remediation files; a fix commit is not proof that the paid failure
cannot recur (see RISK-001 and RISK-002).

## 3. What the logbook does not claim

* It does not claim that the V2/V3 paid telemetry is present in `50b2ca3`; the
  `runs/` trees are git-ignored. The canonical counts and the local reports are
  the record.
* It does not claim that the Stage 1/2 campaign is deliverable evidence; those
  measurements are local-only and marked **NOT_VERIFIED** for this submission.
* It does not claim statistical significance. Every factorial entry is
  `EXPLORATORY` at n = 1 per cell.
* It does not claim that a passing gate is a human approval. No approval record
  is fabricated here.
* It does not rewrite the historical V3 `tool_rounds=0` values; only new runs
  carry the fixed counter.

## 4. Evidence index

| Event | Path |
| --- | --- |
| Baseline v1 | `token_benchmarks/baseline_v1/notes.md` |
| Baseline v2 (5-run token benchmark) | `token_benchmarks/baseline_v2/summary.{md,json,csv}` |
| V2 protocol and halt | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/CAND01_BATCH_2X2_PROTOCOL_V2.md`, `C3_HALT_REPORT_20261115.md` |
| V3 protocol, audits, tests | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/` |
| Final remediation | `token_benchmarks/final_remediation_20261116/` |
| RC1 / V2 / V3 / analysis raw evidence | local `.worktrees/` only **(local)** |
