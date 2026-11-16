"""Behavioural probe: the three remediated defects must be visible pre-fix.

Runs against whatever `structured.py`/`observability.py` are on disk, using only
APIs that exist before and after the fix. Exit 0 = the defects were DETECTED
(which is expected on the pre-fix tree); exit 1 = a defect was not detectable.
"""
from __future__ import annotations

import sys
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel

sys.path.insert(0, ".")
from tradingagents import observability as o  # noqa: E402
from tradingagents.agents.utils.structured import (  # noqa: E402
    finalize_single_pass, run_data_tools,
)
from tradingagents.agents.utils.structured import _schema_tool_name  # noqa: E402


class Stance(BaseModel):
    stance: Literal["Bullish", "Bearish", "Neutral"]
    summary: str


class Scripted:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def __call__(self, messages, **kwargs):
        if hasattr(messages, "to_messages"):
            messages = messages.to_messages()
        self.seen.append(list(messages))
        return self.replies.pop(0)

    def bind_tools(self, tools, **kwargs):
        from langchain_core.runnables import RunnableLambda
        return RunnableLambda(self)


def dangling(messages):
    pending = set()
    for m in messages:
        if pending and getattr(m, "type", None) != "tool":
            return sorted(pending)
        if getattr(m, "tool_calls", None):
            pending = {c.get("id") for c in m.tool_calls}
        if getattr(m, "type", None) == "tool":
            pending.discard(getattr(m, "tool_call_id", None))
    return sorted(pending)


def main() -> int:
    detected = 0

    # 1. R12: the fallback replays a dangling schema tool_call and drops the system prompt.
    llm = Scripted([
        AIMessage(content="", tool_calls=[{"name": _schema_tool_name(Stance),
                    "args": {"stance": "Mildly Bearish", "summary": "x"},
                    "id": "s1", "type": "tool_call"}]),
        AIMessage(content="prose"),
    ])
    prompt = ChatPromptTemplate.from_messages(
        [("system", "SYS"), MessagesPlaceholder("messages")])
    finalize_single_pass(llm=llm, structured_llm=llm, prompt=prompt,
                         messages=[HumanMessage(content="JPM")], tools=[],
                         schema=Stance, render=lambda r: r.summary,
                         agent_name="market_analyst", run_tools=lambda b: [], state={})
    retry = llm.seen[1]
    if dangling(retry):
        print("DETECTED: retry carries dangling tool_call ids", dangling(retry)); detected += 1
    if not any(isinstance(m, SystemMessage) for m in retry):
        print("DETECTED: retry dropped the system prompt"); detected += 1

    # 2. DSML: a markup-only fallback is stored verbatim as the report.
    markup = ('<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="get_verified_market_snapshot"> '
              '<｜｜DSML｜｜ parameter name="symbol" string="true">XOM</｜｜DSML｜｜ parameter> '
              '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>')
    llm2 = Scripted([
        AIMessage(content="", tool_calls=[{"name": _schema_tool_name(Stance),
                    "args": {"stance": "Mildly Bearish", "summary": "x"},
                    "id": "s2", "type": "tool_call"}]),
        AIMessage(content=markup),
    ])
    text, _report, _msgs = finalize_single_pass(
        llm=llm2, structured_llm=llm2, prompt=prompt,
        messages=[HumanMessage(content="XOM")], tools=[], schema=Stance,
        render=lambda r: r.summary, agent_name="market_analyst",
        run_tools=lambda b: [], state={})
    if "｜｜DSML｜｜" in text:
        print("DETECTED: protocol markup reached the report text"); detected += 1

    # 3. tool_rounds: in-process tool execution records no round.
    collector = o.RunMetricsCollector()
    collector.begin_run(ticker="JPM", trade_date="2026-09-23")

    class Tool:
        name = "t"

        def invoke(self, args):
            return "ok"

    runner = run_data_tools([Tool()], state={})
    with o.run_scoped(collector), o.agent_scoped("market_analyst"):
        runner([{"name": "t", "args": {}, "id": "1"}])
    if len(collector.tool_rounds) == 0:
        print("DETECTED: tool round was not recorded"); detected += 1

    print(f"defects detected: {detected}/4")
    return 0 if detected >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
