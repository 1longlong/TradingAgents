# Test results (actual command output)

Environment: worktree `cand01_v3`, interpreter `/home/sky/cs5351/TradingAgents/.venv/bin/python`,
`TZ=UTC`, from the repository root. Nothing here is a historical or remembered
number; each block is the tail of a real run.

## 1. Full suite

```
$ TZ=UTC .venv/bin/python -m pytest -q
2 failed, 2208 passed, 2 skipped, 26 warnings, 319 subtests passed in 22.76s
```

Collected: **2212** (2208 passed + 2 failed + 2 skipped); 319 subtests passed.

| # | Failure | Status |
| --- | --- | --- |
| 1 | `tests/test_cli_prefs.py::test_selections_are_remembered_after_a_run` | pre-existing, environment-coupled |
| 2 | `tests/test_cli_prefs.py::test_a_remembered_endpoint_is_offered_back` | pre-existing, environment-coupled |

Both fail because `~/.tradingagents/cli_prefs.json` exists (the developer's
remembered CLI selections leak into the test). They reproduce identically on the
frozen C3 baseline with the ambient `TRADINGAGENTS_*` keys unset:

```
$ cd .worktrees/cand01_final_wt && TZ=UTC .venv/bin/python -m pytest -q
2 failed, 2163 passed, 2 skipped, 26 warnings, 319 subtests passed in 24.88s
```

They were not modified: the brief forbids changing unrelated tests to remove an
existing failure.

| | Baseline `15270b1` | This candidate |
| --- | --- | --- |
| passed | 2,163 | **2,208** (+45) |
| failed | 2 | 2 (same two) |
| skipped | 2 | 2 (`langchain_aws` absent; live DeepSeek key absent) |
| subtests | 319 | 319 |
| **new failures** | — | **0** |

## 2. New tests (45)

| File | Tests | Result |
| --- | --- | --- |
| `tests/test_system_attribution.py` | 13 | 13 passed |
| `tests/test_memory_isolation.py` | 20 | 20 passed |
| `tests/test_cand01_batch_16run_v3_infra.py` | 12 | 12 passed |

```
$ TZ=UTC .venv/bin/python -m pytest tests/test_system_attribution.py \
    tests/test_memory_isolation.py tests/test_cand01_batch_16run_v3_infra.py -q
45 passed
```

## 3. Targeted suites

| Suite | Result |
| --- | --- |
| `tests/test_observability.py` | 110 passed |
| `tests/test_c3_regressions.py` | 80 passed |
| `tests/test_c3_final_freeze.py` | 82 passed |
| `tests/test_cand01_batch_16run_v2_infra.py` | 16 passed |
| `tests/test_token_benchmark.py` | 106 passed |
| `tests/test_audit_b_regressions.py` | 68 passed |

## 4. compileall

```
$ .venv/bin/python -m compileall -q tradingagents scripts tests
compileall OK
```

## 5. ruff

```
$ .venv/bin/python -m ruff check tradingagents scripts tests
Found 121 errors.   # identical set, before and after: delta 0
```

Ruff is not a gate on this repository (the C3 baseline already reports 121
findings). The comparison below is normalised by file+rule (line numbers
excluded): the candidate's finding set is **identical** to the baseline's, so
this work introduces no new lint finding. The new files were additionally held
to a clean standard and pass `ruff check` with no findings.

## 6. Offline dry runs

The 16 registered runs are rehearsed after the freeze (the freeze check is part
of the rehearsal): `run --experiment <V3> --dry-run` for R01–R16. Result is
recorded in `RUN_READINESS.md` and the freeze report.
