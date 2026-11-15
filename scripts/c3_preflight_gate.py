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
import hashlib
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


def check_fingerprint_matches_record(expected: str) -> None:
    """The committed freeze record must describe *this* tree, not an older one.

    ``c3/code_freeze.txt`` cannot name the commit it is committed in (a commit
    cannot contain its own hash), so it records the code fingerprint instead.
    That number is stable across the freeze commit, which makes it the one
    field that can prove the record and the tree agree. Without this check a
    freeze record naming an earlier commit and an earlier tree ran unnoticed
    (audit A-07).
    """
    import json
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import token_benchmark as tb

    record = BATCH_DIR / "c3" / "code_freeze.txt"
    text = record.read_text(encoding="utf-8")
    declared = None
    for line in text.splitlines():
        # Only the machine-readable line counts: "  working_tree_sha256   : <hex>".
        # An earlier looser parse also matched the human label line and read a
        # truncated value, which made every record look stale.
        stripped = line.strip()
        if stripped.startswith("working_tree_sha256") and "=" not in stripped:
            declared = stripped.split(":", 1)[-1].strip()
            break
    if not declared or len(declared) != 64:
        _fail("freeze record",
              f"{record.name} records no usable working_tree_sha256 ({declared!r})")
    experiment = json.loads((BATCH_DIR / "experiment.json").read_text(encoding="utf-8"))
    actual = tb.compute_code_state(BATCH_DIR, experiment).get("working_tree_sha256")
    if actual != declared:
        _fail("freeze record",
              f"code_freeze.txt records {declared[:16]}…, but this tree "
              f"fingerprints to {actual[:16]}…; the record describes a "
              f"different tree")
    if expected[:12] not in text:
        _fail("freeze record",
              f"code_freeze.txt does not mention the frozen commit {expected[:12]}")
    _ok("freeze record", f"{declared[:16]}… matches this tree and names {expected[:12]}")


def check_import_root(expected_root: Path = REPO_ROOT) -> None:
    import tradingagents

    actual = Path(tradingagents.__file__).resolve()
    if expected_root.resolve() not in actual.parents:
        _fail("import root", f"tradingagents loaded from {actual}, "
                             f"not under {expected_root}")
    _ok("import root", str(actual.parent))


#: The fields ``config_sha256`` covers. Mirrors
#: ``gen_cand01_batch_16run_specs_v2.HASHED_FIELDS`` and
#: ``token_benchmark.REGISTERED_HASH_FIELDS``; a test asserts the three agree.
HASHED_FIELDS = (
    "experiment_id", "schema_version", "switches_required", "provider",
    "quick_model", "deep_model", "output_language", "cache_policy",
    "checkpoint_enabled", "budget", "cases", "switches", "news_scope",
)


def registration_sha256(definition: dict) -> str:
    """Recompute a registration's ``config_sha256``."""
    missing = [k for k in HASHED_FIELDS if k not in definition]
    if missing:
        raise KeyError(f"missing hashed field(s): {missing}")
    subset = {k: definition[k] for k in HASHED_FIELDS}
    payload = json.dumps(subset, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def check_spec_hash(spec: dict) -> None:
    """The spec must still carry the hash its registration declares.

    The hash is **recomputed** from the registration's hashed fields and
    compared. Checking only that a 64-character string is present lets a
    tampered ``deep_model`` run -- audit C-01 demonstrated exactly that.
    """
    registered = spec.get("config_sha256")
    if not registered:
        _fail("spec hash", "spec has no config_sha256")

    registration_path = (Path(spec["_spec_path"]).resolve().parent
                         / "experiment.json")
    if not registration_path.is_file():
        _fail("spec hash", f"no registration beside {registration_path.parent}")
    registration = json.loads(registration_path.read_text(encoding="utf-8"))

    if registration.get("config_sha256") != registered:
        _fail("spec hash", f"spec carries {registered[:12]}… but its "
                           f"registration carries "
                           f"{str(registration.get('config_sha256'))[:12]}…")
    try:
        actual = registration_sha256(registration)
    except KeyError as exc:
        _fail("spec hash", f"registration lacks hashed fields: {exc}")
    if actual != registered:
        _fail("spec hash", f"registration hashes to {actual[:12]}…, not the "
                           f"declared {registered[:12]}…; the definition "
                           f"changed after it was registered")
    # The hash vouches for the *registration*, not for this spec file. A spec
    # can still disagree with it field-by-field (audit C-01: tampering the
    # spec's own ``deep_model`` passed a recompute-only check), so every field
    # both files carry must be identical.
    for key in sorted(set(registration) & set(spec)):
        if key == "config_sha256":
            continue
        if registration[key] != spec[key]:
            _fail("spec hash", f"spec field {key!r} disagrees with the "
                               f"registration: spec has {spec[key]!r}, "
                               f"registration has {registration[key]!r}")
    _ok("spec hash", f"{registered[:16]}… (recomputed, and every shared field "
                     f"matches the registration)")


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
    seen_dirs: dict[str, list[str]] = {}
    for spec_dir in sorted((BATCH_DIR / "specs").iterdir()):
        reg = spec_dir / "experiment.json"
        if not reg.is_file():
            continue
        data = json.loads(reg.read_text(encoding="utf-8"))
        run_id = spec_dir.name.split("_", 1)[0]
        # Two directories for one run ID would silently collapse here (the
        # second assignment wins) while the count still came to 16 as long as
        # some other ID was missing. A duplicated run ID means two different
        # definitions claim one sample; refuse rather than pick one.
        seen_dirs.setdefault(run_id, []).append(spec_dir.name)
        if len(seen_dirs[run_id]) > 1:
            _fail("manifest",
                  f"run ID {run_id} is registered {len(seen_dirs[run_id])} "
                  f"times ({', '.join(seen_dirs[run_id])}); one run ID must "
                  f"name exactly one run")
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

    spec_path = Path(args.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["_spec_path"] = str(spec_path)
    arms_by_run = _run_arm_map()
    if args.run_id not in arms_by_run:
        _fail("manifest", f"run {args.run_id} is not a registered run ID")
    expected_switches = arms_by_run[args.run_id]
    _ok("manifest", f"run {args.run_id} -> switches {expected_switches}")

    # The spec file the gate is pointed at must be the registration for this run
    # ID. Specs carry no run ID field, so the directory name is the authority;
    # a truncated-prefix match would let R1 match R10.
    spec_dir = spec_path.parent.name
    if spec_dir.split("_", 1)[0] != args.run_id:
        _fail("spec path", f"{args.spec} belongs to {spec_dir!r}, "
                           f"not to run {args.run_id}")

    frozen = args.expected_commit or _frozen_commit()
    check_frozen_commit(frozen)
    check_fingerprint_matches_record(frozen)
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
