# Execution Readiness — CAND-01 × Batch-Macro 2×2 (V2)

| | |
| --- | --- |
| Protocol | V2 (`CAND01_BATCH_2X2_PROTOCOL_V2.md`) |
| Specs | 16, generated, frozen |
| Paid calls made | **0** |
| Verdict | **READY_WITH_LIMITATIONS** — see §6, `INDEPENDENT_AUDIT.md`, `PREFLIGHT_REPORT.md` |

This document states exactly what is ready, what is not, and what the operator
must do before authorising spend. It does not claim the experiment is free of
risk; it names the risks.

---

## 1. What is ready

| Item | State | Evidence |
| --- | --- | --- |
| CAND-01 single-pass implementation present in product code | Yes | `graph/setup.py` AND-rule; `tests/test_cand01_single_pass_finalization.py` |
| Switches reach the child process | Verified per arm in a fresh interpreter **and** from the spec by the run path | `test_switch_env_vars_reach_the_child_configuration`; `test_run_single_applies_the_spec_switches_to_the_graph_config` |
| The graph consumes the declared switches | Verified against the **real** `GraphSetup`, all 4 arms | `tests/test_switch_consumption.py` |
| `s2_downstream=false` refused | Yes | `test_s2_downstream_false_is_refused_not_ignored` |
| Finnhub-only news on the executed path | Verified with a GDELT tripwire at 0 calls | `tests/test_finnhub_only_scope.py` |
| GDELT excluded even when Finnhub fails | Verified | `test_a_finnhub_outage_is_not_rescued_by_gdelt` |
| Global news explicitly disabled, no fetch | Verified | `test_global_news_is_explicitly_disabled_not_borrowed` |
| 16 specs derived by one generator | Yes, byte-reproducible | `gen_..._v2.py --check` → *53 artefacts reproduce; 16 differ only in volatile fields* |
| 16 distinct, reproducible `config_sha256` | Yes | §5 of the protocol; recomputed independently |
| 2×2 matrix correct | Yes | `test_the_4x4_design_covers_every_cell_exactly_once` |
| Randomised order reproducible and equal to V1 | Yes, seed `20261114` | `test_execution_order_matches_the_v1_pre_registered_order` |
| Usage accounting: MISSING ≠ 0, no double count | Verified in `observability.py` | Audit C |
| Full test suite | **1990 passed, 2 pre-existing failures** (both classified as pre-existing, neither reachable at RC1) | `logs/final_test_matrix.txt`, `logs/classification_of_2_failures.txt` |
| RC1, stashes, `.env`, historical data intact | Yes | `logs/protected_state.txt` |

---

## 2. What the operator must do before the first paid call

1. **Read `PREFLIGHT_REPORT.md`** and confirm the limitations in §6 are
   acceptable.
2. **Confirm the budget posture.** `max_total_tokens = null` this round: there is
   no token ceiling. The gate reports `UNCAPPED` and will not stop a runaway run.
   If a ceiling is wanted, it must be set **before** registration, not midway
   through a round.
3. **Provide `FINNHUB_API_KEY`** in the environment **and confirm the preflight
   prints it as configured**. Audit A-01 found that the harness did not forward
   this key at all (fixed this round; `credential_state()` now reports it).
   Without it every news call returns `AUTH_MISSING` and every run is degraded
   identically — detectable, but 16 wasted runs.
4. **Confirm the code state is committed** (or accept that `code_state.json`
   records `git_working_tree_dirty: true`). Provenance is recorded either way,
   but a dirty tree is weaker evidence.
5. **Execute in the registered order** (`EXECUTION_ORDER.txt`) and do not
   re-order mid-round.
6. **Run from the repository root** (or with the repo on `sys.path`), *not* from
   an unrelated cwd with the shared `.venv`. Audit A-00 proved that the editable
   install resolves `tradingagents` to `/home/sky/cs5351/TradingAgents` regardless
   of which worktree you think you are in; a child launched elsewhere imports the
   wrong tree. See limitation L-1.
7. **Audit B2 is still open**: the generator, specs and tests are *untracked*.
   If strong provenance is required, authorise a commit first.

---

## 3. Pre-flight checklist (mechanical)

Run these before authorising spend; each is offline.

| # | Command | Expected |
| --- | --- | --- |
| 1 | `python scripts/gen_cand01_batch_16run_specs_v2.py --out <dir> --check` | `OK: 53 artefacts reproduce; 16 differ only in volatile fields` |
| 2 | `TZ=UTC python -m pytest tests/test_cand01_batch_16run_v2_infra.py tests/test_switch_consumption.py tests/test_finnhub_only_scope.py tests/test_audit_a_regressions.py tests/test_audit_b_regressions.py tests/test_audit_c_regressions.py -q` | all pass |
| 3 | `sha256sum -c MANIFEST.sha256` (in the V2 directory) | all OK |
| 4 | `git -C <repo> rev-parse HEAD` | unchanged from the recorded value |
| 5 | `sha256sum .env` | unchanged from the recorded value |

---

## 4. Run-time stop conditions

The run must be halted by the operator or by the harness on `S1`–`S8`
(protocol §11). The most important is `S1`: **the effective switches disagreeing
with the spec aborts before the paid call, not after.**

`S7` is specific to this round: **any evidence that GDELT was contacted ends the
round**, because it would mean the news scope silently changed between
registration and execution.

---

## 5. Expected per-run shape

| Field | Value |
| --- | --- |
| Analysts | `market`, `news`, `fundamentals` |
| Rounds | research 1, risk 1 |
| Runs | 16 (one attempt each, unless a run is stopped and retried) |
| Wall clock | not pre-registered; recorded per run |
| Tokens | `max_total_tokens = null` |

---

## 6. Limitations carried into the pilot

These are **known and accepted**, not defects discovered late:

1. **No S2-downstream estimate.** The switch has no OFF implementation and is
   refused when `false`. All arms hold it `true`.
2. **Global/macro news is disabled.** All arms run without it, so no arm can
   benefit or suffer from macro news; any global-news effect is out of scope.
3. **News depends on Finnhub alone.** By design there is no second feed, so a
   provider outage degrades all arms.
4. **n = 4, exploratory.** No significance claims will be made.
5. **Two pre-existing failures, neither introduced here.** From the repo cwd
   these are `tests/test_cli_prefs.py` (`.env` coupling; **identical at RC1** —
   both go green under `env -i`). From a cwd outside the repo they are instead two
   `FileNotFoundError`s in `tests/test_cand01_single_pass_finalization.py`, a file
   this round never touched and which **does not exist at RC1**. Either way the
   suite is not "0 failed"; see `TEST_RESULTS.md` §4.
6. **V1 hashes are void.** No V1 `config_sha256` can be reproduced, so V1 results
   cannot serve as a numeric baseline for V2.
7. **Uncommitted.** At registration the changes were uncommitted in the working
   tree; commit before a paid round if strong provenance is required.
8. **Budget gate is uncapped.** It reports state honestly but cannot prevent
   overspend this round.

### Limitations found by the independent audits (new this round)

| ID | Limitation | Impact on the pilot |
| --- | --- | --- |
| **L-0** | The V2 apparatus (generator, specs, tests, `switch_verification.py`) is **untracked** (Audit B2). `git archive HEAD` contains none of it. | Provenance rests on this working tree + `MANIFEST.sha256`. Authorise a commit if that is not enough. |
| **L-1** | The shared `.venv` editable-installs `tradingagents` from the **main checkout**, not the worktree (Audit A-00). | Must launch from the repo root, or with the repo on `sys.path`. Otherwise the child silently imports a tree whose news defaults still include GDELT. |
| **L-2** | Finnhub per-day fetching is serial (Audit A-04). | Slower, not wrong. Up to 16 requests per `get_news` call. |
| **L-3** | `tests/test_cand01_single_pass_finalization.py` reads sources by cwd-relative path (pre-existing, untracked). | Suite must be run from the repo root. Not a code defect. |
| **L-4** | Some module docstrings still describe a GDELT-secondary architecture (Audit A-06). | Documentation drift only; no behaviour. |
| **L-5** | Raw vendor usage is not preserved; negative counts are accepted as complete; an empty finished run may report `attribution_complete: true` (Audit C-4/5/6). | Affects forensic depth of a post-hoc spend dispute, not per-run token totals. |
| **L-6** | PIT is day-granularity: a same-day 23:59 article is admitted for a same-day decision (Audit A-07). | Declared convention, not a leak. |

---

## 7. Readiness statement

The experiment is **prepared**: code, specs, hashes, switch delivery, news scope,
tests and evidence are in place and independently audited.

It is **not** unconditionally ready to spend, for the reasons in §6 — chiefly the
uncapped budget, the uncommitted tree (L-0), and the shared-venv import hazard
(L-1). Those are operator decisions and launch-discipline requirements, not
technical blockers, so the honest verdict is **READY_WITH_LIMITATIONS** rather
than a bare `READY_FOR_PAID_PILOT`.

All Critical/High audit findings (A-01, A-02, B1, C-1) were fixed and re-audited
with mutation tests; the two remaining Highs are **A-00** (launch discipline,
mitigated) and **B2** (needs an authorised commit). See `INDEPENDENT_AUDIT.md` §5.
