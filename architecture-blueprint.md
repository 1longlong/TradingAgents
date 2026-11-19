# Architecture Blueprint — CS5351 TradingAgents Fork

**Status:** course-deliverable master constraint document (descriptive, not a specification change).
**Branch:** `fix/cs5351-final-submission` at `50b2ca3` (tag `cand01-v3-final-remediation`).
**Upstream base:** TradingAgents `v0.5.0` (upstream `release` at `2d17df8`).
**Evidence freeze chain:** `rc1 9948bf8` → `V2 15270b1` (tag `c3-final-freeze`) → `V3 e3b5cca` (tag `c3-v3-final-freeze`) → final `50b2ca3` (tag `cand01-v3-final-remediation`); 68 commits from rc1 to final, 0 merges.
**Measured runtime:** CityU Foundry `CS5351/DeepSeek-V4-Flash` (quick and deep) through the OpenAI-compatible endpoint `https://llm.cs.cityu.edu.hk/v1`; Finnhub-only company news, GDELT excluded; FRED macro; one trade date `2026-09-23`; point-in-time (PIT) enforcement.

This blueprint is a constraint document for the course submission. It states what the
code does, where that behaviour lives, and which claims are evidenced. It does not
describe an intended future architecture, and it does not override code: where this
document and the checked-out code disagree, the code is authoritative and the
document is defective.

---

## 1. Purpose and scope

### 1.1 Purpose

The fork adds two things to an otherwise unchanged v0.5.0 product:

1. **Token observability and attribution.** Every logical LLM call and tool execution
   is recorded with its agent (or declared system component), provider-reported usage,
   prompt/tool-result sizes, and a per-run frozen artifact. The instrumentation is
   observational: it changes no prompts, model settings, tools, routing, or outputs.
2. **CAND-01.** A single-pass analyst finalisation feature and a batch-macro tool,
   both behind ablation switches, plus the 2×2 experiment apparatus that measured
   them on the frozen V2/V3 batches.

The blueprint fixes the vocabulary and the evidence boundaries used by the ADRs and
by `docs/architecture/invariants.md` and `docs/architecture/trace-matrix.md`. The
retrospective requirement baseline is `docs/req/requirements.yaml`; this blueprint
does not introduce requirement IDs of its own.

### 1.2 In scope

- The multi-agent graph as built by `tradingagents/graph/setup.py` and run by
  `tradingagents/graph/trading_graph.py`.
- The data, news, macro, memory, structured-output, and observability paths exercised
  by a measured run.
- The experiment/freeze apparatus under `scripts/` and
  `token_benchmarks/live_pilot_2x2/`.
- Testing and deployment constraints that the delivered tree actually satisfies.

### 1.3 Out of scope / explicitly not claimed

- **Investment performance.** No ground truth is measured for returns, risk-adjusted
  performance, or decision quality. The experiment measures token cost and run
  validity, not alpha.
- **Causal or statistically significant optimisation effects.** The 2×2 has
  `n = 1` per cell, one trade date, four tickers, one model. Numbers are descriptive.
- **Universal enforcement.** PIT, attribution completeness, and memory isolation are
  enforced on the paths the tests cover; there is no claim that an arbitrary new
  vendor or a future code path inherits them automatically.
- **Upstream authorship.** Sections 2 and 5 separate inherited v0.5.0 behaviour from
  branch work. The branch does not claim the upstream agent topology or PIT corpus.

---

## 2. Upstream versus our contribution

### 2.1 Inherited from TradingAgents v0.5.0

- The LangGraph multi-agent topology: four analysts → bull/bear researchers →
  research manager → trader → three risk analysts → portfolio manager.
- The agent prompt scaffold and the five-tier rating language, the debate/risk
  round controllers, the CLI, checkpoint/resume, backtest, portfolio context, and
  the vendor router. The prompts were not frozen at v0.5.0: rc1 (`9948bf8`)
  extended the analyst prompts (e.g. `market_analyst.py` gains MFI and the
  invalidation/scenario text), and those extensions are branch work.
- The v0.5.0 PIT corpus: `dataflows/date_window.py`, injected `trade_date`, the
  PIT memory filter (`get_past_context(..., as_of=...)`), live-profile withholding,
  and the dated-vendor conventions. The branch extends and exercises these; it did
  not invent the v0.5.0 PIT release.
- The v0.5.0 downstream structured agents (Research Manager, Trader, Portfolio
  Manager), which already used `with_structured_output` plus a free-text fallback.
- The upstream test suite and packaging metadata (`pyproject.toml`, `Dockerfile`).

### 2.2 Added or materially changed on this branch

| Area | What the branch adds | Primary code |
| --- | --- | --- |
| Token observability | Per-run collector, stable agent IDs, ContextVar attribution (agent/system/none), callback handler, telemetry schema 2, atomic per-run artifact, usage coverage and self-audit | `tradingagents/observability.py` |
| Observability wiring | Node wrappers (`attrib_agent_node`), ToolNode round wrapper (`attrib_tool_round`), pre-graph reflector scope (`system_component_scoped`) | `tradingagents/graph/setup.py`, `tradingagents/graph/reflection.py`, `tradingagents/graph/trading_graph.py` |
| Single-pass finalisation | Schema bound as an extra tool on the terminal analyst call; switch off by default; all fallbacks land on the RC1 two-call path | `tradingagents/agents/utils/structured.py`, the market/news/fundamentals analysts |
| Batch macro | `get_macro_indicators_batch` with per-series independence and total-input coercion; switch removes it from both the analyst and the news `ToolNode` | `tradingagents/agents/utils/macro_data_tools.py`, `tradingagents/agents/analysts/news_analyst.py`, `tradingagents/graph/trading_graph.py` |
| Finnhub-only news scope | Company news routed to `get_news_finnhub_only`; global news explicitly `CONFIG_DISABLED` under the Finnhub route; retired Yahoo/Alpha Vantage news paths removed | `tradingagents/dataflows/interface.py`, `tradingagents/dataflows/finnhub_news.py`, `tradingagents/default_config.py` |
| Experiment harness | Pre-registered 16-run 2×2 specs, `config_sha256`, memory snapshot hashing, budget contract, preflight gate, freeze records, verifiers | `scripts/token_benchmark.py`, `scripts/gen_cand01_batch_16run_specs_v{2,3}.py`, `scripts/c3_*.py` |
| Fallback safety | R12 dangling-`tool_call` + lost-system-prompt fix; DSML/protocol-markup sanitiser at report exits; truthful single-pass tool-round telemetry | `tradingagents/agents/utils/structured.py`, `tradingagents/observability.py` |

**Not changed:** the agent graph topology, the debate/risk round semantics, the
five-tier rating scale, the data-vendor contracts for prices/fundamentals, and the
memory log's product semantics (append-only decision log). The observability module
explicitly declares itself observational-only and changes no business semantics
(`tradingagents/observability.py:1-40`).

### 2.3 What "final" means

`50b2ca3` is the remediation of the frozen V3 tree. The V3 experiment ran on
`e3b5cca`; the fixes in `e0ea1b0`/`e9eed04` and the follow-up remediation commits
changed fallback and telemetry behaviour but did **not** re-run the paid batch.
Therefore V3 measurements describe `e3b5cca`, while the delivered tree is `50b2ca3`.
That distinction is load-bearing and is repeated wherever the numbers are quoted.

---

## 3. Multi-agent graph

### 3.1 Node order and edges

The graph is built as a `StateGraph(AgentState)`
(`tradingagents/graph/setup.py:127-203`) and compiled without a checkpointer by
default (`tradingagents/graph/trading_graph.py:184-188`). The shipped analyst
selection is `("market", "social", "news", "fundamentals")`.

```
START
  → Market Analyst ⇄ tools_market → Msg Clear Market
  → Sentiment Analyst → Msg Clear Sentiment        (no tools bound; data prefetched)
  → News Analyst ⇄ tools_news → Msg Clear News
  → Fundamentals Analyst ⇄ tools_fundamentals → Msg Clear Fundamentals
  → Bull Researcher ⇄ Bear Researcher            (debate rounds)
  → Research Manager
  → Trader
  → Aggressive Analyst ⇄ Conservative Analyst ⇄ Neutral Analyst   (risk rounds)
  → Portfolio Manager
  → END
```

- Each analyst node routes through its own conditional edge: if the last message has
  `tool_calls`, go to that analyst's `ToolNode`; otherwise go to its message-clear
  node (`tradingagents/graph/conditional_logic.py:12-48`). The sentiment node binds no
  tools and prefetches its sources into the prompt, so in practice it always takes the
  clear edge; the `tools_social` node remains registered but is not reached from that
  node. The clear node then hands off to the next analyst, or to the Bull Researcher
  after the last one (`setup.py:160-182`).
- Debate and risk routers use complete path maps (`DEBATE_PATH_MAP`,
  `RISK_ANALYSIS_PATH_MAP`) so a fall-through speaker label can never produce a
  missing LangGraph edge (`setup.py:38-48`, `184-199`).
- Round counts are configuration: `max_debate_rounds` and
  `max_risk_discuss_rounds` (default 1 each). The debate stops at
  `2 × max_debate_rounds` entries; the risk discussion stops at
  `3 × max_risk_discuss_rounds` (`conditional_logic.py:50-73`).
- The analyst execution plan supports subsets and preserves execution order
  (`tradingagents/graph/analyst_execution.py`).

### 3.2 Agent roles and output state

| Node | Role | State written |
| --- | --- | --- |
| Market Analyst | Prices, indicators, verified OHLCV snapshot | `market_report`, `market_report_obj` |
| Sentiment Analyst | StockTwits/Reddit prefetch + news context | `sentiment_report` |
| News Analyst | Company news, macro, prediction markets | `news_report` |
| Fundamentals Analyst | Statements and company fundamentals | `fundamentals_report`, `fundamentals_report_obj` |
| Bull / Bear Researchers | Adversarial investment cases | `investment_debate_state` |
| Research Manager | Debate judgement, rating, plan | `investment_plan`, `investment_debate_state` |
| Trader | Concrete transaction proposal | `trader_investment_plan` |
| Aggressive / Conservative / Neutral | Risk debate | `risk_debate_state` |
| Portfolio Manager | Final decision and rating | `final_trade_decision` |

The full state schema, including `trade_date`, `instrument_context`, `past_context`,
`portfolio_context`, and the typed `*_report_obj` side channels, is in
`tradingagents/agents/utils/agent_states.py:1-73`.

### 3.3 Attribution wrappers

Every business-agent node is wrapped by `attrib_agent_node(agent_id, fn, node_name)`
before being added, and every analyst `ToolNode` by `attrib_tool_round(agent_id, ...)`
(`setup.py:130-158`). The wrappers set the `ContextVar` scope, record a
`NodeContextEvent`, and restore the previous scope in `finally`
(`tradingagents/observability.py:2374-2520`). This is the only place agent identity is
established; it is never inferred from generated text.

---

## 4. Data flow of one run

### 4.1 Entry points

- **CLI:** `tradingagents` (Typer app) → `cli/main.py`; it calls `create_run_state`,
  `begin_checkpoint`, streams the compiled graph, then writes reports and the state
  log. The CLI is the interactive path; the measured batch uses `propagate()`.
- **Programmatic:** `TradingAgentsGraph.propagate(company_name, trade_date,
  asset_type="stock", portfolio=None)`
  (`tradingagents/graph/trading_graph.py:450-478`). It validates the date, enters a
  telemetry run scope, enters a checkpoint scope, and calls `_run_graph`.

### 4.2 Ordered flow

1. **Date validation.** `_validate_trade_date` requires canonical `YYYY-MM-DD` and
   rejects any date after today (`trading_graph.py:55-66`).
2. **State assembly.** `create_run_state` settles this ticker's pending decision-log
   entries, builds `past_context` filtered by the PIT cutoff, resolves deterministic
   instrument identity, and renders portfolio context when supplied
   (`trading_graph.py:576-594`; `tradingagents/graph/propagation.py:18-39`).
3. **Graph construction.** LLM clients are created from config
   (`trading_graph.py:129-150`); tool nodes are created per analyst
   (`trading_graph.py:232-278`); `GraphSetup` compiles the graph
   (`trading_graph.py:184-188`).
4. **Pre-graph reflection.** Pending entries for the same ticker are resolved against
   realised returns and a reflection LLM call; the call is scoped to
   `system:pre_graph_reflector` (`trading_graph.py:360-408`;
   `tradingagents/graph/reflection.py:41-73`).
5. **Graph execution.** `graph.invoke` (or `graph.stream` in debug) runs the nodes in
   section 3. Tool loops are executed by `ToolNode`; single-pass analysts execute
   their own tool batches inside the node (section 6).
6. **Post-run outputs.**
   - State log: `results_dir/<safe_ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json`
     (`trading_graph.py:671-712`).
   - Decision log: `store_decision` appends a pending entry
     (`trading_graph.py:606-614`).
   - Signal: `SignalProcessor.process_signal` extracts the five-tier rating
     (`trading_graph.py:714-716`; `tradingagents/graph/signal_processing.py`).
   - Report tree: `write_report_tree` (CLI and `save_reports`)
     (`tradingagents/reporting.py:13`).
   - Telemetry: one atomic JSON artifact per run
     (`tradingagents/observability.py:2262-2308`).

### 4.3 Checkpointing

When `checkpoint_enabled` is set, `begin_checkpoint` compiles the graph with a
per-ticker SQLite saver, keys the thread by analyst selection, debate/risk depth,
asset type, and portfolio fingerprint, and `checkpoint_input` passes `None` on resume
so LangGraph continues rather than duplicating messages
(`trading_graph.py:498-559`). A completed run clears its checkpoint.

---

## 5. Tools and structured output

### 5.1 Tool inventory

Tool objects are defined in `tradingagents/agents/utils/*_tools.py` and bound to
per-analyst `ToolNode`s in `trading_graph.py:232-278`.

| Analyst | Tools the LLM is actually bound to |
| --- | --- |
| Market | `get_stock_data`, `get_indicators`, `get_verified_market_snapshot` |
| Sentiment | none — stocktwits, Reddit and `get_news` are prefetched into the prompt (`sentiment_analyst.py:130-190`) |
| News | `get_news`, `get_global_news`, `get_macro_indicators`, `get_prediction_markets`, plus `get_macro_indicators_batch` when the switch is on (`news_analyst.py:154-164`) |
| Fundamentals | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` |

The graph also registers `get_insider_transactions` in the news `ToolNode`, but the
news analyst's bound list does not include it, so the model cannot call it on the
shipped path. It is a vestigial ToolNode entry, not an analyst tool. Similarly, the
sentiment node's `tools_social` ToolNode (`get_news`) is not reachable because the
sentiment analyst binds no tools and returns a no-tool-call message. These are noted
because the "tools available to the news analyst" and "tools in the news ToolNode"
sets are not identical.

Every dated tool declares `trade_date` as an `InjectedState("trade_date")` parameter.
The graph strips model-supplied values for injected arguments and overlays the state
value; the single-pass runner reproduces that contract (`structured.py:571-725`).
This prevents a model from moving a data window past the run date.

Tools return **text**, not exceptions, for recoverable data problems: typed sentinels
such as `NO_DATA_AVAILABLE` / `DATA_UNAVAILABLE` / `CONFIG_DISABLED` are part of the
contract (`tradingagents/dataflows/interface.py:187-311`). A failed tool call inside a
`ToolNode` becomes a `ToolMessage` with `status="error"`, which the model can read
(`structured.py:700-721`). Optional categories (macro, prediction markets) degrade to
a sentinel; core categories raise so a broken primary is loud
(`interface.py:93-101`, `255-311`).

### 5.2 Two structured-output mechanisms

There are two distinct patterns, and conflating them is a common source of wrong
claims:

1. **Whole-turn structured output (downstream agents).**
   `invoke_structured_or_freetext` calls `llm.with_structured_output(Schema)` and
   renders the parsed object; on any failure it retries once as free text
   (`structured.py:187-245`). Used by Research Manager, Trader, Portfolio Manager,
   and Sentiment Analyst. On failure the returned object is `None` — prose is never
   reported as a typed object.
2. **Terminal analyst finalisation (the three tool-loop analysts).**
   The analyst loop itself cannot carry the schema on every turn; structure is
   applied at the terminal generation. RC1 uses `finalize_analyst_report` (a second
   call over the finished loop); CAND-01 uses `finalize_single_pass` (the schema is
   bound as an extra tool on the call that would have written prose).

Schemas are Pydantic models in `tradingagents/agents/schemas.py` (1,226 lines):
`MarketAnalystReport`, `FundamentalsAnalystReport`, `NewsAnalystReport`,
`SentimentReport`, `ResearchPlan`, `TraderProposal`, `PortfolioDecision`, and their
renderers.

### 5.3 Prompt hygiene for schema-bound calls

- Free-text layout sentences are withheld from the schema-bound call only; the
  free-text fallback keeps them (`structured.py:101-135`, `271-337`).
- Tool-use instructions that conflict with a schema-only binding are neutralised for
  that call (`STRUCTURED_TOOL_INSTRUCTION_RE`, `structured.py:79-90`).
- `NO_EXTERNAL_TOOLS` prevents schema-bound agents from trying to call data tools
  (`structured.py:44-49`).
- The single-pass call additionally says it may call data tools if evidence is still
  missing, because it is bound to both data tools and the schema
  (`SINGLE_PASS_FINALISATION_INSTRUCTION`, `structured.py:83-96`).

### 5.4 Typed side channels and S2 routing

The market and fundamentals analysts return `market_report_obj` /
`fundamentals_report_obj` alongside markdown. Bull, Bear, and the three risk analysts
route role-specific fields (invalidation conditions, scenario sets, evidence) through
`tradingagents/agents/utils/s2_context.py` and `routed_report`. The switch
`s2_downstream` is declared but has **no OFF implementation**; the verifier refuses
to run it as `False` rather than pretending an off-arm exists
(`tradingagents/graph/switch_verification.py:42`, `77-80`). Treat S2 routing as
always-on in the delivered tree.

---

## 6. Single-pass finalisation (CAND-01)

### 6.1 Switch and preconditions

`single_pass_finalization_enabled` defaults to `False`
(`tradingagents/default_config.py:138-143`). `GraphSetup` enables it only when both
the single-pass switch and `structured_analyst_output_enabled` are true
(`setup.py:88-93`). Setting it without structured output is a no-op, pinned by
`tests/test_cand01_single_pass_finalization.py::RegressionTest::test_setup_requires_structured_before_enabling_single_pass`.

### 6.2 Algorithm

`finalize_single_pass` (`structured.py:856-1087`):

1. Bind the analyst's data tools **plus** the schema as tools:
   `llm.bind_tools([*tools, schema])`.
2. Loop up to `SINGLE_PASS_MAX_ROUNDS = 4`:
   - Invoke the prompt over the growing history.
   - If the turn carries the schema call and no data call, validate it and render the
     report. Return the rendered report, the parsed object, and a terminal message
     sequence in which every executed data call is paired with its `ToolMessage` and
     the last turn has no pending tool call.
   - If the turn mixes schema and data calls, execute only the data calls and strip
     the schema call from the assistant turn so the next request has no dangling id.
   - If the turn has data calls only, execute them through `run_data_tools`, which
     re-injects PIT state and records one tool round per non-empty batch.
   - If the turn has neither shape (prose), return that prose (sanitised) as the
     report, keeping the terminal sequence legal.
3. Every failure path lands on a legal fallback: schema-invalid → one free-text retry
   over the same history through `prompt | llm`; budget/tool exhaustion → one
   free-text retry; no structured capability → the plain loop.
4. `report_obj` is `None` on every fallback, so downstream cannot mistake prose for a
   typed report.

### 6.3 Why it is expected to save tokens, and what was measured

The RC1 two-call path pays for a full prose report and then pays a second call that
re-sends the history to regenerate the same analysis as typed fields; the prose is
discarded. Single-pass removes that second call. On V3 (the `e3b5cca` tree, 15 valid
samples, three complete blocks):

| Block | Effect per run | Relative |
| --- | --- | --- |
| NVDA | −8,907 | −3.82% |
| AAPL | −16,390 | −8.31% |
| XOM | −33,472 | −14.82% |
| **Balanced mean** | **−19,589** | **−8.96%** |

These are descriptive numbers, not a significance test. The gain is concentrated in
the three analysts; downstream nodes gave back about +8,921 tokens because the merged
reports are longer. The same experiment found single-pass introduced fallback quality
failures (R07/R14 markup, R12 provider 400), which is why the delivery includes the
remediation in section 13 and why the shipped default remains off.

---

## 7. Batch macro (CAND-01)

`get_macro_indicators_batch` (`macro_data_tools.py:132-219`) fetches several FRED
series in one tool call. Contract:

- The `BeforeValidator` (`_coerce_indicator_list`) is total: string, comma list,
  JSON-ish list, tuple/set, dict, and `None` are all accepted and never raise; a
  malformed model argument cannot abort the run (`macro_data_tools.py:16-88`).
- Inputs are deduplicated case-insensitively; more than
  `MAX_BATCH_INDICATORS = 12` is refused without fetching.
- Each series is fetched through the same `route_to_vendor` call, same PIT date, same
  window and formatting as the single-series tool, so per-series text is identical.
- One series failing does not lose the others; the failure is reported inline. If all
  fail, the block starts with an explicit `DATA_UNAVAILABLE` and the counts.
- Empty or all-duplicate requests return an instruction, not a fabricated series.

The switch is read at graph construction. When off, the news analyst neither binds
the tool nor advertises it in the prompt (`news_analyst.py:173-197`), and the news
`ToolNode` also excludes it (`trading_graph.py:253-267`), so an OFF run cannot execute
a batch call even if the model emits one. The single-series tool always remains.

**Measured V3 effect:** mean −17,702 tokens/run, but the direction is not consistent
(NVDA −51,716; AAPL +1,612; XOM −3,002). The NVDA figure depends on R01, a run with
an environment-degraded market feed. Excluding R01 the batch effect is about −695.
Tool calls fell from 7–9 single-series calls to 1–1.2 batch calls, but total macro
payload bytes were roughly unchanged, so the call-count reduction did not translate
into a token reduction. The branch therefore treats batch macro as **not
demonstrated** to save tokens, despite being a valid call-reduction tool.

---

## 8. Point-in-time (PIT) enforcement

PIT means a run dated `D` may use only information available by the decision point
for `D`; it must not read data published or revised later. The delivered enforcement
has several independent layers.

### 8.1 Date discipline at the boundary

- `trade_date` must be canonical and not in the future (`trading_graph.py:55-66`).
- The resolved instrument identity is injected into every agent's context so a model
  cannot substitute a different company (`trading_graph.py:410-421`).
- Dated tools receive `trade_date` from graph state via `InjectedState`, not from the
  model (`agent_utils` tool declarations; `structured.py` re-implements the injection
  for single-pass).

### 8.2 Date windows

`tradingagents/dataflows/date_window.py` is the shared rule set:

- `as_of(requested, trade_date)` returns the earlier of the model's requested date
  and the run date (`date_window.py:115-125`).
- `as_of_window` clamps a window's end to the run date and preserves a wholly
  future window's length by moving it back (`date_window.py:128-138`).
- `publication_cutoff(trade_date)` returns midnight UTC after the trade date, so
  same-day news is admitted and post-decision days are not (`date_window.py:141-162`).
- `in_window` uses a half-open window and keeps an undated item only when the window
  reaches the present; in a backtest an undated item cannot be proven safe and is
  dropped (`date_window.py:24-32`).
- `withhold_live_profile` refuses to serve a present-day company profile into a
  historical run (`date_window.py:165-191`).

### 8.3 Memory PIT

Past lessons are filtered by the date their outcome became known
(`resolved:YYYY-MM-DD`), not by the decision date
(`tradingagents/agents/utils/memory.py:73-110`; `trading_graph.py:423-432`). A live
run disables the filter; a historical run sees only lessons resolved by its date.

### 8.4 Scope and limits

The PIT tests cover news (Finnhub/GDELT), social sentiment, dated market tools,
macro/macro-batch clamping, fundamentals live-profile withholding, memory as-of, and
single-pass tool injection. There is no single global "PIT middleware": a new vendor
or a new undated tool must use `date_window.as_of`/`as_of_window` or it is not
covered. This is stated as a partial-invariant boundary in
`docs/architecture/invariants.md`.

---

## 9. News path

### 9.1 Configured scope

The shipped configuration is Finnhub-only:

- `data_vendors.news_data` and `tool_vendors.get_news` are `"finnhub"`
  (`default_config.py:172-192`).
- `get_news`'s Finnhub route is `get_news_finnhub_only`, which does not contact GDELT
  (`interface.py:132-142`).
- `get_global_news`'s Finnhub route is `get_global_news_finnhub`, which returns an
  explicit `CONFIG_DISABLED` status rather than borrowing another provider
  (`finnhub_news.py:734-766`).
- GDELT remains implemented (`dataflows/gdelt_news.py`) and is reachable only by
  explicitly changing the vendor configuration for a study that wants macro news.
  The point is that the configured Finnhub path cannot silently acquire a second
  feed.

### 9.2 Point-in-time and provenance

- Finnhub company news takes an explicit symbol and `from`/`to` window. Articles are
  filtered against `[start 00:00Z, cutoff)`, where the cutoff defaults to midnight
  after the end date; unparsable or missing timestamps are dropped because
  future-ness cannot be disproven (`finnhub_news.py:1-70`).
- The key is read at call time and redacted from logs/exceptions
  (`finnhub_news.py:79-110`).
- Relevance is a weak, recorded signal: `related` metadata is not sufficient to
  claim an article is about the requested company
  (`tradingagents/dataflows/news_relevance.py`).
- The merged block carries a status per source (`NewsStatus`), so an outage,
  a rate limit, an empty-but-valid window, and a disabled configuration are
  distinguishable (`tradingagents/dataflows/news_status.py`,
  `news_merge.py`).

### 9.3 Availability must come from provenance, not prose

The news node classifies the company feed from the real `get_news` `ToolMessage`s.
If unavailable, Python forces `Unknown` and prepends the application banner; if
available, it adds the system status line. It never reads or rewrites the model's
text to decide availability (`news_analyst.py:24-157`, `_guard_news_unavailable`,
`_news_available_note`). PF-01 fixed the single-pass case where the classification
ran before the loop had executed the news tool (commit `7832a90`; tests in
`tests/test_cand01_single_pass_finalization.py::NewsMissingnessTest` and
`tests/test_cand01_news_positive_path.py`).

---

## 10. Memory

### 10.1 Product semantics

`TradingMemoryLog` (`tradingagents/agents/utils/memory.py`) is an append-only
markdown decision log:

- **Write:** `store_decision` appends `[date | ticker | rating | pending]` plus the
  decision. A fast raw-text scan makes the write idempotent for the same
  ticker/date.
- **Settle:** at the start of a new same-ticker run, `_resolve_pending_entries`
  fetches the realised return over `holding_period_days`, calls the Reflector, and
  atomically batch-updates the entries with return, alpha, holding period, and
  `resolved:<date>` (`trading_graph.py:360-408`).
- **Read:** `get_past_context` returns up to 5 same-ticker decisions and 3
  cross-ticker lessons, filtered to lessons already resolved by the PIT cutoff.
- **Rotation:** `memory_log_max_entries` caps resolved entries; pending entries are
  never dropped (`memory.py:251-286`).
- **Atomicity:** updates use a temp file plus `os.replace`, so a crash cannot leave a
  half-written log (`memory.py:176-178`, `230-232`).

This is the shipped product behaviour and it is stateful by design: a run can change
the next same-ticker run's prompt context and cost.

### 10.2 Experiment semantics (per-run isolation)

The V2 batch proved that shared memory confounds the 2×2: R05's write changed R06's
execution path and token cost. V3 introduced an experiment-only contract:

- One immutable baseline snapshot (`.../memory/baseline_v3.md`, empty, SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
- One writable copy per run at
  `specs/<run>/runs/run_01/attempt_MM/memory/trading_memory.md`.
- `_config_for_spec` points `memory_log_path` at the copy before graph construction
  (`scripts/token_benchmark.py:4161-4180`).
- Preflight refuses a missing/changed snapshot, a modified copy, a copy outside the
  attempt directory, a copy equal to the baseline, or a V3 spec without a memory
  block (`scripts/token_benchmark.py:3784+`, `4230+`).
- Post-run `memory_state.json` records the baseline hash; a changed baseline makes
  the run `INVALID` with `memory_snapshot_modified`
  (`scripts/token_benchmark.py:2715`, `2878`).

This isolation is **experiment harness behaviour**, not a product default. The
product still uses one log; the harness overrides the path per run.

---

## 11. Usage attribution

### 11.1 Scope model

Attribution is a `ContextVar` (`AttributionContext`) with exactly one of:

- `agent` — set by `attrib_agent_node` for a graph node (stable agent id).
- `system` — set by `system_component_scoped` for a product component that calls a
  provider outside a node. The only shipped component is
  `pre_graph_reflector` (`observability.py:151-163`, `381-405`).
- `none` — no scope. A call in this state is recorded under `unattributed`; the
  experiment harness treats it as `INCOMPLETE` and voids the run
  (`scripts/token_benchmark.py:569-790`).

The API refuses to use an agent id as a system component and vice versa
(`observability.py:359-405`), so a component cannot be laundered as an agent.

### 11.2 Recording

`ObservabilityCallbackHandler` (`observability.py:1117-1425`) listens on LangChain
callbacks. It records:

- **LLM call:** agent/component, provider, model, success/error class, start/end,
  prompt message count and UTF-8 bytes, tool-message bytes, and provider usage
  (`input`, `output`, `reasoning`, `cached_input`) plus the sanitized raw usage blob.
- **Tool execution:** name, agent, success, duration, argument fingerprint, result
  byte size and SHA-256, duplicate count. Result bodies are never stored.
- **Tool round:** one per `ToolNode` batch / one per non-empty batch in the
  single-pass runner.
- **Prefetch / structured / node:** counts, sizes, outcomes, never content.

Prompt and tool-result contents are deliberately excluded; the privacy tests assert
this (`tests/test_observability.py::TestPromptDiagnostics` and
`TestTelemetryPersistence::test_privacy_*`).

### 11.3 Invariants of the telemetry payload

The collector (`RunMetricsCollector`, `observability.py:714-1032`) and
`_build_telemetry_dict` (`1739-2117`) enforce:

- **Provider usage is authoritative.** Missing usage is `UNKNOWN` / `PARTIAL`, never
  zero. A provider that reports usage but omits a field increments a
  `calls_missing_*` counter and does not add zero (`observability.py:881-923`).
- **Totals close.** `run_totals` is the sum of agent buckets, system-component
  buckets, and the unattributed pseudo-agent. A call is never dropped from the total
  because of who made it (`observability.py:1856-1900`).
- **Attribution is reported.** `attribution_summary` gives agent/system/unattributed
  call and token counts; `attribution_complete` is false when any event is
  unattributed (`observability.py:1925-1972`).
- **Cached input is a subset of input, not added again.**
- **Coverage and self-audit are separate.** `usage_coverage.complete` requires every
  call to carry usage **and** both token fields; `usage_checks` records raw-blob
  presence and impossible negative counts (`observability.py:1900-1930`).

### 11.4 Artifact and schema

- One atomic JSON per run:
  `<results_dir>/<safe_ticker>/<date>/telemetry/<run_id>.json`
  (`observability.py:2262-2308`).
- Schema version 2 (`observability.py:711`), with per-event
  `attribution_type`/`component_id` and separate `system_components`.
- The experiment harness independently replays per-call events and compares them to
  the run totals; disagreement is `MISMATCH`, missing usage is `MISSING`/`INCOMPLETE`,
  and only `VALID` samples are used for comparisons
  (`scripts/token_benchmark.py:569-790`).

### 11.5 Measured coverage

- V2 (5 valid samples): 99 LLM calls, 99/99 with complete provider usage. R06 was
  invalid for attribution (21/21 usage but one unscoped call), not for missing usage.
- V3 (15 valid samples): 298 LLM calls, 298/298 with complete provider usage;
  432 tool calls. All 18 attempts: 307 LLM / 456 tool.
- V3 valid tokens: 3,002,579 (input 2,549,258 + output 453,321); failed attempts
  65,090; total 3,067,669.
- V2: 7 attempts, 5 valid, 1,463,791 tokens (valid 1,109,645 + failed 354,146);
  138 LLM / 227 tool calls across all attempts.

These are the numbers the ADRs cite; they come from the run ledger and from
independently recomputed telemetry, not from a summary written by the thing being
measured.

---

## 12. Freeze and experiment infrastructure

### 12.1 Design

The experiment is a pre-registered 2×2 over `batch_macro` × `single_pass`, with
`structured=true` and `s2_downstream=true`, four tickers (NVDA, AAPL, JPM, XOM), one
trade date (`2026-09-23`), and 16 runs in a fixed order
(`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`).
The same design was used for V2 and V3; V3 added attribution and memory contracts and
therefore new `config_sha256` values.

### 12.2 Specs and hashes

Each run has a pre-registered spec and registration (`specs/R01…R16/spec.json`,
`experiment.json`) carrying the arm, switches, news scope, budget, memory declaration,
and `config_sha256`. The registration hash is recomputed, not trusted
(`scripts/token_benchmark.py`; tests
`tests/test_c3_regressions.py::test_registration_hash_is_recomputed_not_trusted`).
`CONFIG_HASH_MANIFEST.csv` lists the 16 hashes; `MANIFEST.sha256` hashes every shipped
batch artifact.

### 12.3 Freeze chain and verification

| Freeze | Commit | Tag | What it certifies |
| --- | --- | --- | --- |
| RC1 | `9948bf8` | `rc1` | validated upstream-style baseline |
| V2 | `15270b1` | `c3-final-freeze` | attribution schema 1 batch |
| V3 | `e3b5cca` | `c3-v3-final-freeze` | attribution schema 2 + memory isolation |
| Final remediation | `50b2ca3` | `cand01-v3-final-remediation` | R12/DSML/tool-round fixes, tests, docs |

`scripts/c3_finalize_freeze.py` writes the record; `scripts/c3_verify_final_freeze.py`
recomputes it from the tree. The verifier checks `HEAD`, tree hash, clean working
tree, code fingerprint, every `MANIFEST.sha256` digest, all 16 config hashes, protocol
and generator hashes, the budget contract, spec path containment, and the annotated
tag (`scripts/c3_verify_final_freeze.py:1-80`). A failure exits non-zero and the
preflight gate refuses to spend.

### 12.4 Pre-spend gates

`_preflight_gate`, `_guard_spending_path`, `verify_frozen_tree`, and `verify_import_root`
refuse a run before a paid call when the spec is outside its registered batch, the
config hash does not recompute, switches disagree with the switch matrix, the news
scope is not Finnhub-only, the budget contract is malformed, or the memory snapshot
is invalid (`scripts/token_benchmark.py`; tests
`tests/test_c3_regressions.py`, `tests/test_memory_isolation.py`). A refusal is
`RunRefused` and consumes no attempt.

### 12.5 Experiment results and audits

- V2 and V3 were run as recorded; V3 had 16 run IDs and 18 attempts (R02 and R12
  retried). R02's first attempt was an environment failure; R12's two attempts were
  invalid (provider 400).
- Three independent read-only audits on the remediation tree returned PASS
  (`token_benchmarks/final_remediation_20261116/INDEPENDENT_AUDIT.md`).
- The **recorded** final suite at `50b2ca3` is 2,227 passed / 4 known failed /
  2 skipped / 319 subtests (`token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`).
- Those four failures were two absolute-path V3 spec checks and two `cli_prefs`
  environment couplings. They are retained in the frozen test record. In this working
  tree on 2026-11-19 the same offline command reports **2,233 passed / 0 failed /
  2 skipped / 319 subtests**; the submission work that fixed them is separate from the
  V3 experiment and does not change the recorded batch numbers.

---

## 13. Failure handling

### 13.1 Agent and structured-output failures

- **Structured call fails** → one free-text retry; the run continues. The report may
  be prose, and `report_obj` is `None`.
- **Schema validation fails in single-pass** → `_free_text_retry` drops a trailing
  assistant turn that carries an unanswered `tool_call` and invokes through
  `prompt | llm`, preserving the system prompt. This is the R12 fix
  (`structured.py:807-854`).
- **Protocol markup in a report** → `sanitize_analyst_text` keeps prose before the
  first marker if it is long enough, otherwise recovers analysis-bearing parameter
  values, otherwise returns an explicit `[REPORT UNAVAILABLE …]`; it never returns
  markup and never silently returns `""` (`structured.py:392-481`).
- **Tool call fails / unknown tool** → an error `ToolMessage`; the model can react.
- **Round budget exhausted** → one free-text attempt over the history; an empty
  model answer is logged and left as `""`, exactly as RC1 can return an empty
  `free_text_block`. This residual is documented, not papered over.

### 13.2 Data failures

- The vendor chain uses only the configured vendors; it never silently falls back to
  an unconfigured one (`interface.py:187-220`).
- Typed errors drive the response: no data → `NO_DATA_AVAILABLE`; all throttled or
  retired → `DATA_UNAVAILABLE`; optional category failure → `DATA_UNAVAILABLE` and
  continue; core category failure → re-raise (`interface.py:220-311`).
- Macro batch failure is per-series; total failure is labelled as such.
- News failures are classified into `NewsStatus` and reflected in the merged block;
  a dead company feed forces `Unknown` rather than a fabricated Neutral.

### 13.3 Run-level failures

- Telemetry finalisation never raises: a failed artifact write logs and returns
  `None`; the analysis result is not lost (`observability.py:2262-2308`).
- A failed reflection leaves the decision pending for the next same-ticker run
  (`trading_graph.py:388-396`).
- Checkpointing resumes from the last successful node when enabled; a successful run
  clears its checkpoint.
- The budget gate reports `UNKNOWN_SPEND` rather than a false total when usage is
  missing; it never rounds missing usage to zero
  (`tradingagents/budget_guard.py:1-100`).

### 13.4 Known residuals

1. A single-pass prose ending can still be empty if the model itself returns `""`.
2. Historical V3 telemetry has `tool_rounds = 0` because the runner did not record
   rounds at `e3b5cca`; the fix applies to new runs, and old data is not rewritten.
3. `markup_sanitized` has its own counter and is not folded into
   `structured_attempts`, so the RC1 attempt identities still balance.
4. The four failures recorded at `50b2ca3` are retained in `TEST_RESULTS.md`; the
   current working tree's offline suite passes (2,233 / 0 failed / 2 skipped / 319
   subtests, observed 2026-11-19). The frozen record is not rewritten.
5. No paid re-run was performed after the remediation; R12 is verified by offline
   fixtures, not by a new provider call.

---

## 14. Testing and deployment constraints

### 14.1 Test layout and commands

- `pyproject.toml` sets `testpaths = ["tests"]`, `pytest-subtests`, and
  `--strict-markers`.
- `tests/` holds the offline suite. The recorded command at `50b2ca3` is:
  `TZ=UTC .venv/bin/python -m pytest -q` → 2,227 passed, 4 failed, 2 skipped,
  319 subtests (`TEST_RESULTS.md`). In this working tree on 2026-11-19 the same
  command reports 2,233 passed, 0 failed, 2 skipped, 319 subtests.
- Targeted suites: `test_observability.py`, `test_system_attribution.py`,
  `test_token_benchmark.py`, `test_memory_isolation.py`, `test_final_remediation.py`,
  `test_cand01_single_pass_finalization.py`, `test_macro_batch.py`,
  `test_finnhub_only_scope.py`, `test_news_lookahead.py`,
  `test_tool_date_enforcement.py`, `test_c3_final_freeze.py`,
  `test_c3_regressions.py`.
- Tests are offline: provider calls are scripted/faked; tool calls are stubbed;
  no network, no paid calls. `tests/test_finnhub_only_scope.py` uses a GDELT tripwire
  to prove the Finnhub path never contacts GDELT.
- `test/live` and `test/offline` are separate upstream trees; the delivered gate is
  `tests/` via `pyproject.toml`.

### 14.2 Runtime and deployment

- Python `>=3.10`; the Docker image builds on `python:3.12-slim`
  (`pyproject.toml`, `Dockerfile`).
- The CLI entry point is `tradingagents = cli.main:app`; Docker runs it as a
  non-root user.
- The measured environment uses an OpenAI-compatible endpoint with
  `CS5351/DeepSeek-V4-Flash` for both quick and deep models, plus `FINNHUB_API_KEY`
  and `FRED_API_KEY`. These are environment inputs, not hard-coded product
  constants. The harness loads CityU credentials via `apply_cityu_env` from a
  secrets file (`scripts/token_benchmark.py:4717+`).
- A run needs a results directory, a cache directory, and a writable memory path;
  defaults are under `~/.tradingagents` (`default_config.py:76-84`).
- Telemetry adds one JSON artifact per run; it does not add a network dependency or
  a database.

### 14.3 Evidence boundary

The blueprint, the ADRs, the invariants, and the trace matrix describe the delivered
tree at `50b2ca3`. The V3 experiment numbers describe `e3b5cca`. Any statement that
mixes the two without saying so is a documentation defect; the trace matrix records
the correct evidence pointer per row.
