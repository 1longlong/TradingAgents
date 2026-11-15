#!/usr/bin/env python3
"""Attest that a commit was the designated freeze, in a way re-freezing cannot undo.

Why this exists
---------------
``c3/FROZEN_COMMIT`` names the commit a paid run must execute, but it cannot
name the commit it is committed in, so it is necessarily untracked. Audit A
round 5 (R-5-B) showed the consequence: take a tampered tree, commit it, run
``c3_write_freeze_record.py``, write the new hash into ``FROZEN_COMMIT`` -- and
both the spending child and the gate print PASS. Every check compared the tree
against a record that the same act of tampering had just rewritten. That is a
circular check, and no amount of sealing the record fixes it: the seal is in
the tree being sealed.

The one fact a later commit cannot change is git's own ancestry. So the
designated freeze is recorded here as an **append-only** history: the first
entry names the commit, and every entry after it must be a *descendant* of the
one before. A tree that re-signs itself necessarily adds a new entry, and the
first entry still names the original commit -- so the recorded designation
survives, and ``verify_frozen_tree`` can require HEAD to be it.

The history is **release metadata**: it names the commit it was written after,
so it cannot live inside that commit, and it is listed in ``.gitignore``. It is
not the load-bearing anchor — ``refs/tags/c3-final-freeze`` is, because a tag's
object hash is content-addressed and is published in ``c3/FREEZE_RECORD.json``
and in the final report. The verifier requires the tag, the record, the history
and ``HEAD`` to name the same commit, so a re-designation that only rewrites this
file is caught by the tag check. (Audit round 2 correctly noted that the older
docstring claimed this file was tracked; that claim was false and is corrected
here.)

Usage::

    # record the current HEAD as the designated freeze (once)
    python scripts/c3_attest.py designate

    # append a note to the history without changing the designation
    python scripts/c3_attest.py append --note "..."

    # check HEAD against the designation (what the gate and child do)
    python scripts/c3_attest.py verify
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = (REPO_ROOT / "token_benchmarks" / "live_pilot_2x2"
             / "cand01_batch_16run_v2")
HISTORY_FILE = BATCH_DIR / "c3" / "FREEZE_HISTORY.jsonl"


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip()


def load_history() -> list[dict]:
    if not HISTORY_FILE.is_file():
        return []
    entries = []
    for number, line in enumerate(HISTORY_FILE.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{HISTORY_FILE.name}:{number} is not JSON: {exc}") from None
    return entries


def designated_commit() -> str | None:
    """The commit the first ``designated_freeze`` entry names, if any."""
    for entry in load_history():
        if entry.get("event") == "designated_freeze" and entry.get("commit"):
            return entry["commit"]
    return None


def is_ancestor(older: str, newer: str) -> bool:
    if older == newer:
        return True
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", older, newer],
        capture_output=True, check=False).returncode == 0


def check_head_is_designated(head: str) -> None:
    """Raise ``RunRefused``-compatible conditions if HEAD is not the freeze.

    The designation is the *first* history entry, never the latest: appending
    later entries -- which a re-freeze must do -- cannot move it.
    """
    entries = load_history()
    if not entries:
        raise _Refused(
            f"no freeze history at {HISTORY_FILE}; the designated freeze is "
            f"not recorded, so a paid run cannot prove it executes the audited "
            f"release")
    designated = designated_commit()
    if not designated:
        raise _Refused(f"{HISTORY_FILE.name} has no designated_freeze entry")
    # The chain must itself be a chain: every entry descends from the first.
    for entry in entries[1:]:
        commit = entry.get("commit")
        if commit and not is_ancestor(designated, commit):
            raise _Refused(
                f"{HISTORY_FILE.name} contains {commit[:12]} which does not "
                f"descend from the designated freeze {designated[:12]}; the "
                f"history has been rewritten, not appended to")
    if head != designated:
        relation = ("a descendant of" if is_ancestor(designated, head)
                    else "unrelated to")
        raise _Refused(
            f"HEAD is {head[:12] or 'unknown'}, {relation} the designated "
            f"freeze {designated[:12]}; the code that would run is not the "
            f"code that was designated for these paid runs")


class _Refused(RuntimeError):
    """Local stand-in so this module does not import the harness."""


class _RunRefusedProxy(RuntimeError):
    pass


def _record(event: str, note: str = "") -> dict:
    head = _git("rev-parse", "HEAD")
    if not head:
        raise SystemExit("not a git checkout")
    entry = {"event": event, "commit": head, "recorded_by": "c3_attest.py"}
    if note:
        entry["note"] = note
    return entry


def _append(entry: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = HISTORY_FILE.read_text(encoding="utf-8") if HISTORY_FILE.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    HISTORY_FILE.write_text(
        existing + json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("designate", help="record HEAD as the designated freeze (once)")
    append = sub.add_parser("append", help="append a note without changing the designation")
    append.add_argument("--note", default="")
    sub.add_parser("verify", help="check HEAD against the designation")

    args = parser.parse_args(argv)

    if args.command == "designate":
        if designated_commit():
            print(f"REFUSED: a designated freeze already exists "
                  f"({designated_commit()[:12]}); the designation is append-only "
                  f"and cannot be replaced", file=sys.stderr)
            return 3
        head = _git("rev-parse", "HEAD")
        dirty = _git("status", "--porcelain", "--untracked-files=no")
        if dirty:
            print(f"REFUSED: the tracked tree is dirty:\n{dirty}", file=sys.stderr)
            return 4
        entry = _record("designated_freeze",
                        "first entry; append-only. This is the commit the 16 paid "
                        "runs must execute.")
        _append(entry)
        print(f"designated freeze: {head}")
        return 0

    if args.command == "append":
        _append(_record("note", args.note))
        print("appended")
        return 0

    if args.command == "verify":
        try:
            check_head_is_designated(_git("rev-parse", "HEAD"))
        except (_Refused, ValueError) as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print(f"ok: HEAD is the designated freeze {designated_commit()[:12]}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
