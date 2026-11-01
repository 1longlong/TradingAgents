#!/usr/bin/env bash
# One-command token benchmark for TradingAgents.
#
# Creates a fresh, timestamped experiment under token_benchmarks/measurements/,
# loads the CityU credentials, validates the configuration, runs the measured
# runs, and verifies the resulting summary against the recorded telemetry.
#
#   ./scripts/run_token_benchmark.sh
#   ./scripts/run_token_benchmark.sh --label after-refactor
#   ./scripts/run_token_benchmark.sh --ticker NVDA --date 2026-09-23
#   ./scripts/run_token_benchmark.sh --runs 3 --label quick
#   ./scripts/run_token_benchmark.sh --dry-run
#   ./scripts/run_token_benchmark.sh --help
#
# This is a thin wrapper: all measurement logic (attempt retries, telemetry
# selection, validity rules, statistics) lives in scripts/token_benchmark.py.
# Nothing here re-implements or overrides the harness's accounting.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Work from the repository root so .env / relative paths resolve the same way
# no matter which directory the command was invoked from.
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd -- "$REPO_ROOT"

DEFAULT_RUNS=5
DEFAULT_LABEL="manual"
SECRETS_FILE="${TRADINGAGENTS_BENCHMARK_SECRETS:-$HOME/.env_secrets}"
HARNESS="$SCRIPT_DIR/token_benchmark.py"

usage() {
  cat <<'EOF'
Usage: scripts/run_token_benchmark.sh [options]

Run one complete token benchmark measurement. Every invocation creates a new
timestamped experiment directory; previous measurements are never overwritten.

Options:
  --label LABEL    Free-form label appended to the directory name (default: manual).
                   Sanitized to [A-Za-z0-9._-]; e.g. "after fix!" -> after-fix.
  --ticker TICKER  Ticker to measure (default: the template's ticker, NVDA).
  --date YYYY-MM-DD  Trade date to measure (default: the template's date).
                   Defaults are never replaced with "today" so results stay
                   comparable with the baseline.
  --runs N         Number of measured runs (default: 5). Must be a positive integer.
  --dry-run        Create the experiment and validate it, but call no LLM and
                   incur no cost. The dry-run archive directory is printed.
  --continue-on-error  Keep going after an invalid run instead of stopping at the
                   first one. Invalid runs still never count as measured samples.
  -h, --help       Show this message and exit.

Environment:
  TRADINGAGENTS_BENCHMARK_SECRETS  Path to the credentials file (default: ~/.env_secrets).
  CITYU_FOUNDRY_API_KEY -> OPENAI_COMPATIBLE_API_KEY
  CITYU_FOUNDRY_BASE_URL -> TRADINGAGENTS_LLM_BACKEND_URL

Exit status:
  0  all target runs valid and every consistency check passed
  1  configuration/environment error (nothing was measured)
  2  unsupported argument
  3  measurement ran but is incomplete (fewer valid runs than requested)
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

# --- argument parsing -------------------------------------------------------
LABEL="$DEFAULT_LABEL"
TICKER=""
DATE=""
RUNS=""
DRY_RUN=0
CONTINUE_ON_ERROR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --label)
      [[ $# -ge 2 && -n "${2:-}" ]] || die "--label requires a value"
      LABEL="$2"; shift 2 ;;
    --label=*)
      LABEL="${1#*=}"
      [[ -n "$LABEL" ]] || die "--label requires a value"
      shift ;;
    --ticker)
      [[ $# -ge 2 && -n "${2:-}" ]] || die "--ticker requires a value"
      TICKER="$2"; shift 2 ;;
    --ticker=*)
      TICKER="${1#*=}"
      [[ -n "$TICKER" ]] || die "--ticker requires a value"
      shift ;;
    --date)
      [[ $# -ge 2 && -n "${2:-}" ]] || die "--date requires a value"
      DATE="$2"; shift 2 ;;
    --date=*)
      DATE="${1#*=}"
      [[ -n "$DATE" ]] || die "--date requires a value"
      shift ;;
    --runs)
      [[ $# -ge 2 && -n "${2:-}" ]] || die "--runs requires a value"
      RUNS="$2"; shift 2 ;;
    --runs=*)
      RUNS="${1#*=}"
      [[ -n "$RUNS" ]] || die "--runs requires a value"
      shift ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --continue-on-error)
      CONTINUE_ON_ERROR=1; shift ;;
    --)
      shift
      [[ $# -eq 0 ]] || die "unexpected argument: $1"
      ;;
    -*)
      printf 'error: unsupported option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
    *)
      printf 'error: unexpected argument: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$RUNS" ]]; then
  [[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer, got '$RUNS'"
fi
if [[ -n "$DATE" && ! "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  die "--date must look like YYYY-MM-DD, got '$DATE'"
fi

# --- interpreter ------------------------------------------------------------
# Prefer the project virtualenv so the same Python that runs the app runs the
# benchmark. Never falls back to a global interpreter silently.
PYTHON=""
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  die "no interpreter at $REPO_ROOT/.venv/bin/python (create the project virtualenv first)"
fi

[[ -f "$HARNESS" ]] || die "harness not found at $HARNESS"

# --- credentials (never printed) -------------------------------------------
# The secrets file is parsed as data by the harness, never sourced, and only the
# two mapped variables are imported so nothing else can change the benchmark.
if [[ "$DRY_RUN" -eq 0 ]]; then
  [[ -f "$SECRETS_FILE" ]] || die "credentials file not found: $SECRETS_FILE
Expected CITYU_FOUNDRY_API_KEY and CITYU_FOUNDRY_BASE_URL there, or set
TRADINGAGENTS_BENCHMARK_SECRETS to point at the right file."
  missing=""
  for key in CITYU_FOUNDRY_API_KEY CITYU_FOUNDRY_BASE_URL; do
    if ! grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$SECRETS_FILE"; then
      missing="$missing $key"
    fi
  done
  [[ -z "$missing" ]] || die "missing required credential(s) in $SECRETS_FILE:$missing"
fi

# --- export nothing that competes with the experiment -----------------------
# The experiment file is the single source of truth for provider, models,
# language and rounds. The harness clears those TRADINGAGENTS_* variables in
# each run child, so exporting them here would only create the illusion of
# control while the spec silently won.

args=(measure --repo-root "$REPO_ROOT" --label "$LABEL")
[[ -n "$TICKER" ]] && args+=(--ticker "$TICKER")
[[ -n "$DATE" ]] && args+=(--date "$DATE")
[[ -n "$RUNS" ]] && args+=(--runs "$RUNS")
[[ "$DRY_RUN" -eq 1 ]] && args+=(--dry-run)
[[ "$CONTINUE_ON_ERROR" -eq 1 ]] && args+=(--continue-on-error)

# The secrets file is parsed as plain data by the harness -- never sourced, so a
# command embedded in it cannot run -- and only the two mapped variables enter
# the environment. Values are never echoed. Passing the path (not the values)
# keeps the secrets out of argv.
if [[ "$DRY_RUN" -eq 0 ]]; then
  exec "$PYTHON" "$HARNESS" "${args[@]}" --secrets-file "$SECRETS_FILE"
fi

exec "$PYTHON" "$HARNESS" "${args[@]}"
