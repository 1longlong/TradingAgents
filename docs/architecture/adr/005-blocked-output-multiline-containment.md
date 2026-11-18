# ADR-005 — Blocked-run output containment for multiline / unsupported executable instructions

- **Status:** **PROPOSED (technical implementation complete, awaiting independent
  review; human acceptance NOT yet given)**
- **Date:** 2026-11-10
- **Deciders:** CS5351 project (student); coding-agent implementation; explicit
  human authorization of the repair plan and test cases only
  (“批准本轮修复计划和测试用例”, 2026-11-10 — plan/test authorization, NOT
  acceptance of the fixes).
- **Trace:** `FR-DQG-006`, `NFR-FC-001`, `NFR-DET-001`
- **Related debt / risk:** `DEBT-029`, `RISK-024` (and the companion audit/validator
  fixes `DEBT-030`/`DEBT-031`, `RISK-025`/`RISK-026`).

## Context

The Data Quality Gate is authoritative: on a blocked run only an
evidence-insufficient `Hold` conclusion is permitted at the output boundary
(`output_guard.enforce_blocked_conclusion`, ADR-001, `FR-DQG-006`). The existing
guard pins *same-line* decision headers (`**Action**: Buy`), the
`FINAL TRANSACTION PROPOSAL: <value>` marker, and same-line Trader sizing to a
canonical Hold / HOLD marker / `not applicable`.

A 2026-11-10 repair review reproduced that a blocked Trader output could still
carry executable instructions the same-line grammar does not model, so the stored
intermediate plan and the saved report contradicted the authoritative Hold:

- Block-style label-only headers with the value on a following physical line,
  including blank-line-separated (`**Action**:` blank `Buy`) and bulleted/numbered
  Markdown values (`Action:` newline `- Buy` / `1. Buy`).
- A block-style `FINAL TRANSACTION PROPOSAL:` whose executable value is on the
  next line (`BUY 100 shares at $100`).
- Split sizing (`**Entry Price**:` newline `$100`, `**Position Sizing**:` newline
  `10%`).
- Unsupported plain fill sentences (`Buy 100 shares at $100. Exit at $120.`).

The same review raised a safety concern about the *exemption* rule: a naive
"preserve any line containing a rationale keyword or any quote" would keep a live
anchored command (`Buy 100 shares at $100 because the earlier forecast improved;`,
`Buy 100 shares at $100; analyst says "good value"`) executable, while the approved
plan requires that genuinely quoted/negated/historical rationale be preserved.

## Decision

Extend `output_guard` with deterministic, LLM-free containment that is structural,
not keyword-based:

1. **Continuation folding.** When a recognised decision / proposal / sizing header
   has no value on its own line, the next non-blank physical line is treated as
   its value *if* it is a direction value (bare word, or a direction word leading
   an explanation, tolerating a Markdown bullet/number/heading prefix). The header
   is pinned to `**<Label>**: Hold` / `FINAL TRANSACTION PROPOSAL: **HOLD**` /
   `not applicable`; a direction value's explanation is kept as the rationale tail
   (`**Action**: Hold because valuation is attractive.`); the value line and any
   intervening blank lines are dropped.

2. **Anchored executable-sentence fallback.** A line that *leads* with a trade
   verb (buy/sell/short/exit/stop/enter/close/add/trim/reduce) after an optional
   bullet/number/heading prefix and carries a quantity/price/size token is a live
   instruction and is neutralised to a non-executable notice.

2a. **Executable-tail stripping in a recognised decision value.** A same-line
   decision header captures one value word; any executable sizing/price/quantity
   tail (``Action: Buy 100 shares at $100``) or a pure residual direction-word
   tail (``**Action**: Strong Buy`` -> value ``Strong``, tail ``Buy``) is stripped,
   keeping only a clearly separated rationale clause (``because``/``since``/``as``/
   ...): ``Action: Buy 100 shares at $100 because valuation is attractive`` ->
   ``**Action**: Hold because valuation is attractive``. Ordinary rationale
   adjectives (``case was weak``) are not treated as executable.

2b. **Bounded unsupported-value fail-closed.** An unrecognised, value-like short
   line (<= 3 emphasis-wrapped words) in a recognised decision value position
   (``**Strong Buy**`` / ``Strong Sell now``) is not trusted: the header is pinned
   to Hold and the value line dropped, rather than trusting an unrecognised
   direction variant.

3. **Structural exemption only.** A line is exempt (preserved verbatim) only when
   the leading trade verb sits *inside* a quoted span, or the line does not lead
   with a command verb at all (so unanchored prose such as `We rejected "Buy ..."`
   and `Earlier proposal: Buy ... It was not executed.` never match). There is
   **no** blanket keyword immunity: `earlier` / `considered` / an incidental
   quotation in a line that starts with a trade verb does not save it. Blockquotes
   are excluded (quoted commentary).

## Consequences

- A blocked run's stored plan / saved report / memory body cannot keep an
  executable direction, fill, exit, stop or size in the supported and the
  unsupported-format cases above; the conclusion stays `Hold`.
- Genuine rationale, quoted alternatives, negated/historical discussion and
  recovery conditions survive; the multiline direction explanation is preserved.
- The pass stays linear (single anchored token scan), idempotent, and
  deterministic; LF/CRLF, whitespace, Markdown and fullwidth variants are covered.
- Limits: exemption is positional, so a contrived line that leads with a trade
  verb but is *meant* as prose (e.g. a rhetorical "Buy we did not pursue") is
  contained rather than preserved — an acceptable fail-closed trade-off for a
  blocked run. Numeric confidence ceiling (DEBT-014) and automatic optional
  adapters (DEBT-015/RISK-015) remain out of scope and unchanged.

## Verification (structural + behavioral offline)

- `tests/test_output_guard.py`: 197 passed (24 multiline + 14 first-review
  boundary + 15 second-review boundary + final-F1 executable-tail / unsupported-
  value direct + fake-Trader cases; normal/degraded unchanged; quoted/negated
  rationale preservation; direction-explanation tail; long-line linear time).
- Strict fully offline suite with `socket.socket.connect` disabled
  (`pytest -q -p no:cacheprovider -m "not integration"`): **4 failed / 1743
  passed / 1 skipped / 1 deselected** — the SAME four known baselines
  (`test_no_data_handling` empty-download + 3 date-sensitive
  `test_ohlcv_cache_freshness`); no new regression; **not all-green** (logbook 070).
- Ruff clean; governance validator PASS (35/35, no secrets); `git diff --check`
  clean.

This ADR is **PROPOSED**: it records a safety-critical change for independent
review. It is not human acceptance; no acceptance, CI enforcement, active
permission enforcement, or human score is claimed.
