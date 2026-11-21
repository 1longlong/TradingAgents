# test/offline/ — pointer to the offline test suite

The simulated-trading subsystem's deterministic tests live at `tests/trading/`
and are collected by the canonical `tests/` suite. The course slide deck refers
to an offline test directory; the actual tests live in the inherited top-level
[`tests/`](../../tests/) directory. This directory is a pointer, not a second test
tree — there are no copies or symlinks, and it contains no test code.

## Run it

From the repository root:

```bash
pytest -q                 # the canonical offline suite
pytest tests/trading -q   # the simulated-trading subsystem's suite
```

Focused examples used by the course gate and the experiment work:

```bash
pytest tests/test_cand01_batch_16run_v3_infra.py -q
pytest tests/test_cli_prefs.py -q
pytest tests/test_submission_compliance.py -q
python scripts/validate/validate_submission.py
```

The default suite is not guaranteed green: known, classified failures exist
(date-sensitive cache tests, a vendor-reachability baseline, and two
absolute-path V3 infrastructure checks in a differently rooted worktree). See
[`docs/code-governance/verification-constraints.md`](../../docs/code-governance/verification-constraints.md)
and [`docs/debt-register.md`](../../docs/debt-register.md); do not claim a green
full suite without running it.

## What the offline subset is

- `tests/conftest.py` installs placeholder API keys and blocks live news vendors;
  the default run requires no network and no paid provider call.
- Tests that need a real provider, network, or paid call must carry
  `@pytest.mark.integration` and are not part of the default run.
- No test writes to a user's home configuration; preferences are isolated with
  `monkeypatch` and `tmp_path`.
- Frozen experiment tests read sealed specs/manifests and verify hashes; they do
  not regenerate or edit frozen artifacts.

## Mapping to the source tree

| Test area | Files |
| --- | --- |
| Graph / agents / routing | `tests/test_analyst_execution.py`, `tests/test_debate_opening.py`, `tests/test_c3_regressions.py` |
| Observability / usage / budget | `tests/test_observability.py`, `tests/test_graph_tool_observability.py`, `tests/test_budget_guard.py`, `tests/test_c3_final_freeze.py` |
| Dataflows / point-in-time / news | `tests/test_finnhub_news.py`, `tests/test_fred.py`, `tests/test_historical_news.py` |
| Simulated trading | `tests/trading/` |
| CLI / preferences | `tests/test_cli_prefs.py` and the `tests/test_cli_*.py` family |
| Frozen CAND-01 infrastructure | `tests/test_cand01_batch_16run_v2_infra.py`, `tests/test_cand01_batch_16run_v3_infra.py` |
| Course compliance | `tests/test_submission_compliance.py` |

The production code these tests exercise is in `tradingagents/`, `cli/`, and the
approved `src/trading/`/`src/safety/` subsystem; see [`src/README.md`](../../src/README.md).
Live tests are described in [`test/live/README.md`](../live/README.md).
