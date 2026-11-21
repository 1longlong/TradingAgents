import json
import os
from datetime import datetime
from io import StringIO

import pandas as pd
from requests.exceptions import RequestException

from .errors import (
    VendorAuthenticationError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from .retry_session import request_timeout, stop_before_request
from .utils import get_scrubbed, retry_after_seconds

API_BASE_URL = "https://www.alphavantage.co/query"

# Network timeout (seconds) so a stalled Alpha Vantage request can't hang the
# CLI/agents indefinitely (#990).
REQUEST_TIMEOUT = 30


class AlphaVantageNotConfiguredError(VendorNotConfiguredError):
    """Raised when Alpha Vantage is selected but no API key is configured.

    A VendorNotConfiguredError (and thus still a ValueError), so the routing
    layer's "vendor unavailable" handling and existing ValueError callers both
    keep working.
    """
    pass


def get_api_key() -> str:
    """Retrieve the API key for Alpha Vantage from environment variables."""
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise AlphaVantageNotConfiguredError(
            "ALPHA_VANTAGE_API_KEY environment variable is not set."
        )
    return api_key

def format_datetime_for_api(date_input, end_of_day: bool = False) -> str:
    """Convert various date formats to the YYYYMMDDTHHMM Alpha Vantage expects.

    A plain date means midnight, which is the start of that day. For the end of
    a window pass ``end_of_day`` so the day itself is inside it, rather than
    dropping everything published on the analysis date.
    """
    if isinstance(date_input, str):
        # If already in correct format, return as-is
        if len(date_input) == 13 and 'T' in date_input:
            return date_input
        # Try to parse common date formats
        try:
            dt = datetime.strptime(date_input, "%Y-%m-%d")
            return dt.strftime("%Y%m%dT2359" if end_of_day else "%Y%m%dT0000")
        except ValueError:
            try:
                dt = datetime.strptime(date_input, "%Y-%m-%d %H:%M")
                return dt.strftime("%Y%m%dT%H%M")
            except ValueError:
                raise ValueError(f"Unsupported date format: {date_input}") from None
    elif isinstance(date_input, datetime):
        return date_input.strftime("%Y%m%dT%H%M")
    else:
        raise ValueError(f"Date must be string or datetime object, got {type(date_input)}")

class AlphaVantageRateLimitError(VendorRateLimitError):
    """Raised when the Alpha Vantage API rate limit is exceeded."""


class AlphaVantageQuotaExhaustedError(AlphaVantageRateLimitError):
    """A throttle the vendor will not lift within a budget: the daily quota or plan.

    Still a ``VendorRateLimitError`` (the family the router reports as "throttled
    or unreachable"), but with ``retry=False``: waiting out a per-day allowance or
    an entitlement does not restore it, and every attempt may still be counted
    against the quota. The router moves on to the next vendor instead.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.retry = False


class AlphaVantageAuthenticationError(VendorAuthenticationError):
    """Raised when Alpha Vantage rejects the supplied API key (HTTP 401/403)."""
    pass


def _raise_for_http_status(exc) -> None:
    """Turn a scrubbed HTTP error into the vendor error its status means.

    ``get_scrubbed`` detaches the response (it holds the URL with the key) but
    keeps the status in ``response.status_code`` and in the message prefix, and
    copies any ``Retry-After`` delay onto the error as ``.retry_after``, so this
    reads the status, never the URL.

    The typed error is scrubbed of the key by construction, so it is raised
    with both links back to the client error dropped: an explicit cause would
    only repeat the scrubbed message, and an implicit context would keep the
    client's own exception (and its request) reachable.
    """
    error = _http_status_error(exc)
    if error is not None:
        raise error


def _http_status_error(exc):
    """The typed error a scrubbed HTTP status means, or None to keep the original."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        for arg in getattr(exc, "args", ()):
            if isinstance(arg, str) and len(arg) > 3 and arg[:3].isdigit():
                status = int(arg[:3])
                break
    retry_after = getattr(exc, "retry_after", None)
    if status in (401, 403):
        return AlphaVantageAuthenticationError(
            f"Alpha Vantage rejected the configured API key (HTTP {status})."
        ).with_retry_evidence(status=status, retry=False)
    if status == 429:
        return AlphaVantageRateLimitError(
            "Alpha Vantage rate limit exceeded (HTTP 429)."
        ).with_retry_evidence(
            status=status,
            retry_after=retry_after if isinstance(retry_after, (int, float)) else None,
            retry=True,
        )
    # Any other status keeps its own type: not proven transient, not an absence.
    return None


def _make_api_request(function_name: str, params: dict) -> dict | str:
    """Helper function to make API requests and handle responses.

    Raises:
        AlphaVantageRateLimitError: When API rate limit is exceeded
    """
    # Create a copy of params to avoid modifying the original
    api_key = get_api_key()
    api_params = params.copy()
    api_params.update({
        "function": function_name,
        "apikey": api_key,
        "source": "trading_agents",
    })

    # Handle entitlement parameter if present in params or global variable
    current_entitlement = globals().get('_current_entitlement')
    entitlement = api_params.get("entitlement") or current_entitlement

    if entitlement:
        api_params["entitlement"] = entitlement
    elif "entitlement" in api_params:
        # Remove entitlement if it's None or empty
        api_params.pop("entitlement", None)

    try:
        response = get_scrubbed(
            API_BASE_URL,
            params=api_params,
            timeout=_request_timeout(),
            secret=api_key,
            extra_metadata=_retry_metadata,
        )
    except RequestException as exc:
        # ``error`` stays None for a status that is not permission/credential,
        # which then keeps the client error's own type.
        error = _http_status_error(exc)
        if error is None:
            raise
        # The typed error is scrubbed of the key by construction, so the two
        # links back to the client error are dropped: an explicit cause would
        # only repeat the scrubbed message, and an implicit context would keep
        # the client's own exception (and its request) reachable. Set both
        # because the raise machinery re-links a fresh exception's context.
        error.__cause__ = None
        error.__suppress_context__ = True
        raise error from None  # the linter wants the clause stated; the two lines above set it

    response_text = response.text

    # Error responses are JSON; data responses are usually CSV (or data-keyed
    # JSON). A non-JSON body is normal data.
    try:
        response_json = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text

    # Alpha Vantage reports problems via "Information" / "Note". Classify so a
    # genuine rate limit and an invalid/missing key aren't conflated (#991):
    # rate-limit phrasing is checked first because those notices also mention
    # "API key" ("your API key ... 25 requests per day").
    notice = response_json.get("Information") or response_json.get("Note")
    if notice:
        low = notice.lower()
        # A notice saying the *daily* allowance or the plan's entitlement is gone
        # is not a wait-and-retry throttle: no short pause restores it, and each
        # attempt may still be metered. A plain call-frequency notice is.
        if any(m in low for m in ("per day", "daily", "premium", "entitlement", "plan")):
            raise AlphaVantageQuotaExhaustedError(notice)
        if any(m in low for m in ("rate limit", "requests per day", "call frequency", "premium")):
            # A call-frequency notice is a short throttle: "come back shortly",
            # with no status or Retry-After, so a bounded wait is the remedy.
            raise AlphaVantageRateLimitError(
                f"Alpha Vantage rate limit exceeded: {notice}"
            ).with_retry_evidence(retry=True)
        if "api key" in low or "apikey" in low:
            # Reuse the existing "not configured" error so a bad key surfaces as
            # a real, actionable failure rather than a mislabeled rate limit (#991).
            raise AlphaVantageNotConfiguredError(f"Alpha Vantage API key invalid or missing: {notice}")

    return response_text


def _request_timeout() -> float:
    """The request timeout: the routed budget left (capped), else the vendor default.

    Called immediately before each HTTP request of this vendor. When the chain's
    budget cannot cover another valid request the request is refused with
    ``VendorRateLimitError`` (retry=False), so no request is started that the
    budget could only cut off mid-flight.
    """
    what = "an Alpha Vantage request"
    timeout = request_timeout(REQUEST_TIMEOUT, what)
    if timeout is None:
        stop_before_request(what, VendorRateLimitError)
    return timeout


def _retry_metadata(response) -> dict:
    """The retention facts to keep from a response we must not re-attach.

    Only a scrubbed, scalar copy of ``Retry-After`` -- the response and its URL
    (which carries the key) stay behind.
    """
    return {"retry_after": retry_after_seconds(getattr(response, "headers", None))}



def _filter_csv_by_date_range(csv_data: str, start_date: str, end_date: str) -> str:
    """
    Filter CSV data to include only rows within the specified date range.

    Args:
        csv_data: CSV string from Alpha Vantage API
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Filtered CSV string
    """
    if not csv_data or csv_data.strip() == "":
        return csv_data

    # Deliberately unguarded: TIME_SERIES_DAILY_ADJUSTED returns the full series
    # up to today, so this trim is the only thing keeping bars after end_date out
    # of a historical run. Swallowing a parse failure would serve the untrimmed
    # body, and with it future prices.
    df = pd.read_csv(StringIO(csv_data))

    # Assume the first column is the date column (timestamp)
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    filtered_df = df[(df[date_col] >= start_dt) & (df[date_col] <= end_dt)]

    return filtered_df.to_csv(index=False)
