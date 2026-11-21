"""Field-level routing of S2 structured analyst fields to downstream agents.

The market and fundamentals analysts emit typed reports (``MarketAnalystReport``
/ ``FundamentalsAnalystReport``) carrying ``invalidation`` conditions and a
``scenario_set``. Before this module those objects were rendered to markdown and
then discarded, so every downstream agent read the fields only as prose it had
to re-interpret.

This module turns the *typed* object into a small, role-specific markdown block
per consumer and per source. Each router returns ``{source: block}``; each
consumer substitutes the routed block for that source's full report via
:func:`routed_report`, so the agent reads only the fields relevant to its job
rather than re-reading the whole report:

* Bull   -> Bull scenario, then every invalidation condition (what would kill
            the bullish case), then weights when they are estimable.
* Bear   -> Bear scenario, then every invalidation condition, then weights when
            they are estimable.
* Risk   -> invalidation conditions, risk triggers, the Bear scenario, and the
            evidence basis behind each field.

Every block is prefixed with :func:`_shared_context` (stance, all key evidence,
figures/levels, risks, interpretation), so the role-specific part is additive
rather than a replacement for the evidence.

Deliberate non-behaviours (a bug here would be a silent quality regression):

* A ``NOT_ESTIMABLE`` scenario set never produces numbers. There is no default
  split, no ``33.3%`` placeholder, and no rescaling of partial weights.
* An invalidation condition is never relabelled a stop-loss, and a stop-loss is
  never presented as an invalidation.
* Missing fields stay missing: the block reports what is absent rather than
  inventing a threshold or an evidence basis.
* Weights are only printed when they are consistent (negative/out-of-range
  values are dropped exactly as the renderer drops them) and only when they sum
  to 100% (within 1 point), so the agent and the report agree. A set that sums
  to anything else is refused as an estimate and never rescaled.
* Substitution never loses key evidence. Because the routed block *replaces*
  the full report, every block also carries the shared context the full report
  had: the stance, every ``key_evidence`` item, ``risks`` when present, the
  analyst-specific figures/levels (``key_figures`` for fundamentals; levels are
  price structure and go into every market block), and the ``interpretation``
  paragraph. Routing decides which *role-specific* fields are added on top; it
  does not decide whether the evidence survives.
"""

from __future__ import annotations

from typing import Any

from tradingagents.agents.schemas import ScenarioStatus, ScenarioType

__all__ = [
    "bull_context_block",
    "bear_context_block",
    "risk_context_block",
    "has_s2_fields",
    "routed_report",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Attribute access that tolerates ``None`` and plain dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clean(value: Any) -> str:
    return (value or "").strip() if isinstance(value, str) else ""


def has_s2_fields(report: Any) -> bool:
    """True when a typed report actually carries S2 data worth routing."""
    if report is None:
        return False
    if _get(report, "invalidation"):
        return True
    scenario_set = _get(report, "scenario_set")
    return bool(scenario_set is not None and _get(scenario_set, "scenarios"))


def _usable_weight(weight: Any) -> float | None:
    """Mirror the renderer: a weight is usable only if it is a real number in
    ``[0, 100]``. Anything else is treated as absent, never coerced."""
    if isinstance(weight, bool):  # bool is an int subclass; not a weight
        return None
    if not isinstance(weight, (int, float)):
        return None
    if weight < 0 or weight > 100:
        return None
    return float(weight)


#: Mirror of the renderer's tolerance (``abs(total - 100) <= 0.5``, widened a
#: point) so a rounded 99.5 / 100.5 set is still shown while 150 is refused.
_WEIGHT_SUM_TOLERANCE = 1.0


def _scenarios(report: Any) -> dict[str, Any]:
    scenario_set = _get(report, "scenario_set")
    out: dict[str, Any] = {}
    for scenario in _get(scenario_set, "scenarios") or []:
        name = _get(scenario, "name")
        key = getattr(name, "value", name)
        if key is not None:
            out[str(key)] = scenario
    return out


def _weights_block(report: Any) -> str | None:
    """One line of estimable weights, or an explicit not-estimable line.

    Returns ``None`` only when the report carries no scenario set at all (so an
    older payload contributes no weights line to its routed block).
    """
    scenario_set = _get(report, "scenario_set")
    if scenario_set is None:
        return None

    status = _get(scenario_set, "status")
    by_name = _scenarios(report)
    ordered = [ScenarioType.BULL.value, ScenarioType.BASE.value, ScenarioType.BEAR.value]
    usable = {
        name: _usable_weight(_get(by_name[name], "weight"))
        for name in ordered
        if name in by_name
    }
    complete = bool(usable) and all(w is not None for w in usable.values())
    # A complete set whose weights sum to 150 is not an estimate, it is an
    # arithmetic error. Printing it as "the analyst's estimate" invited the
    # downstream agent to read impossible numbers as probabilities.
    consistent = complete and abs(sum(usable.values()) - 100.0) <= _WEIGHT_SUM_TOLERANCE

    if status is ScenarioStatus.ESTIMATED and consistent:
        parts = ", ".join(f"{name} {usable[name]:g}%" for name in ordered if name in usable)
        return f"Scenario weights (analyst estimate): {parts}."

    if status is ScenarioStatus.ESTIMATED and complete and not consistent:
        # Complete but inconsistent: refuse the numbers as probabilities, do not
        # rescale them, and do not silently drop them into the generic wording.
        return (
            "Scenario weights: the analyst supplied weights that do not sum to "
            "100%. Do not read them as probabilities and do not rescale them."
        )

    # Any other combination is not estimable: state it, print no numbers, and
    # never fall back to an equal split.
    return (
        "Scenario weights: not estimable from the available evidence. Do not "
        "assume an equal split or any specific probability."
    )


def _invalidation_block(report: Any, heading: str) -> list[str]:
    conditions = _get(report, "invalidation") or []
    if not conditions:
        return [
            f"{heading}: none stated this run. This is an absence, not a finding "
            "that the thesis cannot be invalidated."
        ]
    lines = [f"{heading}:"]
    for i, cond in enumerate(conditions, 1):
        signal = _clean(_get(cond, "observable_signal"))
        condition = _clean(_get(cond, "condition"))
        threshold = _clean(_get(cond, "threshold"))
        basis = _clean(_get(cond, "evidence_basis"))
        invalidates = _clean(_get(cond, "invalidates"))

        line = f"{i}. {condition or signal}"
        if signal and signal != condition:
            line += f" (observable signal: {signal})"
        if threshold:
            line += f" [threshold stated by the analyst: {threshold}]"
        else:
            line += " [no numeric threshold stated; read the signal, do not invent one]"
        if invalidates:
            line += f" -> invalidates: {invalidates}"
        if basis:
            line += f" (evidence basis: {basis})"
        lines.append(line)
    lines.append(
        "These are thesis-falsification conditions, not stop-losses: do not "
        "restate them as a price stop."
    )
    return lines


def _scenario_block(scenario: Any, label: str) -> list[str]:
    if scenario is None:
        return [f"{label} scenario: not provided this run."]
    lines = [f"{label} scenario:"]
    evidence = _clean(_get(scenario, "supporting_evidence"))
    triggers = _clean(_get(scenario, "trigger_conditions"))
    inval = _clean(_get(scenario, "invalidation_conditions"))
    if evidence:
        lines.append(f"- Supporting evidence: {evidence}")
    if triggers:
        lines.append(f"- Trigger conditions: {triggers}")
    if inval:
        lines.append(f"- Scenario invalidation: {inval}")
    if len(lines) == 1:
        lines.append("- (no detail fields were populated)")
    return lines


def _shared_context(report: Any) -> list[str]:
    """The context every routed block carries, regardless of role.

    A routed block *replaces* the full report, so anything here that is omitted
    is lost to that consumer, not merely deprioritised. These are the fields the
    requirement calls essential ("no loss of key evidence"): the stance, every
    key-evidence item verbatim, risks when the analyst stated any, the
    analyst-specific figures (``key_figures``) / price structure
    (``key_levels``), and the closing interpretation.

    Levels are labelled as price structure rather than thesis invalidation
    because the invalidation conditions are a separate, explicitly rendered
    block: a Bull reader must not mistake a support level for a falsification
    trigger, and vice versa.
    """
    lines: list[str] = []

    stance = _get(report, "stance")
    stance_text = _clean(getattr(stance, "value", stance))
    lines.append(f"**Stance:** {stance_text or 'Unknown'}")

    evidence = _get(report, "key_evidence") or []
    if evidence:
        lines.append("")
        lines.append("**Key evidence:**")
        for item in evidence:
            claim = _clean(_get(item, "claim"))
            quote = _clean(_get(item, "evidence"))
            source = _clean(_get(item, "source"))
            lines.append(f"- {claim} — {quote} ({source})")
    else:
        lines.append("")
        lines.append(
            "**Key evidence:** none stated this run. This is an absence, not a "
            "finding."
        )

    figures = _get(report, "key_figures") or []
    if figures:
        lines.append("")
        lines.append("**Key figures:**")
        for figure in figures:
            metric = _clean(_get(figure, "metric"))
            value = _clean(_get(figure, "value"))
            read = _clean(_get(figure, "read"))
            lines.append(f"- {metric}: {value} — {read}")

    levels = _get(report, "key_levels") or []
    if levels:
        lines.append("")
        lines.append("Key levels (price structure, not thesis invalidation):")
        for level in levels:
            label = _clean(_get(level, "label"))
            price = _clean(_get(level, "price"))
            why = _clean(_get(level, "why"))
            lines.append(f"- {label}: {price}" + (f" ({why})" if why else ""))

    risks = _get(report, "risks") or []
    if risks:
        lines.append("")
        lines.append("**Risks:**")
        for risk in risks:
            lines.append(f"- {_clean(risk)}")

    interpretation = _clean(_get(report, "interpretation"))
    if interpretation:
        lines.append("")
        lines.append(interpretation)

    return lines


# --------------------------------------------------------------------------- #
# public routing helper
# --------------------------------------------------------------------------- #
def routed_report(full_text: str, block: str | None, source: str) -> str:
    """Substitute a routed S2 block for a full report when one exists.

    When ``block`` is falsy the full report is returned unchanged so an
    old-prose-only run yields a byte-identical prompt. When a block exists the
    consumer gets only the routed fields instead of re-reading the whole
    report: that is the point of field routing, and it is what makes the
    change token-negative rather than token-positive.
    """
    if not block:
        return full_text
    return block.strip()


# --------------------------------------------------------------------------- #
# public routers
# --------------------------------------------------------------------------- #
def _routed_sources(
    market_report: Any, fundamentals_report: Any, render: Any
) -> dict[str, str]:
    """Map each source with typed fields to its block; omit sources without."""
    routed: dict[str, str] = {}
    for source, report in (
        ("market", market_report),
        ("fundamentals", fundamentals_report),
    ):
        if not has_s2_fields(report):
            continue
        body = [f"#### From the {source} report"]
        # Shared context first (stance, key evidence, figures/levels, risks,
        # interpretation), then the role-specific routing below it. Prepending
        # keeps the evidence where a reader looks for it while leaving the
        # Bull/Bear/risk-specific block intact and unchanged.
        body += _shared_context(report)
        body.append("")
        body += render(report)
        routed[source] = "\n".join(body)
    return routed


def bull_context_block(market_report: Any, fundamentals_report: Any) -> dict[str, str]:
    """Fields the Bull researcher needs, keyed by source (``{}`` if none)."""

    def render(report: Any) -> list[str]:
        lines = _scenario_block(_scenarios(report).get(ScenarioType.BULL.value), "Bull")
        lines += _invalidation_block(
            report, "Invalidation conditions (theses this bull case must survive)"
        )
        weights = _weights_block(report)
        if weights:
            lines.append(weights)
        return lines

    return _routed_sources(market_report, fundamentals_report, render)


def bear_context_block(market_report: Any, fundamentals_report: Any) -> dict[str, str]:
    """Fields the Bear researcher needs, keyed by source (``{}`` if none)."""

    def render(report: Any) -> list[str]:
        lines = _scenario_block(_scenarios(report).get(ScenarioType.BEAR.value), "Bear")
        lines += _invalidation_block(
            report, "Invalidation conditions (what would prove this bear case wrong)"
        )
        weights = _weights_block(report)
        if weights:
            lines.append(weights)
        return lines

    return _routed_sources(market_report, fundamentals_report, render)


def risk_context_block(market_report: Any, fundamentals_report: Any) -> dict[str, str]:
    """Fields the risk debators need, keyed by source (``{}`` if none)."""

    def render(report: Any) -> list[str]:
        lines = _invalidation_block(report, "Invalidation conditions")
        lines += _scenario_block(
            _scenarios(report).get(ScenarioType.BEAR.value), "Bear (downside)"
        )

        # Key levels are NOT rendered here any more: ``_shared_context`` puts the
        # labelled price structure in every block, so repeating it would double
        # this block's length and say the same thing twice.

        triggers = []
        for name, scenario in _scenarios(report).items():
            trigger = _clean(_get(scenario, "trigger_conditions"))
            if trigger:
                triggers.append(f"- {name}: {trigger}")
        if triggers:
            lines.append("Scenario risk triggers:")
            lines += triggers

        weights = _weights_block(report)
        if weights:
            lines.append(weights)
        return lines

    return _routed_sources(market_report, fundamentals_report, render)
