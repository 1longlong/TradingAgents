#!/usr/bin/env python3
"""Verify the 16 V2 registrations match the frozen protocol's arm table.

``C3_PROTOCOL_FREEZE.md`` restates the design so an operator reads one page
before spending money. A restatement that has drifted from the registrations is
worse than no restatement, so this script checks it mechanically instead of
trusting the prose.

It reads the arm table straight out of ``CAND01_BATCH_2X2_PROTOCOL_V2.md``, so
the protocol — not this script — remains the authority.

Usage::

    TZ=UTC PYTHONSAFEPATH=1 PYTHONPATH=<root> python scripts/c3_verify_protocol_freeze.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
PROTOCOL = BATCH_DIR / "CAND01_BATCH_2X2_PROTOCOL_V2.md"
ORDER_FILE = BATCH_DIR / "EXECUTION_ORDER.txt"

TRADE_DATE = "2026-09-23"
STOCKS = ("NVDA", "AAPL", "JPM", "XOM")

_ROW = re.compile(
    r"^\|\s*`(?P<arm>B|AB|C0|CC)`\s*\|"
    r"\s*(?P<batch>true|false)\s*\|"
    r"\s*(?P<single>true|false)\s*\|"
    r"\s*(?P<structured>true|false)\s*\|"
    r"\s*(?P<s2>true|false)\s*\|",
    re.MULTILINE,
)


def protocol_arm_table() -> dict[str, dict[str, bool]]:
    """Parse the frozen arm table from the protocol document."""
    text = PROTOCOL.read_text(encoding="utf-8")
    table = {}
    for m in _ROW.finditer(text):
        table[m["arm"]] = {
            "batch_macro": m["batch"] == "true",
            "single_pass": m["single"] == "true",
            "structured": m["structured"] == "true",
            "s2_downstream": m["s2"] == "true",
        }
    if set(table) != {"B", "AB", "C0", "CC"}:
        raise SystemExit(f"FAIL protocol: parsed arm table {sorted(table)}")
    return table


def arm_of(switches: dict[str, bool]) -> str:
    """The arm a switch set names, by its two varying factors."""
    for arm, expected in protocol_arm_table().items():
        if all(switches.get(k) is v for k, v in expected.items()):
            return arm
    raise SystemExit(f"FAIL switches {switches} match no arm in the protocol")


def main() -> int:
    table = protocol_arm_table()
    order = ORDER_FILE.read_text(encoding="utf-8")
    failures: list[str] = []
    seen: dict[str, int] = {}

    for spec_dir in sorted((BATCH_DIR / "specs").iterdir()):
        if not spec_dir.is_dir():
            continue
        run_id = spec_dir.name.split("_", 1)[0]
        seen[run_id] = seen.get(run_id, 0) + 1
        reg = json.loads((spec_dir / "experiment.json").read_text(encoding="utf-8"))
        spec = json.loads((spec_dir / "spec.json").read_text(encoding="utf-8"))
        case = reg["cases"][0]
        label = spec_dir.name.split("_")[2] if len(spec_dir.name.split("_")) > 2 else "?"

        # The switches must equal the protocol row for the arm the directory names.
        expected = table.get(label)
        if expected is None:
            failures.append(f"{spec_dir.name}: directory names unknown arm {label!r}")
            continue
        if reg.get("switches") != expected:
            failures.append(
                f"{spec_dir.name}: switches {reg.get('switches')} != protocol row "
                f"for arm {label}: {expected}")
        if spec.get("switches") != expected:
            failures.append(f"{spec_dir.name}: spec.json switches disagree with registration")

        # The design constants hold everywhere.
        for name in ("structured", "s2_downstream"):
            if reg["switches"].get(name) is not True:
                failures.append(f"{spec_dir.name}: {name} must be true in every arm")

        # One trade date, four stocks, each arm once per stock.
        if case["trade_date"] != TRADE_DATE:
            failures.append(f"{spec_dir.name}: trade_date {case['trade_date']} != {TRADE_DATE}")
        if case["ticker"] != spec_dir.name.split("_")[1]:
            failures.append(f"{spec_dir.name}: ticker {case['ticker']} disagrees with directory")

        # The declared arm must be where the pre-registered order puts it.
        line = next((line for line in order.splitlines() if line.startswith(f"{case['ticker']}:")), "")
        block = re.findall(r"'([A-Z0-9]+)'", line)
        if block and label not in block:
            failures.append(f"{spec_dir.name}: arm {label} not in the order for {case['ticker']}")

    dupes = [r for r, n in seen.items() if n > 1]
    if dupes:
        failures.append(f"duplicate run IDs: {dupes}")
    if len(seen) != 16:
        failures.append(f"expected 16 run IDs, found {len(seen)}")

    # Every arm × stock pair appears exactly once.
    pairs = dict.fromkeys(table, 0)
    for spec_dir in sorted((BATCH_DIR / "specs").iterdir()):
        if not spec_dir.is_dir():
            continue
        reg = json.loads((spec_dir / "experiment.json").read_text(encoding="utf-8"))
        pairs[arm_of(reg["switches"])] += 1
    if any(n != len(STOCKS) for n in pairs.values()):
        failures.append(f"arm coverage is not {len(STOCKS)} each: {pairs}")

    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        print(f"\nPROTOCOL FREEZE VERIFICATION FAILED — {len(failures)} problem(s)")
        return 1

    print("ok    arm table: parsed 4 rows from the protocol (the authority)")
    print("ok    16 registrations: switches match their arm's protocol row")
    print("ok    constants: structured=true and s2_downstream=true in all 16")
    print(f"ok    trade date: {TRADE_DATE} in all 16")
    print(f"ok    coverage: {len(STOCKS)} arms x {len(STOCKS)} stocks = 16, each arm once per stock")
    print("ok    order: every arm appears in its stock's pre-registered block")
    print("\nPROTOCOL FREEZE VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
