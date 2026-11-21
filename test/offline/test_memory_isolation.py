"""Per-run memory isolation (V3) — real harness functions, real memory parser.

A run must start from the immutable snapshot and write only to its own copy, so
one run can never change the next run's pending entries, reflector calls or
token cost. These tests drive the harness functions and the product's own
``TradingMemoryLog``; no network or paid call is involved.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))
import token_benchmark as tb  # noqa: E402

BATCH = REPO_ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3"
BASELINE = BATCH / "memory/baseline_v3.md"
SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"


def _registration(run_id: str = "R01") -> tuple[Path, dict]:
    directory = BATCH / "specs" / run_id
    return directory, json.loads((directory / "experiment.json").read_text(encoding="utf-8"))


def _copy_batch(tmp_path: Path) -> Path:
    """A throwaway batch root so a test never writes into the certified tree."""
    target = tmp_path / "batch"
    (target / "specs").mkdir(parents=True)
    shutil.copytree(BATCH / "memory", target / "memory")
    for source in (BATCH / "specs").iterdir():
        if source.is_dir():
            shutil.copytree(source, target / "specs" / source.name)
    # Every batch-level file (experiment, SWITCH_MATRIX, manifests, protocol)
    # so the copy is a complete registration root for the path checks.
    for source in BATCH.iterdir():
        if source.is_file():
            shutil.copy2(source, target / source.name)
    return target


def _pending_entry(ticker="NVDA", date="2026-09-23", rating="Hold") -> str:
    return (f"[{date} | {ticker} | {rating} | pending]\n\nDECISION:\nRating: {rating}"
            + SEPARATOR)


def _prepared_spec(tmp_path, run_id="R01_NVDA_C0"):
    """A prepared spec in a throwaway batch root."""
    batch = _copy_batch(tmp_path)
    directory = batch / "specs" / run_id
    registration = json.loads((directory / "experiment.json").read_text())
    spec_path = tb.prepare_run_spec(directory, registration,
                                    registration["cases"][0], 1, 1)
    return batch, spec_path, json.loads(spec_path.read_text())


class TestSnapshotAndCopy:
    def test_every_run_gets_its_own_copy_of_the_same_snapshot(self, tmp_path):
        batch = _copy_batch(tmp_path)
        experiment_dir = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((experiment_dir / "experiment.json").read_text())
        first = tb.prepare_run_spec(experiment_dir, registration,
                                    registration["cases"][0], 1, 1)
        second_dir = batch / "specs" / "R02_NVDA_AB"
        second_registration = json.loads((second_dir / "experiment.json").read_text())
        second = tb.prepare_run_spec(second_dir, second_registration,
                                     second_registration["cases"][0], 1, 1)

        first_spec = json.loads(first.read_text())
        second_spec = json.loads(second.read_text())
        baseline_sha = tb._sha256_file(batch / "memory/baseline_v3.md")
        assert first_spec["memory"]["baseline_sha256"] == baseline_sha
        assert second_spec["memory"]["baseline_sha256"] == baseline_sha
        assert first_spec["memory"]["run_memory_path"] != second_spec["memory"]["run_memory_path"]
        assert first_spec["memory"]["run_initial_sha256"] == baseline_sha
        assert second_spec["memory"]["run_initial_sha256"] == baseline_sha
        assert first_spec["memory"]["pending_before"] == 0
        assert second_spec["memory"]["pending_before"] == 0

    def test_a_write_to_one_run_copy_leaves_the_others_untouched(self, tmp_path):
        batch = _copy_batch(tmp_path)
        experiment_dir = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((experiment_dir / "experiment.json").read_text())
        spec_path = tb.prepare_run_spec(experiment_dir, registration,
                                        registration["cases"][0], 1, 1)
        spec = json.loads(spec_path.read_text())
        baseline_before = tb._sha256_file(batch / "memory/baseline_v3.md")

        with Path(spec["memory"]["run_memory_path"]).open("a", encoding="utf-8") as handle:
            handle.write(_pending_entry("AAPL", "2026-09-23"))
        state = tb.memory_state_after_run(spec)
        assert state["run_changed"] is True
        assert state["pending_after"] == 1
        assert state["baseline_unchanged"] is True
        assert tb._sha256_file(batch / "memory/baseline_v3.md") == baseline_before

        # A second run built afterwards still starts clean.
        other = batch / "specs" / "R02_NVDA_AB"
        other_reg = json.loads((other / "experiment.json").read_text())
        other_spec = json.loads(tb.prepare_run_spec(other, other_reg,
                                                   other_reg["cases"][0], 1, 1).read_text())
        assert other_spec["memory"]["pending_before"] == 0
        assert other_spec["memory"]["run_initial_sha256"] == baseline_before

    def test_run_order_does_not_change_any_run_initial_state(self, tmp_path):
        batch = _copy_batch(tmp_path)
        shas = []
        for run_id, order in (("R01_NVDA_C0", 1), ("R02_NVDA_AB", 2)):
            directory = batch / "specs" / run_id
            registration = json.loads((directory / "experiment.json").read_text())
            spec = json.loads(tb.prepare_run_spec(
                directory, registration, registration["cases"][0], 1,
                order).read_text())
            shas.append(spec["memory"]["run_initial_sha256"])
            # Dirty this run's copy before building the next one.
            with Path(spec["memory"]["run_memory_path"]).open("a", encoding="utf-8") as handle:
                handle.write(_pending_entry())
        assert len(set(shas)) == 1
        assert shas[0] == tb._sha256_file(batch / "memory/baseline_v3.md")


class TestValidationFailsClosed:
    @staticmethod
    def _spec(tmp_path):
        return _prepared_spec(tmp_path)

    def test_a_missing_snapshot_is_refused(self, tmp_path):
        batch, spec_path, spec = self._spec(tmp_path)
        (batch / "memory/baseline_v3.md").unlink()
        with pytest.raises(tb.RunRefused, match="snapshot is missing"):
            tb.validate_memory_spec(spec, attempt_dir=spec_path.parent)

    def test_a_changed_snapshot_is_refused(self, tmp_path):
        batch, spec_path, spec = self._spec(tmp_path)
        with (batch / "memory/baseline_v3.md").open("a", encoding="utf-8") as handle:
            handle.write("\ntampered\n")
        with pytest.raises(tb.RunRefused, match="snapshot changed"):
            tb.validate_memory_spec(spec, attempt_dir=spec_path.parent)

    def test_a_modified_run_copy_before_the_graph_is_refused(self, tmp_path):
        _batch, spec_path, spec = self._spec(tmp_path)
        with Path(spec["memory"]["run_memory_path"]).open("a", encoding="utf-8") as handle:
            handle.write("x")
        with pytest.raises(tb.RunRefused, match="modified before the graph|not initialised"):
            tb.validate_memory_spec(spec, attempt_dir=spec_path.parent)

    def test_the_snapshot_cannot_be_the_run_copy(self, tmp_path):
        batch, spec_path, spec = self._spec(tmp_path)
        spec["memory"]["run_memory_path"] = str(batch / "memory/baseline_v3.md")
        with pytest.raises(tb.RunRefused, match="shared snapshot"):
            tb.validate_memory_spec(spec, attempt_dir=spec_path.parent)

    def test_a_copy_outside_the_attempt_directory_is_refused(self, tmp_path):
        _batch, spec_path, spec = self._spec(tmp_path)
        other = tmp_path / "elsewhere"
        other.mkdir()
        copy = other / "trading_memory.md"
        shutil.copy2(spec["memory"]["run_memory_path"], copy)
        spec["memory"]["run_memory_path"] = str(copy)
        with pytest.raises(tb.RunRefused, match="outside its attempt directory"):
            tb.validate_memory_spec(spec, attempt_dir=spec_path.parent)

    def test_a_v3_registration_without_a_memory_block_is_refused(self, tmp_path, monkeypatch):
        """A V3 registration that declares no isolation is refused, even if it
        self-hashes consistently (the snapshot contract is not optional)."""
        batch = _copy_batch(tmp_path)
        # Make the throwaway batch the active one for this test, so the path
        # checks target it rather than the certified tree.
        monkeypatch.setenv("TRADINGAGENTS_C3_BATCH", str(batch))
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())
        registration.pop("memory")
        registration["config_sha256"] = tb.registration_sha256(registration)
        (directory / "experiment.json").write_text(json.dumps(registration))
        spec = tb.build_run_spec(directory, registration, registration["cases"][0], 1, 1)
        assert "memory" not in spec
        spec_path = directory / "runs" / "run_01" / "attempt_01" / "spec.json"
        spec_path.parent.mkdir(parents=True)
        spec_path.write_text(json.dumps(spec))
        spec["_spec_path"] = str(spec_path)
        with pytest.raises(tb.RunRefused, match="no memory isolation block|missing required field"):
            tb._preflight_gate(spec)

    def test_a_registration_with_a_wrong_snapshot_hash_is_refused(self, tmp_path):
        batch = _copy_batch(tmp_path)
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())
        registration["memory"]["baseline_sha256"] = "0" * 64
        with pytest.raises(tb.RunRefused, match="snapshot changed"):
            tb.memory_block_for_registration(directory, registration)

    def test_a_registration_without_the_isolation_mode_is_refused(self, tmp_path):
        batch = _copy_batch(tmp_path)
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())
        registration["memory"] = {"baseline_relpath": "memory/baseline_v3.md"}
        with pytest.raises(tb.RunRefused, match="mode"):
            tb.memory_block_for_registration(directory, registration)


class TestConfigAndReflector:
    def test_the_graph_reads_and_writes_the_run_copy(self, tmp_path):
        _batch, spec_path, spec = _prepared_spec(tmp_path)
        config, _applied = tb._config_for_spec(spec)
        assert config["memory_log_path"] == spec["memory"]["run_memory_path"]
        assert config["memory_log_path"] != str(BASELINE)

    def test_a_pending_entry_in_one_run_copy_does_not_trigger_the_next_runs_reflector(self, tmp_path):
        """Order independence, proved through the product's own resolver."""
        from tradingagents.agents.utils.memory import TradingMemoryLog
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        batch = _copy_batch(tmp_path)
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())
        spec = json.loads(tb.prepare_run_spec(directory, registration,
                                             registration["cases"][0], 1, 1).read_text())

        class _Reflector:
            def __init__(self):
                self.calls = 0

            def reflect_on_final_decision(self, **kwargs):
                self.calls += 1
                return "reflection"

        graph = object.__new__(TradingAgentsGraph)
        graph.config = {"memory_log_path": spec["memory"]["run_memory_path"],
                        "holding_period_days": 5}
        graph.memory_log = TradingMemoryLog(graph.config)
        graph.reflector = _Reflector()
        graph._resolve_benchmark = lambda ticker: "SPY"
        graph._fetch_returns = lambda *a, **k: (0.01, 0.0, 5, "2026-09-30")

        # Run A leaves a pending entry in its own copy.
        graph.memory_log.store_decision("AAPL", "2026-09-23", "Rating: Hold")
        graph._resolve_pending_entries("AAPL")
        assert graph.reflector.calls == 1  # its own pending entry is resolved

        # Run B starts from the snapshot: no pending entry, no reflector call.
        other_dir = batch / "specs" / "R02_NVDA_AB"
        other_reg = json.loads((other_dir / "experiment.json").read_text())
        other_spec = json.loads(tb.prepare_run_spec(
            other_dir, other_reg, other_reg["cases"][0], 1, 1).read_text())
        graph.config = {"memory_log_path": other_spec["memory"]["run_memory_path"],
                        "holding_period_days": 5}
        graph.memory_log = TradingMemoryLog(graph.config)
        graph.reflector = _Reflector()
        graph._resolve_pending_entries("AAPL")
        assert graph.reflector.calls == 0
        assert graph.memory_log.get_pending_entries() == []


def _valid_payload(run_id="r1"):
    return {
        "run": {"run_status": "completed", "telemetry_run_id": run_id},
        "usage_coverage": {"complete": True, "llm_calls": 1,
                           "calls_with_provider_usage": 1,
                           "calls_without_provider_usage": 0,
                           "calls_missing_input_tokens": 0,
                           "calls_missing_output_tokens": 0},
        "audit_quality": {"usage_complete": True, "attribution_complete": True,
                          "telemetry_complete": True},
        "run_totals": {"reported_input_tokens_sum": 10,
                       "reported_output_tokens_sum": 5, "llm_calls": 1,
                       "tool_calls": 0},
        "attribution": {"agent_calls": 1, "system_calls": 0, "unattributed_calls": 0,
                        "agent_tokens": 15, "system_tokens": 0,
                        "unattributed_tokens": 0, "system_components": []},
        "llm_call_events": [
            {"callback_run_id": "c1", "reported_input_tokens": 10,
             "reported_output_tokens": 5, "usage_source": "provider",
             "attribution_type": "agent", "component_id": None},
        ],
    }


class TestHarnessRecordsMemory:
    def test_a_clean_run_records_the_memory_state_and_stays_valid(self, tmp_path):
        batch = _copy_batch(tmp_path)
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())

        def runner(spec_path, exp_dir, run_index, attempt=1):
            spec = json.loads(Path(spec_path).read_text())
            runtime = Path(spec["results_dir"])
            (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
            tele = runtime / "telemetry" / "run-x-1.json"
            tele.write_text(json.dumps(_valid_payload()))
            state = Path(spec["memory"]["run_memory_path"])
            with state.open("a", encoding="utf-8") as handle:
                handle.write(SEPARATOR)
            metrics = tb.memory_state_after_run(spec)
            (Path(spec_path).parent / tb.MEMORY_STATE_FILE).write_text(json.dumps(metrics))
            return {"status": "ok", "returncode": 0, "error": None,
                    "report": {"status": "completed", "run_status": "completed",
                               "telemetry_path": str(tele)}}

        metrics = tb.execute_measured_run(directory, registration,
                                          registration["cases"][0], 1, runner=runner)
        assert metrics["valid"] is True
        assert metrics["memory"]["baseline_unchanged"] is True
        assert metrics["memory"]["run_changed"] is True

    def test_a_modified_baseline_invalidates_the_run(self, tmp_path):
        batch = _copy_batch(tmp_path)
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())

        def runner(spec_path, exp_dir, run_index, attempt=1):
            spec = json.loads(Path(spec_path).read_text())
            runtime = Path(spec["results_dir"])
            (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
            tele = runtime / "telemetry" / "run-x-1.json"
            tele.write_text(json.dumps(_valid_payload()))
            baseline = Path(spec["memory"]["baseline_path"])
            with baseline.open("a", encoding="utf-8") as handle:
                handle.write("\ntampered\n")
            metrics = tb.memory_state_after_run(spec)
            (Path(spec_path).parent / tb.MEMORY_STATE_FILE).write_text(json.dumps(metrics))
            return {"status": "ok", "returncode": 0, "error": None,
                    "report": {"status": "completed", "run_status": "completed",
                               "telemetry_path": str(tele)}}

        metrics = tb.execute_measured_run(directory, registration,
                                          registration["cases"][0], 1, runner=runner)
        assert metrics["valid"] is False
        assert metrics["invalid_reason"] == tb.INVALID_MEMORY_BASELINE_MODIFIED
        assert metrics["memory"]["baseline_unchanged"] is False


class TestStrippedSpecCannotRun:
    def test_a_spec_claiming_r01_without_its_definition_is_refused(self):
        """Audit B M1: deleting the identity fields must not fall back to the
        shipped default arm and the shared developer log."""
        spec = {
            "experiment_id": "R01",
            "case": {"case_id": "NVDA_2026-09-23", "ticker": "NVDA",
                     "trade_date": "2026-09-23", "analysts": ["market"],
                     "research_rounds": 1, "risk_rounds": 1},
            "provider": "openai_compatible",
            "quick_model": "CS5351/DeepSeek-V4-Flash",
            "deep_model": "CS5351/DeepSeek-V4-Flash",
        }
        with pytest.raises(tb.RunRefused, match="registered run"):
            tb._preflight_gate(spec)


class TestMemoryEvidenceIsRequired:
    def test_a_memory_run_without_state_evidence_is_invalid(self, tmp_path):
        """Audit A/C M1: a run that declares isolation but leaves no
        memory_state.json must not be a valid sample."""
        batch = _copy_batch(tmp_path)
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())

        def runner(spec_path, exp_dir, run_index, attempt=1):
            spec = json.loads(Path(spec_path).read_text())
            runtime = Path(spec["results_dir"])
            (runtime / "telemetry").mkdir(parents=True, exist_ok=True)
            tele = runtime / "telemetry" / "run-x-1.json"
            tele.write_text(json.dumps(_valid_payload()))
            # Deliberately no memory_state.json: the run's memory evidence is
            # missing (killed child, deleted copy).
            return {"status": "ok", "returncode": 0, "error": None,
                    "report": {"status": "completed", "run_status": "completed",
                               "telemetry_path": str(tele)}}

        metrics = tb.execute_measured_run(directory, registration,
                                          registration["cases"][0], 1, runner=runner)
        assert metrics["valid"] is False
        assert metrics["invalid_reason"] == tb.INVALID_MEMORY_STATE_MISSING


class TestDoctoredRegistrationCannotBypassIsolation:
    def test_dropping_memory_and_protocol_version_is_still_refused(self, tmp_path, monkeypatch):
        """Audit B: deleting the two fields that *declare* isolation must not
        turn a V3 run into a shared-memory run. The batch contract still says
        isolation, so the spec without a memory block is refused."""
        batch = _copy_batch(tmp_path)
        monkeypatch.setenv("TRADINGAGENTS_C3_BATCH", str(batch))
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())
        registration.pop("memory")
        registration.pop("protocol_version")
        registration["config_sha256"] = tb.registration_sha256(registration)
        (directory / "experiment.json").write_text(json.dumps(registration))
        spec = tb.build_run_spec(directory, registration, registration["cases"][0], 1, 1)
        assert "memory" not in spec
        spec_path = directory / "runs" / "run_01" / "attempt_01" / "spec.json"
        spec_path.parent.mkdir(parents=True)
        spec_path.write_text(json.dumps(spec))
        spec["_spec_path"] = str(spec_path)
        with pytest.raises(tb.RunRefused, match="no memory isolation block|missing required field"):
            tb._preflight_gate(spec)

    def test_the_registration_preflight_also_refuses_it(self, tmp_path, monkeypatch):
        batch = _copy_batch(tmp_path)
        monkeypatch.setenv("TRADINGAGENTS_C3_BATCH", str(batch))
        directory = batch / "specs" / "R01_NVDA_C0"
        registration = json.loads((directory / "experiment.json").read_text())
        registration.pop("memory")
        registration.pop("protocol_version")
        registration["config_sha256"] = tb.registration_sha256(registration)
        with pytest.raises(tb.RunRefused, match="no memory snapshot"):
            tb._preflight_registration(directory, registration, registration["cases"][0])


class TestBaselineProvenance:
    def test_the_baseline_has_no_pending_entries(self):
        text = BASELINE.read_text(encoding="utf-8")
        assert "| pending]" not in text

    def test_the_provenance_records_what_was_excluded(self):
        provenance = json.loads(
            (BATCH / "memory/baseline_v3.provenance.json").read_text(encoding="utf-8"))
        assert provenance["baseline_sha256"] == tb._sha256_file(BASELINE)
        assert provenance["baseline_pending"] == 0
        assert provenance["excluded"], "the experiment-generated entries must be documented"
        if not provenance["kept_entries"]:
            # An intentionally empty baseline is allowed only when it says why.
            assert provenance["empty_baseline"] is True
            assert provenance["empty_reason"].strip()
