"""Dynamic requirement-to-test traceability check."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = REPO_ROOT / "docs" / "req" / "requirements.yaml"
TEST_ROOT = REPO_ROOT / "test" / "offline"


def _requirement_ids() -> list[str]:
    data = yaml.safe_load(REQUIREMENTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    ids = [item["id"] for item in data if isinstance(item, dict) and "id" in item]
    assert ids
    return ids


def _test_references() -> dict[str, set[str]]:
    references: dict[str, set[str]] = {}
    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            text = f"{node.name}\n{ast.get_docstring(node) or ''}"
            for match in re.finditer(r"\b(?:FR|INV|NFR)-\d+\b", text):
                references.setdefault(match.group(0), set()).add(
                    f"{path.relative_to(REPO_ROOT)}::{node.name}"
                )
    return references


def test_every_requirement_id_has_at_least_one_test():
    """[FR-01] Every requirement in the registry is traced to a test."""
    requirements = _requirement_ids()
    references = _test_references()
    missing = [requirement for requirement in requirements if not references.get(requirement)]
    assert missing == [], f"requirements without a referencing test: {missing}"


def test_traceability_references_are_real_test_functions():
    """[FR-01] Requirement references point at collected test functions."""
    references = _test_references()
    assert references
    for requirement, tests in references.items():
        assert tests, requirement
        assert all("::test_" in test for test in tests)
