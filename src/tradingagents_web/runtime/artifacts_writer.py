"""Write the run artifacts the CLI writes, without reimplementing report layout."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.evidence.origin import ORIGIN_STATE_KEY
from tradingagents.reporting import write_report_tree
from tradingagents_web.artifacts.audit import AUDIT_FILES, public_data


class RunArtifactWriter:
    def __init__(
        self,
        results_dir: str | Path,
        ticker: str,
        trade_date: str,
        run_id: str,
        metadata: dict | None = None,
    ):
        """Keep Web runs separate from CLI artifacts (ADR-001, INV-WEB-001)."""
        if not re.fullmatch(r"r_[0-9a-f]{12}", run_id):
            raise ValueError("invalid web run identifier")
        self.results_dir = Path(results_dir)
        self.ticker = ticker
        self.trade_date = trade_date
        self.run_id = run_id
        # REQ-WEB-013: persist only effective presentation fields, never endpoints or portfolios.
        allowed = {
            "analysts",
            "research_depth",
            "llm_provider",
            "quick_think_llm",
            "deep_think_llm",
            "output_language",
            "asset_type",
        }
        self.metadata = public_data(
            {
                key: value
                for key, value in (metadata or {}).items()
                if key in allowed and (not isinstance(value, str) or len(value) <= 256)
            }
        )
        self.run_dir = self.results_dir / "web_runs" / run_id
        self.reports_dir = self.run_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.message_log = self.run_dir / "message_tool.log"
        self.sections: dict[str, str] = {}
        self.set_status("starting")

    @property
    def artifact_id(self) -> str:
        return sha256(str(self.run_dir.relative_to(self.results_dir)).encode()).hexdigest()[:16]

    def set_status(self, status: str) -> None:
        """Persist per-run lifecycle metadata, never a second history index."""
        metadata = {
            "run_id": self.run_id,
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "status": status,
            "metadata": self.metadata,
        }
        temporary = self.run_dir / "run.json.tmp"
        temporary.write_text(json.dumps(metadata), encoding="utf-8")
        temporary.replace(self.run_dir / "run.json")

    def on_message(self, payload: dict) -> None:
        timestamp = str(payload.get("timestamp") or datetime.now().strftime("%H:%M:%S"))
        message_type = str(payload.get("type") or "Agent")
        content = str(payload.get("content") or "").replace("\n", " ")
        self._append(f"{timestamp} [{message_type}] {content}\n")

    def on_tool_call(self, payload: dict) -> None:
        timestamp = str(payload.get("timestamp") or datetime.now().strftime("%H:%M:%S"))
        name = str(payload.get("name") or payload.get("tool") or "tool")
        args = payload.get("arguments") or payload.get("args") or {}
        rendered = ", ".join(f"{key}={value}" for key, value in args.items())
        self._append(f"{timestamp} [Tool Call] {name}({rendered})\n")

    def on_section(self, payload: dict) -> None:
        section = str(payload.get("section") or "")
        content = str(payload.get("content") or "")
        if not section or "/" in section or "\\" in section or section.startswith("."):
            return
        self.sections[section] = content
        (self.reports_dir / f"{section}.md").write_text(content, encoding="utf-8")

    def complete(self, final_state: dict | None = None) -> Path:
        state = dict(final_state or {})
        state.setdefault("trade_date", self.trade_date)
        for key, value in self.sections.items():
            state.setdefault(key, value)
        state.setdefault("market_report", "")
        state.setdefault("sentiment_report", "")
        state.setdefault("news_report", "")
        state.setdefault("fundamentals_report", "")
        state.setdefault(
            "investment_debate_state",
            {
                "bull_history": "",
                "bear_history": "",
                "judge_decision": self.sections.get("investment_plan", ""),
            },
        )
        state.setdefault("trader_investment_plan", self.sections.get("trader_investment_plan", ""))
        state.setdefault(
            "risk_debate_state",
            {
                "aggressive_history": "",
                "conservative_history": "",
                "neutral_history": "",
                "judge_decision": self.sections.get("final_trade_decision", ""),
            },
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = (
            self.results_dir
            / "reports"
            / f"{safe_ticker_component(self.ticker)}_{stamp}_{self.run_id}"
        )
        complete = write_report_tree(state, self.ticker, save_path)
        # Keep a run-local copy so the run artifact and the saved report tree
        # are both downloadable from the same history item.
        shutil.copyfile(complete, self.run_dir / "complete_report.md")
        # REQ-WEB-009: keep canonical core audit families addressable by this run's opaque ID.
        for relative in AUDIT_FILES.values():
            source = save_path / relative
            if source.is_file() and not source.is_symlink():
                destination = self.run_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                # Add only existing structured lifecycle/origin descriptors. No raw arguments.
                extra: dict[str, Any] = {}
                if relative == AUDIT_FILES["evidence_manifest"]:
                    origins = state.get(ORIGIN_STATE_KEY)
                    if isinstance(origins, dict):
                        fields = {
                            "target_date",
                            "observation_date",
                            "availability_date",
                            "published_at",
                            "filed_at",
                            "retrieved_at",
                            "date_basis",
                            "value_scale",
                            "unit",
                            "currency",
                            "period_end_source",
                            "schema_version",
                        }
                        extra[ORIGIN_STATE_KEY] = {
                            identifier: {
                                key: value for key, value in origin.items() if key in fields
                            }
                            for identifier, origin in origins.items()
                            if isinstance(origin, dict)
                        }
                    attempts = state.get("data_quality_source_attempts")
                    if isinstance(attempts, list):
                        fields = {
                            "source",
                            "tool",
                            "started_at",
                            "duration",
                            "result_status",
                            "error_type",
                            "error_message",
                        }
                        extra["data_quality_source_attempts"] = [
                            {key: value for key, value in item.items() if key in fields}
                            for item in attempts
                            if isinstance(item, dict)
                        ]
                if relative == AUDIT_FILES["debate_trace"]:
                    debate = state.get("investment_debate_state")
                    if isinstance(debate, dict) and isinstance(debate.get("conflicts"), list):
                        fields = {
                            "conflict_id",
                            "kind",
                            "severity",
                            "status",
                            "evidence_ids",
                            "participants",
                            "first_seen_round",
                            "last_seen_round",
                        }
                        extra["conflicts"] = [
                            {key: value for key, value in item.items() if key in fields}
                            for item in debate["conflicts"]
                            if isinstance(item, dict)
                        ]
                if extra:
                    projected = json.loads(destination.read_text(encoding="utf-8"))
                    projected["web_context"] = public_data(extra)
                    destination.write_text(
                        json.dumps(projected, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
        return complete

    def _append(self, line: str) -> None:
        with open(self.message_log, "a", encoding="utf-8") as stream:
            stream.write(line)
