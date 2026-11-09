"""Fundamentals-analyst tool governance: prepare, execute, and one bounded wrap-up.

Wired into the real graph only when
``config["fundamentals_tool_governance"]["enabled"]`` is true
(:mod:`tradingagents.graph.fundamentals_governance`); with it off none of these
nodes is added and the fundamentals analyst follows its original path. The
market section is configured separately and never switches this one on.

The loop, as the graph runs it::

    Fundamentals Analyst --tool calls--> fundamentals_tool_prepare --may run--> fundamentals_tool_execute
                                         \\--answered--> Fundamentals Analyst (while rounds remain) |
                                         \\--stop/wrap-up--> fundamentals_wrap_up                   v
                                                             Fundamentals Analyst (rounds left)
                                                             fundamentals_wrap_up   (spent)
    fundamentals_wrap_up
    fundamentals_finish     >--> Msg Clear Fundamentals

* ``fundamentals_tool_prepare`` plans the round through
  :class:`~tradingagents.agents.utils.tool_governance.ToolExecutor` and **saves
  the registration** (charged round + saved plan + one message per call it will
  not run) as the ``tool_governance`` graph state -- under
  ``analysts["fundamentals"]``, which is this analyst's own record. It never
  dispatches. If the plan has nothing to dispatch (every call was blocked), it
  emits the plan's own block messages so the analyst is never left with an
  unanswered call.
* ``fundamentals_tool_execute`` reads that saved registration back and
  dispatches it. It is a **separate** node, so a tool exception there happens
  after the graph already holds the registration: the round is not charged
  twice, and re-running the node resumes the same round without spending
  another round. Once the batch has fully executed and every call is paired, a
  conditional edge decides the next step: ``Fundamentals Analyst`` while the
  allowance remains, ``fundamentals_wrap_up`` directly once it is spent.
* Permission is exactly the four tools the analyst is bound to --
  ``get_fundamentals``, ``get_balance_sheet``, ``get_cashflow``,
  ``get_income_statement`` -- as defined by the tools passed to the executor
  (the analyst's own ``ToolNode``); any other name fails the batch before
  anything runs.
* The key rule: charging the last allowed round sets ``closed`` (no *new* batch
  may start), but it never revokes calls that round already approved. The
  router reads the saved plan, not ``closed``, so the final round's execute /
  reuse / block work runs to completion first. Only after that does the run
  wrap up -- and once the allowance is spent a tool-call turn goes straight to
  the wrap-up, never back to the normal analyst tool loop.
* ``fundamentals_wrap_up`` is reached once no further round may run. It makes
  **at most one** model call, on an unbound model, writes
  ``fundamentals_report`` from the fundamental evidence already in the
  messages, and marks the analyst ``finished``. It never returns to the tool
  loop; if the model errors, refuses, is truncated, returns nothing, or still
  asks for tools, it raises -- no second generation, no invented report.
* ``fundamentals_finish`` handles the analyst writing its own plain-text
  report: that text *is* the report, so no wrap-up call is spent replacing it.
  A refusal or a truncated answer is not a report, and raises instead of being
  stored.

An unusable analyst answer (refusal, explicit truncation, blank body) is final
in the router (:meth:`ConditionalLogic.should_continue_fundamentals_governed`):
the run raises at that first response, storing no report, marking nothing
finished, and making no second request.

Graph state holds only plain data: the governance record and the model's calls.
No ``PreparedRound``, model or ``ToolNode`` is ever stored there.

Nothing here reads, reuses or reports the market analyst's record, messages or
report: the counters are keyed by this analyst's name, and the report is written
only to ``fundamentals_report``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.tool_governance import (
    GOVERNANCE_STATE_KEY,
    ToolContext,
    ToolExecutor,
    message_text,
    reject_unusable_response,
    run_analyst_tool_node,
)

from .fundamentals_governance import (
    FUNDAMENTALS_TOOLS,
    parse_fundamentals_tool_governance,
)
from .market_tool_governance import (
    _BLOCK_NOTE,
    BLOCK_PREFIX,
    _calls_of,
    _make_execute,
    _make_prepare,
    analyst_report,
    governance_state_of,
    live_config,
    pending_calls as _pending_calls,
    prepared_work as _prepared_work,
    run_id_of,
    run_state_of,
    scope_of,
)

logger = logging.getLogger(__name__)

ANALYST = "fundamentals"


class FundamentalsGovernanceError(RuntimeError):
    """The governed fundamentals flow could not finish honestly.

    Raised by the wrap-up when it cannot produce a report (model error, blank
    output, or the model still asking for tools) or by the execute node when the
    saved registration it is meant to dispatch is gone. It never carries a
    fabricated report.
    """


# ---------------------------------------------------------------------------
# Run inputs (plain data only)
# ---------------------------------------------------------------------------


def fundamentals_run_id(state: Mapping[str, Any]) -> str:
    """This run's unique id (shared with every other governed analyst)."""
    return run_id_of(state, "fundamentals")


def _context(state: Mapping[str, Any], run_id: str) -> ToolContext:
    company = state.get("company_of_interest")
    instrument = company.strip() if isinstance(company, str) and company.strip() else None
    return ToolContext(
        analyst=ANALYST,
        run_id=run_id,
        instrument=instrument,
        trade_date=state.get("trade_date"),
    )


def _permitted_tools(tool_node: Any) -> list[Any]:
    """The tools the fundamentals analyst is bound to. **The** permission set.

    It is the analyst's own ``ToolNode`` content -- the same objects the model
    is bound to -- restricted by name to
    :data:`~tradingagents.graph.fundamentals_governance.FUNDAMENTALS_TOOLS`.
    A ``tool_node`` replaced by a wider one therefore grants no extra tools, and
    a missing one grants none at all: nothing outside the four is ever callable
    through this analyst.
    """
    bound = list(getattr(tool_node, "tools_by_name", {}).values())
    return [
        tool
        for tool in bound
        if getattr(tool, "name", getattr(tool, "__name__", None)) in FUNDAMENTALS_TOOLS
    ]


def _executor(
    tool_node: Any, *, state: Mapping[str, Any], run_id: str
) -> ToolExecutor:
    """An executor over exactly the four fundamental tools this analyst binds."""
    return ToolExecutor(
        _permitted_tools(tool_node),
        node=tool_node,
        analyst=ANALYST,
        run_id=run_id,
        limits=parse_fundamentals_tool_governance(live_config(state)).limits(),
        context=_context(state, run_id),
        runner=run_analyst_tool_node,
        confirms_success=confirms_success,
    )


def confirms_success(call: Mapping[str, Any], message: Mapping[str, Any]) -> bool:
    """Whether a tool message is *explicit* evidence that valid data came back.

    Success reuse is opt-in and needs positive proof. The absence of an error
    is not proof: a non-empty text, a ``status="success"`` or the absence of a
    known error prefix can describe a stub, an empty statement or a prose
    explanation, so it can never be the confirmation that lets a later call be
    served from cache. This confirmer therefore confirms **nothing**:
    fundamentals tool results are recorded, paired and counted, but success
    reuse for them is switched off until a tool can vouch for its own payload.

    It stays a callable (not ``None``) so the executor can still ask, and so
    enabling a real confirmer later is a one-line change.
    """
    del call, message
    return False


def fundamentals_scope_of(governance: Mapping[str, Any]) -> dict[str, Any]:
    """The fundamentals analyst's record inside a ``tool_governance`` value."""
    return scope_of(governance, analyst=ANALYST)


def _scope_of(governance: Mapping[str, Any]) -> dict[str, Any]:
    """Alias kept short inside this module (always this analyst's record)."""
    return fundamentals_scope_of(governance)


def _reject(message: Any, what: str) -> None:
    """Raise :class:`FundamentalsGovernanceError` for an answer that is not a report."""
    reject_unusable_response(message, what, FundamentalsGovernanceError)


def prepared_work(state: Mapping[str, Any], *, analyst: str = ANALYST) -> bool:
    """Router helper: does this analyst's saved plan still owe work?"""
    return _prepared_work(state, analyst=analyst)


def pending_calls(state: Mapping[str, Any], *, analyst: str = ANALYST) -> list[str]:
    """Router helper: this analyst's calls left with no answer and no allowance."""
    return _pending_calls(state, analyst=analyst)


def _keep_scope(
    governance: Mapping[str, Any], scope: Mapping[str, Any]
) -> dict[str, Any]:
    """Write this analyst's record back, leaving every other analyst untouched."""
    analysts = dict(governance.get("analysts") or {})
    analysts[ANALYST] = dict(scope)
    return {**governance, "analysts": analysts}


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def create_fundamentals_governance_nodes(*, llm: Any, tool_node: Any) -> dict[str, Any]:
    """Build the four fundamentals governance nodes for one run graph.

    ``llm`` is the fundamentals analyst's model (one unbound wrap-up call);
    ``tool_node`` is the graph's own fundamentals ``ToolNode`` (dispatched
    through the executor -- never stored in state).
    """
    return {
        "prepare": _make_prepare(tool_node, analyst=ANALYST, executor_of=_executor),
        "execute": _make_execute(
            tool_node,
            analyst=ANALYST,
            executor_of=_executor,
            on_missing_registration=_missing_registration,
        ),
        "finish": _make_finish(),
        "wrap_up": _make_wrap_up(llm),
    }


def _missing_registration(exc: Exception) -> Exception:
    return FundamentalsGovernanceError(
        "the saved registration for this fundamentals tool round is missing; "
        f"the execute node refuses to charge a new round ({exc})"
    )


def _make_finish():
    def fundamentals_finish(state: Mapping[str, Any]) -> dict[str, Any]:
        """The analyst wrote its own report: record it as the run's report.

        A plain-text final answer is the report. Mark the analyst ``finished``
        so a re-entry writes nothing that could overwrite it, and keep the text
        as ``fundamentals_report`` for the downstream nodes.

        An answer that is not a report -- a refusal, a token-limit cut-off, or
        an empty body -- raises. It is not stored as ``fundamentals_report``,
        the analyst is not marked finished, and nothing is generated a second
        time.
        """
        governance = governance_state_of(state)
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages else None
        report = analyst_report(last)
        if not report:
            if last is None or not isinstance(last, AIMessage):
                raise FundamentalsGovernanceError(
                    "fundamentals_finish reached without the analyst's final "
                    "message; no report was written"
                )
            if getattr(last, "tool_calls", None):
                raise FundamentalsGovernanceError(
                    "fundamentals_finish reached while the analyst still asks "
                    "for tools; no report was written"
                )
            # A usable plain-text answer is guaranteed here: the router only
            # sends a non-empty one to finish. Anything else reached this node
            # by mistake and must not be stored as a report.
            _reject(last, "fundamentals_finish")
            raise FundamentalsGovernanceError(
                "fundamentals_finish reached with an answer that is not a "
                "report; no report was written"
            )
        scope = {**_scope_of(governance), "finished": True, "closed": True}
        return {
            GOVERNANCE_STATE_KEY: _keep_scope(governance, scope),
            "fundamentals_report": report,
            # The analyst's own message is the final answer and the router
            # reads it back from the state: echo it so the turn stays visible.
            "messages": [last],
        }

    return fundamentals_finish


def _make_wrap_up(llm: Any):
    def fundamentals_wrap_up(state: Mapping[str, Any]) -> dict[str, Any]:
        governance = governance_state_of(state)
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages else None

        own_report = analyst_report(last)
        if own_report:
            # Reached only if a caller skips the finish node: never spend a
            # second generation replacing the analyst's own report.
            scope = {**_scope_of(governance), "finished": True, "closed": True}
            return {
                "fundamentals_report": own_report,
                GOVERNANCE_STATE_KEY: _keep_scope(governance, scope),
                "messages": [last],
            }

        # Every call the model already issued owes it one message, before the
        # report and without running anything. They go to the state with the
        # report (echoed annotated batch + its pairs + the wrap-up answer), so
        # no dangling tool call is left behind.
        echoed: list[Any] = []
        pairs: list[Any] = []
        if isinstance(last, AIMessage):
            pairs = _answer_final_calls(messages, governance)
            echoed = [last, *pairs]

        # The model is shown the analyst's last request *with* its answers, so
        # the conversation it writes from ends in a usable (blocked/restated)
        # tool reply instead of an unanswered tool call.
        result = llm.invoke(_wrap_up_prompt(state, [*messages, *pairs]))

        # A refusal, a token-limit cut-off, an empty body or a request for more
        # tools is final: raise, so nothing is stored and nothing is generated
        # again (the guard is the one both exits share).
        _reject(result, "fundamentals wrap-up")
        report = message_text(result.content)

        scope = {**_scope_of(governance), "finished": True, "closed": True}
        return {
            "messages": [*echoed, result],
            "fundamentals_report": report,
            GOVERNANCE_STATE_KEY: _keep_scope(governance, scope),
        }

    return fundamentals_wrap_up


def _answer_final_calls(messages: list[Any], governance: Mapping[str, Any]) -> list[Any]:
    """One ``ToolMessage`` per still-unpaired call of the last model message.

    A call with a recorded result restates it; any other is blocked. Nothing
    here runs a tool.
    """
    from langchain_core.messages import ToolMessage

    last = messages[-1]
    results = _scope_of(governance).get("results") or {}
    paired: list[ToolMessage] = []
    for call in _calls_of(last):
        call_id = call.get("id")
        if call_id is None:
            continue
        recorded = results.get(str(call_id))
        if recorded is not None:
            content = recorded.get("text") or ""
            status = recorded.get("status")
        else:
            content = (
                f"{BLOCK_PREFIX}: this call was not run; the fundamentals "
                "analyst's tool allowance is spent. Use the evidence already "
                f"collected and state explicitly what is missing.\n\n{_BLOCK_NOTE}"
            )
            status = None
        message = ToolMessage(
            content=content, tool_call_id=str(call_id), name=call.get("name")
        )
        if status == "error":
            message.status = "error"
        paired.append(message)
    return paired


def _wrap_up_prompt(state: Mapping[str, Any], messages: list[Any]) -> list[Any]:
    """The single wrap-up call's prompt: system rules + the tool conversation."""
    system = (
        "You are the Fundamentals Analyst. The tool-call allowance for this run "
        "is spent, so you cannot call any tool now. Using ONLY the fundamental "
        "tool results already present in this conversation, write the "
        "fundamentals report.\n\n"
        "Rules:\n"
        "- Do not invent financial figures, line items, percentages or "
        "reporting periods. Every revenue, earnings, margin, balance-sheet, "
        "cash-flow or statement figure must come from a tool result in this "
        "conversation; if a statement or field is absent, do not estimate it.\n"
        "- Explicitly list which financial statements (balance sheet, income "
        "statement, cash flow) or which fields are missing or unavailable. A "
        "blocked or empty call means the data was not collected, not that it "
        "does not exist.\n"
        "- Do not use data after the trade date; the tools only return history "
        "up to it, and any figure dated later must not be described.\n"
        "- Write a detailed fundamentals report and end with a Markdown "
        "summary table."
        f"{get_language_instruction()}"
    )
    human = (
        f"Company: {state.get('company_of_interest', '')}. "
        f"Trade date: {state.get('trade_date', '')}. "
        "Here is the research so far:"
    )
    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
        *[_as_message(message) for message in messages],
    ]


def _as_message(message: Any) -> Any:
    """The conversation as message objects (the model needs objects, not dicts)."""
    if isinstance(message, (AIMessage, HumanMessage, SystemMessage)):
        return message
    from langchain_core.messages import ToolMessage, convert_to_messages

    if isinstance(message, ToolMessage):
        return message
    return convert_to_messages([message])[0]


__all__ = [
    "ANALYST",
    "FUNDAMENTALS_TOOLS",
    "FundamentalsGovernanceError",
    "analyst_report",
    "confirms_success",
    "create_fundamentals_governance_nodes",
    "fundamentals_run_id",
    "fundamentals_scope_of",
    "governance_state_of",
    "live_config",
    "pending_calls",
    "prepared_work",
    "run_state_of",
    "scope_of",
]
