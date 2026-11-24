# Integrated core and WebUI records

The canonical layout is `src/` and `test/`. The core records below describe the
release data-quality gate, evidence, debate, usage ledger and output guards;
the WebUI records describe the presentation extension over that core. Existing
requirement and invariant IDs remain scoped to their original modules. An
unqualified core ADR number refers to the release ADR with its descriptive
filename; a WebUI ADR number refers to the WebUI ADR with its descriptive
filename. Both sets remain present. Historical approvals retain their original
scope and do not approve this merge or a new feature. Verification results are
historical unless explicitly identified as a merged-tree run.

## Release core

# Traceability Matrix

Maps every requirement ID to its design artifacts, source files, tests, and
current verification evidence, plus a runtime/audit-monitor column. This file
MUST be updated in the same change that adds or changes a requirement. `TODO`
items are real gaps, not a claim of completeness.

The **Runtime/audit monitor** column separates what actually exists today
(`REAL:`, a concrete state field, exported artifact, router, or validator hook)
from what is only planned (`PLANNED:`), which is either `none` or a named gap
that is explicitly **NOT implemented**. A planned monitor is never counted as
enforcement.

| Req ID | Requirement | Design artifacts | Source files | Tests | Verification evidence (observed) | Runtime/audit monitor |
| --- | --- | --- | --- | --- | --- | --- |
| FR-DQG-001 | Deterministic Data Quality Gate | `adr/001-data-quality-gate.md`, `invariants.md` | `src/tradingagents/graph/data_quality_gate.py`; `src/tradingagents/evidence/{gate,multi_category_gate,models,validate,quality,adapter,policy}.py` | `test/offline/test_data_quality_gate_graph.py`; `test/offline/test_market_evidence_gate.py`; `test/offline/test_evidence_models.py`; `test/offline/test_market_data_validator_structured.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). OpenCode suite: 420 passed (supplied). | REAL: `data_quality_gate` writes `data_quality_gate_decision` + `data_quality_evidence_records` to AgentState; exported `0_quality/gate_summary.md`. PLANNED: none. |
| FR-DQG-002 | Fail-closed gate verdict precedence | `adr/001-data-quality-gate.md`, `invariants.md` | `src/tradingagents/evidence/gate.py`; `src/tradingagents/graph/data_quality_gate.py`; `src/tradingagents/graph/conditional_logic.py` | `test/offline/test_data_quality_gate_graph.py`; `test/offline/test_market_evidence_gate.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). | REAL: `data_quality_error` field + `should_continue_after_data_gate` router; assertion in offline tests. PLANNED: alert on blocked rate. |
| FR-DQG-003 | Deterministic gate identifiers and serialization | `adr/001-data-quality-gate.md`, `memory-design.md` | `src/tradingagents/evidence/{models,adapter}.py`; `src/tradingagents/graph/data_quality_gate.py` | `test/offline/test_evidence_models.py`; `test/offline/test_evidence_step2_regressions.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). | REAL: deterministic run_id/IDs in exported `evidence_manifest.json`. PLANNED: none. |
| FR-DQG-004 | Multi-category data-quality gate engine | `adr/001-data-quality-gate.md`, `adr/008-automatic-structured-evidence-ingestion.md`, `invariants.md` | `src/tradingagents/evidence/{multi_category_gate,gate,policy,ingest,vendor_adapters}.py`; `src/tradingagents/dataflows/evidence_capture.py`; `src/tradingagents/graph/{data_quality_gate,evidence_tool_node}.py` | `test/offline/test_stage2_multicategory_gate.py`; `test/offline/test_data_quality_gate_graph.py`; `test/offline/test_gate_debate_integration.py`; `test/offline/test_structured_evidence_ingestion.py`; `test/offline/test_policy_to_date_python310.py` | Stage-2 relevant suite: 442 passed (logbook 043); `test_stage2_multicategory_gate.py`: 26 passed. 2026-11-06 review finding 2 fix (logbook 065). **2026-11-11 Stage 1 (ADR-008, approved plan+tests ONLY, NOT human acceptance):** automatic structured optional-evidence ingestion from real vendor-origin records (fundamentals via SEC facts + default yfinance/Alpha Vantage statements; news via Yahoo/Alpha Vantage; sentiment via StockTwits/Reddit) through the real tool path and a compiled StateGraph (analyst -> wrapped ToolNode -> clear -> gate -> research -> report), with a durable capture flush at the tool-node boundary (survives `interrupt_after=["tools"]` + saver close + rebuild + `invoke(None)`), versioned attempt envelopes (distinct `started_at=None` attempts not collapsed), sanitized attempts/errors, manual-grade clamping (no self-asserted High), per-category validation, and lineage-based independence. `test/offline/test_structured_evidence_ingestion.py`: 53 passed; full strict-offline suite 1897 passed / 1 skipped / 1 deselected / 88 subtests / 0 socket attempts (logbook 079). **2026-11-12 Python 3.10 CI repair (approved plan+tests ONLY, NOT human acceptance):** `policy.to_date` normalizes a legitimate terminal uppercase `Z` on an extended date+time-shaped string (one separator char incl. `Z` + an at-least-HH time payload, HH-only through fractions) to `+00:00` so a pre-3.11 `fromisoformat` accepts real StockTwits `created_at` sentiment timestamps; date-only `Z`, repeated `ZZ`, `zZ`/`Zz`, `+00:00Z`, and malformed/date-only forms are NOT rewritten and raw parser behavior is retained (native 3.12 accepts raw `...zZ`, native 3.9 rejects it — interpreter-native, NOT universal rejection; lowercase `z`/repeated `ZZ` rejection holds); legacy non-`Z` numeric/compact `to_date` behavior preserved per interpreter (compact acceptance expanded in 3.11; observed 3.12 acceptance is historical baseline only) and adapter `_iso_date` numeric/bool rejection unchanged; offsets keep calendar-date semantics. Independent native 3.9.25/3.12.7 old/new-parser probes (NOT 3.10 proof) drove the guard fixes; **independent OpenCode technical verification COMPLETE (logbook 089): full 2406 passed / 0 sockets; focused 5-module subset 240 / 0; original-2 under pre-3.11 simulation 2 / 0; 22/22 native-3.9 checks; `ruff` clean; governance 43/43; frozen files unchanged)**; explicit human acceptance and actual remote 3.10 CI remain PENDING. `test/offline/test_policy_to_date_python310.py`: 39 passed; `test/offline/test_structured_evidence_ingestion.py`: 53 passed; builder focused/regression 191 passed; full strict-offline 2406 passed / 0 sockets (logbook 089). | REAL: `data_quality_group_statuses` exported in `gate_summary.md` + manifest; optional records + `data_quality_source_attempts` envelope written to state/manifest; durable `data_quality_ingested_evidence`/`data_quality_source_attempt_envelopes`/`data_quality_not_attempted_feeds` state channels. PLANNED: per-category dashboards. |
| FR-DQG-005 | Shared deterministic redacted report artifacts | `adr/001-data-quality-gate.md`, `adr/002-dynamic-debate-termination.md`, `code-governance/verification-constraints.md` | `src/tradingagents/report_artifacts.py`; `src/tradingagents/reporting.py`; `src/tradingagents/graph/trading_graph.py`; `src/cli/main.py` | `test/offline/test_report_artifacts_stage2.py`; `test/offline/test_reporting.py`; `test/offline/test_report_artifacts_audit.py` | Stage-2 relevant suite: 442 passed (current tree); `test_report_artifacts_stage2.py`: 16 passed. 2026-11-06 review finding 3 fix: evidence_manifest exports each record's per-evidence validations by evidence_id AND the separate validation_results_by_evidence_id map; run_summary adds run_id/asset_type/snapshot_id (null when unavailable), quality_counts, and usage_provenance (debate calls separate from total-run calls; unmeasured tool/input-output counts explicit None). `test/offline/test_report_artifacts_audit.py`: 20 passed (was 12; second review adds legacy-embedded preservation, authoritative-map override, shuffle-invariant ordering, ambiguous-identity handling; logbook 061/063). | REAL: `0_quality/*`, `2_research/debate_trace.json`, `run_summary.json` are the audit artifacts themselves; `run_summary.usage_provenance` flags estimated vs measured; run_summary.json, 2_research/debate_trace.json AND the Markdown Run Summary all carry the same participation/skip/stop information and per-field provenance (ADR-007; test/offline/test_report_artifacts_audit.py). PLANNED: none. |
| FR-DQG-006 | Authoritative blocked verdict at the output boundary | `adr/001-data-quality-gate.md`, `invariants.md` | `src/tradingagents/agents/utils/output_guard.py`; `src/tradingagents/agents/utils/rating.py`; `src/tradingagents/agents/managers/{research_manager,portfolio_manager}.py`; `src/tradingagents/agents/trader/trader.py`; `src/tradingagents/graph/signal_processing.py`; `src/tradingagents/agents/utils/memory.py` | `test/offline/test_output_guard.py`; `test/offline/test_research_manager_hold_contract.py`; `test/offline/test_structured_agents.py`; `test/offline/test_memory_log.py` | 2026-11-06 fix of review finding 1, extended by the operator review, the independent recheck findings 1+3, the operator recheck residual, and the operator executable-instruction maintenance. Recognition is a single shared linear scan (`rating.decision_header` / `_split_header`: NFKC-first, optional bullet/heading, arbitrary plain descriptor — no cap — required separator, single-word value) so fullwidth/NFKC labels and values, long decision-label descriptors (`My final ... recommendation rating: Buy`), repeated/trailing labels, Markdown wrapping and executable `FINAL TRANSACTION PROPOSAL: BUY because ...` markers are all pinned to `**<Label>**: Hold` with the explanation preserved as non-executable prose. On a blocked Trader output the fullwidth/long-form entry/stop/position-sizing fields are neutralised to `not applicable` while the rationale survives. Quoted alternatives/blockquotes and narrative mentions (`> ..., not a decision.` / `We rejected the earlier rating: Sell`) are preserved and no longer override the decision: `extract_rating` now takes the last *structural* header as authoritative before its looser within-line fallback, so the plain textual signal, the saved report decision and the memory body all agree with the structured Hold. The final signal boundary stays gate-aware (`SignalProcessor.process_signal(text, state)` -> Hold). `test/offline/test_output_guard.py`: 130 passed (logbook 067); focused affected suite 520 passed; strict offline suite 4 failed / 1661 passed (same known baselines; not all-green). 2026-11-06 fixes await explicit human review. | REAL: output guard pins decision fields; final signal + memory tag exported in saved report. PLANNED: none. |
| FR-DDT-001 | Dynamic evidence-aware debate termination | `adr/002-dynamic-debate-termination.md`, `invariants.md` | `src/tradingagents/debate/{evaluator,evaluator_node,config,models}.py`; `src/tradingagents/graph/setup.py` | `test/offline/test_debate_evaluator.py`; `test/offline/test_debate_graph.py`; `test/offline/test_debate_turn.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043); OpenCode 420 passed (supplied). | REAL: `debate_termination_decision` (route/stop_reason/trace) written to AgentState and `debate_trace.json`. PLANNED: none. |
| FR-DDT-002 | Valid-new-evidence manifest and citation allowlist | `adr/002-dynamic-debate-termination.md`, `adr/010-exact-claim-validation.md` | `src/tradingagents/debate/{evidence_manifest,turn,claims}.py`; `src/tradingagents/agents/researchers/{bull,bear}_researcher.py`; `src/tradingagents/evidence/origin.py` | `test/offline/test_debate_evidence_manifest.py`; `test/offline/test_debate_turn.py`; `test/offline/test_researchers_verdict_gate.py`; `test/offline/test_gate_debate_integration.py`; `test/offline/test_exact_claim_validation.py`; `test/offline/test_exact_claim_runtime.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). 2026-11-06 review finding 2 fix: the manifest/allowlist now receives per-record-classified gate records, so a normal/Medium gate run exposes valid IDs and a cited+linked real ID counts as new; genuinely Low/Blocked/future IDs still never count (`test/offline/test_gate_debate_integration.py`: 9 passed, logbook 065). **2026-11-11 Stage 3 (ADR-010, approved plan+tests ONLY, NOT human acceptance):** a cited, eligible ID whose typed exact claim does not validate (wrong date/value/unit against the record's typed origin) is removed from the valid-new-evidence sets, so it cannot extend the debate; a correct typed exact claim counts normally, and the qualitative/no-claim path is unchanged. `test/offline/test_exact_claim_validation.py`: 60 passed; `test/offline/test_exact_claim_runtime.py`: 9 passed; full strict-offline 2044 passed / 0 sockets (logbook 081). **2026-11-12 two-defect repair (ADR-010 amendment):** a standalone typed `claim=...` line outside the `DEBATE_METADATA` marker (before/after/no-marker, incl. the no-stance FAILED branch) is recovered by a shared strict extractor into the SAME date/value/unit/origin validation; marker presence never hides outside claims (dedupe only by canonical identity); fenced (incl. unclosed) and quoted examples are never trusted; contradictory `role`/`date_role` aliases are unparseable; wrong/unknown/future/Low/foreign fields rejected/unverified, never verified; honest additive coverage is exported and survives a real SQLite resume; legacy no-typed path unchanged; frozen 20/7 records unchanged. `test/offline/test_standalone_claims.py`: 49 passed (logbook 085). | REAL: manifest `valid_ids` exported; allowlist applied in researcher path; evaluator prunes invalid-claimed IDs before new-evidence counting; claim validation summary exported in `debate_trace.json` (now incl. honest `coverage`). PLANNED: citation-coverage metric monitor. |
| FR-DDT-003 | Budget-safe termination with summary reserve | `adr/002-dynamic-debate-termination.md`, `adr/009-durable-run-usage-ledger.md`, `runtime-policy-catalog.md` | `src/tradingagents/debate/{budget,config}.py`; `src/tradingagents/debate/{usage_ledger,usage_capture,researcher_accounting}.py`; `src/tradingagents/debate/evaluator.py`; `src/tradingagents/agents/researchers/{bull,bear}_researcher.py`; `src/tradingagents/graph/{setup,conditional_logic,trading_graph}.py`; `src/cli/main.py` | `test/offline/test_debate_budget.py`; `test/offline/test_debate_config.py`; `test/offline/test_debate_evaluator.py`; `test/offline/test_debate_precall_budget.py`; `test/offline/test_durable_usage_ledger.py`; `test/offline/test_whole_run_usage.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). 2026-11-06 review finding 2 fix: conservative pre-call admission guard before every Bull/Bear so max_calls=1 never executes 2 debate calls; a refused call routes to the Research Manager with budget_exhausted for the incomplete round; enabled=False keeps the legacy baseline. `test/offline/test_debate_precall_budget.py`: 22 passed (was 14; second review requires remaining >= reserve + estimated next-call cost, exact token/time boundaries before Bull/Bear; logbook 060/063). **2026-11-11 Stage 2 (ADR-009, approved plan+tests ONLY, NOT human acceptance):** durable per-run reservation/settlement ledger (SQLite) written BEFORE the outbound call, settled after, reconciled idempotently on resume; a summary admission distinct from the optional-call guard (consumes the reserve without a second optional estimate, requires a remaining call slot, atomic across capture instances); `test/offline/test_durable_usage_ledger.py`: 33 passed; `test/offline/test_whole_run_usage.py`: 10 passed; full strict-offline 1940 passed (logbook 080). | REAL: `debate_usage` (calls/tokens/seconds/estimated) + `budget_exhausted` stop_reason in trace. REAL: `debate_usage` now records MEASURED elapsed time (injectable monotonic clock; invalid/backwards/non-finite aborts), provider-reported token provenance with explicit estimated/missing fallback, per-call conflict originals, logical-vs-transport call distinction, and a sanitized failure ledger (ADR-007). ADR-009 adds a DURABLE ledger (`usage_ledger.db`) with per-invocation reservation/settlement, `whole_run_usage` (all phases) in `run_summary.json`/markdown, and a fail-closed pre-call guard on unresolved spend. PLANNED: cross-process live concurrency beyond the offline barrier tests (offline-proven only). |

| FR-DDT-004 | Backward-compatible termination config | `adr/002-dynamic-debate-termination.md` | `src/tradingagents/debate/config.py`; `src/tradingagents/graph/setup.py` | `test/offline/test_debate_config.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (current tree, logbook 046). | REAL: config validated before graph build (ValueError). PLANNED: none. |
| FR-DDT-005 | Deterministic ConflictRecord runtime lifecycle | `adr/002-dynamic-debate-termination.md`, `adr/010-exact-claim-validation.md`, `invariants.md` | `src/tradingagents/debate/{conflicts,turn,models,evaluator_node,claims}.py`; `src/tradingagents/agents/managers/research_manager.py`; `src/tradingagents/evidence/origin.py` | `test/offline/test_debate_conflicts.py`; `test/offline/test_debate_turn.py`; `test/offline/test_debate_evaluator.py`; `test/offline/test_debate_graph.py`; `test/offline/test_exact_claim_runtime.py` | `test/offline/test_debate_conflicts.py`: 39 passed (logbook 046); conflict/debate/graph/Stage-2 relevant suite: 490 passed (logbook 046). **2026-11-11 Stage 3 (ADR-010):** a factual conflict asserted on an evidence ID whose typed exact claim did not validate is not created (and drops an open one on re-observation) — a valid-but-misused citation never supports/resolves a factual conflict; action/interpretive conflicts unaffected (`test/offline/test_exact_claim_runtime.py::TestConflictLifecycle`, logbook 081). | REAL: derived conflicts + `ConflictSummary` persisted to debate state; invalid-claimed IDs excluded from conflict evidence validation. PLANNED: none. |
| NFR-DET-001 | Determinism | `invariants.md` | `src/tradingagents/evidence/{quality,gate}.py`; `src/tradingagents/debate/evaluator.py`; `src/tradingagents/debate/conflicts.py` | `test/offline/test_evidence_models.py`; `test/offline/test_debate_evaluator.py`; `test/offline/test_debate_conflicts.py`; `test/offline/test_ohlcv_cache_freshness.py`; `test/offline/test_governance_scaffold.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (current tree, logbook 046). **2026-11-11 repair**: the cache-freshness regression matrix proves freshness is deterministic across UTC / `Asia/Hong_Kong` / `America/New_York` (summer+winter/DST) by round-tripping the same local wall time; the governance validator rejects `schema_version` `"1.0"` on both the real-schema and the deterministic-subset paths (ADR-006, logbook 078). | REAL: none dedicated (determinism proven by offline tests only). PLANNED: repeat-run equality monitor. |
| NFR-FC-001 | Fail closed | `invariants.md` | `src/tradingagents/evidence/gate.py`; `src/tradingagents/graph/data_quality_gate.py`; `src/tradingagents/debate/evaluator.py`; `src/tradingagents/debate/conflicts.py`; `src/tradingagents/agents/utils/output_guard.py`; `src/tradingagents/graph/signal_processing.py` | `test/offline/test_market_evidence_gate.py`; `test/offline/test_debate_evaluator.py`; `test/offline/test_debate_conflicts.py`; `test/offline/test_output_guard.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (logbook 046). Missing/malformed/inconsistent gate state fails closed at the output AND final-signal boundaries (`effective_gate_verdict`, `SignalProcessor.process_signal(text, state) -> Hold` on blocked; `test/offline/test_output_guard.py`, logbook 065). | REAL: `data_quality_error` + blocked route + Hold signal boundaries. PLANNED: blocked-escape alert (none). |
| NFR-PIT-001 | Point-in-time integrity | `memory-design.md`, `invariants.md`, `adr/010-exact-claim-validation.md` | `src/tradingagents/evidence/{validate,origin}.py`; `src/tradingagents/dataflows/market_data_validator.py`; `src/tradingagents/debate/claims.py` | `test/offline/test_fundamentals_lookahead.py`; `test/offline/test_news_lookahead.py`; `test/offline/test_social_lookahead.py`; `test/offline/test_memory_pointintime.py`; `test/offline/test_exact_claim_validation.py` | Existing point-in-time tests pass within the offline suite; re-run is date-sensitive (see logbook). **2026-11-11 Stage 3 (ADR-010):** claim dates are validated against the matching typed date role only (target vs observation vs availability vs timestamp); a matched-but-future role value is a look-ahead rejection; an SEC filed date is not the fiscal end; a news publication date is not a figure's date; a date-only source cannot prove a timestamp. `test/offline/test_exact_claim_validation.py::TestCorrectWrongByRole/TestSecFiledNotFiscalEnd/TestNewsPublishedIsNotClaimDate/TestTimestampsAndGranularity` (logbook 081). **2026-11-12 (ADR-010 amendment):** standalone typed claims recovered from outside the marker flow through the SAME role/value/unit validator, so a future-dated or role-mismatched standalone claim is a fail-closed rejection (`test/offline/test_standalone_claims.py::TestFailClosedNegatives`). | REAL: as-of applied in `market_data_validator`/`validate`; observed_at on every exported record; typed origin date roles (`data_quality_origin_metadata`). PLANNED: none (claim-date semantic check now implemented for typed exact claims; free prose beyond the conservative parser stays unverified). |
| NFR-AUD-001 | Auditability | `invariants.md`, `adr/010-exact-claim-validation.md` | `src/tradingagents/evidence/models.py`; `src/tradingagents/debate/{models,evaluator,conflicts,claims}.py`; `src/tradingagents/report_artifacts.py` | `test/offline/test_evidence_models.py`; `test/offline/test_debate_evaluator.py`; `test/offline/test_debate_conflicts.py`; `test/offline/test_report_artifacts_audit.py`; `test/offline/test_exact_claim_validation.py`; `test/offline/test_exact_claim_runtime.py` | Conflict/debate/graph/Stage-2 relevant suite: 490 passed (current tree, logbook 046). Per-evidence validation traceability and run-summary identity/provenance now exported (logbook 061). **2026-11-11 Stage 3 (ADR-010):** every typed exact-claim verdict (verified/rejected/unverified + reason + asserted date/value/unit + cited ids) is exported in `2_research/debate_trace.json` (`claim_validation`) and injected into the Research Manager prompt; the raw rejected fact is redacted from the trusted plan/trader/final decision without a global Hold (`test/offline/test_exact_claim_runtime.py::TestManagerAuditAndTrustedOutput`, logbook 081). **2026-11-12 (ADR-010/011 amendments):** standalone typed-claim coverage (`typed_lines_found`/`parsed`/`unparseable`) is exported (redacted) in `debate_trace.json` and a non-verified standalone typed line in a trusted plan/report is replaced by the unverified marker at `enforce_trusted_boundary`; the ADR-011 boundary fix keeps an ordinary price/date byte-for-byte unchanged (`test/offline/test_confidence_boundary.py::TestRealBoundaryPropagation`; `test/offline/test_standalone_claims.py::TestRealBoundariesAndResume`; logbook 085). | REAL: reason codes/policy_version/critical_evidence_ids/trace exported; exact-claim validation summary exported (verified/rejected/unverified) in debate_trace.json; debate participation truth (structured-only, legacy prose = unverified) + sanitized failure ledger + per-field usage provenance exported in run_summary/debate_trace/markdown (ADR-007; test/offline/test_debate_participation.py, test_report_artifacts_audit.py); live-confirmed by 2026-11-10 D2 (participation explicitly `data_quality_blocked`, no absent-opponent attribution in trusted report; logbook 074). PLANNED: none. |
| NFR-BUD-001 | Budget safety | `adr/009-durable-run-usage-ledger.md`, `runtime-policy-catalog.md` | `src/tradingagents/debate/{budget,config}.py`; `src/tradingagents/debate/{usage_ledger,usage_capture,researcher_accounting}.py`; `src/tradingagents/agents/researchers/{bull,bear}_researcher.py`; `src/tradingagents/graph/{setup,conditional_logic,trading_graph}.py`; `src/cli/main.py` | `test/offline/test_debate_budget.py`; `test/offline/test_debate_precall_budget.py`; `test/offline/test_durable_usage_ledger.py`; `test/offline/test_whole_run_usage.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). Pre-call guard prevents over-budget optional calls; summary reserve preserved; usage estimates honestly flagged (logbook 060). **2026-11-11 Stage 2 (ADR-009):** durable ledger fail-closed on unresolved/unknown spend; atomic admission (call+token+time+reserve) re-read inside a `BEGIN IMMEDIATE` txn across independent capture instances; summary reserve protected per attempt; `test/offline/test_durable_usage_ledger.py` 33 passed + `test/offline/test_whole_run_usage.py` 10 passed; full strict-offline 1940 passed / 0 sockets (logbook 080). | REAL: `debate_usage`/`run_summary.usage` (estimated flag). REAL: measured elapsed + provider token provenance now in `debate_usage` (ADR-007; test/offline/test_debate_budget.py, test_debate_researcher_timing.py); live-confirmed by 2026-11-10 D1 (measured + provider, logbook 074). ADR-009 adds a durable cross-resume ledger (reservation before call, settlement after, idempotent reconcile) and whole-run aggregation. PLANNED: live-provider concurrency/retry observation (hidden SDK retries remain `unknown`; offline-only proof). |

| NFR-BC-001 | Backward compatibility | `runtime-policy-catalog.md`, `adr/010-exact-claim-validation.md`, `adr/011-deterministic-degraded-confidence-cap.md` | `src/tradingagents/debate/config.py`; `src/tradingagents/graph/setup.py`; `src/tradingagents/debate/{confidence_policy,claims,turn,models}.py` | `test/offline/test_debate_config.py`; `test/offline/test_debate_graph.py`; `test/offline/test_confidence_boundary.py`; `test/offline/test_standalone_claims.py` | Stage-2 relevant suite: 442 passed (current tree, logbook 043). **2026-11-12 two-defect repair (approved corrected plan+tests ONLY, NOT human acceptance):** the ADR-011 boundary fix keeps ordinary prices/dates byte-for-byte identical and the ADR-010 standalone recovery is additive — a legacy/qualitative turn with no standalone typed lines keeps the exact prior `claim_validation_summary` shape (no `coverage` key) and `DebateTurn` defaults (0/0); frozen EvidenceRecord(20)/SourceAttempt(7) unchanged. `test/offline/test_confidence_boundary.py` 51 + `test/offline/test_standalone_claims.py` 49 passed; full strict-offline 2290 passed / 0 sockets (logbook 085). | REAL: none dedicated. PLANNED: legacy-vs-enabled routing diff monitor. |
| NFR-OFF-001 | Offline testability | `code-governance/verification-constraints.md` | `test/conftest.py`; `scripts/validate/strict_offline_harness.py` | `test/offline/test_data_quality_gate_graph.py`; `test/offline/test_debate_evaluator.py`; `test/offline/test_governance_scaffold.py`; `test/live/test_no_data_handling.py`; `test/offline/test_ohlcv_cache_freshness.py` | Count-and-fail harness records/asserts forbidden socket attempts (logbook 071). **2026-11-11 repair (DEBT-034/DEBT-001/DEBT-002)**: `test/live/test_no_data_handling.py` now mocks `stockstats_utils.vendor_reachable` (True → no-data `NoMarketDataError`; False → outage `VendorRateLimitError`) under `tmp_path`, and `test/offline/test_ohlcv_cache_freshness.py` uses the local wall-clock epoch with a UTC/HK/NY summer+winter matrix. Full strict-offline suite: **1844 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts** (logbook 078). Zero-attempt now ACHIEVED offline; independently confirmed by OpenCode (focused 76 passed/0 attempts; full 1844 passed/0 attempts; TZ=UTC/HK/NY cache+no-data each 18 passed/0 attempts), logbook 078. Remote CI not re-run (push not authorized). | REAL: `@pytest.mark.integration` marker + offline conftest + count-and-fail harness. PLANNED: dedicated CI socket-deny job (not implemented in this historical snapshot). |
| NFR-SEC-001 | Secret safety | `code-governance/verification-constraints.md` | `.env.example`; `AGENTS.md`; `.opencode/permissions.jsonc` | — | Deterministic secret scan of new files found no secrets (see `scripts/validate`). | REAL: validator `scan_secrets` (reports location only). PLANNED: pre-commit secret hook. |
| NFR-CMP-001 | Deterministic offline baseline comparison | `adr/003-phase4a-offline-comparison.md`, `invariants.md` | `src/tradingagents/comparison/{runner,schemas,fixtures}.py`; `scripts/run_phase4a_comparison.py` | `test/offline/test_comparison_runner.py`; `test/offline/test_comparison_schemas.py` | Phase 4A comparison tests: 90 passed (current tree; correction round 73, logbook 054; narrow fail-closed correction 90, logbook 055). The actual stop reason is preserved (no_new_evidence / budget_exhausted / max_rounds_reached); a scripted run that exhausts its available rounds is recorded as `input_exhausted` and is never an early stop. Narrow fail-closed correction: `CaseResult.__post_init__` rejects a contradictory `strategy`/`early_stopped`/`stop_reason` combination (FIXED is never early-stopped; an early-stopped DYNAMIC result must carry a genuine `_DYNAMIC_STOP_REASONS` reason) so an inconsistent result can never reach the aggregate/report. | REAL: `evaluation-output/comparison_results.json` stop_reason per case. PLANNED: none. |
| NFR-CMP-002 | Machine-readable measured-vs-estimated comparison metrics | `adr/003-phase4a-offline-comparison.md` | `src/tradingagents/comparison/{metric_formulas,schemas,runner,report}.py` | `test/offline/test_comparison_schemas.py`; `test/offline/test_comparison_runner.py` | `test/offline/test_comparison_schemas.py` + `test/offline/test_comparison_runner.py`: 90 passed (correction round 73, logbook 054; narrow fail-closed correction 90, logbook 055); evaluation-output reports `Total tool calls`, per-case `Tool calls`/`Source`, `Estimated (not measured) cases`, and the actual per-case + aggregate stop reasons. Narrow fail-closed correction: `early_stop_rate` / the early-stop label can never be produced for a contradictory `strategy`/`early_stopped`/`stop_reason` combination. | REAL: report `Source`/`Estimated` columns + `usage_provenance`. PLANNED: none. |
| NFR-CMP-003 | Human traceability rubric and honest scripted-result labeling | `adr/003-phase4a-offline-comparison.md` | `src/tradingagents/comparison/{schemas,report,runner}.py` | `test/offline/test_comparison_schemas.py`; `test/offline/test_comparison_runner.py` | `evaluation-output/comparison_report.md` states offline/scripted scope, not a live-provider result; traceability reported as `pending`; usage `Source` distinguishes estimated/measured (logbook 049). Correction round: a SCORED result requires exactly four non-null scores in `TRACEABILITY_DIMENSIONS` order and rejects missing/extra/null/reordered sets; PENDING stays pending (logbook 054). | REAL: report `traceability: pending` + scripted-scope disclaimer. PLANNED: human-score gate (manual). |

## TODO / gaps

- `TODO (60536848-WANG-Yiwen): The 2026-11-06 independent-recheck fixes for
  findings 1/2/3 (FR-DQG-004/006, FR-DDT-002; DEBT-016/017/018; RISK-016/017) are
  technically verified offline and await explicit human review. No human approval
  or traceability score has been recorded for them.`
- `TODO (60536848-WANG-Yiwen): The 2026-11-06 operator executable-instruction
  maintenance (FR-DQG-006; DEBT-020/RISK-019) is technically verified offline and
  awaits explicit human review. It narrows the CLI-hardening gap and the numeric
  degraded confidence ceiling / automatic optional adapters, which remain OPEN and
  were not touched. No human approval or traceability score has been recorded.`
- `TODO (60536848-WANG-Yiwen): The degraded-run numeric confidence ceiling
  (DEBT-014) and automatic multi-category (fundamentals/news/sentiment) evidence
  adapters (DEBT-015/RISK-015) remain explicitly OPEN; no numeric policy or
  adapter was invented in this change.`

- `TODO (60536848-WANG-Yiwen): Stage 2 (ADR-009 durable run-scoped usage ledger
  and whole-run aggregation; DEBT-021/RISK-020 durable-accounting gap) is
  implemented and offline-verified (test/offline/test_durable_usage_ledger.py 33 passed;
  test/offline/test_whole_run_usage.py 10 passed; full strict-offline 1940 passed / 0
  sockets; logbook 080) and awaits INDEPENDENT OpenCode review + explicit human
  acceptance. All four repair items were approved in plan/test scope on 2026-11-11;
  this is implementation approval, NOT final acceptance. (Stage 4 is now
  implemented — see the Stage 4 entry below.)`

- `TODO (60536848-WANG-Yiwen): Stage 3 (ADR-010 exact claim date/value/unit
  validation; DEBT-022/RISK-020 claim-semantics gap) is implemented and
  offline-verified (test/offline/test_exact_claim_validation.py 48 passed;
  test/offline/test_exact_claim_runtime.py 9 passed; full strict-offline 2044 passed / 0
  sockets; logbook 081) and awaits INDEPENDENT OpenCode review + explicit human
  acceptance. Approved in plan/test scope on 2026-11-11 (implementation approval,
  NOT final acceptance). Only typed exact claims and common inline exact prose are
  deterministically validated; arbitrary natural-language semantics are NOT
  claimed proven (an unparseable prose claim stays `unverified`).`

- `TODO (60536848-WANG-Yiwen): Stage 4 (ADR-011 deterministic degraded-run
  confidence cap 0.60; DEBT-014/RISK-014) is implemented and offline-verified
  (test/offline/test_confidence_cap_policy.py + test/offline/test_confidence_cap_runtime.py +
  test/offline/test_confidence_cap_cli.py = 110 passed / 0 sockets; full strict-offline
  2154 passed / 1 skipped / 1 deselected / 22 warnings / 88 subtests / 0 sockets;
  Ruff `All checks passed`; validate_requirements 43/43 PASS; `git diff --check`
  clean; logbook 082) and the independent OpenCode offline verification is
  **CONFIRMED** (same counts; HEAD 5ecea91 unchanged; frozen files unchanged);
  explicit human acceptance remains pending. Approved in plan/test scope on
  2026-11-11 (implementation approval, NOT final acceptance). The post-gate analyst-report / plan / debate+risk-history
  text AND the persisted turn/stance numeric confidence are capped on a per-read
  state COPY before every post-gate model prompt (Bull/Bear/Evaluator/RM/Trader/
  risk×3/PM), so a legacy/direct-GraphSetup/SQLite resume cannot feed a raw 0.95
  to the evaluator or any later prompt; the API and CLI resume paths additionally
  run the SAME fail-closed resume sanitizer before any model/stream call. Typed
  RM/Trader/PM schema confidence is capped on its EXACT raw value BEFORE the lossy
  ``:.2f`` render (a raw 0.6000001/0.604/0.954321 is genuinely capped and its exact
  raw recorded in the audit, never masked by the rounded rendered text). The cap
  is an ENGINEERING ceiling, NOT a calibrated probability and NOT production
  threshold tuning; `blocked` runs keep their non-numeric Hold discipline.`

- `TODO (60536848-WANG-Yiwen): Two-defect repair (2026-11-12; ADR-010 + ADR-011
  amendments; DEBT-039/DEBT-040, RISK-033/RISK-034) is implemented and
  offline-verified: the degraded-confidence suffix grammar no longer corrupts an
  ordinary price (`$204.38.` byte-identical; bare `204.38 confidence` still
  quarantined; genuine forms still cap 0.60; CRLF soft-wrap binds; date/sign/path
  fragments excluded) and the 8 out-of-marker Bear typed lines are recovered into
  the same fail-closed date/value/unit/origin validation with honest coverage
  (fenced incl. unclosed / quoted examples never trusted; alias contradictions
  unparseable; unknown/future/wrong fields rejected). `test/offline/test_confidence_boundary.py`
  51 + `test/offline/test_standalone_claims.py` 49 passed; full strict-offline 2290 passed
  / 1 skipped / 1 deselected / 22 warnings / 88 subtests / 0 sockets; Ruff clean;
  governance 43/43; `git diff --check` clean (logbook 085). Approved in corrected
  plan+test scope on 2026-11-12 (implementation approval, NOT final acceptance).
  **Independent OpenCode technical review is COMPLETE (logbook 086):** same 2290 / 0
  sockets; independent OFFLINE replay of the actual prior-school Bear text recovers
  all 8 claims as 1 verified (volume) / 5 rejected (unknown optional evidence) /
  2 unverified (price currency/unit genuinely unknown) — honest, NOT all-8-verified;
  real Trader/report/record_decision boundaries (real `_is_blocked_state`) confirmed.
  Independent review + explicit human acceptance: review COMPLETE, **human
  acceptance + any live retest remain pending**; preserved live evidence NOT
  relabelled as post-fix live proof.`

- `TODO (60536848-WANG-Yiwen): Verified-span repair (2026-11-12; ADR-010 addendum;
  DEBT-041/RISK-035) is implemented and offline-verified: a CORRECT long-decimal
  typed claim (`value=306127800.0000000000`, `unit=shares`, real volume ID+origin)
  that strictly validates as verified is no longer re-redacted by the generic prose
  scanner. Protection is OCCURRENCE-EXACT (tied to each verified ClaimRecord's own
  `date=`/`value=` field offsets via `claims.extract_claim_span_occurrences`), keeps
  the date+value pair together (no cross-pairing), and shares ONE whole-document
  fence/Example exclusion walk with canonical and standalone detection (a fenced/
  Example canonical claim gains no protection). Separate prose/tail assertions and
  wrong/future/wrong-unit/currency/scale/unknown/Low/Blocked claims remain redacted;
  an unparseable mixed line fails closed. Canonical + standalone forms covered,
  including field-order/wrapper variants (date/value FIRST or LAST with
  bullet/numeric-list or canonical whitespace/backticks) located at exact token
  offsets and supported formats (uppercase keys, spaced keys, canonical backticks,
  equivalent numeric forms). Blanking is PER-TOKEN (`_span_is_authorized`): a verified
  date/value token is never erased and an unauthorized span is always blanked
  regardless of heuristic pairing — duplicate identical `||` canonical subclaims are
  preserved across exhaustive 720 field-order permutations, and mixed verified+wrong
  siblings redact only the bad component.
  `test/offline/test_verified_span_boundary.py` 77 passed (incl. REAL `write_report_tree`
  and `record_decision`/`TradingMemoryLog` with the real `_is_blocked_state`);
  focused relevant suite 716 passed; full strict-offline **2367 passed / 1 skipped /
  1 deselected / 22 warnings / 88 subtests / 0 sockets**; Ruff clean; governance
  43/43; `git diff --check` clean (logbook 087). Approved in plan+test scope on
  2026-11-12 (implementation approval, NOT final acceptance). **Independent OpenCode
  FINAL technical review is COMPLETE (logbook 088):** full 2367 / 0 sockets; focused
  specified 8 modules 556 / 0 sockets (different subset from the 716 related suite;
  not conflated); exhaustive 4320 format cases (720 orders × 6 formats) preserved;
  saved-response replay 19 total checks incl. the 5 equivalent variants all true;
  real report/memory preserve the correct long line while future/unknown-ID claims
  are removed. Authority is PER VERIFIED TOKEN OCCURRENCE (not heuristic pair),
  unprotected partner still checked, no whole-line bypass. Prior 26-call /
  202,941-token school run remains historical bug evidence; **explicit human final
  acceptance + any post-fix live retest pending**.`

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
- `TODO (60536848-WANG-Yiwen): Defect-1 (ADR-010 amendment) — gate origin
  metadata now survives ingestion persistence and real captured-origin conflicts
  fail closed via the declared `data_quality_origin_conflicted_ids` channel. Files:
  `src/tradingagents/graph/data_quality_gate.py`, `src/tradingagents/evidence/ingest.py`,
  `src/tradingagents/evidence/origin.py`, `src/tradingagents/agents/utils/agent_states.py`,
  `src/tradingagents/debate/evaluator_node.py`,
  `src/tradingagents/agents/utils/output_guard.py`. Tests:
  `test/offline/test_gate_origin_authority.py` (18 passed). FR-DQG-004, NFR-PIT-001,
  NFR-AUD-001, INV-3, INV-4. Offline-verified only; the prior incomplete
  2026-11-11 school-model live run is NOT relabelled as a fixed live proof.`
- `TODO (60536848-WANG-Yiwen): Defect-2 (ADR-009 amendment) — structured-output
  raw AIMessage usage retained (same single call, `include_raw=True` with a
  binding-only fallback), settlement precedes parse/sanitize/render, and mixed
  aggregates are labelled `mixed` (report-only, never a per-call source). Files:
  `src/tradingagents/agents/utils/structured.py`, `src/tradingagents/debate/usage_capture.py`,
  `src/tradingagents/debate/budget.py`, `src/tradingagents/report_artifacts.py`. Tests:
  `test/offline/test_structured_raw_usage.py` (18 passed). NFR-BUD-001, NFR-AUD-001,
  FR-DDT-003, NFR-BC-001, INV-7. Offline-verified only; NOT a live proof.`


## WebUI extension

# TradingAgents WebUI Trace Matrix

Status: **Approved for documentation by the human owner on 2026-11-05.** Iterations 1, 2, and 3 are implemented. Execution on 2026-11-06 produced **147 passed** for the WebUI backend suite; full regression produced **1131 passed, 4 historical failures, 2 skipped, 88 subtests passed**; frontend Vitest produced **25 passed**; Chromium Playwright E2E produced **6 passed**. Firefox/WebKit were excluded by user instruction, and the real GraphRunner/live model path remains unrun. The `Evidence status` column remains conservative: passing local tests do not replace a human verification verdict. The module paths are the approved ownership paths from `architecture-blueprint.md` Section 7; see `docs/architecture/evaluation-logbook.md`.

Legend:
- **Module**: primary implementation owner.
- **Planned test**: the node expected to provide the machine check.
- **Monitor**: the runtime signal a reviewer or operator can inspect.
- **Evidence status**: `planned` unless an actual result is recorded in `docs/architecture/evaluation-logbook.md`.

## Requirements to modules and tests

| Requirement | Module | Planned test | Monitor | Evidence status |
| --- | --- | --- | --- | --- |
| REQ-WEB-001 | `api/config.py`, `api/runs.py`, `models/requests.py`, `frontend/src/pages/NewAnalysis` | `test/offline/test_web_runs.py` | Run request validation; env-locked fields | planned |
| REQ-WEB-002 | `runtime/coordinator.py`, `runtime/projector.py`, `frontend/src/pages/LiveRun` | `test/offline/test_web_events.py` | Event sequence; statuses; stats | planned |
| REQ-WEB-003 | `runtime/coordinator.py`, `api/runs.py`, `frontend/src/pages/NewAnalysis` | `test/offline/test_web_runs.py` | Checkpoint flag; clear audit line | planned |
| REQ-WEB-004 | `api/runs.py`, `models/requests.py`, `frontend/src/components/PortfolioEditor` | `test/offline/test_web_portfolio.py` | Portfolio fingerprint; three-state label | planned |
| REQ-WEB-005 | `runtime/coordinator.py`, `api/runs.py` | `test/offline/test_web_runs.py` | `cancelled`; no decision entry; checkpoint present | planned |
| REQ-WEB-006 | `runtime/coordinator.py`, `api/runs.py` | `test/offline/test_web_runs.py` | 409 conflict; single active run | planned |
| REQ-WEB-007 | `runtime/coordinator.py`, `runtime/event_buffer.py`, `frontend/src/hooks/useRunStream` | `test/offline/test_web_events.py` | Snapshot + replay; reconnect | planned |
| REQ-WEB-008 | `artifacts/readers.py`, `frontend/src/pages/Report` | `test/offline/test_web_reporting.py` | I–V sections; REVIEW warning; wall times | planned |
| REQ-WEB-009 | `runtime/artifacts_writer.py`, `artifacts/downloads.py`, `api/history.py` | `test/offline/test_web_reporting.py` | Run directory layout; downloads | planned |
| REQ-WEB-010 | `artifacts/index.py`, `artifacts/readers.py`, `api/history.py` | `test/offline/test_web_history.py` | History sources; no writes | planned |
| REQ-WEB-011 | `runtime/backtest_runner.py`, `api/backtests.py` | `test/offline/test_web_backtest.py` | Summary fields; isolated log | planned |
| REQ-WEB-012 | `api/announcements.py`, `frontend/src/components/Announcements` | `test/offline/test_web_announcements.py` | Fallback; acknowledgement gate | planned |
| REQ-WEB-013 | `api/config.py`, `security.py`, `models/responses.py` | `test/offline/test_web_security.py` | Key status; no key value | planned |
| REQ-WEB-014 | `frontend/src/i18n`, `frontend/src/components/LanguageSwitch` | `test/offline/test_web_frontend_contract.py` | UI language; report language | planned |
| REQ-WEB-020 | `settings.py`, `security.py` | `test/offline/test_web_security.py` | Bind address; Host/Origin checks | planned |
| REQ-WEB-021 | `frontend/`, `playwright.config.ts` | `test/offline/test_web_frontend_contract.py` | Browser matrix | planned |
| REQ-WEB-022 | `runtime/event_buffer.py`, `runtime/projector.py` | `test/offline/test_web_events.py` | Event latency; sequence gaps | planned |
| REQ-WEB-023 | `security.py`, `errors.py`, `models/responses.py` | `test/offline/test_web_security.py` | Redaction; response scan | planned |
| REQ-WEB-024 | `artifacts/index.py`, `security.py` | `test/offline/test_web_security.py` | Identifier resolution; traversal rejection | planned |
| REQ-WEB-025 | `frontend/src/components/Markdown.tsx`, `security.py` | `test/offline/test_web_security.py` | Escaped output; blocked schemes | planned |
| REQ-WEB-026 | `src/tradingagents_web/`, `test/offline/test_web_contracts.py` | `test/offline/test_web_contracts.py`, `test/offline/test_cli_commands.py` | Structural gate; CLI contract | planned |
| REQ-WEB-027 | `src/tradingagents_web/`, route inventory | `test/offline/test_web_contracts.py` | No prompt/vendor/execution changes | planned |
| REQ-WEB-028 | `api/runs.py`, `runtime/coordinator.py` | `test/offline/test_web_portfolio.py`, `test/offline/test_web_contracts.py` | Portfolio fingerprint; REVIEW | planned |
| REQ-WEB-029 | `runtime/coordinator.py` | `test/offline/test_web_runs.py` | Single run; cancellation audit | planned |
| REQ-WEB-030 | `runtime/backtest_runner.py`, `artifacts/index.py` | `test/offline/test_web_backtest.py`, `test/offline/test_web_history.py` | Isolated log; read-only history | planned |
| REQ-WEB-031 | `security.py`, `frontend/src/components/Markdown.tsx` | `test/offline/test_web_security.py` | No execution; escaped content | planned |

## Invariant coverage

| Invariant | Enforcement module | Planned violation test | Evidence status |
| --- | --- | --- | --- |
| INV-WEB-001 | Package boundary; `test_web_contracts.py` | `test/offline/test_web_contracts.py::test_core_and_cli_surface_unchanged` | planned |
| INV-WEB-002 | Route inventory; no execution API | `test/offline/test_web_security.py::test_no_execution_endpoint_exists` | planned |
| INV-WEB-003 | `api/config.py`, `models/responses.py`, `errors.py` | `test/offline/test_web_security.py::test_secrets_never_serialized` | planned |
| INV-WEB-004 | `artifacts/index.py`, `models/responses.py` | `test/offline/test_web_security.py::test_responses_contain_no_filesystem_paths` | planned |
| INV-WEB-005 | `api/runs.py`, `artifacts/index.py` | `test/offline/test_web_security.py::test_path_traversal_is_rejected` | planned |
| INV-WEB-006 | `models/requests.py`, `api/runs.py` | `test/offline/test_web_portfolio.py::test_three_portfolio_states_remain_distinct` | planned |
| INV-WEB-007 | `runtime/coordinator.py`, `frontend/src/pages/Report` | `test/offline/test_web_contracts.py::test_review_is_not_hold` | planned |
| INV-WEB-008 | `runtime/backtest_runner.py` | `test/offline/test_web_backtest.py::test_backtest_does_not_touch_live_memory` | planned |
| INV-WEB-009 | `runtime/coordinator.py` | `test/offline/test_web_runs.py::test_second_run_is_rejected` | planned |
| INV-WEB-010 | `runtime/coordinator.py` | `test/offline/test_web_runs.py::test_cancel_preserves_checkpoint_and_writes_no_decision` | planned |
| INV-WEB-011 | `artifacts/index.py`, `artifacts/readers.py` | `test/offline/test_web_history.py::test_history_endpoints_are_read_only` | planned |
| INV-WEB-012 | `frontend/src/components/Markdown.tsx`, `security.py` | `test/offline/test_web_security.py::test_untrusted_content_is_escaped` | planned |
| INV-WEB-013 | `settings.py`, `security.py` | `test/offline/test_web_security.py::test_non_loopback_host_header_is_rejected` | planned |
| INV-WEB-014 | `api/backtests.py`, `runtime/projector.py` | `test/offline/test_web_backtest.py::test_no_backtest_cancel_route`, `test/offline/test_web_events.py::test_no_fabricated_agent_error_status` | planned |
| INV-WEB-015 | `app.py`, `cli.py`, packaging test | `test/offline/test_web_contracts.py::test_missing_static_assets_fail_loudly` | planned |

## Test suites by layer

| Suite | Command (planned) | Purpose | Status |
| --- | --- | --- | --- |
| Backend offline | `python -m pytest -q test/offline/test_web_*.py` | API, runtime, security, artifacts, backtest | not implemented |
| Existing regression | `python -m pytest -q test/offline --disable-socket --allow-unix-socket` | Prove no regression | not run for this change |
| Frontend unit | `npm run test -- --run` | Store, hooks, components, i18n | not implemented |
| Frontend build | `npm run build` | Typecheck and assets | not run |
| E2E | `npm run e2e` | Chromium/Firefox/WebKit flows | not implemented |
| Packaging | build wheel + clean install + `/api/health` | Static assets and entry point | not run |
| Live | `python -m pytest -q test/live/test_web_live.py` | Real model/data path | not authorized |

## Traceability rules

1. Every new or modified web module or function cites its requirement and invariant IDs in its module or function documentation.
2. Every acceptance criterion in `docs/req/requirements.yaml` has at least one planned test node here.
3. Every invariant has a test that fails when the invariant is violated.
4. A changed requirement or test plan needs a new human review before dependent implementation.
5. This matrix is updated in the same change as the code or test it maps.
6. `planned` never means `passing`; only `docs/architecture/evaluation-logbook.md` records executed results.


## Analysis-path repair mapping

Execution results are recorded in `evaluation-logbook.md`; the following nodes map the repaired contracts without changing requirement approval status.

| Requirements / invariants | Verification nodes |
| --- | --- |
| REQ-WEB-001, REQ-WEB-013 | `test/offline/test_web_analysis_flow.py::test_server_endpoint_and_locks_survive_browser_defaults`; frontend `src/tradingagents_web/frontend/tests/analysis-flow.test.tsx` provider/model submission case |
| REQ-WEB-002, REQ-WEB-005, REQ-WEB-009, INV-WEB-001 | `test/offline/test_web_analysis_flow.py::test_real_graph_runner_through_core_graph_to_report` |
| REQ-WEB-007 | `test/offline/test_web_analysis_flow.py::test_completed_snapshot_contains_report_messages_and_counters`, `test_expired_event_cursor_returns_full_snapshot`; frontend reload/failure snapshot cases; Chromium wizard completion/reload case |
| INV-WEB-003 | `test/offline/test_web_analysis_flow.py::test_real_runner_failure_is_correlated_and_redacted` |
| INV-WEB-009 | `test/offline/test_web_analysis_flow.py::test_artifact_initialization_failure_releases_slot` |
| REQ-WEB-009, INV-WEB-001 | `test/offline/test_web_analysis_flow.py::test_repeated_analysis_keeps_each_run_and_legacy_artifacts` |
| REQ-WEB-002, REQ-WEB-007 | `test/offline/test_web_analysis_flow.py::test_resumed_run_is_running`; frontend `src/tradingagents_web/frontend/tests/run-store.test.ts` resumed/snapshot fallback cases |


### Market-data error follow-up

REQ-WEB-002/005 and INV-WEB-003/010 map to `test/offline/test_web_analysis_flow.py::test_real_market_tool_rate_limit_is_not_reported_as_llm_failure` and `::test_failure_categories_do_not_expose_exception_details`. A failed data request must remain a failed task with a truthful market-data explanation; these cases do not authorize fabricated data, a successful result, or implicit vendor fallback.

## Release / WebUI merge compatibility

| Scope | Source | Offline evidence | Status |
| --- | --- | --- | --- |
| Core ADR-008 structured evidence; REQ-WEB-002; INV-WEB-001 | `src/tradingagents_web/runtime/graph_runner.py` binds `use_collector` around the streamed graph, seeded from prior checkpoint state | `test/offline/test_web_analysis_flow.py::test_stream_runner_preserves_merged_core_contexts`; real graph/report test | Implemented for merge compatibility; final human merge review pending |
| Core ADR-009 durable usage; FR-DDT-003; INV-6/7 | Same adapter resolves execution identity, opens/registers the existing ledger, binds usage capture and attaches whole-run usage | Same parameterized test checks real ledger binding and cleanup on complete/failure/cancel | Offline checks passed; no live-provider claim |
| Core ADR-011 resume confidence; FR-DQG-006; INV-1 | Same adapter sanitizes prior checkpoint state before streaming and passes trusted final state to signal extraction | Same parameterized test rejects unsafe resume before any stream and forces Hold for a blocked state despite directional text | Offline checks passed; no core/CLI implementation changed beyond importing release |
| Historical AI-log container compatibility | `test/ci_gates.py` reads a legacy list base or an entries-envelope base without exempting new path coverage | `test/offline/test_ci_gates.py::test_ai_log_imports_legacy_list_without_waiving_new_coverage` | Positive and negative cases passed |

## Unified registry validation

| Contract | Artifacts / enforcement | Offline evidence |
| --- | --- | --- |
| Preserve original core and WebUI requirements; NFR-SEC-001, INV-1/10 | `docs/req/requirements.yaml`, `docs/req/req-schema.json`; canonical 1.1 format, all 48 IDs, strict typed thresholds, explicit historical scope | `test/offline/test_governance_scaffold.py::TestUnifiedRegistryContracts`: unchanged WebUI entries, lossless core reconstruction, weakened/missing contracts rejected |
| Reject duplicate identities, invalid dependencies and historical evidence upgrades | `scripts/validate/validate_requirements.py::validate_canonical_semantics`, also called from `test/ci_gates.py::validate_registry` | Existing positive/negative CI-gate tests plus unified-registry tests on real and forced fallback paths |
| Parse the retained V1 policy without damaging glob/URL strings; NFR-SEC-001 | `scripts/validate/validate_requirements.py::parse_jsonc` | Quoted globs, URLs, escaped quotes and unterminated-comment regression |
| Missing YAML support and duplicate fields fail closed; NFR-SEC-001, INV-1 | `load_registry_yaml` and the governance CLI | Duplicate YAML-field and missing-dependency regressions; neither path may report unchecked data as passing |

## Workspace visual-parity follow-up

These rows describe frontend presentation over existing contracts. They do not
upgrade requirement status or approve new HTTP projections. Paths below are
relative to `src/tradingagents_web/frontend/`; ADR-003 is the frontend-stack ADR.

| Requirement / invariant | Implementation | Verification |
| --- | --- | --- |
| REQ-WEB-001/003/004/013; INV-WEB-006/014 | `src/tradingagents_web/frontend/src/pages/NewAnalysisPage.tsx`, `src/tradingagents_web/frontend/src/app/App.tsx`, `src/tradingagents_web/frontend/src/api/runClient.ts`: three-step sheet, explicit assets, configured models/locks/thinking, private drafts and server portfolio validation | `src/tradingagents_web/frontend/tests/analysis-flow.test.tsx`; `e2e/visual-parity.spec.ts` sheet geometry, invalid input/endpoint, crypto and privacy cases |
| REQ-WEB-002/005/006/007; INV-WEB-009/010/014 | `src/tradingagents_web/frontend/src/pages/LiveRunPage.tsx`, `src/tradingagents_web/frontend/src/components/Research.tsx`, `src/tradingagents_web/frontend/src/api/runClient.ts`: recorded progress/events, confirmation, cancellation, active conflicts and terminal report | `e2e/run.spec.ts`; existing store tests and backend run/event suites |
| REQ-WEB-008/009/010; INV-WEB-011/014 | `src/tradingagents_web/frontend/src/api/client.ts`, `src/tradingagents_web/frontend/src/components/HistoryTable.tsx`, `src/tradingagents_web/frontend/src/pages/OverviewPage.tsx`, `src/tradingagents_web/frontend/src/pages/HistoryPage.tsx`, `src/tradingagents_web/frontend/src/pages/HistoryDetailPage.tsx`, `src/tradingagents_web/frontend/src/utils/workspace.ts`: all-page history, reference tables, actual sections and downloads | `src/tradingagents_web/frontend/tests/history-parity.test.ts`; `e2e/visual-parity.spec.ts` missing complete artifact, archive and Markdown downloads |
| REQ-WEB-010; INV-WEB-011/012 | `src/tradingagents_web/frontend/src/pages/JournalPage.tsx`, `src/tradingagents_web/frontend/src/components/Modal.tsx`: independent decision/outcome/reflection dialog with sanitized content | `e2e/visual-parity.spec.ts` journal detail; existing Markdown sanitization suite |
| REQ-WEB-006/011/012/013; INV-WEB-014 | `src/tradingagents_web/frontend/src/pages/BacktestPage.tsx`, `src/tradingagents_web/frontend/src/pages/Backtest/BacktestSummary.tsx`, `src/tradingagents_web/frontend/src/api/backtestClient.ts`, `src/tradingagents_web/frontend/src/app/AppShell.tsx`, `src/tradingagents_web/frontend/src/components/Announcements.tsx`: actual summary/null scores, conflict, notes and idle-only clear confirmation | `src/tradingagents_web/frontend/tests/backtest-summary.test.tsx`; backtest/announcement E2E; settings negative confirmation case |
| REQ-WEB-021; INV-WEB-014 | `src/tradingagents_web/frontend/src/styles/index.css`, reference `src/tradingagents_web/frontend/src/styles/workspace.css`, `src/tradingagents_web/frontend/src/components/Research.tsx`, `src/tradingagents_web/frontend/src/components/HistoryTable.tsx`: shared geometry/themes without conflicting preflight | `e2e/visual-parity.spec.ts` 0.75px geometry and both-theme responsive checks |
| REQ-WEB-027; INV-WEB-001/014 | `src/tradingagents_web/frontend/src/pages/HistoryPage.tsx`: audit/comparison lack an approved read projection; no mock results or new routes | `e2e/visual-parity.spec.ts` unavailable surfaces; unchanged backend/API scope |


## Existing-core HTTP projections

Scope: `web-projections-20261120-v1`; ADR-002/003. These implementation records
supersede the earlier audit/comparison interface-gap status without upgrading
requirements or claiming final human acceptance.

| Requirement / invariant | Modules and functions | Verification |
| --- | --- | --- |
| REQ-WEB-008/009/024, NFR-AUD-001; INV-WEB-003/004/005/011/012 | `artifacts/audit.py`: public-data redaction, no-follow canonical reads, strict JSON parsing, bounded bundles/downloads and identity/cutoff projection; `api/audit.py`: indexed history/run views and family previews/downloads | `test/offline/test_web_audit.py`: complete/legacy/partial/invalid/oversized/UTF-8/nonfinite/duplicate data, symlink escapes, opaque IDs, credentials/URL/path redaction, inconsistent identity/verdict and saved-date rejection |
| REQ-WEB-002/009/010/013; INV-WEB-001/003/011/014 | `runtime/artifacts_writer.py`: run-local core audit copies, allowlisted lifecycle/origin context and effective configuration; `runtime/coordinator.py`, `api/runs.py`: writer association and language snapshot; `artifacts/index.py`, `readers.py`, `api/history.py`: optional safe presentation metadata | Same audit suite: real completed fake-run association, unavailable active-run families, actual runtime lifecycle, metadata/context privacy; previous run/history/security suites |
| NFR-CMP-001/002/003; INV-9, INV-WEB-001/014 | `api/comparisons.py`: fixed core factories, catalog, core replay/pairing, bounded JSON projection/download; `app.py`: router registration | `test/offline/test_web_comparisons.py`: exact D/E/F/G outcomes, pending rubric, unknown/mismatched identities, bounded output and no writes/active slot use |
| REQ-WEB-008/009/010/013, NFR-CMP-001; INV-WEB-011/012/014 | Frontend `api/auditClient.ts`, `pages/AuditPage.tsx` (including overview projection), `ComparisonPage.tsx`, `OverviewPage.tsx`, `HistoryDetailPage.tsx`, `LiveRunPage.tsx`, `components/HistoryTable.tsx`, API types and route registration | `src/tradingagents_web/frontend/tests/audit-comparison.test.tsx`, `e2e/audit-comparison.spec.ts`: unknown telemetry, evidence filter/detail, disagreement, available-only preview/download, actual replay, G not early stop, mismatched pairing/export refusal; previous frontend suites |

All backend module paths above are relative to `src/tradingagents_web/`.

## Simulated trading subsystem (TRD) trace rows

| Requirement | Enforcing module(s) | Primary tests |
|---|---|---|
| **FR-TRD-001** — deterministic safety gate | `src/safety/rules.py`, `src/safety/engine.py`, `src/trading/pipeline.py` | `test/offline/trading/test_rules.py`, `test/offline/trading/test_engine.py`, `test/offline/trading/test_negative.py`, `test/offline/trading/test_pipeline.py` |
| **FR-TRD-002** — simulated executor | `src/trading/executor.py`, `src/trading/portfolio.py` | `test/offline/trading/test_executor.py`, `test/offline/trading/test_portfolio.py`, `test/offline/trading/test_pipeline.py` |
| **FR-TRD-003** — portfolio ledger | `src/trading/portfolio.py`, `src/trading/models.py` | `test/offline/trading/test_portfolio.py`, `test/offline/trading/test_models.py` |
| **FR-TRD-004** — append-only audit | `src/trading/audit.py`, `src/safety/engine.py`, `src/trading/executor.py`, `src/trading/approval.py` | `test/offline/trading/test_audit.py`, `test/offline/trading/test_approval.py`, `test/offline/trading/test_engine.py`, `test/offline/trading/test_invariants.py` |
| **FR-TRD-005** — walk-forward simulation | `src/trading/clock.py`, `src/trading/backtest.py`, `src/trading/persistence.py` | `test/offline/trading/test_clock.py`, `test/offline/trading/test_providers.py`, `test/offline/trading/test_backtest.py` |
| **FR-TRD-006** — persistence/reset/bankruptcy | `src/trading/portfolio.py`, `src/trading/persistence.py`, `src/trading/runtime.py`, `src/trading/cli.py` | `test/offline/trading/test_persistence.py`, `test/offline/trading/test_bankruptcy.py`, `test/offline/trading/test_runtime.py`, `test/offline/trading/test_cli_reset.py` |
| **INV-TRD-001** — no execution without approval | `src/safety/engine.py`, `src/trading/pipeline.py` | `test/offline/trading/test_invariants.py`, `test/offline/trading/test_negative.py` |
| **INV-TRD-002** — engine-only executor entry | `src/safety/engine.py`, `src/trading/executor.py` | `test/offline/trading/test_structure.py`, `test/offline/trading/test_invariants.py`, `test/offline/trading/test_executor.py` |
| **INV-TRD-003** — append-only audit | `src/trading/audit.py` | `test/offline/trading/test_audit.py`, `test/offline/trading/test_invariants.py`, `test/offline/trading/test_negative.py` |
| **NFR-TRD-001** — 100% hard-rule rejection | `src/safety/rules.py`, `src/safety/engine.py` | `test/offline/trading/test_rules.py`, `test/offline/trading/test_engine.py` |

## D1 integration trace rows (FR-ANL / FR-OBS / FR-HAR / FR-CAM)

These rows record capabilities that the delivered token-observability work added
without an identifier. They use the same columns as the table above. Every row is
`implemented` in the merged tree; a row whose `fit_criterion.status.state` is
`partially_verified` names the residual rather than claiming a green result.

The D1 integration (2026-11-21) resolved the 21 personal requirements one at a
time against this matrix. Two were merged into established Release rows
(`FR-007` -> `NFR-PIT-001`, `NFR-003` -> `NFR-SEC-001`) and one into
`FR-ANL-001` (`FR-013`); the interim point-in-time analysis row was therefore
removed as a synonym and its paths, tests and evidence now live on
`NFR-PIT-001` (the old personal alias is not a separate registry row). The registry is 52 rows: the
original 32 Release IDs plus 20 retrospective IDs. The complete 21-row
reconciliation and the 64-row acceptance-criterion table follow the D1 table
below.

| Req ID | Requirement | Design artifacts | Source files | Tests | Verification evidence (observed) | Runtime/audit monitor |
| --- | --- | --- | --- | --- | --- | --- |
| FR-ANL-001 | Deterministic multi-agent analysis pipeline topology | `architecture-blueprint.md` | `src/tradingagents/graph/setup.py`; `src/tradingagents/graph/trading_graph.py`; `src/tradingagents/agents/analysts/{market,news,fundamentals}_analyst.py`; `src/tradingagents/agents/managers/{research,portfolio}_manager.py` | `test/offline/test_analyst_execution.py`; `test/offline/test_debate_opening.py`; `test/offline/test_c3_regressions.py` | Named files pass offline (merged worktree). | REAL: compiled `StateGraph` in `GraphSetup`; single graph per run. PLANNED: none. |
| FR-ANL-002 | Typed vendor failures instead of silent empty successes | `invariants.md` | `src/tradingagents/dataflows/{errors,news_status,market_data_validator,interface}.py` | `test/offline/test_vendor_errors.py`; `test/live/test_no_data_handling.py`; `test/offline/test_news_error_classification.py`; `test/offline/test_news_status_taxonomy.py`; `test/offline/test_market_data_validator.py` | Named files pass offline; vendor reachability mocked. | REAL: typed exception classes + `SourceResultStatus`. PLANNED: none. |
| FR-ANL-003 | Typed analyst reports with a labelled free-text fallback | `adr/014-single-pass-finalization.md`, `adr/018-structured-fallback-safety.md`, `invariants.md` | `src/tradingagents/agents/schemas.py`; `src/tradingagents/agents/utils/structured.py`; `src/tradingagents/agents/analysts/*.py` | `test/offline/test_structured_analyst_output.py`; `test/offline/test_structured_agents.py`; `test/offline/test_structured_agent_prompts.py` | Named files pass offline. Blank-report residual pinned by `test/offline/test_cand01_single_pass_finalization.py::BlankReportResidualTest`. | REAL: typed report fields in `AgentState`; explicit missing-field rendering. PLANNED: none. |
| FR-ANL-004 | Agent and system-component usage attribution | `adr/013-provider-usage-observability.md`, `invariants.md` | `src/tradingagents/observability.py`; `src/tradingagents/graph/reflection.py`; `src/tradingagents/graph/propagation.py` | `test/offline/test_system_attribution.py`; `test/offline/test_observability.py`; `test/offline/test_c3_regressions.py` | Named files pass offline. Commit `e3b5cca` / tag `c3-v3-final-freeze`. | REAL: `AGENT_UNATTRIBUTED` bucket; `system:pre_graph_reflector` identity. PLANNED: none. |
| FR-ANL-005 | Single-pass structured report finalisation | `adr/014-single-pass-finalization.md`, `adr/018-structured-fallback-safety.md` | `src/tradingagents/agents/utils/structured.py`; `src/tradingagents/graph/setup.py`; `src/tradingagents/default_config.py` | `test/offline/test_cand01_single_pass_finalization.py`; `test/offline/test_final_remediation.py`; `test/offline/test_c3_regressions.py` | Named files pass offline. Commit `e0ea1b0`. | REAL: `finalize_single_pass` at the transport boundary. PLANNED: none. |
| FR-ANL-006 | `batch_macro_enabled` switch with exact per-series preservation | `adr/015-batch-macro-switch.md`, `evaluation-logbook.md`, `invariants.md` | `src/tradingagents/agents/utils/macro_data_tools.py`; `src/tradingagents/default_config.py`; `src/tradingagents/graph/setup.py`; `src/tradingagents/graph/switch_verification.py` | `test/offline/test_macro_batch.py`; `test/offline/test_switch_consumption.py`; `test/offline/test_ablation_switches.py` | Named files pass offline. Token effect recorded as exploratory/not robust; NOT restated as a verified saving. | REAL: switch read by `GraphSetup`; batch tool bound only when ON. PLANNED: none. |
| FR-ANL-008 | Finnhub-only company-news provenance | `adr/016-finnhub-only-news.md`, `invariants.md` | `src/tradingagents/dataflows/finnhub_news.py`; `src/tradingagents/dataflows/news_merge.py`; `src/tradingagents/dataflows/interface.py`; `src/tradingagents/default_config.py` | `test/offline/test_finnhub_only_scope.py`; `test/offline/test_finnhub_news.py`; `test/offline/test_gdelt_news.py`; `test/offline/test_news_dual_source.py` | Named files pass offline. | REAL: configured route resolves company news to Finnhub; GDELT unreachable. PLANNED: none. |
| FR-ANL-009 | Per-run memory isolation from an immutable snapshot | `adr/017-per-run-memory-isolation.md`, `memory-design.md`, `invariants.md` | `src/tradingagents/agents/utils/memory.py`; `scripts/token_benchmark.py`; `scripts/gen_cand01_batch_16run_specs_v3.py` | `test/offline/test_memory_isolation.py`; `test/offline/test_memory_pointintime.py`; `test/offline/test_memory_log.py`; `test/offline/test_cand01_batch_16run_v3_infra.py` | Isolation tests pass offline. Two absolute-path V3 infra checks are documented known failures outside their generating checkout; NOT claimed green. | REAL: registered snapshot hash + per-run copy. PLANNED: none. |
| FR-ANL-010 | Vendor-routed market, news and macro data acquisition | `architecture-blueprint.md`, `runtime-policy-catalog.md`, `invariants.md` | `src/tradingagents/dataflows/{interface,config,y_finance,finnhub_news,fred,alpha_vantage_stock,alpha_vantage_fundamentals,alpha_vantage_indicator}.py`; `src/tradingagents/agents/utils/{core_stock_tools,fundamental_data_tools}.py` | `test/offline/test_dataflows_config.py`; `test/offline/test_fred.py`; `test/offline/test_vendor_errors.py`; `test/offline/test_finnhub_news.py` | Named files pass offline against stubbed vendors; no live key or vendor response claimed. | REAL: routing table + dated markdown rendering. PLANNED: none. |
| FR-OBS-001 | Event-level token accounting with a null-not-zero rule | `adr/013-provider-usage-observability.md`, `runtime-policy-catalog.md`, `invariants.md` | `src/tradingagents/observability.py`; `src/cli/stats_handler.py` | `test/offline/test_observability.py`; `test/offline/test_graph_tool_observability.py`; `test/offline/test_whole_run_usage.py` | Named files pass offline against scripted transports. | REAL: per-event records with four separate counts; absent field is null. PLANNED: none. Overlaps `NFR-AUD-001`. |
| FR-OBS-002 | Evaluated usage-completeness verdict that gates validity | `adr/013-provider-usage-observability.md`, `runtime-policy-catalog.md`, `evaluation-logbook.md` | `scripts/token_benchmark.py`; `src/tradingagents/observability.py` | `test/offline/test_c3_final_freeze.py`; `test/offline/test_token_benchmark.py`; `test/offline/test_c3_regressions.py` | Usage-verdict tests pass offline. | REAL: VALID/MISSING/INCOMPLETE/MISMATCH consumed by validity. PLANNED: none. |
| FR-OBS-003 | Tool-round and system-component events counted outside agent buckets | `adr/013-provider-usage-observability.md`, `runtime-policy-catalog.md`, `invariants.md` | `src/tradingagents/observability.py`; `src/tradingagents/graph/evidence_tool_node.py`; `src/cli/stats_handler.py` | `test/offline/test_graph_tool_observability.py`; `test/offline/test_system_attribution.py`; `test/offline/test_merge_integration.py` | Named files pass offline; unattributed bucket asserted directly. | REAL: tool-round telemetry + unattributed bucket included in run totals. PLANNED: none. |
| FR-OBS-004 | Invocation-level settlement of Single-Pass attempts | `adr/009-durable-run-usage-ledger.md`, `adr/014-single-pass-finalization.md`, `adr/013-provider-usage-observability.md` | `src/tradingagents/agents/utils/structured.py`; `src/tradingagents/debate/usage_capture.py` | `test/offline/test_merge_integration.py`; `test/offline/test_structured_raw_usage.py` | Named files pass offline with a scripted recording transport. | REAL: N outbound attempts produce N invocation records; no nested settlement. PLANNED: none. |
| FR-OBS-005 | Telemetry selection integrity across repeated attempts | `adr/013-provider-usage-observability.md`, `evaluation-logbook.md` | `scripts/token_benchmark.py` | `test/offline/test_token_benchmark.py`; `test/offline/test_c3_regressions.py` | Named files pass offline against archived run directories. | REAL: pre-fixed selection rule; superseded attempts preserved. PLANNED: none. |
| FR-HAR-001 | One-command archived token measurement harness | `evaluation-logbook.md`, `token_benchmarks/README.md` | `scripts/run_token_benchmark.sh`; `scripts/token_benchmark.py` | `test/offline/test_run_token_benchmark_sh.py`; `test/offline/test_token_benchmark.py` | `test/offline/test_token_benchmark.py` passes offline. `test/offline/test_run_token_benchmark_sh.py` passes in the final integrated suite (5,132 passed / 3 skipped, `94755cf`); earlier `NOT_RUN` was an environment limitation. | REAL: archived run directories + summary. PLANNED: none. |
| FR-HAR-002 | Experiment reproducibility bound to one frozen commit | `runtime-policy-catalog.md`, `evaluation-logbook.md` | `scripts/c3_finalize_freeze.py`; `scripts/c3_verify_final_freeze.py`; `scripts/c3_build_manifest.py`; `scripts/c3_preflight_gate.py`; `scripts/gen_cand01_batch_16run_specs_v3.py` | `test/offline/test_c3_final_freeze.py`; `test/offline/test_c3_regressions.py`; `test/offline/test_cand01_batch_16run_v3_infra.py`; `test/offline/test_switch_consumption.py` | Freeze/regression checks pass offline. Two V3 infra checks are known path-sensitive failures; recorded, not hidden. | REAL: freeze record + tag + HEAD + manifest + release seal. PLANNED: none. |
| FR-CAM-001 | Optimisation campaign with an explicit accept-or-revert decision | `evaluation-logbook.md` | `scripts/campaign_ablation_round.py`; `scripts/ablation_analysis.py`; `scripts/quality_evidence_check.py` | `test/offline/test_ablation_switches.py` | `test/offline/test_ablation_switches.py` passes offline. Campaign numbers NOT re-derived; recorded as NOT_VERIFIED for this submission. | REAL: campaign scripts + accept/revert records. PLANNED: none. |

| FR-HAR-003 | Fail-closed spend contract for authorised paid runs | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/BUDGET_GUARD_DESIGN.md`, `runtime-policy-catalog.md` | `scripts/token_benchmark.py`; `src/tradingagents/budget_guard.py`; `scripts/gen_cand01_batch_16run_specs_v3.py` | `test/offline/test_budget_guard.py`; `test/offline/test_c3_final_freeze.py` | `test/offline/test_budget_guard.py` passes offline. Contract is a refusal rule, not a measured saving; no provider spend claimed. | REAL: mode-declared cap; distinct refusals; unknown spend never zero. PLANNED: none. |
| NFR-VER-001 | Executed offline test suite and independent audit | `evaluation-logbook.md` | `test/offline/test_final_remediation.py`; `test/offline/test_c3_final_freeze.py`; `test/offline/test_c3_regressions.py`; `test/offline/test_audit_a_regressions.py`; `test/offline/test_audit_b_regressions.py`; `test/offline/test_audit_c_regressions.py` | `test/offline/test_final_remediation.py`; `test/offline/test_c3_final_freeze.py`; `test/offline/test_submission_compliance.py` | Historical: 2,227 passed / 4 known failed / 2 skipped at `50b2ca3`; .env-free 2,233 / 0 / 2 / 319; three AI audits PASS. Current integrated tree: **5,132 passed / 3 skipped**, validators PASS, `ruff check .` PASS (`94755cf`). | REAL: suite + audit reports are the verification of record. PLANNED: merged-tree green run (blocked). |
| NFR-VER-002 | Executed verification instead of simulated results | `code-governance/verification-constraints.md` | `test/conftest.py`; `scripts/c3_verify_final_freeze.py`; `scripts/c3_finalize_freeze.py`; `scripts/c3_preflight_gate.py` | `test/offline/test_c3_final_freeze.py`; `test/offline/test_governance_scaffold.py` | Offline guards block live vendors; freeze verifier recomputes hashes; rehearsal-failure paths exist. Process control, DOCUMENTED_ONLY. | REAL: conftest guards + freeze verifier. PLANNED: mechanical detector for a simulated claim (none). |

## Release rows extended by the D1 integration

The 32 Release rows are preserved. Three were extended additively; no
Release field was removed, no fit criterion was changed, and no threshold
was altered. Everything added is source path, test path or evidence prose.

| Release row | Added by D1 | Why it is additive, not a re-scope |
| --- | --- | --- |
| NFR-PIT-001 | +4 source files (`date_window.py`, `core_stock_tools.py`, `news_data_tools.py`, `memory.py`); +3 tests (`test_tool_date_enforcement.py`, `test_undated_tools_as_of.py`, `test_pit_notice.py`); +1 evidence line for personal FR-007 | The row already required "no future data reaches a decision"; the additions name the delivered analysis-pipeline paths that enforce it. The requirement text and fit criterion are unchanged. |
| NFR-SEC-001 | +3 source files (`api_key_env.py`, `src/cli/utils.py`, `run_token_benchmark.sh`); `tests` changed from `[]` to 2 credential tests; +1 evidence line for personal NFR-003 | The row already required secret safety; the additions name the delivered credential-handling paths. Adding tests strengthens, never weakens, the row. |
| FR-ANL-001 | +3 source files (conservative/neutral debaters, `trader.py`); `source_requirement_ids` gains `FR-013`; +1 evidence line | FR-ANL-001 is itself retrospective; personal FR-013 describes the same pipeline from the decision end, so it is merged rather than duplicated. |

## Personal registry reconciliation (21 rows)

The personal registry (`docs/req/requirements.yaml` on
`feature/token-observability`, 21 requirements / 64 acceptance criteria)
was resolved requirement by requirement against the Release text. `add` =
a new Release-format ID; `merge` = integrated into an established Release
row; `merge-new` = integrated into a new row created for the same
obligation. No personal ID is left unmapped.

| Personal ID | Destination | Decision | Rationale |
| --- | --- | --- | --- | --- |
| FR-001 | FR-ANL-001 | add | No Release row states the agent topology. Personal FR-013 (final decision synthesis) is the same pipeline described from the decision end and is merged into this row. |
| FR-002 | FR-ANL-010 | add | No Release row states vendor-routed data acquisition. NFR-PIT-001 covers date integrity and FR-DQG-004 covers evidence gating, but neither covers acquisition. |
| FR-003 | FR-ANL-003 | add | No Release row states typed analyst reports or the labelled free-text fallback. |
| FR-004 | FR-ANL-004 | add | No Release row states per-agent/per-system-component usage attribution. NFR-AUD-001 audits decisions, not usage. |
| FR-005 | FR-ANL-005 | add | No Release row states Single-Pass structured finalisation. |
| FR-006 | FR-ANL-006 | add | No Release row states the batch-macro switch. |
| FR-007 | NFR-PIT-001 | merge | NFR-PIT-001 already states the same obligation (no future data reaches a decision; every dated path evaluated as of the trade date). Integrated: personal paths, 3 extra test files and a D1 evidence line were added to NFR-PIT-001; no separate point-in-time row remains. |
| FR-008 | FR-ANL-008 | add | No Release row states Finnhub-only news provenance; NFR-SEC-001 is about secrets and FR-DQG-004 about gating, not provenance. |
| FR-009 | FR-ANL-009 | add | No Release row states per-run memory isolation from a registered snapshot. |
| FR-010 | FR-ANL-002 | add | Kept separate from NFR-FC-001: NFR-FC-001 governs gate/evaluator fail-closed routing; this row governs the typed vendor/parser failure taxonomy. The shared principle is noted on the row. |
| FR-011 | FR-OBS-002 | add | No Release row states the VALID/MISSING/INCOMPLETE/MISMATCH usage verdict or its consumption by run validity. |
| FR-012 | FR-HAR-003 | add | Not merged into NFR-BUD-001: NFR-BUD-001 enforces the debate summary reserve, while this is the paid-run admission contract (null cap, refusal modes, unknown spend). Same word, different enforcement point. |
| FR-013 | FR-ANL-001 | merge-new | Merged into the new pipeline row: the single final decision, configured debate rounds and the portfolio manager as the only decision emitter are the same obligation as FR-ANL-001. |
| FR-014 | FR-HAR-001 | add | No Release row states a one-command archived measurement harness. |
| FR-015 | FR-OBS-005 | add | No Release row states telemetry selection integrity across repeated attempts. |
| FR-016 | FR-CAM-001 | add | No Release row states the optimisation campaign accept-or-revert loop. |
| NFR-001 | FR-OBS-001 | add | No Release row states event-level token accounting or the null-not-zero rule. Two derived rows (FR-OBS-003, FR-OBS-004) separate tool-round/component accounting and Single-Pass invocation settlement. |
| NFR-002 | FR-HAR-002 | add | No Release row states experiment freeze reproducibility. |
| NFR-003 | NFR-SEC-001 | merge | NFR-SEC-001 already states secret safety. Integrated: key-file permissions, no interactive prompt, no-sourcing wrapper and argv hygiene are recorded with their source files and tests on NFR-SEC-001. |
| NFR-004 | NFR-VER-001 | add | No Release row states that the delivered suite and independent audits are the verification of record. NFR-OFF-001 covers network isolation only. |
| NFR-005 | NFR-VER-002 | add | No Release row states the executed-verification (no simulated results) process obligation. |

## Personal acceptance-criterion destinations (64 rows)

Every original personal acceptance criterion is listed. "Placement" says
where the criterion lives in the destination row; none was dropped, and a
criterion expressed through a named test is traceable to that file.

| Personal AC | Destination | Placement | Test / evidence |
| --- | --- | --- | --- |
| AC-FR-001-01 | FR-ANL-001 | fit_criterion | `test/offline/test_analyst_execution.py` |
| AC-FR-001-02 | FR-ANL-001 | fit_criterion | `test/offline/test_debate_opening.py` |
| AC-FR-001-03 | FR-ANL-001 | fit_criterion | `test/offline/test_c3_regressions.py` |
| AC-FR-002-01 | FR-ANL-010 | fit_criterion | `test/offline/test_dataflows_config.py` |
| AC-FR-002-02 | FR-ANL-010 | fit_criterion + evidence | `test/offline/test_finnhub_news.py` |
| AC-FR-002-03 | FR-ANL-010 | fit_criterion | `test/offline/test_vendor_errors.py` |
| AC-FR-003-01 | FR-ANL-003 | fit_criterion | `test/offline/test_structured_analyst_output.py` |
| AC-FR-003-02 | FR-ANL-003 | fit_criterion | `test/offline/test_structured_agents.py` |
| AC-FR-003-03 | FR-ANL-003 | fit_criterion | `test/offline/test_structured_agents.py` |
| AC-FR-004-01 | FR-ANL-004 | fit_criterion | `test/offline/test_system_attribution.py` |
| AC-FR-004-02 | FR-ANL-004 | fit_criterion | `test/offline/test_system_attribution.py` |
| AC-FR-004-03 | FR-ANL-004 | fit_criterion | `test/offline/test_system_attribution.py` |
| AC-FR-005-01 | FR-ANL-005 | fit_criterion | `test/offline/test_cand01_single_pass_finalization.py` |
| AC-FR-005-02 | FR-ANL-005 | fit_criterion | `test/offline/test_cand01_single_pass_finalization.py` |
| AC-FR-005-03 | FR-ANL-005 | tests + evidence | `test/offline/test_final_remediation.py` |
| AC-FR-006-01 | FR-ANL-006 | fit_criterion | `test/offline/test_macro_batch.py` |
| AC-FR-006-02 | FR-ANL-006 | fit_criterion | `test/offline/test_macro_batch.py` |
| AC-FR-006-03 | FR-ANL-006 | fit_criterion | `test/offline/test_switch_consumption.py` |
| AC-FR-007-01 | NFR-PIT-001 | tests + evidence | `test/offline/test_news_lookahead.py` |
| AC-FR-007-02 | NFR-PIT-001 | tests | `test/offline/test_tool_date_enforcement.py` |
| AC-FR-007-03 | NFR-PIT-001 | tests | `test/offline/test_pit_notice.py` |
| AC-FR-008-01 | FR-ANL-008 | fit_criterion | `test/offline/test_finnhub_only_scope.py` |
| AC-FR-008-02 | FR-ANL-008 | fit_criterion | `test/offline/test_finnhub_only_scope.py` |
| AC-FR-008-03 | FR-ANL-008 | fit_criterion | `test/offline/test_finnhub_only_scope.py` |
| AC-FR-009-01 | FR-ANL-009 | fit_criterion | `test/offline/test_memory_isolation.py` |
| AC-FR-009-02 | FR-ANL-009 | fit_criterion | `test/offline/test_memory_isolation.py` |
| AC-FR-009-03 | FR-ANL-009 | fit_criterion | `test/offline/test_memory_isolation.py` |
| AC-FR-010-01 | FR-ANL-002 | fit_criterion | `test/offline/test_news_error_classification.py` |
| AC-FR-010-02 | FR-ANL-002 | fit_criterion | `test/offline/test_market_data_validator.py` |
| AC-FR-010-03 | FR-ANL-002 | tests + evidence | `test/offline/test_c3_regressions.py` |
| AC-FR-011-01 | FR-OBS-002 | fit_criterion | `test/offline/test_c3_final_freeze.py` |
| AC-FR-011-02 | FR-OBS-002 | fit_criterion | `test/offline/test_c3_final_freeze.py` |
| AC-FR-011-03 | FR-OBS-002 | fit_criterion | `test/offline/test_c3_final_freeze.py` |
| AC-FR-012-01 | FR-HAR-003 | fit_criterion | `test/offline/test_budget_guard.py` |
| AC-FR-012-02 | FR-HAR-003 | fit_criterion | `test/offline/test_c3_final_freeze.py` |
| AC-FR-012-03 | FR-HAR-003 | fit_criterion | `test/offline/test_budget_guard.py` |
| AC-FR-013-01 | FR-ANL-001 | fit_criterion (merged) | `test/offline/test_debate_opening.py` |
| AC-FR-013-02 | FR-ANL-001 | tests (merged) | `test/offline/test_structured_agents.py` |
| AC-FR-013-03 | FR-ANL-001 | tests (merged) | `test/offline/test_reporting.py` |
| AC-FR-014-01 | FR-HAR-001 | fit_criterion | `test/offline/test_run_token_benchmark_sh.py` |
| AC-FR-014-02 | FR-HAR-001 | fit_criterion | `test/offline/test_run_token_benchmark_sh.py` |
| AC-FR-014-03 | FR-HAR-001 | fit_criterion | `test/offline/test_token_benchmark.py` |
| AC-FR-015-01 | FR-OBS-005 | fit_criterion | `test/offline/test_token_benchmark.py` |
| AC-FR-015-02 | FR-OBS-005 | fit_criterion | `test/offline/test_token_benchmark.py` |
| AC-FR-015-03 | FR-OBS-005 | fit_criterion | `test/offline/test_token_benchmark.py` |
| AC-FR-016-01 | FR-CAM-001 | evidence (script) | `scripts/campaign_ablation_round.py` |
| AC-FR-016-02 | FR-CAM-001 | fit_criterion | `test/offline/test_ablation_switches.py` |
| AC-FR-016-03 | FR-CAM-001 | evidence (report) | `token_benchmarks/baseline_v2/notes.md` |
| AC-NFR-001-01 | FR-OBS-001 | fit_criterion | `test/offline/test_observability.py` |
| AC-NFR-001-02 | FR-OBS-001 | fit_criterion | `test/offline/test_observability.py` |
| AC-NFR-001-03 | FR-HAR-001 | fit_criterion (harness half) | `test/offline/test_token_benchmark.py` |
| AC-NFR-002-01 | FR-HAR-002 | fit_criterion | `test/offline/test_c3_final_freeze.py` |
| AC-NFR-002-02 | FR-HAR-002 | fit_criterion | `test/offline/test_cand01_batch_16run_v3_infra.py` |
| AC-NFR-002-03 | FR-HAR-002 | fit_criterion | `test/offline/test_c3_regressions.py` |
| AC-NFR-002-04 | FR-HAR-002 | evidence (known failure) | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/RUN_READINESS.md` |
| AC-NFR-003-01 | NFR-SEC-001 | tests (integrated) | `test/offline/test_api_key_env.py` |
| AC-NFR-003-02 | NFR-SEC-001 | tests (integrated) | `test/offline/test_api_key_env.py` |
| AC-NFR-003-03 | NFR-SEC-001 | tests (integrated) | `test/offline/test_run_token_benchmark_sh.py` |
| AC-NFR-004-01 | NFR-VER-001 | tests + evidence | `test/offline/test_final_remediation.py` |
| AC-NFR-004-02 | NFR-VER-001 | evidence (recorded counts) | `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` |
| AC-NFR-004-03 | NFR-VER-001 | evidence (audits) | `token_benchmarks/final_remediation_20261116/INDEPENDENT_AUDIT.md` |
| AC-NFR-005-01 | NFR-VER-002 | evidence (offline guards) | `test/conftest.py` |
| AC-NFR-005-02 | NFR-VER-002 | evidence (freeze verifier) | `scripts/c3_verify_final_freeze.py` |
| AC-NFR-005-03 | NFR-VER-002 | evidence (rehearsal paths) | `test/offline/test_c3_final_freeze.py` |

## D1 verification gaps preserved

- The historical D1 note recorded the merged suite as `NOT_RUN` while D2–D9
  conflicts existed. That state is superseded: the completed tree (`94755cf`)
  passes **5,132 tests / 3 skipped**, both validators, and `ruff check .`.
- Two V3 batch-16 infrastructure checks are absolute-path sensitive and fail
  outside their generating checkout. They are recorded as known failures in
  `FR-HAR-002` and are not hidden.
- The campaign numbers quoted from `token_benchmarks/**` are session
  self-reports; they are not re-derived here (`FR-CAM-001`).

## Release merge compatibility

| Scope | Enforcement / adaptation | Verification |
| --- | --- | --- |
| Existing core/WebUI plus imported FR-TRD/INV-TRD/NFR-TRD contracts; INV-WEB-001 | Schema 1.1 and `scripts/validate/validate_requirements.py` recognize all 58 original IDs; retain typed thresholds, source provenance and historical evidence scope | `test/offline/test_governance_scaffold.py`: original core recovery hash, unchanged WebUI hash, complete ID set, TRD thresholds and negative weakening/evidence-upgrade cases |
| INV-TRD-001/002/003 and NFR-TRD-001 | Imported implementation stays unchanged; `test/offline/trading/` root constants and test-package markers adapt only canonical collection | All 244 imported offline tests including AST gateway checks and requirement-to-function traceability; full combined offline regression |
| Permission/CI/layout compatibility | Retain V1 permissions and feature blocking gates, add safety ask guard; preserve native source layout and ignore local skills/design reference | Schema/permissions/registry validation, lint, exact source/requirement parity inspection; explicit local demo blocker retained |

Merge authorization comes from the current user conversation; it is not a new
product implementation or final acceptance decision.


## One-command startup

Scope/test contract `web-startup-20261120-v1`; current user approved the two
startup modes and README update. No core/CLI, dependency or permission change.

| Requirement / invariant | Implementation | Verification |
| --- | --- | --- |
| REQ-WEB-020/026; INV-WEB-001/013/015 | `cli.py`: mode/port/host validation, existing static serving, single worker and browser-after-startup; `launcher.py`: source/tool/dependency checks, build gating, readiness and owned-process supervision | `test/offline/test_web_launcher.py`: default no-build operation, exclusive flags, invalid/duplicate ports and non-loopback hosts, absent prerequisites, build failure/missing output, child exit/spawn failure/timeout/interruption, readiness ordering and owned-group cleanup |
| REQ-WEB-020/023/026; INV-WEB-003/013 | Existing `frontend/vite.config.ts`: loopback host, strict frontend port and validated backend-port proxy selected by the launcher | Frontend lint/types/build and 37 tests; real local dev/build smoke with explicit isolated-fixture marker verifies custom proxy, Vite client/HTML, session/CSRF, static files, occupied-port refusal and Ctrl+C listener cleanup |

Module paths above are relative to `src/tradingagents_web/`. Browser launch
ordering is covered by deterministic callback tests; smoke startup did not open
a browser or invoke a real model/data provider.


## Stage-based live activity

Scope: `web-activity-20261120-v1`, current user requests for TUI-like process
messages, prominent activity and automatically selected, clickable stage tabs.

| Contract | Presentation ownership | Verification |
| --- | --- | --- |
| REQ-WEB-002; INV-WEB-001/003/012/014 | `runtime/projector.py`: TUI labels, public text blocks, stage/speaker metadata and appended public research/risk arguments; existing redaction and event buffers unchanged | `test/offline/test_web_activity.py`: cumulative IDs, public/private blocks, producing-node attribution, empty risk defaults, history deltas, risk judgment and unknown recovered provenance; existing events/security/real graph suites |
| REQ-WEB-002/007; INV-WEB-014 | `frontend/src/stores/runStore.ts`, `utils/runActivity.ts`: optional metadata, actual progress and missing-state handling; no sequence/recovery or business-semantic change | `frontend/tests/run-activity.test.tsx`: event/snapshot preservation, terminal retention and no fabricated completion; existing store and analysis-flow tests |
| REQ-WEB-002/007/021; INV-WEB-012/014 | `frontend/src/components/RunActivity.tsx`, `pages/LiveRunPage.tsx`, `styles/index.css`: top-level activity, auto/manual/keyboard tabs, per-stage reports, message filters, expand/follow controls and separate complete-report view | Same component suite; `frontend/e2e/run.spec.ts`: real SSE stage switching, report toggle/reload, cancellation and failed tool activity recovery; existing responsive Chromium suite |

Browser evidence is Chromium only, not completion of the entire REQ-WEB-021
browser matrix. No live provider execution is part of this presentation check.


## Report table containment

REQ-WEB-009/021, ADR-003, INV-WEB-001/012/014 map to the existing shared
`frontend/src/components/Markdown.tsx` and scoped `styles/index.css`. Tables
retain native semantics within a keyboard-focusable horizontal scroll region;
Markdown cells override inherited nowrap, fixed height and last-column sizing.
`src/tradingagents_web/frontend/tests/markdown-sanitize.test.tsx` checks all-column/content preservation and
unsafe table content. `e2e/report-tables.spec.ts` checks actual browser geometry,
contents-sidebar separation, page width, wrapping and keyboard scrolling at
desktop, portrait and landscape sizes. No core or history-list layout changes.


## English/Chinese interface

Scope: `web-i18n-20261120-v1`; REQ-WEB-014/021 and ADR-003.

| Contract | Ownership | Verification |
| --- | --- | --- |
| UI-language switching, persistence and fallback | `frontend/src/i18n/index.ts`, `ui.ts`, existing en/zh JSON resources; `components/LanguageSwitch.tsx`, `app/AppShell.tsx` | `src/tradingagents_web/frontend/tests/localization.test.tsx`: matching variables/catalogues/static lookups and UI props, no hardcoded JSX copy, normalized unsupported locales, optional storage, document language, reactive stage labels, source-content preservation and plural/format behavior; existing catalogue parity tests |
| Whole workspace presentation, preserved API/domain values | Existing app, pages, components and date utilities; top-bar/settings/wizard controls, scoped language-button styles | `e2e/localization.spec.ts`: route labels and persisted reload, Chinese narrow layouts, modal control, wizard validation and in-place values, original models/output language submitted, terminal recovery and active-run language changes with one SSE connection; previous English browser flows |
| INV-WEB-001/007/012/014 | Display-only lookup; original form values, stores, report bodies, tool text, ratings, identifiers and stream lifecycle retained | Same locale suite explicitly checks REVIEW versus Hold, opaque identifiers, custom titles/windows, source Markdown and tool messages; prior offline/core/WebUI suites |

Unknown provider/runtime diagnostics and source content retain their original
text. Proper names, symbols, shortcuts, the CLEAR confirmation token and REVIEW
remain literal identities. Browser execution evidence is Chromium only.

## Per-analysis debate settings

Scope: `web-debate-settings-20261120-v1`; REQ-WEB-001/003/013/014, FR-DDT-004;
ADR-001-choice, ADR-003-frontend-stack and ADR-007-run-controls addenda.

| Contract | Ownership | Verification |
| --- | --- | --- |
| Strict public settings, authoritative core validation, environment precedence and legacy depth | `models/requests.py`, `api/config.py`, `api/runs.py`, `runtime/debate_policy.py` | `test/offline/test_web_debate_config.py`: full/partial/default/legacy inputs, independent risk caps, environment locks, strict types/ranges/reserves, NaN/Inf, internal/unknown keys, no rejected-value echo and unchanged defaults |
| Effective snapshots and historical settings without fabricated legacy values | `runtime/coordinator.py`, `runtime/artifacts_writer.py`, `artifacts/index.py`, frontend report/live components | Same offline suite: actual runner inputs, snapshots and saved history; malformed/missing historical policy; `e2e/debate-settings.spec.ts`: real API, completion, reload and history parity |
| Custom-policy checkpoint isolation, preserved default identity | `runtime/analysis_graph.py`, existing `runtime/graph_runner.py` | Same offline suite: default core-signature equality and each threshold/budget/mode difference; `test_web_analysis_flow.py`: real offline core graph with default and custom fixed policies |
| Bilingual controls, independent risk rounds, safe drafts, validation and canonical payload | `frontend/src/components/DebateSettings.tsx`, `utils/debateSettings.ts`, existing wizard/client/catalogues | `src/tradingagents_web/frontend/tests/debate-settings.test.tsx`, `src/tradingagents_web/frontend/tests/analysis-flow.test.tsx`: public projection, locks/draft priority, presets/risk independence, negative feedback, translations and payload; Chromium suite: real run plus negative Chinese validation and mobile locked controls |

INV-WEB-001/003/006/009/010/012/014 remain covered by these checks and the full
offline/frontend/browser regression. Core, CLI and simulated trading have no
working-tree changes. This mapping records implementation evidence, not a new
human acceptance decision or live-provider result.


## TUI capability parity

Scope: web-tui-parity-20261120-v1; REQ-WEB-001/002/006/007/013/014/021,
INV-WEB-001/003/006/007/012/014; ADR-001-choice/003-frontend-stack refinements.

| Contract | Ownership | Verification |
| --- | --- | --- |
| Individual observed roles, report finalizers and selected analyst timing | runtime/projector.py, graph_runner.py; existing core timing helper reused | test_web_tui_parity.py: repeated turns, nested-callback exclusion, tool-request versus final-report boundary, injected exact clock, partial/restored participation; test_web_analysis_flow.py: actual core graph through snapshots, exact counts and analyst time |
| Timing events retained through completion/reconnect and correctly grouped risk roles | runtime/coordinator.py; frontend run store, activity component and grouping utility | Same offline suite: terminal event without times preserves prior samples; tests/run-activity.test.tsx and e2e/tui-parity.spec.ts: stage isolation, recorded roles, counts, timings and reload; run.spec.ts: actual SSE timing event |
| Bounded public OpenRouter discovery with cached/custom fallback | new runtime/model_catalog.py, app.py, api/config.py; wizard/client refresh | Offline tests: sort/filter/deduplicate/cache/refresh, malformed/oversize/HTTP/redirect/timeout failure, stale fallback and no error-value echo/auth forwarding; analysis-flow.test.tsx: manual-ID preservation and failed refresh; tui-parity.spec.ts: browser refresh/manual entry/mobile |
| CLI-equivalent positive integer calendar spacing | existing BacktestPage.tsx input/datalist; API/core unchanged | Existing backtest validation positives/negatives; e2e/backtest.spec.ts submits a nonpreset five-day interval through the real fixture API |

Language options, credential/preference ownership, core/CLI and simulated trading
remain unchanged. API keys are never needed for public-model discovery. No live
provider evidence or final human acceptance is claimed.


## Simulated trading Web composition

Scope: web-simulation-20261121-v1. Existing FR-TRD-001..006,
INV-TRD-001..003, NFR-TRD-001 and REQ-WEB-001/006/007/013/014/021/023;
ADR-001-simulated-trading-system.md plus the Web ADR refinements apply.

| Contract | Web ownership | Final verification coverage |
| --- | --- | --- |
| Strict Decimal inputs, issued human approval, deterministic sizing and engine-only fills | models/simulation_requests.py, api/simulation.py, runtime/simulation.py | test_web_simulation.py: actual pipeline outcomes, approve/deny/expiry/quote/version/epoch, idempotency/restart and no quantity/config/authority overrides; unchanged trading invariants |
| Fixed account namespace, audit retention/verification and fail-closed recovery | runtime/simulation.py; inherited core store/audit | Same suite: reset, tampered state/audit, post-fill save failure, audit visibility, symlink escape, owner conflict, no restored pending authority |
| Serial isolated walk-forward with matching resume | runtime/simulation_jobs.py; coordinator.external_run; existing core BacktestRunner/providers/clocks | Same suite: offline BUY/SELL, pending orders unexecuted, no-action and skipped behavior, portfolio/cursor/account isolation, identical-parameter resume, injected research/quote boundaries and active-slot conflict |
| Account/decision/approval/backtest/audit controls with honest states | new frontend api/simulationClient.ts, SimulationPage.tsx, pages/Simulation components; existing app/nav/styles/catalogues | tests/simulation.test.tsx: validation, typed reset/epoch, canonical/idempotent requests, human reason/name, expired requests and inert audit; e2e/simulation.spec.ts: actual core account/approval/audit/reset, walk-forward/resume/reload, negative submissions and mobile themes |
| Package and platform compatibility | pyproject package finder includes existing trading/safety; app defers POSIX-only simulation composition on Windows | Static/package import checks and previous full offline/frontend/browser regression; Windows runtime itself is not claimed as tested |

The user requested one final verification phase. Until that phase runs these
rows describe coverage, not passing results or final human acceptance.


## Frontend information simplification

web-ui-simplify-20261121-v1 changes presentation only. Existing IDs, domain
semantics, API contracts and approval status remain unchanged.

| Existing coverage | Presentation enforcement | Verification |
| --- | --- | --- |
| REQ-WEB-002/010/021 | Overview latest/recent research; concise history; no duplicate sidebar summary or decorative counts | visual-parity.spec.ts simplified workspace and external-task routing cases; existing history/locale/responsive cases |
| REQ-WEB-001/006/007/014 | Same analysis inputs/stage tabs/errors; counters and policy detail disclosed on demand | analysis-flow, run-activity, localization unit tests; run/debate/tui-parity browser cases |
| REQ-WEB-008/011, NFR-CMP-001/002/003 | Audit verdict remains explicit; one backtest score table; preset comparison under help with identity/rubric details | audit-comparison unit/browser tests; backtest and report-table browser cases |
| FR-TRD-001..006, INV-TRD-001..003 | Core amounts/holdings, approval/expiry/error/reset confirmations remain; extra account/attempt/rule details collapsed; completed runs have no resume action | simulation unit/browser cases, including no completed-resume and reload assertions; existing offline core/API tests |

No runtime provider evidence or new requirement verification status is inferred
from this UI adjustment. Closing check outcomes belong to the evaluation logbook.


## Backtest failure diagnostics

Existing REQ-WEB-006/011/013, INV-WEB-003/014 and ADR-007-run-controls.md are
implemented by errors.run_failure, RunCoordinator._execute_backtest and the
existing backtest failure banner. test_web_backtest.py::
test_backtest_failures_are_logged_safely_and_release_the_slot covers internal,
configuration/missing-key, authentication, provider rate limit and Yahoo rate
limit exceptions through the actual coordinator/API, including secret/path
non-disclosure, preserved live memory and failure recovery. backtest.spec.ts
covers the categorized reference in English/Chinese without a misleading empty
card. No requirement status or actual-provider success is inferred.


## Editable Web model defaults

web-model-defaults-20261121-v1 refines existing REQ-WEB-001/003/005/011/013 and
INV-WEB-001/003/006/014 under ADR-001-choice.md. No requirement IDs or statuses
change. config.py exposes editable model provenance and preserved other locks;
runs.py applies per-analysis selection after policy enforcement and scopes
endpoint/thinking fields to their provider. backtests.py copies current server
defaults. NewAnalysisPage preselects configured values, preserves matching draft
choices, resets stale model drafts and clears cross-provider fields.

Evidence: test_web_analysis_flow.py::
test_server_defaults_and_other_locks_survive_omitted_model_inputs,
test_explicit_analysis_models_override_environment_defaults_without_cross_provider_leak,
test_provider_switch_rejects_inherited_model_ids,
test_provider_switch_can_use_its_explicit_endpoint_and_thinking;
test_web_backtest.py::test_backtests_keep_environment_model_defaults;
analysis-flow.test.tsx configured-default and draft-baseline cases;
tui-parity.spec.ts environment-default preselection/selection/submission case.
Existing budget/round, credential redaction, invalid-input and recovery tests
remain required. No live-provider call or new human acceptance is inferred.


## Per-date backtest progress

web-backtest-progress-20261121-v1 uses REQ-WEB-006/007/011/021/026 and
INV-WEB-003/009/014 under ADR-007-run-controls.md. Generic observer ownership is
core backtest.py; Web presentation ownership is runtime/backtest_progress.py;
existing runner/coordinator/API bridge notifications to bounded GET snapshots.
BacktestProgress.tsx and the existing page/client own in-place presentation.
No requirement IDs, statuses, business acceptance, model or safety rule changes.

Evidence: test_backtest.py::
test_backtest_observer_reports_real_cells_resume_and_settlement,
test_observer_failure_cannot_change_execution_and_is_removed_after_exit,
test_observers_are_nested_and_thread_context_isolated;
test_web_backtest.py::
test_real_core_progress_is_visible_before_completion_and_while_settling,
test_progress_rejects_invalid_transitions_and_bounds_snapshots;
backtest-progress.test.tsx observed/settlement, paging and legacy cases;
backtest.spec.ts per-date progress/refresh/settlement/mobile/bilingual case.
Existing core signature, CLI, memory, failure, slot and negative request tests
remain required. Optional observation adds no UI dependency to the core.

## PR #5 integration maintenance

ADR-012 preserves existing requirements rather than defining new Gate or budget
policies. NFR-AUD-001 / NFR-BUD-001 map to `src/tradingagents/agents/utils/structured.py`,
`src/tradingagents/graph/setup.py`, the three `src/tradingagents/graph/*_tool_governance.py` wrap-ups and
`test/offline/test_merge_execution_boundaries.py` (real SQLite evidence retention and
ledger events); `test/offline/test_structured_raw_usage.py` and
`test/offline/test_durable_usage_ledger.py` retain raw usage/admission assertions.
NFR-BC-001 maps to `src/tradingagents/graph/run_identity.py` v2 and the effective debate policy,
`test/offline/test_checkpoint_config_compat.py` and the new integration tests.
NFR-PIT-001 / NFR-OFF-001 map to the combined cache/no-data tests, including the
summer/winter UTC/Hong Kong/New York matrix without process-global tzset.
FR-DQG-006 maps to the retained Gate/Confidence Sanitizer/evaluator edges and
trusted-report transformations, with the existing confidence/output-guard tests.
Verification is offline only; complete Windows collection remains blocked by
`src/trading/audit.py` importing POSIX `fcntl` (see evaluation logbook).


Local release/WebUI integration, 2026-11-21 (release 9a08e08, WebUI 977a22b):
REQ-WEB-002/005, INV-WEB-003/010 and NFR-OFF-001 are covered by
`test/offline/test_web_analysis_flow.py::test_real_market_tool_rate_limit_degrades_without_llm_failure`
(real router and graph, bounded offline vendor failure, unavailable tool data,
blocked Hold, memory and checkpoint cleanup).
REQ-WEB-013 / INV-WEB-010 / NFR-BC-001 retain the eleven custom-policy isolation
cases in `test/offline/test_web_debate_config.py` against the v2 core digest and
existing Web suffix. The Yahoo backend floor assertion uses the migrated repo
root in `test/offline/test_yahoo_error_classifier.py`. No IDs or status change.


PR #7 CI repair, web-ci-repair-20261121-v1: REQ-WEB-026 / INV-WEB-001 /
NFR-OFF-001 retain optional Web runtime installation in verification jobs.
`test/offline/test_ci_gates.py::test_web_verification_installs_optional_web_runtime`
checks that contract and the lean core smoke install. Live relocation is covered
by test_trading_live_relocation_retains_live_identity,
test_relocated_live_content_changes_still_require_evidence and the negative
test_duplicate_old_and_new_live_paths_are_rejected. No approval/semantic/security
policy or runtime behavior is changed by this bounded correction.


web-ci-types-security-20261121-v1 (ADR-012-error-handling-merge-integration.md):
NFR-BC-001 / INV-1 preserve original business acceptance while module annotations
express actual optional/union/callback contracts. FR-TRD-* / INV-TRD-001/002
safety/portfolio/audit edits are annotations only and retain the complete trading
suite. Full mypy and Bandit scan the same complete src tree with unchanged rules.

- NFR-PIT-001 / NFR-OFF-001 / INV-8: test_reddit_fallback.py covers UTF-8/UTF-16
  DTD/entity refusal, normal namespaced/escaped Atom data, forbidden initial
  URL schemes/authorities, off-origin/downgrade redirects and retained headers/
  timeouts; test_stocktwits_resilience.py verifies unsafe schemes are unavailable,
  never absence, before I/O.
- NFR-BUD-001 / INV-7: test_durable_usage_ledger.py::
  test_scope_sql_cannot_admit_other_runs_or_phases and
  test_hostile_run_id_in_admission_preserves_another_runs_capacity preserve SQL
  identity/phase boundaries and reservations with hostile parameter values.
- FR-DDT-005 / INV-5 / INV-13: test_debate_conflicts.py::
  test_conflict_id_keeps_legacy_bytes_without_a_security_hash and
  test_state_adapter_returns_conflicts_notes_and_denials preserve IDs and
  invalid-evidence denial/retention through the actual state adapter.
- NFR-BC-001: test_structured_agent_prompts.py::
  test_market_prompt_literal_content_remains_release_identical pins the release
  literal SHA-256 while retaining the language-instruction call.

No requirement ID/status or invariant threshold is changed by this maintenance.


web-ci-policy-simple-20261121-v1 (ADR-012-error-handling-merge-integration.md):
REQ-WEB-026 retains executable installation/CI checks with GitHub-owned human
merge review. No runtime acceptance criterion or invariant threshold changes.
`test/offline/test_ci_gates.py` covers:

- `test_approval_command_delegates_to_github_without_claiming_a_review`: no
  token, Git chronology or fabricated approval required/issued by the command.
- `test_workflow_retains_blocking_checks_without_duplicate_review_logic`: AI
  logging and all aggregate prerequisites remain, no continue-on-error added.
- `test_unconfigured_semantic_evaluation_is_explicitly_unrun` and
  `test_semantic_command_does_not_report_unrun_evaluation_as_pass`: absent/empty
  policy returns NOT RUN without evaluator execution or a quality-pass claim.
- `test_semantic_evaluation_is_not_required_without_model_changes`: unrelated
  changes do not read a policy or execute evaluation.
- `test_partially_configured_or_invalid_semantic_policy_still_blocks`,
  `test_semantic_replay_applies_fixed_dataset_and_threshold` and
  `test_configured_semantic_evaluation_retains_failure_boundaries`: invalid
  setup, changed fixtures, evaluator failure/missing report, wrong dataset,
  nonfinite metrics and failed thresholds cannot become optional success.

Obsolete tests for the retired custom review-marker/chronology protocol are
replaced under explicit human policy-change authorization. Existing schema,
permission, structure, AI-log, transcript and dependency checks are retained.


ci-report-clock-20261121-v1: NFR-DET-001 / FR-DQG-006 / NFR-AUD-001,
ADR-011-deterministic-degraded-confidence-cap.md. The existing
`test/offline/test_confidence_cap_runtime.py::TestPublicReportAndMemory::test_report_export_idempotent`
now fixes the report clock with test-local monkeypatch, asserts the exact
Generated header and retains full report and confidence-cap audit equality.
This controls the known volatile input instead of removing content assertions.
Production timestamps, confidence handling and public writer contracts remain
unchanged; no new requirement, invariant or status is introduced.

## Prior-test approval gate — test-approval-v1

| Requirement / invariant | Design | Enforcer | Tests | Monitor / fallback |
| --- | --- | --- | --- | --- |
| NFR-GOV-001 / INV-28 | 029-test-plan-approval.md; blueprint prior-test section | test/ci_gates.py; CI review-and-log | test/offline/test_ci_gates.py prior_test_approval cases | Safe CLI decision + bound review URL/commit; failure blocks aggregate. Hosted execution NOT_RUN until publication. |

The human owner approved this plan and its positive/negative cases on 2026-11-24
in the current conversation. That approval is not a fabricated GitHub review.


## submission-fix-v1

| Obligation | Design / enforcing component | Verification / monitor |
| --- | --- | --- |
| NFR-GOV-002 / INV-29 | ADR-030; test/ci_gates.py; test/semantic_evaluator.py; fixed test/semantic_cases.json; base-owned semantic workflow | test/offline/test_ci_gates.py semantic failures and source binding; test/offline/test_semantic_evaluator.py quality/safety/provenance violations. Runtime monitor: CI exit status and explicit failing metric; real observations remain required. |
| NFR-SEC-001 / REQ-WEB-026 | ADR-031; explicitly rooted native Read/Edit permission paths | test_native_permission_file_paths_have_an_explicit_root_binding and four native role probes using local scripted transport. Outside, secret and protected-write denials remain effective. |
| NFR-DET-001 | test_undated_tools_as_of.py transport test, fixed 2026-09-02 clock | Existing GDELT failure assertion remains; no production archive-rule change. |
| Existing AI context obligations | ADR-004 application-context addendum; existing agent factories, structured.py, graph state, memory and output guards | Source mapping and actual/target design split; automatic tokenizer/compaction is explicitly not implemented. Semantic source fingerprint links candidate code, prompts and runtime config. |

No original requirement threshold, frozen protocol or experiment result is
rewritten. Report/review/submission-validator/transcript work is excluded.

## Governance directory consolidation

Scope: governance-layout-v1, approved in the controlling conversation.

| Existing obligation | Ownership | Verification and fallback |
| --- | --- | --- |
| REQ-WEB-026: installable, verifiable repository | scripts/validate/validate_requirements.py; the three required code-governance documents | TestRequiredArtifactPresence checks exact governance inventory, a valid artifact checkout and missing/empty failures for each required document. Missing evidence blocks; do not suppress the failure. |
| NFR-SEC-001: role/path consistency | .opencode/permissions.jsonc; docs/architecture/permission-model.md | TestActivePermissionConsistency checks the actual policy, readable editable Build paths, all-role document reads, unknown-action denial, secret/external/protected denials and read-only roles. Native verification remains ADR-031's bounded evidence. |
| NFR-GOV-001 / NFR-GOV-002 | Unchanged prior-test approval and semantic checker; verification-constraints.md | Existing approval/semantic regression cases remain. The historical first-install allowlist is unchanged and does not require a deleted document to exist. No review or quality threshold is relaxed. |

Artifact inventories no longer require inactive supporting proposals. Product
source, permission actions, original registry criteria and raw sessions are
unchanged. Verification outcomes are recorded after execution in the logbook.
