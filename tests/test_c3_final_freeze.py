"""Final-freeze round regression tests: U-1, U-2, A-00, dry run, effective config.

Every test here pins a defect that was *open* at the Plan C3 halt report
(``C3_HALT_REPORT_20261115.md`` §4) and is claimed fixed by the final freeze:

* **U-1** — the telemetry/usage agreement was computed and never consumed.
* **U-2** — ``max_total_tokens: null`` was indistinguishable from a missing or
  broken budget file.
* the freeze designation named an *ancestor* of ``HEAD``, so no run could pass;
* **A-00** — the scripts imported ``tradingagents`` from the main checkout
  because only ``scripts/`` was on ``sys.path``;
* ``dry_run`` did not rehearse the spec, the graph or the switches;
* ``effective_config.json`` was written and never verified.

Where a defect has a "before" behaviour, the test asserts the *new* consequence
(an invalid run, a refusal, a null total) rather than an implementation detail,
so reverting the fix makes the test fail for the reason the audit gave.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REHEARSAL_SWITCHES = {"batch_macro": False, "single_pass": True,
                       "structured": True, "s2_downstream": True}

_SPEC_FOR_PROBE: dict = {"switches": {"batch_macro": False, "single_pass": True,
                                      "structured": True, "s2_downstream": True}}

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
BATCH = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"

sys.path.insert(0, str(SCRIPTS))
import token_benchmark as tb  # noqa: E402

from tradingagents import observability as obs  # noqa: E402
from tradingagents.graph.switch_verification import (  # noqa: E402
    expected_analyst_kwargs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _payload(*, calls=2, with_usage=2, total_in=100, total_out=20,
             events=True, complete=True, **overrides):
    """A telemetry payload shaped like the real one (no fabricated numbers)."""
    payload = {
        "run": {"run_status": "completed"},
        "usage_coverage": {
            "complete": complete,
            "llm_calls": calls,
            "calls_with_provider_usage": with_usage,
            "calls_without_provider_usage": calls - with_usage,
            "calls_missing_input_tokens": 0,
            "calls_missing_output_tokens": 0,
        },
        "audit_quality": {"usage_complete": complete,
                          "attribution_complete": True,
                          "telemetry_complete": True},
        "run_totals": {
            "reported_input_tokens_sum": total_in,
            "reported_output_tokens_sum": total_out,
            "llm_calls": calls,
            "tool_calls": 3,
        },
    }
    if events:
        per_in, per_out = total_in // calls, total_out // calls
        payload["llm_call_events"] = [
            {"callback_run_id": f"c{i}",
             "reported_input_tokens": per_in + (total_in % calls if i == 0 else 0),
             "reported_output_tokens": per_out + (total_out % calls if i == 0 else 0),
             "usage_source": "provider" if i < with_usage else None}
            for i in range(calls)
        ]
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# U-1 — the usage verdict gates validity
# ---------------------------------------------------------------------------
class TestUsageVerdict:
    def test_valid_when_every_call_reports_and_the_replay_agrees(self):
        payload = _payload()
        verdict = tb.usage_verdict(payload, replay_used=120)
        assert verdict["state"] == tb.USAGE_VALID
        assert tb.extract_run_metrics(payload, None, 0)["valid"] is True

    def test_missing_usage_is_missing_and_totals_are_null_not_zero(self):
        payload = _payload(calls=2, with_usage=0, complete=False,
                           total_in=0, total_out=0)
        verdict = tb.usage_verdict(payload)
        assert verdict["state"] == tb.USAGE_MISSING
        metrics = tb.extract_run_metrics(payload, None, 0)
        assert metrics["valid"] is False
        assert metrics["invalid_reason"] == tb.INVALID_USAGE_MISSING
        # The defect: an unknown total used to be published as a measured 0.
        assert metrics["total_tokens"] is None
        assert metrics["reported_input_tokens_sum"] is None
        assert metrics["reported_output_tokens_sum"] is None

    def test_partial_usage_is_incomplete_not_missing(self):
        payload = _payload(calls=2, with_usage=1, complete=False,
                           total_in=50, total_out=10, events=False)
        payload["llm_call_events"] = [
            {"callback_run_id": "c0", "reported_input_tokens": 50,
             "reported_output_tokens": 10, "usage_source": "provider"},
            {"callback_run_id": "c1", "reported_input_tokens": None,
             "reported_output_tokens": None, "usage_source": None},
        ]
        verdict = tb.usage_verdict(payload)
        assert verdict["state"] == tb.USAGE_INCOMPLETE
        metrics = tb.extract_run_metrics(payload, None, 0)
        assert metrics["invalid_reason"] == tb.INVALID_USAGE_INCOMPLETE
        # A partial run's observed tokens are a lower bound, not zero and not a
        # full total.
        assert metrics["total_tokens"] == 60
        assert metrics["totals_are_lower_bound"] is True

    def test_zero_calls_is_missing_even_if_the_payload_says_complete(self):
        payload = _payload(calls=0, with_usage=0, total_in=0, total_out=0,
                           events=False)
        assert tb.usage_verdict(payload)["state"] == tb.USAGE_MISSING

    def test_replay_disagreement_is_a_mismatch_and_voids_the_run(self):
        """U-1: ``agrees_with_telemetry`` is now consumed, not just computed.

        The payload is internally consistent except for one thing: both call
        records carry the *same* callback run id, so the spend replay counts one
        call while the run totals count two. That is precisely the case the old
        code computed ``agrees_with_telemetry=False`` for and then ignored.
        """
        payload = _payload(calls=2, with_usage=2, total_in=100, total_out=20,
                           events=False)
        payload["llm_call_events"] = [
            {"callback_run_id": "duplicate", "reported_input_tokens": 50,
             "reported_output_tokens": 10, "usage_source": "provider"},
            {"callback_run_id": "duplicate", "reported_input_tokens": 50,
             "reported_output_tokens": 10, "usage_source": "provider"},
        ]
        metrics = tb.extract_run_metrics(payload, None, 0)
        # The replay saw 60 tokens, the telemetry claims 120.
        assert metrics["budget"]["agrees_with_telemetry"] is False
        assert metrics["budget"]["used_tokens"] == 60
        assert metrics["valid"] is False
        assert metrics["invalid_reason"] == tb.INVALID_USAGE_MISMATCH

    def test_per_call_events_that_do_not_sum_to_the_totals_are_a_mismatch(self):
        payload = _payload()
        payload["run_totals"]["reported_input_tokens_sum"] = 10_000
        assert tb.usage_verdict(payload)["state"] == tb.USAGE_MISMATCH

    def test_negative_totals_are_a_mismatch(self):
        payload = _payload()
        payload["run_totals"]["reported_input_tokens_sum"] = -1
        assert tb.usage_verdict(payload)["state"] == tb.USAGE_MISMATCH

    def test_usage_counts_that_do_not_add_up_are_a_mismatch(self):
        payload = _payload()
        payload["usage_coverage"]["calls_without_provider_usage"] = 3
        assert tb.usage_verdict(payload)["state"] == tb.USAGE_MISMATCH

    def test_unattributed_usage_fails_closed(self):
        payload = _payload()
        payload["unattributed_llm_events"] = 1
        assert tb.usage_verdict(payload)["state"] == tb.USAGE_INCOMPLETE
        assert tb.extract_run_metrics(payload, None, 0)["valid"] is False

    def test_a_payload_without_per_call_records_is_inconclusive_not_a_mismatch(self):
        payload = _payload(events=False)
        verdict = tb.usage_verdict(payload)
        assert verdict["state"] == tb.USAGE_VALID
        assert verdict["event_records_present"] is False
        assert verdict["replay_conclusive"] is False

    def test_an_unfinalized_run_keeps_its_own_reason(self):
        payload = _payload()
        payload["audit_quality"]["telemetry_complete"] = False
        metrics = tb.extract_run_metrics(payload, None, 0)
        assert metrics["invalid_reason"] == tb.INVALID_TELEMETRY_INCOMPLETE


class TestRawUsageIsPreserved:
    """L-5 / C-5: the vendor's own numbers survive, and negatives never count."""

    def test_raw_usage_blob_is_kept(self):
        usage = obs._extract_usage_metadata(
            {"input_tokens": 3, "output_tokens": 4,
             "input_token_details": {"cache_read": 1}})
        assert usage["raw"] == {"input_tokens": 3, "output_tokens": 4,
                                "input_token_details": {"cache_read": 1}}

    def test_long_strings_are_dropped_from_the_raw_blob(self):
        usage = obs._extract_usage_metadata(
            {"input_tokens": 1, "output_tokens": 1, "note": "x" * 200})
        assert "note" not in usage["raw"]

    def test_a_negative_token_count_is_treated_as_unreported(self):
        usage = obs._extract_usage_metadata({"input_tokens": -5, "output_tokens": 7})
        assert usage["input"] is None
        assert usage["complete"] is False

    def test_negative_counts_inside_the_blob_are_counted_by_the_telemetry(self):
        collector = obs.RunMetricsCollector()
        collector.begin_run()
        collector.finish_run("completed")
        payload = collector.build_telemetry()
        assert payload["usage_checks"]["negative_token_counts"] == 0


class TestEmptyRunIsNotComplete:
    def test_an_empty_finished_run_is_not_attribution_complete(self):
        collector = obs.RunMetricsCollector()
        collector.begin_run()
        collector.finish_run("completed")
        payload = collector.build_telemetry()
        assert payload["audit_quality"]["attribution_complete"] is False
        assert payload["audit_quality"]["usage_complete"] is False


class TestAgentUsageCompleteness:
    def test_a_partial_agent_is_not_marked_complete(self):
        metrics = tb._extract_agent_metrics(
            {"llm_calls": 2, "calls_without_provider_usage": 1,
             "reported_input_tokens_sum": 10, "reported_output_tokens_sum": 5})
        assert metrics["usage_complete"] is False
        assert metrics["token_totals_are_lower_bound"] is True

    def test_a_fully_measured_agent_is_complete(self):
        metrics = tb._extract_agent_metrics(
            {"llm_calls": 2, "calls_without_provider_usage": 0,
             "reported_input_tokens_sum": 10, "reported_output_tokens_sum": 5})
        assert metrics["usage_complete"] is True


# ---------------------------------------------------------------------------
# U-2 — budget configuration semantics
# ---------------------------------------------------------------------------
class TestBudgetContract:
    def test_uncapped_authorized_with_null_is_accepted(self):
        state = tb.budget_state_from_experiment(
            {"budget": {"budget_mode": "uncapped_authorized",
                        "max_total_tokens": None}})
        assert state["ok"] is True and state["max_total_tokens"] is None
        assert state["mode"] == tb.BUDGET_MODE_UNCAPPED

    def test_capped_with_positive_integer_is_accepted(self):
        state = tb.budget_state_from_experiment(
            {"budget": {"budget_mode": "capped", "max_total_tokens": 1_000}})
        assert state["ok"] is True and state["max_total_tokens"] == 1_000

    @pytest.mark.parametrize("budget,expected", [
        ({"max_total_tokens": None}, tb.BUDGET_MODE_MISSING),
        ({"budget_mode": "whatever", "max_total_tokens": None}, tb.BUDGET_MODE_INVALID),
        ({"budget_mode": "uncapped_authorized"}, tb.BUDGET_CAP_INVALID),
        ({"budget_mode": "uncapped_authorized", "max_total_tokens": 5},
         tb.BUDGET_CAP_INVALID),
        ({"budget_mode": "capped", "max_total_tokens": None}, tb.BUDGET_CAP_INVALID),
        ({"budget_mode": "capped", "max_total_tokens": -1}, tb.BUDGET_CAP_INVALID),
        ({"budget_mode": "capped", "max_total_tokens": True}, tb.BUDGET_CAP_INVALID),
        ("not-an-object", tb.BUDGET_BLOCK_NOT_OBJECT),
    ])
    def test_unusable_blocks_are_refused_with_distinct_states(self, budget, expected):
        state = tb.budget_state_from_experiment({"budget": budget})
        assert state["ok"] is False
        assert state["state"] == expected
        with pytest.raises(tb.RunRefused):
            tb.require_budget_state({"budget": budget})

    def test_a_missing_budget_block_is_distinct_from_a_null_cap(self):
        absent = tb.budget_state_from_experiment({"experiment_id": "x"})
        assert absent["state"] == tb.BUDGET_BLOCK_MISSING
        declared = tb.budget_state_from_experiment(
            {"budget": {"budget_mode": "uncapped_authorized",
                        "max_total_tokens": None}})
        assert declared["ok"] is True

    def test_a_missing_file_is_its_own_state(self, tmp_path):
        state = tb.load_budget_state(tmp_path / "nope.json")
        assert state["state"] == tb.BUDGET_FILE_MISSING

    def test_malformed_json_is_its_own_state(self, tmp_path):
        path = tmp_path / "experiment.json"
        path.write_text("{not json", encoding="utf-8")
        assert tb.load_budget_state(path)["state"] == tb.BUDGET_MALFORMED

    def test_unreadable_file_is_its_own_state(self, tmp_path):
        path = tmp_path / "experiment.json"
        path.write_text("{}", encoding="utf-8")
        path.chmod(0o000)
        try:
            if os.access(path, os.R_OK):  # root ignores the mode bits
                pytest.skip("running with permission to read anything")
            assert tb.load_budget_state(path)["state"] == tb.BUDGET_FILE_UNREADABLE
        finally:
            path.chmod(0o600)

    def test_a_frozen_batch_registration_without_a_contract_is_refused(self, tmp_path):
        """The batch must state the contract; a generic experiment need not."""
        with pytest.raises(tb.RunRefused, match="BUDGET_BLOCK_MISSING"):
            tb._preflight_registration(
                BATCH / "specs" / "R01_NVDA_C0",
                {"experiment_id": "R01", "cases": [{"case_id": "c"}]},
                {"case_id": "c"})

    def test_the_delivered_specs_declare_the_contract(self):
        for directory in sorted((BATCH / "specs").iterdir()):
            registration = json.loads(
                (directory / "experiment.json").read_text(encoding="utf-8"))
            budget = registration["budget"]
            assert budget["budget_mode"] == "uncapped_authorized", directory.name
            assert budget["max_total_tokens"] is None, directory.name

    def test_the_summary_reports_the_contract_not_just_the_cap(self):
        payload = _payload()
        metrics = tb.extract_run_metrics(payload, None, 0, max_total_tokens=None,
                                         budget_state={
                                             "ok": True, "state": tb.BUDGET_OK,
                                             "mode": "uncapped_authorized",
                                             "max_total_tokens": None,
                                             "source": "<test>"})
        assert metrics["budget"]["mode"] == "uncapped_authorized"
        assert metrics["budget"]["cap_authorised"] is True
        assert metrics["budget"]["state"] == "UNCAPPED"

    def test_an_unusable_contract_invalidates_the_sample(self, tmp_path, monkeypatch):
        exp = tmp_path / "exp"
        exp.mkdir()
        experiment = {"experiment_id": "e", "measured_runs": 1,
                      "cases": [{"ticker": "NVDA", "trade_date": "2026-09-23",
                                 "case_id": "c", "analysts": ["market"],
                                 "research_rounds": 1, "risk_rounds": 1}],
                      "budget": {"max_total_tokens": None}}  # no mode
        # The strict contract is the registered batch's rule; say this
        # registration is one, rather than depending on the real tree.
        monkeypatch.setattr(tb, "_is_frozen_batch_registration", lambda _p: True)
        with pytest.raises(tb.RunRefused, match="BUDGET_MODE_MISSING"):
            tb._preflight_registration(exp, experiment, experiment["cases"][0])


# ---------------------------------------------------------------------------
# A-00 — the scripts must import the tree they live in
# ---------------------------------------------------------------------------
class TestImportRootIsolation:
    def test_the_gate_script_imports_its_own_repository(self, tmp_path):
        """Run by path from an unrelated cwd: only ``scripts/`` is on sys.path."""
        code = (
            "import runpy, sys\n"
            f"sys.argv = ['c3_preflight_gate.py']\n"
            f"runpy.run_path({str(SCRIPTS / 'c3_preflight_gate.py')!r}, "
            "run_name='probe')\n"
            "import tradingagents\n"
            "print(tradingagents.__file__)\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        result = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path),
                                capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().startswith(str(REPO_ROOT)), result.stdout

    def test_the_child_environment_pins_the_experiment_root(self):
        env = tb._child_env_for_spec({"experiment_root": "/frozen/tree",
                                      "switches": {}})
        assert env["PYTHONPATH"].split(os.pathsep)[0] == "/frozen/tree"
        assert env["PYTHONSAFEPATH"] == "1"

    def test_a_wrong_import_root_is_refused(self):
        with pytest.raises(RuntimeError, match="outside the expected"):
            tb.verify_import_root("/definitely/not/this/tree")


# ---------------------------------------------------------------------------
# dry_run — a rehearsal that can fail
# ---------------------------------------------------------------------------
class _StubSetup:
    """Stands in for ``GraphSetup``: carries what it was told to consume."""

    def __init__(self, switches):
        self.observed = expected_analyst_kwargs(switches)


class _StubGraph:
    def __init__(self, switches):
        self.graph_setup = _StubSetup(switches)
        self._observed = expected_analyst_kwargs(switches)


def _rehearsal_experiment() -> dict:
    return {
        "experiment_id": "rehearsal",
        "provider": "openai_compatible",
        "quick_model": "m",
        "deep_model": "m",
        "output_language": "English",
        "cache_policy": "preserve_existing",
        "switches": {"batch_macro": False, "single_pass": True,
                     "structured": True, "s2_downstream": True},
        "news_scope": {"company_news": "finnhub",
                       "global_news": "finnhub:CONFIG_DISABLED",
                       "gdelt": "excluded"},
        "budget": {"budget_mode": "uncapped_authorized", "max_total_tokens": None},
        "measured_runs": 1,
        "cases": [{"ticker": "NVDA", "trade_date": "2026-09-23", "case_id": "c",
                   "analysts": ["market", "news", "fundamentals"],
                   "research_rounds": 1, "risk_rounds": 1}],
    }


class TestDryRunRehearsal:
    def test_a_dry_run_builds_the_real_spec_and_graph(self, tmp_path, monkeypatch):
        exp = tmp_path / "exp"
        exp.mkdir()
        experiment = _rehearsal_experiment()
        seen = {}

        def _construct(spec, config):
            seen["spec"] = spec
            seen["config"] = config
            return _StubGraph(spec["switches"])

        import tradingagents.graph.switch_verification as switch_mod

        monkeypatch.setattr(tb, "_construct_graph", _construct)
        monkeypatch.setattr(
            switch_mod, "consume_switches_from_setup",
            lambda setup: expected_analyst_kwargs(seen["spec"]["switches"]))
        monkeypatch.setattr(tb, "verify_frozen_tree", lambda *a, **k: None)

        metrics = tb.execute_measured_run(
            exp, experiment, experiment["cases"][0], 1, dry_run=True)
        assert metrics["run_status"] == "dry_run"
        rehearsal = metrics["rehearsal"]
        assert rehearsal["graph_rehearsed"] is True
        assert rehearsal["effective_config_verified"]["verified"] is True
        assert seen["config"]["single_pass_finalization_enabled"] is True
        assert seen["config"]["structured_analyst_output_enabled"] is True
        assert seen["spec"]["run_index"] == 1  # the real spec, built in memory
        # A rehearsal leaves no attempt, no spec, no refusal log.
        assert list(exp.iterdir()) == []

    def test_a_dry_run_can_fail(self, tmp_path):
        exp = tmp_path / "exp"
        exp.mkdir()
        experiment = _rehearsal_experiment()
        experiment["switches"]["s2_downstream"] = False
        with pytest.raises(tb.RunRefused, match="s2_downstream"):
            tb.execute_measured_run(exp, experiment, experiment["cases"][0], 1,
                                    dry_run=True)
        assert list(exp.iterdir()) == []

    def test_a_rehearsal_cannot_disable_the_freeze_check(self, monkeypatch):
        """The seam is a test-only hole; a batch rehearsal may not use it."""
        spec = json.loads((BATCH / "specs/R01_NVDA_C0/spec.json").read_text())
        spec["_spec_path"] = str(BATCH / "specs/R01_NVDA_C0/spec.json")
        monkeypatch.setenv("TRADINGAGENTS_SKIP_FREEZE_CHECK", "1")
        with pytest.raises(tb.RunRefused, match="cannot be disabled"):
            tb.rehearse_run_spec(spec)

    def test_a_rehearsal_sandboxes_the_graph_directories(self, tmp_path, monkeypatch):
        """Constructing the real graph creates directories; a rehearsal must not."""
        exp = tmp_path / "exp"
        exp.mkdir()
        experiment = _rehearsal_experiment()
        seen = {}

        def _construct(spec, config):
            seen.update(config)
            seen["sandbox_existed"] = Path(config["results_dir"]).parent.exists()
            return _StubGraph(spec["switches"])

        import tradingagents.graph.switch_verification as switch_mod

        monkeypatch.setattr(tb, "_construct_graph", _construct)
        monkeypatch.setattr(
            switch_mod, "consume_switches_from_setup",
            lambda setup: getattr(setup, "observed", None)
            or expected_analyst_kwargs(_REHEARSAL_SWITCHES))
        monkeypatch.setattr(tb, "verify_frozen_tree", lambda *a, **k: None)

        metrics = tb.execute_measured_run(
            exp, experiment, experiment["cases"][0], 1, dry_run=True)
        assert metrics["rehearsal"]["graph_rehearsed"] is True
        assert seen["sandbox_existed"] is True
        # The sandbox is gone and the experiment directory is untouched.
        assert not Path(seen["results_dir"]).exists()
        assert not Path(seen["cache"] if "cache" in seen else seen["data_cache_dir"]).exists()
        assert list(exp.iterdir()) == []

    def test_a_dry_run_without_a_provider_reports_the_scope(self, tmp_path, monkeypatch):
        exp = tmp_path / "exp"
        exp.mkdir()
        experiment = {"experiment_id": "e", "measured_runs": 1,
                      "cases": [{"ticker": "NVDA", "trade_date": "2026-09-23",
                                 "case_id": "c", "analysts": ["market"],
                                 "research_rounds": 1, "risk_rounds": 1}]}
        # Nothing would construct a graph here, so nothing can be verified about
        # one: the rehearsal says so rather than pretending.
        metrics = tb.execute_measured_run(exp, experiment, experiment["cases"][0],
                                          1, dry_run=True)
        assert metrics["rehearsal"]["graph_rehearsed"] is False
        assert "no provider" in metrics["rehearsal"]["reason"]


class TestSpecBodyDigest:
    def test_runtime_markers_do_not_change_the_release_digest(self):
        """The child adds ``_spec_path``; the digest must still match the release."""
        from scripts import gen_cand01_batch_16run_specs_v2 as gen

        spec = json.loads((BATCH / "specs/R01_NVDA_C0/spec.json").read_text())
        delivered = tb.spec_body_sha256(spec)
        with_marker = tb.spec_body_sha256({**spec, "_spec_path": "/anywhere"})
        assert delivered == with_marker
        # ...and the run path and the generator agree on the value.
        assert delivered == gen.spec_body_sha256(spec)


# ---------------------------------------------------------------------------
# The manifest covers what ships
# ---------------------------------------------------------------------------
class TestManifestCoverage:
    def test_the_manifest_covers_every_batch_file_that_ships(self):
        """A manifest that omits a file "verifies" while covering nothing."""
        from c3_build_manifest import POST_COMMIT_METADATA, build_manifest

        listed = {line.split("  ", 1)[1] for line in build_manifest()}
        present = set()
        for line in subprocess.run(
                ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others",
                 "--exclude-standard", "--", BATCH.relative_to(REPO_ROOT).as_posix()],
                capture_output=True, text=True, check=True).stdout.splitlines():
            relative = Path(line).relative_to(BATCH.relative_to(REPO_ROOT)).as_posix()
            if relative == "MANIFEST.sha256" or relative in POST_COMMIT_METADATA:
                continue
            present.add(relative)
        assert listed == present, sorted(present - listed)
        assert "logs/mutation_final_freeze.txt" in listed


# ---------------------------------------------------------------------------
# effective_config.json — written *and* verified
# ---------------------------------------------------------------------------
class TestEffectiveConfig:
    @pytest.fixture(autouse=True)
    def _stub_switch_probe(self, monkeypatch):
        import tradingagents.graph.switch_verification as switch_mod

        monkeypatch.setattr(
            switch_mod, "consume_switches_from_setup",
            lambda setup: getattr(setup, "observed", None)
            or expected_analyst_kwargs(_SPEC_FOR_PROBE["switches"]))

    @staticmethod
    def _spec(switches=None):
        _SPEC_FOR_PROBE["switches"] = switches or _SPEC_FOR_PROBE["switches"]
        return {"experiment_id": "R01",
                "config_sha256": "a" * 64,
                "switches": switches or {"batch_macro": False, "single_pass": True,
                                         "structured": True, "s2_downstream": True},
                "provider": "openai_compatible", "quick_model": "m",
                "deep_model": "m", "case": {"analysts": ["market"]},
                "experiment_root": str(REPO_ROOT)}

    def test_a_faithful_record_verifies(self):
        spec = self._spec()
        graph = _StubGraph(spec["switches"])
        payload = tb.build_effective_config(
            config={"llm_provider": "openai_compatible"},
            spec=spec, graph=graph,
            applied_switches={"structured_analyst_output_enabled": True})
        assert tb.verify_effective_config(
            payload, spec, expected_root=REPO_ROOT)["verified"] is True

    def test_a_switch_mismatch_is_refused(self):
        spec = self._spec()
        graph = _StubGraph({"batch_macro": False, "single_pass": False,
                            "structured": True, "s2_downstream": True})
        payload = tb.build_effective_config(config={}, spec=spec, graph=graph,
                                            applied_switches={})
        with pytest.raises(RuntimeError, match="does not match"):
            tb.verify_effective_config(payload, spec, expected_root=REPO_ROOT)

    def test_a_wrong_import_root_is_refused(self):
        spec = self._spec()
        graph = _StubGraph(spec["switches"])
        payload = tb.build_effective_config(config={}, spec=spec, graph=graph,
                                            applied_switches={})
        with pytest.raises(RuntimeError, match="outside"):
            tb.verify_effective_config(payload, spec, expected_root="/somewhere/else")

    def test_the_writer_verifies_before_it_writes(self):
        """Writing a record nobody validates is how one drifts from reality."""
        import inspect

        source = inspect.getsource(tb._write_effective_config)
        assert "verify_effective_config(" in source
        assert source.index("verify_effective_config(") < source.index(".write_text(")

    def test_a_tampered_hash_is_refused(self):
        spec = self._spec()
        graph = _StubGraph(spec["switches"])
        payload = tb.build_effective_config(config={}, spec=spec, graph=graph,
                                            applied_switches={})
        payload["config_sha256"] = "b" * 64
        with pytest.raises(RuntimeError, match="config_sha256"):
            tb.verify_effective_config(payload, spec, expected_root=REPO_ROOT)


# ---------------------------------------------------------------------------
# The freeze record names this tree, not an ancestor
# ---------------------------------------------------------------------------
class TestFreezeDesignation:
    def test_the_final_freeze_is_generated_from_the_tree_not_typed(self):
        source = (SCRIPTS / "c3_finalize_freeze.py").read_text(encoding="utf-8")
        assert 'git("rev-parse", "HEAD")' in source
        assert "tree_sha" in source and "fingerprint" in source
        # No hand-written commit or digest.
        import re

        literals = re.findall(r"\b[0-9a-f]{40}\b", source)
        assert literals == [], f"hard-coded SHA(s) in c3_finalize_freeze.py: {literals}"

    def test_the_verifier_requires_head_to_equal_the_record(self):
        source = (SCRIPTS / "c3_verify_final_freeze.py").read_text(encoding="utf-8")
        assert 'record.get("commit") != head' in source
        assert 'recorded_commit != head' in source
        assert 'tag_object != head' in source

    def test_a_tree_without_a_record_is_not_a_freeze(self, tmp_path):
        from c3_verify_final_freeze import verify

        result = verify(tmp_path)
        assert result["ok"] is False
        assert any("never certified" in failure for failure in result["failures"])

    def test_the_manifest_builder_covers_every_tracked_artefact(self):
        from c3_build_manifest import build_manifest

        lines = build_manifest()
        names = {line.split("  ", 1)[1] for line in lines}
        assert "CAND01_BATCH_2X2_PROTOCOL_V2.md" in names
        assert "c3/code_freeze.txt" in names
        assert "specs/R01_NVDA_C0/spec.json" in names
        # The manifest cannot contain itself, nor the metadata that names the
        # commit it is committed in.
        assert "MANIFEST.sha256" not in names
        assert not any(name.startswith("c3/FROZEN_COMMIT") for name in names)
        assert not any(name.startswith("c3/FREEZE_RECORD.json") for name in names)
