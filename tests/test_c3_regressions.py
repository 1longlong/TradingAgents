"""Plan C3 regressions: the two C3 defects found before the paid pilot.

Neither is a style issue; each was observed on the real code path:

``C3-01`` -- ``scripts/token_benchmark._run_single`` built
``TradingAgentsGraph`` twice per measured run: once to construct it, then again
after the switch check, discarding the first. The first instance had already
created LLM clients and a ``StatsCallbackHandler``, so two live handlers existed
for one run and the construction cost was paid twice.

``C3-02`` -- ``observability._extract_usage_metadata`` read cached input only
from the LangChain spelling (``input_token_details.cache_read``). The endpoint
this study actually calls reports ``prompt_tokens_details.cached_tokens`` and
``prompt_cache_hit_tokens``, so genuine cache hits were recorded as ``0`` --
a measured quantity reported as unmeasured.
"""
import inspect
import textwrap

import pytest

from tradingagents.observability import _extract_usage_metadata


def _run_single_source() -> str:
    import scripts.token_benchmark as tb

    return inspect.getsource(tb._run_single)


# ---------------------------------------------------------------------------
# C3-01: exactly one graph per measured run
# ---------------------------------------------------------------------------
def test_run_single_constructs_exactly_one_graph():
    src = _run_single_source()
    assert src.count("TradingAgentsGraph(") == 1, (
        "one measured run must construct exactly one graph; a second "
        "construction creates a second live stats handler"
    )


def test_run_single_constructs_exactly_one_stats_handler():
    src = _run_single_source()
    assert src.count("StatsCallbackHandler()") == 1


def test_switch_verification_happens_before_propagate():
    """A mislabelled arm must be refused before it can spend money."""
    src = _run_single_source()
    verify_at = src.index("verify_switches_consumed(")
    propagate_at = src.index("graph.propagate(")
    assert verify_at < propagate_at


def test_switch_verification_reads_the_live_graph():
    """The check must inspect the graph that will run, not a stand-in."""
    src = _run_single_source()
    assert "consume_switches_from_setup(graph.graph_setup)" in src


# ---------------------------------------------------------------------------
# C3-02: cached input is read from every spelling the provider may use
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        # The exact shape the configured endpoint returned on a live probe.
        (
            {
                "completion_tokens": 1,
                "prompt_tokens": 9,
                "total_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 0},
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 9,
            },
            0,
        ),
        # DeepSeek-style gateway with real cache hits.
        (
            {
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "prompt_tokens_details": {"cached_tokens": 800},
                "prompt_cache_hit_tokens": 800,
            },
            800,
        ),
        # LangChain-normalised spelling, unchanged from before.
        (
            {"input_tokens": 300, "output_tokens": 7,
             "input_token_details": {"cache_read": 128}},
            128,
        ),
        # Anthropic-style spelling seen through some gateways.
        ({"input_tokens": 300, "output_tokens": 7,
          "cache_read_input_tokens": 64}, 64),
    ],
)
def test_cached_input_is_read_from_each_provider_spelling(raw, expected):
    assert _extract_usage_metadata(raw)["cached_input"] == expected


def test_cached_input_is_not_double_counted_across_spellings():
    """Two spellings of one number must not be added together."""
    raw = {
        "input_tokens": 300,
        "output_tokens": 7,
        "input_token_details": {"cache_read": 128},
        "prompt_cache_hit_tokens": 128,
        "prompt_tokens_details": {"cached_tokens": 128},
    }
    assert _extract_usage_metadata(raw)["cached_input"] == 128


def test_absent_cached_input_stays_unknown_not_zero():
    """No cache field anywhere must be ``None`` (unknown), never 0."""
    usage = _extract_usage_metadata({"input_tokens": 10, "output_tokens": 2})
    assert usage["cached_input"] is None


def test_cached_input_never_enters_the_input_total():
    """Cached tokens are a subset of input; totals must not grow."""
    raw = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 800},
    }
    usage = _extract_usage_metadata(raw)
    assert usage["input"] == 1000
    assert usage["output"] == 50


# ---------------------------------------------------------------------------
# C3-03: import provenance is enforced, not assumed
# ---------------------------------------------------------------------------
def test_verify_import_root_accepts_this_tree():
    import scripts.token_benchmark as tb

    tb.verify_import_root(tb._PROJECT_ROOT)   # must not raise


def test_verify_import_root_rejects_a_foreign_tree(tmp_path):
    import scripts.token_benchmark as tb

    with pytest.raises(RuntimeError, match="refusing to run"):
        tb.verify_import_root(tmp_path / "some_other_checkout")


def test_run_single_checks_import_root_before_building_clients():
    src = _run_single_source()
    assert src.index("verify_import_root(") < src.index("TradingAgentsGraph(")


def test_run_single_writes_effective_config_before_propagating():
    src = _run_single_source()
    assert "_write_effective_config(" in src
    assert src.index("_write_effective_config(") < src.index("graph.propagate(")


def test_prepare_run_spec_pins_the_experiment_root(tmp_path):
    import scripts.token_benchmark as tb

    exp = tmp_path / "exp"
    exp.mkdir()
    case = {"ticker": "NVDA", "trade_date": "2026-09-23", "case_id": "c1",
            "analysts": ["market"], "research_rounds": 1, "risk_rounds": 1}
    spec_path = tb.prepare_run_spec(exp, {"experiment_id": "e"}, case, 1)
    import json

    spec = json.loads(spec_path.read_text())
    assert spec["experiment_root"] == str(tb._PROJECT_ROOT)


def test_effective_config_redacts_secrets_and_records_provenance(tmp_path, monkeypatch):
    import json

    import scripts.token_benchmark as tb
    import tradingagents.graph.switch_verification as sv

    class _FakeSetup:
        def __init__(self):
            self.batch_macro = True

    class _FakeGraph:
        graph_setup = _FakeSetup()

    # Patch the collaborator the writer imports, not the writer's own module
    # globals: restoring is then guaranteed by monkeypatch even if the body
    # raises, and no reload of the harness is needed.
    monkeypatch.setattr(sv, "consume_switches_from_setup",
                        lambda setup: {"batch_macro": True})

    path = tb._write_effective_config(
        tmp_path,
        config={"api_key": "sk-should-never-appear", "quick_think_llm": "m"},
        spec={"switches": {"batch_macro": True}},
        graph=_FakeGraph(),
        applied_switches={"batch_macro_enabled": True},
    )

    text = path.read_text()
    assert "sk-should-never-appear" not in text
    payload = json.loads(text)
    assert payload["resolved_config"]["api_key"] == {"redacted": True, "is_set": True}
    assert payload["import_provenance"]["tradingagents_module"].endswith("__init__.py")


# ---------------------------------------------------------------------------
# C3-04: refusal is a distinct outcome, not a failed attempt
# ---------------------------------------------------------------------------
_GOOD_SWITCHES = {"batch_macro": True, "structured": True,
                  "single_pass": False, "s2_downstream": True}
_GOOD_SCOPE = {"company_news": "finnhub", "global_news": "finnhub:CONFIG_DISABLED",
               "gdelt": "excluded"}


def test_preflight_accepts_a_conforming_spec():
    import scripts.token_benchmark as tb

    assert tb._preflight_gate(
        {"switches": dict(_GOOD_SWITCHES), "news_scope": dict(_GOOD_SCOPE)}
    ) == {"checked": True}


@pytest.mark.parametrize("scope", [
    {"company_news": "gdelt", "global_news": "finnhub:CONFIG_DISABLED", "gdelt": "excluded"},
    {"company_news": "alpha_vantage", "global_news": "finnhub:CONFIG_DISABLED", "gdelt": "excluded"},
    {"company_news": "finnhub", "global_news": "gdelt", "gdelt": "excluded"},
    {"company_news": "finnhub", "global_news": "finnhub:CONFIG_DISABLED", "gdelt": "enabled"},
])
def test_preflight_refuses_a_non_finnhub_news_scope(scope):
    import scripts.token_benchmark as tb

    with pytest.raises(tb.RunRefused):
        tb._preflight_gate({"switches": dict(_GOOD_SWITCHES), "news_scope": scope})


def test_preflight_refuses_s2_downstream_false():
    import scripts.token_benchmark as tb

    switches = dict(_GOOD_SWITCHES, s2_downstream=False)
    with pytest.raises(tb.RunRefused):
        tb._preflight_gate({"switches": switches})


def test_a_run_refusal_is_raised_not_recorded_as_metrics(tmp_path):
    import scripts.token_benchmark as tb

    def refusing_runner(*_a, **_k):
        return {"status": tb.RUN_REFUSED_STATUS, "error": "bad scope",
                "report": None, "telemetry_new": [], "telemetry_before": []}

    with pytest.raises(tb.RunRefused, match="bad scope"):
        tb.execute_measured_run(
            tmp_path, {"experiment_id": "e"},
            {"ticker": "NVDA", "trade_date": "2026-09-23", "case_id": "c"},
            1, runner=refusing_runner, run_dir=tmp_path,
        )


def test_refusal_log_is_separate_from_attempts(tmp_path):
    import json

    import scripts.token_benchmark as tb

    log = tb._record_refusal(
        tmp_path, {"ticker": "NVDA", "trade_date": "2026-09-23", "case_id": "c"},
        3, tb.RunRefused("spec switches rejected"),
    )
    assert log.name == "refusals.jsonl"
    entry = json.loads(log.read_text().strip())
    assert entry["run_index"] == 3
    assert "spec switches rejected" in entry["reason"]
    # No attempt directory was created by the refusal.
    assert not any(tmp_path.glob("runs"))


def test_generator_pins_experiment_root_to_its_own_repo():
    import scripts.gen_cand01_batch_16run_specs_v2 as gen
    import scripts.token_benchmark as tb

    assert gen._experiment_root() == str(tb._PROJECT_ROOT)


# ---------------------------------------------------------------------------
# C3-05: a dry run leaves no trace
# ---------------------------------------------------------------------------
def test_dry_run_writes_no_attempt_or_spec(tmp_path):
    import scripts.token_benchmark as tb

    exp = tmp_path / "exp"
    exp.mkdir()
    case = {"ticker": "NVDA", "trade_date": "2026-09-23", "case_id": "c",
            "analysts": ["market"], "research_rounds": 1, "risk_rounds": 1}
    metrics = tb.execute_measured_run(exp, {"experiment_id": "e"}, case, 1,
                                      dry_run=True)
    assert metrics["run_status"] == "dry_run"
    assert metrics["valid"] is False
    assert not (exp / "runs").exists(), "a dry run created an attempt directory"
    assert list(exp.iterdir()) == [], f"dry run left artefacts: {list(exp.iterdir())}"


def test_dry_run_does_not_rewrite_recorded_code_state(tmp_path, monkeypatch):
    import json

    import scripts.token_benchmark as tb

    exp = tmp_path / "exp"
    exp.mkdir()
    sentinel = {"code_state_phase": "start_of_measurement", "working_tree_sha256": "abc"}
    (exp / "code_state.json").write_text(json.dumps(sentinel))
    monkeypatch.setattr(tb, "compute_code_state", lambda *_a, **_k: dict(sentinel))
    monkeypatch.setattr(tb, "write_code_state",
                        lambda *_a, **_k: pytest.fail("dry run wrote code state"))

    tb.run_experiment(exp, {"experiment_id": "e", "measured_runs": 1,
                            "cases": [{"ticker": "NVDA", "trade_date": "2026-09-23",
                                       "case_id": "c", "analysts": ["market"],
                                       "research_rounds": 1, "risk_rounds": 1}]},
                      dry_run=True)
    assert json.loads((exp / "code_state.json").read_text()) == sentinel


def test_compute_code_state_does_not_write(tmp_path):
    import scripts.token_benchmark as tb

    state = tb.compute_code_state(tmp_path)
    assert state["code_state_phase"] == "start_of_measurement"
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Audit-B blockers found after the first freeze
# ---------------------------------------------------------------------------
#: The three audit findings are recorded here by name because each one would
#: have produced *plausible* paid data that measured the wrong thing. They are
#: the reason the batch was not allowed to run on the first freeze.
def _registration(run_dir_name: str = "R01_NVDA_C0") -> dict:
    import json
    from pathlib import Path

    path = (Path(__file__).resolve().parent.parent / "token_benchmarks" /
            "live_pilot_2x2" / "cand01_batch_16run_v2" / "specs" /
            run_dir_name / "experiment.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_prepare_run_spec_carries_the_registered_arm(tmp_path):
    """B-01: the child spec omitted ``switches``, so every arm ran as AB.

    ``_apply_spec_switches`` reads switches off the *spec*; with none present it
    returned ``{}`` and ``default_config`` supplied ``batch_macro=True,
    single_pass=False``. All 16 labels would have produced one arm.
    """
    import json

    import scripts.token_benchmark as tb

    experiment = _registration()
    (tmp_path / "experiment.json").write_text(json.dumps(experiment))

    spec = json.loads(
        tb.prepare_run_spec(tmp_path, experiment, experiment["cases"][0], 1).read_text()
    )
    assert spec["switches"] == experiment["switches"]
    assert spec["config_sha256"] == experiment["config_sha256"]
    assert spec["switches_source"] == "registered"
    # And those switches must actually reach the config the graph receives.
    from tradingagents.default_config import DEFAULT_CONFIG

    applied = tb._apply_spec_switches(spec, {}, DEFAULT_CONFIG)
    assert applied["batch_macro_enabled"] is experiment["switches"]["batch_macro"]
    assert applied["single_pass_finalization_enabled"] is experiment["switches"]["single_pass"]


@pytest.mark.parametrize("field, tampered", [
    ("deep_model", "evil-model"),
    ("quick_model", "evil-model"),
    ("switches", {"batch_macro": True, "s2_downstream": True,
                  "single_pass": False, "structured": True}),
])
def test_prepare_run_spec_inherits_only_registered_values(tmp_path, field, tampered):
    """A spec can never carry a value the registration does not have."""
    import json

    import scripts.token_benchmark as tb

    experiment = _registration()
    (tmp_path / "experiment.json").write_text(json.dumps(experiment))
    spec = json.loads(
        tb.prepare_run_spec(tmp_path, experiment, experiment["cases"][0], 1).read_text()
    )
    if field in spec:
        assert spec[field] == experiment[field]
        assert spec[field] != tampered


def test_registration_hash_is_recomputed_not_trusted(tmp_path):
    """B-02: a spec carrying ``"0"*64`` used to run.

    The gate must recompute ``config_sha256`` from the hashed fields. A string
    that is merely present -- or that matches a definition edited after
    registration -- is refused.
    """
    import json

    import scripts.token_benchmark as tb

    experiment = _registration()
    (tmp_path / "experiment.json").write_text(json.dumps(experiment))
    spec = json.loads(
        tb.prepare_run_spec(tmp_path, experiment, experiment["cases"][0], 1).read_text()
    )
    assert tb._preflight_gate(spec)["checked"] is True

    zeroed = dict(spec, config_sha256="0" * 64)
    with pytest.raises(tb.RunRefused, match="config_sha256 mismatch"):
        tb._preflight_gate(zeroed)

    # Editing the definition after registration invalidates the old hash.
    edited = dict(experiment, deep_model="evil-model")
    (tmp_path / "experiment.json").write_text(json.dumps(edited))
    with pytest.raises(tb.RunRefused, match="config_sha256 mismatch"):
        tb._preflight_gate(spec)


def test_registration_hash_fields_agree_across_modules():
    """Three modules must hash the same subset or the verification is theatre."""
    import scripts.token_benchmark as tb
    from scripts import c3_preflight_gate as gate
    from scripts import gen_cand01_batch_16run_specs_v2 as gen

    assert tuple(tb.REGISTERED_HASH_FIELDS) == tuple(gen.HASHED_FIELDS)
    assert tuple(gate.HASHED_FIELDS) == tuple(gen.HASHED_FIELDS)


def test_all_registered_specs_verify_against_their_registration():
    """B-03: the delivered specs, MANIFEST and per-run CSV must agree."""
    import csv
    import hashlib
    import json
    from pathlib import Path

    import scripts.token_benchmark as tb
    from scripts import c3_preflight_gate as gate

    batch = (Path(__file__).resolve().parent.parent / "token_benchmarks" /
             "live_pilot_2x2" / "cand01_batch_16run_v2")

    manifest = batch / "MANIFEST.sha256"
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        actual = hashlib.sha256((batch / rel.lstrip("./")).read_bytes()).hexdigest()
        assert actual == digest, f"{rel} does not match MANIFEST.sha256"

    with (batch / "RUN_MANIFEST_TEMPLATE.csv").open() as fh:
        for row in csv.DictReader(fh):
            body = hashlib.sha256((batch / row["spec_path"]).read_bytes()).hexdigest()
            assert body == row["spec_body_sha256"], row["run_id"]
            reg = json.loads((batch / row["experiment_path"]).read_text())
            assert tb.registration_sha256(reg) == row["config_sha256"], row["run_id"]


def test_refused_registration_consumes_no_attempt(tmp_path):
    """A refused run must not burn ``attempt_01``."""
    import json

    import scripts.token_benchmark as tb

    experiment = _registration()
    with pytest.raises(tb.RunRefused):
        tb._preflight_registration(tmp_path, dict(experiment, switches=None),
                                   experiment["cases"][0])
    assert tb.attempt_dirs(tmp_path, 1) == []

    # The discard helper keeps a directory that already holds telemetry.
    run_dir = tb._attempt_dir(tmp_path, 1, 1)
    run_dir.mkdir(parents=True)
    (run_dir / "spec.json").write_text("{}")
    tb._discard_refused_attempt(tmp_path, 1, 1)
    assert not run_dir.exists()
    run_dir.mkdir(parents=True)
    (run_dir / "telemetry.json").write_text("{}")
    tb._discard_refused_attempt(tmp_path, 1, 1)
    assert run_dir.exists(), "a directory holding telemetry is evidence, never delete it"


def test_gate_rejects_a_spec_field_that_disagrees_with_its_registration(tmp_path):
    """C-01: recomputing from the registration alone let a tampered spec pass."""
    import json
    from pathlib import Path

    from scripts import c3_preflight_gate as gate

    batch = (Path(__file__).resolve().parent.parent / "token_benchmarks" /
             "live_pilot_2x2" / "cand01_batch_16run_v2" / "specs" / "R01_NVDA_C0")
    (tmp_path / "experiment.json").write_bytes((batch / "experiment.json").read_bytes())
    spec = json.loads((batch / "spec.json").read_text())
    spec["_spec_path"] = str(tmp_path / "spec.json")
    gate.check_spec_hash(spec)

    for field, value in [("deep_model", "evil"),
                         ("news_scope", {"company_news": "gdelt", "gdelt": "excluded"}),
                         ("switches", dict(spec["switches"], batch_macro=True))]:
        with pytest.raises(SystemExit):
            gate.check_spec_hash(dict(spec, **{field: value}))


# ---------------------------------------------------------------------------
# Round-2 audit findings: rehearsals that cannot fail, duplicate run IDs,
# and refusals that rewrite the recorded code state
# ---------------------------------------------------------------------------
def _batch_dir() -> "__import__('pathlib').Path":
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "token_benchmarks" /
            "live_pilot_2x2" / "cand01_batch_16run_v2")


def test_dry_run_refuses_an_invalid_switch_combination(tmp_path):
    """A rehearsal that cannot fail is not a rehearsal.

    ``run_experiment(dry_run=True)`` used to skip the registration pre-flight,
    so ``--dry-run`` accepted ``s2_downstream: false`` -- a switch with no OFF
    implementation -- and printed "would run".
    """
    import json

    import scripts.token_benchmark as tb

    experiment = _registration()
    experiment["cases"] = [experiment["cases"][0]]
    experiment["switches"] = dict(experiment["switches"], s2_downstream=False)
    experiment["config_sha256"] = tb.registration_sha256(experiment)
    (tmp_path / "experiment.json").write_text(json.dumps(experiment))

    with pytest.raises(tb.RunRefused):
        tb.run_experiment(tmp_path, experiment, dry_run=True)
    # And the rehearsal left no state behind.
    assert not (tmp_path / tb.CODE_STATE_FILE).exists()


def test_refused_run_does_not_rewrite_code_state(tmp_path):
    """A run that never started has no code state to record."""
    import json

    import scripts.token_benchmark as tb

    experiment = _registration()
    experiment["cases"] = [experiment["cases"][0]]
    (tmp_path / "experiment.json").write_text(json.dumps(experiment))
    (tmp_path / tb.CODE_STATE_FILE).write_text('{"sentinel": true}\n')
    before = (tmp_path / tb.CODE_STATE_FILE).read_bytes()

    broken = dict(experiment, switches=None)
    with pytest.raises(tb.RunRefused):
        tb.run_experiment(tmp_path, broken)

    assert (tmp_path / tb.CODE_STATE_FILE).read_bytes() == before, \
        "a refused run must not rewrite the recorded code state"


def test_gate_rejects_a_duplicated_run_id(tmp_path, monkeypatch):
    """Two directories for one run ID must not collapse to one silent winner."""
    import shutil

    from scripts import c3_preflight_gate as gate

    specs = tmp_path / "specs"
    specs.mkdir()
    real = _batch_dir() / "specs"
    # All 16 real runs, plus one extra directory that claims an existing ID.
    # The count then still reaches 16 only because of the duplicate, so a check
    # that merely counts would pass; the duplicate must be named explicitly.
    names = [p.parent.name for p in sorted(real.glob("*/experiment.json"))]
    names.append("R01_NVDA_AB")
    for name in names:
        src = next(real.glob(f"{name.split('_')[0]}_*/experiment.json"))
        dst = specs / name
        dst.mkdir()
        dst.joinpath("experiment.json").write_text(src.read_text())

    monkeypatch.setattr(gate, "BATCH_DIR", tmp_path)
    with pytest.raises(SystemExit):
        gate._run_arm_map()
    # Prove the *reason* is the duplicate, not the count: with the extra
    # directory removed the same 16 must be accepted.
    shutil.rmtree(specs / "R01_NVDA_AB")
    assert len(gate._run_arm_map()) == 16


def test_gate_accepts_the_real_registration_set(monkeypatch):
    """And the duplicate detector must not fire on the 16 delivered runs."""
    from scripts import c3_preflight_gate as gate

    assert len(gate._run_arm_map()) == 16
