"""V3 batch infrastructure: memory contract, hashes, protocol consistency."""
from __future__ import annotations

import csv
import hashlib
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
    return hashlib.sha256(BASELINE.read_bytes()).hexdigest()


#: The only run-spec fields that embed the checkout root. The generator derives
#: them from its own location (``_experiment_root``) and from ``--out``, so a
#: clean clone legitimately writes different values for these two fields.
#: Everything else -- switches, case, config_sha256, identity, ordering and the
#: memory/budget blocks -- is frozen and must still compare exactly.
_HOST_PATH_FIELDS = ("experiment_root", "results_dir")


def _normalize_host_paths(spec: dict) -> dict:
    """Make the two documented host-path fields checkout-independent.

    This is deliberately narrow: it rewrites ``experiment_root`` to a marker and
    strips the same prefix from ``results_dir`` only when that field actually
    lives under it. Any other difference is left untouched so a genuine config,
    switch or case change still fails the reproduction test.
    """
    import copy

    normalized = copy.deepcopy(spec)
    root = normalized.get("experiment_root")
    results = normalized.get("results_dir")
    if isinstance(root, str):
        normalized["experiment_root"] = "<REPO_ROOT>"
        if isinstance(results, str):
            prefix = root.rstrip("/") + "/"
            if results.startswith(prefix):
                normalized["results_dir"] = "<REPO_ROOT>/" + results[len(prefix):]
    return normalized


def _manifest_rows(text: str) -> list[dict]:
    return list(csv.DictReader(text.splitlines()))


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


def test_schema_3_is_accepted_by_the_harness():
    """The harness must run a V3 registration, not reject it on schema."""
    import scripts.token_benchmark as tb

    assert 3 in tb.SUPPORTED_EXPERIMENT_SCHEMAS
    registration = _runs()[0]
    tb.validate_experiment(registration)  # must not raise


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
    # Build in memory against the real out root. Specs embed two host paths
    # (experiment_root, results_dir) derived from the checkout, so compare them
    # after normalising only those documented fields; every other field,
    # including config_sha256, is compared exactly.
    artifacts = gv3.build(BATCH, memory_sha256=_baseline_sha())
    drift = []
    for rel, content in artifacts.items():
        path = BATCH / rel
        if not path.is_file():
            drift.append(f"missing {rel}")
            continue
        if rel == "code_state.json":
            continue  # volatile (timestamp, git state)
        if rel.endswith("/spec.json"):
            frozen = _normalize_host_paths(json.loads(path.read_text(encoding="utf-8")))
            fresh = _normalize_host_paths(json.loads(content))
            if frozen != fresh:
                changed = sorted(
                    key for key in set(frozen) | set(fresh)
                    if frozen.get(key) != fresh.get(key)
                )
                drift.append(f"differs after host-path normalisation {rel}: {changed}")
            continue
        if rel == "RUN_MANIFEST_TEMPLATE.csv":
            # spec_body_sha256 hashes experiment_root, so the value necessarily
            # moves with the checkout. Verify each side's digest against the
            # spec it names, then compare every other column exactly. The
            # separate MANIFEST.sha256 test pins the frozen bytes themselves.
            frozen_rows = _manifest_rows(path.read_text(encoding="utf-8"))
            fresh_rows = _manifest_rows(content)
            if [r["run_id"] for r in frozen_rows] != [r["run_id"] for r in fresh_rows]:
                drift.append(f"differs in row identity/order {rel}")
                continue
            for frozen_row, fresh_row in zip(frozen_rows, fresh_rows, strict=True):
                for row, tree in ((frozen_row, "frozen"), (fresh_row, "fresh")):
                    spec_path = row["spec_path"]
                    if tree == "frozen":
                        spec = json.loads(
                            (BATCH / spec_path).read_text(encoding="utf-8")
                        )
                    else:
                        spec = json.loads(artifacts[spec_path])
                    if gv3.spec_body_sha256(spec) != row["spec_body_sha256"]:
                        drift.append(f"{tree} manifest digest does not match {spec_path}")
                left = {k: v for k, v in frozen_row.items() if k != "spec_body_sha256"}
                right = {k: v for k, v in fresh_row.items() if k != "spec_body_sha256"}
                if left != right:
                    drift.append(f"differs in non-digest columns {rel} {frozen_row['run_id']}")
            continue
        if path.read_text(encoding="utf-8") != content:
            drift.append(f"differs {rel}")
    assert drift == []


def test_the_frozen_batch_files_are_byte_identical_to_the_manifest():
    """Frozen specs/manifests are pinned by SHA-256, independent of this host."""
    manifest = BATCH / "MANIFEST.sha256"
    assert manifest.is_file(), manifest
    errors = []
    entries = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        rel = rel.strip()
        path = BATCH / rel
        entries += 1
        if not path.is_file():
            errors.append(f"missing {rel}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append(f"hash mismatch {rel}")
    assert entries > 0
    assert errors == []


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


def test_the_cli_check_mode_passes(tmp_path):
    # ``--check`` legitimately fails on the delivered tree because the 16 specs
    # embed the original checkout root. Run it on a copy whose only differences
    # are those documented host-path fields (plus the manifest digests that
    # derive from them), so a real config/switch/case drift still fails.
    import shutil

    dest = tmp_path / "batch"
    shutil.copytree(BATCH, dest)
    for spec_file in sorted((dest / "specs").glob("*/spec.json")):
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        case = spec["case"]
        relative_results = (
            Path("specs") / spec_file.parent.name / "runs" / "run_01"
            / "attempt_01" / "runtime" / case["ticker"] / case["trade_date"]
        )
        spec["experiment_root"] = str(REPO_ROOT)
        spec["results_dir"] = str(dest / relative_results)
        spec_file.write_text(
            json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    manifest = dest / "RUN_MANIFEST_TEMPLATE.csv"
    rows = _manifest_rows(manifest.read_text(encoding="utf-8"))
    for row in rows:
        spec = json.loads((dest / row["spec_path"]).read_text(encoding="utf-8"))
        row["spec_body_sha256"] = gv3.spec_body_sha256(spec)
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(dest),
         "--memory-baseline", str(dest / "memory/baseline_v3.md"), "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "artefacts reproduce" in result.stdout
