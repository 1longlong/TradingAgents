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

Exit code 0 means the offline checks passed. With live probes it prints
"GATE PASSED — safe to spend money"; with ``--skip-network`` (which requires
``C3_I_MEAN_TO_SKIP_NETWORK=yes``) it prints "OFFLINE ONLY", which is **not**
authorisation to spend. Anything else means stop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Audit A-00: running ``python scripts/c3_preflight_gate.py`` puts only
# ``scripts/`` on ``sys.path``, so ``import tradingagents`` resolved through the
# shared editable install to the *main* checkout -- from any cwd. The gate then
# checked a tree it was not looking at (and ``check_import_root`` refused, so
# the documented launch could never pass). Pin this file's own repository root
# ahead of everything else: the gate now always inspects the tree it lives in.
_THIS_ROOT = Path(__file__).resolve().parents[1]
if str(_THIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_THIS_ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c3_attest import check_head_is_designated  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
#: The container commit is read from a file that the *release* step writes,
#: not embedded here: a commit cannot contain its own hash. ``--expected-commit``
#: or ``C3_FROZEN_COMMIT`` override it.
FROZEN_COMMIT_FILE = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/c3/FROZEN_COMMIT"


def _frozen_commit() -> str:
    """The commit this gate will certify HEAD against.

    ``--expected-commit`` / ``C3_FROZEN_COMMIT`` used to *replace* the frozen
    reference, which let a caller point the gate at whatever commit was checked
    out (audit A round 5, R-5-D). The append-only designation
    (``c3/FREEZE_HISTORY.jsonl``) removed the need for that: the reference is a
    recorded fact, not an argument. An override is now an *assertion* -- it must
    agree with both the file and the designation, or the gate refuses.
    """
    if not FROZEN_COMMIT_FILE.is_file():
        raise SystemExit(
            f"FAIL  frozen commit: {FROZEN_COMMIT_FILE} is missing; refusing to "
            f"run without a frozen reference"
        )
    recorded = FROZEN_COMMIT_FILE.read_text(encoding="utf-8").strip()
    claimed = (os.environ.get("C3_FROZEN_COMMIT") or "").strip()
    if claimed and claimed != recorded:
        raise SystemExit(
            f"FAIL  frozen commit: C3_FROZEN_COMMIT claims {claimed[:12]}, but "
            f"{FROZEN_COMMIT_FILE.name} records {recorded[:12]}; the override may "
            f"only restate the frozen reference, not replace it"
        )
    return recorded

#: The 2x2, as frozen in the protocol. Each arm maps to its four switches.
ARMS = {
    "B":  {"batch_macro": False, "structured": True,  "single_pass": False, "s2_downstream": True},
    "AB": {"batch_macro": True,  "structured": True,  "single_pass": False, "s2_downstream": True},
    "C0": {"batch_macro": False, "structured": True,  "single_pass": True,  "s2_downstream": True},
    "CC": {"batch_macro": True,  "structured": True,  "single_pass": True,  "s2_downstream": True},
}

FORBIDDEN_NEWS_VENDORS = {"gdelt", "alpha_vantage", "yahoo"}

#: One row of the protocol's arm table: ``| `CC` | true | true | true | true |``.
_ARM_ROW = re.compile(
    r"^\|\s*`(?P<arm>B|AB|C0|CC)`\s*\|"
    r"\s*(?P<batch>true|false)\s*\|"
    r"\s*(?P<single>true|false)\s*\|"
    r"\s*(?P<structured>true|false)\s*\|"
    r"\s*(?P<s2>true|false)\s*\|",
    re.MULTILINE,
)


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

    # HEAD == FROZEN_COMMIT is circular on its own: FROZEN_COMMIT is untracked,
    # so anything that can rewrite the record can also rewrite the pointer
    # (Audit A round 5, R-5-B; and the 2026-11-15 self-tamper incident). The
    # append-only designation in FREEZE_HISTORY.jsonl names the *first* commit
    # ever designated, and later entries cannot retract it.
    try:
        check_head_is_designated(head)
    except Exception as exc:  # noqa: BLE001 - any failure means "refuse"
        _fail("designated freeze", str(exc))
    _ok("designated freeze", head[:12])


def check_release_seal() -> None:
    """The ``c3/`` release files must be one consistent set (audit B-08).

    ``FROZEN_COMMIT``, ``code_freeze.txt`` and ``env_credential_audit.txt`` are
    release metadata: ``FROZEN_COMMIT`` cannot live in the commit it names, so
    the three cannot cross-reference each other by git. ``RELEASE_SEAL.sha256``
    is generated *with* them and is therefore the only artefact that pins all
    three to one issuance: regenerating any of them breaks the seal, and the
    gate refuses rather than trusting a record that may lag or disagree.
    """
    import hashlib

    seal = BATCH_DIR / "c3" / "RELEASE_SEAL.sha256"
    if not seal.is_file():
        _fail("release seal", f"{seal.name} is missing; the c3/ files are unpinned")
    stale: list[str] = []
    for line in seal.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        # ``FROZEN_COMMIT`` names the commit that contains the seal, so it must
        # be written after the seal -- the same fixed point as
        # ``code_freeze.txt`` naming its own commit. It is therefore listed in
        # the seal without being checked against it; the gate already requires
        # HEAD to equal its contents, which pins it far more tightly.
        if rel.strip().endswith("FROZEN_COMMIT"):
            continue
        path = BATCH_DIR / rel.strip()
        if not path.is_file():
            stale.append(f"{rel} (missing)")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            stale.append(f"{rel} (changed since the seal was written)")
    if stale:
        _fail("release seal",
              "the c3/ release files no longer match RELEASE_SEAL.sha256: "
              + "; ".join(stale) + " -- regenerate the seal with the record")
    _ok("release seal", f"{len(seal.read_text().splitlines())} c3/ files pinned")


def check_fingerprint_matches_record() -> None:
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
    # The record is written before the commit that commits it, so it can never
    # name that commit. The fingerprint is therefore the authority; the commit
    # it does name only has to be an ancestor of HEAD, which proves the record
    # came from this line of work rather than from an unrelated tree.
    recorded = None
    for line in text.splitlines():
        if line.strip().startswith("Commit at write time:"):
            # The line is human-readable ("<sha>   (the parent of the freeze
            # commit, by construction)"), so take the first token: passing the
            # prose to git made `merge-base --is-ancestor` exit 128 and the gate
            # fail on a perfectly good release (audit round 2).
            recorded = line.split(":", 1)[-1].strip().split()[0]
            break
    if not recorded:
        _fail("freeze record", f"{record.name} names no write-time commit")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", recorded, "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if ancestor.returncode != 0:
        _fail("freeze record",
              f"code_freeze.txt was written at {recorded[:12]}, which is not an "
              f"ancestor of HEAD; the record belongs to another line of work")
    _ok("freeze record",
        f"{declared[:16]}… matches this tree; record parent "
        f"{recorded[:12]} (an ancestor, as it must be: a file cannot name the "
        f"commit that contains it)")


def check_final_freeze() -> None:
    """The whole certification, shared with the spending child.

    The individual checks above produce precise messages for the common
    failures; this one is the single definition of "the tree is the certified
    freeze" (commit == record == tag == history, tree SHA, manifest, all 16 spec
    hashes, budget contract, in-tree paths). Without it the gate and the child
    would each be checking a subset, and a subset is what let a stale
    designation certify the wrong commit.
    """
    try:
        from c3_verify_final_freeze import verify as _verify_final_freeze
    except ImportError:  # pragma: no cover - the script lives beside this one
        import importlib.util

        module_spec = importlib.util.spec_from_file_location(
            "c3_verify_final_freeze",
            Path(__file__).resolve().parent / "c3_verify_final_freeze.py")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        _verify_final_freeze = module.verify
    result = _verify_final_freeze(REPO_ROOT)
    if not result["ok"]:
        _fail("final freeze", "; ".join(result["failures"][:4]))
    _ok("final freeze", f"{len(result['checks'])} certification checks passed")



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


def _protocol_arm_table() -> dict[str, dict]:
    """The arm table from the frozen protocol document.

    This is the independent authority for what each arm means. Reading the
    expected switches from the same registration being validated was circular:
    audit B-10/B-11 showed a registration edited consistently (switches *and*
    ``config_sha256`` rehashed) ran a different arm, and the gate printed
    "GATE PASSED — safe to spend money", because it had only checked the file
    against itself. The protocol is not editable by a spec edit, so a swap now
    has to disagree with a document that says otherwise.
    """
    text = (BATCH_DIR / "CAND01_BATCH_2X2_PROTOCOL_V2.md").read_text(encoding="utf-8")
    table: dict[str, dict] = {}
    for m in _ARM_ROW.finditer(text):
        table[m["arm"]] = {
            "batch_macro": m["batch"] == "true",
            "single_pass": m["single"] == "true",
            "structured": m["structured"] == "true",
            "s2_downstream": m["s2"] == "true",
        }
    if set(table) != {"B", "AB", "C0", "CC"}:
        _fail("protocol", f"could not parse the 4-arm table; got {sorted(table)}")
    # The hard-coded ``ARMS`` below is a second copy; refuse if they disagree.
    # Two sources of truth that may drift are worse than one that is checked.
    if table != ARMS:
        _fail("protocol",
              f"the parsed arm table {table} disagrees with the compiled-in "
              f"ARMS {ARMS}; one of them has drifted from the protocol")
    return table


def _frozen_switch_matrix() -> dict[str, dict]:
    """``{run_id: switches}`` from the tracked ``SWITCH_MATRIX.csv``.

    ``SWITCH_MATRIX.csv`` was written in the registration commit
    (``b00dd00``) and is covered by the tracked tree the gate hashes, so it is
    an authority that a spec edit cannot silently rewrite: changing it changes
    ``working_tree_sha256`` and the freeze record stops matching.
    """
    import csv

    path = BATCH_DIR / "SWITCH_MATRIX.csv"
    if not path.is_file():
        _fail("manifest", f"{path} is missing; cannot anchor the arms")
    out: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            run_id = (row.get("run_id") or "").strip()
            if not run_id:
                continue
            out[run_id] = {
                "batch_macro": _as_bool(row["batch_macro"]),
                "single_pass": _as_bool(row["single_pass"]),
                "structured": _as_bool(row["structured"]),
                "s2_downstream": _as_bool(row["s2_downstream"]),
            }
    return out


def _as_bool(text: str) -> bool:
    value = (text or "").strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    _fail("manifest", f"unparseable boolean {text!r} in SWITCH_MATRIX.csv")


def check_spec_location(spec_path: Path, run_id: str) -> None:
    """The spec must be the registration of *this* run, in its own directory.

    Audit round 2 (M1): a self-consistent copy of R01 with a different
    ``deep_model``, rehashed and placed in ``/tmp/R01_NVDA_C0``, passed the
    spec-hash, arm and news checks. The paid child already refuses it (its
    registration path is not the frozen one), so this is defence in depth --
    but a gate that prints "safe to spend" for a copy is not doing its job.
    """
    import csv

    path = BATCH_DIR / "SWITCH_MATRIX.csv"
    row = {}
    if path.is_file():
        with path.open(newline="", encoding="utf-8") as handle:
            row = next((r for r in csv.DictReader(handle)
                        if (r.get("run_id") or "").strip() == run_id), {})
    ticker, arm = (row.get("ticker") or "").strip(), (row.get("arm") or "").strip()
    if not ticker or not arm:
        _fail("spec location", f"Run ID {run_id} is not in SWITCH_MATRIX.csv")
    expected = (BATCH_DIR / "specs" / f"{run_id}_{ticker}_{arm}").resolve()
    actual = Path(spec_path).resolve().parent
    if actual != expected:
        _fail("spec location",
              f"{spec_path} is in {actual}, but {run_id} is registered at "
              f"{expected}; a copy elsewhere is not the registered run")
    _ok("spec location", str(actual.name))


def _run_arm_map() -> dict[str, dict]:
    """``{run_id: switches}`` for all 16 registered runs.

    The expected switches come from the **frozen protocol's** arm table keyed by
    the arm the directory names -- not from the registration file itself, which
    would make the check circular. The registration is then required to agree.
    """
    table = _protocol_arm_table()
    frozen = _frozen_switch_matrix()
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
        parts = spec_dir.name.split("_")
        if len(parts) < 3:
            _fail("manifest", f"{spec_dir.name}: cannot read an arm from the name")
        arm = parts[2]
        if arm not in table:
            _fail("manifest", f"{spec_dir.name}: {arm!r} is not an arm of this protocol")
        switches = data.get("switches")
        if not switches:
            _fail("manifest", f"{spec_dir.name}: registration declares no switches")
        # The registration must equal the protocol row for the arm it is named as.
        if switches != table[arm]:
            _fail("arm",
                  f"{spec_dir.name} is named arm {arm}, whose protocol switches "
                  f"are {table[arm]}, but its registration declares {switches}")
        # ...and must equal the arm SWITCH_MATRIX.csv froze for this Run ID.
        # The protocol says what an arm means; the matrix says which arm this
        # Run ID runs. A consistent in-place edit plus a directory rename would
        # satisfy the protocol check only if the ID moved to another arm, which
        # this catches.
        if run_id not in frozen:
            _fail("arm", f"{spec_dir.name}: Run ID {run_id} is absent from "
                         f"SWITCH_MATRIX.csv")
        if switches != frozen[run_id]:
            _fail("arm",
                  f"{spec_dir.name}: SWITCH_MATRIX.csv froze {frozen[run_id]} for "
                  f"{run_id}, but the registration declares {switches}")
        out[run_id] = frozen[run_id]
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
    check_spec_location(spec_path, args.run_id)

    # An override may only *restate* the frozen reference (audit A round 5,
    # R-5-D; audit round 2, L1: the flag used to bypass that assertion).
    frozen = _frozen_commit()
    if args.expected_commit and args.expected_commit != frozen:
        _fail("frozen commit",
              f"--expected-commit {args.expected_commit[:12]} does not restate "
              f"the frozen reference {frozen[:12]}; the reference is a recorded "
              f"fact, not an argument")
    if args.skip_network and os.environ.get("C3_I_MEAN_TO_SKIP_NETWORK") != "yes":
        _fail("network probes",
              "--skip-network exists for offline verification only. A run whose "
              "Finnhub/FRED probes never ran is not authorised to spend; set "
              "C3_I_MEAN_TO_SKIP_NETWORK=yes to acknowledge that explicitly")
    check_frozen_commit(frozen)
    check_fingerprint_matches_record()
    check_release_seal()
    check_import_root()
    check_final_freeze()
    check_spec_hash(spec)
    check_arm_matches_manifest(spec, expected_switches)
    check_news_scope(spec)
    if not args.skip_network:
        check_finnhub(spec["case"]["ticker"], spec["case"]["trade_date"])
        check_fred(spec["case"]["trade_date"])

    if args.skip_network:
        print("\nGATE PASSED (OFFLINE ONLY) — this is NOT authorisation to spend: "
              "the Finnhub/FRED probes did not run")
    else:
        print("\nGATE PASSED — safe to spend money on this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
