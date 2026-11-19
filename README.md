# TradingAgents — CS5351 course submission

This repository is the CS5351 final-submission tree of **TradingAgents**, a
multi-agent LLM framework for equity analysis. Upstream TradingAgents (Tauric
Research, Apache-2.0) models a trading firm as a team of specialised agents. This
fork keeps that architecture and adds a measured, auditable observability and
experiment layer for the course project.

> Research and coursework only. Nothing here is financial, investment, or trading
> advice, and no result in this repository is a claim of alpha.

## What TradingAgents is

For one ticker and one point-in-time trade date, the graph runs:

1. **Analysts** — market, news, and fundamentals agents gather evidence and write
   reports.
2. **Researchers** — a bull and a bear researcher debate the evidence.
3. **Research manager** — turns the debate into an investment plan.
4. **Trader** — proposes a sized transaction from the analysts' and researchers'
   reports.
5. **Risk management** — aggressive, neutral, and conservative debators challenge
   the proposal.
6. **Portfolio manager** — emits the final decision, rating, and rationale.

The graph is built with LangGraph, the CLI is Typer/questionary based, and data
flows are routed through point-in-time-aware vendor adapters. See
[`src/README.md`](src/README.md) for the canonical source layout.

## Course objectives

- Measure what a multi-agent LLM run actually costs, without storing prompts or
  model output.
- Test one concrete cost-reduction idea (single-pass structured finalisation)
  behind an off-by-default switch instead of assuming it helps.
- Keep every claim reproducible offline: no network, no paid API, and no real
  credential in the default test run.
- Make the submission's requirements, design decisions, evidence, and residual
  risks traceable to code and tests.

## Contributions in this fork

- **Token observability with attribution.** A per-run callback collector records
  provider-reported usage per logical call, attributes it to an agent or a named
  system component, and treats missing usage as `UNKNOWN`/`PARTIAL`, never as
  zero. A run with unattributed calls fails closed at the experiment boundary
  rather than silently under-reporting spend. See
  [`docs/architecture/adr/001-provider-usage-observability.md`](docs/architecture/adr/001-provider-usage-observability.md).
- **Single-pass structured finalisation.** Three tool-loop analysts can emit
  their typed report as the terminal schema tool call, removing the second
  full-context generation that RC1 used to rewrite prose into fields. It is
  behind `single_pass_finalization_enabled` (default `False`) and falls back to
  the RC1 free-text path. See
  [`docs/architecture/adr/002-single-pass-finalization.md`](docs/architecture/adr/002-single-pass-finalization.md).
- **Batch-macro ablation.** A batch FRED tool tests whether fewer tool round
  trips reduce tokens. It is a measured ablation, not a shipped default; see
  [`docs/architecture/adr/003-batch-macro-switch.md`](docs/architecture/adr/003-batch-macro-switch.md).
- **Reliability fixes.** Typed provider errors and fail-closed budget/usage
  verdicts, Finnhub-only news provenance, point-in-time date handling, per-run
  memory isolation, checkout-independent experiment specs, and a deterministic
  offline validation gate.

## Repository map

| Path | Contents |
| --- | --- |
| `tradingagents/` | Product package: graph, agents, dataflows, observability, LLM clients. |
| `cli/` | Interactive CLI and preference persistence. |
| `tests/` | Offline pytest suite (default `pytest -q`). |
| `test/offline/` | Pointer to the offline test subset and its rules. |
| `test/live/` | Pointer to opt-in live/integration tests; never run in CI. |
| `src/` | Map from the course slide layout to the real packages. |
| `docs/req/` | Machine-readable requirements and JSON Schema. |
| `docs/architecture/` | ADRs, invariants, trace matrix, evaluation records. |
| `docs/code-governance/` | Governance constraints and tool manifest. |
| `prompts/` | Archival static startup prompts (not runtime configuration). |
| `transcripts/` | Annotated student transcript policy and template. |
| `token_benchmarks/` | Frozen CAND-01 registrations, manifests, and reports. |
| `scripts/validate/validate_submission.py` | Offline course-compliance gate. |

## Install

Requires Python 3.10+. CI runs the suite on 3.10–3.13; the clean-install and submission-validator jobs use 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The clean-install smoke job also checks that a bare `pip install .` imports
`tradingagents` and `cli.main`.

## Run

```bash
tradingagents          # installed CLI entry point
python -m cli.main     # run directly from the source tree
```

The interactive flow asks for the ticker, analysis date, output language,
analysts, research depth, provider, and models. Previous answers are offered
back as defaults; they never skip a prompt. `TRADINGAGENTS_*` environment
variables can skip individual steps.

## Offline tests

The default suite is offline and LLM-free. It uses dummy API keys from
`tests/conftest.py`, blocks live news vendors, and does not require network
access or a paid provider call.

```bash
pytest -q
pytest tests/test_cand01_batch_16run_v3_infra.py -q
pytest tests/test_cli_prefs.py -q
python scripts/validate/validate_submission.py
```

`tests/test_submission_compliance.py` runs the validator as a pytest test, so the
course gate is enforced both locally and in CI. Live/integration tests are marked
`@pytest.mark.integration` and are opt-in; see [`test/live/README.md`](test/live/README.md).

## Real API configuration (no secrets)

Copy the placeholder file and fill in only the provider you use:

```bash
cp .env.example .env
```

Set the key in `.env` or the environment, for example `OPENAI_API_KEY` or
`DEEPSEEK_API_KEY`. For the course endpoint, configure an OpenAI-compatible
provider:

```bash
export TRADINGAGENTS_LLM_PROVIDER=openai_compatible
export TRADINGAGENTS_LLM_BACKEND_URL=https://your-endpoint.example/v1
export OPENAI_COMPATIBLE_API_KEY=...   # only if the endpoint requires one
```

Never commit `.env`, a real key, a bearer token, or a private key. `.env` is
gitignored; `.env.example` contains placeholders only. The full provider list is
in `.env.example` and the CLI's provider menu.

## Results and evidence

- A run writes its reports and state under the configured results directory
  (`TRADINGAGENTS_RESULTS_DIR`, default under `results/`).
- Per-run telemetry is written as JSON under
  `<results_dir>/<ticker>/<date>/telemetry/<run_id>.json`; the CLI prints the
  telemetry path after a run.
- The frozen CAND-01 experiment lives in
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/`. Its `specs/`,
  `MANIFEST.sha256`, and protocol records are immutable; the tests verify both
  their byte hashes and generator reproduction.
- Recorded evaluation and audit material is under
  [`docs/architecture/`](docs/architecture/) and
  [`docs/architecture/evaluation-table.md`](docs/architecture/evaluation-table.md).

### Exploratory single-pass result

In the V3 2×2, the balanced three-block comparison measured
**−19,589 tokens per run (−8.96%)** for single-pass finalisation. This is an
exploratory result: there is **n = 1 measured run per cell**, the blocks are not
replicates, and the estimate is not statistically confirmatory. The batch-macro
arm measured −17,702 tokens/run overall, but only −695/run after excluding the
environment-degraded R01, so it is not a demonstrated saving. Read
[`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/`](token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/)
and the ADRs before quoting any number.

## Known limitations

- The V3 factorial is exploratory (n = 1 per cell); no significance or production
  performance claim is made.
- Single-pass finalisation remains off by default. Its fallback surface is real:
  malformed schema calls, raw DSML markup, and one provider 400 appeared in the
  V3 single-pass arms.
- The batch-macro token benefit did not materialise after the degraded run is
  excluded.
- Results depend on the provider, model, vendor data, and the point-in-time trade
  date. Re-runs are not expected to reproduce token counts exactly.
- Live/integration tests require explicit credentials and human authorization;
  they are never part of the default CI run.
- A real student-annotated transcript is still **PENDING_HUMAN_CONFIRMATION**;
  see [`transcripts/README.md`](transcripts/README.md).

## Documentation

Start with [`docs/req/requirements.yaml`](docs/req/requirements.yaml) and
[`docs/architecture/trace-matrix.md`](docs/architecture/trace-matrix.md), then the
ADRs, invariants, and governance constraints. The verification rules behind the
course gate are in
[`docs/code-governance/verification-constraints.md`](docs/code-governance/verification-constraints.md);
the gate itself is implemented in
[`scripts/validate/validate_submission.py`](scripts/validate/validate_submission.py).

## Attribution and license

TradingAgents was created by [Tauric Research](https://github.com/TauricResearch)
and is distributed under the Apache License 2.0; see [`LICENSE`](LICENSE). This
fork retains the upstream architecture and adds the course-specific observability,
experiment, and governance layers described above. Upstream paper:
<https://arxiv.org/abs/2412.20138>.
