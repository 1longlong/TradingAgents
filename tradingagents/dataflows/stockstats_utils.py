import logging
import os
import time
from datetime import datetime, timezone, tzinfo
from typing import Annotated

import pandas as pd
import requests as _requests
import yfinance as yf
from stockstats import wrap
from yfinance._http import requests as _yf_http
from yfinance.exceptions import YFRateLimitError

from .config import get_config
from .errors import (
    VendorAuthenticationError,
    VendorError,
    VendorRateLimitError,
    VendorRequestRejectedError,
)
from .symbol_utils import NoMarketDataError, normalize_symbol
from .utils import safe_ticker_component, vendor_reachable

logger = logging.getLogger(__name__)

_YAHOO_HOST = "https://query2.finance.yahoo.com"


# Failures are classified by exception *type* and HTTP status, never by message
# text. yfinance 1.8 talks curl_cffi (falling back to ``requests``); the two
# backends have unrelated exception classes that both inherit OSError, so both
# are named explicitly rather than via OSError. A transport failure says the
# vendor could not be reached; a response error says it answered and refused.
def _named(exceptions, names: tuple[str, ...], fallback: type) -> tuple[type, ...]:
    """``getattr`` a set of class names, tolerating names a backend lacks."""
    return tuple(getattr(exceptions, name, fallback) for name in names)


# The transport family per backend (unreachable, not a refusal). ``requests``
# splits these off ``RequestException``; curl_cffi exposes some as bare
# ``RequestException``/``CurlError`` (curl exit codes), so its base is included.
# ``HTTPError`` and the JSON-decode classes are deliberately absent and are
# subtracted at the end: an answered refusal and a malformed body are not outages.
_REQUEST_TRANSPORT_NAMES = (
    "ConnectionError",
    "Timeout",
    "ConnectTimeout",
    "ReadTimeout",
    "ChunkedEncodingError",
    "SSLError",
    "ProxyError",
)
_CURL_TRANSPORT_NAMES = (
    "ConnectionError",
    "Timeout",
    "ChunkedEncodingError",
    "RequestException",
)


def _transport_types() -> tuple[type[BaseException], ...]:
    """Both backends' transport classes, whatever yfinance is wired to today."""
    requests_exc = _requests.exceptions
    classes: list[type[BaseException]] = [TimeoutError, ConnectionError]
    classes += _named(requests_exc, _REQUEST_TRANSPORT_NAMES, requests_exc.RequestException)
    if _yf_http.exceptions is not requests_exc:
        classes += _named(
            _yf_http.exceptions, _CURL_TRANSPORT_NAMES, _yf_http.exceptions.RequestException
        )
    return tuple(classes)


def _http_status(exc: BaseException) -> int | None:
    """The HTTP status a client error carries, if it carries one.

    ``requests``/``curl_cffi`` ``HTTPError`` keep it on ``.response``; a
    re-raised scrubbed error (``get_scrubbed``) has that response detached and
    keeps only its message in ``.args``. Read both, so a credential-scrubbed
    exception can still be classified without re-attaching the request URL.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    # Only an HTTP client error's own message is trusted for the status (e.g.
    # "403 Client Error: Forbidden for url: ..."). Any other exception may
    # merely begin with digits ("404 pages were not found"), which is not a
    # status and must not be read as one.
    if not isinstance(exc, _http_error_types()):
        return None
    for arg in getattr(exc, "args", ()):
        if not isinstance(arg, str):
            continue
        # Require the client library's own template ("NNN Client Error: ..." /
        # "HTTP Error NNN: ..."), so free text that merely begins with digits is
        # never mistaken for a status.
        prefix = arg[:15]
        client_error = (
            len(arg) >= 5
            and arg[:3].isdigit()
            and arg[3] == " "
            and arg[4:].startswith(("Client Error:", "Server Error:"))
        )
        if client_error:
            return int(arg[:3])
        if prefix.startswith("HTTP Error ") and arg[11:14].isdigit():
            return int(arg[11:14])
    return None


def _client_errors() -> tuple[type[BaseException], ...]:
    """Both HTTP backends' client-error bases, so a catch never depends on the active one."""
    fallback = _yf_http.exceptions.RequestException
    names = ("RequestException", "Timeout", "ConnectTimeout", "ReadTimeout", "JSONDecodeError")
    classes = _named(_yf_http.exceptions, names, fallback)
    if _yf_http.exceptions is not _requests.exceptions:
        classes += _named(_requests.exceptions, names, _requests.exceptions.RequestException)
    return (TimeoutError, ConnectionError, *classes)


def _http_error_types() -> tuple[type[BaseException], ...]:
    """Both backends' ``HTTPError``.

    yfinance uses ``curl_cffi`` when installed and plain ``requests`` otherwise
    (``yfinance._http``), and the two classes are unrelated, so a classifier
    that names only the active one silently misses the other backend.
    """
    live = _yf_http.exceptions.HTTPError
    return (
        (live,)
        if live is _requests.exceptions.HTTPError
        else (live, _requests.exceptions.HTTPError)
    )


def is_transport_error(exc: BaseException) -> bool:
    """True when ``exc`` reports unreachability, not a refusal or a payload.

    ``HTTPError`` (any status) and JSON-decode errors are excluded even though
    they share a backend's ``RequestException`` base; non-transport answers that
    share ``OSError`` (a closed socket, a JSON-parse ``ValueError``) are not in
    the named set, so they fall through as unclassified.
    """
    if isinstance(exc, (*_http_error_types(), *(_json_decode_types_inner()))):
        return False
    if isinstance(exc, YFRateLimitError):
        # Throttled, not unreachable: ``as_vendor_error`` maps it first.
        return False
    return isinstance(exc, _transport_types())


def _json_decode_types_inner() -> tuple[type[BaseException], ...]:
    classes = [_yf_http.exceptions.JSONDecodeError]
    requests_json = _requests.exceptions.JSONDecodeError
    if requests_json is not classes[0]:
        classes.append(requests_json)
    return tuple(classes)


_YAHOO_DISPLAY_NAME = "Yahoo Finance"


def as_vendor_error(exc: BaseException, vendor: str | None = None) -> VendorError | None:
    """Classify a vendor HTTP/transport failure by type/status, or return None.

    Backend-neutral: the rules describe *network* conditions, so any vendor can
    use them. The display name in the message defaults to Yahoo Finance only
    because yfinance is this project's default HTTP vendor; a caller acting for
    any other vendor must pass its own name. The router always does, so a
    non-Yahoo timeout is never reported as "Yahoo Finance is unreachable".

    - 429 throttle         -> ``VendorRateLimitError``
    - 401/403 credential   -> ``VendorAuthenticationError``
    - 400/404 request      -> ``VendorRequestRejectedError``
    - 5xx                  -> ``VendorRateLimitError`` (transient service error)
    - transport            -> ``VendorRateLimitError`` (unreachable)
    - any other status     -> None: an unknown status is not proven transient
    - JSON decode / bug    -> None: neither is an absence

    None means "not classified", never "absence". The returned error copies the
    vendor's own (already scrubbed) wording and no exception chain, so a URL
    carrying a key cannot ride along. The label is attached with
    ``with_vendor``, so a raiser that already knows its identity keeps it.
    """
    if isinstance(exc, VendorError):
        return exc if vendor is None else exc.with_vendor(vendor)
    if isinstance(exc, YFRateLimitError):
        # The one vendor-specific class: only yfinance raises it, so it names
        # itself regardless of the label passed in.
        return VendorRateLimitError(
            "Yahoo Finance rate limit exceeded (HTTP 429); it was not retrieved"
        )
    error = _classify_http_or_transport(exc, vendor or _YAHOO_DISPLAY_NAME)
    if error is not None and vendor is not None:
        error.with_vendor(vendor)
    return error


def _classify_http_or_transport(exc: BaseException, name: str) -> VendorError | None:
    """The shared status/transport rules, phrased with the caller's display name."""
    if isinstance(exc, _http_error_types()):
        status = _http_status(exc)
        if status == 429:
            return VendorRateLimitError(
                f"{name} rate limit exceeded (HTTP 429); it was not retrieved"
            )
        if status in (401, 403):
            return VendorAuthenticationError(
                f"{name} rejected the configured credentials (HTTP {status}): {exc}"
            )
        if status in (400, 404):
            return VendorRequestRejectedError(
                f"{name} refused the request (HTTP {status}): {exc}"
            )
        if status is not None and 500 <= status < 600:
            return VendorRateLimitError(
                f"{name} service error (HTTP {status}); it was not retrieved"
            )
        return None
    if is_transport_error(exc):
        return VendorRateLimitError(f"{name} is unreachable; it was not retrieved ({exc})")
    return None


def raise_for_unreachable(what: str, vendor: str | None = None) -> VendorRateLimitError:
    """Report a dead host as an outage, attributed to ``vendor``."""
    name = vendor or _YAHOO_DISPLAY_NAME
    return VendorRateLimitError(
        f"{name} is unreachable; it did not answer a request; {what} was not retrieved"
    )


# A vendor's latest OHLCV row this many calendar days before the requested date
# is treated as stale. Generous enough to span long holiday weekends, tight
# enough to catch the year-old frames yfinance occasionally returns (#1021).
MAX_OHLCV_STALE_DAYS = 10

# How long a same-day cache that does not yet reach the requested day may be
# reused before it is refetched (#1150). Short enough that an intraday run picks
# up today's close soon after it publishes, long enough that a day with no bar
# at all (weekend, holiday) cannot trigger a download on every call.
OHLCV_CACHE_TTL_SECONDS = 900


def local_tz() -> tzinfo | None:
    """The host's local timezone, as an explicit tz (``None`` only if unresolvable).

    ``datetime.now().astimezone().tzinfo`` is the zone the platform applies to
    wall-clock time, so a naive ``pd.Timestamp.today()`` can be interpreted in
    it without guessing. A fixed offset is acceptable here: the comparison
    spans one day, so a DST transition inside it shifts by at most an hour.
    """
    return datetime.now().astimezone().tzinfo


def raise_for_empty(symbol: str, canonical: str, what: str) -> None:
    """Report an empty Yahoo result as an absence, or as an outage if it is one.

    yfinance returns an empty frame for a failed request rather than raising, so
    without this a Yahoo outage reads as "this symbol has no {what}".

    ``vendor_reachable`` only reports whether the host answers at all, so it can
    corroborate an outage but must never confirm an absence: a host that answers
    HEAD can still have failed the specific request. It is therefore consulted
    only to *avoid* a false absence, never to establish one.
    """
    if not vendor_reachable(_YAHOO_HOST):
        raise raise_for_unreachable(what)
    raise NoMarketDataError(symbol, canonical, f"no {what}")


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize the date column to ``Date``.

    Some yfinance builds leave the index unnamed (so ``reset_index()`` yields
    ``index``) or use ``Datetime`` for intraday data. Rename the first
    date-like column so indicators don't silently drop when it isn't ``Date``.
    """
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _local_midnight(value) -> pd.Timestamp:
    """A single timestamp as its naive, midnight-normalized local date (or NaT)."""
    if pd.isna(value):
        return pd.NaT
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return pd.NaT
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)  # drop tz, keep the local wall-clock date
    return ts.normalize()


def _normalize_dates(dates) -> pd.Series:
    """Parse to naive, midnight-normalized dates so tz-aware or intraday
    timestamps compare correctly against the naive ``curr_date`` cutoff (#1201).

    Normalized per element: 5 years of yfinance bars span daylight-saving
    changes (and cache CSVs round-trip the offsets as strings), so the series can
    carry mixed UTC offsets that ``pd.to_datetime`` cannot unify without
    ``utc=True`` — which would shift non-US (positive-offset) markets to the
    previous day. Keeping each bar's own local date avoids both.
    """
    return pd.to_datetime(pd.Series(dates).map(_local_midnight))


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse/normalize dates and
    coerce prices to numeric (NaN where invalid). Dropping incomplete rows and
    filling gaps is left to ``_fill_price_gaps`` so the caller can first inspect
    the latest in-range bar (#1201)."""
    data = _ensure_date_column(data)
    data["Date"] = _normalize_dates(data["Date"])
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    return data


def _fill_price_gaps(data: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with no close and forward/back-fill remaining price gaps so
    indicators compute on a continuous series."""
    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    # copy() so a filtered (sliced) input is written to safely, not via a view.
    data = data.dropna(subset=["Close"]).copy()
    data[price_cols] = data[price_cols].ffill().bfill()
    return data


def _coerce_ohlcv_dates(data: pd.DataFrame) -> pd.Series:
    """Return parsed dates from an OHLCV frame, whether Date is a column or the index."""
    if "Date" in data.columns:
        return pd.to_datetime(data["Date"], errors="coerce").dropna()
    # yfinance keeps the dates in the index (a DatetimeIndex, sometimes unnamed).
    if isinstance(data.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(data.index, errors="coerce")).dropna()
    # Fallback: expose the index and look for any date-like column.
    df = data.reset_index()
    for col in ("Date", "Datetime", "date", "index"):
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if not parsed.empty:
                return parsed
    return pd.Series(dtype="datetime64[ns]")


def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
) -> None:
    """Reject OHLCV whose latest row is far older than curr_date.

    Raises NoMarketDataError (with a stale-specific detail) so the router treats
    it like any other "no usable data from this vendor" — try the next vendor,
    then emit one clear unavailable signal. Empty frames are left to the
    caller's existing no-data handling; this guards only the dangerous case of
    present-but-stale rows (a vendor returning a year-old frame that would
    otherwise feed wrong prices to the agent, #1021).
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    dates = _coerce_ohlcv_dates(data)
    if dates.empty:
        return
    latest = dates.max().normalize()
    stale_days = (requested - latest).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) — refusing to use it",
        )


def _as_aware(ts, tz) -> pd.Timestamp:
    """The instant ``ts`` denotes, treating a naive timestamp as local wall time.

    Three different time meanings meet here and must not be conflated:

    - the cache file's mtime is an **absolute epoch** (``os.path.getmtime``);
    - ``pd.Timestamp.today()`` is **local wall time** (naive): midnight on the
      host that runs the analysis, not midnight UTC;
    - ``curr_date`` is a **business date** (naive, no instant at all).

    A naive local wall time is therefore interpreted in ``tz`` -- the host's
    local zone, never relabelled as UTC. ``tz_localize(timezone.utc)`` would
    shift the instant by the host's offset and mis-date every file for hosts
    east/west of UTC.
    """
    ts = pd.Timestamp(ts)
    return ts if ts.tzinfo is not None else ts.tz_localize(tz)


def _cache_is_fresh(data_file, curr_date_dt, now) -> bool:
    """Whether the symbol's cached download can serve this request.

    The file holds the download made on the day it was written, so it serves
    only that day. A current-day request also refetches once the file is older
    than the TTL: Yahoo publishes a partial daily candle during market hours,
    whose ``Close`` is not the closing price, and row inspection cannot tell it
    from a final one (#1150).

    ``now`` is the host's local wall time (as ``pd.Timestamp.today()`` returns
    it); an aware ``now`` keeps its own zone. Both the file's instant and
    ``now`` are compared in that one zone, so "written today" means the same
    calendar day on the machine doing the analysis, including across midnight.
    """
    # Read the instant from the epoch; never from ``datetime.fromtimestamp``
    # with no zone, which re-applies the platform's local conversion.
    epoch = os.path.getmtime(data_file)
    written_at = pd.Timestamp(epoch, unit="s", tz=timezone.utc)
    now_ts = _as_aware(now, local_tz())
    # Compare *dates*, not instants: the file serves the local calendar day it
    # was written on. ``curr_date_dt`` is a naive business date (it has no
    # instant), so it is only ever compared as a date -- never tz-converted,
    # which a naive timestamp silently ignores.
    written_day = written_at.tz_convert(local_tz()).date()
    now_day = now_ts.date()
    if written_day != now_day:
        return False
    requested_day = pd.Timestamp(curr_date_dt).date()
    if requested_day < now_day:
        return True
    age_seconds = (now_ts - written_at) / pd.Timedelta(seconds=1)
    return age_seconds <= OHLCV_CACHE_TTL_SECONDS


def load_ohlcv(symbol: str, curr_date: str, fill_gaps: bool = True) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 5 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.

    ``fill_gaps`` carries prices forward over gaps so indicators compute on a
    continuous series. Pass ``False`` to read the values as the vendor reported
    them, leaving a cell that was never reported empty.
    """
    # Resolve broker/forex symbols (XAUUSD+ -> GC=F) to Yahoo's convention,
    # then reject values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date).normalize()

    # One cache file per symbol, holding the latest 5y-to-today download.
    now = pd.Timestamp.today()
    start_date = now - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    # yfinance ``end`` is EXCLUSIVE; request tomorrow so today's row is included
    # when curr_date is the current day (#986). Look-ahead is still prevented by
    # the curr_date filter below.
    end_str = (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data.csv",
    )

    # A cached file may be empty if a prior fetch failed (unknown symbol,
    # transient rate limit). Treat an empty/columnless cache as a miss and
    # re-fetch rather than serving the poisoned file forever.
    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if (
            not cached.empty
            and "Close" in cached.columns
            and _cache_is_fresh(data_file, curr_date_dt, now)
        ):
            data = cached

    if data is None:
        downloaded = yf_retry(lambda: yf.download(
            canonical,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        downloaded = _ensure_date_column(downloaded.reset_index())
        # Only cache real data — never persist an empty frame. An empty download
        # on a dead host is an outage, not an absence; the reachability check
        # lives in raise_for_empty so every empty-result path shares it.
        if downloaded.empty or "Close" not in downloaded.columns:
            raise_for_empty(symbol, canonical, "price rows")
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting.
    data = data[data["Date"] <= curr_date_dt]

    # A closeless newest bar is an unsettled session, not a symbol without data.
    # _fill_price_gaps below drops it, here and mid-series alike, so the frame
    # ends at the last settled bar; only a range with no close anywhere is no
    # data (#1201, #1289).
    if not data.empty and pd.isna(data["Close"].iloc[-1]):
        settled = data["Close"].notna().to_numpy().nonzero()[0]
        if settled.size == 0:
            raise NoMarketDataError(
                symbol, canonical, "no bar in range has a closing price"
            )
        logger.warning(
            "%s: %d trailing bar(s) through %s have no closing price; using %s "
            "as the latest close.", canonical, len(data) - settled[-1] - 1,
            data["Date"].iloc[-1].date(), data["Date"].iloc[settled[-1]].date(),
        )

    # Indicators need a continuous series, so gaps are carried forward. A caller
    # that reports the numbers themselves asks for the frame as it was reported:
    # a filled cell is the previous session's price under this session's date.
    data = _fill_price_gaps(data) if fill_gaps else data.dropna(subset=["Close"]).copy()

    # Reject a stale frame (latest row far older than curr_date) rather than
    # feeding year-old prices into indicators (#1021).
    _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
