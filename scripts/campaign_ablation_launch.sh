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
set -u

REPO_ROOT="/home/sky/cs5351/TradingAgents"
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

setsid "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/campaign_ablation_round.py" \
  --rounds 5 "$@" >> "$LOG" 2>&1 < /dev/null &
new_pid=$!
echo "$new_pid" > "$PIDFILE"
echo "started campaign pid $new_pid; log: $LOG"
