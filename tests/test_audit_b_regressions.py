"""Regressions from independent audit B (harness & specs), items B1 and B4.

B1 was the decisive finding: the run path never read ``spec["switches"]``, so
the only thing that could put a switch into the child was an ambient
``TRADINGAGENTS_*`` variable. Under a neutral environment the audit measured
**12 of 16** delivered specs running with switches that contradict their own
arm label (every C0 and CC run -- the entire CAND-01 factor -- plus every B run).

Every test here builds the config from a *real delivered spec*, not from a
literal, and the non-vacuity section proves the tests would have failed on the
audited code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.token_benchmark as harness
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.switch_verification import (
    SwitchNotConsumed,
    validate_spec_switches,
    verify_switches_consumed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = (REPO_ROOT / "token_benchmarks" / "live_pilot_2x2"
            / "cand01_batch_16run_v2" / "specs")

SWITCH_KEYS = {
    "batch_macro": "batch_macro_enabled",
    "structured": "structured_analyst_output_enabled",
    "single_pass": "single_pass_finalization_enabled",
}


def delivered_specs() -> list[Path]:
    paths = sorted(SPEC_DIR.glob("*/spec.json"))
    assert len(paths) == 16, f"expected 16 delivered specs, found {len(paths)}"
    return paths


def load(spec_path: Path) -> dict:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    spec["_dir"] = Path(spec_path).parent.name
    return spec


def arm_of(spec: dict) -> str:
    """The arm is encoded in the directory name (``R01_NVDA_C0``), not in
    ``experiment_id`` (``R01``): the ID is arm-agnostic by design."""
    return spec["_dir"].split("_")[-1]


def neutral_defaults() -> dict:
    """``DEFAULT_CONFIG`` with every switch forced to the non-spec value.

    This is the audit's neutral environment in miniature: if the spec is not the
    source, the result cannot match the arm.
    """
    base = dict(DEFAULT_CONFIG)
    base["batch_macro_enabled"] = True
    base["structured_analyst_output_enabled"] = True
    base["single_pass_finalization_enabled"] = False
    return base


# --- B1: the spec is the source of the switches -----------------------------


@pytest.mark.parametrize("spec_path", delivered_specs(), ids=lambda p: p.parent.name)
def test_every_delivered_spec_reaches_config_as_declared(spec_path):
    spec = load(spec_path)
    config = dict(neutral_defaults())
    harness._apply_spec_switches(spec, config, neutral_defaults())

    for name, key in SWITCH_KEYS.items():
        assert config[key] is spec["switches"][name], (spec_path.parent.name, name)


@pytest.mark.parametrize("arm", ["B", "AB", "C0", "CC"])
def test_each_arm_is_distinguishable_from_a_neutral_environment(arm):
    """The audit's blast radius, inverted: each arm must differ from neutral."""
    spec_path = next(p for p in delivered_specs()
                     if arm_of(load(p)) == arm)
    spec = load(spec_path)
    config = dict(neutral_defaults())
    harness._apply_spec_switches(spec, config, neutral_defaults())
    # An arm is distinguishable when the tuple of switch values it produces
    # differs from the tuple a spec-free (neutral) run would produce. AB happens
    # to *equal* the shipped defaults, so it is not "changed" -- it is still
    # identified, because it is the one arm that equals the defaults, and the
    # other three cannot be confused with it.
    produced = tuple(config[k] for k in SWITCH_KEYS.values())
    neutral = tuple(neutral_defaults()[k] for k in SWITCH_KEYS.values())
    same_as_neutral = produced == neutral
    if arm != "AB":
        assert not same_as_neutral, (
            f"arm {arm} would run identically to a neutral environment"
        )
    else:
        assert same_as_neutral, "AB is the arm that equals the shipped defaults"


def test_the_C0_and_CC_arms_really_flip_single_pass():
    """The whole CAND-01 factor: only these two arms turn single-pass on."""
    on = set()
    for spec_path in delivered_specs():
        spec = load(spec_path)
        if spec["switches"]["single_pass"]:
            on.add(arm_of(spec))
    assert on == {"C0", "CC"}


def test_a_spec_contradicting_an_exported_env_var_is_refused():
    """Two records disagreeing about the arm is not a tie to break silently."""
    spec = load(delivered_specs()[0])
    spec = dict(spec)
    spec["switches"] = dict(spec["switches"], single_pass=not spec["switches"]["single_pass"])
    ambient = dict(neutral_defaults())
    # Ambient agrees with the *other* value.
    key = SWITCH_KEYS["single_pass"]
    ambient[key] = spec["switches"]["single_pass"] is False
    with pytest.raises(SwitchNotConsumed, match="refusing to run an ambiguous arm"):
        harness._apply_spec_switches(
            spec, dict(ambient), ambient, explicitly_exported=frozenset({key})
        )


def test_an_unset_variable_is_not_a_contradiction():
    """A neutral environment has no opinion; the spec fills the gap."""
    spec = load(delivered_specs()[0])
    config = dict(neutral_defaults())
    harness._apply_spec_switches(spec, config, neutral_defaults(),
                                 explicitly_exported=frozenset())
    assert config[SWITCH_KEYS["single_pass"]] is spec["switches"]["single_pass"]


def test_a_spec_without_switches_is_left_on_defaults():
    """Pre-V2 specs keep the shipped behaviour; nothing unrelated breaks."""
    config = {"batch_macro_enabled": True}
    applied = harness._apply_spec_switches({"experiment_id": "old"}, config, config)
    assert applied == {}
    assert config == {"batch_macro_enabled": True}


def test_a_spec_declaring_s2_downstream_false_is_refused_by_the_run_path():
    spec = load(delivered_specs()[0])
    spec = dict(spec)
    spec["switches"] = dict(spec["switches"], s2_downstream=False)
    config = dict(neutral_defaults())
    with pytest.raises(SwitchNotConsumed, match="s2_downstream"):
        harness._apply_spec_switches(spec, config, neutral_defaults())


# --- B1: the child environment also carries the arm -------------------------


def test_child_env_exports_every_declared_switch():
    spec = load(delivered_specs()[0])
    env = harness._child_env_for_spec(spec)
    for name, env_var in harness.SPEC_SWITCH_ENV:
        assert env[env_var] == ("true" if spec["switches"][name] else "false"), name


def test_child_env_has_no_variable_for_the_unimplemented_switch():
    declared = {name for name, _ in harness.SPEC_SWITCH_ENV}
    assert "s2_downstream" not in declared


def test_child_env_carries_the_finnhub_key_from_the_parent(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "sentinel-key")
    env = harness._child_env_for_spec({"experiment_id": "x", "switches": {}})
    assert env["FINNHUB_API_KEY"] == "sentinel-key"


# --- B1: the verifier really runs on the constructed graph ------------------


@pytest.mark.parametrize("spec_path", delivered_specs(), ids=lambda p: p.parent.name)
def test_the_constructed_setup_reproduces_every_delivered_arm(spec_path):
    spec = load(spec_path)
    config = dict(neutral_defaults())
    harness._apply_spec_switches(spec, config, neutral_defaults())

    class _Setup:
        pass

    setup = _Setup()
    setup.config = config
    observed = __import__(
        "tradingagents.graph.switch_verification", fromlist=["x"]
    ).consume_switches_from_setup(setup)
    verify_switches_consumed(spec["switches"], observed=observed)


def test_a_mismatched_spec_is_rejected_after_a_real_build(monkeypatch):
    """Non-vacuity: the verifier is not a formality over the right answer."""
    import tradingagents.graph.setup as setup_mod
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    spec_path = next(p for p in delivered_specs()
                     if load(p)["switches"]["single_pass"])
    spec = load(spec_path)
    config = dict(neutral_defaults())
    harness._apply_spec_switches(spec, config, neutral_defaults())

    fake_llm = FakeListChatModel(responses=["ok"] * 20)
    graph_setup = setup_mod.GraphSetup(
        quick_thinking_llm=fake_llm,
        deep_thinking_llm=fake_llm,
        tool_nodes=TradingAgentsGraph._create_tool_nodes(None),
        conditional_logic=ConditionalLogic(),
        config=config,
    )
    from tradingagents.graph.switch_verification import consume_switches_from_setup

    observed = consume_switches_from_setup(graph_setup)
    verify_switches_consumed(spec["switches"], observed=observed)

    # The spec claims the opposite arm: the comparison must fail.
    wrong = dict(spec["switches"], single_pass=not spec["switches"]["single_pass"])
    with pytest.raises(SwitchNotConsumed):
        verify_switches_consumed(wrong, observed=observed)


def test_consume_from_setup_matches_the_real_graphsetup(monkeypatch):
    """The mirrored derivation must equal what the real graph really passes."""
    from tests.test_switch_consumption import ARMS, build_real_graph
    from tradingagents.graph.switch_verification import consume_switches_from_setup

    for arm, switches in ARMS.items():
        observed = build_real_graph(switches, monkeypatch)

        class _Setup:
            pass

        setup = _Setup()
        setup.config = {
            "batch_macro_enabled": switches["batch_macro"],
            "structured_analyst_output_enabled": switches["structured"],
            "single_pass_finalization_enabled": switches["single_pass"],
        }
        mirrored = consume_switches_from_setup(setup)
        assert mirrored == observed, arm


# --- B4: the overwrite guard must not be a single-file check ---------------


def test_generator_refuses_a_specs_tree_without_experiment_json(tmp_path):
    """The audited bug: only ``experiment.json`` was checked."""
    import scripts.gen_cand01_batch_16run_specs_v2 as gen

    tampered = tmp_path / "c1" / "specs" / "R01_NVDA_C0"
    tampered.mkdir(parents=True)
    (tampered / "spec.json").write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(gen.RefusedError):
        gen.ensure_writable_out_dir(tmp_path / "c1")


def test_generator_still_accepts_an_empty_directory(tmp_path):
    import scripts.gen_cand01_batch_16run_specs_v2 as gen

    empty = tmp_path / "fresh"
    empty.mkdir()
    gen.ensure_writable_out_dir(empty)   # must not raise


def test_generator_refuses_the_delivered_tree():
    import scripts.gen_cand01_batch_16run_specs_v2 as gen

    out = REPO_ROOT / "token_benchmarks" / "live_pilot_2x2" / "cand01_batch_16run_v2"
    with pytest.raises(gen.RefusedError):
        gen.ensure_writable_out_dir(out)


# --- delivered specs stay valid under the product guard -------------------


@pytest.mark.parametrize("spec_path", delivered_specs(), ids=lambda p: p.parent.name)
def test_delivered_specs_pass_the_product_guard(spec_path):
    spec = load(spec_path)
    validate_spec_switches(spec["switches"])


# --- B1: end-to-end through the real ``_run_single`` -----------------------
#
# The unit tests above exercise ``_apply_spec_switches``. This one drives the
# actual function the harness spawns for every measured run, with the graph
# construction stubbed out, so it fails if ``_run_single`` stops calling the
# helper -- which was the audited bug (the helper did not exist, and nothing in
# the run path read ``spec["switches"]``).


def _run_single_with_stub_graph(tmp_path, monkeypatch, spec: dict, ambient: dict):
    """Run the real ``_run_single``; return the config the graph would get."""
    import sys
    import types

    captured = {}

    class _StubGraph:
        def __init__(self, *args, **kwargs):
            captured["config"] = dict(kwargs["config"])
            # The run path reads the *constructed* setup back to prove the
            # switches were consumed; a stub must expose the same attribute.
            self.graph_setup = types.SimpleNamespace(config=kwargs["config"])

        def propagate(self, *args, **kwargs):
            return {}

    module = types.ModuleType("tradingagents.graph.trading_graph")
    module.TradingAgentsGraph = _StubGraph
    monkeypatch.setitem(sys.modules, "tradingagents.graph.trading_graph", module)

    # ``default_config`` is imported once at process start; force the ambient
    # value here so this test does not depend on the shell that ran it.
    import tradingagents.default_config as dc
    patched_defaults = dict(dc.DEFAULT_CONFIG)
    patched_defaults.update(ambient)
    monkeypatch.setattr(dc, "DEFAULT_CONFIG", patched_defaults)

    spec_path = tmp_path / "spec.json"
    # A spec may only claim the hash of the run it belongs to, so give the
    # helper the registration beside it. C3 recomputes ``config_sha256`` from
    # the definition rather than trusting the string, so a bare spec with no
    # registration is (correctly) refused before reaching this point.
    registration = SPEC_DIR / spec.get("_dir", "") / "experiment.json"
    if registration.is_file():
        (tmp_path / "experiment.json").write_bytes(registration.read_bytes())
        spec = dict(spec, registration_dir=str(tmp_path))
    spec.pop("_dir", None)
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return harness._run_single(str(spec_path)), captured


def test_run_single_applies_the_spec_switches_to_the_graph_config(tmp_path, monkeypatch):
    spec = load(delivered_specs()[2])          # R03_NVDA_CC
    assert spec["switches"]["single_pass"] is True
    _code, captured = _run_single_with_stub_graph(tmp_path, monkeypatch, spec, {
        "single_pass_finalization_enabled": False,   # neutral / hostile default
        "batch_macro_enabled": True,
        "structured_analyst_output_enabled": True,
    })
    assert captured["config"]["single_pass_finalization_enabled"] is True, (
        "the run path ignored the spec and ran the shipped default arm"
    )


def test_run_single_applies_batch_macro_false_from_the_spec(tmp_path, monkeypatch):
    spec = load(delivered_specs()[3])          # R04_NVDA_B
    assert spec["switches"]["batch_macro"] is False
    _code, captured = _run_single_with_stub_graph(tmp_path, monkeypatch, spec, {
        "batch_macro_enabled": True,
        "single_pass_finalization_enabled": False,
        "structured_analyst_output_enabled": True,
    })
    assert captured["config"]["batch_macro_enabled"] is False


def test_run_single_refuses_a_spec_whose_arm_is_ambiguous(tmp_path, monkeypatch):
    spec = load(delivered_specs()[3])          # B: single_pass=False, batch_macro=False
    ambient = {
        "batch_macro_enabled": True,           # exported value disagrees
        "single_pass_finalization_enabled": False,
        "structured_analyst_output_enabled": True,
    }
    monkeypatch.setenv("TRADINGAGENTS_BATCH_MACRO_ENABLED", "true")
    # C3 moved the check ahead of graph construction, and a refused run now
    # reports through ``refusal.json`` + exit code 2 instead of raising out of
    # ``_run_single``. What matters is unchanged: no graph is built and the
    # reason is recorded, so a mislabelled arm can never produce a sample.
    exit_code, captured = _run_single_with_stub_graph(tmp_path, monkeypatch, spec, ambient)
    assert exit_code == 2
    refusal = json.loads((tmp_path / harness.REFUSAL_FILE).read_text())
    assert "batch_macro=False" in refusal["reason"]
    assert captured == {}
