"""Phase 4A runner script: deterministic offline comparison (no LLM/network).

Run from the repository root:

    .venv/bin/python scripts/run_phase4a_comparison.py

This replays the representative scripted case fixtures (scenarios D/E/F)
through both the fixed-round baseline and the dynamic policy using the pure
debate evaluator, aggregates the results, and writes:

    evaluation-output/comparison_results.json   (machine-readable)
    evaluation-output/comparison_report.md      (concise Markdown)

It never invokes an LLM, data vendor, or network; it reads no wall clock; and
it never overwrites the raw fixtures. It is an **offline scripted comparison**,
not a live-provider result and not final tuning.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.comparison.fixtures import ALL_SCRIPTED_CASES  # noqa: E402
from tradingagents.comparison.report import write_comparison_report  # noqa: E402
from tradingagents.comparison.runner import (  # noqa: E402
    pair_and_aggregate,
    replay_scripted_case,
)


def main() -> int:
    results = []
    for build in ALL_SCRIPTED_CASES:
        case = build()
        paired = replay_scripted_case(case)
        results.append(paired["fixed"])
        results.append(paired["dynamic"])
    report = pair_and_aggregate(results)
    paths = write_comparison_report(report)
    print(
        f"Phase 4A offline comparison wrote {len(report.paired_cases)} case(s) "
        f"to evaluation-output/: "
        + ", ".join(f"{k}={v}" for k, v in sorted(paths.items()))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
