# Test Results — CAND-01 × Batch-Macro 2×2 (Round 6, final freeze)

Every number below comes from a run whose raw output is stored in `logs/`, or is
reproducible with the command given. Nothing here is estimated. All runs used
`TZ=UTC` and the project interpreter; no provider was contacted.

**The full `pytest` suite was not run this round** — it is explicitly out of
scope. The matrices below are the targeted and regression suites for the code
this round changed, plus the CAND-01/news protections.

---

## 1. Targeted regression matrices

| Matrix | Files | Result |
| --- | --- | --- |
| Harness, freeze, audit and observability | 12 | **576 passed, 0 failed** |
| CAND-01, news, dates, symbols, structured | 16 | **519 passed, 142 subtests, 0 failed** |

Commands (both from the repository root, `.venv` interpreter):

```
TZ=UTC python -m pytest \
  tests/test_c3_regressions.py tests/test_c3_final_freeze.py \
  tests/test_cand01_batch_16run_v2_infra.py tests/test_switch_consumption.py \
  tests/test_audit_a_regressions.py tests/test_audit_b_regressions.py \
  tests/test_audit_c_regressions.py tests/test_budget_guard.py \
  tests/test_token_benchmark.py tests/test_observability.py \
  tests/test_finnhub_only_scope.py tests/test_run_token_benchmark_sh.py -q

TZ=UTC python -m pytest \
  tests/test_cand01_news_positive_path.py tests/test_cand01_single_pass_finalization.py \
  tests/test_finnhub_news.py tests/test_gdelt_news.py tests/test_news_audit_regressions.py \
  tests/test_news_dual_source.py tests/test_news_relevance.py tests/test_news_status_taxonomy.py \
  tests/test_news_error_classification.py tests/test_news_lookahead.py tests/test_historical_news.py \
  tests/test_tool_date_enforcement.py tests/test_undated_tools_as_of.py \
  tests/test_alpha_vantage_hardening.py tests/test_dataflows_config.py \
  tests/test_symbol_normalization_paths.py -q
```

## 2. New tests for this round's fixes

`tests/test_c3_final_freeze.py` — **50 tests**, all passing:

| Group | Tests | Pins |
| --- | --- | --- |
| `TestUsageVerdict` | 10 | U-1: `VALID`/`MISSING`/`INCOMPLETE`/`MISMATCH`, unknown totals are `null`, replay disagreement voids the run, unattributed usage fails closed |
| `TestRawUsageIsPreserved` | 4 | L-5: raw blob kept and bounded, negative counts never accepted |
| `TestEmptyRunIsNotComplete` | 1 | L-5: an empty finished run is not "attribution complete" |
| `TestAgentUsageCompleteness` | 2 | L-5: partial agent coverage is reported as a lower bound |
| `TestBudgetContract` | 20 | U-2: every distinct failure state, and the delivered specs declare `uncapped_authorized` |
| `TestImportRootIsolation` | 3 | A-00: a script run by path from an unrelated cwd imports *this* tree; the child pins `PYTHONPATH` |
| `TestDryRunRehearsal` | 3 | dry run builds the real spec/graph, verifies switches, writes nothing, and can be refused |
| `TestEffectiveConfig` | 5 | the record is verified before it is written, and a mismatch/wrong root/tampered hash is refused |
| `TestFreezeDesignation` | 4 | the record is generated from the tree, the verifier requires `HEAD == record == tag`, no hand-written SHA, manifest scope |

## 3. Mutation evidence — the tests can fail

`scripts/c3_mutation_evidence.py` re-introduces each defect, runs the tests that
are supposed to catch it, and restores the file, verifying its SHA-256.
Result: **9/9 caught, every file byte-identically restored.**

| Mutation | Tests failing |
| --- | --- |
| M1 stop consuming the U-1 verdict | 1 |
| M2 publish an unknown total as `0` | 1 |
| M3 accept a budget block with no mode | 2 |
| M4 drop the gate's repo-root pin (A-00) | 1 |
| M5 rehearse without building the graph | 1 |
| M6 write `effective_config` without verifying | 1 |
| M7 accept a negative token count | 1 |
| M8 an empty run reports complete attribution | 1 |
| M9 the verifier stops requiring `HEAD == record` | 1 |

Raw output: `logs/mutation_final_freeze.txt`.

## 4. Generation, compilation and static checks

| Check | Result |
| --- | --- |
| `gen_cand01_batch_16run_specs_v2.py --check` | `OK: 53 artefacts reproduce; 16 differ only in volatile fields` |
| `python -m compileall tradingagents cli scripts tests` | clean |
| `ruff check` on every file changed this round | clean |
| `c3_build_manifest.py --check` | every entry verifies |

## 5. Honest gaps

* **No full-suite number is claimed.** The two pre-existing issues noted in
  earlier rounds (the `.env`-coupled `tests/test_cli_prefs.py`, and the
  cwd-relative CAND-01 test) are recorded in `EXECUTION_READINESS.md` §4; the
  second is now fixed, the first is unchanged from RC1 and out of scope.
* **No paid call, no Pipeline, no R01–R16.** Nothing in this document is
  evidence about real token consumption; that is what the full test round and
  the paid runs are for.
* The `logs/` files from earlier rounds are historical evidence and were not
  rewritten. Files added this round are marked by their content
  (`mutation_final_freeze.txt`).
