# Integrated branch records

Both branch histories are retained below. Dates, result counts, approval scopes,
and unresolved items belong to the recorded execution, not this merge. Commands
in release history use the former root-level layout; their current equivalents
use `src/`, `test/offline/`, and `test/live/`. No historical result is a fresh
verification of the merged tree.

## WebUI branch records

# Technical Debt Register

| ID | Category | Evidence / consequence | Next action / review trigger | Status |
| --- | --- | --- | --- | --- |
| DEBT-001 | Evaluation debt | Iteration-1 implementation is approved; Iterations 2 and 3 are implemented but their implementation reviews are pending; the requirements registry remains `draft` and no GitHub test-plan/safety/governance markers are recorded | Align requirements statuses/evidence in a separate reviewed change; record GitHub review markers if CI gating is used | Iteration-2/3 review and registry markers pending |
| DEBT-002 | Evaluation debt | No approved runtime semantic evaluator, fixed dataset, or quality thresholds | Approve these on a base revision before any runtime prompt/model change; the semantic gate fails closed until then | Open |
| DEBT-003 | Guardrail debt | GitHub branch protection/ruleset settings are external to repository files | Release already requires reviews, but its required-status-check list is empty; require `blocking-gate` after the reviewed workflow is pushed | Open |
| DEBT-004 | Evaluation debt | Four historical baseline failures, recorded in bug-diary.md | Reproduce and repair in a separately scoped change; do not waive them automatically | Open |
| DEBT-005 | Evaluation debt | Full-source mypy reports 202 errors in 27 files; Bandit reports 5 findings requiring triage | Record actual findings and fix them explicitly; do not suppress the checker or downgrade its result | Open |
| DEBT-006 | Human/cognitive debt | Preparation originally remained uncommitted by user instruction | User subsequently authorized a single preparation commit; commit authorization does not establish final governance review | Commit authorized; review pending |
| DEBT-007 | Hidden dependencies | Broad baseline runtime dependency ranges are not a locked environment | Capture resolved dependency versions in CI run artifacts and review updates and audit results | Open |
| DEBT-008 | Evaluation debt | Regular PR regression runs do not exercise credential-dependent live APIs | Plan authorized live verification before declaring those requirements verified; skipped API tests are not passing live evidence | Open |
| DEBT-009 | Architecture debt | Web framework, event transport, frontend stack, and package path were selected in ADR-002 through ADR-004 and implemented for Iteration 1 | No further design action for the read-only slice; later iterations still need their own ADRs | Resolved for Iteration 1 |
| DEBT-010 | Verification debt | The official requirements schema gate was unrun at drafting time; it has since passed in the iteration-1 test environment | No further action for the schema gate itself; rerun after any registry change | Resolved 2026-11-05 |
| DEBT-011 | Governance debt | `docs/architecture/permission-model.md` was filled but has not received a human review verdict | Review the runtime permission matrix and record the verdict before implementation | Documented; review pending |
| DEBT-012 | Evaluation debt | Architecture experiments EVAL-01 through EVAL-10 (latency, browser, clean install, full security/quality evaluation) have not been fully run; WebUI backend/frontend suites and the frontend build have been executed | Execute and record the remaining experiments in `docs/architecture/evaluation-logbook.md`; do not claim planned checks as passing | Partially evaluated |
| DEBT-013 | Dependency debt | FastAPI, Uvicorn, Zustand, and the npm tree are installed for local verification; npm audit reports 0 vulnerabilities, but project dependency/license approval and pip-audit are still pending | Complete dependency, license, and advisory approval before merge/release | Approval pending |
| DEBT-014 | Packaging debt | The wheel contains the new Iteration-2 modules, `static/index.html`, and the `tradingagents-web` entry point, but a clean-install health check in a fresh environment has not been run | Run the clean-install smoke before release | Partially verified |
| DEBT-015 | Verification debt | Frontend Vitest passes 25 tests; Chromium Playwright E2E passes 6 tests. Firefox/WebKit were excluded by user instruction, so the full browser matrix remains unverified | Run Firefox/WebKit only if the user later expands the matrix | Partially verified |
| DEBT-016 | Environment debt | Local verification used Python 3.14.3, outside the CI matrix (3.10–3.13) | Run the CI matrix before merge/release | Open |
| DEBT-017 | Performance debt | Vite reports a 604.7 kB main JS chunk (above the 500 kB warning threshold) | Consider route-level code splitting before release | Open |
| DEBT-018 | Verification debt | The real `GraphRunner` and core LangGraph now have offline integration coverage through memory/report/history output; live model/data provider behavior remains unverified | Run an authorized live smoke with credentials and cost limits before declaring live analysis verified | Open |
| DEBT-019 | Verification debt | The real `run_backtest` path has not been exercised against live model/data providers; automated tests use a fake runner that writes an isolated memory log | Run an authorized live backtest smoke with credentials and cost limits before declaring live backtest verified | Open |
| DEBT-020 | Identity debt | When the client does not supply a backtest `run_id`, the browser-facing `bt_` id is process-memory only while the core writes its timestamp id to disk; a restart loses the `bt_` route alias | Supply or persist the core run id in a future reviewed change, or document the restart behaviour in the UI | Open |

Prompt rot, hallucinated dependencies, untouchable code, agent-induced bloat, and other categories should be recorded when supported by actual evidence. No entry implies a defect has been repaired or accepted.

## Security scanner evidence — 2026-10-24

These are inherited scanner findings requiring triage, not confirmed exploitability or approved exemptions.

| Check | Location | Finding |
| --- | --- | --- |
| B608 | `src/tradingagents/agents/analysts/market_analyst.py:25` | Possible SQL injection vector through string-based query construction. |
| B310 | `src/tradingagents/dataflows/reddit.py:190` | Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected. |
| B314 | `src/tradingagents/dataflows/reddit.py:191` | Using xml.etree.ElementTree.fromstring to parse untrusted XML data is known to be vulnerable to XML attacks. Replace xml.etree.ElementTree.fromstring with its defusedxml equivalent function or make sure defusedxml.defuse_stdlib() is called |
| B310 | `src/tradingagents/dataflows/stocktwits.py:90` | Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected. |
| B608 | `src/tradingagents/graph/checkpointer.py:99` | Possible SQL injection vector through string-based query construction. |

Dependency consistency and the current 122-version advisory audit passed. The application source has not been modified to clear type/security/regression findings.


## Release core records (79103c3)

# Debt Register

Records technical debt and known uncertainty. Fail closed: when a decision,
evidence, or requirement is missing or unknown, it is listed here with an owner
and an action rather than invented. Linked from `docs/architecture/risk-list.md`.

| ID | Debt / uncertainty | Impact | Owner / action |
| --- | --- | --- | --- |
| DEBT-001 | Date-sensitive cache tests fail depending on the current clock; a green full-suite result is not reproducible across days. | Flaky/misleading verification. | **Resolved (technical, verified offline 2026-11-11, DEBT-034)**: the `tests/test_ohlcv_cache_freshness.py` fixture converted a naive `Timestamp` with `NOW.timestamp()` (naive → UTC) while production reads mtimes with `pd.Timestamp.fromtimestamp` (local), shifting the wall time by the host UTC offset (8h under `Asia/Hong_Kong`, −4h under `America/New_York` DST) and misreading fresh/expired caches. Fixed to the local-wall-clock epoch (`to_pydatetime().timestamp()`) with a UTC / `Asia/Hong_Kong` / `America/New_York` summer+winter matrix; freshness/TTL semantics unchanged. Row retained for audit history. |
| DEBT-002 | One baseline test (`tests/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache`) depends on vendor reachability; it makes one intercepted outbound attempt (via requests/urllib3) and fails in offline sandboxes. | A correct change can look broken offline; the NFR-OFF-001 count-and-fail harness observes 1 attempt (no connection made) so NW-zero is not achievable without changing this baseline. | **Resolved (technical, verified offline 2026-11-11, DEBT-034)**: the test mocked `yf.download` but not `stockstats_utils.vendor_reachable`, so it probed Yahoo and raised `VendorRateLimitError` under strict socket denial instead of `NoMarketDataError`. Now `vendor_reachable` is mocked (True → genuine no-data → `NoMarketDataError`; False → outage → `VendorRateLimitError`), the per-test fixture uses `tmp_path` (no shared `tests/_tmp_cache`), and the strict-offline harness reports **0 forbidden socket attempts**. Row retained for audit history. |
| DEBT-003 | Real-vendor provider paths are exercised only by mocks/stubs in the offline suite. | Real-integration regressions may go unnoticed. | Live `@pytest.mark.integration` remains opt-in; see `test/live/README.md`. |
| DEBT-004 | **OpenCode `permissions.jsonc` schema could not be fully verified against the installed OpenCode version** (no access to external config). | A malformed permission file could break tools or be silently ignored. | `TODO (60536848-WANG-Yiwen): verify schema against installed OpenCode; use the conservative minimal documented form until then; do not invent unsupported keys.` |
| DEBT-005 | Provisional student identity (transcript `transcripts/60536848-WANG-Yiwen.md`). | Submission identity risk. | **Resolved** (2026-10-21): official student ID confirmed (60536848, WANG Yiwen); transcript renamed to `transcripts/60536848-WANG-Yiwen.md` and provisional-identity warnings/TODOs removed. Row retained for audit history. |
| DEBT-006 | Ruff whole-repo formatting (`ruff format`) intentionally not applied (deferred in `pyproject.toml`). | Code style is not uniform, but avoids mass-reformat conflicts. | Preserve; do not mass-reformat unrelated files. |
| DEBT-007 | Rule precedence in the Debate Evaluator is subtle and easy to mis-order. | Wrong cost/quality behavior. | Deterministic ordering + targeted evaluator tests. |
| DEBT-008 | `DEBATE_METADATA` marker-absent prose fallback heuristic is imperfect. | A stance may be unclear on marker-absent turns. | Parse failure contributes zero new evidence and cannot extend the debate (`FR-DDT-002`). |
| DEBT-009 | The Stage 2 multi-category gate engine (`evaluate_multi_category_gate`) was proven at the engine + test level but **was not yet the runtime graph default**; the runtime gate node used the single-category `build_gate_decision`. | A reader could mistake engine-level proof for full integration. | **Resolved** (2026-10-21): the runtime graph default now delegates to `evaluate_multi_category_gate` via `create_data_quality_gate_node`, evaluating the critical market category plus the optional categories; optional evidence enters only via the explicit `data_quality_optional_evidence` contract. Engine + graph tests prove normal/degraded/blocked routing, determinism, and point-in-time rejection (logbook 043). Row retained for audit history. |
| DEBT-010 | The `ConflictRecord` model existed but nothing lifecycle-managed it at runtime; there was no tracker to create, observe, resolve, or escalate conflicts, so the conflict surface was only a data type. | A reader could mistake the model for a working conflict feature. | **Resolved** (2026-10-21): a pure, LLM-free tracker (`tradingagents/debate/conflicts.py`) derives conflicts only from structured `conflict_assertions`, fails closed on unverifiable evidence, deduplicates/merges, and resolves/escalates with reason capture; the evaluator node persists the derived conflicts + a safe `ConflictSummary`, and the Research Manager injects it safely (`FR-DDT-005`; `tests/test_debate_conflicts.py` 39 passed, logbook 046). Row retained for audit history. |
| DEBT-012 | Review finding 2 (2026-11-06): the debate call hard limit could be exceeded before evaluation — a valid `max_calls=1` config executed Bull and Bear (2 calls) before emitting `budget_exhausted`. Token/time reservation also uses estimates, not a conservative preflight or bounded outputs. | Optional over-budget calls the design prohibits (sections 1.2/4.6/4.9/7.2). | **Resolved** (2026-11-06, milestones 2 + second review): a conservative pre-call admission guard runs before every Bull/Bear so `max_calls=1` never executes 2 debate calls; a refused call skips to the Research Manager with `budget_exhausted` for the incomplete round; `enabled=False` keeps the legacy baseline. The second review found the guard compared remaining capacity only to the summary reserve, so remaining == reserve (with an estimated next-call cost) was wrongly admitted; corrected to require remaining >= reserve + estimated next-call cost, with exact token/time boundary tests before the first Bull and before Bear. `tests/test_debate_precall_budget.py` 22 passed (logbook 060/063). Token/time figures remain honest estimates, not physical provider bounds; the call limit concerns debate calls only, not total-run budget. Row retained for audit history. |
| DEBT-013 | Review finding 3 (2026-11-06): the audit export lost per-evidence validations — `data_quality_validation_results` had entries but every exported `evidence_manifest` record had an empty `validation_results`, and `run_summary` omitted run_id, asset_type, snapshot ID, per-record quality counts, tool calls, and separate input/output token counts. | Incomplete traceability (design sections 5.1/5.3). | **Resolved** (2026-11-06, milestone 3): `evidence_manifest.json` attaches each record's validations by `evidence_id` and exports the separate `validation_results_by_evidence_id` map; `run_summary.json` adds `run_id`/`asset_type`/`snapshot_id` (null when unavailable), `quality_counts`, and `usage_provenance` (debate calls kept separate from total-run calls; unmeasured tool/input-output counts explicit `None`, never fabricated). `tests/test_report_artifacts_audit.py` 20 passed (logbook 061/063). The second review found `_records_with_validations` overwrote a record's embedded validations with `[]` when the separate map lacked an entry; corrected to prefer a present authoritative map entry, otherwise preserve/normalize the record's own embedded validations (never another ID's), with deterministic ordering. Row retained for audit history. |
| DEBT-014 | Review finding 4 (2026-11-06): the degraded-run confidence ceiling is only a prompt instruction; no numeric cap is enforced or defined by any schema/policy through the Trader/Portfolio Manager. | A degraded run could still read as over-confident. | **Resolved (technical, Stage 4 / ADR-011, offline-verified 2026-11-11; NOT a human acceptance)**: the human specified the ceiling as **0.60** and approved the plan + tests (not final acceptance). A pure deterministic policy (`tradingagents/debate/confidence_policy.py`) enforces it: only explicit confidence-labelled numerics are capped (decimal/percent/fullwidth/leading-dot/scientific/JSON/Markdown/multiline/duplicate; malformed/bool/NaN/out-of-range quarantined; missing stays missing; categorical low/medium/high distinct; normal/blocked unchanged). Enforced on debate turns + stances (numeric + readable text), the evaluator snapshot, RM/Trader/PM schemas + prose, the report writer (independent recompute) and the memory log; a shared per-read state-input sanitizer caps the persisted analyst report / plan / debate+risk history text AND turn/stance numerics before every post-gate prompt (direct GraphSetup + SQLite resume); the API and CLI resume paths run the SAME fail-closed sanitizer first. Typed RM/Trader/PM schema confidence is capped on its EXACT raw value BEFORE the lossy `:.2f` render (0.6000001/0.604/0.954321 genuinely capped, exact raw in the audit). A deterministic post-gate Confidence Sanitizer node AND the per-node wrapper's changed-input delta merge persist the capped analyst-report / plan / history fields (and capped node OUTPUTS, e.g. risk arguments) into the RETURNED state and `_log_state`/public JSON on FRESH and direct-legacy-resume paths alike (originals only in the audit). Offline: focused 110 passed / 0 sockets, full 2154 passed (logbook 082). Historical note (kept for audit): the 2026-11-06 fix deliberately did NOT invent a ceiling before policy specified it. Owner: `TODO (60536848-WANG-Yiwen): independent OpenCode review + human acceptance; 0.60 is an engineering ceiling, NOT a calibrated probability and NOT production tuning.` |
| DEBT-015 | Broader original-design item 5 (2026-11-06 review): automatic multi-category fundamentals/news/sentiment EvidenceRecord adapters and the full source-attempt lifecycle are not wired into the gate; the market adapter uses one snapshot source with hardcoded asset_type/volume units; freshness uses a weekday calendar without exchange holidays; researcher usage records char estimates; the append-only event types and audit_incomplete fallback were not found. | A reader could mistake the limited implementation for full original-design conformance. | **Partially resolved — Stage 1 (2026-11-11, approved plan+tests ONLY, NOT human acceptance)**: automatic structured optional-evidence ingestion (fundamentals/news/sentiment) and the source-attempt lifecycle are now wired into the real gate via ADR-008 (`tradingagents/evidence/{ingest,vendor_adapters}.py`, `tradingagents/dataflows/evidence_capture.py`, `tradingagents/graph/evidence_tool_node.py`); offline-verified (`tests/test_structured_evidence_ingestion.py`: 53 passed; full strict-offline 1897 passed / 0 socket attempts, logbook 079). REMAINING (still OPEN): exchange-holiday calendar, researcher char-estimate usage, append-only event types / audit_incomplete fallback. Historical note (kept for audit): at Stage 1 all four approved plan items (durable cross-resume budget accounting, claim-date/value/unit check, degraded confidence cap) were NOT yet implemented; Stages 2 (ADR-009), 3 (ADR-010) and 4 (ADR-011) have since been implemented offline and await independent OpenCode review + human acceptance (implementation approval, not final acceptance). Owner: `TODO (60536848-WANG-Yiwen): independent review + human acceptance of Stage 1; all four items were approved in plan/test scope on 2026-11-11 (Stages 1-4 now implemented; not final acceptance).` |
| DEBT-011 | Phase 4A comparison results are deterministic **offline scripted fixtures**, not live-provider measurements; human traceability is pending a human score against the rubric; no production thresholds were tuned. | A reader could mistake a scripted-fixture delta for a production-grade performance claim. | `Open (recorded)`: every Phase 4A report/readme states the offline/scripted scope, the `pending` traceability, and that no production thresholds were tuned. `TODO (60536848-WANG-Yiwen): a human must score each case against the traceability rubric before any traceability value is reported as scored; live-provider benchmarking (Phase 4B) requires separate, explicit authorization.` |
| DEBT-016 | 2026-11-06 independent recheck finding 1: a blocked-run decision could still escape as a final Buy when the model used an alternative rating-header format (`Rating：Buy` fullwidth colon, `Final rating: Buy`), because the guard and `extract_rating` recognized different header grammars and merely prepending Hold did not neutralize the later header. | Blocked runs could still yield a directional final signal. | **Resolved** (2026-11-06): the guard recognizes the same grammar the extractor reads (fullwidth colon, prefixed labels, unicode dashes, repeated/trailing labels) and the final signal boundary is gate-aware (`SignalProcessor.process_signal(text, state)` -> Hold on blocked; memory log records Hold). Complete-graph regressions in `tests/test_output_guard.py` (78 passed). Row retained for audit history; awaiting human review. |
| DEBT-017 | 2026-11-06 independent recheck finding 2: `evaluate_multi_category_gate` discarded the aggregator's per-record status map and serialized the provisional adapter records (`Low`/`unvalidated`), so a normal/Medium gate run produced empty `EvidenceManifest.valid_ids`, an empty allowlist, and round-1 `no_new_evidence`. | Valid evidence was unusable by the debate; dynamic termination stopped on a false absence of evidence. | **Resolved** (2026-11-06): each record's own classification/reasons/validations are applied before serialization (never a blanket group promotion); a real gate -> manifest/allowlist -> researcher -> evaluator -> report regression proves it (`tests/test_gate_debate_integration.py` 9 passed). Row retained for audit history; awaiting human review. |
| DEBT-018 | 2026-11-06 independent recheck finding 3: the guard stripped whitespace and concatenated Hold with the tail (`Rating: Holdbecause ...`), yielding REVIEW instead of Hold. | Restricted Hold output contract broken; unnecessary manual-review signals. | **Resolved** (2026-11-06): the semantic separator (and markdown boundary) is preserved across all decision-field variants; guarded output is idempotent and parses to Hold (`tests/test_output_guard.py`). Row retained for audit history; awaiting human review. |
| DEBT-019 | 2026-11-06 operator recheck (residual): the blocked guard still escaped on fullwidth labels/values (`Ｒａｔｉｎｇ：Ｂｕｙ`) and on arbitrarily prefixed labels (`My final overall investment rating: Buy`), because the guard matched a bounded descriptor list and only the fullwidth colon; the plain textual signal and the memory DECISION body could still read Buy while the structured signal (and memory tag) were Hold. | Saved report/decision text and the blocked memory body could contradict the Hold tag. | **Resolved** (2026-11-06): the guard now uses the rating parser's own shared NFKC/label recognition (`labelled_decision_tail`) to canonicalise every line the parser reads as a labelled rating call to `**Rating**: Hold`, preserving a natural-language tail; idempotent. Fullwidth/prefixed/repeated/trailing and full-graph report+memory consistency covered (`tests/test_output_guard.py` 90 passed). Row retained for audit history; awaiting human review. |
| DEBT-020 | 2026-11-06 operator executable-instruction maintenance: the blocked guard left executable directional instructions in the stored intermediate plans — fullwidth/NFKC `Action`/`Recommendation` headers, fullwidth `Entry Price`/`Stop Loss`/`Position Sizing` sizing, an `FINAL TRANSACTION PROPOSAL: BUY` marker with an explanation tail, and long decision-label descriptors all survived a prepended Hold. | A blocked run's stored Trader/Research plan still exposed an executable direction or sizing. | **Resolved (technical, awaiting human review)** (2026-11-06): one shared linear recognizer (`rating.decision_header`/`_split_header`) pins every decision field to `**<Label>**: Hold`, neutralises fullwidth/long-form sizing to `not applicable`, and pins explained proposal markers; quoted/narrative alternatives and rationale are preserved, `extract_rating` no longer lets a quoted/narrative mention override the decision, and the operation is idempotent and fast on long prose. The CLI state-passing gap, the degraded numeric confidence ceiling (DEBT-014) and automatic optional adapters (DEBT-015/RISK-015) remain OPEN and were not touched. `tests/test_output_guard.py` 130 passed; strict offline suite 4 failed / 1661 passed (logbook 067). |

## 2026-11-06 live-verification findings and documentation/revision debt

New records from the 2026-11-06 authorized school-model live verification and the
2026-11-06 documentation/requirements revision. Source is NOT changed for the
live findings; they are recorded, not fixed.

| ID | Debt / uncertainty | Impact | Owner / action |
| --- | --- | --- | --- |
| DEBT-021 | Live debate budget accounting ignores actual provider usage. `record_call_usage` estimates time from prompt+response characters / 30 and estimates tokens from characters, instead of using provider-reported `exact_tokens` / measured `exact_seconds`. 2026-11-06 NVDA live run: Bull actual 12.72 s vs 2,171.77 estimated seconds; 18,058 reported tokens vs 16,289 estimated. The pre-call guard then refused Bear with `budget_exhausted` before any complete Bull/Bear round (0 rounds). The guard is active and safe; the accounting BASIS is the defect. | Dynamic termination ends on a mis-estimated budget in real runs; dynamic-vs-fixed cost comparison is unreliable live. | `Open (recorded)`. `TODO (60536848-WANG-Yiwen): in a separately authorized implementation round, pass provider usage + an injectable measured clock into `exact_tokens`/`exact_seconds`, keep explicitly-labelled estimates as fallback, and add complete/incomplete-round budget tests. Do NOT raise the production threshold to hide the gap.` Addressed (2026-11-10, ADR-007, offline): measured injectable clock + provider usage provenance, labelled fallback, complete/incomplete-round + provenance tests; caps NOT raised. LIVE-CONFIRMED (2026-11-10 D1, logbook 074): real Bull+Bear, one complete round, stop max_rounds_reached, measured seconds + provider tokens. REMAINING: cross-resume/failed-checkpoint budget accounting NOT solved; all-agent production totals untracked.` **2026-11-11 Stage 2 (ADR-009, offline): durable cross-resume/failed-checkpoint accounting ADDRESSED offline** via a run-scoped SQLite reservation/settlement ledger (`tradingagents/debate/usage_ledger.py`) — reservations precede calls, settlements survive a post-provider crash, resume reconciles idempotently, unknown/unresolved spend fails closed, and whole-run usage is aggregated for reporting (`tests/test_durable_usage_ledger.py` 33 passed; `tests/test_whole_run_usage.py` 10 passed; full strict-offline 1940 passed / 0 sockets, logbook 080). NOT live-confirmed; not final acceptance. |
| DEBT-022 | Live citation allowlist does not validate claim-date semantics. In the NVDA 2026-11-06 run, Bull cited the valid close evidence ID but relabelled the `observed_at=2026-11-04` close (200.13) as "2026-11-05" in prose and in structured `new_claims`. The allowlist verifies record eligibility (known/High-or-Medium/on-or-before target), not the semantic truth of a claim's stated date/value. | A saved research report can carry a factually wrong observation date despite citing a valid ID. | **Addressed offline for typed exact claims — Stage 3 (2026-11-11, ADR-010; approved plan+tests ONLY, NOT human acceptance)**: `tradingagents/evidence/origin.py` carries versioned, evidence-ID-keyed typed origin metadata (distinct target / observation / availability / filed_at / published_at / retrieved_at roles + unit/currency/scale; the 20 locked `EvidenceRecord` fields are unchanged); `tradingagents/debate/claims.py` deterministically validates a typed `ClaimRecord` (date role/value/unit/scale) against the cited record + origin. A wrong exact date/value/unit on a valid ID no longer counts as valid new evidence, cannot create/resolve a factual conflict, and is redacted from the trusted plan/trader/final decision; the Research Manager receives a verified/rejected/unverified summary. `tests/test_exact_claim_validation.py` 48 passed + `tests/test_exact_claim_runtime.py` 9 passed; full strict-offline 2044 passed / 0 sockets (logbook 081). REMAINING (honest): only typed exact claims and common inline exact prose are deterministically validated; arbitrary natural-language semantics are NOT proven (unparseable prose stays `unverified`), and default yfinance/AV fundamentals remain undated. Independent review + human acceptance pending. Owner: `TODO (60536848-WANG-Yiwen): independent OpenCode review; human acceptance; live validation.` |
| DEBT-023 | Evaluation debt: the full offline suite is not all-green (known date-sensitive cache failures + a network-reachability baseline), and no type-check, dependency/vulnerability, fixed semantic-eval, or diff-aware AI-use-log gates exist. The requirements-schema fallback (no `jsonschema`) enforces only a subset, not the extended `fit_criterion` conditionals. | Verification gaps could let a regression or a non-compliant requirement pass unnoticed. | `Open (recorded)`. `TODO (60536848-WANG-Yiwen): decide on the cache/network baselines; implement the CI gates defined in docs/code-governance/verification-constraints.md (authorized round); ensure `jsonschema` is installed wherever the schema is relied on.` |
| DEBT-024 | Prompt rot: `prompts/prompt_v1.3.yaml` is authoritative in `Prompt.md`, but `.opencode/rules.md` (HUMAN-ONLY) still references `prompts/prompt_v1.2.yaml`. | An agent reading `.opencode/rules.md` sees a stale prompt version. | **Partially resolved** (2026-11-10): `prompt_v1.3.yaml` is now in the validator's `REQUIRED_FILES`/`YAML_FILES`/`SCAN_FILES` lists. The `.opencode/rules.md` stale v1.2 reference stays OPEN because that file is HUMAN-ONLY: `TODO (60536848-WANG-Yiwen): adopt the human-rules proposal to advance the reference to v1.3.` |
| DEBT-025 | Hidden dependency / coupling: the blocked-run memory log now imports `tradingagents.agents.utils.output_guard.HOLD`, coupling `memory.py` to the guard module; the guard and `rating` share a recognizer whose grammar must stay aligned. | A future change to either module could silently break the other. | `Open (documented)`. `TODO (60536848-WANG-Yiwen): keep the shared recognizer single-sourced; cover the coupling with tests (already in test_output_guard/test_memory_log).` |
| DEBT-026 | Agent-induced bloat (lesson): a first guard regex caused catastrophic backtracking and a descriptor cap required rework before the final single linear recognizer (logbook 067). This churn was corrected in-pass, not shipped. | Rework cost; risk of recurrence if a future agent reintroduces regex-based recognition. | `Resolved (lesson recorded)`. Prefer the single shared linear recognizer; avoid backtracking regexes. |
| DEBT-027 | Guardrail debt: `.opencode/permissions.jsonc` is broad (not path-scoped) and its load/enforcement is UNVERIFIED; the deny-by-default role-by-path whitelist exists only as a proposal; plan-first, ADR-for-safety, and CI gates are process-only, not enforced. | A prohibited action could proceed if the human misses it; no machine guarantee. | `Open (recorded)`. `TODO (60536848-WANG-Yiwen): run the benign enforcement probe; adopt or reject the proposal; implement CI gates in an authorized round.` |
| DEBT-028 | Human/cognitive debt: Phase 4A human traceability scores remain pending; no production performance thresholds are approved/measured; the 2026-11-06 maintenance and this documentation revision are NOT human-approved; team roster/consensus/contribution data are not entered. | Deliverables depending on human decisions remain incomplete and cannot be claimed. | `Open (human)`. `TODO (WANG Yiwen + team): enter traceability scores, agree thresholds, record human approvals and team process data. Do not fabricate.` |
| DEBT-029 | 2026-11-10 repair batch: a blocked Trader output's executable multiline instructions survived the guard — block-style `**Action**:` / `FINAL TRANSACTION PROPOSAL:` values on a following physical line (including blank-line-separated, bulleted/numbered `- Buy`/`1. Buy`, and direction+explanation values, and split `Entry Price:` / `Position Sizing:` values) plus unsupported plain `Buy 100 shares at $100. Exit at $120.` sentences stayed in the stored plan and saved report while the final signal was Hold. | A blocked run's stored plan contradicted the authoritative Hold with executable direction/sizing. | **Resolved (technical, awaiting independent review + later human acceptance)** (2026-11-10): label-only headers fold their continuation value (blank lines skipped; bullet/number/heading prefixes tolerated) into a pinned Hold / HOLD marker / not-applicable sizing, keeping a direction value's explanation as the rationale tail, and drop the value line; an **anchored** executable-sentence fallback (trade verb at line start + quantity/price token) fails closed for unsupported formats with **structural-only** exemption (a verb inside a quotation, or a line that does not lead with a command verb — so `We rejected "Buy ..."` / `Earlier proposal: Buy ... It was not executed.` survive, while a live command that later mentions `earlier`/`considered` or quotes a phrase is still contained). Blockquotes preserved. Linear, idempotent, LF/CRLF/whitespace/Markdown/fullwidth covered. A recognised decision value's executable sizing/price/quantity tail (and a pure residual direction-word tail, e.g. `Strong Buy`) is stripped keeping only a clearly separated rationale clause, and a bounded unsupported-value fail-closed policy drops an unrecognised value-like line (`**Strong Buy**`) in a recognised decision position. `tests/test_output_guard.py` 197 passed (24 multiline + 14 boundary + 15 second-review + final-F1 direct/fake-Trader executable-tail and unsupported-value cases, plus normal/degraded-unchanged); strict offline suite 1743 passed / 4 known baselines (logbook 070). DEBT-014/DEBT-015/RISK-015 remain OPEN. |
| DEBT-030 | 2026-11-10 repair batch: `report_artifacts._validation_map` dropped explicitly empty authoritative per-evidence lists (`{id: []}`), so `_records_with_validations` preserved a stale embedded `passed` check the gate had cleared. | Saved `evidence_manifest.json` could show a validation the gate no longer asserts. | **Resolved (technical, awaiting independent review)** (2026-11-10): a PRESENT map entry (including a malformed value that cannot carry a validation) is authoritative and exported as `[]`, overriding embedded; an ABSENT entry keeps the legacy embedded fallback; nonempty override, no cross-ID leakage, deterministic ordering and redaction preserved; helper + saved-artifact tests (`tests/test_report_artifacts_audit.py`). |
| DEBT-031 | 2026-11-10 repair batch: the real `jsonschema` path accepted duplicate requirement IDs the deterministic fallback rejected, because `uniqueItems` compares whole objects and two same-ID requirements can differ in every other field. | A duplicate-ID registry could pass CI's real-schema gate. | **Resolved (technical, awaiting independent review)** (2026-11-10): a shared `validate_unique_requirement_ids()` runs on BOTH entry paths (the fallback delegates its uniqueness check to the same helper); duplicate IDs with differing objects are rejected on the real and forced-fallback paths; the 22 existing IDs and schema constraints are unchanged; no count hardcoded (`tests/test_governance_scaffold.py`). |
| DEBT-032 | 2026-11-10 doc/traceability batch: (a) the inspected permission schema cannot express per-path edit/read, so the proposal's path rules and the planner read-only execute intent are process-enforced only (planner expressed as deny-all bash); (b) the course slide layout (`src/`, `test/offline`, `test/live`) still needs instructor confirmation — only pointer README dirs exist; (c) the reference check is NARROW (product priorities/tradeoffs only); test tags are not yet a CI gate. | A reader could over-read the docs as enforcement; the course layout remains an unconfirmed exception. | `Open (recorded)`. Documented NOT as enforcement; see `permission-model.md` expressibility gap and `structural-constraints.md`. `TODO (60536848-WANG-Yiwen): confirm the course layout with the instructor; a CI traceability gate is not implemented.` |

## 2026-11-10 school-model live run findings (recorded, not fixed)

From the user-authorized OpenCode live end-to-end run (NVDA 2026-11-05, degraded
gate; logbook 073). Source is NOT changed for these; they are recorded.

| ID | Debt / uncertainty | Impact | Owner / action |
| --- | --- | --- | --- |
| DEBT-021 (2026-11-10 confirmation — HISTORICAL / PRE-REPAIR observation) | At the time of this run: still OPEN. Live run re-confirms the char-based time/token ESTIMATE basis: Bull actual callback **19.70 s / 16,931 tokens** (in 14,969 / out 1,962) vs runtime estimate **2,024.4 s / 15,183 tokens**. With `max_time` 600 s, `reserved_summary_seconds` 90, `next_call_estimate_seconds` 30, the pre-call guard **correctly refused Bear**, but the badly inflated time estimate stopped it **prematurely**: the Bear node was visited, yet **0 actual Bear model calls** occurred and `bear_history` is empty (`stop_reason = budget_exhausted`). The ACTUAL runtime did NOT exceed 600 s — only the faulty estimate did. Report honestly keeps total-run calls/input/output null and reports debate-only estimated 1 call / 15,183 tokens / 2,024.4 s. | Dynamic termination ends prematurely on a mis-estimated budget; dynamic-vs-fixed live cost comparison unreliable; 0 complete rounds. | `Open (recorded)`. Same action as above: pass provider usage + an injectable measured clock into `exact_tokens`/`exact_seconds`, keep labelled estimates as fallback, add complete/incomplete-round tests. Do NOT raise the threshold to hide the gap; do NOT claim the actual runtime exceeded the cap. Addressed (2026-11-10, ADR-007, offline). |
| DEBT-033 | 2026-11-10 live run secondary observation (NOT yet a proven separate code defect): the Research Manager prose says "the bear overplayed its hand" although no actual Bear response exists (Bear was refused pre-call; `bear_history` empty). | Potentially misleading attribution to an unexecuted opponent; a reader could think a Bear turn occurred. | `Open (review only)`. `Addressed (2026-11-10, ADR-007, offline): deterministic participation truth + SAFE PARTIAL-DEBATE TEMPLATE replace trusted bilateral prose on positively-partial debates; raw narrative quarantined. Rating policy preserved. LIVE-CONFIRMED (2026-11-10 D2, logbook 074): participation explicitly data_quality_blocked, no absent-opponent attribution in trusted report. Human review pending.` |
| DEBT-034 | 2026-11-11 CI/baseline repair: (a) the CI Python jobs (no optional `jsonschema`) exercise the deterministic subset fallback, which checked `project.schema_version` only as non-empty and accepted `"1.0"` that the real schema pattern `^v[0-9]+\.[0-9]+$` rejects (all 4 Python jobs red on the same test); (b) `tests/test_ohlcv_cache_freshness.py` mis-converted the fixture wall time to the epoch, shifting by the host UTC offset; (c) `tests/test_no_data_handling.py` probed real vendor reachability (1 intercepted socket attempt). | CI red on a value the governance job rejects; date/TZ-dependent cache tests; NFR-OFF-001 socket count non-zero. | **Resolved (technical, verified offline 2026-11-11; NOT a human acceptance / remote-CI-green claim — push not authorized)**: (a) the subset fallback now reads the pattern from the actual schema and rejects non-matching/non-string/missing versions on BOTH paths (ADR-006); (b) the cache fixture uses the local wall-clock epoch with a UTC/Hong Kong/New York summer+winter matrix; (c) the no-data test mocks `vendor_reachable` (True → `NoMarketDataError`, False → `VendorRateLimitError`), uses `tmp_path`, and the strict-offline harness reports **0 socket attempts**. Focused + full strict-offline suite pass offline; remote GitHub CI is NOT re-run here (push not authorized) and independent OpenCode verification is pending. |

| DEBT-035 | ADR-008 Stage 1 residual gaps (2026-11-11, approved plan+tests ONLY, NOT human acceptance): (a) the tool/analyst boundary persists captured evidence at the tool and analyst nodes, but a checkpoint taken mid-audit *between* an unrelated node and the gate before any capture boundary is still only as fresh as the last boundary flush (the gate itself also re-reads the live collector); (b) capture is proven offline with mocked raw transports and a compiled production-schema graph, not against live vendors; (c) `route_to_vendor` attempt `source` is the vendor id while the adapter success `source` is the dataflow name (e.g. `yfinance_news`), so an auditor must read the pair together; (d) default yfinance/Alpha Vantage fundamentals carry no filing date and are captured undated (honestly Low), so they never add decisive optional evidence. | A reader could over-read Stage 1 as full live-wired optional corroboration and complete coverage. | `Open (recorded)`. Stage 1 is offline-verified (`tests/test_structured_evidence_ingestion.py`: 53 passed; full strict-offline 1897 passed / 0 socket attempts, logbook 079) and awaits independent review + human acceptance. Stages 3–4 remain unimplemented (Stage 2 implemented 2026-11-11, ADR-009). Owner: `TODO (60536848-WANG-Yiwen): independent review; human acceptance; live-vendor validation; Stages 3–4. Do not claim full original-design conformance.` |

| DEBT-036 | ADR-009 Stage 2 residual gaps (2026-11-11, approved plan+tests ONLY, NOT human acceptance): (a) hidden SDK transport retries are unobserved (`transport_attempts` stays `null`/unknown — logical calls, not transport attempts); (b) a pre-call reservation is a deterministic ESTIMATE, not a physical billing bound on provider spend; (c) the whole-run aggregation, atomic admission, and resume reconciliation are proven OFFLINE with mocked models + a real `SqliteSaver` and threading barriers, not against live providers or truly separate processes; (d) `whole_run_usage` is reporting only and never a whole-run spend cap. | A reader could over-read Stage 2 as a live billing guarantee or a whole-run budget cap. | `Open (recorded)`. Offline-verified (`tests/test_durable_usage_ledger.py` 33 passed; `tests/test_whole_run_usage.py` 10 passed; full strict-offline 1940 passed / 0 sockets, logbook 080); awaits independent OpenCode review + human acceptance. Owner: `TODO (60536848-WANG-Yiwen): independent review; human acceptance; any live-provider concurrency/retry observation requires separate authorization (Phase 4B-like). Do not claim a physical billing bound.` |

## Eight course debt categories (mapping)

The course lists exactly eight AI-era debt categories. This mapping points to
genuine records above; a category with no genuine instance is marked so — **no
debt is invented to fill it**.

| Category | Genuine record(s) | Status |
| --- | --- | --- |
| prompt rot | DEBT-024 | Observed |
| hallucinated dependencies | Clean-install `smoke-install` job guards undeclared runtime deps; no dependency/vulnerability scan yet. | No confirmed hallucinated dependency; scan MISSING (see DEBT-023) |
| untouchable code | `evidence/` + `debate/` pure modules are isolated and unit-tested; no confirmed untouchable hotspot. | No observed instance |
| hidden dependencies | DEBT-025 (`memory.py` → `output_guard.HOLD`; shared recognizer coupling) | Observed (documented) |
| agent-induced bloat | DEBT-026 (backtracking-regex churn, resolved) | Observed (resolved) |
| evaluation debt | DEBT-023, DEBT-001, DEBT-002 | Observed |
| guardrail debt | DEBT-027, DEBT-004 | Observed |
| human/cognitive debt | DEBT-028, DEBT-011, DEBT-014 | Observed (pending human) |
| DEBT-037 | 2026-11-11 confirmed live-run Defect-1: the gate built 5 market origins then `output.update(persisted)` overwrote them with the live collector's empty origin delta, so `data_quality_origin_metadata` was `{}` and all 5 exact claims were `claim_origin_unknown`. A latent first/last-wins origin precedence (capture_origin `setdefault`; merge_into_state last-wins) also silently destroyed genuine captured-origin conflicts. | Useful exact-claim validation defeated on the real runtime path; a conflicted origin could be silently trusted. | **Addressed offline (2026-11-11, ADR-010 amendment; approved plan+tests ONLY, NOT human acceptance):** authoritative origin merge AFTER persistence; conflicts retained and failed closed via the declared `data_quality_origin_conflicted_ids` channel; `origin_records_from_state` drops conflicted ids at the read choke point; seeding unconditional from state; no first/last-wins / derived re-trust / resurrection; existing-state tombstones are honoured even with no active collector (direct consumer excludes dropped ids at the read choke point; derivation skips dropped records); 20/7 records unchanged. `tests/test_gate_origin_authority.py` 18 passed; full strict-offline 2190 passed / 0 sockets (logbook 083). NOT live-confirmed; independent review + human acceptance + future live verification pending. |
| DEBT-038 | 2026-11-11 confirmed live-run Defect-2: RM/Trader/PM structured Pydantic results lost raw transport usage before settlement, so 3 structured calls were estimated despite provider reporting usage (blocked fixture: 6 calls / 22,600 reported vs 22,067 recorded, with `totals.tokens_source=provider` a misleading mixed label). | Non-exact whole-run reconciliation and a misleading aggregate source label. | **Addressed offline (2026-11-11, ADR-009 amendment; approved plan+tests ONLY, NOT human acceptance):** `include_raw=True` (same single call) settles usage from the raw AIMessage while typed output renders/caps; binding-only fallback (no free-text downgrade, no extra call) for providers rejecting only include_raw; settlement precedes parse/sanitize/render so known raw usage is never unknown-cost; unknown transport stays unknown; `mixed` is AGGREGATE/report-only (never per-call; not a durable-ledger source), known tokens preserved. `tests/test_structured_raw_usage.py` 18 passed; full strict-offline 2190 passed / 0 sockets (logbook 083). NOT live-confirmed; independent review + human acceptance + future live verification pending. |
| DEBT-039 | 2026-11-11 confirmed live-run price corruption (Defect 1): `rewrite_confidence_text` handled the input `Re-entry requires a close above $204.38. Confidence is set at the plan's 0.55.` as `$204.unknown (invalid confidence quarantined) ...` in the Trader plan and exported reports, corrupting an ordinary price. Root cause: the suffix numeric literal absorbed a trailing sentence period (`38.`) and had no left token boundary (a match could start mid-token after `$204.`/`38`); the malformed `38.` was then quarantined. | Report/plan integrity: an ordinary financial figure was rewritten and quarantined despite the contract that ordinary figures are unchanged. | **Addressed offline (2026-11-12, ADR-011 amendment; approved corrected plan + test cases ONLY, NOT human acceptance):** fractional part all-or-nothing (no trailing-period absorption); terminators (`. ! ? ;`) are boundaries, not connectors; CRLF-aware soft vertical whitespace still binds a genuine suffix; left token boundary excludes currency/sign/date/path-glued numerics so `$204.38` / `2026-11-05` / `2026/11/05` fragments are never candidates. Bare `204.38 confidence` remains invalid/quarantined; genuine forms still cap to 0.60. `tests/test_confidence_boundary.py` 51 passed; existing confidence suites 110 passed; full strict-offline 2290 passed / 0 sockets (logbook 085). NOT live-confirmed; independent review + human acceptance + future live verification pending. |
| DEBT-040 | 2026-11-11 confirmed live-run exact-claim coverage gap (Defect 2): the Bear model wrote 8 `claim=metric=...|...` lines BEFORE `DEBATE_METADATA:`; the marker-only parser recorded `metadata_parse_status=ok` with `exact_claims=[]` and an empty claim-validation summary, so those typed claims never entered date/value/unit validation (not proof a wrong claim was verified — proof it was not checked). | Out-of-contract typed claims silently dropped into an empty success; live date/value/unit enforcement not actually exercised. | **Addressed offline (2026-11-12, ADR-010 amendment; approved corrected plan + test cases ONLY, NOT human acceptance):** shared strict `extract_standalone_typed_claims` recovers standalone typed lines (before/after/no-marker; no-stance FAILED branch included) into the SAME validation; marker claims never hide outside claims (dedupe only by canonical identity); fenced (``` / ~~~ / unclosed) and quoted examples never admitted; contradictory `role`/`date_role` aliases are unparseable; missing/unknown/future/Low/foreign/wrong fields rejected/unverified, never verified; honest additive coverage serialized in `DebateTurn`/`claim_validation_summary`/`debate_trace.json`, consumed at `enforce_trusted_boundary`, preserved across a real SQLite resume; frozen EvidenceRecord(20)/SourceAttempt(7) unchanged. `tests/test_standalone_claims.py` 49 passed; full strict-offline 2290 passed / 0 sockets (logbook 085). NOT live-confirmed; extraction ≠ trust; arbitrary prose beyond strict typed lines stays unverified; independent review + human acceptance + future live verification pending. |
| DEBT-041 | 2026-11-12 school live run residual: a CORRECT long-decimal typed claim (`claim=metric=volume|role=observation_date|date=2026-11-05|value=306127800.0000000000|unit=shares|evidence=<real volume ID>`) validated as verified, but `enforce_trusted_boundary` re-parsed the same line with its generic prose scanner whose `_nearest_unit` uses a 24-character proximity; the long normalized value pushed `shares` beyond the window, producing `claim_unit_or_currency_unknown` and BLANKING the already-verified date/value. Short `306127800` survived (representation-length-dependent false rejection = evidence loss, not bad-claim acceptance). Reproduced in `write_report_tree` and `record_decision`/memory. | Correct evidence is needlessly lost from trusted plans/reports/memory. | **Addressed offline (2026-11-12, ADR-010 addendum; approved plan+test cases ONLY, NOT human acceptance):** occurrence-exact protection of a verified typed ClaimRecord's own `date=`/`value=` spans (`claims.extract_claim_span_occurrences` + `output_guard._verified_typed_protected_spans`) applied to both prose passes by PER-TOKEN authority (`_span_is_authorized`): a verified token is never erased and an unauthorized span is always blanked regardless of heuristic pairing (two identical verified canonical `||` subclaims across exhaustive 720 field-order permutations preserved; mixed verified+wrong siblings redact only the bad component); one shared fence/Example/blockquote exclusion walk for standalone AND canonical (a fenced/Example/quoted canonical claim gains no protection); raw-segment offsets use the strict parser's `key.strip().lower()` so supported variants (uppercase `DATE=`/`VALUE=`, spaced `date = ...`, canonical backticked `claim=`) and equivalent numeric forms are protected (no grammar expansion); no window enlargement / whole-line skip / grammar widening; unparseable mixed line fails closed. `tests/test_verified_span_boundary.py` 77 passed; focused 716; full strict-offline 2367 passed / 0 sockets (logbook 087). NOT live-confirmed; independent OpenCode FINAL technical review COMPLETE (logbook 088); explicit human final acceptance + any post-fix live retest pending. |

## Imported simulated-trading subsystem layout — 2026-11-20

---

# Part II — Personal token-observability debt (DEBT-042…DEBT-055)

**Source and status.** This part integrates the personal debt register from the
latest personal worktree (`docs/debt-register.md`, revision 2026-11-21). Release
`DEBT-001`–`DEBT-041` above are unchanged. All personal items are owned by
`PENDING_HUMAN_CONFIRMATION`: no human has accepted them.

**Identifier mapping (verified against the occupied Release IDs 001–041):**

| Personal | Final | Personal | Final |
| --- | --- | --- | --- |
| DEBT-001 | DEBT-042 | DEBT-006 | DEBT-047 |
| DEBT-002 | DEBT-043 | DEBT-007 | DEBT-048 |
| DEBT-003 | DEBT-044 | DEBT-008 | DEBT-049 |
| DEBT-004 | DEBT-045 | DEBT-009 | DEBT-050 |
| DEBT-005 | DEBT-046 | DEBT-010 | DEBT-051 |

New items recovered during the D4 pre-V2/history review: `DEBT-052` (paid-run
authorization artefact), `DEBT-053` (commit-author identities), `DEBT-054`
(session-store reproducibility), `DEBT-055` (D5 transcript draft). They are
added because the evidence supports them, not to reclassify historical failures.

## DEBT-042 — `cli_prefs` tests are coupled to host state

- **Description:** two tests drive the real interactive selection flow but do
  not isolate the host's remembered CLI state or a parent-directory `.env`.
  `cli/prefs.py:26` hard-codes `~/.tradingagents/cli_prefs.json`, and
  `tradingagents/__init__.py:14` calls `load_dotenv(find_dotenv(usecwd=True))`,
  which walks up from the worktree and loads `/home/sky/cs5351/TradingAgents/.env`.
  In the reproduced failure that parent `.env` supplies the ambient
  `TRADINGAGENTS_*` selection values, so `get_user_selections()` skips the
  stubbed prompts and records the host values instead.
- **Impact:** `test_selections_are_remembered_after_a_run` and
  `test_a_remembered_endpoint_is_offered_back` fail on a developer host with
  real `.env`/prefs state. The suite is not hermetic; the failure is unrelated to
  product behaviour. It accounts for 2 of the 4 known failures.
- **Status:** `MITIGATED` in this submission branch: `tests/test_cli_prefs.py`
  now scrubs the ambient `TRADINGAGENTS_*` selection env (autouse, scoped) and the
  two tests pass with a real host `.env` present. The CLI itself still reads
  host state; that is expected product behaviour.
- **Evidence:** `tests/test_cli_prefs.py` (env-scrub fixture), `cli/prefs.py:26`, `tradingagents/__init__.py:10-15`,
  `cli/main.py:737` (`provider_from_env`), and the reproduced failure
  (`assert 'CS5351/DeepSeek-V4-Flash' == 'gpt-5.6-mini'`).
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** done in this branch (env scrub + prefs path patch). Remaining:
  decide whether the CLI should expose an explicit `TRADINGAGENTS_HOME` so host
  isolation is a product feature rather than a test fixture.

## DEBT-043 — V3 specs embed absolute host paths

- **Description:** each frozen V3 spec stores `experiment_root` and `results_dir`
  as absolute paths from the generating worktree, e.g.
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/specs/R01_NVDA_C0/spec.json:22`
  (`/home/sky/cs5351/TradingAgents/.worktrees/cand01_v3`) and `:36` (the
  attempt runtime directory). The generator reproduces the bytes, including the
  host path.
- **Impact:** in any other worktree the two V3 infrastructure tests fail with
  `SPEC DRIFT DETECTED`; this is 2 of the 4 known failures. The frozen artefacts
  are still verifiable in their original worktree, and `MANIFEST.sha256` is
  intact, so the experiment itself is not invalidated.
- **Status:** `ACCEPTED` (documented in
  `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` §1 and
  `REGRESSION_AUDIT.md` §5.1).
- **Evidence:** `specs/R01_NVDA_C0/spec.json:22,36`;
  `tests/test_cand01_batch_16run_v3_infra.py::test_the_generator_reproduces_the_delivered_artifacts`
  and `::test_the_cli_check_mode_passes`; reproduced failure in this worktree.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** for a future V4, store host-relative paths and a
  content-addressed `experiment_root`; for V3, mark the two tests as
  `skipif` outside the original worktree or run them there. Do **not** rewrite
  the frozen V3 specs — that would move `c3-v3-final-freeze`.

## DEBT-044 — Single-pass per-tool telemetry gap

- **Description:** the graph path records one `ToolExecutionEvent` per tool
  through the LangChain `on_tool_end` callback
  (`tradingagents/observability.py:1411`). Single-pass executes tools in-process
  in `run_data_tools` and records only one `ToolRoundEvent` per batch
  (`tradingagents/agents/utils/structured.py:672-700`); it never calls
  `record_tool_execution`. Consequently `tool_calls`, `tool_result_utf8_bytes`
  and per-tool success/error are absent or zero for C0/CC in telemetry, while
  `tool_rounds` is now correct.
- **Impact:** per-tool cost/bytes are not comparable between the two-call arms
  (B/AB) and the single-pass arms (C0/CC). The V3 campaign's per-arm tool counts
  come from the run ledger / state, not from per-tool telemetry, so any future
  per-tool analysis of single-pass runs is a lower bound.
- **Status:** `OPEN`.
- **Evidence:** `structured.py:672-700` (`record_tool_round` only);
  `observability.py:925` (`record_tool_execution`) and `:1411` (callback call
  site); `tests/test_final_remediation.py::TestToolRounds` covers rounds, not
  per-tool events; `final_remediation_20261116/INDEPENDENT_AUDIT.md` Audit B
  records "single-pass 无 per-tool 事件" as a known gap.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** emit `record_tool_execution` (or an equivalent in-process
  event) per `_execute_calls` result, keeping `duplicate_count` semantics; add a
  test that one model turn with two tools produces 1 round + 2 tool events.
  Requires owner approval because it changes telemetry semantics for new runs.

## DEBT-045 — Summary CSV omits the markup counter

- **Description:** `structured_markup_sanitized` is published per agent and in
  `run_totals` in the JSON telemetry, but `write_summary_csv` in
  `scripts/token_benchmark.py:1471-1489` does not include it in `fieldnames`.
  The Markdown summary and JSON carry it; the CSV does not.
- **Impact:** a reader who only consumes `summary.csv` cannot see that a
  fallback report was sanitised, although the run still records the structured
  failure correctly (`structured_attempts == success + failure + unsupported`).
  Low severity for the V3 campaign (the 15 valid runs predate this counter, so
  no V3 CSV is affected), but it is a schema asymmetry.
- **Status:** `OPEN` (low).
- **Evidence:** `scripts/token_benchmark.py:1471-1489` (CSV columns) versus
  `tradingagents/observability.py` (`structured_markup_sanitized` in per-agent
  and `run_totals`); `final_remediation_20261116/REGRESSION_AUDIT.md` §5.3
  records "summary CSV 的列未新增".
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** add the column in a backward-compatible CSV revision
  (new column at the end, existing readers unaffected) and update the summary
  schema test. No re-freeze of V3 is required for new runs.

## DEBT-046 — No post-fix live rerun

- **Description:** the R12 fallback, DSML sanitation and `tool_rounds` fixes
  (`e0ea1b0`..`50b2ca3`) were validated only offline: scripted chat models,
  historical markup fixtures, the pre-fix probe and mutation tests. No paid
  pipeline run was executed after the fixes; R12's 400 and R07/R14's DSML
  reports remain the last live observations.
- **Impact:** the fixes are proven to prevent the known failure modes on
  fixtures, not proven to produce clean reports on live provider traffic. The
  V3 experimental results (3,067,669 tokens, −19,589) are pre-fix and are not
  re-measured under the remediated code.
- **Status:** `ACCEPTED` (explicitly out of scope: "本轮不再重跑真实实验").
- **Evidence:** `token_benchmarks/final_remediation_20261116/FINAL_REMEDIATION_REPORT_CN.md`
  §8.4; `.../TEST_RESULTS.md` §6 ("付费调用 0 / 外部 API 0"); `BRANCH_HISTORY_REPORT.txt` (LOCAL_ARCHIVE, not shipped)
  §8.2/§10 item 5.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** if budget and authorization allow, run one small paid
  rehearsal on the remediated code (e.g. R12/JPM/CC and R07/AAPL/CC) and compare
  report cleanliness and token totals; otherwise keep the NOT_VERIFIED label.

## DEBT-047 — n = 1 per cell

- **Description:** the V3 2×2 design has one valid observation per cell in the
  three complete blocks (NVDA, AAPL, XOM); JPM/CC is missing (R12 invalid). There
  are no repeats, no confidence intervals and no significance tests.
- **Impact:** the single-pass effect (−19,589 tokens/run, −8.96%) is a
  directionally consistent observation across three blocks but cannot support a
  population claim. The batch-macro mean (−17,702) is not robust: excluding R01
  it is about −695, and AAPL is +1,612.
- **Status:** `ACCEPTED`.
- **Evidence:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/FINAL_ENGINEERING_REPORT_CN.md`;
  `.worktrees/v3_runs_20261116/FINAL_EXPERIMENT_REPORT_V3.md` (LOCAL_ARCHIVE, not shipped) §3 ("每格 n=1");
  `BRANCH_HISTORY_REPORT.txt` (LOCAL_ARCHIVE, not shipped) §4.4/§8.3.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** n ≥ 3 per cell, at least two dates and a second model, before
  any confirmatory claim; pre-register the analysis.

## DEBT-048 — No ground truth for decision quality

- **Description:** the study measures token cost and structural integrity
  (usage closure, attribution, memory isolation, freeze integrity). It has no
  forward returns, no independent analyst scoring and no P&L. "Real investment
  returns" is `NOT_MEASURED`.
- **Impact:** no statement about which arm makes better decisions is supported;
  the DSML-degraded R07/R14 reports show that cheaper output can be worse
  quality, but quality itself is not scored.
- **Status:** `ACCEPTED`.
- **Evidence:** `.worktrees/v3_runs_20261116/FINAL_EXPERIMENT_REPORT_V3.md` §7;
  `BRANCH_HISTORY_REPORT.txt` (LOCAL_ARCHIVE, not shipped) §4.7/§8.3.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** add a forward-return or independent-rubric endpoint in a
  future study; do not retrofit a quality claim onto V3.

## DEBT-049 — Provider endpoint not in the config hash

- **Description:** `HASHED_FIELDS` in `scripts/c3_preflight_gate.py:292-300`
  covers experiment id, schema, switches, provider, models, language, cache,
  checkpoint, budget, cases, switches and news scope, but not the resolved
  endpoint (`backend_url`). Two runs at different endpoints with the same model
  name hash identically.
- **Impact:** the gate cannot detect a rerouted provider endpoint; the frozen
  `config_sha256` does not fully describe what was called. Recorded as L3 in V3
  Audit B.
- **Status:** `OPEN` (low; not exercised by the delivered runs, which used the
  same CityU endpoint).
- **Evidence:** `scripts/c3_preflight_gate.py:292-300`;
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_B.md`
  (residual L3 "endpoint not hashed").
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** add `backend_url`/endpoint to `HASHED_FIELDS` and the three
  mirrored definitions in a future protocol version; this changes all 16
  `config_sha256` values and therefore requires a new freeze.

## DEBT-050 — Generic `measure` path shares the host memory log

- **Description:** the 16 registered runs get a per-run copy of the immutable
  snapshot (V3). The generic `measure` command (`scripts/token_benchmark.py
  _cmd_measure`) builds an unregistered experiment and leaves
  `memory_log_path` at the default `~/.tradingagents/memory/trading_memory.md`
  (`tradingagents/default_config.py:80`), so one-shot measurements share mutable
  memory across invocations.
- **Impact:** `measure` results are not memory-isolated and are not comparable
  to the registered A/B/C runs; a pending entry from one measurement can change
  the next measurement's pre-graph reflector prompt.
- **Status:** `OPEN` (low; outside the 16 registered runs).
- **Evidence:** `tradingagents/default_config.py:80`;
  `scripts/token_benchmark.py:4919` (`_cmd_measure`) and `:4173` / `:4333`
  (isolation only on the registered/rehearsal paths);
  `INDEPENDENT_AUDIT_A.md` M3 ("generic (non-registered) specs still use the
  shared log").
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** either copy a declared snapshot for `measure` too, or state
  in the `measure` help/notes that it is explicitly non-isolated. Do not change
  the registered path without a re-freeze.

---

## DEBT-051 — Pre-existing ruff baseline (whole-repo lint is not green)

**Status:** ACCEPTED (documented, not hidden).
**Evidence:** at `50b2ca3` under `ruff 0.17.1`, `ruff check .` reports **233 findings**
(40 in `tradingagents/`, `cli/`, `scripts/`, `main.py`; 88 in `tests/`; 105 in
`token_benchmarks/` evidence scripts). The old CI comment claimed the repo was
"fully clean"; that is not true under current ruff releases.
**Why not fixed here:** fixing it requires product-code and test edits that this
course-deliverable round forbids. CI therefore lints only the Python files the
submission adds/changes (all clean) and this debt stays open.
**Next action:** a separate, authorised cleanup round (pin ruff, fix findings,
or record a reviewed baseline), then restore a whole-repo blocking lint job.

## Explicitly not counted as debt

- The 4 failing tests are classified above (DEBT-042, DEBT-043); they are not
  product regressions.
- The V3 historical `tool_rounds=0` is not rewritten; new runs carry real
  values (see BUG-011). It is a data-history limitation, not a current defect.
- The 2 skipped tests are environment skips (`langchain_aws` absent; live
  DeepSeek key absent), not debt.


## DEBT-052 — No dated paid-run authorization artefact

- **Description:** the V2 and V3 batches executed and their token totals are
  recorded, but the repository contains no approval artefact naming an
  authorizing person, a budget and a date. `AGENTS.md` §5/§11 requires such an
  authorization; the session record contains turns that approve or withhold paid
  execution (`AUL-102`), but a conversation turn is not the dated written
  authorization the rule requires.
- **Impact:** the repository cannot demonstrate compliance with its own paid-run
  rule; a reader cannot tell who authorized the spend.
- **Status:** `OPEN`.
- **Evidence:** `docs/review-memo.md` "Unverified / evidence gaps" item 4;
  `docs/ai-use-log.yaml` `AUL-074`–`AUL-103` (all `PENDING_HUMAN_CONFIRMATION`);
  `AGENTS.md` §5.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** record the dated authorizations (or declare that none exists)
  in `docs/review-memo.md`; do not invent one.

## DEBT-053 — Commit-author identities are unresolved

- **Description:** git authors `WTQ`, `Plan C3`, `C3 Engine` and `t` appear in the
  personal history. `dsh-agent` is partly explained by the OpenCode
  session of 2026-11-16 00:22–01:28; the others are not named by any recorded
  session. `t` is git's default single-character `user.name`, not a person.
- **Impact:** personal contribution attribution is uncertain; the merged tree
  must not assign those commits to a named student without evidence.
- **Status:** `OPEN` (accepted as unresolved, not invented).
- **Evidence:** `docs/ai-use-log.yaml` `unresolved_authorship`; `AUL-103`
  (self-tamper record); `docs/review-memo.md` gap 5.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** the student either confirms the mapping or the records stay
  "unresolved".

## DEBT-054 — Historical session stores are local, mutable and outside the repository

- **Description:** the reconstruction cites `~/.local/share/opencode/opencode.db`
  and `~/.dsh/sessions/--home-sky-cs5351-TradingAgents--/`. Neither is in the
  repository; both are mutable. The session record is evidence of what was asked
  and answered, not of what was committed.
- **Impact:** a reader without those stores cannot reproduce the historical
  reconstruction; nothing in the tree proves the stores were not edited before
  they were read.
- **Status:** `ACCEPTED` (inherent limitation of the evidence source).
- **Evidence:** `docs/review-memo.md` gap 7.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** prefer git-committed artefacts for any claim that must be
  reproducible; label store-derived claims as session evidence.

## DEBT-055 — D5 transcript is an AI-prepared draft pending personal annotation

- **Description:** `transcripts/60726054-WangTianQi.md` is an evidence-grounded
  AI-prepared draft. The personal decisions, reasoning, reflections and the final
  attestation are not written or signed; the file contains
  `HUMAN_CONFIRMATION_REQUIRED` markers.
- **Impact:** D5 is not a completed student-annotated transcript until the student
  writes the personal annotations and signs the attestation.
- **Status:** `OPEN`.
- **Evidence:** `transcripts/60726054-WangTianQi.md`;
  `transcripts/README.md`; the D4–D6 implementation report (human-review
  checklist).
- **Owner:** `PENDING_HUMAN_CONFIRMATION` (WangTianQi).
- **Next action:** complete and sign the transcript; do not ship it as final
  before that.

Release `24adf97` adds `src/trading/` and `src/safety/`. The current branch keeps
all sources under `src/` and tests under `test/offline/` or `test/live/`; imported
subsystem tests move to the corresponding `trading/` subdirectories. This
supersedes release's root `tests/trading/` layout and pointer-only README claims.
No real broker execution or unattended live trading is introduced.
## PR #5 verification follow-up (2026-11-21)

TODO (repository maintainers): verify the integrated full tree on Linux CI.
Windows cannot collect 13 simulated-trading modules because `fcntl` is absent;
that subtree was not modified or stubbed. The strict socket harness also blocks
Windows asyncio's local socketpair setup (two context-isolation tests), while
those tests pass in ordinary offline mocked execution. These are explicit
verification limits, not waived failures or evidence of a complete green suite.
TODO (another contributor): review PR #5 before final merge. See ADR-012 and the
integration entry in the evaluation logbook for exact results.


## PR #7 CI blockers — 2026-11-21

Observed run 44867605790 on 095fa59: complete-source mypy has 322 errors in
60 files; 58 files are unchanged release implementations after relocation.
Bandit reports nine medium and one high findings, including URL/XML handling,
non-security SHA1 and dynamically assembled SQL statements requiring individual
triage. Owner: maintainers. Action: authorize a separate core/CLI/trading/safety
type and security repair with ADR/tests; do not suppress scans or change trading
semantics just to pass. No such source changes are made by the bounded CI fix.

The approval gate lacks a genuine earlier test-plan review. Owner: human
maintainers/reviewer. Existing chat authorization cannot fabricate that platform
history; a later code review alone does not satisfy the current prior-test gate.
A human must decide the compliant review/integration path. The four changed
prompts/prompt_v1.* files are development-governance prompts with naming edits,
but the current semantic detector treats all prompt-file changes as model
changes. Owner: governance maintainers. Action: review that classification and,
where runtime prompt/model evaluation is required, establish the evaluator,
fixed dataset and thresholds on the base first. No fake evaluation, automatic
approval or fail-open gate is added. These blockers keep blocking-gate red.


### PR #7 type/security repair status — 2026-11-21

The 322 type errors and 10 configured medium/high scan findings from head
095fa59 are repaired in the current working tree under explicit expanded user
authorization. Full mypy/Bandit/Ruff and complete isolated regressions pass;
127-version dependency audit passes after a recorded proxy-failed attempt.
The existing CORE-BT-20261121-TYPES summarize errors are included in this repair:
known-alpha narrowing now matches the already-filtered runtime values.
These are local results, not a passing remote job or final human acceptance.

Approval chronology/current-head reviews and the base-approved semantic policy
remain open. The larger candidate now includes type-only model/graph source
edits as well as historical development-prompt naming changes, which the current
semantic detector sees. No detector exemption, empty evaluator, fabricated
baseline score or retrospective prior-test approval is supplied. Maintainers
must decide the compliant integration/review path. No new broker or trading
capability is added.


### CI policy simplification — 2026-11-21

Scope web-ci-policy-simple-20261121-v1, explicitly requested by the human owner.
The former missing special-marker/prior-test chronology blocker is retired by
policy, not retroactively satisfied. Human merge review remains GitHub-owned.
An absent/empty semantic base policy is now NOT RUN without blocking; no model
quality evidence or completed evaluation is claimed. Designing a real evaluator,
fixed dataset and thresholds remains open work owned by maintainers. Once
configured, replay failures remain blocking. Earlier failure records above
remain historical, not current policy instructions.

Read-only release protection inspection confirmed one required approving review,
code-owner review, stale-review dismissal, last-push approval and administrator
enforcement. Required status contexts were empty. Maintainers must separately
configure the aggregate status if mandatory remote CI enforcement is desired;
this task does not change remote protection. Local edits do not update PR #7
until a separately authorized commit and push.

## Prior-test approval deployment evidence — 2026-11-24

Owner: repository maintainer. Action: after an explicitly authorized publication,
exercise a real test-only PR review and implementation epoch. Hosted behavior is
NOT_RUN until then. The exact legacy-base installation is a human-reviewed
bootstrap, not a reconstructed historical approval. Git committer timestamps
cannot attest private uncommitted work; human process oversight remains necessary.
The unrelated GDELT date-sensitive regression found during the earlier read-only
audit is outside test-approval-v1 and must remain visible if reproduced.


## submission-fix-v1 follow-up — 2026-11-24

- Owner: repository maintainer. Authentic fixed-set candidate model observations
  are not provided. Action: authorize a specific provider/run/budget or provide
  genuine existing observations with exact candidate/dataset provenance; until
  then relevant PRs block, not pass. No paid execution is implied.
- Owner: repository maintainer. ADR-029's first installation must be published
  separately before this batch; do not widen its bootstrap to admit unrelated
  fixes. Commit/push/PR creation remain separately authorized actions.
- Owner: architecture maintainer. Automatic application context compaction is
  designed in ADR-004 but not implemented. Action: obtain a separate scoped
  implementation/test approval before claiming enforcement.
- Native permission loading/path-operation gaps were reproduced and repaired
  under explicit human authorization (ADR-031); keep the host sandbox and
  command-safety limitations visible and revalidate after OpenCode upgrades.
