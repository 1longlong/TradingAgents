# ADR 001 — Provider-usage observability with agent/system attribution

**Status:** Accepted (retrospective)
**Date:** Not recorded in the source material. This decision is reconstructed from the
freeze chain and the observability code; no calendar date is asserted.
**Review evidence:** three independent audit passes are recorded in
`token_benchmarks/final_remediation_20261116/INDEPENDENT_AUDIT.md`; this ADR does not
claim they approved this document, only that the implementation they audited is the
one described here.
**Related invariants:** INV-1, INV-2, INV-3, INV-13.

## Context

RC1 could count LLM calls, but the count could not answer the questions the
experiment needed: *which agent spent the tokens*, *did the provider actually report
usage*, and *what happens when it did not*. Three concrete failures forced a design:

1. **Missing usage was being read as zero.** A provider response without a usage
   payload is not a zero-token call; treating it as one understates spend and makes a
   partial measurement look complete.
2. **Attribution was not established by the runtime.** The pre-graph Reflector calls
   `quick_thinking_llm.invoke()` outside every graph node
   (`trading_graph.py:360-408`). In V2 that call had no scope, was recorded as
   `unattributed`, and voided R06 even though 21/21 calls carried usage
   (`BRANCH_HISTORY_REPORT.txt`, V2 section).
3. **The aggregate agreement check was computed but not consumed.** Audit U-1 found
   that a replay disagreement still left a run marked valid; a check that cannot fail
   is not a check.

The experiment also had a hard privacy constraint: token and cost evidence must be
auditable without storing prompt bodies, news feeds, tool results, or model output.

## Options considered

### A. Keep SDK/global aggregate totals only

Use the callback handler's existing total-token counters and keep the run-level
numbers. **Rejected.** It cannot attribute spend, cannot distinguish "provider
reported 0" from "provider said nothing", and cannot detect a self-inconsistent
payload.

### B. Reconstruct attribution after the run from logs or an external tracer

Parse LangSmith/LangChain traces or application logs post hoc. **Rejected.** It adds
an external dependency to the evidence chain, depends on trace retention, and either
stores raw content or loses the call-to-agent mapping. The experiment must be
reproducible from the artifact alone.

### C. Attribute the pre-graph Reflector to an agent

Label the Reflector call as, say, the portfolio manager so the totals close.
**Rejected.** This is false attribution: it would move a system cost into the
per-agent comparison and corrupt the very measurement the experiment is making. The
system-component bucket exists specifically to avoid this.

### D. Callback collector + ContextVar attribution + explicit system components

One `RunMetricsCollector` per run, a LangChain callback handler that records logical
calls and tool executions, a `ContextVar` that carries either an `agent` id or a
`system` component id, and a `none` state that is reported rather than hidden.
**Chosen.**

## Decision

Adopt the callback-based collector with three attribution kinds:

- `agent` — set by `attrib_agent_node` around every business-agent node, using the
  stable ids in `tradingagents/observability.py:137-202`.
- `system` — set by `system_component_scoped`; the only shipped component is
  `pre_graph_reflector` (`observability.py:151-163`, `381-405`).
- `none` — no scope. The event goes to the `unattributed` pseudo-agent, the run's
  `attribution_complete` is false, and the experiment harness marks the run
  `INCOMPLETE` (`scripts/token_benchmark.py:569-790`).

Provider usage is authoritative. Missing usage is `UNKNOWN`/`PARTIAL`, never zero;
a usage payload that omits a field increments a named missing-field counter
(`observability.py:881-923`). `run_totals` is the sum over agent, system, and
unattributed buckets, so no call disappears from the total because of who made it
(`observability.py:1856-1900`). The artifact is one atomic JSON per run at
`<results_dir>/<safe_ticker>/<date>/telemetry/<run_id>.json`, schema version 2
(`observability.py:711`, `2262-2308`).

## Rationale

- It records at the only place identity is knowable — the execution scope — instead
  of inferring identity from generated text, model names, or call order.
- It keeps the system bucket visible. A system call is not an agent, but it is still
  spend; excluding it would make the totals lie, and relabelling it as an agent
  would make the per-agent comparison lie.
- It fails closed at the experiment boundary, not by aborting the product. The
  product keeps running; the sample is marked invalid. That is the correct trade for
  a measurement harness.
- The callback records sizes, counts, hashes, and sanitized usage payloads only, so
  the privacy constraint is structural, not a policy on top.

## Consequences

### Positive

- V2 (5 valid samples) and V3 (15 valid samples) both achieved 100% provider-usage
  coverage on valid samples: 99/99 and 298/298 calls. Totals close per run and were
  independently recomputed.
- R06's failure could be diagnosed as attribution, not usage; the V3 run was not
  invalid for that reason.
- Per-agent token rankings became possible (V3: market 757,866; fundamentals
  576,117; news 536,017; the rest split among downstream nodes), which is what made
  the single-pass attribution analysis meaningful.
- The per-event / per-call replay check turns a self-report into a cross-check.

### Negative

- The instrumentation is invasive in wiring terms: every node and tool node must be
  wrapped, and the wrappers are a permanent maintenance surface.
- ContextVar scope is easy to get wrong under nesting; the code has explicit
  restoration and identity guards, and the tests cover exception and concurrency
  paths, but a future caller can still use the wrong scope.
- The schema evolved (version 2) and every consumer must tolerate both the legacy
  aggregate shape and the per-call shape. `usage_verdict` explicitly reports legacy
  payloads as "inconclusive" rather than inventing a mismatch.
- Attribution completeness is an experiment-harness verdict, not a product runtime
  failure. A production user can still run without reading telemetry.

## Evidence

- **Code:** `tradingagents/observability.py` (collector, handler, attribution,
  telemetry builder, artifact writer); `tradingagents/graph/setup.py:130-158`
  (agent/tool wrapping); `tradingagents/graph/reflection.py` (system scope);
  `scripts/token_benchmark.py:569-790` (`usage_verdict`), `tradingagents/budget_guard.py`.
- **Commits:** `866133d` (token benchmark infrastructure), `6057b52` (U-1, U-2,
  A-00, dry-run and freeze designation fixes), V3 freeze `e3b5cca`; remediation
  `50b2ca3`. The V3 report names `6e66dca` as the candidate and `f19d6ed` as the
  increment reviewed by the audits.
- **Tests:** `tests/test_observability.py` (callbacks, missing/partial usage,
  collector isolation, privacy, run totals, lifecycle);
  `tests/test_system_attribution.py` (system bucket, totals close, unscoped call
  invalid, scope restoration, tamper guard);
  `tests/test_c3_final_freeze.py::TestUsageVerdict`,
  `TestRawUsageIsPreserved`, `TestEmptyRunIsNotComplete`;
  `tests/test_c3_regressions.py` (cached-input accounting, replay checks,
  fingerprinting).
- **Reports:** `BRANCH_HISTORY_REPORT.txt` §3.1 and V2/V3 counts;
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/REFLECTOR_ATTRIBUTION_AUDIT.md`;
  `.worktrees/v3_analysis_review_20261116/FINAL_ANALYSIS_CN.md`.

## What this ADR does not claim

It does not claim that every future provider path is attributed, nor that a run with
missing usage fails at runtime. It claims that the measured runs' artifacts carry
provider-reported usage, that missing usage is not converted to zero, and that the
experiment harness refuses an unattributed sample.
