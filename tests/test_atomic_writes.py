"""Single-file atomic replacement for reports and the run-state log.

Every failure case is injected into the real write path and checked against the
actual files on disk: the previous file must be byte-for-byte unchanged, a
missing target must stay missing, and the temporary file must be gone.
"""

import builtins
import contextlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from tradingagents.file_io import write_text_atomic
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree

OLD = "旧版本：完整内容\nline two\n"
NEW = "新版本：中文内容 ✓\nline two\n"


def _temp_files(directory: Path, target: Path) -> list[Path]:
    """Files in ``directory`` that are temporary files for ``target``."""
    return sorted(
        p for p in Path(directory).iterdir()
        if p.name.startswith(f".{target.name}.") and p.name.endswith(".tmp")
    )


class _Tracking:
    """Temporary files created while the fault injector is active."""

    def __init__(self):
        self.made: list[str] = []


@contextlib.contextmanager
def _temp_file_faults(monkeypatch, tracking: _Tracking, partial_for: str, fail_after: int):
    """Fail the write of the temporary file for ``partial_for`` partway through.

    The temporary file is still really created and really partially written;
    only the handle returned for it stops short. Everything else uses the real
    file handling, so the rest of the tree keeps behaving normally.
    """
    real_mkstemp = tempfile.mkstemp
    real_fdopen = os.fdopen

    def mkstemp(**kwargs):
        fd, name = real_mkstemp(**kwargs)
        tracking.made.append(name)
        return fd, name

    pending = iter(tracking.made)
    armed = [True]

    def fdopen(fd, *args, **kwargs):
        handle = real_fdopen(fd, *args, **kwargs)
        # os.fdopen on Windows reports the fd, not the path, so the path comes
        # from the mkstemp calls made during this block (one write, one open).
        created = next(pending, None)
        if (
            armed[0]
            and created is not None
            and os.path.basename(created).startswith(f".{partial_for}.")
        ):
            armed[0] = False
            return _FailingWriteHandle(handle, fail_after=fail_after)
        return handle

    monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(os, "fdopen", fdopen)
    yield tracking


class _FailingWriteHandle:
    """A real file handle whose ``write`` stops after committing part of it."""

    def __init__(self, handle, fail_after: int):
        self._handle = handle
        self._fail_after = fail_after
        self._written = 0

    def write(self, text):
        if self._written >= self._fail_after:
            raise OSError(28, "No space left on device (injected)")
        keep = min(len(text), self._fail_after - self._written)
        self._handle.write(text[:keep])
        self._written += keep
        raise OSError(28, "No space left on device (injected)")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._handle.close()
        return False


# --- reporting.py ---------------------------------------------------------


def _report_state(**overrides):
    state = {
        "market_report": "MKT",
        "news_report": "NEWS",
        "investment_debate_state": {"judge_decision": "RM PLAN"},
        "trader_investment_plan": "TRADE",
        "risk_debate_state": {"judge_decision": "PM DECISION"},
    }
    state.update(overrides)
    return state


@pytest.mark.unit
def test_first_report_write_creates_the_whole_tree(tmp_path):
    out = write_report_tree(_report_state(), "AAPL", tmp_path)

    assert out == tmp_path / "complete_report.md"
    assert (tmp_path / "1_analysts" / "market.md").read_text(encoding="utf-8") == "MKT"
    assert (tmp_path / "1_analysts" / "news.md").read_text(encoding="utf-8") == "NEWS"
    assert (tmp_path / "2_research" / "manager.md").read_text(encoding="utf-8") == "RM PLAN"
    assert (tmp_path / "3_trading" / "trader.md").read_text(encoding="utf-8") == "TRADE"
    assert (tmp_path / "5_portfolio" / "decision.md").read_text(encoding="utf-8") == "PM DECISION"
    complete = out.read_text(encoding="utf-8")
    assert complete.startswith("# Trading Analysis Report: AAPL\n\nGenerated: ")
    assert "## I. Analyst Team Reports" in complete
    assert "## V. Portfolio Manager Decision" in complete
    # The temporary files are gone once each replace succeeded.
    for path in tmp_path.rglob("*"):
        assert not path.name.endswith(".tmp")


@pytest.mark.unit
def test_report_over_write_replaces_every_file_with_utf8(tmp_path):
    write_report_tree(_report_state(), "AAPL", tmp_path)
    out = write_report_tree(
        _report_state(market_report="市场：看涨", trader_investment_plan="交易：买入"), "AAPL", tmp_path
    )

    assert (tmp_path / "1_analysts" / "market.md").read_text(encoding="utf-8") == "市场：看涨"
    assert (tmp_path / "3_trading" / "trader.md").read_text(encoding="utf-8") == "交易：买入"
    # Sections the second run no longer carries are not deleted (unchanged behaviour).
    assert (tmp_path / "1_analysts" / "news.md").read_text(encoding="utf-8") == "NEWS"
    complete = out.read_bytes().decode("utf-8")
    assert "市场：看涨" in complete and "交易：买入" in complete
    assert "## V. Portfolio Manager Decision" in complete


def _seed_report_tree(root: Path) -> dict[Path, bytes]:
    write_report_tree(_report_state(), "AAPL", root)
    return {p: p.read_bytes() for p in sorted(root.rglob("*.md"))}


@pytest.mark.unit
def test_partial_temporary_report_write_leaves_previous_tree_intact(tmp_path, monkeypatch):
    before = _seed_report_tree(tmp_path)
    failing_path = tmp_path / "1_analysts" / "news.md"
    tracking = _Tracking()

    with (
        _temp_file_faults(monkeypatch, tracking, partial_for=failing_path.name, fail_after=2),
        pytest.raises(OSError, match="No space left"),
    ):
        write_report_tree(_report_state(market_report="新市场"), "AAPL", tmp_path)

    # market.md was replaced before the failure; the rest were not started.
    assert (tmp_path / "1_analysts" / "market.md").read_text(encoding="utf-8") == "新市场"
    for path in before:
        if path.name != "market.md":
            assert path.read_bytes() == before[path], path
    # The failing write really used a temporary file (not the target) and that
    # file was removed; no trace of it remains on disk.
    temp = [Path(name) for name in tracking.made]
    assert any(p.name.startswith(".news.md.") for p in temp)
    for p in temp:
        assert p.name.endswith(".tmp")
        assert not p.exists()
    assert not _temp_files(tmp_path / "1_analysts", tmp_path / "1_analysts" / "news.md")


@pytest.mark.unit
def test_report_flush_failure_keeps_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "1_analysts" / "market.md"
    target.parent.mkdir()
    target.write_bytes(OLD.encode("utf-8"))

    def failing_fsync(fd):
        raise OSError(5, "Input/output error (injected)")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="Input/output error"):
        write_text_atomic(target, NEW)

    assert target.read_bytes() == OLD.encode("utf-8")
    assert _temp_files(target.parent, target) == []


@pytest.mark.unit
def test_report_replace_failure_keeps_previous_tree_and_raises(tmp_path, monkeypatch):
    before = _seed_report_tree(tmp_path)
    real_replace = os.replace

    def failing_replace(src, dst):
        if Path(dst).name == "complete_report.md":
            raise PermissionError(13, "Access is denied (injected)")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(PermissionError, match="Access is denied"):
        write_report_tree(_report_state(market_report="新市场"), "AAPL", tmp_path)

    assert (tmp_path / "1_analysts" / "market.md").read_text(encoding="utf-8") == "新市场"
    assert (tmp_path / "complete_report.md").read_bytes() == before[tmp_path / "complete_report.md"]
    assert _temp_files(tmp_path, tmp_path / "complete_report.md") == []


@pytest.mark.unit
def test_first_report_write_failure_leaves_no_partial_target(tmp_path, monkeypatch):
    def failing_replace(src, dst):
        raise OSError(13, "replace failed (injected)")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_report_tree(_report_state(), "AAPL", tmp_path)

    target_dir = tmp_path / "1_analysts"
    assert not (target_dir / "market.md").exists()
    assert _temp_files(target_dir, target_dir / "market.md") == []
    assert not (tmp_path / "complete_report.md").exists()


@pytest.mark.unit
def test_cleanup_failure_does_not_hide_the_original_error(tmp_path, monkeypatch):
    target = tmp_path / "1_analysts" / "market.md"
    target.parent.mkdir()
    target.write_bytes(OLD.encode("utf-8"))
    real_unlink = Path.unlink

    def failing_replace(src, dst):
        raise OSError(13, "replace failed (injected)")

    def failing_unlink(self, *args, **kwargs):
        if self.suffix == ".tmp":
            raise PermissionError(13, "cannot delete temporary file")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)
    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(OSError, match="replace failed"):
        write_text_atomic(target, NEW)

    assert target.read_bytes() == OLD.encode("utf-8")


@pytest.mark.unit
def test_consecutive_writes_never_share_a_temporary_file(tmp_path, monkeypatch):
    target = tmp_path / "report.md"
    target.write_bytes(OLD.encode("utf-8"))
    seen: list[str] = []
    real_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(**kwargs):
        fd, name = real_mkstemp(**kwargs)
        seen.append(name)
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", tracking_mkstemp)
    write_text_atomic(target, NEW)
    write_text_atomic(target, NEW + "again\n")

    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(Path(name).parent == tmp_path for name in seen)
    assert target.read_text(encoding="utf-8") == NEW + "again\n"


@pytest.mark.unit
def test_serialisation_failure_never_touches_the_target(tmp_path):
    target = tmp_path / "report.md"
    target.write_bytes(OLD.encode("utf-8"))

    def prepare() -> str:
        return json.dumps({"bad": object()})  # raises before the target is touched

    with pytest.raises(TypeError):
        write_text_atomic(target, prepare())

    assert target.read_bytes() == OLD.encode("utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.md"]


# --- _log_state -----------------------------------------------------------


STATES = {
    "company_of_interest": "600519.SS",
    "trade_date": "2026-09-01",
    "market_report": "市场",
    "sentiment_report": "情绪",
    "news_report": "新闻",
    "fundamentals_report": "基本面",
    "investment_plan": "计划",
    "trader_investment_plan": "交易计划",
    "final_trade_decision": "评级: 买入",
    "investment_debate_state": {
        "bull_history": "", "bear_history": "", "history": "",
        "current_response": "", "judge_decision": "", "count": 0,
    },
    "risk_debate_state": {
        "aggressive_history": "", "conservative_history": "", "neutral_history": "",
        "history": "", "judge_decision": "", "latest_speaker": "",
        "current_aggressive_response": "", "current_conservative_response": "",
        "current_neutral_response": "", "count": 0,
    },
}


def _graph(tmp_path) -> TradingAgentsGraph:
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"results_dir": str(tmp_path)}
    graph.ticker = "600519.SS"
    graph.log_states_dict = {}
    return graph


def _log_path(tmp_path) -> Path:
    return tmp_path / "600519.SS" / "TradingAgentsStrategy_logs" / "full_states_log_2026-09-01.json"


@pytest.mark.unit
def test_state_log_first_write_and_overwrite_keep_json_shape(tmp_path):
    graph = _graph(tmp_path)
    graph._log_state("2026-09-01", STATES)
    path = _log_path(tmp_path)

    assert graph.log_states_dict["2026-09-01"]["final_trade_decision"] == "评级: 买入"
    written = path.read_text(encoding="utf-8")
    assert "买入" in written and "\\u" not in written
    assert written.startswith('{\n    "company_of_interest"')
    parsed = json.loads(written)
    assert list(parsed) == [
        "company_of_interest", "trade_date", "market_report", "sentiment_report",
        "news_report", "fundamentals_report", "investment_debate_state",
        "trader_investment_decision", "risk_debate_state", "investment_plan",
        "final_trade_decision",
    ]

    graph._log_state("2026-09-01", {**STATES, "final_trade_decision": "评级: 卖出"})
    assert json.loads(path.read_text(encoding="utf-8"))["final_trade_decision"] == "评级: 卖出"
    assert graph.log_states_dict["2026-09-01"]["final_trade_decision"] == "评级: 卖出"
    assert _temp_files(path.parent, path) == []


@pytest.mark.unit
def test_state_log_serialisation_failure_keeps_old_file_and_memory(tmp_path):
    graph = _graph(tmp_path)
    graph._log_state("2026-09-01", STATES)
    path = _log_path(tmp_path)
    before = path.read_bytes()
    before_memory = dict(graph.log_states_dict)

    with pytest.raises(TypeError):
        graph._log_state("2026-09-01", {**STATES, "market_report": {"not": object()}})

    assert path.read_bytes() == before
    json.loads(path.read_text(encoding="utf-8"))
    assert graph.log_states_dict == before_memory
    assert _temp_files(path.parent, path) == []


@pytest.mark.unit
def test_state_log_partial_write_failure_keeps_old_file_and_memory(tmp_path, monkeypatch):
    graph = _graph(tmp_path)
    graph._log_state("2026-09-01", STATES)
    path = _log_path(tmp_path)
    before = path.read_bytes()
    before_memory = dict(graph.log_states_dict)
    tracking = _Tracking()

    with (
        _temp_file_faults(monkeypatch, tracking, partial_for=path.name, fail_after=20),
        pytest.raises(OSError, match="No space left"),
    ):
        graph._log_state("2026-09-01", {**STATES, "final_trade_decision": "新评级"})

    assert path.read_bytes() == before
    assert graph.log_states_dict == before_memory
    assert _temp_files(path.parent, path) == []


@pytest.mark.unit
def test_state_log_replace_failure_keeps_old_file_and_memory(tmp_path, monkeypatch):
    graph = _graph(tmp_path)
    graph._log_state("2026-09-01", STATES)
    path = _log_path(tmp_path)
    before = path.read_bytes()
    before_memory = dict(graph.log_states_dict)

    def failing_replace(src, dst):
        raise PermissionError(13, "Access is denied (injected)")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(PermissionError, match="Access is denied"):
        graph._log_state("2026-09-01", {**STATES, "final_trade_decision": "新评级"})

    assert path.read_bytes() == before
    assert graph.log_states_dict == before_memory
    assert _temp_files(path.parent, path) == []


@pytest.mark.unit
def test_first_state_log_failure_leaves_no_file_and_no_memory_entry(tmp_path, monkeypatch):
    graph = _graph(tmp_path)

    def failing_fsync(fd):
        raise OSError(5, "Input/output error (injected)")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="Input/output error"):
        graph._log_state("2026-09-01", STATES)

    assert not _log_path(tmp_path).exists()
    assert graph.log_states_dict == {}
    logs = tmp_path / "600519.SS" / "TradingAgentsStrategy_logs"
    assert list(logs.iterdir()) == []


@pytest.mark.unit
def test_log_state_does_not_use_plain_open_for_the_target(tmp_path, monkeypatch):
    """The old in-place ``open(..., "w")`` path would truncate on failure."""
    graph = _graph(tmp_path)
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if Path(file).name == "full_states_log_2026-09-01.json" and "w" in mode:
            raise AssertionError("target opened in place")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    graph._log_state("2026-09-01", STATES)
    assert _log_path(tmp_path).exists()
