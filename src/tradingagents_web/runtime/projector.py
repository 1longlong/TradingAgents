"""Project real graph state: REQ-WEB-002, ADR-001, INV-WEB-014."""

from __future__ import annotations

from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS

ROLE_GROUPS = {
    "research": ("Bull Researcher", "Bear Researcher", "Research Manager"),
    "trading": ("Trader",),
    "risk": ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager"),
}

_SECTION_TITLES = {
    "market_report": "Market Analysis",
    "sentiment_report": "Social Sentiment",
    "news_report": "News Analysis",
    "fundamentals_report": "Fundamentals Analysis",
    "investment_plan": "Research Team Decision",
    "trader_investment_plan": "Trading Team Plan",
    "final_trade_decision": "Portfolio Management Decision",
}


def _public_text(content) -> str:
    """TUI-equivalent public text only (INV-WEB-003/012, ADR-003)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part.strip())
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(_public_text(part.get("text")))
        return " ".join(part for part in parts if part)
    return ""


def _message_type(message, content: str) -> str:
    if isinstance(message, HumanMessage):
        return "Control" if content == "Continue" else "User"
    if isinstance(message, ToolMessage):
        return "Data"
    return "Agent" if isinstance(message, AIMessage) else "System"


class StreamProjector:
    """Stateful projector for LangGraph ``stream_mode='values'`` chunks."""

    def __init__(self, analysts=None):
        self._seen_messages: set[str] = set()
        self.sections: dict[str, str] = {}
        self.analysts = list(ANALYST_NODE_SPECS if analysts is None else analysts)
        self._statuses: dict[str, str] = {}
        self._history: dict[str, str] = {}
        self._stage = "analysts"
        self._observed_roles: set[str] = set()
        self.roles = [ANALYST_NODE_SPECS[key].agent_node for key in self.analysts]
        self.roles += [role for group in ROLE_GROUPS.values() for role in group]

    def node_status(self, role: str, status: str) -> list[dict]:
        """Observed node lifecycle only; unknown/nested/tool callbacks are ignored."""
        if role not in self.roles:
            return []
        self._observed_roles.add(role)
        return self._status_event(role, status)

    def _status_event(self, role: str, status: str) -> list[dict]:
        if self._statuses.get(role) == status:
            return []
        self._statuses[role] = status
        return [{"type": "agent.status", "payload": {"agent": role, "status": status}}]

    def counts(self) -> dict[str, int]:
        finalizers = {
            **{
                ANALYST_NODE_SPECS[key].report_key: ANALYST_NODE_SPECS[key].agent_node
                for key in self.analysts
            },
            "investment_plan": "Research Manager",
            "trader_investment_plan": "Trader",
            "final_trade_decision": "Portfolio Manager",
        }
        return {
            "reports_total": len(finalizers),
            "reports_completed": sum(
                bool(self.sections.get(section)) and self._statuses.get(role) == "completed"
                for section, role in finalizers.items()
            ),
            "agents_total": len(self.roles),
            "agents_completed": sum(self._statuses.get(role) == "completed" for role in self.roles),
        }

    def project(self, chunk: dict) -> list[dict]:
        events: list[dict] = []
        # A recovered cumulative message list has no trustworthy historical
        # stage boundary. Keep it in All activity rather than guessing.
        message_stage = (
            self._stage
            if self._statuses or not any(chunk.get(section) for section in _SECTION_TITLES)
            else None
        )

        for message in chunk.get("messages", []) or []:
            message_id = getattr(message, "id", None)
            if message_id:
                if message_id in self._seen_messages:
                    continue
                self._seen_messages.add(message_id)

            content = _public_text(getattr(message, "content", ""))
            if content:
                events.append(
                    {
                        "type": "message",
                        "payload": {
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "type": _message_type(message, content),
                            "content": content,
                            "stage": message_stage,
                            "speaker": getattr(message, "name", None),
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
                            "stage": message_stage,
                        },
                    }
                )

        # These are public argument histories, not private reasoning/audit fields.
        for state_key, stage, speakers in (
            (
                "investment_debate_state",
                "research",
                {
                    "bull_history": "Bull researcher",
                    "bear_history": "Bear researcher",
                },
            ),
            (
                "risk_debate_state",
                "risk",
                {
                    "aggressive_history": "Aggressive risk analyst",
                    "conservative_history": "Conservative risk analyst",
                    "neutral_history": "Neutral risk analyst",
                },
            ),
        ):
            debate_state = chunk.get(state_key) or {}
            for field, speaker in speakers.items():
                history = _public_text(debate_state.get(field))
                key = f"{state_key}.{field}"
                previous = self._history.get(key, "")
                if history and history != previous:
                    self._history[key] = history
                    delta = (
                        history[len(previous) :].strip()
                        if history.startswith(previous)
                        else history
                    )
                    if delta:
                        events.append(
                            {
                                "type": "message",
                                "payload": {
                                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                                    "type": "Agent",
                                    "speaker": speaker,
                                    "stage": stage,
                                    "content": delta,
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

        # Infer progress from actual graph state, as the CLI does (REQ-WEB-002).
        phases = [
            (
                ANALYST_NODE_SPECS[key].agent_node,
                bool(chunk.get(ANALYST_NODE_SPECS[key].report_key)),
            )
            for key in self.analysts
        ]
        phases.extend(
            [
                (
                    "Research Team",
                    bool(chunk.get("investment_plan") or debate.get("judge_decision")),
                ),
                ("Trader", bool(chunk.get("trader_investment_plan"))),
                (
                    "Risk Team",
                    bool(chunk.get("final_trade_decision") or risk.get("judge_decision")),
                ),
            ]
        )
        active_found = False
        for agent, complete in phases:
            status = "completed" if complete else "pending" if active_found else "in_progress"
            active_found = active_found or not complete
            if agent not in self._observed_roles:
                events.extend(self._status_event(agent, status))
        # Recover recorded outputs without inventing execution of absent roles.
        recorded = {
            "Bull Researcher": bool(debate.get("bull_history")),
            "Bear Researcher": bool(debate.get("bear_history")),
            "Research Manager": bool(chunk.get("investment_plan") or debate.get("judge_decision")),
            "Aggressive Analyst": bool(risk.get("aggressive_history")),
            "Conservative Analyst": bool(risk.get("conservative_history")),
            "Neutral Analyst": bool(risk.get("neutral_history")),
            "Portfolio Manager": bool(
                chunk.get("final_trade_decision") or risk.get("judge_decision")
            ),
        }
        for role, present in recorded.items():
            if role not in self._observed_roles:
                events.extend(self._status_event(role, "completed" if present else "pending"))
        # A values chunk contains the previous node's output. Advance only after
        # attributing those messages, so a finished analyst is not labeled research.
        if chunk.get("trader_investment_plan"):
            self._stage = "risk"
        elif chunk.get("investment_plan") or debate.get("judge_decision"):
            self._stage = "trading"
        elif all(chunk.get(ANALYST_NODE_SPECS[key].report_key) for key in self.analysts):
            self._stage = "research"
        return events
