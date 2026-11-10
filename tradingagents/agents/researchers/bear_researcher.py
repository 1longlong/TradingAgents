import time

from tradingagents.agents.utils.agent_utils import (
    get_data_quality_context_from_state,
    get_instrument_context_from_state,
    get_language_instruction,
    opponent_argument_or_opening,
    report_or_absent,
)
from tradingagents.debate.budget import (
    budget_admission_decision,
    can_afford_optional_call,
    extract_provider_usage,
    record_call_usage,
    resolve_budget_config_from_state,
    validate_clock_elapsed,
)
from tradingagents.debate.evidence_manifest import build_citation_allowlist
from tradingagents.debate.failure_audit import (
    STATUS_CLOCK_ABORT,
    STATUS_CLOCK_END_INVALID,
    STATUS_INVOKE_FAILED,
    build_attempted_usage,
    record_failure,
    resolve_audit_paths,
)
from tradingagents.debate.state import append_debate_turn
from tradingagents.debate.turn import METADATA_INSTRUCTION, parse_turn_metadata


class InvalidClockError(RuntimeError):
    """Raised when the injectable clock yields an unusable elapsed reading."""


def _safe_clock(clock) -> float | None:
    """Read one clock sample, returning ``None`` when the call itself fails."""
    try:
        return clock()
    except Exception:  # noqa: BLE001 — a broken clock taints the reading
        return None


def _run_identity(state):
    """Best-effort run identity for the failure ledger (never invents)."""
    run_id = state.get("run_id")
    if not run_id and state.get("company_of_interest") and state.get("trade_date"):
        run_id = f"{state.get('trade_date')}/{state.get('company_of_interest')}"
    return run_id


def _record_failure(
    state, speaker, error, *, attempted, status, reason=None, turn_index=None
) -> None:
    """Write a sanitized failure record (attempt accounting, no content)."""
    failure_path, _ = resolve_audit_paths(state)
    usage_snapshot = build_attempted_usage(
        state.get("debate_usage"), attempted=attempted, turn_index=turn_index
    )
    record_failure(
        failure_path,
        run_id=_run_identity(state),
        turn=speaker,
        speaker=speaker,
        phase="debate_invocation",
        error=error,
        status=status,
        reason=reason,
        usage_snapshot=usage_snapshot,
    )


def create_bear_researcher(llm, debate_termination_config=None, *, clock=time.monotonic):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]

        # Pre-call budget guard: an optional Bear call that would breach the
        # call hard limit (e.g. max_calls=1 already spent by Bull) or eat the
        # reserved summary capacity is refused, routing to the Research Manager
        # with budget_exhausted for the incomplete round.
        config = resolve_budget_config_from_state(state, debate_termination_config)
        usage = state.get("debate_usage")
        if not can_afford_optional_call(usage, config):
            return {
                "debate_termination_decision": budget_admission_decision(
                    next_speaker="Bear",
                    calls_used=int((usage or {}).get("calls", 0)),
                    max_calls=int(config.max_calls),
                    config=config,
                    usage=usage,
                ),
            }
        history = investment_debate_state.get("history", "")

        current_response = opponent_argument_or_opening(
            investment_debate_state.get("current_response", ""), "bull analyst"
        )
        market_research_report = report_or_absent(state["market_report"], "market")
        sentiment_report = report_or_absent(state["sentiment_report"], "sentiment")
        news_report = report_or_absent(state["news_report"], "news")
        fundamentals_report = report_or_absent(state["fundamentals_report"], "fundamentals")
        instrument_context = get_instrument_context_from_state(state)
        data_quality_context = get_data_quality_context_from_state(state)
        data_quality_allowlist = build_citation_allowlist(
            state.get("data_quality_evidence_records"), state.get("trade_date")
        )
        data_quality_verdict = state.get("data_quality_verdict")
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )

        prompt = f"""You are a Bear Analyst making the case against investing in the {target_label}. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:

- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

Resources available:

{instrument_context}
{data_quality_context}
{data_quality_allowlist}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bull argument: {current_response}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the {target_label}.
""" + get_language_instruction()

        if data_quality_verdict == "degraded":
            prompt += (
                "\n\nData quality is degraded: low-evidence claims cannot be "
                "decisive, cite only the evidence IDs listed above, and cap your "
                "confidence accordingly."
            )

        prompt += METADATA_INSTRUCTION

        # Measure the real invocation with the injectable monotonic clock. An
        # invalid INITIAL clock reading aborts BEFORE the model call (no call is
        # made; the ledger records 0 attempted calls). A failed invocation
        # re-raises (existing abort behavior) after a sanitized audit entry that
        # records ONE logical attempted call / failed_calls=1; no state usage is
        # fabricated and the failed checkpoint is NOT advanced by this ledger.
        turn_index = int(investment_debate_state.get("count", 0) or 0)
        start = _safe_clock(clock)
        if validate_clock_elapsed(start, start)["ok"] is False:
            # Abort before llm.invoke; telemetry unavailable; 0 actual calls.
            _record_failure(
                state, "Bear", None, attempted=False,
                status=STATUS_CLOCK_ABORT, reason="clock_invalid", turn_index=turn_index,
            )
            raise InvalidClockError("Bear debate initial clock unavailable (clock_invalid)")
        try:
            response = llm.invoke(prompt)
        except Exception as error:
            _record_failure(
                state, "Bear", error, attempted=True,
                status=STATUS_INVOKE_FAILED, turn_index=turn_index,
            )
            raise
        end = _safe_clock(clock)

        content = response.content
        turn = parse_turn_metadata(speaker="Bear", content=content)

        new_investment_debate_state = append_debate_turn(
            investment_debate_state, turn
        )

        clock_check = validate_clock_elapsed(start, end)
        if not clock_check["ok"]:
            # Binding contract: an invalid/backwards/non-finite END reading
            # aborts. The invocation was actually attempted (one logical call),
            # so the ledger records attempted=1 with unavailable clock; no
            # response token cost is invented. Telemetry unavailable.
            _record_failure(
                state, "Bear", None, attempted=True,
                status=STATUS_CLOCK_END_INVALID, reason="clock_invalid", turn_index=turn_index,
            )
            raise InvalidClockError(
                f"Bear debate timing unavailable ({clock_check['reason']})"
            )
        provider_usage = extract_provider_usage(response)
        usage = record_call_usage(
            state.get("debate_usage"),
            prompt_chars=len(prompt),
            response_chars=len(content),
            provider_usage=provider_usage,
            measured_seconds=clock_check["seconds"],
        )

        return {
            "investment_debate_state": new_investment_debate_state,
            "debate_usage": usage,
        }

    return bear_node
