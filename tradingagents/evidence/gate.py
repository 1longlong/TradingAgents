"""GateDecision generation for the Data Quality Gate.

The gate turns a set of per-category :class:`~tradingagents.evidence.models.EvidenceGroupQuality`
objects into a single :class:`~tradingagents.evidence.models.GateDecision`
verdict and the routing it implies.

Verdict precedence (authoritative):

1. **blocked** — any critical group is ``Blocked``, or there is **no** group
   evidence at all (empty input fails closed and can never look ``normal``).
2. **degraded** — any important group is ``Low``, or coverage across the
   evaluated (critical + important) groups is insufficient (not ``High``/
   ``Medium``).
3. **normal** — otherwise (supporting groups are ignored by the gate).

The gate is injectable on ``decided_at`` for deterministic tests, and it always
preserves limitations, reason codes, critical evidence IDs, the human-readable
reason, and the policy version. **Gate exceptions fail closed** (they raise
rather than silently returning ``normal``): an internal error must never let a
low-quality run pass as if it were normal.

Determinism: group, evidence, and reason outputs are sorted deterministically,
so identical inputs always produce identical outputs regardless of insertion
order. Supplied ``decided_at`` timestamps are validated as ISO-8601.
"""

from __future__ import annotations

from datetime import datetime, timezone

from tradingagents.evidence.models import (
    Criticality,
    EvidenceGroupQuality,
    GateDecision,
    GateVerdict,
    QualityStatus,
)
from tradingagents.evidence.policy import (
    CATEGORY_MARKET,
    DEFAULT_MULTI_CATEGORY_POLICY,
    REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE,
    MarketPolicy,
    MultiCategoryPolicy,
)

_LIM_BLOCKED = "Blocked: critical evidence failure; debate skipped."
_LIM_DEGRADED = "Degraded: confidence capped; limitations apply."
_LIM_NORMAL = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_iso(value: str) -> None:
    """Raise ``ValueError`` if ``value`` is not a valid ISO-8601 timestamp."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"decided_at must be a non-empty ISO-8601 string, got {value!r}")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"decided_at must be an ISO-8601 timestamp, got {value!r}") from exc


def _evaluated(groups: list[EvidenceGroupQuality]) -> list[EvidenceGroupQuality]:
    return [
        group
        for group in groups
        if group.criticality in (Criticality.CRITICAL, Criticality.IMPORTANT)
    ]


def _critical_group_blocked(groups: list[EvidenceGroupQuality]) -> bool:
    return any(
        group.criticality == Criticality.CRITICAL
        and group.quality_status == QualityStatus.BLOCKED
        for group in groups
    )


def _coverage_insufficient(groups: list[EvidenceGroupQuality]) -> bool:
    evaluated = _evaluated(groups)
    if not evaluated:
        # No critical/important coverage at all => insufficient (fail closed).
        return True
    return any(
        group.quality_status not in (QualityStatus.HIGH, QualityStatus.MEDIUM)
        for group in evaluated
    )


def _any_important_low(groups: list[EvidenceGroupQuality]) -> bool:
    return any(
        group.criticality == Criticality.IMPORTANT
        and group.quality_status == QualityStatus.LOW
        for group in groups
    )


def _critical_evidence_ids(groups: list[EvidenceGroupQuality]) -> list[str]:
    ids: list[str] = []
    for group in groups:
        if group.criticality == Criticality.CRITICAL and group.quality_status != QualityStatus.HIGH:
            ids.extend(group.evidence_ids)
    return sorted(set(ids))


def _reason_codes(groups: list[EvidenceGroupQuality]) -> list[str]:
    codes: list[str] = []
    for group in groups:
        codes.extend(group.reason_codes)
    return sorted(set(codes))


def _reason_text(groups: list[EvidenceGroupQuality], verdict: GateVerdict) -> str:
    codes = _reason_codes(groups)
    if verdict == GateVerdict.BLOCKED:
        return "Gate blocked: " + "; ".join(codes) + "."
    if verdict == GateVerdict.DEGRADED:
        return "Gate degraded: " + "; ".join(codes) + "."
    return "Gate normal."


def build_gate_decision(
    group_statuses: list[EvidenceGroupQuality],
    *,
    decided_at: str | None = None,
    policy: MarketPolicy | None = None,
) -> GateDecision:
    """Build a :class:`GateDecision` from the per-category quality.

    Args:
        group_statuses: One :class:`EvidenceGroupQuality` per evaluated category.
        decided_at: Optional deterministic timestamp (ISO-8601). Defaults to the
            current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``.
        policy: Deterministic policy (provides ``policy_version``).

    Returns:
        A ``GateDecision`` with the verdict and routing. Raises on internal
        inconsistency rather than silently returning ``normal`` (fail closed).
        Empty input produces a ``blocked`` decision.

    Raises:
        ValueError: If a ``group_statuses`` entry is not an
            :class:`EvidenceGroupQuality`, or if ``decided_at`` is supplied but
            not a valid ISO-8601 timestamp (guards against a misconfigured gate
            silently passing or emitting a malformed timestamp).
    """
    policy = policy or MarketPolicy()
    groups = list(group_statuses)
    for entry in groups:
        if not isinstance(entry, EvidenceGroupQuality):
            raise ValueError(
                "gate inputs must be EvidenceGroupQuality, got "
                f"{type(entry).__name__}"
            )

    if decided_at is not None:
        _validate_iso(decided_at)

    if not groups:
        # Fail closed: no evidence must never look normal.
        verdict = GateVerdict.BLOCKED
        limitation = _LIM_BLOCKED
    elif _critical_group_blocked(groups):
        verdict = GateVerdict.BLOCKED
        limitation = _LIM_BLOCKED
    elif _any_important_low(groups) or _coverage_insufficient(groups):
        verdict = GateVerdict.DEGRADED
        limitation = _LIM_DEGRADED
    else:
        verdict = GateVerdict.NORMAL
        limitation = _LIM_NORMAL

    # Deterministic ordering of group outputs.
    groups_sorted = sorted(groups, key=lambda g: (g.category, g.quality_status.value))

    return GateDecision(
        decision=verdict,
        decided_at=decided_at if decided_at is not None else _now_iso(),
        group_statuses=groups_sorted,
        critical_evidence_ids=_critical_evidence_ids(groups_sorted),
        limitations=[limitation] if limitation else [],
        reason_codes=_reason_codes(groups_sorted),
        human_readable_reason=_reason_text(groups_sorted, verdict),
        policy_version=policy.policy_version,
    )


# ---------------------------------------------------------------------------
# Stage 2: multi-category gate (market critical + optional categories)
# ---------------------------------------------------------------------------


def build_unavailable_category(
    category: str,
    *,
    reason: str = REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE,
    reasons: list[str] | None = None,
    policy_version: str = "1.0",
    message: str | None = None,
) -> EvidenceGroupQuality:
    """Build an explicit, deterministic ``unavailable``/``insufficient`` category.

    This is the honest Stage 2 result for a category whose trustworthy
    structured evidence is **not** available (for example ``fundamentals``,
    ``news``, or ``sentiment``, which only persist prose reports in this
    codebase and must never be parsed for factual evidence). It carries a stable
    reason code, the source count as ``0``, and a clear human-readable message.
    It never fabricates a source, date, unit, or confidence.

    Args:
        category: The stable category name.
        reason: The primary reason code (defaults to the no-structured-source
            code; pass ``REASON_INSUFFICIENT_STRUCTURED_EVIDENCE`` on a degraded
            path).
        reasons: Optional additional reason codes merged in (deduplicated,
            ordered).
        policy_version: The category policy version that produced this result.
        message: Optional override of the human-readable reason; default states
            no trustworthy structured evidence is available.

    Returns:
        An ``EvidenceGroupQuality`` with ``quality_status=Low``, ``criticality``
        left to the caller to set via the `.criticality` argument in a richer
        builder when needed, source counts of ``0``, and the stable reason code.
    """
    effective = {reason}
    effective.update(reasons or [])
    codes = sorted(c for c in effective if c)
    return EvidenceGroupQuality(
        category=category,
        quality_status=QualityStatus.LOW,
        criticality=Criticality.IMPORTANT,
        evidence_ids=[],
        source_count=0,
        independent_source_count=0,
        reason_codes=codes,
        human_readable_reason=(
            message
            or "Unavailable: no trustworthy structured "
            f"evidence for category '{category}'."
        ),
    )


def _market_group(groups: list[EvidenceGroupQuality]) -> EvidenceGroupQuality | None:
    """The single market/critical group, or ``None`` if there is no criticality
    evidence for the market category."""
    for group in groups:
        if group.category == CATEGORY_MARKET:
            return group
    return None


def _has_critical_group(groups: list[EvidenceGroupQuality]) -> bool:
    """True iff at least one group has the CRITICAL role (markets fail closed)."""
    return any(g.criticality == Criticality.CRITICAL for g in groups)


def build_multi_category_gate_decision(
    group_statuses: list[EvidenceGroupQuality],
    *,
    decided_at: str | None = None,
    policy: MultiCategoryPolicy | None = None,
) -> GateDecision:
    """Build a :class:`GateDecision` over multiple categories (Stage 2).

    Precedence (authoritative, over the multi-category gate):

    1. **blocked** — a CRITICAL (market) group is ``Blocked``, or no
       CRITICAL/market group is present at all (fail closed: a run with no
       verified market ground truth can never look normal).
    2. **degraded** — the CRITICAL/market group is not ``High``/``Medium``, any
       OPTIONAL category is ``Low`` **and** its policy says
       ``degrade_on_unavailable``, or the evaluated critical coverage is
       otherwise insufficient. Optional categories may never block.
    3. **normal** — otherwise.

    ``critical_evidence_ids`` and ``reason_codes`` are collected from all groups.
    Optional categories that are unavailable (a ``Low``/no-source group) degrade
    the verdict under the policy but never escalate it to ``blocked``.

    Legacy compatibility: the original single-category :func:`build_gate_decision`
    is unchanged; this is the Stage 2 variant that additionally understands the
    optional-category role model.

    Args:
        group_statuses: One :class:`EvidenceGroupQuality` per evaluated category.
        decided_at: Optional deterministic ISO-8601 timestamp. Defaults to now.
        policy: The :class:`MultiCategoryPolicy` bundle.

    Returns:
        A ``GateDecision`` carrying the verdict, sorted group statuses, the
        critical evidence IDs, reason codes, and the policy version. Raises on
        internal inconsistency rather than silently returning ``normal``.

    Raises:
        ValueError: If a ``group_statuses`` entry is not an
            :class:`EvidenceGroupQuality`, or if ``decided_at`` is supplied but
            not a valid ISO-8601 timestamp.
    """
    policy = policy or DEFAULT_MULTI_CATEGORY_POLICY
    groups = list(group_statuses)
    for entry in groups:
        if not isinstance(entry, EvidenceGroupQuality):
            raise ValueError(
                "multi-category gate inputs must be EvidenceGroupQuality, "
                f"got {type(entry).__name__}"
            )
    if decided_at is not None:
        _validate_iso(decided_at)

    market = _market_group(groups)
    has_critical = _has_critical_group(groups)

    if market is None or not has_critical or market.quality_status == QualityStatus.BLOCKED:
        verdict = GateVerdict.BLOCKED
        limitation = _LIM_BLOCKED
    elif market.quality_status not in (QualityStatus.HIGH, QualityStatus.MEDIUM):
        # Market is Low or otherwise not adequate: degrade the whole run.
        verdict = GateVerdict.DEGRADED
        limitation = _LIM_DEGRADED
    elif _optional_degrade_requested(groups, policy):
        verdict = GateVerdict.DEGRADED
        limitation = _LIM_DEGRADED
    else:
        verdict = GateVerdict.NORMAL
        limitation = _LIM_NORMAL

    groups_sorted = sorted(groups, key=lambda g: (g.category, g.quality_status.value))

    return GateDecision(
        decision=verdict,
        decided_at=decided_at if decided_at is not None else _now_iso(),
        group_statuses=groups_sorted,
        critical_evidence_ids=_critical_evidence_ids(groups_sorted),
        limitations=[limitation] if limitation else [],
        reason_codes=_reason_codes(groups_sorted),
        human_readable_reason=_reason_text(groups_sorted, verdict),
        policy_version=policy.policy_version,
    )


def _optional_degrade_requested(
    groups: list[EvidenceGroupQuality],
    policy: MultiCategoryPolicy,
) -> bool:
    """True iff an OPTIONAL category is unavailable and the policy degrades.

    A category that is present at ``Low``/no-source counts as unavailable. The
    policy's per-category ``degrade_on_unavailable`` flag decides whether that
    lowers the whole verdict. When the flag is False the category is treated as
    skipped (no blocks, no degrade), so a run that only lacks an optional
    category can still be ``normal``.
    """
    for group in groups:
        if group.criticality != Criticality.IMPORTANT:
            continue
        if group.quality_status not in (
            QualityStatus.LOW,
            QualityStatus.BLOCKED,
        ):
            continue
        category_policy = policy.optional.get(group.category)
        if category_policy is not None and category_policy.degrade_on_unavailable:
            return True
    return False
