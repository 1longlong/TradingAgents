# ADR 006 — Structured fallback must be legal, prompt-preserving, and markup-free

**Status:** Accepted (retrospective)
**Date:** Not recorded in the source material. Reconstructed from the V3 analysis and
the remediation commits; no calendar date is asserted.
**Related invariants:** INV-4, INV-5, INV-13.

## Context

The V3 batch exposed three failures in the single-pass fallback path. They were not
model noise; each had a deterministic code cause.

1. **R12 — provider 400 on the retry.** `finalize_single_pass` appended the schema-
   carrying assistant turn to `history` before validating it. When validation failed,
   the old fallback called `llm.invoke(_single_pass_messages(history))`. That replayed
   an assistant turn with a `tool_call` id and no matching `ToolMessage`, which an
   OpenAI-compatible provider rejects; it also used bare `llm` instead of
   `prompt | llm`, dropping the analyst system prompt (the fallback request was
   674/655 bytes versus 6,741 bytes for a normal first call). R12 failed the same way
   on both attempts, always on the fifth request.
2. **R07/R14 — tool-call protocol markup became the report.** When the schema call
   failed, the free-text fallback had no tools bound. The model wrote its native
   DeepSeek DSML tool-call syntax as **text**. The old code returned that text as
   `market_report`. R07 carried 1,922 chars (real analysis inside the `summary`
   parameter); R14 carried 346 chars (one snapshot call, no analysis). Downstream
   agents then read protocol tokens instead of price evidence.
3. **Single-pass tool rounds were invisible.** `run_data_tools` executed tool batches
   inside the analyst node, bypassing the graph `ToolNode` where rounds were counted.
   V3 telemetry therefore reported `tool_rounds = 0` for runs that had several rounds,
   which makes the experiment's tool-cost analysis and the audit trail wrong.

The common thread is that fallback paths are where contracts quietly break: they are
rare, they are exercised only on failure, and they were not held to the same
message-shape and provenance rules as the success path.

## Options considered

### A. Remove the fallback; fail the run on a schema error

**Rejected.** One malformed model reply would abort a paid run and lose all evidence
gathered before it. RC1's contract is that a shape change never blocks a run.

### B. Catch the error and return an empty report

**Rejected.** An empty `market_report` looks like "no analysis was needed", not like
"the model failed". Downstream agents would silently reason without market evidence.
The project has an explicit `REPORT UNAVAILABLE` vocabulary for this reason.

### C. Retry harder / with a different temperature

**Rejected.** R12 reproduced on every attempt at the same request, so it was a
deterministic message-shape bug, not sampling variance. Retrying the same illegal
request would spend more tokens to fail the same way.

### D. Repair the message history, preserve the prompt, sanitise markup

**Chosen.** A single `_free_text_retry` helper drops a trailing tool-call-only
assistant turn, invokes through the caller's `prompt | llm`, and sanitises the result.
`sanitize_analyst_text` is applied at every report exit and never returns markup, never
returns `""` silently, and never discards recoverable analysis.

### E. Strip all angle-bracket / markup-like content

**Rejected.** It is over-broad and lossy: R07's `summary` parameter contained the only
analysis in the reply, and a "delete everything in angle brackets" filter would have
deleted it. The sanitizer extracts named analysis parameters and preserves prose before
the first protocol marker.

### F. Re-run the paid V3 batch after the fix to re-measure

**Rejected for this delivery.** It would be a new experiment with a new code version,
not a re-interpretation of V3. The remediation is verified with offline fixtures and
mutation tests; the V3 numbers remain attributed to `e3b5cca`. This is a deliberate
evidence boundary, recorded in the residual list.

## Decision

1. **One retry helper.** `_free_text_retry(prompt, llm, history, agent_name)`:
   - drops `history[-1]` only when it is an assistant turn with `tool_calls` (so a
     normal prose reply and a properly paired tool sequence are not damaged);
   - calls `(prompt | llm).invoke(messages)` so the analyst system prompt is present;
   - sanitises the returned text.

   All single-pass fallback exits use it: schema-validation failure, empty prose /
   exhausted budget, and the two `structured_llm is None` exits. The two-call
   `finalize_analyst_report` failure branch is also sanitised.

2. **Mixed-turn repair.** When a turn carries both the schema call and data calls,
   execute the data calls and strip the schema call from the assistant turn before the
   next request, so no unresolved `tool_call` id is sent. This was audit A's additional
   finding; the test is `test_a_mixed_schema_plus_data_turn_leaves_no_dangling_call`.

3. **Markup sanitiser.** `sanitize_analyst_text` (`structured.py:392-481`):
   - clean text → unchanged;
   - prose before the first protocol marker, if at least
     `MIN_RECOVERED_REPORT_CHARS = 120`, → keep that prose;
   - otherwise recover values from analysis-bearing DSML parameter names
     (`summary`, `analysis`, `interpretation`, `risks`, `key_levels`, `key_figures`,
     `invalidation`, `scenario_set`, `catalysts`, `valuation`, …) and join them;
   - otherwise return an explicit `[REPORT UNAVAILABLE — …]` template, never markup,
     never `""`;
   - record one `markup_sanitized` structured event and a warning on every path.

4. **Truthful rounds.** `run_data_tools` records exactly one `ToolRoundEvent` per
   non-empty model tool batch, marks `status="error"` when every call in the batch
   failed, records nothing for an empty batch, and does not double-count the graph's
   `ToolNode` path (`structured.py:668-699`, `observability.record_tool_round`).

5. **Telemetry accounting.** The markup event has its own
   `structured_markup_sanitized` counter and is not folded into
   `structured_attempts`/`structured_fallbacks`, preserving
   `attempts == successes + failures + unsupported`.

## Rationale

- A fallback is still a provider request. It must satisfy the same message-pairing and
  prompt-provenance rules as the primary request; otherwise the "graceful" path is
  worse than a clean failure.
- Provenance beats content matching. The sanitiser identifies protocol markup by its
  markers and extracts known analysis fields; it does not guess from prose. Similarly,
  the news guard decides availability from ToolMessages, not from the report's words.
- An explicit unavailable report is more truthful than an empty string and more useful
  than markup. It tells downstream that evidence is missing, which is a semantically
  valid input; empty text is ambiguous.
- Keeping the historical V3 numbers attached to `e3b5cca` prevents a fix from being
  retroactively credited with an improvement it was never measured on.

## Consequences

### Positive

- R12's 400 is fixed at all three fallback exits; a retry now carries no dangling call
  and keeps the system prompt. Regression tests and mutation tests pin both properties.
- R07-style mixed prose + markup keeps its analysis; R14-style markup-only becomes an
  explicit unavailable report. Neither can leak markup into `market_report`.
- Single-pass runs now report real tool rounds; the telemetry and the analysis can
  distinguish "no rounds" from "rounds not counted".
- Structured attempt identities still balance, so audit B's invariant is preserved.
- The pre-fix detection probe reports 4/4 defects on `e3b5cca` and 0/4 on the fixed
  tree; four mutations (dangling turn, bare `llm.invoke`, skipped sanitise, deleted
  round hook) are each caught by a named test.

### Negative

- The fallback surface is now larger and must be maintained: message pairing, prompt
  preservation, markup parsing, and separate counters all interact.
- The sanitiser is a whitelist. A future schema field that carries analysis but is not
  in `_ANALYSIS_PARAMETER_NAMES` will be dropped rather than recovered. That is safer
  than guessing, but it is a real limitation.
- Markup recovery is best-effort; it does not attempt to "repair the model". The model
  can still return markup next time; the guarantee is only that it cannot become the
  report.
- A blank model answer still produces a blank report. The sanitizer cannot invent
  analysis; the code logs the anomaly and leaves `report_obj = None`.
- No paid re-run validates the fixed behaviour end-to-end against the real provider;
  the evidence is offline fixtures, 20 new tests, and mutation checks.

## Evidence

- **Code:** `tradingagents/agents/utils/structured.py` (`_free_text_retry`,
  `_terminal_messages`, `_strip_partial_schema_call`, mixed-turn handling,
  `sanitize_analyst_text`, `run_data_tools`, `SINGLE_PASS_MAX_ROUNDS`);
  `tradingagents/observability.py` (markup counter, tool-round recording).
- **Commits:** `e0ea1b0` and `e9eed04` are the R12 fix commits named in the task
  record; the remediation series ends at `50b2ca3` (tag
  `cand01-v3-final-remediation`). The frozen V3 tree `e3b5cca` is intentionally not
  moved.
- **Tests:** `tests/test_final_remediation.py` — 20 tests across
  `TestR12Fallback` (dangling call, system prompt, complete pairing, second failure,
  normal output), `TestAuditAFollowUps` (prose sanitisation, `structured_llm is None`,
  mixed turn, prose-before-markup, field recovery), `TestDsmlSanitizer` (clean text,
  R07 fixture, R14 fixture, end-to-end fallback), `TestMarkupTelemetry` (one attempt,
  own counter), and `TestToolRounds` (one batch = one round, two rounds, no call = no
  round, telemetry payload, failing tool still a round).
- **Reports:** `token_benchmarks/final_remediation_20261116/R12_FALLBACK_FIX.md`,
  `DSML_MARKET_REPORT_FIX.md`, `TOOL_ROUNDS_TELEMETRY_FIX.md`,
  `FINAL_REMEDIATION_REPORT_CN.md`, `TEST_RESULTS.md`, `INDEPENDENT_AUDIT.md`;
  `.worktrees/v3_analysis_review_20261116/FINAL_ANALYSIS_CN.md` Q5/Q7 (the failures
  and the root cause).
- **Probe/mutation evidence:** `token_benchmarks/final_remediation_20261116/tests/pre_fix_detection_probe.py` (4/4 detected
  pre-fix, 0/4 post-fix); mutation table in `TEST_RESULTS.md` §5.

## What this ADR does not claim

It does not claim all markup can be recovered, that every future report exit will be
sanitised, or that the fixed tree has been re-measured against the live provider. It
claims the three known failure mechanisms are fixed, every known report exit is
covered, the retry is a legal provider request, and the fixes are pinned by tests that
fail when the fix is reverted.
