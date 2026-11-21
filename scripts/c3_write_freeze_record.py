#!/usr/bin/env python3
"""Write ``c3/code_freeze.txt`` for whatever tree is checked out right now.

Run this **after** the freeze commit, from the clean frozen tree::

    TZ=UTC PYTHONSAFEPATH=1 PYTHONPATH=<root> python scripts/c3_write_freeze_record.py

The script also writes ``c3/RELEASE_SEAL.sha256``, which pins the record and
the credential audit to one issuance; the two must never be regenerated apart.
Then commit both, and finally write ``c3/FROZEN_COMMIT`` (untracked) with
``git rev-parse HEAD`` -- it cannot be sealed, because it names the commit the
seal is committed in.

Why the record is generated rather than authored
------------------------------------------------
Audit A-07 found a freeze record that named ``99f6709`` while the tree was at
``b00dd00``: the file had been hand-edited, and hand-edited provenance drifts.
The commit cannot be named inside itself, so the record carries the *code
fingerprint* -- which is identical before and after the freeze commit -- plus
the commit of its parent. ``c3_preflight_gate.check_fingerprint_matches_record``
then proves the record describes the tree being run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BATCH_REL = "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
BATCH_REL = __import__("os").environ.get("C3_BATCH_REL", _DEFAULT_BATCH_REL).strip("/")
BATCH_DIR = REPO_ROOT / BATCH_REL
# Audit A-00: pin this checkout ahead of the shared editable install, exactly as
# ``token_benchmark.py`` does, so the fingerprint describes the tree that is
# being released rather than the main checkout.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import token_benchmark as tb  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def _refuse_to_overwrite_sealed_release() -> None:
    """A sealed release is replaced only on purpose, never by re-running.

    The record is *generated*, so running this script again silently re-certifies
    whatever tree is checked out. Audit B round 4 (B-15) verified the
    consequence directly: edit a registration, commit, re-run this writer, and
    the gate printed "GATE PASSED -- safe to spend money" for a different
    experiment. Refusing by default makes the dangerous invocation impossible
    to perform by accident, which is the same lesson the legacy launcher taught
    (``INCIDENT_20261115_legacy_launcher.md``).
    """
    import os

    old = BATCH_DIR / "c3" / "RELEASE_SEAL.sha256"
    if not old.is_file():
        return
    if os.environ.get("C3_I_MEAN_TO_RESEAL") == "yes":
        print("!! re-sealing an existing release on explicit instruction "
              "(C3_I_MEAN_TO_RESEAL=yes)")
        return
    print("REFUSED: a sealed release already exists and this script would "
          "silently re-certify the current tree.", file=sys.stderr)
    print(f"  existing seal: {old}", file=sys.stderr)
    print("  Re-sealing is legitimate only on a deliberate release. If this "
          "is one, re-run with:", file=sys.stderr)
    print("    C3_I_MEAN_TO_RESEAL=yes python scripts/c3_write_freeze_record.py",
          file=sys.stderr)
    raise SystemExit(3)


def main() -> int:
    _refuse_to_overwrite_sealed_release()
    experiment = json.loads((BATCH_DIR / "experiment.json").read_text(encoding="utf-8"))
    state = tb.compute_code_state(BATCH_DIR, experiment)
    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))

    # Every digest below is read from the tree here; none is typed by hand.
    import hashlib

    def _digest(relative: str) -> str:
        return hashlib.sha256((BATCH_DIR / relative).read_bytes()).hexdigest()

    protocol_sha = _digest(__import__("os").environ.get(
    "C3_PROTOCOL_NAME", "CAND01_BATCH_2X2_PROTOCOL_V2.md"))
    generator_sha = hashlib.sha256(
        (REPO_ROOT / __import__("os").environ.get(
            "C3_GENERATOR", "scripts/gen_cand01_batch_16run_specs_v2.py")).read_bytes()
    ).hexdigest()
    spec_lines = []
    budget_modes = set()
    caps = set()
    for directory in sorted((BATCH_DIR / "specs").iterdir()):
        if not directory.is_dir():
            continue
        registration = json.loads(
            (directory / "experiment.json").read_text(encoding="utf-8"))
        budget = registration.get("budget") or {}
        budget_modes.add(budget.get("budget_mode"))
        caps.add(budget.get("max_total_tokens"))
        spec_lines.append(
            f"  {directory.name:<16} config_sha256={registration.get('config_sha256')} "
            f"spec_sha256={hashlib.sha256((directory / 'spec.json').read_bytes()).hexdigest()}")
    if budget_modes != {"uncapped_authorized"} or caps != {None}:
        print(f"REFUSED: budget contract drifted: modes={budget_modes} caps={caps}",
              file=sys.stderr)
        raise SystemExit(4)

    text = f"""PLAN C3 — CODE FREEZE RECORD
generated: {state.get('timestamp_utc')}
schema    : 2

This file cannot name the commit it is committed in (a commit cannot contain
its own hash). The authority is therefore the **code fingerprint**, which is
identical before and after the freeze commit, plus the digest of every artefact
the study depends on. The commit, the tree SHA and the release tag are recorded
after the commit by ``scripts/c3_finalize_freeze.py`` (``c3/FREEZE_RECORD.json``)
and checked by ``scripts/c3_verify_final_freeze.py``.

Branch              : {branch}
Commit at write time: {head}   (the parent of the freeze commit, by construction)
Working tree at write: {'DIRTY' if dirty else 'clean'}

Fingerprint (the authority -- the gate recomputes this and refuses on a mismatch)
  fingerprint_algorithm : {state.get('fingerprint_algorithm')}
  working_tree_sha256   : {state.get('working_tree_sha256')}
  git_working_tree_dirty: {state.get('git_working_tree_dirty')}
  files fingerprinted   : {state.get('file_count')} ({state.get('tracked_file_count')} tracked)
  tool_schema_version   : {state.get('tool_schema_version')}

Artefact digests (SHA-256, recomputed by the verifier)
  protocol_sha256 : {protocol_sha}
  generator_sha256: {generator_sha}
  MANIFEST.sha256 : see the manifest; every entry is verified

Spec hashes (16 registered runs)
{chr(10).join(spec_lines)}

Budget contract (U-2)
  budget_mode     : uncapped_authorized   (explicit; a null cap is never inferred)
  max_total_tokens: null

Runtime
  Python        : {state.get('python_version')}
  Interpreter   : {sys.executable}
  Provider      : openai_compatible
  Endpoint      : https://llm.cs.cityu.edu.hk/v1
  Models        : CS5351/DeepSeek-V4-Flash (quick and deep)
  langgraph     : {(state.get('package_versions') or {}).get('langgraph')}
  langchain-core: {(state.get('package_versions') or {}).get('langchain-core')}

Invocation (every run)
  TZ=UTC PYTHONSAFEPATH=1 python scripts/c3_preflight_gate.py ...
  TZ=UTC PYTHONSAFEPATH=1 python scripts/token_benchmark.py ...

The scripts pin their own repository root on ``sys.path`` (audit A-00), so the
documented invocation runs this tree even though the shared ``.venv`` installs
``tradingagents`` as an editable package pointing at another checkout. The
spending child verifies the import root again and refuses a mismatch.

Remediation history (each audit blocker, fixed before any paid call)
  A-02  finnhub_news kept the OLDEST articles instead of the newest; live NVDA
        showed news newest 2026-09-16 while all in-window articles from the
        final two days were dropped.  FIXED, plus truncation is now disclosed
        (A-02b).
  A-01  a stale worktree .env (40-char FRED key) was loadable via
        find_dotenv(usecwd=True).  FIXED (removed).
  A-09  ~/.env_secrets carried no FINNHUB_API_KEY, so the wrapper path would
        render AUTH_MISSING news.  FIXED and verified live.
  B-01  prepare_run_spec dropped 'switches', so every arm would have run AB.
        FIXED.
  B-02  config_sha256 was never recomputed; tampered definitions ran.  FIXED.
  B-03  MANIFEST.sha256 and spec_body_sha256 went stale.  FIXED.
  B-r2  --dry-run skipped the pre-flight and accepted s2_downstream=false;
        duplicate run IDs collapsed silently; a refused run rewrote
        code_state.json.  FIXED.
  C-01  the gate recomputed the hash but never compared spec fields.  FIXED.
  U-1   agrees_with_telemetry was computed and never consumed; a conflicting
        run still reported valid=True.  FIXED: MISSING / INCOMPLETE / MISMATCH
        are now invalid, and an unknown total is null, never 0.
  U-2   max_total_tokens=null was indistinguishable from a missing or broken
        budget file.  FIXED: budget_mode=uncapped_authorized is required.
  A-00  the gate imported the main checkout from any cwd.  FIXED: scripts pin
        their own repo root; the child re-verifies the import root.
  Freeze the designation named an ancestor of HEAD, so no run could pass.
        FIXED: the designation is written after the commit and must equal HEAD.
  apply_cityu_env: the named secrets file now wins over the ambient
        environment.  FIXED.

Known limitations carried into the run (documented, not silent)
  L-2  Finnhub news is fetched serially per day chunk (performance).
  L-3  no longer applies: the cwd-relative test was made path-independent.
  L-4  some module docstrings still describe the superseded news architecture.
  L-6  PIT is day granular on the news window start (declared convention).
  L-7  n = 4, exploratory; no significance claim is supported.
  L-8  V1 config_sha256 values are permanently void; V1 is not a numeric baseline.
  L-9  the V1 manifest's stale R01 spec hash is historical and untouched.
  L-10 s2_downstream has no OFF implementation; it is refused when false.
  L-11 global/macro news is disabled in every arm; no global-news effect is in
        scope. ``get_insider_transactions`` has no Finnhub implementation and is
        not bound to any of the three run analysts.
"""
    out = BATCH_DIR / "c3" / "code_freeze.txt"
    out.write_text(text, encoding="utf-8")
    # The seal must be written *with* the record, after it: the seal hashes the
    # record, and nothing may modify the record afterwards without breaking it.
    # Doing these two steps by hand allowed a record to be regenerated while the
    # seal kept the old digest, which made every gate run fail on a correct
    # release. One step, one consistent set.
    c3 = BATCH_DIR / "c3"
    sealed = [c3 / "code_freeze.txt", c3 / "env_credential_audit.txt"]
    seal_lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(BATCH_DIR).as_posix()}"
        for path in sealed if path.is_file()
    ]
    (c3 / "RELEASE_SEAL.sha256").write_text("\n".join(seal_lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"wrote {c3 / 'RELEASE_SEAL.sha256'} ({len(seal_lines)} files)")
    print(f"  fingerprint: {state.get('working_tree_sha256')}")
    print(f"  commit     : {head}")
    print(f"  dirty      : {state.get('git_working_tree_dirty')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
