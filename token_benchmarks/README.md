# Token benchmark: one-command measurement

`scripts/run_token_benchmark.sh` runs one complete, archived token measurement
of the current working tree. It is a thin wrapper around the existing harness
(`scripts/token_benchmark.py`); all accounting — attempt retries, telemetry
selection, validity rules, statistics — stays in one place.

## Usage

```bash
# Measure the current code (5 valid runs, label "manual")
./scripts/run_token_benchmark.sh

# Add a label
./scripts/run_token_benchmark.sh --label after-refactor

# Override ticker / date / run count
./scripts/run_token_benchmark.sh --ticker NVDA --date 2026-09-23 --label after-fix
./scripts/run_token_benchmark.sh --runs 3

# Validate the configuration without calling any LLM (no credentials needed)
./scripts/run_token_benchmark.sh --dry-run

# Show help (no network access)
./scripts/run_token_benchmark.sh --help
```

The script can be run from any directory; it locates the repository itself.
`--ticker` and `--date` default to the **template's** values (NVDA / 2026-09-23),
never to today's date, so results stay comparable with the baseline.

Exit status:

| code | meaning |
| ---- | ------- |
| 0 | every requested run is valid and all consistency checks passed |
| 1 | configuration or environment error (nothing was measured) |
| 2 | unsupported argument |
| 3 | measurement ran but is incomplete (fewer valid runs than requested) |

`3` is not a bug to work around: invalid runs are kept as evidence and are
never averaged in. The report shows the reason for each one.

## What it produces

Each invocation creates a new directory — never reusing or overwriting one:

```text
token_benchmarks/measurements/
└── 20261024_153000_NVDA_2026-09-23_after-fix/
    ├── experiment.json          # configuration snapshot for this run
    ├── notes.md                 # purpose, configuration, verification verdict
    ├── code_state.json          # branch, HEAD, dirty flag, working-tree fingerprint
    ├── measurement_status.json  # machine-readable verdict + every check
    ├── summary.md               # readable report       (written by the harness)
    ├── summary.json             # structured summary    (written by the harness)
    ├── summary.csv              # per-run rows
    ├── summary_agents.csv       # per-agent rows
    └── runs/
        ├── run_01/attempt_01/   # spec, run_state, runner_report, telemetry
        └── run_02/attempt_01/   # failed attempts are kept, never deleted
```

`token_benchmarks/measurements/` is git-ignored: measurements are local
evidence and never dirty the working tree.

## Credentials

For a real run the script reads `~/.env_secrets` (override the location with
`TRADINGAGENTS_BENCHMARK_SECRETS`) and maps exactly two variables:

```
CITYU_FOUNDRY_API_KEY   -> OPENAI_COMPATIBLE_API_KEY
CITYU_FOUNDRY_BASE_URL  -> TRADINGAGENTS_LLM_BACKEND_URL
```

The file is parsed as plain `KEY=VALUE` data — it is **never sourced**, so a
command embedded in it cannot execute — and nothing else from it enters the
environment. Values are never printed, logged, or written into any artifact.
An explicitly exported variable takes precedence over the file.

`--dry-run` needs no credentials and calls no LLM.

## Verification

A zero exit code from the harness is not treated as success. After running, the
summary is cross-checked against the telemetry it claims to come from:

- the stored run count equals the requested count;
- each run's `input + output` equals its `total_tokens`;
- each run's totals equal the sum of the individual LLM events in its own
  telemetry artifact;
- **no** LLM call failed (`llm_error_count == 0`);
- provider usage accounted for every call, attribution is complete, and
  telemetry was finalized;
- every stored average covers exactly the valid runs;
- the number of valid runs equals the requested number.

Only when all of these hold does the script print
`Benchmark completed: N/N valid`. Otherwise it prints `Benchmark INCOMPLETE`
with the failing checks and the path to the preserved evidence.

## Reproducibility

`code_state.json` records the branch, HEAD, whether the working tree was dirty,
a diff fingerprint, and a **working-tree fingerprint**: a SHA-256 over a sorted
manifest of every tracked *and untracked* source file under `tradingagents/`,
`cli/`, `scripts/`, `tests/`, the baseline `experiment.json` files, and the
project configuration files. Each entry is `{relative POSIX path, sha256 of the
file contents}`; no contents and no secrets are stored.

That means an edit to a *new, not-yet-committed* file changes the fingerprint
just as much as an edit to a tracked one — which the older diff-only hash could
not see. Additions and deletions also change it, because the manifest is the
list of files that exist.

Excluded by policy (writing them can never invalidate a measurement): `.env*`,
`.venv/`, Python caches/`*.pyc`, `token_benchmarks/*/runs|cases|measurements/`,
`code_state.json`, generated `summary*` files, `data_cache/`, `reports/`,
logs, and `*backup*` directories.

The fingerprint is taken **before the first run and again after the last run**.
If the two differ, the measurement is marked invalid: `code_state.json` gets
`code_changed_during_measurement`, `summary.json` carries the same flag plus
`measurement_complete: false`, and the notes/exit status say
`INVALID: code_changed_during_measurement`. Such a result is never a baseline.

`experiment_config_sha256` records the configuration separately, so two
measurements can be compared even when one of them was taken on a different
checkout. Offline `summarize` keeps working on any machine: it reuses the
recorded fingerprint instead of recomputing it, and it keeps the "code changed"
verdict sticky.

A dirty tree is recorded as-is — it is not a claim of reproducibility. LLM
sampling is not deterministic even on identical code, so treat the numbers as
describing *this* tree at *this* moment.
