"""V3 batch infrastructure: memory contract, hashes, protocol consistency."""
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BATCH = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3"
GENERATOR = REPO_ROOT / "scripts/gen_cand01_batch_16run_specs_v3.py"
BASELINE = BATCH / "memory/baseline_v3.md"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_v3", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gv3 = _load_generator()


def _runs():
    return [json.loads((d / "experiment.json").read_text())
            for d in sorted((BATCH / "specs").iterdir()) if d.is_dir()]


def _specs():
    return [json.loads((d / "spec.json").read_text())
            for d in sorted((BATCH / "specs").iterdir()) if d.is_dir()]


def _baseline_sha() -> str:
    import hashlib
    return hashlib.sha256(BASELINE.read_bytes()).hexdigest()


def test_16_specs_and_no_per_run_code_state():
    directories = [d for d in (BATCH / "specs").iterdir() if d.is_dir()]
    assert len(directories) == 16
    for directory in directories:
        assert (directory / "experiment.json").is_file()
        assert (directory / "spec.json").is_file()
        # Provenance is per batch; per-run copies are written at run time and
        # must not be tracked, or a paid run would dirty the certified tree.
        assert not (directory / "code_state.json").exists(), directory.name


def test_every_registration_carries_the_memory_contract():
    sha = _baseline_sha()
    for registration in _runs():
        memory = registration["memory"]
        assert memory["mode"] == "per_run_snapshot_copy"
        assert memory["baseline_relpath"] == "memory/baseline_v3.md"
        assert memory["baseline_sha256"] == sha
        assert registration["schema_version"] == 3
        assert registration["protocol_version"] == "V3"


def test_config_hashes_recompute_and_are_distinct():
    hashes = []
    for registration in _runs():
        declared = registration["config_sha256"]
        assert gv3.config_sha256(registration) == declared
        assert len(declared) == 64
        hashes.append(declared)
    assert len(set(hashes)) == 16


def test_the_hashed_field_set_includes_memory():
    assert "memory" in gv3.HASHED_FIELDS
    import scripts.token_benchmark as tb
    assert tuple(gv3.HASHED_FIELDS) == tuple(tb.REGISTERED_HASH_FIELDS)


def test_the_protocol_hash_table_matches_the_registrations():
    import re
    text = (BATCH / "CAND01_BATCH_2X2_PROTOCOL_V3.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| `(R\d\d)` \| .*?\| `([0-9a-f]{64})` \|$", text, re.M))
    registrations = {r["experiment_id"]: r["config_sha256"] for r in _runs()}
    assert rows == registrations
    with (BATCH / "CONFIG_HASH_MANIFEST.csv").open(newline="", encoding="utf-8") as handle:
        csv_hashes = {row["run_id"]: row["config_sha256"] for row in csv.DictReader(handle)}
    assert csv_hashes == registrations


def test_specs_carry_the_memory_declaration_and_the_registered_hash():
    for spec in _specs():
        assert spec["memory"]["mode"] == "per_run_snapshot_copy"
        assert spec["memory"]["baseline_sha256"] == _baseline_sha()
        assert spec["config_sha256"]


def test_switches_match_the_frozen_matrix():
    with (BATCH / "SWITCH_MATRIX.csv").open(newline="", encoding="utf-8") as handle:
        matrix = {row["run_id"]: row for row in csv.DictReader(handle)}
    assert len(matrix) == 16
    for directory in sorted((BATCH / "specs").iterdir()):
        if not directory.is_dir():
            continue
        run_id = directory.name.split("_", 1)[0]
        registration = json.loads((directory / "experiment.json").read_text())
        row = matrix[run_id]
        assert row["ticker"] == directory.name.split("_")[1]
        assert row["arm"] == directory.name.split("_")[2]
        assert registration["switches"]["batch_macro"] is (row["batch_macro"] == "True")
        assert registration["switches"]["single_pass"] is (row["single_pass"] == "True")
        assert registration["switches"]["structured"] is True
        assert registration["switches"]["s2_downstream"] is True


def test_the_generator_reproduces_the_delivered_artifacts():
    # Build *in memory* against the real out root: the specs embed host paths
    # derived from it, so a temp dir would compare different bytes.
    artifacts = gv3.build(BATCH, memory_sha256=_baseline_sha())
    drift = []
    for rel, content in artifacts.items():
        path = BATCH / rel
        if not path.is_file():
            drift.append(f"missing {rel}")
            continue
        if rel == "code_state.json":
            continue  # volatile (timestamp)
        if path.read_text(encoding="utf-8") != content:
            drift.append(f"differs {rel}")
    assert drift == []


def test_a_tampered_memory_hash_is_refused_before_any_run(tmp_path):
    import scripts.token_benchmark as tb

    directory = BATCH / "specs/R01_NVDA_C0"
    registration = json.loads((directory / "experiment.json").read_text())
    spec = tb.build_run_spec(directory, registration, registration["cases"][0], 1, 1)
    assert spec["memory"]["baseline_sha256"] == _baseline_sha()
    spec["memory"]["baseline_sha256"] = "0" * 64
    with pytest.raises(tb.RunRefused):
        tb.validate_memory_spec(spec)


def test_the_baseline_is_immutable_and_pending_free():
    text = BASELINE.read_text(encoding="utf-8")
    assert "| pending]" not in text
    before = _baseline_sha()
    # Nothing in this test suite may rewrite it.
    assert _baseline_sha() == before


def test_the_cli_check_mode_passes():
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(BATCH),
         "--memory-baseline", str(BASELINE), "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "artefacts reproduce" in result.stdout
