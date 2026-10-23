# Traceability Matrix

Maps every requirement ID to its design artifacts, source files, tests, and
current verification evidence. This file MUST be updated in the same change that
adds or changes a requirement. `TODO` items are real gaps, not a claim of
completeness.

| Req ID | Requirement | Design artifacts | Source files | Tests | Verification evidence (observed) |
| --- | --- | --- | --- | --- | --- |
| FR-DQG-001 | Deterministic Data Quality Gate | `adr/001-data-quality-gate.md`, `invariants.md` | `tradingagents/graph/data_quality_gate.py`; `tradingagents/evidence/{gate,multi_category_gate,models,validate,quality,adapter,policy}.py` | `tests/test_data_quality_gate_graph.py`; `tests/test_market_evidence_gate.py`; `tests/test_evidence_models.py`; `tests/test_market_data_validator_structured.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). OpenCode suite: 420 passed (supplied). |
| FR-DQG-002 | Fail-closed gate verdict precedence | `adr/001-data-quality-gate.md`, `invariants.md` | `tradingagents/evidence/gate.py`; `tradingagents/graph/data_quality_gate.py`; `tradingagents/graph/conditional_logic.py` | `tests/test_data_quality_gate_graph.py`; `tests/test_market_evidence_gate.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). |
| FR-DQG-003 | Deterministic gate identifiers and serialization | `adr/001-data-quality-gate.md`, `memory-design.md` | `tradingagents/evidence/{models,adapter}.py`; `tradingagents/graph/data_quality_gate.py` | `tests/test_evidence_models.py`; `tests/test_evidence_step2_regressions.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). |
| FR-DQG-004 | Multi-category data-quality gate engine | `adr/001-data-quality-gate.md`, `invariants.md` | `tradingagents/evidence/{multi_category_gate,gate,policy}.py`; `tradingagents/graph/data_quality_gate.py` | `tests/test_stage2_multicategory_gate.py`; `tests/test_data_quality_gate_graph.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043); `test_stage2_multicategory_gate.py`: 26 passed. Runtime graph default now uses the multi-category engine (engine + graph integration, logbook 043). |
| FR-DQG-005 | Shared deterministic redacted report artifacts | `adr/001-data-quality-gate.md`, `adr/002-dynamic-debate-termination.md`, `code-governance/verification-constraints.md` | `tradingagents/report_artifacts.py`; `tradingagents/reporting.py`; `tradingagents/graph/trading_graph.py`; `cli/main.py` | `tests/test_report_artifacts_stage2.py`; `tests/test_reporting.py` | Stage-2 relevant suite: 442 passed (current tree); `test_report_artifacts_stage2.py`: 16 passed. |
| FR-DDT-001 | Dynamic evidence-aware debate termination | `adr/002-dynamic-debate-termination.md`, `invariants.md` | `tradingagents/debate/{evaluator,evaluator_node,config,models}.py`; `tradingagents/graph/setup.py` | `tests/test_debate_evaluator.py`; `tests/test_debate_graph.py`; `tests/test_debate_turn.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043); OpenCode 420 passed (supplied). |
| FR-DDT-002 | Valid-new-evidence manifest and citation allowlist | `adr/002-dynamic-debate-termination.md` | `tradingagents/debate/{evidence_manifest,turn}.py`; `tradingagents/agents/researchers/{bull,bear}_researcher.py` | `tests/test_debate_evidence_manifest.py`; `tests/test_debate_turn.py`; `tests/test_researchers_verdict_gate.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). |
| FR-DDT-003 | Budget-safe termination with summary reserve | `adr/002-dynamic-debate-termination.md`, `runtime-policy-catalog.md` | `tradingagents/debate/{budget,config}.py`; `tradingagents/debate/evaluator.py` | `tests/test_debate_budget.py`; `tests/test_debate_config.py`; `tests/test_debate_evaluator.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). |
| FR-DDT-004 | Backward-compatible termination config | `adr/002-dynamic-debate-termination.md` | `tradingagents/debate/config.py`; `tradingagents/graph/setup.py` | `tests/test_debate_config.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (current tree, logbook 046). |
| FR-DDT-005 | Deterministic ConflictRecord runtime lifecycle | `adr/002-dynamic-debate-termination.md`, `invariants.md` | `tradingagents/debate/{conflicts,turn,models,evaluator_node}.py`; `tradingagents/agents/managers/research_manager.py` | `tests/test_debate_conflicts.py`; `tests/test_debate_turn.py`; `tests/test_debate_evaluator.py`; `tests/test_debate_graph.py` | `tests/test_debate_conflicts.py`: 39 passed (logbook 046); conflict/debate/graph/Stage-2 relevant suite: 490 passed (logbook 046). |
| NFR-DET-001 | Determinism | `invariants.md` | `tradingagents/evidence/{quality,gate}.py`; `tradingagents/debate/evaluator.py`; `tradingagents/debate/conflicts.py` | `tests/test_evidence_models.py`; `tests/test_debate_evaluator.py`; `tests/test_debate_conflicts.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (current tree, logbook 046). |
| NFR-FC-001 | Fail closed | `invariants.md` | `tradingagents/evidence/gate.py`; `tradingagents/graph/data_quality_gate.py`; `tradingagents/debate/evaluator.py`; `tradingagents/debate/conflicts.py` | `tests/test_market_evidence_gate.py`; `tests/test_debate_evaluator.py`; `tests/test_debate_conflicts.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (current tree, logbook 046). |
| NFR-PIT-001 | Point-in-time integrity | `memory-design.md`, `invariants.md` | `tradingagents/evidence/validate.py`; `tradingagents/dataflows/market_data_validator.py` | `tests/test_fundamentals_lookahead.py`; `tests/test_news_lookahead.py`; `tests/test_social_lookahead.py`; `tests/test_memory_pointintime.py` | Existing point-in-time tests pass within the offline suite; re-run is date-sensitive (see logbook). |
| NFR-AUD-001 | Auditability | `invariants.md` | `tradingagents/evidence/models.py`; `tradingagents/debate/{models,evaluator,conflicts}.py` | `tests/test_evidence_models.py`; `tests/test_debate_evaluator.py`; `tests/test_debate_conflicts.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (current tree, logbook 046). |
| NFR-BUD-001 | Budget safety | `runtime-policy-catalog.md` | `tradingagents/debate/{budget,config}.py` | `tests/test_debate_budget.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). |
| NFR-BC-001 | Backward compatibility | `runtime-policy-catalog.md` | `tradingagents/debate/config.py`; `tradingagents/graph/setup.py` | `tests/test_debate_config.py`; `tests/test_debate_graph.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). |
| NFR-OFF-001 | Offline testability | `code-governance/verification-constraints.md` | `tests/conftest.py` | `tests/test_data_quality_gate_graph.py`; `tests/test_debate_evaluator.py` | Stage-2 relevant suite ran offline (logbook 043); 442 passed. |
| NFR-SEC-001 | Secret safety | `code-governance/verification-constraints.md` | `.env.example`; `AGENTS.md`; `.opencode/permissions.jsonc` | — | Deterministic secret scan of new files found no secrets (see `scripts/validate`). |
| NFR-CMP-001 | Deterministic offline baseline comparison | `adr/003-phase4a-offline-comparison.md`, `invariants.md` | `tradingagents/comparison/{runner,schemas,fixtures}.py`; `scripts/run_phase4a_comparison.py` | `tests/test_comparison_runner.py`; `tests/test_comparison_schemas.py` | Phase 4A comparison tests: 90 passed (current tree; correction round 73, logbook 054; narrow fail-closed correction 90, logbook 055). The actual stop reason is preserved (no_new_evidence / budget_exhausted / max_rounds_reached); a scripted run that exhausts its available rounds is recorded as `input_exhausted` and is never an early stop. Narrow fail-closed correction: `CaseResult.__post_init__` rejects a contradictory `strategy`/`early_stopped`/`stop_reason` combination (FIXED is never early-stopped; an early-stopped DYNAMIC result must carry a genuine `_DYNAMIC_STOP_REASONS` reason) so an inconsistent result can never reach the aggregate/report. |
| NFR-CMP-002 | Machine-readable measured-vs-estimated comparison metrics | `adr/003-phase4a-offline-comparison.md` | `tradingagents/comparison/{metric_formulas,schemas,runner,report}.py` | `tests/test_comparison_schemas.py`; `tests/test_comparison_runner.py` | `tests/test_comparison_schemas.py` + `tests/test_comparison_runner.py`: 90 passed (correction round 73, logbook 054; narrow fail-closed correction 90, logbook 055); evaluation-output reports `Total tool calls`, per-case `Tool calls`/`Source`, `Estimated (not measured) cases`, and the actual per-case + aggregate stop reasons. Narrow fail-closed correction: `early_stop_rate` / the early-stop label can never be produced for a contradictory `strategy`/`early_stopped`/`stop_reason` combination. |
| NFR-CMP-003 | Human traceability rubric and honest scripted-result labeling | `adr/003-phase4a-offline-comparison.md` | `tradingagents/comparison/{schemas,report,runner}.py` | `tests/test_comparison_schemas.py`; `tests/test_comparison_runner.py` | `evaluation-output/comparison_report.md` states offline/scripted scope, not a live-provider result; traceability reported as `pending`; usage `Source` distinguishes estimated/measured (logbook 049). Correction round: a SCORED result requires exactly four non-null scores in `TRACEABILITY_DIMENSIONS` order and rejects missing/extra/null/reordered sets; PENDING stays pending (logbook 054). |

## TODO / gaps

- `RESOLVED (60536848-WANG-Yiwen, 2026-10-21): Official student ID confirmed
  (60536848, WANG Yiwen) and transcript filename finalized to
  transcripts/60536848-WANG-Yiwen.md.`
- `TODO (60536848-WANG-Yiwen): Verify the OpenCode `permissions.jsonc` schema
  against the installed OpenCode version; record result in debt-register.`
- `TODO (60536848-WANG-Yiwen): Decide whether to stabilize or document the
  date-sensitive cache tests and the network-reachability-dependent baseline
  test.`
- `TODO (60536848-WANG-Yiwen): Phase 4A human traceability is pending a human
  score against the documented rubric; every case is reported as "pending" until
  then. Phase 4A results are deterministic offline scripted fixtures, not
  live-provider measurements, and no production thresholds were tuned.
  Correction round implemented (scored status requires exactly four non-null
  traceability scores in TRACEABILITY_DIMENSIONS order; input exhaustion is not
  a dynamic early stop; the actual stop reason is preserved in results,
  JSON/aggregates, and Markdown) and verified by 90 focused comparison tests
  passing (logbook 054/055). Narrow fail-closed correction: a `CaseResult` with
  a contradictory `strategy`/`early_stopped`/`stop_reason` combination is
  rejected at construction (FIXED is never early-stopped; an early-stopped
  DYNAMIC result must carry a genuine `_DYNAMIC_STOP_REASONS` reason), so an
  inconsistent result can never be aggregated or rendered. Human review decision
  (logbook 056, 2026-10-23): **Phase 4A approved with limitations** — the full
  offline suite is not completely green, human traceability scores remain
  `pending`, and no production threshold tuning has been performed.`