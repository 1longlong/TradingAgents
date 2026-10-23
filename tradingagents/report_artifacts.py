"""Stage 2 report artifacts: shared, deterministic, redacted run/quality outputs.

The shared writer (:func:`write_report_artifacts`) produces the
CLI/API-common on-disk artifacts for a completed run:

- ``0_quality/evidence_manifest.json`` — the gate's structured evidence records
  plus per-category group statuses and the gate decision (verdict, reasons,
  policy version). No analyst prose, no chain-of-thought.
- ``0_quality/gate_summary.md`` — a concise human-readable Data Quality summary
  derived only from the structured gate state.
- ``2_research/debate_trace.json`` — the deterministic Debate Evaluator decision
  trace (route, stop reason, round count, per-round metrics, budget/usage and
  estimated flags). Deliberately excludes the Bull/Bear readable prose so no
  chain-of-thought or hidden prompt is persisted.
- ``run_summary.json`` — a compact summary of the run (ticker, trade date, gate
  verdict, debate stop reason/round count, usage/budget and measured-vs-estimated
  flags, and the exported report paths).

Every string that reaches disk is passed through :func:`redact_secrets` so no
API key, token, or ``Bearer``/``sk-`` value is ever written. Optional-category
availability is derived deterministically from the gate state and the
multi-category policy (never parsed from analyst prose).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tradingagents.evidence.policy import OPTIONAL_CATEGORIES, MultiCategoryPolicy

# Anything that looks like a secret key/value pair, token, or bearer credential.
# Deliberately conservative: redact and never echo the matched value.
#
# Two kinds of pattern:
# - ``_WHOLE_SECRET_PATTERNS`` — the whole token is itself the credential
#   (``sk-...`` keys, ``AKIA...`` AWS keys), so the entire match is replaced.
# - ``_LABELED_SECRET_PATTERNS`` — the value is the credential but the trailing
#   field/label (``api_key=``, ``Bearer``, ``X-...-Key=``) is not; only the
#   credential substring is replaced so the surrounding context is preserved.
_SECRET_WHOLE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"(sk-[A-Za-z0-9_\-]{8,})",
        r"(AKIA[A-Z0-9]{16})",
    )
)

_SECRET_LABELED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}",
        r"(api[_-]?key\s*[=:]\s*)[A-Za-z0-9_\-\.]{8,}",
        r"(token\s*[=:]\s*)[A-Za-z0-9_\-\.]{8,}",
        r"(secret\s*[=:]\s*)[A-Za-z0-9_\-\.]{8,}",
        r"(X-[A-Za-z-]+-Key\s*[=:]\s*)[A-Za-z0-9_\-\.]{8,}",
    )
)


def _sub_labeled(match: re.Match[str]) -> str:
    """Keep the field/label (group 1) and redact only the credential value."""
    return match.group(1) + _SECRET_SENTINEL


_SECRET_SENTINEL = "[REDACTED]"


def redact_secrets(text: Any) -> Any:
    """Return ``text`` with any secret-looking substring replaced by ``[REDACTED]``.

    Applies to strings; other JSON-safe values are returned unchanged. The match
    is conservative (we only replace the credential-looking substring, never the
    field name), so the surrounding context is preserved for an audit.
    """
    if isinstance(text, str):
        for pattern in _SECRET_WHOLE_PATTERNS:
            text = pattern.sub(_SECRET_SENTINEL, text)
        for pattern in _SECRET_LABELED_PATTERNS:
            text = pattern.sub(_sub_labeled, text)
        return text
    if isinstance(text, dict):
        return {k: redact_secrets(v) for k, v in text.items()}
    if isinstance(text, (list, tuple)):
        return [redact_secrets(v) for v in text]
    return text


def _json_dumps(data: Any) -> str:
    """Deterministic, compact, ASCII-safe JSON with redaction applied."""
    return json.dumps(redact_secrets(data), indent=2, sort_keys=True)


def _group_statuses(final_state: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-category group statuses from the gate state (may be market-only).

    Always returns the four stable category statuses: the market category from
    the gate state (when present) plus an explicit deterministic unavailable
    result for each optional category that is absent (derived from the policy,
    never parsed from analyst prose).
    """
    raw = final_state.get("data_quality_group_statuses") or []
    statuses = [dict(g) for g in raw if isinstance(g, dict)] if isinstance(raw, list) else []

    # Merge the optional categories that are not already present.
    present = {s.get("category") for s in statuses}
    from tradingagents.evidence.gate import build_unavailable_category

    for category in OPTIONAL_CATEGORIES:
        if category not in present:
            statuses.append(build_unavailable_category(category).to_dict())

    # Stable ordering by category name for a deterministic artifact.
    statuses.sort(key=lambda s: str(s.get("category", "")))
    return statuses


def _evidence_manifest(final_state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``0_quality/evidence_manifest.json`` payload."""
    records = final_state.get("data_quality_evidence_records") or []
    decision = final_state.get("data_quality_gate_decision") or {}
    verdict = final_state.get("data_quality_verdict") or str(decision.get("decision", ""))
    return {
        "verdict": verdict,
        "gate_decision": dict(decision) if isinstance(decision, dict) else {},
        "category_statuses": _group_statuses(final_state),
        "evidence_records": [dict(r) for r in records if isinstance(r, dict)],
        "policy_version": str(decision.get("policy_version", "") or ""),
        "secret_redaction": _SECRET_SENTINEL,
    }


def _gate_summary_md(final_state: dict[str, Any]) -> str:
    """A concise Data Quality summary markdown derived from structured state only."""
    decision = final_state.get("data_quality_gate_decision") or {}
    verdict = final_state.get("data_quality_verdict") or str(decision.get("decision", ""))
    lines: list[str] = ["# Data Quality Gate Summary", ""]
    lines.append(f"Verdict: {verdict}.")
    if decision.get("decided_at"):
        lines.append(f"Decided at: {decision['decided_at']}.")
    if decision.get("policy_version"):
        lines.append(f"Policy version: {decision['policy_version']}.")
    reason = decision.get("human_readable_reason")
    if reason:
        lines.append(f"Reason: {reason}")
    limitations = decision.get("limitations") or []
    if limitations:
        lines.append("Limitations: " + "; ".join(str(x) for x in limitations) + ".")
    critical_ids = decision.get("critical_evidence_ids") or []
    if critical_ids:
        lines.append("Critical evidence IDs: " + ", ".join(str(x) for x in critical_ids) + ".")
    lines.append("")
    lines.append("## Category statuses")
    lines.append("")
    lines.append("| Category | Quality | Reason codes | Independent sources |")
    lines.append("| --- | --- | --- | --- |")
    for group in _group_statuses(final_state):
        category = group.get("category", "")
        quality = group.get("quality_status", "")
        reasons = ", ".join(group.get("reason_codes") or [])
        sources = group.get("independent_source_count", 0)
        lines.append(f"| {category} | {quality} | {reasons} | {sources} |")
    error = final_state.get("data_quality_error")
    if error:
        lines.append("")
        lines.append(f"Gate error: {error}")
    return "\n".join(lines) + "\n"


def _debate_trace(final_state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``2_research/debate_trace.json`` payload.

    Includes only the deterministic decision trace and round metrics — never the
    Bull/Bear readable prose (chain-of-thought / hidden prompts are excluded).
    """
    decision = final_state.get("debate_termination_decision") or {}
    debate = final_state.get("investment_debate_state") or {}
    usage = final_state.get("debate_usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    trace_entries: list[dict[str, Any]] = []
    if isinstance(decision, dict):
        for entry in decision.get("trace") or []:
            if isinstance(entry, dict):
                trace_entries.append(dict(entry))
    round_metrics = [dict(r) for r in (debate.get("round_metrics") or []) if isinstance(r, dict)]
    budget = debate.get("budget") or {}
    if not isinstance(budget, dict):
        budget = {}
    return {
        "route": str(decision.get("route", "") or ""),
        "stop_reason": str(decision.get("stop_reason", "") or ""),
        "round_count": len(round_metrics),
        "trace": trace_entries,
        "round_metrics": round_metrics,
        "budget": dict(budget),
        "usage": dict(usage),
        "measured_vs_estimated": {
            "estimated": bool(usage.get("estimated", False)),
            "budget_estimated": bool(budget.get("estimated", False)),
        },
    }


def _run_summary(
    final_state: dict[str, Any],
    ticker: str,
    save_path: Path,
    report_paths: dict[str, str],
) -> dict[str, Any]:
    """Build the ``run_summary.json`` payload."""
    decision = final_state.get("data_quality_gate_decision") or {}
    debate_decision = final_state.get("debate_termination_decision") or {}
    debate = final_state.get("investment_debate_state") or {}
    round_metrics = [r for r in (debate.get("round_metrics") or []) if isinstance(r, dict)]
    usage = final_state.get("debate_usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    return {
        "ticker": ticker,
        "trade_date": final_state.get("trade_date"),
        "gate_verdict": final_state.get("data_quality_verdict")
        or str(decision.get("decision", "") or ""),
        "gate_policy_version": str(decision.get("policy_version", "") or ""),
        "debate_stop_reason": str(debate_decision.get("stop_reason", "") or ""),
        "debate_round_count": len(round_metrics),
        "debate_route": str(debate_decision.get("route", "") or ""),
        "usage": dict(usage),
        "measured_vs_estimated": {
            "estimated": bool(usage.get("estimated", False)),
        },
        "report_paths": report_paths,
    }


def write_report_artifacts(
    final_state: dict[str, Any],
    ticker: str,
    save_path: Path,
    *,
    policy: MultiCategoryPolicy | None = None,
) -> dict[str, str]:
    """Write the Stage 2 report artifacts under ``save_path``.

    Returns a ``{logical_name: relative_path}`` mapping used to enrich the
    ``complete_report.md`` and the ``run_summary.json``. All JSON output is
    redacted (no secrets) and excludes any analyst prose / chain-of-thought.
    """
    save_path = Path(save_path)
    quality_dir = save_path / "0_quality"
    research_dir = save_path / "2_research"
    quality_dir.mkdir(parents=True, exist_ok=True)
    research_dir.mkdir(parents=True, exist_ok=True)

    # 0_quality/evidence_manifest.json
    manifest = _evidence_manifest(final_state)
    manifest_path = quality_dir / "evidence_manifest.json"
    manifest_path.write_text(_json_dumps(manifest), encoding="utf-8")

    # 0_quality/gate_summary.md
    summary_path = quality_dir / "gate_summary.md"
    summary_path.write_text(redact_secrets(_gate_summary_md(final_state)), encoding="utf-8")

    # 2_research/debate_trace.json
    trace = _debate_trace(final_state)
    trace_path = research_dir / "debate_trace.json"
    trace_path.write_text(_json_dumps(trace), encoding="utf-8")

    report_paths = {
        "evidence_manifest": "0_quality/evidence_manifest.json",
        "gate_summary": "0_quality/gate_summary.md",
        "debate_trace": "2_research/debate_trace.json",
    }

    # run_summary.json
    run_summary = _run_summary(final_state, ticker, save_path, report_paths)
    run_summary_path = save_path / "run_summary.json"
    run_summary_path.write_text(_json_dumps(run_summary), encoding="utf-8")

    return {
        "evidence_manifest": str(manifest_path.relative_to(save_path)),
        "gate_summary": str(summary_path.relative_to(save_path)),
        "debate_trace": str(trace_path.relative_to(save_path)),
        "run_summary": str(run_summary_path.relative_to(save_path)),
    }


def build_data_quality_section(final_state: dict[str, Any]) -> str:
    """Markdown ``Data Quality`` section for ``complete_report.md`` (structured only)."""
    return "## Data Quality\n\n" + _gate_summary_md(final_state).split("\n", 1)[1].rstrip()


def build_run_summary_section(
    final_state: dict[str, Any],
    ticker: str,
    report_paths: dict[str, str],
) -> str:
    """Markdown ``Run Summary`` section for ``complete_report.md`` (redacted)."""
    decision = final_state.get("data_quality_gate_decision") or {}
    debate_decision = final_state.get("debate_termination_decision") or {}
    debate = final_state.get("investment_debate_state") or {}
    round_metrics = [r for r in (debate.get("round_metrics") or []) if isinstance(r, dict)]
    usage = final_state.get("debate_usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    lines = [
        "## Run Summary",
        "",
        f"- Ticker: {ticker}",
        f"- Trade date: {final_state.get('trade_date')}",
        f"- Gate verdict: {final_state.get('data_quality_verdict') or str(decision.get('decision', ''))}",
        f"- Debate stop reason: {debate_decision.get('stop_reason', '')}",
        f"- Debate rounds completed: {len(round_metrics)}",
        f"- Usage: {usage.get('calls', 0)} calls, {usage.get('tokens', 0)} tokens, "
        f"{usage.get('seconds', 0.0)}s (estimated={bool(usage.get('estimated', False))})",
    ]
    if report_paths:
        lines.append("")
        lines.append("Artifacts:")
        for name, path in sorted(report_paths.items()):
            lines.append(f"- {name}: `{path}`")
    return "\n".join(lines) + "\n"
