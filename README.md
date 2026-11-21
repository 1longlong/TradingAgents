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
- [2026-09] **TradingAgents v0.5.0** released with point-in-time integrity across every dated path, SEC EDGAR fundamentals served as filed, backtesting over a ticker and date grid, portfolio-aware runs, and current model lineups across every provider. See [CHANGELOG.md](CHANGELOG.md) for the full list.
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
python -m cli.main     # alternative: run directly from source
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

To use TradingAgents inside your code, you can import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision. You can run `main.py`, here's also a quick example:

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

See `tradingagents/default_config.py` for all configuration options.

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

The decision log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return (raw, and alpha against the instrument's regional benchmark), generates a one-paragraph reflection, and injects the most recent same-ticker decisions plus recent cross-ticker lessons into the Portfolio Manager prompt, so each analysis carries forward what worked and what didn't.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. The run view says whether it resumed a saved run or started fresh. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

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

Contributions are welcome: bug fixes, documentation, and feature ideas; past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

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

---

## CS5351 Course Project Section (Downstream Student Fork)

> The content above is the upstream (Tauric Research) product guide, preserved
> verbatim for attribution and reference. The sections below are the CS5351
> course-project overlay maintained by the student fork.

### Purpose and the three workstreams

This repository is the CS5351 downstream fork of TradingAgents. The integrated
tree contains three distinct lines of work with separate provenance:

1. **Release team work** — deterministic Data Quality Gate, dynamic debate
   termination, evidence capture, durable usage accounting, blocked/degraded
   safeguards, the Phase 4A offline comparison, and the independent simulated
   trading subsystem.
2. **WangTianQi's personal feature** — token observability and attribution,
   Single-Pass structured finalisation, the batch-macro ablation, Finnhub-only
   configured news, per-run experiment memory isolation, and the frozen V2/V3
   CAND-01 measurement apparatus.
3. **Shared integration** — the merged architecture, canonical requirement IDs,
   ADR/invariant numbering, and the documentation/governance consolidation in
   this worktree.

Nothing here is financial, investment, or trading advice, and no result in this
repository is a claim of alpha. The simulated-trading subsystem is a simulation;
it has no real broker path.

### Current integration status (2026-11-21)

- This worktree is `integrate/token-into-release-20261121` at base `24adf97`,
  **merging** the personal feature `57b93df` (personal final code `50b2ca3`).
- **The Git merge is in progress and has not been completed, committed, or
  pushed.** Do not read this tree as a published release.
- D1–D9 documentation integration is staged in this worktree: the merged
  requirements/ADR/invariant/governance set is present. The protected
  `.opencode/rules.md`, `.opencode/permissions.jsonc` and the CI workflow remain
  unresolved and require explicit human handling.
- The remote CI has **not** been run for the integrated tree, and the full
  offline suite has **not** been run while unrelated documentation conflicts
  remain. See [`Report.md`](Report.md) and
  [`docs/architecture/risk-list.md`](docs/architecture/risk-list.md).

### Historical Release status (preserved, time-scoped)

These statements are historical and are **not** the current integration state:

- Phase 4A (deterministic offline baseline comparison) was completed and
  human-approved with limitations (WANG Yiwen 60536848, 2026-10-23; see
  [`docs/review-memo.md`](docs/review-memo.md)).
- The 2026-11-06 maintenance fixes and the 2026-11-10 repair batches were
  authorized as plan/test-only work and remained pending final human acceptance
  at that time.
- Phase 4B (live-provider benchmarking) and production threshold tuning were
  prohibited by default. The personal V2/V3 paid campaigns later ran under dated,
  run-specific authorizations recorded in [`docs/ai-use-log.yaml`](docs/ai-use-log.yaml);
  those authorizations do not authorize further spend.
- A 2026-11-06 authorized live check (NVDA / 2026-11-05) ended **degraded**, not
  blocked; it is not exhaustive live proof.
- Nothing in this repository has been submitted, presented, or graded.

### Workstream A — Release team

- **Deterministic Data Quality Gate (`FR-DQG-001`)** — an LLM-free gate that
  validates market evidence against five deterministic classes and fails closed
  on missing or low-quality evidence before the Bull/Bear debate.
- **Dynamic, evidence-aware debate termination (`FR-DDT-001`)** — a deterministic
  Debate Evaluator that ends the debate on evidence/model-conflict staleness or
  budget exhaustion instead of always running fixed rounds.
- **Evidence capture and audit (`FR-DQG-004/005`, ADR-008)** — structured
  optional-evidence ingestion and deterministic report artifacts
  (`gate_summary.md`, `evidence_manifest.json`, `debate_trace.json`,
  `run_summary.json`).
- **Durable usage settlement (`FR-DDT-003`, ADR-009)** — a run-scoped SQLite
  reservation/settlement ledger for debate budget safety.
- **Blocked/degraded safeguards (`FR-DQG-006`, `NFR-FC-001`, ADR-011)** — the
  output guard pins blocked runs to Hold, and a degraded run's confidence is
  capped deterministically.
- **Independent simulated trading subsystem (`FR-TRD-*`, `INV-TRD-*`)** — the
  approved `src/trading/` + `src/safety/` subsystem; simulation only.
- **Phase 4A comparison (`NFR-CMP-*`)** — offline scripted-fixture comparison,
  approved with limitations; not live-provider measurement.

### Workstream B — WangTianQi's personal token-observability feature

- **Provider usage observability and attribution (`FR-OBS-001/003/004`,
  `FR-ANL-004`; ADR-013)** — a per-run collector with `agent` / `system` / `none`
  scopes. Missing usage is `null`, never zero; run totals close over agent,
  system and unattributed buckets. An unattributed call voids a *measured
  experiment sample* at the harness boundary; the product graph does not abort.
- **Single-Pass structured finalisation (`FR-ANL-005`; ADR-014, ADR-018)** — the
  analyst can emit its typed report on the terminal schema call instead of
  paying a second prose rewrite. `single_pass_finalization_enabled` defaults to
  `False` and requires structured output; fallbacks never present prose as a
  typed object, never replay a dangling tool call, and never leak protocol markup.
- **Batch-macro ablation (`FR-ANL-006`; ADR-015)** — `get_macro_indicators_batch`
  behind `batch_macro_enabled`; the switch removes the tool from both the analyst
  and the news `ToolNode`. Kept as an ablation, not a demonstrated optimisation.
- **Finnhub-only configured news (`FR-ANL-008`; ADR-016)** — company news routes
  only to Finnhub; global news is `CONFIG_DISABLED`; a Finnhub outage is never
  rescued by GDELT. The GDELT adapter remains in the tree but is unreachable from
  the configured route.
- **Per-run experiment memory isolation (`FR-ANL-009`; ADR-017)** — registered
  runs copy one immutable snapshot, hash it, and refuse a missing/changed copy
  before spending. Harness-only: generic runs still use the shared host log.
- **Frozen V2/V3 measurements and audits (`FR-HAR-*`, `FR-CAM-001`,
  `NFR-VER-*`)** — pre-registered 16-run specs, config hashes, freeze
  records/manifests, pre-spend gates, and three independent (AI-authored) audits.
  See [`token_benchmarks/`](token_benchmarks/) and
  [`docs/architecture/evaluation-logbook.md`](docs/architecture/evaluation-logbook.md).

### Workstream C — shared integrated architecture

**Accounting scopes are distinct and must not be conflated:**

| Scope | Enforcer | What it measures |
| --- | --- | --- |
| Debate budget | `tradingagents/debate/budget.py` | debate optional calls vs caps + summary reserve |
| Durable ledger | `tradingagents/debate/usage_ledger.py` | per-run reservation/settlement across resume |
| Paid-run spend contract | `tradingagents/budget_guard.py` + `scripts/token_benchmark.py` | known spend vs an explicit cap |
| Per-agent telemetry | `tradingagents/observability.py` | run-wide calls/tokens by agent/system/none |
| Report provenance | `tradingagents/report_artifacts.py` | debate-scoped measured/estimated labels |

`run_summary.json` reports the **debate-scoped** view (`total_run_calls` and
`tool_calls` are `null`); the telemetry artifact is the **run-wide** source. They
are two artifacts with two scopes, not two copies of one number.

**Canonical identifiers (integrated):**

- 52 requirements: 32 Release IDs plus 20 retrospective IDs
  (`FR-ANL-*`, `FR-OBS-*`, `FR-HAR-*`, `FR-CAM-*`, `NFR-VER-*`) — see
  [`docs/req/requirements.yaml`](docs/req/requirements.yaml) and
  [`docs/req/req-schema.json`](docs/req/req-schema.json).
- ADR-001–ADR-019: ADR-012 is the PR #5 error-handling/usage integration; ADR-013 observability;
  ADR-014 Single-Pass; ADR-015 batch macro; ADR-016 Finnhub-only news; ADR-017
  memory isolation; ADR-018 structured fallback; ADR-019 simulated trading.
- INV-1–INV-27 plus INV-TRD-001–003 — see
  [`docs/architecture/invariants.md`](docs/architecture/invariants.md).
- Risks `RISK-036`–`RISK-049` and debt `DEBT-042`–`DEBT-055` are the renumbered
  personal records; Release `RISK-001`–`RISK-035` and `DEBT-001`–`DEBT-041` keep
  their meanings.

**Source/test layout:** `tradingagents/` and `cli/` are the product trees;
`tests/` is the canonical suite; `src/trading/` and `src/safety/` are the approved
additive subsystem; `test/offline/` and `test/live/` are pointer READMEs. See
[`src/README.md`](src/README.md), [`test/offline/README.md`](test/offline/README.md)
and [`test/live/README.md`](test/live/README.md).

**Prompt artifacts:** `prompts/prompt_v1.3.yaml` is the current Coding-Agent
startup prompt. `prompts/prompt_v1.0.yaml`/`v1.1.yaml` are the historical CS5351
startup prompts. The Market Analyst runtime-prompt snapshots that the personal
line also called v1.0/v1.1 are archived separately under
[`prompts/archive/`](prompts/archive/README.md); they are not startup prompts and
not runtime configuration.

### Results and limitations (do not overstate)

- V2: 7 attempts / 5 valid / 1 environment-failed / 1 invalid / 1,463,791 tokens.
- V3: 18 attempts / 16 Run IDs / 15 valid / 1 environment-failed / 2 invalid /
  3,067,669 tokens.
- Combined: 25 attempts / 20 valid / 4,531,460 tokens (4,112,224 valid; 419,236
  failed).
- Single-Pass: −19,589 tokens/run (−8.96 %) on the balanced three-block mean,
  negative in all three blocks — **exploratory**, n=1 per cell, one model, one
  trade date. Batch macro was not robust (about −695/run excluding the
  environment-degraded R01).
- The recorded suite at `50b2ca3` is 2,227 passed / 4 known failed / 2 skipped /
  319 subtests; a `.env`-free submission-branch run reports 2,233 / 0 / 2 / 319.
  The merged-tree full suite is **NOT_RUN**. No paid rerun was executed after the
  final remediation, and there is no ground truth or P&L evidence.

### Artifact index

| Path | Type | Description |
| --- | --- | --- |
| [`AGENTS.md`](AGENTS.md) | Governance | Coding-agent governance rules and honest enforcement status. |
| [`architecture-blueprint.md`](architecture-blueprint.md) | Design | Master constraint/design document (Release base + token-observability sections). |
| [`Prompt.md`](Prompt.md) | Prompt | Static startup-prompt anchor and prompt-lineage clarification. |
| [`Report.md`](Report.md) | Process | Integrated team process report + personal reflection sections. |
| [`docs/req/requirements.yaml`](docs/req/requirements.yaml) | Requirements | Machine-readable PRD + 52-requirement registry. |
| [`docs/req/req-schema.json`](docs/req/req-schema.json) | Schema | Draft 2020-12 validation schema. |
| [`docs/architecture/adr/019-simulated-trading-system.md`](docs/architecture/adr/019-simulated-trading-system.md) | ADR | Simulated trading system. |
| [`docs/architecture/adr/013-provider-usage-observability.md`](docs/architecture/adr/013-provider-usage-observability.md) | ADR | Provider-usage observability and attribution. |
| [`docs/architecture/adr/014-single-pass-finalization.md`](docs/architecture/adr/014-single-pass-finalization.md) | ADR | Single-Pass structured finalisation. |
| [`docs/architecture/adr/015-batch-macro-switch.md`](docs/architecture/adr/015-batch-macro-switch.md) | ADR | Batch-macro ablation switch. |
| [`docs/architecture/adr/016-finnhub-only-news.md`](docs/architecture/adr/016-finnhub-only-news.md) | ADR | Finnhub-only configured news. |
| [`docs/architecture/adr/017-per-run-memory-isolation.md`](docs/architecture/adr/017-per-run-memory-isolation.md) | ADR | Per-run experiment memory isolation. |
| [`docs/architecture/adr/018-structured-fallback-safety.md`](docs/architecture/adr/018-structured-fallback-safety.md) | ADR | Structured-fallback safety. |
| [`docs/architecture/invariants.md`](docs/architecture/invariants.md) | Design | INV-1–INV-27 + INV-TRD invariants. |
| [`docs/architecture/trace-matrix.md`](docs/architecture/trace-matrix.md) | Trace | Requirement → artifact/source/test/evidence map + reconciliation. |
| [`docs/architecture/memory-design.md`](docs/architecture/memory-design.md) | Design | Product memory + experiment isolation. |
| [`docs/architecture/option-ledger.md`](docs/architecture/option-ledger.md) | Decisions | Release options + personal OPT-01–OPT-10. |
| [`docs/architecture/permission-model.md`](docs/architecture/permission-model.md) | Governance | Roles, matrix, honest enforcement status, credential handling. |
| [`docs/architecture/risk-list.md`](docs/architecture/risk-list.md) | Risk | Release RISK-001–035 + personal RISK-036–049. |
| [`docs/architecture/runtime-policy-catalog.md`](docs/architecture/runtime-policy-catalog.md) | Policy | Release policies + personal RP-01–RP-08. |
| [`docs/architecture/evaluation-logbook.md`](docs/architecture/evaluation-logbook.md) | Evidence | Release log + personal LOG-001–LOG-012. |
| [`docs/architecture/evaluation-table.md`](docs/architecture/evaluation-table.md) | Evidence | Release table + personal Part III. |
| [`docs/code-governance/structural-constraints.md`](docs/code-governance/structural-constraints.md) | Governance | Module/structural constraints. |
| [`docs/code-governance/verification-constraints.md`](docs/code-governance/verification-constraints.md) | Governance | Verification rules and tiers. |
| [`docs/code-governance/mcp-tool-manifest.md`](docs/code-governance/mcp-tool-manifest.md) | Governance | MCP/tool policy (no MCP server configured). |
| [`docs/ai-use-log.yaml`](docs/ai-use-log.yaml) | Governance | 105 integrated AI-use records. |
| [`docs/ai-use-session-audit.md`](docs/ai-use-session-audit.md) | Governance | Session audit, ID mappings, tool-attribution evidence. |
| [`docs/review-memo.md`](docs/review-memo.md) | Governance | Release reviews + personal REC-01–REC-10 (human-pending). |
| [`docs/debt-register.md`](docs/debt-register.md) | Debt | Release DEBT-001–041 + personal DEBT-042–055. |
| [`docs/bug-diary.md`](docs/bug-diary.md) | Evidence | Release defects + personal BUG-001–BUG-018. |
| [`prompts/prompt_v1.3.yaml`](prompts/prompt_v1.3.yaml) | Prompt | Current authoritative Coding-Agent startup prompt. |
| [`prompts/archive/`](prompts/archive/README.md) | Evidence | Archived historical Market Analyst prompt snapshots (not runtime config). |
| [`transcripts/60726054-WangTianQi.md`](transcripts/60726054-WangTianQi.md) | Transcript | WangTianQi AI-prepared draft; personal annotations and signature **pending**. |
| [`transcripts/60536848-WANG-Yiwen.md`](transcripts/60536848-WANG-Yiwen.md) | Transcript | Teammate's preserved human-supervision record (do not edit). |

### Deliverable-to-repo mapping (this fork)

The authoritative project slide lists `src/`, `test/offline/`, and `test/live/`.
This repository uses `tradingagents/` and `cli/` as the product source trees,
`src/trading/` and `src/safety/` for the approved simulated-trading subsystem,
and `tests/` for all tests. The three README pointers above document that mapping
explicitly; **no** product code is duplicated or relocated.

### Transcripts and human review

- [`transcripts/60726054-WangTianQi.md`](transcripts/60726054-WangTianQi.md) is an
  **AI-prepared, unsigned draft**; the personal decisions, reflections and
  attestation remain `HUMAN_CONFIRMATION_REQUIRED`.
- [`transcripts/60536848-WANG-Yiwen.md`](transcripts/60536848-WANG-Yiwen.md) is the
  teammate's preserved transcript and is not part of WangTianQi's deliverable.
- Every personal review, ADR, risk and debt item remains
  `PENDING_HUMAN_CONFIRMATION`; no human sign-off is claimed.

### Attribution and license

TradingAgents was created by [Tauric Research](https://github.com/TauricResearch)
and is distributed under the Apache License 2.0; see [`LICENSE`](LICENSE). The
upstream product documentation above is preserved for attribution. The CS5351
overlay adds the Release team's improvements, WangTianQi's token-observability
feature, and the integrated governance/verification set. AI-assisted work is
recorded in [`docs/ai-use-log.yaml`](docs/ai-use-log.yaml); commit-author
identities that the tree cannot establish remain unresolved rather than assigned.
