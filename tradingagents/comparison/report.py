"""Phase 4A report writer: deterministic JSON + Markdown comparison output.

Writes two artifacts into a clearly-identified evaluation-output directory
without ever overwriting the raw fixture/input files:

- ``comparison_results.json`` — the full, machine-readable
  :class:`ComparisonReport` (deterministic, sort_keys, ASCII-safe).
- ``comparison_report.md`` — a concise human-readable Markdown summary of the
  same report.

The output directory defaults to ``evaluation-output/`` at the repository root.
Raw inputs (fixtures) are never written here; this module only consumes a
:class:`ComparisonReport` and writes derived artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingagents.comparison.schemas import ComparisonReport

DEFAULT_OUTPUT_DIR = Path("evaluation-output")


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a (zero denominator)"
    return f"{value:.4f}"


def _json_dumps(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def write_comparison_report(
    report: ComparisonReport,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, str]:
    """Write ``comparison_results.json`` + ``comparison_report.md``.

    Returns a ``{logical_name: relative_path}`` mapping. Never touches raw
    fixture inputs.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "comparison_results.json"
    md_path = output_dir / "comparison_report.md"

    json_path.write_text(_json_dumps(report.to_dict()), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    return {
        "comparison_json": json_path.name,
        "comparison_markdown": md_path.name,
    }


def _render_markdown(report: ComparisonReport) -> str:
    lines: list[str] = [
        "# Phase 4A — Baseline Comparison (offline, scripted)",
        "",
        "> **Scope:** deterministic offline comparison of a fixed-round baseline "
        "vs the dynamic policy on identical case identity, evidence snapshot, "
        "policy version, and scripted debate inputs. **Not** a live-provider "
        "result and **not** final tuning. Wall-clock/token values that are "
        "estimates are flagged; no timing is asserted.",
        "",
        f"- **Total compared cases:** {report.total_cases}",
        "",
        "## Per-case results",
        "",
        "| Case (ticker/date/snapshot) | Strategy | Rounds | Early stop | Stop reason | "
        "LLM calls | Tool calls | Tokens | Time (s) | Source | Citation cov. | "
        "False-strong rate | Traceability |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for identity, fixed, dynamic in report.paired_cases:
        label = f"{identity.ticker}/{identity.target_date}/{identity.evidence_snapshot_id}"
        lines.append(_case_row(label, "fixed", fixed))
        lines.append(_case_row(label, "dynamic", dynamic))
    lines += [
        "",
        "## Aggregate (sums and rates)",
        "",
        "| Metric | Fixed baseline | Dynamic policy |",
        "| --- | --- | --- |",
        f"| Total LLM calls | {report.fixed_total_llm_calls} | {report.dynamic_total_llm_calls} |",
        f"| Total tool calls | {report.fixed_total_tool_calls} | {report.dynamic_total_tool_calls} |",
        f"| Total tokens | {report.fixed_total_tokens} | {report.dynamic_total_tokens} |",
        f"| Total time (s) | {report.fixed_total_time:.3f} | {report.dynamic_total_time:.3f} |",
        f"| Total debate rounds | {report.fixed_total_rounds} | {report.dynamic_total_rounds} |",
        f"| Early-stop count | {report.fixed_early_stop_count} | {report.dynamic_early_stop_count} |",
        f"| Dynamic early-stop rate | — | {_fmt(report.dynamic_early_stop_rate)} |",
        f"| False-strong conclusion count | {report.fixed_false_strong_count} | {report.dynamic_false_strong_count} |",
        f"| False-strong conclusion rate | {_fmt(report.fixed_false_strong_rate)} | {_fmt(report.dynamic_false_strong_rate)} |",
        f"| Estimated (not measured) cases | {report.fixed_estimated_cases} | {report.dynamic_estimated_cases} |",
        _stop_reasons_row("Stop reasons (fixed)", report.fixed_stop_reasons),
        _stop_reasons_row("Stop reasons (dynamic)", report.dynamic_stop_reasons),
        "",
        "## Notes",
        "",
        "- **Stop reason** is the *actual* deterministic reason each case reached "
        "(``max_rounds_reached`` for the fixed cap, a real dynamic-policy stop "
        "such as ``no_new_evidence``/``budget_exhausted``, and "
        "``input_exhausted`` when the scripted input simply ran out). It is never "
        "replaced by a generic or inferred label: a run that merely runs out of "
        "scripted rounds is **not** reported as a dynamic early stop.",
        "- **Evidence-citation coverage** is derived from valid cited evidence "
        "IDs over the snapshot's eligible IDs.",
        "- **False-strong-conclusion rate** is computed from an explicit "
        "machine-readable ``strong_conclusion`` flag plus the gate/quality "
        "outcome, never from prose.",
        "- **Human traceability** uses a documented rubric with human-entered "
        "scores; unscored cases stay ``pending`` (``n/a``) rather than "
        "fabricating a rating.",
        "- **Usage source**: ``Source`` is ``estimated`` when the token/time "
        "values were derived by the deterministic char-based estimator, else "
        "``measured``. An estimated value is never presented as measured; the "
        "aggregate ``Estimated (not measured) cases`` row reports the honest "
        "per-strategy count.",
        "- A zero denominator yields ``n/a (zero denominator)`` and is never "
        "fabricated.",
        f"- Policy version pinned for every case: "
        f"{report.paired_cases[0][0].policy_version if report.paired_cases else 'n/a'}.",
        "",
    ]
    return "\n".join(lines)


def _case_row(label: str, strategy: str, agg) -> str:
    coverage = _fmt(agg.evidence_citation_coverage)
    false_rate = _fmt(agg.false_strong_conclusion_rate)
    tr = agg.traceability_status.value
    tr = f"{agg.traceability_mean:.3f}" if agg.traceability_mean is not None else "pending"
    usage_source = "estimated" if agg.tool_usage_estimated else "measured"
    stop_reason = agg.stop_reason or "—"
    return (
        f"| {label} | {strategy} | {agg.debate_rounds} | "
        f"{'yes' if agg.early_stop_rate == 1.0 else 'no'} | {stop_reason} | "
        f"{agg.llm_calls} | {agg.tool_calls} | {agg.total_tokens} | "
        f"{agg.elapsed_seconds:.3f} | {usage_source} | {coverage} | "
        f"{false_rate} | {tr} |"
    )


def _stop_reasons_row(label: str, counts: dict[str, int]) -> str:
    counts = dict(counts or {})
    if not counts:
        return f"| {label} | — |"
    rendered = " | ".join(f"{reason}: {count}" for reason, count in counts.items())
    return f"| {label} | {rendered} |"
