import ast
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BeforeValidator

from tradingagents.dataflows.date_window import as_of
from tradingagents.dataflows.interface import route_to_vendor

# A batch larger than this is almost certainly the model looping, and the
# combined payload would swamp the context for no benefit.
MAX_BATCH_INDICATORS = 12


def _coerce_indicator_list(value):
    """Accept the shapes a model actually emits for an array argument.

    The declared type is ``list[str]``, but models send a bare string
    (``"cpi"``), a comma-separated string (``"cpi,vix"``), a JSON-ish list
    rendered as text (``"['cpi','vix']"``), a JSON array string
    (``'["cpi","vix"]'``), a tuple, a set, or null. Left alone, each of those
    raises a pydantic ``ValidationError`` inside the tool; LangChain's
    ``handle_validation_error`` defaults to ``False`` and LangGraph re-raises
    anything that is not a ``ToolInvocationError``, so a formatting slip would
    **abort the entire run**.

    This function is therefore written to be total: every input shape returns a
    list of strings, and it never raises.
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            # Try the JSON-ish spellings a model produces: python repr, then
            # strict JSON (double quotes). Neither is guaranteed to parse — a
            # model-written "['cpi', vix]" is a *syntax* error for literal_eval,
            # which raises ValueError, not just SyntaxError — so both attempts
            # are wrapped and any failure falls through to comma splitting.
            for parse in (_literal_eval_or_none, _json_loads_or_none):
                parsed = parse(text)
                if isinstance(parsed, (list, tuple, set)):
                    return [_as_str(item) for item in parsed]
            # Unparsable "[" ... "]" text is still better split than dropped.
            return [part.strip() for part in text.strip("[]").split(",") if part.strip()]
        return [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(value, dict):
        # Misuse: a mapping where a list belongs. Take its keys, which is what
        # the caller almost certainly meant, rather than raising.
        return [_as_str(key) for key in value]
    if isinstance(value, (list, tuple, set)):
        return [_as_str(item) for item in value]
    return [_as_str(value)]


def _literal_eval_or_none(text):
    """``ast.literal_eval`` that returns None instead of raising.

    A malformed bracketed list such as ``"['cpi', vix]"`` makes literal_eval
    raise ``ValueError('malformed node or string')``, not ``SyntaxError``, so
    both must be caught or a model formatting slip would propagate out of the
    validator and abort the run.
    """
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None


def _json_loads_or_none(text):
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _as_str(value):
    """Stringify one indicator without ever raising or producing 'None'."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


@tool
def get_macro_indicators(
    indicator: Annotated[
        str,
        "Macro indicator: a friendly alias such as 'cpi', 'core_pce', "
        "'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve', "
        "'real_gdp', 'vix', or a raw FRED series ID such as 'CPIAUCSL'.",
    ],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format; the end of the window"],
    look_back_days: Annotated[
        int | None, "Trailing window length in days; omit for a 1-year window"
    ] = None,
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """
    Retrieve a macroeconomic indicator time series from FRED (Federal Reserve
    Economic Data): policy rates, Treasury yields, inflation, labor, and growth.
    Returns the series title, units, frequency, the latest value, the change
    over the window, and a recent observation table. Uses the configured
    macro_data vendor.

    Args:
        indicator (str): Friendly alias or raw FRED series ID
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Trailing window length; omit for a 1-year window

    Returns:
        str: A formatted markdown report of the macro series
    """
    return route_to_vendor("get_macro_indicators", indicator, as_of(curr_date, trade_date), look_back_days)


# Substrings that mean a single series was not served. Used only to report the
# batch-level outcome honestly; the per-series text is never rewritten.
_UNAVAILABLE_MARKERS = ("DATA_UNAVAILABLE", "NO_DATA_AVAILABLE")


def _is_unavailable(text: str) -> bool:
    return any(marker in text for marker in _UNAVAILABLE_MARKERS)


@tool
def get_macro_indicators_batch(
    indicators: Annotated[
        list[str],
        BeforeValidator(_coerce_indicator_list),
        "Macro indicators, each a friendly alias such as 'cpi', 'core_pce', "
        "'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve', "
        "'real_gdp', 'vix', or a raw FRED series ID such as 'CPIAUCSL'.",
    ],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format; the end of the window"],
    look_back_days: Annotated[
        int | None, "Trailing window length in days; omit for a 1-year window"
    ] = None,
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """
    Retrieve SEVERAL macroeconomic indicator time series from FRED in one call.

    Prefer this over repeated ``get_macro_indicators`` calls whenever more than
    one series is needed: it returns exactly the same per-series reports, but as
    one tool result, so the conversation does not pay a separate round trip for
    each series. Each series is fetched independently — if one fails, the others
    are still returned and the failure is reported inline for that series only.

    Args:
        indicators (list[str]): Friendly aliases or raw FRED series IDs
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Trailing window length; omit for a 1-year window

    Returns:
        str: The formatted markdown report of each series, in the order requested
    """
    as_of_date = as_of(curr_date, trade_date)

    # Defensive re-normalisation. The BeforeValidator already ran on the real
    # ``.invoke()`` path, but ``.func`` and direct calls bypass pydantic, and a
    # malformed argument must never become an exception here either.
    if not isinstance(indicators, (list, tuple, set)):
        indicators = _coerce_indicator_list(indicators)

    seen: set[str] = set()
    ordered: list[str] = []
    for indicator in indicators:
        key = _as_str(indicator).strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        ordered.append(key)

    if not ordered:
        return "No macro indicators were requested; pass at least one alias or series ID."
    if len(ordered) > MAX_BATCH_INDICATORS:
        return (
            f"Too many indicators in one batch ({len(ordered)} > {MAX_BATCH_INDICATORS}). "
            f"Request at most {MAX_BATCH_INDICATORS} per call and ask again for the rest."
        )

    sections: list[str] = []
    unavailable: list[str] = []
    for indicator in ordered:
        try:
            # Same vendor call, same PIT pin and same formatting as the
            # single-series tool: the text of each series is byte-identical.
            text = route_to_vendor(
                "get_macro_indicators", indicator, as_of_date, look_back_days
            )
        except Exception as e:  # one bad series must not lose the others
            text = (
                f"## FRED: {indicator}\n"
                f"DATA_UNAVAILABLE: this series could not be retrieved ({type(e).__name__}: {e}). "
                f"The other requested series are unaffected; do not estimate or "
                f"fabricate values for {indicator}."
            )
        if _is_unavailable(text):
            unavailable.append(indicator)
        sections.append(text)

    body = "\n\n".join(sections)
    if unavailable and len(unavailable) == len(ordered):
        # The router returns a string, never an exception, so a total outage
        # would otherwise look like a successful batch. Say so explicitly.
        return (
            f"DATA_UNAVAILABLE: none of the {len(ordered)} requested macro series "
            f"could be retrieved ({', '.join(unavailable)}). This says nothing about "
            f"the economy; do not infer that these series are unchanged or absent.\n\n"
            + body
        )
    return body
