# test/offline/ — deliverable mapping for deterministic offline tests

The authoritative project slide lists `test/offline/`. This inherited repository
places **all** tests under `tests/`, and the canonical offline deterministic
suite is run from there. This `README` indexes the deterministic offline tests
and maps deliverable `test/offline/` to `tests/`. **No test is duplicated or
relocated.**

## How to run the offline deterministic suite

```bash
# From the repository root, with the dev extra installed:
pytest -q
```

The default `pytest -q` run requires **no network and no paid LLM**. Tests that
need a vendor/Live path are marked `@pytest.mark.integration` and are opt-in
(see `test/live/README.md`).

## Note on full-suite status

The full offline suite is **not** claimed fully green: a small number of dated
cache tests are date-sensitive, and one baseline test depends on vendor
reachability. See `docs/architecture/evaluation-logbook.md`,
`docs/architecture/evaluation-table.md`, and `docs/architecture/risk-list.md`.

## Feature-work offline test index (deterministic)

These are the test modules that cover the deterministic Data Quality Gate and
dynamic debate termination, runnable offline:

| Test module | Coverage |
| --- | --- |
| `tests/test_data_quality_gate_graph.py` | Gate node integration, fail-closed routing, malformed/missing gate state. |
| `tests/test_market_evidence_gate.py` | Market evidence gate behavior. |
| `tests/test_evidence_models.py` | Evidence dataclasses, serialization, determinism, acyclicity. |
| `tests/test_evidence_step2_regressions.py` | Step 2 regressions (decimal-math / gate core). |
| `tests/test_market_data_validator_structured.py` | Structured snapshot -> evidence adaption. |
| `tests/test_debate_evaluator.py` | Deterministic `evaluate_round` rule ordering; decision trace. |
| `tests/test_debate_graph.py` | Debate evaluator node / graph routing. |
| `tests/test_debate_turn.py` | `DEBATE_METADATA` parsing and fallback; metadata parse failure. |
| `tests/test_debate_evidence_manifest.py` | Valid-new-evidence manifest / citation allowlist. |
| `tests/test_debate_budget.py` | Budget accounting and summary reserve. |
| `tests/test_debate_config.py` | `debate_termination` config validation and defaults. |
| `tests/test_research_manager_hold_contract.py` | Research-manager hold contract. |
| `tests/test_researchers_verdict_gate.py` | Researchers' verdict gate / citation enforcement. |

> The combined debate-focused subset (gate + debate + evidence + verdict gate +
> hold contract) ran **333 passed, offline, 1.00s** in the current working tree
> (see `docs/architecture/evaluation-logbook.md`).

## Other offline test families (upstream, preserved)

The full `tests/` directory also contains the upstream offline suite covering
dataflows, LLM-clients, CLI, point-in-time/look-ahead, and reporting. These are
indexed by the upstream suite and are not listed exhaustively here.