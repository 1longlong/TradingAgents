"""Regression tests for the two prompt lineages in the submission validator.

Release coding-agent startup prompts are governance artifacts
(``version``/``phase``/``role``/``binding_rules``), while the archived Market
Analyst files are historical runtime-prompt snapshots with their own provenance
(``source_commit``/``source_file``/``historical_usage_status``). The validator
must require both, read only top-level metadata, and fail on a wrong lineage
instead of silently accepting it.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts/validate/validate_submission.py"

STARTUP = (
    "prompts/prompt_v1.0.yaml",
    "prompts/prompt_v1.1.yaml",
    "prompts/prompt_v1.2.yaml",
    "prompts/prompt_v1.3.yaml",
)
ARCHIVAL = (
    "prompts/archive/market-analyst-rc1-v1.0.yaml",
    "prompts/archive/market-analyst-final-v1.1.yaml",
)


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_submission", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_submission = _load_validator()


def _copy(root: Path, rels: tuple[str, ...]) -> None:
    for rel in rels:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A prompt tree with both real lineages, with ROOT pointed at it."""
    _copy(tmp_path, STARTUP + ARCHIVAL)
    monkeypatch.setattr(validate_submission, "ROOT", tmp_path)
    return tmp_path


def _errors() -> list[str]:
    errors: list[str] = []
    validate_submission.check_prompts(errors)
    return errors


def test_valid_release_startup_prompts(sandbox):
    assert _errors() == []


def test_valid_archival_snapshots(sandbox):
    assert _errors() == []


def test_namespaces_are_distinct_and_complete():
    assert set(validate_submission.STARTUP_PROMPT_FILES).isdisjoint(
        validate_submission.ARCHIVAL_PROMPT_FILES
    )
    assert validate_submission.STARTUP_PROMPT_FILES == STARTUP
    assert validate_submission.ARCHIVAL_PROMPT_FILES == ARCHIVAL
    assert all(path.startswith("prompts/") for path in STARTUP + ARCHIVAL)


def test_missing_startup_prompt_fails(sandbox):
    (sandbox / "prompts/prompt_v1.3.yaml").unlink()
    errors = _errors()
    assert any(
        "prompt_v1.3.yaml" in error and "required Release startup prompt is missing" in error
        for error in errors
    ), errors


def test_missing_archival_snapshot_fails(sandbox):
    (sandbox / "prompts/archive/market-analyst-final-v1.1.yaml").unlink()
    errors = _errors()
    assert any(
        "market-analyst-final-v1.1.yaml" in error
        and "required Market Analyst archive is missing" in error
        for error in errors
    ), errors


def test_blank_startup_version_fails(sandbox):
    path = sandbox / "prompts/prompt_v1.3.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r"(?m)^version:.*$", 'version: ""', text, count=1), encoding="utf-8")
    errors = _errors()
    assert any("missing or empty 'version'" in error for error in errors), errors


def test_missing_archival_source_commit_fails(sandbox):
    path = sandbox / "prompts/archive/market-analyst-rc1-v1.0.yaml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text(
        "".join(line for line in lines if not line.startswith("source_commit:")),
        encoding="utf-8",
    )
    errors = _errors()
    assert any("missing or empty 'source_commit'" in error for error in errors), errors


def test_invalid_yaml_fails(sandbox):
    (sandbox / "prompts/prompt_v1.3.yaml").write_text(
        "version: [unclosed\n", encoding="utf-8"
    )
    errors = _errors()
    assert any("YAML parse failed" in error for error in errors), errors


def test_non_mapping_document_fails(sandbox):
    (sandbox / "prompts/prompt_v1.3.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    errors = _errors()
    assert any("top-level document must be a mapping" in error for error in errors), errors


def test_archive_content_in_startup_path_is_wrong_lineage(sandbox):
    source = sandbox / "prompts/archive/market-analyst-rc1-v1.0.yaml"
    (sandbox / "prompts/prompt_v1.3.yaml").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    errors = _errors()
    assert any("wrong prompt lineage" in error and "Market Analyst archive" in error for error in errors), errors


def test_startup_content_in_archive_path_is_wrong_lineage(sandbox):
    source = sandbox / "prompts/prompt_v1.3.yaml"
    (sandbox / "prompts/archive/market-analyst-final-v1.1.yaml").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    errors = _errors()
    assert any("wrong prompt lineage" in error and "Release startup prompt" in error for error in errors), errors


def test_nested_metadata_does_not_satisfy_top_level_requirements(sandbox):
    """A same-named key nested under another mapping must not count."""
    (sandbox / "prompts/prompt_v1.3.yaml").write_text(
        "metadata:\n"
        "  version: v1.3\n"
        "  phase: implementation\n"
        "  role: coding-agent\n"
        "  binding_rules: [one]\n",
        encoding="utf-8",
    )
    errors = _errors()
    for key in ("version", "phase", "role", "binding_rules"):
        assert any(f"missing or empty {key!r}" in error for error in errors), (key, errors)
