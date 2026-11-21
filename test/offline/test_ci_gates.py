"""Positive and negative checks for verification-constraints.md sections 1, 5, 6.

Fixtures are synthetic test data, never product requirements or human approvals.
"""

from __future__ import annotations

import copy
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


@pytest.fixture
def approval_history(tmp_path, monkeypatch):
    approved = {"test/offline/test_feature.py": "tests", "docs/req/requirements.yaml": "req",
                "architecture-blueprint.md": "plan"}
    final = {**approved, "src/new.py": "implementation"}
    monkeypatch.setattr(gates, "tree", lambda root, ref: final if ref == "head" else approved)
    monkeypatch.setattr(gates, "runtime_changes", lambda root, base, ref: {"src/new.py"} if ref == "head" else set())
    monkeypatch.setattr(gates, "is_ancestor", lambda *args: True)
    monkeypatch.setattr(gates, "git", lambda root, *args: "head\n" if args[0] == "rev-list" else "2026-10-24T02:00:00+00:00\n")
    review = {"state": "COMMENTED", "body": "[test-plan-approved]", "commit_id": "approved",
              "submitted_at": "2026-10-24T01:00:00Z"}
    return tmp_path, review, final


@pytest.mark.parametrize("state", ["COMMENTED", "APPROVED"])
def test_test_approval_precedes_implementation(approval_history, state):
    root, review, _ = approval_history
    review["state"] = state
    gates.check_prior_approval(root, "base", "head", [review])


def test_explicitly_dismissed_plan_review_does_not_approve(approval_history):
    root, review, _ = approval_history
    review["state"] = "DISMISSED"
    with pytest.raises(gates.GateError, match="Missing earlier"):
        gates.check_prior_approval(root, "base", "head", [review])


def test_late_test_approval_blocks(approval_history):
    root, review, _ = approval_history
    review["submitted_at"] = "2026-10-24T03:00:00Z"
    with pytest.raises(gates.GateError, match="Missing earlier"):
        gates.check_prior_approval(root, "base", "head", [review])


def test_test_changes_after_approval_block(approval_history):
    root, review, final = approval_history
    final["test/offline/test_feature.py"] = "unapproved-tests"
    with pytest.raises(gates.GateError):
        gates.check_prior_approval(root, "base", "head", [review])


def test_empty_design_cannot_be_treated_as_approval(approval_history, monkeypatch):
    root, review, _ = approval_history
    monkeypatch.setattr(gates, "blob", lambda root, ref, path: "")
    with pytest.raises(gates.GateError, match="nonempty approved design"):
        gates.check_prior_approval(root, "base", "head", [review])


def test_self_approval_and_bots_are_not_trusted():
    client = gates.GitHub("owner/repo", "not-a-real-token")
    assert not client.trusted({"user": {"login": "author", "type": "User"}}, "author")
    assert not client.trusted({"user": {"login": "bot", "type": "Bot"}}, "author")


@pytest.fixture
def review_context(tmp_path, monkeypatch):
    client = gates.GitHub("owner/repo", "synthetic-token")
    request = {"head": {"sha": "head"}, "base": {"sha": "base"}, "user": {"login": "author"}}
    reviews = [{"state": "APPROVED", "commit_id": "head", "body": "[governance-approved]",
                "user": {"login": "reviewer", "type": "User"}}]
    monkeypatch.setattr(client, "get", lambda route: request if route == "pulls/1" else {"permission": "write"})
    monkeypatch.setattr(client, "reviews", lambda number: reviews)
    monkeypatch.setattr(gates, "changes", lambda *args: {".github/workflows/ci.yml"})
    monkeypatch.setattr(gates, "runtime_changes", lambda *args: set())
    return tmp_path, client, reviews


def test_governance_review_binds_the_current_head(review_context):
    root, client, _ = review_context
    gates.check_pull_request(root, "base", "head", 1, client)


def test_governance_review_on_an_old_head_blocks(review_context):
    root, client, reviews = review_context
    reviews[0]["commit_id"] = "old-head"
    with pytest.raises(gates.GateError, match="Current head"):
        gates.check_pull_request(root, "base", "head", 1, client)


def test_outstanding_request_for_changes_blocks(review_context):
    root, client, reviews = review_context
    reviews.append({**reviews[0], "state": "CHANGES_REQUESTED"})
    with pytest.raises(gates.GateError, match="still requests"):
        gates.check_pull_request(root, "base", "head", 1, client)


@pytest.mark.parametrize("has_adr", [False, True])
def test_safety_review_also_requires_accompanying_adr(review_context, monkeypatch, has_adr):
    root, client, reviews = review_context
    reviews[0]["body"] = "[safety-approved]"
    adr = "docs/architecture/adr/002-fixture.md"
    monkeypatch.setattr(gates, "runtime_changes", lambda *args: {"src/new.py"})
    monkeypatch.setattr(gates, "check_prior_approval", lambda *args: None)
    monkeypatch.setattr(gates, "changes", lambda *args: {"src/new.py", adr} if has_adr else {"src/new.py"})
    monkeypatch.setattr(gates, "tree", lambda *args: {adr: "fixture"})
    monkeypatch.setattr(gates, "blob", lambda *args: "# Context\n# Decision\n# Consequences\n" + "fixture " * 30)
    if has_adr:
        gates.check_pull_request(root, "base", "head", 1, client)
    else:
        with pytest.raises(gates.GateError, match="accompanying ADR"):
            gates.check_pull_request(root, "base", "head", 1, client)


def test_read_only_collaborator_cannot_approve(review_context, monkeypatch):
    _, client, reviews = review_context
    monkeypatch.setattr(client, "get", lambda route: {"permission": "read"})
    assert not client.trusted(reviews[0], "author")


def test_github_api_url_is_not_user_controlled():
    with pytest.raises(gates.GateError, match="Invalid GitHub"):
        gates.GitHub("https://untrusted.example", "fixture")


def test_prompt_change_without_approved_evaluation_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "semantic_needed", lambda *args: True)
    monkeypatch.setattr(gates, "blob", lambda *args: "[tool.tradingagents.ci]\nsemantic_evaluation = {}\n")
    with pytest.raises(gates.GateError, match="no base-approved"):
        gates.check_semantic(tmp_path, "base", "head")


@pytest.mark.parametrize("score,success", [(1.0, True), (0.4, False)])
def test_semantic_replay_applies_fixed_dataset_and_threshold(tmp_path, monkeypatch, score, success):
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
        gates.check_semantic(tmp_path, "base", "head")
    else:
        with pytest.raises(gates.GateError, match="threshold"):
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
