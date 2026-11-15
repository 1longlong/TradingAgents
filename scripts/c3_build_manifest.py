#!/usr/bin/env python3
"""Build ``MANIFEST.sha256`` for the registered batch directory.

The manifest is the artefact-level integrity record: every file the experiment
depends on, with its SHA-256, relative to the batch directory. It is generated,
never edited, and the freeze verifier checks every entry.

Excluded on purpose:

* the manifest itself (it cannot contain its own digest);
* the release metadata written *after* the commit
  (``c3/FROZEN_COMMIT``, ``c3/FREEZE_RECORD.json``, ``c3/FREEZE_HISTORY.jsonl``,
  ``c3/FINAL_FREEZE_REPORT.md``), because it does not exist yet and names the
  commit the manifest is committed in.

Usage::

    TZ=UTC python scripts/c3_build_manifest.py            # write
    TZ=UTC python scripts/c3_build_manifest.py --check    # verify only
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_REL = "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
BATCH_DIR = REPO_ROOT / BATCH_REL

MANIFEST = "MANIFEST.sha256"
POST_COMMIT_METADATA = {
    "c3/FROZEN_COMMIT",
    "c3/FREEZE_RECORD.json",
    "c3/FREEZE_HISTORY.jsonl",
    "c3/FINAL_FREEZE_REPORT.md",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest() -> list[str]:
    """One ``<digest>  <relative path>`` line per tracked batch file."""
    import subprocess

    listing = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", BATCH_REL],
        capture_output=True, text=True, check=True).stdout.splitlines()
    lines: list[str] = []
    for tracked in sorted(listing):
        relative = Path(tracked).relative_to(BATCH_REL).as_posix()
        if relative == MANIFEST or relative in POST_COMMIT_METADATA:
            continue
        path = BATCH_DIR / relative
        if not path.is_file():
            raise SystemExit(f"tracked file is missing: {path}")
        lines.append(f"{_sha256(path)}  {relative}")
    if not lines:
        raise SystemExit("no tracked files under the batch directory")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify the existing manifest instead of writing it")
    args = parser.parse_args(argv)
    expected = build_manifest()
    path = BATCH_DIR / MANIFEST
    if args.check:
        if not path.is_file():
            print(f"FAIL  {path} is missing", file=sys.stderr)
            return 1
        actual = [line for line in path.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        if actual != expected:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            print("FAIL  MANIFEST.sha256 is stale", file=sys.stderr)
            for line in missing[:10]:
                print(f"  missing/updated: {line.split('  ', 1)[-1]}", file=sys.stderr)
            for line in extra[:10]:
                print(f"  stale: {line.split('  ', 1)[-1]}", file=sys.stderr)
            return 1
        print(f"ok    MANIFEST.sha256: {len(actual)} entries verify")
        return 0
    path.write_text("\n".join(expected) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(expected)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
