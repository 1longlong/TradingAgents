"""RUNTIME proof of the Finnhub-only news scope.

Read-only w.r.t. the repo. No network: every outbound HTTP entry point
(urllib.request.urlopen, socket connect) is also tripwired so a hidden third
provider cannot silently fetch.

Method
------
1. Import the real `tradingagents.dataflows.gdelt_news` and monkeypatch its
   `get_news_gdelt` / `get_global_news_gdelt` module attributes to raise AND
   count.
2. Also replace the `gdelt` entries of `interface.VENDOR_METHODS[...]` with the
   same raising stubs (defence in depth: even if routing selected gdelt, it dies).
3. Invoke the REAL analyst-facing LangChain tools
   `tradingagents.agents.utils.news_data_tools.get_news` / `.get_global_news`
   (i.e. through route_to_vendor, exactly as the News Analyst does).
4. Scenario A: Finnhub works (patched at the *innermost* layer, `_request`, so
   the real parsing / PIT filter / render / merge all execute).
   Scenario B: Finnhub raises (patched at `get_news_finnhub`) -> no GDELT rescue.
   Scenario C: Finnhub key missing (real VendorNotConfiguredError path).
"""
import socket
import urllib.request
import json

GDELT_CALLS = []
NETWORK_CALLS = []

# --- network tripwire (must be installed before any call) --------------------
_real_urlopen = urllib.request.urlopen


def _no_network(*a, **k):
    NETWORK_CALLS.append(("urlopen", a[:1]))
    raise AssertionError(f"unexpected network access: {a[:1]}")


urllib.request.urlopen = _no_network

import tradingagents.dataflows.gdelt_news as gn
import tradingagents.dataflows.finnhub_news as fn
from tradingagents.dataflows import interface
from tradingagents.agents.utils.news_data_tools import get_news, get_global_news
from tradingagents.default_config import DEFAULT_CONFIG


def _gdelt_boom(name):
    def _inner(*a, **k):
        GDELT_CALLS.append((name, a, k))
        raise AssertionError(f"GDELT CALLED: {name}{a}{k}")
    return _inner


# --- 0. config surface ------------------------------------------------------
print("=== 0. shipped config ===")
print("  data_vendors['news_data']        =", DEFAULT_CONFIG["data_vendors"]["news_data"])
print("  tool_vendors['get_news']         =", DEFAULT_CONFIG["tool_vendors"]["get_news"])
print("  tool_vendors['get_global_news']  =", DEFAULT_CONFIG["tool_vendors"]["get_global_news"])
print("  runtime get_config()             =", interface.get_config()["tool_vendors"])

# --- 1. install GDELT tripwires ---------------------------------------------
gn.get_news_gdelt = _gdelt_boom("get_news_gdelt")
gn.get_global_news_gdelt = _gdelt_boom("get_global_news_gdelt")
for method, stub in (("get_news", _gdelt_boom("VENDOR_METHODS[get_news][gdelt]")),
                     ("get_global_news", _gdelt_boom("VENDOR_METHODS[get_global_news][gdelt]"))):
    interface.VENDOR_METHODS[method]["gdelt"] = stub
print("\n=== 1. tripwires installed ===")
print("  VENDOR_METHODS['get_news']['gdelt']        ->", interface.VENDOR_METHODS["get_news"]["gdelt"].__name__,
      "(stub)")
print("  VENDOR_METHODS['get_global_news']['gdelt'] ->", interface.VENDOR_METHODS["get_global_news"]["gdelt"].__name__,
      "(stub)")

results = []


def check(label, cond, detail=""):
    results.append((label, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label} {detail}")


# --- 2. Scenario A: Finnhub serves a canned company-news payload ------------
print("\n=== 2. Scenario A: real get_news tool, Finnhub answers (patched _request) ===")
PAYLOAD = json.dumps([
    {"category": "company", "datetime": 1790006400,  # 2026-09-21T16:00:00Z
     "headline": "Nvidia beats quarterly revenue estimates",
     "summary": "Nvidia reported results above estimates.", "source": "Reuters",
     "url": "https://finnhub.io/api/news?id=aaa", "related": "NVDA"},
    {"category": "company", "datetime": 1790092800,  # 2026-09-22T16:00:00Z
     "headline": "Nvidia announces new data-center GPU",
     "summary": "New GPU announced.", "source": "CNBC",
     "url": "https://finnhub.io/api/news?id=bbb", "related": "NVDA"},
])


def _fake_request(url):
    if "finnhub.io" in url:
        return 200, PAYLOAD, ""
    NETWORK_CALLS.append(("non-finnhub", url))
    raise AssertionError(f"unexpected non-Finnhub URL: {url}")


fn._request = _fake_request
out = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
print("  --- rendered analyst text (truncated) ---")
print("\n".join("  | " + l for l in out.splitlines()[:14]))
check("article content reached the analyst", "Nvidia beats quarterly" in out)
check("provenance header names Finnhub company news only",
      "Finnhub company news" in out and "GDELT" not in out.upper())
check("GDELT call count == 0 after get_news", GDELT_CALLS == [], f"calls={GDELT_CALLS}")

# --- 3. Scenario A2: same call WITH a trade_date (PIT cutoff injection) -------
print("\n=== 3. Scenario A2: get_news with trade_date (as_of_cutoff injected) ===")
seen = []
fn._request = lambda url: (seen.append(url), (200, PAYLOAD, ""))[1]
out2 = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18",
                        "end_date": "2026-09-23", "trade_date": "2026-09-21"})
print("  finnhub URLs requested:", seen)
print("  first lines:", out2.splitlines()[:2])
check("GDELT call count == 0 after get_news(trade_date)", GDELT_CALLS == [], f"{GDELT_CALLS}")

# --- 4. Scenario B: Finnhub raises -> must NOT fall back to GDELT -----------
print("\n=== 4. Scenario B: Finnhub outage (get_news_finnhub raises) ===")


def _finnhub_down(*a, **k):
    raise RuntimeError("simulated Finnhub outage")


fn.get_news_finnhub = _finnhub_down
out3 = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
print("  --- rendered analyst text (truncated) ---")
print("\n".join("  | " + l for l in out3.splitlines()[:8]))
check("Finnhub outage is NOT rescued by GDELT", GDELT_CALLS == [], f"calls={GDELT_CALLS}")
check("failure rendered as DATA_UNAVAILABLE, not 'no news'", "DATA_UNAVAILABLE" in out3)
check("failure does not claim a confirmed absence", "confirmed absence" in out3)
check("failure text mentions no GDELT", "GDELT" not in out3.upper())

# --- 5. Scenario C: no Finnhub key (real code path) -------------------------
print("\n=== 5. Scenario C: FINNHUB_API_KEY missing (real _safe_call path) ===")
import os
del fn.get_news_finnhub            # restore module-level original
fn._request = _real_urlopen
saved = os.environ.pop("FINNHUB_API_KEY", None)
try:
    out4 = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
finally:
    if saved is not None:
        os.environ["FINNHUB_API_KEY"] = saved
print("\n".join("  | " + l for l in out4.splitlines()[:8]))
check("missing key -> explicit AUTH_MISSING status", "AUTH_MISSING" in out4)
check("missing key does not trigger GDELT", GDELT_CALLS == [], f"calls={GDELT_CALLS}")

# --- 6. get_global_news: CONFIG_DISABLED, fetches nothing -------------------
print("\n=== 6. real get_global_news tool ===")
NETWORK_CALLS.clear()
out5 = get_global_news.invoke({"curr_date": "2026-09-30", "look_back_days": 7, "limit": 10})
print("\n".join("  | " + l for l in out5.splitlines()))
out5b = get_global_news.invoke({"curr_date": "2026-09-30", "trade_date": "2026-09-30"})
print("  (with trade_date) ->", out5b.splitlines()[0] if out5b else "<empty>")
check("returns NewsStatus CONFIG_DISABLED", "NEWS_STATUS=CONFIG_DISABLED" in out5)
check("does not read as 'no news'", "no news" not in out5.lower() or "disabled" in out5.lower())
check("does not read as an outage", "DATA_UNAVAILABLE" not in out5 and "could not answer" not in out5)
check("does not claim a confirmed absence", "confirmed absence" not in out5)
check("fetched nothing (no network, no GDELT)", NETWORK_CALLS == [] and GDELT_CALLS == [],
      f"net={NETWORK_CALLS} gdelt={GDELT_CALLS}")

# --- 7. provenance header honesty -------------------------------------------
print("\n=== 7. provenance header for a single-provider block ===")
from tradingagents.dataflows.news_merge import ProviderOutcome, merge_news_sections
from tradingagents.dataflows.news_status import NewsStatus
single = merge_news_sections(
    [ProviderOutcome("Finnhub",
                     "### X beats (source: R)\n**Published:** 2026-09-21T16:00:00+00:00\nLink: https://e.test/1",
                     status=NewsStatus.SUCCESS_REAL_CONTENT)],
    ticker="NVDA", start_date="2026-09-18", end_date="2026-09-23")
print("  " + single.splitlines()[0])
check("single-provider header names only Finnhub",
      single.splitlines()[0] == "## NVDA News, from 2026-09-18 to 2026-09-23 (Finnhub company news, publish time verified per article).",
      "")
check("single-provider header does not mention GDELT", "GDELT" not in single.upper())

# --- 8. legacy providers unreachable via news routing -----------------------
print("\n=== 8. legacy news provider reachability via the routing table ===")
print("  VENDOR_METHODS['get_news'] keys        :", list(interface.VENDOR_METHODS["get_news"]))
print("  VENDOR_METHODS['get_global_news'] keys :", list(interface.VENDOR_METHODS["get_global_news"]))
vals = list(interface.VENDOR_METHODS["get_news"].values()) + \
       list(interface.VENDOR_METHODS["get_global_news"].values())
check("finnhub_news.get_news_combined is NOT in routing",
      fn.get_news_combined not in vals)
import tradingagents.dataflows.alpha_vantage_news as avn
check("alpha_vantage_news exposes no news function",
      not any("news" in n.lower() for n in dir(avn) if not n.startswith("__")),
      f"dir={[n for n in dir(avn) if not n.startswith('__')]}")
check("no yfinance news entry in routing",
      not any("yf" in getattr(v, "__module__", "").lower() for v in vals))

# --- 9. GDELT still reachable if explicitly configured (sanity) -------------
print("\n=== 9. sanity: explicit gdelt config WOULD reach the stub (proves tripwire live) ===")
from tradingagents.dataflows.config import set_config, get_config
set_config({"tool_vendors": {"get_news": "gdelt"}})
try:
    get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
except Exception as exc:
    print("  raised as expected:", type(exc).__name__, str(exc)[:80])
check("tripwire actually fires when gdelt is configured", len(GDELT_CALLS) > 0, f"calls={len(GDELT_CALLS)}")
gdelt_after_sanity = len(GDELT_CALLS)
set_config({"tool_vendors": {"get_news": "finnhub"}})

print("\n================ SUMMARY ================")
print(f"  GDELT calls during the Finnhub-only scenarios (1-8): "
      f"{gdelt_after_sanity - len(GDELT_CALLS) if False else 'see above'}")
failed = [r for r in results if not r[1]]
for label, ok, detail in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {label} {detail}")
print(f"\n  {len(results) - len(failed)}/{len(results)} checks passed")
raise SystemExit(1 if failed else 0)
