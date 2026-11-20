"""Parse the four read-only artifact sources into API payloads."""

from __future__ import annotations

from pathlib import Path

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import summarize

from .index import Artifact


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _run_sections(path: Path) -> dict[str, str]:
    reports = path / "reports"
    sections: dict[str, str] = {}
    if reports.is_dir():
        for file in sorted(reports.glob("*.md")):
            sections[file.stem] = _read(file)
    complete = path / "complete_report.md"
    if complete.is_file():
        sections["complete_report"] = _read(complete)
    return sections


def _run_artifacts(path: Path) -> list[dict]:
    artifacts = [{"kind": "archive"}]
    reports = path / "reports"
    if reports.is_dir():
        artifacts.extend(
            {"kind": "section", "section": file.stem} for file in sorted(reports.glob("*.md"))
        )
    if (path / "complete_report.md").is_file():
        artifacts.append({"kind": "complete"})
    return artifacts


def _saved_sections(path: Path) -> dict[str, str]:
    sections: dict[str, str] = {}
    for subdir in ("1_analysts", "2_research", "3_trading", "4_risk", "5_portfolio"):
        directory = path / subdir
        if not directory.is_dir():
            continue
        for file in sorted(directory.glob("*.md")):
            sections[f"{subdir}/{file.stem}"] = _read(file)
    complete = path / "complete_report.md"
    if complete.is_file():
        sections["complete_report"] = _read(complete)
    return sections


def _saved_artifacts(path: Path) -> list[dict]:
    artifacts = [{"kind": "archive"}]
    for subdir in ("1_analysts", "2_research", "3_trading", "4_risk", "5_portfolio"):
        directory = path / subdir
        if not directory.is_dir():
            continue
        artifacts.extend(
            {"kind": "section", "section": f"{subdir}/{file.stem}"}
            for file in sorted(directory.glob("*.md"))
        )
    if (path / "complete_report.md").is_file():
        artifacts.append({"kind": "complete"})
    return artifacts


def _metadata(artifact: Artifact) -> dict:
    return {
        **artifact.metadata,
        "ticker": artifact.ticker,
        "date": artifact.date,
        "source": artifact.source,
        "status": artifact.status,
    }


def run_detail(artifact: Artifact) -> dict:
    return {
        "artifact_id": artifact.artifact_id,
        "source": artifact.source,
        "ticker": artifact.ticker,
        "date": artifact.date,
        "status": artifact.status,
        "rating": artifact.rating,
        "review": artifact.review,
        "metadata": _metadata(artifact),
        "sections": _run_sections(artifact.path),
        "artifacts": _run_artifacts(artifact.path),
    }


def saved_detail(artifact: Artifact) -> dict:
    return {
        "artifact_id": artifact.artifact_id,
        "source": artifact.source,
        "ticker": artifact.ticker,
        "date": artifact.date,
        "status": artifact.status,
        "rating": artifact.rating,
        "review": artifact.review,
        "metadata": _metadata(artifact),
        "sections": _saved_sections(artifact.path),
        "artifacts": _saved_artifacts(artifact.path),
    }


def backtest_detail(artifact: Artifact) -> dict:
    log_path = artifact.path / "trading_memory.md"
    summary = summarize(TradingMemoryLog({"memory_log_path": str(log_path)}))
    by_rating = {
        rating: {
            "count": score.count,
            "hit_rate": score.hit_rate,
            "mean_alpha": score.mean_alpha,
        }
        for rating, score in summary.by_rating.items()
    }
    return {
        "artifact_id": artifact.artifact_id,
        "source": artifact.source,
        "ticker": artifact.ticker,
        "date": artifact.date,
        "status": artifact.status,
        "rating": artifact.rating,
        "review": artifact.review,
        "metadata": _metadata(artifact),
        "summary": {
            "resolved": summary.resolved,
            "pending": summary.pending,
            "unscored": summary.unscored,
            "holding": summary.holding,
            "by_rating": by_rating,
        },
        "artifacts": [{"kind": "log"}],
    }


def decision_detail(artifact: Artifact) -> dict:
    entries = TradingMemoryLog({"memory_log_path": str(artifact.path)}).load_entries()
    return {
        "artifact_id": artifact.artifact_id,
        "source": artifact.source,
        "ticker": artifact.ticker,
        "date": artifact.date,
        "status": artifact.status,
        "rating": artifact.rating,
        "review": artifact.review,
        "metadata": _metadata(artifact),
        "entries": entries,
        "artifacts": [{"kind": "decision_log"}],
    }


def detail(artifact: Artifact) -> dict:
    if artifact.source == "run":
        return run_detail(artifact)
    if artifact.source == "saved":
        return saved_detail(artifact)
    if artifact.source == "backtest":
        return backtest_detail(artifact)
    if artifact.source == "decision":
        return decision_detail(artifact)
    raise ValueError(f"unknown artifact source: {artifact.source!r}")
