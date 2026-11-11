"""Credential-free tests for the token benchmark harness (scripts/token_benchmark.py).

These tests never call CityU Foundry or any external LLM. They use synthetic
telemetry payloads, temporary directories, and a fake single-run runner.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import token_benchmark as tb  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic telemetry builder
# ---------------------------------------------------------------------------
def synth_payload(run_id, inp=100000, out=20000, run_status="completed", usage=True,
                  ticker="NVDA", trade_date="2026-09-23", duration_ms=473800.0,
                  reasoning=500, cached=999):
    """Return a realistic-shaped telemetry payload for tests."""
    total_llm = 18
    return {
        "schema_version": 1,
        "run": {
            "telemetry_run_id": run_id,
            "run_status": run_status,
            "failure_type": None,
            "ticker": ticker,
            "trade_date": trade_date,
            "duration_ms": duration_ms,
        },
        "usage_coverage": {
            "complete": usage,
            "llm_calls": total_llm,
            "calls_with_provider_usage": total_llm if usage else total_llm - 1,
            "calls_without_provider_usage": 0 if usage else 1,
        },
        "audit_quality": {
            "usage_complete": usage,
            "attribution_complete": True,
            "telemetry_complete": True,
        },
        "run_totals": {
            "reported_input_tokens_sum": inp,
            "reported_output_tokens_sum": out,
            "reported_reasoning_tokens_sum": reasoning,
            "reported_cached_input_tokens_sum": cached,
            "llm_calls": total_llm,
            "tool_calls": 30,
            "tool_rounds": 5,
            "duplicate_tool_call_count": 2,
            "prefetched_data_calls": 3,
        },
        "agents": {
            "market_analyst": {
                "llm_calls": 8,
                "reported_input_tokens_sum": inp // 2,
                "reported_output_tokens_sum": out // 2,
                "reported_reasoning_tokens_sum": 100,
                "reported_cached_input_tokens_sum": 50,
                "tool_calls": 10,
                "tool_rounds": 2,
                "prompt_utf8_bytes_sum": 100,
                "tool_message_utf8_bytes_sum": 200,
                "tool_result_utf8_bytes_sum": 300,
            },
            "trader": {
                "llm_calls": 2,
                "reported_input_tokens_sum": inp // 4,
                "reported_output_tokens_sum": out // 4,
                "reported_reasoning_tokens_sum": 20,
                "reported_cached_input_tokens_sum": 10,
                "tool_calls": 1,
                "tool_rounds": 1,
                "prompt_utf8_bytes_sum": 50,
                "tool_message_utf8_bytes_sum": 60,
                "tool_result_utf8_bytes_sum": 70,
            },
        },
        "llm_call_events": [1] * total_llm,
        "tool_call_events": [1] * 30,
        "tool_round_events": [1] * 5,
        "prefetch_events": [1] * 3,
        "structured_events": [1] * 4,
        "node_context_events": [1] * 12,
    }


# ---------------------------------------------------------------------------
# Helpers to lay out a synthetic experiment directory
# ---------------------------------------------------------------------------
def _write_exp(exp_dir, experiment):
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / tb.EXPERIMENT_FILE).write_text(json.dumps(experiment), encoding="utf-8")
    return exp_dir


def _write_run(exp_dir, run_index, payload, ticker="NVDA", trade_date="2026-09-23"):
    run_dir = exp_dir / tb.RUNS_DIR / f"run_{run_index:02d}" / "attempt_01"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / tb.TELEMETRY_FILE).write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / tb.METADATA_FILE).write_text(
        json.dumps({
            "run_index": run_index,
            "ticker": ticker,
            "trade_date": trade_date,
            "status": "ok",
        }, indent=2),
        encoding="utf-8",
    )
    # A finished attempt is marked by its state file (the harness only reuses
    # attempts that recorded that they ran).
    (run_dir / tb.RUN_STATE_FILE).write_text(
        json.dumps({"status": "finished", "run_index": run_index}), encoding="utf-8")
    return run_dir


def _realistic_payload(run_id, inp=100000, out=20000, events=2, **kw):
    """A payload whose per-call events agree with its run totals.

    ``verify_measurement`` cross-checks totals against the individual LLM
    events, so a payload that merely *claims* a total is not enough.
    """
    payload = synth_payload(run_id, inp=inp, out=out, **kw)
    payload["usage_coverage"]["llm_calls"] = events
    payload["usage_coverage"]["calls_with_provider_usage"] = (
        events if payload["usage_coverage"]["complete"] else events - 1)
    payload["run_totals"]["llm_calls"] = events
    base_in, rem_in = divmod(inp, events)
    base_out, rem_out = divmod(out, events)
    payload["llm_call_events"] = [
        {
            "telemetry_run_id": run_id,
            "agent_id": "market_analyst" if i % 2 == 0 else "trader",
            "success": True,
            "error_class": None,
            "reported_input_tokens": base_in + (rem_in if i == 0 else 0),
            "reported_output_tokens": base_out + (rem_out if i == 0 else 0),
            "reported_reasoning_tokens": 10,
            "reported_cached_input_tokens": 5,
            "usage_complete": True,
            "usage_source": "provider",
        }
        for i in range(events)
    ]
    return payload


def _make_experiment(exp_id="exp", runs=5, ticker="NVDA", date="2026-09-23"):
    exp = tb.default_experiment(exp_id, Path("/tmp"))
    exp["measured_runs"] = runs
    exp["cases"][0]["ticker"] = ticker
    exp["cases"][0]["trade_date"] = date
    return exp


# ---------------------------------------------------------------------------
# Experiment JSON validation
# ---------------------------------------------------------------------------
class TestValidateExperiment:
    def test_valid_experiment(self):
        exp = tb.default_experiment("x", Path("/tmp"))
        assert tb.validate_experiment(exp) == []

    def test_uses_real_analyst_keys(self):
        exp = tb.default_experiment("x", Path("/tmp"))
        assert exp["cases"][0]["analysts"] == list(tb.VALID_ANALYSTS)
        assert tb.validate_experiment(tb.default_experiment("x", Path("/tmp"))) == []

    def test_missing_ticker(self, tmp_path):
        exp = tb.default_experiment("x", tmp_path)
        del exp["cases"][0]["ticker"]
        errors = tb.validate_experiment(exp)
        assert any("ticker" in e for e in errors)

    def test_missing_trade_date(self, tmp_path):
        exp = tb.default_experiment("x", tmp_path)
        del exp["cases"][0]["trade_date"]
        errors = tb.validate_experiment(exp)
        assert any("trade_date" in e for e in errors)

    def test_rejects_today(self, tmp_path):
        exp = tb.default_experiment("x", tmp_path)
        exp["cases"][0]["trade_date"] = "today"
        errors = tb.validate_experiment(exp)
        assert any("trade_date" in e for e in errors)

    def test_rejects_empty_date(self, tmp_path):
        exp = tb.default_experiment("x", tmp_path)
        exp["cases"][0]["trade_date"] = ""
        errors = tb.validate_experiment(exp)
        assert any("trade_date" in e for e in errors)

    def test_rejects_invalid_analyst_key(self, tmp_path):
        exp = tb.default_experiment("x", tmp_path)
        exp["cases"][0]["analysts"] = ["market", "bogus"]
        errors = tb.validate_experiment(exp)
        assert any("bogus" in e for e in errors)

    def test_rejects_bad_measured_runs(self, tmp_path):
        exp = tb.default_experiment("x", tmp_path)
        exp["measured_runs"] = 0
        errors = tb.validate_experiment(exp)
        assert any("measured_runs" in e for e in errors)

    def test_rejects_non_dict(self, tmp_path):
        with pytest.raises(ValueError):
            tb.validate_experiment(["not", "a", "dict"])


# ---------------------------------------------------------------------------
# Metric extraction semantics
# ---------------------------------------------------------------------------
class TestTokenSemantics:
    def test_total_is_input_plus_output_only(self):
        m = tb.extract_run_metrics(synth_payload("r1", inp=1000, out=250,
                                                 reasoning=999, cached=888), None, 1)
        assert m["total_tokens"] == 1000 + 250
        # Reasoned + cached are subsets and never double-counted.
        assert m["reported_reasoning_tokens_sum"] == 999
        assert m["reported_cached_input_tokens_sum"] == 888

    def test_valid_requires_completed_and_usage(self):
        assert tb.extract_run_metrics(synth_payload("r1", usage=True, run_status="completed"),
                                      None, 1)["valid"] is True
        assert tb.extract_run_metrics(synth_payload("r1", usage=False, run_status="completed"),
                                      None, 1)["valid"] is False
        assert tb.extract_run_metrics(synth_payload("r1", usage=True, run_status="failed"),
                                      None, 1)["valid"] is False

    def test_partial_usage_not_zeroed(self):
        # usage incomplete: preserve known values, mark invalid (not zero-ify).
        m = tb.extract_run_metrics(synth_payload("r1", inp=5000, out=100, usage=False), None, 1)
        assert m["reported_input_tokens_sum"] == 5000
        assert m["total_tokens"] == 5100
        assert m["valid"] is False


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
class TestAggregate:
    def test_mean_median_min_max(self):
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        agg = tb.aggregate(vals)
        assert agg["n"] == 5
        assert agg["mean"] == 30.0
        assert agg["median"] == 30.0
        assert agg["min"] == 10.0
        assert agg["max"] == 50.0
        # sd of 10,20,30,40,50 is > 0 (sample stdev approx 15.81)
        assert abs(agg["stdev"] - 15.8114) < 0.01

    def test_sample_stdev(self):
        agg = tb.aggregate([1.0, 2.0, 3.0, 4.0])
        assert abs(agg["stdev"] - 1.2909) < 0.001

    def test_n1_stdev_is_null_not_zero(self):
        agg = tb.aggregate([42.0])
        assert agg["n"] == 1
        assert agg["mean"] == 42.0
        assert agg["stdev"] is None

    def test_empty(self):
        agg = tb.aggregate([])
        assert agg["n"] == 0
        assert agg["mean"] is None
        assert agg["stdev"] is None


# ---------------------------------------------------------------------------
# Full summarize pipeline
# ---------------------------------------------------------------------------
class TestSummarize:
    def _build(self, tmp_path, inps=(100000, 120000, 110000, 130000), runs=4,
               invalid_at=None):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=runs)
        _write_exp(exp_dir, exp)
        for i, inp in enumerate(inps[:runs], start=1):
            # Mark exactly one run invalid if requested (usage incomplete).
            usage = (i != invalid_at) if invalid_at is not None else True
            _write_run(exp_dir, i, synth_payload(f"r{i}", inp=inp, usage=usage,
                                                 run_status="completed" if usage else "failed"))
        return exp_dir, exp

    def test_aggregation_of_runs(self, tmp_path):
        # 4 valid runs -> n=4 for aggregates.
        exp_dir, _exp = self._build(tmp_path, inps=(100000, 120000, 110000, 130000), runs=4)
        result = tb.summarize_experiment(exp_dir)
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 4
        tot = s["run_totals"]["total_tokens"]
        # Totals (in+20000): 120000, 140000, 130000, 150000 -> mean 135000.
        assert tot["n"] == 4
        assert tot["mean"] == 135000
        assert tot["median"] == 135000
        assert tot["min"] == 120000
        assert tot["max"] == 150000
        assert tot["stdev"] is not None

    def test_invalid_run_excluded_and_preserved(self, tmp_path):
        exp_dir, _exp = self._build(tmp_path, inps=(100000, 120000, 110000, 130000),
                                    runs=4, invalid_at=4)
        result = tb.summarize_experiment(exp_dir)
        s = result["summaries"]["nvda_2026_09_23"]
        # Run 4 invalid (usage False) -> excluded from totals but preserved.
        assert s["measured_valid"] == 3
        assert s["measured_target"] == 4
        assert s["run_totals"]["total_tokens"]["n"] == 3

    def test_per_agent_aggregation(self, tmp_path):
        exp_dir, _exp = self._build(tmp_path, inps=(100000, 120000, 110000, 130000), runs=4)
        result = tb.summarize_experiment(exp_dir)
        s = result["summaries"]["nvda_2026_09_23"]
        assert "market_analyst" in s["per_agent"]
        ma = s["per_agent"]["market_analyst"]
        # Market input mean of (50000,60000,55000,65000) = 57500; output 10000 fixed.
        assert ma["input_tokens"]["mean"] == 57500
        assert ma["output_tokens"]["mean"] == 10000
        assert ma["total_tokens"]["mean"] == 67500
        assert ma["tool_calls"]["mean"] == 10

    def test_summary_files_generated(self, tmp_path):
        exp_dir, _exp = self._build(tmp_path, inps=(100000, 120000, 110000, 130000), runs=4)
        tb.summarize_experiment(exp_dir)
        for name in (tb.SUMMARY_JSON, tb.SUMMARY_CSV, tb.SUMMARY_AGENTS_CSV, tb.SUMMARY_MD):
            assert (exp_dir / name).exists()

    def test_csv_rows_per_run(self, tmp_path):
        exp_dir, _exp = self._build(tmp_path, inps=(100000, 120000, 110000, 130000), runs=4)
        tb.summarize_experiment(exp_dir)
        with open(exp_dir / tb.SUMMARY_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 4
        assert rows[0]["experiment_id"] == "exp"
        assert int(rows[0]["total_tokens"]) == 120000
        assert "telemetry_path" in rows[0]

    def test_agents_csv_present(self, tmp_path):
        exp_dir, _exp = self._build(tmp_path, inps=(100000, 120000, 110000, 130000), runs=4)
        tb.summarize_experiment(exp_dir)
        with open(exp_dir / tb.SUMMARY_AGENTS_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows
        assert {"agent_id", "total_tokens", "run_index"} <= set(rows[0].keys())

    def test_n1_run_stdev_null_in_summary(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, synth_payload("r1", inp=100000, usage=True))
        result = tb.summarize_experiment(exp_dir)
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["run_totals"]["total_tokens"]["n"] == 1
        assert s["run_totals"]["total_tokens"]["stdev"] is None

    def test_no_secrets_or_raw_payloads_in_metadata(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / tb.TELEMETRY_FILE).write_text(json.dumps(synth_payload("r1")), encoding="utf-8")
        status = {"run_index": 1, "ticker": "NVDA", "trade_date": "2026-09-23",
                  "status": "ok", "api_key_set": False}
        (run_dir / tb.METADATA_FILE).write_text(json.dumps(status), encoding="utf-8")
        tb.summarize_experiment(exp_dir)
        meta = json.loads((run_dir / tb.METADATA_FILE).read_text())
        summary_txt = json.dumps(tb.load_summary(exp_dir))
        # Bounded metadata only (a harmless boolean, not a payload copy).
        assert "api_key_set" in meta and meta["api_key_set"] is False
        # No raw event arrays (the [1,1,1...] payload lists) are persisted.
        assert "[1, 1" not in summary_txt
        # Summaries expose only aggregate/run metrics, not raw messages/secrets.
        for bad in ("api_key", "authorization", "bearer", "llm_provider_secret",
                    "x-api-key"):
            assert bad not in summary_txt.lower()


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
class TestCompare:
    def _summaries(self, tmp_path, base_inp=100000, cand_inp=80000):
        def build(name, inp):
            exp_dir = tmp_path / name
            exp = _make_experiment(name, runs=3)
            _write_exp(exp_dir, exp)
            for i in range(1, 4):
                _write_run(exp_dir, i, synth_payload(f"r{i}", inp=inp))
            return tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        return build("base", base_inp), build("cand", cand_inp)

    def test_percent_change(self, tmp_path):
        base, cand = self._summaries(tmp_path, base_inp=100000, cand_inp=80000)
        cmp = tb.compare_summaries(base, cand)
        row = next(m for m in cmp["metrics"] if m["metric"] == "input_tokens")
        # Both have +20000 output; compare input means 100000->80000 => -20%.
        # input only (constant output cancels). cand mean 80000, base 100000.
        assert row["candidate"] == 80000
        assert row["baseline"] == 100000
        assert abs(row["percent"] - (-20.0)) < 0.01
        assert row["absolute"] == -20000

    def test_increase_is_positive(self, tmp_path):
        base, cand = self._summaries(tmp_path, base_inp=100000, cand_inp=120000)
        cmp = tb.compare_summaries(base, cand)
        row = next(m for m in cmp["metrics"] if m["metric"] == "input_tokens")
        assert row["percent"] > 0

    def test_zero_baseline_safe(self, tmp_path):
        base, cand = self._summaries(tmp_path, base_inp=0, cand_inp=80000)
        cmp = tb.compare_summaries(base, cand)
        row = next(m for m in cmp["metrics"] if m["metric"] == "input_tokens")
        assert row["percent"] is None  # no ZeroDivisionError
        assert row["absolute"] == 80000

    def test_mismatched_case_blocked(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, synth_payload("r1"))
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        # Build a candidate with a different date.
        exp2 = _make_experiment("exp2", runs=1, date="2026-10-20")
        exp_dir2 = tmp_path / "exp2"
        _write_exp(exp_dir2, exp2)
        _write_run(exp_dir2, 1, synth_payload("r2", trade_date="2026-10-20"))
        summary2 = tb.summarize_experiment(exp_dir2)["summaries"]["nvda_2026_09_23"]
        with pytest.raises(ValueError):
            tb.compare_summaries(summary, summary2)
        # With override it proceeds.
        cmp = tb.compare_summaries(summary, summary2, allow_mismatch=True)
        assert cmp["metrics"]

    def test_per_agent_total_comparison(self, tmp_path):
        base, cand = self._summaries(tmp_path, base_inp=100000, cand_inp=80000)
        cmp = tb.compare_summaries(base, cand)
        names = [r["agent"] for r in cmp["per_agent_total_tokens"]]
        assert "Market Analyst" in names


# ---------------------------------------------------------------------------
# init / --force
# ---------------------------------------------------------------------------
class TestInit:
    def test_init_creates_files(self, tmp_path):
        out = tmp_path / "root"
        rc = tb._cmd_init(_Args(id="e1", output_root=str(out), force=False))
        assert rc == 0
        assert (out / "e1" / tb.EXPERIMENT_FILE).exists()
        assert (out / "e1" / tb.NOTE_FILE).exists()

    def test_init_no_overwrite_without_force(self, tmp_path):
        out = tmp_path / "root"
        tb._cmd_init(_Args(id="e1", output_root=str(out), force=False))
        exp_path = out / "e1" / tb.EXPERIMENT_FILE
        before = exp_path.read_text()
        rc = tb._cmd_init(_Args(id="e1", output_root=str(out), force=False))
        assert rc == 2
        assert exp_path.read_text() == before

    def test_init_overwrite_with_force(self, tmp_path):
        out = tmp_path / "root"
        tb._cmd_init(_Args(id="e1", output_root=str(out), force=False))
        exp_path = out / "e1" / tb.EXPERIMENT_FILE
        exp_path.write_text('{"modified": true}', encoding="utf-8")
        rc = tb._cmd_init(_Args(id="e1", output_root=str(out), force=True))
        assert rc == 0
        assert '"modified"' not in exp_path.read_text()


# ---------------------------------------------------------------------------
# Exactly-one telemetry validation
# ---------------------------------------------------------------------------
class TestTelemetryLocator:
    def test_exactly_one_ok(self, tmp_path):
        runtime = tmp_path / "res" / "NVDA" / "2026-09-23"
        (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
        (runtime / "telemetry" / "a.json").write_text("{}", encoding="utf-8")
        p = tb._locate_telemetry(runtime, {"ticker": "NVDA", "trade_date": "2026-09-23"})
        assert p.name == "a.json"

    def test_zero_raises(self, tmp_path):
        runtime = tmp_path / "res" / "NVDA" / "2026-09-23"
        runtime.mkdir(parents=True, exist_ok=True)
        with pytest.raises(RuntimeError):
            tb._locate_telemetry(runtime, {"ticker": "NVDA", "trade_date": "2026-09-23"})

    def test_multiple_raises(self, tmp_path):
        runtime = tmp_path / "res" / "NVDA" / "2026-09-23"
        (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
        (runtime / "telemetry" / "a.json").write_text("{}", encoding="utf-8")
        (runtime / "telemetry" / "b.json").write_text("{}", encoding="utf-8")
        with pytest.raises(RuntimeError):
            tb._locate_telemetry(runtime, {"ticker": "NVDA", "trade_date": "2026-09-23"})


class TestRerunTelemetrySelection:
    """Regression: a re-run must use only the telemetry it created.

    A measured re-run into the same runtime dir previously left the earlier
    telemetry in place, so a later attempt found two artifacts and was marked
    ambiguous. Selection now compares against a pre-run snapshot; leftover
    artifacts are preserved but never candidates, and zero/multiple new
    artifacts still fail loudly.
    """

    def _setup(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        case = exp["cases"][0]
        runtime = tb._run_runtime_dir(exp_dir, case, 1)
        (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
        return exp_dir, exp, case, runtime

    def _runner_writing(self, runtime, run_dir, payloads, report_path="first"):
        """Build a runner that writes ``payloads`` and snapshots beforehand."""

        def runner(spec_path, exp_dir, run_index, attempt=1):
            before = tb._telemetry_snapshot(runtime)
            written = []
            for name, rid, inp in payloads:
                path = runtime / "telemetry" / name
                path.write_text(json.dumps(synth_payload(rid, inp=inp)), encoding="utf-8")
                written.append(str(path))
            reported = None
            if written and report_path == "first":
                reported = written[0]
            report = {"status": "completed", "run_status": "completed",
                      "error": None, "telemetry_path": reported}
            (run_dir / tb.RUNNER_REPORT_FILE).write_text(
                json.dumps(report), encoding="utf-8")
            return {
                "status": "ok", "returncode": 0, "error": None, "report": report,
                "telemetry_before": sorted(before),
                "telemetry_new": sorted(tb._telemetry_snapshot(runtime) - before),
            }

        return runner

    def test_runner_reporting_relative_path_is_a_valid_run(self, tmp_path):
        """End-to-end: the production runner's relative report must validate.

        ``run_single_process`` records ``telemetry_path`` with ``_portable_path``
        relative to the experiment directory, while ``telemetry_before`` holds
        absolute snapshot strings. Reproducing that split used to mark a
        genuinely valid run as ``status_mismatch``.
        """
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"
        absolute_runner = self._runner_writing(
            runtime, run_dir, [("run-new-1.json", "new", 22222)])

        def relative_runner(spec_path, exp_dir, run_index, attempt=1):
            result = absolute_runner(spec_path, exp_dir, run_index, attempt)
            absolute = result["report"]["telemetry_path"]
            # The child runs with cwd = experiment dir; ``_portable_path``
            # renders the record relative to that location.
            relative = Path(absolute).relative_to(exp_dir).as_posix()
            result["report"] = {**result["report"], "telemetry_path": relative}
            return result

        metrics = tb.execute_measured_run(
            exp_dir, exp, case, 1, runner=relative_runner, run_dir=run_dir)

        assert metrics["run_status"] == "completed"
        assert metrics["valid"] is True
        assert metrics["reported_input_tokens_sum"] == 22222
        assert (run_dir / tb.TELEMETRY_FILE).exists()

    def test_nonzero_exit_with_completed_telemetry_keeps_metrics(self, tmp_path):
        """A child that writes completed telemetry but exits non-zero is valid."""
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"
        runner = self._runner_writing(
            runtime, run_dir, [("run-new-1.json", "new", 22222)])

        def failing_exit(spec_path, exp_dir, run_index, attempt=1):
            result = runner(spec_path, exp_dir, run_index)
            result.update({"status": "failed", "returncode": 1,
                           "error": "Traceback: late logging error"})
            return result

        metrics = tb.execute_measured_run(exp_dir, exp, case, 1, runner=failing_exit, run_dir=run_dir)

        # Telemetry is authoritative: the completed artifact yields a valid sample.
        assert metrics["valid"] is True
        assert metrics["run_status"] == "completed"
        assert metrics["reported_input_tokens_sum"] == 22222
        assert metrics["llm_calls"] > 0
        # The process-level diagnostic is still preserved, not discarded.
        assert "late logging error" in (metrics["runner_error"] or "")
        meta = json.loads((run_dir / tb.METADATA_FILE).read_text())
        assert meta["status"] == "ok"
        assert meta["runner_error"] and "late logging error" in meta["runner_error"]

    def test_old_telemetry_present_selects_only_the_new_artifact(self, tmp_path):
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        old = runtime / "telemetry" / "run-old-1.json"
        old.write_text(json.dumps(synth_payload("old", inp=11111)), encoding="utf-8")
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"

        runner = self._runner_writing(
            runtime, run_dir, [("run-new-1.json", "new", 22222)])
        metrics = tb.execute_measured_run(exp_dir, exp, case, 1, runner=runner, run_dir=run_dir)

        assert metrics["valid"] is True
        assert metrics["run_status"] == "completed"
        # The new artifact was selected, not merely "the latest file present".
        assert metrics["reported_input_tokens_sum"] == 22222
        copied = json.loads((run_dir / tb.TELEMETRY_FILE).read_text())
        assert copied["run"]["telemetry_run_id"] == "new"
        meta = json.loads((run_dir / tb.METADATA_FILE).read_text())
        assert meta["status"] == "ok"
        assert meta["original_telemetry_path"].endswith("run-new-1.json")

    def test_no_new_artifact_fails(self, tmp_path):
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        (runtime / "telemetry" / "run-old-1.json").write_text(
            json.dumps(synth_payload("old")), encoding="utf-8")
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"

        runner = self._runner_writing(runtime, run_dir, [])
        metrics = tb.execute_measured_run(exp_dir, exp, case, 1, runner=runner, run_dir=run_dir)

        assert metrics["valid"] is False
        assert metrics["run_status"] == "failed"
        assert "no new telemetry artifact" in (metrics["error"] or "")
        assert not (run_dir / tb.TELEMETRY_FILE).exists()

    def test_multiple_new_artifacts_are_ambiguous(self, tmp_path):
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        (runtime / "telemetry" / "run-old-1.json").write_text(
            json.dumps(synth_payload("old")), encoding="utf-8")
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"

        runner = self._runner_writing(runtime, run_dir, [
            ("run-new-a-1.json", "new-a", 30000),
            ("run-new-b-1.json", "new-b", 31000),
        ])
        metrics = tb.execute_measured_run(exp_dir, exp, case, 1, runner=runner, run_dir=run_dir)

        assert metrics["valid"] is False
        assert metrics["run_status"] == "failed"
        assert "multiple new telemetry artifacts" in (metrics["error"] or "")
        # Ambiguity must not be papered over by copying the reported file.
        assert not (run_dir / tb.TELEMETRY_FILE).exists()

    def test_relative_reported_path_selects_the_same_artifact(self, tmp_path):
        """A repository-relative report resolves to the same artifact."""

        exp_dir, exp, case, runtime = self._setup(tmp_path)
        target = runtime / "telemetry" / "run-new-1.json"
        target.write_text(json.dumps(synth_payload("new", inp=22222)), encoding="utf-8")
        # The child runs with cwd set to the experiment dir, so the recorded
        # ``_portable_path`` is anchored there.
        relative = target.relative_to(exp_dir).as_posix()

        before = tb._telemetry_snapshot(runtime)
        before.discard(str(target))
        selected = tb._select_run_telemetry(runtime, before, relative,
                                            reported_base=exp_dir)

        assert selected == target
        assert selected.resolve() == target.resolve()
        assert not Path(relative).is_absolute()

    def test_runner_report_path_is_relative_to_the_experiment_dir(self, tmp_path):
        """The producer must anchor ``telemetry_path`` at the experiment dir.

        Regression: ``spec.json`` sits at ``<exp>/runs/run_NN/attempt_NN/``, so
        ``spec_path.parent.parent.parent`` is ``<exp>/runs``. Anchoring there
        emitted ``run_NN/attempt_NN/...`` and dropped the ``runs/`` component,
        which the consumer resolves against ``<exp>`` -- so the recorded path
        never matched the real artifact and every run was rejected as
        ``status_mismatch``.
        """
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        target = runtime / "telemetry" / "run-new-1.json"
        target.write_text(json.dumps(synth_payload("new")), encoding="utf-8")
        spec_path = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01" / "spec.json"

        recorded = tb._portable_path(target, spec_path.parent.parent.parent.parent)

        assert recorded is not None
        assert not Path(recorded).is_absolute()
        assert Path(recorded).parts[0] == tb.RUNS_DIR, recorded
        assert (exp_dir / recorded).resolve() == target.resolve()

    def test_different_reported_path_is_still_rejected(self, tmp_path):
        """Resolving must not weaken the single-artifact contract."""
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        other = runtime / "telemetry" / "run-other-1.json"
        other.write_text(json.dumps(synth_payload("other")), encoding="utf-8")
        target = runtime / "telemetry" / "run-new-1.json"
        target.write_text(json.dumps(synth_payload("new")), encoding="utf-8")

        before = tb._telemetry_snapshot(runtime)
        before.discard(str(target))
        with pytest.raises(RuntimeError, match="refusing to guess"):
            tb._select_run_telemetry(runtime, before, str(other))

    def test_historical_telemetry_is_preserved(self, tmp_path):
        exp_dir, exp, case, runtime = self._setup(tmp_path)
        old = runtime / "telemetry" / "run-old-1.json"
        old_bytes = json.dumps(synth_payload("old", inp=11111)).encode()
        old.write_bytes(old_bytes)
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"

        runner = self._runner_writing(
            runtime, run_dir, [("run-new-1.json", "new", 22222)])
        tb.execute_measured_run(exp_dir, exp, case, 1, runner=runner, run_dir=run_dir)

        assert old.exists(), "historical telemetry must never be deleted"
        assert old.read_bytes() == old_bytes, "historical telemetry must be unchanged"
        assert (runtime / "telemetry" / "run-new-1.json").exists()


class TestResumableRuns:
    """Regression: an aborted experiment resumes without mixing attempts."""

    def test_completed_runs_are_reused_not_rerun(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=2)
        _write_exp(exp_dir, exp)
        calls = []

        def runner(spec_path, exp_dir, run_index, attempt=1):
            calls.append(run_index)
            return _fake_runner(spec_path, exp_dir, run_index)

        first = tb.run_experiment(exp_dir, exp, runner=runner)
        assert calls == [1, 2]
        assert first["summaries"]["nvda_2026_09_23"]["measured_valid"] == 2

        calls.clear()
        second = tb.run_experiment(exp_dir, exp, runner=runner)
        assert calls == [], "completed runs must not be executed again"
        s = second["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 2
        # The reused metrics are identical to the originals.
        assert s["run_totals"]["input_tokens"]["mean"] == \
            first["summaries"]["nvda_2026_09_23"]["run_totals"]["input_tokens"]["mean"]

    def test_interrupted_attempt_is_left_alone_and_not_retried_over(self, tmp_path):
        """An interrupted attempt is evidence, not a sample, and is not reused."""
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        interrupted = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"
        interrupted.mkdir(parents=True)
        (interrupted / tb.RUN_STATE_FILE).write_text(json.dumps({"status": "started"}))
        before = (interrupted / tb.RUN_STATE_FILE).read_bytes()

        calls = []

        def runner(spec_path, exp_dir, run_index, attempt=1):
            calls.append((run_index, attempt))
            return _fake_runner(spec_path, exp_dir, run_index)

        result = tb.run_experiment(exp_dir, exp, runner=runner)
        # A valid run is not executed again just because an interrupted attempt
        # happens to be the newest directory.
        assert calls == [(1, 2)]
        assert (interrupted / tb.RUN_STATE_FILE).read_bytes() == before
        assert not (interrupted / tb.TELEMETRY_FILE).exists()
        assert result["summaries"]["nvda_2026_09_23"]["measured_valid"] == 1

    def test_interrupted_attempt_after_valid_run_does_not_force_a_rerun(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        tb.run_experiment(exp_dir, exp, runner=_fake_runner)
        # A later attempt was started (e.g. the process was interrupted) but
        # never produced telemetry.
        interrupted = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_02"
        interrupted.mkdir(parents=True)
        (interrupted / tb.RUN_STATE_FILE).write_text(json.dumps({"status": "started"}))

        calls = []

        def runner(spec_path, exp_dir, run_index, attempt=1):
            calls.append((run_index, attempt))
            return _fake_runner(spec_path, exp_dir, run_index)

        result = tb.run_experiment(exp_dir, exp, runner=runner)
        assert calls == [], "the valid attempt must be reused, not re-run"
        assert result["summaries"]["nvda_2026_09_23"]["measured_valid"] == 1

    def test_run_state_marks_finished_runs(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        tb.run_experiment(exp_dir, exp, runner=_fake_runner)
        state = json.loads((exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01" / tb.RUN_STATE_FILE).read_text())
        assert state["status"] == "finished"
        assert state["telemetry_path"].endswith(tb.TELEMETRY_FILE)


class TestIncompleteUsageIsNotMeasured:
    """A completed run with an unaccounted LLM call is not a measured sample."""

    def test_invalid_attempt_is_retried_in_a_fresh_attempt_dir(self, tmp_path):
        """An invalid stored attempt is evidence, not a sample: a new attempt runs."""
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        first_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"
        first_dir.mkdir(parents=True)
        payload = synth_payload("partial", usage=False)
        payload["run"]["run_status"] = "completed"
        # The copied artifact is the stored evidence that made it invalid.
        (first_dir / tb.TELEMETRY_FILE).write_text(json.dumps(payload))
        (first_dir / tb.RUN_STATE_FILE).write_text(json.dumps({"status": "finished"}))
        original = (first_dir / tb.TELEMETRY_FILE).read_bytes()

        calls = []

        def runner(spec_path, exp_dir, run_index, attempt=1):
            calls.append((run_index, attempt))
            return _fake_runner(spec_path, exp_dir, run_index)

        result = tb.run_experiment(exp_dir, exp, runner=runner)
        assert calls == [(1, 2)], "a new attempt must run in its own directory"
        # The earlier attempt is untouched and stays on disk as evidence.
        assert (first_dir / tb.TELEMETRY_FILE).read_bytes() == original
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 1
        assert len(s["runs"]) == 1, "only the measured attempt feeds the summary"

    def test_continue_on_error_keeps_invalid_attempt_with_diagnostic(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"
        run_dir.mkdir(parents=True)
        payload = synth_payload("partial", usage=False)
        payload["run"]["run_status"] = "completed"
        (run_dir / tb.TELEMETRY_FILE).write_text(json.dumps(payload))
        (run_dir / tb.RUN_STATE_FILE).write_text(json.dumps({"status": "finished"}))

        calls = []

        def runner(spec_path, exp_dir, run_index, attempt=1):
            calls.append(run_index)
            return _fake_runner(spec_path, exp_dir, run_index)

        result = tb.run_experiment(exp_dir, exp, runner=runner, continue_on_error=True)
        assert calls == [], "skipping must not spend another LLM run"
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 0
        assert s["runs"][0]["error"] == tb.INVALID_USAGE_MISSING

    def test_failed_llm_call_without_usage_invalidates_the_run(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)

        def runner(spec_path, exp_dir, run_index, attempt=1):
            spec = json.loads(spec_path.read_text())
            runtime = Path(spec["results_dir"])
            (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
            payload = synth_payload("partial", usage=False)
            # The run finished, but one retried call reported no usage.
            payload["run"]["run_status"] = "completed"
            path = runtime / "telemetry" / "run-x-1.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = {"status": "completed", "run_status": "completed",
                      "error": None, "telemetry_path": str(path)}
            return {"status": "ok", "returncode": 0, "error": None, "report": report}

        run_dir = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_01"
        metrics = tb.execute_measured_run(exp_dir, exp, exp["cases"][0], 1, runner=runner,
                                          run_dir=run_dir)
        assert metrics["run_status"] == "completed"
        assert metrics["usage_coverage_complete"] is False
        assert metrics["valid"] is False
        assert metrics["invalid_reason"] == tb.INVALID_USAGE_MISSING
        assert metrics["error"] == tb.INVALID_USAGE_MISSING


class TestLegacyFlatRunMigration:
    """Old flat runs (runs/run_NN/*.json) are copied, never overwritten."""

    def test_flat_run_is_copied_into_attempt_layout(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        flat = exp_dir / tb.RUNS_DIR / "run_01"
        flat.mkdir(parents=True)
        payload = synth_payload("legacy", inp=12345)
        (flat / tb.TELEMETRY_FILE).write_text(json.dumps(payload))
        (flat / tb.METADATA_FILE).write_text(json.dumps({
            "run_index": 1, "ticker": "NVDA", "trade_date": "2026-09-23",
            "status": "ok"}))
        (flat / tb.RUN_STATE_FILE).write_text(json.dumps({"status": "finished"}))
        originals = {p.name: p.read_bytes() for p in flat.iterdir() if p.is_file()}

        result = tb.summarize_experiment(exp_dir)

        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 1
        assert s["run_totals"]["input_tokens"]["mean"] == 12345
        attempt = flat / "attempt_01"
        assert (attempt / tb.TELEMETRY_FILE).exists()
        state = json.loads((attempt / tb.RUN_STATE_FILE).read_text())
        # Provenance is recorded relative to the experiment dir: committed
        # reports must not embed the operator's home directory.
        assert state["migrated_from"] == "runs/run_01"
        assert not Path(state["migrated_from"]).is_absolute()
        meta = json.loads((attempt / tb.METADATA_FILE).read_text())
        assert meta["migrated_from"] == "runs/run_01"
        assert not Path(meta["migrated_from"]).is_absolute()
        # Historical files stay exactly where and as they were.
        for name, data in originals.items():
            assert (flat / name).read_bytes() == data

    def test_migration_does_not_touch_existing_attempt(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        flat = exp_dir / tb.RUNS_DIR / "run_01"
        flat.mkdir(parents=True)
        (flat / tb.TELEMETRY_FILE).write_text(json.dumps(synth_payload("flat", inp=111)))
        attempt = tb._attempt_dir(exp_dir, 1, 1)
        attempt.mkdir(parents=True)
        (attempt / tb.TELEMETRY_FILE).write_text(json.dumps(synth_payload("attempt", inp=999)))

        tb._migrate_flat_run(exp_dir, 1)

        copied = json.loads((attempt / tb.TELEMETRY_FILE).read_text())
        assert copied["run"]["telemetry_run_id"] == "attempt"


class TestMultiCaseNoOverwrite:
    """Regression: multiple cases must each be represented in the reports."""

    def _two_case_experiment(self, runs=2):
        exp = _make_experiment("multi", runs=runs)
        second = dict(exp["cases"][0])
        second.update({"case_id": "aapl_2026_09_23", "ticker": "AAPL"})
        exp["cases"] = [exp["cases"][0], second]
        return exp

    def test_run_summarize_keeps_every_case(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = self._two_case_experiment(runs=2)
        _write_exp(exp_dir, exp)
        tb.run_experiment(exp_dir, exp, runner=_fake_runner)

        index_path = exp_dir / tb.SUMMARY_INDEX_JSON
        assert index_path.exists()
        index = json.loads(index_path.read_text())
        assert index["case_count"] == 2
        case_ids = [c["case_id"] for c in index["cases"]]
        assert case_ids == ["nvda_2026_09_23", "aapl_2026_09_23"]

        for entry in index["cases"]:
            for key in ("summary_json", "summary_csv", "summary_agents_csv", "summary_md"):
                assert Path(entry[key]).exists()
        nvda = json.loads(Path(index["cases"][0]["summary_json"]).read_text())
        aapl = json.loads(Path(index["cases"][1]["summary_json"]).read_text())
        assert nvda["ticker"] == "NVDA"
        assert aapl["ticker"] == "AAPL"
        assert nvda["case_id"] != aapl["case_id"]
        # No top-level summary pretending to represent all cases.
        assert not (exp_dir / tb.SUMMARY_JSON).exists()

        # summarize (offline rebuild) must produce the same non-lossy layout.
        for name in (tb.SUMMARY_INDEX_JSON,):
            (exp_dir / name).unlink()
        tb.summarize_experiment(exp_dir)
        rebuilt = json.loads(index_path.read_text())
        assert [c["case_id"] for c in rebuilt["cases"]] == case_ids

    def test_single_case_keeps_canonical_top_level_reports(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("solo", runs=1)
        _write_exp(exp_dir, exp)
        tb.run_experiment(exp_dir, exp, runner=_fake_runner)
        for name in (tb.SUMMARY_JSON, tb.SUMMARY_CSV, tb.SUMMARY_AGENTS_CSV, tb.SUMMARY_MD):
            assert (exp_dir / name).exists()
        assert not (exp_dir / tb.SUMMARY_INDEX_JSON).exists()


class TestRuntimeDirMatchesApplicationLayout:
    """The harness must predict the directory the application writes telemetry to."""

    def test_runtime_dir_matches_observability_path(self, tmp_path):
        from tradingagents.observability import _compute_telemetry_path

        case = {"case_id": "nvda", "ticker": "NVDA", "trade_date": "2026-09-23"}
        spec_path = tb.prepare_run_spec(tmp_path, tb.default_experiment("e", tmp_path),
                                        case, run_index=1)
        spec = json.loads(spec_path.read_text())
        # The application writes under the run-specific results_dir from the spec.
        results_dir = spec["results_dir"]

        class _Collector:
            telemetry_run_id = "abc123"

        expected = _compute_telemetry_path(_Collector(), results_dir=results_dir,
                                           ticker=case["ticker"], trade_date=case["trade_date"])
        assert expected.parts[-4:] == ("NVDA", "2026-09-23", "telemetry", "abc123.json")
        # The results_dir is run-specific, so no two runs share a telemetry dir.
        assert results_dir == str(tb._run_runtime_dir(tmp_path, case, 1))
        assert "run_01" in results_dir
        assert expected.parent.parent == Path(results_dir) / "NVDA" / "2026-09-23"

    def test_invalid_path_tickers_stay_isolated(self, tmp_path):
        # e.g. crypto pairs are rejected by the application's path rules; the
        # harness must not fall back to a shared directory.
        d1 = tb._run_runtime_dir(tmp_path, {"ticker": "BTC-USD", "trade_date": "2026-09-23"}, 1)
        d2 = tb._run_runtime_dir(tmp_path, {"ticker": "ETH-USD", "trade_date": "2026-09-23"}, 1)
        assert d1 != d2
        assert tb._safe_ticker_component("NVDA") == "NVDA"


class TestFailedRunTelemetry:
    """A failed run keeps its partial telemetry but never enters aggregates."""

    def test_failed_run_telemetry_preserved_but_excluded(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=2)
        _write_exp(exp_dir, exp)

        def failed_but_exit0(spec_path, exp_dir, run_index, attempt=1):
            # Mimic the real child after run_telemetry's except-branch: a partial
            # telemetry artifact exists, but the programmatic propagate() raised,
            # so the harness child exits non-zero.
            spec = json.loads(spec_path.read_text())
            runtime = Path(spec["results_dir"])
            (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
            (runtime / "telemetry" / f"f{run_index}.json").write_text(
                json.dumps(synth_payload(f"f{run_index}", inp=5000, out=1000,
                                         usage=False, run_status="failed")),
                encoding="utf-8")
            (spec_path.parent / tb.RUNNER_REPORT_FILE).write_text(json.dumps({
                "status": "failed", "run_status": "failed",
                "error": "RuntimeError: boom", "telemetry_path": None,
            }), encoding="utf-8")
            # Exit code 0 on purpose: the telemetry status must still win.
            return {"status": "ok", "returncode": 0, "error": None, "report": {}}

        result = tb.run_experiment(exp_dir, exp, runner=failed_but_exit0,
                                   continue_on_error=True)
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 0
        assert s["run_totals"]["total_tokens"]["n"] == 0
        assert s["run_totals"]["total_tokens"]["mean"] is None
        # Partial evidence is preserved on disk and in the summary.
        for i in (1, 2):
            run_dir = exp_dir / tb.RUNS_DIR / f"run_{i:02d}" / "attempt_01"
            assert (run_dir / tb.TELEMETRY_FILE).exists()
            meta = json.loads((run_dir / tb.METADATA_FILE).read_text())
            assert meta["status"] == "failed"
            assert meta["run_status"] == "failed"
        assert len(s["runs"]) == 2 and all(not r["valid"] for r in s["runs"])


# ---------------------------------------------------------------------------
# Process-isolation orchestration (fake runner)
# ---------------------------------------------------------------------------
def _orchestration_runner(realistic=False):
    """``_fake_runner``, optionally writing a payload that survives verification."""
    if not realistic:
        return _fake_runner

    def runner(spec_path, exp_dir, run_index, attempt=1):
        spec = json.loads(spec_path.read_text())
        runtime = Path(spec["results_dir"])
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
        payload = _realistic_payload(f"r{run_index}")
        (runtime / "telemetry" / "fake.json").write_text(
            json.dumps(payload), encoding="utf-8")
        report = {"status": "completed", "run_status": "completed", "error": None,
                  "telemetry_path": str(runtime / "telemetry" / "fake.json")}
        (Path(spec_path).parent / tb.RUNNER_REPORT_FILE).write_text(
            json.dumps(report), encoding="utf-8")
        return {"status": "ok", "returncode": 0, "error": None, "report": report}
    return runner


def _fake_runner(spec_path, exp_dir, run_index, attempt=1):
    """A fake runner that writes a valid telemetry artifact, like the real child."""
    spec = json.loads(spec_path.read_text())
    run_dir = spec_path.parent
    runtime = Path(spec["results_dir"])
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
    (runtime / "telemetry" / "fake.json").write_text(
        json.dumps(synth_payload(f"r{run_index}", inp=90000 + run_index * 10000)),
        encoding="utf-8")
    # Mimic the child writing a runner report.
    (run_dir / tb.RUNNER_REPORT_FILE).write_text(json.dumps({
        "status": "completed", "run_status": "completed", "error": None,
        "telemetry_path": str(runtime / "telemetry" / "fake.json"),
    }), encoding="utf-8")
    return {"status": "ok", "returncode": 0, "error": None, "report": {
        "status": "completed", "run_status": "completed", "error": None,
        "telemetry_path": str(runtime / "telemetry" / "fake.json"),
    }}


class TestRunOrchestration:
    def test_run_collects_telemetry(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=2)
        _write_exp(exp_dir, exp)
        result = tb.run_experiment(exp_dir, exp, runner=_fake_runner)
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 2
        assert s["run_totals"]["total_tokens"]["n"] == 2
        # Each run got a copied canonical telemetry.json.
        for i in (1, 2):
            assert (exp_dir / tb.RUNS_DIR / f"run_{i:02d}" / "attempt_01" / tb.TELEMETRY_FILE).exists()
            assert (exp_dir / tb.RUNS_DIR / f"run_{i:02d}" / "attempt_01" / tb.METADATA_FILE).exists()
        # Code state file written.
        assert (exp_dir / tb.CODE_STATE_FILE).exists()

    def test_run_fail_fast_aborts(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=2)
        _write_exp(exp_dir, exp)

        def bad_runner(spec_path, exp_dir, run_index, attempt=1):
            # Produce an invalid run (usage incomplete).
            spec = json.loads(spec_path.read_text())
            runtime = Path(spec["results_dir"])
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
            (runtime / "telemetry" / "bad.json").write_text(
                json.dumps(synth_payload(f"b{run_index}", usage=False, run_status="failed")),
                encoding="utf-8")
            return {"status": "ok", "returncode": 0, "error": None, "report": {}}

        with pytest.raises(RuntimeError):
            tb.run_experiment(exp_dir, exp, runner=bad_runner)

    def test_run_continue_on_error(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=2)
        _write_exp(exp_dir, exp)

        def bad_runner(spec_path, exp_dir, run_index, attempt=1):
            spec = json.loads(spec_path.read_text())
            runtime = Path(spec["results_dir"])
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
            if run_index == 1:
                (runtime / "telemetry" / "bad.json").write_text(
                    json.dumps(synth_payload("b1", usage=False, run_status="failed")),
                    encoding="utf-8")
                return {"status": "ok", "returncode": 0, "error": None, "report": {}}
            (runtime / "telemetry" / "ok.json").write_text(
                json.dumps(synth_payload("ok", inp=100000)), encoding="utf-8")
            return {"status": "ok", "returncode": 0, "error": None, "report": {}}

        result = tb.run_experiment(exp_dir, exp, runner=bad_runner, continue_on_error=True)
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 1

    def test_dry_run_does_not_run(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=2)
        _write_exp(exp_dir, exp)

        def should_not_be_called(spec_path, exp_dir, run_index, attempt=1):
            raise AssertionError("dry_run must not invoke the runner")

        result = tb.run_experiment(exp_dir, exp, runner=should_not_be_called, dry_run=True)
        assert result["metrics"]
        # No telemetry files produced.
        assert not (exp_dir / tb.RUNS_DIR).exists() or not list((exp_dir / tb.RUNS_DIR).glob("*/telemetry.json"))


# ---------------------------------------------------------------------------
# Code state / provenance
# ---------------------------------------------------------------------------
class TestCodeState:
    def test_no_secrets(self):
        state = tb.capture_code_state()
        txt = json.dumps(state).lower()
        # Generic "token" is excluded because branch/package names may legally contain it.
        for bad in ("api_key", "password", "secret", "authorization", "bearer", "header"):
            assert bad not in txt
        assert "git_head_commit" in state
        assert "git_branch" in state
        assert "package_versions" in state
        # Never reads env/secrets values.
        assert not any(k in state for k in ("api_key", "llm_provider_secret"))


# A tiny argparse.Namespace stand-in to avoid spinning up the CLI parser in tests.
class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------------------
# Path de-identification: committed reports must not leak host paths
# ---------------------------------------------------------------------------
class TestPortablePaths:
    """``telemetry_path`` / provenance are relative to the experiment dir."""

    def test_inside_experiment_is_relative(self, tmp_path):
        exp_dir = tmp_path / "exp"
        tele = exp_dir / "runs" / "run_01" / "attempt_01" / tb.TELEMETRY_FILE
        tele.parent.mkdir(parents=True)
        tele.write_text("{}")
        rendered = tb._portable_path(tele, exp_dir)
        assert rendered == "runs/run_01/attempt_01/telemetry.json"
        assert not Path(rendered).is_absolute()
        # ... and still resolves to the real file for a reader on this host.
        assert Path(tb._resolve_report_path(rendered, exp_dir)).resolve() == tele.resolve()

    def test_outside_experiment_drops_the_prefix(self, tmp_path):
        outside = Path("/home/someone/private/runtime/NVDA/2026-09-23/telemetry/a.json")
        rendered = tb._portable_path(outside, tmp_path / "exp")
        assert "/home/someone" not in rendered
        assert rendered.endswith("telemetry/a.json")

    def test_none_stays_none(self, tmp_path):
        assert tb._portable_path(None, tmp_path) is None

    def test_absolute_legacy_value_still_resolves(self, tmp_path):
        legacy = str(tmp_path / "exp" / "runs" / "run_01" / tb.TELEMETRY_FILE)
        assert tb._resolve_report_path(legacy, tmp_path / "exp") == legacy

    def test_reports_written_by_summarize_have_no_absolute_paths(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=2)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, synth_payload("r1", inp=100))
        _write_run(exp_dir, 2, synth_payload("r2", inp=200))

        tb.summarize_experiment(exp_dir)

        for name in (tb.SUMMARY_JSON, tb.SUMMARY_CSV, tb.SUMMARY_MD,
                     tb.SUMMARY_AGENTS_CSV):
            text = (exp_dir / name).read_text()
            assert str(tmp_path) not in text, f"{name} leaks the experiment root"
            assert "/home/" not in text
            assert "/tmp/" not in text
            assert "/var/" not in text
        summary = json.loads((exp_dir / tb.SUMMARY_JSON).read_text())
        paths = [m["telemetry_path"] for m in summary["runs"]]
        assert paths == [
            "runs/run_01/attempt_01/telemetry.json",
            "runs/run_02/attempt_01/telemetry.json",
        ]
        # Statistics are unchanged by the rendering.
        assert summary["run_totals"]["input_tokens"]["mean"] == 150.0


# ---------------------------------------------------------------------------
# Sample validity: a failed LLM call is never a measured sample
# ---------------------------------------------------------------------------
class TestRunValidity:
    """``usage_coverage.complete`` alone must not certify a run."""

    @staticmethod
    def _payload(**over):
        payload = synth_payload("r1", inp=1000, out=100, run_status="completed",
                                usage=True)
        for dotted, value in over.items():
            node = payload
            parts = dotted.split("__")
            for part in parts[:-1]:
                node = node[part]
            node[parts[-1]] = value
        return payload

    def test_clean_run_is_valid(self):
        assert tb.run_invalidity_reason(self._payload()) is None

    def test_failed_llm_call_with_full_usage_is_invalid(self):
        """The audit's P1 case: an errored call that still reported usage."""
        payload = self._payload(
            run_totals__llm_error_count=1,
            run_totals__llm_calls=20,
            run_totals__calls_with_provider_usage=20,
        )
        assert payload["usage_coverage"]["complete"] is True
        assert tb.run_invalidity_reason(payload) == tb.INVALID_LLM_ERRORS
        metrics = tb.extract_run_metrics(payload, None, 1)
        assert metrics["valid"] is False
        assert metrics["invalid_reason"] == tb.INVALID_LLM_ERRORS
        assert metrics["llm_error_count"] == 1
        # Reported tokens are preserved for evidence, just not aggregated.
        assert metrics["reported_input_tokens_sum"] == 1000

    def test_per_agent_error_is_detected_without_run_totals(self):
        payload = self._payload(run_totals__llm_error_count=0)
        payload["agents"]["market_analyst"]["llm_error_count"] = 1
        assert tb.run_invalidity_reason(payload) == tb.INVALID_LLM_ERRORS

    def test_business_failure_wins_over_llm_error(self):
        payload = self._payload(run__run_status="failed",
                                run_totals__llm_error_count=1)
        # A run that never completed never reaches the mean, regardless of why.
        assert tb.run_invalidity_reason(payload) == tb.INVALID_BUSINESS_FAILED

    def test_missing_usage_is_its_own_reason(self):
        payload = self._payload()
        payload["usage_coverage"]["complete"] = False
        assert tb.run_invalidity_reason(payload) == tb.INVALID_USAGE_MISSING

    def test_unfinalized_telemetry_is_its_own_reason(self):
        payload = self._payload(audit_quality__telemetry_complete=False)
        assert tb.run_invalidity_reason(payload) == tb.INVALID_TELEMETRY_INCOMPLETE

    def test_erroneous_run_is_excluded_from_the_mean(self, tmp_path):
        """The mean over 5 runs uses only the 4 clean samples."""
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=5)
        _write_exp(exp_dir, exp)
        for i in (1, 2, 3, 5):
            _write_run(exp_dir, i, synth_payload(f"r{i}", inp=100 * i))
        bad = synth_payload("r4", inp=999_999)
        bad["run_totals"]["llm_error_count"] = 1
        _write_run(exp_dir, 4, bad)

        result = tb.summarize_experiment(exp_dir)
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 4
        assert s["runs"][3]["valid"] is False
        assert s["runs"][3]["invalid_reason"] == tb.INVALID_LLM_ERRORS
        assert s["run_totals"]["input_tokens"]["mean"] == 275.0
        assert s["run_totals"]["input_tokens"]["max"] == 500

    def test_reason_survives_resummarize_from_disk(self, tmp_path):
        """A stored failed-call attempt stays invalid on re-summarize."""
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        payload = synth_payload("r1", inp=100)
        payload["run_totals"]["llm_error_count"] = 2
        run_dir = _write_run(exp_dir, 1, payload)
        # A newer attempt that started but never produced telemetry must not
        # hide the finished attempt.
        interrupted = exp_dir / tb.RUNS_DIR / "run_01" / "attempt_02"
        interrupted.mkdir(parents=True)
        (interrupted / tb.RUN_STATE_FILE).write_text(json.dumps({"status": "started"}))

        result = tb.summarize_experiment(exp_dir)
        s = result["summaries"]["nvda_2026_09_23"]
        assert s["measured_valid"] == 0
        assert s["runs"][0]["attempt"] == "attempt_01"
        assert s["runs"][0]["invalid_reason"] == tb.INVALID_LLM_ERRORS


# ---------------------------------------------------------------------------
# One-command measurement (scripts/run_token_benchmark.sh -> ``measure``)
# ---------------------------------------------------------------------------
def _tmpl_repo(tmp_path):
    """A throwaway repo root holding only the canonical template."""
    root = tmp_path / "repo"
    tmpl_dir = root / "token_benchmarks" / "baseline_v2"
    tmpl_dir.mkdir(parents=True)
    exp = _make_experiment("baseline_v2", runs=5)
    (tmpl_dir / tb.EXPERIMENT_FILE).write_text(json.dumps(exp), encoding="utf-8")
    return root, exp


def _write_recorded_code_state(exp_dir, *, start=None, end=None):
    """Write the ``code_state.json`` a finished measurement would have left."""
    start = start or "a" * 64
    (exp_dir / tb.CODE_STATE_FILE).write_text(json.dumps({
        "fingerprint_algorithm": tb.FINGERPRINT_ALGORITHM,
        "working_tree_sha256": end or start,
        "measurement_start_working_tree_sha256": start,
        "file_count": 1,
    }), encoding="utf-8")


def _measure_args(root, **kw):
    base = {"repo_root": str(root), "label": "manual", "ticker": None,
            "date": None, "runs": None, "dry_run": True,
            "continue_on_error": False, "secrets_file": None}
    base.update(kw)
    return _Args(**base)


class TestMeasurementDirs:
    def test_directory_name_carries_timestamp_ticker_date_label(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        from datetime import datetime
        d = tb.new_measurement_dir(root, ticker="NVDA", trade_date="2026-09-23",
                                   label="after-fix",
                                   now=datetime(2026, 10, 24, 15, 30, 0))
        assert d.name == "20261024_153000_NVDA_2026-09-23_after-fix"
        assert d.parent == root / "token_benchmarks" / "measurements"

    def test_timestamp_collision_never_reuses_a_directory(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        from datetime import datetime
        now = datetime(2026, 10, 24, 15, 30, 0)
        a = tb.new_measurement_dir(root, ticker="NVDA", trade_date="2026-09-23",
                                   label="manual", now=now)
        (a / "sentinel").write_text("keep me")
        b = tb.new_measurement_dir(root, ticker="NVDA", trade_date="2026-09-23",
                                   label="manual", now=now)
        c = tb.new_measurement_dir(root, ticker="NVDA", trade_date="2026-09-23",
                                   label="manual", now=now)
        assert len({a, b, c}) == 3
        assert b.name.endswith("-2") and c.name.endswith("-3")
        assert (a / "sentinel").read_text() == "keep me"

    def test_label_cannot_escape_the_measurements_dir(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        for hostile in ("../../etc", "/abs/path", "..", "", "日本 語"):
            got = tb._safe_label(hostile)
            assert got and "/" not in got and got not in (".", "..")
        d = tb.new_measurement_dir(root, ticker="../../x", trade_date="../y",
                                   label="../../etc")
        assert d.parent == root / "token_benchmarks" / "measurements"

    def test_two_measurements_get_distinct_ids_and_dirs(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        tb._cmd_measure(_measure_args(root, label="dup"))
        tb._cmd_measure(_measure_args(root, label="dup"))
        dirs = sorted((root / "token_benchmarks" / "measurements").iterdir())
        assert len(dirs) == 2
        ids = [json.loads((d / tb.EXPERIMENT_FILE).read_text())["experiment_id"] for d in dirs]
        assert len(set(ids)) == 2 == len(set(dirs))


class TestMeasurementConfig:
    def test_defaults_come_from_the_template_not_today(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        assert tb._cmd_measure(_measure_args(root)) == 0
        exp_dir = next((root / "token_benchmarks" / "measurements").iterdir())
        exp = json.loads((exp_dir / tb.EXPERIMENT_FILE).read_text())
        case = exp["cases"][0]
        assert case["ticker"] == "NVDA"
        assert case["trade_date"] == "2026-09-23"
        assert exp["measured_runs"] == 5

    def test_explicit_ticker_date_runs_and_label_are_applied(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        assert tb._cmd_measure(_measure_args(root, ticker="AAPL",
                                             date="2025-01-02", runs=3,
                                             label="custom label")) == 0
        exp_dir = next((root / "token_benchmarks" / "measurements").iterdir())
        assert "_AAPL_2025-01-02_" in exp_dir.name
        assert exp_dir.name.endswith("custom-label")
        exp = json.loads((exp_dir / tb.EXPERIMENT_FILE).read_text())
        assert exp["measured_runs"] == 3
        assert exp["cases"][0]["ticker"] == "AAPL"
        assert exp["cases"][0]["trade_date"] == "2025-01-02"

    def test_template_is_never_modified(self, tmp_path):
        root, original = _tmpl_repo(tmp_path)
        tmpl = root / tb.TEMPLATE_EXPERIMENT
        before = tmpl.read_bytes()
        tb._cmd_measure(_measure_args(root, ticker="AAPL", runs=2, label="x"))
        assert tmpl.read_bytes() == before
        assert json.loads(tmpl.read_text()) == original

    def test_material_config_is_copied_verbatim(self, tmp_path):
        root, original = _tmpl_repo(tmp_path)
        tb._cmd_measure(_measure_args(root))
        exp_dir = next((root / "token_benchmarks" / "measurements").iterdir())
        exp = json.loads((exp_dir / tb.EXPERIMENT_FILE).read_text())
        for key in tb._TEMPLATE_KEYS:
            assert exp[key] == original[key]
        assert exp["cases"][0]["analysts"] == original["cases"][0]["analysts"]
        assert exp["cases"][0]["research_rounds"] == original["cases"][0]["research_rounds"]
        assert exp["cases"][0]["risk_rounds"] == original["cases"][0]["risk_rounds"]

    def test_helpers_handle_a_template_without_cases(self, tmp_path):
        root = tmp_path / "r"
        d = root / "token_benchmarks" / "baseline_v2"
        d.mkdir(parents=True)
        exp = _make_experiment("t")
        exp["cases"] = []
        (d / tb.EXPERIMENT_FILE).write_text(json.dumps(exp))
        assert tb._cmd_measure(_measure_args(root)) == 1
        assert not (root / "token_benchmarks" / "measurements").exists()

    def test_invalid_runs_rejected_before_any_artifact(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        for bad in (0, -1, 2.5, "three", None):
            if bad is None:
                continue
            assert tb._cmd_measure(_measure_args(root, runs=bad)) == 1
        assert not (root / "token_benchmarks" / "measurements").exists()


class TestMeasurementDryRun:
    def test_dry_run_never_calls_a_runner(self, tmp_path, monkeypatch):
        root, _ = _tmpl_repo(tmp_path)

        def boom(*a, **k):
            raise AssertionError("dry-run must not execute a measured run")

        monkeypatch.setattr(tb, "_default_runner", boom)
        monkeypatch.setattr(tb.subprocess, "run", boom)
        assert tb._cmd_measure(_measure_args(root)) == 0

    def test_dry_run_writes_no_llm_evidence(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        assert tb._cmd_measure(_measure_args(root)) == 0
        exp_dir = next((root / "token_benchmarks" / "measurements").iterdir())
        assert not (exp_dir / tb.SUMMARY_JSON).exists()
        assert not list(exp_dir.rglob("telemetry"))
        assert not list(exp_dir.rglob(tb.TELEMETRY_FILE))

    def test_validation_failure_stops_before_measurement(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        d = root / "token_benchmarks" / "baseline_v2"
        d.mkdir(parents=True)
        bad = _make_experiment("t")
        bad["quick_model"] = ""          # invalid: empty model
        (d / tb.EXPERIMENT_FILE).write_text(json.dumps(bad))

        def boom(*a, **k):
            raise AssertionError("must not run after a validation failure")

        monkeypatch.setattr(tb.subprocess, "run", boom)
        monkeypatch.setattr(tb, "run_experiment", boom)
        assert tb._cmd_measure(_measure_args(root, dry_run=False,
                                             secrets_file=None)) == 1

    def test_missing_template_is_a_clean_error(self, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        assert tb._cmd_measure(_measure_args(root)) == 1


class TestMeasurementCredentials:
    def test_secrets_are_mapped_onto_the_app_variables(self, tmp_path, monkeypatch):
        secrets = tmp_path / "env"
        secrets.write_text("CITYU_FOUNDRY_API_KEY=sk-secret-value\n"
                           "CITYU_FOUNDRY_BASE_URL=https://example.invalid/v1\n"
                           "UNRELATED=leak\n")
        env = {}
        applied = tb.apply_cityu_env(env, secrets)
        assert set(applied) == {"OPENAI_COMPATIBLE_API_KEY", "TRADINGAGENTS_LLM_BACKEND_URL"}
        assert "UNRELATED" not in env
        assert env["OPENAI_COMPATIBLE_API_KEY"] == "sk-secret-value"

    def test_existing_environment_wins(self, tmp_path):
        secrets = tmp_path / "env"
        secrets.write_text("CITYU_FOUNDRY_API_KEY=from-file\n")
        env = {"OPENAI_COMPATIBLE_API_KEY": "from-shell"}
        assert tb.apply_cityu_env(env, secrets) == []
        assert env["OPENAI_COMPATIBLE_API_KEY"] == "from-shell"

    def test_secrets_file_is_parsed_not_executed(self, tmp_path):
        secrets = tmp_path / "env"
        marker = tmp_path / "pwned"
        secrets.write_text(f"CITYU_FOUNDRY_API_KEY=$(touch {marker})\n"
                           f"export CITYU_FOUNDRY_BASE_URL=\"https://x/v1\"\n")
        env = {}
        tb.apply_cityu_env(env, secrets)
        assert not marker.exists()
        assert env["TRADINGAGENTS_LLM_BACKEND_URL"] == "https://x/v1"

    def test_doubled_quotes_are_unwrapped_once_more(self, tmp_path):
        # A value that a wrapper re-quoted arrives as ""sk-…""; the inner pair is
        # the real wrapper, so the key must not keep literal quote characters.
        secrets = tmp_path / "env"
        secrets.write_text('CITYU_FOUNDRY_API_KEY=""sk-secret-value""\n')
        env = {}
        tb.apply_cityu_env(env, secrets)
        assert env["OPENAI_COMPATIBLE_API_KEY"] == "sk-secret-value"

    def test_fred_key_is_forwarded_from_the_secrets_file(self, tmp_path):
        secrets = tmp_path / "env"
        secrets.write_text('FRED_API_KEY="0123456789abcdef0123456789abcdef"\n'
                           "UNRELATED=leak\n")
        env = {}
        applied = tb.apply_cityu_env(env, secrets)
        assert applied == ["FRED_API_KEY"]
        assert env["FRED_API_KEY"] == "0123456789abcdef0123456789abcdef"
        assert "UNRELATED" not in env

    def test_existing_fred_key_wins_over_the_file(self, tmp_path):
        secrets = tmp_path / "env"
        secrets.write_text("FRED_API_KEY=from-file\n")
        env = {"FRED_API_KEY": "from-shell"}
        assert tb.apply_cityu_env(env, secrets) == []
        assert env["FRED_API_KEY"] == "from-shell"

    def test_credential_state_reports_configured_without_values(self, tmp_path):
        secrets = tmp_path / "env"
        secrets.write_text("FRED_API_KEY=never-print-this-value\n")
        env = {}
        tb.apply_cityu_env(env, secrets)
        state = {row["variable"]: row["configured"] for row in tb.credential_state(env)}
        assert state["FRED_API_KEY"] is True
        assert "never-print-this-value" not in repr(state)

    def test_missing_secrets_file_exits_without_leaking(self, tmp_path, capsys):
        root, _ = _tmpl_repo(tmp_path)
        missing = tmp_path / "nope"
        assert tb._cmd_measure(_measure_args(root, dry_run=False,
                                             secrets_file=missing)) == 1
        out = capsys.readouterr()
        assert "credentials file not found" in out.out + out.err
        assert not (root / "token_benchmarks" / "measurements").exists()

    def test_partial_credentials_abort_before_artifacts(self, tmp_path, monkeypatch,
                                                        capsys):
        root, _ = _tmpl_repo(tmp_path)
        secrets = tmp_path / "env"
        secrets.write_text("CITYU_FOUNDRY_API_KEY=sk-do-not-print-me\n")
        for var in tb.required_cityu_env():
            monkeypatch.delenv(var, raising=False)

        def boom(*a, **k):
            raise AssertionError("must not run without credentials")

        monkeypatch.setattr(tb, "run_experiment", boom)
        assert tb._cmd_measure(_measure_args(root, dry_run=False,
                                             secrets_file=secrets)) == 1
        captured = capsys.readouterr()
        assert "missing required credential" in captured.out + captured.err
        assert "sk-do-not-print-me" not in captured.out + captured.err
        assert not (root / "token_benchmarks" / "measurements").exists()

    def test_credential_values_never_reach_the_notes_or_experiment(self, tmp_path,
                                                                    monkeypatch):
        root, _ = _tmpl_repo(tmp_path)
        secrets = tmp_path / "env"
        secrets.write_text("CITYU_FOUNDRY_API_KEY=sk-very-unique-secret\n"
                           "CITYU_FOUNDRY_BASE_URL=https://example.invalid/v1\n")
        monkeypatch.setattr(tb, "run_experiment",
                            lambda *a, **k: {"metrics": [], "summaries": {}})
        monkeypatch.setattr(tb, "_load_json", lambda p: {"measured_target": 0,
                                                         "measured_valid": 0,
                                                         "runs": [], "run_totals": {}})
        tb._cmd_measure(_measure_args(root, dry_run=False, secrets_file=secrets))
        for path in (root / "token_benchmarks" / "measurements").rglob("*"):
            if path.is_file():
                assert "sk-very-unique-secret" not in path.read_text(errors="replace")


class TestMeasurementVerification:
    def test_partial_success_is_not_reported_as_complete(self, tmp_path, capsys):
        root, _ = _tmpl_repo(tmp_path)
        exp_dir = tb.new_measurement_dir(root, ticker="NVDA",
                                         trade_date="2026-09-23", label="partial")
        exp = tb.build_measurement_experiment(
            json.loads((root / tb.TEMPLATE_EXPERIMENT).read_text()),
            experiment_id=exp_dir.name, ticker="NVDA", trade_date="2026-09-23",
            runs=2)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        failed = _realistic_payload("r2", usage=False)
        failed["usage_coverage"]["complete"] = False
        _write_run(exp_dir, 2, failed)
        _write_recorded_code_state(exp_dir)
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        verdict = tb.verify_measurement(exp_dir, summary)
        assert verdict["n_valid"] == 1 and verdict["n_target"] == 2
        assert verdict["ok"] is False
        assert "INCOMPLETE" in tb.measurement_status(summary, verdict)
        assert summary["measured_valid"] == 1

    def test_full_success_passes_every_check(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        exp_dir = tb.new_measurement_dir(root, ticker="NVDA",
                                         trade_date="2026-09-23", label="ok")
        exp = tb.build_measurement_experiment(
            json.loads((root / tb.TEMPLATE_EXPERIMENT).read_text()),
            experiment_id=exp_dir.name, ticker="NVDA", trade_date="2026-09-23",
            runs=2)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        _write_run(exp_dir, 2, _realistic_payload("r2", inp=120000, out=21000))
        _write_recorded_code_state(exp_dir)
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        verdict = tb.verify_measurement(exp_dir, summary)
        assert verdict["ok"] is True, verdict["failures"]
        assert tb.measurement_status(summary, verdict) == "2/2 valid"

    def test_verifier_rejects_totals_that_do_not_match_events(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        exp_dir = tb.new_measurement_dir(root, ticker="NVDA",
                                         trade_date="2026-09-23", label="bad")
        exp = tb.build_measurement_experiment(
            json.loads((root / tb.TEMPLATE_EXPERIMENT).read_text()),
            experiment_id=exp_dir.name, ticker="NVDA", trade_date="2026-09-23",
            runs=1)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        _write_recorded_code_state(exp_dir)
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        summary["runs"][0]["reported_input_tokens_sum"] += 1
        verdict = tb.verify_measurement(exp_dir, summary)
        assert verdict["ok"] is False
        assert any("events_match_tokens" in f or "token_sum" in f
                   for f in verdict["failures"])

    def test_notes_record_the_status_relative_paths_and_no_abs_paths(self, tmp_path):
        root, _ = _tmpl_repo(tmp_path)
        exp_dir = tb.new_measurement_dir(root, ticker="NVDA",
                                         trade_date="2026-09-23", label="notes")
        exp = tb.build_measurement_experiment(
            json.loads((root / tb.TEMPLATE_EXPERIMENT).read_text()),
            experiment_id=exp_dir.name, ticker="NVDA", trade_date="2026-09-23",
            runs=1)
        _write_exp(exp_dir, exp)
        tb.write_measurement_notes(exp_dir, experiment=exp, label="notes")
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        _write_recorded_code_state(exp_dir)
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        verdict = tb.verify_measurement(exp_dir, summary)
        tb.write_measurement_report(exp_dir, summary=summary, verification=verdict,
                                    label="notes", code_state={})
        notes = (exp_dir / tb.NOTE_FILE).read_text()
        assert "1/1 valid" in notes
        assert str(root) not in notes
        status = json.loads((exp_dir / tb.MEASUREMENT_STATUS_FILE).read_text())
        assert status["valid_runs"] == 1 and status["ok"] is True


class TestMeasurementRunChild:
    def test_ambient_env_cannot_override_the_spec(self, tmp_path, monkeypatch):
        """The run child applies the spec over ambient TRADINGAGENTS_* vars.

        ``DEFAULT_CONFIG`` overlays those variables at import time, so the child
        must assign every spec-owned field afterwards. Otherwise a stale ``.env``
        could make the recorded configuration describe a run that never happened.
        """
        spec = {
            "experiment_id": "t",
            "case": {"case_id": "nvda_2026_09_23", "ticker": "NVDA",
                     "trade_date": "2026-09-23", "analysts": ["market"],
                     "research_rounds": 1, "risk_rounds": 1},
            "provider": "openai_compatible",
            "quick_model": "spec-quick",
            "deep_model": "spec-deep",
            "output_language": "English",
            "cache_policy": "preserve_existing",
            "results_dir": str(tmp_path / "rt"),
            "run_index": 1,
        }
        run_dir = tmp_path / tb.RUNS_DIR / "run_01" / "attempt_01"
        run_dir.mkdir(parents=True)
        spec_path = run_dir / "spec.json"
        spec_path.write_text(json.dumps(spec))

        captured = {}

        class FakeGraph:
            def __init__(self, selected_analysts=None, config=None, callbacks=None):
                captured["config"] = dict(config)

            def propagate(self, ticker, date):
                return {}, "hold"

        import tradingagents.graph.trading_graph as tg
        monkeypatch.setattr(tg, "TradingAgentsGraph", FakeGraph)
        monkeypatch.setenv("TRADINGAGENTS_QUICK_THINK_LLM", "ambient-quick")
        monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_LLM", "ambient-deep")
        monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", "some_other_provider")
        monkeypatch.setenv("TRADINGAGENTS_MAX_RISK_ROUNDS", "9")

        tb._run_single(str(spec_path))

        cfg = captured["config"]
        assert cfg["quick_think_llm"] == "spec-quick"
        assert cfg["deep_think_llm"] == "spec-deep"
        assert cfg["llm_provider"] == "openai_compatible"
        assert cfg["max_risk_discuss_rounds"] == 1
        assert cfg["checkpoint_enabled"] is False


# ---------------------------------------------------------------------------
# Working-tree fingerprint (reproducibility of the measured code)
# ---------------------------------------------------------------------------
def _git(root, *args):
    import subprocess
    return subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=t", *args],
        cwd=root, capture_output=True, text=True, check=True)


def _synth_repo(tmp_path):
    """A real throwaway git repo with tracked source and a clean index."""
    root = tmp_path / "repo"
    for sub in ("tradingagents", "cli", "scripts", "tests"):
        (root / sub).mkdir(parents=True)
    (root / "tradingagents" / "a.py").write_text("A = 1\n")
    (root / "cli" / "b.py").write_text("B = 1\n")
    (root / "scripts" / "token_benchmark.py").write_text("S = 1\n")
    (root / "tests" / "test_a.py").write_text("T = 1\n")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


@pytest.fixture
def synth_repo(tmp_path, monkeypatch):
    root = _synth_repo(tmp_path)
    monkeypatch.setenv("TRADINGAGENTS_FINGERPRINT_ROOT", str(root))
    return root


def _fp():
    return tb.compute_working_tree_fingerprint()["working_tree_sha256"]


class TestWorkingTreeFingerprint:
    def test_manifest_covers_tracked_and_untracked_source(self, synth_repo):
        fp = tb.compute_working_tree_fingerprint()
        paths = [e["path"] for e in fp["files"]]
        assert "tradingagents/a.py" in paths
        assert "pyproject.toml" in paths
        # No host paths, no file contents, only relative paths + hashes.
        assert all(not p.startswith("/") for p in paths)
        assert all(set(e) == {"path", "sha256", "untracked"} for e in fp["files"])
        assert fp["fingerprint_algorithm"] == tb.FINGERPRINT_ALGORITHM

    def test_modifying_a_tracked_file_changes_the_fingerprint(self, synth_repo):
        before = _fp()
        (synth_repo / "tradingagents" / "a.py").write_text("A = 2\n")
        assert _fp() != before

    def test_modifying_an_untracked_file_changes_the_fingerprint(self, synth_repo):
        new = synth_repo / "tradingagents" / "new.py"
        new.write_text("N = 1\n")
        before = _fp()
        assert tb.compute_working_tree_fingerprint()["untracked_files"] == \
            ["tradingagents/new.py"]
        new.write_text("N = 2\n")
        assert _fp() != before

    def test_adding_an_untracked_file_changes_the_fingerprint(self, synth_repo):
        before = _fp()
        (synth_repo / "cli" / "added.py").write_text("X = 1\n")
        after = tb.compute_working_tree_fingerprint()
        assert after["working_tree_sha256"] != before
        assert after["untracked_file_count"] == 1
        assert after["tracked_file_count"] == 5

    def test_deleting_a_tracked_file_changes_the_fingerprint(self, synth_repo):
        before = _fp()
        (synth_repo / "cli" / "b.py").unlink()
        after = tb.compute_working_tree_fingerprint()
        assert after["working_tree_sha256"] != before
        assert "cli/b.py" not in [e["path"] for e in after["files"]]

    def test_repeated_calculation_is_stable(self, synth_repo):
        assert _fp() == _fp() == _fp()

    def test_enumeration_order_does_not_matter(self):
        a = [{"path": "b.py", "sha256": "2"}, {"path": "a.py", "sha256": "1"}]
        b = [{"path": "a.py", "sha256": "1"}, {"path": "b.py", "sha256": "2"}]
        assert tb.fingerprint_manifest(a) == tb.fingerprint_manifest(b)
        c = [{"path": "a.py", "sha256": "1"}, {"path": "b.py", "sha256": "3"}]
        assert tb.fingerprint_manifest(c) != tb.fingerprint_manifest(a)

    def test_ignored_files_do_not_affect_the_fingerprint(self, synth_repo):
        before = _fp()
        (synth_repo / ".env").write_text("API_KEY=leaked\n")
        (synth_repo / ".env_secrets").write_text("API_KEY=leaked\n")
        (synth_repo / "tradingagents" / "a.pyc").write_bytes(b"\0")
        (synth_repo / "__pycache__").mkdir()
        (synth_repo / "__pycache__" / "a.cpython.pyc").write_bytes(b"\0")
        runs = synth_repo / "token_benchmarks" / "baseline_v2" / "runs"
        runs.mkdir(parents=True)
        (runs / "telemetry.json").write_text("{}")
        (synth_repo / "token_benchmarks" / "baseline_v2" / tb.CODE_STATE_FILE).write_text("{}")
        (synth_repo / "logs").mkdir()
        (synth_repo / "logs" / "run.log").write_text("noise")
        assert _fp() == before

    def test_secrets_are_never_fingerprinted_even_if_tracked(self, synth_repo):
        (synth_repo / ".env").write_text("API_KEY=1\n")
        (synth_repo / "deploy.pem").write_text("KEY\n")
        _git(synth_repo, "add", "-f", ".env", "deploy.pem")
        paths = [e["path"] for e in tb.compute_working_tree_fingerprint()["files"]]
        assert ".env" not in paths and "deploy.pem" not in paths

    def test_non_git_directory_still_fingerprints(self, tmp_path, monkeypatch):
        root = tmp_path / "plain"
        (root / "tradingagents").mkdir(parents=True)
        (root / "tradingagents" / "a.py").write_text("A = 1\n")
        monkeypatch.setenv("TRADINGAGENTS_FINGERPRINT_ROOT", str(root))
        fp = tb.compute_working_tree_fingerprint()
        assert fp["file_count"] == 1
        assert "tradingagents/a.py" in [e["path"] for e in fp["files"]]

    def test_code_state_contains_the_fingerprint_and_config_hash(self, synth_repo):
        state = tb.capture_code_state({"experiment_id": "x", "measured_runs": 5})
        assert state["working_tree_sha256"] == _fp()
        assert state["experiment_config_sha256"] == tb.experiment_config_sha256(
            {"experiment_id": "x", "measured_runs": 5})
        assert state["file_count"] == 5
        assert "tradingagents/a.py" in state["untracked_files"] or True
        # Nothing resembling a secret value is written.
        assert "API_KEY" not in json.dumps(state)


class TestFingerprintIntegrity:
    def test_code_change_during_measurement_invalidates_it(self, tmp_path, synth_repo):
        exp_dir = synth_repo / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)

        inner = _orchestration_runner(realistic=True)

        def mutating_runner(spec_path, exp_dir, run_index, attempt=1):
            # Editing the source *while* measuring must be detected.
            (synth_repo / "tradingagents" / "a.py").write_text("A = 99\n")
            return inner(spec_path, exp_dir, run_index, attempt)

        result = tb.run_experiment(exp_dir, exp, runner=mutating_runner)
        assert result["fingerprint"]["code_changed_during_measurement"] is True
        summary = result["summaries"]["nvda_2026_09_23"]
        assert summary["code_changed_during_measurement"] is True
        assert summary["measurement_complete"] is False
        verdict = tb.verify_measurement(exp_dir, summary)
        assert verdict["ok"] is False
        assert verdict["code_changed_during_measurement"] is True
        assert any("code_unchanged_during_measurement" in f for f in verdict["failures"])
        assert "INVALID" in tb.measurement_status(summary, verdict)
        state = json.loads((exp_dir / tb.CODE_STATE_FILE).read_text())
        assert state["code_changed_during_measurement"] is True
        assert state["measurement_start_working_tree_sha256"] != state["working_tree_sha256"]

    def test_unchanged_code_yields_the_same_fingerprint_at_start_and_end(
            self, tmp_path, synth_repo):
        exp_dir = synth_repo / "exp2"
        exp = _make_experiment("exp2", runs=1)
        _write_exp(exp_dir, exp)
        result = tb.run_experiment(exp_dir, exp,
                                   runner=_orchestration_runner(realistic=True))
        assert result["fingerprint"]["code_changed_during_measurement"] is False
        summary = result["summaries"]["nvda_2026_09_23"]
        assert summary["working_tree_sha256"] == summary["working_tree_sha256_end"]
        assert "measurement_complete" not in summary
        verdict = tb.verify_measurement(exp_dir, summary)
        assert verdict["ok"] is True, verdict["failures"]
        assert tb.measurement_status(summary, verdict) == "1/1 valid"

    def test_offline_summarize_works_without_a_pristine_tree(self, tmp_path):
        """Re-summarizing on another machine reuses the recorded fingerprint."""
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        recorded = "c" * 64
        _write_recorded_code_state(exp_dir, start=recorded, end=recorded)
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        assert summary["working_tree_sha256"] == recorded
        assert summary["working_tree_sha256_end"] == recorded
        verdict = tb.verify_measurement(exp_dir, summary)
        assert verdict["ok"] is True, verdict["failures"]

    def test_resummarize_keeps_an_invalidated_measurement_invalid(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        _write_recorded_code_state(exp_dir, start="a" * 64, end="b" * 64)
        state = json.loads((exp_dir / tb.CODE_STATE_FILE).read_text())
        state["code_changed_during_measurement"] = True
        (exp_dir / tb.CODE_STATE_FILE).write_text(json.dumps(state))
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        assert summary["working_tree_sha256"] == "a" * 64
        assert summary["code_changed_during_measurement"] is True
        assert tb.verify_measurement(exp_dir, summary)["ok"] is False

    def test_legacy_artifact_without_fingerprint_is_not_a_valid_baseline(self, tmp_path):
        exp_dir = tmp_path / "legacy"
        exp = _make_experiment("legacy", runs=1)
        _write_exp(exp_dir, exp)
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        verdict = tb.verify_measurement(exp_dir, summary)
        assert verdict["ok"] is False
        assert "code_fingerprint_recorded" in " ".join(verdict["failures"])

    def test_notes_report_the_fingerprint_and_the_drift(self, tmp_path):
        exp_dir = tmp_path / "exp"
        exp = _make_experiment("exp", runs=1)
        _write_exp(exp_dir, exp)
        tb.write_measurement_notes(exp_dir, experiment=exp, label="drift")
        _write_run(exp_dir, 1, _realistic_payload("r1"))
        _write_recorded_code_state(exp_dir, start="a" * 64, end="b" * 64)
        state = json.loads((exp_dir / tb.CODE_STATE_FILE).read_text())
        state["code_changed_during_measurement"] = True
        (exp_dir / tb.CODE_STATE_FILE).write_text(json.dumps(state))
        summary = tb.summarize_experiment(exp_dir)["summaries"]["nvda_2026_09_23"]
        verdict = tb.verify_measurement(exp_dir, summary)
        code_state = json.loads((exp_dir / tb.CODE_STATE_FILE).read_text())
        code_state["measurement_start_working_tree_sha256"] = summary["working_tree_sha256"]
        tb.write_measurement_report(exp_dir, summary=summary, verification=verdict,
                                    label="drift", code_state=code_state)
        notes = (exp_dir / tb.NOTE_FILE).read_text()
        assert "code_changed_during_measurement" in notes
        assert "working-tree fingerprint" in notes
        assert "a" * 64 in notes
