"""Translate accumulated graph chunks into WebUI events."""

from __future__ import annotations

from datetime import datetime

_SECTION_TITLES = {
    "market_report": "Market Analysis",
    "sentiment_report": "Social Sentiment",
    "news_report": "News Analysis",
    "fundamentals_report": "Fundamentals Analysis",
    "investment_plan": "Research Team Decision",
    "trader_investment_plan": "Trading Team Plan",
    "final_trade_decision": "Portfolio Management Decision",
}


class StreamProjector:
    """Stateful projector for LangGraph ``stream_mode='values'`` chunks."""

    def __init__(self):
        self._seen_messages: set[str] = set()
        self.sections: dict[str, str] = {}

    def project(self, chunk: dict) -> list[dict]:
        events: list[dict] = []

        for message in chunk.get("messages", []) or []:
            message_id = getattr(message, "id", None)
            if message_id:
                if message_id in self._seen_messages:
                    continue
                self._seen_messages.add(message_id)

            content = getattr(message, "content", "")
            if content:
                if isinstance(content, list):
                    content = " ".join(str(part) for part in content)
                events.append(
                    {
                        "type": "message",
                        "payload": {
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "type": type(message).__name__,
                            "content": str(content),
                        },
                    }
                )

            for tool_call in getattr(message, "tool_calls", []) or []:
                if isinstance(tool_call, dict):
                    name = tool_call.get("name", "tool")
                    args = tool_call.get("args", {})
                else:
                    name = getattr(tool_call, "name", "tool")
                    args = getattr(tool_call, "args", {})
                events.append(
                    {
                        "type": "tool_call",
                        "payload": {
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "name": name,
                            "arguments": args,
                        },
                    }
                )

        for section in _SECTION_TITLES:
            value = chunk.get(section)
            if value and value != self.sections.get(section):
                self.sections[section] = value
                events.append(
                    {
                        "type": "report.section",
                        "payload": {
                            "section": section,
                            "title": _SECTION_TITLES[section],
                            "content": value,
                        },
                    }
                )

        debate = chunk.get("investment_debate_state") or {}
        judge = debate.get("judge_decision")
        if judge and judge != self.sections.get("investment_plan"):
            self.sections["investment_plan"] = judge
            events.append(
                {
                    "type": "report.section",
                    "payload": {
                        "section": "investment_plan",
                        "title": _SECTION_TITLES["investment_plan"],
                        "content": judge,
                    },
                }
            )

        risk = chunk.get("risk_debate_state") or {}
        judge = risk.get("judge_decision")
        if judge and judge != self.sections.get("final_trade_decision"):
            self.sections["final_trade_decision"] = judge
            events.append(
                {
                    "type": "report.section",
                    "payload": {
                        "section": "final_trade_decision",
                        "title": _SECTION_TITLES["final_trade_decision"],
                        "content": judge,
                    },
                }
            )

        return events
