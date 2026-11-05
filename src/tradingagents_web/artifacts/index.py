"""Read-only scan of existing CLI/API artifacts.

Artifact identifiers are ``sha256(relative_path)[:16]``. They are stable for a
path, never persisted, and never sent to the browser as filesystem paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.agents.utils.rating import RATING_REVIEW, extract_rating
from tradingagents.dataflows.utils import safe_ticker_component

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAVED_DATE_RE = re.compile(r"_(\d{8})_")
COMPLETE_TICKER_RE = re.compile(r"Trading Analysis Report:\s*([A-Za-z0-9._\-^=+]+)")


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    source: str
    path: Path
    ticker: str
    date: str | None
    status: str
    rating: str | None
    review: bool
    updated_at: float
    title: str

    def to_item(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "source": self.source,
            "ticker": self.ticker,
            "date": self.date,
            "status": self.status,
            "rating": self.rating,
            "review": self.review,
            "updated_at": datetime.fromtimestamp(
                self.updated_at, tz=timezone.utc
            ).isoformat(),
            "title": self.title,
        }


def _digest(path: Path, root: Path, prefix: str = "") -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return sha256(f"{prefix}{relative}".encode()).hexdigest()[:16]


def _mtime(path: Path) -> float:
    if path.is_file():
        return path.stat().st_mtime
    times = [entry.stat().st_mtime for entry in path.rglob("*") if entry.is_file()]
    return max(times, default=path.stat().st_mtime)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rating(text: str | None) -> tuple[str | None, bool]:
    if not text:
        return None, False
    value = extract_rating(text)
    if value is None:
        return RATING_REVIEW, True
    return value, value == RATING_REVIEW


def _safe_ticker(name: str) -> str | None:
    try:
        return safe_ticker_component(name)
    except ValueError:
        return None


class ArtifactIndex:
    """Scan the configured results directory and memory log on demand."""

    def __init__(self, settings):
        self.settings = settings
        self.results_dir = Path(settings.results_dir)
        self.memory_log_path = Path(settings.memory_log_path)

    def scan(self) -> list[Artifact]:
        items: list[Artifact] = []
        items.extend(self._scan_runs())
        items.extend(self._scan_saved())
        items.extend(self._scan_backtests())
        items.extend(self._scan_decision_memory())
        items.sort(key=lambda item: (item.updated_at, item.artifact_id), reverse=True)
        return items

    def find(self, artifact_id: str) -> Artifact | None:
        return next(
            (item for item in self.scan() if item.artifact_id == artifact_id),
            None,
        )

    def _scan_runs(self) -> list[Artifact]:
        found: list[Artifact] = []
        if not self.results_dir.is_dir():
            return found
        for ticker_dir in sorted(self.results_dir.iterdir()):
            if not ticker_dir.is_dir():
                continue
            ticker = _safe_ticker(ticker_dir.name)
            if ticker is None:
                continue
            for date_dir in sorted(ticker_dir.iterdir()):
                if not date_dir.is_dir() or not DATE_RE.fullmatch(date_dir.name):
                    continue
                reports = date_dir / "reports"
                final = reports / "final_trade_decision.md"
                final_text = _read(final) if final.is_file() else None
                rating, review = _rating(final_text)
                status = "completed" if final.is_file() else "partial"
                found.append(
                    Artifact(
                        artifact_id=_digest(date_dir, self.results_dir),
                        source="run",
                        path=date_dir,
                        ticker=ticker,
                        date=date_dir.name,
                        status=status,
                        rating=rating,
                        review=review,
                        updated_at=_mtime(date_dir),
                        title=f"{ticker} {date_dir.name}",
                    )
                )
        return found

    def _scan_saved(self) -> list[Artifact]:
        found: list[Artifact] = []
        saved_root = self.results_dir / "reports"
        if not saved_root.is_dir():
            return found
        for saved_dir in sorted(saved_root.iterdir()):
            if not saved_dir.is_dir():
                continue
            complete = saved_dir / "complete_report.md"
            complete_text = _read(complete) if complete.is_file() else None
            match = COMPLETE_TICKER_RE.search(complete_text or "")
            ticker = _safe_ticker(match.group(1)) if match else _safe_ticker(
                saved_dir.name.split("_", 1)[0]
            )
            if ticker is None:
                continue
            date_match = SAVED_DATE_RE.search(saved_dir.name)
            date = None
            if date_match:
                raw = date_match.group(1)
                date = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
            decision = saved_dir / "5_portfolio" / "decision.md"
            rating_text = _read(decision) if decision.is_file() else complete_text
            rating, review = _rating(rating_text)
            found.append(
                Artifact(
                    artifact_id=_digest(saved_dir, self.results_dir),
                    source="saved",
                    path=saved_dir,
                    ticker=ticker,
                    date=date,
                    status="completed" if complete.is_file() else "partial",
                    rating=rating,
                    review=review,
                    updated_at=_mtime(saved_dir),
                    title=f"{ticker} saved report",
                )
            )
        return found

    def _scan_backtests(self) -> list[Artifact]:
        found: list[Artifact] = []
        root = self.results_dir / "backtest"
        if not root.is_dir():
            return found
        for run_dir in sorted(root.iterdir()):
            if not run_dir.is_dir():
                continue
            log = run_dir / "trading_memory.md"
            if not log.is_file():
                continue
            entries = TradingMemoryLog({"memory_log_path": str(log)}).load_entries()
            tickers = sorted({entry["ticker"] for entry in entries})
            dates = sorted({entry["date"] for entry in entries})
            found.append(
                Artifact(
                    artifact_id=_digest(run_dir, self.results_dir),
                    source="backtest",
                    path=run_dir,
                    ticker=",".join(tickers) or run_dir.name,
                    date=dates[-1] if dates else None,
                    status="completed",
                    rating=None,
                    review=False,
                    updated_at=_mtime(run_dir),
                    title=f"Backtest {run_dir.name}",
                )
            )
        return found

    def _scan_decision_memory(self) -> list[Artifact]:
        if not self.memory_log_path.is_file():
            return []
        entries = TradingMemoryLog(
            {"memory_log_path": str(self.memory_log_path)}
        ).load_entries()
        if not entries:
            return []
        tickers = sorted({entry["ticker"] for entry in entries})
        dates = sorted({entry["date"] for entry in entries})
        return [
            Artifact(
                artifact_id=_digest(self.memory_log_path, self.memory_log_path, "decision:"),
                source="decision",
                path=self.memory_log_path,
                ticker=",".join(tickers) or "decision",
                date=dates[-1] if dates else None,
                status="completed",
                rating=None,
                review=False,
                updated_at=_mtime(self.memory_log_path),
                title="Decision memory",
            )
        ]
