# ADR 002 — Single-pass structured finalisation behind an off-by-default switch

**Status:** Accepted (retrospective)
**Date:** Not recorded in the source material. Reconstructed from the CAND-01 commit
series and the V3 analysis; no calendar date is asserted.
**Related invariants:** INV-4, INV-9, INV-13.

## Context

The three tool-loop analysts (market, news, fundamentals) fetch data over several
turns. RC1 ends the loop with a full prose report, then pays a second call that
re-sends the whole history and asks the model to rewrite the same analysis as typed
fields. The prose is then discarded. That is two generations of the same content.

The V2 pilot made the cost concrete: the discarded prose turn averaged 4,151 output
tokens across 12 analyst finalisations, while the replacement call's input was within
156 tokens of it (`structured.py:856-900` docstring, quoting the RC1 2×2 pilot). The
V2 R02 (NVDA/AB) run is the pathological example: 8 `get_news` calls, 10 tool rounds,
339,738 tokens, news analyst alone 138,321.

CAND-01 asked whether the second generation can be removed without breaking the
report contract or the graph's turn-taking. It is an experiment, not a presumed
improvement: the shipped configuration must remain RC1.

## Options considered

### A. Keep the RC1 two-call path unconditionally

**Rejected as the only path**, not as the default. It is the safe baseline and stays
the shipped behaviour, but it leaves a measured repeatable cost on every analyst
finalisation.

### B. Let the model write prose, then parse the prose into the schema post hoc

**Rejected.** A parser would have to invent absent fields or fail on prose that does
not enumerate them. It also does not remove a generation; it adds a parsing failure
mode on top. The project had already rejected "extract fields from prose" in favour
of generation-time structuring.

### C. Bind the schema on every tool turn

**Rejected.** The schema travels as a tool definition. Re-sending it on every data
turn multiplies its input cost and competes with the data tools; it also makes the
model likely to answer early on a turn that should have fetched evidence.

### D. Bind the schema as one more tool, and end when the model calls it

The model keeps its data tools. When it is ready to answer, it emits the schema tool
call instead of prose; that call *is* the report. **Chosen.**

### E. Enable single-pass by default after V2

**Rejected.** V2's single NVDA block was not enough, and V3 subsequently found
format failures concentrated in the single-pass arms. Enabling by default before a
post-remediation re-run would ship an unvalidated quality trade.

## Decision

Implement `finalize_single_pass` (`structured.py:856-1087`) and expose it through
`single_pass_finalization_enabled`, default `False`
(`default_config.py:138-143`). It only takes effect when
`structured_analyst_output_enabled` is also true (`setup.py:88-93`).

The loop:

1. Binds `[*tools, schema]` and invokes `prompt | bound` over the growing history.
2. Accepts a schema call as terminal only when the same turn asks for no data tool.
3. On a mixed turn, executes the data calls first and strips the schema call from the
   assistant turn, so no unresolved call id is replayed.
4. On a data-only turn, executes the batch through `run_data_tools`, which re-injects
   the hidden PIT `trade_date` and records one tool round per non-empty batch.
5. Returns a legal terminal sequence: every executed data call is paired with its
   `ToolMessage`, and the last turn has no pending call.
6. On schema validation failure, budget exhaustion, or total tool failure, retries
   once as free text through `prompt | llm`, then returns prose with
   `report_obj = None`. It never returns markup and never fabricates a typed object.

`SINGLE_PASS_MAX_ROUNDS = 4` is a safety stop, not a policy; hitting it degrades to
the free-text ending rather than dropping evidence.

## Rationale

- The saving mechanism is structural: one full-context generation is removed, not
  the evidence and not the analysis length. V3's stored analysis characters were
  higher in the single-pass arms, which supports "not writing less" even though it
  does not prove quality.
- Binding the schema beside the data tools preserves the agent's ability to keep
  fetching. It does not force an early answer.
- Keeping the switch off by default makes the change reversible and keeps the
  shipped product on the path that had the most validation.
- Every fallback lands on RC1 behaviour, so the feature can only change the report's
  shape, not whether a run completes. That property is what made the experiment
  ethically and operationally acceptable.

## Consequences

### Positive

- V3 balanced mean: **−19,589 tokens/run (−8.96%)**, with all three complete blocks
  negative (NVDA −8,907, AAPL −16,390, XOM −33,472). The mechanism is concentrated in
  the three analysts; downstream nodes gave back about +8,921.
- LLM calls fell in the expected nodes (news 4.63→3.25, fundamentals 4.00→3.13,
  market 4.13→3.79).
- The design produces a typed report on success while preserving `report_obj = None`
  on every fallback, so downstream code cannot mistake prose for data.

### Negative

- It introduced a new fallback surface. V3's CC arm had two market reports that were
  raw DSML markup (R07/R14) and one provider 400 (R12). Those are the direct reason
  for ADR 006 and for the off-by-default status.
- The ordinary success path is harder to reason about than RC1: mixed turns,
  double-schema turns, budget exhaustion, and tool failure all need their own
  terminal-message handling. The test file is correspondingly large.
- It does not guarantee a non-empty report. If the model emits `""`, the result is
  `""`, logged and not dressed up as a typed report (residual, also true of RC1).
- A historical V3 telemetry field, `tool_rounds`, reads 0 because the runner did not
  record rounds at the frozen `e3b5cca`; the fix applies to new runs only.

## Evidence

- **Code:** `tradingagents/agents/utils/structured.py` (`finalize_single_pass`,
  `run_data_tools`, `_terminal_messages`, `_free_text_retry`, `_single_pass_messages`,
  `_strip_partial_schema_call`); `tradingagents/agents/analysts/{market,news,fundamentals}_analyst.py`;
  `tradingagents/default_config.py:138-143`; `tradingagents/graph/setup.py:88-113`.
- **Commits:** `e38ac3e` introduced the switch; `e33ab2c` injected `trade_date` and
  removed the blank ending; `26862d2` fixed PIT injected args, structured telemetry,
  and the legal terminal turn; `ebe81e3` returned executed tool results with their
  calls; `ec629dd` ran data tools on a mixed schema+data turn; `72ae0f8` narrowed
  "mixed" to a data call; `7832a90` classified news provenance after the loop (PF-01).
  R12 and DSML remediation: `e0ea1b0`, `e9eed04`, final `50b2ca3`.
- **Tests:** `tests/test_cand01_single_pass_finalization.py` (schema validation, tool
  loop, hidden-date precedence, terminal routing, fallbacks, news missingness,
  telemetry lifecycle, compiled-graph loops, mixed turns, double-schema turns,
  mode compatibility); `tests/test_final_remediation.py` (R12 and DSML regressions);
  `tests/test_ablation_switches.py` (switch plumbing).
- **Reports:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/FINAL_ENGINEERING_REPORT_CN.md`
  and `EXPERIMENT_PROTOCOL_V3.md`; `.worktrees/v3_analysis_review_20261116/FINAL_ANALYSIS_CN.md`
  (Q1–Q8, including the explicit n=1 and no-significance caveats).

## What this ADR does not claim

It does not claim a statistically significant saving, a quality improvement, or that
single-pass is safe to enable by default. The V3 effect is descriptive, on one model,
one date, four tickers, and n=1 per cell. The shipped default is off, and the
remediation was verified offline rather than by a new paid batch.
