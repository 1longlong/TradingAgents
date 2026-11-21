"""Governance for the tools an analyst model asks for.

This module limits **the model's tool requests** -- how many rounds it may cycle
through ``model -> tools -> model`` and how many calls it may issue -- and
recognises a repeat of a request whose result is already known. It does **not**
retry, throttle or count the data requests a tool makes internally: bounded
vendor retries and the vendor circuit breaker (``dataflows.retry_session`` /
``dataflows.vendor_breaker``) keep owning that layer, and the two counters are
never mixed.

Scope of this module (deliberately narrow, first batch):

* **planning** never calls a tool, never builds a ``ToolNode`` and never
  touches a graph;
* **execution** is a separate, opt-in step (:class:`ToolExecutor`) that runs a
  plan through the analyst's own ``ToolNode``; it is **not** wired into the
  production graph;
* everything it stores is a plain ``dict``/``str``/``int`` -- serialisable, and
  free of model, tool or message instances;
* reuse is only ever inside **one analyst of one run**. There is no cache that
  survives a run, and no cross-analyst sharing: the message state is wiped
  between analysts, so an analyst could not rely on another's evidence anyway.

The entry points are:

``ToolLimits``          -- the caps, each tied to the one counter it bounds.
``plan_tool_round``     -- pure: split a batch of calls into execute/reuse/block,
                           or resume a batch already on record.
``record_round_start``  -- execution actually began: spend the round/call
                           allowance for what is still going to be executed.
``record_tool_result``  -- store one result (only a confirmed, reusable success
                           is kept for reuse), idempotently per ``tool_call_id``.
``ToolExecutor.execute``-- run one planned round: dispatch only the permitted
                           calls to the analyst's real ``ToolNode``, answer
                           reuse/replay/block from the plan, record every
                           result, and return one message per call.

Counting, in one place (``rounds``/``requested``/``executed``/``reused``/
``blocked`` are all counted in **tool calls**, never in HTTP or vendor
requests):

* ``rounds`` -- one per model batch, whether it executed, reused or blocked;
* ``requested`` -- the calls the rules decided, i.e. the calls that were a
  usable request at all: ``requested == executed + reused + blocked`` with
  ``blocked`` counting only *decided* blocks;
* ``malformed`` -- the calls that were not a usable request at all (not a
  mapping, no id, no name, args not a mapping, unknown tool, schema violation).
  They are never decided, never executed, never reused, and never paired with a
  message; they are counted here and in ``blocked``, and **not** in
  ``requested``. So for a whole record:
  ``requested + malformed == executed + reused + blocked``;
* ``executed`` -- calls planned to run (charged when the round starts, before
  any call is dispatched);
* ``reused`` -- calls answered from a confirmed success on record;
* ``blocked`` -- calls the rules refused (limits, duplicates) plus ``malformed``.

An aborted batch (a malformed call, or a batch that cannot be identified)
charges nothing: its plan has every count at 0, no execution decision and no
``tool_message`` -- the caller gets a ``ToolPlan.invalid`` entry and must fail
the batch instead.

The fingerprint refuses to stand in for the tool's own validation: it only adds
the defaults the schema declares and the run date in place of an omitted
*required* date (which the framework injects before validation, see
``NON_MODEL_ARGS``). It never repairs a missing or malformed argument, so a call
the tool would reject can never match the fingerprint of one that ran.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from inspect import get_annotations
from typing import Any, TypedDict

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.dataflows.date_window import as_of, as_of_window
from tradingagents.dataflows.interface import get_category_for_method, get_vendor
from tradingagents.dataflows.symbol_utils import normalize_symbol

SCHEMA_VERSION = 1

# --- outcome kinds ---------------------------------------------------------
# What a tool result *is*, from the governance layer's point of view. Only
# CACHEABLE_SUCCESS may be stored for reuse; everything else is recorded so the
# caller can see what happened, and is never served again from the record.
CACHEABLE_SUCCESS = "cacheable_success"
MISSING_DATA = "missing_data"   # a vendor-confirmed absence (NO_DATA_AVAILABLE)
DEGRADED = "degraded"           # the chain could not answer (DATA_UNAVAILABLE)
ERROR = "error"                 # the call raised
UNKNOWN = "unknown"             # no positive success signal
REFUSED_TIMEOUT = "refused_timeout"  # an allowed call that never produced a result
NON_REUSABLE_SUCCESS = "non_reusable_success"  # confirmed, but never served again

NON_CACHEABLE_OUTCOMES = frozenset(
    {MISSING_DATA, DEGRADED, ERROR, UNKNOWN, REFUSED_TIMEOUT, NON_REUSABLE_SUCCESS}
)

# The absence/degradation prefixes ``route_to_vendor`` writes into the tool
# result. They are context, never proof of success: a result is not cacheable
# because it avoids them (see ``classify_tool_result``).
_ABSENCE_PREFIX = "NO_DATA_AVAILABLE"
_DEGRADED_PREFIX = "DATA_UNAVAILABLE"

# --- block reasons ---------------------------------------------------------
BLOCK_ROUND_LIMIT = "round_limit"         # the analyst used all its tool rounds
BLOCK_CALL_LIMIT = "call_limit"           # the analyst used all its tool calls
BLOCK_DUPLICATE_IN_BATCH = "duplicate_in_batch"  # same request twice in one batch
BLOCK_DUPLICATE_FAILED = "duplicate_failed"      # a failure for it is on record
BLOCK_DUPLICATE_CALL_ID = "duplicate_call_id"    # same id twice in one batch
BLOCK_INVALID_CALL = "invalid_call"       # not a usable request: no id/name/args

# --- invalidity causes -----------------------------------------------------
# A batch that cannot be planned at all, or one call inside a batch that cannot
# be planned. Neither ever produces an execution entry or a ``tool_message``.
INVALID_CALL_NONE = "call_not_mapping"
INVALID_CALL_MISSING_ID = "missing_id"
INVALID_CALL_MISSING_NAME = "missing_name"
INVALID_CALL_ARGS = "args_not_mapping"
INVALID_CALL_UNKNOWN_TOOL = "unknown_tool"
INVALID_CALL_SCHEMA = "schema_violation"

INVALID_BATCH_NONE = "batch_not_string"
INVALID_BATCH_EMPTY = "batch_empty"
INVALID_BATCH_CALL = "batch_element_not_mapping"
INVALID_BATCH_MISSING_ID = "batch_element_missing_id"
INVALID_BATCH_DUPLICATE_ID = "batch_duplicate_id"
INVALID_BATCH_CHANGED = "batch_call_changed"
INVALID_BATCH_REPLAY_ONLY = "batch_replayed_in_full"


def _empty_scope(analyst: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    """A fresh, serialisable per-analyst record (the shape stored in state)."""
    return {
        "version": SCHEMA_VERSION,
        "analyst": analyst,
        "run_id": run_id,
        "rounds": 0,
        "requested": 0,
        "executed": 0,
        "reused": 0,
        "blocked": 0,
        # Calls that were not a usable request at all (see the module docstring).
        "malformed": 0,
        "outcomes": dict.fromkeys(sorted(NON_CACHEABLE_OUTCOMES), 0),
        "closed": False,
        # finished: the report exists, so a re-entry must write nothing that
        # could overwrite it (see ``write_report``).
        "finished": False,
        # fingerprint -> {"status", "text", "tool_call_id"}: cacheable successes
        # only.
        "cache": {},
        # fingerprint -> {"status", "tool_call_id", "reason"}: what this analyst
        # asked for and did not get, so a repeat is not expected to do better.
        "attempts": {},
        # tool_call_id -> {"status", "fingerprint"}: idempotency per call.
        "results": {},
        # batch id -> {call id -> decision}: the plan of a charged round, so a
        # replay resumes it instead of being planned again.
        "planned_rounds": {},
        # batch id -> the charge marker (how many rounds it spent); written with
        # the plan and the counters in the same update.
        "charged_rounds": {},
    }


def new_state(run_id: str | None = None) -> dict[str, Any]:
    """An empty governance state, ready to be stored under ``tool_governance``.

    ``run_id`` identifies one run of the graph. Two runs (or two analysts) with
    different ``run_id``/``analyst`` keys never share a record.
    """
    return {"version": SCHEMA_VERSION, "run_id": run_id, "analysts": {}}


def get_scope(
    state: Mapping[str, Any] | None,
    analyst: str,
    run_id: str | None = None,
    *,
    create: bool = False,
) -> dict[str, Any]:
    """The analyst's record, or an empty one (never shared, never mutated).

    A record written under a different ``run_id`` is not reused: it is replaced
    by a fresh record when ``create`` is set, so a stale record from a previous
    run in the same state cannot leak evidence into this one.
    """
    if not state:
        return _empty_scope(analyst if create else None, run_id)
    analysts = state.get("analysts") or {}
    scope = analysts.get(analyst)
    if not isinstance(scope, Mapping):
        return _empty_scope(analyst if create else None, run_id)
    if run_id is not None and scope.get("run_id") not in (None, run_id):
        return _empty_scope(analyst if create else None, run_id)
    return dict(scope)


def with_scope(
    state: Mapping[str, Any] | None,
    analyst: str,
    scope: Mapping[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    """Return ``state`` with ``analyst``'s record replaced by ``scope``."""
    base = dict(state or {})
    base["version"] = SCHEMA_VERSION
    if run_id is not None:
        base["run_id"] = run_id
    analysts = dict(base.get("analysts") or {})
    analysts[analyst] = dict(scope)
    base["analysts"] = analysts
    return base


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

# tool name -> the model-visible argument schema (JSON schema). Metadata only:
# the objects are never stored in the state and never called. Only tools given
# here can be governed; every other name is a malformed call (there is no
# schema to check a fingerprint against), which is the safe default.
_tool_schemas: dict[str, Mapping[str, Any]] | None = None

# The same tool objects the analysts bind. Imported lazily so this module stays
# importable (and testable) without the dataflow vendor stack.
_DEFAULT_TOOL_FACTORIES = (
    "tradingagents.agents.utils.agent_utils:get_stock_data",
    "tradingagents.agents.utils.agent_utils:get_indicators",
    "tradingagents.agents.utils.agent_utils:get_verified_market_snapshot",
    "tradingagents.agents.utils.agent_utils:get_news",
    "tradingagents.agents.utils.agent_utils:get_global_news",
    "tradingagents.agents.utils.agent_utils:get_insider_transactions",
    "tradingagents.agents.utils.agent_utils:get_macro_indicators",
    "tradingagents.agents.utils.agent_utils:get_prediction_markets",
    "tradingagents.agents.utils.agent_utils:get_fundamentals",
    "tradingagents.agents.utils.agent_utils:get_balance_sheet",
    "tradingagents.agents.utils.agent_utils:get_cashflow",
    "tradingagents.agents.utils.agent_utils:get_income_statement",
)

# Tool categories whose output is a stable, non-live snapshot of past data. Only
# these may ever be reused. ``news_data`` (ticker news, global news) and
# ``prediction_markets`` (live probabilities) are excluded on purpose, and
# ``get_insider_transactions`` carries no date at all, so it is excluded by name.
REUSABLE_CATEGORIES = frozenset(
    {"core_stock_apis", "technical_indicators", "fundamental_data", "macro_data"}
)
NON_REUSABLE_TOOLS = frozenset({"get_insider_transactions"})


def _load_default_schemas() -> dict[str, Mapping[str, Any]]:
    import importlib

    schemas: dict[str, Mapping[str, Any]] = {}
    for spec in _DEFAULT_TOOL_FACTORIES:
        module_name, _, attr = spec.partition(":")
        try:
            tool = getattr(importlib.import_module(module_name), attr)
            schemas[tool.name] = tool.tool_call_schema.model_json_schema()
        except (ImportError, AttributeError, TypeError):
            continue
    return schemas


def _schemas() -> dict[str, Mapping[str, Any]]:
    global _tool_schemas
    if _tool_schemas is None:
        _tool_schemas = _load_default_schemas()
    return _tool_schemas


def register_tool_schema(name: str, schema: Mapping[str, Any]) -> None:
    """Add or replace one tool's argument schema (tests, out-of-tree tools)."""
    _schemas()[name] = schema


def tool_schema(name: str) -> Mapping[str, Any] | None:
    """The registered argument schema for ``name``, or None if not governed."""
    return _schemas().get(name)


# Arguments the model does not supply: ``InjectedState`` fields the framework
# fills (all of them are named ``trade_date`` today) and the tool's ``_``
# metadata. The framework injects them *before* validating call arguments, so
# the run date really is the value the tool will be validated with.
NON_MODEL_ARGS = frozenset({"trade_date", "_", "__root__"})


def is_reusable_read_only_tool(name: str) -> bool:
    """Whether a confirmed success of ``name`` may be served again.

    Unknown tools are not reusable: an unregistered tool cannot be shown to be
    a read-only snapshot, so its result is only ever used for the call that
    produced it.
    """
    if name in NON_REUSABLE_TOOLS or tool_schema(name) is None:
        return False
    try:
        return get_category_for_method(name) in REUSABLE_CATEGORIES
    except (ValueError, KeyError):
        return False


# ---------------------------------------------------------------------------
# Argument validation (the same rules the tool itself applies)
# ---------------------------------------------------------------------------

_SCALAR_TYPES: Mapping[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": (list, tuple),
    "object": Mapping,
}


def _matches_type(value: Any, json_type: str) -> bool:
    expected = _SCALAR_TYPES.get(json_type)
    if expected is None:  # unknown type keyword: do not claim to validate it
        return True
    if json_type in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _matches_spec(value: Any, spec: Any) -> bool:
    """Whether ``value`` satisfies one schema property (type + anyOf/oneOf).

    ``None`` matches only when the spec admits ``null``: the ``int | None``
    arguments (``limit``, ``look_back_days``) accept it, a bare ``str`` does not.
    """
    if value is None:
        return "null" in _declared_types(spec)
    declared = _declared_types(spec)
    if not declared:  # no type information: cannot reject
        return True
    return any(_matches_type(value, name) for name in declared)


def _declared_types(spec: Any) -> list[str]:
    if not isinstance(spec, Mapping):
        return []
    names: list[str] = []
    if isinstance(spec.get("type"), str):
        names.append(spec["type"])
    for key in ("anyOf", "oneOf"):
        for option in spec.get(key) or ():
            if isinstance(option, Mapping) and isinstance(option.get("type"), str):
                names.append(option["type"])
    return names


def _schema_defaults(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = (schema or {}).get("properties") or {}
    return {
        name: spec["default"]
        for name, spec in properties.items()
        if isinstance(spec, Mapping) and "default" in spec
    }


def _validate_args(
    schema: Mapping[str, Any] | None,
    args: Mapping[str, Any],
    trade_date: str | None = None,
) -> str | None:
    """Return the reason ``args`` would fail the tool's validation, or None.

    Covers what the tool's own pydantic model checks before the body runs: the
    tool must be known, every model-supplied argument must be a declared name,
    required arguments must be present (an omitted required ``trade_date`` is
    injected, so it is present), values must match their declared JSON type,
    and ``int``-only arguments must not be booleans.
    """
    if schema is None:
        return INVALID_CALL_UNKNOWN_TOOL
    properties = schema.get("properties") or {}
    required = list(schema.get("required") or ())
    if trade_date and "trade_date" in properties:
        required = [name for name in required if name != "trade_date"]
    for name in args:
        if name not in properties:
            return f"unexpected_argument:{name}"
    for name in required:
        if name not in args:
            return f"missing_required:{name}"
    for name, value in args.items():
        if name in NON_MODEL_ARGS:
            continue
        if not _matches_spec(value, properties[name]):
            return f"type_mismatch:{name}"
    return None


class MalformedCallError(ValueError):
    """A call that must not be planned: it never gets an execution entry."""

    def __init__(self, call_id: str | None, reason: str) -> None:
        super().__init__(f"{call_id!r}: {reason}")
        self.call_id = call_id
        self.reason = reason


def _entry_id(call: Any) -> str | None:
    """The call's id as a string, or None when it has no usable id."""
    if not isinstance(call, Mapping):
        return None
    value = call.get("id")
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return None
    text = str(value)
    return text if text else None



def validate_call(
    call: Any,
    *,
    schema: Mapping[str, Any] | None | object = ...,
    trade_date: str | None = None,
) -> str:
    """Raise :class:`MalformedCallError` when ``call`` is not a usable request.

    Returns the call id when it is usable. A malformed call is never executed
    and never paired with a ``tool_message``: it produces no execution entry,
    so it can neither be served from the cache nor run.
    """
    if not isinstance(call, Mapping):
        raise MalformedCallError(None, INVALID_CALL_NONE)
    call_id = _entry_id(call)
    if call_id is None:
        raise MalformedCallError(None, INVALID_CALL_MISSING_ID)
    name = call.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MalformedCallError(call_id, INVALID_CALL_MISSING_NAME)
    args = call.get("args")
    if args is None:
        args = {}
    if not isinstance(args, Mapping):
        raise MalformedCallError(call_id, INVALID_CALL_ARGS)
    resolved = tool_schema(name) if schema is ... else schema
    if resolved is None:
        raise MalformedCallError(call_id, INVALID_CALL_UNKNOWN_TOOL)
    reason = _validate_args(resolved, args, trade_date)
    if reason is not None:
        raise MalformedCallError(call_id, f"{INVALID_CALL_SCHEMA}:{reason}")
    return call_id


def _payload_of(result: Any) -> Any:
    content = getattr(result, "content", result)
    return content


def _leading_text(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, list):
        return ""
    if not isinstance(content, str):
        return ""
    return content.lstrip()


def classify_tool_result(
    result: Any,
    *,
    raised: bool = False,
    cacheable_success: bool | None = None,
) -> str:
    """Say what ``result`` is, without ever inferring success from absence.

    * raised -> ``ERROR``;
    * no result at all (``None``/empty/empty list) -> ``UNKNOWN``;
    * a ``FunctionMessage`` -> ``UNKNOWN``: the tool ran and said something,
      which is not a confirmation that it returned data;
    * text starting with the router's absence marker -> ``MISSING_DATA``;
    * text starting with the router's degradation marker -> ``DEGRADED``;
    * otherwise ``CACHEABLE_SUCCESS`` **only** when ``cacheable_success=True``.
      Passing ``None`` means "no confirmation", so the result stays ``UNKNOWN``;
      an unrecognised text is never promoted to success just because it avoids
      the two markers.
    """
    if raised:
        return ERROR
    if result is None:
        return UNKNOWN
    payload = _payload_of(result)
    if payload is None or (isinstance(payload, str) and not payload.strip()):
        return UNKNOWN
    if isinstance(payload, list) and not payload:
        return UNKNOWN
    if type(result).__name__ == "FunctionMessage":
        return UNKNOWN
    text = _leading_text(result)
    if text.startswith(_ABSENCE_PREFIX):
        return MISSING_DATA
    if text.startswith(_DEGRADED_PREFIX):
        return DEGRADED
    if cacheable_success is True:
        return CACHEABLE_SUCCESS
    return UNKNOWN


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolLimits:
    """Caps for one analyst.

    Each cap bounds exactly one counter, and none of them counts HTTP requests
    or vendor attempts (that is the retry/budget layer's business):

    * ``max_rounds`` bounds **rounds** -- one per batch of tool calls the model
      issued, whether the batch was executed, reused or blocked;
    * ``max_calls`` bounds **executed** calls -- calls actually handed to the
      tools. A reused call already has its answer and is not executed again, so
      it spends no execution allowance; it still spends a round.

    ``None`` disables that cap (the run-level recursion limit still applies).
    """

    max_rounds: int | None = None
    max_calls: int | None = None
    # Reserved: a run-level remaining budget the caller may pass in. Governs the
    # same two counters (never a vendor request count); used only through
    # ``effective()``, which tightens and never loosens.
    remaining_budget: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        for name in ("max_rounds", "max_calls"):
            _check_cap(name, getattr(self, name))
        budget = self.remaining_budget
        if budget is not None:
            for key in ("max_rounds", "max_calls"):
                _check_cap(f"remaining_budget[{key!r}]", budget.get(key))

    def effective(self) -> ToolLimits:
        """These limits tightened by the received run-level remaining budget.

        The budget reserves headroom for a caller's own caps; it never loosens
        one, and it is expressed in the same ``rounds``/``calls`` counters.
        """
        if not self.remaining_budget:
            return self
        return ToolLimits(
            max_rounds=_tighten(self.max_rounds, self.remaining_budget.get("max_rounds")),
            max_calls=_tighten(self.max_calls, self.remaining_budget.get("max_calls")),
        )


def _check_cap(name: str, value: Any) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative int or None, got {value!r}")


def _tighten(cap: int | None, remaining: int | None) -> int | None:
    if remaining is None:
        return cap
    return remaining if cap is None else min(cap, remaining)


def round_limit_reached(scope: Mapping[str, Any], limits: ToolLimits) -> bool:
    """Whether this analyst may start no further tool round at all."""
    limits = limits.effective()
    if scope.get("closed") or scope.get("finished"):
        return True
    if limits.max_rounds is not None and scope.get("rounds", 0) >= limits.max_rounds:
        return True
    return limits.max_calls is not None and scope.get("executed", 0) >= limits.max_calls


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

# The only parameters a model normally supplies that name an instrument. They
# are normalised with ``normalize_symbol`` and then folded into the injected
# instrument identity, so ``aapl`` and the run's ``AAPL`` are one request while
# an explicit ``MSFT`` in a run on ``AAPL`` is not.
SYMBOL_PARAMS = frozenset({"symbol", "ticker"})

# Arguments a *tool* rewrites internally before serving. Only these two rules
# are applied when building the fingerprint, because they are what the tool
# actually does after validation:
#
# * ``(start_date, end_date)`` -> ``as_of_window(start, end, trade_date)``
#   (``get_stock_data``, ``get_news``);
# * ``curr_date`` -> ``as_of(curr, trade_date)`` (the tools in
#   ``_AS_OF_METHODS``, none of which has a date it does not pass through it).
#
# The rules are the tools' own functions, so an unparseable date is kept
# verbatim, exactly as the tool keeps it.
CURR_DATE_PARAM = "curr_date"
# Tool names whose body calls ``as_of(curr_date, trade_date)``. A tool outside
# this set (e.g. ``get_insider_transactions``, which takes no date) is not
# rewritten.
_AS_OF_METHODS = frozenset(
    {
        "get_indicators",
        "get_verified_market_snapshot",
        "get_global_news",
        "get_fundamentals",
        "get_balance_sheet",
        "get_cashflow",
        "get_income_statement",
        "get_macro_indicators",
    }
)


def _vendor_chain(tool_name: str) -> str | None:
    """The configured vendor chain for ``tool_name``, or None if unknown.

    Changing ``data_vendors``/``tool_vendors`` changes who answers, so it must
    change the fingerprint; a tool outside the router's categories has no chain.
    """
    try:
        return str(get_vendor(get_category_for_method(tool_name), tool_name))
    except (ValueError, KeyError):
        return None


@dataclass(frozen=True)
class ToolContext:
    """Everything about the run that a fingerprint needs, computed once.

    Building it resolves the schema and the vendor chain of each tool name
    (``dataflows.interface``: the same routing the tools themselves use), then
    :meth:`fingerprint` stays a pure, cheap call.
    """

    analyst: str
    run_id: str | None = None
    instrument: str | None = None
    trade_date: str | None = None
    schemas: Mapping[str, Mapping[str, Any]] | None = None
    vendor_chains: Mapping[str, str | None] | None = None
    default_limit: Any = None

    def schema_for(self, tool_name: str) -> Mapping[str, Any] | None:
        if self.schemas is not None and tool_name in self.schemas:
            return self.schemas[tool_name]
        return tool_schema(tool_name)

    def vendor_chain_for(self, tool_name: str) -> str | None:
        if self.vendor_chains is not None and tool_name in self.vendor_chains:
            return self.vendor_chains[tool_name]
        return _vendor_chain(tool_name)

    def fingerprint(self, call: Mapping[str, Any]) -> str:
        """Digest of one call. Raises :class:`MalformedCallError` if unusable."""
        name = call.get("name") if isinstance(call, Mapping) else None
        tool_name = name if isinstance(name, str) else ""
        return request_fingerprint(
            call,
            schema=self.schema_for(tool_name),
            analyst=self.analyst,
            run_id=self.run_id,
            instrument=self.instrument,
            trade_date=self.trade_date,
            vendor_chain=self.vendor_chain_for(tool_name),
            default_limit=self.default_limit,
        )


def _tool_date_rewrite(
    tool_name: str, args: Mapping[str, Any], trade_date: str | None
) -> dict[str, Any]:
    """Apply exactly the date rules the tool itself applies after validation.

    The table is explicit per tool so that a rule is never assumed from a
    parameter name: a tool outside it leaves its dates verbatim.

    * ``get_stock_data``/``get_news`` call ``as_of_window(start, end, trade_date)``;
    * the ``curr_date`` tools call ``as_of(curr, trade_date)`` *unconditionally*,
      so an omitted ``curr_date`` (schema default ``None``, see
      ``get_balance_sheet``) resolves to the run date inside the tool too.

    ``as_of``/``as_of_window`` are the tools' own functions: they keep an
    unparseable value verbatim, so a slash date stays a different request, and
    no value is invented here that the tool would not itself compute.
    """
    rewritten = dict(args)
    if not trade_date:
        return rewritten
    if tool_name in ("get_stock_data", "get_news"):
        start, end = rewritten.get("start_date"), rewritten.get("end_date")
        if isinstance(start, str) and isinstance(end, str):
            start, end = as_of_window(start, end, trade_date)
            rewritten["start_date"], rewritten["end_date"] = start, end
    elif tool_name in _AS_OF_METHODS:
        curr = rewritten.get(CURR_DATE_PARAM)
        if curr is None or isinstance(curr, str):
            rewritten[CURR_DATE_PARAM] = as_of(curr, trade_date)
    return rewritten


def _fingerprint_payload(
    call: Mapping[str, Any],
    schema: Mapping[str, Any] | None,
    *,
    analyst: str,
    run_id: str | None,
    instrument: str | None,
    trade_date: str | None,
    vendor_chain: str | None,
    default_limit: Any = None,
) -> dict[str, Any]:
    """The exact, JSON-ready input to the hash. No free-text normalisation.

    Only what is explicitly allowed changes here:

    * schema-declared defaults are added, so omitting ``look_back_days`` equals
      passing ``30`` -- nothing else is filled in;
    * an omitted *required* ``trade_date`` is added, because the framework
      injects the run date before validating;
    * ``symbol``/``ticker`` go through ``normalize_symbol``;
    * :func:`_tool_date_rewrite` -- the tool's own post-validation rules.

    Every other value is kept verbatim: ``"Fed rate cut"`` and ``"fed rate
    cut"`` stay two topics, ``"AAPL "`` is normalised only by the symbol rule,
    and lists or comma-separated values are never sorted (so ``[rsi, macd]``,
    ``[macd, rsi]`` and a partial indicator set are all distinct requests).
    """
    tool_name = str(call.get("name") or "")
    args = dict(call.get("args") or {})
    for key, value in _schema_defaults(schema or {}).items():
        args.setdefault(key, value)
    if trade_date and schema is not None:
        for name in schema.get("required") or ():
            if name in NON_MODEL_ARGS and name not in args:
                args[name] = trade_date

    params: dict[str, Any] = {}
    for key in sorted(args):
        value = args[key]
        if key in SYMBOL_PARAMS and isinstance(value, str) and value.strip():
            params[key] = normalize_symbol(value)
        else:
            params[key] = value
    for key, value in _tool_date_rewrite(tool_name, params, trade_date).items():
        params[key] = value

    # An omitted limit means "the configured default" only for tools that read
    # the configuration themselves; it is a different request from an explicit
    # ``None`` elsewhere.
    if default_limit is not None and params.get("limit") is None:
        params["limit"] = default_limit

    return {
        "tool": tool_name,
        "schema_version": SCHEMA_VERSION,
        "args": params,
        "analyst": analyst,
        "run_id": run_id,
        "instrument": normalize_symbol(instrument) if instrument else None,
        "trade_date": trade_date,
        "vendor_chain": vendor_chain,
    }


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def request_fingerprint(
    call: Mapping[str, Any],
    *,
    schema: Mapping[str, Any] | None | object = ...,
    analyst: str,
    run_id: str | None,
    instrument: str | None = None,
    trade_date: str | None = None,
    vendor_chain: str | None = None,
    default_limit: Any = None,
) -> str:
    """Stable digest of one request, scoped to this run and this analyst.

    ``schema`` is the schema to judge the call against: the tool's live one by
    default (``...``), an explicit one for a test/out-of-tree tool, and ``None``
    only to assert a tool is *not* governed. Raises
    :class:`MalformedCallError` for a call the tool would reject or that has no
    schema: such a call has no fingerprint, so it can never match the cached
    success of one that ran.
    """
    if vendor_chain is None:
        name = call.get("name") if isinstance(call, Mapping) else None
        vendor_chain = _vendor_chain(name) if isinstance(name, str) else None
    resolved = tool_schema(call.get("name")) if schema is ... else schema
    validate_call(call, schema=resolved, trade_date=trade_date)
    payload = _fingerprint_payload(
        call,
        resolved,
        analyst=analyst,
        run_id=run_id,
        instrument=instrument,
        trade_date=trade_date,
        vendor_chain=vendor_chain,
        default_limit=default_limit,
    )
    return _digest(payload)


# ---------------------------------------------------------------------------
# Planning a round
# ---------------------------------------------------------------------------


def _reuse_text(entry: Mapping[str, Any]) -> str:
    """The text a *new* request is served when an earlier success is reused."""
    text = entry.get("text") or ""
    return (
        f"{text}\n\n"
        "[Tool governance: this exact request already succeeded earlier in this "
        "analyst's run; the recorded result is reused instead of being fetched "
        "again. The message id is new; the content is the earlier output.]"
    )


def _message_status(outcome: Any) -> str | None:
    """The only ``ToolMessage`` status an outcome may carry: ``error`` or none.

    ``cacheable_success``/``missing_data``/``degraded``/``unknown`` are
    governance outcomes, not message statuses: a ``ToolMessage`` accepts
    ``success`` and ``error`` only, so a successful outcome carries no status
    (as a real successful message does) and an error carries ``"error"``.
    """
    return "error" if outcome == ERROR else None


def _preserving_tool_message(
    tool_call_id: str, text: str, status: str | None = None
) -> dict[str, Any]:
    """The ``tool_message`` pair of a call governance answers locally.

    ``status`` is carried through only when it is a legal message status (an
    error stays an error); no governance outcome ever becomes a status.
    """
    message: dict[str, Any] = {
        "type": "tool",
        "tool_call_id": tool_call_id,
        "content": text,
    }
    status = _message_status(status)
    if status is not None:
        message["status"] = status
    return message


def _replayed_message(
    tool_call_id: str, stored: Mapping[str, Any]
) -> dict[str, Any]:
    """The message restating *this call's own* recorded outcome, verbatim.

    This is a replay, not a reuse: the outcome may be a success, an error, a
    missing-data report or a degradation. The text and its status are kept
    exactly, no success claim is added, and the *current* call id is used.
    """
    return _preserving_tool_message(
        tool_call_id,
        stored.get("text") or "",
        stored.get("status"),
    )


@dataclass(frozen=True)
class ToolPlan:
    """One round's decisions, all plain dicts (serialisable).

    ``execute``/``reuse``/``block`` each hold one entry per decided call, in
    request order. ``reuse`` holds two different things, told apart by
    ``entry["action"]``:

    * ``"reuse"`` -- a **new** request answered by an earlier *confirmed
      success*; its text carries the reuse note, and ``source`` /
      ``source_tool_call_id`` name the call that produced it.
    * ``"replay"`` -- the **same** call whose own result is on record; its
      message is that result verbatim (content *and* status: an error stays an
      error, a missing-data report stays a missing-data report), with no success
      claim added.

    ``invalid`` holds the batch/call diagnostics that are not decisions: a
    non-empty ``invalid`` means the batch must not be executed at all
    (``ToolPlan.must_abort``), and it never contains a ``tool_message``.

    ``rounds`` is the number of rounds this plan still has to spend: 1 for a
    new batch, 0 for a dispatched replay or a batch that is already on record.

    ``mode`` is ``"new"``, ``"resume"`` (the batch is on record and has calls
    still to run) or ``"replay"`` (every call of the batch already has a result
    -- its messages are restated, nothing runs again).
    """

    round_key: str | None
    execute: tuple[dict[str, Any], ...]
    reuse: tuple[dict[str, Any], ...]
    block: tuple[dict[str, Any], ...]
    rounds: int
    requested: int
    executed: int
    reused: int
    blocked: int
    close_after_execute: bool = False
    mode: str = "new"
    resumed: bool = False
    invalid: tuple[dict[str, Any], ...] = ()
    invalid_reason: str | None = None
    messages: tuple[dict[str, Any], ...] = ()

    @property
    def must_abort(self) -> bool:
        """The batch is unusable: nothing may be executed or paired from it."""
        return bool(self.invalid)

    @property
    def executed_calls(self) -> tuple[dict[str, Any], ...]:
        """The calls to hand to a ToolNode, in request order.

        Each is a complete ``ToolCall`` (``name``, ``args``, ``id`` and
        ``type="tool_call"``), so a real ``ToolNode`` accepts the tuple as-is
        and every result comes back paired to its original ``tool_call_id``.
        """
        return tuple(entry["call"] for entry in self.execute)

    @property
    def executed_call_ids(self) -> tuple[str, ...]:
        return tuple(entry["id"] for entry in self.execute)

    @property
    def block_reasons(self) -> dict[str, str]:
        return {entry["id"]: entry["reason"] for entry in self.block}


def _call_payload(call: Mapping[str, Any]) -> dict[str, Any]:
    """A complete ``ToolCall``: omitting ``type`` breaks a real ``ToolNode``."""
    args = call.get("args")
    payload: dict[str, Any] = {
        "name": call.get("name"),
        "args": dict(args) if isinstance(args, Mapping) else {},
        "id": str(call.get("id")),
        "type": "tool_call",
    }
    if "index" in call:
        payload["index"] = call["index"]
    return payload


def _call_key(call: Mapping[str, Any]) -> str:
    """A stable digest of everything the model dictated about one call."""
    encoded = json.dumps(
        _call_payload(call), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _batch_key(call_ids: Iterable[str]) -> str:
    payload = json.dumps(list(call_ids), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def saved_plan(
    scope: Mapping[str, Any], calls: Iterable[Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The saved plan of exactly this batch, or ``None`` if it has none.

    Read-only companion to :func:`plan_tool_round`: it answers "what was
    decided for this batch?" without re-planning, so a router can tell an
    approved round whose cap is spent (the plan still has work to run) from one
    that has nothing left. Returns ``(decisions, results)``, decisions keyed by
    call id with the ``_dispatched`` ledger removed. A batch with any unusable
    call has no saved plan.
    """
    items, invalid, batch = inspect_batch(calls)
    del items
    if batch is None or invalid:
        return None
    saved = (scope.get("planned_rounds") or {}).get(batch)
    if not isinstance(saved, Mapping) or not saved:
        return None
    decisions = {key: dict(value) for key, value in saved.items() if key != "_dispatched"}
    return decisions, dict(scope.get("results") or {})


def inspect_batch(calls: Any) -> tuple[tuple[dict[str, Any], ...], list[dict[str, Any]], str | None]:
    """Check a batch before anything is keyed or looked up.

    Returns ``(calls, invalid, batch_key)``. ``invalid`` is empty for a batch
    whose elements are all mappings with unique, non-empty ids; otherwise it
    lists one diagnostic per problem and ``batch_key`` is None, so no partial
    plan is produced and no call is paired.
    """
    if isinstance(calls, (str, bytes)) or not isinstance(calls, Iterable):
        return (), [{"reason": INVALID_BATCH_NONE, "index": None, "id": None}], None
    items = list(calls)
    if not items:
        return (), [{"reason": INVALID_BATCH_EMPTY, "index": None, "id": None}], None
    invalid: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, call in enumerate(items):
        if not isinstance(call, Mapping):
            invalid.append({"reason": INVALID_BATCH_CALL, "index": index, "id": None})
            continue
        call_id = _entry_id(call)
        if call_id is None:
            invalid.append({"reason": INVALID_BATCH_MISSING_ID, "index": index, "id": None})
            continue
        if call_id in ids:
            invalid.append({"reason": INVALID_BATCH_DUPLICATE_ID, "index": index, "id": call_id})
        ids.append(call_id)
    if invalid:
        return tuple(items), invalid, None
    return tuple(items), [], _batch_key(ids)


def _execute(entry_id: str, call: Mapping[str, Any], fingerprint: str) -> dict[str, Any]:
    return {
        "action": "execute",
        "id": entry_id,
        "name": call.get("name"),
        "fingerprint": fingerprint,
        "call": _call_payload(call),
    }


def _reuse(
    entry_id: str, call: Mapping[str, Any], fingerprint: str, entry: Mapping[str, Any]
) -> dict[str, Any]:
    source = {
        "text": entry.get("text") or "",
        "tool_call_id": entry.get("tool_call_id"),
        "status": entry.get("status"),
    }
    return {
        "action": "reuse",
        "id": entry_id,
        "name": call.get("name"),
        "fingerprint": fingerprint,
        "call": _call_payload(call),
        # The current request's id pairs with the reused text: the id of the
        # message that produced the result belongs to the earlier round.
        "tool_message": _preserving_tool_message(entry_id, _reuse_text(entry)),
        "source_tool_call_id": entry.get("tool_call_id"),
        # Everything needed to answer again if the round is resumed before its
        # own result is recorded.
        "source": source,
    }


def _ledger_recorded(scope: Mapping[str, Any], batch: str | None) -> bool:
    """Whether this round carries the ``_dispatched`` ledger at all.

    Only the execution adapter writes it (``record_dispatch``). Its presence
    marks an adapter-owned round, where a saved execute decision with no result
    is resumed; a planning-only state keeps the older "replay or re-plan" rules.
    """
    planned = dict((scope.get("planned_rounds") or {}).get(batch) or {})
    return "_dispatched" in planned


def _block(entry_id: str, call: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "action": "block",
        "id": entry_id,
        "name": call.get("name"),
        "reason": reason,
        "call": _call_payload(call),
        "tool_message": _preserving_tool_message(entry_id, _BLOCK_TEXT[reason]),
    }


def _flatten(execute: list, reuse: list, block: list, messages: list) -> list[dict[str, Any]]:
    """The batch's messages in request order, for local (non-ToolNode) answers."""
    del execute
    by_id = {entry["id"]: entry for entry in block}
    by_id.update({entry["id"]: entry for entry in reuse})
    return [by_id[message["tool_call_id"]] for message in messages if message["tool_call_id"] in by_id]


def _invalid_plan(reason: str, invalid: Iterable[Mapping[str, Any]]) -> ToolPlan:
    return ToolPlan(
        round_key=None,
        execute=(),
        reuse=(),
        block=(),
        rounds=0,
        requested=0,
        executed=0,
        reused=0,
        blocked=0,
        invalid_reason=reason,
        invalid=tuple(dict(item) for item in invalid),
    )


def plan_tool_round(
    scope: Mapping[str, Any],
    calls: Iterable[Any],
    limits: ToolLimits | None = None,
    *,
    context: ToolContext | None = None,
    analyst: str | None = None,
    run_id: str | None = None,
    dispatched: bool = False,
) -> ToolPlan:
    """Split one batch of ``tool_calls`` into execute / reuse / block. Pure.

    The whole batch is decided up front against the *remaining* allowance, so a
    parallel executor can never overrun a cap because several calls were
    started before the first result came back.

    Two different situations both present as "the same batch again", and they
    are handled differently:

    * **A resumed round** -- ``dispatched=True``, or the batch is already on
      record *and* still has calls without a result. The saved plan is read
      (never re-planned): the calls still to run are returned as ``execute``
      (same `ids`, same fingerprints, nothing re-decided), the calls whose
      result is on record are not executed again, and a call whose arguments
      changed under the same id makes the batch invalid
      (``INVALID_BATCH_CHANGED``) rather than being silently treated as the
      same call. A call that was never handed to the node (no result, and no
      dispatch on record) is re-decided against the current record, so a
      retried unconfirmed result is not returned as if it were confirmed.
      ``rounds`` is 0: the round was already spent.
    * **A replay** -- every call of the batch already has a result. Nothing
      may be dispatched again, so ``execute`` is empty, ``mode="replay"`` and
      ``messages`` restates each recorded result.

    For a new batch the order of decision, per call, is:

    1. the call is not a usable request -> a diagnostic in ``invalid`` (no
       decision, no message, no cache lookup);
    2. the same call id appeared earlier in this batch -> ``duplicate_call_id``;
    3. a confirmed success is on record for the same fingerprint -> **reuse**;
       a reuse spends no execution allowance (the round still counts);
    4. the same fingerprint appeared earlier in this batch -> execute the first,
       ``duplicate_in_batch`` the rest (no result exists yet);
    5. a failed/absent/unconfirmed result is on record -> ``duplicate_failed``;
    6. the call would start beyond ``max_calls`` executed -> ``call_limit``;
    7. otherwise execute.

    ``context`` supplies the fingerprint inputs (instrument, date, vendor
    chains, schemas). Without it, ``analyst`` (default from ``scope``) and
    ``run_id`` (default from ``scope``) are used and the vendor chain/schema are
    resolved from the live configuration.
    """
    limits = (limits or ToolLimits()).effective()
    if context is None:
        context = ToolContext(
            analyst=analyst or scope.get("analyst") or "",
            run_id=run_id if run_id is not None else scope.get("run_id"),
        )
    elif run_id is not None and context.run_id is None:
        context = ToolContext(**{**context.__dict__, "run_id": run_id})

    items, batch_problems, batch = inspect_batch(calls)
    if batch is None:
        reason = batch_problems[0]["reason"] if batch_problems else INVALID_BATCH_NONE
        return _invalid_plan(reason, batch_problems)

    if dispatched:
        return _resume(scope, items, batch, limits, context, dispatched=True)
    ledger = _ledger_recorded(scope, batch)
    recorded = (scope.get("charged_rounds") or {}).get(batch)
    if ledger or recorded is not None:
        # The saved plan is read back. For the adapter's two-phase state (a
        # ledger is present) a round with no result yet is genuinely unfinished
        # -- the tool never ran or raised -- so running it is a resume; for a
        # planning-only state, a batch with nothing left to run is a replay.
        replay = _resume(scope, items, batch, limits, context, dispatched=False)
        if replay.mode == "replay" and not ledger:
            replay = _replay_plan(replay)
        return replay
    # A *new* batch: an unrelated outstanding call of an earlier batch never
    # invalidates it; that call is simply resumed when its own batch returns.

    cache = scope.get("cache") or {}
    attempts = scope.get("attempts") or {}
    rounds_closed = (
        bool(scope.get("closed"))
        or bool(scope.get("finished"))
        or (limits.max_rounds is not None and scope.get("rounds", 0) >= limits.max_rounds)
    )

    execute: list[dict[str, Any]] = []
    reuse: list[dict[str, Any]] = []
    block: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen: set[str] = set()
    executing = 0

    for call in items:
        call_id = _entry_id(call)
        if call_id is None:  # inspect_batch guarantees this cannot happen
            invalid.append({"reason": INVALID_CALL_MISSING_ID, "index": None, "id": None})
            continue
        if call_id in seen_ids:
            entry = _block(call_id, call, BLOCK_DUPLICATE_CALL_ID)
            block.append(entry)
            messages.append(entry["tool_message"])
            continue
        seen_ids.add(call_id)
        try:
            fingerprint = context.fingerprint(call)
        except MalformedCallError as exc:
            invalid.append(
                {"reason": exc.reason, "index": None, "id": call_id, "call": _call_payload(call)}
            )
            continue

        if rounds_closed:
            entry = _block(call_id, call, BLOCK_ROUND_LIMIT)
            block.append(entry)
            messages.append(entry["tool_message"])
            continue
        if fingerprint in cache:
            entry = _reuse(call_id, call, fingerprint, cache[fingerprint]["entry"])
            reuse.append(entry)
            messages.append(entry["tool_message"])
            continue
        if fingerprint in seen:
            entry = _block(call_id, call, BLOCK_DUPLICATE_IN_BATCH)
            block.append(entry)
            messages.append(entry["tool_message"])
            continue
        if fingerprint in attempts:
            entry = _block(call_id, call, BLOCK_DUPLICATE_FAILED)
            block.append(entry)
            messages.append(entry["tool_message"])
            continue
        if (
            limits.max_calls is not None
            and scope.get("executed", 0) + executing >= limits.max_calls
        ):
            entry = _block(call_id, call, BLOCK_CALL_LIMIT)
            block.append(entry)
            messages.append(entry["tool_message"])
            continue

        execute.append(_execute(call_id, call, fingerprint))
        seen.add(fingerprint)
        executing += 1

    if invalid:
        # A partially unusable batch is not executed: no half-paired plan.
        return _invalid_plan(invalid[0]["reason"], invalid)

    # Every round is chargeable, including one made only of reuses or blocks: a
    # model that repeats itself is still cycling.
    new_rounds = scope.get("rounds", 0) + 1
    new_executed = scope.get("executed", 0) + executing
    close_after = (
        limits.max_rounds is not None and new_rounds >= limits.max_rounds
    ) or (limits.max_calls is not None and new_executed >= limits.max_calls)
    return ToolPlan(
        round_key=batch,
        execute=tuple(execute),
        reuse=tuple(reuse),
        block=tuple(block),
        rounds=1,
        requested=len(execute) + len(reuse) + len(block),
        executed=len(execute),
        reused=len(reuse),
        blocked=len(block),
        close_after_execute=close_after,
        mode="new",
        messages=tuple(messages),
    )


def _replay_plan(plan: ToolPlan) -> ToolPlan:
    """A batch whose calls all have results restates them and executes none."""
    messages = plan.messages
    return ToolPlan(
        round_key=plan.round_key,
        execute=(),
        reuse=plan.reuse,
        block=plan.block,
        rounds=0,
        requested=plan.requested,
        executed=0,
        reused=plan.reused,
        blocked=plan.blocked,
        mode="replay",
        resumed=True,
        messages=messages,
    )


def _resume(
    scope: Mapping[str, Any],
    items: tuple[dict[str, Any], ...],
    batch: str,
    limits: ToolLimits,
    context: ToolContext,
    *,
    dispatched: bool,
) -> ToolPlan:
    """Read back the plan of a batch already on record (never re-decide it)."""
    saved = dict((scope.get("planned_rounds") or {}).get(batch) or {})
    # ``_dispatched`` is the round's dispatch ledger, not a decision.
    saved.pop("_dispatched", None)
    results = scope.get("results") or {}
    execute: list[dict[str, Any]] = []
    reuse: list[dict[str, Any]] = []
    block: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    for call in items:
        call_id = str(call.get("id"))
        decision = saved.get(call_id)
        if decision is None:
            # The batch key matched but this id is not part of the saved plan.
            invalid.append(
                {"reason": INVALID_BATCH_REPLAY_ONLY, "index": None, "id": call_id}
            )
            continue
        if _call_key(call) != decision["call_key"]:
            # Same id, different request: silently treating it as the same call
            # would execute something the model never asked for twice.
            invalid.append(
                {"reason": INVALID_BATCH_CHANGED, "index": None, "id": call_id,
                 "call": _call_payload(call)}
            )
            continue
        if decision["action"] == "block":
            entry = _block(call_id, call, decision["reason"])
            block.append(entry)
            messages.append(entry["tool_message"])
            continue
        if call_id in results:
            # This call already ran: restate *its own* recorded outcome. The
            # status travels with it (an error stays an error), no success is
            # claimed, and the tool is never called again.
            message = _replayed_message(call_id, results[call_id])
            reuse.append({
                "action": "replay",
                "id": call_id,
                "name": call.get("name"),
                "fingerprint": decision["fingerprint"],
                "call": _call_payload(call),
                "tool_message": message,
                "status": results[call_id].get("status"),
            })
            messages.append(message)
            continue
        if decision["action"] == "block":
            entry = _block(call_id, call, decision["reason"])
            block.append(entry)
            messages.append(entry["tool_message"])
            continue
        if call_id in results:
            # This call already ran: restate *its own* recorded outcome. The
            # status travels with it (an error stays an error), no success is
            # claimed, and the tool is never called again.
            message = _replayed_message(call_id, results[call_id])
            reuse.append({
                "action": "replay",
                "id": call_id,
                "name": call.get("name"),
                "fingerprint": decision["fingerprint"],
                "call": _call_payload(call),
                "tool_message": message,
                "status": results[call_id].get("status"),
            })
            messages.append(message)
            continue
        if scope.get("finished"):
            # The analyst is finished (report written): a call that never
            # produced a result cannot run now. Its round was already charged.
            entry = _block(call_id, call, BLOCK_ROUND_LIMIT)
            block.append(entry)
            messages.append(entry["tool_message"])
            continue
        if decision["action"] == "execute":
            # Saved to run, but no result is on record: the tool either never
            # started (the commit did not happen), raised / was cancelled, or
            # its result was lost. There is no reliable proof it produced the
            # requested data, so it is re-decided against what is known *now*
            # -- an unconfirmed result is not a confirmed one, and a request
            # that has since failed must not run again -- then run. The round
            # was already charged, so the rounds allowance is not re-tested,
            # and nothing is charged twice.
            cache = scope.get("cache") or {}
            attempts = scope.get("attempts") or {}
            try:
                fingerprint = context.fingerprint(call)
            except MalformedCallError as exc:
                return _invalid_plan(
                    exc.reason,
                    ({"reason": exc.reason, "index": None, "id": call_id},),
                )
            if fingerprint in cache:
                entry = _reuse(call_id, call, fingerprint, cache[fingerprint]["entry"])
                reuse.append(entry)
                messages.append(entry["tool_message"])
                continue
            if fingerprint in attempts:
                entry = _block(call_id, call, BLOCK_DUPLICATE_FAILED)
                block.append(entry)
                messages.append(entry["tool_message"])
                continue
            if (
                limits.max_calls is not None
                and scope.get("executed", 0)
                - sum(1 for e in saved.values() if e.get("action") == "execute")
                >= limits.max_calls
            ):
                entry = _block(call_id, call, BLOCK_CALL_LIMIT)
                block.append(entry)
                messages.append(entry["tool_message"])
                continue
            execute.append(_execute(call_id, call, decision["fingerprint"]))
            continue
        if decision["action"] == "reuse":
            # A new request answered by an earlier confirmed success. The saved
            # source holds the real text, so the resume answers with it even
            # though this round's own result was never recorded.
            entry = _reuse(call_id, call, decision["fingerprint"],
                           decision.get("source") or {})
            reuse.append(entry)
            messages.append(entry["tool_message"])
            continue
        execute.append(_execute(call_id, call, decision["fingerprint"]))

    if invalid:
        return _invalid_plan(invalid[0]["reason"], invalid)

    mode = "resume" if execute else "replay"
    blocked = len(block)
    return ToolPlan(
        round_key=None,
        execute=tuple(execute),
        reuse=tuple(reuse),
        block=tuple(block),
        rounds=0,
        requested=len(execute) + len(reuse) + len(block),
        executed=len(execute),
        reused=len(reuse),
        blocked=blocked,
        mode=mode,
        resumed=True,
        messages=tuple(messages),
    )


_BLOCK_TEXT = {
    BLOCK_ROUND_LIMIT: (
        "TOOL_GOVERNANCE_BLOCKED: this analyst has used its allowance of tool "
        "rounds; the tool was not run. Write the report from the evidence already "
        "collected and state explicitly what could not be verified."
    ),
    BLOCK_CALL_LIMIT: (
        "TOOL_GOVERNANCE_BLOCKED: this analyst has used its allowance of tool "
        "calls; the tool was not run. Use the evidence already collected."
    ),
    BLOCK_DUPLICATE_IN_BATCH: (
        "TOOL_GOVERNANCE_BLOCKED: an identical request is executed earlier in "
        "this same batch; its result will answer that call. The tool was not run twice."
    ),
    BLOCK_DUPLICATE_FAILED: (
        "TOOL_GOVERNANCE_BLOCKED: an identical request already failed or returned "
        "no usable data in this analyst's run; it was not repeated. Do not assume "
        "its result exists, and do not estimate values."
    ),
    BLOCK_DUPLICATE_CALL_ID: (
        "TOOL_GOVERNANCE_BLOCKED: this batch uses a tool_call id that an earlier "
        "call in the same batch already used; results could not be paired. The "
        "tool was not run for this entry."
    ),
}


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def _decision_record(entry: Mapping[str, Any]) -> dict[str, Any]:
    """What must be replayed for one decided call, saved with the round.

    A reuse decision carries the *entry it was served from* (text and the id of
    the call that produced it), so a resume before the round's own result is
    recorded can still answer with the real content instead of re-running the
    tool or answering with nothing.
    """
    record = {
        "action": entry["action"],
        "fingerprint": entry.get("fingerprint"),
        "reason": entry.get("reason"),
        "call_key": _call_key(entry["call"]),
    }
    if entry["action"] == "reuse":
        record["source"] = dict(entry.get("source") or {})
    return record


def record_round_start(
    scope: Mapping[str, Any],
    plan: ToolPlan,
    limits: ToolLimits | None = None,
) -> dict[str, Any]:
    """Spend the round (and the execution allowance) of a new plan.

    Returns a **new** record; a plan that has nothing left to charge (a resume,
    a replay, an invalid batch, or the same plan recorded twice) returns
    ``scope`` itself unchanged, so recording is idempotent.

    * ``rounds``   += 1 once per new batch (reuse-only or all-blocked too);
    * ``requested``+= the calls the rules decided;
    * ``executed`` += the calls that will actually run, ``reused``/``blocked``
      as decided.

    The plan and the charge marker are written in the same update, so a later
    dispatch of the same batch is recognised as a resume, not a new round.
    """
    limits = (limits or ToolLimits()).effective()
    if plan.must_abort or not plan.rounds or plan.round_key is None:
        return scope
    charged = scope.get("charged_rounds") or {}
    if plan.round_key in charged:
        return scope

    new = dict(scope)
    planned = dict(new.get("planned_rounds") or {})
    decisions = {
        entry["id"]: _decision_record(entry) for entry in (*plan.execute, *plan.reuse, *plan.block)
    }
    # The dispatch ledger starts empty: a call is written there only once the
    # node was actually handed it (``record_dispatch``).
    decisions["_dispatched"] = []
    planned[plan.round_key] = decisions
    new["planned_rounds"] = planned
    new["charged_rounds"] = {**charged, plan.round_key: plan.rounds}
    new["rounds"] = new.get("rounds", 0) + plan.rounds
    new["requested"] = new.get("requested", 0) + plan.requested
    new["executed"] = new.get("executed", 0) + plan.executed
    new["reused"] = new.get("reused", 0) + plan.reused
    new["blocked"] = new.get("blocked", 0) + plan.blocked

    if round_limit_reached(new, limits):
        new["closed"] = True
    return new


def record_dispatch(
    scope: Mapping[str, Any], batch: str | None, call_ids: Iterable[str]
) -> dict[str, Any]:
    """Remember that ``call_ids`` of ``batch`` were handed to the node.

    Written by the execution adapter *after* the node returned; it answers "can
    this unfinished call run again?", which ``results`` alone cannot: a result
    is recorded for every call the node answered, but not for one whose tool
    raised. Idempotent, and a no-op for an unknown batch.
    """
    planned = dict(scope.get("planned_rounds") or {})
    decisions = planned.get(batch)
    if decisions is None:
        return scope
    ledger = list(decisions.get("_dispatched") or ())
    added = [str(call_id) for call_id in call_ids if str(call_id) not in ledger]
    if not added:
        return scope
    new = dict(scope)
    planned[batch] = {**decisions, "_dispatched": ledger + added}
    new["planned_rounds"] = planned
    return new


def record_malformed(scope: Mapping[str, Any], count: int = 1) -> dict[str, Any]:
    """Count calls that were not a usable request (see the module docstring).

    They are blocked, but not requested: ``requested`` counts only calls the
    rules decided. A malformed batch has no usable call at all.
    """
    if count <= 0:
        return scope
    new = dict(scope)
    new["malformed"] = new.get("malformed", 0) + count
    new["blocked"] = new.get("blocked", 0) + count
    return new


def record_tool_result(
    scope: Mapping[str, Any],
    *,
    tool_call_id: str | None,
    tool_name: str | None = None,
    fingerprint: str | None = None,
    result: Any = None,
    raised: bool = False,
    cacheable_success: bool | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Record one finished (or never-started) call. Returns a **new** record.

    * the outcome comes from :func:`classify_tool_result`; with ``raised=False``
      and ``result=None`` an allowed call that produced nothing is
      ``REFUSED_TIMEOUT``;
    * ``CACHEABLE_SUCCESS`` is stored for reuse -- and only when the tool is in
      :data:`REUSABLE_CATEGORIES` and not :data:`NON_REUSABLE_TOOLS`. Any other
      outcome is counted and remembered in ``attempts`` as a repeat not worth
      serving, and is never cached as a success;
    * the recorded result is also kept under ``results[tool_call_id]`` (plain
      text), so a resumed or replayed round can pair its own message without
      running the tool again;
    * this layer never retries and never touches vendor state;
    * idempotent per ``tool_call_id``: recording the same call again returns the
      record unchanged (the same object when nothing changed).

    ``cacheable_success`` is the caller's explicit confirmation that the tool
    returned data. ``None`` is *not* a confirmation: a text that merely avoids
    the two absence markers stays ``UNKNOWN``. ``raised=True``, a ``FunctionMessage``
    or ``status="error"`` on a ``ToolMessage`` is never a confirmation.
    """
    if tool_call_id is None:
        raise ValueError("a result must belong to a tool_call_id")
    if tool_call_id in (scope.get("results") or {}):
        return scope

    if raised or getattr(result, "status", None) == "error":
        status = ERROR
    elif result is None:
        status = REFUSED_TIMEOUT
    else:
        status = classify_tool_result(
            result, raised=False, cacheable_success=cacheable_success
        )
    detail = reason
    text = "" if result is None else _content_text(result)

    if status == CACHEABLE_SUCCESS and not is_reusable_read_only_tool(tool_name or ""):
        # Confirmed data, but from a tool whose output must not be served twice
        # (live feeds, undated sources): keep it for this call only. The call
        # itself was a success, so it is not a repeat to avoid.
        status = NON_REUSABLE_SUCCESS
        detail = f"{tool_name} is not a reusable read-only snapshot tool"

    new = dict(scope)
    results = dict(new.get("results") or {})
    outcomes = dict(new.get("outcomes") or {})
    outcomes[status] = outcomes.get(status, 0) + 1
    results[tool_call_id] = {"status": status, "fingerprint": fingerprint, "text": text}
    new["results"] = results
    new["outcomes"] = outcomes

    if status == CACHEABLE_SUCCESS:
        entry = {
            "text": text,
            "tool_call_id": tool_call_id,
            "template": getattr(result, "name", None),
            "status": status,
        }
        cache = dict(new.get("cache") or {})
        cache[fingerprint] = {**entry, "entry": entry}
        new["cache"] = cache
        # A success supersedes an earlier failure of the same request.
        attempts = dict(new.get("attempts") or {})
        attempts.pop(fingerprint, None)
        new["attempts"] = attempts
    elif status not in (NON_REUSABLE_SUCCESS,):
        # A genuine non-success: a repeat is not expected to do better. A
        # ``NON_REUSABLE_SUCCESS`` *did* return data, it is merely not served
        # again from the cache, so it must not be remembered as a failure
        # (that would tell the model the data does not exist).
        if fingerprint is not None:
            attempts = dict(new.get("attempts") or {})
            attempts.setdefault(
                fingerprint,
                {"status": status, "tool_call_id": tool_call_id, "reason": detail},
            )
            new["attempts"] = attempts
        new["last_incomplete"] = {"status": status, "tool_call_id": tool_call_id, "reason": detail}
    return new


def _content_text(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return content if isinstance(content, str) else str(content)


def mark_finished(scope: Mapping[str, Any]) -> dict[str, Any]:
    """Mark the analyst's report as written: tools stay closed for good."""
    new = dict(scope)
    new["finished"] = True
    new["closed"] = True
    return new


# ---------------------------------------------------------------------------
# Executing a planned round
# ---------------------------------------------------------------------------
#
# This is the only place in this module that runs anything. It is deliberately
# separate from planning and is **not** wired into the production graph.
#
# What the installed ``ToolNode`` actually does (checked against
# langgraph-prebuilt 1.1.1 / langgraph 1.2.19, not assumed):
#
# * it accepts a list of ``ToolCall`` dicts (``type == "tool_call"``). For that
#   input shape it reads the graph state from the channels *when it runs inside
#   a graph*, and only uses a state key that is actually present -- that is how
#   ``InjectedState("trade_date")`` is filled. Outside a graph there is no
#   channel to read, so ``tool.invoke`` fails with a missing-config
#   ``ValueError``; the node must be hosted in a graph for injection to work
#   (see :func:`run_tool_node_in_graph`);
# * with a ``list`` of calls it returns ``{"messages": [...]}``, one message per
#   call (checked with the installed package, not assumed);
# * ``handle_tool_errors`` decides what becomes a message: the default handler
#   turns argument ``ToolInvocationError``/``ValidationError`` into
#   ``ToolMessage(status="error")`` and **re-raises** everything else (auth,
#   config, internal bugs);
# * ``GraphBubbleUp`` (interrupts, cancellation, ``GraphInterrupt``) is always
#   re-raised, whatever the handler;
# * a tool call whose name is not registered comes back as an error message,
#   never as an exception.
#
# None of that is changed here: the adapter only chooses *which* calls to hand
# over, and never swallows what the node raises.
#
# Two phases, so a caller always holds the record of a round that started:
#
#     prepared = executor.prepare(governance, calls, state=run_state, config=config)
#     store(prepared.state)          # may fail: nothing ran yet
#     execution = executor.execute(prepared)   # == commit(prepared): tools run
#     store(execution.state)         # the observed results
#
# ``prepare`` is the only way in, because the registered round (charged, plan
# saved, still pending) only exists as the ``PreparedRound`` it returns. A
# caller that never got one back -- ``prepare`` raised, or the caller lost the
# object (it is not stored itself; only ``prepared.state`` is) -- has no round
# to resume: registering the batch again is a *new* round by construction.
#
# Tool arguments the model never supplies (``InjectedState``, e.g. the run
# date) are not governance data and are never put in ``ToolContext``: it is a
# fingerprint input only. They come from the real run, handed in explicitly as
# ``state=``/``config=`` on ``prepare`` and ``commit``; a missing one is
# refused before any tool starts instead of being executed with a blank value.
#
# This layer is not durable: there is no checkpointing here, and no claim of
# exactly-once execution across a process crash.

_TOOL_NODE_CLASS: Any = None


class _NodeHostState(TypedDict, total=False):
    """State of the minimal graph that hosts a ``ToolNode`` (default runner).

    A real ``ToolNode`` is a graph node and expects ``messages`` -- it takes
    the calls from the last ``AIMessage`` and reads state through the graph's
    channels -- so the host declares ``messages`` and the run's ``trade_date``
    (the one run value a tool may be injected with). It is **not** the run's
    state: nothing else of the state exists here, and it keeps nothing of the
    run context. ``result`` holds the node's own answer.
    """

    result: Any
    messages: list
    trade_date: str


class _AnalystHostState(AgentState, total=False):
    """State of the host graph for an analyst runner (market, fundamentals).

    Every field of ``AgentState`` (so a tool may read any field the run carries,
    not only ``trade_date``), except ``messages``: that one is redeclared as a
    plain list, so the ``ToolNode``'s own output *replaces* the calls it was
    given instead of being appended to them. ``result`` carries the node's
    answer out. (The run's real graph keeps ``add_messages``; this host is only
    the place an analyst's ``ToolNode`` runs for one round.)
    """

    messages: list
    result: Any


# Kept for the original market runner's name; both names are the same class.
_MarketHostState = _AnalystHostState


def run_tool_node_in_graph(
    node: Any,
    calls: list[dict[str, Any]],
    *,
    state: Mapping[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Run ``node`` inside a minimal graph built from ``state`` and ``config``.

    This is the default *runner* -- the protocol is
    ``runner(node, calls, *, state=None, config=None) -> output``.
    ``state`` is the real run state the node's tools may read, and ``config``
    the real run config (thread, store, context), passed through unchanged.

    The node runs as a real graph node, which is how it gets graph state
    (``InjectedState``) and its runtime. A tool sees a value from ``state`` only
    through a channel the host declares (the run's ``trade_date``); everything
    else of the state does not exist here, so a tool never sees a value the run
    did not carry.

    This is a test/small-adapter host, not the run's graph: no checkpointer, no
    run semantics of its own, no other state. Required inputs are checked by the
    executor *before* it gets here.
    """
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph

    # The node runs as the graph's node, exactly as in production, so it gets
    # graph state (``InjectedState``) and the host runtime from langgraph.
    ai_message = AIMessage(content="", tool_calls=[dict(call) for call in calls])

    def finish(graph_state: Mapping[str, Any]) -> dict[str, Any]:
        return {"result": {"messages": graph_state["messages"]}}

    initial: dict[str, Any] = dict(state or {})
    initial["messages"] = [ai_message]
    graph = StateGraph(_NodeHostState)
    graph.add_node("tools", node)
    graph.add_node("finish", finish)
    graph.add_edge(START, "tools")
    graph.add_edge("tools", "finish")
    graph.add_edge("finish", END)
    kwargs: dict[str, Any] = {"config": config} if config is not None else {}
    return graph.compile().invoke(initial, **kwargs)["result"]


def run_market_tool_node(
    node: Any,
    calls: list[dict[str, Any]],
    *,
    state: Mapping[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Run the market ``ToolNode`` in a graph carrying the **real run state**.

    Same runner protocol as :func:`run_tool_node_in_graph`, but the host graph
    declares the whole :class:`AgentState`, not a three-channel subset: the
    market node is already a node of the run graph, so its tools may see any
    state field the run carries (not only ``trade_date``). Nothing else is
    changed -- the run's messages are replaced by this round's calls, and the
    node's own ``messages`` output is returned.

    The executor checks required injected fields against the run state before
    anything is dispatched, so a missing one is refused there, not here.
    """
    return run_analyst_tool_node(node, calls, state=state, config=config)


def run_analyst_tool_node(
    node: Any,
    calls: list[dict[str, Any]],
    *,
    state: Mapping[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Run an analyst's ``ToolNode`` in a graph carrying the **real run state**.

    The shared implementation behind :func:`run_market_tool_node` and the
    fundamentals runner: exactly the same protocol and host graph, so an
    analyst's own ``ToolNode`` sees the same run state whichever analyst
    dispatches through it.
    """
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph

    # The node runs as the graph's node, so it gets graph state
    # (``InjectedState``) and the runtime from langgraph. ``_AnalystHostState``
    # replaces ``messages`` with the tool results, so ``finish`` sees exactly
    # one message per call.
    ai_message = AIMessage(content="", tool_calls=[dict(call) for call in calls])

    def finish(graph_state: Mapping[str, Any]) -> dict[str, Any]:
        return {"result": {"messages": graph_state["messages"]}}

    initial: dict[str, Any] = dict(state or {})
    initial["messages"] = [ai_message]
    graph = StateGraph(_AnalystHostState)
    graph.add_node("tools", node)
    graph.add_node("finish", finish)
    graph.add_edge(START, "tools")
    graph.add_edge("tools", "finish")
    graph.add_edge("finish", END)
    kwargs: dict[str, Any] = {"config": config} if config is not None else {}
    return graph.compile().invoke(initial, **kwargs)["result"]


def _tool_node_class() -> Any:
    """``ToolNode``, imported lazily (planning must work without the graph stack)."""
    global _TOOL_NODE_CLASS
    if _TOOL_NODE_CLASS is None:
        from langgraph.prebuilt import ToolNode

        _TOOL_NODE_CLASS = ToolNode
    return _TOOL_NODE_CLASS


def _accepts_state_or_config(target: Any) -> bool:
    """Whether ``target`` can be handed ``state=``/``config=``.

    ``target`` is a callable, or an object whose ``invoke`` is used. It must
    name both parameters (keyword-only or not) or take ``**kwargs``. Checked
    rather than assumed: a runner or node that cannot receive them must not be
    run silently as if it had (an ``InjectedState`` value would never arrive).
    """
    if not callable(target):
        target = getattr(target, "invoke", None)
        if target is None:
            return False
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return False
    parameters = signature.parameters.values()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters):
        return True
    named = {
        p.name
        for p in parameters
        if p.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    }
    return {"state", "config"} <= named


def _requires_state(tool: Any) -> frozenset[str]:
    """The state fields ``tool`` *requires* (a required, declared ``InjectedState``).

    Read from the tool's own function signature. A defaulted injection (like
    the graph-state accessor itself) is not a requirement: the framework
    omits it when the state does not carry it, exactly as in the real graph.
    """
    from langgraph.prebuilt import InjectedState

    function = getattr(tool, "func", None)
    if function is None:
        return frozenset()
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):  # pragma: no cover
        return frozenset()
    required: set[str] = set()
    try:
        hints = get_annotations(function, eval_str=True)
    except (NameError, TypeError):  # pragma: no cover - unresolvable annotation
        hints = getattr(function, "__annotations__", {})
    for name, annotation in hints.items():
        if not _is_required_parameter(signature, name):
            continue
        for metadata in getattr(annotation, "__metadata__", ()):
            if isinstance(metadata, InjectedState) and metadata.field:
                required.add(metadata.field)
    return frozenset(required)


def _is_required_parameter(signature: inspect.Signature, name: str) -> bool:
    """Whether ``name`` has neither a default nor a ``*args``-like kind."""
    parameter = signature.parameters.get(name)
    if parameter is None:  # pragma: no cover
        return False
    if parameter.kind in (
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    ):
        return False
    return parameter.default is inspect.Parameter.empty


class GovernanceBatchError(RuntimeError):
    """The batch cannot be executed: no call was dispatched.

    Raised *before* anything runs, for an unusable batch (see
    ``ToolPlan.must_abort``), a call the analyst is not allowed to make, or a
    registration that the caller could not keep. No tool was started.
    """


class GovernanceResultError(RuntimeError):
    """The batch ran but did not account for every call.

    This is a bug signal, not a data problem: a normally completed batch must
    produce exactly one message per call. It is never turned into a model
    message.
    """


class GovernanceStateError(RuntimeError):
    """The run cannot supply what a call needs: no tool was started.

    The real run state/config is handed in explicitly, never taken from
    :class:`ToolContext` (a fingerprint input only). A required
    ``InjectedState`` field -- the run date, today -- that the run does not
    carry, or a runner/node that cannot be handed the run state and config,
    is refused before dispatch rather than executed with a blank value.
    """


@dataclass(frozen=True)
class PreparedRound:
    """A round registered *before* any tool runs. Holds no tool instance.

    ``state`` is the governance state that already contains this round
    (charged, plan saved), so a caller can store it before dispatching. The
    field is a single-key mapping ``{"tool_governance": {...}}``. ``batch`` is
    the batch exactly as the model issued it, kept so the messages can be
    returned in request order.

    ``analyst`` names whose record this round belongs to. ``run_state`` and
    ``config`` are the real run state and run config the tools may read,
    carried from ``prepare`` to ``execute``; they are not governance data and
    are never stored in ``state``.
    """

    state: dict[str, Any]
    plan: ToolPlan
    batch: tuple[dict[str, Any], ...]
    analyst: str
    run_state: dict[str, Any]
    config: dict[str, Any] | None

    @property
    def pending(self) -> tuple[str, ...]:
        """The call ids that still have to run (empty for a replay)."""
        return self.plan.executed_call_ids


@dataclass(frozen=True)
class ToolExecution:
    """The outcome of :meth:`ToolExecutor.execute` / :meth:`commit`.

    ``state`` is the governance state to store back (same shape as
    ``PreparedRound.state``); ``scope`` is the analyst's record inside it.
    ``messages`` holds one plain message dict per call, in request order.
    ``dispatched`` lists the ids actually handed to the ``ToolNode`` -- never a
    reuse, a replay or a block.
    """

    state: dict[str, Any]
    plan: ToolPlan
    messages: tuple[dict[str, Any], ...]
    dispatched: tuple[str, ...]
    analyst: str

    @property
    def scope(self) -> dict[str, Any]:
        """The ``analyst``'s record (``state["tool_governance"]["analysts"][analyst]``).

        An empty record when this analyst has none: never another analyst's
        record, whichever order the records were written in.
        """
        analysts = (self.state.get(GOVERNANCE_STATE_KEY) or {}).get("analysts") or {}
        record = analysts.get(self.analyst)
        return dict(record) if isinstance(record, Mapping) else {}

    @property
    def executed_count(self) -> int:
        """How many calls really ran (not how many were permitted)."""
        return len(self.dispatched)


GOVERNANCE_STATE_KEY = "tool_governance"

# The only statuses a real ``ToolMessage`` accepts. Governance outcomes
# (``missing_data``/``degraded``/``unknown``/...) live in the record only and
# never reach a message.
_MESSAGE_STATUSES = frozenset({None, "success", "error"})


def _bound_tool_names(tools: Iterable[Any]) -> frozenset[str]:
    """The names of the tools an analyst is bound to (``name`` or ``__name__``)."""
    names: set[str] = set()
    for tool in tools:
        for attribute in ("name", "__name__"):
            value = getattr(tool, attribute, None)
            if isinstance(value, str) and value:
                names.add(value)
                break
    return frozenset(names)


class ToolExecutor:
    """Runs one planned round against one analyst's own ``ToolNode``.

    Permission is defined by the tools the analyst is *bound to* -- the same
    objects passed to ``tools``, which is the analyst's own ``tools`` list --
    not by the governance schema registry. A tool the module knows about but
    this analyst cannot call makes the batch fail before anything runs
    (``GovernanceBatchError``); it is never handed to the node.

    ``node`` is the ``ToolNode`` that executes these calls; when it is omitted
    a real ``ToolNode(list(tools))`` is built on first dispatch. ``runner`` is
    how the node is invoked, called as
    ``runner(node, calls, *, state=run_state, config=config)``; it defaults to
    :func:`run_tool_node_in_graph`. A node that already runs inside the run
    graph can be passed its own runner; the run's state and config (handed to
    :meth:`prepare`) are what answer ``InjectedState`` either way.

    The run state and config are *not* taken from :class:`ToolContext`: the
    context is a fingerprint input only. They are passed to :meth:`prepare` and
    carried to :meth:`execute`; when a call needs a state field the run does
    not carry, nothing is dispatched (:class:`GovernanceStateError`).

    ``confirms_success`` is the **only** source of a success claim. It is called
    as ``confirms_success(call, message)`` with the call dict and the observed
    message dict, and must return ``True`` only when it has positive evidence
    that the call returned valid data. Without a confirmer no result is cached;
    absence/degradation/error results are never cached whatever it says.
    """

    def __init__(
        self,
        tools: Iterable[Any],
        *,
        node: Any = None,
        analyst: str,
        run_id: str | None = None,
        limits: ToolLimits | None = None,
        context: ToolContext | None = None,
        runner: Any = None,
        confirms_success: Any = None,
    ) -> None:
        if not isinstance(analyst, str) or not analyst:
            # The record is keyed by this name: an implicit one would read
            # whichever analyst happens to be in the state.
            raise ValueError("ToolExecutor needs an explicit analyst name")
        self._tools = tuple(tools)
        self._permitted = _bound_tool_names(self._tools)
        self._node = node
        self._runner = runner or run_tool_node_in_graph
        self._confirms_success = confirms_success
        if context is None:
            context = ToolContext(analyst=analyst, run_id=run_id)
        if analyst != context.analyst:
            raise ValueError(
                f"analyst {analyst!r} does not match the context "
                f"({context.analyst!r}); the record and the fingerprint "
                "would name different analysts"
            )
        if run_id is not None and context.run_id is None:
            context = ToolContext(**{**context.__dict__, "run_id": run_id})
        self.context = context
        # The plan resolves the analyst and the run id exactly this way, so the
        # same values are used for every lookup and every update.
        self.analyst = analyst
        self.run_id = context.run_id
        self.limits = limits or ToolLimits()

    # -- public API ---------------------------------------------------------

    def prepare(
        self,
        state: Mapping[str, Any] | None,
        calls: Iterable[Any],
        *,
        dispatched: bool = False,
        run_state: Mapping[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> PreparedRound:
        """Plan and register one round. **No tool runs.**

        ``state`` is the ``tool_governance`` value (``{"version", "run_id",
        "analysts"}``) from the graph state, or ``None``. The returned
        ``PreparedRound.state`` is the same value with this round charged and
        its plan saved; storing it is the caller's job and may fail -- if it
        does, nothing has run and the exception propagates.

        ``run_state`` is the **real run state** (the graph's, e.g. with
        ``trade_date``) and ``config`` the real run config. They are carried to
        :meth:`execute` and handed to the runner; they are not governance data.
        A call that needs a state field the run does not carry (a required
        ``InjectedState``, such as the run date) or a runner/node that cannot
        receive them makes the batch fail here, before anything runs.

        An unusable batch -- including a call the analyst is not bound to --
        raises :class:`GovernanceBatchError` and returns nothing.
        """
        items = tuple(calls)
        run_state = dict(run_state or {})
        plan = plan_tool_round(
            get_scope(state, self.analyst, self.run_id),
            items,
            self.limits,
            context=self.context,
            analyst=self.analyst,
            run_id=self.run_id,
            dispatched=dispatched,
        )
        if plan.must_abort:
            raise GovernanceBatchError(
                f"batch rejected before execution: {plan.invalid_reason}"
            )
        self._require_permitted(plan)
        self._require_run_inputs(plan, run_state, config)
        # One message per call, in the model's request order. The plan groups
        # decisions by action (on a resume a replay can come before a call that
        # still has to run), so the order comes from the caller's batch.
        order = [_entry_id(call) for call in items]
        self._check_one_message_per_call(plan, order)
        # Charging is idempotent: a resume/replay plan has nothing left to
        # charge, so registering it again spends no round.
        scope = record_round_start(self._scope_of(state), plan, self.limits)
        scope = record_dispatch(scope, plan.round_key, plan.executed_call_ids)
        return PreparedRound(
            state={GOVERNANCE_STATE_KEY: with_scope(state, self.analyst, scope, self.run_id)},
            plan=plan,
            batch=tuple(dict(call) for call in items),
            analyst=self.analyst,
            run_state=run_state,
            config=dict(config) if config is not None else None,
        )

    def execute(
        self,
        prepared: PreparedRound,
        *,
        run_state: Mapping[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ToolExecution:
        """Dispatch :meth:`prepare`'s round (the same thing as :meth:`commit`).

        Only a ``PreparedRound`` can be executed: it is the only handle to the
        registered round. Re-registering a batch instead would be a new round
        (charged again), and nothing here would know what ran; if the prepared
        round was lost, that is what the caller gets.

        ``run_state``/``config`` replace what the round was prepared with;
        omitting them reuses the prepared ones.

        Tool exceptions propagate unchanged. The registered round is still
        ``prepared`` -- the same object, still pending -- so the caller that
        holds it can prepare the batch again against ``prepared.state``: that
        is a resume of the same round, never a second charge.
        """
        if not isinstance(prepared, PreparedRound):
            raise TypeError(
                "execute() takes the PreparedRound returned by prepare(); a "
                "governance state or a batch cannot be executed, and a round "
                "that was lost is not resumed by charging a new one"
            )
        if prepared.analyst != self.analyst:
            raise ValueError(
                f"the prepared round belongs to {prepared.analyst!r}, not "
                f"{self.analyst!r}"
            )
        return self.commit(prepared, run_state=run_state, config=config)

    def commit(
        self,
        prepared: PreparedRound,
        *,
        run_state: Mapping[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ToolExecution:
        """Dispatch a prepared round and record what came back.

        Only the calls the plan marked ``execute`` reach the node; ``reuse``,
        ``replay`` and ``block`` are answered from the plan's already-paired
        messages. Exceptions from the node propagate unchanged (auth,
        configuration, internal errors; interrupts and cancellation are never
        swallowed). ``prepared`` stays a valid pending registration, so
        preparing the same batch against ``prepared.state`` is a resume: no
        round is charged twice and no call receives a result that was never
        observed. ``run_state``/``config`` replace the prepared ones when
        given (omitting them reuses what :meth:`prepare` was given).
        """
        plan = prepared.plan
        state = _governance_of(prepared.state)
        by_id = {
            _entry_id(entry["call"]): entry
            for entry in (*plan.execute, *plan.reuse, *plan.block)
        }
        order = [_entry_id(call) for call in prepared.batch]
        effective_state = (
            dict(prepared.run_state) if run_state is None else dict(run_state)
        )
        effective_config = prepared.config if config is None else config
        # Nothing runs if the run cannot supply what the calls need.
        self._require_run_inputs(plan, effective_state, effective_config)

        outputs = self._dispatch(
            list(plan.executed_calls), effective_state, effective_config
        )
        ran = self._index_outputs(outputs)
        missing = [call_id for call_id in plan.executed_call_ids if call_id not in ran]
        if missing:
            raise GovernanceResultError(
                "the batch completed but these calls have no result: "
                + ", ".join(missing)
            )

        scope = dict(get_scope(state, self.analyst, self.run_id))
        messages: list[dict[str, Any]] = []
        dispatched_ids: list[str] = []
        for call_id in order:
            entry = by_id[call_id]
            message = ran.pop(call_id, None) if entry["action"] == "execute" else None
            if message is None:
                messages.append(dict(entry["tool_message"]))
                continue
            payload = _message_dict(message)
            messages.append(payload)
            dispatched_ids.append(call_id)
            scope = record_tool_result(
                scope,
                tool_call_id=call_id,
                tool_name=entry.get("name"),
                fingerprint=entry.get("fingerprint"),
                result=payload.get("content"),
                raised=(payload.get("status") == "error"),
                # ``None`` means "not confirmed": the confirmer is the only
                # source of a success claim, so without one nothing is cached.
                cacheable_success=self._confirms(entry, payload),
            )
        if ran:
            raise GovernanceResultError(
                "the ToolNode returned results for calls outside the plan: "
                + ", ".join(sorted(ran))
            )
        scope = record_dispatch(scope, plan.round_key, dispatched_ids)
        return ToolExecution(
            state={GOVERNANCE_STATE_KEY: with_scope(state, self.analyst, scope, self.run_id)},
            plan=plan,
            messages=tuple(messages),
            dispatched=tuple(dispatched_ids),
            analyst=prepared.analyst,
        )

    # -- internals ----------------------------------------------------------

    def _scope_of(self, state: Mapping[str, Any] | None) -> dict[str, Any]:
        return dict(get_scope(state, self.analyst, self.run_id))

    def _require_run_inputs(
        self,
        plan: ToolPlan,
        run_state: Mapping[str, Any],
        config: Mapping[str, Any] | None,
    ) -> None:
        """Refuse a batch whose run cannot supply what its tools need.

        A required ``InjectedState`` field the run does not carry would make
        the framework omit it (or fail deep inside), so the tool would run with
        a blank value: refused here, before anything runs. So is a runner/node
        that cannot be handed the run state and config at all -- both are
        reported as one :class:`GovernanceStateError`.
        """
        problems: list[str] = []
        if plan.executed_calls:
            # Only a dispatch needs the protocol; a pure replay/reuse round
            # never reaches the runner or the node.
            if not _accepts_state_or_config(self._runner):
                problems.append("the runner cannot receive state and config")
            if not _accepts_state_or_config(self._node_or_build().invoke):
                problems.append("the node cannot receive state and config")
        for call in plan.executed_calls:
            tool = self._tool_named(call.get("name"))
            if tool is None:  # the node answers an unknown name with an error
                continue
            for field in sorted(_requires_state(tool)):
                value = run_state.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    problems.append(
                        f"{call.get('name')} needs run state {field!r}, which the "
                        "run does not carry"
                    )
        if problems:
            raise GovernanceStateError(
                "nothing was dispatched; " + "; ".join(dict.fromkeys(problems))
            )

    def _tool_named(self, name: Any) -> Any:
        for tool in self._tools:
            if name in (getattr(tool, "name", None), getattr(tool, "__name__", None)):
                return tool
        return None

    def _require_permitted(self, plan: ToolPlan) -> None:
        denied = sorted(
            {
                str(entry.get("name"))
                for entry in plan.execute
                if entry.get("name") not in self._permitted
            }
        )
        if denied:
            raise GovernanceBatchError(
                f"tool(s) {', '.join(denied)} are not bound to the "
                f"{self.analyst!r} analyst; the batch was not executed"
            )

    def _confirms(self, entry: Mapping[str, Any], payload: Mapping[str, Any]) -> bool | None:
        if self._confirms_success is None:
            return None
        verdict = self._confirms_success(dict(entry["call"]), dict(payload))
        return True if verdict is True else None

    @staticmethod
    def _check_one_message_per_call(plan: ToolPlan, order: list[str]) -> None:
        """Every call the node will not run must already have its own message."""
        planned = [
            entry["tool_message"].get("tool_call_id")
            for entry in (*plan.reuse, *plan.block)
        ]
        expected = set(order) - set(plan.executed_call_ids)
        if len(planned) != len(expected) or set(planned) != expected:
            raise GovernanceResultError(
                "the plan does not pair one message with every call it will not run"
            )

    def _node_or_build(self) -> Any:
        if self._node is None:
            # The real factory: a ``ToolNode`` over exactly the tools the
            # analyst is bound to (the same list permission is derived from).
            self._node = _tool_node_class()(list(self._tools))
        return self._node

    def _dispatch(
        self,
        calls: list[dict[str, Any]],
        state: Mapping[str, Any],
        config: Mapping[str, Any] | None,
    ) -> Any:
        if not calls:
            return []
        node = self._node_or_build()
        node_config = dict(config) if config is not None else None
        invoke = self._runner if callable(self._runner) else self._runner.invoke
        return invoke(node, calls, state=dict(state), config=node_config)
    @staticmethod
    def _index_outputs(outputs: Any) -> dict[str, Any]:
        if outputs is None:
            outputs = []
        if isinstance(outputs, Mapping):
            outputs = outputs.get("messages", [])
        result: dict[str, Any] = {}
        for message in outputs:
            call_id = _message_call_id(message)
            if call_id is None:
                raise GovernanceResultError(
                    "the ToolNode returned a message without a tool_call_id"
                )
            if call_id in result:
                raise GovernanceResultError(
                    f"the ToolNode returned more than one result for call {call_id!r}"
                )
            result[call_id] = message
        return result


def _governance_of(state: Mapping[str, Any]) -> dict[str, Any]:
    """The ``tool_governance`` value inside a prepared/execution state."""
    inner = dict(state).get(GOVERNANCE_STATE_KEY)
    return dict(inner or {})


def _message_call_id(message: Any) -> str | None:
    value = message.get("tool_call_id") if isinstance(message, Mapping) else None
    if value is None:
        value = getattr(message, "tool_call_id", None)
    return None if value is None else str(value)


def _message_dict(message: Any) -> dict[str, Any]:
    """A plain, serialisable message dict, keeping only a legal status.

    The id and the full content are carried verbatim. ``status`` is kept only
    when it is ``success`` or ``error`` -- the only values a ``ToolMessage``
    accepts -- so a governance outcome (``missing_data``/``degraded``/...) can
    never end up in a message.
    """
    if isinstance(message, Mapping):
        payload = dict(message)
    else:
        payload = {
            "type": "tool",
            "tool_call_id": _message_call_id(message),
            "content": getattr(message, "content", ""),
        }
        name = getattr(message, "name", None)
        if name is not None:
            payload["name"] = name
    status = getattr(message, "status", None)
    if status is None and isinstance(message, Mapping):
        status = message.get("status")
    if status in _MESSAGE_STATUSES:
        payload["status"] = status
    else:
        payload.pop("status", None)
    return payload


# ---------------------------------------------------------------------------
# Bounded wrap-up: what an analyst answer may become a report
# ---------------------------------------------------------------------------
#
# Shared by every governed analyst (market, fundamentals) so both exits -- the
# analyst's own text and the single wrap-up generation -- are held to exactly
# the same rules.


def message_calls(message: Any) -> list[dict[str, Any]]:
    """The model's tool calls on ``message``, as plain dicts (graph-safe)."""
    calls = getattr(message, "tool_calls", None) or []
    return [dict(call) for call in calls]


def message_text(content: Any) -> str:
    """The text of a message content (a string or a list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, Mapping) and isinstance(block.get("text"), str)
        )
    return ""


def unusable_response_reason(message: Any) -> str | None:
    """Why ``message`` cannot become a report, or ``None`` if it can.

    Uses the project's existing structured-response rules rather than a new
    heuristic: :func:`structured._refusal_text` for an explicit refusal (the
    Chat Completions field, a ``refusal`` content block, ``content_blocks``)
    and :func:`structured._finish_reason` for an explicit token-limit stop. The
    blank check follows the free-text path of
    :func:`structured.invoke_structured_or_freetext`: no text at all is not an
    answer.
    """
    from tradingagents.agents.utils import structured

    refusal = structured._refusal_text(message)
    if refusal is not None:
        return f"the model refused: {refusal.strip()[:200]}"
    finish = structured._finish_reason(message)
    if finish in structured._TRUNCATED_FINISH_REASONS:
        return f"the provider stopped at its token limit ({finish}): the text is partial"
    if not structured._message_content(message).strip():
        return "the model returned no content"
    return None


def analyst_report(message: Any) -> str:
    """The analyst's own final text, if it wrote one (else ``""``).

    An analyst that answers with plain text -- no tool calls -- has written its
    report itself. That text is the report; the governed path must not send it
    through the wrap-up and replace it with a second generation.

    An unusable answer is not a report: a refusal, an answer the provider cut
    off, or a blank body returns ``""`` so the caller fails instead of saving
    it as the report (see :func:`reject_unusable_response`).
    """
    from langchain_core.messages import AIMessage

    if not isinstance(message, AIMessage):
        return ""
    if getattr(message, "tool_calls", None):
        return ""
    if unusable_response_reason(message) is not None:
        return ""
    return message_text(message.content).strip()


def reject_unusable_response(message: Any, what: str, error: type[Exception]) -> None:
    """Raise ``error`` if ``message`` cannot be a report.

    Called on **both** exits -- the analyst's own text and the single wrap-up
    generation -- so a refusal, a truncated answer, an empty body or a request
    for (now closed) tools fails the run: it is never stored as the report,
    never marks the analyst finished, and never triggers a second generation.
    """
    from langchain_core.messages import AIMessage

    if not isinstance(message, AIMessage):
        raise error(f"{what} returned {type(message).__name__}, not a message")
    if getattr(message, "tool_calls", None):
        raise error(
            f"{what} asked for tools after its allowance was spent; the tools "
            "are closed and no report was fabricated"
        )
    problem = unusable_response_reason(message)
    if problem is not None:
        raise error(f"{what} did not produce a report: {problem}")
