"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import (
    get_data_quality_context_from_state,
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.output_guard import (
    enforce_blocked_conclusion,
    enforce_trusted_boundary,
    is_blocked_run,
)
from tradingagents.agents.utils.rating import extract_rating
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.debate.claims import claim_summary_prompt_block
from tradingagents.debate.conflicts import build_conflict_summary
from tradingagents.debate.participation import (
    participation_prompt_block,
    summarize_participation,
)


def _enforce_non_directional_hold(plan_text: str) -> str:
    """Deterministically coerce a Research Manager plan to a non-directional Hold.

    Thin wrapper over :func:`tradingagents.agents.utils.output_guard.enforce_blocked_conclusion`
    (the shared guard) so the Research Manager, Trader, and Portfolio Manager
    all enforce the same blocked-run contract. The rationale is preserved
    unchanged; only the recommendation field is pinned.
    """
    return enforce_blocked_conclusion(plan_text, field="recommendation")


def _conflict_summary_block(investment_debate_state: dict) -> str:
    """A safe, structured conflict summary block for the Research Manager prompt.

    Consumes only the tracked conflicts (already validated and derived by the
    Debate Evaluator from structured metadata). It prefers the persisted
    ``conflict_summary`` (which also carries the resolve/escalate resolution
    notes) and recomputes ``open_blocking_count`` authoritatively from the
    conflicts it actually carries, so a stale count or an empty summary never
    misreports a blocking disagreement. It never embeds free-form analyst prose
    or chain-of-thought, and it returns an empty string when there are no
    tracked conflicts — so a bare action-only divergence (which is not a
    blocking conflict) is not presented as a fabricated disagreement. Safe even
    for a legacy state with no conflict fields.
    """
    conflicts_raw = investment_debate_state.get("conflicts") or []
    if not conflicts_raw:
        return ""
    try:
        # The persisted summary carries the resolution notes; recompute the
        # blocking count from the conflicts actually present (authoritative).
        summary = build_conflict_summary(
            conflict_summary = investment_debate_state.get("conflict_summary"),
            conflicts=conflicts_raw,
        )
    except Exception:  # noqa: BLE001 — never let a bad conflict block the manager
        return ""
    return summary.to_prompt_block()


def _partial_debate_sections(plan_text: str, participation: dict) -> tuple[str, str, str]:
    """Split a partial-debate plan into honest (recommendation, rationale, actions).

    The recommendation keeps the model's *valid* rating (existing 5-tier parser)
    but the rationale/actions are replaced by a deterministic statement of who
    actually executed. Unverified bilateral attribution from the raw model prose
    is never carried into the trusted plan.
    """
    rating = extract_rating(plan_text) or "Review"
    executed = participation.get("executed_speakers") or []
    missing = participation.get("missing_speakers") or []
    skipped = participation.get("skipped_speakers") or []
    evidence = participation.get("evidence")
    reason = participation.get("skip_reason") or participation.get("stop_reason") or "unknown"
    unverified = [
        speaker
        for speaker in ("Bull", "Bear")
        if participation.get(speaker.lower()) == "unverified"
    ]

    if executed:
        executed_line = f"Speakers confirmed executed: {', '.join(executed)}."
    elif unverified:
        executed_line = "No speaker is confirmed executed; execution status is unverified."
    else:
        executed_line = "No speaker executed a model call."
    if unverified:
        unverified_line = (
            f"Execution is UNVERIFIED for: {', '.join(unverified)} "
            "(no argument is attributed to them)."
        )
    else:
        unverified_line = ""
    if missing:
        missing_line = (
            f"No response from: {', '.join(missing)} (no argument is attributed to them)."
        )
    else:
        missing_line = ""
    if skipped:
        skip_line = f"Skipped for stop reason: {', '.join(skipped)} ({reason})."
    else:
        skip_line = f"Debate stop reason: {reason}."

    rationale = (
        f"This is a single-sided/incomplete debate. {executed_line} "
        f"{unverified_line} {missing_line} {skip_line} Assessment is limited to "
        f"the executed speaker(s)' evidence; it must NOT be read as a validated "
        f"two-sided debate. Execution evidence: {evidence}."
    ).replace("  ", " ").strip()
    actions = (
        "Proceed only with the evidence actually presented. Do not assume any "
        "counter-argument, conflict, approval, or position from a speaker that "
        "did not respond. If the single-sided evidence is insufficient to size a "
        "position, prefer the smaller/incomplete-evidence posture."
    )
    return rating, rationale, actions


def build_partial_debate_template(plan_text: str, participation: dict) -> str:
    """Deterministic trusted Research Manager plan for a partial/unknown debate.

    Preserves the existing valid rating policy (the model's 5-tier rating is
    kept via the shared parser) but replaces the narrative with an authoritative
    participation statement. The tradeoff is less narrative detail in the
    authoritative partial plan; the raw model prose is quarantined separately.
    """
    rating, rationale, actions = _partial_debate_sections(plan_text, participation)
    return (
        f"**Recommendation**: {rating}\n\n"
        f"**Rationale**: {rationale}\n\n"
        f"**Strategic Actions**: {actions}"
    )


def _quarantine_partial_raw(state, participation: dict, raw_text: str) -> str | None:
    """Write the raw partial-debate model narrative to a redacted audit file.

    This is NON-authoritative audit material only. The path is resolved via
    :func:`resolve_audit_paths` (prefers an explicit ``debate_partial_audit_path``,
    otherwise a safe default under the run's ``results_dir``/identity) so the real
    graph persists it even without an explicit override. The raw narrative is
    passed through :func:`redact_secrets` and is never placed in the trusted
    plan/report body or the memory body. Returns the path written, or ``None``.
    """
    from tradingagents.debate.failure_audit import resolve_audit_paths

    _, quarantine_path = resolve_audit_paths(state)
    if not quarantine_path:
        return None
    try:
        from pathlib import Path

        from tradingagents.report_artifacts import redact_secrets

        target = Path(quarantine_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        import json

        run_id = state.get("run_id")
        if not run_id and state.get("company_of_interest") and state.get("trade_date"):
            run_id = f"{state.get('trade_date')}/{state.get('company_of_interest')}"
        record = {
            "run_id": run_id,
            "trade_date": state.get("trade_date"),
            "status": participation.get("status"),
            "evidence": participation.get("evidence"),
            "executed_speakers": participation.get("executed_speakers"),
            "missing_speakers": participation.get("missing_speakers"),
            "skip_reason": participation.get("skip_reason"),
            "non_authoritative": True,
            "raw_model_narrative": redact_secrets(raw_text),
        }
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return str(target)
    except Exception:  # noqa: BLE001 — audit write failure never blocks the plan
        return None


def _summary_budget_denied_result(state, participation, blocked) -> dict:
    """Deterministic, auditable Research Manager result when the summary budget
    cannot be safely afforded (ADR-009).

    No model invocation is made. A blocked run stays a non-directional Hold; a
    non-blocked run returns an ``insufficient_evidence`` Hold with the auditable
    participation/stop reason, so the summary reserve is never exceeded
    unknowingly and an unknown failed structured attempt is never retried against
    the same reserve.
    """
    investment_debate_state = state["investment_debate_state"]
    rating = "Hold"
    reason = "summary_budget_unavailable"
    template = (
        f"**Recommendation**: {rating}\n\n"
        f"**Rationale**: The modelled summary was skipped to protect the reserved "
        f"summary budget ({reason}). This is a deterministic, evidence-limited "
        f"conclusion; it must not be read as a validated two-sided debate.\n\n"
        f"**Strategic Actions**: Hold. Re-run on fresh evidence; do not size a "
        f"position on an unsummarised debate."
    )
    new_state = {
        "judge_decision": template,
        "history": investment_debate_state.get("history", ""),
        "bear_history": investment_debate_state.get("bear_history", ""),
        "bull_history": investment_debate_state.get("bull_history", ""),
        "current_response": template,
        "count": investment_debate_state.get("count", 0),
    }
    for field_name in (
        "turns",
        "conflicts",
        "conflict_summary",
        "claim_validation_summary",
        "stances",
        "previously_cited_evidence_ids",
        "round_metrics",
        "metadata_parse_failed_count",
        "no_new_evidence_streak",
        "budget",
    ):
        if field_name in investment_debate_state:
            new_state[field_name] = investment_debate_state[field_name]
    return {
        "investment_debate_state": new_state,
        "investment_plan": template,
        "debate_termination_decision": state.get("debate_termination_decision"),
        "summary_budget_denied": True,
        "summary_budget_denied_reason": reason,
    }


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        history = state["investment_debate_state"].get("history", "")
        data_quality_context = get_data_quality_context_from_state(state)
        # Fail-closed: treat missing/malformed/inconsistent gate state as
        # blocked, matching the router and the shared output guard.
        blocked = is_blocked_run(state)
        data_quality_verdict = "blocked" if blocked else state.get("data_quality_verdict")

        investment_debate_state = state["investment_debate_state"]
        conflict_block = _conflict_summary_block(investment_debate_state)
        conflict_section = (
            f"\n\n{conflict_block}" if conflict_block else ""
        )
        # ADR-010: the deterministic exact-claim validation summary (verified vs
        # rejected vs unverified), prose-free. Empty when no exact claim was made.
        claim_summary = investment_debate_state.get("claim_validation_summary") or {}
        claim_block = (
            claim_summary_prompt_block(claim_summary)
            if isinstance(claim_summary, dict)
            else ""
        )
        claim_section = f"\n\n{claim_block}" if claim_block else ""

        # Authoritative participation truth (pure/structured). Used to make the
        # debate assumption explicit rather than asserting a two-sided debate.
        participation = summarize_participation(
            investment_debate_state,
            debate_termination_decision=state.get("debate_termination_decision"),
            gate_verdict="blocked" if blocked else state.get("data_quality_verdict"),
        )
        participation_block = participation_prompt_block(participation)
        full_two_sided = participation.get("status") == "both"
        if full_two_sided:
            debate_assumption = (
                "The debate always contains conflicting arguments; deciding which side is stronger is the job, so conflict alone is not a reason to Hold. "
                "Commit to the side with the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; "
                "do not manufacture a direction to appear decisive. Weigh the bull and bear cases on their merits, independent of which side spoke first or last."
            )
        else:
            debate_assumption = (
                "IMPORTANT — this is NOT a complete two-sided debate. Only the "
                "speaker(s) reported below actually responded; do NOT invent, "
                "assume, or attribute any argument, conflict, approval, position "
                "or rebuttal to a speaker that produced no response. Base the "
                "assessment only on the executed speaker(s)' evidence. You may "
                "still choose a direction if that evidence genuinely supports it; "
                "do not manufacture a bilateral conflict that did not occur."
            )

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

{data_quality_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

{debate_assumption}
{conflict_section}
{claim_section}

---

**{participation_block}**

**Debate History:**
{history}

## Output

Write these sections, in this order, starting with the recommendation on its own line:

- **Recommendation**: exactly one of Buy / Overweight / Hold / Underweight / Sell
- **Rationale**: which arguments decided it
- **Strategic Actions**: concrete steps for the trader, sized against a standard allocation

{NO_EXTERNAL_TOOLS}""" + get_language_instruction()

        if data_quality_verdict == "blocked":
            prompt += (
                "\n\nIMPORTANT — DEBATE WAS BLOCKED BY THE DATA QUALITY GATE. "
                "You did not receive a normal bull/bear debate; the standard "
                "debate was skipped because critical market data is missing or "
                "conflicting. This is an evidence-insufficient conclusion only. "
                "State explicitly: (1) the missing/conflicting critical data and "
                "the validation that completed, (2) the limited observations "
                "available, and (3) the conditions under which the block would "
                "clear on a later run. You MUST NOT produce a strong directional "
                "Buy or Sell — a Hold (or a clearly-hedged, evidence-insufficient "
                "call) is the correct outcome. Do not manufacture conviction "
                "you do not have. State the conclusion as insufficient evidence "
                "rather than inventing a direction."
            )
        elif data_quality_verdict == "degraded":
            prompt += (
                "\n\nIMPORTANT — DATA QUALITY IS DEGRADED. Confidence is capped "
                "by the limitations above: low-evidence claims cannot be "
                "decisive. Cite only the evidence IDs listed in the gate context. "
                "If the core view is supported only by Low evidence, choose Hold "
                "or explicitly state the evidence is insufficient rather than "
                "manufacturing direction. Do not overstate certainty."
            )

        # ADR-009: protect the summary reserve BEFORE every actual summary
        # attempt. If the safe reserve cannot be proven (unresolved spend, reserve
        # breach, or a disabled-but-unspent ledger), the manager uses a
        # deterministic auditable fallback instead of a model call — never
        # exceeding policy unknowingly and never retrying an unknown structured
        # failure against the same reserve.
        from tradingagents.debate.budget import resolve_budget_config_from_state
        from tradingagents.debate.researcher_accounting import (
            admit_summary_attempt,
            summary_affordable,
        )

        summary_config = resolve_budget_config_from_state(state, None)
        if not summary_affordable(state, summary_config):
            return _summary_budget_denied_result(state, participation, blocked)

        # ADR-011: cap the TYPED numeric confidence at full raw precision BEFORE
        # the lossy 2-decimal render, so a raw 0.954321 / 0.6000001 is genuinely
        # capped (and its exact raw recorded in the audit) instead of being masked
        # by the rounded rendered text.
        from tradingagents.debate.confidence_policy import cap_typed_confidence
        from tradingagents.debate.usage_capture import BudgetDeniedError

        typed_audit: list[dict] = []

        def _cap_typed(result):
            return cap_typed_confidence(
                result, state,
                source="Research Manager", boundary="research_manager_typed",
                sink=typed_audit,
            )

        try:
            investment_plan = invoke_structured_or_freetext(
                structured_llm,
                llm,
                prompt,
                render_research_plan,
                "Research Manager",
                # Re-check affordability before the fallback attempt so a failed
                # structured summary does not retry against the same reserve.
                affordable=lambda: summary_affordable(state, summary_config),
                # Atomically consume ONE call slot per actual summary attempt, so a
                # structured→free-text fallback cannot exceed the configured cap.
                admit_attempt=lambda: admit_summary_attempt(state, summary_config),
                sanitize_result=_cap_typed,
            )
        except BudgetDeniedError:
            return _summary_budget_denied_result(state, participation, blocked)
        # Retain the raw model narrative for potential quarantine (non-authoritative
        # audit only). It is never placed in the trusted plan/report/memory body.
        raw_model_text = investment_plan

        # The deterministic SAFE PARTIAL-DEBATE TEMPLATE applies whenever the
        # debate is NOT an authoritatively-confirmed two-sided debate — including
        # "unknown"/legacy states (no structured execution evidence either way).
        # The approved plan requires partial OR unknown -> deterministic trusted
        # template, so the trusted plan never carries unverified bilateral
        # attribution and there is no wrapper-only contradiction.
        partial_or_unknown = not full_two_sided
        if blocked:
            # Authoritative contract: a blocked run is always a non-directional
            # Hold. On a partial/unknown blocked run the trusted narrative is
            # replaced by the participation template so it cannot carry invented
            # absent-opponent attribution, THEN Hold is re-pinned on top.
            investment_plan = _enforce_non_directional_hold(investment_plan)
            if partial_or_unknown:
                investment_plan = build_partial_debate_template(investment_plan, participation)
                investment_plan = _enforce_non_directional_hold(investment_plan)
        elif partial_or_unknown:
            investment_plan = build_partial_debate_template(investment_plan, participation)

        # ADR-010: a REJECTED exact claim (valid ID, wrong date/value/unit) must not
        # survive in the trusted plan as a verified fact. This is a narrow,
        # line-scoped redaction of the wrong fact only (never a global Hold); a
        # verified claim or the qualitative prose is left untouched. This ALSO
        # freshly validates any exact fact the manager itself wrote (a downstream
        # hallucination is contained at this boundary too).
        investment_plan = enforce_trusted_boundary(investment_plan, state)

        # ADR-011: cap any explicit confidence-labelled numeric in the trusted
        # plan on a degraded run (raw value quarantined in the audit block). The
        # structured ``confidence`` field is capped on the same authoritative
        # verdict. Never touches ordinary financial figures.
        from tradingagents.debate.confidence_policy import cap_agent_text, update_audit

        investment_plan, _cap_entries = cap_agent_text(
            investment_plan, state,
            source="Research Manager", boundary="research_manager_plan",
        )
        # The typed numeric cap (raw-precision) and the rendered-text cap share the
        # same update; a rendered effective value is within cap so there is no
        # double cap, only the exact-raw typed entry stays.
        _cap_entries = list(typed_audit) + list(_cap_entries)

        # Quarantine the raw model narrative for a partial/unknown debate as
        # separate NON-authoritative audit material (redacted), never in the
        # trusted plan/report body/memory. The default path is resolved from the
        # run's results_dir/identity so the real graph persists it even without an
        # explicit override.
        if partial_or_unknown:
            _quarantine_partial_raw(state, participation, raw_model_text)

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }
        # Preserve the Phase 3B bookkeeping so the debate termination trace
        # survives the manager's conclusion for checkpointing and reports. These
        # fields are optional; a legacy state simply carries nothing extra.
        for phase3b_field in (
            "turns",
            "conflicts",
            "conflict_summary",
            "claim_validation_summary",
            "stances",
            "previously_cited_evidence_ids",
            "round_metrics",
            "metadata_parse_failed_count",
            "no_new_evidence_streak",
            "budget",
        ):
            if phase3b_field in investment_debate_state:
                new_investment_debate_state[phase3b_field] = investment_debate_state[phase3b_field]

        result = {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
            "debate_termination_decision": state.get("debate_termination_decision"),
        }
        if _cap_entries:
            result["confidence_cap_audit"] = update_audit(state, _cap_entries)
        return result

    return research_manager_node
