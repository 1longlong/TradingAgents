# Bug Diary

Records defects detected during development and the corrections requested by
review. Only defects with observed evidence are listed; unknown defect details
are marked `TODO` rather than invented. Cross-references review in
`docs/review-memo.md` and `docs/ai-use-log.yaml`.

## Phase 3B — detected and corrected during review

The following defect classes were raised during the Codex/human review of the
Phase 3B debate work and addressed in the corresponding implementation pass.
They are recorded at class level because the detailed per-bed stack traces are
available in the annotated transcript
(`transcripts/60536848-WANG-Yiwen.md`).

- **Router fall-through crash risk (#1088-family).** A conditional router that
  can return a speaker label absent from the edge map would crash LangGraph on
  a fall-through. Corrected by making `DEBATE_PATH_MAP` and
  `DEBATE_EVALUATOR_PATH_MAP` complete so any fall-through maps to a registered
  node.
- **Non-deterministic / float-noisy comparisons.** Normalized financial
  comparisons were unreliable. Corrected by quantizing to `Decimal` via
  `quantize_decimal` and using deterministic ordering.
- **Acyclic serialization risk.** A nested `SourceAttempt` inside
  `EvidenceRecord` (or a back-reference cycle in `ValidationResult`) would break
  round-tripping. Corrected by keeping `SourceAttempt` separate (7 fields),
  referencing by `evidence_id` string only, and writing only `to_dict()` forms
  into `AgentState`.
- **Missing summary budget reserve.** A debate could continue until it exhausted
  budget mid-debate and lose its report. Corrected by reserving summary
  tokens/time before any `continue` verdict and enforcing hard max
  tokens/time/calls.
- **Debate continuing with zero new valid evidence.** Repeated rounds with no
  new evidence wasted cost. Corrected by the `no_new_evidence` rule (respecting
  `no_new_evidence_patience`).

## 2026-11-06 — Blocked verdict escaped at the final output (review finding 1)

- **Defect (observed, deterministic).** With missing critical market data the
  real Data Quality Gate returned `blocked`; the graph correctly skipped the
  Bull/Bear researchers and the Research Manager rewrote its recommendation to
  Hold, but the Trader -> Aggressive/Conservative/Neutral risk debate ->
  Portfolio Manager path still carried a synthetic noncompliant model Buy into
  `final_trade_decision`, and `SignalProcessor` returned Buy. The blocked verdict
  was therefore not authoritative at the output boundary (design sections 3.6 and
  7.3). Reproduced offline by
  `/Users/wangyiwen/Documents/Codex/2026-10-19/https-github-com-1longlong-tradingagents-https/tradingagents_offline_demo.py`
  (`blocked_adversarial_model.final_signal` = `Buy`). This is a synthetic-test
  enforcement defect, not a measured live incident.
- **Root cause.** Only the Research Manager inlined a blocked-run coercion; the
  Trader and Portfolio Manager had no gate awareness, and the gate read used
  `state.get("data_quality_verdict")` without the router's fail-closed
  validation.
- **Correction.** A single deterministic, LLM-free guard
  (`tradingagents/agents/utils/output_guard.py`) reads the gate state fail-closed
  (missing/malformed/inconsistent -> blocked) and pins only the decision field
  (Recommendation / Rating / Action) to Hold on blocked runs, for both structured
  and free-text output, preserving the rationale, evidence-insufficient
  explanation, and recovery conditions. It is wired into the Research Manager
  (replacing the prior duplicated coercion), the Trader, and the Portfolio
  Manager. Fixing the review demo now yields `final_signal` = `Hold`.
- **Verification.** `tests/test_output_guard.py` (47 passed) plus the affected
  suite (294 passed); full offline suite 3 failed / 1528 passed, the 3 failures
  the known date-sensitive cache tests (logbook 058).
- **Not fixed in this milestone:** review finding 2 (pre-call budget hard limit),
  finding 3 (audit export loses per-evidence validations), and finding 4
  (degraded confidence is a prompt instruction, no validated numeric cap) remain
  open and are recorded in `docs/debt-register.md` / risk-list. No confidence
  ceiling was invented.

## 2026-11-06 — Guard edge cases, pre-call budget, and audit export (operator review)

Operator technical review (not human phase approval) confirmed the primary
blocked-to-Buy escape was fixed and raised the following, all corrected in
maintenance milestones with focused regressions:

- **Guard edge case 1 — executable trailing BUY survived without a header.** A
  free-text answer with no decision header but a `FINAL TRANSACTION PROPOSAL:
  **BUY**` line had Hold prepended while the executable BUY remained, because the
  no-header branch returned before pinning the compatibility marker. Corrected:
  the marker and sizing fields are pinned regardless of whether a primary header
  exists.
- **Guard edge case 2 — repeated decision headers kept later directional calls.**
  `Action: Buy\nAction: Sell` became `Action: Hold\nAction: Sell` (only the first
  header was pinned); two `Rating` headers similarly left Sell. Corrected: every
  recognized decision header and every `FINAL TRANSACTION PROPOSAL` form is
  pinned, with Markdown bullet/heading/value markup tolerated around the decision
  field only (ordinary rationale prose is never rewritten), preserving
  idempotence. A documented narrow rule also neutralises a blocked Trader's
  executable entry/stop/position sizing while preserving the quoted rationale.
- **Budget hard limit exceeded before evaluation (review finding 2).**
  `max_calls=1` executed Bull and Bear (2 calls) before emitting
  `budget_exhausted`. Corrected by a conservative pre-call guard before every
  Bull/Bear; a refused call skips to the Research Manager with `budget_exhausted`
  for the incomplete round; `enabled=False` keeps the legacy baseline. Usage
  stays an honest estimate, never a claimed physical provider bound.
- **Audit export lost per-evidence validations (review finding 3).** The manifest
  did not export the separate validation map, and `run_summary` omitted
  identity/snapshot/quality counts and usage provenance. Corrected:
  `evidence_manifest.json` associates validations by `evidence_id` and exports the
  separate map; `run_summary.json` adds identity/snapshot/quality counts and a
  usage provenance block where debate calls are separate from total-run calls and
  unmeasured tool/input-output counts are explicit `None` (never fabricated).
- **Verification.** `tests/test_output_guard.py` 55 passed;
  `tests/test_debate_precall_budget.py` 14 passed;
  `tests/test_report_artifacts_audit.py` 12 passed; full offline suite 3 failed /
  1562 passed (the 3 known date-sensitive cache tests, logbook 058–062).
- **Still open:** review finding 4 (degraded confidence ceiling not a validated
  numeric cap; DEBT-014) and broader original-design item 5 (automatic
  multi-category adapters / full source-attempt lifecycle; DEBT-015/RISK-015),
  both explicitly out of scope here.

## 2026-11-06 — Second review: budget boundary and audit compatibility

Independent second review (not a human phase approval) confirmed 81 new regression
tests passed and reproduced one residual budget bug and two audit-compatibility
issues, all corrected:

- **Pre-call token/time check ignored the estimated next-call cost.** With
  `max_tokens=10000`, `reserved_summary_tokens=1000`,
  `next_round_estimate_tokens=2000`, `max_time=100000`, and usage
  `tokens=9000`, `can_afford_optional_call` returned True although all remaining
  tokens were the reserve; the same held when remaining seconds equalled
  `reserved_summary_seconds`. Corrected: the check now requires
  `remaining >= reserved_summary_* + next_call_estimate_*` (half the next-round
  estimate, rounded up for tokens), with exact token/time boundary tests before
  the first Bull and before Bear. The comparison is honestly labelled
  `estimated`, and the call limit is debate calls only (not total-run budget).
- **Audit overwrote embedded validations with `[]`.** `_records_with_validations`
  replaced a record's `validation_results` with `[]` whenever the separate
  validation map lacked an entry, dropping legitimate legacy/embedded
  validations. Corrected: prefer a present authoritative map entry, otherwise
  preserve/normalize the record's own embedded validations; never attach another
  ID's result; deterministic ordering preserved.
- **Ambiguous identity silently chose the first record.** Disagreeing
  `run_id`/`snapshot_id` across records is now reported as `None` with an
  `identity_ambiguous` flag, and the inaccurate comment implying the adapter mints
  `snapshot_id` was removed (null until a real snapshot identity is recorded).
- **Verification.** `tests/test_debate_precall_budget.py` 22 passed;
  `tests/test_report_artifacts_audit.py` 20 passed; full offline suite 3 failed /
  1578 passed (3 known date-sensitive cache tests; logbook 063).

## Independent recheck 2026-11-06 (blocked-signal, quality propagation, separator)

An independent AI technical review (not a human approval) reproduced three
defects on the current uncommitted guard/budget/audit tree; the fixes below keep
the previous guard/budget/audit work intact:

- **B-2026-11-06-1 (High): blocked verdict could still become a final Buy for
  alternative rating headers.** `enforce_blocked_conclusion('Rating：Buy')`
  prepended Hold but left the fullwidth-colon header, and `extract_rating`
  NFKC-normalized it and took the LAST rating (Buy); `Final rating: Buy` escaped
  the same way because the guard anchored labels while the extractor searched
  within a line. Fixed: the guard now recognizes the same header grammar the
  extractor reads (fullwidth colon, prefixed labels, unicode dashes,
  repeated/trailing alternative labels) and the final signal boundary is
  gate-aware (`SignalProcessor.process_signal(text, state)` returns Hold on a
  blocked run; the memory log records Hold). Complete-graph regressions prove
  `Rating：Buy`, `Final rating: Buy`, and separator cases end Hold.
- **B-2026-11-06-2 (High): real gate -> manifest -> debate quality propagation
  was broken.** `evaluate_multi_category_gate` discarded the aggregator's
  per-record map and serialized the provisional adapter records
  (`Low`/`unvalidated`), so a normal/Medium run produced empty
  `EvidenceManifest.valid_ids`, an empty allowlist, and round-1
  `no_new_evidence`. Fixed: each record's own classification/reasons/validations
  are applied before serialization (never a blanket promotion from the group
  rating). A real gate -> manifest/allowlist -> researcher -> evaluator -> report
  regression proves qualified Medium/High counts as new while genuine
  Low/Blocked/future evidence does not.
- **B-2026-11-06-3 (Medium): guard concatenated Hold with following prose.**
  `Rating: Buy because ...` became `Rating: Holdbecause ...` (final signal
  REVIEW). Fixed: the semantic whitespace separator (and markdown boundary) is
  preserved on every decision-field variant; guarded output is idempotent and
  parses to Hold.
- **Verification.** `tests/test_output_guard.py` 78 passed;
  `tests/test_gate_debate_integration.py` 9 passed; focused affected suites 409
  passed. Full offline suite counts are recorded in logbook 065 (known
  date-sensitive/Yahoo baselines remain; not claimed all-green). These 2026-11-06
  fixes await explicit human review.

## Operator recheck 2026-11-06 (guard/parser agreement residual)

- **B-2026-11-06-4 (High): textual parser and guard still diverged.** Even after
  the finding-1 fix, `enforce_blocked_conclusion('Ｒａｔｉｎｇ：Ｂｕｙ')` and
  `enforce_blocked_conclusion('My final overall investment rating: Buy')` left a
  directional line the parser read (the guard matched a bounded descriptor list
  and only the fullwidth colon, not fullwidth letters/value), so the plain signal
  and the memory DECISION body could read Buy while the structured signal was
  Hold. Fixed by canonicalising every parser-recognized labelled rating line to
  `**Rating**: Hold` using the rating parser's own shared NFKC/label recognition
  (`labelled_decision_tail`), preserving the natural-language tail as explanation;
  idempotent. Fullwidth/prefixed/repeated/trailing and full-graph report+memory
  consistency covered (`tests/test_output_guard.py` 90 passed; logbook 066).
  `cli/main.py` is byte-identical to HEAD (no CLI change).

## Operator executable-instruction maintenance 2026-11-06

- **B-2026-11-06-5 (High): executable directional instructions survived a blocked
  gate in the stored intermediate plans.** On the current tree a blocked run with
  a fake model returning `Ａｃｔｉｏｎ：Ｂｕｙ / Entry Price：100 / Stop Loss：95 /
  Position Sizing：20% / FINAL TRANSACTION PROPOSAL: BUY because momentum improved`
  had `**Action**: Hold` prepended but left all four executable lines intact;
  long/fullwidth `Recommendation` headers and proposal markers with an explanation
  tail behaved the same. The former guard matched a bounded ASCII regex and the
  sizing/proposal recognizers accepted only ASCII separators and an end-of-line
  value. Fixed by one shared, linear decision recognizer
  (`rating.decision_header`/`_split_header`) used by the guard: it NFKC-normalizes,
  tolerates any plain descriptor prefix (no length cap), requires a separator and a
  single-word value, and excludes blockquotes/narrative so quoted alternatives and
  rationale are preserved. Every decision field (Action / Recommendation / Rating)
  is pinned to `**<Label>**: Hold`; a blocked Trader's fullwidth entry/stop/sizing
  fields become `not applicable`; an explained proposal marker becomes
  `FINAL TRANSACTION PROPOSAL: **HOLD**` with the tail kept. Idempotent; normal and
  degraded runs unchanged.
- **B-2026-11-06-6 (High, regressions found while correcting B-2026-11-06-5):**
  (a) a first regex-based attempt (`_HEADER_DESCRIPTOR = (word-space)*`) caused
  catastrophic backtracking on long ordinary lines (focused run stalled after 19
  tests); fixed by replacing it with the linear token scan. (b) the first design
  confused an empty post-value tail with "no match" and had a descriptor cap; both
  removed. (c) `extract_rating` still used its old loose within-line search, so a
  quoted/narrative alternative (`> Rating: Sell ...` or `We rejected the earlier
  rating: Sell ...`) overrode the pinned Hold and the plain textual signal read
  Sell; fixed by making `extract_rating` take the last *structural* header as
  authoritative before its looser lower-case fallback, so the parser and guard
  agree while genuine mid-sentence labels ("Final rating — Underweight") still
  parse.
- **Verification.** `tests/test_output_guard.py` 130 passed (fullwidth label/value
  and sizing separators, arbitrary/long prefixes, repeated/trailing labels,
  proposal `BUY because ...`, Markdown wrapping, rationale/recovery/quoted-
  alternative preservation, idempotence, long-line performance, and a full blocked
  graph asserting the stored Trader/Research plans and the saved report); focused
  affected suite 520 passed; strict fully offline suite 4 failed / 1661 passed / 1
  skipped / 1 deselected / 22 warnings / 88 subtests (the same known baselines;
  not all-green, logbook 067). Ruff clean, governance validator PASS, `git diff
  --check` clean. `cli/main.py` unchanged. Awaits explicit human review; the CLI
  state-passing gap, degraded numeric confidence ceiling (DEBT-014) and automatic
  optional adapters (DEBT-015/RISK-015) remain OPEN.

## Known / open bug-like behaviors (not hidden)

- Date-sensitive cache tests (`DEBT-001`) and the network-reachability-dependent
  baseline test (`DEBT-002`) produce non-green full-suite results on some
  days/environments. These are behaviors to stabilize or document, not
  silent defects.

## TODO

- `TODO (60536848-WANG-Yiwen): Capture any additional per-defect stack-trace
  detail in the final annotated transcript if required for submission, without
  copying secrets.`
## November 10 repair batch (multiline guard / empty-map override / shared ID uniqueness)

- **B-2026-11-10-1 (High): a blocked Trader output's executable multiline
  instructions survived the guard.** On the current tree, a blocked run with a
  free-text Trader reply such as `**Action**:` newline `Buy` / `**Entry Price**:
  $100` / `**Position Sizing**: 10%`, a block-style `FINAL TRANSACTION PROPOSAL:`
  newline `BUY 100 shares at $100`, or an unsupported plain `Buy 100 shares at
  $100. Exit at $120.` was prepended with `**Action**: Hold` yet the executable
  direction/sizing/proposal text remained in the stored intermediate plan and the
  saved report — contradicting the authoritative Hold. The header grammar
  requires a single-word value on the same physical line, so block-style values
  (including blank-line-separated values), direction-plus-explanation values, and
  unsupported executable sentences were not recognised. Fixed by folding a
  label-only header's continuation value (skipping blank physical lines) into a
  pinned `**<Label>**: Hold` / `FINAL TRANSACTION PROPOSAL: **HOLD**` /
  `not applicable` form and dropping the executable value line, plus an
  **anchored** executable-sentence fallback (a trade verb at line start with a
  quantity/price/size token) that fails closed for unsupported formats. Quoted
  spans, negation/historical/rejected/considered rationale markers and
  blockquotes are preserved verbatim, so a line that only discusses a trade
  (`We rejected "Buy 100 shares at $100" ...`, `Earlier proposal: ... It was not
  executed.`) is never deleted. Linear token scan, idempotent, LF/CRLF/whitespace/
  Markdown/fullwidth covered.
  - In-pass correction 1 (from the in-progress review): the first fix used an
    unanchored whole-line regex and an immediate-next-line lookup, which both
    deleted legitimate quoted/negated rationale and missed blank-line-separated
    values; corrected to the anchored match + structural quoted-span guard +
    blank-line-skipping value lookup (12 boundary tests observed failing first).
  - In-pass correction 2 (from the second in-progress review): bulleted/numbered
    Markdown direction values (`Action:` newline `- Buy` / `1. Buy`) still
    survived; the blanket "any rationale keyword or any quote" exemption wrongly
    kept live commands (`Buy 100 shares at $100 because the earlier forecast
    improved;`, `Buy 100 shares at $100; analyst says "good value".`) and a
    multiline `Buy because ...` explanation was discarded. Fixed: value
    recognisers tolerate bullet/number/heading prefixes; exemption is now
    STRUCTURAL only (the leading trade verb must sit inside a quotation, or the
    line must not lead with a command verb), so a live command is contained even
    when it later mentions a keyword or quotes a phrase; a direction value's
    explanation is preserved as the rationale tail (`**Action**: Hold because
    valuation is attractive.`). New direct + fake-Trader boundary regressions were
    observed failing before the correction, then passing.
  - In-pass correction 3 (final F1 review): `Action: Buy 100 shares at $100
    because valuation is attractive` had become `**Action**: Hold 100 shares at
    $100 because ...` (executable position/price kept in the decision field), and
    `Action:` newline `**Strong Buy**` survived as a directive. Fixed: a
    recognised decision value's executable sizing/price/quantity tail (and a pure
    residual direction-word tail, e.g. `Strong Buy`) is stripped, keeping only a
    clearly separated rationale clause (`because`/`since`/...); and a bounded
    unsupported-value fail-closed policy drops an unrecognised value-like line
    (`**Strong Buy**`) in a recognised decision value position and pins Hold. The
    executable-tail detector uses quantity/price/size and pure direction words
    only (not rationale adjectives), so ordinary long prose keeps its rationale
    (the prior long-prose test still passes). Direct + fake-Trader regressions and
    a normal/degraded-unchanged assertion: `tests/test_output_guard.py` 197
    passed; strict offline 1743 passed / 4 known baselines (logbook 070).
- **B-2026-11-10-2 (Medium): explicitly empty authoritative validation entries
  were dropped, reviving a stale embedded passed check.** `_validation_map`
  omitted a present `{evidence_id: []}`, so `_records_with_validations` fell back
  to the record's stale embedded `validation_results` and kept a check the gate
  had cleared. Fixed: a PRESENT entry (including a malformed value that cannot
  carry a validation) is authoritative and exported as `[]`, overriding embedded;
  an ABSENT entry keeps the legacy embedded fallback. Nonempty override, no
  cross-ID leakage, deterministic ordering and redaction preserved.
- **B-2026-11-10-3 (Medium): real-jsonschema path accepted duplicate requirement
  IDs the fallback rejected.** JSON Schema `uniqueItems` compares whole objects,
  so two requirements sharing an `id` but differing in other fields both passed
  the real validator while the deterministic fallback rejected them. Fixed by a
  shared `validate_unique_requirement_ids()` invoked on BOTH entry paths (the
  fallback now delegates its uniqueness check to the same helper). Duplicate IDs
  with differing objects are rejected on the real and forced-fallback paths; the
  22 existing IDs and schema constraints are unchanged; no count is hardcoded.
- **Verification.** `tests/test_output_guard.py` + `test_report_artifacts_audit.py`
  + `test_governance_scaffold.py` 219 passed (24 multiline + 14 boundary guard
  cases, 11 report/validation cases); focused affected suite 379 passed; strict
  fully offline suite (socket disabled) 1714 passed / 1 skipped / 1 deselected /
  4 known-baseline failures (not all-green, logbook 070). Ruff clean; governance
  validator PASS (35/35, no secrets); `git diff --check` clean. These fixes await
  independent review and later human acceptance; the degraded numeric confidence
  ceiling (DEBT-014) and automatic optional adapters (DEBT-015/RISK-015) remain
  OPEN and were not touched.

---

# Part II — Personal token-observability defect records (BUG-001…BUG-018)

**Source and status.** This part integrates the personal bug diary from the latest
personal worktree (`docs/bug-diary.md`, revision 2026-11-21) and adds two
pre-V2 defects recovered from the historical session audit. The Release bug
history above is unchanged. Personal BUG identifiers do not collide with the
Release diary (which uses headings rather than `BUG-` IDs). Every status is
AI-assessed from committed evidence; human confirmation is
`PENDING_HUMAN_CONFIRMATION`.

**Status vocabulary (personal series).** `FIXED` (a regression test exists and
passes offline), `FIXED — NOT VERIFIED LIVE` (no paid rerun after the fix),
`PROCESS-CLOSED` (no paid run occurred and the history was preserved, not solved
by code).

**Identifier note.** Defects are reported against the integrated tree. Personal
`DEBT-005` (no post-fix live rerun) is now `DEBT-046`; personal
`DEBT-003` (single-pass per-tool telemetry) is now `DEBT-044`. The original
personal requirement aliases in the cross-reference are mapped to the canonical
IDs.

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


## BUG-017 — Telemetry re-run selection picked the wrong artifact

| Field | Value |
| --- | --- |
| **Discovered** | 2026-10-23/24, harness audit and QA session; recorded in the session record as the "telemetry re-run conflict" (`AUL-085`, `AUL-098`) |
| **Symptom** | A run directory accumulated more than one telemetry artifact when an attempt was restarted — the record cites a 19-call and a 20-call artifact for one run, and elsewhere a 19-call and a 28-call file — and the harness selected by file size or modification time rather than by a rule fixed before the run. |
| **Impact** | The measured sample could be the wrong attempt; a re-run could silently improve or worsen a cell, and the reported total would not describe the run that was actually executed. |
| **Root cause** | No pre-run selection rule: the harness discovered telemetry after the fact and preferred the larger/newer file. |
| **Fix / mitigation** | The harness now selects exactly one artifact for the measured attempt by a pre-run snapshot, never by size or mtime, and preserves every superseded artifact as evidence (`FR-OBS-005`). |
| **Regression test** | `tests/test_token_benchmark.py` (repeated-attempt selection and preservation cases); `tests/test_c3_regressions.py`. |
| **Status** | `FIXED` (offline). Not a live-runtime claim. |
| **Remaining gap** | Historical attempts whose artifacts are not in the delivered tree cannot be re-selected; their totals stay as recorded. |
| **Human review** | `PENDING_HUMAN_CONFIRMATION`. |

## BUG-018 — Tool calls were not observable on the early graph path

| Field | Value |
| --- | --- |
| **Discovered** | 2026-10-23/24, real smoke run in the harness-audit session (`AUL-085`, `AUL-098`) |
| **Symptom** | A smoke run reported 20 LLM calls while the tool-call count did not match the six tool rounds the run had executed; per-tool execution telemetry was absent on the graph path. |
| **Impact** | A reader could not reconcile calls, tool rounds and tokens; any per-agent tool-cost claim was unsupported. |
| **Root cause** | The graph `ToolNode` executed tools without a tool-round/execution instrumentation hook, so the collector saw model calls but not the tool work around them. |
| **Fix / mitigation** | `attrib_tool_round` wraps each graph tool node and records one round per invocation (`tradingagents/observability.py`, `tradingagents/graph/setup.py`); tool executions are recorded by the callback handler. This is a **different path** from the later single-pass `tool_rounds=0` defect (BUG-011); they are not duplicates. |
| **Regression test** | `tests/test_observability.py` (`TestAttribToolRound`), `tests/test_final_remediation.py::TestToolRounds`, `tests/test_graph_tool_observability.py`. |
| **Status** | `FIXED` for the graph path (offline). The original 20-call smoke observation is a session self-report and was not re-executed for this record. |
| **Remaining gap** | Single-pass per-tool events remain incomplete (`DEBT-044`). |
| **Human review** | `PENDING_HUMAN_CONFIRMATION`. |


## Cross-reference (personal series)

- Defect-to-test mapping is also recorded in
  `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` §4–§5 and
  `.../REGRESSION_AUDIT.md` §2.
- The pre-fix probe
  (`token_benchmarks/final_remediation_20261116/tests/pre_fix_detection_probe.py`)
  detects 4/4 defects on `e3b5cca` and 0/4 after `50b2ca3`; it is the only
  executable proof that the R12/DSML/tool-round tests are non-vacuous.
- `BUG-012` and `BUG-013` are process/engineering defects, not model or data
  defects; they are included because they changed what "verified" meant.
- `BUG-017` and `BUG-018` were recovered from the 2026-10-23/24 session record
  (`AUL-085`, `AUL-098`) during the D4 pre-V2 recovery; their discovery dates are
  supported, their exact times are `NOT_VERIFIED`.
- Rejected optimisations (Stage 4, Stage 6) and provider/network disruptions
  (HTTP 429, ECONNRESET) are **not** filed here: they are experiment decisions
  and operational incidents, recorded in `Report.md` and `REC-09`, not product
  defects.
