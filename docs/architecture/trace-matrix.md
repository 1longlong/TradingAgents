# Trace Matrix

Status: Implemented (Step 14).

Every requirement in `docs/req/requirements.yaml` maps to an enforcing module
and at least one test function. The dynamic coverage test
`test/offline/test_traceability.py::test_every_requirement_id_has_at_least_one_test`
fails if any requirement ID loses its test reference.

| Requirement | Enforcing module(s) | Primary verification test(s) |
|---|---|---|
| **FR-01** — Every LLM decision passes through the deterministic rule engine before execution | `src/trading/pipeline.py` (`decision_from_final_state`, `TradingPipeline.process`), `src/safety/rules.py`, `src/safety/engine.py` | `test/offline/test_rules.py::test_nfr01_each_hard_rule_rejects_its_violation`, `test/offline/test_negative.py::test_fr01_llm_decision_violating_rule_is_rejected`, `test/offline/test_engine.py::test_fr01_rejected_state_writes_reason_and_cannot_execute`, `test/offline/test_pipeline.py::test_fr01_adapter_ignores_llm_supplied_numbers` |
| **FR-02** — Simulated executor updates positions and cash for APPROVED decisions only | `src/trading/executor.py`, `src/trading/portfolio.py`, `src/trading/pipeline.py` | `test/offline/test_executor.py::test_fr02_executor_applies_approved_buy_and_writes_both_events`, `test/offline/test_executor.py::test_fr02_executor_applies_approved_sell`, `test/offline/test_portfolio.py::test_fr02_approved_buy_updates_cash_and_position`, `test/offline/test_pipeline.py::test_fr02_pipeline_happy_path_sizes_evaluates_and_executes` |
| **FR-03** — Portfolio maintains cash, positions, average cost, and realized/unrealized PnL | `src/trading/portfolio.py`, `src/trading/models.py` | `test/offline/test_portfolio.py::test_fr03_selling_all_clears_average_cost_but_keeps_realized_pnl`, `test/offline/test_portfolio.py::test_fr03_mark_to_market_updates_unrealized_pnl_and_equity`, `test/offline/test_models.py::test_fr03_order_intent_and_snapshot_quantize_money` |
| **FR-04** — Append-only audit for decisions, rule evaluations, executions, and human approvals | `src/trading/audit.py`, `src/safety/engine.py`, `src/trading/executor.py`, `src/trading/approval.py` | `test/offline/test_audit.py::test_fr04_required_fields_and_genesis_hash`, `test/offline/test_audit.py::test_fr04_append_preserves_prior_bytes_and_links_hash_chain`, `test/offline/test_approval.py::test_fr04_approval_request_can_be_approved_and_engine_transitions`, `test/offline/test_engine.py::test_fr01_approved_state_runs_all_rules_and_policies` |
| **FR-05** — Historical walk-forward simulation over a date range, with simulated time | `src/trading/clock.py`, `src/trading/backtest.py`, `src/trading/persistence.py`, `src/trading/runtime.py` | `test/offline/test_clock.py::test_fr05_simulation_clock_uses_market_close_not_wall_clock`, `test/offline/test_providers.py::test_fr05_weekday_calendar_skips_weekends_and_is_inclusive`, `test/offline/test_providers.py::test_fr05_historical_quote_provider_reads_only_requested_day`, `test/offline/test_backtest.py::test_fr05_100_day_mock_run_completes_and_persists_cursor`, `test/offline/test_backtest.py::test_fr05_resume_continues_after_interrupted_day` |
| **FR-06** — Persistent portfolio state, manual reset, and sticky BANKRUPT protection | `src/trading/portfolio.py`, `src/trading/persistence.py`, `src/trading/runtime.py`, `src/trading/cli.py`, `src/safety/engine.py` (SR-09) | `test/offline/test_persistence.py::test_fr06_save_and_load_round_trip_all_portfolio_fields`, `test/offline/test_persistence.py::test_fr06_reset_clears_state_and_appends_audit`, `test/offline/test_bankruptcy.py::test_fr06_zero_equity_enters_bankrupt_and_is_sticky`, `test/offline/test_backtest.py::test_fr06_bankruptcy_rejects_all_subsequent_days`, `test/offline/test_runtime.py::test_fr06_reset_clears_bankruptcy_and_preserves_audit`, `test/offline/test_cli_reset.py::test_fr06_cli_reset_clears_state_and_prints_summary` |
| **INV-01** — Zero executions without rule-engine approval | `src/safety/engine.py`, `src/trading/pipeline.py`, `src/trading/executor.py`, `src/trading/backtest.py` | `test/offline/test_invariants.py::test_inv01_non_approved_outcomes_never_reach_execution`, `test/offline/test_invariants.py::test_inv01_approved_is_the_only_path_that_executes`, `test/offline/test_negative.py::test_inv01_rejected_decision_never_reaches_executor`, `test/offline/test_executor.py::test_inv01_execution_started_audit_failure_leaves_portfolio_untouched` |
| **INV-02** — Rule engine is the only executor entry point | `src/safety/engine.py` (engine-issued token), `src/trading/executor.py` (token verification) | `test/offline/test_structure.py::test_inv02_executor_is_imported_only_by_the_safety_engine`, `test/offline/test_invariants.py::test_inv02_forged_authorization_is_rejected_without_mutation`, `test/offline/test_executor.py::test_inv02_forged_base_authorization_is_rejected`, `test/offline/test_executor.py::test_inv02_wrong_provenance_token_is_rejected`, `test/offline/test_negative.py::test_inv02_attempt_to_bypass_rule_engine_fails` |
| **INV-03** — Audit log is append-only and tamper-evident | `src/trading/audit.py` | `test/offline/test_audit.py::test_inv03_modification_of_existing_entry_detected`, `test/offline/test_audit.py::test_inv03_truncation_of_last_entry_detected`, `test/offline/test_audit.py::test_inv03_missing_head_anchor_detected`, `test/offline/test_invariants.py::test_inv03_audit_tampering_is_detected`, `test/offline/test_negative.py::test_inv03_attempt_to_modify_audit_fails` |
| **NFR-01** — 100% rejection of hard safety-rule violations | `src/safety/rules.py`, `src/safety/engine.py` | `test/offline/test_rules.py::test_nfr01_valid_baseline_passes_every_hard_rule`, `test/offline/test_rules.py::test_nfr01_each_hard_rule_rejects_its_violation`, `test/offline/test_rules.py::test_rule_and_policy_wrappers_fail_closed_on_errors` |

## Additional Verifications

- Executor import boundary and network/broker import prohibition:
  `test/offline/test_structure.py::test_fr01_no_network_or_broker_sdk_imports_in_subsystem`.
- Wall-clock isolation: `test/offline/test_structure.py::test_fr05_no_wall_clock_calls_outside_clock_module`.
- Live smoke test (opt-in): `test/live/test_live_backtest.py::test_live_three_day_backtest_smoke`.
- Required negative suite:
  `test/offline/test_negative.py::test_fr01_llm_decision_violating_rule_is_rejected`,
  `test_inv01_rejected_decision_never_reaches_executor`,
  `test_inv03_attempt_to_modify_audit_fails`,
  `test_inv02_attempt_to_bypass_rule_engine_fails`.
