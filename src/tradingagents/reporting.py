"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.

Stage 2: the writer additionally emits the shared quality/debate artifacts
(``0_quality/*``, ``2_research/debate_trace.json``, ``run_summary.json``) via
:func:`tradingagents.report_artifacts.write_report_artifacts`, and adds concise
``Data Quality`` and ``Run Summary`` sections to ``complete_report.md``.
"""

from datetime import datetime
from pathlib import Path

from tradingagents.report_artifacts import (
    build_data_quality_section,
    build_run_summary_section,
    write_report_artifacts,
)

# A raw Bull/Bear debate transcript is NOT authoritative trusted output: it is the
# model's argument as spoken and may contain a claim that later failed exact
# validation. It is retained for audit but explicitly labelled non-authoritative so
# it is never read as a verified fact.
_NON_AUTHORITATIVE_NOTICE = (
    "> NON-AUTHORITATIVE: raw debate transcript, shown for audit only. It may "
    "contain exact claims that failed deterministic validation; rely only on the "
    "Research Manager / Trader / Portfolio sections for trusted facts."
)


def _trusted_text(
    final_state: dict,
    text: str,
    *,
    section: str = "report_section",
    audit_sink: list | None = None,
) -> str:
    """Redact + confidence-cap a trusted output before writing it.

    Applies the same narrow, line-scoped exact-claim redaction used at the agent
    boundary AND (ADR-011) independently recomputes the degraded-run confidence
    cap from the authoritative gate verdict in ``final_state`` — it never trusts a
    state-supplied effective/audit value. This means a legacy checkpoint or a
    hand-built/imported state cannot resurrect a raw over-cap confidence in the
    saved report. Ordinary financial figures are untouched.

    ``section`` gives each report section a DISTINCT audit boundary (so sections
    never collapse to one ``report`` identity), and any new audit entries are
    appended to ``audit_sink`` (when supplied) so the report summary can count
    them. ``final_state`` itself is never mutated here.
    """
    from tradingagents.agents.utils.output_guard import enforce_trusted_boundary
    from tradingagents.debate.confidence_policy import cap_agent_text

    redacted = enforce_trusted_boundary(text, final_state)
    capped, entries = cap_agent_text(
        redacted, final_state, source="report", boundary=f"report:{section}",
    )
    if audit_sink is not None and entries:
        audit_sink.extend(entries)
    return capped


def write_report_tree(final_state: dict, ticker: str, save_path) -> Path:
    """Save a completed run's reports to ``save_path``; return the complete-report path.

    Trusted sections (analyst reports, Research Manager, Trader, risk analysts,
    Portfolio Manager and the consolidated plan/decision) are passed through
    :func:`_trusted_text` so a rejected exact fact is redacted at the report
    boundary too, and each section's confidence-cap audit is collected into one
    sanitized copy (never mutating the caller's ``final_state``) so the report
    summary reflects the raw/effective provenance of imported/legacy states. The
    raw Bull/Bear transcript is written under an explicit NON-AUTHORITATIVE
    notice.
    """
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []
    report_audit: list = []

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        text = _trusted_text(final_state, final_state["market_report"], section="market", audit_sink=report_audit)
        (analysts_dir / "market.md").write_text(text, encoding="utf-8")
        analyst_parts.append(("Market Analyst", text))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        text = _trusted_text(final_state, final_state["sentiment_report"], section="sentiment", audit_sink=report_audit)
        (analysts_dir / "sentiment.md").write_text(text, encoding="utf-8")
        analyst_parts.append(("Sentiment Analyst", text))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        text = _trusted_text(final_state, final_state["news_report"], section="news", audit_sink=report_audit)
        (analysts_dir / "news.md").write_text(text, encoding="utf-8")
        analyst_parts.append(("News Analyst", text))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        text = _trusted_text(final_state, final_state["fundamentals_report"], section="fundamentals", audit_sink=report_audit)
        (analysts_dir / "fundamentals.md").write_text(text, encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", text))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        # Raw Bull/Bear transcripts: NON-AUTHORITATIVE (audit only).
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            raw = f"{_NON_AUTHORITATIVE_NOTICE}\n\n{debate['bull_history']}"
            (research_dir / "bull.md").write_text(raw, encoding="utf-8")
            research_parts.append(("Bull Researcher (non-authoritative transcript)", raw))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            raw = f"{_NON_AUTHORITATIVE_NOTICE}\n\n{debate['bear_history']}"
            (research_dir / "bear.md").write_text(raw, encoding="utf-8")
            research_parts.append(("Bear Researcher (non-authoritative transcript)", raw))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            text = _trusted_text(final_state, debate["judge_decision"], section="research_manager", audit_sink=report_audit)
            (research_dir / "manager.md").write_text(text, encoding="utf-8")
            research_parts.append(("Research Manager", text))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        text = _trusted_text(final_state, final_state["trader_investment_plan"], section="trader", audit_sink=report_audit)
        (trading_dir / "trader.md").write_text(text, encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{text}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            text = _trusted_text(final_state, risk["aggressive_history"], section="risk_aggressive", audit_sink=report_audit)
            (risk_dir / "aggressive.md").write_text(text, encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", text))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            text = _trusted_text(final_state, risk["conservative_history"], section="risk_conservative", audit_sink=report_audit)
            (risk_dir / "conservative.md").write_text(text, encoding="utf-8")
            risk_parts.append(("Conservative Analyst", text))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            text = _trusted_text(final_state, risk["neutral_history"], section="risk_neutral", audit_sink=report_audit)
            (risk_dir / "neutral.md").write_text(text, encoding="utf-8")
            risk_parts.append(("Neutral Analyst", text))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            text = _trusted_text(final_state, risk["judge_decision"], section="portfolio", audit_sink=report_audit)
            (portfolio_dir / "decision.md").write_text(text, encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{text}")

    # Stage 2: shared quality/debate/run artifacts (redacted, structured only).
    # ADR-011: the artifact input is a SANITIZED COPY of the state — the numeric
    # confidence in persisted turns/stances AND the readable text are capped on the
    # copy (never the caller's object), and the per-section ``_trusted_text`` audit
    # is merged together with the copy's own per-turn/per-field audit into the copy's
    # ``confidence_cap_audit``. Thus the exported ``run_summary.json`` /
    # ``gate_summary.md`` / ``complete_report.md`` summary reflect the
    # imported/legacy cap provenance (capped_count > 0) instead of counting 0, and
    # the exported JSON can never carry a raw over-cap turn confidence.
    from tradingagents.debate.confidence_policy import merge_audit, sanitize_state_inputs

    artifact_state, input_audit = sanitize_state_inputs(final_state)
    merged_audit = merge_audit(
        artifact_state.get("confidence_cap_audit"),
        list(input_audit) + list(report_audit),
    )
    if merged_audit:
        artifact_state["confidence_cap_audit"] = merged_audit
    artifact_paths = write_report_artifacts(artifact_state, ticker, save_path)

    # Write consolidated report (with the concise Data Quality and Run Summary
    # sections appended so the complete report mirrors the shared artifacts).
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    sections.append(build_data_quality_section(artifact_state))
    sections.append(build_run_summary_section(artifact_state, ticker, artifact_paths))
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections), encoding="utf-8")
    return save_path / "complete_report.md"
