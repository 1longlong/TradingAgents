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
