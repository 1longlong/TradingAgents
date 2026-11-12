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


def _validation_map(final_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The separate per-evidence validation map, normalized to JSON-safe dicts.

    The gate stores validation results keyed by ``evidence_id`` (value a list of
    ``ValidationResult`` dicts, or a single dict in some legacy paths). This
    normalizes to ``{evidence_id: [dict, ...]}`` with stable ordering and never
    invents a result for an evidence ID that has none.

    A PRESENT entry is authoritative even when it is *explicitly empty*: an entry
    that normalizes to ``[]`` (``{id: []}``, or a malformed value that cannot carry
    a validation) is kept as ``{id: []}`` so
    :func:`_records_with_validations` overrides a stale embedded
    ``validation_results`` instead of reviving a cleared ``passed`` check. Only an
    ABSENT entry is omitted, which keeps the legacy embedded fallback.
    """
    raw = final_state.get("data_quality_validation_results") or {}
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for evidence_id in sorted(raw, key=str):
        value = raw[evidence_id]
        if isinstance(value, dict):
            entries = [dict(value)]
        elif isinstance(value, (list, tuple)):
            entries = [dict(v) for v in value if isinstance(v, dict)]
        else:
            # A malformed present value cannot carry a validation; it is treated
            # as an authoritative empty list, never a fall-through to embedded.
            entries = []
        normalized[str(evidence_id)] = entries
    return normalized


def _normalize_embedded_validations(value: Any) -> list[dict[str, Any]]:
    """Normalize a record's embedded ``validation_results`` to a list of dicts.

    Accepts a list of dicts (the canonical embedded form) or a single dict (a
    legacy embedded form); anything else normalizes to an empty list. The order
    is preserved (it is the record's own recorded order), never reordered.
    """
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(v) for v in value if isinstance(v, dict)]
    return []


def _records_with_validations(
    records: list[Any],
    validation_map: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Attach each record's own validations (by evidence ID) to the export.

    Association is strictly by ``evidence_id``:

    - When the authoritative separate map has an entry for this record's ID, that
      entry is used (the map is the gate's own per-evidence view).
    - When the map has no entry, the record's **own embedded**
      ``validation_results`` are preserved and normalized — a legitimate
      legacy/embedded validation is never dropped just because the separate map
      is absent.
    - Another record's results are never attached, and nothing is fabricated: a
      record with neither a map entry nor embedded validations gets ``[]``.

    Validation order inside an entry is the authoritative (map) or recorded
    (embedded) order and is never reordered here.
    """
    out: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        item = dict(record)
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id in validation_map:
            item["validation_results"] = list(validation_map[evidence_id])
        else:
            item["validation_results"] = _normalize_embedded_validations(
                item.get("validation_results")
            )
        out.append(item)
    return out


def _evidence_manifest(final_state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``0_quality/evidence_manifest.json`` payload."""
    records = final_state.get("data_quality_evidence_records") or []
    decision = final_state.get("data_quality_gate_decision") or {}
    verdict = final_state.get("data_quality_verdict") or str(decision.get("decision", ""))
    validation_map = _validation_map(final_state)
    return {
        "verdict": verdict,
        "gate_decision": dict(decision) if isinstance(decision, dict) else {},
        "category_statuses": _group_statuses(final_state),
        "evidence_records": _records_with_validations(records, validation_map),
        # The separate validation map is exported verbatim (JSON-safe, sorted) so
        # the audit preserves the gate's own per-evidence view, not only the copy
        # attached to each record.
        "validation_results_by_evidence_id": validation_map,
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
    cap = _confidence_cap_block(final_state)
    lines.append("")
    if cap.get("cap_applies"):
        lines.append(
            f"Confidence ceiling: {cap.get('cap')} (degraded run; "
            f"policy v{cap.get('policy_version')}; engineering constraint, not a "
            f"calibrated probability). Capped entries: {cap.get('capped_count', 0)}; "
            f"quarantined: {cap.get('quarantined_count', 0)}."
        )
    else:
        lines.append(
            f"Confidence ceiling: not applied (verdict={cap.get('verdict')}; "
            f"policy v{cap.get('policy_version')})."
        )
    return "\n".join(lines) + "\n"


def _participation_summary(final_state: dict[str, Any]) -> dict[str, Any]:
    """Authoritative, deterministic participation for the report (INV-6/NFR-AUD-001).

    Derived only from structured debate state; a legacy prose-only history is
    reported as unverified rather than promoted to executed.
    """
    from tradingagents.debate.participation import summarize_participation

    debate = final_state.get("investment_debate_state") or {}
    if not isinstance(debate, dict):
        debate = {}
    decision = final_state.get("debate_termination_decision")
    gate = final_state.get("data_quality_verdict")
    if not gate:
        gate_decision = final_state.get("data_quality_gate_decision") or {}
        if isinstance(gate_decision, dict):
            gate = gate_decision.get("decision")
    return summarize_participation(
        debate,
        debate_termination_decision=decision if isinstance(decision, dict) else None,
        gate_verdict=str(gate) if gate else None,
    )


def _redacted_claim_validation(summary: dict[str, Any]) -> dict[str, Any]:
    """A JSON-safe, secret-redacted view of the exact-claim validation summary.

    Carries only the allow-listed per-claim descriptors (status/reason/metric/
    date/value/unit/ids) the evaluator already produced — never raw model prose.
    Malformed entries are skipped (fail safe), never coerced.
    """
    out: dict[str, list[dict[str, Any]]] = {"verified": [], "rejected": [], "unverified": []}
    for key in ("verified", "rejected", "unverified"):
        entries = summary.get(key) if isinstance(summary, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            out[key].append(
                {
                    "status": redact_secrets(str(entry.get("status", ""))),
                    "reason": redact_secrets(str(entry.get("reason", ""))),
                    "metric": redact_secrets(str(entry.get("metric", ""))),
                    "date_role": redact_secrets(str(entry.get("date_role", ""))),
                    "date": redact_secrets(str(entry.get("date", ""))),
                    "value": redact_secrets(str(entry.get("value", ""))),
                    "unit": redact_secrets(str(entry.get("unit", ""))),
                    "evidence_ids": [
                        redact_secrets(str(e)) for e in (entry.get("evidence_ids") or [])
                    ],
                }
            )
    # ADR-010 amendment: pass through the standalone typed-claim coverage block
    # (deterministic counts only, no prose) so an out-of-marker typed claim is never
    # an invisible empty success in the exported trace.
    coverage = summary.get("coverage") if isinstance(summary, dict) else None
    if isinstance(coverage, dict) and coverage:
        turns = coverage.get("turns")
        out["coverage"] = {
            "typed_lines_found": int(coverage.get("typed_lines_found", 0) or 0),
            "parsed": int(coverage.get("parsed", 0) or 0),
            "unparseable": int(coverage.get("unparseable", 0) or 0),
            "source": redact_secrets(str(coverage.get("source", ""))),
            "turns": [
                {
                    "speaker": redact_secrets(str(t.get("speaker", ""))),
                    "typed_lines_found": int(t.get("typed_lines_found", 0) or 0),
                    "parsed": int(t.get("parsed", 0) or 0),
                    "unparseable": int(t.get("unparseable", 0) or 0),
                }
                for t in turns
                if isinstance(t, dict)
            ]
            if isinstance(turns, list)
            else [],
        }
    return out


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
    claim_validation = debate.get("claim_validation_summary") or {}
    if not isinstance(claim_validation, dict):
        claim_validation = {}
    return {
        "route": str(decision.get("route", "") or ""),
        "stop_reason": str(decision.get("stop_reason", "") or ""),
        "round_count": len(round_metrics),
        "participation": _participation_summary(final_state),
        "claim_validation": _redacted_claim_validation(claim_validation),
        "trace": trace_entries,
        "round_metrics": round_metrics,
        "budget": dict(budget),
        "usage": dict(usage),
        "usage_provenance": _usage_provenance(final_state),
        "measured_vs_estimated": {
            "estimated": bool(usage.get("estimated", False)),
            "budget_estimated": bool(budget.get("estimated", False)),
        },
    }


def _quality_counts(final_state: dict[str, Any]) -> dict[str, int]:
    """Count evidence records per quality tier (deterministic, from structured state).

    Only the quality statuses the records actually carry are counted; an absent
    or unknown status is counted under ``unknown`` rather than invented. Tiers
    are always present with an explicit ``0`` so a reader cannot mistake a
    missing key for a zero-quality run.
    """
    counts = {"High": 0, "Medium": 0, "Low": 0, "Blocked": 0, "unknown": 0}
    records = final_state.get("data_quality_evidence_records") or []
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            status = str(record.get("quality_status", "") or "")
            if status in counts:
                counts[status] += 1
            else:
                counts["unknown"] += 1
    return counts


def _single_identity(values: set[str]) -> tuple[str | None, bool]:
    """Return the one agreed value and an ambiguity flag.

    ``(value, False)`` when all records agree on a single value; ``(None, True)``
    when records disagree (ambiguous — do not silently pick a first identity);
    ``(None, False)`` when there is no value at all (genuinely absent).
    """
    if len(values) == 1:
        return next(iter(values)), False
    if len(values) > 1:
        return None, True
    return None, False


def _run_identity(final_state: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Identity descriptors derived from structured state (null when absent).

    ``run_id``/``asset_type``/``snapshot_id`` come from the evidence records when
    present. A value all records agree on is reported; a value the records
    *disagree* on is reported as ``None`` and flagged ``*_ambiguous: True`` rather
    than silently choosing a first identity; a genuinely absent value is ``None``
    and not flagged. The market adapter does **not** currently mint a
    ``snapshot_id``, so ``snapshot_id`` is normally ``None`` until an actual
    snapshot identity is recorded on the records.
    """
    records = final_state.get("data_quality_evidence_records") or []
    run_ids: set[str] = set()
    asset_types: set[str] = set()
    snapshot_ids: set[str] = set()
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("run_id"):
                run_ids.add(str(record["run_id"]))
            if record.get("asset_type"):
                asset_types.add(str(record["asset_type"]))
            # A distinct ``snapshot_id`` is honoured only when a record actually
            # carries it; the adapter does not mint one today.
            if record.get("snapshot_id"):
                snapshot_ids.add(str(record["snapshot_id"]))

    run_id, run_ambiguous = _single_identity(run_ids)
    asset_from_records, asset_ambiguous = _single_identity(asset_types)
    snapshot_id, snapshot_ambiguous = _single_identity(snapshot_ids)

    # An explicit top-level asset_type is authoritative and never ambiguous; a
    # record-level disagreement only matters when we must rely on the records.
    explicit_asset = final_state.get("asset_type")
    if explicit_asset:
        asset_type, asset_ambiguous = str(explicit_asset), False
    else:
        asset_type = asset_from_records

    return {
        "ticker": ticker,
        "asset_type": asset_type,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "run_id_ambiguous": run_ambiguous,
        "asset_type_ambiguous": asset_ambiguous,
        "snapshot_id_ambiguous": snapshot_ambiguous,
    }


def _usage_provenance(final_state: dict[str, Any]) -> dict[str, Any]:
    """Debate usage and its measured/estimated provenance, honestly labelled.

    Debate calls are reported separately from any total-run call count: the
    state only counts *debate* researcher calls, so a total-run count and
    tool-call count are explicitly unavailable (``None``) rather than conflated
    with the debate figure. Per-field provenance (``measured`` / ``provider`` /
    ``estimated`` / ``mixed`` / ``unavailable``) is surfaced from the recorded
    ``debate_usage.provenance`` so an estimate is never presented as measured.
    Input/output token splits are reported only when they are actually known; a
    split missing any contributing side (or flagged partial) is reported as
    ``None``/partial rather than as a complete provider total.
    """
    usage = final_state.get("debate_usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    provenance = usage.get("provenance") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    estimated = bool(usage.get("estimated", False))

    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    input_partial = bool(usage.get("input_tokens_partial") or provenance.get("input_tokens_partial"))
    output_partial = bool(usage.get("output_tokens_partial") or provenance.get("output_tokens_partial"))

    return {
        "debate_calls": int(usage.get("calls", 0) or 0),
        "debate_tokens": int(usage.get("tokens", 0) or 0),
        "debate_seconds": float(usage.get("seconds", 0.0) or 0.0),
        "estimated": estimated,
        "tokens_source": provenance.get("tokens"),
        "seconds_source": provenance.get("seconds"),
        "clock": usage.get("clock", "unavailable"),
        "failed_calls": int(usage.get("failed_calls", 0) or 0),
        "transport_attempts": usage.get("transport_attempts"),
        "tokens_conflict": bool(provenance.get("tokens_conflict")),
        "tokens_partial": bool(provenance.get("tokens_partial")),
        # Split counts are only a full provider total when not partial.
        "input_tokens": None if input_partial else input_tokens,
        "output_tokens": None if output_partial else output_tokens,
        "input_tokens_partial": input_partial,
        "output_tokens_partial": output_partial,
        "total_run_calls": None,
        "tool_calls": None,
        # ADR-009: the whole-run aggregate (all model-calling phases) and the real
        # execution identity, plus an explicit completeness. These are REPORTING
        # only — never a budget limit — and ``debate_*`` above remains the
        # debate-scoped subset. ``completeness`` is ``unknown`` when no phase was
        # accounted, so a reader never mistakes the debate figure for a full-run
        # total.
        "whole_run_usage": _whole_run_usage(final_state),
        "execution_run_id": final_state.get("run_id"),
        "unavailable_reason": (
            "total-run calls and tool calls are not tracked by the debate "
            "accounting; the whole_run_usage block reports every accounted model "
            "invocation (with completeness). debate calls are reported separately "
            "and must not be read as total-run calls. Token splits are "
            "provider-only and null when any contributing call lacked that side."
        ),
    }


def _whole_run_usage(final_state: dict[str, Any]) -> dict[str, Any]:
    """The whole-run usage block (per-phase + totals + completeness), JSON-safe.

    Absent a ``whole_run_usage`` state field (a legacy/pre-feature run) it reports
    ``completeness: unknown`` with zeroed totals — never a fabricated total.
    """
    block = final_state.get("whole_run_usage")
    if not isinstance(block, dict):
        return {
            "by_phase": {},
            "totals": {
                "calls": 0,
                "tokens": 0,
                "seconds": 0.0,
                "unknown_cost_calls": 0,
                "reserved_unconfirmed_calls": 0,
                "reserved_estimated_tokens": 0,
                "reserved_estimated_seconds": 0.0,
            },
            "completeness": "unknown",
            "unresolved_invocations": 0,
            "reserved_unconfirmed_calls": 0,
            "settled_calls": 0,
            "reserved_unconfirmed": [],
        }
    return block


def _confidence_cap_block(final_state: dict[str, Any]) -> dict[str, Any]:
    """The versioned ADR-011 confidence-cap summary (verdict recomputed)."""
    try:
        from tradingagents.debate.confidence_policy import confidence_cap_summary

        return confidence_cap_summary(final_state)
    except Exception:  # noqa: BLE001 — a report must never crash on this block
        return {
            "verdict": "blocked",
            "policy_version": "",
            "cap": None,
            "cap_applies": False,
            "entry_count": 0,
            "capped_count": 0,
            "quarantined_count": 0,
            "entries": [],
            "note": "confidence cap summary unavailable",
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
    identity = _run_identity(final_state, ticker)
    return {
        "ticker": identity["ticker"],
        "trade_date": final_state.get("trade_date"),
        "run_id": identity["run_id"],
        "asset_type": identity["asset_type"],
        "snapshot_id": identity["snapshot_id"],
        # True when evidence records disagree on the value; the value itself is
        # then None (ambiguous), never a silently chosen first identity.
        "identity_ambiguous": {
            "run_id": identity["run_id_ambiguous"],
            "asset_type": identity["asset_type_ambiguous"],
            "snapshot_id": identity["snapshot_id_ambiguous"],
        },
        "gate_verdict": final_state.get("data_quality_verdict")
        or str(decision.get("decision", "") or ""),
        "gate_policy_version": str(decision.get("policy_version", "") or ""),
        "quality_counts": _quality_counts(final_state),
        "debate_stop_reason": str(debate_decision.get("stop_reason", "") or ""),
        "debate_round_count": len(round_metrics),
        "debate_route": str(debate_decision.get("route", "") or ""),
        "participation": _participation_summary(final_state),
        "usage": dict(usage),
        "usage_provenance": _usage_provenance(final_state),
        # ADR-009: whole-run totals (all phases) and the real execution identity,
        # explicitly separate from the debate-scoped ``usage`` above.
        "whole_run_usage": _whole_run_usage(final_state),
        "execution_run_id": final_state.get("run_id"),
        # ADR-011: the versioned confidence-cap audit + policy (recomputed from the
        # authoritative gate verdict, never trusted from a state-supplied value).
        "confidence_cap": _confidence_cap_block(final_state),
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


def _identity_md(value: str | None, ambiguous: bool) -> str:
    """Render an identity value for markdown, flagging ambiguity honestly."""
    if ambiguous:
        return "unavailable (records disagree)"
    return value if value is not None else "unavailable"


def _whole_run_usage_md(block: dict[str, Any]) -> str:
    """A Markdown line summarizing the whole-run usage block with completeness.

    The token source labels the AGGREGATE provenance (``provider`` / ``estimated``
    / ``mixed``): a total mixing provider-exact and estimated/unknown calls is
    ``mixed`` and is never presented as an exact provider total (ADR-009
    amendment). ``mixed`` is report-only and never a per-call source.
    """
    totals = (block or {}).get("totals") or {}
    completeness = (block or {}).get("completeness", "unknown")
    unknown = int(totals.get("unknown_cost_calls", 0) or 0)
    reserved = int((block or {}).get("reserved_unconfirmed_calls", 0) or 0)
    unreadable = bool((block or {}).get("accounting_unreadable"))
    tokens_source = totals.get("tokens_source")
    return (
        f"- Whole-run usage: {int(totals.get('calls', 0) or 0)} calls, "
        f"{int(totals.get('tokens', 0) or 0)} tokens, "
        f"{float(totals.get('seconds', 0.0) or 0.0)}s "
        f"(completeness={completeness}, tokens_source={tokens_source}, "
        f"unknown_cost_calls={unknown}, "
        f"reserved_unconfirmed_calls={reserved}, accounting_unreadable={unreadable}; "
        "all model-calling phases; reporting only, not a budget limit)"
    )


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
    identity = _run_identity(final_state, ticker)
    provenance = _usage_provenance(final_state)
    participation = _participation_summary(final_state)
    skip_reason = participation.get("skip_reason") or participation.get("stop_reason") or "n/a"
    lines = [
        "## Run Summary",
        "",
        f"- Ticker: {ticker}",
        f"- Trade date: {final_state.get('trade_date')}",
        f"- Run id: {_identity_md(identity['run_id'], identity['run_id_ambiguous'])}",
        f"- Asset type: {_identity_md(identity['asset_type'], identity['asset_type_ambiguous'])}",
        f"- Snapshot id: {_identity_md(identity['snapshot_id'], identity['snapshot_id_ambiguous'])}",
        f"- Gate verdict: {final_state.get('data_quality_verdict') or str(decision.get('decision', ''))}",
        f"- Debate stop reason: {debate_decision.get('stop_reason', '')}",
        f"- Debate participation: status={participation.get('status')}, "
        f"executed={participation.get('executed_speakers') or []}, "
        f"missing={participation.get('missing_speakers') or []}, "
        f"skipped={participation.get('skipped_speakers') or []}, "
        f"skip_reason={skip_reason}",
        f"- Debate rounds completed: {len(round_metrics)}",
        f"- Debate usage: {provenance['debate_calls']} calls, {provenance['debate_tokens']} tokens, "
        f"{provenance['debate_seconds']}s (tokens={provenance['tokens_source']}, "
        f"seconds={provenance['seconds_source']}, estimated={provenance['estimated']}; "
        "debate calls only, not total-run calls)",
        _whole_run_usage_md(provenance["whole_run_usage"]),
    ]
    if report_paths:
        lines.append("")
        lines.append("Artifacts:")
        for name, path in sorted(report_paths.items()):
            lines.append(f"- {name}: `{path}`")
    return "\n".join(lines) + "\n"
