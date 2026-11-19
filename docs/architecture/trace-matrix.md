# Requirements Trace Matrix

**Baseline:** `docs/req/requirements.yaml` (retrospective requirements baseline, 13
functional + 4 non-functional requirements). The IDs below are the baseline's IDs; no
new requirements are introduced here.

**Tree:** `fix/cs5351-final-submission` at `50b2ca3` (tag
`cand01-v3-final-remediation`). Implementation and test paths below were checked to
exist in this worktree. Evidence points to a commit/tag, a measured run directory, or a
recorded report; it is not a claim that the command was re-run for this document.

**Reading the ADR column.** `—` means the row has no branch ADR (upstream v0.5.0
behaviour or a harness/documentation capability, not a design decision at ADR level). `ADR-00N` means the decision is recorded in
`docs/architecture/adr/`. Where a requirement spans inherited and branch work, the ADR
covers only the branch part.

| Req ID | Requirement (short) | ADR | Implementation path(s) | Test path(s) | Evidence |
| --- | --- | --- | --- | --- | --- |
| **FR-001** | Multi-agent investment analysis: analysts → researchers → manager → trader → risk → portfolio manager; one final decision; configurable rounds | — (upstream topology; blueprint §3) | `tradingagents/graph/setup.py`, `tradingagents/graph/trading_graph.py`, `tradingagents/agents/analysts/market_analyst.py`, `tradingagents/agents/researchers/bull_researcher.py`, `tradingagents/agents/managers/portfolio_manager.py` | `tests/test_analyst_execution.py`, `tests/test_debate_opening.py`, `tests/test_c3_regressions.py` | commit `50b2ca3`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/` |
| **FR-002** | Market, news, fundamentals and macro data acquisition through the vendor router; dated, agent-readable output | ADR-004 (news scope); upstream vendor layer otherwise | `tradingagents/dataflows/interface.py`, `tradingagents/dataflows/finnhub_news.py`, `tradingagents/dataflows/fred.py`, `tradingagents/dataflows/y_finance.py` | `tests/test_dataflows_config.py`, `tests/test_fred.py`, `tests/test_finnhub_news.py`, `tests/test_vendor_errors.py`, `tests/test_alpha_vantage_hardening.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/REMEDIATION.md` |
| **FR-003** | Three tool-loop analysts emit typed, schema-validated reports; free-text fallback still renders missing fields explicitly | ADR-006, ADR-002 | `tradingagents/agents/schemas.py`, `tradingagents/agents/utils/structured.py`, `tradingagents/agents/analysts/market_analyst.py`, `tradingagents/agents/analysts/news_analyst.py`, `tradingagents/agents/analysts/fundamentals_analyst.py` | `tests/test_structured_analyst_output.py`, `tests/test_structured_agents.py`, `tests/test_structured_agent_prompts.py` | `token_benchmarks/final_remediation_20261116/DSML_MARKET_REPORT_FIX.md`; `token_benchmarks/final_remediation_20261116/FINAL_REMEDIATION_REPORT_CN.md` |
| **FR-004** | Every provider usage event attributed to an agent or a named system component; pre-graph reflector is `system:pre_graph_reflector`; `none` invalidates a measured run | ADR-001 | `tradingagents/observability.py`, `tradingagents/graph/reflection.py`, `tradingagents/graph/propagation.py` | `tests/test_system_attribution.py`, `tests/test_observability.py`, `tests/test_c3_regressions.py` | commit `e3b5cca` / tag `c3-v3-final-freeze`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_A.md`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_C.md` |
| **FR-005** | Single-pass structured finalisation: schema bound beside data tools, no second prose regeneration, fallbacks to RC1 without markup leakage | ADR-002, ADR-006 | `tradingagents/agents/utils/structured.py`, `tradingagents/graph/setup.py`, `tradingagents/default_config.py` | `tests/test_cand01_single_pass_finalization.py`, `tests/test_final_remediation.py`, `tests/test_c3_regressions.py` | commit `e0ea1b0`; `token_benchmarks/final_remediation_20261116/FINAL_REMEDIATION_REPORT_CN.md`, `token_benchmarks/final_remediation_20261116/R12_FALLBACK_FIX.md`, `token_benchmarks/final_remediation_20261116/DSML_MARKET_REPORT_FIX.md` |
| **FR-006** | `batch_macro_enabled` switch; ON binds batch tool preserving per-series text; OFF leaves only the single-series tool | ADR-003 | `tradingagents/agents/utils/macro_data_tools.py`, `tradingagents/default_config.py`, `tradingagents/graph/setup.py`, `tradingagents/graph/switch_verification.py` | `tests/test_macro_batch.py`, `tests/test_switch_consumption.py`, `tests/test_ablation_switches.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/experiment.json`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/SWITCH_MATRIX.csv`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md` |
| **FR-007** | PIT: news window, undated exclusion, tool date clamping, memory cutoff; no historical data after the trade date | ADR-002 (single-pass injection), ADR-005 (memory PIT); otherwise upstream PIT corpus | `tradingagents/dataflows/date_window.py`, `tradingagents/agents/utils/core_stock_tools.py`, `tradingagents/agents/utils/news_data_tools.py`, `tradingagents/agents/utils/memory.py` | `tests/test_news_lookahead.py`, `tests/test_fundamentals_lookahead.py`, `tests/test_tool_date_enforcement.py`, `tests/test_undated_tools_as_of.py`, `tests/test_pit_notice.py`, `tests/test_memory_pointintime.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/EXPERIMENT_PROTOCOL_V3.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/CAND01_BATCH_2X2_PROTOCOL_V2.md` |
| **FR-008** | Finnhub-only company news; GDELT disabled and unreachable from the configured route; global news explicitly disabled, not borrowed | ADR-004 | `tradingagents/dataflows/finnhub_news.py`, `tradingagents/dataflows/news_merge.py`, `tradingagents/dataflows/interface.py`, `tradingagents/default_config.py` | `tests/test_finnhub_only_scope.py`, `tests/test_finnhub_news.py`, `tests/test_gdelt_news.py`, `tests/test_news_dual_source.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/logs/finnhub_only_execution_proof.txt`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/RC1_COMPATIBILITY.md` |
| **FR-009** | Per-run memory isolation: one immutable snapshot, one writable copy per run, hash registered, missing/changed state invalidates | ADR-005 | `tradingagents/agents/utils/memory.py`, `scripts/token_benchmark.py`, `scripts/gen_cand01_batch_16run_specs_v3.py` | `tests/test_memory_isolation.py`, `tests/test_memory_pointintime.py`, `tests/test_memory_log.py`, `tests/test_cand01_batch_16run_v3_infra.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/MEMORY_ISOLATION_AUDIT.md`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/MEMORY_SNAPSHOT_PROVENANCE.md`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/memory/baseline_v3.provenance.json`; commit `afa0fc6` |
| **FR-010** | Typed vendor/parser/data-quality errors; unverifiable usage, attribution, memory, switches or budget voids or refuses the run | ADR-006 (fallback component); upstream error taxonomy otherwise | `tradingagents/dataflows/errors.py`, `tradingagents/dataflows/news_status.py`, `tradingagents/dataflows/market_data_validator.py`, `tradingagents/dataflows/interface.py` | `tests/test_vendor_errors.py`, `tests/test_no_data_handling.py`, `tests/test_news_error_classification.py`, `tests/test_news_status_taxonomy.py`, `tests/test_market_data_validator.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/CAND01_BATCH_2X2_PROTOCOL_V2.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/TEST_RESULTS.md` |
| **FR-011** | Usage verdict VALID/MISSING/INCOMPLETE/MISMATCH; only VALID is a measured sample; unknown total is null, replay disagreement voids | ADR-001 | `scripts/token_benchmark.py`, `tradingagents/observability.py` | `tests/test_c3_final_freeze.py` (`TestUsageVerdict`), `tests/test_c3_regressions.py`, `tests/test_token_benchmark.py`, `tests/test_budget_guard.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/C3_HALT_REPORT_20261115.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/logs/mutation_final_freeze.txt`; commit `15270b1` |
| **FR-012** | Budget contract: null cap only with explicit `uncapped_authorized`; distinct refusals; unknown spend not zero | — (harness; blueprint §12) | `scripts/token_benchmark.py`, `tradingagents/budget_guard.py`, `scripts/gen_cand01_batch_16run_specs_v3.py` | `tests/test_budget_guard.py`, `tests/test_c3_final_freeze.py`, `tests/test_token_benchmark.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/BUDGET_GUARD_DESIGN.md`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/EXECUTION_READINESS.md`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/code_freeze.txt` |
| **FR-013** | Research manager, trader and risk team synthesise one final rating with rationale; configured debate rounds; portfolio manager is the single final emitter | — (upstream decision synthesis; blueprint §3) | `tradingagents/agents/managers/research_manager.py`, `tradingagents/agents/managers/portfolio_manager.py`, `tradingagents/agents/trader/trader.py`, `tradingagents/agents/risk_mgmt/aggressive_debator.py`, `tradingagents/graph/setup.py` | `tests/test_debate_opening.py`, `tests/test_structured_agents.py`, `tests/test_reporting.py` | commit `50b2ca3`; tag `cand01-v3-final-remediation` |
| **NFR-001** | Event-level token observability with input/output/cached/reasoning split; retries and failed attempts preserved; duplicate callbacks counted once; totals equal event sum; V2/V3 batch counts | ADR-001 | `tradingagents/observability.py`, `scripts/token_benchmark.py`, `scripts/run_token_benchmark.sh` | `tests/test_observability.py`, `tests/test_token_benchmark.py`, `tests/test_run_token_benchmark_sh.py`, `tests/test_graph_tool_observability.py` | `token_benchmarks/README.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/TEST_RESULTS.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/TEST_RESULTS.md`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/logs/mutation_final_freeze.txt` |
| **NFR-002** | Experiment reproducibility: freeze record + tag + tree fingerprint + manifest + 16 config hashes bind to one commit; drift refused before spend | — (blueprint §12; ADR-005 for memory hash) | `scripts/c3_finalize_freeze.py`, `scripts/c3_verify_final_freeze.py`, `scripts/c3_build_manifest.py`, `scripts/c3_preflight_gate.py`, `scripts/gen_cand01_batch_16run_specs_v3.py` | `tests/test_c3_final_freeze.py`, `tests/test_c3_regressions.py`, `tests/test_cand01_batch_16run_v3_infra.py`, `tests/test_switch_consumption.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/code_freeze.txt`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/RELEASE_SEAL.sha256`, `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/MANIFEST.sha256`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/c3/code_freeze.txt`; `token_benchmarks/final_remediation_20261116/REGRESSION_AUDIT.md` |
| **NFR-003** | Credentials never printed/logged/committed/artefacted; secrets file parsed as data, only CityU vars mapped, exported value wins, key out of argv, owner-only permissions | — (blueprint §14) | `tradingagents/llm_clients/api_key_env.py`, `cli/utils.py`, `scripts/run_token_benchmark.sh`, `.env.example` | `tests/test_api_key_env.py`, `tests/test_google_api_key.py`, `tests/test_cli_env_skip.py`, `tests/test_env_overrides.py` | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/env_credential_audit.txt`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/logs/credential_state.txt`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/logs/audit/AUDIT_C_REPORT.md`; `token_benchmarks/README.md` |
| **NFR-004** | Executable test suite, targeted regressions, defect probes and independent audits; recorded final 2,227/4 known/2 skipped/319 subtests; 20 new tests; three PASS audits | ADR-006 (remediation evidence) | `tests/test_final_remediation.py`, `tests/test_c3_final_freeze.py`, `tests/test_c3_regressions.py`, `tests/test_audit_a_regressions.py`, `tests/test_audit_b_regressions.py`, `tests/test_audit_c_regressions.py` | `tests/test_final_remediation.py`, `tests/test_c3_final_freeze.py`, `tests/test_c3_regressions.py`, `tests/test_audit_a_regressions.py`, `tests/test_audit_b_regressions.py`, `tests/test_audit_c_regressions.py` | `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`; `token_benchmarks/final_remediation_20261116/INDEPENDENT_AUDIT.md` |

---

## Coverage notes and unresolved items

These are the places where the requirement text, the code, and the evidence do not line
up exactly. They are recorded rather than smoothed over.

1. **FR-005 AC-05-02 is stronger than the code.** The AC says every fallback "still
   produces a non-empty report and never a blank one". The code cannot guarantee this:
   if the model itself returns `""`, the single-pass ending returns `""` (logged,
   `report_obj = None`), exactly as RC1 can return an empty `free_text_block`. The
   residual is pinned by `tests/test_cand01_single_pass_finalization.py::BlankReportResidualTest`
   and documented in ADR-002/ADR-006. The requirement should be read as "non-empty on
   the tested fallback paths", not as a universal guarantee.

2. **FR-010 is partly upstream.** The typed vendor/error taxonomy predates the branch
   (v0.5.0); the branch adds the structured fallback safety (ADR-006) and the harness
   fail-closed behaviour. The row maps the branch decision, not authorship of the whole
   taxonomy.

3. **FR-007 has no dedicated PIT ADR.** PIT is largely inherited from v0.5.0; the
   branch's changes are the single-pass injected-date path (ADR-002) and the memory
   per-run/PIT filtering interaction (ADR-005). The trace row therefore points to two
   ADRs rather than claiming a single PIT decision.

4. **NFR-004's full-suite figure is the recorded freeze result.** `TEST_RESULTS.md`
   records 2,227 passed / 4 known failed / 2 skipped / 319 subtests at `50b2ca3`
   (two absolute-path V3 spec checks and two `test_cli_prefs` couplings). This working
   tree now reports 2,233 passed / 0 failed / 2 skipped / 319 subtests (observed
   2026-11-19), so the frozen figure and the current figure should not be conflated.

5. **Remediation was verified offline, not by a new paid batch.** FR-005 AC-03 and the
   R12/DSML fixes are covered by `tests/test_final_remediation.py` and mutation/probe
   evidence. No provider call was made after the remediation, so the V3 numbers remain
   attached to `e3b5cca` and the final tree's behaviour is verified by fixtures.

6. **`s2_downstream` has no OFF implementation.** `tradingagents/graph/switch_verification.py`
   declares it and refuses `False`; the delivered graph always routes S2 fields. This is
   not a requirements row (no requirement currently claims an off-arm), but it is a
   constraint anyone reading the "switches" language should know. See blueprint §5.4.

7. **Freeze tags are local.** The branch history records that only `rc1` was present on
   the remote; `c3-final-freeze`, `c3-v3-final-freeze`, and
   `cand01-v3-final-remediation` exist locally. The verification is still executable,
   but a fresh clone would not have the tags unless they are pushed.
