"""Market-analyst tool governance: prepare, execute, and one bounded wrap-up.

Wired into the real graph only when ``config["market_tool_governance"]["enabled"]``
is true (:mod:`tradingagents.graph.market_governance`); with it off none of
these nodes is added and the market analyst follows its original path.

The loop, as the graph runs it::

    Market Analyst --tool calls--> market_tool_prepare --may run--> market_tool_execute
                                  \\--answered--> Market Analyst (while rounds remain) |
                                  \\--stop/wrap-up--> market_wrap_up                  v
                                                                    Market Analyst (rounds left)
                                                                    market_wrap_up   (spent)
    market_wrap_up
    market_finish     >--> Msg Clear Market

* ``market_tool_prepare`` plans the round through
  :class:`~tradingagents.agents.utils.tool_governance.ToolExecutor` and **saves
  the registration** (charged round + saved plan + one message per call it will
  not run) as the ``tool_governance`` graph state. It never dispatches. If the
  plan has nothing to dispatch (every call was blocked), it emits the plan's
  own block messages so the analyst is never left with an unanswered call.
* ``market_tool_execute`` reads that saved registration back and dispatches it.
  It is a **separate** node, so a tool exception there happens after the graph
  already holds the registration: the round is not charged twice, and re-running
  the node resumes the same round without spending another round or
  duplicating a cached result. Once the batch has fully executed and every call
  is paired, a conditional edge decides the next step: ``Market Analyst`` while
  the allowance remains, ``market_wrap_up`` directly once it is spent -- the
  analyst is not asked again just to be told it cannot use tools.
* The key rule: charging the last allowed round sets ``closed`` (no *new* batch
  may start), but it never revokes calls that round already approved. The
  router reads the saved plan, not ``closed``, so the final round's execute /
  reuse / block work runs to completion first. Only after that does the run
  wrap up -- and once the allowance is spent a tool-call turn goes straight to
  the wrap-up, never back to the normal analyst tool loop.
* ``market_wrap_up`` is reached once no further round may run (allowance spent,
  or the model stopped without writing). It makes **at most one** model call,
  on an unbound model, writes ``market_report`` from the tool evidence already
  in the messages, and marks the analyst ``finished``. It never returns to the
  tool loop; if the model errors, refuses, is truncated, returns nothing, or
  still asks for tools, it raises -- no second generation, no invented report.
* ``market_finish`` handles the analyst writing its own plain-text report: that
  text *is* the report, so no wrap-up call is spent replacing it. A refusal or
  a truncated answer is not a report, and raises instead of being stored.

An unusable analyst answer (refusal, explicit truncation, blank body) is final
in the router (:meth:`ConditionalLogic.should_continue_market_governed`): the
run raises at that first response, storing no report, marking nothing finished,
and making no second request.

Graph state holds only plain data: the governance record and the model's calls.
No ``PreparedRound``, model or ``ToolNode`` is ever stored there.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from tradingagents.agents.utils import structured
from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.tool_governance import (
    GOVERNANCE_STATE_KEY,
    GovernanceBatchError,
    ToolContext,
    ToolExecutor,
    get_scope,
    new_state,
    run_market_tool_node,
    saved_plan,
)
from tradingagents.dataflows.config import get_config

from .market_governance import parse_market_tool_governance

logger = logging.getLogger(__name__)

ANALYST = "market"

# The run-state fields a market tool may read; only simple, serialisable ones.
_RUN_STATE_KEYS = (
    "company_of_interest",
    "trade_date",
    "asset_type",
    "instrument_context",
)

BLOCK_PREFIX = "TOOL_GOVERNANCE_BLOCKED"
_BLOCK_NOTE = (
    "[Tool governance] This call was NOT run: the market analyst's tool allowance "
    "is spent. Do not infer anything the result would have shown; state "
    "explicitly that this data is missing."
)


class MarketGovernanceError(RuntimeError):
    """The governed market flow could not finish honestly.

    Raised by the wrap-up when it cannot produce a report (model error, blank
    output, or the model still asking for tools) or by the execute node when the
    saved registration it is meant to dispatch is gone. It never carries a
    fabricated report.
    """


# ---------------------------------------------------------------------------
# Run inputs (plain data only)
# ---------------------------------------------------------------------------


def market_run_id(state: Mapping[str, Any]) -> str:
    """This run's unique id.

    An initial state stamped by the graph carries one; a state built elsewhere
    (a bare programmatic state, a test) gets a fresh one, which the first update
    stores under ``tool_governance.run_id`` so every later lookup uses it.
    """
    inner = (state.get(GOVERNANCE_STATE_KEY) or {}).get("run_id")
    if isinstance(inner, str) and inner:
        return inner
    return f"market-{uuid.uuid4().hex}"


def governance_state_of(state: Mapping[str, Any]) -> dict[str, Any]:
    """The stored ``tool_governance`` value, or a fresh one for this run."""
    stored = state.get(GOVERNANCE_STATE_KEY)
    if not isinstance(stored, Mapping) or not stored:
        return new_state(market_run_id(state))
    return dict(stored)


def run_state_of(state: Mapping[str, Any]) -> dict[str, Any]:
    """The real run state the tools may read (serialisable fields only)."""
    return {key: state[key] for key in _RUN_STATE_KEYS if key in state}


def live_config(state: Mapping[str, Any]) -> dict[str, Any]:
    """The run config.

    The node signature is ``(state)``, so the config comes from the run state
    when the caller stamped it there and otherwise from the configuration the
    run installed (``set_config`` in the graph constructor).
    """
    stamped = state.get("run_config")
    return dict(stamped) if isinstance(stamped, Mapping) else get_config()


def _context(state: Mapping[str, Any], run_id: str) -> ToolContext:
    company = state.get("company_of_interest")
    instrument = company.strip() if isinstance(company, str) and company.strip() else None
    return ToolContext(
        analyst=ANALYST,
        run_id=run_id,
        instrument=instrument,
        trade_date=state.get("trade_date"),
    )


def _executor(
    tool_node: Any, *, state: Mapping[str, Any], run_id: str
) -> ToolExecutor:
    """An executor over exactly the tools the market ``ToolNode`` holds."""
    tools = list(getattr(tool_node, "tools_by_name", {}).values())
    return ToolExecutor(
        tools,
        node=tool_node,
        analyst=ANALYST,
        run_id=run_id,
        limits=parse_market_tool_governance(live_config(state)).limits(),
        context=_context(state, run_id),
        runner=run_market_tool_node,
        confirms_success=confirms_success,
    )


def confirms_success(call: Mapping[str, Any], message: Mapping[str, Any]) -> bool:
    """Whether a tool message is *explicit* evidence that valid data came back.

    Success reuse is opt-in and needs positive proof. The absence of an error
    is not proof: "non-empty + status=success + no known error prefix" accepts
    an unknown notice, a stub, an empty table, or a prose explanation as valid
    data, so it can never be the confirmation that lets a later call be served
    from cache. This confirmer therefore confirms **nothing**: market tool
    results are recorded, paired and counted, but success reuse for them is
    switched off until a tool can vouch for its own payload (a typed, dated
    result), which is a data-quality decision, not a text heuristic.

    It stays a callable (not ``None``) so the executor can still ask, and so
    enabling a real confirmer later is a one-line change.
    """
    del call, message
    return False


def _calls_of(message: Any) -> list[dict[str, Any]]:
    """The model's tool calls on ``message``, as plain dicts (graph-safe)."""
    calls = getattr(message, "tool_calls", None) or []
    return [dict(call) for call in calls]


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, Mapping) and isinstance(block.get("text"), str)
        )
    return ""


def scope_of(governance: Mapping[str, Any]) -> dict[str, Any]:
    """The market analyst's record inside a ``tool_governance`` value."""
    record = (governance.get("analysts") or {}).get(ANALYST)
    return dict(record) if isinstance(record, Mapping) else {}


def analyst_report(message: Any) -> str:
    """The analyst's own final text, if it wrote one (else ``""``).

    A market analyst that answers with plain text -- no tool calls -- has
    written its report itself. That text is the report; the governed path must
    not send it through the wrap-up and replace it with a second generation.

    An unusable answer is not a report: a refusal, an answer the provider cut
    off, or a blank body returns ``""`` so the caller fails instead of saving
    it as ``market_report`` (see :func:`reject_unusable_response`).
    """
    if not isinstance(message, AIMessage):
        return ""
    if getattr(message, "tool_calls", None):
        return ""
    if _response_problem(message) is not None:
        return ""
    return _text_of(message.content).strip()


def _response_problem(message: AIMessage) -> str | None:
    """Why ``message`` cannot become a report, or ``None`` if it can.

    Uses the project's existing structured-response rules rather than a new
    heuristic: :func:`structured._refusal_text` for an explicit refusal (the
    Chat Completions field, a ``refusal`` content block, ``content_blocks``)
    and :func:`structured._finish_reason` for an explicit token-limit stop. The
    blank check follows the free-text path of
    :func:`structured.invoke_structured_or_freetext`: no text at all is not an
    answer.
    """
    refusal = structured._refusal_text(message)
    if refusal is not None:
        return f"the model refused: {refusal.strip()[:200]}"
    finish = structured._finish_reason(message)
    if finish in structured._TRUNCATED_FINISH_REASONS:
        return f"the provider stopped at its token limit ({finish}): the text is partial"
    if not structured._message_content(message).strip():
        return "the model returned no content"
    return None


def reject_unusable_response(message: Any, what: str) -> None:
    """Raise :class:`MarketGovernanceError` if ``message`` cannot be a report.

    Called on **both** exits -- the analyst's own text (``market_finish``) and
    the single wrap-up generation -- so a refusal, a truncated answer, or an
    empty body fails the run: it is never stored as ``market_report``, never
    marks the analyst finished, and never triggers a second generation.
    """
    if not isinstance(message, AIMessage):
        raise MarketGovernanceError(
            f"{what} returned {type(message).__name__}, not a message"
        )
    if getattr(message, "tool_calls", None):
        raise MarketGovernanceError(
            f"{what} asked for tools after its allowance was spent; the tools "
            "are closed and no report was fabricated"
        )
    problem = _response_problem(message)
    if problem is not None:
        raise MarketGovernanceError(f"{what} did not produce a report: {problem}")


def prepared_work(state: Mapping[str, Any]) -> bool:
    """Whether the batch the analyst just issued has a registered plan to emit.

    The prepare node registers the batch (charge + saved plan; the execute node
    resumes it). This answers the router's question -- "does the registered
    batch still have entries to execute, reuse, replay or block?" -- from the
    **saved plan**, never from ``closed``.

    ``closed``/``finished`` are deliberately not consulted. Charging the last
    allowed round sets them (no *new* batch may start), but the calls that round
    approved were decided before that and still have to run or be answered; a
    cap that discards an approved plan turns the last round into a silent
    block.

    A call the execute node has already answered -- it ran, was replayed,
    reused or blocked -- is on record in ``results`` and no longer pending. A
    batch with any other execute, reuse or replay goes through
    ``market_tool_execute`` even when its round spent the allowance: the plan's
    own messages are what pair it, and neither the analyst nor the wrap-up may
    be handed a tool call that still owes a result. Only a batch with no saved
    plan (nothing was registered) skips straight to the wrap-up.
    """
    last = (state.get("messages") or [None])[-1]
    if not isinstance(last, AIMessage):
        return False
    calls = _calls_of(last)
    if not calls:
        return False
    scope = scope_of(governance_state_of(state))
    plan = saved_plan(scope, calls)
    if plan is None:
        return False
    decisions, results = plan
    for call_id, decision in decisions.items():
        if decision.get("action") == "block":
            continue  # the plan carries this call's block message
        if str(call_id) in results:
            continue  # already answered (ran, replayed, reused or blocked)
        if decision.get("action") == "execute" and scope.get("finished"):
            continue  # cannot run any more; the resume blocks it
        return True
    return False


def pending_calls(state: Mapping[str, Any]) -> list[str]:
    """The last batch's calls that nobody may run, if any.

    Answers the router's question of a tool-call turn: "which calls are left
    without a reply that this run can no longer produce?" The caller asks it
    only when the allowance is spent. A call is **not** pending when

    * the saved plan blocks it (the plan's own block message answers it),
    * ``results`` already records it (it ran, was replayed, reused or blocked),
    * the plan says ``execute`` and the analyst is ``finished`` (the tools are
      closed; the resume blocks it),

    so a batch the graph has fully planned and paired returns ``[]``. Anything
    else -- no saved plan for this batch, a call the plan refuses to execute,
    or an approved call nobody may run -- is returned by id: routing on would
    leave a dangling tool call.
    """
    last = (state.get("messages") or [None])[-1]
    if not isinstance(last, AIMessage):
        return []
    calls = _calls_of(last)
    if not calls:
        return []
    scope = scope_of(governance_state_of(state))
    plan = saved_plan(scope, calls)
    if plan is None:
        return [str(call.get("id")) for call in calls if call.get("id") is not None]
    decisions, results = plan
    finished = bool(scope.get("finished"))
    pending: list[str] = []
    for call in calls:
        call_id = call.get("id")
        if call_id is None:
            continue
        decision = decisions.get(call_id) or {}
        if decision.get("action") == "block":
            continue  # the plan carries this call's block message
        if str(call_id) in results:
            continue  # already answered (ran, replayed, reused or blocked)
        if decision.get("action") == "execute" and finished:
            continue  # cannot run any more; the resume blocks it
        pending.append(str(call_id))
    return pending


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def create_market_governance_nodes(*, llm: Any, tool_node: Any) -> dict[str, Any]:
    """Build the three market governance nodes for one run graph.

    ``llm`` is the market analyst's model (one unbound wrap-up call);
    ``tool_node`` is the graph's own market ``ToolNode`` (dispatched through
    the executor -- never stored in state).
    """
    return {
        "prepare": _make_prepare(tool_node),
        "execute": _make_execute(tool_node),
        "finish": _make_finish(),
        "wrap_up": _make_wrap_up(llm),
    }


def _make_prepare(tool_node: Any):
    def market_tool_prepare(state: Mapping[str, Any]) -> dict[str, Any]:
        governance = governance_state_of(state)
        last = (state.get("messages") or [None])[-1]
        if not isinstance(last, AIMessage):
            return {GOVERNANCE_STATE_KEY: governance}
        calls = _calls_of(last)
        if not calls:
            # Nothing to register: the analyst is done with the tools.
            return {GOVERNANCE_STATE_KEY: governance}

        executor = _executor(tool_node, state=state, run_id=governance["run_id"])
        try:
            prepared = executor.prepare(
                governance,
                calls,
                run_state=run_state_of(state),
                config=live_config(state),
            )
        except GovernanceBatchError as exc:
            # Unusable before anything runs. Its calls are still paired (as
            # blocked) so the wrap-up is not left with a dangling tool call.
            logger.warning("market tool round refused: %s", exc)
            return {
                GOVERNANCE_STATE_KEY: _refuse(
                    governance, calls, str(exc), governance["run_id"]
                )
            }
        # This update is what the graph saves: the round is charged and its plan
        # stored, so the execute node resumes it instead of charging again.
        saved = prepared.state[GOVERNANCE_STATE_KEY]
        plan = prepared.plan
        if not plan.execute and not plan.reuse:
            # Nothing here will be dispatched (e.g. every call was blocked
            # because the allowance is spent): the plan's own messages are the
            # batch's answers, so emit them now -- the analyst must never be
            # left with a tool call that has no reply.
            return {
                GOVERNANCE_STATE_KEY: _record_blocked(saved, plan),
                "messages": [_tool_message(entry["tool_message"]) for entry in plan.block],
            }
        return {GOVERNANCE_STATE_KEY: saved}

    return market_tool_prepare


def _refuse(
    governance: Mapping[str, Any],
    calls: list[dict[str, Any]],
    reason: str,
    run_id: str,
) -> dict[str, Any]:
    """Record a batch that could not be planned: none of its calls ran."""
    # A first refused batch still needs the analyst's complete record shape, so
    # the counters and flags never read as missing.
    scope = scope_of(governance) or get_scope(governance, ANALYST, run_id, create=True)
    results = dict(scope.get("results") or {})
    refused = 0
    for call in calls:
        call_id = call.get("id")
        if call_id is None or str(call_id) in results:
            continue
        results[str(call_id)] = {
            "status": "error",
            "text": f"{BLOCK_PREFIX}: call refused before execution ({reason}).",
        }
        refused += 1
    if refused:
        scope["results"] = results
        scope["blocked"] = scope.get("blocked", 0) + refused
        scope["closed"] = True
    analysts = dict(governance.get("analysts") or {})
    analysts[ANALYST] = scope
    return {**dict(governance), "analysts": analysts}


def _make_execute(tool_node: Any):
    def market_tool_execute(state: Mapping[str, Any]) -> dict[str, Any]:
        governance = governance_state_of(state)
        last = (state.get("messages") or [None])[-1]
        if not isinstance(last, AIMessage):
            return {GOVERNANCE_STATE_KEY: governance}
        calls = _calls_of(last)
        if not calls:
            return {GOVERNANCE_STATE_KEY: governance}

        executor = _executor(tool_node, state=state, run_id=governance["run_id"])
        try:
            prepared = executor.prepare(
                governance,
                calls,
                dispatched=True,  # resume the saved plan: never a new round
                run_state=run_state_of(state),
                config=live_config(state),
            )
        except GovernanceBatchError as exc:
            # The saved registration is not in the state: charging a round here
            # would pretend the graph saved what it did not.
            raise MarketGovernanceError(
                "the saved registration for this tool round is missing; the "
                "execute node refuses to charge a new round "
                f"({exc})"
            ) from exc
        if prepared.plan.rounds:
            # Same rule if a plan is somehow returned with a charge attached.
            raise MarketGovernanceError(
                "the saved registration for this tool round is missing; the "
                "execute node refuses to charge a new round"
            )
        execution = executor.execute(prepared)
        governance = execution.state[GOVERNANCE_STATE_KEY]
        # A blocked call has had its one answer; record it as its result so the
        # batch is queued as answered and the analyst is asked for its report
        # next -- never re-sent to execute the same plan again.
        governance = _record_blocked(governance, prepared.plan)
        return {
            GOVERNANCE_STATE_KEY: governance,
            "messages": [_tool_message(payload) for payload in execution.messages],
        }

    return market_tool_execute


def _record_blocked(
    governance: Mapping[str, Any], plan: Any
) -> dict[str, Any]:
    """Remember each blocked call of ``plan`` as answered (never a success)."""
    blocked = getattr(plan, "block", ()) or ()
    if not blocked:
        return dict(governance)
    scope = scope_of(governance)
    results = dict(scope.get("results") or {})
    changed = False
    for entry in blocked:
        call_id = str(entry.get("id"))
        if call_id in results:
            continue
        results[call_id] = {
            "status": "blocked",
            "fingerprint": entry.get("fingerprint"),
            "text": (entry.get("tool_message") or {}).get("content") or "",
        }
        changed = True
    if not changed:
        return dict(governance)
    scope["results"] = results
    analysts = dict(governance.get("analysts") or {})
    analysts[ANALYST] = scope
    return {**dict(governance), "analysts": analysts}


def _tool_message(payload: Mapping[str, Any]) -> ToolMessage:
    """A real ``ToolMessage`` for one paired call (a blocked one is marked)."""
    content = payload.get("content") or ""
    if content.startswith(BLOCK_PREFIX):
        content = f"{content}\n\n{_BLOCK_NOTE}"
    message = ToolMessage(
        content=content,
        tool_call_id=str(payload.get("tool_call_id")),
        name=payload.get("name"),
    )
    if payload.get("status") == "error":
        message.status = "error"
    return message


def _make_finish():
    def market_finish(state: Mapping[str, Any]) -> dict[str, Any]:
        """The analyst wrote its own report: record it as the run's report.

        A plain-text final answer is the report. Mark the analyst ``finished``
        so a re-entry writes nothing that could overwrite it, and keep the text
        as ``market_report`` for the downstream nodes.

        An answer that is not a report -- a refusal, a token-limit cut-off, or
        an empty body -- raises. It is not stored as ``market_report``, the
        analyst is not marked finished, and nothing is generated a second time.
        """
        governance = governance_state_of(state)
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages else None
        report = analyst_report(last)
        if not report:
            if last is None or not isinstance(last, AIMessage):
                raise MarketGovernanceError(
                    "market_finish reached without the analyst's final message; "
                    "no report was written"
                )
            if getattr(last, "tool_calls", None):
                raise MarketGovernanceError(
                    "market_finish reached while the analyst still asks for "
                    "tools; no report was written"
                )
            # A usable plain-text answer is guaranteed here: the router only
            # sends a non-empty one to finish. Anything else reached this node
            # by mistake and must not be stored as a report.
            reject_unusable_response(last, "market_finish")
            raise MarketGovernanceError(
                "market_finish reached with an answer that is not a report; "
                "no report was written"
            )
        scope = scope_of(governance)
        scope = {**scope, "finished": True, "closed": True}
        analysts = dict(governance.get("analysts") or {})
        analysts[ANALYST] = scope
        return {
            GOVERNANCE_STATE_KEY: {**governance, "analysts": analysts},
            "market_report": report,
        }

    return market_finish


def _make_wrap_up(llm: Any):
    def market_wrap_up(state: Mapping[str, Any]) -> dict[str, Any]:
        governance = governance_state_of(state)
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages else None

        own_report = analyst_report(last)
        if own_report:
            # Reached only if a caller skips the finish node: never spend a
            # second generation replacing the analyst's own report.
            scope = scope_of(governance)
            scope = {**scope, "finished": True, "closed": True}
            analysts = dict(governance.get("analysts") or {})
            analysts[ANALYST] = scope
            return {
                "market_report": own_report,
                GOVERNANCE_STATE_KEY: {**governance, "analysts": analysts},
            }

        # Every call the model already issued owes it one message, before the
        # report and without running anything.
        if isinstance(last, AIMessage):
            messages.extend(_answer_final_calls(messages, governance))

        result = llm.invoke(_wrap_up_prompt(state, messages))

        # A refusal, a token-limit cut-off, an empty body or a request for more
        # tools is final: raise, so nothing is stored and nothing is generated
        # again (the same guard the analyst's own text goes through).
        reject_unusable_response(result, "market wrap-up")
        report = _text_of(result.content)

        scope = scope_of(governance)
        scope["finished"] = True
        scope["closed"] = True
        analysts = dict(governance.get("analysts") or {})
        analysts[ANALYST] = scope
        return {
            "messages": [result],
            "market_report": report,
            GOVERNANCE_STATE_KEY: {**governance, "analysts": analysts},
        }

    return market_wrap_up


def _answer_final_calls(
    messages: list[Any], governance: Mapping[str, Any]
) -> list[ToolMessage]:
    """One ``ToolMessage`` per still-unpaired call of the last model message.

    A call with a recorded result restates it; any other is blocked. Nothing
    here runs a tool.
    """
    last = messages[-1]
    results = scope_of(governance).get("results") or {}
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
                f"{BLOCK_PREFIX}: this call was not run; the analyst's tool "
                "allowance is spent. Use the evidence already collected and "
                f"state explicitly what is missing.\n\n{_BLOCK_NOTE}"
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
        "You are the Market Analyst. The tool-call allowance for this run is "
        "spent, so you cannot call any tool now. Using ONLY the tool results "
        "already present in this conversation, write the market report.\n\n"
        "Rules:\n"
        "- Do not invent indicators, prices, volumes or any numeric value. Every "
        "exact OHLCV, price-level or indicator-value claim must come from the "
        "verified market snapshot in this conversation; if that snapshot is "
        "absent or unavailable, do not state exact numbers and say so.\n"
        "- Explicitly list what data is missing. A blocked or empty call means "
        "the data was not collected, not that it does not exist.\n"
        "- Do not claim historical validation, support/resistance bounces or "
        "exact percentage moves unless the tool output supports them with "
        "concrete dates and prices.\n"
        "- Write a detailed market report and end with a Markdown summary "
        "table."
        f"{get_language_instruction()}"
    )
    human = (
        f"Instrument: {state.get('company_of_interest', '')}. "
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
    if isinstance(message, (AIMessage, HumanMessage, SystemMessage, ToolMessage)):
        return message
    from langchain_core.messages import convert_to_messages

    return convert_to_messages([message])[0]


__all__ = [
    "ANALYST",
    "BLOCK_PREFIX",
    "MarketGovernanceError",
    "analyst_report",
    "confirms_success",
    "create_market_governance_nodes",
    "governance_state_of",
    "live_config",
    "market_run_id",
    "pending_calls",
    "prepared_work",
    "run_state_of",
    "scope_of",
]
