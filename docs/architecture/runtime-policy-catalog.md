# Runtime policy catalog

**Purpose.** One row per runtime policy that the TradingAgents experiment relies
on: what the rule is, where it is enforced, which test or verifier proves it, and
how much of it is actually mechanical. A policy that exists only in a protocol is
not a runtime policy.

**Status vocabulary:** `ENFORCED`, `PARTIALLY_ENFORCED`, `DOCUMENTED_ONLY`,
`NOT_VERIFIED` (same meaning as `docs/architecture/permission-model.md`).
"Harness path" means a run started through `scripts/token_benchmark.py` with a
registered spec; "product path" means the CLI or a direct
`TradingAgentsGraph.propagate()` call.

**Base.** `50b2ca3` (post-remediation). The frozen V3 evidence was produced at
`e3b5cca`; the freeze is a historical property of that commit, not of `HEAD`.

---

## 1. Catalog

### RP-01 — Data sources: Finnhub-only company news, disabled global news, FRED macro

**Rule.** Company news is Finnhub only. Global news is not borrowed from another
provider: the configured path returns `NEWS_STATUS=CONFIG_DISABLED` and performs
no fetch. Macro is FRED. The registered spec must declare
`company_news=finnhub`, `global_news=finnhub:CONFIG_DISABLED`, and
`gdelt=excluded`.

**Enforcement**

* `tradingagents/default_config.py` sets `tool_vendors["get_news"]="finnhub"`,
  `tool_vendors["get_global_news"]="finnhub"`.
* `tradingagents/dataflows/interface.py` binds the Finnhub key to
  `get_news_finnhub_only` and `get_global_news_finnhub`; `get_news_combined` is
  not in the routing table.
* `scripts/token_benchmark.py::_preflight_gate` refuses a registered spec whose
  `news_scope` is not the frozen one, and refuses any field naming GDELT,
  Alpha Vantage, or Yahoo.

**Test / evidence.** `tests/test_finnhub_only_scope.py` (GDELT tripwire on module
attributes and routing; Finnhub-down case; global-disabled case);
`tests/test_news_dual_source.py`; V2 protocol §4; V3 protocol §12.

**Status.** `ENFORCED` on the registered harness path; `PARTIALLY_ENFORCED` for
generic/CLI runs, where `tool_vendors` remains a mutable config value.

---

### RP-02 — Point-in-time (PIT) data

**Rule.** A run with trade date `D` may not use information published after `D`.
PIT is day-granular: an article dated `D` is treated as available for `D`; an
undated article is dropped in a backtest and kept only in a live window.

**Enforcement**

* `tradingagents/dataflows/date_window.py::as_of` clamps a requested end date to
  the trade date; `as_of_window` does the same for a window.
* Tool wrappers in `tradingagents/agents/utils/` inject the run's trade date as
  the publication cutoff; `propagate()` rejects a non-canonical or future date.
* Finnhub's `_request` path filters on `as_of_cutoff` and drops undated
  articles in a backtest (`tradingagents/dataflows/finnhub_news.py`).
* Fundamentals: live-profile values are withheld for a historical run
  (`tests/test_fundamentals_lookahead.py`).

**Test / evidence.** `tests/test_tool_date_enforcement.py` (model cannot hide the
trade date; future date clamps), `tests/test_fundamentals_lookahead.py`,
`tests/test_news_lookahead.py`, `tests/test_social_lookahead.py`,
`tests/test_pit_notice.py`, `tests/test_undated_tools_as_of.py`.

**Status.** `ENFORCED` on the graph/tool path, with a known granularity limit:
day-granular PIT cannot distinguish an article published at 09:00 from one at
23:59 on the trade date. A direct Python tool call that does not receive the
state's trade date bypasses the clamp (`test_direct_call_without_state_is_unchanged`).

---

### RP-03 — Structured output and fallback

**Rule.** When structured output is enabled, an analyst must return a schema-
valid report. A schema failure is retried once as free text; the report must
never be empty, and protocol markup (DSML `tool_calls` written as text) must
never reach a report field.

**Enforcement**

* `tradingagents/agents/utils/structured.py`: `finalize_analyst_report` /
  `finalize_single_pass`, `_free_text_retry`, `sanitize_analyst_text`.
* The single-pass retry removes the dangling assistant turn and keeps the system
  prompt (`_free_text_retry`); a mixed schema+data turn drops the unexecuted
  schema call; every report exit (prose, two-level fallback, `structured_llm is
  None`) passes through the sanitizer.
* `tests/test_structured_agents.py`, `tests/test_structured_analyst_output.py`,
  `tests/test_final_remediation.py` (20 tests, including R07/R14 fixtures).

**Status.** `ENFORCED` as a contract: a schema failure is handled and a markup
report is sanitized. `PARTIALLY_ENFORCED` as a quality guarantee: the fallback is
free text, so it can still be a weaker report; the V3 data has 5 market fallbacks,
all in single-pass arms.

---

### RP-04 — Usage completeness (U-1)

**Rule.** Every provider call must report usage; every token field must be
present; every call must be attributed. A run with a missing or contradictory
usage payload is not a measured sample. Missing is `null`, never `0`.

**Enforcement**

* `scripts/token_benchmark.py::usage_verdict` returns `VALID` / `MISSING` /
  `INCOMPLETE` / `MISMATCH`; `extract_run_metrics` consumes the verdict and only
  `VALID` yields a sample.
* Event-level checks reject `attribution_type="none"`, a non-true
  `attribution_complete`, an attribution summary that does not sum to the call
  count, a per-call event sum that differs from `run_totals`, and a replay total
  that differs from the telemetry total.
* `tradingagents/observability.py` records `reported_usage_raw`, counts missing
  fields, and never coerces `None` to `0`.

**Test / evidence.** `tests/test_c3_final_freeze.py::TestUsageVerdict` (10 tests);
`tests/test_token_benchmark.py`; `tests/test_observability.py`;
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/CAND01_BATCH_2X2_PROTOCOL_V2.md`
§9.

**Status.** `ENFORCED` on the harness path. A direct graph/CLI run does not call
`usage_verdict`, so this is `PARTIALLY_ENFORCED` system-wide.

---

### RP-05 — Budget contract (U-2)

**Rule.** A null cap is "unlimited" only when the registration explicitly says
`budget_mode="uncapped_authorized"`. A missing file, malformed block, missing
mode, or non-integer cap is a refusal, not an implicit uncapped run. A capped
run refuses further paid calls at the cap.

**Enforcement**

* `scripts/token_benchmark.py::budget_state_from_experiment` distinguishes
  `BUDGET_PROTOCOL_MISSING`, `BUDGET_PROTOCOL_UNREADABLE`,
  `BUDGET_CONFIG_MALFORMED`, `BUDGET_BLOCK_MISSING`,
  `BUDGET_BLOCK_NOT_OBJECT`, `BUDGET_MODE_MISSING`, `BUDGET_MODE_INVALID`, and
  `BUDGET_CAP_INVALID`; `require_budget_state` raises `RunRefused`.
* `_preflight_gate` refuses a frozen-batch spec with no budget block.
* `tradingagents/budget_guard.py::BudgetGate` reports
  `UNCAPPED` / `OK` / `EXHAUSTED` / `UNKNOWN_SPEND`, never presents a lower bound
  as a total, and raises `BudgetExhausted` when a known cap is reached.

**Test / evidence.** `tests/test_budget_guard.py`;
`tests/test_c3_final_freeze.py::TestBudgetContract` (20 cases); V2 protocol
§9/§14.1; `BUDGET_GUARD_DESIGN.md`.

**Status.** `ENFORCED` on the harness/preflight path; `PARTIALLY_ENFORCED`
system-wide. Current batches are `uncapped_authorized`, so the cap *mechanism*
exists but is not active.

---

### RP-06 — Budget caps

**Rule.** If `max_total_tokens` is an integer, the gate blocks once known spend
plus reservations reaches it. A cap that cannot be interpreted raises rather than
defaulting.

**Enforcement**

* `BudgetGate.__post_init__` rejects a bool, non-int, or negative cap.
* `BudgetGate.check()` raises `BudgetExhausted` in `EXHAUSTED`; `remaining` and
  `describe()` mark unknown spend as a lower bound.

**Test / evidence.** `tests/test_budget_guard.py::test_exhausted_at_the_cap_blocks_further_calls`,
`test_reserved_tokens_count_towards_the_cap`,
`test_uninterpretable_cap_raises_rather_than_defaulting`.

**Status.** `ENFORCED` as a mechanism; not active in the registered V2/V3 batches
(`budget_mode="uncapped_authorized"`). The absence of a cap is not evidence of
cost control.

---

### RP-07 — Memory isolation

**Rule.** A registered V3 run starts from an immutable baseline snapshot copied
into its own attempt directory; the baseline hash must not change; a run without
its copy, or with a modified baseline, is invalid.

**Enforcement**

* `scripts/token_benchmark.py::memory_block_for_registration`,
  `prepare_run_memory`, `validate_memory_spec`, `_preflight_gate`,
  `memory_state_after_run`.
* `_config_for_spec` points `memory_log_path` at the run copy before graph
  construction.
* A missing `memory_state.json` is `memory_state_missing`; a changed baseline is
  `memory_snapshot_modified`.

**Test / evidence.** `tests/test_memory_isolation.py` (21 tests);
`tests/test_cand01_batch_16run_v3_infra.py`; V3 protocol §3; audits
`MEMORY_ISOLATION_AUDIT.md`, `MEMORY_SNAPSHOT_PROVENANCE.md`.

**Status.** `PARTIALLY_ENFORCED`: true for registered V3 runs (18/18 attempts
baseline-unchanged), not for generic `measure`, CLI, or direct graph runs, which
still use the shared log (audit A, M3).

---

### RP-08 — Experiment freeze / registered-run gate

**Rule.** A paid run must come from the audited commit, with a clean tree, a
matching release seal, manifest, spec hash, arm matrix, protocol/generator hash,
and tag. A run that cannot prove this is refused.

**Enforcement**

* `scripts/token_benchmark.py::verify_frozen_tree` recomputes the freeze facts in
  the spending process, not just in a separate gate.
* `scripts/c3_verify_final_freeze.py` checks `HEAD == FROZEN_COMMIT`, tree SHA,
  fingerprint, every `MANIFEST.sha256` entry, all 16 `config_sha256` values,
  protocol/generator hashes, and the annotated tag.
* `scripts/c3_preflight_gate.py` adds the release seal, spec/arm/news checks, and
  the import-root check.
* `TRADINGAGENTS_SKIP_FREEZE_CHECK=1` is refused for a run of the frozen batch.

**Test / evidence.** `tests/test_c3_final_freeze.py`,
`tests/test_c3_regressions.py`, `tests/test_cand01_batch_16run_v3_infra.py`.

**Status.** `PARTIALLY_ENFORCED`: fail-closed and tested for the registered
harness path, but (a) `HEAD=50b2ca3` is not the V3 freeze commit (`e3b5cca`), so
the verifier cannot certify it; (b) the freeze metadata is release metadata that is not tracked (and is
absent from this checkout); (c) V3 specs embed absolute build-worktree paths, so generator
`--check` reports `SPEC DRIFT` in a different checkout (observed 2026-11-19);
(d) a direct API/CLI run bypasses the gate entirely. "Frozen" is a property of
the recorded commit, not of the current branch.

---

## 2. Current-state checks (observed 2026-11-19)

| Check | Command | Result |
| --- | --- | --- |
| Freeze verifier | `.venv/bin/python scripts/c3_verify_final_freeze.py` | `FAIL` — `cand01_batch_16run_v2/c3/FREEZE_RECORD.json` missing; the tracked tree cannot certify itself |
| V2/V3 generator check | `gen_cand01_batch_16run_specs_v{2,3}.py --out … --check` | `SPEC DRIFT DETECTED` — 16 `spec.json` files and `RUN_MANIFEST_TEMPLATE.csv`; cause is absolute `experiment_root`/`results_dir` |
| Finnhub-only tests | `pytest tests/test_finnhub_only_scope.py -q` | pass |
| Memory/attribution tests | `pytest tests/test_memory_isolation.py tests/test_system_attribution.py -q` | 34 passed |
| Remediation tests | `pytest tests/test_final_remediation.py -q` | 20 passed |

These are observations, not policy successes. The first two are the reason
RP-08 is not `ENFORCED` at `HEAD`.

## 3. Policy precedence and failure mode

1. A **refusal before a paid call** is the preferred failure: `RunRefused` keeps
   "the run never started" distinct from "the run failed" and preserves the
   evidence.
2. A **invalid run** is retained, never deleted or averaged in; it is not a
   sample.
3. A **documented-only** rule is not a control. In particular, operator
   authorization for a paid run is external to every gate; passing the gate does
   not mean a human approved the spend.

## 4. Evidence index

| Policy | Enforcer | Test |
| --- | --- | --- |
| RP-01 data sources | `default_config.py`, `dataflows/interface.py`, `_preflight_gate` | `test_finnhub_only_scope.py`, `test_news_dual_source.py` |
| RP-02 PIT | `date_window.py`, tool wrappers, `propagate` | `test_tool_date_enforcement.py`, `test_*_lookahead.py`, `test_pit_notice.py` |
| RP-03 structured fallback | `agents/utils/structured.py` | `test_structured_agents.py`, `test_structured_analyst_output.py`, `test_final_remediation.py` |
| RP-04 U-1 | `token_benchmark.py::usage_verdict`, `observability.py` | `test_c3_final_freeze.py::TestUsageVerdict`, `test_token_benchmark.py`, `test_observability.py` |
| RP-05 U-2 | `token_benchmark.py::budget_state_from_experiment`, `budget_guard.py` | `test_budget_guard.py`, `TestBudgetContract` |
| RP-06 caps | `BudgetGate.check` | `test_budget_guard.py` |
| RP-07 memory | `validate_memory_spec`, `memory_state_after_run` | `test_memory_isolation.py` |
| RP-08 freeze | `verify_frozen_tree`, `c3_verify_final_freeze.py`, `c3_preflight_gate.py` | `test_c3_final_freeze.py`, `test_c3_regressions.py` |
