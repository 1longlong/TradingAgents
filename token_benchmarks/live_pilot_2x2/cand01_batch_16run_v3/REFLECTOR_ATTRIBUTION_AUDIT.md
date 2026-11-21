# Reflector attribution — root cause, fix, evidence

## 1. Root cause (confirmed in the 2026-11-16 telemetry)

`propagate()` calls `_resolve_pending_entries(ticker)` *before* `graph.invoke()`.
For a pending decision-log entry with resolvable returns it calls
`Reflector.reflect_on_final_decision()` → `quick_thinking_llm.invoke(messages)`.
Agent attribution is installed only by `attrib_agent_node` inside graph nodes,
so that provider call had no scope and was recorded as `unattributed` (R06,
`global_sequence=0`, 1,479/146 tokens, 2 messages = the reflector prompt).

## 2. Fix

A single attribution context replaces the agent-only ContextVar
(`tradingagents/observability.py`):

| Scope | `attribution_type` | Fields |
| --- | --- | --- |
| `agent_scoped(agent_id)` | `agent` | `agent_id` |
| `system_component_scoped(component_id)` | `system` | `component_id` |
| no scope | `none` | `agent_id="unattributed"` |

* The context is a `ContextVar`, restored in `finally` on success, exception and
  cancellation; nesting is supported (an agent scope inside a system scope wins
  for its block and restores the system scope afterwards).
* `Reflector.reflect_on_final_decision` wraps **only the `invoke`** in
  `system_component_scoped("pre_graph_reflector")`. Prompt, model, temperature
  and call logic are unchanged; the call is never relabelled as an analyst.
* Telemetry (schema 2) records per event `attribution_type` and `component_id`,
  aggregates system components in their own `system_components` bucket, and
  reports `attribution` totals (agent / system / unattributed calls and tokens).
* `run_totals` sum agents + system components + unattributed: no call is
  dropped from the total because of who made it.
* A `none` event still makes `audit_quality.attribution_complete=false` and the
  run `INVALID` (`token_usage_incomplete`); the harness (`extract_run_metrics`)
  accepts `system` as legitimate attribution.

## 3. Evidence

| Check | Result |
| --- | --- |
| `tests/test_system_attribution.py` | 10/10 pass |
| reflect call → `system_components["pre_graph_reflector"]`, no agent bucket | pass |
| totals close: agent 15 + system 15 + unattributed 0 = 30 | pass |
| scope restored after success/exception, inside an agent scope | pass |
| unscoped call → `attribution_type="none"`, run INVALID | pass |
| harness: valid system event keeps `usage_verdict=VALID`; unattributed → INVALID | pass |

No paid call was made to test this; the callback path is driven with a fake
chat model that reports provider usage.
