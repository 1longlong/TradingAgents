"""Credential-free tests for the one-command wrapper (scripts/run_token_benchmark.sh).

These never call an LLM and never read the real ``~/.env_secrets``: every case
that could touch credentials points ``TRADINGAGENTS_BENCHMARK_SECRETS`` at a
synthetic file. The wrapper is exercised as a subprocess so argument parsing,
exit codes, and "no assistant secrets leak" behavior are tested for real.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "scripts" / "run_token_benchmark.sh"
HARNESS = REPO_ROOT / "scripts" / "token_benchmark.py"


def _sandbox(tmp_path: Path) -> Path:
    """A minimal repo root the wrapper can operate on without touching the real tree."""
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(WRAPPER, scripts / WRAPPER.name)
    shutil.copy2(HARNESS, scripts / HARNESS.name)
    tmpl = root / "token_benchmarks" / "baseline_v2"
    tmpl.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "token_benchmarks" / "baseline_v2" / "experiment.json",
                 tmpl / "experiment.json")
    # The wrapper requires the project virtualenv; reuse the real interpreter.
    venv = root / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(REPO_ROOT / ".venv" / "bin" / "python")
    # The harness imports the application package; link it in rather than
    # copying the tree (the sandbox stays read-only for app code).
    (root / "tradingagents").symlink_to(REPO_ROOT / "tradingagents",
                                        target_is_directory=True)
    (root / "cli").symlink_to(REPO_ROOT / "cli", target_is_directory=True)
    return root


def _run(root: Path, *args: str, cwd: Path | None = None, secrets: Path | None = None):
    env = dict(os.environ)
    env.pop("TRADINGAGENTS_BENCHMARK_SECRETS", None)
    if secrets is not None:
        env["TRADINGAGENTS_BENCHMARK_SECRETS"] = str(secrets)
    return subprocess.run(
        [str(root / "scripts" / WRAPPER.name), *args],
        cwd=str(cwd or root.parent), capture_output=True, text=True, env=env,
        timeout=120, stdin=subprocess.DEVNULL,
    )


def _measurements(root: Path) -> list[Path]:
    d = root / "token_benchmarks" / "measurements"
    return sorted(d.iterdir()) if d.exists() else []


class TestWrapperContract:
    def test_help_is_offline_and_documents_the_defaults(self, tmp_path):
        root = _sandbox(tmp_path)
        proc = _run(root, "--help", cwd=tmp_path)
        assert proc.returncode == 0
        out = proc.stdout
        assert "scripts/run_token_benchmark.sh" in out
        assert "--label" in out and "--dry-run" in out and "--runs" in out
        assert "default: 5" in out
        # No side effects from --help.
        assert _measurements(root) == []

    def test_unsupported_option_is_a_clear_error(self, tmp_path):
        root = _sandbox(tmp_path)
        proc = _run(root, "--bogus")
        assert proc.returncode == 2
        assert "unsupported option: --bogus" in proc.stderr
        assert _measurements(root) == []

    def test_unexpected_positional_is_rejected(self, tmp_path):
        root = _sandbox(tmp_path)
        proc = _run(root, "NVDA")
        assert proc.returncode == 2
        assert "unexpected argument: NVDA" in proc.stderr

    @pytest.mark.parametrize("value", ["0", "-3", "abc", "2.5", ""])
    def test_runs_must_be_a_positive_integer(self, tmp_path, value):
        root = _sandbox(tmp_path)
        proc = _run(root, "--runs", value)
        assert proc.returncode == 1
        assert "--runs" in proc.stderr
        assert _measurements(root) == []

    def test_option_without_a_value_is_rejected(self, tmp_path):
        root = _sandbox(tmp_path)
        proc = _run(root, "--label")
        assert proc.returncode == 1
        assert "--label requires a value" in proc.stderr

    def test_bad_date_format_is_rejected(self, tmp_path):
        root = _sandbox(tmp_path)
        proc = _run(root, "--date", "23/09/2026", "--dry-run")
        assert proc.returncode == 1
        assert "YYYY-MM-DD" in proc.stderr


class TestWrapperDryRun:
    def test_dry_run_needs_no_credentials_and_calls_no_llm(self, tmp_path):
        root = _sandbox(tmp_path)
        proc = _run(root, "--dry-run", "--runs", "2",
                    secrets=tmp_path / "definitely-missing")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "dry run completed" in proc.stdout
        assert "no LLM called" in proc.stdout
        dirs = _measurements(root)
        assert len(dirs) == 1
        exp = json.loads((dirs[0] / "experiment.json").read_text())
        assert exp["measured_runs"] == 2
        # Nothing that looks like a measurement result exists yet.
        assert not (dirs[0] / "summary.json").exists()

    def test_dry_run_works_from_an_unrelated_cwd(self, tmp_path):
        root = _sandbox(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        proc = _run(root, "--dry-run", "--label", "from-elsewhere", cwd=elsewhere)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert _measurements(root)[0].name.endswith("from-elsewhere")
        assert _measurements(root)[0].parent == root / "token_benchmarks" / "measurements"

    def test_dry_run_leaves_the_template_untouched(self, tmp_path):
        root = _sandbox(tmp_path)
        tmpl = root / "token_benchmarks" / "baseline_v2" / "experiment.json"
        before = tmpl.read_bytes()
        assert _run(root, "--dry-run").returncode == 0
        assert tmpl.read_bytes() == before


class TestWrapperCredentials:
    def test_missing_secrets_file_fails_before_measuring(self, tmp_path):
        root = _sandbox(tmp_path)
        proc = _run(root, secrets=tmp_path / "nope")
        assert proc.returncode == 1
        combined = proc.stdout + proc.stderr
        assert "credentials file not found" in combined
        assert _measurements(root) == []

    def test_partial_secrets_are_reported_by_name_only(self, tmp_path):
        root = _sandbox(tmp_path)
        secrets = tmp_path / "env"
        secrets.write_text("CITYU_FOUNDRY_API_KEY=sk-never-print-this\n")
        proc = _run(root, secrets=secrets)
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 1
        assert "CITYU_FOUNDRY_BASE_URL" in combined
        assert "sk-never-print-this" not in combined
        assert _measurements(root) == []

    def test_secret_value_never_appears_in_output_or_artifacts(self, tmp_path):
        root = _sandbox(tmp_path)
        secrets = tmp_path / "env"
        secrets.write_text(
            "CITYU_FOUNDRY_API_KEY=sk-unique-sentinel-value\n"
            "CITYU_FOUNDRY_BASE_URL=http://127.0.0.1:9/v1\n")
        # Dry-run so no network is attempted; the credential path is still
        # exercised by pointing at a real file.
        proc = _run(root, "--dry-run", secrets=secrets)
        assert "sk-unique-sentinel-value" not in proc.stdout + proc.stderr
        for path in (root / "token_benchmarks").rglob("*"):
            if path.is_file():
                assert "sk-unique-sentinel-value" not in path.read_text(errors="replace")


class TestWrapperFailureReporting:
    def test_unreachable_endpoint_reports_incomplete_and_keeps_evidence(self, tmp_path):
        """A dead endpoint must not be reported as success (or as 5/5)."""
        root = _sandbox(tmp_path)
        secrets = tmp_path / "env"
        secrets.write_text(
            "CITYU_FOUNDRY_API_KEY=sk-dummy\n"
            "CITYU_FOUNDRY_BASE_URL=http://127.0.0.1:9/v1\n")
        proc = _run(root, "--runs", "1", "--label", "dead", secrets=secrets)
        assert proc.returncode != 0
        assert "Benchmark completed" not in proc.stdout
        dirs = _measurements(root)
        assert len(dirs) == 1
        # The failed attempt is preserved, not silently discarded.
        attempts = list((dirs[0] / "runs").glob("run_*/attempt_*"))
        assert attempts
        assert (attempts[0] / "spec.json").exists()
