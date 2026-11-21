"""Explicit metric formulas for the Phase 4A baseline comparison.

Every metric is a pure function with an explicit numerator and denominator.
Zero-denominator behavior is documented and returns ``None`` (never raises and
never fabricates a fractional value). Tests in
``tests/test_comparison_schemas.py`` pin each formula and its zero-denominator
case.

Formulas (authoritative):

- ``early_stop_rate = early_stopped / cases`` (per case: ``1.0`` if early
  stopped else ``0.0``).
- ``evidence_citation_coverage = valid_cited_evidence_count /
  total_eligible_evidence_ids``. The numerator is the count of **valid** cited
  evidence IDs (known, High/Medium, on-or-before-target, linked to a claim);
  the denominator is the count of eligible evidence IDs in the snapshot.
- ``false_strong_conclusion_rate = false_strong_conclusion_count /
  strong_conclusion_count``. ``strong_conclusion`` is an explicit
  machine-readable flag; ``false_strong`` is that flag ANDed with a
  gate/quality outcome that does not support a strong conclusion (gate verdict
  ``blocked`` or ``degraded``). It is never inferred from prose.
- ``traceability_mean`` = arithmetic mean of the human-entered per-dimension
  scores; ``None`` (status ``pending``) when no human score is recorded.

The outputs are *derived* values; raw measured/estimated input stays in
:class:`~tradingagents.comparison.schemas.CaseResult`.
"""

from __future__ import annotations

from tradingagents.comparison.schemas import CaseResult, TraceabilityStatus

# Gate verdicts that do NOT support a strong (unrestricted) conclusion.
_STRONG_UNSAFE_VERDICTS = frozenset({"blocked", "degraded"})


def ratio(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator`` as a float, or ``None`` on zero denominator."""
    if denominator <= 0:
        return None
    return numerator / denominator


def early_stop_rate(early_stopped: bool, cases: int = 1) -> float | None:
    return ratio(1 if early_stopped else 0, cases)


def evidence_citation_coverage(
    valid_cited_evidence_count: int, total_eligible_evidence_ids: int
) -> float | None:
    return ratio(valid_cited_evidence_count, total_eligible_evidence_ids)


def _is_false_strong(
    *,
    strong_conclusion: bool,
    gate_verdict: str,
    quality_status: str,
) -> bool:
    """True iff a strong conclusion is not supported by the gate/quality outcome.

    ``strong_conclusion`` is a machine-readable flag from the structured
    output, never inferred from prose. A strong conclusion is *false* when the
    gate verdict is blocked/degraded or the group quality is not High/Medium —
    i.e. the run claimed a strong conclusion it had no evidentiary right to.
    """
    if not strong_conclusion:
        return False
    if str(gate_verdict or "").strip().lower() in _STRONG_UNSAFE_VERDICTS:
        return True
    # Unknown quality is treated as NOT supporting a strong conclusion (fail
    # closed): we will not claim a strong conclusion on unverifiable standing,
    # consistent with INV-1/INV-3. An empty quality_status (not supplied) is
    # NOT itself a false-strong signal — only a real Low/Blocked quality is.
    quality = str(quality_status or "").strip()
    return bool(quality and quality not in ("High", "Medium"))


def false_strong_conclusion_rate(
    false_strong_count: int, strong_conclusion_count: int
) -> float | None:
    return ratio(false_strong_count, strong_conclusion_count)


def traceability_mean(scores: list[float | None]) -> float | None:
    """Arithmetic mean of human-entered scores; ``None`` when unscored."""
    values = [float(s) for s in scores if s is not None]
    if not values:
        return None
    return sum(values) / len(values)


def compute_case_aggregate(result: CaseResult):
    """Derive a :class:`CaseAggregate` from a single :class:`CaseResult`.

    Re-exported by :mod:`tradingagents.comparison.schemas` to avoid a
    circular import at module load; the actual calculation lives here.
    """
    from tradingagents.comparison.schemas import CaseAggregate

    valid_cited = len({str(x) for x in result.valid_cited_evidence_ids if x})
    coverage = evidence_citation_coverage(
        valid_cited, result.total_eligible_evidence_ids
    )
    false_strong_count = 1 if _is_false_strong(
        strong_conclusion=result.strong_conclusion,
        gate_verdict=result.gate_verdict,
        quality_status=result.quality_status,
    ) else 0
    strong_count = 1 if result.strong_conclusion else 0
    strong_rate = false_strong_conclusion_rate(false_strong_count, strong_count)
    # A traceability mean is reported ONLY for a fully SCORED result. A PENDING
    # result — even one carrying partial human scores — stays ``None`` so a
    # partial/headline score is never presented as an authoritative rating.
    scored_mean = (
        traceability_mean(result.traceability_scores)
        if result.traceability_status == TraceabilityStatus.SCORED
        else None
    )

    return CaseAggregate(
        identity=result.identity,
        strategy=result.strategy,
        llm_calls=result.llm_calls,
        tool_calls=result.tool_calls,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        elapsed_seconds=result.elapsed_seconds,
        debate_rounds=result.debate_rounds,
        early_stop_rate=early_stop_rate(result.early_stopped),
        evidence_citation_coverage=coverage,
        false_strong_conclusion_rate=strong_rate,
        strong_conclusion_count=strong_count,
        false_strong_conclusion_count=false_strong_count,
        traceability_mean=scored_mean,
        traceability_status=result.traceability_status,
        tool_usage_estimated=bool(result.estimated),
        consumed_calls_label=f"{result.llm_calls} calls / {result.total_tokens} tokens",
        stop_reason=result.stop_reason,
    )
