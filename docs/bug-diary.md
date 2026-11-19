# Bug Diary — TradingAgents CAND-01 / Token Observability

Scope: defects found in the shipped branch `50b2ca3` history (`rc1` `9948bf8`
.. `50b2ca3`), not upstream `rc1` bugs. Each entry names the commit(s) that
introduced or fixed it, the regression test that now pins it, and the honest
verification state: `FIXED` (test exists and passes offline), `FIXED — NOT
VERIFIED LIVE` (no paid rerun after the fix), or `PROCESS-CLOSED`.

Dates are commit dates unless stated. Where only a commit range proves
discovery, the range is given instead of an invented date. Every status below is
AI-assessed from the committed evidence; human confirmation is
`PENDING_HUMAN_CONFIRMATION`.

---

## BUG-001 — PF-01: company-news source classified before the tool loop

| Field | Value |
| --- | --- |
| **Discovered** | commit range `9948bf8..7832a90` (2026-11-12..2026-11-14); exact discovery date `NOT_VERIFIED` |
| **Symptom** | Single-pass News Analyst reported "Stance: Unknown" / `DATA_UNAVAILABLE` even when `get_news` had returned real Finnhub articles. |
| **Impact** | Every single-pass news report could be forced unavailable; the news factor of the 2×2 would have been measured on a dead feed. |
| **Root cause** | The classifier ran at node entry, before any `get_news` call, so it always saw an empty tool history. RC1's two-call path was unaffected because `ToolNode` had already written the `ToolMessage` into state before the finalising visit. |
| **Fix commits** | `7832a90` (2026-11-14): `finalize_single_pass` gains opt-in `accept=` and `executed=` hooks; the news node classifies over the full executed history and re-derives status for prose fallbacks. |
| **Regression test** | `tests/test_cand01_news_positive_path.py` — `RealCompanyNewsTest`, `MultipleRealArticlesTest`, `VendorShapeCompatibilityTest`, `NewsFailurePathTest`, `GraphHistoryIntegrityTest`, `ProseFallbackTest`, `StanceInvariantsTest` (42 tests, including P1–P3 positive, N1–N6 negative, G1–G6 integrity). |
| **Status** | `FIXED` — V3 shows 15 valid runs (15 of 16 Run IDs; R12 invalid) with 8.8–10.6 kB Finnhub blocks and 0 GDELT calls. |

## BUG-002 — F1: hidden `trade_date` not injected; terminal blank report

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-13, from the independent audit of the `e38ac3e..e33ab2c` range (fix commit date; exact audit time `NOT_VERIFIED`) |
| **Symptom** | `run_data_tools` called `tool.invoke(args)` without injecting the `InjectedState("trade_date")` value declared by every data tool, so window-clamping tools could read past the run date. Exhausting `SINGLE_PASS_MAX_ROUNDS`, or a round where every tool failed, ended the node with an empty `free_text_block` and a blank report. |
| **Impact** | PIT violation (future data reachable) and a report-less run; both invalidate the experiment cell. |
| **Root cause** | The single-pass runner bypassed `ToolNode`, re-implementing argument injection without the hidden state field; the fallback path invoked the finalizer with `""`. |
| **Fix commits** | `e33ab2c` (2026-11-13): inject state, issue one plain free-text call when rounds are spent or all tools failed, return prose as-is. |
| **Regression test** | `tests/test_cand01_single_pass_finalization.py` `test_hidden_trade_date_parameter_is_injected_from_state`, `test_missing_trade_date_leaves_the_tool_default`, `test_model_omitting_trade_date_gets_the_state_value`, `test_model_supplying_a_future_date_cannot_move_the_window`, `test_every_tool_failing_still_yields_a_report`, `test_empty_render_falls_back_rather_than_returning_blank`. |
| **Status** | `FIXED` |

## BUG-003 — F3: executed tool results were not written back to `MessagesState`

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-14, R3 audit finding F3(b), reproduced in a compiled graph (fix commit date; exact audit time `NOT_VERIFIED`) |
| **Symptom** | The single-pass node wrote only assistant turns back to state. The `ToolMessage`s it executed lived in a local history, so every data-tool call was left dangling; `should_continue_*` routed back to the tool node, the tool ran a second time, and the run died with `GraphRecursionError` for k≥1. |
| **Impact** | Multi-round single-pass runs crashed; k=0 was unaffected, so unit tests that only checked one round missed it. |
| **Root cause** | `_terminal_messages` rebuilt state from assistant turns only and dropped the executed results. |
| **Fix commit** | `ebe81e3` (2026-11-14): rebuild the sequence from assistant turns plus executed results, pair each call with its `ToolMessage`, close on an assistant turn with no pending call; add a real compiled-graph test. |
| **Regression test** | `tests/test_cand01_single_pass_finalization.py` `test_tool_results_are_returned_to_the_graph_so_the_loop_continues`, `CompiledGraphLoopTest` (k=0/1/2, vendor-call counting), `test_returned_state_has_no_dangling_tool_call`. |
| **Status** | `FIXED` |

## BUG-004 — F2: a mixed schema+data turn was treated as terminal

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-14, R3b-F2 and R3c-F1 (fix commits `ec629dd`, `72ae0f8`) |
| **Symptom** | A model turn that emitted the report schema together with a data-tool call was treated as terminal, silently dropping the requested evidence. A second schema call in one turn was also mis-detected as "mixed", dropping a valid report. |
| **Impact** | Evidence loss and a dangling schema call id in shared state; a later clean schema turn could be ignored, so the run fell back to prose. |
| **Root cause** | "Mixed" was `len(all_calls) > 1`; data calls were not executed before accepting the schema; the unexecuted schema call stayed on the assistant turn. |
| **Fix commits** | `ec629dd` (2026-11-14): run data calls first, accept schema only on a turn with no data call, strip the co-emitted schema call; correct the `ToolNode` reference. `72ae0f8` (2026-11-14): mixed requires a non-schema call beside the schema. |
| **Regression test** | `tests/test_cand01_single_pass_finalization.py` `MixedTurnTest` (`test_mixed_turn_runs_the_data_tool_before_finalising`, `test_mixed_turn_leaves_no_dangling_call`, `test_mixed_turn_then_budget_exhaustion_still_reports`), `test_two_schema_calls_still_produce_the_structured_report`; `tests/test_final_remediation.py::TestAuditAFollowUps::test_a_mixed_schema_plus_data_turn_leaves_no_dangling_call`. |
| **Status** | `FIXED` |

## BUG-005 — U-1: `agrees_with_telemetry` was computed but never consumed

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-15, C3 round-5 audit; listed open in `C3_HALT_REPORT_20261115.md` §4 |
| **Symptom** | A run whose spend replay disagreed with its own telemetry totals still reported `valid=True` and counted as a sample. |
| **Impact** | Corrupt usage data could enter the measured mean; the "valid" label was not load-bearing. |
| **Root cause** | `_budget_summary` produced the flag; no consumer read it. |
| **Fix commit** | `6057b52` (2026-11-16 00:53): four-state verdict `VALID`/`MISSING`/`INCOMPLETE`/`MISMATCH`; only `VALID` produces a sample; `MISSING` publishes `total_tokens: null`, never `0`; `replay_conclusive` distinguishes legacy data. |
| **Regression test** | `tests/test_c3_final_freeze.py::TestUsageVerdict` (13 tests); mutations M1 (stop consuming) and M2 (publish 0) caught. |
| **Status** | `FIXED` |

## BUG-006 — U-2: a null cap was indistinguishable from a broken budget file

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-15, C3 round-5 audit; listed open in `C3_HALT_REPORT_20261115.md` §4 |
| **Symptom** | An explicit uncapped round, a missing protocol file, invalid JSON and a block with no cap all produced `max_total_tokens=None`; three of the four should have been refusals. |
| **Impact** | A misconfigured or unreadable budget could run as "uncapped" and spend. |
| **Root cause** | The loader collapsed every absent/unreadable state to `None`. |
| **Fix commit** | `6057b52` (2026-11-16): `budget_mode = "uncapped_authorized"` required for a null cap; seven distinct refusal states; no artificial ceiling reintroduced. |
| **Regression test** | `tests/test_c3_final_freeze.py::TestBudgetContract` (20 cases); mutation M3 caught. |
| **Status** | `FIXED` |

## BUG-007 — Reflector call outside every agent scope (unattributed)

| Field | Value |
| --- | --- |
| **Discovered** | In the V2 paid batch after `15270b1` (2026-11-16 early morning); R06 (`AAPL/B`) was invalid with 1 of 21 calls at `global_sequence=0` unattributed |
| **Symptom** | The pre-graph `Reflector.reflect_on_final_decision()` provider call had no attribution; `run_totals` did not include it and the run was `INVALID`. |
| **Impact** | One entire paid attempt (190,468 tokens) was void; any pending memory entry would repeat the loss. |
| **Root cause** | `propagate()` calls `_resolve_pending_entries()` before `graph.invoke()`; `attrib_agent_node` installs scope only inside graph nodes, so the reflector invocation was unscoped. |
| **Fix commit** | `afa0fc6` (2026-11-16 12:32): `AttributionContext` (`ContextVar`) with `agent_scoped`, `system_component_scoped`, and `none`; reflector wraps only `invoke` as `system:pre_graph_reflector`; telemetry schema 2; `none` still invalidates. |
| **Regression test** | `tests/test_system_attribution.py` (13 tests): `TestReflectorAttribution`, `TestAttributionIntegrityGuards`, `TestHarnessAcceptsSystemAttribution`. |
| **Status** | `FIXED` — V3 reports 16/16 `attribution_complete=true`. |

## BUG-008 — Cross-run memory pollution (shared mutable log)

| Field | Value |
| --- | --- |
| **Discovered** | In the V2 paid batch after `15270b1` (2026-11-16 early morning): R05's pending decision changed R06's pre-graph reflector prompt and token cost |
| **Symptom** | All runs shared `~/.tradingagents/memory/trading_memory.md`; one run's pending entry triggered the next run's reflector before the graph. |
| **Impact** | Run order changed prompts and token totals; cells were not independent. |
| **Root cause** | A single mutable memory log was reused across runs; no per-run copy, no snapshot verification. |
| **Fix commit** | `afa0fc6` (2026-11-16): one immutable baseline (`baseline_v3.md`, empty, sha256 `e3b0c442…b855`), per-run copy under `attempt_MM/memory/`, pre-run hash/containment checks, post-run `memory_state.json`, `baseline_unchanged=False` → `INVALID`. |
| **Regression test** | `tests/test_memory_isolation.py` (21 tests): `TestSnapshotAndCopy`, `TestValidationFailsClosed`, `TestConfigAndReflector`, `TestHarnessRecordsMemory`, `TestStrippedSpecCannotRun`, `TestMemoryEvidenceIsRequired`, `TestBaselineProvenance`. |
| **Status** | `FIXED` — V3: 18/18 attempts `baseline_unchanged=True`. |

## BUG-009 — R12 provider 400 on the structured-fallback retry

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-16, V3 batch run 13:07–14:44; R12 (`JPM/CC`) attempt a01 and a02 both failed at the 5th request |
| **Symptom** | `400 invalid_request_error: An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'` |
| **Impact** | 2 failed attempts, 31,176 + 31,390 = 62,566 tokens; JPM/CC cell missing (15/16 valid). |
| **Root cause** | `finalize_single_pass` appended the schema-carrying assistant turn before validating it; on validation failure the fallback replayed that turn with no `ToolMessage`. It also called bare `llm` instead of `prompt | llm`, dropping the analyst system prompt. |
| **Fix commit** | `e0ea1b0` (2026-11-16 16:17), follow-up `e9eed04` (audit closures). `_free_text_retry` drops a trailing tool-call-only assistant turn, keeps `prompt | llm`, sanitises the result; used at all fallback exits. |
| **Regression test** | `tests/test_final_remediation.py::TestR12Fallback` (5 tests: no dangling id, system prompt kept, valid pairing unchanged, second failure raised, normal output unchanged). |
| **Status** | `FIXED — NOT VERIFIED LIVE` (pre-fix probe 4/4, mutation caught; no paid rerun) |

## BUG-010 — DSML markup leaked into `market_report`

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-16, V3 batch run 13:07–14:44; R07 (`AAPL/CC`) and R14 (`XOM/CC`) |
| **Symptom** | `market_report` contained raw `<｜｜DSML｜｜ calls>` text: R07 1,922 chars (analysis inside a `summary` parameter), R14 346 chars (one snapshot call, no analysis); downstream cited no SMA/MACD/RSI. |
| **Impact** | Two valid single-pass runs produced degraded reports, biasing the CC arm's apparent token win. |
| **Root cause** | Schema validation failed, the fallback had no tools bound, the model wrote the tool call as text, and the old code stored that text as the report. |
| **Fix commit** | `e0ea1b0` (2026-11-16): `sanitize_analyst_text` recovers analysis-bearing parameters, keeps prose before the first marker, else writes an explicit `REPORT UNAVAILABLE`; applied at the direct prose exit, both `structured_llm is None` exits and the fallback retry; markup recorded as `markup_sanitized`, counted separately. |
| **Regression test** | `tests/test_final_remediation.py::TestDsmlSanitizer` (4 tests) and `TestAuditAFollowUps` (5 tests, including `test_analysis_before_markup_is_kept`); `TestMarkupTelemetry::test_one_markup_fallback_is_one_attempt_with_its_own_counter`. |
| **Status** | `FIXED — NOT VERIFIED LIVE` (R07/R14 fixtures; no paid rerun) |

## BUG-011 — `tool_rounds` was always 0 on single-pass runs

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-16, V3 analysis phase 15:11–15:20; all single-pass runs showed 0 rounds despite 23–35 tool calls |
| **Symptom** | `tool_rounds=0` for C0/CC, making per-arm tool-round comparison impossible. |
| **Impact** | One of the four pre-registered secondary metrics was missing for half the design. |
| **Root cause** | Rounds were emitted only by the graph `ToolNode` hook (`attrib_tool_round`); single-pass executes tools in-process in `run_data_tools` and never passes through `ToolNode`. An instrumentation gap, not "zero rounds". |
| **Fix commit** | `e0ea1b0` (2026-11-16): `observability.record_tool_round(...)` reads the current agent scope; `run_data_tools._run` records one round per non-empty batch, 0 for an empty batch, `status="error"` when all tools failed; no double counting with `ToolNode`. |
| **Regression test** | `tests/test_final_remediation.py::TestToolRounds` (5 tests: one turn/2 calls = 1 round, two rounds = 2, no call = 0, failure still 1, rounds reach the payload). |
| **Status** | `FIXED` for new runs; historical V3 `tool_rounds=0` is preserved, not rewritten. |

## BUG-012 — Self-tamper: `cp -a` of a worktree wrote into the audited branch

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-15 23:46 (commits `e1d018e` "tamper", `d7af7ea` "resign") |
| **Symptom** | A probe intended as a sandbox copied a git worktree's `.git` pointer and committed to the real audited branch: one commit carried the genuine H-C fix under a wrong message, the next re-sealed the release record to certify the probe tree's fingerprint (`936916c6…`) and named `PYTHONPATH=/tmp/opencode/_attest_probe`; the gate then printed "GATE PASSED — safe to spend money". |
| **Impact** | The committed release record certified a tree that no longer existed; had the 16 paid runs started, every fingerprint claim would have been false. Zero paid calls were made. |
| **Root cause** | Operator error plus a procedural gap: a worktree `.git` is a pointer, not a copy; the freeze record could be rewritten by the same re-seal path; the audited tree was writable during audit (H-E/C-12). |
| **Repair (not a revert)** | `e1d018e` and `d7af7ea` are kept in history; the release was re-issued additively and the append-only `FREEZE_HISTORY.jsonl` + annotated tag now anchor the designation. Full disclosure in `INCIDENT_20261115B_self_tamper.md`. |
| **Regression test** | `tests/test_c3_final_freeze.py::TestFreezeDesignation` (4 tests) and the verifier (`scripts/c3_verify_final_freeze.py`) pin `HEAD == record == tag commit == first designation`; no test can enforce future operator discipline, so the control is procedural. |
| **Status** | `PROCESS-CLOSED` (no paid run occurred; history preserved and disclosed) |

## BUG-013 — Circular freeze designation

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-15, C3 round-5 audit finding R-5-B; the attestation also designated `eaba4f7`, an ancestor of `HEAD`, which would have refused all 16 runs |
| **Symptom** | `c3/FROZEN_COMMIT` could be rewritten by the same freeze-writer run, so "the frozen commit" could move; a designation written before the final commit could never equal `HEAD`. |
| **Impact** | The "frozen" claim was not load-bearing; the gate could pass on a tree that was not the certified one. |
| **Root cause** | The designation was both the input and the output of the sealing step, and was written before the commit it named. |
| **Fix commits** | `f556bef` (2026-11-15, H-C case tampering + non-circular designation), `1bba51f` (R-5-C/R-5-D guards), `6057b52` (2026-11-16: designation written strictly after the final commit; verifier requires `HEAD`, record, annotated tag and append-only history to agree; recomputes tree SHA, fingerprint, manifest, all 16 config hashes). |
| **Regression test** | `tests/test_c3_final_freeze.py::TestFreezeDesignation` (4 tests); mutation M9 (verifier stops requiring `HEAD == record`) caught. |
| **Status** | `FIXED` |

## BUG-014 — A-02: Finnhub truncation kept the oldest articles

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-15, C3 round-2 audit (A-02, Critical) |
| **Symptom** | The rendered news block was built from the *oldest* articles in the window; on the live NVDA 2026-09-23 sample the newest rendered article was 2026-09-16 while 63 articles from the final two days were dropped. |
| **Impact** | The news analyst could analyse week-old news on a trade-date-sensitive task; single-pass V2 runs would have inherited the defect. |
| **Root cause** | Truncation sorted/sliced in the wrong direction (kept the first N in ascending order) instead of keeping the newest N. |
| **Fix commit** | `24d488d` (2026-11-15); disclosure of the truncation in the report reader added by `4eaf8cc`. |
| **Regression test** | `tests/test_cand01_news_positive_path.py` (42 tests; recency/truncation cases) and the C3 preflight 16-condition list. |
| **Status** | `FIXED` (verified in the V3 batch: 8.8–10.6 kB Finnhub blocks with dated citations). |

## BUG-015 — B-01: every arm would have run the same switch configuration

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-15, C3 round-2 audit (B-01, Critical) |
| **Symptom** | `prepare_run_spec` wrote a child `spec.json` with no `switches` and no `config_sha256`; all 16 labels would have executed `default_config` (the AB arm), silently collapsing the 2×2. |
| **Impact** | The entire experiment would have measured one configuration under four names — a total loss of the batch and the comparison. |
| **Root cause** | The child-spec writer copied the run identity fields but not the switch/config fields, and nothing asserted their presence. |
| **Fix commit** | `24d488d` (2026-11-15). |
| **Regression test** | C3 preflight condition list and `tests/test_c3_final_freeze.py` config-hash/switch tests (e.g. `TestEffectiveConfig::test_a_tampered_hash_is_refused`). |
| **Status** | `FIXED` (all 16 V3 specs carry distinct switches and `config_sha256`). |

## BUG-016 — B-15: the fingerprint covered zero registered artefacts

| Field | Value |
| --- | --- |
| **Discovered** | 2026-11-15, C3 round-4 audit (B-15, Blocker) |
| **Symptom** | The freeze fingerprint hashed no `specs/`, `SWITCH_MATRIX.csv`, protocol or manifest entries; editing a registration and re-running the writer still printed "GATE PASSED". |
| **Impact** | The certified fingerprint did not cover the files it claimed to certify; a tampered registration could pass the gate. |
| **Root cause** | The fingerprint input list was built from a narrow file set that excluded the registration artefacts. |
| **Fix commit** | `90c7689` (all round-4 findings), `2770789` (provenance/counts/manifest). |
| **Regression test** | Mutations M5–M9 (fingerprint coverage, re-seal guard, mandatory fields, spec cross-check, child freeze check); `tests/test_c3_final_freeze.py::TestManifestCoverage`. |
| **Status** | `FIXED` (fingerprint covers 55 batch files; mutations caught). |

---

## Cross-reference

- Defect-to-test mapping is also recorded in
  `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` §4–§5 and
  `.../REGRESSION_AUDIT.md` §2.
- The pre-fix probe (`token_benchmarks/final_remediation_20261116/tests/pre_fix_detection_probe.py`)
  detects 4/4 defects on `e3b5cca` and 0/4 after `50b2ca3`; this is the only
  executable proof that the R12/DSML/tool-round tests are non-vacuous.
- `BUG-012` and `BUG-013` are process/engineering defects, not model or data
  defects; they are included because they changed what "verified" meant.
