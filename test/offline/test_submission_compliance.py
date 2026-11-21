"""Enforce the offline course-compliance gate from pytest.

The same script runs as a dedicated CI job; keeping a pytest wrapper means a
developer cannot get a green local suite while the submission artifacts are
missing or broken. The validator never uses the network, an LLM, or a paid API.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VALIDATOR = REPO_ROOT / "scripts/validate/validate_submission.py"


@pytest.mark.unit
def test_the_submission_compliance_validator_passes():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "PASS: submission compliance" in output
