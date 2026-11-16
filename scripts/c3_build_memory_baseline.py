#!/usr/bin/env python3
"""Build the immutable memory snapshot a V3 experiment starts every run from.

The product keeps a single developer decision log at
``~/.tradingagents/memory/trading_memory.md``. A run appends to it, and the next
run resolves pending entries *before* its graph starts (that reflection is a
provider call). For a controlled experiment every run must therefore start from
the same bytes and write only to its own copy.

This script produces that baseline from a source log, excluding entries that
were created *by* the experiment it is baselining (they are not history; they
are prior treatment). The source log is never modified; the output is a new
file whose provenance is written next to it.

Usage::

    python scripts/c3_build_memory_baseline.py \
        --source ~/.tradingagents/memory/trading_memory.md \
        --out <batch>/memory/baseline_v3.md \
        --exclude AAPL:2026-09-23
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"
_HEADER = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2}) \| (?P<ticker>[A-Z0-9.\-^]+) \|")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_entries(text: str) -> list[dict]:
    entries = []
    for raw in text.split(SEPARATOR):
        body = raw.strip()
        if not body:
            continue
        match = _HEADER.match(body.splitlines()[0])
        entries.append({
            "raw": body,
            "date": match.group("date") if match else None,
            "ticker": match.group("ticker") if match else None,
            "pending": body.splitlines()[0].rstrip().endswith("| pending]"),
        })
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path,
                        default=Path.home() / ".tradingagents/memory/trading_memory.md")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="TICKER:YYYY-MM-DD",
                        help="entry created by the experiment being baselined")
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"REFUSED: source log not found: {args.source}")
        return 2
    source_bytes = args.source.read_bytes()
    source_text = source_bytes.decode("utf-8")
    excluded = set()
    for item in args.exclude:
        ticker, _, date = item.partition(":")
        if not ticker or not date:
            print(f"REFUSED: --exclude must be TICKER:YYYY-MM-DD, got {item!r}")
            return 2
        excluded.add((ticker.strip().upper(), date.strip()))

    entries = parse_entries(source_text)
    kept, dropped = [], []
    for entry in entries:
        key = (entry["ticker"], entry["date"])
        if entry["ticker"] and entry["date"] and key in excluded:
            dropped.append({"ticker": key[0], "date": key[1],
                            "sha256": sha256_bytes(entry["raw"].encode("utf-8"))})
        else:
            kept.append(entry)

    if not kept:
        print("REFUSED: every entry was excluded; a baseline cannot be empty")
        return 2
    if any(entry["pending"] for entry in kept):
        print("REFUSED: the baseline would still contain pending entries; "
              "each would trigger a pre-graph reflection")
        return 2

    out_text = SEPARATOR.join(entry["raw"] for entry in kept) + SEPARATOR
    out_bytes = out_text.encode("utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(out_bytes)

    provenance = {
        "schema": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/c3_build_memory_baseline.py",
        "source": str(args.source),
        "source_sha256": sha256_bytes(source_bytes),
        "source_entries": len(entries),
        "excluded": dropped,
        "baseline": str(args.out),
        "baseline_sha256": sha256_bytes(out_bytes),
        "baseline_entries": len(kept),
        "baseline_pending": 0,
        "kept_entries": [{"ticker": e["ticker"], "date": e["date"]} for e in kept],
    }
    provenance_path = args.out.with_suffix(".provenance.json")
    provenance_path.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"wrote {args.out} ({len(kept)} entries, sha256 {provenance['baseline_sha256']})")
    print(f"wrote {provenance_path}")
    for item in dropped:
        print(f"  excluded {item['ticker']} {item['date']} (experiment-generated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
