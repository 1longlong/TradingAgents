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
BATCH_DIR = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import token_benchmark as tb  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def main() -> int:
    experiment = json.loads((BATCH_DIR / "experiment.json").read_text(encoding="utf-8"))
    state = tb.compute_code_state(BATCH_DIR, experiment)
    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))

    text = f"""PLAN C3 — CODE FREEZE RECORD
generated: {state.get('timestamp_utc')}

This file cannot name the commit it is committed in (a commit cannot contain
its own hash). It therefore records the code fingerprint, which is identical
before and after the freeze commit, plus the commit it was written on.

Branch              : {branch}
Commit at write time: {head}
Working tree at write: {'DIRTY' if dirty else 'clean'}

Fingerprint (the authority -- the gate recomputes this and refuses on a mismatch)
  fingerprint_algorithm : {state.get('fingerprint_algorithm')}
  working_tree_sha256   : {state.get('working_tree_sha256')}
  git_working_tree_dirty: {state.get('git_working_tree_dirty')}
  files fingerprinted   : {state.get('file_count')} ({state.get('tracked_file_count')} tracked)
  tool_schema_version   : {state.get('tool_schema_version')}

Runtime
  Python        : {state.get('python_version')}
  Isolated venv : /tmp/opencode/expvenv  (never the shared developer venv)
  Provider      : openai_compatible
  Endpoint      : https://llm.cs.cityu.edu.hk/v1
  Models        : CS5351/DeepSeek-V4-Flash (quick and deep)
  langgraph     : {(state.get('package_versions') or {}).get('langgraph')}
  langchain-core: {(state.get('package_versions') or {}).get('langchain-core')}
  max_total_tokens: null  (uncapped; usage recorded in full, never estimated)

Invocation (every run)
  TZ=UTC PYTHONSAFEPATH=1 PYTHONPATH={REPO_ROOT} \\
    /tmp/opencode/expvenv/bin/python scripts/c3_preflight_gate.py ...
  TZ=UTC PYTHONSAFEPATH=1 PYTHONPATH={REPO_ROOT} \\
    /tmp/opencode/expvenv/bin/python scripts/token_benchmark.py ...

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
  B-03  MANIFEST.sha256 and spec_body_sha256 went stale.  FIXED (verify 94/94).
  B-r2  --dry-run skipped the pre-flight and accepted s2_downstream=false;
        duplicate run IDs collapsed silently; a refused run rewrote
        code_state.json.  FIXED.
  C-01  the gate recomputed the hash but never compared spec fields.  FIXED.
  apply_cityu_env: the named secrets file now wins over the ambient
        environment (an unreachable-endpoint probe was dialling the real paid
        endpoint).  FIXED.

Known limitations carried into the run (documented, not silent)
  L-2  Finnhub news is fetched serially per day chunk.
  L-3  a cwd-relative test remains.
  L-5  raw vendor usage payloads are not preserved, only the parsed totals.
  L-6  PIT is day granular on the news window start.
  get_insider_transactions has no Finnhub implementation and would raise
        ValueError, but it is not bound to any of the three run analysts.
"""
    out = BATCH_DIR / "c3" / "code_freeze.txt"
    out.write_text(text, encoding="utf-8")
    # The seal must be written *with* the record, after it: the seal hashes the
    # record, and nothing may modify the record afterwards without breaking it.
    # Doing these two steps by hand allowed a record to be regenerated while the
    # seal kept the old digest, which made every gate run fail on a correct
    # release. One step, one consistent set.
    import hashlib

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
