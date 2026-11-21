# Option Ledger — Alternative Designs and Why We Chose What We Did

Each row records an alternative we considered, why we did not take it, and the
decision we took. The decision columns are stable IDs; the gate and evaluator
ADRs are the authoritative decision records.

## Data Quality Gate

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DQG-ALT-1 | LLM-based quality judge (prompt an LLM to score data quality) | Non-deterministic, requires an LLM call, not offline-testable, costly, hard to audit a verdict. | Deterministic, LLM-free gate (`FR-DQG-001`). |
| DQG-ALT-2 | Inline `SourceAttempt` nested inside `EvidenceRecord` | Breaks acyclic serialization; hard to round-trip JSON; violates INV-4. | Separate `SourceAttempt` record (7 fields), never embedded. |
| DQG-ALT-3 | Float math for normalized financial values | Float noise breaks deterministic comparisons and point-in-time reproducibility. | `Decimal` (quantized via `quantize_decimal`). |
| DQG-ALT-4 | Gate raises the whole run on any low quality | Too aggressive; blocks runs a human would tolerate (degraded). | Tiered verdicts `blocked > degraded > normal` (`FR-DQG-002`). |
| DQG-ALT-5 | Random `run_id` for evidence IDs | Breaks reproducibility; evidence differs per run. | `run_id` derived from `(trade_date, normalized symbol)` (`FR-DQG-003`). |
| DQG-ALT-6 | Gate writes frozen dataclasses into AgentState | Not checkpoint/JSON serializable; LangGraph state is dicts. | Write serialized `to_dict()` forms only (`FR-DQG-001`). |

## Dynamic debate termination

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DDT-ALT-1 | Always run a fixed `max_debate_rounds` (upstream default) | Wastes tokens/turns after convergence or no-new-evidence; no summary reserve guarantee. | Dynamic, evidence-aware evaluator (`FR-DDT-001`). |
| DDT-ALT-2 | LLM-judged "is the debate over?" | Non-deterministic, adds cost and an extra LLM call, not auditable deterministically. | Deterministic `evaluate_round` rule ordering (`FR-DDT-001`). |
| DDT-ALT-3 | Prose-only turn metadata parsed opportunistically | Unreliable; a missed stance could extend or shorten debate arbitrarily. | Structured `DEBATE_METADATA` marker with a best-effort prose fallback; a parse failure contributes zero new evidence and cannot extend the debate (`FR-DDT-002`). |
| DDT-ALT-4 | No summary reserve; rely on wall-clock only | A run could exhaust budget mid-debate and lose its report. | Explicit summary tokens/time reserve + hard max tokens/time/calls (`FR-DDT-003`). |
| DDT-ALT-5 | Break upstream by defaulting to dynamic always | Regresses legacy behavior and default `pytest -q`. | `debate_termination.enabled` default; `False` reproduces fixed-round routing (`FR-DDT-004`). |
| DDT-ALT-6 | Incomplete router path map relying on fall-through | A fall-through could hit a missing edge and crash LangGraph (#1088). | Complete `DEBATE_PATH_MAP` / `DEBATE_EVALUATOR_PATH_MAP` (`FR-DDT-001`). |

## Documentation / delivery

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DOC-ALT-1 | Duplicate the main-system source into `src/` to match the slide | Duplicates code, risk of drift, out of scope. | Main system stays in `tradingagents/` + `cli/`; the approved simulated-trading subsystem is the explicit `src/trading/` + `src/safety/` exception. |
| DOC-ALT-2 | Claim a green full suite | False; known date-sensitive and network-reachability failures remain. | Record exact observed outcomes and note failures (`evaluation-logbook.md`, `risk-list.md`). |
## 2026-11-13 update — independent simulated-trading subsystem

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DOC-ALT-3 | Keep all trading code only in `tradingagents/` or leave the subsystem as a separate unmerged branch | The approved subsystem has a different safety/clock/audit boundary and its tests need canonical collection | Approved independent subsystem: `src/trading/`, `src/safety/`, and `tests/trading/`. |
| DOC-ALT-4 | Duplicate the simulated-trading tests in both `test/` and `tests/` | Two test trees drift and the canonical suite cannot identify the authoritative copy | Use `tests/trading/` only. |

---

## Token-observability option decisions (OPT-01…OPT-10)

The decisions above are the Release option record. The personal token-observability delivery
recorded its own alternatives as `OPT-01…OPT-10`; they are distinct identifiers, not a
renumbering of the Release options, and are preserved here with their original rationale and
evidence.

**Purpose.** Record the design options that were considered for the CAND-01 /
batch-macro work, what was actually built and measured, and what was decided.
The ledger is deliberately asymmetric: an option that was never implemented is
not credited with an effect, and an option that was measured at n = 1 per cell is
not called "proven".

**Decision vocabulary**

| Decision | Meaning in this ledger |
| --- | --- |
| `ADOPTED` | Implemented and accepted for use, with the stated conditions. |
| `REJECTED` | Not accepted for this study. Code may remain available but is not recommended. |
| `DEFERRED` | Implemented or available, but not relied on; further validation is required. |
| `NOT_MEASURED` | No measurement exists; no effect is claimed. |

**Evidence rule.** A result is only listed if it comes from a tracked artefact or
the canonical evaluation record. Results that live only in the local, untracked
analysis directories are labelled **(local)**; they are evidence of what was
observed, not artefacts a reader can re-run from the submitted tree.

---

### 1. Options at a glance

| ID | Option | Expected goal | Implementation | Data / design | Result | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| OPT-01 | Batch macro tool | Collapse 7–9 single-series FRED calls per news run into one call (a mixed AB run can total up to 13 macro calls); fewer round trips and fewer macro tokens | `get_macro_indicators_batch` in `tradingagents/agents/utils/macro_data_tools.py`; `batch_macro_enabled`; news analyst binds the batch tool | V3 2x2, arms AB/CC; FRED; 15 valid runs | Calls fall to 1 per news run (vs 7–9 single-series; up to 13 total on mixed runs), but the token effect is not robust: mean batch effect −17,702; −695 when R01 is excluded; per block −51,716 / +1,612 / −3,002 | `DEFERRED` |
| OPT-02 | Single-pass finalisation (CAND-01) | Remove the prose-then-structured rewrite; save output tokens | `finalize_single_pass` in `tradingagents/agents/utils/structured.py`; `single_pass_finalization_enabled` AND `structured_analyst_output_enabled` | V3 arms C0/CC; 15 valid runs | Mean single-pass effect −19,589 tokens; per block −8,907 / −16,390 / −33,472; the output reduction is proportionally larger (about 25% vs 5.7% of its base); 5 market fallbacks all occur in single-pass arms | `ADOPTED` (conditional) |
| OPT-03 | Both switches on (CC) | Combine the two savings; cheapest arm | Both `batch_macro=true` and `single_pass=true` | V3 R03/R07/R14/R12 | Valid CC mean 181,443 tokens (lowest), but R12 failed twice and 2 of 3 valid CC runs had raw markup in `market_report` (1,922 / 346 chars) | `REJECTED` |
| OPT-04 | Second news vendor (GDELT) | Resilience to a Finnhub outage; wider news coverage | `gdelt_news.py` remains registered as an opt-in route; `get_news` defaults to `finnhub`; `get_global_news` returns `CONFIG_DISABLED` | V2/V3 Finnhub-only; 15/15 V3 runs non-empty; 0 GDELT calls | V1 had GDELT called twice per run; V2 removed it and added a tripwire. Single-vendor scope is a property of the measurement, not a claim that Finnhub is sufficient | `REJECTED` for this study |
| OPT-05 | RAGAS / 173-question quality evaluation | Score faithfulness / answer quality beyond token counts | None found in the tree: no question set, judge, harness, or fixtures | No run | `NOT_MEASURED`; no quality score, return, or ground truth exists | `NOT_MEASURED` |
| OPT-06 | Reranker over news / retrieved passages | Improve relevance and reduce context tokens | None found in the tree: no embedding index, retriever, or reranker dependency | No run | `NOT_MEASURED`; news is vendor-filtered and truncated by the frozen implementation | `NOT_MEASURED` |
| OPT-07 | Per-run memory isolation | Stop run order from changing a later run's prompt/cost; make V3 comparable | Immutable empty snapshot; per-run copy; pre/post hash checks; `memory_state.json` | V3, 18 attempts | 18/18 `baseline_unchanged=true`; 16/16 registrations carry the contract; V2 R05→R06 pollution removed for registered runs | `ADOPTED` |
| OPT-08 | System-component attribution | Attribute the pre-graph reflector instead of voiding the run; never hide a call | `AttributionContext`; `system_component_scoped("pre_graph_reflector")`; telemetry schema 2 | V3, 16 runs | 16/16 `attribution_complete=true`; no `unattributed` events; system tokens are a separate bucket | `ADOPTED` |
| OPT-09 | `tool_rounds` instrumentation | Count tool rounds correctly (V3 telemetry recorded 0) | `record_tool_round` per non-empty batch; `attrib_tool_round` wrapper; single-pass path counted separately from graph `ToolNode` | Offline tests; historical V3 not re-run | New tests cover 0, 1, 2 and failing rounds; historical V3 `tool_rounds=0` is not rewritten | `ADOPTED` |
| OPT-10 | Pre-RC1 Stage 1 / Stage 2 campaign (dedup; structured one-shot) | Remove duplicated report text; make structured output one-shot | Local campaign at commit `866133d` (ancestor of `rc1`); not implemented as a delivered protocol | 5-run NVDA measurements (local only) | Stage 1 mean 191,760 vs 237,706 (−19.3%); Stage 2 mean 180,462 (−5.9% vs Stage 1). The campaign's own audit says the run-level Stage 1 figure over-attributes to dedupe | `NOT_MEASURED` (for this submission) |

---

### 2. Why the main options were decided this way

#### OPT-01 — batch macro: fewer calls, not a token saving

The mechanism is real: the news analyst's macro tool calls drop from 7–9 single-series (up to 13 total on mixed runs)
single-series calls to one batch call, and the V3 quality review records that
directly **(local)**. The cost claim is not real enough to lean on:

* mean batch effect −17,702 tokens, but the three blocks disagree
  (NVDA −51,716; AAPL +1,612; XOM −3,002);
* excluding R01 (the environment-degraded C0 run) leaves −695, i.e. essentially
  zero;
* excluding R07/R14 leaves only NVDA, where the effect is −51,716 — the same
  single block that drives the mean.

The batch response is larger, and the extra bytes stay in history and are
re-sent. That is why the call-count win does not become a token win. The switch
is shipped and default-enabled, but the ledger records `DEFERRED` for the
*token-efficiency claim*: do not cite batch macro as a token optimisation on this
evidence.

Evidence: `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/CAND01_BATCH_2X2_PROTOCOL_V2.md`
§3; `tests/test_macro_batch.py`; V3 factorial tables **(local)**.

#### OPT-02 — single-pass: the saving is consistent, the format risk is not zero

Single-pass is the only option whose direction is negative in every estimable
sensitivity:

| Block | Single-pass effect (tokens) |
| --- | --- |
| NVDA | −8,907 |
| AAPL | −16,390 |
| XOM | −33,472 |
| mean | −19,589 |

The output component falls more than the input component (the duplicate prose
turn is removed), which is the intended mechanism. But the same path produced:

* five market-analyst fallbacks, all in single-pass arms;
* R07 (AAPL/CC) with a 1,922-character raw DSML markup `market_report`;
* R14 (XOM/CC) with a 346-character raw markup report;
* R12 (JPM/CC), which failed twice with a provider 400 before completing.

The pre-registered conclusion is therefore **ADOPTED, conditional**: accepted as
a real token reduction, not as a default-on setting, and only with the
exit sanitizer and fallback tests added in `e0ea1b0`/`e9eed04`/`51edd41`/
`eaeebab`. The default in `tradingagents/default_config.py` remains
`single_pass_finalization_enabled=False`.

Evidence: `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`;
`tests/test_final_remediation.py` (20 tests);
`token_benchmarks/final_remediation_20261116/DSML_MARKET_REPORT_FIX.md`;
V3 factorial tables **(local)**.

#### OPT-03 — CC both-on: cheapest mean, worst reliability

CC has the lowest valid mean (181,443) and the lowest output mean, but the
sample is n = 3, not n = 4: R12 never produced a decision. Of the three valid CC
runs, two had a markup `market_report` rather than a report. Calling that
"best" would optimise the one metric the study can compute while ignoring the
one it cannot (decision quality). `REJECTED` as a recommended configuration; the
CC arm remains a data point, not a product recommendation.

#### OPT-04 — second news vendor: rejected for a controlled token comparison

V1's configuration said "Finnhub-only" but routed `finnhub` to
`get_news_combined`, which called Finnhub **and** GDELT, and also called GDELT
again as the explicit second vendor. That is two providers in every arm, which
makes a per-token arm comparison depend on a second vendor's response size and
can mask a Finnhub outage. V2 made the scope honest:

* `get_news` → `get_news_finnhub_only`;
* `get_global_news` → `get_global_news_finnhub` returning
  `NEWS_STATUS=CONFIG_DISABLED` and performing no fetch;
* `tool_vendors["get_news"] = "finnhub"` and
  `tool_vendors["get_global_news"] = "finnhub"`;
* GDELT remains registered for a future study that explicitly selects it.

Evidence: V2 protocol §4; `tests/test_finnhub_only_scope.py` (9 tests, GDELT
tripwire); V3 protocol §12.

#### OPT-05 and OPT-06 — quality evaluation and reranking were not measured

No RAGAS configuration, 173-question set, judge model, answer key, embedding
index, retriever, or reranker exists in the submitted tree (verified by a
repository-wide search for `ragas`, `rerank`, and `173`). The V3 quality review
states plainly that there is no ground truth, no realised return, and no
forward-looking return, and that no arm can be called "more accurate" **(local)**.
Adding either option would require:

1. a new protocol and a new registration (they change prompts, calls, and token
   accounting);
2. an external judge or additional provider calls, which the frozen budget did
   not authorize;
3. a quality rubric with human or otherwise independent labels.

They are therefore `NOT_MEASURED`, not "rejected because they failed". No number
is reported for them.

#### OPT-07 — memory isolation: adopted because the alternative confounds the design

The R05→R06 case is the evidence: the second AAPL run's first provider call was
the pre-graph reflector, and the run was void. The V3 fix copies an immutable
empty snapshot into each attempt and checks the baseline hash before and after
(`scripts/token_benchmark.py::validate_memory_spec`,
`memory_state_after_run`). 18/18 V3 attempts report
`baseline_unchanged=true`; 16/16 registrations carry the contract.

Caveat: isolation applies to **registered V3 runs**. Generic measurement and
CLI runs still use the shared log (audit A, finding M3). See
`docs/architecture/memory-design.md` §5.

#### OPT-08 — system-component attribution: adopted, and never disguised as an agent

The pre-graph reflector is a legitimate non-agent provider call. The fix gives it
a declared system scope and a separate telemetry bucket; it does not relabel it
as an analyst and does not make an unattributed call valid. V3 reports 16/16
runs with complete attribution and zero `unattributed` events.

#### OPT-09 — tool_rounds: adopted, with the historical data left alone

The V3 telemetry recorded `tool_rounds=0` even when tools ran, because the
single-pass path bypassed the graph `ToolNode` counter. The fix counts one round
per non-empty tool batch and does not double-count the graph path. The historical
V3 numbers are **not** rewritten; only new runs carry true values. Tests cover
0/1/2 rounds and a failing tool.

#### OPT-10 — pre-RC1 Stage 1/2: real locally, but not deliverable evidence

The local campaign at `866133d` (an ancestor of `rc1`) measured 5 NVDA runs per
stage:

| Stage | Mean total tokens | Delta |
| --- | --- | --- |
| S0 baseline | 237,706 | — |
| S1 report dedup | 191,760 | −19.3% |
| S2 structured one-shot | 180,462 | −5.9% vs S1 |

The campaign's own audit says the run-level S1 delta over-attributes to dedupe
and that tool-data variance contributed. More importantly for this submission,
the measurement directories under the source workspace's `token_benchmarks/measurements/`
and the campaign reports are **untracked** and are absent from `50b2ca3`; they
cannot be re-run from the delivered tree. The row is therefore recorded as
`NOT_MEASURED` with verification **NOT_VERIFIED** for this submission. It is not
used as evidence for any V2/V3 conclusion.

---

### 3. What would change a decision

| Option | Evidence that would change it |
| --- | --- |
| Batch macro | A balanced multi-run experiment where the batch arm is not confounded by an environment-degraded cell and the payload is bounded; then a token effect with a confidence interval. |
| Single-pass | Replication across dates/stocks and a format-failure rate low enough to make default-on defensible; the sanitizer is necessary but does not by itself prove quality. |
| CC both-on | A CC run set with no provider failures and no markup reports, plus a quality measure; the current 3/3 valid CC set includes two degraded reports and one missing cell. |
| Second news vendor | A new protocol that makes the vendor count part of the treatment and measures outage resilience, not just token cost. |
| RAGAS / 173-question / reranker | A registered question set, an independent judge, and a protocol that budgets the extra calls; none exists today. |
| Memory isolation | A later study that deliberately varies memory content; V3's empty baseline cannot measure a memory effect. |

### 4. Verification notes

* V3 factorial numbers are balanced (NVDA/AAPL/XOM) descriptive estimates at
  n = 1 per cell; they are `EXPLORATORY`, not significance tests. The JPM block
  is incomplete (R12 invalid) and is not used in the means.
* V2 has only one complete block (NVDA) plus AAPL/C0; it is not used for a
  second factorial. The V2 NVDA cells are reported in
  `docs/architecture/evaluation-table.md` Part II.
* The only source-code performance changes accepted in this line are CAND-01
  (single-pass), the batch macro tool, and the observability/memory/attribution
  infrastructure. Nothing here changes the trading strategy or the model.
