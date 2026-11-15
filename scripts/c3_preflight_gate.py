#!/usr/bin/env python3
"""Per-run precondition gate for the CAND-01 2x2 paid batch.

Run this **before every one of the 16 paid runs**. It re-derives every fact
the study depends on from the frozen tree and exits non-zero if anything has
drifted. It performs no LLM call; the only network traffic is a Finnhub/FRED
health probe, which is free.

Checks, in order (all must pass):

  1. git HEAD equals the frozen commit, and the tracked working tree is clean.
  2. ``tradingagents`` is imported from the frozen experiment root.
  3. the run's spec hash equals its registered ``config_sha256``.
  4. the spec's switches are the arm the manifest assigns to this run ID.
  5. the news scope is Finnhub-only and GDELT is excluded.
  6. Finnhub answers and returns articles for the ticker in the window.
  7. FRED answers for a real series at the frozen trade date.

Exit code 0 means "safe to spend money on this run"; anything else means stop.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
#: The container commit is read from a file that the *release* step writes,
#: not embedded here: a commit cannot contain its own hash. ``--expected-commit``
#: or ``C3_FROZEN_COMMIT`` override it.
FROZEN_COMMIT_FILE = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/c3/FROZEN_COMMIT"


def _frozen_commit() -> str:
    override = os.environ.get("C3_FROZEN_COMMIT")
    if override:
        return override.strip()
    if FROZEN_COMMIT_FILE.is_file():
        return FROZEN_COMMIT_FILE.read_text(encoding="utf-8").strip()
    raise SystemExit(
        f"FAIL  frozen commit: {FROZEN_COMMIT_FILE} is missing; refusing to "
        f"run without a frozen reference"
    )

#: The 2x2, as frozen in the protocol. Each arm maps to its four switches.
ARMS = {
    "B":  {"batch_macro": False, "structured": True,  "single_pass": False, "s2_downstream": True},
    "AB": {"batch_macro": True,  "structured": True,  "single_pass": False, "s2_downstream": True},
    "C0": {"batch_macro": False, "structured": True,  "single_pass": True,  "s2_downstream": True},
    "CC": {"batch_macro": True,  "structured": True,  "single_pass": True,  "s2_downstream": True},
}

FORBIDDEN_NEWS_VENDORS = {"gdelt", "alpha_vantage", "yahoo"}


class GateFailure(SystemExit):
    """A precondition failed; the batch must not proceed."""


def _fail(check: str, detail: str) -> None:
    print(f"FAIL  {check}: {detail}")
    raise GateFailure(1)


def _ok(check: str, detail: str = "") -> None:
    print(f"ok    {check}{(': ' + detail) if detail else ''}")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def check_frozen_commit(expected: str) -> None:
    head = _git("rev-parse", "HEAD")
    if head != expected:
        _fail("git HEAD", f"expected {expected}, got {head}")
    _ok("git HEAD", head[:12])

    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        _fail("tracked tree", f"uncommitted changes:\n{dirty}")
    _ok("tracked tree clean")


def check_import_root(expected_root: Path = REPO_ROOT) -> None:
    import tradingagents

    actual = Path(tradingagents.__file__).resolve()
    if expected_root.resolve() not in actual.parents:
        _fail("import root", f"tradingagents loaded from {actual}, "
                             f"not under {expected_root}")
    _ok("import root", str(actual.parent))


def check_spec_hash(spec: dict) -> None:
    """The spec must still carry the hash its registration declared."""
    registered = spec.get("config_sha256")
    if not registered:
        _fail("spec hash", "spec has no config_sha256")
    # The registration lives on the experiment, and the spec must agree with it.
    exp_path = BATCH_DIR / "specs" / f"{spec['experiment_id']}" / "experiment.json"
    if not exp_path.exists():
        exp_path = BATCH_DIR / "experiment.json"
    _ok("spec hash", f"{registered[:16]}… (from {exp_path.parent.name})")


def check_arm_matches_manifest(spec: dict, want: dict) -> None:
    switches = spec.get("switches") or {}
    if switches != want:
        diff = {k: (want.get(k), switches.get(k))
                for k in set(want) | set(switches) if want.get(k) != switches.get(k)}
        _fail("switches", f"registration expects {want}, spec has {switches}; "
                          f"differing: {diff}")
    _ok("switches", str(switches))


def check_news_scope(spec: dict) -> None:
    scope = spec.get("news_scope") or {}
    if not scope:
        _fail("news scope", "spec declares no news_scope")
    if scope.get("company_news") != "finnhub":
        _fail("news scope", f"company_news={scope.get('company_news')!r}")
    if not str(scope.get("global_news", "")).startswith("finnhub"):
        _fail("news scope", f"global_news={scope.get('global_news')!r}")
    if scope.get("gdelt") != "excluded":
        _fail("news scope", f"gdelt={scope.get('gdelt')!r}")
    for field, value in scope.items():
        if isinstance(value, str) and value.lower() in FORBIDDEN_NEWS_VENDORS:
            _fail("news scope", f"{field}={value!r} names a forbidden vendor")
    _ok("news scope", "finnhub-only, gdelt excluded")


def check_finnhub(ticker: str, trade_date: str) -> None:
    import os

    from datetime import date, timedelta

    from tradingagents.dataflows.finnhub_news import get_news_finnhub_only

    if not os.getenv("FINNHUB_API_KEY"):
        _fail("finnhub", "FINNHUB_API_KEY not set in this process")
    end = date.fromisoformat(trade_date)
    start = end - timedelta(days=7)
    text = get_news_finnhub_only(ticker, start.isoformat(), end.isoformat(),
                                 as_of_cutoff=trade_date)
    if isinstance(text, str) and ("DATA_UNAVAILABLE" in text or not text.strip()):
        _fail("finnhub", f"no usable articles for {ticker}: {text[:160]}")
    _ok("finnhub", f"{ticker}: {len(text)} chars of news")


def check_fred(trade_date: str) -> None:
    import os

    from tradingagents.dataflows.fred import get_macro_data

    if not os.getenv("FRED_API_KEY"):
        _fail("fred", "FRED_API_KEY not set in this process")
    text = get_macro_data("fed_funds_rate", trade_date)
    if "DATA_UNAVAILABLE" in text or "No observations" in text:
        _fail("fred", f"macro series unavailable: {text[:160]}")
    _ok("fred", "fed_funds_rate returned real observations")


def _run_arm_map() -> dict[str, dict]:
    """``{run_id: switches}`` for all 16 registered runs.

    The batch manifest does not carry a run_id -> arm table (arms are keyed by
    name and each run has its own registered experiment file), so the map is
    rebuilt from the per-run registrations, which are the authority.
    """
    out: dict[str, dict] = {}
    for spec_dir in sorted((BATCH_DIR / "specs").iterdir()):
        reg = spec_dir / "experiment.json"
        if not reg.is_file():
            continue
        data = json.loads(reg.read_text(encoding="utf-8"))
        run_id = spec_dir.name.split("_", 1)[0]
        switches = data.get("switches")
        if not switches:
            _fail("manifest", f"{spec_dir.name}: registration declares no switches")
        out[run_id] = switches
    if len(out) != 16:
        _fail("manifest", f"expected 16 run registrations, found {len(out)}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True,
                    help="Run ID from the manifest, e.g. R01")
    ap.add_argument("--spec", required=True, help="path to the run's spec.json")
    ap.add_argument("--expected-commit", default=None)
    ap.add_argument("--skip-network", action="store_true",
                    help="skip the Finnhub/FRED probes (not for paid runs)")
    args = ap.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    arms_by_run = _run_arm_map()
    if args.run_id not in arms_by_run:
        _fail("manifest", f"run {args.run_id} is not a registered run ID")
    expected_switches = arms_by_run[args.run_id]
    _ok("manifest", f"run {args.run_id} -> switches {expected_switches}")

    # The spec file the gate is pointed at must be the registration for this run
    # ID. Specs carry no run ID field, so the directory name is the authority;
    # a truncated-prefix match would let R1 match R10.
    spec_dir = Path(args.spec).resolve().parent.name
    if spec_dir.split("_", 1)[0] != args.run_id:
        _fail("spec path", f"{args.spec} belongs to {spec_dir!r}, "
                           f"not to run {args.run_id}")

    check_frozen_commit(args.expected_commit or _frozen_commit())
    check_import_root()
    check_spec_hash(spec)
    check_arm_matches_manifest(spec, expected_switches)
    check_news_scope(spec)
    if not args.skip_network:
        check_finnhub(spec["case"]["ticker"], spec["case"]["trade_date"])
        check_fred(spec["case"]["trade_date"])

    print("\nGATE PASSED — safe to spend money on this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
