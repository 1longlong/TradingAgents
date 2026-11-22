"""Quantify: (a) how many network calls a get_news window costs,
(b) the exact text get_global_news gives the analyst, (c) the
`could not answer` vs CONFIG_DISABLED wording collision.
"""
import json
import os
import sys

REPO = "/tmp/opencode/planC2_wt"
sys.path.insert(0, REPO)
os.environ.setdefault("FINNHUB_API_KEY", "dummy")

import tradingagents.dataflows.finnhub_news as fn
from tradingagents.dataflows.news_status import NewsStatus, render_status, _STATUS_TEXT

assert fn.__file__.startswith(REPO), fn.__file__

print("=== A. Finnhub request count per get_news window ===")
print("  _MAX_CHUNKS =", fn._MAX_CHUNKS, " _MAX_ATTEMPTS =", fn._MAX_ATTEMPTS,
      " _MAX_RECORDS_PER_CALL =", fn._MAX_RECORDS_PER_CALL)
from datetime import datetime
for days in (1, 7, 16, 30):
    start = datetime(2026, 9, 1)
    end = datetime(2026, 9, days)
    chunks = fn._day_chunks(start, end)
    print(f"  window {days:2d} days -> {len(chunks):2d} chunk(s) "
          f"=> {len(chunks)} HTTP requests (x2 on 429/500 retry = {len(chunks)*2} max)")

calls = []
fn._request = lambda url: (calls.append(url), (200, "[]", ""))[1]
out = fn.get_news_finnhub_only("NVDA", "2026-09-16", "2026-09-23")
print(f"  measured: 8-day window issued {len(calls)} sequential, SERIAL HTTP requests")

print("\n=== B. exact text the analyst receives from get_global_news ===")
from tradingagents.agents.utils.news_data_tools import get_global_news
txt = get_global_news.invoke({"curr_date": "2026-09-30"})
print("  " + txt)
print("\n  contains 'could not answer' :", "could not answer" in txt)
print("  contains 'DATA_UNAVAILABLE' :", "DATA_UNAVAILABLE" in txt)
print("  contains 'disabled'         :", "disabled" in txt.lower())

print("\n=== C. wording collision across statuses (render_status) ===")
for st in (NewsStatus.CONFIG_DISABLED, NewsStatus.PROVIDER_UNAVAILABLE,
           NewsStatus.AUTH_MISSING, NewsStatus.HTTP_ERROR):
    line = render_status(st, vendor="Finnhub", subject="global market news",
                         start_date="2026-09-30", end_date="2026-09-30")
    print(f"  {st.value:20s} sentence: "
          f"{line.split(' — ')[0].split(': ',1)[1][:60]!r} ...")
print("  => ALL non-EMPTY_VALID classes share the identical 'could not answer' "
      "sentence; only the NEWS_STATUS token and parenthetical differ.")

print("\n=== D. does /home checkout differ from the worktree? ===")
import pathlib
main = pathlib.Path("/home/sky/cs5351/TradingAgents/tradingagents/default_config.py")
wt = pathlib.Path(REPO) / "tradingagents/default_config.py"
print("  worktree tool_vendors :",
      [l.strip() for l in wt.read_text().splitlines() if '"get_news"' in l or '"get_global_news"' in l])
print("  main     tool_vendors :",
      [l.strip() for l in main.read_text().splitlines() if '"get_news"' in l or '"get_global_news"' in l])
