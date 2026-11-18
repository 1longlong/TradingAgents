"""Company statements as they were filed, from SEC EDGAR.

Every other fundamentals vendor serves a period's current value and cuts the
statement at the fiscal period end. That is two claims a run should not make: a
period that has ended is not public until the company files, weeks later, and a
figure that was later restated is not what investors saw at the time.

EDGAR reports every fact with the date it was filed, so a run dated ``curr_date``
serves exactly what was on file by then, restatements included at the vintage
that was current: Apple's 2008 total assets read 39.6B until the 2010 amendment
restated them to 36.2B.

Access needs no key or account, only a User-Agent identifying the caller, which
SEC requires and refuses requests without. US filers only: anything absent from
EDGAR's ticker map falls through to the next configured vendor.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from importlib import metadata
from pathlib import Path

import requests

from .config import get_config
from .errors import NoMarketDataError, VendorRateLimitError

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# A filing history only changes when something new is filed, so one fetch per
# company per day serves every date a run asks about.
_CACHE_TTL_SECONDS = 24 * 60 * 60

# Line items, each with the tags filers use for it, best first. First match wins
# and values are never summed across tags: a company reporting revenue under two
# tags would otherwise be counted twice.
_STATEMENTS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "balance_sheet": [
        ("Total Assets", ("Assets",)),
        ("Current Assets", ("AssetsCurrent",)),
        ("Cash and Equivalents", ("CashAndCashEquivalentsAtCarryingValue",)),
        ("Total Liabilities", ("Liabilities",)),
        ("Current Liabilities", ("LiabilitiesCurrent",)),
        ("Stockholders Equity", ("StockholdersEquity",
                                 "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")),
    ],
    "income_statement": [
        ("Revenue", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                     "SalesRevenueNet")),
        ("Cost of Revenue", ("CostOfRevenue", "CostOfGoodsAndServicesSold")),
        ("Gross Profit", ("GrossProfit",)),
        ("Operating Income", ("OperatingIncomeLoss",)),
        ("Net Income", ("NetIncomeLoss",)),
        ("Diluted EPS", ("EarningsPerShareDiluted",)),
    ],
    "cashflow": [
        ("Operating Cash Flow", ("NetCashProvidedByUsedInOperatingActivities",
                                 "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")),
        ("Investing Cash Flow", ("NetCashProvidedByUsedInInvestingActivities",)),
        ("Financing Cash Flow", ("NetCashProvidedByUsedInFinancingActivities",)),
        ("Capital Expenditure", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
    ],
}

# A statement's figures cover a span: a quarter is about 90 days, a year about
# 365. One filing reports both the quarter and the year to date under the same
# end date, so a match on the end date alone can report half a year as a quarter.
_SPANS = {"quarterly": (60, 115), "annual": (300, 400)}


def _user_agent() -> str:
    """Who SEC sees. No account or key exists; callers identify themselves.

    www.sec.gov, which serves the ticker map, refuses a User-Agent carrying no
    contact address: a client name alone or with a project URL gets 403, one
    with an address gets 200. So the default carries a placeholder address and
    the package version. Set SEC_EDGAR_USER_AGENT to your own name and address
    so SEC can reach you about your traffic rather than the project.
    """
    configured = os.getenv("SEC_EDGAR_USER_AGENT", "").strip()
    return configured or f"TradingAgents/{_version()} (contact@example.com)"


def _version() -> str:
    """The installed package version, so a release identifies itself correctly."""
    try:
        return metadata.version("tradingagents")
    except metadata.PackageNotFoundError:
        return "dev"


def _fetch_json(url: str) -> dict:
    """Read a public EDGAR document, respecting SEC's identification rule."""
    try:
        response = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        # Every failure here is "this vendor cannot serve it now", so the router
        # moves on instead of seeing a transport exception it has no rule for.
        raise VendorRateLimitError(f"SEC EDGAR request failed ({status or type(exc).__name__})") from exc
    except ValueError as exc:
        raise VendorRateLimitError("SEC EDGAR returned an unreadable response") from exc


def _cached_json(url: str, name: str) -> dict:
    path = Path(get_config()["data_cache_dir"]) / "sec_edgar" / name
    if path.exists() and time.time() - path.stat().st_mtime < _CACHE_TTL_SECONDS:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass  # a truncated file is a miss, not a failure
    data = _fetch_json(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temp, path)
    return data


def cik_for(ticker: str) -> str | None:
    """The filer's CIK, or None when the ticker is not a US filer."""
    table = _cached_json(_TICKERS_URL, "company_tickers.json")
    wanted = ticker.strip().upper()
    for entry in table.values():
        if entry.get("ticker", "").upper() == wanted:
            return f"{int(entry['cik_str']):010d}"
    return None


def _as_of(facts: dict, tags: tuple[str, ...], curr_date: str, span: tuple[int, int]) -> tuple[dict, str]:
    """({period end: value}, unit) for the first tag the filer reports, as known then.

    A period reported more than once takes its latest filing on or before the
    date, so an amendment counts from the day it was filed and not before. The
    unit comes from the filing: most lines are USD, earnings per share are
    USD/shares, and scaling those alike would print a real figure as zero.
    """
    low, high = span
    values: dict[str, float] = {}
    chosen_unit = "USD"
    # Tags are tried in order and a period keeps the first one that reports it:
    # filers renamed lines over the years, so one tag covers only part of the
    # history. Values are never added across tags, which would double count.
    for tag in tags:
        for unit, unit_values in ((facts.get(tag) or {}).get("units", {})).items():
            latest: dict[str, dict] = {}
            for fact in unit_values:
                if fact["filed"] > curr_date or fact["end"] in values:
                    continue
                # A duration fact (revenue, cash flow) must cover the span asked
                # for. An instant fact (a balance) has no span and serves both.
                if "start" in fact:
                    days = (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
                    if not low <= days <= high:
                        continue
                seen = latest.get(fact["end"])
                if seen is None or fact["filed"] >= seen["filed"]:
                    latest[fact["end"]] = fact
            if latest:
                chosen_unit = unit
                values.update({end: fact["val"] for end, fact in latest.items()})
    return dict(sorted(values.items())), chosen_unit


def _filed_as_of(
    facts: dict, tags: tuple[str, ...], curr_date: str, span: tuple[int, int]
) -> tuple[dict[str, tuple[float, str, str]], str]:
    """Structured variant of :func:`_as_of` that keeps the *filing* date.

    Returns ``({period_end: (value, filed_date, accession)}, unit)`` for the
    first tag that reports each period as known on or before ``curr_date``. The
    filed date (not the fiscal period end) is when the figure became public, so
    a point-in-time consumer can prove availability. Accession numbers are
    included when the filing carries one; an absent accession is left blank
    rather than invented. Values/units follow the same first-tag-wins rule as
    :func:`_as_of` (no summing across tags).
    """
    low, high = span
    values: dict[str, tuple[float, str, str]] = {}
    chosen_unit = "USD"
    for tag in tags:
        for unit, unit_values in ((facts.get(tag) or {}).get("units", {})).items():
            latest: dict[str, dict] = {}
            for fact in unit_values:
                if fact["filed"] > curr_date or fact["end"] in values:
                    continue
                if "start" in fact:
                    days = (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
                    if not low <= days <= high:
                        continue
                seen = latest.get(fact["end"])
                if seen is None or fact["filed"] >= seen["filed"]:
                    latest[fact["end"]] = fact
            if latest:
                chosen_unit = unit
                values.update({
                    end: (
                        fact["val"],
                        str(fact.get("filed", "")),
                        str(fact.get("accn", "") or ""),
                    )
                    for end, fact in latest.items()
                })
    return dict(sorted(values.items())), chosen_unit


# Metric name mapping for structured capture (label -> stable metric id). Only
# metrics with a stable identifier are captured; unknown labels are skipped.
_STATEMENT_METRICS: dict[str, dict[str, str]] = {
    "balance_sheet": {
        "Total Assets": "total_assets",
        "Total Liabilities": "total_liabilities",
        "Stockholders Equity": "stockholders_equity",
    },
    "income_statement": {
        "Revenue": "revenue",
        "Net Income": "net_income",
    },
    "cashflow": {
        "Operating Cash Flow": "operating_cash_flow",
    },
}


def structured_statement_facts(
    kind: str,
    ticker: str,
    freq: str,
    curr_date: str | None,
) -> dict:
    """Every capturable statement fact, as known on or before ``curr_date``.

    Typed accessor used by the evidence capture layer. It reads the same cached
    EDGAR facts :func:`_statement` reads (no extra network beyond the shared
    cache) and returns, per metric id, the period rows with their **filed**
    date preserved::

        {"balance_sheet": {"total_assets":
            [{"period_end": "2025-03-31", "filed": "2025-05-02",
              "value": 391..., "unit": "USD", "accn": "..."}, ...], ...}}

    Raises ``NoMarketDataError`` exactly like :func:`_statement` when the symbol
    is not a US filer or has no ``us-gaap`` facts.
    """
    resolved_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    cik = cik_for(ticker)
    if cik is None:
        raise NoMarketDataError(ticker, ticker, "not a US SEC filer")
    facts = _cached_json(_FACTS_URL.format(cik=cik), f"CIK{cik}.json")
    us_gaap = (facts.get("facts") or {}).get("us-gaap")
    if not us_gaap:
        raise NoMarketDataError(ticker, ticker, "US filer with no us-gaap facts")

    span = _SPANS["quarterly" if freq.lower() == "quarterly" else "annual"]
    metric_map = _STATEMENT_METRICS.get(kind, {})
    out: dict[str, list[dict]] = {}
    for label, tags in _STATEMENTS[kind]:
        metric_id = metric_map.get(label)
        if metric_id is None:
            continue
        values, unit = _filed_as_of(us_gaap, tags, resolved_date, span)
        if not values:
            continue
        out[metric_id] = [
            {
                "period_end": end,
                "filed": filed,
                "value": value,
                "unit": unit,
                "accn": accn,
            }
            for end, (value, filed, accn) in values.items()
        ]
    return {kind: out}


def _statement(kind: str, ticker: str, freq: str, curr_date: str, title: str) -> str:
    curr_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    cik = cik_for(ticker)
    if cik is None:
        raise NoMarketDataError(ticker, ticker, "not a US SEC filer")

    facts = _cached_json(_FACTS_URL.format(cik=cik), f"CIK{cik}.json")
    us_gaap = (facts.get("facts") or {}).get("us-gaap")
    if not us_gaap:
        raise NoMarketDataError(ticker, ticker, "US filer with no us-gaap facts")

    span = _SPANS["quarterly" if freq.lower() == "quarterly" else "annual"]
    lines = {label: _as_of(us_gaap, tags, curr_date, span) for label, tags in _STATEMENTS[kind]}
    periods = sorted({end for values, _ in lines.values() for end in values})
    if not periods:
        raise NoMarketDataError(ticker, ticker, f"no {freq} {title.lower()} filed by {curr_date}")

    header = (
        f"# {title} for {ticker.upper()} ({freq}), USD in millions unless the row says otherwise\n"
        f"# SEC EDGAR facts filed on or before {curr_date}, at the values filed then\n\n"
    )
    rows = [",".join([""] + periods)]
    for label, (values, unit) in lines.items():
        # Every row spans the same columns, or a reader lines the table up wrong.
        if not values:
            rows.append(",".join([label] + ["unavailable (not tagged by this filer)"] * len(periods)))
            continue
        name = label if unit == "USD" else f"{label} ({unit})"
        # Plain numbers: a thousands separator would split the CSV field.
        cells = [
            (f"{values[p] / 1e6:.0f}" if unit == "USD" else f"{values[p]:.2f}")
            if p in values else "" for p in periods
        ]
        rows.append(",".join([name] + cells))
    return header + "\n".join(rows) + "\n"


def _capture_statement(kind: str, ticker: str, freq: str, curr_date: str | None, tool: str) -> None:
    """Best-effort typed capture of this statement's facts (filed date kept).

    Wrapped so capture never changes the public prose return: a capture failure
    is swallowed (the caller still receives the statement string). No-op outside
    an active run.
    """
    try:
        from .evidence_capture import capture_sec_statement_facts

        facts = structured_statement_facts(kind, ticker, freq, curr_date)
        capture_sec_statement_facts(ticker, facts, freq=freq, tool=tool)
    except Exception:  # noqa: BLE001 — capture must not break the public tool
        pass


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    """Balance sheet as filed on or before ``curr_date``."""
    result = _statement("balance_sheet", ticker, freq, curr_date, "Balance Sheet")
    _capture_statement("balance_sheet", ticker, freq, curr_date, "get_balance_sheet")
    return result


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    """Income statement as filed on or before ``curr_date``.

    A fourth quarter is never derived: filers report it only inside the annual
    figure, and subtracting three separately filed quarters would invent a number
    with no filing date behind it.
    """
    result = _statement("income_statement", ticker, freq, curr_date, "Income Statement")
    _capture_statement("income_statement", ticker, freq, curr_date, "get_income_statement")
    return result


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    """Cash flow statement as filed on or before ``curr_date``."""
    result = _statement("cashflow", ticker, freq, curr_date, "Cash Flow Statement")
    _capture_statement("cashflow", ticker, freq, curr_date, "get_cashflow")
    return result
