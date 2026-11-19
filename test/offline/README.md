# `test/offline/` — pointer to the offline test suite

The course slide deck refers to an offline test directory. The actual tests live
in the inherited top-level [`tests/`](../../tests/) directory; this directory is a
pointer, not a second test tree. There are no copies or symlinks.

## What the offline subset is

The default `pytest -q` run is offline and LLM-free:

- `tests/conftest.py` installs placeholder API keys and blocks live news vendors.
- Tests that need a real provider, network, or paid call must carry
  `@pytest.mark.integration` and are not part of the default run.
- No test writes to a user's home configuration; preferences are isolated with
  `monkeypatch` and `tmp_path`.
- Frozen experiment tests read sealed specs/manifests and verify hashes; they do
  not regenerate or edit frozen artifacts.

## Run it

From the repository root:

```bash
pytest -q
```

Focused examples used by the course gate:

```bash
pytest tests/test_cand01_batch_16run_v3_infra.py -q
pytest tests/test_cli_prefs.py -q
pytest tests/test_submission_compliance.py -q
python scripts/validate/validate_submission.py
```

## Mapping to the source tree

| Test area | Files |
| --- | --- |
| Graph / agents / routing | `tests/test_analyst_execution.py`, `tests/test_debate_opening.py`, `tests/test_c3_regressions.py` |
| Observability / usage / budget | `tests/test_graph_tool_observability.py`, `tests/test_budget_guard.py`, `tests/test_c3_final_freeze.py` |
| Dataflows / point-in-time / news | `tests/test_finnhub_news.py`, `tests/test_fred.py`, `tests/test_historical_news.py` |
| CLI / preferences | `tests/test_cli_*.py` |
| Frozen CAND-01 infrastructure | `tests/test_cand01_batch_16run_v2_infra.py`, `tests/test_cand01_batch_16run_v3_infra.py` |
| Course compliance | `tests/test_submission_compliance.py` |

The production code these tests exercise is in `tradingagents/` and `cli/`; see
[`src/README.md`](../../src/README.md). Live tests are described in
[`test/live/README.md`](../live/README.md).
