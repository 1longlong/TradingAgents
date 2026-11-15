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
