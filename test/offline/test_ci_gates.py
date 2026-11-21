"""Positive and negative checks for verification-constraints.md sections 1, 5, 6.

Fixtures are synthetic test data, never product requirements or human approvals.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from test import ci_gates as gates

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registry(tmp_path):
    (tmp_path / "docs/req").mkdir(parents=True)
    (tmp_path / "docs/architecture").mkdir()
    (tmp_path / "source.py").write_text("# fixture\n")
    (tmp_path / "docs/architecture/invariants.md").write_text("")
    (tmp_path / "docs/req/req-schema.json").write_text((ROOT / "docs/req/req-schema.json").read_text())
    data = {"schema_version": "1.0", "project": {
        "name": "fixture", "purpose": "Schema test only", "baseline_ref": "release",
        "baseline_commit": "a" * 40, "scope": ["fixture"], "out_of_scope": []},
        "requirements": [{"id": "REQ-A01", "type": "functional", "statement": "fixture",
            "priority": "must", "priority_tradeoff": "fixture", "origin": "baseline",
            "sources": [{"kind": "repository", "reference": "source.py", "locator": "fixture",
                         "rationale": "Test fixture only"}], "status": "draft", "fit_criteria": [{
                "id": "FC-A01-01", "metric": "violations", "unit": "violations",
                "comparison": "eq", "threshold": 0, "verification": {"method": "pytest",
                    "mode": "offline", "command": "not executed", "evidence": ["planned.py"]}}]}]}

    def write(value=data):
        (tmp_path / "docs/req/requirements.yaml").write_text(yaml.safe_dump(value))
        return gates.validate_registry(tmp_path)

    return tmp_path, data, write


def test_schema_valid_draft_does_not_execute_verification(registry):
    _, data, write = registry
    assert write() == data


def test_schema_empty_registry_blocks(registry):
    root, _, _ = registry
    (root / "docs/req/requirements.yaml").write_text("")
    with pytest.raises(gates.GateError, match="incomplete"):
        gates.validate_registry(root)


def test_duplicate_yaml_keys_block():
    with pytest.raises(gates.GateError, match="Duplicate YAML key"):
        gates.load_yaml("requirements: []\nrequirements: []\n")


@pytest.mark.parametrize("mutation,message", [
    (lambda d: d["requirements"][0].update(type="invariant", priority="could"), "invalid"),
    (lambda d: d["requirements"][0].update(depends_on=["REQ-A02"]), "Unknown requirement"),
    (lambda d: d["requirements"][0].update(depends_on=["REQ-A01"]), "cycle"),
    (lambda d: d["requirements"][0]["sources"][0].update(reference="missing.py"), "Missing requirement source"),
    (lambda d: d["requirements"][0].update(invariant_refs=["INV-MISSING"]), "Unknown invariant"),
    (lambda d: d["requirements"][0].update(status="verified"), "Missing evidence"),
])
def test_registry_semantic_errors_block(registry, mutation, message):
    _, data, write = registry
    mutation(data)
    with pytest.raises(gates.GateError, match=message):
        write()


@pytest.mark.parametrize("duplicate", ["requirement", "criterion"])
def test_distinct_objects_cannot_reuse_ids(registry, duplicate):
    _, data, write = registry
    other = copy.deepcopy(data["requirements"][0])
    other["statement"] = "different fixture"
    if duplicate == "criterion":
        other["id"] = "REQ-A02"
    else:
        other["fit_criteria"][0]["id"] = "FC-A02-01"
    data["requirements"].append(other)
    with pytest.raises(gates.GateError, match="Duplicate"):
        write()


@pytest.mark.parametrize("path", ["../outside", "/tmp/outside", "a/../../outside", "a\\outside"])
def test_repository_path_cannot_escape(tmp_path, path):
    with pytest.raises(gates.GateError):
        gates.local_path(tmp_path, path)


def test_symlink_escape_blocks(tmp_path):
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(gates.GateError, match="escapes"):
        gates.local_path(tmp_path, "escape/file")


def test_current_permission_policy_protects_boundaries():
    gates.validate_permissions(ROOT)


def test_permission_relaxation_is_detected(tmp_path):
    import json5

    (tmp_path / ".opencode").mkdir()
    data = json5.loads((ROOT / ".opencode/permissions.jsonc").read_text())
    data["agent"]["verify"]["permission"]["edit"] = "allow"
    (tmp_path / ".opencode/permissions.jsonc").write_text(json.dumps(data))
    with pytest.raises(gates.GateError, match="permission|Read-only"):
        gates.validate_permissions(tmp_path)


def test_mechanical_source_relocation_preserves_logical_identity():
    assert gates.canonical_name("tradingagents/portfolio.py") == "src/tradingagents/portfolio.py"
    assert gates.canonical_name("tests/test_backtest.py") == "test/offline/test_backtest.py"


@pytest.mark.parametrize("name", ["__init__.py", "conftest.py", "test_live_backtest.py"])
def test_trading_live_relocation_retains_live_identity(name):
    """REQ-WEB-026 / NFR-OFF-001: relocation must not invent offline files."""
    assert gates.canonical_name(f"tests/trading/live/{name}") == f"test/live/trading/{name}"
    assert gates.canonical_name(f"test/live/trading/{name}") == f"test/live/trading/{name}"
    assert gates.canonical_name(f"tests/trading/{name}") == f"test/offline/trading/{name}"


def test_relocated_live_content_changes_still_require_evidence(tmp_path, monkeypatch):
    """REQ-WEB-026: equal relocated content is unchanged, a changed fixture is not."""
    snapshots = {
        "base": "100644 blob same\ttests/trading/live/conftest.py\0",
        "head": "100644 blob same\ttest/live/trading/conftest.py\0",
    }
    monkeypatch.setattr(gates, "git", lambda root, *args: snapshots[args[-1]])
    assert gates.changes(tmp_path, "base", "head") == set()
    snapshots["head"] = "100644 blob changed\ttest/live/trading/conftest.py\0"
    assert gates.changes(tmp_path, "base", "head") == {"test/live/trading/conftest.py"}


def test_duplicate_old_and_new_live_paths_are_rejected(tmp_path, monkeypatch):
    """REQ-WEB-026: a duplicate relocated module cannot hide in a logical tree."""
    snapshot = ("100644 blob same\ttests/trading/live/conftest.py\0"
                "100644 blob same\ttest/live/trading/conftest.py\0")
    monkeypatch.setattr(gates, "git", lambda *args: snapshot)
    with pytest.raises(gates.GateError, match="Duplicate logical source"):
        gates.tree(tmp_path, "fixture")


def test_web_verification_installs_optional_web_runtime():
    """REQ-WEB-026 / INV-WEB-001: verify WebUI without enlarging the core install."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    for name in ["regression", "static-analysis", "architecture-security"]:
        commands = [step.get("run", "") for step in jobs[name]["steps"]]
        assert "python -m pip install -e '.[dev,web]'" in commands
    smoke = [step.get("run", "") for step in jobs["smoke-install"]["steps"]]
    assert "python -m pip install ." in smoke


def test_core_must_not_import_presentation_layer(tmp_path, monkeypatch):
    for path in ["src/tradingagents", "src/cli", "test/offline", "test/live"]:
        (tmp_path / path).mkdir(parents=True)
    (tmp_path / "src/tradingagents/bad.py").write_text("from fastapi import FastAPI\n")
    monkeypatch.setattr(gates, "validate_permissions", lambda root: None)
    with pytest.raises(gates.GateError, match="presentation"):
        gates.structural_checks(tmp_path)


def test_ai_log_requires_a_new_meaningful_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "changes", lambda *args: {"src/new.py", "docs/ai-use-log.yaml"})
    entry = {"id": "fixture", "date": "2026-10-24", "tool": "fixture", "purpose": "fixture",
             "human_review": "pending", "paths": ["src/new.py"]}
    monkeypatch.setattr(gates, "blob", lambda root, ref, path: yaml.safe_dump({"entries": [entry] if ref == "head" else []}))
    gates.check_ai_log(tmp_path, "base", "head")
    monkeypatch.setattr(gates, "blob", lambda *args: yaml.safe_dump({"entries": [entry]}))
    with pytest.raises(gates.GateError, match="do not cover"):
        gates.check_ai_log(tmp_path, "base", "head")


def test_ai_log_unchanged_blocks_code(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "changes", lambda *args: {"src/new.py"})
    with pytest.raises(gates.GateError, match="must update"):
        gates.check_ai_log(tmp_path, "base", "head")


def test_ai_log_imports_legacy_list_without_waiving_new_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "changes", lambda *args: {"src/new.py", "docs/ai-use-log.yaml"})
    old = {"id": "AUL-001", "scope": "historic release work"}
    new = {"id": "merge", "date": "2026-11-19", "tool": "OpenCode", "purpose": "merge",
           "human_review": "pending", "paths": ["src/new.py"]}
    monkeypatch.setattr(gates, "blob", lambda root, ref, path: yaml.safe_dump(
        {"entries": [old, new]} if ref == "head" else [old]
    ))
    gates.check_ai_log(tmp_path, "base", "head")
    new["paths"] = []
    with pytest.raises(gates.GateError, match="do not cover"):
        gates.check_ai_log(tmp_path, "base", "head")


def test_approval_command_delegates_to_github_without_claiming_a_review(monkeypatch, capsys):
    """ADR-012 / REQ-WEB-026: CI never invents or backdates human approval."""
    monkeypatch.setattr(gates.sys, "argv", ["ci_gates", "approval"])
    for name in ["GITHUB_TOKEN", "GITHUB_EVENT_PATH", "GITHUB_REPOSITORY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gates, "git", lambda *args: pytest.fail("Review notice must not inspect Git chronology"))
    assert gates.main() == 0
    output = capsys.readouterr().out
    assert "GitHub branch protection" in output
    assert "does not issue or verify an approval" in output
    assert "PASS:" not in output


def test_workflow_retains_blocking_checks_without_duplicate_review_logic():
    """ADR-012 / REQ-WEB-026: native review and automated checks have separate owners."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    commands = [step.get("run", "") for step in jobs["review-and-log"]["steps"]]
    assert any("ci_gates ai-log" in command for command in commands)
    assert all("ci_gates approval" not in command for command in commands)
    assert jobs["review-and-log"]["permissions"] == {"contents": "read"}
    required = {"context", "regression", "static-analysis", "architecture-security",
                "requirements", "review-and-log", "semantic-evaluation", "smoke-install",
                "governance-validation"}
    assert set(jobs["blocking-gate"]["needs"]) == required
    assert any("ci_gates semantic" in step.get("run", "")
               for step in jobs["semantic-evaluation"]["steps"])
    assert all(not job.get("continue-on-error", False) for job in jobs.values())
    assert all(not step.get("continue-on-error", False)
               for job in jobs.values() for step in job["steps"])


@pytest.mark.parametrize("policy", [
    "[tool.tradingagents.ci]\n", "[tool.tradingagents.ci]\nsemantic_evaluation = {}\n",
])
def test_unconfigured_semantic_evaluation_is_explicitly_unrun(tmp_path, monkeypatch, capsys, policy):
    """ADR-012 / REQ-WEB-026: optional absence is not model-quality evidence."""
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    monkeypatch.setattr(gates, "blob", lambda *args: policy)
    monkeypatch.setattr(gates.subprocess, "run", lambda *args, **kwargs: pytest.fail("No evaluator is configured"))
    assert gates.check_semantic(tmp_path, "base", "head") is False
    output = capsys.readouterr().out
    assert "::notice" in output and "NOT RUN" in output
    assert "not a model-quality pass" in output
    assert "PASS:" not in output


def test_semantic_command_does_not_report_unrun_evaluation_as_pass(monkeypatch, capsys):
    """ADR-012 / REQ-WEB-026: the CLI preserves the NOT RUN outcome."""
    monkeypatch.setattr(gates.sys, "argv", ["ci_gates", "semantic", "--base", "base"])
    monkeypatch.setattr(gates, "git", lambda *args: "fixture-commit")
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    monkeypatch.setattr(gates, "blob", lambda *args: "[tool.tradingagents.ci]\n")
    assert gates.main() == 0
    output = capsys.readouterr().out
    assert "NOT RUN" in output
    assert "PASS:" not in output


def test_semantic_evaluation_is_not_required_without_model_changes(tmp_path, monkeypatch, capsys):
    """ADR-012 / REQ-WEB-026: unrelated changes do not invoke an evaluator."""
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: False)
    monkeypatch.setattr(gates, "blob", lambda *args: pytest.fail("No policy read needed"))
    assert gates.check_semantic(tmp_path, "base", "head") is False
    assert "NOT REQUIRED" in capsys.readouterr().out


@pytest.mark.parametrize("policy", [
    '[tool.tradingagents.ci.semantic_evaluation]\nevaluator = "test/evaluator.py"\n',
    '[tool.tradingagents.ci]\nsemantic_evaluation = "disabled"\n',
    '[tool.tradingagents.ci.semantic_evaluation]\nevaluator = 3\ndataset = "test/data.json"\n'
    '[tool.tradingagents.ci.semantic_evaluation.thresholds.quality]\ncomparison = "gte"\nthreshold = 0.9\n',
])
def test_partially_configured_or_invalid_semantic_policy_still_blocks(tmp_path, monkeypatch, policy):
    """ADR-012 / REQ-WEB-026: only absent/empty policy is optional; errors block."""
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    monkeypatch.setattr(gates, "blob", lambda *args: policy)
    with pytest.raises(gates.GateError, match="semantic|Semantic"):
        gates.check_semantic(tmp_path, "base", "head")


@pytest.mark.parametrize("score,success", [(1.0, True), (0.4, False)])
def test_semantic_replay_applies_fixed_dataset_and_threshold(tmp_path, monkeypatch, score, success):
    """ADR-012 / REQ-WEB-026: configured quality failures remain blocking."""
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    policy = '''[tool.tradingagents.ci.semantic_evaluation]
evaluator = "test/evaluator.py"
dataset = "test/dataset.json"
[tool.tradingagents.ci.semantic_evaluation.thresholds.quality]
comparison = "gte"
threshold = 0.9
'''
    evaluator = f'''import argparse, hashlib, json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--dataset'); p.add_argument('--output')
a=p.parse_args(); data=Path(a.dataset).read_bytes()
Path(a.output).write_text(json.dumps({{'dataset_sha256':hashlib.sha256(data).hexdigest(),
 'sample_count':len(json.loads(data)), 'metrics':{{'quality':{score}}}}}))
'''
    values = {"pyproject.toml": policy, "test/evaluator.py": evaluator, "test/dataset.json": '[{"fixture": true}]'}
    monkeypatch.setattr(gates, "blob", lambda root, ref, path: values[path])
    if success:
        assert gates.check_semantic(tmp_path, "base", "head") is True
    else:
        with pytest.raises(gates.GateError, match="threshold"):
            gates.check_semantic(tmp_path, "base", "head")


@pytest.mark.parametrize("failure", ["evaluator_changed", "dataset_changed", "process_failed",
                                      "report_missing", "wrong_dataset", "nonfinite_metric"])
def test_configured_semantic_evaluation_retains_failure_boundaries(tmp_path, monkeypatch, failure):
    """ADR-012 / REQ-WEB-026: optional setup cannot waive configured evidence."""
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    policy = '''[tool.tradingagents.ci.semantic_evaluation]
evaluator = "test/evaluator.py"
dataset = "test/dataset.json"
[tool.tradingagents.ci.semantic_evaluation.thresholds.quality]
comparison = "gte"
threshold = 0.9
'''
    dataset = '[{"fixture": true}]'
    values = {"pyproject.toml": policy, "test/evaluator.py": "# fixed evaluator", "test/dataset.json": dataset}

    def read_blob(root, ref, path):
        if ref == "head" and path == {"evaluator_changed": "test/evaluator.py",
                                      "dataset_changed": "test/dataset.json"}.get(failure):
            return values[path] + "\n"
        return values[path]

    def evaluate(command, **kwargs):
        if failure.endswith("_changed"):
            pytest.fail("Changed evaluation fixtures must be rejected before execution")
        assert not any("API_KEY" in name for name in kwargs["env"])
        assert "disable_socket" in command[2]
        if failure not in {"process_failed", "report_missing"}:
            report = {"dataset_sha256": hashlib.sha256(dataset.encode()).hexdigest(),
                      "sample_count": 1, "metrics": {"quality": 1.0}}
            if failure == "wrong_dataset":
                report["sample_count"] = 2
            else:
                report["metrics"]["quality"] = float("nan")
            Path(command[-1]).write_text(json.dumps(report))
        return subprocess.CompletedProcess(command, 1 if failure == "process_failed" else 0, "", "")

    monkeypatch.setenv("PROVIDER_API_KEY", "fixture-secret")
    monkeypatch.setattr(gates, "blob", read_blob)
    monkeypatch.setattr(gates.subprocess, "run", evaluate)
    with pytest.raises(gates.GateError):
        gates.check_semantic(tmp_path, "base", "head")


def test_transcript_export_is_complete_and_cannot_overwrite(tmp_path, monkeypatch):
    (tmp_path / "transcripts").mkdir()
    data = {"messages": [{"text": "fixture with ``` fence"}], "tools": [{"result": "fixture"}]}
    monkeypatch.setattr(gates.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, json.dumps(data), ""))
    gates.export_transcript(tmp_path, "ses_fixture", "transcripts/fixture.md")
    text = (tmp_path / "transcripts/fixture.md").read_text()
    assert '"tools"' in text and '"messages"' in text and "````json" in text
    with pytest.raises(gates.GateError, match="new file"):
        gates.export_transcript(tmp_path, "ses_fixture", "transcripts/fixture.md")


def test_transcript_export_cannot_write_outside_transcripts(tmp_path):
    with pytest.raises(gates.GateError, match="under transcripts"):
        gates.export_transcript(tmp_path, "ses_fixture", "AGENTS.md")


def test_dependency_audit_excludes_only_the_editable_application():
    class Distribution:
        def __init__(self, name, editable):
            self.metadata = {"Name": name}
            self.version = "1.0"
            self.editable = editable

        def read_text(self, name):
            return json.dumps({"dir_info": {"editable": self.editable}})

    assert gates.audit_pins([Distribution("tradingagents", True), Distribution("tradingagents", False),
                            Distribution("PyYAML", False)]) == ["pyyaml==1.0"]
    with pytest.raises(gates.GateError, match="Unreviewed editable"):
        gates.audit_pins([Distribution("unexpected-editable", True)])
    with pytest.raises(gates.GateError, match="No installed"):
        gates.audit_pins([Distribution("tradingagents", True)])
