#!/usr/bin/env python3
"""Verify that the checked-out tree *is* the certified final freeze.

This is the one authority for the freeze question. ``c3_preflight_gate.py`` and
the spending child (``token_benchmark.verify_frozen_tree``) call it instead of
each re-implementing a subset, because a check that exists in two places drifts.

What it proves, from the tree and from git, with nothing trusted from the
record except the commit it *claims*:

1. ``HEAD`` equals ``c3/FROZEN_COMMIT``, the record's ``commit``, the tag's
   commit and the first (append-only) freeze-history designation. A commit made
   after the freeze moves ``HEAD`` and every one of these fails. This is the
   fix for the defect that made the previous freeze unusable: it designated an
   *ancestor* of ``HEAD``, so ``HEAD == FROZEN_COMMIT`` could never hold.
2. ``HEAD^{tree}`` equals the recorded tree SHA.
3. The tracked working tree is clean and nothing non-ignored is untracked.
4. The recomputed code fingerprint equals both ``c3/code_freeze.txt`` and the
   record. The fingerprint covers the harness, the specs, the protocol and the
   tests, and excludes ``c3/`` (which states it).
5. Every digest in ``MANIFEST.sha256`` matches the file it names.
6. All 16 specs are present, each reconciliation of ``config_sha256`` against
   its registration succeeds, ``CONFIG_HASH_MANIFEST.csv`` agrees, and every
   spec carries the hash of its own registration.
7. The protocol and generator hashes match the record.
8. Every registration states ``budget_mode = uncapped_authorized`` with
   ``max_total_tokens = null`` (U-2: a null cap is only "uncapped" when
   declared, never inferred).
9. Spec absolute paths point inside this tree (a spec generated against a
   vanished checkout would otherwise fail the child's import-root check at
   spend time).
10. The annotated release tag exists, points at ``HEAD`` and carries the
    fingerprint in its message.

Exit code 0 = the tree is the certified freeze. Anything else = stop.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BATCH_REL = "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
BATCH_DIR = REPO_ROOT / BATCH_REL
C3 = BATCH_DIR / "c3"
TAG = "c3-final-freeze"
RECORD_FILE = C3 / "FREEZE_RECORD.json"
REPORT_FILE = C3 / "FINAL_FREEZE_REPORT.md"
FROZEN_FILE = C3 / "FROZEN_COMMIT"
HISTORY_FILE = C3 / "FREEZE_HISTORY.jsonl"
SEAL_FILE = C3 / "RELEASE_SEAL.sha256"
CODE_FREEZE_FILE = C3 / "code_freeze.txt"
MANIFEST_FILE = BATCH_DIR / "MANIFEST.sha256"
PROTOCOL_FILE = BATCH_DIR / "CAND01_BATCH_2X2_PROTOCOL_V2.md"
GENERATOR_FILE = REPO_ROOT / "scripts" / "gen_cand01_batch_16run_specs_v2.py"
HASH_MANIFEST_FILE = BATCH_DIR / "CONFIG_HASH_MANIFEST.csv"

EXPECTED_RUNS = 16
EXPECTED_BUDGET_MODE = "uncapped_authorized"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=False).stdout.strip()


def _git_raw(root: Path, *args: str) -> str:
    """Like :func:`_git` but without stripping: tag-object digests need bytes."""
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=False).stdout


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify(root: Path = REPO_ROOT) -> dict:
    """Run every freeze check. Returns ``{"ok", "checks", "failures"}``."""
    root = Path(root).resolve()
    batch = root / BATCH_REL
    c3 = batch / "c3"
    checks: list[str] = []
    failures: list[str] = []

    def ok(message: str) -> None:
        checks.append(message)

    def bad(message: str) -> None:
        failures.append(message)

    record_path = c3 / "FREEZE_RECORD.json"
    if not record_path.is_file():
        return {"ok": False, "checks": checks,
                "failures": [f"{record_path} is missing; the tree was never "
                             f"certified (run scripts/c3_finalize_freeze.py "
                             f"after the final commit)"]}
    try:
        record = _load_json(record_path)
    except ValueError as exc:
        return {"ok": False, "checks": checks,
                "failures": [f"{record_path} is not JSON: {exc}"]}

    head = _git(root, "rev-parse", "HEAD")
    head_tree = _git(root, "rev-parse", "HEAD^{tree}")

    # -- 1. identity -------------------------------------------------------
    frozen_file = c3 / "FROZEN_COMMIT"
    if not frozen_file.is_file():
        bad(f"{frozen_file} is missing")
    else:
        recorded_commit = frozen_file.read_text(encoding="utf-8").strip()
        if recorded_commit != head:
            bad(f"HEAD is {head[:12]}, but c3/FROZEN_COMMIT names "
                f"{recorded_commit[:12]}; the code that would run is not the "
                f"code that was certified")
        else:
            ok(f"HEAD == FROZEN_COMMIT ({head[:12]})")
    if record.get("commit") != head:
        bad(f"the record names commit {str(record.get('commit'))[:12]}, HEAD is "
            f"{head[:12]}")
    else:
        ok(f"record.commit == HEAD ({head[:12]})")

    # -- 2. tree -----------------------------------------------------------
    if record.get("tree_sha") != head_tree:
        bad(f"the record's tree {str(record.get('tree_sha'))[:12]} != HEAD tree "
            f"{head_tree[:12]}")
    else:
        ok(f"record.tree_sha == HEAD tree ({head_tree[:12]})")

    # -- 3. cleanliness ----------------------------------------------------
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        bad(f"the tracked tree is dirty:\n{dirty}")
    else:
        ok("tracked working tree is clean")
    untracked = _git(root, "status", "--porcelain", "--untracked-files=normal")
    if untracked:
        bad(f"untracked (non-ignored) files are present:\n{untracked}")
    else:
        ok("no untracked, non-ignored files")

    # -- 4. fingerprint ----------------------------------------------------
    from token_benchmark import compute_code_state  # noqa: E402

    experiment = _load_json(batch / "experiment.json")
    state = compute_code_state(batch, experiment)
    actual_fingerprint = state.get("working_tree_sha256")
    recorded_fingerprint = (record.get("fingerprint") or {}).get("working_tree_sha256")
    if actual_fingerprint != recorded_fingerprint:
        bad(f"this tree fingerprints to {actual_fingerprint}, the record says "
            f"{recorded_fingerprint}")
    else:
        ok(f"fingerprint recomputed and equal ({str(actual_fingerprint)[:16]}…)")
    declared = None
    if CODE_FREEZE_FILE.is_file():
        for line in CODE_FREEZE_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("working_tree_sha256") and "=" not in stripped:
                declared = stripped.split(":", 1)[-1].strip()
                break
    if declared != recorded_fingerprint:
        bad(f"c3/code_freeze.txt declares {declared}, the record says "
            f"{recorded_fingerprint}")
    else:
        ok("c3/code_freeze.txt agrees with the record")

    # -- 5. manifest -------------------------------------------------------
    if _sha256(MANIFEST_FILE) != record.get("manifest_sha256"):
        bad("MANIFEST.sha256 has changed since certification")
    else:
        ok(f"MANIFEST.sha256 digest matches the record "
           f"({record.get('manifest_entries')} entries)")
    if MANIFEST_FILE.is_file():
        entries = 0
        for line in MANIFEST_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entries += 1
            digest, _, rel = line.partition("  ")
            path = batch / rel.strip()
            if not path.is_file():
                bad(f"manifest entry {rel}: file is missing")
            elif _sha256(path) != digest:
                bad(f"manifest entry {rel}: digest mismatch")
        if entries != record.get("manifest_entries"):
            bad(f"manifest has {entries} entries, the record says "
                f"{record.get('manifest_entries')}")
        elif not any(f.startswith("manifest entry") for f in failures):
            ok(f"all {entries} manifest entries verify")
    else:
        bad("MANIFEST.sha256 is missing")

    # -- 6/7/8/9. specs, hashes, budget, paths ------------------------------
    from token_benchmark import registration_sha256  # noqa: E402

    specs_dir = batch / "specs"
    spec_dirs = sorted(d for d in specs_dir.iterdir() if d.is_dir()) \
        if specs_dir.is_dir() else []
    if len(spec_dirs) != EXPECTED_RUNS:
        bad(f"expected {EXPECTED_RUNS} spec directories, found {len(spec_dirs)}")

    recorded_specs = record.get("specs") or {}
    hash_manifest: dict[str, str] = {}
    if HASH_MANIFEST_FILE.is_file():
        import csv

        with HASH_MANIFEST_FILE.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("run_id"):
                    hash_manifest[row["run_id"]] = row.get("config_sha256", "")

    hash_problems = 0
    for directory in spec_dirs:
        run_id = directory.name.split("_", 1)[0]
        try:
            registration = _load_json(directory / "experiment.json")
            spec = _load_json(directory / "spec.json")
        except (OSError, ValueError) as exc:
            bad(f"{directory.name}: unreadable artefact: {exc}")
            continue
        declared_hash = registration.get("config_sha256")
        try:
            recomputed = registration_sha256(registration)
        except KeyError as exc:
            bad(f"{directory.name}: cannot recompute config_sha256: {exc}")
            hash_problems += 1
            continue
        if recomputed != declared_hash:
            bad(f"{directory.name}: config_sha256 {str(declared_hash)[:12]} does "
                f"not recompute ({recomputed[:12]})")
            hash_problems += 1
        if spec.get("config_sha256") != declared_hash:
            bad(f"{directory.name}: spec.json carries a different config_sha256")
            hash_problems += 1
        if hash_manifest.get(run_id) != declared_hash:
            bad(f"{directory.name}: CONFIG_HASH_MANIFEST.csv disagrees")
            hash_problems += 1
        entry = recorded_specs.get(run_id) or {}
        if entry.get("config_sha256") != declared_hash:
            bad(f"{directory.name}: FREEZE_RECORD.json disagrees")
            hash_problems += 1
        if entry.get("spec_sha256") != _sha256(directory / "spec.json"):
            bad(f"{directory.name}: spec.json changed since certification")
            hash_problems += 1
        budget = registration.get("budget") or {}
        if budget.get("budget_mode") != EXPECTED_BUDGET_MODE:
            bad(f"{directory.name}: budget_mode={budget.get('budget_mode')!r}, "
                f"expected {EXPECTED_BUDGET_MODE!r}")
            hash_problems += 1
        if "max_total_tokens" not in budget or budget["max_total_tokens"] is not None:
            bad(f"{directory.name}: max_total_tokens must be explicitly null for "
                f"{EXPECTED_BUDGET_MODE}")
            hash_problems += 1
        # -- 9. absolute paths inside this tree ---------------------------
        for field in ("results_dir", "experiment_root"):
            value = spec.get(field)
            if not value:
                bad(f"{directory.name}: spec has no {field}")
                hash_problems += 1
                continue
            try:
                Path(value).resolve().relative_to(root)
            except (ValueError, OSError):
                bad(f"{directory.name}: {field}={value} is outside {root}")
                hash_problems += 1
    if not hash_problems:
        ok(f"{len(spec_dirs)} specs: config_sha256 recomputed, manifests agree, "
           f"budget uncapped_authorized, paths inside the tree")

    # -- 7. protocol / generator / sealed release files --------------------
    if _sha256(PROTOCOL_FILE) != record.get("protocol_sha256"):
        bad("CAND01_BATCH_2X2_PROTOCOL_V2.md has changed since certification")
    else:
        ok("protocol digest matches the record")
    if _sha256(GENERATOR_FILE) != record.get("generator_sha256"):
        bad("gen_cand01_batch_16run_specs_v2.py has changed since certification")
    else:
        ok("generator digest matches the record")
    # Audit round 2 (F5): these fields were recorded and never recomputed.
    if _sha256(c3 / "code_freeze.txt") != record.get("code_freeze_sha256"):
        bad("c3/code_freeze.txt has changed since certification")
    else:
        ok("code_freeze.txt digest matches the record")
    if _sha256(c3 / "RELEASE_SEAL.sha256") != record.get("release_seal_sha256"):
        bad("c3/RELEASE_SEAL.sha256 has changed since certification")
    else:
        ok("RELEASE_SEAL.sha256 digest matches the record")

    # -- 10. tag + history -------------------------------------------------
    tag_object = _git(root, "rev-parse", f"refs/tags/{TAG}^{{commit}}")
    if tag_object != head:
        bad(f"tag {TAG} points at {tag_object[:12] or 'nothing'}, not HEAD "
            f"{head[:12]}")
    else:
        ok(f"tag {TAG} names HEAD")
    tag_sha = _git(root, "rev-parse", f"refs/tags/{TAG}")
    if tag_sha != record.get("tag_object_sha"):
        bad(f"tag object is {tag_sha[:12]}, the record says "
            f"{str(record.get('tag_object_sha'))[:12]}")
    else:
        ok("tag object digest matches the record")
    tag_message = _git_raw(root, "cat-file", "tag", TAG)
    if str(recorded_fingerprint) not in tag_message:
        bad("the tag message does not carry the certified fingerprint")
    else:
        ok("tag message carries the fingerprint")
    # The message digest is what pins the tag's *content*; the tag object SHA
    # pins it too, but only if this value is actually compared.
    message_body = (tag_message.split("\n\n", 1)[1]
                    if "\n\n" in tag_message else tag_message)
    if hashlib.sha256(message_body.encode("utf-8")).hexdigest() != \
            record.get("tag_message_sha256"):
        bad("the tag message has changed since certification")
    else:
        ok("tag message digest matches the record")

    history = c3 / "FREEZE_HISTORY.jsonl"
    if not history.is_file():
        bad(f"{history} is missing; the designation is not recorded")
    else:
        entries = [json.loads(line) for line in
                   history.read_text(encoding="utf-8").splitlines() if line.strip()]
        designated = next((e.get("commit") for e in entries
                           if e.get("event") == "designated_freeze"), None)
        if designated != head:
            bad(f"the append-only history designates "
                f"{str(designated)[:12]}, not HEAD {head[:12]}")
        else:
            ok("append-only history designates HEAD")
        for entry in entries[1:]:
            commit = entry.get("commit")
            if commit and subprocess.run(
                    ["git", "-C", str(root), "merge-base", "--is-ancestor",
                     str(designated), commit],
                    capture_output=True).returncode != 0:
                bad(f"history entry {commit[:12]} does not descend from the "
                    f"designated freeze; the history was rewritten")

    # -- import provenance (A-00) -----------------------------------------
    spec = importlib.util.find_spec("tradingagents")
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None:
        bad("tradingagents is not importable")
    else:
        try:
            origin.relative_to(root)
        except ValueError:
            bad(f"tradingagents resolves to {origin}, outside {root} (audit "
                f"A-00: a shared editable install would run the wrong tree)")
        else:
            ok(f"tradingagents resolves inside the tree ({origin.parent})")

    return {"ok": not failures, "checks": checks, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = verify(REPO_ROOT)
    if args.json:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        for check in result["checks"]:
            print(f"ok    {check}")
        for failure in result["failures"]:
            print(f"FAIL  {failure}")
    if not result["ok"]:
        if not args.json:
            print("\nFINAL FREEZE VERIFICATION FAILED")
        return 1
    if not args.json and not args.quiet:
        print("\nFINAL FREEZE VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
