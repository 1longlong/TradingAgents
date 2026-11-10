"""The explicit, off-by-default switch for the sentiment-analyst prefetch split.

With the switch off (the default) the sentiment analyst keeps its original
path: one node that fetches news, StockTwits and Reddit and then calls the
model. With it on, the graph gains one extra node::

    Sentiment Prefetch -> Sentiment Analyst

``Sentiment Prefetch`` makes the same three calls with the same window and
saves the three text blocks plus their identity in the ``sentiment_inputs``
state field (plain, serializable data only). The analyst node then builds its
prompt from that saved input and does not fetch anything.

What this buys, and what it does not:

* **What it buys.** Once the prefetch node has returned -- so LangGraph has
  committed its update to the checkpoint -- a crash inside the model call
  resumes at the analyst node and reuses the saved text instead of fetching
  the three sources again. An ``<... unavailable ...>`` placeholder is part of
  the saved text and is reused as-is, never silently refreshed.
* **What it does not buy.** If the prefetch node itself fails, or the process
  dies after one or two fetches but before the node returns, nothing was
  saved and a resume fetches again. There is no per-source checkpoint, no
  cross-run cache, no exactly-once guarantee across crashes.

The saved input is only consumed when every identity field matches the run
that is asking for it (schema version, the run's own ``run_id``, the analyst,
ticker, asset type, the full date window, the news article limit, the
StockTwits limit and the vendor chain). A missing, partial, wrong-version or
mismatched input is refused before the model is called; the analyst never
falls back to re-fetching.

The request parameters (``news_article_limit`` especially) and the news vendor
chain are read from **one snapshot** of the run's config (``state["run_config"]``,
the config the run was started with) and are part of the identity, so the saved
text is tied to the article count and the vendor chain the request actually
used -- not to whatever the global config says later. The snapshot lives in
this execution context only (``dataflows.config.config_snapshot``): the global
config is never written, so a concurrent ``set_config`` neither leaks into the
fetches nor is overwritten when the prefetch exits.

Generation judges the saved input against the **current run's** config the same
way: it opens the same context-local snapshot and reads the expected article
limit and vendor chain from it, never from the saved identity itself and never
from the global config. A run config that changed is refused before the model;
an unrelated global change is ignored.

The saving boundary is the node boundary: a node either returns its saved
input (and the checkpoint has it), or it raises and nothing is saved. Fetch
exceptions -- authentication, internal errors, cancellation and interrupts --
propagate exactly as on the single-node path.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

#: The config key holding the switch (``config["sentiment_prefetch"]["enabled"]``).
SECTION_KEY = "sentiment_prefetch"

#: The state field holding the saved prefetch result.
STATE_KEY = "sentiment_inputs"

#: The social analyst's wire key (``AnalystType.SOCIAL``).
ANALYST = "social"

#: The node label of the prefetch step.
PREFETCH_NODE = "Sentiment Prefetch"

#: Bumped whenever the saved shape or the meaning of a saved block changes.
#: A checkpoint saved under another version is not consumed.
SCHEMA_VERSION = "sentiment-inputs/v1"

#: The source arguments that change the fetched text, saved alongside it so a
#: resume whose call parameters changed is not served the old blocks.
STOCKTWITS_LIMIT = 30
_SOURCES = ("news", "stocktwits", "reddit")
_IDENTITY_FIELDS = (
    "schema_version",
    "run_id",
    "analyst",
    "ticker",
    "asset_type",
    "start_date",
    "end_date",
    "stocktwits_limit",
    "news_article_limit",
    "news_vendor_chain",
    "stocktwits_vendor",
    "reddit_vendor",
)

_ALLOWED_KEYS = frozenset({"enabled"})


class SentimentInputError(RuntimeError):
    """The saved sentiment input cannot be consumed for this run.

    Raised by the analyst node *before* the model is called: a missing,
    partial, wrong-version or identity-mismatched input is a hard failure, not
    a reason to fetch the sources again.
    """


@dataclass(frozen=True)
class FetchParameters:
    """The request parameters one prefetch actually used.

    Captured from the snapshot the fetches run under and passed to them, so the
    saved identity records the values the vendors received rather than whatever
    the configuration says after the call.
    """

    #: ``news_article_limit``: the article count both news vendors request.
    news_article_limit: int
    #: ``limit=`` passed to :func:`fetch_stocktwits_messages`.
    stocktwits_limit: int = STOCKTWITS_LIMIT


@dataclass(frozen=True)
class FetchSnapshot:
    """The one config snapshot a prefetch fetches under.

    Both the request parameters and the vendor chain in the saved identity are
    read from ``config`` -- the same mapping the fetches run under -- so the
    label can never name a vendor or a count the request did not use.
    """

    config: Mapping[str, Any]
    parameters: FetchParameters


def news_article_limit_now() -> Any:
    """The article limit a news call would use right now.

    Both news vendors read ``get_config()["news_article_limit"]`` at call
    time, so this is the exact config value the vendor is about to request --
    and inside :func:`fetch_snapshot` it is the snapshot's value.
    """
    from tradingagents.dataflows.config import get_config

    return get_config()["news_article_limit"]


def current_fetch_parameters() -> FetchParameters:
    """Snapshot the request parameters for one prefetch, before fetching.

    Called inside :func:`fetch_snapshot` on the prefetch path, so it reads the
    snapshot in effect for this execution context. On the single-node path the
    same snapshot is opened around the calls the node is making.
    """
    return FetchParameters(
        news_article_limit=news_article_limit_now(),
        stocktwits_limit=STOCKTWITS_LIMIT,
    )


@contextmanager
def fetch_snapshot(config: Mapping[str, Any]):
    """Run the fetches under ``config``, for this execution context only.

    ``config`` is the run's own config (``state["run_config"]``). It is copied
    and installed with :func:`tradingagents.dataflows.config.config_snapshot`,
    so the news tool and the vendor it routes to read *these* values, while any
    ``set_config`` happening elsewhere leaves this context and this snapshot
    untouched. Nothing global is written or restored.

    Yields the :class:`FetchSnapshot` used to label the result; leaving the
    block -- normally, on an exception, or on cancellation -- releases it.
    """
    from tradingagents.dataflows.config import config_snapshot

    with config_snapshot(config) as pinned:
        yield FetchSnapshot(config=pinned, parameters=current_fetch_parameters())


def _is_article_limit(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


@dataclass(frozen=True)
class SentimentPrefetch:
    """The validated switch."""

    enabled: bool = False


def parse_sentiment_prefetch(config: Mapping[str, Any] | None) -> SentimentPrefetch:
    """Read and strictly validate ``config["sentiment_prefetch"]``.

    Absent section, or ``enabled`` absent/False -> disabled (the default).
    A non-mapping section, an unknown key, or a non-boolean ``enabled`` is
    refused, never coerced.
    """
    section = (config or {}).get(SECTION_KEY)
    if section is None:
        return SentimentPrefetch()
    if not isinstance(section, Mapping):
        raise ValueError(f"{SECTION_KEY} must be a mapping, got {section!r}")
    unknown = sorted(set(section) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"unknown {SECTION_KEY} key(s): {', '.join(unknown)}")
    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(
            f"{SECTION_KEY}.enabled must be a boolean, got {enabled!r}"
        )
    return SentimentPrefetch(enabled=enabled)


def is_enabled(config: Mapping[str, Any] | None) -> bool:
    """Whether the prefetch split is switched on for this run."""
    return parse_sentiment_prefetch(config).enabled


def source_parameters(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The source identities that affect the three blocks (no credentials).

    The vendor chain order for news (which decides who answers) and the fixed
    StockTwits/Reddit clients. ``config`` is the snapshot the fetches run
    under; calling it again with the same mapping -- which the prefetch does
    after the block -- proves the chain was not changed by another caller
    while the fetches were in flight. No API key, URL or other configuration
    value is stored or hashed.
    """
    from tradingagents.dataflows.config import config_snapshot

    if config is None:
        chain = _news_vendor_chain()
    else:
        with config_snapshot(config):
            chain = _news_vendor_chain()
    return {
        "news_vendor_chain": chain,
        "stocktwits_vendor": "stocktwits",
        "reddit_vendor": "reddit",
    }


def _news_vendor_chain() -> tuple[str, ...]:
    from tradingagents.dataflows.interface import get_vendor

    return tuple(
        vendor.strip()
        for vendor in str(get_vendor("news_data", "get_news")).split(",")
        if vendor.strip()
    )


def refuse_changed_fetch_parameters(
    snapshot: FetchSnapshot, current: FetchParameters
) -> None:
    """Refuse when the context's snapshot is no longer the one that fetched.

    Only reachable if the snapshot was replaced inside the block (a nested
    snapshot). The label is never corrected afterwards; the prefetch fails
    before anything is saved.
    """
    if current.news_article_limit != snapshot.parameters.news_article_limit:
        raise SentimentInputError(
            "news_article_limit changed between snapshot and fetch "
            f"(saved {snapshot.parameters.news_article_limit!r}, "
            f"this context has {current.news_article_limit!r}); "
            "refusing to label the fetched text with a stale limit"
        )


def run_id_of(state: Mapping[str, Any]) -> str | None:
    """The run's existing unique id, or None when the state carries none."""
    value = (state.get("tool_governance") or {}).get("run_id")
    if isinstance(value, str) and value:
        return value
    return None


def build_identity(
    state: Mapping[str, Any],
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    fetch_parameters: FetchParameters,
    fetch_config: Mapping[str, Any],
) -> dict[str, Any]:
    """The non-sensitive identity a saved input is bound to.

    ``fetch_parameters`` and ``fetch_config`` are always explicit: the saved
    identity is stamped with the request parameters and the vendor chain the
    prefetch actually used, and the generation node compares against the same
    two values read from the current run's config.
    """
    identity: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id_of(state),
        "analyst": ANALYST,
        "ticker": ticker,
        "asset_type": state.get("asset_type", "stock"),
        "start_date": start_date,
        "end_date": end_date,
        "news_article_limit": fetch_parameters.news_article_limit,
        "stocktwits_limit": fetch_parameters.stocktwits_limit,
    }
    identity.update(source_parameters(fetch_config))
    return identity


def save_inputs(
    state: Mapping[str, Any],
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    snapshot: FetchSnapshot,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> dict[str, Any]:
    """The plain-data value the prefetch node returns under ``STATE_KEY``.

    ``snapshot`` is the one config the fetches ran under: its parameters and
    its vendor chain label the text, never a later config read. Only the
    identity and the three text blocks are stored: no model, no exception, no
    tool, no response object. A block that is not text is a programming error
    and is refused rather than silently saved.
    """
    fetch_parameters = snapshot.parameters
    if not _is_article_limit(fetch_parameters.news_article_limit):
        raise SentimentInputError(
            "the news article limit used by the prefetch must be a positive int, "
            f"got {fetch_parameters.news_article_limit!r}"
        )
    blocks = {
        "news": news_block,
        "stocktwits": stocktwits_block,
        "reddit": reddit_block,
    }
    for name, value in blocks.items():
        if not isinstance(value, str):
            raise SentimentInputError(
                f"the {name} prefetch result must be text, got {type(value).__name__}"
            )
    return {
        "identity": build_identity(
            state,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            fetch_parameters=fetch_parameters,
            fetch_config=snapshot.config,
        ),
        "blocks": blocks,
    }


def load_inputs(
    state: Mapping[str, Any],
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    snapshot: FetchSnapshot,
) -> dict[str, str]:
    """The three saved blocks, or raise :class:`SentimentInputError`.

    Every check runs before the analyst builds its prompt, so a bad input can
    never reach the model and can never trigger a re-fetch. The three blocks
    are returned exactly as saved (placeholders included).

    ``snapshot`` is opened on the **current run's** config, not the global
    one: its parameters and vendor chain are the expected values, so a resume
    is judged by what this run would fetch, never by what it previously saved.
    """
    saved = state.get(STATE_KEY)
    if not isinstance(saved, Mapping):
        raise SentimentInputError(
            "the sentiment prefetch split is enabled but no saved sentiment "
            "input is in the run state; the analyst does not fetch sources itself"
        )
    identity = saved.get("identity")
    if not isinstance(identity, Mapping):
        raise SentimentInputError("the saved sentiment input has no identity")
    missing = [field for field in _IDENTITY_FIELDS if field not in identity]
    if missing:
        raise SentimentInputError(
            f"the saved sentiment input identity is incomplete: missing {', '.join(missing)}"
        )
    if identity["schema_version"] != SCHEMA_VERSION:
        raise SentimentInputError(
            f"the saved sentiment input uses schema {identity['schema_version']!r}, "
            f"this run expects {SCHEMA_VERSION!r}"
        )

    expected = build_identity(
        state,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        fetch_parameters=snapshot.parameters,
        fetch_config=snapshot.config,
    )
    if not expected["run_id"]:
        raise SentimentInputError(
            "this run has no run_id; a saved sentiment input cannot be matched to it"
        )
    for field in _IDENTITY_FIELDS:
        have = identity[field]
        want = expected[field]
        if not _same(have, want):
            raise SentimentInputError(
                f"the saved sentiment input was fetched for a different run "
                f"({field}: saved {have!r}, this run has {want!r}); "
                "it is not reused and the sources are not re-fetched"
            )

    blocks = saved.get("blocks")
    if not isinstance(blocks, Mapping):
        raise SentimentInputError("the saved sentiment input has no data blocks")
    loaded: dict[str, str] = {}
    for name in _SOURCES:
        block = blocks.get(name)
        if not isinstance(block, str):
            raise SentimentInputError(
                f"the saved sentiment input is missing its {name} block"
            )
        loaded[name] = block
    return loaded


def _same(have: Any, want: Any) -> bool:
    """Deep equality; a JSON round-trip turns the saved tuple into a list."""
    if isinstance(want, (list, tuple)):
        return (
            isinstance(have, (list, tuple))
            and len(have) == len(want)
            and all(_same(a, b) for a, b in zip(have, want, strict=True))
        )
    return have == want


__all__ = [
    "ANALYST",
    "PREFETCH_NODE",
    "SCHEMA_VERSION",
    "SECTION_KEY",
    "STATE_KEY",
    "STOCKTWITS_LIMIT",
    "FetchParameters",
    "FetchSnapshot",
    "SentimentInputError",
    "SentimentPrefetch",
    "build_identity",
    "current_fetch_parameters",
    "fetch_snapshot",
    "is_enabled",
    "load_inputs",
    "news_article_limit_now",
    "parse_sentiment_prefetch",
    "refuse_changed_fetch_parameters",
    "run_id_of",
    "save_inputs",
    "source_parameters",
]
