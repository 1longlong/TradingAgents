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
    """Raised when the injectable clock yields an unusable elapsed reading.

    A non-finite/backwards/negative reading must abort the invocation (fail
    closed) rather than fall back to character-based time or invent zero.
    """


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


def create_bull_researcher(llm, debate_termination_config=None, *, clock=time.monotonic):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]

        # Pre-call budget guard: never make an optional debate call that would
        # breach the call hard limit or consume the reserved summary capacity.
        # A refused call skips safely to the Research Manager with an explicit
        # budget_exhausted reason instead of executing over budget.
        config = resolve_budget_config_from_state(state, debate_termination_config)
        usage = state.get("debate_usage")
        if not can_afford_optional_call(usage, config):
            return {
                "debate_termination_decision": budget_admission_decision(
                    next_speaker="Bull",
                    calls_used=int((usage or {}).get("calls", 0)),
                    max_calls=int(config.max_calls),
                    config=config,
                    usage=usage,
                ),
            }
        history = investment_debate_state.get("history", "")

        current_response = opponent_argument_or_opening(
            investment_debate_state.get("current_response", ""), "bear analyst"
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

        prompt = f"""You are a Bull Analyst advocating for investing in the {target_label}. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the company's market opportunities, revenue projections, and scalability.
- Competitive Advantages: Emphasize factors like unique products, strong branding, or dominant market positioning.
- Positive Indicators: Use financial health, industry trends, and recent positive news as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.

Resources available:
{instrument_context}
{data_quality_context}
{data_quality_allowlist}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bear argument: {current_response}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate that demonstrates the strengths of the bull position.
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
                state, "Bull", None, attempted=False,
                status=STATUS_CLOCK_ABORT, reason="clock_invalid", turn_index=turn_index,
            )
            raise InvalidClockError("Bull debate initial clock unavailable (clock_invalid)")
        try:
            response = llm.invoke(prompt)
        except Exception as error:
            _record_failure(
                state, "Bull", error, attempted=True,
                status=STATUS_INVOKE_FAILED, turn_index=turn_index,
            )
            raise
        end = _safe_clock(clock)

        content = response.content
        turn = parse_turn_metadata(speaker="Bull", content=content)

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
                state, "Bull", None, attempted=True,
                status=STATUS_CLOCK_END_INVALID, reason="clock_invalid", turn_index=turn_index,
            )
            raise InvalidClockError(
                f"Bull debate timing unavailable ({clock_check['reason']})"
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

    return bull_node
