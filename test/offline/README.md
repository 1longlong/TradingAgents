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
