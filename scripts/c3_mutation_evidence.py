#!/usr/bin/env python3
"""Mutation evidence for the final-freeze round.

Each mutation re-introduces one defect this round claims to have fixed; the
named tests must fail. The file is restored and its SHA-256 re-verified before
the next mutation starts, so a failed restore can never be mistaken for a pass.

This is evidence, not a test: it mutates tracked source, so it is run by hand
before the freeze and its output is committed under ``logs/``.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

MUTATIONS = [
    (
        "M1 U-1: stop consuming the usage verdict",
        "scripts/token_benchmark.py",
        'if verdict["state"] != USAGE_VALID:\n        invalid_reason = invalid_reason or verdict["invalid_reason"]',
        'if False:\n        invalid_reason = invalid_reason or verdict["invalid_reason"]',
        "tests/test_c3_final_freeze.py::TestUsageVerdict",
    ),
    (
        "M2 U-1: publish an unknown total as 0",
        "scripts/token_benchmark.py",
        'if verdict["state"] == USAGE_MISSING:\n        inp = out = None',
        'if verdict["state"] == USAGE_MISSING:\n        inp = out = 0',
        "tests/test_c3_final_freeze.py::TestUsageVerdict::test_missing_usage_is_missing_and_totals_are_null_not_zero",
    ),
    (
        "M3 U-2: accept a budget block with no mode",
        "scripts/token_benchmark.py",
        'if "budget_mode" not in budget:',
        'if False:',
        "tests/test_c3_final_freeze.py::TestBudgetContract",
    ),
    (
        "M4 A-00: drop the gate script's repo-root pin",
        "scripts/c3_preflight_gate.py",
        '_THIS_ROOT = Path(__file__).resolve().parents[1]\nif str(_THIS_ROOT) not in sys.path:\n    sys.path.insert(0, str(_THIS_ROOT))',
        '_THIS_ROOT = Path(__file__).resolve().parents[1]',
        "tests/test_c3_final_freeze.py::TestImportRootIsolation::test_the_gate_script_imports_its_own_repository",
    ),
    (
        "M5 dry run: rehearse without building the graph",
        "scripts/token_benchmark.py",
        '    "graph_rehearsed": True,',
        '    "graph_rehearsed": False,',
        "tests/test_c3_final_freeze.py::TestDryRunRehearsal::test_a_dry_run_builds_the_real_spec_and_graph",
    ),
    (
        "M6 effective_config: write without verifying",
        "scripts/token_benchmark.py",
        "    verify_effective_config(payload, spec,\n                            expected_root=spec.get(\"experiment_root\"))",
        "    pass",
        "tests/test_c3_final_freeze.py::TestEffectiveConfig::test_the_writer_verifies_before_it_writes",
    ),
    (
        "M7 L-5: accept a negative token count",
        "tradingagents/observability.py",
        "if isinstance(value, int) and value >= 0:\n            return value",
        "if isinstance(value, int):\n            return value",
        "tests/test_c3_final_freeze.py::TestRawUsageIsPreserved::test_a_negative_token_count_is_treated_as_unreported",
    ),
    (
        "M8 L-5: an empty run reports complete attribution",
        "tradingagents/observability.py",
        "has_events = (total_llm + run_totals[\"tool_calls\"]) > 0",
        "has_events = True",
        "tests/test_c3_final_freeze.py::TestEmptyRunIsNotComplete",
    ),
    (
        "M9 freeze: the verifier stops requiring HEAD == the record",
        "scripts/c3_verify_final_freeze.py",
        'if record.get("commit") != head:',
        'if False:',
        "tests/test_c3_final_freeze.py::TestFreezeDesignation::test_the_verifier_requires_head_to_equal_the_record",
    ),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    failures = 0
    for name, relative, old, new, tests in MUTATIONS:
        path = ROOT / relative
        before = sha(path)
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"SETUP FAIL {name}: anchor found {text.count(old)} times")
            failures += 1
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        try:
            result = subprocess.run(
                [PY, "-m", "pytest", tests, "-q", "--no-header", "-p", "no:cacheprovider"],
                cwd=str(ROOT), capture_output=True, text=True,
                env={**__import__("os").environ, "TZ": "UTC"})
        finally:
            path.write_text(text, encoding="utf-8")
            after = sha(path)
        status = "CAUGHT" if result.returncode != 0 else "MISSED"
        if result.returncode == 0:
            failures += 1
        tail = [line for line in result.stdout.splitlines() if "passed" in line
                or "failed" in line][-1:] or [""]
        print(f"{status:6} {name}  [{tail[0].strip()}]")
        print(f"       {relative}: {before[:16]}… -> restored {after[:16]}… "
              f"{'OK' if before == after else 'MISMATCH'}")
        if before != after:
            failures += 1
    print()
    print(f"{len(MUTATIONS) - failures}/{len(MUTATIONS)} mutations caught and "
          f"restored byte-identically")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
