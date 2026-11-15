"""Runtime proof #2 — exact mission protocol, WITH an explicit import-path guard.

Why the guard: the worktree's shared .venv contains
  .venv/lib/python3.14/site-packages/__editable__.tradingagents-0.5.0.pth
  -> __editable___tradingagents_0_5_0_finder.py
     MAPPING = {'tradingagents': '/home/sky/cs5351/TradingAgents/tradingagents', ...}
so `tradingagents` resolves to the *main checkout*, not the worktree. We
therefore prepend the worktree to sys.path and assert every module came from
/tmp/opencode/planC2_wt before trusting any result.

Network is tripwired (urllib.request.urlopen raises + records).
"""
import json
import os
import sys
import urllib.request

REPO = "/tmp/opencode/planC2_wt"
sys.path.insert(0, REPO)
os.chdir(REPO)

GDELT_CALLS = []
NETWORK = []


def _deny_network(*a, **k):
    NETWORK.append(("urlopen", a[:1]))
    raise AssertionError(f"unexpected network call: {a[:1]}")


urllib.request.urlopen = _deny_network

import tradingagents
import tradingagents.dataflows.gdelt_news as gn
import tradingagents.dataflows.finnhub_news as fn
import tradingagents.dataflows.news_merge as nm
from tradingagents.dataflows import interface
import tradingagents.default_config as dc
from tradingagents.agents.utils import news_data_tools as ndt

MODS = [("tradingagents", tradingagents), ("gdelt_news", gn), ("finnhub_news", fn),
        ("news_merge", nm), ("interface", interface), ("default_config", dc),
        ("news_data_tools", ndt)]
print("=== import provenance ===")
bad = []
for label, mod in MODS:
    ok = mod.__file__ and mod.__file__.startswith(REPO)
    bad.append(label) if not ok else None
    print(f"  [{'ok ' if ok else 'BAD'}] {label:15s} -> {mod.__file__}")
if bad:
    print("FATAL: imports resolved outside the worktree:", bad)
    sys.exit(2)

from tradingagents.agents.utils.news_data_tools import get_news, get_global_news

_ORIG = {
    "gn_news": gn.get_news_gdelt,
    "gn_global": gn.get_global_news_gdelt,
    "vm_news": interface.VENDOR_METHODS["get_news"]["gdelt"],
    "vm_global": interface.VENDOR_METHODS["get_global_news"]["gdelt"],
    "fn_fetch": fn.get_news_finnhub,
    "fn_request": fn._request,
    "urlopen": _deny_network,
}


def _boom(name):
    def _inner(*a, **k):
        GDELT_CALLS.append((name, a, k))
        raise AssertionError(f"GDELT CALLED: {name}")
    return _inner


def _finnhub_down(*a, **k):
    raise RuntimeError("simulated Finnhub outage")


def _finnhub_http(url):
    if "finnhub.io" in url:
        return 200, PAYLOAD, ""
    raise AssertionError(f"non-Finnhub URL requested: {url}")


PAYLOAD = json.dumps([
    {"datetime": 1790006400, "headline": "Nvidia beats quarterly revenue estimates",
     "summary": "Nvidia reported results above estimates.", "source": "Reuters",
     "url": "https://finnhub.io/api/news?id=aaa", "related": "NVDA"},
])

print("\n=== config (shipped defaults + runtime) ===")
print("  DEFAULT_CONFIG['tool_vendors']   :", dc.DEFAULT_CONFIG["tool_vendors"])
print("  DEFAULT_CONFIG['data_vendors']   :", dc.DEFAULT_CONFIG["data_vendors"])
print("  get_config()['tool_vendors']     :", interface.get_config()["tool_vendors"])
print("  VENDOR_METHODS['get_news']        :",
      {k: getattr(v, "__name__", repr(v)) for k, v in interface.VENDOR_METHODS["get_news"].items()})
print("  VENDOR_METHODS['get_global_news'] :",
      {k: getattr(v, "__name__", repr(v)) for k, v in interface.VENDOR_METHODS["get_global_news"].items()})

results = []


def check(label, cond, detail=""):
    results.append((label, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


def tripwires():
    gn.get_news_gdelt = _boom("gdelt_news.get_news_gdelt")
    gn.get_global_news_gdelt = _boom("gdelt_news.get_global_news_gdelt")
    interface.VENDOR_METHODS["get_news"]["gdelt"] = _boom("VENDOR_METHODS[get_news][gdelt]")
    interface.VENDOR_METHODS["get_global_news"]["gdelt"] = _boom("VENDOR_METHODS[get_global_news][gdelt]")


def restore():
    gn.get_news_gdelt = _ORIG["gn_news"]
    gn.get_global_news_gdelt = _ORIG["gn_global"]
    interface.VENDOR_METHODS["get_news"]["gdelt"] = _ORIG["vm_news"]
    interface.VENDOR_METHODS["get_global_news"]["gdelt"] = _ORIG["vm_global"]
    fn.get_news_finnhub = _ORIG["fn_fetch"]
    fn._request = _ORIG["fn_request"]


tripwires()

print("\n=== A. get_news, Finnhub answers (finnhub_news._request patched) ===")
n0 = len(GDELT_CALLS)
fn._request = _finnhub_http
outA = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
print("\n".join("  | " + l for l in outA.splitlines()[:12]))
check("article content reached the analyst", "Nvidia beats quarterly" in outA)
check("GDELT call count == 0", len(GDELT_CALLS) == n0, f"calls={GDELT_CALLS[n0:]}")
check("provenance header does not mention GDELT", "GDELT" not in outA.upper())
check("single-provider provenance form", "(Finnhub company news, publish time verified" in outA)

print("\n=== B. get_news with trade_date (as_of_cutoff injection) ===")
n0 = len(GDELT_CALLS)
urls = []
fn._request = lambda url: (urls.append(url), _finnhub_http(url))[1]
outB = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18",
                        "end_date": "2026-09-23", "trade_date": "2026-09-21"})
print("  urls:", [u.split("&token")[0] for u in urls])
check("GDELT call count == 0", len(GDELT_CALLS) == n0, f"{GDELT_CALLS[n0:]}")
check("window clamped to trade_date", "from 2026-09-18 to 2026-09-21" in outB)
check("no requests for days after trade_date", all("to=2026-09-2" in u for u in urls) and
      not any("2026-09-22" in u or "2026-09-23" in u for u in urls))

print("\n=== C. Finnhub raises -> must NOT fall back to GDELT ===")
n0 = len(GDELT_CALLS)
fn.get_news_finnhub = _finnhub_down
outC = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
print("\n".join("  | " + l for l in outC.splitlines()[:5]))
check("GDELT call count == 0 (NO fallback)", len(GDELT_CALLS) == n0, f"{GDELT_CALLS[n0:]}")
check("rendered as DATA_UNAVAILABLE", "DATA_UNAVAILABLE" in outC)
check("not a confirmed absence", "confirmed absence" in outC)
check("does not mention GDELT", "GDELT" not in outC.upper())
fn.get_news_finnhub = _ORIG["fn_fetch"]

print("\n=== D. FINNHUB_API_KEY missing (real code path) ===")
n0 = len(GDELT_CALLS)
fn._request = _ORIG["fn_request"]
saved = os.environ.pop("FINNHUB_API_KEY", None)
try:
    outD = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
finally:
    if saved is not None:
        os.environ["FINNHUB_API_KEY"] = saved
print("\n".join("  | " + l for l in outD.splitlines()[:4]))
check("AUTH_MISSING surfaced", "AUTH_MISSING" in outD)
check("GDELT call count == 0", len(GDELT_CALLS) == n0, f"{GDELT_CALLS[n0:]}")
check("no network attempted", NETWORK == [], f"{NETWORK}")

print("\n=== E. get_global_news (real analyst-facing tool) ===")
n0 = len(GDELT_CALLS)
NETWORK.clear()
outE = get_global_news.invoke({"curr_date": "2026-09-30", "look_back_days": 7, "limit": 10})
print("\n".join("  | " + l for l in outE.splitlines()))
outE2 = get_global_news.invoke({"curr_date": "2026-09-30", "trade_date": "2026-09-30"})
print("  | (with trade_date) " + (outE2.splitlines()[0] if outE2 else "<empty>"))
check("CONFIG_DISABLED returned", "NEWS_STATUS=CONFIG_DISABLED" in outE)
check("GDELT call count == 0", len(GDELT_CALLS) == n0, f"{GDELT_CALLS[n0:]}")
check("no network attempted", NETWORK == [], f"{NETWORK}")
check("not disguised as 'no news'", "genuine absence" not in outE and "no news was published" not in outE)
check("not disguised as an outage", "DATA_UNAVAILABLE" not in outE and "could not answer" not in outE)
check("states real reason", "no global/macro endpoint" in outE)

print("\n=== F. provenance header honesty (news_merge) ===")
from tradingagents.dataflows.news_merge import ProviderOutcome, merge_news_sections
from tradingagents.dataflows.news_status import NewsStatus
ART = ("### X beats (source: R)\n**Published:** 2026-09-21T16:00:00+00:00\n"
       "Link: https://e.test/1")
single = merge_news_sections(
    [ProviderOutcome("Finnhub", ART, status=NewsStatus.SUCCESS_REAL_CONTENT)],
    ticker="NVDA", start_date="2026-09-18", end_date="2026-09-23")
print("  header:", single.splitlines()[0])
check("single-provider header names only Finnhub",
      single.splitlines()[0].endswith("(Finnhub company news, publish time verified per article)."))
check("single-provider header has no GDELT", "GDELT" not in single.upper())
single_fail = merge_news_sections(
    [ProviderOutcome("Finnhub", "", status=NewsStatus.RATE_LIMITED)],
    ticker="NVDA", start_date="2026-09-18", end_date="2026-09-23")
check("single-provider failure says 'the configured provider'",
      "the configured provider" in single_fail and "any provider" not in single_fail)

print("\n=== G. legacy providers ===")
vals = list(interface.VENDOR_METHODS["get_news"].values()) + list(
    interface.VENDOR_METHODS["get_global_news"].values())
check("get_news_combined NOT in routing table", fn.get_news_combined not in vals)
import tradingagents.dataflows.alpha_vantage_news as avn
check("alpha_vantage_news exposes no news function",
      not any("news" in n.lower() for n in dir(avn) if not n.startswith("_")),
      str([n for n in dir(avn) if not n.startswith("_")]))
import tradingagents.dataflows.y_finance as yf_mod
check("y_finance exposes no news function",
      not any("news" in n.lower() for n in dir(yf_mod) if not n.startswith("_")))

print("\n=== H. tripwire liveness sanity (explicit gdelt config MUST fire) ===")
from tradingagents.dataflows.config import set_config
n0 = len(GDELT_CALLS)
set_config({"tool_vendors": {"get_news": "gdelt"}})
try:
    get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-18", "end_date": "2026-09-23"})
except AssertionError:
    pass
check("tripwire fires when gdelt IS configured", len(GDELT_CALLS) > n0, f"{GDELT_CALLS[n0:]}")
set_config({"tool_vendors": {"get_news": "finnhub"}})

restore()
print("\n================ SUMMARY ================")
failed = [r for r in results if not r[1]]
for label, ok, detail in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {label} {detail}")
print(f"\n  {len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
