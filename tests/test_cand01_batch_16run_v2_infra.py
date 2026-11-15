"""Harness V2 infrastructure: spec generation, hashing, switches, accounting.

These tests are the machine-checkable part of
``token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/CAND01_BATCH_2X2_PROTOCOL_V2.md``.
They generate the 16 specs into a temporary directory (never into the delivered
tree) and assert the properties the protocol depends on.

The non-vacuity tests at the bottom mutate the inputs and assert the checks
*fire*; a check that cannot fail is not a check.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "gen_cand01_batch_16run_specs_v2.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_v2", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gv2 = _load_generator()


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("v2_specs")
    artifacts = gv2.build(out)
    gv2.write_artifacts(out, artifacts)
    return out


def _runs(root: Path):
    rows = []
    for directory in sorted((root / "specs").iterdir()):
        rows.append({
            "dir": directory.name,
            "experiment": json.loads((directory / "experiment.json").read_text()),
            "spec": json.loads((directory / "spec.json").read_text()),
        })
    return rows


# --- 1. spec-set completeness ----------------------------------------------


def test_16_specs_are_generated(generated):
    assert len(list((generated / "specs").iterdir())) == 16


def test_every_spec_directory_has_the_three_files(generated):
    for directory in (generated / "specs").iterdir():
        for name in ("experiment.json", "spec.json", "code_state.json"):
            assert (directory / name).is_file(), f"{directory.name} missing {name}"


def test_top_level_manifests_are_present(generated):
    for name in (
        "experiment.json",
        "SWITCH_MATRIX.csv",
        "RUN_MANIFEST_TEMPLATE.csv",
        "CONFIG_HASH_MANIFEST.csv",
        "EXECUTION_ORDER.txt",
    ):
        assert (generated / name).is_file(), name


def test_the_4x4_design_covers_every_cell_exactly_once(generated):
    cells = [
        (r["experiment"]["cases"][0]["ticker"], r["dir"].split("_")[2])
        for r in _runs(generated)
    ]
    assert sorted(cells) == sorted(
        (t, a)
        for t in ("AAPL", "JPM", "NVDA", "XOM")
        for a in ("B", "AB", "C0", "CC")
    )


def test_each_ticker_has_all_four_arms(generated):
    for ticker in ("NVDA", "AAPL", "JPM", "XOM"):
        arms = {r["dir"].split("_")[2] for r in _runs(generated)
                if r["dir"].split("_")[1] == ticker}
        assert arms == {"B", "AB", "C0", "CC"}, ticker


def test_all_runs_share_one_trade_date(generated):
    dates = {r["experiment"]["cases"][0]["trade_date"] for r in _runs(generated)}
    assert dates == {"2026-09-23"}


def test_all_arms_differ_only_in_the_two_experiment_switches(generated):
    for run in _runs(generated):
        switches = run["experiment"]["switches"]
        # Held constant across all four arms by design.
        assert switches["structured"] is True
        assert switches["s2_downstream"] is True
        # The 2x2 factors.
        assert switches["single_pass"] is (run["dir"].split("_")[2] in ("C0", "CC"))
        assert switches["batch_macro"] is (run["dir"].split("_")[2] in ("AB", "CC"))


# --- 2. run identity and order ---------------------------------------------


def test_run_ids_are_unique_and_sequential(generated):
    ids = sorted(r["dir"].split("_")[0] for r in _runs(generated))
    assert ids == [f"R{n:02d}" for n in range(1, 17)]


def test_run_id_position_matches_the_manifest(generated, tmp_path):
    text = (generated / "SWITCH_MATRIX.csv").read_text().splitlines()
    header, rows = text[0].split(","), [line.split(",") for line in text[1:]]
    pos = {row[0]: int(row[1]) for row in rows}
    assert sorted(pos.values()) == list(range(1, 17))
    assert header[0] == "run_id"


def test_execution_order_is_reproducible_from_the_seed(generated):
    order = gv2.execution_order()
    # A second, independent construction must agree.
    assert order == gv2.execution_order(20261114)
    recorded = (generated / "EXECUTION_ORDER.txt").read_text()
    for block, arms in order.items():
        assert f"{block}: {arms}" in recorded


def test_execution_order_matches_the_v1_pre_registered_order():
    """V2 re-registers the specs but must not silently re-randomise them."""
    assert gv2.execution_order() == {
        "NVDA": ["C0", "AB", "CC", "B"],
        "AAPL": ["C0", "B", "CC", "AB"],
        "JPM": ["C0", "AB", "B", "CC"],
        "XOM": ["C0", "CC", "B", "AB"],
    }


def test_within_each_block_the_run_ids_are_contiguous(generated):
    runs = _runs(generated)
    for ticker in ("NVDA", "AAPL", "JPM", "XOM"):
        block_ids = sorted(
            int(r["dir"].split("_")[0][1:]) for r in runs
            if r["dir"].split("_")[1] == ticker
        )
        assert block_ids == list(range(block_ids[0], block_ids[0] + 4)), ticker


# --- 3. config_sha256 -------------------------------------------------------


def test_hash_is_stable_across_calls(generated):
    for run in _runs(generated):
        assert gv2.config_sha256(run["experiment"]) == run["experiment"]["config_sha256"]


def test_all_16_hashes_are_distinct(generated):
    hashes = [r["experiment"]["config_sha256"] for r in _runs(generated)]
    assert len(set(hashes)) == 16


def test_hash_is_64_lowercase_hex(generated):
    import re
    for run in _runs(generated):
        assert re.fullmatch(r"[0-9a-f]{64}", run["experiment"]["config_sha256"])


def test_the_spec_carries_the_same_hash_as_its_experiment(generated):
    for run in _runs(generated):
        assert run["spec"]["config_sha256"] == run["experiment"]["config_sha256"]


def test_code_state_records_the_definition_hash_not_a_hand_value(generated):
    for directory in (generated / "specs").iterdir():
        state = json.loads((directory / "code_state.json").read_text())
        assert len(state["experiment_definition_sha256"]) == 64
        assert len(state["generator_sha256"]) == 64


def test_hash_input_fields_are_recorded_explicitly():
    """The hashed field set is part of the protocol, so it must not drift."""
    assert gv2.HASHED_FIELDS == (
        "experiment_id", "schema_version", "switches_required", "provider",
        "quick_model", "deep_model", "output_language", "cache_policy",
        "checkpoint_enabled", "budget", "cases", "switches", "news_scope",
    )


# --- 4. switch delivery -----------------------------------------------------


def test_switch_env_var_names_match_the_product_code():
    """Each switch's env var must be a real row of ``_ENV_OVERRIDES``."""
    from tradingagents import default_config

    overrides = default_config._ENV_OVERRIDES
    expected_key = {
        "batch_macro": "batch_macro_enabled",
        "single_pass": "single_pass_finalization_enabled",
        "structured": "structured_analyst_output_enabled",
    }
    for switch, env_name in gv2.SWITCH_ENV_VARS.items():
        assert overrides.get(env_name) == expected_key[switch], switch
    # Every implemented switch must have a delivery route.
    assert set(gv2.SWITCH_ENV_VARS) == {"batch_macro", "single_pass", "structured"}


@pytest.mark.parametrize(
    "arm,expected",
    [
        ("B", {"batch_macro_enabled": False, "single_pass_finalization_enabled": False,
               "structured_analyst_output_enabled": True}),
        ("AB", {"batch_macro_enabled": True, "single_pass_finalization_enabled": False,
                "structured_analyst_output_enabled": True}),
        ("C0", {"batch_macro_enabled": False, "single_pass_finalization_enabled": True,
                "structured_analyst_output_enabled": True}),
        ("CC", {"batch_macro_enabled": True, "single_pass_finalization_enabled": True,
                "structured_analyst_output_enabled": True}),
    ],
)
def test_switch_env_vars_reach_the_child_configuration(arm, expected):
    """Run each arm's env in a *fresh interpreter*, as the harness spawns it."""
    import os

    switches = gv2.ARM_SWITCHES[arm]
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRADINGAGENTS_")}
    env["TZ"] = "UTC"
    for name, value in switches.items():
        if name in gv2.SWITCH_ENV_VARS:
            env[gv2.SWITCH_ENV_VARS[name]] = "true" if value else "false"
    code = (
        "import json\n"
        "from tradingagents.default_config import DEFAULT_CONFIG as C\n"
        f"print(json.dumps({{k: C[k] for k in {list(expected)!r}}}))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == expected


def test_s2_downstream_false_is_refused_not_ignored():
    with pytest.raises(gv2.RefusedError, match="s2_downstream"):
        gv2.require_supported_switches({"s2_downstream": False})


def test_s2_downstream_true_is_accepted():
    gv2.require_supported_switches({"s2_downstream": True})


# --- 5. Finnhub-only scope is baked into every spec ------------------------


def test_every_spec_declares_the_finnhub_only_scope(generated):
    for run in _runs(generated):
        scope = run["experiment"]["news_scope"]
        assert scope["company_news"] == "finnhub"
        assert scope["gdelt"] == "excluded"
        assert scope["global_news"] == "finnhub:CONFIG_DISABLED"


def test_the_shipped_default_never_routes_news_to_gdelt():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["tool_vendors"]["get_news"] == "finnhub"
    assert DEFAULT_CONFIG["tool_vendors"]["get_global_news"] == "finnhub"


# --- 6. budget --------------------------------------------------------------


def test_the_budget_cap_is_unset_by_design(generated):
    round_cfg = json.loads((generated / "experiment.json").read_text())
    assert round_cfg["budget"]["max_total_tokens"] is None
    for run in _runs(generated):
        assert run["experiment"]["budget"]["max_total_tokens"] is None


# --- 7. generation hygiene --------------------------------------------------


def test_generation_is_byte_reproducible(generated):
    again = copy.deepcopy(gv2.build(generated))
    for rel, content in again.items():
        path = generated / rel
        if rel.endswith("code_state.json"):
            continue  # wall-clock timestamp is expected to differ
        assert path.read_text() == content, rel


def test_generator_refuses_to_overwrite_existing_artefacts(generated):
    out = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(generated)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert out.returncode == 2
    assert "refusing to overwrite" in out.stderr


def test_check_mode_detects_tampering(generated, tmp_path):
    tampered = tmp_path / "tampered"
    gv2.write_artifacts(tampered, gv2.build(tampered))
    target = tampered / "specs" / "R01_NVDA_C0" / "experiment.json"
    doc = json.loads(target.read_text())
    doc["switches"]["batch_macro"] = not doc["switches"]["batch_macro"]
    target.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    out = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(tampered), "--check"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert out.returncode == 1
    assert "DRIFT" in out.stderr


# --- 8. non-vacuity ---------------------------------------------------------
#
# Each test below proves a check can fail. If the check silently passed, the
# corresponding invariant above would be worthless.


@pytest.mark.parametrize(
    "field", ["batch_macro", "single_pass", "structured", "s2_downstream"]
)
def test_flipping_any_switch_changes_the_hash(field):
    base = gv2.per_run_experiment(
        {"run_id": "R01", "position": 1, "ticker": "NVDA", "arm": "C0"}
    )
    flipped = copy.deepcopy(base)
    flipped.pop("config_sha256")
    flipped["switches"][field] = not flipped["switches"][field]
    assert gv2.config_sha256(flipped) != base["config_sha256"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("quick_model", "other-model"),
        ("deep_model", "other-model"),
        ("provider", "anthropic"),
        ("output_language", "Chinese"),
        ("cache_policy", "clear"),
        ("checkpoint_enabled", True),
        ("switches_required", False),
    ],
)
def test_changing_any_hashed_field_changes_the_hash(field, value):
    base = gv2.per_run_experiment(
        {"run_id": "R01", "position": 1, "ticker": "NVDA", "arm": "C0"}
    )
    changed = copy.deepcopy(base)
    changed.pop("config_sha256")
    changed[field] = value
    assert gv2.config_sha256(changed) != base["config_sha256"]


def test_changing_the_case_changes_the_hash():
    base = gv2.per_run_experiment(
        {"run_id": "R01", "position": 1, "ticker": "NVDA", "arm": "C0"}
    )
    changed = copy.deepcopy(base)
    changed.pop("config_sha256")
    changed["cases"][0]["trade_date"] = "2026-09-24"
    assert gv2.config_sha256(changed) != base["config_sha256"]


def test_changing_the_news_scope_changes_the_hash():
    base = gv2.per_run_experiment(
        {"run_id": "R01", "position": 1, "ticker": "NVDA", "arm": "C0"}
    )
    changed = copy.deepcopy(base)
    changed.pop("config_sha256")
    changed["news_scope"] = dict(base["news_scope"], gdelt="included")
    assert gv2.config_sha256(changed) != base["config_sha256"]


def test_excluded_fields_do_not_change_the_hash():
    base = gv2.per_run_experiment(
        {"run_id": "R01", "position": 1, "ticker": "NVDA", "arm": "C0"}
    )
    changed = copy.deepcopy(base)
    changed.pop("config_sha256")
    changed["description"] = "different prose"
    assert gv2.config_sha256(changed) == base["config_sha256"]


def test_a_missing_hashed_field_is_an_error_not_a_default():
    base = gv2.per_run_experiment(
        {"run_id": "R01", "position": 1, "ticker": "NVDA", "arm": "C0"}
    )
    broken = copy.deepcopy(base)
    broken.pop("switches")
    with pytest.raises(KeyError, match="switches"):
        gv2.config_sha256(broken)


# ---------------------------------------------------------------------------
# The C3 protocol freeze declaration must agree with the registrations
# ---------------------------------------------------------------------------
def test_protocol_freeze_verification_passes():
    """``C3_PROTOCOL_FREEZE.md`` restates the design; it must not drift.

    Run before the first paid call. The restatement is what an operator reads
    before spending money, so a drifted one is worse than none.
    """
    import subprocess
    import sys

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(root / "scripts/c3_verify_protocol_freeze.py")],
        cwd=root, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(root)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROTOCOL FREEZE VERIFIED" in result.stdout


def test_freeze_declaration_states_the_correct_axes():
    """The design varies batch_macro x single_pass; structured is held constant.

    Writing the axes down wrong is how a reader comes to believe an arm tests
    something it does not (the same class of error as a spec that runs as the
    wrong arm).
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    doc = (root / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
           / "C3_PROTOCOL_FREEZE.md").read_text()
    assert "`batch_macro` × `single_pass`" in doc
    assert "no paid call was made before this document was committed" in doc.lower()
    assert "0" in doc.split("Paid calls at freeze time")[1].split("\n")[0]
