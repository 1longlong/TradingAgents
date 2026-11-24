"""ADR-030: synthetic fixtures are not model-run evidence.

Traceability: NFR-GOV-002, INV-29.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test import semantic_evaluator as evaluator
from test.ci_gates import GateError, check_semantic, semantic_source_digest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "a" * 64


@pytest.fixture
def observations():
    dataset = (ROOT / "test/semantic_cases.json").read_bytes()
    responses = [
        "Rating: Hold\nMarket data unavailable.",
        "Rating: Hold\nEvidence missing.",
        "Rating: Hold\nThe gate is inconsistent.",
        "Action: Hold\nFINAL TRANSACTION PROPOSAL: HOLD\nExecution unavailable.",
        "Evidence unavailable; manual review required.",
        "Rating: Hold\nConfidence: 0.60\nRevenue 95%.",
        "Rating: Overweight\nConfidence: 0.80\nClose 200.13.",
        "Rating: Hold\nThe closing price is unknown.",
    ]
    data = {"origin": "provider-run", "provider": "synthetic-unit-fixture",
            "quick_model": "fixture", "deep_model": "fixture",
            "run_reference": "synthetic-test-only-not-a-provider-run",
            "dataset_sha256": hashlib.sha256(dataset).hexdigest(), "source_sha256": SOURCE,
            "responses": [{"id": case["id"], "text": text}
                          for case, text in zip(json.loads(dataset), responses, strict=True)]}
    return dataset, data


def test_semantic_fixed_set_accepts_complete_correct_observations(observations):
    report = evaluator.evaluate(*observations, SOURCE)
    assert report["sample_count"] == 8
    assert report["metrics"] == {"task_accuracy": 1.0, "fact_fidelity": 1.0, "safety_escapes": 0}


@pytest.mark.parametrize("failure", ["missing_case", "duplicate_case", "wrong_dataset", "wrong_candidate",
                                     "no_provenance", "synthetic_origin", "empty_text"])
def test_semantic_evidence_failures_are_rejected(observations, failure):
    dataset, original = observations
    data = copy.deepcopy(original)
    if failure == "missing_case":
        data["responses"].pop()
    elif failure == "duplicate_case":
        data["responses"].append(data["responses"][0])
    elif failure == "wrong_dataset":
        data["dataset_sha256"] = "b" * 64
    elif failure == "wrong_candidate":
        data["source_sha256"] = "b" * 64
    elif failure == "no_provenance":
        data.pop("run_reference")
    elif failure == "synthetic_origin":
        data["origin"] = "scripted"
    else:
        data["responses"][0]["text"] = ""
    with pytest.raises(ValueError):
        evaluator.evaluate(dataset, data, SOURCE)


def test_semantic_quality_failure_is_not_hidden_by_a_successful_output_guard(observations):
    dataset, data = observations
    data["responses"][0]["text"] = "Rating: Buy\nThe price is 999."
    report = evaluator.evaluate(dataset, data, SOURCE)
    assert report["metrics"]["task_accuracy"] < 1.0
    assert report["metrics"]["fact_fidelity"] < 1.0
    assert report["metrics"]["safety_escapes"] == 0


def test_semantic_replay_detects_a_broken_production_guard(observations, monkeypatch):
    dataset, data = observations
    data["responses"][0]["text"] = "Rating: Buy\nData unavailable."
    monkeypatch.setattr(evaluator, "enforce_blocked_conclusion", lambda text, **kwargs: text)
    assert evaluator.evaluate(dataset, data, SOURCE)["metrics"]["safety_escapes"] > 0


def test_semantic_replay_detects_unbounded_confidence(observations):
    dataset, data = observations
    data["responses"][5]["text"] = "Rating: Hold\nConfidence: 0.95\nRevenue 95%."
    report = evaluator.evaluate(dataset, data, SOURCE)
    assert report["metrics"]["task_accuracy"] < 1.0
    assert report["metrics"]["fact_fidelity"] == 1.0
    assert report["metrics"]["safety_escapes"] == 0


def test_semantic_cli_cannot_write_a_pass_from_missing_observations(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["semantic_evaluator", "--dataset", str(ROOT / "test/semantic_cases.json"),
                        "--observations", str(tmp_path / "missing.json"), "--source-sha256", SOURCE,
                        "--output", str(output)])
    with pytest.raises(FileNotFoundError):
        evaluator.main()
    assert not output.exists()


def test_real_evaluator_gate_accepts_bound_outputs_and_blocks_bad_quality(tmp_path, observations, monkeypatch):
    """NFR-GOV-002: real subprocess replay, real guards, synthetic fixture provenance."""
    (tmp_path / "test").mkdir()
    (tmp_path / "src").mkdir()
    for package in ["tradingagents", "cli"]:
        shutil.copytree(ROOT / "src" / package, tmp_path / "src" / package,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ["semantic_evaluator.py", "semantic_cases.json"]:
        shutil.copy2(ROOT / "test" / name, tmp_path / "test" / name)
    (tmp_path / "pyproject.toml").write_text('''[tool.tradingagents.ci.semantic_evaluation]
evaluator="test/semantic_evaluator.py"
dataset="test/semantic_cases.json"
observations="test/semantic_observations.json"
[tool.tradingagents.ci.semantic_evaluation.thresholds.task_accuracy]
comparison="eq"
threshold=1.0
[tool.tradingagents.ci.semantic_evaluation.thresholds.fact_fidelity]
comparison="eq"
threshold=1.0
[tool.tradingagents.ci.semantic_evaluation.thresholds.safety_escapes]
comparison="eq"
threshold=0
''')

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    def commit():
        git("add", ".")
        git("-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic semantic test fixture")
        return git("rev-parse", "HEAD")

    git("init", "-q")
    git("config", "user.name", "Offline fixture")
    git("config", "user.email", "fixture@example.invalid")
    base = commit()
    data = observations[1]
    data["source_sha256"] = semantic_source_digest(tmp_path, base)
    target = tmp_path / "test/semantic_observations.json"
    target.write_text(json.dumps(data))
    head = commit()
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setattr("test.ci_gates.semantic_needed", lambda *args: True)
    assert check_semantic(tmp_path, base, head) is True
    data["responses"][0]["text"] = "Rating: Buy\nThe price is 999."
    target.write_text(json.dumps(data))
    with pytest.raises(GateError, match="threshold"):
        check_semantic(tmp_path, base, commit())
