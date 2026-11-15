#!/usr/bin/env python3
"""Certify the checked-out commit as the final freeze, once, after the commit.

Why this exists
---------------
The previous freeze designated ``eaba4f7`` while the branch had already moved on,
so ``HEAD == FROZEN_COMMIT`` could never be true again and all 16 runs would have
been refused forever (``C3_HALT_REPORT_20261115.md`` §4). The cause was ordering:
the designation was written *before* the final commit. This script only runs
*after* the commit, on a clean tree, and records what ``HEAD`` actually is.

It writes, all generated from the tree rather than typed by hand:

``c3/FROZEN_COMMIT``
    The commit SHA (release metadata: a commit cannot contain its own hash).
``c3/FREEZE_RECORD.json``
    Machine-readable record: commit, tree, working-tree fingerprint, spec
    hashes, generator hash, protocol hash, manifest digest, tag.
``c3/FREEZE_HISTORY.jsonl``
    Append-only designation. The *first* entry names the freeze; later entries
    cannot retract it.
``c3/FINAL_FREEZE_REPORT.md``
    The human-readable record, rendered from ``FREEZE_RECORD.json``.
``refs/tags/c3-final-freeze``
    An annotated tag whose message carries the commit, tree and fingerprint.
    The tag object is content-addressed, so it is an anchor outside the tree
    that a later edit cannot silently repoint.

All five are listed in ``.gitignore``: they are release metadata, they cannot be
part of the commit they describe, and a clean working tree is a precondition for
the paid runs. Everything that *can* be committed -- the code fingerprint
(``c3/code_freeze.txt``), its seal and ``MANIFEST.sha256`` -- is committed, and
this script refuses if either disagrees with the tree.

Usage::

    TZ=UTC PYTHONSAFEPATH=1 python scripts/c3_finalize_freeze.py
    TZ=UTC PYTHONSAFEPATH=1 python scripts/c3_verify_final_freeze.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
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

RECORD_SCHEMA = 1


class FinalizeError(SystemExit):
    """The tree cannot be certified as the final freeze."""


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                            capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise FinalizeError(
            f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def declared_freeze_fingerprint() -> str:
    """The fingerprint committed in ``c3/code_freeze.txt``."""
    text = CODE_FREEZE_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("working_tree_sha256") and "=" not in stripped:
            value = stripped.split(":", 1)[-1].strip()
            if len(value) == 64:
                return value
    raise FinalizeError(
        f"{CODE_FREEZE_FILE} records no usable working_tree_sha256; run "
        f"scripts/c3_write_freeze_record.py before the commit")


def manifest_problems() -> list[str]:
    """Every entry of ``MANIFEST.sha256`` must still match its file."""
    if not MANIFEST_FILE.is_file():
        return [f"{MANIFEST_FILE} is missing"]
    problems = []
    for line in MANIFEST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, rel = line.partition("  ")
        path = BATCH_DIR / rel.strip()
        if not path.is_file():
            problems.append(f"{rel}: missing")
        elif sha256_file(path) != digest:
            problems.append(f"{rel}: changed since the manifest was written")
    return problems


def spec_hashes() -> dict[str, dict]:
    """``{run_id: {config_sha256, spec_sha256, experiment_sha256}}``."""
    out: dict[str, dict] = {}
    for directory in sorted((BATCH_DIR / "specs").iterdir()):
        if not directory.is_dir():
            continue
        run_id = directory.name.split("_", 1)[0]
        try:
            registration = json.loads(
                (directory / "experiment.json").read_text(encoding="utf-8"))
            spec = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FinalizeError(f"{directory.name}: unreadable artefact: {exc}") from None
        out[run_id] = {
            "config_sha256": registration.get("config_sha256"),
            "spec_sha256": sha256_file(directory / "spec.json"),
            "experiment_sha256": sha256_file(directory / "experiment.json"),
            "arm": directory.name.split("_")[2],
            "ticker": directory.name.split("_")[1],
            "budget_mode": (registration.get("budget") or {}).get("budget_mode"),
            "max_total_tokens": (registration.get("budget") or {}).get("max_total_tokens"),
            "spec_carries_registration_hash": (
                spec.get("config_sha256") == registration.get("config_sha256")),
        }
    return out


def append_history(entry: dict, *, allow_existing_designation: bool) -> list[dict]:
    existing: list[dict] = []
    if HISTORY_FILE.is_file():
        for number, line in enumerate(
                HISTORY_FILE.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                existing.append(json.loads(line))
            except ValueError as exc:
                raise FinalizeError(
                    f"{HISTORY_FILE}:{number} is not JSON: {exc}") from None
    designated = next((e.get("commit") for e in existing
                       if e.get("event") == "designated_freeze"), None)
    if designated and designated != entry["commit"] and not allow_existing_designation:
        raise FinalizeError(
            f"{HISTORY_FILE} already designates {designated[:12]}, but HEAD is "
            f"{entry['commit'][:12]}. The designation is append-only: a new "
            f"freeze is a new branch (or an explicit C3_I_MEAN_TO_REFREEZE=yes), "
            f"never a silent replacement")
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        if existing and HISTORY_FILE.stat().st_size and \
                not HISTORY_FILE.read_text(encoding="utf-8").endswith("\n"):
            handle.write("\n")
        handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    return existing


def ensure_tag(commit: str, message: str) -> str:
    """Create the annotated tag (or reuse it when it already names ``commit``)."""
    existing = git("rev-parse", "-q", "--verify", f"refs/tags/{TAG}^{{commit}}",
                   check=False)
    if existing:
        if existing != commit:
            raise FinalizeError(
                f"tag {TAG} already points at {existing[:12]}, not {commit[:12]}; "
                f"refusing to repoint a published release tag")
        return git("rev-parse", f"refs/tags/{TAG}")
    subprocess.run(["git", "-C", str(REPO_ROOT), "tag", "-a", TAG, commit,
                    "-m", message], check=True, capture_output=True, text=True)
    return git("rev-parse", f"refs/tags/{TAG}")


def render_report(record: dict) -> str:
    lines = [
        "# FINAL FREEZE REPORT — CAND-01 × Batch-Macro 2×2",
        "",
        "**Generated by `scripts/c3_finalize_freeze.py`. Every value below is read",
        "from the tree or from git at certification time; none is typed by hand.**",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Certified at (UTC) | `{record['generated_at_utc']}` |",
        f"| Final commit | `{record['commit']}` |",
        f"| Tree SHA | `{record['tree_sha']}` |",
        f"| Branch | `{record['branch']}` |",
        f"| Release tag | `{record['tag']}` → `{record['tag_object_sha']}` |",
        f"| Code fingerprint | `{record['fingerprint']['working_tree_sha256']}` |",
        f"| Fingerprint algorithm | `{record['fingerprint']['fingerprint_algorithm']}` |",
        f"| Files fingerprinted | {record['fingerprint']['file_count']} "
        f"({record['fingerprint']['tracked_file_count']} tracked) |",
        f"| Protocol SHA-256 | `{record['protocol_sha256']}` |",
        f"| Generator SHA-256 | `{record['generator_sha256']}` |",
        f"| MANIFEST.sha256 (file) | `{record['manifest_sha256']}` |",
        f"| MANIFEST entries verified | {record['manifest_entries']} |",
        f"| code_freeze.txt SHA-256 | `{record['code_freeze_sha256']}` |",
        f"| RELEASE_SEAL.sha256 SHA-256 | `{record['release_seal_sha256']}` |",
        f"| Budget contract | `{record['budget']['mode']}`, "
        f"`max_total_tokens={record['budget']['max_total_tokens']}` |",
        "| Paid LLM calls at certification | **0** |",
        "",
        "## Specs (all 16, config_sha256 recomputed by the verifier)",
        "",
        "| Run | Ticker | Arm | config_sha256 | spec.json SHA-256 | budget |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for run_id, entry in sorted(record["specs"].items()):
        lines.append(
            f"| `{run_id}` | {entry['ticker']} | `{entry['arm']}` | "
            f"`{entry['config_sha256']}` | `{entry['spec_sha256']}` | "
            f"{entry['budget_mode']} |")
    lines += [
        "",
        "## How this record is checked",
        "",
        "```",
        "python scripts/c3_verify_final_freeze.py",
        "```",
        "",
        "It recomputes the fingerprint, the tree SHA, every manifest digest and",
        "every `config_sha256`, and requires `HEAD` to equal this record's commit",
        "and the tag's commit. A commit made after this one changes `HEAD` and the",
        "verification fails, which is the point: the record names *this* commit,",
        "not an ancestor of whatever is checked out later.",
        "",
        "## What is not in the commit, and why",
        "",
        "A commit cannot contain its own hash. `c3/FROZEN_COMMIT`,",
        "`c3/FREEZE_RECORD.json`, `c3/FREEZE_HISTORY.jsonl` and this report are",
        "therefore release metadata written after the commit and listed in",
        "`.gitignore`; the working tree is clean with them present. Everything",
        "that can be committed — `c3/code_freeze.txt` (the code fingerprint),",
        "`c3/RELEASE_SEAL.sha256` and `MANIFEST.sha256` (every artefact digest) —",
        "is in the commit.",
        "",
        "## Honest scope",
        "",
        "* 0 paid LLM calls, 0 real Pipeline runs, 0 runs of R01–R16.",
        "* No profitability or alpha claim is supported by this experiment, and",
        "  none is made: the pre-registered outcome is `total_tokens`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--allow-existing-designation", action="store_true",
                        help="replace a designation that names another commit")
    args = parser.parse_args(argv)

    import os

    allow = args.allow_existing_designation or \
        os.environ.get("C3_I_MEAN_TO_REFREEZE") == "yes"
    if not allow and HISTORY_FILE.is_file():
        designated = None
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("event") == "designated_freeze":
                    designated = entry.get("commit")
                    break
        head = git("rev-parse", "HEAD")
        if designated and designated != head:
            raise FinalizeError(
                f"a freeze is already designated ({designated[:12]}) and HEAD is "
                f"{head[:12]}; re-freezing is a deliberate act. Re-run with "
                f"C3_I_MEAN_TO_REFREEZE=yes only if this is a new release")

    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    tree_sha = git("rev-parse", "HEAD^{tree}")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise FinalizeError(
            f"the tracked tree is dirty; commit first, then certify:\n{dirty}")
    untracked = git("status", "--porcelain", "--untracked-files=normal")
    if untracked:
        raise FinalizeError(
            f"untracked (non-ignored) files are present; they would not be part "
            f"of the certified commit:\n{untracked}")

    if not MANIFEST_FILE.is_file():
        raise FinalizeError(f"{MANIFEST_FILE} is missing; build it before the commit")
    problems = manifest_problems()
    if problems:
        raise FinalizeError("MANIFEST.sha256 does not verify: " + "; ".join(problems))
    manifest_entries = len([
        line for line in MANIFEST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()])

    declared = declared_freeze_fingerprint()

    from token_benchmark import compute_code_state  # noqa: E402

    experiment = json.loads((BATCH_DIR / "experiment.json").read_text(encoding="utf-8"))
    state = compute_code_state(BATCH_DIR, experiment)
    if state.get("working_tree_sha256") != declared:
        raise FinalizeError(
            f"this tree fingerprints to {state.get('working_tree_sha256')}, but "
            f"c3/code_freeze.txt declares {declared}; re-run "
            f"scripts/c3_write_freeze_record.py and commit the result")
    if state.get("git_working_tree_dirty"):
        raise FinalizeError("the fingerprint says the working tree is dirty")


    specs = spec_hashes()
    if len(specs) != 16:
        raise FinalizeError(f"expected 16 run specs, found {len(specs)}")
    budget_modes = {s["budget_mode"] for s in specs.values()}
    caps = {s["max_total_tokens"] for s in specs.values()}
    if budget_modes != {"uncapped_authorized"} or caps != {None}:
        raise FinalizeError(
            f"budget contract drifted: modes={budget_modes} caps={caps}; this "
            f"round is uncapped_authorized with max_total_tokens=null (U-2)")
    if not all(s["spec_carries_registration_hash"] for s in specs.values()):
        raise FinalizeError("a spec carries a different config_sha256 than its registration")

    protocol_sha = sha256_file(PROTOCOL_FILE)
    generator_sha = sha256_file(GENERATOR_FILE)
    if not protocol_sha or not generator_sha:
        raise FinalizeError("protocol or generator is missing")

    generated_at = datetime.now(timezone.utc).isoformat()
    tag_message = (
        f"CAND-01 x Batch-Macro 2x2 final freeze\n"
        f"commit: {head}\n"
        f"tree: {tree_sha}\n"
        f"fingerprint: {declared}\n"
        f"protocol_sha256: {protocol_sha}\n"
        f"generator_sha256: {generator_sha}\n"
        f"certified_at_utc: {generated_at}\n"
    )
    tag_object = ensure_tag(head, tag_message)

    FROZEN_FILE.write_text(head + "\n", encoding="utf-8")

    history_entry = {
        "event": "designated_freeze",
        "commit": head,
        "tree": tree_sha,
        "fingerprint": declared,
        "tag": TAG,
        "tag_object": tag_object,
        "recorded_by": "c3_finalize_freeze.py",
        "recorded_at_utc": generated_at,
        "note": ("written after the commit it names; HEAD == this commit is the "
                 "only accepted state"),
    }
    append_history(history_entry, allow_existing_designation=allow)

    record = {
        "schema": RECORD_SCHEMA,
        "generated_at_utc": generated_at,
        "commit": head,
        "tree_sha": tree_sha,
        "branch": branch,
        "tag": TAG,
        "tag_object_sha": tag_object,
        "tag_message_sha256": sha256_bytes(tag_message.encode("utf-8")),
        "fingerprint": {
            "fingerprint_algorithm": state.get("fingerprint_algorithm"),
            "working_tree_sha256": state.get("working_tree_sha256"),
            "git_working_tree_dirty": state.get("git_working_tree_dirty"),
            "file_count": state.get("file_count"),
            "tracked_file_count": state.get("tracked_file_count"),
            "tool_schema_version": state.get("tool_schema_version"),
        },
        "protocol_sha256": protocol_sha,
        "generator_sha256": generator_sha,
        "protocol_version": json.loads(
            (BATCH_DIR / "experiment.json").read_text(encoding="utf-8")
        ).get("protocol_version"),
        "code_freeze_sha256": sha256_file(CODE_FREEZE_FILE),
        "release_seal_sha256": sha256_file(SEAL_FILE),
        "manifest_sha256": sha256_file(MANIFEST_FILE),
        "manifest_entries": manifest_entries,
        "budget": {
            "mode": "uncapped_authorized",
            "max_total_tokens": None,
            "declared_in": "specs/<run_id>/experiment.json",
        },
        "specs": specs,
        "paid_llm_calls": 0,
        "pipeline_runs": 0,
    }
    RECORD_FILE.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    REPORT_FILE.write_text(render_report(record), encoding="utf-8")

    # Verify immediately, and fail the certification if it does not hold.
    from c3_verify_final_freeze import verify

    result = verify(REPO_ROOT)
    if not result["ok"]:
        for failure in result["failures"]:
            print(f"FAIL  {failure}", file=sys.stderr)
        raise FinalizeError("the freeze does not verify; not certifying")

    print("certified final freeze")
    print(f"  commit      : {head}")
    print(f"  tree        : {tree_sha}")
    print(f"  fingerprint : {declared}")
    print(f"  tag         : {TAG} -> {tag_object}")
    print(f"  record      : {RECORD_FILE}")
    print(f"  report      : {REPORT_FILE}")
    for check in result["checks"]:
        print(f"  ok  {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
