# TradingAgents Research Workspace

TradingAgents is a local investment-research application combining specialist analysts, bullish and bearish debate, a trading proposal and risk review. This project extends the existing TradingAgents system with a browser workspace, deterministic evidence controls, configurable debate rules, usage observability, fault tolerance and simulated trading. The original CLI and Python interfaces remain available.

The research core uses LangGraph to coordinate model roles and data tools. Evidence validation and the Data Quality Gate determine whether inputs are usable; deterministic policies control debate termination, resource budgets and final-output restrictions. Language models provide analysis, while code enforces acceptance and safety boundaries. Reports, checkpoints, decision memory and usage records support inspection and recovery.

A React/TypeScript frontend communicates with a FastAPI backend. Server-Sent Events (SSE) carry execution activity and report updates, and runtime adapters reuse the research core. A separate simulated-trading subsystem manages portfolios, approvals and audit records through a deterministic safety gateway. The WebUI is designed for one local user and binds to loopback addresses only. Research outputs are advisory, and simulated orders have no real broker connection.

**Project repository:** [1longlong/TradingAgents](https://github.com/1longlong/TradingAgents).

## Main capabilities

| Capability | What it provides |
| --- | --- |
| Research workspace | Analysis setup, provider/model selection, portfolio context, English/Chinese interface labels and report-language selection |
| Execution visibility | Agent messages, tool activity, stage tabs, intermediate reports, cancellation requests and browser reconnection |
| Evidence and reports | Research audit, evidence-quality decisions, report history and downloads |
| Debate controls | Dynamic or fixed-round behavior, separate debate/risk round caps and research-debate resource budgets |
| Analysis backtesting | Serial ticker/date evaluation, per-date progress, scoring and resumable saved runs |
| Simulated trading | Account state, deterministic decision evaluation, human approvals, walk-forward simulation and verified trading audit |
| Usage and comparison | Model-usage attribution and a separate comparison of policies on predefined offline cases |

Policy comparison is a diagnostic experiment on scripted scenarios. It does not compare the investment performance of completed analyses. Token-optimization experiments are recorded separately; lower token use alone does not establish better research quality or returns.

## Quick start

### 1. Install the development environment

The package requires Python 3.10 or later. Use Python 3.12 when creating the environment below. Building the WebUI also requires Node.js 22 and npm. Shell examples use bash/zsh syntax.

```bash
git clone https://github.com/1longlong/TradingAgents.git
cd TradingAgents
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,web]'
npm ci --prefix src/tradingagents_web/frontend
```

On Windows PowerShell, activate the environment with `.\.venv\Scripts\Activate.ps1`. The simulated-trading subsystem requires POSIX file locking and is unavailable on Windows; other WebUI features remain usable.

### 2. Configure providers

Copy the environment template once, then edit the local copy:

```bash
cp .env.example .env
```

Set the key for the selected provider and both model IDs. For example, a DeepSeek configuration has this shape; replace the placeholders with your own key and model IDs supported by your account:

```dotenv
DEEPSEEK_API_KEY=your-api-key
TRADINGAGENTS_LLM_PROVIDER=deepseek
TRADINGAGENTS_QUICK_THINK_LLM=your-quick-model-id
TRADINGAGENTS_DEEP_THINK_LLM=your-deep-model-id
```

The [environment template](.env.example) lists other providers and optional data-service credentials. Configure credentials on the server; the browser never accepts or displays API keys. Keep local environment files out of version control.

Yahoo Finance is the default price/indicator source and does not require an API key. Finnhub-backed company news requires `FINNHUB_API_KEY`, and FRED macro data requires `FRED_API_KEY`. Available evidence therefore depends on the analysts and vendors selected. Vendor chains are explicit: retries do not silently switch to an unconfigured service or fabricate replacement data. See [default configuration](src/tradingagents/default_config.py) for vendor chains, retry limits and optional settings.

### 3. Start the WebUI

For frontend development with hot reload:

```bash
python -m tradingagents_web --dev --open
```

This starts the backend at `http://127.0.0.1:8000` and the frontend at `http://127.0.0.1:5173`. Use the frontend URL; its proxy handles API and SSE traffic. Frontend changes reload automatically; restart the command after backend or environment changes.

To build and run the application through one server:

```bash
python -m tradingagents_web --build --open
```

Open `http://127.0.0.1:8000`. The command builds the frontend before serving it. When the existing build is current, use `python -m tradingagents_web --open` to start without rebuilding. The installed `tradingagents-web` command accepts the same options.

Press `Ctrl+C` in the launching terminal to stop the services. For alternative ports:

```bash
python -m tradingagents_web --dev --port 8008 --frontend-port 5178 --open
```

The proxy follows the backend port. Startup reports occupied ports rather than stopping other applications. The launcher expects dependencies to be installed already. Starting the server does not start an analysis; submitting research or provider-backed backtests uses the configured external services.

### 4. Use the workspace

Start with **New analysis**, choose an instrument and analysis date, select analysts and review the model/debate settings. Follow activity through the stage tabs, then open the completed report or revisit it through history. Optional portfolio input distinguishes an explicitly empty portfolio from no portfolio context.

Server provider/model values are **defaults for interactive analysis** and can be changed for an individual run. **Analysis backtests use the server defaults**, not the last selections in the analysis wizard. Restart the server after changing its environment. Debate budgets govern the research debate, not the total monetary cost of every stage.

The application shares one active-task slot across analysis, backtesting and simulation. Backtests show processed ticker/date cells and settlement activity; progress is not an estimate of remaining time. Browser reconnection attaches to the current server process. Cancellation of analysis is cooperative and may wait for an in-flight provider call; backtests and walk-forward runs do not offer cancellation.

For a provider-free simulation, open **Simulated trading → Walk-forward → Offline scenario** and enter daily scenario decisions and prices. The existing core applies sizing, fees and safety rules. Interactive account decisions instead use completed research reports. Human approval remains required where the safety policy demands it, and account reset requires confirmation. Scenario results are simulated outcomes, not measured market returns.

## CLI and Python access

The terminal workflow remains available from the same environment:

```bash
tradingagents
tradingagents --checkpoint
tradingagents --portfolio portfolio.json
tradingagents backtest NVDA,AAPL --start 2024-01-08 --end 2024-02-08 --every 7
```

Provide an existing portfolio JSON file when using `--portfolio`. Environment overrides can skip the corresponding CLI prompts; the WebUI's editable-default behavior is a separate interface contract. Use `tradingagents --help` for command options.

Python callers can use the same core after configuring their provider:

```python
from copy import deepcopy
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = deepcopy(DEFAULT_CONFIG)
graph = TradingAgentsGraph(config=config)
state, decision = graph.propagate("NVDA", "2024-01-08")
```

Results, cache/checkpoints and decision memory default to `~/.tradingagents/logs`, `~/.tradingagents/cache` and `~/.tradingagents/memory/trading_memory.md`. Override them with `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR` and `TRADINGAGENTS_MEMORY_LOG_PATH`. Analysis backtests and simulations use their own state namespaces. Checkpoint resume requires compatible run settings and portfolio identity.

## Project organization

```text
TradingAgents/
├── README.md                         # Introduction, setup and verification
├── AGENTS.md                         # OpenCode governance entry point
├── Prompt.md                         # Static development startup instruction
├── architecture-blueprint.md          # System architecture and ownership
├── Report.md                         # Project report and individual reflections
├── docs/
│   ├── req/
│   │   ├── requirements.yaml         # Requirements and acceptance criteria
│   │   └── req-schema.json           # Requirements schema
│   ├── architecture/                 # ADRs, invariants, traceability and evaluation
│   ├── code-governance/
│   │   ├── structural-constraints.md
│   │   ├── verification-constraints.md
│   │   └── mcp-tool-manifest.md
│   ├── ai-use-log.yaml
│   ├── review-memo.md
│   ├── debt-register.md
│   └── bug-diary.md
├── .opencode/                        # Role permissions and standing rules
├── .agent/rules.md                   # Shared development constraints
├── .github/workflows/ci.yml          # CI jobs and aggregate blocking status
├── prompts/                          # Versioned prompt artifacts
├── src/
│   ├── tradingagents/                # Research core, data, models and reporting
│   ├── cli/                          # Terminal interface
│   ├── tradingagents_web/            # HTTP API, runtime adapters and frontend
│   ├── trading/                      # Simulated account and execution components
│   └── safety/                       # Deterministic execution gateway
├── test/
│   ├── offline/                      # Deterministic tests
│   ├── live/                         # External-service tests
│   └── ci_gates.py                   # Repository and approval checks
├── transcripts/                      # Annotated development-session records
├── scripts/                          # Validation and measurement utilities
├── token_benchmarks/                  # Preserved experiment specifications/results
└── assets/                           # Supporting project images
```

The research core is independent of HTTP and browser presentation. Web adapters reuse core contracts rather than implementing another analysis engine. Simulated execution is isolated behind the safety gateway. These boundaries and their acceptance checks are described in the [architecture blueprint](architecture-blueprint.md), [requirements](docs/req/requirements.yaml) and [trace matrix](docs/architecture/trace-matrix.md).

Architecture decisions, invariants, state ownership, risks and evaluation records are maintained under [architecture documentation](docs/architecture/). Review, defect, debt and OpenCode-use records track the development process. Session records preserve their original evidence; summaries and scripted fixtures do not replace complete sessions or real model observations.

## Verification

Run commands from the repository root with the virtual environment active and the `dev` extra installed. Use an isolated test environment without provider credentials for offline verification; dotenv loading is disabled in the commands below.

### Offline tests

```bash
PYTHON_DOTENV_DISABLED=1 python -m pytest -q test/offline --disable-socket --allow-unix-socket
```

These tests use fixtures and temporary state. Python network sockets are blocked; the execution host remains responsible for broader process/network isolation.

### Live tests

After explicit approval of the provider, run and cost limit, supply the required credentials in the test environment:

```bash
python -m pytest -q test/live
```

The simulated-trading live smoke test additionally requires opt-in:

```bash
RUN_LIVE_TRADING_TESTS=1 python -m pytest -q test/live/trading -s
```

Live tests may call real model/data services and incur costs, while trading execution remains simulated. Review the selected fixtures and network/proxy configuration before running them. Missing credentials, optional dependencies or opt-in flags can cause skips; skips are not successful live verification.

### Full Python suite

Use the CI-equivalent network-isolated regression command:

```bash
PYTHON_DOTENV_DISABLED=1 python -m pytest -q --disable-socket --allow-unix-socket
```

It collects the full Python suite, including live-test modules, while blocking Python network calls. Keep provider credentials unset. For a separately authorized full run with real external-service access, use `python -m pytest -q` in the prepared live-test environment; explicit opt-in requirements still apply.

### Frontend and repository checks

```bash
npm run typecheck --prefix src/tradingagents_web/frontend
npm run lint --prefix src/tradingagents_web/frontend
npm run test --prefix src/tradingagents_web/frontend
npm run e2e --prefix src/tradingagents_web/frontend
python -m test.ci_gates schema
python -m test.ci_gates structure
python -m test.ci_gates permissions
python -m ruff check .
python -m mypy src
python -m pip check
```

The browser suite uses Chromium; run `npx playwright install chromium` from `src/tradingagents_web/frontend` once before running it. Dependency advisory checks use `python -m test.ci_gates dependencies` and source security checks use `python -m bandit -r src -ll`. Advisory checks require network access. Consult the [verification constraints](docs/code-governance/verification-constraints.md) for scope, review requirements and result reporting, and the [evaluation logbook](docs/architecture/evaluation-logbook.md) for actual recorded runs.

## CI blocking-gate design

The [GitHub workflow](.github/workflows/ci.yml) combines six required gate categories:

| Gate | What blocks a change |
| --- | --- |
| Prior test approval | Missing, late, revoked or unauthorized human approval of the relevant test/design revision before implementation |
| Static analysis and structure | Lint/type/dependency/security failures, invalid module or permission boundaries, frontend failures or clean-install failures |
| Requirements schema | Invalid schema, identifiers, references or acceptance contracts |
| Semantic evaluation | Required prompt/model evaluation missing authentic candidate-bound observations, or failing its fixed-set thresholds |
| Regression | Failure of previous and current suites, including the complete isolated Python regression |
| OpenCode-use logging | Missing meaningful records covering the changed implementation, test, prompt or tooling paths |

The semantic criteria are constrained task accuracy **1.0**, specified factual fidelity **1.0** and output-safety escapes **0** on the fixed evaluation set. These thresholds do not measure investment returns. Synthetic evaluator fixtures are separate from genuine provider observations.

Prior-test approval uses an allowlisted human's submitted GitHub **Comment review**, bound to the exact test/design commit. It is distinct from both an ordinary conversation comment and final merge approval. The protected base owns the checker and reviewer policy; candidates cannot authorize themselves. Detailed review syntax and rollout rules are in [ADR-029](docs/architecture/adr/029-test-plan-approval.md), with semantic evaluation specified in [ADR-030](docs/architecture/adr/030-semantic-evaluation.md).

The aggregate PR status is **`blocking-gate`**; push/manual runs report **`branch-checks`**. Failed, cancelled or skipped prerequisite jobs block the aggregate result. Branch protection must require the PR status and independent human review; a workflow file alone does not configure those repository settings. Initial gate installation and later governed changes require separate review, and hosted enforcement depends on the policy/checker being installed on the protected base. CI provides verification, not automated deployment or release.

## Development with OpenCode

Start with [AGENTS.md](AGENTS.md) and [Prompt.md](Prompt.md). Use Plan to inspect and propose, Docs to maintain agreed drafts, Build for approved implementation and Verify for assessment. Approval of the plan and test strategy precedes product implementation. Architecture or safety-boundary changes require corresponding design and human review.

With the virtual environment active, launch OpenCode from the project root:

```bash
task_root="$(pwd -P)"
TRADINGAGENTS_PERMISSION_ROOT="${task_root#/}" OPENCODE_CONFIG="$task_root/.opencode/permissions.jsonc" opencode --agent plan
```

The permission configuration was verified against OpenCode 1.18.29. Its native read/edit resources omit the initial slash, so the canonical-root binding above is required. It scopes the existing permissions rather than broadening them; keep automatic approval disabled. OpenCode's own model/provider configuration is separate from TradingAgents runtime configuration. See the [permission model](docs/architecture/permission-model.md) and [native compatibility decision](docs/architecture/adr/031-native-permission-paths.md).

Keep requirements, architecture, tests and verification evidence aligned when behavior changes. Record actual assistance and human decisions without reconstructing missing history. Preserve frozen experiment specifications and original observations. Complete session exports use the identified session and a new destination:

```bash
python -m test.ci_gates transcript --session SESSION_ID --output transcripts/STUDENT_ID-STUDENT_NAME.md
```

The exporter retains complete sanitized native JSON and refuses overwrites. Add genuine intervention annotations separately. Detailed rules remain in the governance documents rather than being duplicated here.

## Troubleshooting and scope

- **Provider errors:** check the selected provider, valid model IDs and its server-side key. Analysis settings do not change backtest defaults. Restart after environment changes.
- **Yahoo throttling:** requests may still fail after bounded retries. Wait before retrying or explicitly configure another supported vendor; a model API key does not change Yahoo's rate limits.
- **Long runs:** inspect stage activity or per-date backtest progress. Closing the browser does not cancel the server task, and server restart loses active in-memory progress.
- **Missing browser page:** install frontend dependencies and run with `--build` or `--dev`. Starting without a build can leave an API-only server.

Saved reports and benchmark results are research artifacts. Model output varies, external evidence may be unavailable, and automated checks establish only their specified scope. The project does not implement real broker execution, unattended live trading or multi-user hosting.

## Acknowledgements and license

This project extends [TradingAgents by Tauric Research](https://github.com/TauricResearch/TradingAgents), using TradingAgents v0.5.0 as its foundation. The original work is described in [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138). Team extensions and supervised OpenCode development are described in the [project report](Report.md).

Distributed under the [Apache License 2.0](LICENSE).
