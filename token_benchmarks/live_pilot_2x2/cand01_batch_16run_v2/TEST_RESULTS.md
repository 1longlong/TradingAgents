# Test Results — CAND-01 × Batch-Macro 2×2 (V2)

All numbers below come from real runs whose raw output is stored in `logs/`.
Nothing here is estimated. Every run used `TZ=UTC`, `.venv/bin/python`, and a
cleared `__pycache__` (a stale cache made a previous round report the wrong tree).

---

## 1. Summary

**Final, post-remediation numbers** (`logs/final_test_matrix.txt`):

| Suite | Result | Log |
| --- | --- | --- |
| Full suite, repo cwd, shipped env | **2 failed, 1990 passed, 2 skipped**, 319 subtests | `logs/final_test_matrix.txt` |
| Full suite, 4 selection keys unset | **2 failed, 1990 passed, 2 skipped**, 319 subtests | `logs/final_test_matrix.txt` |
| Full suite, `env -i`, cwd-independent | **2 failed, 1990 passed, 2 skipped**, 319 subtests | `logs/final_test_matrix.txt` |
| RC1 baseline (control) | **2 failed, 1471 passed, 2 skipped**, 240 subtests | `logs/final_test_matrix.txt` |
| RC1 baseline, `env -i` | **1473 passed, 2 skipped** | `logs/final_test_matrix.txt` |

Pre-remediation snapshots, kept for the audit trail (superseded — they predate
the audit fixes): `logs/full_suite_as_shipped.txt` (1889/2),
`logs/targeted_v2_suites.txt` (187), `logs/news_and_cand01_sweep.txt` (567),
`logs/rc1_baseline_full_suite.txt` (1471/2).

### 1.1 Classification of every failure

**Two** failures, and *which* two depends on the cwd, because this repo has two
pre-existing cwd-coupling defects. Both classes are classified below; evidence
in `logs/classification_of_2_failures.txt`.

| Cwd | Failing tests | Classification |
| --- | --- | --- |
| repo root (documented way to run) | `test_cli_prefs.py::{test_selections_are_remembered_after_a_run, test_a_remembered_endpoint_is_offered_back}` | **Baseline-pre-existing** — identical at RC1, file byte-identical to RC1, go green under `env -i` |
| outside the repo (`/tmp/opencode`) | `test_cand01_single_pass_finalization.py::{test_rc1_two_call_functions_are_unchanged_and_still_exported, test_setup_requires_structured_before_enabling_single_pass}` | **Pre-existing test-infrastructure limitation** (L-3) — the file opens `tradingagents/...` by a cwd-relative path, so from elsewhere it raises `FileNotFoundError` *before* asserting; from the repo root it is `71 passed`. The file is **untracked, mtime 14:59 (before this round's first edit) and absent from RC1**, so there is no RC1 counterpart it could regress from |

**New failures introduced by this round: 0.** Every file edited this round is
new or listed in the mutation table in §4; none of the two failing files was
touched.

### 1.2 Classification of every skip

| Test | Reason | Classification |
| --- | --- | --- |
| `tests/test_bedrock_provider.py:74` | `langchain_aws` not installed | Environmental, expected |
| `tests/test_deepseek_reasoning.py:209` | no `DEEPSEEK_API_KEY`; live API call skipped | Environmental, expected; correctly refuses to run a live call |

Both skips are environmental and appear identically on RC1.

---

## 2. The two failures are baseline (evidence)

1. **Same file, byte-identical to RC1.**
   `git diff --quiet 9948bf8 -- tests/test_cli_prefs.py` → no difference.
2. **Same failures in a pristine RC1 checkout** (`/tmp/opencode/rc1_baseline`,
   `9948bf8`, no candidate code): `2 failed, 10 passed`.
3. **Same failures in the RC1 full suite**: `2 failed, 1471 passed`.

**Root cause.** `tradingagents/__init__.py` calls
`load_dotenv(find_dotenv(usecwd=True))` at import, so `.env` populates
`DEFAULT_CONFIG`; the CLI then skips the interactive model-selection prompt the
tests drive.

Per-key isolation (measured, not assumed):

| Key alone | Failures reproduced |
| --- | --- |
| `TRADINGAGENTS_LLM_PROVIDER` | **both** |
| `TRADINGAGENTS_DEEP_THINK_LLM` | one |
| `TRADINGAGENTS_QUICK_THINK_LLM` | none |
| `TRADINGAGENTS_LLM_BACKEND_URL` | contributes with the provider key |

**Not worked around.** `.env` was restored byte-exact after the isolation
experiments (`2eea6491…9645`), and no test was edited. With the four selection
keys absent, the file reports **12 passed**.

---

## 3. Targeted coverage of this round's claims

| Claim | Test(s) | Count |
| --- | --- | --- |
| 16 specs generated, complete, correct 2×2 | `test_cand01_batch_16run_v2_infra.py` | 46 |
| Switches consumed by the real `GraphSetup` | `test_switch_consumption.py` | 19 |
| Finnhub-only on the executed path, GDELT at 0 calls | `test_finnhub_only_scope.py` | 9 |
| Audit A remediation (key forwarding, PIT, wording) | `test_audit_a_regressions.py` | 15 |
| Audit B remediation (spec switches authoritative, overwrite guard) | `test_audit_b_regressions.py` | 68 |
| Audit C remediation (completion-call telemetry, consumer table) | `test_audit_c_regressions.py` | 18 |
| CAND-01 single-pass finalisation | `test_cand01_single_pass_finalization.py` | (existing) |
| PF-01 positive news path | `test_cand01_news_positive_path.py` | (existing) |

---

## 4. Non-vacuity — the tests can fail

A check that cannot fail is not a check. Four source mutations were applied to
real files, the suite was run, and each file was restored and its SHA-256
verified identical. Full transcript: `logs/mutation_tests.txt`.

| Mutation | Tests failed | File restored byte-identically |
| --- | --- | --- |
| Remove `"switches"` from `HASHED_FIELDS` | **6 failed** | YES |
| Make the generator accept `s2_downstream=false` | **1 failed** | YES |
| Route `get_news` back to the GDELT-merging function | **3 failed** (interceptor recorded the GDELT call) | YES |
| Make the switch verifier skip `s2_downstream` | **1 failed** | YES |
| Change the seed `20261114` → other | **2 failed** (order no longer matches V1) | YES |

**Mutations added after the independent audits** (each targets a defect an
auditor actually found; each file was restored and its SHA-256 re-checked):

| Mutation (re-introduces the audited code) | Tests failed |
| --- | --- |
| `_PASSTHROUGH_ENV` without `FINNHUB_API_KEY` (A-01) | **3 failed** |
| PIT cutoff dropped when `trade_date` is empty (A-02) | **2 failed** |
| `CONFIG_DISABLED` back to the "could not answer" sentence (A-03) | **4 failed** |
| `_run_single` no longer applies spec switches (B1) | **3 failed** |
| Generator guard keyed on `experiment.json` only (B4) | **1 failed** |
| `on_llm_start(..., prompts=None)` (C-1, the RC1 code) | **3 failed** |
| `ANALYST_CONSUMERS`: `market.single_pass` dropped (C-3) | **21 failed** |
| `ANALYST_CONSUMERS`: `news` replaced by `social` (C-3) | **21 failed** |

Additional non-vacuity proofs:

* **Namespace trap:** patching `tradingagents.agents` intercepts **0** graph
  factory calls; patching `tradingagents.graph.setup` intercepts **1**. Measured.
* **Hash sensitivity:** flipping any single switch changes the hash; changing any
  hashed field changes it; changing an excluded field does not; dropping a hashed
  field raises.
* **Spec drift:** `--check` returns exit 1 and prints `DRIFT` when a switch is
  edited in a generated spec.

---

## 5. Coverage of the required Harness properties

| Required property | Status | Where |
| --- | --- | --- |
| 16-run spec completeness | Covered | infra tests |
| Four-arm switch matrix | Covered | infra tests |
| Run ID uniqueness | Covered | infra tests |
| Reproducible random order | Covered | infra tests + seed mutation |
| Reproducible hash | Covered | infra tests + `--check` |
| Hash tamper detection | Covered | `--check` + switch-flip cases |
| Finnhub-only | Covered | execution-path tripwire |
| GDELT not called | Covered | tripwire, 0 calls |
| Child-process config passing | Covered | fresh-interpreter per-arm test **+** `_run_single` stub-graph tests |
| Real graph consumes switches | Covered | real `GraphSetup`, 4 arms; consumer table cross-checked against it |
| Spec switches authoritative over ambient env | Covered | `test_audit_b_regressions.py`; contradictory export refused |
| `FINNHUB_API_KEY` forwarded to the child | Covered | `test_audit_a_regressions.py` (3 tests) |
| PIT cutoff never silently dropped | Covered | `test_audit_a_regressions.py` (3 tests) |
| `CONFIG_DISABLED` ≠ outage in rendered text | Covered | `test_audit_a_regressions.py` |
| Non-chat LLM calls reach telemetry | Covered | `test_audit_c_regressions.py` (3 tests) |
| OFF-path compatibility | Covered | legacy specs unaffected |
| ON-path PF-01 positive news | Covered | `test_cand01_news_positive_path.py` |
| Usage dedup | Covered | `observability.py`; Audit C |
| MISSING handling | Covered | `observability.py`; Audit C |
| Interruption retention | Covered | `observability.py`; Audit C |
| Budget gate | Design + mocked tests | `BUDGET_GUARD_DESIGN.md` |
| dry_run / refused run | Not independently re-tested this round | see limitations |
| No historical file overwritten | Covered | `logs/protected_state.txt` |

---

## 6. Honest gaps

Two items from the task list are **not** independently re-verified by a new test
in this round:

1. **`dry_run` stop path** and **refused runs never producing `attempt_00`.**
   The code that owned these behaviours (`record_stopped`, the stop path) lived in
   the lost V1 scripts. The current Harness (`scripts/token_benchmark.py`) does
   not contain those functions, so there is nothing in the delivered tree to test.
   They must be treated as **V2-unimplemented**, not as passing.
2. **`effective_config.json`.** The V1 evidence files exist under
   `cand01_batch_16run/generated/`, but the writer was in the lost bundle. V2
   specs carry `switches` + `config_sha256` for the child to verify, and the
   verifier is committed and tested; the *writer* of `effective_config.json` is
   not part of the delivered code.

Both gaps are recorded in `PREFLIGHT_REPORT.md` and drive the
`READY_WITH_LIMITATIONS` verdict.

---

## Erratum — appended at Plan C3 freeze (audit A-11)

The numbers in §1 above are a **historical record of the C2 round**, not a
description of the frozen V2 tree. They are left in place rather than edited:
the round's logs are evidence, and rewriting a recorded result to match later
code would destroy the audit trail the report exists to provide.

Live state at the C3 freeze (`git rev-parse HEAD` = `cat c3/FROZEN_COMMIT`):

| Measure | Value |
| --- | --- |
| Full suite, isolated venv `/tmp/opencode/expvenv` | **2083 passed, 2 skipped**, 319 subtests, **0 failed** |
| The 2 failures recorded in §1 | **gone** — they came from a stale worktree `.env` (audit A-01), now deleted |

The §1 figure `2 failed, 1990 passed` therefore describes neither the current
tree nor the frozen one. The two gaps named at the end of §1 were both closed
in C3 (`effective_config.json` is now written by `_write_effective_config`;
the pre-flight gate is a committed script with its own tests).
