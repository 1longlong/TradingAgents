"""The normalized execution identity of one run, for checkpoint resume.

A checkpoint may only be resumed by a run that would *execute the same work*.
That is decided from a small, explicit **allow-list** of configuration values
that change what the graph does -- never from the whole configuration:

* the analysts' effective tool allowances (rounds and calls actually enforced);
* the vendor chain each registered tool routes to, in chain order;
* the article counts / lookback / queries that decide what the news tools fetch;
* the model provider, the two model names, sampling knobs and the per-provider
  reasoning effort the run actually forwards;
* the analysis output language.

Everything else -- credentials, tokens, ``backend_url`` and other URLs, output
directories, debug/display switches, retry and breaker budgets -- is *not* part
of the identity. None of it changes which work a resumed graph performs, and
several of those values must never be written to a log or a thread id.

Two rules keep the identity honest:

* **Defaults equal explicit same values.** The effective tool allowance is read
  through the same parsers the graph uses, so ``{"enabled": True}`` and
  ``{"enabled": True, "max_rounds": 4, "max_calls": 10}`` are one identity.
  A *disabled* section contributes nothing, because its caps are never read.
* **Only the passed mapping is read.** Nothing here reads or writes the global
  configuration, and nothing is derived from wall-clock time or process state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

#: Bumped when the identity's fields or their meaning change. A checkpoint
#: tagged with another version is not treated as compatible: its thread id was
#: computed by a different rule, so it is simply a different run.
IDENTITY_VERSION = "run-identity/v1"

#: The tools the graph's ``ToolNode``s are built from, with the vendor category
#: each routes through (``tradingagents.dataflows.interface.TOOLS_CATEGORIES``).
#: The order is fixed so the identity is deterministic; the chain *order* inside
#: a value ("yfinance,alpha_vantage") is significant and kept verbatim.
ROUTED_TOOLS: tuple[tuple[str, str], ...] = (
    ("get_stock_data", "core_stock_apis"),
    ("get_indicators", "technical_indicators"),
    ("get_verified_market_snapshot", "technical_indicators"),
    ("get_fundamentals", "fundamental_data"),
    ("get_balance_sheet", "fundamental_data"),
    ("get_cashflow", "fundamental_data"),
    ("get_income_statement", "fundamental_data"),
    ("get_news", "news_data"),
    ("get_global_news", "news_data"),
    ("get_insider_transactions", "news_data"),
    ("get_macro_indicators", "macro_data"),
    ("get_prediction_markets", "prediction_markets"),
)

#: The model settings ``TradingAgentsGraph._get_provider_kwargs`` forwards to the
#: chat client. ``effort`` is the one the selected provider actually uses:
#: google -> ``google_thinking_level``, openai -> ``openai_reasoning_effort``,
#: anthropic -> ``anthropic_effort``. Provider-specific keys are only included
#: for the provider that reads them, because a key no client reads is not part
#: of what this run executes.
_PROVIDER_EFFORT_KEY = {
    "google": "google_thinking_level",
    "openai": "openai_reasoning_effort",
    "anthropic": "anthropic_effort",
}


def _vendor_chain(config: Mapping[str, Any], tool: str, category: str) -> str:
    """The configured vendor chain for one tool, read from ``config`` alone.

    Mirrors ``dataflows.interface.get_vendor``: the tool-level ``tool_vendors``
    entry wins, else the category entry, else ``"default"``. The value is kept
    verbatim (trimmed) so "yfinance,alpha_vantage" and its reverse differ.
    """
    tool_vendors = config.get("tool_vendors") or {}
    if isinstance(tool_vendors, Mapping) and tool in tool_vendors:
        value = tool_vendors[tool]
    else:
        data_vendors = config.get("data_vendors") or {}
        if isinstance(data_vendors, Mapping) and category in data_vendors:
            value = data_vendors[category]
        else:
            value = "default"
    return str(value).strip()


def _analysis_limit(parsed: Any) -> list[int] | None:
    """The effective ``[max_rounds, max_calls]`` of one analyst, or None."""
    if not parsed.enabled:
        # Disabled: both caps are never read, so a leftover value cannot matter.
        return None
    return [parsed.max_rounds, parsed.max_calls]


def _governance_identity(config: Mapping[str, Any]) -> dict[str, Any]:
    """The three analysts' effective tool allowances (``None`` when disabled)."""
    from .fundamentals_governance import parse_fundamentals_tool_governance
    from .market_governance import parse_market_tool_governance
    from .news_governance import parse_news_tool_governance

    return {
        "market": _analysis_limit(parse_market_tool_governance(config)),
        "fundamentals": _analysis_limit(parse_fundamentals_tool_governance(config)),
        "news": _analysis_limit(parse_news_tool_governance(config)),
    }


def _model_identity(config: Mapping[str, Any]) -> dict[str, Any]:
    """The model settings the run installs on its chat clients."""
    provider = str(config.get("llm_provider") or "").lower()
    effort_key = _PROVIDER_EFFORT_KEY.get(provider)
    return {
        "provider": provider,
        "deep_think_llm": config.get("deep_think_llm"),
        "quick_think_llm": config.get("quick_think_llm"),
        "temperature": config.get("temperature"),
        "max_tokens": config.get("max_tokens"),
        # Only the key the selected provider forwards; a foreign one is inert.
        "effort": config.get(effort_key) if effort_key else None,
    }


def _news_identity(config: Mapping[str, Any]) -> dict[str, Any]:
    """The inputs that decide what the news tools fetch."""
    queries = config.get("global_news_queries")
    return {
        "news_article_limit": config.get("news_article_limit"),
        "global_news_article_limit": config.get("global_news_article_limit"),
        "global_news_lookback_days": config.get("global_news_lookback_days"),
        # Order is significant: it is the order the queries are issued in.
        "global_news_queries": list(queries) if isinstance(queries, (list, tuple)) else queries,
    }


def _language_identity(config: Mapping[str, Any]) -> str:
    """The analysis output language, normalized like the prompt helper does."""
    value = config.get("output_language", "English")
    return "English" if str(value).strip().lower() == "english" else str(value).strip()


def execution_identity(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """The normalized, JSON-safe execution identity of ``config``.

    Only the allow-listed execution fields are read; see the module docstring.
    The returned mapping contains no credential, token or URL by construction.
    """
    cfg = dict(config or {})
    return {
        "version": IDENTITY_VERSION,
        "analysts_tool_allowance": _governance_identity(cfg),
        "vendor_chains": {
            tool: _vendor_chain(cfg, tool, category) for tool, category in ROUTED_TOOLS
        },
        "news": _news_identity(cfg),
        "models": _model_identity(cfg),
        "output_language": _language_identity(cfg),
    }


def execution_digest(config: Mapping[str, Any] | None) -> str:
    """A short, deterministic digest of :func:`execution_identity`.

    Deterministic keys and separators, so the same identity always yields the
    same digest; only the digest -- never the values -- is written to a log.
    """
    encoded = json.dumps(
        execution_identity(config), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "IDENTITY_VERSION",
    "ROUTED_TOOLS",
    "execution_digest",
    "execution_identity",
]
