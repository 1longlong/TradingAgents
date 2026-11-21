# Runtime Policy Catalog

This catalog lists the deterministic policy/config surface that controls the
CS5351 feature behavior. It is the reference for the settings that are
validated before graph execution, plus their safe defaults. The authoritative
default values live in the source; this document records their meaning.

## Data Quality Gate policy (evidence)

`tradingagents/evidence/policy.py` defines `MarketPolicy`, `MarketRecordPolicy`,
and `MetricTolerance` using quantized `Decimal`. The `policy_version` is carried
on every `GateDecision` for auditability (`NFR-AUD-001`).

| Setting | Meaning | Default |
| --- | --- | --- |
| `policy_version` | Stamped policy version on every gate verdict | (recorded on the policy object) |
| `min_independent_sources` | Independently credible sources required for a `High` group | see `DEFAULT_MARKET_POLICY` |
| threshold tolerances | Per-metric Decimal tolerances for cross-source consistency | see `MetricTolerance` |

Semantics are confirmed by the policy object; the exact numeric defaults are in
`tradingagents/evidence/policy.py` and are not re-invented here.

## Debate termination policy (config)

`tradingagents/debate/config.py` defines `DEFAULT_DEBATE_TERMINATION_CONFIG`
(tuned by `resolve_debate_termination_config`). All fields are validated by
`DebateTerminationConfig.validate`; a frozen instance cannot diverge afterward.

| Setting | Meaning | Default |
| --- | --- | --- |
| `enabled` | `True` uses dynamic rules; `False` reproduces legacy fixed-round routing | `True` |
| `no_new_evidence_patience` | Rounds of no-new-valid-evidence before `no_new_evidence` stop | `1` |
| `stance_distance_threshold` | Max rating distance for "stances close" | `1.0` |
| `confidence_delta_threshold` | Max confidence delta for "close" and "material change" | `0.25` |
| `max_calls` | Hard limit on **debate** calls (NOT the whole-run call count) | `2_000_000` |
| `max_tokens` | Hard limit on **debate** tokens, compared against the deterministic estimate (NOT a measured provider bound) | `2_000_000` |
| `max_time` | Hard limit on **debate** elapsed seconds, compared against the deterministic estimate (NOT measured wall-clock) | `600.0` |
| `reserved_summary_tokens` | Reserved summary token reserve | `4_000` |
| `reserved_summary_seconds` | Reserved summary time reserve | `90.0` |
| `next_round_estimate_tokens` | Estimated next-round token cost for budget accounting | `2_000` |
| `next_round_estimate_seconds` | Estimated next-round time cost for budget accounting | `60.0` |
| `max_debate_rounds` | Legacy fixed-round cap (used when `enabled=False` / rule ordering) | `1` |
| `evidence_manifest_field` | AgentState field holding gate manifest evidence records | `data_quality_evidence_records` |
| `trace_field` | AgentState field holding the termination decision trace | `debate_termination_decision` |

## Budget accounting (corrected 2026-11-06)

`tradingagents/debate/budget.py` estimates and accounts for token/time/call
usage deterministically. Important corrections to earlier wording:

- The summary reserve is checked **before EVERY Bull/Bear admission** (a
  conservative pre-call guard in `can_afford_optional_call`), not merely before a
  `continue` verdict. The check requires
  `remaining >= reserved_summary + next_round_estimate`, with exact token/time
  boundaries tested before the first Bull and before Bear
  (`tests/test_debate_precall_budget.py`).
- The limits are **debate-scoped** (`max_calls`/`max_tokens`/`max_time` bound the
  debate optional calls), **not** whole-run limits. The call limit concerns debate
  calls, not total-run calls.
- Token/time figures are **deterministic ESTIMATES** (char-based), **not actual
  provider bounds**. The guard cannot be claimed to enforce physical provider
  usage.
- **Live discrepancy (historical, 2026-11-06 — now addressed offline):** that
  authorized live run showed the char-based estimate was wildly off (Bull
  estimated 2,171.77 s vs actual 12.72 s; 16,289 estimated vs 18,058 reported
  tokens), so the estimate exhausted the debate time budget and Bear was refused
  with `budget_exhausted` before any complete round. The guard was active and
  safe; the accounting basis was the defect.
- **Correction applied by ADR-007 (2026-11-10, offline; live-confirmed for one
  round in a bounded run):** each real Bull/Bear call is timed with an injectable
  monotonic clock and uses provider-reported token usage when valid, with an
  explicitly-labelled estimate fallback; invalid/backwards/non-finite clocks
  abort rather than reviving char-time estimates.
- **Correction applied by ADR-009 (2026-11-11, offline):** a durable run-scoped
  SQLite ledger writes a reservation before every outbound call and settles it
  after, reconciles idempotently on resume, and fails closed on unresolved
  in-flight spend.
- The residual is explicit: hidden SDK transport retries are unobserved
  (`transport_attempts` unknown), a pre-call reservation is an estimate rather
  than a physical billing bound, and live cross-process concurrency is
  offline-barrier-proven only. Do not describe the guard as enforcing physical
  provider usage.

## Enforcement

A misconfigured `debate_termination` block raises `ValueError` in `validate`
before graph execution, so a bad config is reported explicitly rather than
silently degrading to a default (`FR-DDT-004`, `NFR-BC-001`).

## Failure / degraded behavior: trigger → action → audit hook → recovery

This table records what the code **actually** does today (`REAL`), and marks
`PENDING` where no fallback/implementation exists (do not invent one). Where the
status is `PENDING`, the correct behavior is to **STOP and make no completed-report
claim** rather than proceed.

| Trigger | Action (actual) | Audit hook (actual) | Recovery / status |
| --- | --- | --- | --- |
| Missing **critical** market evidence / gate internal error | Fail closed → gate `blocked`; router skips debate → Research Manager; output pinned to Hold | `data_quality_error`, `data_quality_gate_decision`, gate_summary, `gate_blocked` reason | **REAL** (offline-tested). Live blocked-path not exercised (RISK-023). |
| Missing **optional** category (fundamentals/news/sentiment) with no trustworthy structured source | Deterministic `Low`/`unavailable_no_structured_source`; may degrade but never block (market is critical) | `data_quality_group_statuses`, gate_summary category table | **REAL** (observed live 2026-11-06: all optional Low → degraded). Automatic adapters OPEN (DEBT-015). |
| Malformed `DEBATE_METADATA` (missing marker) | Parse contributes **zero** new evidence; never extends the debate (best-effort prose fallback) | turn parse result / decision trace | **REAL** (offline-tested, FR-DDT-002). |
| Pre-call budget refusal (remaining < reserve + estimate) | Refuse the optional call; route to Research Manager with `budget_exhausted` for the incomplete round | `debate_usage` (estimated flag), `budget_exhausted` stop_reason, debate_trace | **REAL** (offline-tested). Basis is ESTIMATE (DEBT-021); live run refused Bear prematurely. |
| Evaluator internal error | Fail closed → `summarize`/`insufficient_evidence` | `debate_termination_decision` trace, `insufficient_evidence` reason | **REAL** (offline-tested). |
| Model / provider failure mid-run | Graph error propagates; no partial "completed report" is claimed | error surfaced by the run harness (no dedicated artifact field) | **PARTIAL / PENDING:** no dedicated in-repo recovery artifact; treat as STOP, do not claim a completed report. |
| Report write / artifact error | `write_report_tree` relies on redaction + safe defaults; a raised error surfaces | report artifacts absent/partial | **PENDING:** no dedicated audit_incomplete fallback artifact exists in this repo; STOP rather than claim a completed report. |
| `audit_incomplete` condition | (no explicit marker emitted by this codebase) | — | **PENDING — NOT IMPLEMENTED.** Recorded as a gap (DEBT-015); do not fabricate a fallback. |

## Still open (unchanged by this documentation round)

- Degraded-run numeric confidence ceiling: OPEN (DEBT-014), not invented.
- Automatic optional multi-category adapters / full source-attempt lifecycle:
  OPEN (DEBT-015 / RISK-015).
- Live measured latency/token budget accounting: OPEN (DEBT-021 / RISK-021).
- Claim-date semantic validation: OPEN (DEBT-022 / RISK-020).
- CLI state-passing hardening: OPEN (as recorded in prior milestones).

---

## Token-observability runtime policies (RP-01…RP-08)

The Release policies above are unchanged. The personal delivery recorded seven additional
runtime policies and one freeze policy as `RP-01…RP-08`. They are complementary: RP-04/RP-05/RP-06
govern the paid-run/experiment path, not the debate budget above.

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

### 1. Catalog

#### RP-01 — Data sources: Finnhub-only company news, disabled global news, FRED macro

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

#### RP-02 — Point-in-time (PIT) data

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

#### RP-03 — Structured output and fallback

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

#### RP-04 — Usage completeness (U-1)

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

#### RP-05 — Budget contract (U-2)

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

#### RP-06 — Budget caps

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

#### RP-07 — Memory isolation

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

#### RP-08 — Experiment freeze / registered-run gate

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

### 2. Current-state checks (observed 2026-11-19)

| Check | Command | Result |
| --- | --- | --- |
| Freeze verifier | `.venv/bin/python scripts/c3_verify_final_freeze.py` | `FAIL` — `cand01_batch_16run_v2/c3/FREEZE_RECORD.json` missing; the tracked tree cannot certify itself |
| V2/V3 generator check | `gen_cand01_batch_16run_specs_v{2,3}.py --out … --check` | `SPEC DRIFT DETECTED` — 16 `spec.json` files and `RUN_MANIFEST_TEMPLATE.csv`; cause is absolute `experiment_root`/`results_dir` |
| Finnhub-only tests | `pytest tests/test_finnhub_only_scope.py -q` | pass |
| Memory/attribution tests | `pytest tests/test_memory_isolation.py tests/test_system_attribution.py -q` | 34 passed |
| Remediation tests | `pytest tests/test_final_remediation.py -q` | 20 passed |

These are observations, not policy successes. The first two are the reason
RP-08 is not `ENFORCED` at `HEAD`.

### 3. Policy precedence and failure mode

1. A **refusal before a paid call** is the preferred failure: `RunRefused` keeps
   "the run never started" distinct from "the run failed" and preserves the
   evidence.
2. A **invalid run** is retained, never deleted or averaged in; it is not a
   sample.
3. A **documented-only** rule is not a control. In particular, operator
   authorization for a paid run is external to every gate; passing the gate does
   not mean a human approved the spend.

### 4. Evidence index

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
