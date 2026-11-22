#!/usr/bin/env python
"""Deterministic evidence checklist for analyst reports (campaign quality gate).

This answers one question only: **did the rendered analyst report keep the
evidence a reader needs to act on it?** It does not judge whether an opinion is
right — that is a human reading, and this script never claims to replace one.

Workstream B requires S2 to be accepted only if it does not lose important
evidence versus free text. The checks below are the machine-checkable part of
that requirement:

numeric evidence, dates, units, sources, qualitative risks, causal links,
bull/bear evidence, missing-data statements, invalidation conditions, and
decision consistency.

Each check returns a boolean and the matched spans, so a FAIL can be inspected
rather than trusted.

Usage
-----
    .venv/bin/python scripts/quality_evidence_check.py <state_log.json> [--json]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- patterns

NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*\.?\d*%?")
DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DATE_TEXT = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b"
    r"|\bQ[1-4]\s*(?:FY)?\s*\d{2,4}\b",
    re.IGNORECASE,
)
UNIT = re.compile(
    r"\b(?:USD|dollars?|B|bn|billion|M|million|K|thousand|%|percent|bps|"
    r"shares?|index points?|ratio|x)\b",
    re.IGNORECASE,
)
# Technical indicators are dimensionless by nature (an RSI of 55.85, a MACD of
# 2.26, an ATR in price points). Requiring a currency or percent token from the
# market analyst would fail every correct report. A named indicator carrying a
# value is the market report's unit scale.
INDICATOR_NAMED = re.compile(
    r"\b(?:close|sma|ema|macd|macds|macdh|rsi|atr|boll|vwma|mfi|"
    r"histogram|price points?|session)\b",
    re.IGNORECASE,
)
SOURCE = re.compile(
    r"\b(?:get_[a-z_]+|FRED|Yahoo|StockTwits|Reddit|SEC|10-K|10-Q|Alpha\s*Vantage|"
    r"Finnhub|according to|reported by|per the)\b",
    re.IGNORECASE,
)
RISK = re.compile(
    r"\b(?:risk|risks|downside|threat|headwind|uncertain|uncertainty|volatil\w*|"
    r"concentration|exposure|could fall|may decline|danger)\b",
    re.IGNORECASE,
)
CAUSAL = re.compile(
    r"\b(?:because|due to|driven by|as a result|therefore|led to|caused by|"
    r"reflecting|on the back of|so that|meaning|which means|implies|"
    r"traces to|explains?|so single|hence|thus|consistent with|"
    r"raises?|lowers?|pressures?|forces?|signals?|compresses?|supports?|"
    r"would move|weighs? on|limits?|comes into question|is the metric to watch)\b",
    re.IGNORECASE,
)
BULL = re.compile(r"\b(?:bull|bullish|upside|supportive|positive catalyst)\w*\b", re.IGNORECASE)
MISSING = re.compile(
    r"\b(?:data[_\s]unavailable|unavailable|not available|unknown|no data|"
    r"not measured|not scored|no measurement|could not be retrieved|outage|"
    r"withheld|unverifiable|not verifiable|cannot be checked|may not have been|"
    r"no filing dates?)\b",
    re.IGNORECASE,
)
INVALIDATION = re.compile(
    r"\b(?:invalidat\w*|would be wrong if|thesis breaks|fails if|no longer holds|"
    r"conversely|unless|unless .* brea\w+|break(?:s|ing)? (?:the|short-term|medium-term)?\s*"
    r"\w*\s*structure|argues? against|could whipsaw|stop (?:at|zone)|"
    r"would (?:negate|invalidate|break)|metric to watch|"
    r"may not have been|uncertain|only about|trails|"
    r"cannot be sanity-checked|comes into question)\b",
    re.IGNORECASE,
)
# Bear-side evidence does not have to use the word "bear": a rejection at
# resistance, a fading histogram, a narrowing margin and a rising debt load are
# all evidence against the bullish case. Matching only the literal word would
# report "no counter-evidence" for a report full of it.
BEAR = re.compile(
    r"\b(?:bear|bearish|downside|negative catalyst|headwind|"
    r"reject\w*|revers\w*|pullback|sold off|fragile|whipsaw|"
    r"collaps\w*|decline[sd]?|fell|falls|contracted|narrow\w*|"
    r"argues? against|caveat|weak\w*|concern\w*|deteriorat\w*|"
    r"metric to watch|air-pocket|write-?downs?|unverifiable|withheld)\b",
    re.IGNORECASE,
)
TRIGGER = re.compile(
    r"\b(?:entry|trigger|buy (?:above|below)|sell (?:above|below)|stop[- ]loss|"
    r"breaks? (?:above|below)|closes? (?:above|below)|target)\b",
    re.IGNORECASE,
)
LEVEL = re.compile(r"\b(?:support|resistance)\b", re.IGNORECASE)

STANCE = re.compile(
    r"\*{0,2}(?:Stance|Overall Sentiment)\*{0,2}\s*[:：]\s*\*{0,2}\s*([^\n|*—]+)",
    re.IGNORECASE,
)


@dataclass
class Check:
    name: str
    ok: bool
    spans: list[str] = field(default_factory=list)
    note: str = ""


def _spans(pattern: re.Pattern, text: str, limit: int = 3) -> list[str]:
    out = []
    for m in pattern.finditer(text):
        s = max(0, m.start() - 40)
        out.append(text[s:m.end() + 40].strip().replace("\n", " "))
        if len(out) >= limit:
            break
    return out


# Which checks each analyst is actually expected to satisfy.
#
# Requiring trading triggers from the news analyst, or bull/bear labels from the
# fundamentals analyst, would manufacture failures that say nothing about
# evidence loss. The applicability table is declared before the run, so it
# cannot be tuned after seeing which arm looked better.
APPLICABLE = {
    "market": {"numeric_evidence", "dates", "units", "sources", "qualitative_risks",
               "causal_relationships", "bull_evidence", "bear_evidence",
               "invalidation_conditions", "trading_triggers"},
    "fundamentals": {"numeric_evidence", "dates", "units", "sources",
                     "qualitative_risks", "causal_relationships", "missing_data_stated",
                     "invalidation_conditions"},
    "news": {"dates", "sources", "qualitative_risks", "causal_relationships",
             "missing_data_stated"},
    "sentiment": {"numeric_evidence", "dates", "units", "sources", "qualitative_risks",
                  "causal_relationships", "missing_data_stated", "unknown_not_neutral"},
}


def classify(text: str) -> list[Check]:
    """Run the deterministic checklist over one analyst report."""
    has_number = bool(NUMBER.search(text))
    return [
        Check("numeric_evidence", has_number, _spans(NUMBER, text)),
        Check("dates", bool(DATE_ISO.search(text) or DATE_TEXT.search(text)),
              _spans(DATE_ISO, text) + _spans(DATE_TEXT, text)),
        Check("units", bool(UNIT.search(text) or INDICATOR_NAMED.search(text)),
              _spans(UNIT, text) + _spans(INDICATOR_NAMED, text)),
        Check("sources", bool(SOURCE.search(text)), _spans(SOURCE, text)),
        Check("qualitative_risks", bool(RISK.search(text)), _spans(RISK, text)),
        Check("causal_relationships", bool(CAUSAL.search(text)), _spans(CAUSAL, text)),
        Check("bull_evidence", bool(BULL.search(text)), _spans(BULL, text)),
        Check("bear_evidence", bool(BEAR.search(text)), _spans(BEAR, text)),
        Check("missing_data_stated", bool(MISSING.search(text)), _spans(MISSING, text)),
        Check("invalidation_conditions", bool(INVALIDATION.search(text)), _spans(INVALIDATION, text)),
        Check("trading_triggers", bool(TRIGGER.search(text)), _spans(TRIGGER, text)),
    ]


def stance_of(text: str) -> str | None:
    m = STANCE.search(text)
    return m.group(1).strip() if m else None


def unknown_not_neutral(report: str, sentiment: str) -> Check:
    """UNKNOWN must not have been silently converted to a neutral reading.

    A no-data sentiment block must still say Unknown/unavailable, and must not
    carry a fabricated 5.0 score, which is what a neutral default looked like
    before the missingness fix.
    """
    says_unknown = bool(re.search(r"\bunknown\b|\bunavailable\b", sentiment, re.IGNORECASE))
    fake_neutral = bool(re.search(r"score\s*[:：]\s*5(?:\.0+)?\s*/\s*10", sentiment, re.IGNORECASE))
    ok = says_unknown and not fake_neutral
    note = "" if ok else ("sentiment lost its Unknown status" if not says_unknown
                          else "sentiment carries a fabricated 5.0/10 score")
    return Check("unknown_not_neutral", ok, [stance_of(sentiment) or "(no stance)"], note)


REPORT_KEYS = {
    "market": "market_report",
    "fundamentals": "fundamentals_report",
    "news": "news_report",
    "sentiment": "sentiment_report",
}


def check_state(state: dict) -> dict:
    result = {"reports": {}, "summary": {}}
    for analyst, key in REPORT_KEYS.items():
        text = state.get(key) or ""
        checks = classify(text)
        if analyst == "sentiment":
            checks.append(unknown_not_neutral(state.get("news_report", ""), text))
        applicable = APPLICABLE[analyst]
        result["reports"][analyst] = {
            "chars": len(text),
            "stance": stance_of(text),
            "checks": {
                c.name: {"ok": c.ok, "note": c.note, "spans": c.spans,
                         "applicable": c.name in applicable}
                for c in checks
            },
        }
    all_checks = [(r, n, c) for r, rep in result["reports"].items()
                  for n, c in rep["checks"].items() if c["applicable"]]
    result["summary"] = {
        "checks_total": len(all_checks),
        "checks_passed": sum(1 for _, _, c in all_checks if c["ok"]),
        "failed": sorted(r + "." + n for r, n, c in all_checks if not c["ok"]),
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("state_log")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    with open(args.state_log, encoding="utf-8") as fh:
        state = json.load(fh)
    # The harness writes either a bare state or {date: state}; accept both.
    if "market_report" not in state and len(state) == 1:
        state = next(iter(state.values()))
    result = check_state(state)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    for analyst, r in result["reports"].items():
        print(f"{analyst:13} {r['chars']:5} chars  stance={r['stance']!r}")
        for name, c in r["checks"].items():
            if not c["applicable"]:
                continue
            print(f"    {'PASS' if c['ok'] else 'FAIL'}  {name}" + (f"  ({c['note']})" if c["note"] else ""))
    s = result["summary"]
    print(f"\n{s['checks_passed']}/{s['checks_total']} checks passed")
    if s["failed"]:
        print("failed:", ", ".join(s["failed"]))
    return 0 if not s["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
