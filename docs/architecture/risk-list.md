# Risk list

**Purpose.** Risks that affect the validity, reproducibility, or safety of the
CAND-01 evaluation. Each risk states likelihood, impact, current status, and the
evidence a reader can inspect. A risk marked `MITIGATED` means a fix exists and
is tested; it does **not** mean the risk is gone. A risk marked `OPEN` is a known
residual, not necessarily a blocker.

**Status vocabulary:** `OPEN`, `MITIGATED`, `PARTIALLY_MITIGATED`, `NOT_MEASURED`.
**Likelihood / impact:** Low, Medium, High, Certain.

**Base.** `50b2ca3` plus the 2026-11-19 submission-packaging files. Raw paid
telemetry is untracked; evidence paths marked **(local)** are outside the
delivered tree.

---

## Summary

| ID | Risk | Likelihood | Impact | Status |
| --- | --- | --- | --- | --- |
| RISK-001 | Provider rejects a message sequence (R12 400) | Medium | High | `MITIGATED` (offline), residual |
| RISK-002 | Tool-call protocol markup (DSML) leaks into a report | High | High | `PARTIALLY_MITIGATED` |
| RISK-003 | Data availability / read-only cache degrades a cell | High | Medium | `OPEN` |
| RISK-004 | PIT is only day-granular | Medium | Medium | `OPEN` (documented) |
| RISK-005 | Shared memory pollutes a later run | High | High | `MITIGATED` registered / `OPEN` generic |
| RISK-006 | Provider usage is missing or contradictory | Medium | High | `MITIGATED` |
| RISK-007 | API key leakage or over-broad access | Low | High | `PARTIALLY_MITIGATED` |
| RISK-008 | LLM/run nondeterminism drives the result | High | Medium | `OPEN` (design limit) |
| RISK-009 | n = 1 per cell is too small for inference | Certain | Medium | `OPEN` (design limit) |
| RISK-010 | Freeze/spec paths do not reproduce in another checkout | High | Medium | `OPEN` |
| RISK-011 | Decision quality is unvalidated | Certain | High | `NOT_MEASURED` |
| RISK-012 | Endpoint/model version is not in `config_sha256` | Medium | High | `OPEN` (documented) |
| RISK-013 | Generic/CLI runs bypass the harness gates | Medium | Medium | `OPEN` |
| RISK-014 | CI / clean-checkout tests were red at `50b2ca3` | High | Medium | `MITIGATED (submission branch); OPEN at 50b2ca3` |

---

## RISK-001 — Provider compatibility: the R12 message sequence is rejected with HTTP 400

**Description.** In V3, R12 (JPM/CC) failed twice with a provider
`invalid_request_error`: an assistant message carried `tool_calls` and was
followed by insufficient `tool_messages`. The trigger was a schema-invalid
`stance="Mildly Bearish"`; the fallback then replayed the dangling assistant turn
and dropped the system prompt.

**Likelihood / impact.** Medium / High. A run that fails this way produces no
decision and loses the paid spend.

**Status.** `MITIGATED` in code (`e0ea1b0` and follow-ups), residual `OPEN`.
The fix removes the dangling turn, keeps the system prompt, and uses
`prompt | llm` for the retry. It is covered by the offline regression file
(`tests/test_final_remediation.py`, 20 tests) and a pre-fix probe (4/4 detected);
it has **not** been re-run against the paid provider.

**Evidence.** `token_benchmarks/final_remediation_20261116/R12_FALLBACK_FIX.md`;
`tests/test_final_remediation.py`; `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`;
local `R12_PROVIDER_ERROR_DIAGNOSIS.md` and the two R12 `runner_report.json`
files **(local)**.

---

## RISK-002 — Tool-call protocol / DSML markup reaches a report

**Description.** In single-pass fallback, the model sometimes writes tool calls
as text (`<||DSML||>` markup). R07 (AAPL/CC) and R14 (XOM/CC) stored 1,922 and
346 characters of raw markup as `market_report`; downstream agents received it
instead of a report. This is a format failure, not a token-accounting failure.

**Likelihood / impact.** High / High. It can silently degrade a valid sample and
is easy to miss in an aggregate token table.

**Status.** `PARTIALLY_MITIGATED`. `sanitize_analyst_text` now runs at every
report exit; it preserves prose before markup, recovers schema fields, and falls
back to an explicit `REPORT UNAVAILABLE` (non-empty, non-markup). Tests cover the
R07/R14 fixtures and the prose/structured/finalizer exits. Residual: the
underlying model behaviour is not prevented, only sanitized; a new output shape
could still evade the patterns.

**Evidence.** `token_benchmarks/final_remediation_20261116/DSML_MARKET_REPORT_FIX.md`;
`tests/test_final_remediation.py`; `tradingagents/agents/utils/structured.py`
(`sanitize_analyst_text`, `finalize_single_pass`); local `QUALITY_COMPARISON.md`
**(local)**.

---

## RISK-003 — Data availability and read-only-cache failures degrade a cell

**Description.** R01 (NVDA/C0) ran with a read-only cache: 14
`NO_DATA_AVAILABLE` from `get_indicators` and 2 `OSError` from
`get_verified_market_snapshot`; the report fell back to a 10-day simple proxy.
V2 R05 attempt 01 failed with `OSError EROFS` while writing the decision log.
These are environment failures, but they change the measured input.

**Likelihood / impact.** High / Medium. The V3 NVDA C0 cell is a valid sample by
the U-1 rules yet is not a clean C0 observation; excluding it changes the batch
effect from −51,716 to −695.

**Status.** `OPEN` (documented limitation). No retry of R01 was made; the
sensitivity analysis reports the result with and without it. The cache-write
path is not hardened by this study.

**Evidence.** Local `QUALITY_COMPARISON.md` and `FACTORIAL_ANALYSIS.md`
**(local)**; V2 `EXPERIMENT_LIMITATIONS.md` **(local)**;
`tests/test_no_data_handling.py`; `tests/test_yfinance_stale_ohlcv_guard.py`.

---

## RISK-004 — PIT is day-granular, not intraday

**Description.** The trade date is the cutoff; an article published at 23:59 on
the trade date is treated as available for that day's analysis. The design
cannot distinguish "before the decision" from "after the close" within the day.

**Likelihood / impact.** Medium / Medium. It can admit same-day information that
an intraday strategy would not have had.

**Status.** `OPEN` (documented design limit, V3 protocol §12). It is enforced
consistently (all arms use the same convention), so it does not bias the arm
comparison; it does limit external validity.

**Evidence.** `tradingagents/dataflows/date_window.py` (`as_of`,
`as_of_window`); `tradingagents/dataflows/finnhub_news.py` (cutoff filter);
`tests/test_tool_date_enforcement.py`; `tests/test_news_lookahead.py`;
`tests/test_fundamentals_lookahead.py`; V3 protocol §12.

---

## RISK-005 — Shared memory pollutes a later run

**Description.** A run appends a pending decision; the next same-ticker run
resolves it with a provider call before the graph, changing the prompt and the
token cost. V2's R05 write caused R06's pre-graph reflector and R06 was invalid.
The same defect would have hit R10 and R14.

**Likelihood / impact.** High / High. It silently couples run order to the
measurement and can void a sample.

**Status.** `MITIGATED` for registered V3 runs: immutable empty baseline,
per-run copy, pre/post hash checks, `memory_state.json`; 18/18 V3 attempts
report `baseline_unchanged=true`. `OPEN` for generic `measure`, CLI, and direct
graph runs, which still use the shared log (audit A, M3).

**Evidence.** `docs/architecture/memory-design.md`;
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/MEMORY_ISOLATION_AUDIT.md`,
`MEMORY_SNAPSHOT_PROVENANCE.md`; `tests/test_memory_isolation.py` (21 tests);
`scripts/token_benchmark.py::validate_memory_spec`; local `R06_DIAGNOSIS.md`
**(local)**.

---

## RISK-006 — Missing or contradictory provider usage

**Description.** A provider may omit usage, omit a token field, or report a total
that disagrees with the per-call events. If a missing value were treated as zero,
the token comparison would be silently wrong.

**Likelihood / impact.** Medium / High. The study's primary metric is tokens.

**Status.** `MITIGATED` on the harness path. `usage_verdict` has four states and
only `VALID` produces a sample; missing is `null`, never `0`; an unattributed
event invalidates the run even if the aggregate flag was tampered with. Residual:
a direct graph/CLI run does not call the verdict.

**Evidence.** `scripts/token_benchmark.py::usage_verdict`,
`extract_run_metrics`; `tradingagents/observability.py`;
`tests/test_c3_final_freeze.py::TestUsageVerdict`;
`tests/test_token_benchmark.py`; `tests/test_observability.py`.

---

## RISK-007 — API key leakage or over-broad access

**Description.** A key can leak through a committed `.env`, a log, a prompt, or
an over-broad local file mode. A key that is present is also usable by any
process with environment access.

**Likelihood / impact.** Low / High. A leaked course key is a real incident even
if no paid run occurs.

**Status.** `PARTIALLY_MITIGATED`. `.env` is git-ignored and untracked; the
credential audit records no key in the branch diff; the CLI writes saved keys
`0600`; tests block live news. Residual: no secret scanner, no least-privilege
key, no egress allowlist; the audited local `.env` was mode `644`; arbitrary
shell reads cannot be blocked by `.opencode/permissions.jsonc`.

**Evidence.** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/env_credential_audit.txt`;
`.gitignore`; `tradingagents/llm_clients/api_key_env.py`; `cli/utils.py`;
`tests/test_api_key_env.py`; `tests/conftest.py`.

---

## RISK-008 — Nondeterminism and one-run outliers

**Description.** Provider sampling, tool return order, and context length vary
between runs. V2's AB cell (339,738) was driven by one long news loop; V3's NVDA
C0 was environment-degraded. A single run can change an effect's sign or size.

**Likelihood / impact.** High / Medium. It makes n = 1 cell estimates fragile.

**Status.** `OPEN` (design limit). The mitigation is disclosure: per-block
values, sensitivity analysis, and no significance claim. A seed is fixed in the
protocol, but it does not control provider sampling.

**Evidence.** V2 `EXPERIMENT_LIMITATIONS.md` **(local)**; V3
`FACTORIAL_ANALYSIS.md`, `DETERMINISTIC_VS_STOCHASTIC` **(local)**; V3 protocol
§12.

---

## RISK-009 — Small samples (n = 1 per cell)

**Description.** The V3 2x2 has one run per cell, one date, four stocks, one
model. JPM/CC is missing. Any "main effect" is a descriptive difference, not an
estimate of a population effect.

**Likelihood / impact.** Certain / Medium. The study is `EXPLORATORY` by design.

**Status.** `OPEN` (design limit). The analysis reports per-block values,
balanced three-block means, and sensitivity; it performs no significance test
and makes no generalisation.

**Evidence.** V3 protocol §12; `docs/architecture/evaluation-table.md` Part I;
local `FACTORIAL_ANALYSIS.md` **(local)**.

---

## RISK-010 — Freeze/spec paths do not reproduce in another checkout

**Description.** V3 specs embed absolute `experiment_root` and `results_dir`
paths from the build worktree. A different checkout regenerates different paths,
so generator `--check` reports drift and the V3 infra tests fail. The freeze
record also names `e3b5cca`, while the current `HEAD` is `50b2ca3`.

**Likelihood / impact.** High / Medium. It makes the "certified tree" claim
checkout-dependent and turns CI red on a clean export.

**Status.** `OPEN`. The freeze verifier fails closed (good), but it cannot
certify `HEAD`; the tracked tree does not contain the V2/V3 `FREEZE_RECORD.json`.
The specs are frozen artifacts and must not be hand-edited to fix the paths; a
new registration would be required.

**Evidence.** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/specs/R01_NVDA_C0/spec.json`
(`experiment_root`, `results_dir`); `scripts/c3_verify_final_freeze.py`;
`tests/test_cand01_batch_16run_v3_infra.py::test_the_generator_reproduces_the_delivered_artifacts`,
`test_the_cli_check_mode_passes`; observed `SPEC DRIFT` and
`c3_verify_final_freeze.py` failure on 2026-11-19.

---

## RISK-011 — Decision quality is unvalidated

**Description.** The study measures tokens and structural completeness, not
whether a decision is correct, well-calibrated, or profitable. There is no
ground truth, no realised return, no forward-looking return, and no human
rating.

**Likelihood / impact.** Certain / High. A cheaper arm can look "better" while
producing worse decisions.

**Status.** `NOT_MEASURED`. The quality comparison explicitly refuses to rank
arms. Any statement that one arm is "more accurate" or "safer" is unsupported.

**Evidence.** Local `QUALITY_COMPARISON.md` **(local)**; V3 protocol §12/§13;
`docs/architecture/evaluation-table.md` §1.5.

---

## RISK-012 — Endpoint and model version are not in `config_sha256`

**Description.** The provider endpoint is ambient
(`TRADINGAGENTS_LLM_BACKEND_URL`, set by `apply_cityu_env`), and the model is
addressed by name (`CS5351/DeepSeek-V4-Flash`). Neither the endpoint nor a model
snapshot digest is in `HASHED_FIELDS`, so changing the endpoint or the provider's
underlying model does not change the registration hash.

**Likelihood / impact.** Medium / High. A "same" registered run can be served by
a different model version, changing cost and answers.

**Status.** `OPEN` (documented V3 limitation). The runbook pins the endpoint; the
hash cannot. Any future comparison must record the endpoint and date separately.

**Evidence.** V3 protocol §8 (`HASHED_FIELDS`) and §12; local V3 run report
**(local)**; audit B residual L3 in
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_B.md`.

---

## RISK-013 — Generic/CLI runs bypass the harness gates

**Description.** Budget, usage, memory, news-scope, switch, and freeze checks run
in `scripts/token_benchmark.py` for a registered spec. A direct
`TradingAgentsGraph.propagate()` or CLI run does not require a registration and
does not execute the same gates.

**Likelihood / impact.** Medium / Medium. A "looks similar" run can be treated as
experiment evidence when it is not.

**Status.** `OPEN`. The separation is intentional (the product must remain
usable), but documentation must not generalize V3 guarantees to every product
path. Audit A recorded the generic memory path as a known residual.

**Evidence.** `scripts/token_benchmark.py::_requires_memory_isolation`,
`_preflight_gate`; `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_A.md`
(M3); `docs/architecture/memory-design.md` §5.

---

## RISK-014 — CI / clean-checkout suite was red at `50b2ca3` (mitigated in this branch)

**Description.** A clean export of `50b2ca3` fails at least the two V3
absolute-path infra tests; in this environment a full clean export also failed
dry-run/`.env`-coupled tests. The committed remediation record itself lists 4
known failures (2 V3 path + 2 `cli_prefs`) in the remediation worktree.
**Mitigation in this submission branch:** `tests/test_cand01_batch_16run_v3_infra.py`
normalises only the documented host-path fields (all identity/config/hash
assertions and the MANIFEST byte check stay strict), and `tests/conftest.py`
supplies a placeholder backend URL when the host has no `.env`. Verified with a
`.env`-free working directory: `2233 passed, 2 skipped, 319 subtests, 0 failed`.
The published commit `50b2ca3` itself is unchanged and still carries the old
behaviour; the fix lives in the course-deliverable branch.

**Likelihood / impact.** High / Medium. A red suite weakens the "verified" claim
and makes a future regression harder to see.

**Status.** `OPEN`. The failures are classified (environment/path coupling, not
product logic), but classification is not a fix. The frozen specs must not be
edited to make the tests pass; a new registration or a path-relative spec design
would be required.

**Evidence.** `.github/workflows/ci.yml`;
`token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`;
`tests/test_cand01_batch_16run_v3_infra.py`; observed clean-export failures on
2026-11-19; `CS5351_SUBMISSION_COMPLIANCE_AUDIT/` (local workspace) **(local)**.

---

## Residual-risk statement

The strongest claims this study can support are measurement-mechanics claims:
the token totals close, usage and attribution are complete on the valid runs,
the memory baseline did not change, and the frozen artifacts are hash-pinned.
The weakest claims are causal and external: a single run per cell on one date
cannot establish an arm effect, and no quality ground truth exists. Risks
RISK-008 through RISK-012 are the reason the evaluation table uses
`EXPLORATORY` and refuses to rank arms by decision quality.
