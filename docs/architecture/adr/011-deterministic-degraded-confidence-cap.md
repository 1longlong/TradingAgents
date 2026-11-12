# ADR-011 — Deterministic Degraded-Run Confidence Cap (0.60)

- **Status:** Proposed — **implementation complete in the working tree; independent
  Codex offline verification CONFIRMED; human acceptance PENDING (NOT claimed
  complete)**. The policy
  module, runtime wiring (debate turns/stances, evaluator, RM/Trader/PM typed +
  prose, report writer, memory), the shared post-gate state-input sanitizer
  (analyst reports / plans / debate+risk histories AND persisted turn/stance
  numerics capped on a per-read COPY before every post-gate prompt), the API and
  CLI fail-closed resume sanitizers, and the typed raw-precision cap are in place
  and offline-verified (fresh 2026-11-11 Stage 4b run: focused 110 passed / 0
  sockets; full strict-offline 2154 passed / 1 skipped / 1 deselected / 22
  warnings / 88 subtests / 0 sockets; Ruff clean; validate_requirements 43/43;
  `git diff --check` clean; logbook 082; independent Codex offline verification
  CONFIRMED same counts, HEAD 5ecea91 unchanged, frozen files unchanged). This line
  records ACTUAL evidence only and is not a completion or signoff claim. Plan +
  test cases for the four-item repair were explicitly approved by WANG Yiwen
  (60536848) in the controlling conversation on 2026-11-11, including the degraded
  confidence ceiling of **0.60**; that approval authorizes the plan and the test
  cases ONLY and is **not** a final human acceptance of any item. Stages 1
  (ADR-008), 2 (ADR-009), 3 (ADR-010) and 4 (this ADR) are implemented in the
  working tree.
- **Date:** 2026-11-11
- **Deciders:** CS5351 project (student); coding-agent (OpenCode Builder);
  independent reviewer (Codex); human review required before acceptance
- **Trace:** `FR-DQG-006` (degraded-run restriction / confidence ceiling),
  `NFR-AUD-001` (auditability), `NFR-DET-001` (determinism), `NFR-BC-001`
  (backward compatibility), `FR-DQG-005` (report artifacts), `FR-DDT-001`,
  `INV-1`/`INV-2`/`INV-4`/`INV-6`/`INV-8`. No new requirement ID is invented:
  this ADR resolves the degraded confidence ceiling gap recorded in DEBT-014 /
  RISK-014 under the existing IDs.

## Context

The degraded (not blocked) gate verdict currently restricts confidence only by
**prompt instruction** (`research_manager.py`, `bull_researcher.py`,
`bear_researcher.py`). No schema, policy or runtime code enforces a numeric
ceiling, so:

- a `DebateTurn`/`StanceSnapshot` can carry `confidence=0.95` on a degraded run
  and that number is persisted into the checkpoint and read by the evaluator;
- the Research Manager / Trader / Portfolio Manager free-text output can state
  "95% confidence" and that prose reaches the intermediate plans, the final
  decision, the saved report, the CLI display and the memory log;
- the public report writer has no gate-aware ceiling at all.

DEBT-014 recorded this precisely and deliberately deferred fixing it: a ceiling
must be specified by policy before it is enforced. The human has now specified
that policy ceiling as **0.60** for a degraded run.

This is an **engineering constraint** (a safety ceiling), NOT a calibrated
probability, NOT an accuracy claim and NOT production threshold tuning. The cap
value 0.60 is an approved policy constant; it asserts nothing about the model's
true confidence calibration.

Two structural facts constrain the repair:

1. **Only typed debate schemas carry a numeric confidence today.**
   `DebateTurn.confidence` and `StanceSnapshot.confidence` are the only numeric
   confidence fields. The Research Manager / Trader / Portfolio Manager schemas
   (`ResearchPlan`, `TraderProposal`, `PortfolioDecision`) have **no** numeric
   confidence field, so their confidence, if expressed, is prose.
2. **The sentiment categorical `confidence` is a label.** `SentimentReport.
   confidence` is `Literal["low","medium","high"]`. It is NOT a calibrated
   numerical value and must remain distinct (never coerced to 0.60 or 1.0).

## Decision

### A. One central pure policy (`tradingagents/debate/confidence_policy.py`)

A single pure, deterministic, LLM-free module owns the ceiling:

- `CONFIDENCE_POLICY_VERSION = "1.0"`, `DEGRADED_CONFIDENCE_CAP = 0.60`;
- `current_trusted_verdict(state)` → `normal` / `degraded` / `blocked`, read
  through the existing fail-closed `effective_gate_verdict` (a missing/malformed
  gate state is `blocked`; a mismatch is `blocked`). The cap applies to a
  **trusted verdict** only; a `blocked` run keeps its existing non-directional
  Hold discipline and is never treated as a numeric-confidence run.
- `cap_value(value, verdict)` → the effective capped float or `None`. A `normal`
  (or `blocked`) run never changes a valid numeric value; a `degraded` run caps
  any valid numeric value at `DEGRADED_CONFIDENCE_CAP`.
- `apply_confidence_cap(value, verdict, *, source, boundary)` → a JSON-safe
  audit dict `{raw_value, effective_value, capped (bool), reason,
  policy_version, boundary, source}`. `raw_value`/`effective_value` are `None`
  when the input numeric is **absent** (never a fabricated `0.60`). `capped` is
  `True` only when a raw value exceeds the cap.
- A deterministic **rounding/rendering** rule, separate from the cap decision:
  the **cap decision** compares the *original finite value* against
  `DEGRADED_CONFIDENCE_CAP` with a strict `>` using an exact `Decimal`, so
  `0.6000001` genuinely exceeds the cap and is capped, while `0.60` exactly and
  any smaller valid value are unchanged. **Rendering** of a capped value into
  prose/number form is the constant cap (`0.6` / `60%`) and never feeds back into
  the decision. The audit records the raw value unchanged (never rounded) so the
  original is always recoverable.
- `scan_confidence_text(text)` → the explicit confidence statements in prose.
  Extraction is deliberately **narrow**: a numeric token counts only when it is
  attached to an explicit confidence label — a **percent** with a label
  (`confidence: 95%` / `confidence of 95%` / `95% confidence`), a **fraction in
  `[0,1]`** with a label (`confidence: 0.95` / `0.62 confidence level`), the
  `DEBATE_METADATA confidence=` field, or a Markdown-wrapped label
  (`**Confidence:** 0.9`). Fullwidth/NFKC forms are covered (`０.９５`, `９５％`).
  An **ordinary financial figure is NEVER a confidence**: a share count, return,
  margin, position size, price or date (`Revenue increased 95%`, `margin 0.31`,
  `200 shares`, `close 200.13`, `2026-05-04`) is left byte-for-byte unchanged. A
  bare `confidence: 95` (no `%`) is **outside** the approved fraction contract and
  is not reinterpreted as `95%` (it is quarantined); there is no arbitrary
  "percent anywhere = confidence" inference.
- `rewrite_confidence_text(text, verdict)` → `(rewritten_text, audit_list)`.
  On a degraded run every labelled confidence above the cap is rewritten to its
  effective ASCII form (`0.95` → `0.6`, `95%` → `60%`, `０.９５` → `0.6`). On a
  normal run the text is unchanged. An **invalid** labelled confidence on a
  degraded run (a bare `confidence: 95` with no `%`, a malformed percentage such
  as `101%`, `NaN`/`inf`/`true`/`false`, an out-of-`[0,1]` value) is
  **quarantined** — replaced by an explicit unknown marker and recorded as
  `invalid_numeric_rejected` — so a malformed/oversized numeric never remains an
  authoritative-looking `confidence: 95` / `confidence: NaN`. The **effective**
  value remains in the trusted text; the **raw** value goes to the
  audit/quarantine record only.
- **NFKC safety.** Matching runs on the NFKC string, but NFKC can change length
  (ligatures `ﬁ`→`fi`, circled digits `①`→`1`); each match index is mapped back
  to the ORIGINAL text via a per-character index map, so a prefix whose length
  changed under NFKC never shifts an edit onto the wrong bytes.
- **`previous` is provenance only.** `apply_confidence_cap(previous=...)` may
  retain a prior raw value only on a genuine same-value/no-value re-entry; it can
  never override a NEW actual model value (a forged/stale `previous["raw_value"]`
  is ignored) and never forges or raises the effective value.
- **Missing stays missing.** Text without any labelled numeric confidence gets no
  invented value and no synthetic audit entry. A categorical concern such as
  "confidence: high" is NOT a numeric value: it is recognised and left as a
  clearly-labelled category, never coerced to a number.
- **Blocked discipline preserved.** A `blocked` run never rewrites text into a
  numeric value; the existing `enforce_blocked_conclusion` Hold pinning and the
  citation/claim guards are untouched and run in addition.

### B. Additive optional numeric confidence on the decision schemas

`ResearchPlan`, `TraderProposal` and `PortfolioDecision` gain an **additive,
optional** numeric field `confidence: float | None = None` with a strict
`[0, 1]` validator (reject bool/NaN/inf/out-of-range; a placeholder string like
`"N/A"` becomes `None`, never a fabricated number). The field is rendered into
the structured markdown as a clearly-labelled `**Confidence**: <effective>`
line ONLY when the model supplied a numeric value; a legacy model that omits it
produces exactly the pre-Stage-4 markdown (NFR-BC-001). The render helpers take
the *effective* (already capped) value, so a raw over-cap value is never
rendered as authoritative prose.

### C. Runtime enforcement (not prompt-only), at every real boundary

The cap is applied by *recomputing from the authoritative gate verdict*
(`current_trusted_verdict(state)`), never by trusting a caller-supplied or stale
effective/audit value on the state. Each boundary recomputes:

1. **Debate turns** (`bull_researcher.py`, `bear_researcher.py`): after
   `parse_turn_metadata`, the numeric `DebateTurn.confidence` is capped on a
   degraded run **before** it enters the debate state (`append_debate_turn`), so
   the evaluator and `StanceSnapshot` see the effective value. A per-turn
   provenance entry is recorded (bounded index-identified, never duplicated for
   the same turn on re-entry).
2. **Evaluator** (`evaluator_node.py`): the persisted `StanceSnapshot.confidence`
   is derived from the already-capped turn confidence, so it can never exceed the
   cap; a provenance entry keyed by round/speaker is written idempotently (a
   re-run of the evaluator for the same round overwrites, never double-counts).
3. **Research Manager** (`research_manager.py`): the structured `confidence`
   (if any) and any numeric confidence in the rendered plan are capped; the
   trusted `investment_plan` carries the effective value; raw over-cap values go
   to the audit channel only.
4. **Trader** (`trader.py`): same, on `trader_investment_plan`.
5. **Portfolio Manager** (`portfolio_manager.py`): same, on
   `final_trade_decision`.
6. **Final signal boundary** (`signal_processing.py`): a degraded run's
   effective value is what the signal/report read.
7. **Report writer** (`reporting.write_report_tree` /
   `report_artifacts.py`): the writer **independently** recomputes the cap from
   the imported/legacy `final_state` (it does not trust a state-supplied
   effective value), so a legacy checkpoint or hand-built state cannot resurrect
   a raw `0.95`. The `run_summary.json` / gate summary carry the versioned
   `confidence_cap` audit block (policy version, verdict, per-boundary entries).
8. **Memory** (`trading_graph.record_decision`): the persisted decision uses the
   trusted effective text, so the reflection memory never stores a raw over-cap
   confidence.
9. **SQLite resume/re-entry**: the audit + effective values are declared on the
   production `AgentState`, so a close → reconstruct → resume re-reads them and a
   recomputation is deterministic (the same effective value; the audit block is
   rebuilt identically, not appended twice).

### D. Audit channels are additive, JSON-safe and checkpoint declared

A versioned audit block is carried on the production `AgentState`
(`confidence_cap_audit`), plus per-turn provenance inside the debate state.
Each entry is a JSON-safe dict with `boundary`, `source`, `raw_value`,
`effective_value`, `capped`, `reason`, `policy_version`. A duplicate entry for
the same boundary identity (e.g. the same turn index, or the same report) is
collapsed (overwrite, never double-count), so an imported legacy state or a
re-entry cannot accumulate phantom entries. Absence is explicit (`null` raw /
effective, a stable `reason`), never an invented raw number.

### E. Non-goals / explicit safety stops

- No calibrated-probability / accuracy claim; 0.60 is an engineering ceiling.
- No production threshold tuning, no Phase 4B, no new provider/paid call/
  dependency/CI/permission/human-rule change.
- No `blocked` weakening: the Hold pinning, exact-claim redaction and citation
  guards stay exactly as they are.
- No extra LLM call; Stage 2 usage-ledger/invocation accounting and Stage 3
  claim validation are untouched and preserved.
- No claim that a prompt cannot still *say* something; only explicit **numeric**
  confidence is capped. Qualitative prose is not a calibrated numeric value.

## Consequences

- Positive: a degraded run's effective confidence is provably ≤ 0.60 through the
  debate, evaluator, all managers, the final decision, the saved report, the CLI
  and the memory log; raw over-cap values are quarantined in the audit block.
- Positive: a normal run and a no-number/legacy run are byte-compatible.
- Negative/cost: three schemas gain an optional field; four prompt-render sites
  and the report writer gain a deterministic post-processing hook; new state
  channels must stay JSON-safe and dedupe on re-entry.
- Risk: an over-eager prose rewriter could mangle ordinary text. Mitigated by
  capping only explicit numeric confidence tokens (decimal/percent/fullwidth)
  and leaving all other prose untouched, with negative tests pinning
  qualitative/blocked behavior.

## Verification (this ADR's implementation)

Approved test cases in `tests/test_confidence_cap_policy.py` (pure matrix) and
`tests/test_confidence_cap_runtime.py` (real runtime) cover: normal/degraded/
blocked matrices; boundary values `0`, `0.59`, `0.60`, `0.61`, `1`; invalid
(bool/NaN/inf/out-of-range/percent/fullwidth/duplicate/conflicting) inputs;
categorical and absent confidence unchanged/distinct; idempotent repeated
application; REAL production `AgentState` + `GraphSetup` with scripted
over-confident models and mocked raw vendor sources proving each
manager/trader/portfolio and the upstream debate see an effective value ≤ 0.60;
an actual SQLite interrupt → close → reconstruct → resume; the public
propagate/CLI/report/memory path preventing stale/raw resurrection; structured
fallback and refusal routes; and blocked Hold remaining Hold. All tests are
socket-disabled/offline with mocked vendors/models; no live call is made.

Fresh final Stage 4b run (2026-11-11): `tests/test_confidence_cap_policy.py` +
`tests/test_confidence_cap_runtime.py` + `tests/test_confidence_cap_cli.py` =
**110 passed / 0 forbidden socket attempts**; full strict-offline suite =
**2154 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden
socket attempts**; Ruff `All checks passed`; `validate_requirements.py` 43/43
PASS; `git diff --check` clean.

Additional precision/no-resurrection coverage added in the final pass:

- a **direct** GraphSetup resume (`graph.graph.invoke(None)` over a real SQLite
  checkpointer, WITHOUT the API resume-sanitizer) with a stale typed
  `confidence=0.95` in persisted turns/stances: the node-level read defense caps
  the numeric channel before the evaluator reads it (proves the shared sanitizer,
  not only the API wrapper);
- the API/CLI resume sanitizer is **fail-closed** on a `update_state` failure
  (zero resumed model/stream calls); repeated safe resume is **idempotent** (no
  audit duplication); a malformed legacy numeric (bool / NaN / out-of-range) is
  **quarantined**, not left authoritative; analyst and risk histories are
  sanitized;
- exported `run_summary.json` / `debate_trace.json` use the effective values and
  per-section/per-turn audit; a raw `.95` appears ONLY in an explicit
  `raw_value` audit/quarantine field;
- typed RM/Trader/PM schema confidence is capped on its **exact raw** value
  (0.6000001 / 0.604 / 0.954321) BEFORE the lossy `:.2f` render, so an over-cap
  value masked by rounding (`.60` / `.95`) is still genuinely capped and the exact
  raw is recorded; a normal run and a within-cap high-precision value are
  unchanged;
- the capped values are PERSISTED into the RETURNED state (not only the protected
  prompt): a deterministic post-gate `Confidence Sanitizer` node writes the capped
  analyst-report / plan / history fields, and every post-gate node wrapper merges
  its changed sanitized INPUT deltas (node outputs win) AND caps its own returned
  text (e.g. a raw risk argument) — so a direct legacy resume that SKIPS the
  sanitizer node still ends with effective reports in the final state and in the
  actual `_log_state` / public JSON export; originals survive only in the explicit
  audit. A direct SQLite resume AFTER the sanitizer node (at the Trader/PM) with a
  stale `market_report=0.95` is covered; risk-history raw over-cap output is capped
  before return; a normal run's report is byte-for-byte unchanged.

See `docs/architecture/evaluation-logbook.md`, `docs/architecture/trace-matrix.md`,
`docs/debt-register.md`, `docs/architecture/risk-list.md`,
`docs/ai-use-log.yaml`, and `docs/review-memo.md` for the recorded evidence,
status changes and remaining gaps.

### Amendment (2026-11-12) — structural token/sentence boundaries (Defect 1)

Approved plan + test cases: human WANG Yiwen, 2026-11-12 (implementation approval,
NOT final human acceptance). A completed 2026-11-11 school-model live run exposed a
report/plan integrity defect: `rewrite_confidence_text` corrupted an ordinary price
in the Trader plan and the exported `report/3_trading/trader.md` /
`report/complete_report.md`.

- **Confirmed defect (offline reproduction of the live input):**
  `Re-entry requires a close above $204.38. Confidence is set at the plan's 0.55.`
  became `... $204.unknown (invalid confidence quarantined) Confidence is set ...`.
  Cause: the suffix numeric literal `\d+(?:\.\d*)?` absorbed the sentence period
  into `38.`, and there was no left token boundary preventing a start mid-token
  (after `$204.` / `38`); the invalid `38.` was then quarantined.
- **Fix (grammar only; enforcement never disabled):**
  - the numeric fractional part is all-or-nothing (`\d+(?:\.\d+)?`), so a trailing
    sentence period is never consumed as a decimal point;
  - the gap between a value and its suffix label is SOFT whitespace only
    (`[ \t]*\r?\n?[ \t]*`, CRLF-aware) — a sentence terminator (`. ! ? ;`) is a
    structural boundary, not a connector, while a soft line wrap (`0.95\nconfidence`
    / `0.95\r\nconfidence`) still binds a genuine suffix;
  - a left token boundary `(?<![\w.,\-/:$€£¥])` keeps a currency-glued price
    (`$204.38`), a bare price fragment (`204.38`), a sign (`-`), and a date/path
    fragment (`2026-11-05` / `2026/11/05`) out of the suffix grammar, so the price
    and date portions are byte-for-byte unchanged.
- **Contract preserved, not weakened:** a bare `204.38 confidence` (no currency, no
  `%`, value `> 1`) remains an INVALID labelled value and is quarantined — it is
  NOT blanket-exempted as a "price"; only unambiguously currency-glued figures are
  excluded from being a confidence candidate. `0.55` (within cap) unchanged; a
  genuine `0.95`/`95%`/`.95`/`9.5e-1`/`+0.95`/fullwidth/JSON/Markdown still caps
  to `0.60`; malformed labelled quarantine (`confidence: 95`, `9e-1x`, `NaN`,
  `true`, `null`) unchanged; normal/blocked unchanged; idempotent.
- **Tests:** `tests/test_confidence_boundary.py` (51 passed) pins the exact live
  reproduction, the sentence/newline/CRLF matrix, currency/date preservation, bare
  invalid quarantine, soft-wrap cap, preserved forms, malformed quarantine,
  idempotence, a zero-collateral ordinary-figure corpus, and real Trader →
  report-tree propagation (`3_trading/trader.md`, `complete_report.md`). The
  existing `tests/test_confidence_cap_{policy,runtime,cli}.py` (110) still pass.
- **Scope/limits:** offline, deterministic, LLM-free verification only. This is an
  ADR-011 amendment for in-scope maintenance of the approved Stage 4 cap; it is NOT
  a live retest and does NOT relabel the preserved live evidence.
- **Status (2026-11-12):** independent Codex technical review **COMPLETE**
  (full strict-offline 2290 passed / 0 sockets; historical `$204.38.` case, LF/CRLF
  soft-wraps, dates/currency preserved, genuine 0.95 capped at REAL Trader/report/
  record_decision boundaries). Explicit **human acceptance remains pending**; the
  old real live run remains historical bug evidence, never post-fix live proof.
