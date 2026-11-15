#!/usr/bin/env bash
# Detached launcher for the ablation campaign.
#
# The interactive shell does not survive a harness restart, and a previous
# attempt lost its redirection target when a variable did not expand in the
# backgrounded subshell. Paths are therefore hard-coded and absolute here, and
# `setsid` detaches the process from the controlling terminal so a session
# restart does not terminate the measurement.
#
# Usage: scripts/campaign_ablation_launch.sh [extra args for the runner]
#
# LEGACY — not referenced by the V2 batch (CAND-01 / cand01_batch_16run_v2).
# It drives campaign_ablation_round.py, which hard-codes the 20261106_195007
# campaign and the pre-V2 arm names. It is kept for the historical record only.
#
# The tree it runs from is derived from this script's own location, NOT
# hard-coded. An earlier revision pinned /home/sky/cs5351/TradingAgents and that
# repository's shared .venv, so invoking it from an experiment worktree would
# have spent money running the *main* checkout's code while the operator
# believed they were measuring the worktree (audit B-09).
set -u

# Refuse by default. This script spends real money, and the only reason anyone
# now runs it is to check that this refactor did not break it -- which is
# exactly how it was accidentally executed on 2026-11-15 (see
# INCIDENT_20261115_legacy_launcher.md). An explicit opt-in makes a
# verification invocation harmless and a real one deliberate.
if [[ "${CAMPAIGN_ABLATION_I_MEAN_IT:-}" != "yes" ]]; then
  echo "refusing to start: this legacy launcher spends money and is not part of Plan C3." >&2
  echo "  To run the historical campaign deliberately, set" >&2
  echo "    CAMPAIGN_ABLATION_I_MEAN_IT=yes" >&2
  echo "  V2 runs use scripts/c3_preflight_gate.py + scripts/token_benchmark.py." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$REPO_ROOT" == "/home/sky/cs5351/TradingAgents" ]]; then
  echo "refusing to start: this legacy launcher is not for the main checkout." >&2
  echo "  It exists for historical campaigns; the V2 batch uses" >&2
  echo "  scripts/c3_preflight_gate.py + scripts/token_benchmark.py instead." >&2
  exit 1
fi
PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "refusing to start: $PYTHON is missing; refusing to fall back to some" >&2
  echo "  other interpreter, which would run code from a different tree." >&2
  exit 1
fi
CAMPAIGN="$REPO_ROOT/token_benchmarks/optimization_campaigns/20261106_195007_macro_s2_completion"
LOG="$CAMPAIGN/logs/campaign_full.log"
PIDFILE="$CAMPAIGN/logs/campaign_full.pid"

mkdir -p "$CAMPAIGN/logs"
cd "$REPO_ROOT" || exit 1

# Refuse to start a second instance: two concurrent runs would compete for the
# same experiment directories and corrupt the measurement. The live process
# table is checked, not just the PID file, because that is what actually
# catches a runner started by some other invocation (see
# incident_duplicate_launch.md, where a PID file missed exactly that case).
running="$(ps -eo pid,args | grep -E 'campaign_ablation_round\.py|_run-single' \
           | grep -v -E 'grep|launch\.sh' | awk '{print $1}' | tr '\n' ' ')"
if [[ -n "${running// /}" ]]; then
  echo "refusing to start: benchmark process(es) already running: $running" >&2
  echo "wait for them to finish, or stop them deliberately, before relaunching." >&2
  exit 1
fi
if [[ -f "$PIDFILE" ]]; then
  existing="$(cat "$PIDFILE")"
  if [[ -n "$existing" ]] && kill -0 "$existing" 2>/dev/null; then
    echo "refusing to start: campaign already running as pid $existing" >&2
    exit 1
  fi
fi

setsid "$PYTHON" "$REPO_ROOT/scripts/campaign_ablation_round.py" \
  --rounds 5 "$@" >> "$LOG" 2>&1 < /dev/null &
new_pid=$!
echo "$new_pid" > "$PIDFILE"
echo "started campaign pid $new_pid; log: $LOG"
