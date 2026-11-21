"""REQ-WEB-002/007; ADR-002/003; INV-WEB-001/003/012/014 activity contracts."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from tradingagents_web.runtime.projector import StreamProjector


def messages(events):
    return [event["payload"] for event in events if event["type"] == "message"]


def test_activity_uses_tui_types_and_deduplicates_cumulative_messages():
    projector = StreamProjector(["market"])
    chunk = {
        "messages": [
            HumanMessage("Analyze NVDA", id="user"),
            HumanMessage("Continue", id="control"),
            AIMessage("Checking price", id="agent"),
            ToolMessage("0", tool_call_id="call", id="data"),
            SystemMessage("None", id="system"),
        ]
    }
    result = messages(projector.project(chunk))
    assert [item["type"] for item in result] == ["User", "Control", "Agent", "Data", "System"]
    assert [item["content"] for item in result][-2:] == ["0", "None"]
    assert messages(projector.project(chunk)) == []


def test_activity_omits_private_non_text_blocks_and_preserves_tool_call():
    projector = StreamProjector(["market"])
    message = AIMessage(
        content=[
            {"type": "text", "text": "Public answer"},
            {"type": "reasoning", "reasoning": "PRIVATE_REASONING"},
            {"type": "thinking", "thinking": "PRIVATE_THINKING"},
        ],
        tool_calls=[{"name": "get_stock_data", "args": {"symbol": "NVDA"}, "id": "call"}],
        id="m",
    )
    events = projector.project({"messages": [message]})
    assert messages(events)[0]["content"] == "Public answer"
    assert "PRIVATE_" not in str(events)
    call = next(event["payload"] for event in events if event["type"] == "tool_call")
    assert call["name"] == "get_stock_data"
    assert call["arguments"] == {"symbol": "NVDA"}
    assert call["stage"] == "analysts"


def test_completed_node_messages_keep_the_stage_that_produced_them():
    projector = StreamProjector(["market"])
    projector.project({"messages": []})
    events = projector.project(
        {"market_report": "Market report", "messages": [AIMessage("Market complete", id="market")]}
    )
    assert messages(events)[0]["stage"] == "analysts"
    events = projector.project(
        {
            "market_report": "Market report",
            "investment_plan": "Research plan",
            "messages": [AIMessage("Research complete", id="research")],
        }
    )
    assert messages(events)[0]["stage"] == "research"
    events = projector.project(
        {
            "market_report": "Market report",
            "investment_plan": "Research plan",
            "trader_investment_plan": "Trade plan",
            "messages": [AIMessage("Trader complete", id="trader")],
        }
    )
    assert messages(events)[0]["stage"] == "trading"
    events = projector.project({"messages": [AIMessage("Risk complete", id="risk")]})
    assert messages(events)[0]["stage"] == "risk"


def test_empty_risk_state_does_not_move_analyst_messages_to_risk():
    projector = StreamProjector(["market"])
    chunk = {"risk_debate_state": {"aggressive_history": "", "count": 0}}
    projector.project(chunk)
    result = messages(
        projector.project({**chunk, "messages": [AIMessage("Still analyzing", id="m")]})
    )
    assert result[0]["stage"] == "analysts"


def test_debate_histories_emit_only_new_public_arguments():
    projector = StreamProjector(["market"])
    chunk = {
        "investment_debate_state": {
            "bull_history": "Bull round one",
            "bear_history": "Bear round one",
        },
        "confidence_cap_raw_transcript": "PRIVATE_RAW",
    }
    result = messages(projector.project(chunk))
    assert [(item["speaker"], item["stage"]) for item in result] == [
        ("Bull researcher", "research"),
        ("Bear researcher", "research"),
    ]
    assert messages(projector.project(chunk)) == []
    chunk["investment_debate_state"]["bull_history"] += "\nBull round two"
    result = messages(projector.project(chunk))
    assert len(result) == 1
    assert result[0]["content"] == "Bull round two"
    assert "PRIVATE_RAW" not in str(result)


def test_risk_histories_and_judgment_remain_distinct():
    result = StreamProjector(["market"]).project(
        {
            "risk_debate_state": {
                "aggressive_history": "Aggressive view",
                "conservative_history": "Conservative view",
                "neutral_history": "Neutral view",
                "judge_decision": "**Rating**: REVIEW",
            }
        }
    )
    assert [item["stage"] for item in messages(result)] == ["risk"] * 3
    section = next(event["payload"] for event in result if event["type"] == "report.section")
    assert section["section"] == "final_trade_decision"
    assert section["content"] == "**Rating**: REVIEW"


def test_recovered_cumulative_messages_do_not_invent_stage_history():
    result = messages(
        StreamProjector(["market"]).project(
            {
                "market_report": "Prior report",
                "investment_plan": "Prior research",
                "messages": [AIMessage("Old message without stage provenance", id="old")],
            }
        )
    )
    assert result[0]["stage"] is None
