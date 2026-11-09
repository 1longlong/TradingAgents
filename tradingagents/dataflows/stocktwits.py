"""StockTwits public symbol-stream fetcher.

StockTwits exposes a per-symbol message stream at
``api.stocktwits.com/api/2/streams/symbol/{ticker}.json`` that requires no
API key, no OAuth, and no registration. Each message includes a
user-labeled sentiment field (``Bullish``/``Bearish``/null), the message
body, timestamp, and posting user.

The function is deliberately self-contained: short timeout, graceful
degradation on any HTTP or parse failure, and a string return type so
the calling agent gets a uniform interface regardless of whether the
network call succeeded.

A response that cannot be read as the documented payload -- a different
top-level type, ``messages`` that is not a list, a non-object entry, or a
nested field used for rendering with the wrong type -- is reported as
``<stocktwits unavailable: ...>`` for the whole response. It is never
reported as silence, and no sentiment ratio is computed from a partially
understood stream (that would present the surviving records as the complete
result). Only the shape is checked; a well-shaped response that is empty or
out of window keeps the previous behaviour.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
from datetime import datetime
from urllib.request import Request, urlopen

from .date_window import coverage_gap, in_window
from .symbol_utils import crypto_base

logger = logging.getLogger(__name__)

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# Safe reason codes for logs: the payload (bodies, usernames, timestamps) never
# reaches a message, and a malformed response is described by shape only.
_REASON_TOP_LEVEL = "top_level_not_object"
_REASON_MESSAGES_TYPE = "messages_not_list"
_REASON_ENTRY_TYPE = "entry_not_object"
_REASON_CREATED_AT = "created_at_not_string"
_REASON_USER = "user_not_object"
_REASON_USERNAME = "user_username_not_string"
_REASON_ENTITIES = "entities_not_object"
_REASON_SENTIMENT = "entities_sentiment_not_object"
_REASON_SENTIMENT_BASIC = "sentiment_basic_not_string"
_REASON_BODY = "body_not_string"


def _shape_error(data) -> str | None:
    """The safe reason code for a response that is not the documented shape.

    ``None`` means the payload can be rendered safely. The checks mirror exactly
    what the renderer and the window filter read, so nothing is trusted by
    accident. Missing values (``None``/absent) are accepted: StockTwits omits
    ``entities`` and ``sentiment`` for unlabeled posts, and ``user`` may be
    absent for deleted accounts -- those render as "no-label"/"?" by design.
    Values that are *present but of the wrong type* are rejected, because the
    renderer must not silently drop or stringify them.
    """
    if not isinstance(data, dict):
        return _REASON_TOP_LEVEL
    messages = data.get("messages")
    if messages is None:
        return None  # tolerated: documented as empty by the existing code
    if not isinstance(messages, list):
        return _REASON_MESSAGES_TYPE
    return _message_shape_error(messages)


def _message_shape_error(messages) -> str | None:
    """Reason code for the first entry whose fields the renderer cannot read."""
    for m in messages:
        if not isinstance(m, dict):
            return _REASON_ENTRY_TYPE
        created = m.get("created_at")
        if created is not None and not isinstance(created, str):
            return _REASON_CREATED_AT
        user = m.get("user")
        if user is not None:
            if not isinstance(user, dict):
                return _REASON_USER
            username = user.get("username")
            if username is not None and not isinstance(username, str):
                return _REASON_USERNAME
        entities = m.get("entities")
        if entities is not None:
            if not isinstance(entities, dict):
                return _REASON_ENTITIES
            sentiment = entities.get("sentiment")
            if sentiment is not None:
                if not isinstance(sentiment, dict):
                    return _REASON_SENTIMENT
                basic = sentiment.get("basic")
                if basic is not None and not isinstance(basic, str):
                    return _REASON_SENTIMENT_BASIC
        body = m.get("body")
        if body is not None and not isinstance(body, str):
            return _REASON_BODY
    return None


def _unavailable(reason: str) -> str:
    """The placeholder for a response that cannot be interpreted safely."""
    return f"<stocktwits unavailable: {reason}>"


def _created_at(message) -> datetime | None:
    """Parse a message's ISO 8601 ``created_at``; None when missing or malformed."""
    raw = message.get("created_at")
    if not raw:
        return None
    with contextlib.suppress(ValueError, TypeError):
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return None


def _within_window(messages, start_date, end_date):
    """Keep only messages published in [start_date, end_date] (look-ahead safe).

    No window (both None) leaves the list untouched for live callers. A message
    whose ``created_at`` (ISO 8601) is unparseable is dropped in a historical
    window, since we can't prove it isn't from after the as-of date (#1220).
    """
    if not (start_date and end_date):
        return messages
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    return [m for m in messages if in_window(_created_at(m), start_dt, end_dt)]


def _stocktwits_symbol(ticker: str) -> str:
    """Map a crypto pair to StockTwits' ``<BASE>.X`` convention.

    StockTwits lists crypto as ``BTC.X`` (Yahoo's ``BTC-USD`` form 404s), so any
    crypto symbol resolves to its base plus ``.X``; other symbols pass through
    upper-cased.
    """
    base = crypto_base(ticker)
    return f"{base}.X" if base else ticker.strip().upper()


def fetch_stocktwits_messages(
    ticker: str,
    limit: int = 30,
    timeout: float = 10.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Fetch recent StockTwits messages for ``ticker`` and return them as a
    formatted plaintext block ready for prompt injection.

    When ``start_date``/``end_date`` (yyyy-mm-dd) are given, messages are trimmed
    to that window, so a historical run never sees today's chatter (#1220). The
    public stream only serves recent messages, so a window it cannot reach is
    reported as unavailable rather than as silence.

    Returns a placeholder string when the endpoint is unreachable, the
    symbol has no messages, or the response shape is unexpected — the
    caller never has to special-case None or exceptions.

    A response whose shape cannot be interpreted raises nothing and is not
    trimmed to its readable records: the whole payload becomes
    ``<stocktwits unavailable: <reason>>``, so an unreadable stream is never
    passed off as "no discussion" and no ratio is derived from it.
    """
    url = _API.format(ticker=_stocktwits_symbol(ticker))
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        # OSError covers URLError/TimeoutError/connection resets; HTTPException
        # covers chunked-transfer errors (IncompleteRead/BadStatusLine, #1024).
        # Log the exception type only: a URL, body or vendor message could carry
        # information the placeholder must not.
        logger.warning("StockTwits fetch failed for %s: %s", ticker, type(exc).__name__)
        return _unavailable(type(exc).__name__)

    # Validate before filtering or rendering. An unreadable payload is reported
    # for the whole response: no ratio is computed and no surviving record is
    # presented as the complete result.
    reason = _shape_error(data)
    if reason is not None:
        logger.warning("StockTwits response rejected for %s: %s", ticker, reason)
        return _unavailable(reason)

    fetched = data.get("messages") or []
    messages = _within_window(fetched, start_date, end_date)
    if not messages:
        if start_date and end_date:
            gap = coverage_gap(
                (_created_at(m) for m in fetched), start_date, end_date,
                "StockTwits", f"messages about ${ticker.upper()}",
            )
            return gap or (
                f"<no StockTwits messages for ${ticker.upper()} within "
                f"{start_date}..{end_date}>"
            )
        return f"<no StockTwits messages found for ${ticker.upper()}>"

    lines = []
    bullish = bearish = unlabeled = 0
    for m in messages[:limit]:
        created = m.get("created_at", "")
        user = m.get("user") or {}
        username = user.get("username", "?")
        entities = m.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic") if isinstance(sentiment_obj, dict) else None
        body = (m.get("body") or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"

        if sentiment == "Bullish":
            bullish += 1
            tag = "Bullish"
        elif sentiment == "Bearish":
            bearish += 1
            tag = "Bearish"
        else:
            unlabeled += 1
            tag = "no-label"
        lines.append(f"[{created} · @{username} · {tag}] {body}")

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    summary = (
        f"Bullish: {bullish} ({bull_pct}%) · "
        f"Bearish: {bearish} ({bear_pct}%) · "
        f"Unlabeled: {unlabeled} · "
        f"Total: {total} most-recent messages"
    )
    return summary + "\n\n" + "\n".join(lines)
