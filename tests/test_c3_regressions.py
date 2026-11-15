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
from pathlib import Path

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
    from scripts import gen_cand01_batch_16run_specs_v2 as gen

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
            # ``spec_body_sha256`` is the generator's definition: the canonical
            # JSON of the spec minus ``results_dir`` -- NOT the hash of the file
            # bytes. Comparing against the file bytes was a self-consistent
            # mistake: the CSV had been rewritten with that formula, so the test
            # passed while disagreeing with the generator that produced it.
            spec = json.loads((batch / row["spec_path"]).read_text())
            body = gen.spec_body_sha256(spec)
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
    # The gate anchors arms to the protocol table and the frozen matrix, so
    # both must be present in the sandbox.
    shutil.copy(_batch_dir() / "CAND01_BATCH_2X2_PROTOCOL_V2.md", tmp_path)
    shutil.copy(_batch_dir() / "SWITCH_MATRIX.csv", tmp_path)
    # All 16 real runs, plus one extra directory that claims an existing ID.
    # The count then still reaches 16 only because of the duplicate, so a check
    # that merely counts would pass; the duplicate must be named explicitly.
    names = [p.parent.name for p in sorted(real.glob("*/experiment.json"))]
    # The duplicate is the *same arm* as the original: two directories both
    # named C0 for R01. The matrix alone would accept both (each carries the
    # frozen C0 switches), so only an explicit duplicate-ID check refuses this.
    # An AB duplicate would be caught by the arm anchor and prove nothing about
    # the duplicate detector.
    names.append("R01_NVDA_C0_duplicate")
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
    shutil.rmtree(specs / "R01_NVDA_C0_duplicate")
    assert len(gate._run_arm_map()) == 16


def test_gate_accepts_the_real_registration_set(monkeypatch):
    """And the duplicate detector must not fire on the 16 delivered runs."""
    from scripts import c3_preflight_gate as gate

    assert len(gate._run_arm_map()) == 16


# ---------------------------------------------------------------------------
# Audit B-10/B-11: a consistently edited registration must not run another arm
# ---------------------------------------------------------------------------
def _rewrite_run_consistently(specs: "pathlib.Path", src_name: str, dst_name: str,
                              switches: dict) -> None:
    """Copy a run and give it ``switches`` *including* a matching rehash.

    This is the B-10 attack: every internal check still passes, because the
    registration agrees with itself. Only an authority outside the file can
    catch it.
    """
    import json
    import shutil

    import scripts.token_benchmark as tb

    src, dst = specs / src_name, specs / dst_name
    shutil.copytree(src, dst)
    reg = json.loads((dst / "experiment.json").read_text())
    spec = json.loads((dst / "spec.json").read_text())
    reg["switches"] = dict(switches)
    reg["config_sha256"] = tb.registration_sha256(reg)
    spec["switches"] = dict(switches)
    spec["config_sha256"] = reg["config_sha256"]
    (dst / "experiment.json").write_text(json.dumps(reg, indent=2))
    (dst / "spec.json").write_text(json.dumps(spec, indent=2))


def test_gate_refuses_an_arm_swapped_in_place_with_a_consistent_rehash(
        tmp_path, monkeypatch):
    """B-10: R01 is named C0; running it as CC must be refused.

    Before the fix the expected switches were read from the same registration
    being validated, so an edit that also rehashed was self-consistent and the
    gate printed "GATE PASSED — safe to spend money".
    """
    import shutil
    from pathlib import Path

    from scripts import c3_preflight_gate as gate

    specs = tmp_path / "specs"
    specs.mkdir()
    real = (Path(__file__).resolve().parent.parent / "token_benchmarks" /
            "live_pilot_2x2" / "cand01_batch_16run_v2" / "specs")
    for d in sorted(real.iterdir()):
        shutil.copytree(d, specs / d.name)
    shutil.copy((Path(__file__).resolve().parent.parent / "token_benchmarks" /
                 "live_pilot_2x2" / "cand01_batch_16run_v2" /
                 "CAND01_BATCH_2X2_PROTOCOL_V2.md"), tmp_path)
    shutil.copy((Path(__file__).resolve().parent.parent / "token_benchmarks" /
                 "live_pilot_2x2" / "cand01_batch_16run_v2" /
                 "SWITCH_MATRIX.csv"), tmp_path)
    monkeypatch.setattr(gate, "BATCH_DIR", tmp_path)

    # Baseline: the real registrations are accepted.
    assert len(gate._run_arm_map()) == 16

    # Swap R01 (named C0) to the CC switches, consistently rehashed.
    import json
    import scripts.token_benchmark as tb
    ep = specs / "R01_NVDA_C0" / "experiment.json"
    reg = json.loads(ep.read_text())
    reg["switches"] = {"batch_macro": True, "s2_downstream": True,
                       "single_pass": True, "structured": True}
    reg["config_sha256"] = tb.registration_sha256(reg)
    ep.write_text(json.dumps(reg, indent=2))

    with pytest.raises(SystemExit):
        gate._run_arm_map()


def test_gate_refuses_an_arm_renamed_into_another_arm(tmp_path, monkeypatch):
    """Renaming the directory does not help: the ID is now duplicated."""
    import shutil
    from pathlib import Path

    from scripts import c3_preflight_gate as gate

    specs = tmp_path / "specs"
    specs.mkdir()
    real = (Path(__file__).resolve().parent.parent / "token_benchmarks" /
            "live_pilot_2x2" / "cand01_batch_16run_v2" / "specs")
    for d in sorted(real.iterdir()):
        shutil.copytree(d, specs / d.name)
    shutil.copy((Path(__file__).resolve().parent.parent / "token_benchmarks" /
                 "live_pilot_2x2" / "cand01_batch_16run_v2" /
                 "CAND01_BATCH_2X2_PROTOCOL_V2.md"), tmp_path)
    shutil.copy((Path(__file__).resolve().parent.parent / "token_benchmarks" /
                 "live_pilot_2x2" / "cand01_batch_16run_v2" /
                 "SWITCH_MATRIX.csv"), tmp_path)
    monkeypatch.setattr(gate, "BATCH_DIR", tmp_path)

    cc = {"batch_macro": True, "s2_downstream": True,
          "single_pass": True, "structured": True}
    # Drop a different run so the count still reaches 16.
    shutil.rmtree(specs / "R16_XOM_AB")
    _rewrite_run_consistently(specs, "R01_NVDA_C0", "R01_NVDA_CC", cc)

    with pytest.raises(SystemExit):
        gate._run_arm_map()


def test_gate_arm_map_matches_the_protocol_table():
    """The expected arm comes from the protocol, not from the registration."""
    from scripts import c3_preflight_gate as gate

    assert gate._protocol_arm_table() == gate.ARMS
    assert gate._run_arm_map()["R01"] == gate.ARMS["C0"]
    assert gate._run_arm_map()["R02"] == gate.ARMS["AB"]


def test_parent_refuses_a_consistently_rehashed_arm_swap():
    """B-10 on the harness path: the parent checks the frozen matrix too.

    ``_preflight_gate`` used to recompute ``config_sha256`` and stop there,
    which proves only that the definition agrees with itself. A registration
    edited *and* rehashed reaches a different arm, so the parent needs the same
    independent anchor the gate uses.

    ``prepare_run_spec`` writes into the directory it is given, so it is never
    pointed at the frozen batch (that created 16 ``runs/`` directories inside
    the delivered specs -- Audit B's B-14). The swap is therefore built by
    editing a local *copy* of the spec's switches, which is what a tampered
    registration produces.
    """
    import json

    import scripts.token_benchmark as tb

    batch = _batch_dir()
    frozen = tb._frozen_switch_matrix()
    assert set(frozen) == {f"R{i:02d}" for i in range(1, 17)}

    # Each real registration carries its Run ID's frozen arm, and the parent's
    # registration pre-flight (which knows the directory) accepts it.
    for run_id, expected in sorted(frozen.items()):
        spec_dir = next(d for d in (batch / "specs").iterdir()
                        if d.name.split("_", 1)[0] == run_id)
        experiment = json.loads((spec_dir / "experiment.json").read_text())
        assert experiment["switches"] == expected, run_id
        tb._preflight_registration(spec_dir, experiment, experiment["cases"][0])

    # A registration that moved to another arm is refused by name. The spec the
    # child would receive is the registration plus the run's case, as
    # ``prepare_run_spec`` builds it; it is assembled here rather than written
    # into the frozen tree.
    spec_dir = batch / "specs/R01_NVDA_C0"
    experiment = json.loads((spec_dir / "experiment.json").read_text())
    spec = {key: experiment[key] for key in tb.REGISTERED_HASH_FIELDS}
    spec.update({"experiment_id": experiment["experiment_id"],
                 "registration_dir": str(spec_dir),
                 "case": experiment["cases"][0]})
    tb._preflight_gate(spec)
    swapped = dict(spec)
    # C0 -> CC: flip batch_macro only. ``structured``/``s2_downstream`` must stay
    # true (there is no OFF implementation), and this is a real arm swap.
    swapped["switches"] = {**frozen["R01"], "batch_macro": True}
    assert swapped["switches"] != frozen["R01"]
    with pytest.raises(tb.RunRefused, match="SWITCH_MATRIX.csv froze"):
        tb._preflight_gate(swapped)



def test_a_copied_run_id_cannot_be_measured_twice(tmp_path):
    """B-06: a Run ID names exactly one directory, not just one name.

    Copying ``R01_NVDA_C0`` into another experiment directory preserves the
    name, the switches and the hash, so every content check passes. Measured
    there it would be a second, independent R01 -- doubling one arm's weight
    and silently corrupting the 4x4 comparison. Only the path distinguishes
    the real sample from the copy.
    """
    import json
    import shutil

    import scripts.token_benchmark as tb

    src = _batch_dir() / "specs/R01_NVDA_C0"
    experiment = _load(src / "experiment.json")
    # The registered directory is accepted.
    tb._preflight_registration(src, experiment, experiment["cases"][0])

    copy = tmp_path / "exp_B" / "R01_NVDA_C0"
    shutil.copytree(src, copy)
    with pytest.raises(tb.RunRefused, match="not that run's registered directory"):
        tb._preflight_registration(copy, experiment, experiment["cases"][0])

    # The child would refuse it too, so a copied spec cannot reach a paid call.
    spec = json.loads(tb.prepare_run_spec(
        copy, experiment, experiment["cases"][0], 1, attempt=0).read_text())
    with pytest.raises(tb.RunRefused, match="not from that run's registered directory"):
        tb._preflight_gate(spec)


def _load(path):
    import json

    return json.loads(path.read_text())


def test_legacy_launcher_refuses_without_explicit_opt_in():
    """B-09 made safe: the money-spending legacy launcher is opt-in only.

    Deriving ``REPO_ROOT`` from the script location fixed the wrong-tree half
    of B-09, but left the launcher runnable -- and the natural way to verify
    that fix was to run it, which spent a campaign on 2026-11-15 (see
    ``INCIDENT_20261115_legacy_launcher.md``). Refusing by default makes the
    verification invocation free.
    """
    import os
    import subprocess
    from pathlib import Path

    script = (Path(__file__).resolve().parent.parent
              / "scripts/campaign_ablation_launch.sh")
    env = {k: v for k, v in os.environ.items()
           if k != "CAMPAIGN_ABLATION_I_MEAN_IT"}
    result = subprocess.run(["bash", str(script)], capture_output=True,
                            text=True, env=env, timeout=30)
    assert result.returncode == 1
    assert "spends money" in result.stderr
    assert "CAMPAIGN_ABLATION_I_MEAN_IT" in result.stderr
    # ...and it did not start anything.
    assert "started campaign" not in result.stdout


def test_a_spec_only_attempt_dir_is_never_overwritten(tmp_path):
    """C-08: a spec-only attempt occupies its slot even though it is not a run.

    ``attempt_dirs`` ignores a directory holding only ``spec.json`` because it
    never ran -- correct. But the *number* it occupies is taken: skipping it made
    ``_preferred_attempt_dir`` return ``attempt_01`` again and overwrite the spec
    that was already there.
    """
    import scripts.token_benchmark as tb

    exp = tmp_path / "exp"
    exp.mkdir()
    (exp / "experiment.json").write_text("{}")
    first = tb._run_slot_dir(exp, 1) / "attempt_01"
    first.mkdir(parents=True)
    (first / "spec.json").write_text('{"keep": "me"}')

    assert tb.attempt_dirs(exp, 1) == [], "a spec-only dir is not a completed attempt"
    assert tb._preferred_attempt_dir(exp, 1).name == "attempt_02"
    # ...and with two attempts the next is still one past the highest.
    (tb._run_slot_dir(exp, 1) / "attempt_02").mkdir()
    assert tb._preferred_attempt_dir(exp, 1).name == "attempt_03"


def test_a_blown_cap_blocks_even_when_usage_is_missing():
    """C-04r: unknown spend must not hide a cap that is already provably blown."""
    from tradingagents.budget_guard import BudgetExhausted, BudgetGate

    gate = BudgetGate(max_total_tokens=100)
    gate.record_call("a", input_tokens=999_999, output_tokens=0, reported=True)
    gate.record_call("b", input_tokens=None, output_tokens=None, reported=False)
    assert gate.state == "EXHAUSTED"
    with pytest.raises(BudgetExhausted):
        gate.check()

    # An uncapped run stays UNKNOWN_SPEND, and a satisfied cap stays OK.
    uncapped = BudgetGate(max_total_tokens=None)
    uncapped.record_call("a", input_tokens=5, output_tokens=5, reported=True)
    uncapped.record_call("b", input_tokens=None, output_tokens=None, reported=False)
    assert uncapped.state == "UNKNOWN_SPEND"
    under = BudgetGate(max_total_tokens=100)
    under.record_call("a", input_tokens=5, output_tokens=5, reported=True)
    assert under.state == "OK"


def test_an_exhausted_budget_makes_the_sample_invalid():
    """C-04r: the gate must be wired into the validity decision, not just reported."""
    import scripts.token_benchmark as tb

    payload = {
        "run": {"run_status": "completed"},
        "run_totals": {"reported_input_tokens_sum": 10, "reported_output_tokens_sum": 5,
                       "llm_calls": 1},
        "usage_coverage": {"complete": True},
        "llm_call_events": [{"callback_run_id": "c1", "reported_input_tokens": 10,
                             "reported_output_tokens": 5, "usage_source": "vendor"}],
    }
    uncapped = tb.extract_run_metrics(payload, None, 0, max_total_tokens=None)
    assert uncapped["valid"] is True
    capped = tb.extract_run_metrics(payload, None, 0, max_total_tokens=1)
    assert capped["valid"] is False
    assert capped["invalid_reason"] == "budget_exhausted"


def test_per_agent_usage_completeness_is_reported():
    """C-05p: an unmeasured agent must not look like one that used zero tokens."""
    import scripts.token_benchmark as tb

    measured_zero = tb._extract_agent_metrics(
        {"reported_input_tokens_sum": 0, "reported_output_tokens_sum": 0, "llm_calls": 1})
    unmeasured = tb._extract_agent_metrics(
        {"llm_calls": 1, "llm_calls_missing_input_tokens": 1})
    assert measured_zero["total_tokens"] == unmeasured["total_tokens"] == 0
    assert measured_zero["usage_complete"] is True
    assert unmeasured["usage_complete"] is False
    assert unmeasured["token_totals_are_lower_bound"] is True
    complete = tb._extract_agent_metrics(
        {"reported_input_tokens_sum": 100, "reported_output_tokens_sum": 50, "llm_calls": 2})
    assert complete["usage_complete"] is True and complete["total_tokens"] == 150
