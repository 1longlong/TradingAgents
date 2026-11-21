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

# Offline deterministic tests

The canonical deterministic tests live here. Core data-quality/debate tests and
WebUI contracts use fake models, fixed data or temporary state. Run from the
repository root:

```bash
python -m pytest -q test/offline --disable-socket --allow-unix-socket
```

Historical result counts in the retained index below are not merged-tree
results. Live/external-service tests remain under `test/live/`.

## Feature-work offline test index (deterministic)

These are the test modules that cover the deterministic Data Quality Gate and
dynamic debate termination, runnable offline:

| Test module | Coverage |
| --- | --- |
| `test/offline/test_data_quality_gate_graph.py` | Gate node integration, fail-closed routing, malformed/missing gate state. |
| `test/offline/test_market_evidence_gate.py` | Market evidence gate behavior. |
| `test/offline/test_evidence_models.py` | Evidence dataclasses, serialization, determinism, acyclicity. |
| `test/offline/test_evidence_step2_regressions.py` | Step 2 regressions (decimal-math / gate core). |
| `test/offline/test_market_data_validator_structured.py` | Structured snapshot -> evidence adaption. |
| `test/offline/test_debate_evaluator.py` | Deterministic `evaluate_round` rule ordering; decision trace. |
| `test/offline/test_debate_graph.py` | Debate evaluator node / graph routing. |
| `test/offline/test_debate_turn.py` | `DEBATE_METADATA` parsing and fallback; metadata parse failure. |
| `test/offline/test_debate_evidence_manifest.py` | Valid-new-evidence manifest / citation allowlist. |
| `test/offline/test_debate_budget.py` | Budget accounting and summary reserve. |
| `test/offline/test_debate_config.py` | `debate_termination` config validation and defaults. |
| `test/offline/test_research_manager_hold_contract.py` | Research-manager hold contract. |
| `test/offline/test_researchers_verdict_gate.py` | Researchers' verdict gate / citation enforcement. |

> The combined debate-focused subset (gate + debate + evidence + verdict gate +
> hold contract) ran **333 passed, offline, 1.00s** in the current working tree
> (see `docs/architecture/evaluation-logbook.md`).

## Other offline test families (upstream, preserved)

The full `test/offline/` directory also contains the upstream offline suite covering
dataflows, LLM-clients, CLI, point-in-time/look-ahead, and reporting. These are
indexed by the upstream suite and are not listed exhaustively here.

## Simulated-trading tests

The imported deterministic subsystem tests live in `test/offline/trading/` and
are included in the full offline command above. Run them independently with:

```bash
python -m pytest -q test/offline/trading --disable-socket --allow-unix-socket
```

The opt-in provider smoke test is separate under `test/live/trading/`.
