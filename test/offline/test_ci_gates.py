"""Positive and negative checks for verification-constraints.md sections 1, 5, 6.

Fixtures are synthetic test data, never product requirements or human approvals.

Traceability: NFR-GOV-001, NFR-GOV-002, NFR-SEC-001, REQ-WEB-026, INV-28, INV-29.
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


def test_native_permission_file_paths_have_an_explicit_root_binding():
    """ADR-031 / NFR-SEC-001: native path matching must not widen the root."""
    import json5

    config = json5.loads((ROOT / ".opencode/permissions.jsonc").read_text())
    for policy in [config["permission"], *(role["permission"] for role in config["agent"].values())]:
        for tool in ["read", "edit"]:
            rules = policy.get(tool)
            if isinstance(rules, dict):
                assert all(pattern == "*" or pattern.startswith("{env:TRADINGAGENTS_PERMISSION_ROOT}/")
                           for pattern in rules)
    assert config["permission"]["external_directory"] == "deny"
    for role in config["agent"]:
        assert gates.permission_effect(config, role, "read", ".env") == "deny"
        assert gates.permission_effect(config, role, "read", "AGENTS.md") == "allow"
        assert gates.permission_effect(config, role, "edit", ".opencode/rules.md") == "deny"


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


def test_prior_test_approval_command_requires_an_explicit_base(monkeypatch, capsys):
    """NFR-GOV-001 / INV-28: no context cannot become an approval notice/pass."""
    monkeypatch.setattr(gates.sys, "argv", ["ci_gates", "approval"])
    assert gates.main() == 1
    assert "base commit is required" in capsys.readouterr().err


def test_prior_test_approval_workflow_preserves_other_gates_and_trusted_execution():
    """ADR-029 / NFR-GOV-001: review evidence is distinct from merge approval."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    commands = [step.get("run", "") for step in jobs["review-and-log"]["steps"]]
    assert any("ci_gates ai-log" in command for command in commands)
    approval = next(command for command in commands if 'run_module("test.ci_gates"' in command)
    assert 'source = base' in approval and "'-I'" in approval
    assert '"--repo-root"' in approval
    assert jobs["review-and-log"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "pull_request_target" not in (ROOT / ".github/workflows/ci.yml").read_text()
    required = {"context", "regression", "static-analysis", "architecture-security",
                "requirements", "review-and-log", "semantic-evaluation", "smoke-install",
                "governance-validation"}
    required.update({"frontend", "frontend-e2e"})
    assert set(jobs["blocking-gate"]["needs"]) == required
    assert any("ci_gates semantic" in step.get("run", "")
               for step in jobs["semantic-evaluation"]["steps"])
    assert all(not job.get("continue-on-error", False) for job in jobs.values())
    assert all(not step.get("continue-on-error", False)
               for job in jobs.values() for step in job["steps"])


@pytest.mark.parametrize("policy", [
    "[tool.tradingagents.ci]\n", "[tool.tradingagents.ci]\nsemantic_evaluation = {}\n",
])
def test_unconfigured_semantic_evaluation_blocks_required_changes(tmp_path, monkeypatch, capsys, policy):
    """ADR-030 / NFR-GOV-002: missing policy cannot waive evaluation."""
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    monkeypatch.setattr(gates, "blob", lambda *args: policy)
    monkeypatch.setattr(gates.subprocess, "run", lambda *args, **kwargs: pytest.fail("No evaluator is configured"))
    with pytest.raises(gates.GateError, match="configured base semantic policy"):
        gates.check_semantic(tmp_path, "base", "head")


def test_semantic_command_rejects_an_unrun_required_evaluation(monkeypatch, capsys):
    """ADR-030 / INV-29: no policy is a blocked result, never a pass."""
    monkeypatch.setattr(gates.sys, "argv", ["ci_gates", "semantic", "--base", "base"])
    monkeypatch.setattr(gates, "git", lambda *args: "fixture-commit")
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    monkeypatch.setattr(gates, "blob", lambda *args: "[tool.tradingagents.ci]\n")
    assert gates.main() == 1
    output = capsys.readouterr()
    assert "BLOCKED" in output.err
    assert "PASS:" not in output.out


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
observations = "test/observations.json"
[tool.tradingagents.ci.semantic_evaluation.thresholds.quality]
comparison = "gte"
threshold = 0.9
'''
    evaluator = f'''import argparse, hashlib, json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--dataset'); p.add_argument('--output'); p.add_argument('--observations'); p.add_argument('--source-sha256')
a=p.parse_args(); data=Path(a.dataset).read_bytes()
Path(a.output).write_text(json.dumps({{'dataset_sha256':hashlib.sha256(data).hexdigest(),
 'sample_count':len(json.loads(data)), 'source_sha256':a.source_sha256, 'metrics':{{'quality':{score}}}}}))
'''
    values = {"pyproject.toml": policy, "test/evaluator.py": evaluator, "test/dataset.json": '[{"fixture": true}]', "test/observations.json": '{"origin":"synthetic-unit-test"}'}
    monkeypatch.setattr(gates, "blob", lambda root, ref, path: values[path])
    monkeypatch.setattr(gates, "semantic_source_digest", lambda *args: "a" * 64)
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
observations = "test/observations.json"
[tool.tradingagents.ci.semantic_evaluation.thresholds.quality]
comparison = "gte"
threshold = 0.9
'''
    dataset = '[{"fixture": true}]'
    values = {"pyproject.toml": policy, "test/evaluator.py": "# fixed evaluator", "test/dataset.json": dataset, "test/observations.json": '{"origin":"synthetic-unit-test"}'}

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
                      "sample_count": 1, "source_sha256": "a" * 64, "metrics": {"quality": 1.0}}
            if failure == "wrong_dataset":
                report["sample_count"] = 2
            else:
                report["metrics"]["quality"] = float("nan")
            Path(command[-1]).write_text(json.dumps(report))
        return subprocess.CompletedProcess(command, 1 if failure == "process_failed" else 0, "", "")

    monkeypatch.setenv("PROVIDER_API_KEY", "fixture-secret")
    monkeypatch.setattr(gates, "blob", read_blob)
    monkeypatch.setattr(gates, "semantic_source_digest", lambda *args: "a" * 64)
    monkeypatch.setattr(gates.subprocess, "run", evaluate)
    with pytest.raises(gates.GateError):
        gates.check_semantic(tmp_path, "base", "head")


def test_semantic_observations_are_mandatory_when_base_policy_requires_them(tmp_path, monkeypatch):
    """ADR-030 / INV-29: missing actual outputs cannot become a quality pass."""
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    policy = '''[tool.tradingagents.ci.semantic_evaluation]
evaluator="test/evaluator.py"
dataset="test/cases.json"
observations="test/observations.json"
[tool.tradingagents.ci.semantic_evaluation.thresholds.quality]
comparison="eq"
threshold=1
'''

    def read(root, ref, path):
        if path.endswith("observations.json"):
            raise gates.GateError("missing file")
        return {"pyproject.toml": policy, "test/evaluator.py": "# evaluator", "test/cases.json": "[{}]"}[path]

    monkeypatch.setattr(gates, "blob", read)
    with pytest.raises(gates.GateError, match="Missing authentic"):
        gates.check_semantic(tmp_path, "base", "head")


def test_semantic_source_digest_ignores_observation_bookkeeping_but_binds_code(monkeypatch):
    """ADR-030 / INV-29: response commit IDs must not create a circular hash."""
    files = {"src/example.py": "aaa", "prompts/prompt.yaml": "bbb", "pyproject.toml": "ccc",
             "test/semantic_observations.json": "old"}
    monkeypatch.setattr(gates, "tree", lambda *args: files)
    initial = gates.semantic_source_digest(ROOT, "head")
    files["test/semantic_observations.json"] = "new"
    assert gates.semantic_source_digest(ROOT, "head") == initial
    files["src/example.py"] = "ddd"
    assert gates.semantic_source_digest(ROOT, "head") != initial


def test_semantic_workflow_uses_protected_code_without_credentials():
    """ADR-030 / NFR-SEC-001: the candidate does not own its quality bar."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    step = next(step for step in jobs["semantic-evaluation"]["steps"] if "Replay fixed" in step.get("name", ""))
    assert "f'{base}:{path}'" in step["run"]
    assert "'-I'" in step["run"]
    assert "Missing protected-base semantic policy" in step["run"]
    assert "GITHUB_TOKEN" not in step["env"]
    assert step["env"]["PYTHON_DOTENV_DISABLED"] == "1"


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


# NFR-GOV-001 / INV-28 / ADR-029: synthetic Git histories and server records.
@pytest.fixture
def prior_test_history(tmp_path):
    import os

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)

    def commit(files, at):
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        environment = dict(os.environ, GIT_AUTHOR_DATE=at, GIT_COMMITTER_DATE=at)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-qm", "Synthetic fixture"], cwd=root, env=environment, check=True)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    base = commit({
        "pyproject.toml": '[project]\nname="fixture"\n[tool.tradingagents.ci.test_approval]\nversion=1\nreviewer_ids=[1]\n',
        "src/sample.py": "VALUE = 0\n",
        "test/offline/test_sample.py": "def test_sample():\n    assert True\n",
        "architecture-blueprint.md": "# Fixture contract\n",
        "docs/req/requirements.yaml": 'requirements:\n- id: NFR-GOV-001\n  status: approved\n',
        "test/ci_gates.py": "TEST_APPROVAL_POLICY_VERSION = 1\n",
    }, "2026-01-01T00:00:00+00:00")
    tests = commit({"test/offline/test_sample.py": "def test_sample():\n    assert 1 == 1\n"},
                   "2026-01-02T00:00:00+00:00")
    implementation = commit({"src/sample.py": "VALUE = 1\n"}, "2026-01-03T00:00:00+00:00")
    return root, base, tests, implementation, commit


def _prior_review(commit, at="2026-01-02T12:00:00Z"):
    return {"state": "COMMENTED", "body": f"Test plan approved for commit {commit}.\nScope: NFR-GOV-001",
            "author": {"__typename": "User", "databaseId": 1, "login": "maintainer"},
            "commit": {"oid": commit}, "submittedAt": at, "updatedAt": at,
            "url": "https://github.com/example/repo/pull/1#pullrequestreview-1"}


def _prior_pr(base, head):
    return {"number": 1, "state": "OPEN", "baseRefOid": base, "headRefOid": head}


def _check_prior(history, reviews, head=None):
    root, base, _, implementation, _ = history
    target = head or implementation
    return gates.check_prior_test_approval(root, base, target, _prior_pr(base, target), reviews, {1})


def test_prior_test_approval_accepts_bound_human_review_before_implementation(prior_test_history):
    result = _check_prior(prior_test_history, [_prior_review(prior_test_history[2])])
    assert result["status"] == "approved"
    assert result["reviews"][0]["reviewer"] == "maintainer"
    assert result["implementation_commits"] == [prior_test_history[3]]


def test_prior_test_approval_survives_an_unrelated_base_advance(prior_test_history):
    root, base, tests, head, commit = prior_test_history
    subprocess.run(["git", "checkout", "--detach", "-q", base], cwd=root, check=True)
    newer_base = commit({"README.md": "Unrelated release documentation\n"}, "2026-01-04T00:00:00Z")
    result = gates.check_prior_test_approval(root, newer_base, head, _prior_pr(newer_base, head),
                                            [_prior_review(tests)], {1})
    assert result["status"] == "approved"
    assert result["implementation_commits"] == [head]


@pytest.mark.parametrize("path", ["Dockerfile", "docker-compose.yml", "requirements.txt",
                                   "src/tradingagents_web/frontend/package.json"])
def test_prior_test_approval_classifies_runtime_and_dependency_configuration(prior_test_history, path):
    root, base, _, head, commit = prior_test_history
    changed = commit({path: "fixture executable configuration\n"}, "2026-01-04T00:00:00Z")
    assert gates.approval_implementation_change(root, head, changed, base)


@pytest.mark.parametrize("mutation", [
    "missing", "bot", "unauthorized", "late", "edited_late", "dismissed", "native_approve",
    "malformed", "wrong_commit", "unknown_commit", "missing_time", "quoted_marker",
])
def test_prior_test_approval_rejects_untrusted_or_retrospective_evidence(prior_test_history, mutation):
    review = _prior_review(prior_test_history[2])
    reviews = [review]
    if mutation == "missing":
        reviews = []
    elif mutation == "bot":
        review["author"]["__typename"] = "Bot"
    elif mutation == "unauthorized":
        review["author"]["databaseId"] = 2
    elif mutation == "late":
        review["submittedAt"] = review["updatedAt"] = "2026-01-04T00:00:00Z"
    elif mutation == "edited_late":
        review["updatedAt"] = "2026-01-04T00:00:00Z"
    elif mutation == "dismissed":
        review["state"] = "DISMISSED"
    elif mutation == "native_approve":
        review["state"] = "APPROVED"
    elif mutation == "malformed":
        review["body"] = "approved"
    elif mutation == "wrong_commit":
        review["commit"]["oid"] = prior_test_history[3]
    elif mutation == "unknown_commit":
        review["body"] = "Test plan approved for commit " + "f" * 40 + ".\nScope: NFR-GOV-001"
        review["commit"]["oid"] = "f" * 40
    elif mutation == "missing_time":
        review.pop("updatedAt")
    else:
        review["body"] = "```text\n" + review["body"] + "\n```"
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, reviews)


def test_prior_test_approval_cannot_approve_combined_test_and_implementation_commit(prior_test_history):
    review = _prior_review(prior_test_history[3], "2026-01-03T12:00:00Z")
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, [review])


@pytest.mark.parametrize("path", ["test/offline/test_sample.py", "test/conftest.py",
                                 "src/tradingagents_web/frontend/tests/widget.test.tsx",
                                 "src/tradingagents_web/frontend/e2e/widget.spec.ts",
                                 "src/tradingagents_web/frontend/vitest.config.ts",
                                 "architecture-blueprint.md"])
def test_prior_test_approval_blocks_unreviewed_final_test_or_contract_changes(prior_test_history, path):
    head = prior_test_history[4]({path: "changed after implementation\n"}, "2026-01-04T00:00:00Z")
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, [_prior_review(prior_test_history[2])], head)


def test_prior_test_approval_supports_separately_reviewed_test_epochs(prior_test_history):
    commit = prior_test_history[4]
    tests2 = commit({"test/offline/test_sample.py": "def test_second():\n    assert 2 == 2\n"},
                    "2026-01-04T00:00:00Z")
    implementation2 = commit({"src/sample.py": "VALUE = 2\n"}, "2026-01-05T00:00:00Z")
    reviews = [_prior_review(prior_test_history[2]), _prior_review(tests2, "2026-01-04T12:00:00Z")]
    result = _check_prior(prior_test_history, reviews, implementation2)
    assert result["implementation_commits"] == [prior_test_history[3], implementation2]
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, reviews[1:], implementation2)


def test_prior_test_approval_status_bookkeeping_does_not_change_acceptance_contract(prior_test_history):
    head = prior_test_history[4]({"docs/req/requirements.yaml":
                                'requirements:\n- id: NFR-GOV-001\n  status: implemented\n'},
                               "2026-01-04T00:00:00Z")
    assert _check_prior(prior_test_history, [_prior_review(prior_test_history[2])], head)["status"] == "approved"


def test_prior_test_approval_rejects_stale_pr_head(prior_test_history):
    root, base, tests, head, _ = prior_test_history
    pr = _prior_pr(base, tests)
    with pytest.raises(gates.GateError, match="PR"):
        gates.check_prior_test_approval(root, base, head, pr, [_prior_review(tests)], {1})


def test_prior_test_approval_test_preparation_is_not_an_approval_claim(prior_test_history):
    root, base, tests, _, _ = prior_test_history
    result = gates.check_prior_test_approval(root, base, tests, _prior_pr(base, tests), [], {1})
    assert result["status"] == "not_required"
    assert not result["reviews"]


@pytest.mark.parametrize("policy", ["", '[tool.tradingagents.ci.test_approval]\nversion=1\nreviewer_ids=[]\n',
                                   '[tool.tradingagents.ci.test_approval]\nversion=1\nreviewer_ids=[true]\n',
                                   '[tool.tradingagents.ci.test_approval]\nversion=2\nreviewer_ids=[1]\n'])
def test_prior_test_approval_missing_or_invalid_base_policy_blocks(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(gates, "blob", lambda *args: policy)
    with pytest.raises(gates.GateError, match="policy"):
        gates.read_test_approval_policy(tmp_path, "base")


def test_prior_test_approval_policy_comes_from_base(prior_test_history):
    root, base, _, _, commit = prior_test_history
    head = commit({"pyproject.toml": '[tool.tradingagents.ci.test_approval]\nversion=1\nreviewer_ids=[2]\n'},
                  "2026-01-04T00:00:00Z")
    assert gates.read_test_approval_policy(root, base) == {1}
    assert gates.read_test_approval_policy(root, head) == {2}


def test_prior_test_approval_graphql_paginates_and_checks_context(monkeypatch):
    calls = []

    def request(query, variables, token):
        calls.append(variables["cursor"])
        page = {"nodes": [_prior_review("a" * 40)],
                "pageInfo": {"hasNextPage": variables["cursor"] is None, "endCursor": "next"}}
        return {"repository": {"pullRequest": dict(_prior_pr("b" * 40, "c" * 40), reviews=page)}}

    monkeypatch.setattr(gates, "github_review_query", request)
    pr, reviews = gates.fetch_test_plan_reviews("example/repo", 1, "b" * 40, "c" * 40, "fixture")
    assert calls == [None, "next"]
    assert len(reviews) == 2 and pr["headRefOid"] == "c" * 40


@pytest.mark.parametrize("problem", ["api", "stale", "truncated"])
def test_prior_test_approval_api_or_pagination_failures_block(monkeypatch, problem):
    def request(query, variables, token):
        if problem == "api":
            raise gates.GateError("GitHub review API unavailable")
        pr = _prior_pr("b" * 40, "d" * 40 if problem == "stale" else "c" * 40)
        pr["reviews"] = {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": None}}
        return {"repository": {"pullRequest": pr}}
    monkeypatch.setattr(gates, "github_review_query", request)
    with pytest.raises(gates.GateError):
        gates.fetch_test_plan_reviews("example/repo", 1, "b" * 40, "c" * 40, "fixture")


def test_prior_test_approval_bootstrap_cannot_include_business_changes(prior_test_history, monkeypatch):
    root, base, _, head, _ = prior_test_history
    monkeypatch.setattr(gates, "TEST_APPROVAL_BOOTSTRAP_BASE", base)
    with pytest.raises(gates.GateError, match="bootstrap"):
        gates.check_test_approval_bootstrap(root, base, head)


def test_prior_test_approval_review_of_a_nonancestor_cannot_authorize(prior_test_history):
    other = prior_test_history[4]({"test/offline/test_other.py": "def test_other():\n    pass\n"},
                                 "2026-01-04T00:00:00Z")
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, [_prior_review(other)])


def test_prior_test_approval_transport_errors_do_not_echo_credentials(monkeypatch):
    import urllib.error

    class OfflineOpener:
        def open(self, request, timeout):
            raise urllib.error.URLError("fixture-sensitive-value")
    monkeypatch.setattr(gates.urllib.request, "build_opener", lambda *args: OfflineOpener())
    with pytest.raises(gates.GateError) as error:
        gates.github_review_query("query", {}, "fixture-sensitive-value")
    assert "fixture-sensitive-value" not in str(error.value)


def test_prior_test_approval_candidate_cannot_add_its_own_reviewer(prior_test_history, tmp_path, monkeypatch):
    root, base, _, _, commit = prior_test_history
    head = commit({"pyproject.toml": '[project]\nname="fixture"\n[tool.tradingagents.ci.test_approval]\nversion=1\nreviewer_ids=[2]\n'},
                  "2026-01-04T00:00:00Z")
    review = _prior_review(prior_test_history[2])
    review["author"]["databaseId"] = 2
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 1}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setattr(gates, "fetch_test_plan_reviews", lambda *args: (_prior_pr(base, head), [review]))
    with pytest.raises(gates.GateError, match="approval"):
        gates.run_test_approval(root, base, head)


@pytest.mark.parametrize("change", ["policy", "checker"])
def test_prior_test_approval_candidate_cannot_remove_the_gate(prior_test_history, change):
    root, base, _, _, commit = prior_test_history
    files = ({"pyproject.toml": '[project]\nname="fixture"\n'} if change == "policy"
             else {"test/ci_gates.py": "# removed\n"})
    head = commit(files, "2026-01-04T00:00:00Z")
    with pytest.raises(gates.GateError):
        gates.run_test_approval(root, base, head)


def test_prior_test_approval_allows_the_allowlisted_pr_author_to_review_tests(prior_test_history):
    root, base, tests, head, _ = prior_test_history
    pr = dict(_prior_pr(base, head), author={"login": "maintainer", "databaseId": 1})
    result = gates.check_prior_test_approval(root, base, head, pr, [_prior_review(tests)], {1})
    assert result["status"] == "approved"


def test_prior_test_approval_removing_marker_revokes_the_record(prior_test_history):
    review = _prior_review(prior_test_history[2])
    review["body"] = "Test plan approval revoked."
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, [review])


def test_prior_test_approval_acceptance_change_is_not_status_bookkeeping(prior_test_history):
    head = prior_test_history[4]({"docs/req/requirements.yaml":
                                'requirements:\n- id: NFR-GOV-001\n  status: approved\n  statement: Different acceptance\n'},
                               "2026-01-04T00:00:00Z")
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, [_prior_review(prior_test_history[2])], head)


def test_prior_test_approval_equal_timestamp_is_not_prior(prior_test_history):
    review = _prior_review(prior_test_history[2], "2026-01-03T00:00:00Z")
    with pytest.raises(gates.GateError, match="approval"):
        _check_prior(prior_test_history, [review])


def test_prior_test_approval_bootstrap_preserves_gates_and_never_issues_approval(prior_test_history, monkeypatch):
    root, _, _, _, commit = prior_test_history
    workflow = 'jobs:\n  review-and-log:\n    steps: []\n  regression:\n    steps: []\n'
    base = commit({"src/sample.py": "VALUE = 0\n", ".github/workflows/ci.yml": workflow},
                  "2026-01-04T00:00:00Z")
    head = commit({"pyproject.toml": '[project]\nname="fixture"\n[tool.tradingagents.ci.test_approval]\nversion=1\nreviewer_ids=[66710554]\n'},
                  "2026-01-05T00:00:00Z")
    monkeypatch.setattr(gates, "TEST_APPROVAL_BOOTSTRAP_BASE", base)
    result = gates.check_test_approval_bootstrap(root, base, head)
    assert result["status"] == "bootstrap" and not result["reviews"]
    weakened = commit({".github/workflows/ci.yml": workflow.replace('regression:', 'removed:')},
                      "2026-01-06T00:00:00Z")
    with pytest.raises(gates.GateError, match="other workflow gates"):
        gates.check_test_approval_bootstrap(root, base, weakened)


def test_prior_test_approval_workflow_executes_base_code_not_candidate(prior_test_history):
    """NFR-GOV-001 / INV-28: exercise actual isolated workflow loader offline."""
    import os
    import sys

    root, _, _, _, commit = prior_test_history
    trusted = ('TEST_APPROVAL_POLICY_VERSION = 1\n'
               'import sys\n'
               'from scripts.validate.validate_requirements import VALUE\n'
               'assert VALUE == "trusted"\n'
               'assert "--repo-root" in sys.argv\n'
               'print("trusted-base-checker")\n')
    base = commit({"test/ci_gates.py": trusted, "test/__init__.py": "",
                   "scripts/validate/validate_requirements.py": 'VALUE = "trusted"\n'},
                  "2026-01-04T00:00:00Z")
    head = commit({"test/ci_gates.py": 'TEST_APPROVAL_POLICY_VERSION = 1\nraise RuntimeError("candidate executed")\n',
                   "scripts/validate/validate_requirements.py": 'raise RuntimeError("candidate validator executed")\n'},
                  "2026-01-05T00:00:00Z")
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    step = next(item for item in jobs["review-and-log"]["steps"]
                if item.get("name") == "Verify prior test approval with the base-owned checker")
    script = step["run"].split("\n", 1)[1].rsplit("\nPY", 1)[0]
    environment = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR") if name in os.environ}
    environment.update(GITHUB_WORKSPACE=str(root), BASE_SHA=base, HEAD_SHA=head)
    result = subprocess.run([sys.executable, "-I", "-c", script], cwd=root,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "trusted-base-checker" in result.stdout
    assert "candidate executed" not in result.stdout + result.stderr
