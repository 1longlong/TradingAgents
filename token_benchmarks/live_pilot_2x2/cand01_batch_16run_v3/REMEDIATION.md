# Remediation record

| ID | Finding (2026-11-16) | Root cause | Fix | Test |
| --- | --- | --- | --- | --- |
| C-1 | Pre-graph reflector usage recorded as `unattributed` (R06 invalid) | reflector call runs outside every `attrib_agent_node` scope | unified `AttributionContext`; `system_component_scoped("pre_graph_reflector")` around the invoke; telemetry schema 2 with `attribution_type`/`component_id`/`attribution` totals | `tests/test_system_attribution.py` (10) |
| C-2 | Runs share mutable memory; R05 changed R06's path/tokens | one developer log, read-modify-write across runs | immutable baseline + per-run copy + pre/post hash verification + fail-closed gate; `memory` hashed into the registration; `memory_state.json` per attempt | `tests/test_memory_isolation.py` (17), `tests/test_cand01_batch_16run_v3_infra.py` (11) |
| E-1 | V2 paid runs could dirty the certified tree via per-run `code_state.json` | generator wrote a tracked file the harness rewrote at run start | V3 writes one batch-level `code_state.json`; per-run copy is written at run time and gitignored; fingerprint/MANIFEST exclude it | generator reproduction test; `.gitignore` |
| E-2 | Freeze tooling pinned to one batch/tag | hard-coded constants | env-selectable `C3_BATCH_REL`, `C3_FREEZE_TAG`, `C3_PROTOCOL_NAME`, `C3_GENERATOR` with V2 defaults; V2 tests unchanged | `tests/test_c3_regressions.py` (80) |

No product prompt, model, temperature or call logic was changed. No test was
deleted or weakened; the only test edits are portability fixes for specs that
pin the tree they were generated against, and the versioned hash-field set.
