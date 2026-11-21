<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>
<br>
<div align="center">
  <a href="https://github.com/TauricResearch" target="_blank"><img alt="TradingAgents #1 Repository of the Day" src="https://trendshift.io/api/badge/repositories/16192" width="250" height="55"/></a>
</div>
<br>
<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agents LLM Financial Trading Framework

## News
- [2026-09] **TradingAgents v0.5.0** released with point-in-time integrity across every dated path, SEC EDGAR fundamentals served as filed, backtesting over a ticker and date grid, portfolio-aware runs, and current model lineups across every provider.
- [2026-08] **TradingAgents v0.4.0** released with look-ahead / point-in-time fixes across FRED macro, social sentiment, and the decision-log memory; clearer decision signals; working CLI checkpoint resume; Trader price grounding; and the GPT-5.6 and GLM-5.3 models.
- [2026-07] **TradingAgents v0.3.1** released with correctness and stability fixes: Alpha Vantage look-ahead filtering, graph-router crash-safety, graph-shape-aware checkpoint resume, working crypto sentiment sources, a configurable LLM retry budget, Bedrock API-key auth, and Claude Sonnet 5 / Fable 5 support.

<details>
<summary>Earlier releases</summary>

- [2026-06] **TradingAgents v0.3.0** released with a verified data-access contract, an expanded provider registry (NVIDIA, Kimi, Groq, Mistral, Bedrock, and any OpenAI-compatible endpoint), FRED and Polymarket data vendors, a current-generation model catalog, and a CI gate.
- [2026-05] **TradingAgents v0.2.5** released with the grounded Sentiment Analyst, GPT-5.5 etc. model coverage, Qwen/GLM/MiniMax dual-region support, `TRADINGAGENTS_*` env-var configurability with API-key auto-detection, remote Ollama support, non-US alpha benchmarks, and ticker path-traversal hardening.
- [2026-04] **TradingAgents v0.2.4** released with structured-output agents (Research Manager, Trader, Portfolio Manager), LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure provider support, Docker, and a Windows UTF-8 encoding fix.
- [2026-03] **TradingAgents v0.2.3** released with multi-language support, GPT-5.4 family models, unified model catalog, backtesting date fidelity, and proxy support.
- [2026-03] **TradingAgents v0.2.2** released with GPT-5.4/Gemini 3.1/Claude 4.6 model coverage, five-tier rating scale, OpenAI Responses API, Anthropic effort control, and cross-platform stability.
- [2026-02] **TradingAgents v0.2.0** released with multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) and improved system architecture.
- [2026-01] **Trading-R1** [Technical Report](https://arxiv.org/abs/2509.11420) released, with [Terminal](https://github.com/TauricResearch/Trading-R1) expected to land soon.

</details>

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | ⚡ [Installation & CLI](#installation-and-cli) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents: from fundamental analysts, sentiment experts, and technical analysts, to trader, risk management team, the platform collaboratively evaluates market conditions and informs trading decisions. Moreover, these agents engage in dynamic discussions to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

Our framework decomposes complex trading tasks into specialized roles.

### Analyst Team
- Fundamentals Analyst: Evaluates company financials and performance metrics, identifying intrinsic values and potential red flags.
- Sentiment Analyst: Aggregates news headlines, StockTwits, and Reddit chatter into a single sentiment read to gauge short-term market mood.
- News Analyst: Monitors global news and macroeconomic indicators, interpreting the impact of events on market conditions.
- Technical Analyst: Utilizes technical indicators (like MACD and RSI) to detect trading patterns and forecast price movements.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance potential gains against inherent risks.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from the analysts and researchers to make informed trading decisions, determining the timing and magnitude of trades.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management and Portfolio Manager
- Continuously evaluates portfolio risk by assessing market volatility, liquidity, and other risk factors. The risk management team evaluates and adjusts trading strategies, providing assessment reports to the Portfolio Manager for final decision.
- The Portfolio Manager approves/rejects the transaction proposal. If approved, the order will be sent to the simulated exchange and executed.

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

## Installation and CLI

### Installation

Clone TradingAgents:
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

Create a virtual environment in any of your favorite environment managers:
```bash
conda create -n tradingagents python=3.12
conda activate tradingagents
```

Or with [uv](https://docs.astral.sh/uv/):
```bash
uv venv --python 3.12
source .venv/bin/activate
```

Install the package and its dependencies (`uv pip install .` with uv):
```bash
pip install .
```

### Docker

Alternatively, run with Docker:
```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

After updating the repository, rebuild the image with `docker compose build`.

For local models with Ollama:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### Required APIs

TradingAgents supports multiple LLM providers. Set the API key for your chosen provider:

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen — International (dashscope-intl.aliyuncs.com)
export DASHSCOPE_CN_API_KEY=...    # Qwen — China (dashscope.aliyuncs.com)
export ZHIPU_API_KEY=...           # GLM via Z.AI (international)
export ZHIPU_CN_API_KEY=...        # GLM via BigModel (China, open.bigmodel.cn)
export MINIMAX_API_KEY=...         # MiniMax — Global (api.minimax.io)
export MINIMAX_CN_API_KEY=...      # MiniMax — China (api.minimaxi.com)
export OPENROUTER_API_KEY=...      # OpenRouter
export MISTRAL_API_KEY=...         # Mistral
export MOONSHOT_API_KEY=...        # Kimi (Moonshot)
export GROQ_API_KEY=...            # Groq
export NVIDIA_API_KEY=...          # NVIDIA NIM
export FRED_API_KEY=...            # FRED macro data (free, optional)
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
```

For Azure OpenAI, copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For AWS Bedrock, install the extra with `pip install ".[bedrock]"`, set `llm_provider: "bedrock"`, configure AWS credentials (environment variables, `~/.aws/credentials`, or an IAM role) and `AWS_DEFAULT_REGION`, and use a Bedrock model ID, e.g. `us.anthropic.claude-opus-4-8-v1:0`.

For local models, configure Ollama with `llm_provider: "ollama"`. The default endpoint is `http://localhost:11434/v1`; set `OLLAMA_BASE_URL` to point at a remote `ollama-serve`. Pull models with `ollama pull <name>`, and pick "Custom model ID" in the CLI for any model not listed by default.

For any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp, or a custom relay), use `llm_provider: "openai_compatible"` and set the endpoint via `backend_url` (or `TRADINGAGENTS_LLM_BACKEND_URL`), e.g. `http://localhost:8000/v1` for vLLM or `http://localhost:1234/v1` for LM Studio. The model is whatever your server serves. No key is needed for local servers; set `OPENAI_COMPATIBLE_API_KEY` when the endpoint requires one.

Alternatively, copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

### CLI Usage

Launch the interactive CLI:
```bash
tradingagents          # installed command
PYTHONPATH=src python -m cli.main     # alternative: run directly from source
```
You will see a screen where you can select your desired tickers, analysis date, LLM provider, research depth, and more. Your previous run's answers come back as the defaults, so pressing Enter accepts them. The `TRADINGAGENTS_*` variables in `.env` still skip their step entirely.

### Markets and tickers

TradingAgents works with any market Yahoo Finance covers, using the exchange-suffixed ticker. Company identity and the alpha benchmark resolve automatically per market.

- US: `AAPL`, `SPY`
- Hong Kong: `0700.HK` · Tokyo: `7203.T` · London: `AZN.L`
- India: `RELIANCE.NS`, `.BO` · Canada: `.TO` · Australia: `.AX`
- China A-shares: Shanghai `.SS`, Shenzhen `.SZ` (e.g. `600519.SS` for Kweichow Moutai)
- Crypto: `BTC-USD`, `ETH-USD`

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. The framework supports multiple LLM providers: OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (Alibaba DashScope, international and China endpoints), GLM (Zhipu), MiniMax (global + China), OpenRouter, Ollama for local models, and Azure OpenAI for enterprise.

### Python Usage

To use TradingAgents inside your code, you can import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision. You can run `src/main.py`, here's also a quick example:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("NVDA", "2026-09-01")
print(decision)
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        # e.g. openai, google, anthropic, deepseek, groq, ollama; openai_compatible covers any OpenAI-compatible endpoint (vLLM, LM Studio, llama.cpp, ...)
config["deep_think_llm"] = "gpt-5.6"      # Model for complex reasoning
config["quick_think_llm"] = "gpt-5.6-luna" # Model for quick tasks
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-09-01")
print(decision)
```

See `src/tradingagents/default_config.py` for all configuration options.

### Fundamentals as filed

US company statements can come from SEC EDGAR, which records the date every figure was filed. A run dated in the past then reads the statements exactly as they stood that day: a fiscal year that has ended but has not been filed yet is not served, and a figure restated later still reads as first reported. Apple's 2008 total assets were filed as $39.6B and restated to $36.2B in 2010, so a run dated in between reads $39.6B.

EDGAR needs no account or API key. Add the vendor to the chain:

```python
config["data_vendors"]["fundamental_data"] = "sec_edgar,yfinance"
```

SEC asks callers to identify themselves and refuses requests that carry no contact address, so a default one is sent. Set your own so SEC can reach you rather than the project:

```bash
SEC_EDGAR_USER_AGENT="Your Name your@email.com"
```

It covers companies that file with the SEC, including foreign companies listed in the US. Anything else, such as Hong Kong or A-share listings, falls through to the next vendor in the chain. EDGAR's machine-readable filings begin in 2009, and a fourth quarter is reported as unavailable rather than derived, because filers publish it only inside the annual figure.

### Current holdings

By default the agents do not know what you hold, so their guidance is written for a reader who applies it to their own position. Pass a portfolio to have the trader, the risk analysts and the portfolio manager work against your actual book.

```python
from tradingagents.portfolio import PortfolioContext

portfolio = PortfolioContext.model_validate({
    "cash": 25000.0,
    "currency": "USD",
    "positions": [{"ticker": "NVDA", "quantity": 120, "average_price": 150.0}],
})
_, decision = ta.propagate("NVDA", "2026-09-01", portfolio=portfolio)
```

The CLI takes the same content as a JSON file: `tradingagents --portfolio my_book.json`.

An empty `positions` list means a flat book, which is different from passing nothing. A run without a portfolio is never treated as flat.

## Persistence and Recovery

TradingAgents persists two kinds of state across runs.

### Decision log

The decision log is always on. Each completed run appends its decision to `~/.src/tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return (raw, and alpha against the instrument's regional benchmark), generates a one-paragraph reflection, and injects the most recent same-ticker decisions plus recent cross-ticker lessons into the Portfolio Manager prompt, so each analysis carries forward what worked and what didn't.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. The run view says whether it resumed a saved run or started fresh. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.src/tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

```bash
tradingagents --checkpoint           # enable for this run
tradingagents --clear-checkpoints    # reset before running
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-09-01")
```

## Evaluating decisions over time

One run gives one decision, which cannot tell you whether the system decides well. `run_backtest` runs the same pipeline over a grid of tickers and dates, writes to a decision log of its own, and scores the decisions whose holding window has since traded.

```python
from tradingagents.backtest import iter_grid, run_backtest, summarize
from tradingagents.agents.utils.memory import TradingMemoryLog

dates = iter_grid("2026-06-01", "2026-08-01", every_n_days=7)
result = run_backtest(["NVDA", "AAPL"], dates, config, selected_analysts=["market", "news"])
print(summarize(TradingMemoryLog({"memory_log_path": str(result.log_path)})).render())
```

From the CLI:

```bash
tradingagents backtest NVDA,AAPL --start 2026-06-01 --end 2026-08-01 --every 7
```

Each cell is scored on realized alpha against the instrument's regional benchmark, grouped by rating. Your own decision log is never written to, and re-running the same grid with `run_id=result.run_id` skips the cells that already ran, so an interrupted sweep continues where it stopped.

## Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models, not a defect. The variation comes from a few distinct sources, and it helps to separate them.

Language model sampling is non-deterministic. Even at a fixed temperature, providers do not guarantee byte-identical output across calls, and reasoning models (the default GPT-5.x family, and any thinking-mode model) vary the most because their internal reasoning is itself sampled.

Live data moves. News, StockTwits, and Reddit return different content as time passes, so a run today sees different inputs than a run last week even for the same historical trade date. Pin the analysis date to hold the price and indicator window fixed, but the social and news sources still reflect "now".

To reduce variation you can lower the sampling temperature. Set `temperature` in your config (or `TRADINGAGENTS_TEMPERATURE` in `.env`); lower values make models that honor it more repeatable. The current curated models are reasoning-first and largely ignore temperature, so for tighter reproducibility name a non-reasoning model in your config, or in `TRADINGAGENTS_DEEP_THINK_LLM` and `TRADINGAGENTS_QUICK_THINK_LLM`. Any model ID your provider serves is accepted, whether or not the picker lists it.

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["temperature"] = 0.0
# Reasoning models ignore temperature. For tighter reproducibility, name a
# non-reasoning model in deep_think_llm / quick_think_llm.
```

What does not vary anymore: the analyzed company identity is resolved deterministically from the ticker before any agent runs, and the market analyst grounds exact price and indicator claims in a verified data snapshot. Earlier reports of "different companies" or fabricated price levels across runs are addressed by these two mechanisms.

Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling above. Treat the framework as a research scaffold for studying multi-agent analysis, not as a strategy with a fixed, replicable return.

## Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas.

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```

## Development preparation and OpenCode

The current branch integrates release `24adf97` into the existing WebUI layout.
The unified requirements registry retains all 22 core, 26 WebUI and 10 standalone
simulated-trading requirements and their original IDs. Historical verification remains explicitly scoped;
format normalization does not grant new product or human-review approval.

The preparation branch is `feature/webui`, based on TradingAgents v0.5.0. Product source is under `src/`; deterministic and external-service tests are under `test/offline/` and `test/live/`. WebUI requirements are recorded in `docs/req/requirements.yaml`; architecture decisions are recorded in `architecture-blueprint.md` and `docs/architecture/adr/`. Iteration 1 (read-only history/report browser), Iteration 2 (single analysis run with wizard, SSE live view, cancellation, checkpoint toggle, and portfolio input), and Iteration 3 (backtest launch/results and announcements) are implemented. Later work remains blocked on test-plan, safety, governance, and dependency approvals. Empty or draft documents are not approval to implement features.

Create an ignored persistent virtual environment, then install the declared development tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m test.ci_gates permissions
python -m test.ci_gates structure
OPENCODE_CONFIG=.opencode/permissions.jsonc opencode --agent plan
```

### WebUI

Use the language button in the top bar to switch the interface between English
and Chinese. The preference is saved in the current browser. The analysis wizard
provides the same control in its footer, so switching preserves your inputs.
Choose the report output language separately in the wizard; reports, original
decisions and tool output retain their generated content.

The server's `TRADINGAGENTS_LLM_PROVIDER`, `TRADINGAGENTS_QUICK_THINK_LLM` and
`TRADINGAGENTS_DEEP_THINK_LLM` values preselect the analysis provider/models but
do not lock them. Change the selections for one analysis; omitted API selections
and backtests keep server defaults. API keys remain server-only. Switching a
provider clears the previous provider's model/endpoint choices; both model IDs
must be supplied for the new provider. Switching back restores its configured
models. A configured server endpoint applies only to its default provider; other
providers use their own default or an explicit endpoint override. Old model
drafts reset when the server's model defaults change; other draft inputs remain.

In **New analysis → Research setup → Debate rules & budgets**, configure the
real analysis before starting it. Choose dynamic termination or the fixed-round
baseline, set the debate and risk-discussion round caps independently, and tune
convergence thresholds, model-call/token/time budgets and summary reserves.
Quick depth presets update both round caps until you explicitly edit risk
rounds. Server environment locks take precedence and appear read-only.

The review step shows selected settings. The run and saved report show the
normalized settings actually used; older reports without recorded settings do
not acquire inferred values. Summary reserves must be below their corresponding
budgets. Budgets cover the research debate and admission uses estimates; they
are not an analysis-wide monetary limit. Checkpoint recovery requires matching
debate settings. **Help & shortcuts → Diagnostic tools → Policy comparison**
opens the separate preset-case experiment; it does not compare your analysis
results or configure a new analysis. Its direct URL remains `/comparison`.

Run activity includes individual agent status, finalized report counts and
per-analyst timing under **Agent status & analyst timing**. The stage tabs filter
these roles alongside their messages. Durations measure work observed during
the current server process; restored earlier stages retain unknown timing.

For OpenRouter, the research setup retrieves a public shortlist of the five
newest mainstream text models, following the TUI selection policy. **Refresh
model list** updates suggestions without replacing your entered model IDs.
Discovery uses the fixed [OpenRouter models endpoint](https://openrouter.ai/docs/api/api-reference/models/get-models),
a five-minute application cache, a ten-second network timeout and a bounded
response. Requests within two seconds share the latest result. On failure,
cached suggestions or manual IDs remain available; no credentials are sent to
model discovery. Selecting a model does not invoke it.

The backtest **Sample every** field accepts any positive whole number of
calendar days, with 7/14/30-day suggestions. It uses the existing backtest API
and retains the same grid, scoring and resume behavior.

The WebUI supports the analysis wizard, one active analysis run, SSE progress/messages/report events, cancellation, checkpoint toggle/clear, portfolio JSON input, completed-report downloads, backtest launch/results with isolated decision logs, and an announcement banner with a blocking acknowledgement when required. Analysis, scoring backtests and simulations share one active-run slot. Analysis runs use the existing CLI/core stream path; backtests call the existing `run_backtest`/`summarize` path. Backtest cancellation is not offered because the core has no cancellation hook. The server is loopback-only and keys remain server-side.

During a backtest, the results panel shows the current instrument/date, elapsed
time and actual per-date status (pending, analyzing, completed, failed or
skipped on resume). The bar counts processed instrument/date cells, including
failures and skips; it is not a time estimate. After the grid is processed the
panel continues to show settlement and summarization until the worker finishes.
Date details are paginated and follow the current date unless you select a page.
Browser refresh reattaches to the same running process; legacy saved artifacts
have no invented per-date progress, and a server restart loses active progress.

Backtests use server model defaults (`TRADINGAGENTS_LLM_PROVIDER`,
`TRADINGAGENTS_QUICK_THINK_LLM`, `TRADINGAGENTS_DEEP_THINK_LLM` and the configured
provider key). Selecting a provider in the analysis wizard does not configure a
backtest. Restart the server after changing its environment. A backtest failure
shows a safe category/message and reference ID; the matching redacted traceback
is written to the server terminal. Earlier failures without a reference ID need
to be retried after restarting with the updated code; their exception was not
retained.

The overview focuses on the latest analysis and recent records. Run counters,
analysis settings, account rules and comparison diagnostics are available in
expandable details. Stage progress, warnings, failed/pending outcomes and human
approval controls remain visible. History opens a report through one action per
row; detailed reports retain context-specific audit and download actions.

#### Simulated trading

Open **Simulated trading** in the sidebar for four connected views:

1. **Account** — explicitly create an account, inspect cash/equity/holdings,
   realized and unrealized results, fees and the core safety policy. Reset
   requires typing `RESET` and preserves the append-only trading audit.
2. **Decisions & approvals** — choose a completed research report and supply an
   explicitly labeled scenario price and aware UTC quote time. The existing
   pipeline computes quantity and applies deterministic rules. Smaller approved
   orders may simulate a fill immediately; approval-gated decisions require a
   human name, reason and explicit approve/reject action. HOLD and REVIEW remain
   no-action outcomes. There is no quantity or execution-permission override.
3. **Walk-forward** — replay user-entered daily decisions/prices offline, or
   choose research with historical quotes to invoke the configured core model
   and data providers. Each run has a separate portfolio, audit and saved daily
   cursor. Interrupted or failed runs can resume with identical parameters and
   server policy; completed runs have no resume action. Summary
   counts describe the current attempt; saved days are skipped. Approval-gated
   orders are counted but remain unexecuted in walk-forward mode. Runs do not
   offer cancellation. Date ranges are limited to 366 calendar days and the
   current weekday calendar skips weekends and days without quotes.
4. **Trading audit** — filter the interactive-account or a simulation's events,
   inspect rule/approval/fill payloads and chain hashes, paginate and download
   the displayed page. The server verifies integrity before returning records;
   this view is separate from Research audit.

To try the offline path without model or market-data calls, open Walk-forward,
choose Offline scenario, use initial cash `10000.00`, and enter a past weekday
BUY at `100` followed by a weekday SELL at `105`. The core performs sizing,
fees, risk checks and simulated fills; the account snapshot and verified audit
show the result. This is supplied scenario data, not measured market returns.
The interactive account instead uses actual completed analysis reports.

Simulation is isolated under the server-owned `results_dir/simulated_trading`
namespace. Account-generation IDs and portfolio versions prevent old pages from
operating on a reset account. Decision request receipts are idempotent;
process-owned pending approvals are not restored after restart and must be
reevaluated. Quotes/approvals must remain fresh, and changed portfolios invalidate
old evaluations. Corrupt state/audit or uncertain post-fill persistence blocks
further mutations for reconciliation; it never silently creates a new account.
An ownership lock prevents two Web processes from mutating the same simulation
workspace. The existing trading core requires POSIX file locking; on Windows
this feature reports unavailable while the other WebUI features remain usable.

All values use Decimal strings and one account unit; no currency conversion or
broker connection is implemented. Analyses, scoring backtests and simulations
share the single-active-task slot. Source and tests for the existing trading/
safety packages are unchanged; packaging now includes those existing modules.

Install dependencies once from the repository root. Use the existing `.venv`,
or create it with `python3 -m venv .venv` first. Node.js 22 LTS and npm must be
available on `PATH`.

```bash
.venv/bin/python -m pip install -e '.[dev,web]'
npm ci --prefix src/tradingagents_web/frontend
```

For everyday development, start both services with one command:

```bash
.venv/bin/python -m tradingagents_web --dev --open
```

This starts the single-worker backend at `http://127.0.0.1:8000` and Vite at
`http://127.0.0.1:5173`. Open the Vite URL for frontend hot reload. Frontend
changes update automatically; restart the command after backend changes. API
requests and SSE pass through Vite's local `/api` proxy. No frontend build is
required in this mode.

To verify the built application instead:

```bash
.venv/bin/python -m tradingagents_web --build --open
```

This builds the frontend, then starts one backend service at
`http://127.0.0.1:8000` that serves both the API and generated static files.
Build failures stop startup. Re-run this command after changing frontend code.
If the existing build is already current, start it without rebuilding:

```bash
.venv/bin/python -m tradingagents_web --open
```

With the virtual environment activated, `tradingagents-web` and
`python -m tradingagents_web` accept the same options. `--dev` and `--build`
are mutually exclusive; both require the source checkout and installed frontend
dependencies. The launcher does not install dependencies automatically.

If another application uses the default ports, select unused ones:

```bash
.venv/bin/python -m tradingagents_web --dev --port 8008 --frontend-port 5178 --open
.venv/bin/python -m tradingagents_web --build --port 8008 --open
```

The proxy follows `--port` automatically. Occupied ports produce an error;
the launcher does not stop existing listeners or silently switch ports.
`--open` waits for service readiness. Press `Ctrl+C` in the launching terminal
to stop its services; development startup failures also clean up owned child
processes. Both listeners bind to `127.0.0.1`; `localhost` is accepted as a host
alias. Existing results, memory and cache configuration stays unchanged.

Without `--dev` or `--build`, missing static assets retain the API-only behavior
and the root page reports the build instruction. Provider keys remain
server-side and are not accepted through the WebUI. Starting a service does not
run an analysis; submitting real analysis/backtest tasks uses the configured
providers normally.

Playwright E2E currently targets Chromium only:

```bash
npm run e2e --prefix src/tradingagents_web/frontend
```

The permission configuration targets OpenCode 1.18.29. Configure OpenCode's provider/model separately from TradingAgents runtime providers. Plan is read-only; use Docs to persist agreed requirements and architecture drafts, Build after plan/test approval, and Verify for independent checks. Docs can run the listed data validators. Draft requirements/design files do not block discussion, but they do not authorize dependent implementation until reviewed and approved; the schema gate must pass first.

```bash
python -m test.ci_gates schema
python -m ruff check .
python -m mypy src
python -m pip check
python -m test.ci_gates dependencies
python -m bandit -r src -ll
python -m pytest -q test/offline --disable-socket --allow-unix-socket
python -m pytest -q test/live
python -m pytest -q --disable-socket --allow-unix-socket
```

Live tests need explicit external-service/cost authorization and appropriate credentials. The network-isolated complete suite is the CI regression command; skipped credential-dependent tests do not establish successful live verification. Historical baseline failures are recorded in `docs/bug-diary.md` and remain blockers, rather than being ignored or converted into passes.

Start authentic AI-use and review records from the first requirements conversation. After explicitly identifying a session, export it with the following command, replacing the placeholders:

```bash
python -m test.ci_gates transcript --session SESSION_ID --output transcripts/STUDENT_ID-STUDENT_NAME.md
```

The exporter writes a new Markdown file containing the complete native sanitized JSON, not a reconstructed summary. Annotate real interventions and approvals afterward. It refuses to overwrite existing transcripts or write outside `transcripts/`. No sessions have been exported as part of preparation.

### CI blocking checks

The actual team repository is [1longlong/TradingAgents](https://github.com/1longlong/TradingAgents). CI checks source layout, architecture/permission boundaries, lint, full-source typing, dependency consistency/advisories, security, a fixed deterministic contract suite, complete network-isolated regression on Python 3.10–3.13, and clean installation. Requirements validation checks both JSON Schema and explicit semantic references. Changes to code, prompts, tests, or CI/developer tooling require a new AI-use entry covering the exact paths.

Human review gates use actual GitHub review records, not local approval claims. A prior `[test-plan-approved]` review binds the test/design revision before implementation. Safety changes need an accompanying ADR and a current-head `[safety-approved]` review. Governance/checker/configuration changes need current-head `[governance-approved]` review. See `docs/review-memo.md` for identity checks, history constraints, first-adoption handling, and limitations.

Runtime prompt/model changes require replay against an evaluator, fixed dataset, and thresholds already approved on the PR base. The policy belongs in `[tool.tradingagents.ci.semantic_evaluation]` in `pyproject.toml`. It is currently empty: such changes fail closed until a real evaluation design is approved. Prompt-contract tests alone are not model-quality evaluation.

Configure GitHub branch protection/rulesets to require the stable **`blocking-gate`** status, human reviews, and dismissal of stale approvals. Only PR/review events report that merge status; push/manual runs report `branch-checks`, so they cannot satisfy or overwrite a PR approval verdict. The aggregation rejects failed, cancelled, or skipped jobs. Workflow files alone do not configure remote branch protection, and no remote setting or passing hosted run is implied. Merge-queue integration is not configured. There is no deployment or automatic release workflow.

Local virtual environments, caches, build outputs, and OpenCode-generated plugin dependencies are rebuildable runtime artifacts ignored by Git. Create the development environment with the commands above when needed.

---

## CS5351 Course Project Section (Downstream Student Fork)

> The content above is the upstream (TauricResearch) product guide, preserved
> verbatim for attribution and reference. The sections below are the CS5351
> course-project governance overlay maintained by the student fork.

### Purpose

This repository is a downstream fork of the upstream `TradingAgents` framework
used as the vehicle for the **CS5351** graduate course project that extends the
framework with two deterministic, governance-driven improvements:

- **Deterministic Data Quality Gate (FR-DQG-001)** — an LLM-free gate that
  validates market evidence against five deterministic classes and fails closed
  on missing or low-quality evidence before the Bull/Bear debate opens.
- **Dynamic, evidence-aware debate termination (FR-DDT-001)** — a deterministic
  Debate Evaluator that ends the debate on evidence/model conflict staleness or
  budget exhaustion instead of always running a fixed number of rounds.

Full course-metadata and requirement/layout details live under [`docs/`](docs/).

### Branch and Deliverable Status (do not assume)

- Current working branch: `feature/data-quality-debate-control`.
- **Phase 4A (deterministic offline baseline comparison) is completed and
  human-approved with limitations** (WANG Yiwen 60536848, 2026-10-23). The base
  commit `8abea81` is already pushed to `origin/feature/data-quality-debate-control`
  (verified via `git ls-remote`). See [`docs/review-memo.md`](docs/review-memo.md).
- **Phase 4B (live-provider benchmarking) and production threshold tuning have
  NOT been performed** and remain prohibited without separate explicit human
  authorization.
- **Current status:** the 2026-11-06 maintenance fixes (guard/budget/audit,
  FR-DQG-006/FR-DDT-002/003), the 2026-11-06 documentation/requirements revision,
  and the 2026-11-10 repair batches (guard multiline containment, empty-map
  override, shared ID uniqueness, plus the documentation/traceability batch) in
  this revision form a **work-in-progress feature-branch checkpoint**, authorized
  for commit/push by the human on 2026-11-10. They are technically verified
  offline and **await explicit human review/acceptance**. Publishing this
  checkpoint is not approval to merge or a claim that all defects are fixed.
- **Next budget/participation repair is proposed, not implemented.** The measured
  runtime accounting correction (DEBT-021), truthful partial-debate reporting
  (DEBT-033), and subsequent live blocked-path verification still await approval
  of the new plan/test matrix. Do not infer completion from this checkpoint.
- **2026-11-10 human approval is PLAN + TESTS ONLY (not acceptance).** The human
  authorized the November 10 repair plan and its test cases. Final human acceptance
  remains **PENDING**; no traceability score is recorded.
- **Verification is not all-green (recorded, not hidden).** The strict-offline
  count-and-fail harness observes **4 known baseline failures** (3 date-sensitive
  `test_ohlcv_cache_freshness` + the `test_no_data_handling` vendor-reachability
  baseline) and **1 intercepted outbound socket attempt** (no connection made) from
  that baseline, so NFR-OFF-001 stays **PARTIAL/OPEN** (DEBT-002/RISK-002). No
  baseline test/CI/waiver was modified.
- **Live check (2026-11-06, authorized, NVDA / 2026-11-05, school model
  `CS5351/DeepSeek-V4-Flash`):** 18 successful model calls / 202,622 reported
  tokens; final gate **degraded**; final signal **Overweight**. A first harness
  attempt (18 calls / 178,453 tokens) failed only because the local streaming
  harness omitted `graph.ticker` before logging — a harness error, **not** a
  project bug; the corrected rerun totalled 36 calls / 381,075 reported tokens
  (retry cost not hidden). Live verification is **not** exhaustive proof; two
  **OPEN, unfixed** issues were found (see
  [`docs/architecture/risk-list.md`](docs/architecture/risk-list.md) RISK-020 /
  RISK-021 and DEBT-021 / DEBT-022).
- **Nothing here has been submitted, presented, or graded.** Student identity is
  confirmed as **WANG Yiwen**, CS5351 student ID **60536848** (see
  [`transcripts/`](transcripts/) and [`docs/debt-register.md`](docs/debt-register.md)).
  Team roster, contribution, and reflection data are **pending human input** and
  are not fabricated.

### Artifact Index

| Path | Type | Description |
| --- | --- | --- |
| [`AGENTS.md`](AGENTS.md) | Governance | Coding-agent governance rules. |
| [`architecture-blueprint.md`](architecture-blueprint.md) | Design | Master constraint/design document. |
| [`Prompt.md`](Prompt.md) | Prompt | Static startup prompt for OpenCode. |
| [`Report.md`](Report.md) | Process | Phase progress report + student reflection. |
| [`docs/req/requirements.yaml`](docs/req/requirements.yaml) | Requirements | Machine-readable PRD (validated against schema). |
| [`docs/req/req-schema.json`](docs/req/req-schema.json) | Schema | CI validation schema for requirements. |
| [`docs/architecture/adr/001-data-quality-gate.md`](docs/architecture/adr/001-data-quality-gate.md) | ADR | Deterministic Data Quality Gate decision. |
| [`docs/architecture/adr/002-dynamic-debate-termination.md`](docs/architecture/adr/002-dynamic-debate-termination.md) | ADR | Dynamic debate-termination decision. |
| [`docs/architecture/invariants.md`](docs/architecture/invariants.md) | Design | Non-negotiable system invariants. |
| [`docs/architecture/trace-matrix.md`](docs/architecture/trace-matrix.md) | Trace | Requirement → artifact/source/test/evidence map. |
| [`docs/architecture/memory-design.md`](docs/architecture/memory-design.md) | Design | Point-in-time / memory design notes. |
| [`docs/architecture/option-ledger.md`](docs/architecture/option-ledger.md) | Decisions | Alternatives considered and why. |
| [`docs/architecture/permission-model.md`](docs/architecture/permission-model.md) | Governance | Agent/permission model. |
| [`docs/architecture/evaluation-logbook.md`](docs/architecture/evaluation-logbook.md) | Evidence | Per-verification evidence log. |
| [`docs/architecture/risk-list.md`](docs/architecture/risk-list.md) | Risk | Known risks and mitigations. |
| [`docs/architecture/evaluation-table.md`](docs/architecture/evaluation-table.md) | Evidence | Test/verification summary table. |
| [`docs/architecture/runtime-policy-catalog.md`](docs/architecture/runtime-policy-catalog.md) | Policy | Runtime policy / config catalog. |
| [`docs/code-governance/structural-constraints.md`](docs/code-governance/structural-constraints.md) | Governance | Module/structural constraints. |
| [`docs/code-governance/verification-constraints.md`](docs/code-governance/verification-constraints.md) | Governance | How code must be verified. |
| [`docs/code-governance/mcp-tool-manifest.md`](docs/code-governance/mcp-tool-manifest.md) | Governance | MCP tool manifest / usage policy. |
| [`docs/ai-use-log.yaml`](docs/ai-use-log.yaml) | Governance | AI-tool use log (deterministic YAML upstream). |
| [`docs/review-memo.md`](docs/review-memo.md) | Governance | Human review memo across phases. |
| [`docs/debt-register.md`](docs/debt-register.md) | Debt | Known technical debt + uncertainty. |
| [`docs/bug-diary.md`](docs/bug-diary.md) | Evidence | Detected defects & fixes. |
| [`.opencode/permissions.jsonc`](.opencode/permissions.jsonc) | Governance | OpenCode permission config. |
| [`.opencode/rules.md`](.opencode/rules.md) | Governance | OpenCode agent rules. |
| [`.agent/rules.md`](.agent/rules.md) | Governance | Shared coding-agent rules. |
| [`prompts/prompt_v1.0.yaml`](prompts/prompt_v1.0.yaml) | Prompt | v1.0 read-only analysis/frozen requirements (historical). |
| [`prompts/prompt_v1.1.yaml`](prompts/prompt_v1.1.yaml) | Prompt | v1.1 implementation + verification + governance (prior authoritative; historical). |
| [`prompts/prompt_v1.2.yaml`](prompts/prompt_v1.2.yaml) | Prompt | v1.2 implementation + verification + governance (prior authoritative; historical). |
| [`prompts/prompt_v1.3.yaml`](prompts/prompt_v1.3.yaml) | Prompt | v1.3 plan-first + STOP + implementation + verification (current authoritative). |
| [`docs/architecture/adr/004-governance-context-design.proposed.md`](docs/architecture/adr/004-governance-context-design.proposed.md) | ADR | PROPOSED context-assembly/compaction design (not implemented). |
| [`docs/code-governance/ci-gate-matrix.md`](docs/code-governance/ci-gate-matrix.md) | Governance | CI gate matrix + PR review template + 8 debt categories (document only). |
| [`docs/code-governance/agent-permissions-proposal.yaml`](docs/code-governance/agent-permissions-proposal.yaml) | Governance | Role×path deny-by-default whitelist PROPOSAL (not active). |
| [`docs/code-governance/human-rules-proposal.md`](docs/code-governance/human-rules-proposal.md) | Governance | Proposed HUMAN-ONLY `.opencode/rules.md` text (awaiting manual adoption). |
| [`transcripts/60536848-WANG-Yiwen.md`](transcripts/60536848-WANG-Yiwen.md) | Transcript | Annotated human-supervision record. |
| [`src/README.md`](src/README.md) | Mapping | Documents the canonical source packages under `src/`. |
| [`test/offline/README.md`](test/offline/README.md) | Mapping | Indexes deterministic tests under `test/offline/`. |
| [`test/live/README.md`](test/live/README.md) | Mapping | Documents `integration`-marker live tests (opt-in). |

### Source and test layout after integration

The source packages are under `src/`: `src/tradingagents/`, `src/cli/`, and
`src/tradingagents_web/`. Deterministic tests are under `test/offline/`;
external-service tests are under `test/live/`. Imports and installed commands
keep their existing names. The release core is integrated into these existing
trees, with no duplicate root-level implementation.
