#!/usr/bin/env python
"""Campaign runner: one run slot at a time, round-robin across the four arms.

Why this exists
---------------
``scripts/token_benchmark.py run`` executes **every** slot of an experiment
before returning, so it cannot interleave arms: the first arm would be measured
entirely before the second one starts, and slow drift in the external data
environment (Yahoo availability, FRED latency) could load onto whichever arm ran
last.

This wrapper adds only *scheduling*. It calls the harness's own
``execute_measured_run`` once per slot, and every measurement, validity rule,
telemetry-selection rule, fingerprint and summary goes through the unchanged
harness. Nothing about measurement is re-implemented here.

Order is C0 → A → B → AB, repeated for as many rounds as requested.

Resumability
------------
A slot that already holds a valid measured sample is skipped, so the script can
be re-run after any interruption and will continue where it stopped. A slot whose
latest attempt failed is retried, which is the harness's own documented
behaviour (a new ``attempt_NN`` directory; the failed attempt is kept).

Usage
-----
    .venv/bin/python scripts/campaign_ablation_round.py --rounds 5
    .venv/bin/python scripts/campaign_ablation_round.py --rounds 1 --arms AB
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import token_benchmark as tb  # noqa: E402

TS = "20261106_195007"
ARMS = {
    "C0": {"batch_macro_enabled": "false", "structured_analyst_output_enabled": "false"},
    "A":  {"batch_macro_enabled": "true",  "structured_analyst_output_enabled": "false"},
    "B":  {"batch_macro_enabled": "false", "structured_analyst_output_enabled": "true"},
    "AB": {"batch_macro_enabled": "true",  "structured_analyst_output_enabled": "true"},
}
ORDER = ["C0", "A", "B", "AB"]


def exp_dir(arm: str) -> Path:
    return (REPO_ROOT / "token_benchmarks" / "measurements"
            / f"{TS}_NVDA_2026-09-23_macro_s2_{arm}")


def slot_is_valid(arm: str, run_index: int) -> bool:
    """True if this slot already holds a valid measured sample."""
    stored = tb._summarized_attempt(exp_dir(arm), run_index)
    return bool(stored is not None and stored.get("valid"))


def next_attempt(arm: str, run_index: int) -> int:
    """Next free attempt number, so an interrupted/failed attempt is preserved."""
    return len(tb.attempt_dirs(exp_dir(arm), run_index)) + 1


def set_switches(arm: str) -> None:
    """Export this arm's switches for the child process the harness spawns."""
    for key, value in ARMS[arm].items():
        os.environ[f"TRADINGAGENTS_{key.upper()}"] = value


def run_one_slot(arm: str, run_index: int) -> dict:
    d = exp_dir(arm)
    experiment = tb._load_json(d / tb.EXPERIMENT_FILE)
    case = experiment["cases"][0]
    attempt = next_attempt(arm, run_index)
    set_switches(arm)
    print(f"\n===== arm {arm} run {run_index} attempt {attempt} "
          f"(batch={ARMS[arm]['batch_macro_enabled']}, "
          f"s2={ARMS[arm]['structured_analyst_output_enabled']}) =====", flush=True)
    tb._mark_run_started(d, experiment, case, run_index, attempt)
    metrics = tb.execute_measured_run(
        d, experiment, case, run_index=run_index,
        run_dir=tb._attempt_dir(d, run_index, attempt),
    )
    status = "VALID" if metrics.get("valid") else f"INVALID ({metrics.get('error')})"
    print(f"===== arm {arm} run {run_index} -> {status} =====", flush=True)
    return metrics


def write_summaries(arm: str) -> None:
    """Rebuild the summary files from stored telemetry using the harness."""
    tb._cmd_summarize(argparse.Namespace(experiment_dir=str(exp_dir(arm))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5,
                    help="target number of valid runs per arm")
    ap.add_argument("--secrets-file", default=str(Path("~/.env_secrets").expanduser()))
    ap.add_argument("--arms", default=",".join(ORDER))
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for arm in arms:
        if arm not in ARMS:
            print(f"error: unknown arm {arm}", file=sys.stderr)
            return 2

    # Credentials are resolved before any LLM call, exactly as the shipped
    # wrapper does. Names are printed, never values.
    applied = tb.apply_cityu_env(os.environ, Path(args.secrets_file))
    missing = [n for n in tb.required_cityu_env() if not os.environ.get(n)]
    if missing:
        print("error: missing credential(s): " + ", ".join(missing), file=sys.stderr)
        return 1
    print(f"credentials applied (names only): {applied}", flush=True)

    for round_no in range(1, args.rounds + 1):
        pending = [a for a in arms if not slot_is_valid(a, round_no)]
        if not pending:
            print(f"\nround {round_no}: all arms already valid, skipping")
            continue
        print(f"\n########## round {round_no}  (pending: {pending}) ##########", flush=True)
        for arm in pending:
            run_one_slot(arm, round_no)

    print("\n===== counts =====")
    ok = True
    for arm in arms:
        n = sum(1 for r in range(1, args.rounds + 1) if slot_is_valid(arm, r))
        print(f"{arm:3} valid={n} / target={args.rounds}")
        ok = ok and n == args.rounds
        try:
            write_summaries(arm)
        except SystemExit:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
