"""Polymarket prediction-market vendor.

Surfaces live, market-implied probabilities for forward-looking events (Fed
decisions, recession, elections, geopolitics, crypto) to the news analyst, as a
complement to news (what happened) and FRED macro data (where things stand):
what the crowd actually prices to happen next.

Uses Polymarket's public Gamma API (https://gamma-api.polymarket.com) — no key,
no auth. Each market's ``outcomePrices`` are the implied probabilities of its
outcomes (a "Yes" at 0.76 means the market prices a 76% chance).
"""
import json
import logging
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter

from .errors import VendorError, VendorRateLimitError, retryable_status, retryable_transport_error
from .retry_session import request_timeout, stop_before_request
from .utils import get_current_date, retry_after_seconds

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Network timeout (seconds), consistent with the other vendors.
REQUEST_TIMEOUT = 30

# Default number of markets to return, ranked by traded volume.
DEFAULT_LIMIT = 6


# A bare ``requests.Session`` retries nothing on its own in requests 2.x, but an
# adapter can be configured to; build one explicitly with zero retries so the
# router's budget is the only retry loop this vendor runs.
def _session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _request(path: str, params: dict) -> dict:
    what = f"a Polymarket request ({path})"
    timeout = request_timeout(REQUEST_TIMEOUT, what)
    if timeout is None:
        stop_before_request(what, VendorRateLimitError)
    try:
        response = _session().get(
            f"{GAMMA_BASE}/{path}",
            params=params,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        retry_after = retry_after_seconds(getattr(getattr(exc, "response", None), "headers", None))
        recoverable = retryable_status(status, retry_after)
        if recoverable is None:
            # No status: a transport failure, judged by type (a TLS/URL problem
            # is configuration, never a momentary outage).
            recoverable = retryable_transport_error(exc)
        # A vendor fault, raised rather than returned as prose: prose would read
        # as success and end the chain at the vendor that failed.
        error = VendorRateLimitError(
            f"Polymarket request failed ({status or type(exc).__name__})"
        ).with_retry_evidence(
            status=status, retry_after=retry_after, retry=bool(recoverable)
        )
        raise error from exc
    except ValueError as exc:
        # An unreadable body is not momentarily missing: do not retry it.
        error = VendorRateLimitError("Polymarket returned an unreadable response")
        error.retry = False
        raise error from exc


def _parse_json_list(value) -> list:
    """Gamma encodes ``outcomes``/``outcomePrices`` as JSON-string arrays."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _is_forward_looking(market: dict, now: datetime) -> bool:
    """Keep only open markets that resolve in the future.

    ``closed`` is the reliable resolved flag (``active`` stays True even for
    settled markets), and a past ``endDate`` means the event already resolved —
    either way it is not a forward-looking signal.
    """
    if market.get("closed"):
        return False
    end_date = market.get("endDate")
    if end_date:
        try:
            if datetime.fromisoformat(end_date.replace("Z", "+00:00")) < now:
                return False
        except ValueError:
            pass
    return bool(_parse_json_list(market.get("outcomePrices"))) and bool(
        _parse_json_list(market.get("outcomes"))
    )


def get_prediction_markets(topic: str, limit: int | None = None, curr_date: str | None = None) -> str:
    """Return live prediction-market probabilities for an event topic.

    Args:
        topic: Event keyword(s), e.g. "Fed rate cut", "recession 2026",
            "US election", or a sector/company event.
        limit: Max markets to return (ranked by traded volume); ``None`` uses
            DEFAULT_LIMIT.
        curr_date: The analysis date. Polymarket serves only live odds, so a
            date before today withholds them.

    Returns:
        A markdown report of the most-traded open markets matching the topic,
        each with its implied probability, traded volume, resolution date, and
        recent (1-week) move.
    """
    if curr_date and curr_date < get_current_date():
        return (
            f"Prediction-market odds are withheld for {curr_date}. Polymarket serves "
            f"only live odds on open markets, with no historical vintage, so serving "
            f"them would put post-decision information into a {curr_date} analysis."
        )
    if limit is None:
        limit = DEFAULT_LIMIT

    try:
        data = _request("public-search", {"q": topic, "limit_per_type": 20})
    except VendorError:
        # Already typed by ``_request``; the router decides whether to retry
        # and how to report it.
        raise
    except requests.RequestException as e:
        # A failure that escaped ``_request``'s classification (e.g. the request
        # was built but the client raised something else) is still a vendor
        # fault, raised typed so the router can classify and retry it.
        logger.warning("Polymarket search failed for %r: %s", topic, type(e).__name__)
        raise VendorRateLimitError(f"Polymarket search failed ({type(e).__name__})") from e

    now = datetime.now(timezone.utc)
    candidates = [
        m
        for event in data.get("events", [])
        for m in event.get("markets", [])
        if _is_forward_looking(m, now)
    ]
    candidates.sort(key=lambda m: m.get("volumeNum") or 0, reverse=True)

    header = (
        f'## Polymarket prediction markets: "{topic}"\n'
        f"Live, market-implied probabilities (higher traded volume = deeper, "
        f"more reliable). A probability is the crowd's priced odds of the event, "
        f"not a forecast you should take as certain.\n\n"
    )

    if not candidates:
        return header + (
            f"No open prediction markets matched '{topic}'. Polymarket coverage "
            f"is concentrated in macro, political, geopolitical, and crypto "
            f"events; a specific equity may have none."
        )

    lines = []
    for m in candidates[:limit]:
        prices = _parse_json_list(m.get("outcomePrices"))
        outcomes = _parse_json_list(m.get("outcomes"))
        try:
            prob = float(prices[0])
        except (ValueError, IndexError):
            continue
        label = outcomes[0] if outcomes else "Yes"
        volume = m.get("volumeNum") or 0
        end_date = (m.get("endDate") or "")[:10]
        wk = m.get("oneWeekPriceChange")
        wk_str = (
            f", 1-week {wk * 100:+.1f}pp"
            if isinstance(wk, (int, float)) and wk
            else ""
        )
        lines.append(
            f"- **{m.get('question')}** — {label} {prob:.0%} "
            f"(${volume:,.0f} volume, resolves {end_date}{wk_str})"
        )

    return header + "\n".join(lines) + "\n"
