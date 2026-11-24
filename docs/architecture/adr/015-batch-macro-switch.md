# ADR-015 — Batch macro as an ablation switch, not a shipped default

**Status:** Retrospective documentation — human acceptance pending
**Provenance:** Reconstructed from the CAND-01
apparatus and the V3 experiment.
**Related invariants:** INV-22, INV-23.

**D2 renumbering (2026-11-21):** formerly `ADR 003`. Renumbered during the Release-first integration because the
personal `ADR 003` collided with a different Release decision. Code `file.py:line` citations below describe the
tree at the time of writing and are not revalidated by this renumbering.

## Context

The news analyst's prompt tells the model to ground macro commentary in FRED series
such as CPI, core PCE, unemployment, the fed funds rate, the 10-year Treasury, the
yield curve, real GDP, and VIX. Before CAND-01 each series was one tool call. The V3
run shows 7.0–9.2 single-series calls per news analyst in the OFF arms.

The hypothesis was that one batch call would reduce tool-call rounds and therefore
tokens. That hypothesis was worth testing, but it was not obviously true: batching
changes how many calls happen, not how much data is returned. The experiment needed
a switch that could produce a genuine pre-batch arm with every other variable fixed.

## Options considered

### A. Batch unconditionally

**Rejected.** No measured token benefit, and it would change the shipped news
analyst before the evidence existed. It would also remove the single-series fallback
that lets the model fetch one series when only one is missing.

### B. Do not build the batch tool; keep only single-series calls

**Rejected.** It leaves the call-count hypothesis untested and keeps a known
inefficiency (7–9 round trips) that the model can trigger on every news run.

### C. Batch tool behind a switch, single-series retained

The batch tool is bound only when `batch_macro_enabled`; the single-series tool is
always bound. **Chosen.**

### D. Replace the single-series tool with the batch tool

**Rejected.** It removes the per-series fallback, makes a total batch failure the
only outcome, and changes the OFF arm from "pre-batch product" to "different
product". The experiment needs the OFF arm to be the genuine prior behaviour.

### E. Auto-batch when the model requests several series

Implement routing that detects repeated single-series calls and coalesces them.
**Rejected.** It hides the mechanism from the model, changes tool semantics under
the model's feet, and makes the measured unit (a model-chosen tool call) ambiguous.

## Decision

- Add `get_macro_indicators_batch` in `tradingagents/agents/utils/macro_data_tools.py`.
  It accepts a list of aliases/series IDs, deduplicates case-insensitively, refuses
  more than `MAX_BATCH_INDICATORS = 12`, fetches each series through the same
  `route_to_vendor("get_macro_indicators", ...)` call and PIT date as the
  single-series tool, and reports per-series failures inline. If every series fails,
  the result starts with an explicit `DATA_UNAVAILABLE` and the list of failures.
- The input validator is total: bare string, comma-separated string, JSON-ish list,
  tuple, set, dict, malformed bracket text, and `None` all resolve to a list and never
  raise. A model formatting slip must not abort the run.
- Add `batch_macro_enabled`, default `True` (shipped behaviour), read at graph
  construction. When off, the news analyst does not bind the batch tool and does not
  advertise it in the prompt (`news_analyst.py:173-197`); the news `ToolNode` also
  excludes it (`trading_graph.py:253-267`), so an OFF run cannot execute a batch call
  even if the model emits one.
- Keep the single-series tool in both arms.

## Rationale

- The switch is honest: it changes what is bound and prompted, not a flag that is
  read and ignored. Both the analyst and the tool node consume the same config value.
- Retaining the single-series tool makes the OFF arm the genuine pre-batch behaviour
  and makes the ON arm robust when one series is missing.
- The total input coercion is defensive but necessary: LangChain re-raises validation
  errors that are not `ToolInvocationError`, so a malformed list argument would
  otherwise abort the entire run.
- Per-series independence bounds the blast radius of one bad FRED series.

## Consequences

### Positive

- Macro tool calls drop from 7–9 single-series calls (up to 13 total on a mixed AB run) to 1–1.2 batch calls in the ON
  arms, which is a real reduction in round trips and tool-call overhead.
- The batch text is byte-identical per series to the single-series call, so the
  model's evidence does not change; the harness can compare arms without a data
  difference.
- Malformed model arguments are total and never crash a paid run; 18 malformed-input
  cases cover the shapes.
- The OFF arm remains a valid control, which is what makes the 2×2 interpretable.

### Negative

- The switch adds a second place that must agree with the analyst's tool list. A
  future tool added only to one side would make the arms silently diverge; the tests
  pin both bindings and the ToolNode.
- The coercion validator is nontrivial code whose failure mode is silent
  normalisation; it is tested but it is still logic that exists only because models
  emit malformed arguments.
- **The measured token benefit did not materialise.** V3 mean is −17,702/run, but
  NVDA −51,716, AAPL +1,612, XOM −3,002; excluding the environment-degraded R01
  leaves about −695. Total macro payload bytes were roughly unchanged, so this ADR
  records a useful tool with no demonstrated token saving, not a successful
  optimisation.
- The batch can return more data in one result than a single call, so a model that
  batches 12 series may spend more context than it saves in round trips.

## Evidence

- **Code:** `tradingagents/agents/utils/macro_data_tools.py` (tool, validator,
  per-series failure handling); `tradingagents/agents/analysts/news_analyst.py`
  (`batch_macro` parameter, prompt hint only when bound);
  `tradingagents/graph/setup.py:104`; `tradingagents/graph/trading_graph.py:253-267`;
  `tradingagents/default_config.py:131-134`.
- **Commits:** the CAND-01 × batch-macro apparatus landed at `b00dd00`; the switch
  and tool are present in the V3 freeze `e3b5cca`; the final tree is `50b2ca3`.
- **Tests:** `tests/test_macro_batch.py` (faithfulness to the single-series text,
  request order, no invented series, 18 malformed inputs, a 12-shape no-raise safety net,
  partial/total failure, binding in both analyst and ToolNode);
  `tests/test_ablation_switches.py` (`BatchMacroSwitchTest`,
  `test_toolnode_honours_batch_switch`); `tests/test_switch_consumption.py`;
  `tests/test_switch_verification` coverage in `tests/test_c3_regressions.py`.
- **Reports:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`
  (2×2 design, OFF/ON arms); `.worktrees/v3_analysis_review_20261116/FINAL_ANALYSIS_CN.md`
  Q3 (no confirmable token benefit; −51,716 / +1,612 / −3,002; ≈ −695 excluding R01).

## What this ADR does not claim

It does not claim batch macro saves tokens, and it does not recommend enabling it for
cost. It claims the switch is real, the OFF arm is a faithful control, and the tool
reduces tool-call count without altering per-series evidence.
