# Known Risks and Mitigations

Each risk records its status, impact, and the action taken or the owner of the
open item. Open items are `TODO` and owned; nothing here is invented to look
complete.

| ID | Risk / issue | Likelihood | Impact | Status | Action / owner |
| --- | --- | --- | --- | --- | --- |
| RISK-001 | Date-sensitive cache tests fail depending on the current clock, so a "green" full-suite result is not reproducible across days. | High (recurring) | Misleading verification signals; flaky CI. | **Mitigated (technical, offline 2026-11-11; DEBT-001/DEBT-034)** | The `tests/test_ohlcv_cache_freshness.py` fixture now converts wall time to the local epoch (`to_pydatetime().timestamp()`) matching production's `pd.Timestamp.fromtimestamp`, with a UTC / `Asia/Hong_Kong` / `America/New_York` summer+winter regression matrix; freshness/TTL semantics unchanged. Remote CI not re-run here. Row retained for audit history. |
| RISK-002 | One baseline test depends on vendor reachability; in a sandbox without network it can fail even when the code is correct. | Medium | A correct change looks broken in offline sandboxes. | **Mitigated (technical, offline 2026-11-11; DEBT-002/DEBT-034)** | `tests/test_no_data_handling.py` mocks `stockstats_utils.vendor_reachable` (True → genuine no-data → `NoMarketDataError`; False → outage → `VendorRateLimitError`) so no real probe is made; the strict-offline harness now reports 0 socket attempts. Row retained for audit history. |
| RISK-003 | Real provider paths are only exercised by mocks/stubs in the offline suite; no paid/vendor call is made by deterministic tests. | Medium | A real-integration regression may go unnoticed offline. | Open (recorded) | Live `@pytest.mark.integration` coverage remains opt-in; document exposure in `test/live/README.md`. |
| RISK-004 | Provisional student identity (transcript file `transcripts/60536848-WANG-Yiwen.md`). | Certain (will be finalized) | Wrong identity on submission; submission risk. | **Resolved** (2026-10-21) | Student ID confirmed (60536848, WANG Yiwen); transcript renamed to `transcripts/60536848-WANG-Yiwen.md` and provisional-identity warnings/TODOs removed. Row retained for audit history. |
| RISK-005 | All Phase 1-3B work is uncommitted and unpushed on `feature/data-quality-debate-control`. | Certain | Work lost on a bad diff; no remote backup. | Open | Keep as working-tree changes until submission; do not push without approval. |
| RISK-006 | OpenCode `permissions.jsonc` schema could not be fully verified against the installed OpenCode version. | Medium | A malformed permission file could break agent tools or be ignored. | Open (recorded) | `TODO (60536848-WANG-Yiwen): Verify schema against installed OpenCode; use conservative minimal form until then.` |
| RISK-007 | Rule precedence in the Debate Evaluator is subtle; a mis-ordered rule could terminate too early or too late. | Medium | Wrong cost/quality behavior. | Mitigated | Deterministic `evaluate_round` ordering plus targeted tests (`tests/test_debate_evaluator.py`). |
| RISK-008 | `DEBATE_METADATA` marker-absent fallback heuristic is imperfect. | Medium | A stance may be unclear on marker-absent turns. | Mitigated | A parse failure contributes zero new evidence and can never extend the debate (`FR-DDT-002`). |
| RISK-009 | The Stage 2 multi-category gate engine was proven at the engine + test level but was **not yet the runtime graph default** (the runtime gate node used the single-category `build_gate_decision`). | Medium | A reader could mistake an engine-level proof for full runtime integration. | **Resolved** (2026-10-21) | The runtime graph default now delegates to `evaluate_multi_category_gate` via `create_data_quality_gate_node`, which evaluates the critical market category plus the optional categories; optional evidence enters only via the explicit `data_quality_optional_evidence` contract. Engine + graph tests prove normal/degraded/blocked routing, determinism, JSON-safety, and point-in-time rejection (logbook 043; `tests/test_data_quality_gate_graph.py`, `tests/test_stage2_multicategory_gate.py`). Row retained for audit history. |
| RISK-010 | Report artifacts (`0_quality/*`, `2_research/debate_trace.json`, `run_summary.json`) require the stage-2 state keys (`data_quality_group_statuses`, `data_quality_evidence_records`, `debate_termination_decision`, `debate_usage`); a legacy checkpoint without them must still produce a safe report. | Low | An undefined-field runtime could emit a sparse/empty artifact. | Mitigated | Deterministic safe defaults asserted by `test_empty_state_produces_safe_report` (`FR-DQG-005`). |
| RISK-011 | The ConflictRecord lifecycle relies on structured `conflict_assertions` and fail-closed evidence validation; the evidence-validation, dedup/merge, and resolve/escalate ordering is subtle and easy to mis-order. | Medium | A conflict could be created/kept on unverifiable footing, or a second misleading resolution note recorded. | Mitigated | Deterministic tracker ordering plus targeted tests (`tests/test_debate_conflicts.py`), fail-closed evidence validation (INV-1/INV-3/INV-13), and a no-op resolve/escalate of a non-open conflict. |
| RISK-013 | A blocked Data Quality Gate verdict could be undone downstream (Trader / risk debate / Portfolio Manager still emitting a model Buy into `final_trade_decision`), so the final signal/report read directional. Independently reviewed on 2026-11-06 (finding 1), then re-opened for alternative rating-header formats (fullwidth colon, prefixed labels). | Medium | Blocked runs expose an executable directional recommendation. | Mitigated (2026-11-06) | A single deterministic output guard (`tradingagents/agents/utils/output_guard.py`) reads the gate state fail-closed and pins only the decision field to Hold on blocked runs (structured + free-text), using the same header grammar the rating extractor reads (fullwidth colon, prefixed labels, unicode dashes, repeated/trailing labels) and preserving the semantic separator; the final signal boundary is gate-aware (`SignalProcessor.process_signal(text, state)` -> Hold) and the memory log records Hold. `tests/test_output_guard.py` 78 passed, including complete-graph escape regressions (logbook 065). |
| RISK-016 | 2026-11-06 independent recheck finding 2: real gate -> manifest -> debate quality propagation was broken (per-record classifications discarded; provisional Low/unvalidated records serialized), so valid evidence could not be cited and the debate stopped on a false absence. | High | Dynamic termination and citation coverage are wrong; report quality counts misleading. | Mitigated (2026-11-06) | Each record's own classification/reasons/validations are applied before serialization; a real gate -> manifest/allowlist -> researcher -> evaluator -> report regression proves qualified evidence counts and genuine Low/Blocked/future evidence does not (`tests/test_gate_debate_integration.py` 9 passed, logbook 065). |
| RISK-017 | 2026-11-06 independent recheck finding 3: guard concatenated Hold with following prose (`Holdbecause ...`), yielding REVIEW. | Medium | Broken restricted Hold contract; unnecessary manual review. | Mitigated (2026-11-06) | Semantic separator/markdown boundary preserved; guarded output idempotent and parses to Hold (`tests/test_output_guard.py`, logbook 065). |
| RISK-015 | Broader original-design item 5 (2026-11-06 review): automatic multi-category adapters and the full source-attempt lifecycle are not wired; the market adapter is single-source with hardcoded asset_type/volume units; freshness omits exchange holidays; researcher usage is char-estimated; append-only event types / audit_incomplete fallback not found. | Medium | A reader could mistake the limited implementation for full original-design conformance. | Partially mitigated — Stage 1 (2026-11-11, approved plan+tests ONLY, NOT human acceptance) | Automatic optional-evidence adapters + source-attempt lifecycle wired via ADR-008 and offline-verified (`tests/test_structured_evidence_ingestion.py`: 53 passed; full strict-offline 1897 passed / 0 socket attempts, logbook 079). REMAINING: exchange-holiday calendar, char-estimate usage, append-only event types, and Stages 2–4 (DEBT-015). `TODO (60536848-WANG-Yiwen): independent review + human acceptance of Stage 1.` |
| RISK-014 | Review findings 2–4 (2026-11-06). Findings 2 (pre-call budget) and 3 (audit export) were corrected in maintenance milestones 2–3; finding 4 (degraded confidence ceiling) was addressed by Stage 4 / ADR-011 (0.60 engineering ceiling, implemented and offline-verified 2026-11-11; awaiting independent Codex review + human acceptance). | Low (finding 4 now a deterministic, tested cap) | Over-confident degraded output is now capped at ≤0.60 across debate/manager/trader/PM/report/memory and every post-gate prompt read (direct GraphSetup + SQLite resume included). | Mitigated (2–3, 4) / awaiting human acceptance | Findings 2–3: pre-call guard + per-evidence/identity audit export (logbook 060/061/063). Finding 4: `tradingagents/debate/confidence_policy.py` + runtime wiring; focused 110 passed / 0 sockets, full 2154 passed (logbook 082, DEBT-014); the capped values are persisted into the returned state and `_log_state`/public JSON (fresh + direct legacy resume), not only the model prompt. The 0.60 value is an ENGINEERING ceiling, NOT a calibrated probability and NOT production threshold tuning; `blocked` runs keep their non-numeric Hold discipline. `TODO (60536848-WANG-Yiwen): independent review + human acceptance`. |
| RISK-012 | Phase 4A comparison results are deterministic offline **scripted fixtures**, not live-provider measurements; human traceability is unscored until a human applies the rubric; no production thresholds were tuned. | Medium | A scripted-fixture delta could be mistaken for a production-grade performance claim. | Open (recorded) | Every Phase 4A report (report.py Markdown, Report.md, ADR-003) and the trace list the honest scope disclaimer; traceability stays `pending`. `TODO (60536848-WANG-Yiwen): require a human score before reporting any traceability value; Phase 4B live-provider benchmarking requires separate explicit authorization.` |
| RISK-018 | 2026-11-06 operator recheck: guard/parser grammar still diverged for fullwidth labels/values and arbitrarily prefixed labels, so the rendered blocked decision text (report/memory body) could parse as Buy while the structured signal was Hold. | Medium | Saved decision text/memory body contradicting the Hold tag. | Mitigated (2026-11-06) | Guard canonicalises every parser-recognized labelled rating line using the shared parser recognition; fullwidth/prefixed/repeated/trailing and full-graph report+memory consistency tests pass (`tests/test_output_guard.py` 90 passed, logbook 066). |
| RISK-019 | 2026-11-06 operator executable-instruction maintenance: a blocked run's stored Trader/Research plan could keep executable directional instructions (fullwidth headers, fullwidth sizing, explained proposal markers, long descriptors) and a quoted/narrative rating mention could override the pinned Hold on the plain textual signal. | Medium | Blocked plans expose an executable direction/sizing or a parser that disagrees with the guard. | Mitigated (2026-11-06, awaiting human review) | A single shared linear recognizer pins every decision field to Hold, neutralises blocked sizing and explained proposal markers, preserves rationale/quoted alternatives, and makes `extract_rating` honour the structural decision over quoted/narrative mentions; idempotent and fast on long prose. `tests/test_output_guard.py` 130 passed; strict offline suite 4 failed / 1661 passed (logbook 067). CLI state-passing gap, DEBT-014 and DEBT-015/RISK-015 remain OPEN. |
| RISK-020 | 2026-11-06 live run: a cited, valid evidence ID does not guarantee the claim's observation date. Bull relabelled the `observed_at=2026-11-04` close (200.13) as "2026-11-05" in prose/metadata; the allowlist checks eligibility, not claim-date truth. | Medium | A saved research report can state a wrong observation date while citing a valid ID. | Mitigated (code, offline; ADR-010, 2026-11-11) | DEBT-022. Typed exact claims are validated against the record + typed origin metadata (distinct date roles); a wrong exact date/value/unit on a valid ID does not count as new evidence, cannot resolve a factual conflict, and is redacted from the trusted plan/report/memory. Offline-proven (`tests/test_exact_claim_validation.py` 47, `tests/test_exact_claim_runtime.py` 9; logbook 081). NOT live-confirmed; arbitrary prose beyond the conservative parser stays `unverified`; independent review + human acceptance pending. |
| RISK-021 | 2026-11-06 live run: debate budget accounting uses char-based ESTIMATES instead of provider usage/measured clock, so time was estimated at 2,171.77 s (actual 12.72 s) and tokens 16,289 (vs 18,058 reported); Bear was refused with `budget_exhausted` and 0 complete rounds ran. The guard is active and safe; the basis is wrong. | High (live) | Dynamic termination ends prematurely on a mis-estimated budget; live cost comparison unreliable. | Mitigated (code, offline; ADR-007, 2026-11-10); live-confirmed D1 | DEBT-021. Measured injectable clock + provider usage provenance implemented offline; LIVE-CONFIRMED 2026-11-10 D1 (logbook 074): one complete round, stop max_rounds_reached. Cross-resume accounting now ADDRESSED offline by ADR-009 (2026-11-11); all-agent totals aggregated for reporting. Live cross-process/retry observation remains open (DEBT-036). |
| RISK-028 | 2026-11-10 school-model live run (NVDA 2026-11-05, DEGRADED): RISK-021 re-confirmed — Bull actual **19.70 s / 16,931 tokens** vs estimate **2,024.4 s / 15,183**; guard correctly refused Bear but the inflated time estimate stopped it prematurely (Bear node visited, **0 actual Bear calls**, `bear_history` empty; `budget_exhausted`). The actual runtime did NOT exceed 600 s — only the faulty estimate did. Gate DEGRADED not blocked, so `blocked_signal_is_hold=true` is vacuous (not live blocked proof); 0 complete Bull/Bear rounds. | High (live) | Premature dynamic termination; the block-handling and completed-round live paths remain unexercised. | Mitigated (code, offline; ADR-007); live-confirmed D1+D2 (bounded) | DEBT-021 / DEBT-033 / RISK-023. 2026-11-10 bounded validation: D1 one complete round with measured/provider usage and stop max_rounds_reached; D2 narrow controlled-fixture blocked-path proof (Hold throughout, zero Bull/Bear invokes; NOT exhaustive/live-vendor). Do not claim all bugs fixed or a historical-edit rewrite. |
| RISK-030 | 2026-11-11 CI/baseline repair: the deterministic subset fallback in `scripts/validate/validate_requirements.py` (used by the CI Python jobs, which do not install `jsonschema`) validated `project.schema_version` only as a non-empty string and accepted `"1.0"`, which the real schema pattern `^v[0-9]+\.[0-9]+$` rejects; the fixture/cache and no-data tests were also TZ/socket fragile. | High (all 4 Python jobs red) | A non-compliant registry value could pass the fallback gate; date/TZ/socket-dependent tests. | Mitigated (technical, offline 2026-11-11; independent Codex verified; remote CI not re-run) | The fallback reads the pattern from the actual schema and rejects non-matching/non-string/missing versions on BOTH paths (ADR-006); the test is never skipped/weakened and dependencies/`.github` are unchanged; cache fixture uses the local wall-clock epoch with a UTC/HK/NY summer+winter matrix; no-data test mocks `vendor_reachable` with both reachable/unreachable cases under `tmp_path`. DEBT-034. Not a claim remote CI is green (push not authorized). |
| RISK-029 | 2026-11-10 live run secondary observation (not a proven defect): the Research Manager prose attributes "the bear overplayed its hand" although no actual Bear response exists (Bear refused pre-call). | Low–Medium | Misleading attribution to an unexecuted opponent in the saved report. | Mitigated (code, offline; ADR-007); live-confirmed D2 (controlled fixture); human review pending | DEBT-033. Deterministic participation truth + SAFE PARTIAL-DEBATE TEMPLATE implemented offline; 2026-11-10 D2 live-confirmed participation explicitly data_quality_blocked with no absent-opponent attribution in the trusted report. |

| RISK-022 | Documentation/requirements revision (2026-11-06): extended schema, PRD, fit criteria, invariant register, context ADR, permission proposal, prompt v1.3, and CI gate matrix are NOT enforced and NOT human-approved; `prompt_v1.3.yaml` is not yet in the validator's required-artifact lists; the local schema fallback does not enforce the extended `fit_criterion` conditionals. | Medium | A reader could mistake documentation for implemented enforcement or approval. | Open (recorded) | DEBT-023/DEBT-024/DEBT-027. Every affected doc states its unverified/not-implemented status; human review pending. |
| RISK-023 | Live verification was a single authorized NVDA/2026-11-05 run that ended **degraded** (not blocked), with 0 complete Bull/Bear rounds; the normal multi-round path and the blocked-path live behavior were NOT exercised live (only a deterministic counterfactual replay of saved outputs was). Live integration is therefore NOT all-bug-proof. | Medium | Over-generalizing from a thin live sample; hidden normal-path or blocked-path live defects. | Open (recorded) | Do not claim exhaustive live proof. A blocked-path and a completed-round live check require separate explicit authorization. |
| RISK-024 | 2026-11-10 repair batch: a blocked Trader plan's executable multiline instructions (block-style `Action`/`FINAL TRANSACTION PROPOSAL` values, blank-line-separated, bulleted/numbered `- Buy`/`1. Buy`, or direction+explanation values, split sizing, unsupported plain fill sentences) survived a prepended Hold and contradicted the authoritative Hold in the stored plan/report. | Medium | Blocked plans expose executable direction/sizing contradicting Hold. | Mitigated (2026-11-10, awaiting independent review + later human acceptance) | Label-only continuation values fold into pinned Hold/HOLD/not-applicable (blank lines skipped, bullets/numbers tolerated, explanation kept as tail); anchored executable-sentence fallback fails closed with structural-only exemption (verb inside a quotation, or a non-command-leading line), so a live command that later mentions a keyword or quotes a phrase is still contained while genuine quoted/negated rationale survives; idempotent and linear. a recognised decision value's executable sizing/price/quantity tail is stripped keeping a clearly separated rationale clause, and a bounded unsupported-value fail-closed policy drops an unrecognised value-like line (`**Strong Buy**`) in a recognised decision position. `tests/test_output_guard.py` 197 passed (24 multiline + 14 boundary + 15 second-review + final-F1 executable-tail/unsupported-value + normal/degraded-unchanged); strict offline 1743 passed / 4 known baselines (logbook 070; DEBT-029). |
| RISK-025 | 2026-11-10 repair batch: explicitly empty authoritative validation entries were dropped so a stale embedded passed check survived in `evidence_manifest.json`. | Low | Audit artifact shows a cleared validation as passing. | Mitigated (2026-11-10, awaiting independent review) | Present `{id: []}` is authoritative and overrides embedded; absent keeps legacy fallback; ordering/redaction/no-cross-ID preserved; helper + saved-artifact tests (DEBT-030). |
| RISK-026 | 2026-11-10 repair batch: real-jsonschema path accepted duplicate requirement IDs (uniqueItems compares whole objects). | Medium | Duplicate-ID registry passes the CI real-schema gate. | Mitigated (2026-11-10, awaiting independent review) | Shared `validate_unique_requirement_ids()` on both entry paths; 22 IDs and schema constraints unchanged; real + forced-fallback duplicate tests (DEBT-031). |
| RISK-027 | 2026-11-10 doc/traceability batch: (a) the permission schema cannot express path-level edit/read, so the proposal + planner read-only execute are process-enforced only; (b) NFR-OFF-001 zero-attempt is NOT achieved — the count-and-fail harness observes 1 intercepted vendor-reachability attempt from the existing `test_no_data_handling` baseline (no connection made); (c) the course slide layout still needs instructor confirmation; (d) the reference check is narrow and test tags are not a CI gate. | Medium | A reader could mistake docs for enforcement; NFR-OFF-001 stays partial; the course layout stays unconfirmed. | Open (recorded, technical batch awaits independent review + human acceptance) | Documented honestly in permission-model/structural-constraints/requirements/invariants; NFR-OFF-001 PARTIAL/OPEN (DEBT-002); baseline/CI/waivers not modified (DEBT-032). `TODO (60536848-WANG-Yiwen): confirm course layout with instructor; no CI traceability gate implemented.` |
| RISK-029 | ADR-009 Stage 2 usage ledger re-reads and enforces the full budget policy (call+token+time+reserve+unresolved) inside a `BEGIN IMMEDIATE` transaction, but (a) hidden SDK transport retries are unobserved (`transport_attempts` unknown); (b) a pre-call reservation is an ESTIMATE, not a physical billing bound; (c) concurrency/resume is proven OFFLINE with a real `SqliteSaver` + threading barriers, not live separate processes; (d) whole-run usage is reporting only, never a whole-run spend cap. | Medium | A reader could over-read Stage 2 as a live billing guarantee or a whole-run budget. | Mitigated (code, offline; 2026-11-11, awaiting independent Codex review + human acceptance) | `tests/test_durable_usage_ledger.py` 33 passed + `tests/test_whole_run_usage.py` 10 passed; full strict-offline 1940 passed / 0 sockets (logbook 080). Owner: `TODO (60536848-WANG-Yiwen): independent review; live cross-process/retry observation needs separate authorization; do not claim a physical billing bound` (DEBT-036). |
| RISK-031 | 2026-11-11 confirmed live-run Defect-1: active-collector persistence overwrote the gate's market origin map (5 records, 0 origins) and a latent first/last-wins origin precedence could silently trust a conflicted origin. | Medium | Exact-claim validation defeated on the real path; a conflicted origin trusted without signal. | **Mitigated (code, offline; ADR-010 amendment, 2026-11-11)** | DEBT-037. Authoritative origin merge after persistence; declared `data_quality_origin_conflicted_ids` channel fails conflicted ids closed at the claim validator / output boundary; no derived re-trust / resurrection; existing-state tombstones honoured without a collector (direct consumer + derivation exclude dropped ids); 20/7 records unchanged. Offline-proven (`tests/test_gate_origin_authority.py` 18; logbook 083). NOT live-confirmed; independent review + human acceptance + future live verification pending. |
| RISK-032 | 2026-11-11 confirmed live-run Defect-2: structured Pydantic results lost raw provider usage before settlement (estimated structured calls; misleading `provider` aggregate label). | Medium | Non-exact whole-run reconciliation; a mixed total could be read as exact provider. | **Mitigated (code, offline; ADR-009 amendment, 2026-11-11)** | DEBT-038. `include_raw` raw-usage settlement (same single call) with binding-only fallback; settlement precedes downstream parse/sanitize/render; `mixed` aggregate/report-only label (never per-call). Offline-proven (`tests/test_structured_raw_usage.py` 18; logbook 083). NOT live-confirmed; independent review + human acceptance + future live verification pending. |
| RISK-033 | 2026-11-11 confirmed live-run price corruption (Defect 1): an ordinary price (`$204.38`) was rewritten to `$204.unknown (invalid confidence quarantined)` in the Trader plan and exported reports because the suffix confidence grammar crossed a sentence boundary. | Medium | A saved plan/report states a corrupted price while appearing authoritative. | **Mitigated (code, offline; ADR-011 amendment, 2026-11-12)** | DEBT-039. Structural numeric/sentence boundaries (no trailing-period absorption; terminators are boundaries; CRLF soft-wrap still binds; currency/sign/date/path-glued numerics excluded); `$204.38.` byte-for-byte preserved; bare `204.38 confidence` still quarantined; genuine forms still cap to 0.60. Offline-proven (`tests/test_confidence_boundary.py` 51; full 2290 / 0 sockets; logbook 085). NOT live-confirmed; independent review + human acceptance + future live verification pending. |
| RISK-034 | 2026-11-11 confirmed live-run exact-claim coverage gap (Defect 2): 8 out-of-marker Bear typed lines were silently dropped (status ok, empty summary), so it was not proven that live date/value/unit enforcement ran. | Medium | A reader could believe exact claims were validated when they were never checked; re-admitting arbitrary prose could over-trust. | **Mitigated (code, offline; ADR-010 amendment, 2026-11-12)** | DEBT-040. Shared strict extractor with fenced/quoted exclusion, alias-contradiction rejection, honest coverage, same fail-closed validator; extraction ≠ trust; frozen 20/7 records unchanged; offline-proven (`tests/test_standalone_claims.py` 49; real SQLite resume; full 2290 / 0 sockets; logbook 085). NOT live-confirmed; independent review + human acceptance + future live verification pending. |
| RISK-035 | 2026-11-12 school live run residual: a verified long-decimal typed claim was re-redacted by the generic prose scanner (24-char nearest-unit window), losing correct evidence from trusted plans/reports/memory (representation-length-dependent false rejection). | Medium | Correct evidence can be unnecessarily removed; the "correct-claim-preservation" contract is violated. | **Mitigated (code, offline; ADR-010 addendum, 2026-11-12)** | DEBT-041. Occurrence-exact PER-TOKEN authority of a verified typed ClaimRecord's own date/value spans (both prose passes; `_span_is_authorized`): a verified token is never erased and an unauthorized span is always blanked regardless of heuristic pairing (duplicate identical `||` canonical subclaims across 720 field-order permutations preserved; mixed verified+wrong redact only the bad component), shared fence/Example/blockquote walk for standalone+canonical; separate prose and wrong/future/wrong-unit/currency/scale/unknown/Low/Blocked still redacted; unparseable mixed line fails closed. Offline-proven (`tests/test_verified_span_boundary.py` 77; focused 716; full 2367 / 0 sockets; logbook 087). NOT live-confirmed; independent Codex FINAL technical review COMPLETE (logbook 088); explicit human final acceptance + any post-fix live retest pending. |

## 2026-11-13 merge update — simulated-trading subsystem

The simulated-trading subsystem is now an approved independent source tree
(`src/trading/`, `src/safety/`) with tests under `tests/trading/`. The subsystem
is deterministic/offline by default, and the only live test is opt-in with a
fixture-scoped yfinance proxy and provider credentials. It does not place real
orders.

---

## Token-observability risks (RISK-036…RISK-049)

The 35 Release risks above keep their identifiers and meanings. The personal delivery's
14 risks are appended below with new identifiers so that no Release risk changes meaning.
The mapping is:

| Personal ID | Final ID |
| --- | --- |
| personal RISK-001 | RISK-036 |
| personal RISK-002 | RISK-037 |
| personal RISK-003 | RISK-038 |
| personal RISK-004 | RISK-039 |
| personal RISK-005 | RISK-040 |
| personal RISK-006 | RISK-041 |
| personal RISK-007 | RISK-042 |
| personal RISK-008 | RISK-043 |
| personal RISK-009 | RISK-044 |
| personal RISK-010 | RISK-045 |
| personal RISK-011 | RISK-046 |
| personal RISK-012 | RISK-047 |
| personal RISK-013 | RISK-048 |
| personal RISK-014 | RISK-049 |

The personal risk entries' debt references were renumbered by the D4 merge: personal
`DEBT-001…DEBT-010` are now **DEBT-042…DEBT-051** in `docs/debt-register.md`. Read a
`DEBT-` reference inside a `RISK-036…RISK-049` entry against that renumbered series, not
against the same-numbered Release debt (Release `DEBT-001…DEBT-041` keep their meanings).
Risk status vocabulary is unchanged: `MITIGATED` means a fix exists and is tested, not that
the risk is gone.

### Personal risk register (renumbered)

**Purpose.** Risks that affect the validity, reproducibility, or safety of the
CAND-01 evaluation. Each risk states likelihood, impact, current status, and the
evidence a reader can inspect. A risk marked `MITIGATED` means a fix exists and
is tested; it does **not** mean the risk is gone. A risk marked `OPEN` is a known
residual, not necessarily a blocker.

**Status vocabulary:** `OPEN`, `MITIGATED`, `PARTIALLY_MITIGATED`, `NOT_MEASURED`.
**Likelihood / impact:** Low, Medium, High, Certain.

**Base.** `50b2ca3` plus the 2026-11-19 submission-packaging files. Raw paid
telemetry is untracked; evidence paths marked **(local)** are outside the
delivered tree.

---

### Summary

| ID | Risk | Likelihood | Impact | Status |
| --- | --- | --- | --- | --- |
| RISK-036 | Provider rejects a message sequence (R12 400) | Medium | High | `MITIGATED` (offline), residual |
| RISK-037 | Tool-call protocol markup (DSML) leaks into a report | High | High | `PARTIALLY_MITIGATED` |
| RISK-038 | Data availability / read-only cache degrades a cell | High | Medium | `OPEN` |
| RISK-039 | PIT is only day-granular | Medium | Medium | `OPEN` (documented) |
| RISK-040 | Shared memory pollutes a later run | High | High | `MITIGATED` registered / `OPEN` generic |
| RISK-041 | Provider usage is missing or contradictory | Medium | High | `MITIGATED` |
| RISK-042 | API key leakage or over-broad access | Low | High | `PARTIALLY_MITIGATED` |
| RISK-043 | LLM/run nondeterminism drives the result | High | Medium | `OPEN` (design limit) |
| RISK-044 | n = 1 per cell is too small for inference | Certain | Medium | `OPEN` (design limit) |
| RISK-045 | Freeze/spec paths do not reproduce in another checkout | High | Medium | `OPEN` |
| RISK-046 | Decision quality is unvalidated | Certain | High | `NOT_MEASURED` |
| RISK-047 | Endpoint/model version is not in `config_sha256` | Medium | High | `OPEN` (documented) |
| RISK-048 | Generic/CLI runs bypass the harness gates | Medium | Medium | `OPEN` |
| RISK-049 | CI / clean-checkout tests were red at `50b2ca3` | High | Medium | `MITIGATED (submission branch); OPEN at 50b2ca3` |

---

### RISK-036 — Provider compatibility: the R12 message sequence is rejected with HTTP 400

**Description.** In V3, R12 (JPM/CC) failed twice with a provider
`invalid_request_error`: an assistant message carried `tool_calls` and was
followed by insufficient `tool_messages`. The trigger was a schema-invalid
`stance="Mildly Bearish"`; the fallback then replayed the dangling assistant turn
and dropped the system prompt.

**Likelihood / impact.** Medium / High. A run that fails this way produces no
decision and loses the paid spend.

**Status.** `MITIGATED` in code (`e0ea1b0` and follow-ups), residual `OPEN`.
The fix removes the dangling turn, keeps the system prompt, and uses
`prompt | llm` for the retry. It is covered by the offline regression file
(`tests/test_final_remediation.py`, 20 tests) and a pre-fix probe (4/4 detected);
it has **not** been re-run against the paid provider.

**Evidence.** `token_benchmarks/final_remediation_20261116/R12_FALLBACK_FIX.md`;
`tests/test_final_remediation.py`; `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`;
local `R12_PROVIDER_ERROR_DIAGNOSIS.md` and the two R12 `runner_report.json`
files **(local)**.

---

### RISK-037 — Tool-call protocol / DSML markup reaches a report

**Description.** In single-pass fallback, the model sometimes writes tool calls
as text (`<||DSML||>` markup). R07 (AAPL/CC) and R14 (XOM/CC) stored 1,922 and
346 characters of raw markup as `market_report`; downstream agents received it
instead of a report. This is a format failure, not a token-accounting failure.

**Likelihood / impact.** High / High. It can silently degrade a valid sample and
is easy to miss in an aggregate token table.

**Status.** `PARTIALLY_MITIGATED`. `sanitize_analyst_text` now runs at every
report exit; it preserves prose before markup, recovers schema fields, and falls
back to an explicit `REPORT UNAVAILABLE` (non-empty, non-markup). Tests cover the
R07/R14 fixtures and the prose/structured/finalizer exits. Residual: the
underlying model behaviour is not prevented, only sanitized; a new output shape
could still evade the patterns.

**Evidence.** `token_benchmarks/final_remediation_20261116/DSML_MARKET_REPORT_FIX.md`;
`tests/test_final_remediation.py`; `tradingagents/agents/utils/structured.py`
(`sanitize_analyst_text`, `finalize_single_pass`); local `QUALITY_COMPARISON.md`
**(local)**.

---

### RISK-038 — Data availability and read-only-cache failures degrade a cell

**Description.** R01 (NVDA/C0) ran with a read-only cache: 14
`NO_DATA_AVAILABLE` from `get_indicators` and 2 `OSError` from
`get_verified_market_snapshot`; the report fell back to a 10-day simple proxy.
V2 R05 attempt 01 failed with `OSError EROFS` while writing the decision log.
These are environment failures, but they change the measured input.

**Likelihood / impact.** High / Medium. The V3 NVDA C0 cell is a valid sample by
the U-1 rules yet is not a clean C0 observation; excluding it changes the batch
effect from −51,716 to −695.

**Status.** `OPEN` (documented limitation). No retry of R01 was made; the
sensitivity analysis reports the result with and without it. The cache-write
path is not hardened by this study.

**Evidence.** Local `QUALITY_COMPARISON.md` and `FACTORIAL_ANALYSIS.md`
**(local)**; V2 `EXPERIMENT_LIMITATIONS.md` **(local)**;
`tests/test_no_data_handling.py`; `tests/test_yfinance_stale_ohlcv_guard.py`.

---

### RISK-039 — PIT is day-granular, not intraday

**Description.** The trade date is the cutoff; an article published at 23:59 on
the trade date is treated as available for that day's analysis. The design
cannot distinguish "before the decision" from "after the close" within the day.

**Likelihood / impact.** Medium / Medium. It can admit same-day information that
an intraday strategy would not have had.

**Status.** `OPEN` (documented design limit, V3 protocol §12). It is enforced
consistently (all arms use the same convention), so it does not bias the arm
comparison; it does limit external validity.

**Evidence.** `tradingagents/dataflows/date_window.py` (`as_of`,
`as_of_window`); `tradingagents/dataflows/finnhub_news.py` (cutoff filter);
`tests/test_tool_date_enforcement.py`; `tests/test_news_lookahead.py`;
`tests/test_fundamentals_lookahead.py`; V3 protocol §12.

---

### RISK-040 — Shared memory pollutes a later run

**Description.** A run appends a pending decision; the next same-ticker run
resolves it with a provider call before the graph, changing the prompt and the
token cost. V2's R05 write caused R06's pre-graph reflector and R06 was invalid.
The same defect would have hit R10 and R14.

**Likelihood / impact.** High / High. It silently couples run order to the
measurement and can void a sample.

**Status.** `MITIGATED` for registered V3 runs: immutable empty baseline,
per-run copy, pre/post hash checks, `memory_state.json`; 18/18 V3 attempts
report `baseline_unchanged=true`. `OPEN` for generic `measure`, CLI, and direct
graph runs, which still use the shared log (audit A, M3).

**Evidence.** `docs/architecture/memory-design.md`;
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/MEMORY_ISOLATION_AUDIT.md`,
`MEMORY_SNAPSHOT_PROVENANCE.md`; `tests/test_memory_isolation.py` (21 tests);
`scripts/token_benchmark.py::validate_memory_spec`; local `R06_DIAGNOSIS.md`
**(local)**.

---

### RISK-041 — Missing or contradictory provider usage

**Description.** A provider may omit usage, omit a token field, or report a total
that disagrees with the per-call events. If a missing value were treated as zero,
the token comparison would be silently wrong.

**Likelihood / impact.** Medium / High. The study's primary metric is tokens.

**Status.** `MITIGATED` on the harness path. `usage_verdict` has four states and
only `VALID` produces a sample; missing is `null`, never `0`; an unattributed
event invalidates the run even if the aggregate flag was tampered with. Residual:
a direct graph/CLI run does not call the verdict.

**Evidence.** `scripts/token_benchmark.py::usage_verdict`,
`extract_run_metrics`; `tradingagents/observability.py`;
`tests/test_c3_final_freeze.py::TestUsageVerdict`;
`tests/test_token_benchmark.py`; `tests/test_observability.py`.

---

### RISK-042 — API key leakage or over-broad access

**Description.** A key can leak through a committed `.env`, a log, a prompt, or
an over-broad local file mode. A key that is present is also usable by any
process with environment access.

**Likelihood / impact.** Low / High. A leaked course key is a real incident even
if no paid run occurs.

**Status.** `PARTIALLY_MITIGATED`. `.env` is git-ignored and untracked; the
credential audit records no key in the branch diff; the CLI writes saved keys
`0600`; tests block live news. Residual: no secret scanner, no least-privilege
key, no egress allowlist; the audited local `.env` was mode `644`; arbitrary
shell reads cannot be blocked by `.opencode/permissions.jsonc`.

**Evidence.** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/env_credential_audit.txt`;
`.gitignore`; `tradingagents/llm_clients/api_key_env.py`; `cli/utils.py`;
`tests/test_api_key_env.py`; `tests/conftest.py`.

---

### RISK-043 — Nondeterminism and one-run outliers

**Description.** Provider sampling, tool return order, and context length vary
between runs. V2's AB cell (339,738) was driven by one long news loop; V3's NVDA
C0 was environment-degraded. A single run can change an effect's sign or size.

**Likelihood / impact.** High / Medium. It makes n = 1 cell estimates fragile.

**Status.** `OPEN` (design limit). The mitigation is disclosure: per-block
values, sensitivity analysis, and no significance claim. A seed is fixed in the
protocol, but it does not control provider sampling.

**Evidence.** V2 `EXPERIMENT_LIMITATIONS.md` **(local)**; V3
`FACTORIAL_ANALYSIS.md`, `DETERMINISTIC_VS_STOCHASTIC` **(local)**; V3 protocol
§12.

---

### RISK-044 — Small samples (n = 1 per cell)

**Description.** The V3 2x2 has one run per cell, one date, four stocks, one
model. JPM/CC is missing. Any "main effect" is a descriptive difference, not an
estimate of a population effect.

**Likelihood / impact.** Certain / Medium. The study is `EXPLORATORY` by design.

**Status.** `OPEN` (design limit). The analysis reports per-block values,
balanced three-block means, and sensitivity; it performs no significance test
and makes no generalisation.

**Evidence.** V3 protocol §12; `docs/architecture/evaluation-table.md` Part I;
local `FACTORIAL_ANALYSIS.md` **(local)**.

---

### RISK-045 — Freeze/spec paths do not reproduce in another checkout

**Description.** V3 specs embed absolute `experiment_root` and `results_dir`
paths from the build worktree. A different checkout regenerates different paths,
so generator `--check` reports drift and the V3 infra tests fail. The freeze
record also names `e3b5cca`, while the current `HEAD` is `50b2ca3`.

**Likelihood / impact.** High / Medium. It makes the "certified tree" claim
checkout-dependent and turns CI red on a clean export.

**Status.** `OPEN`. The freeze verifier fails closed (good), but it cannot
certify `HEAD`; the tracked tree does not contain the V2/V3 `FREEZE_RECORD.json`.
The specs are frozen artifacts and must not be hand-edited to fix the paths; a
new registration would be required.

**Evidence.** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/specs/R01_NVDA_C0/spec.json`
(`experiment_root`, `results_dir`); `scripts/c3_verify_final_freeze.py`;
`tests/test_cand01_batch_16run_v3_infra.py::test_the_generator_reproduces_the_delivered_artifacts`,
`test_the_cli_check_mode_passes`; observed `SPEC DRIFT` and
`c3_verify_final_freeze.py` failure on 2026-11-19.

---

### RISK-046 — Decision quality is unvalidated

**Description.** The study measures tokens and structural completeness, not
whether a decision is correct, well-calibrated, or profitable. There is no
ground truth, no realised return, no forward-looking return, and no human
rating.

**Likelihood / impact.** Certain / High. A cheaper arm can look "better" while
producing worse decisions.

**Status.** `NOT_MEASURED`. The quality comparison explicitly refuses to rank
arms. Any statement that one arm is "more accurate" or "safer" is unsupported.

**Evidence.** Local `QUALITY_COMPARISON.md` **(local)**; V3 protocol §12/§13;
`docs/architecture/evaluation-table.md` §1.5.

---

### RISK-047 — Endpoint and model version are not in `config_sha256`

**Description.** The provider endpoint is ambient
(`TRADINGAGENTS_LLM_BACKEND_URL`, set by `apply_cityu_env`), and the model is
addressed by name (`CS5351/DeepSeek-V4-Flash`). Neither the endpoint nor a model
snapshot digest is in `HASHED_FIELDS`, so changing the endpoint or the provider's
underlying model does not change the registration hash.

**Likelihood / impact.** Medium / High. A "same" registered run can be served by
a different model version, changing cost and answers.

**Status.** `OPEN` (documented V3 limitation). The runbook pins the endpoint; the
hash cannot. Any future comparison must record the endpoint and date separately.

**Evidence.** V3 protocol §8 (`HASHED_FIELDS`) and §12; local V3 run report
**(local)**; audit B residual L3 in
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_B.md`.

---

### RISK-048 — Generic/CLI runs bypass the harness gates

**Description.** Budget, usage, memory, news-scope, switch, and freeze checks run
in `scripts/token_benchmark.py` for a registered spec. A direct
`TradingAgentsGraph.propagate()` or CLI run does not require a registration and
does not execute the same gates.

**Likelihood / impact.** Medium / Medium. A "looks similar" run can be treated as
experiment evidence when it is not.

**Status.** `OPEN`. The separation is intentional (the product must remain
usable), but documentation must not generalize V3 guarantees to every product
path. Audit A recorded the generic memory path as a known residual.

**Evidence.** `scripts/token_benchmark.py::_requires_memory_isolation`,
`_preflight_gate`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_A.md`
(M3); `docs/architecture/memory-design.md` §5.

---

### RISK-049 — CI / clean-checkout suite was red at `50b2ca3` (mitigated in this branch)

**Description.** A clean export of `50b2ca3` fails at least the two V3
absolute-path infra tests; in this environment a full clean export also failed
dry-run/`.env`-coupled tests. The committed remediation record itself lists 4
known failures (2 V3 path + 2 `cli_prefs`) in the remediation worktree.
**Mitigation in this submission branch:** `tests/test_cand01_batch_16run_v3_infra.py`
normalises only the documented host-path fields (all identity/config/hash
assertions and the MANIFEST byte check stay strict), and `tests/conftest.py`
supplies a placeholder backend URL when the host has no `.env`. Verified with a
`.env`-free working directory: `2233 passed, 2 skipped, 319 subtests, 0 failed`.
The published commit `50b2ca3` itself is unchanged and still carries the old
behaviour; the fix lives in the course-deliverable branch.

**Likelihood / impact.** High / Medium. A red suite weakens the "verified" claim
and makes a future regression harder to see.

**Status.** `OPEN`. The failures are classified (environment/path coupling, not
product logic), but classification is not a fix. The frozen specs must not be
edited to make the tests pass; a new registration or a path-relative spec design
would be required.

**Evidence.** `.github/workflows/ci.yml`;
`token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`;
`tests/test_cand01_batch_16run_v3_infra.py`; observed clean-export failures on
2026-11-19; `CS5351_SUBMISSION_COMPLIANCE_AUDIT/` (local workspace) **(local)**.

---

### Residual-risk statement

The strongest claims this study can support are measurement-mechanics claims:
the token totals close, usage and attribution are complete on the valid runs,
the memory baseline did not change, and the frozen artifacts are hash-pinned.
The weakest claims are causal and external: a single run per cell on one date
cannot establish an arm effect, and no quality ground truth exists. Risks
RISK-043 through RISK-047 are the reason the evaluation table uses
`EXPLORATORY` and refuses to rank arms by decision quality.
