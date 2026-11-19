# Technical Debt Register — TradingAgents CAND-01 / Token Observability

Baseline: `50b2ca3` (tag `cand01-v3-final-remediation`), 2026-11-16. Verified
on 2026-11-19 at that base commit: the debts below that touch code/tests were
re-checked by reading the implementation and by running the full suite
(4 failed, 2,227 passed, 2 skipped, 319 subtests); the two path-pinned V3 tests
and the two `cli_prefs` tests were reproduced. A later uncommitted test-isolation
patch (D7) is present in the worktree and changes the suite result to 2,233
passed / 0 failed; it does not remove the underlying debts, only makes the two
test groups checkout-independent.

Status vocabulary: `OPEN` (needs work), `ACCEPTED` (known limitation, consciously
carried), `MITIGATED` (contained by a guard but not removed). Every item is
owned by `PENDING_HUMAN_CONFIRMATION`: no human has accepted these debts yet.

---

## Summary

| ID | Debt | Status | Owner |
| --- | --- | --- | --- |
| DEBT-001 | `cli_prefs` tests are coupled to host state | MITIGATED (tests isolated in this branch; CLI host behaviour unchanged) | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-002 | V3 specs embed absolute host paths | PARTIALLY_MITIGATED (tests normalise host paths; frozen specs unchanged) | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-003 | Single-pass per-tool telemetry gap | OPEN | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-004 | Summary CSV omits the markup counter | OPEN | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-005 | No post-fix live rerun | ACCEPTED | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-006 | n = 1 per cell | ACCEPTED | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-007 | No ground truth for decision quality | ACCEPTED | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-008 | Provider endpoint not in the config hash | OPEN | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-009 | Generic `measure` path shares the host memory log | OPEN | `PENDING_HUMAN_CONFIRMATION` |
| DEBT-010 | Pre-existing ruff baseline (233 findings at `50b2ca3` under ruff 0.17.1) is not fixed; CI lints only submission files | ACCEPTED | `PENDING_HUMAN_CONFIRMATION` |

---

## DEBT-001 — `cli_prefs` tests are coupled to host state

- **Description:** two tests drive the real interactive selection flow but do
  not isolate the host's remembered CLI state or a parent-directory `.env`.
  `cli/prefs.py:26` hard-codes `~/.tradingagents/cli_prefs.json`, and
  `tradingagents/__init__.py:14` calls `load_dotenv(find_dotenv(usecwd=True))`,
  which walks up from the worktree and loads `/home/sky/cs5351/TradingAgents/.env`.
  In the reproduced failure that parent `.env` supplies the ambient
  `TRADINGAGENTS_*` selection values, so `get_user_selections()` skips the
  stubbed prompts and records the host values instead.
- **Impact:** `test_selections_are_remembered_after_a_run` and
  `test_a_remembered_endpoint_is_offered_back` fail on a developer host with
  real `.env`/prefs state. The suite is not hermetic; the failure is unrelated to
  product behaviour. It accounts for 2 of the 4 known failures.
- **Status:** `MITIGATED` in this submission branch: `tests/test_cli_prefs.py`
  now scrubs the ambient `TRADINGAGENTS_*` selection env (autouse, scoped) and the
  two tests pass with a real host `.env` present. The CLI itself still reads
  host state; that is expected product behaviour.
- **Evidence:** `tests/test_cli_prefs.py` (env-scrub fixture), `cli/prefs.py:26`, `tradingagents/__init__.py:10-15`,
  `cli/main.py:737` (`provider_from_env`), and the reproduced failure
  (`assert 'CS5351/DeepSeek-V4-Flash' == 'gpt-5.6-mini'`).
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** done in this branch (env scrub + prefs path patch). Remaining:
  decide whether the CLI should expose an explicit `TRADINGAGENTS_HOME` so host
  isolation is a product feature rather than a test fixture.

## DEBT-002 — V3 specs embed absolute host paths

- **Description:** each frozen V3 spec stores `experiment_root` and `results_dir`
  as absolute paths from the generating worktree, e.g.
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/specs/R01_NVDA_C0/spec.json:22`
  (`/home/sky/cs5351/TradingAgents/.worktrees/cand01_v3`) and `:36` (the
  attempt runtime directory). The generator reproduces the bytes, including the
  host path.
- **Impact:** in any other worktree the two V3 infrastructure tests fail with
  `SPEC DRIFT DETECTED`; this is 2 of the 4 known failures. The frozen artefacts
  are still verifiable in their original worktree, and `MANIFEST.sha256` is
  intact, so the experiment itself is not invalidated.
- **Status:** `ACCEPTED` (documented in
  `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` §1 and
  `REGRESSION_AUDIT.md` §5.1).
- **Evidence:** `specs/R01_NVDA_C0/spec.json:22,36`;
  `tests/test_cand01_batch_16run_v3_infra.py::test_the_generator_reproduces_the_delivered_artifacts`
  and `::test_the_cli_check_mode_passes`; reproduced failure in this worktree.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** for a future V4, store host-relative paths and a
  content-addressed `experiment_root`; for V3, mark the two tests as
  `skipif` outside the original worktree or run them there. Do **not** rewrite
  the frozen V3 specs — that would move `c3-v3-final-freeze`.

## DEBT-003 — Single-pass per-tool telemetry gap

- **Description:** the graph path records one `ToolExecutionEvent` per tool
  through the LangChain `on_tool_end` callback
  (`tradingagents/observability.py:1411`). Single-pass executes tools in-process
  in `run_data_tools` and records only one `ToolRoundEvent` per batch
  (`tradingagents/agents/utils/structured.py:672-700`); it never calls
  `record_tool_execution`. Consequently `tool_calls`, `tool_result_utf8_bytes`
  and per-tool success/error are absent or zero for C0/CC in telemetry, while
  `tool_rounds` is now correct.
- **Impact:** per-tool cost/bytes are not comparable between the two-call arms
  (B/AB) and the single-pass arms (C0/CC). The V3 campaign's per-arm tool counts
  come from the run ledger / state, not from per-tool telemetry, so any future
  per-tool analysis of single-pass runs is a lower bound.
- **Status:** `OPEN`.
- **Evidence:** `structured.py:672-700` (`record_tool_round` only);
  `observability.py:925` (`record_tool_execution`) and `:1411` (callback call
  site); `tests/test_final_remediation.py::TestToolRounds` covers rounds, not
  per-tool events; `final_remediation_20261116/INDEPENDENT_AUDIT.md` Audit B
  records "single-pass 无 per-tool 事件" as a known gap.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** emit `record_tool_execution` (or an equivalent in-process
  event) per `_execute_calls` result, keeping `duplicate_count` semantics; add a
  test that one model turn with two tools produces 1 round + 2 tool events.
  Requires owner approval because it changes telemetry semantics for new runs.

## DEBT-004 — Summary CSV omits the markup counter

- **Description:** `structured_markup_sanitized` is published per agent and in
  `run_totals` in the JSON telemetry, but `write_summary_csv` in
  `scripts/token_benchmark.py:1471-1489` does not include it in `fieldnames`.
  The Markdown summary and JSON carry it; the CSV does not.
- **Impact:** a reader who only consumes `summary.csv` cannot see that a
  fallback report was sanitised, although the run still records the structured
  failure correctly (`structured_attempts == success + failure + unsupported`).
  Low severity for the V3 campaign (the 15 valid runs predate this counter, so
  no V3 CSV is affected), but it is a schema asymmetry.
- **Status:** `OPEN` (low).
- **Evidence:** `scripts/token_benchmark.py:1471-1489` (CSV columns) versus
  `tradingagents/observability.py` (`structured_markup_sanitized` in per-agent
  and `run_totals`); `final_remediation_20261116/REGRESSION_AUDIT.md` §5.3
  records "summary CSV 的列未新增".
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** add the column in a backward-compatible CSV revision
  (new column at the end, existing readers unaffected) and update the summary
  schema test. No re-freeze of V3 is required for new runs.

## DEBT-005 — No post-fix live rerun

- **Description:** the R12 fallback, DSML sanitation and `tool_rounds` fixes
  (`e0ea1b0`..`50b2ca3`) were validated only offline: scripted chat models,
  historical markup fixtures, the pre-fix probe and mutation tests. No paid
  pipeline run was executed after the fixes; R12's 400 and R07/R14's DSML
  reports remain the last live observations.
- **Impact:** the fixes are proven to prevent the known failure modes on
  fixtures, not proven to produce clean reports on live provider traffic. The
  V3 experimental results (3,067,669 tokens, −19,589) are pre-fix and are not
  re-measured under the remediated code.
- **Status:** `ACCEPTED` (explicitly out of scope: "本轮不再重跑真实实验").
- **Evidence:** `token_benchmarks/final_remediation_20261116/FINAL_REMEDIATION_REPORT_CN.md`
  §8.4; `.../TEST_RESULTS.md` §6 ("付费调用 0 / 外部 API 0"); `BRANCH_HISTORY_REPORT.txt` (LOCAL_ARCHIVE, not shipped)
  §8.2/§10 item 5.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** if budget and authorization allow, run one small paid
  rehearsal on the remediated code (e.g. R12/JPM/CC and R07/AAPL/CC) and compare
  report cleanliness and token totals; otherwise keep the NOT_VERIFIED label.

## DEBT-006 — n = 1 per cell

- **Description:** the V3 2×2 design has one valid observation per cell in the
  three complete blocks (NVDA, AAPL, XOM); JPM/CC is missing (R12 invalid). There
  are no repeats, no confidence intervals and no significance tests.
- **Impact:** the single-pass effect (−19,589 tokens/run, −8.96%) is a
  directionally consistent observation across three blocks but cannot support a
  population claim. The batch-macro mean (−17,702) is not robust: excluding R01
  it is about −695, and AAPL is +1,612.
- **Status:** `ACCEPTED`.
- **Evidence:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/FINAL_ENGINEERING_REPORT_CN.md`;
  `.worktrees/v3_runs_20261116/FINAL_EXPERIMENT_REPORT_V3.md` (LOCAL_ARCHIVE, not shipped) §3 ("每格 n=1");
  `BRANCH_HISTORY_REPORT.txt` (LOCAL_ARCHIVE, not shipped) §4.4/§8.3.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** n ≥ 3 per cell, at least two dates and a second model, before
  any confirmatory claim; pre-register the analysis.

## DEBT-007 — No ground truth for decision quality

- **Description:** the study measures token cost and structural integrity
  (usage closure, attribution, memory isolation, freeze integrity). It has no
  forward returns, no independent analyst scoring and no P&L. "Real investment
  returns" is `NOT_MEASURED`.
- **Impact:** no statement about which arm makes better decisions is supported;
  the DSML-degraded R07/R14 reports show that cheaper output can be worse
  quality, but quality itself is not scored.
- **Status:** `ACCEPTED`.
- **Evidence:** `.worktrees/v3_runs_20261116/FINAL_EXPERIMENT_REPORT_V3.md` §7;
  `BRANCH_HISTORY_REPORT.txt` (LOCAL_ARCHIVE, not shipped) §4.7/§8.3.
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** add a forward-return or independent-rubric endpoint in a
  future study; do not retrofit a quality claim onto V3.

## DEBT-008 — Provider endpoint not in the config hash

- **Description:** `HASHED_FIELDS` in `scripts/c3_preflight_gate.py:292-300`
  covers experiment id, schema, switches, provider, models, language, cache,
  checkpoint, budget, cases, switches and news scope, but not the resolved
  endpoint (`backend_url`). Two runs at different endpoints with the same model
  name hash identically.
- **Impact:** the gate cannot detect a rerouted provider endpoint; the frozen
  `config_sha256` does not fully describe what was called. Recorded as L3 in V3
  Audit B.
- **Status:** `OPEN` (low; not exercised by the delivered runs, which used the
  same CityU endpoint).
- **Evidence:** `scripts/c3_preflight_gate.py:292-300`;
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_B.md`
  (residual L3 "endpoint not hashed").
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** add `backend_url`/endpoint to `HASHED_FIELDS` and the three
  mirrored definitions in a future protocol version; this changes all 16
  `config_sha256` values and therefore requires a new freeze.

## DEBT-009 — Generic `measure` path shares the host memory log

- **Description:** the 16 registered runs get a per-run copy of the immutable
  snapshot (V3). The generic `measure` command (`scripts/token_benchmark.py
  _cmd_measure`) builds an unregistered experiment and leaves
  `memory_log_path` at the default `~/.tradingagents/memory/trading_memory.md`
  (`tradingagents/default_config.py:80`), so one-shot measurements share mutable
  memory across invocations.
- **Impact:** `measure` results are not memory-isolated and are not comparable
  to the registered A/B/C runs; a pending entry from one measurement can change
  the next measurement's pre-graph reflector prompt.
- **Status:** `OPEN` (low; outside the 16 registered runs).
- **Evidence:** `tradingagents/default_config.py:80`;
  `scripts/token_benchmark.py:4919` (`_cmd_measure`) and `:4173` / `:4333`
  (isolation only on the registered/rehearsal paths);
  `INDEPENDENT_AUDIT_A.md` M3 ("generic (non-registered) specs still use the
  shared log").
- **Owner:** `PENDING_HUMAN_CONFIRMATION`.
- **Next action:** either copy a declared snapshot for `measure` too, or state
  in the `measure` help/notes that it is explicitly non-isolated. Do not change
  the registered path without a re-freeze.

---

## DEBT-010 — Pre-existing ruff baseline (whole-repo lint is not green)

**Status:** ACCEPTED (documented, not hidden).
**Evidence:** at `50b2ca3` under `ruff 0.17.1`, `ruff check .` reports **233 findings**
(40 in `tradingagents/`, `cli/`, `scripts/`, `main.py`; 88 in `tests/`; 105 in
`token_benchmarks/` evidence scripts). The old CI comment claimed the repo was
"fully clean"; that is not true under current ruff releases.
**Why not fixed here:** fixing it requires product-code and test edits that this
course-deliverable round forbids. CI therefore lints only the Python files the
submission adds/changes (all clean) and this debt stays open.
**Next action:** a separate, authorised cleanup round (pin ruff, fix findings,
or record a reviewed baseline), then restore a whole-repo blocking lint job.

## Explicitly not counted as debt

- The 4 failing tests are classified above (DEBT-001, DEBT-002); they are not
  product regressions.
- The V3 historical `tool_rounds=0` is not rewritten; new runs carry real
  values (see BUG-011). It is a data-history limitation, not a current defect.
- The 2 skipped tests are environment skips (`langchain_aws` absent; live
  DeepSeek key absent), not debt.
