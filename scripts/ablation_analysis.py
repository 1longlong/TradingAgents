#!/usr/bin/env python
"""Ablation analysis for the batch-macro + S2 campaign.

Reads the four arm summaries written by the official harness and the raw
per-run telemetry, then writes:

* ``arm_summary.csv``        - per-arm means, SD, CV, 95 % CI
* ``ablation_comparison.csv``- every treatment/control contrast per metric
* ``per_agent_comparison.csv``- per-agent token and call counts per arm
* ``failure_rates.csv``      - attempts, completions, timeouts, success rate

Every number originates in harness output. Nothing is estimated.

Statistical policy (enforced here, not in prose):

* n = 5 per arm. Comparisons whose 95 % confidence intervals overlap are
  labelled ``INCONCLUSIVE``. A p-value above 0.05 is never read as evidence
  that there is *no* effect; it is reported as "not detected at this n".
* The sample unit is the run, and the harness picks the latest finished
  attempt of each run. That rule is reproduced exactly here so the numbers
  match ``summary.json``.
* Failed attempts are excluded from the sample but counted in the failure
  table. They are never deleted and never treated as samples.

Usage
-----
    .venv/bin/python scripts/ablation_analysis.py --out <campaign_dir>
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics as st
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TS = "20261106_195007"

ARMS = ["C0", "A", "B", "AB"]

#: What each arm switches on. Read from the experiment definitions at runtime;
#: this table is only used to label output.
ARM_LABELS = {
    "C0": "batch=off, s2=off (control)",
    "A": "batch=on, s2=off",
    "B": "batch=off, s2=on",
    "AB": "batch=on, s2=on",
}

#: Two-sided 95 % t critical values, indexed by degrees of freedom.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179}

ANALYSTS = ["market_analyst", "fundamentals_analyst", "news_analyst",
            "sentiment_analyst"]
DOWNSTREAM = ["bull_researcher", "bear_researcher", "research_manager",
              "trader", "neutral_analyst", "aggressive_analyst",
              "conservative_analyst", "portfolio_manager"]


# ------------------------------------------------------------------ maths

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz)."""
    maxit, eps, fpmin = 200, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > fpmin else fpmin)
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / c
        c = c if abs(c) > fpmin else fpmin
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / c
        c = c if abs(c) > fpmin else fpmin
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(ln_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_p_two_sided(t: float, df: float) -> float:
    """Two-sided p-value of Student's t. scipy is not installed here."""
    return betai(df / 2.0, 0.5, df / (df + t * t))


def t95(df: int) -> float:
    return _T95.get(df, 1.96)


def ci95(mean: float, sd: float, n: int) -> tuple[float, float]:
    if n < 2:
        return (float("nan"), float("nan"))
    half = t95(n - 1) * sd / math.sqrt(n)
    return mean - half, mean + half


def welch(x: list[float], y: list[float]) -> dict:
    """Welch t-test statistics for x (treatment) against y (control)."""
    nx, ny = len(x), len(y)
    mx, my = st.mean(x), st.mean(y)
    vx, vy = st.variance(x), st.variance(y)
    se = math.sqrt(vx / nx + vy / ny)
    if se == 0:
        return {"mean_x": mx, "mean_y": my, "t": float("nan"),
                "df": float("nan"), "p": float("nan"), "se": 0.0}
    df = (vx / nx + vy / ny) ** 2 / ((vx / nx) ** 2 / (nx - 1)
                                     + (vy / ny) ** 2 / (ny - 1))
    t = (mx - my) / se
    return {"mean_x": mx, "mean_y": my, "t": t, "df": df,
            "p": t_p_two_sided(t, df), "se": se}


def cohens_d(x: list[float], y: list[float]) -> float | None:
    nx, ny = len(x), len(y)
    if nx < 2 or ny < 2:
        return None
    sx, sy = st.variance(x), st.variance(y)
    pooled = math.sqrt(((nx - 1) * sx + (ny - 1) * sy) / (nx + ny - 2))
    return (st.mean(x) - st.mean(y)) / pooled if pooled else None


def verdict(lo_c: float, hi_c: float, lo_t: float, hi_t: float) -> str:
    if any(math.isnan(v) for v in (lo_c, hi_c, lo_t, hi_t)):
        return "INCONCLUSIVE (n<2)"
    if hi_c < lo_t or hi_t < lo_c:
        return "SEPARATED (95% CIs disjoint)"
    return "INCONCLUSIVE (95% CIs overlap)"


# ------------------------------------------------------------- harness IO

def exp_dir(arm: str) -> Path:
    return (REPO_ROOT / "token_benchmarks" / "measurements"
            / f"{TS}_NVDA_2026-09-23_macro_s2_{arm}")


def load_summary(arm: str) -> dict:
    return json.loads((exp_dir(arm) / "summary.json").read_text())


def valid_attempts(arm: str) -> list[tuple[int, Path, dict]]:
    """Reproduce the harness rule: latest finished attempt of each run.

    An attempt counts as finished when it wrote telemetry carrying provider
    usage. That is exactly how ``_read_attempt`` decides, so the sample here
    matches ``summary.json`` run for run.
    """
    out = []
    for run_index in range(1, 6):
        finished = []
        run_dir = exp_dir(arm) / "runs" / f"run_{run_index:02d}"
        for attempt in sorted(run_dir.glob("attempt_*")):
            tel = attempt / "telemetry.json"
            if not tel.exists():
                continue
            data = json.loads(tel.read_text())
            if "reported_input_tokens_sum" in data.get("run_totals", {}):
                finished.append((run_index, attempt, data))
        if finished:
            out.append(finished[-1])
    return out


def attempt_outcomes(arm: str) -> dict:
    counts = {"completed": 0, "failed": 0, "interrupted": 0}
    timeouts = 0
    for report in exp_dir(arm).glob("runs/run_*/attempt_*/runner_report.json"):
        data = json.loads(report.read_text())
        status = data.get("status")
        if status in counts:
            counts[status] += 1
        if status != "completed" and "Timeout" in str(data.get("error") or ""):
            timeouts += 1
    counts["attempts"] = sum(counts.values())
    counts["timeouts"] = timeouts
    return counts


#: metric name -> extractor over one telemetry document
METRICS = {
    "total_tokens": lambda t: (t["run_totals"]["reported_input_tokens_sum"]
                               + t["run_totals"]["reported_output_tokens_sum"]),
    "input_tokens": lambda t: t["run_totals"]["reported_input_tokens_sum"],
    "output_tokens": lambda t: t["run_totals"]["reported_output_tokens_sum"],
    "cached_input_tokens": lambda t: t["run_totals"]["reported_cached_input_tokens_sum"],
    "llm_calls": lambda t: t["run_totals"]["llm_calls"],
    "tool_calls": lambda t: t["run_totals"]["tool_calls"],
    "tool_rounds": lambda t: t["run_totals"]["tool_rounds"],
    "runtime_ms": lambda t: t["run"]["duration_ms"],
}

CONTRASTS = [
    ("A", "C0", "batch macro alone"),
    ("B", "C0", "S2 alone"),
    ("AB", "C0", "combined vs control"),
    ("AB", "A", "S2 added to batch macro"),
    ("AB", "B", "batch macro added to S2"),
]


# ---------------------------------------------------------------- writers

def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    if not rows:
        path.write_text("")
        return
    fields = fields or list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)

    raw = {
        arm: {m: [f(tel) for _, _, tel in valid_attempts(arm)]
              for m, f in METRICS.items()}
        for arm in ARMS
    }
    summaries = {arm: load_summary(arm) for arm in ARMS}

    # ---- per arm ------------------------------------------------------
    arm_rows = []
    for arm in ARMS:
        row = {"arm": arm, "configuration": ARM_LABELS[arm],
               "valid_runs": summaries[arm]["measured_valid"]}
        row.update(attempt_outcomes(arm))
        for metric, values in raw[arm].items():
            n = len(values)
            mean, sd = st.mean(values), st.stdev(values)
            lo, hi = ci95(mean, sd, n)
            row[f"{metric}_mean"] = round(mean, 2)
            row[f"{metric}_sd"] = round(sd, 2)
            row[f"{metric}_median"] = round(st.median(values), 2)
            row[f"{metric}_cv_pct"] = round(100 * sd / mean, 2) if mean else None
            row[f"{metric}_ci95_lo"] = round(lo, 2)
            row[f"{metric}_ci95_hi"] = round(hi, 2)
        arm_rows.append(row)
    write_csv(out / "arm_summary.csv", arm_rows)

    # ---- contrasts ----------------------------------------------------
    contrast_rows = []
    for treatment, control, meaning in CONTRASTS:
        for metric in METRICS:
            tx, cx = raw[treatment][metric], raw[control][metric]
            w = welch(tx, cx)
            pct = 100 * (w["mean_x"] - w["mean_y"]) / w["mean_y"]
            lo_t, hi_t = ci95(w["mean_x"], st.stdev(tx), len(tx))
            lo_c, hi_c = ci95(w["mean_y"], st.stdev(cx), len(cx))
            contrast_rows.append({
                "contrast": f"{treatment} vs {control}",
                "meaning": meaning,
                "metric": metric,
                "control_mean": round(w["mean_y"], 2),
                "treatment_mean": round(w["mean_x"], 2),
                "abs_diff": round(w["mean_x"] - w["mean_y"], 2),
                "pct_diff": round(pct, 2),
                "cohens_d": round(cohens_d(tx, cx), 3),
                "welch_t": round(w["t"], 3),
                "welch_df": round(w["df"], 2),
                "welch_p": round(w["p"], 4),
                "p_below_0_05": "yes" if w["p"] < 0.05 else "no",
                "control_ci95": f"[{lo_c:.0f}, {hi_c:.0f}]",
                "treatment_ci95": f"[{lo_t:.0f}, {hi_t:.0f}]",
                "verdict": verdict(lo_c, hi_c, lo_t, hi_t),
                "n_control": len(cx),
                "n_treatment": len(tx),
            })
    write_csv(out / "ablation_comparison.csv", contrast_rows)

    # ---- per agent ----------------------------------------------------
    agent_rows = []
    for arm in ARMS:
        runs = [tel for _, _, tel in valid_attempts(arm)]
        for agent in ANALYSTS + DOWNSTREAM:
            present = [r["agents"][agent] for r in runs if agent in r.get("agents", {})]
            if not present:
                continue
            agent_rows.append({
                "arm": arm,
                "agent": agent,
                "group": "analyst" if agent in ANALYSTS else "downstream",
                "input_tokens_mean": round(st.mean(x["reported_input_tokens_sum"] for x in present)),
                "output_tokens_mean": round(st.mean(x["reported_output_tokens_sum"] for x in present)),
                "total_tokens_mean": round(st.mean(x["reported_input_tokens_sum"]
                                                   + x["reported_output_tokens_sum"] for x in present)),
                "llm_calls_mean": round(st.mean(x["llm_calls"] for x in present), 2),
                "tool_calls_mean": round(st.mean(x["tool_calls"] for x in present), 2),
                "tool_rounds_mean": round(st.mean(x["tool_rounds"] for x in present), 2),
                "n": len(present),
            })
    write_csv(out / "per_agent_comparison.csv", agent_rows)

    # ---- failure rates ------------------------------------------------
    failure_rows = []
    for arm in ARMS:
        o = attempt_outcomes(arm)
        failure_rows.append({
            "arm": arm, "attempts": o["attempts"],
            "completed": o["completed"], "failed": o["failed"],
            "interrupted": o["interrupted"], "timeouts": o["timeouts"],
            "timeout_rate_pct": round(100 * o["timeouts"] / o["attempts"], 2) if o["attempts"] else None,
            "completion_rate_pct": round(100 * o["completed"] / o["attempts"], 2) if o["attempts"] else None,
        })
    write_csv(out / "failure_rates.csv", failure_rows)

    # ---- console ------------------------------------------------------
    print(f"{'arm':4}{'n':>3}{'total':>10}{'sd':>9}{'CV%':>6}{'input':>9}"
          f"{'output':>9}{'calls':>7}{'tools':>7}{'dur_s':>8}")
    for arm in ARMS:
        row = next(r for r in arm_rows if r["arm"] == arm)
        print(f"{arm:4}{row['valid_runs']:>3}{row['total_tokens_mean']:>10.0f}"
              f"{row['total_tokens_sd']:>9.0f}{row['total_tokens_cv_pct']:>6.1f}"
              f"{row['input_tokens_mean']:>9.0f}{row['output_tokens_mean']:>9.0f}"
              f"{row['llm_calls_mean']:>7.1f}{row['tool_calls_mean']:>7.1f}"
              f"{row['runtime_ms_mean']/1000:>8.0f}")

    for metric in ("total_tokens", "tool_calls", "llm_calls"):
        print(f"\n{metric}:")
        for row in contrast_rows:
            if row["metric"] != metric:
                continue
            print(f"  {row['contrast']:9} {row['pct_diff']:+7.2f}%  "
                  f"p={row['welch_p']:.4f}  d={row['cohens_d']:+.2f}  "
                  f"{row['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
