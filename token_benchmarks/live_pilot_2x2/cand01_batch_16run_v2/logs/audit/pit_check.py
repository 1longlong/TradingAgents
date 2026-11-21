"""PIT honesty checks for the Finnhub company-news path (no network).

Patches ONLY ``finnhub_news._request`` (the transport), so the real timestamp
parsing, window filter, relevance filter, render and merge all execute.
"""
import json
import sys

REPO = "/tmp/opencode/planC2_wt"
sys.path.insert(0, REPO)

import tradingagents.dataflows.finnhub_news as fn
from tradingagents.dataflows import date_window

assert fn.__file__.startswith(REPO), fn.__file__

results = []


def check(label, cond, detail=""):
    results.append((label, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


# 2026-09-21T10:00:00Z, 2026-09-21T23:59:00Z, 2026-09-22T00:30:00Z (post-cutoff)
# 2026-09-22T18:00:00Z (post-cutoff), and one undated row.
ROWS = [
    {"datetime": 1789984800, "headline": "Nvidia morning story", "summary": "s",
     "source": "Reuters", "url": "https://finnhub.io/api/news?id=m", "related": "NVDA"},
    {"datetime": 1790035140, "headline": "Nvidia late-evening story", "summary": "s",
     "source": "CNBC", "url": "https://finnhub.io/api/news?id=n", "related": "NVDA"},
    {"datetime": 1790037000, "headline": "Nvidia next-day small-hours story", "summary": "s",
     "source": "WSJ", "url": "https://finnhub.io/api/news?id=o", "related": "NVDA"},
    {"datetime": 1790100000, "headline": "Nvidia next-day-evening story", "summary": "s",
     "source": "FT", "url": "https://finnhub.io/api/news?id=p", "related": "NVDA"},
    {"headline": "Nvidia undated story", "summary": "s", "source": "Barron's",
     "url": "https://finnhub.io/api/news?id=q", "related": "NVDA"},
]
from datetime import datetime, timezone
for r in ROWS:
    if "datetime" in r:
        print("  row", r["datetime"], "->", datetime.fromtimestamp(r["datetime"], tz=timezone.utc).isoformat(),
              "|", r["headline"])

PAYLOAD = json.dumps(ROWS)
import os
os.environ.setdefault("FINNHUB_API_KEY", "dummy-not-used")
fn._request = lambda url: (200, PAYLOAD, "")

print("\n=== 1. publication_cutoff(trade_date) ===")
for d in ("2026-09-21", "2026-09-30", None, ""):
    print(f"  publication_cutoff({d!r}) = {date_window.publication_cutoff(d)!r}")
check("cutoff is midnight AFTER trade_date",
      date_window.publication_cutoff("2026-09-21") == "2026-09-22T00:00:00Z")
check("no trade_date -> None (vendor end-of-window default)",
      date_window.publication_cutoff(None) is None)

print("\n=== 2. real fetch with as_of_cutoff=2026-09-22T00:00:00Z ===")
out = fn.get_news_finnhub_only("NVDA", "2026-09-21", "2026-09-21",
                               as_of_cutoff="2026-09-22T00:00:00Z")
print("\n".join("  | " + l for l in out.splitlines()[:20]))
check("same-day morning article ADMITTED", "Nvidia morning story" in out)
check("same-day 23:59 article ADMITTED", "Nvidia late-evening story" in out)
check("next-day 00:30 article REJECTED", "next-day small-hours" not in out)
check("next-day evening article REJECTED", "next-day-evening" not in out)
check("undated article REJECTED (cannot prove not-future)", "undated story" not in out)

print("\n=== 3. same fetch WITHOUT as_of_cutoff (end-of-window default) ===")
out2 = fn.get_news_finnhub_only("NVDA", "2026-09-21", "2026-09-21")
admitted = [r["headline"] for r in ROWS if r.get("headline", "") in out2]
print("  admitted:", admitted)
check("without a cutoff, next-day rows are still excluded by [start, end] window",
      "next-day small-hours" not in out2)

print("\n=== 4. real tool path: get_news with trade_date injects the cutoff ===")
from tradingagents.agents.utils.news_data_tools import get_news
out3 = get_news.invoke({"ticker": "NVDA", "start_date": "2026-09-21",
                        "end_date": "2026-09-23", "trade_date": "2026-09-21"})
print("\n".join("  | " + l for l in out3.splitlines()[:8]))
check("tool window clamped to trade_date", "from 2026-09-21 to 2026-09-21" in out3)
check("tool rejects post-trade-date articles", "small-hours" not in out3 and "next-day-evening" not in out3)

print("\n=== 5. inside the SAME day but after the decision is still admitted ===")
# Documented convention: cutoff = midnight after trade_date, so a story filed
# at 23:59 on the trade date is admitted even if the decision was at 10:00.
check("documented: same-day-late article admitted (coarse, day-level PIT)",
      "Nvidia late-evening story" in out3,
      "=> a 23:59 story is visible to a decision dated the same day")

print("\n=== SUMMARY ===")
failed = [r for r in results if not r[1]]
for l, ok, d in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {l} {d}")
print(f"  {len(results)-len(failed)}/{len(results)} passed")
