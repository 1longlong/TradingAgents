"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

import json
import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# LLMs sometimes write a placeholder string ("None", "N/A", ...) into an optional
# numeric field instead of omitting it. Coerce those to None so the structured
# call validates instead of erroring (#1058). Pydantic still parses real numeric
# strings ("189.5") to float.
_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}


def _coerce_optional_float(value):
    """Normalise an LLM-written optional numeric field before validation.

    Three shapes show up in practice: a placeholder string ("None", "N/A") in
    place of an omitted value (#1058); a percentage where a price was asked for
    ("15%", #1288); and a human-formatted price ("$1,234.50"). A percentage
    cannot be salvaged into an absolute level -- reading "15%" as 15 would put a
    stop at $15 on a $600 stock -- so it is dropped like a placeholder, leaving
    one bad field to null out instead of failing the whole proposal. A formatted
    price is reduced to its number.

    Anything that is not a single number is dropped the same way. A range
    ("150-160") or a hedge ("around 150") would otherwise reach pydantic, fail
    validation, and discard the whole decision, losing every field the model got
    right along with the price.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.lower() in _NULLISH_FLOAT or text.endswith("%"):
        return None
    cleaned = text.replace(",", "").lstrip("$€£¥").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Conflicting arguments alone are not a "
            "reason to Hold: commit to the stronger side, sized by how "
            "decisively it wins. Choose Hold only when the evidence is still "
            "balanced after weighing, or too thin to support a call."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including sizing guidance relative to a standard allocation. The "
            "research team does not see the caller's holdings; the trader and "
            "portfolio manager apply the actual position."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: float | None = Field(
        default=None,
        description=(
            "Optional entry price target as an absolute number in the instrument's "
            "quote currency (e.g. 189.5), never a percentage or a range. Omit it "
            "if you cannot state a specific level."
        ),
    )
    stop_loss: float | None = Field(
        default=None,
        description=(
            "Optional stop-loss as an absolute price in the instrument's quote "
            "currency (e.g. 172.0), never a percentage. Convert a percentage "
            "distance to the price level it implies, or omit it."
        ),
    )
    position_sizing: str | None = Field(
        default=None,
        description="Optional sizing guidance, e.g. '5% of portfolio'.",
    )

    @field_validator("entry_price", "stop_loss", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    # Named even when absent, so a reader can tell a level the trader chose not
    # to give from one the schema never asked for.
    for label, value in (("Entry Price", proposal.entry_price),
                         ("Stop Loss", proposal.stop_loss),
                         ("Position Sizing", proposal.position_sizing)):
        parts.extend(["", f"**{label}**: {value if value is not None and value != '' else 'not provided'}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate. "
            "Conflicting arguments alone are not a reason to Hold: commit to the "
            "stronger side, sized by how decisively it wins. Choose Hold only "
            "when the evidence is still balanced after weighing, or too thin to "
            "support a call."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise action plan covering entry strategy, position sizing, "
            "key risk levels, and time horizon. Two to four sentences."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    price_target: float | None = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    time_horizon: str | None = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )

    @field_validator("price_target", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    # Named even when absent: a missing line reads as a field nobody asked for,
    # so a reader cannot tell "no target" from "target not reported".
    target = decision.price_target if decision.price_target is not None else "not provided"
    parts.extend(["", f"**Price Target**: {target}"])
    parts.extend(["", f"**Time Horizon**: {decision.time_horizon or 'not provided'}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sentiment Analyst
# ---------------------------------------------------------------------------


class SentimentBand(str, Enum):
    """Discrete sentiment direction produced by the Sentiment Analyst.

    Six tiers keep the signal granular enough to be actionable while remaining
    small enough for every provider to map reliably from its JSON output.
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"
    MILDLY_BEARISH = "Mildly Bearish"
    BEARISH = "Bearish"
    # Not a sentiment reading: no source returned usable data, so there is
    # nothing to measure. Kept in the enum (rather than modelled as a missing
    # value) because every downstream consumer reads ``overall_band`` as a
    # string and must see this state explicitly instead of a silent default.
    UNKNOWN = "Unknown"


class SentimentDataStatus(str, Enum):
    """Whether the Sentiment Analyst had anything real to measure.

    Determined in Python from the prefetched source strings, never by the
    model: a placeholder that the model could overrule would let an outage
    become a neutral reading again.
    """

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class SentimentReport(BaseModel):
    """Structured sentiment report produced by the Sentiment Analyst.

    Replaces the previous free-form prose output so downstream consumers
    (dashboards, audit logs, PDF renderers, other agents) can read
    ``overall_band`` and ``overall_score`` without maintaining fragile regex
    fallbacks that drift with every model release. ``narrative`` preserves the
    rich source-by-source analysis; ``render_sentiment_report`` prepends a
    deterministic header so the saved report stays human-readable.
    """

    overall_band: SentimentBand = Field(
        description=(
            "Overall sentiment direction. Exactly one of: "
            "Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish / Unknown. "
            "Use Mixed when sources point in clearly different directions. "
            "Use Neutral only when the data you did receive genuinely balances. "
            "Use Unknown when no source returned usable data: nothing was measured, "
            "so there is no direction to report and a band here would be invented."
        ),
    )
    overall_score: float | None = Field(
        default=None,
        ge=0.0,
        le=10.0,
        description=(
            "Numeric sentiment intensity on a 0–10 scale. "
            "0 = maximally bearish, 5 = neutral, 10 = maximally bullish. "
            "Guideline for consistency with overall_band: "
            "Bullish ~6.5–10, Mildly Bullish ~5.5–6.4, Neutral/Mixed ~4.5–5.5, "
            "Mildly Bearish ~3.5–4.4, Bearish ~0–3.4. "
            "Only the 0–10 bounds are enforced. "
            "Set this to null when overall_band is Unknown: there is no "
            "measurement to score, and a number here would be invented."
        ),
    )
    data_status: SentimentDataStatus = Field(
        default=SentimentDataStatus.AVAILABLE,
        description=(
            "Coverage of the three prefetched sources. "
            "AVAILABLE = all returned usable data; PARTIAL = some did; "
            "UNAVAILABLE = none did (nothing to measure); "
            "ERROR = a source raised an error rather than reporting no coverage."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "Confidence in the assessment based on data quality and sample size. "
            "Use 'low' when one or more sources returned a placeholder or fewer "
            "than 5 data points; 'medium' when data is present but sparse; "
            "'high' when all three sources returned substantive data."
        ),
    )
    narrative: str = Field(
        description=(
            "Full sentiment report covering, in order: "
            "(1) source-by-source breakdown with specific evidence (cite message "
            "counts, ratios, notable posts); "
            "(2) cross-source divergences and alignments; "
            "(3) dominant narrative themes; "
            "(4) catalysts and risks surfaced by the data; "
            "(5) a markdown table summarising key sentiment signals, their "
            "direction, source, and supporting evidence. "
            "Keep it informative and substantive: develop each section thoroughly "
            "with concrete evidence so every point adds new signal for the trader."
        ),
    )


def render_sentiment_report(report: SentimentReport) -> str:
    """Render a SentimentReport to the markdown shape the rest of the system expects.

    The structured header (band + score + confidence) is prepended to the
    narrative so the saved report is both human-readable and machine-parseable
    without regex.
    """
    if report.overall_score is None:
        score = "Score: not scored (no data)"
    else:
        score = f"Score: {report.overall_score:.1f}/10"
    return "\n".join([
        f"**Overall Sentiment:** **{report.overall_band.value}** ({score})",
        f"**Confidence:** {report.confidence.capitalize()}",
        f"**Data status:** {report.data_status.value}",
        "",
        report.narrative,
    ])


# ---------------------------------------------------------------------------
# Sentiment data availability
# ---------------------------------------------------------------------------
# Every sentiment fetcher degrades to a placeholder string rather than raising,
# so "non-empty string" says nothing about whether data arrived. These patterns
# mirror the exact placeholders the fetchers emit (reddit.py:260/270,
# stocktwits.py:96/110, date_window.py coverage_gap, and the routed news
# wrapper). They are matched against the string the analyst was given, so the
# availability verdict cannot be talked around by the model.
_SENTIMENT_UNAVAILABLE_MARKERS = (
    "unavailable",
    "not an absence of",
    "no stocktwits messages",
    "no reddit posts",
    "no news found",
    "coverage starts",
    "data_unavailable",
    "no_data_available",
    "currently down",
)
# A source did not merely have no coverage; the fetch itself failed.
_SENTIMENT_ERROR_MARKERS = (
    "fetch failed",
    "<stocktwits unavailable:",
    "timed out",
    "ratelimit",
    "rate limit",
    "currently down",
)
# A feed that did not reach the window is not an error, so this is tested
# before the error markers: the coverage notice itself contains the word
# "unavailable" (date_window.coverage_gap) and would otherwise read as ERROR.
# Only the window-miss wording counts here. "not an absence of" alone is not a
# coverage marker: the fetch-failure placeholder ends with that same clause and
# must still classify as an error.
_SENTIMENT_COVERAGE_MARKERS = (
    "coverage starts",
    "serves recent items",
    "serves newer items",
)


def _classify_sentiment_source(block: str | None) -> SentimentDataStatus:
    """Classify one prefetched source string as real data or a placeholder.

    Order matters: a coverage-gap notice is a *successful* fetch that reached
    the wrong era, so it is matched before the error markers even though it
    contains the word "unavailable".
    """
    text = (block or "").strip()
    if not text:
        return SentimentDataStatus.UNAVAILABLE
    lowered = text.lower()
    if any(m in lowered for m in _SENTIMENT_COVERAGE_MARKERS):
        return SentimentDataStatus.UNAVAILABLE
    if any(m in lowered for m in _SENTIMENT_ERROR_MARKERS):
        return SentimentDataStatus.ERROR
    # A ``NEWS_STATUS=`` line states an answer-level outcome for the news feed.
    # Only ``SUCCESS_REAL_CONTENT`` means articles actually reached the model.
    # Without this branch ``NEWS_STATUS=EMPTY_VALID`` ("the vendor answered and
    # had no articles") matched no marker and fell through to AVAILABLE -- so an
    # empty news window read as real sentiment data, the same asymmetry the news
    # classifier closed for itself (audit follow-up, this campaign).
    if _news_status_is_failure(text) and "NEWS_STATUS=SUCCESS_REAL_CONTENT" not in text:
        return SentimentDataStatus.UNAVAILABLE
    if any(m in lowered for m in _SENTIMENT_UNAVAILABLE_MARKERS):
        return SentimentDataStatus.UNAVAILABLE
    return SentimentDataStatus.AVAILABLE


def classify_sentiment_sources(*blocks: str | None) -> SentimentDataStatus:
    """Overall data status from the individually classified source blocks.

    AVAILABLE needs every source; PARTIAL needs at least one real source and at
    least one that was not; UNAVAILABLE means none was real; ERROR means none
    was real *and* at least one failed outright, which is a different fact from
    a feed simply not reaching back far enough.
    """
    per_source = [_classify_sentiment_source(b) for b in blocks]
    real = sum(1 for s in per_source if s is SentimentDataStatus.AVAILABLE)
    errored = sum(1 for s in per_source if s is SentimentDataStatus.ERROR)
    if real and real == len(per_source):
        return SentimentDataStatus.AVAILABLE
    if real:
        return SentimentDataStatus.PARTIAL
    if errored:
        return SentimentDataStatus.ERROR
    return SentimentDataStatus.UNAVAILABLE


# Markers the news router/tools use to say "you got no usable company news".
# Mirrors ``macro_data_tools._UNAVAILABLE_MARKERS`` plus the coverage-gap
# placeholder, so a live-only vendor answering an old window is not mistaken for
# "this company had no news".
_NEWS_UNAVAILABLE_MARKERS = (
    "DATA_UNAVAILABLE",
    "NO_DATA_AVAILABLE",
    "unavailable for",
    "only serves newer items",
    # yfinance's own absence wording (yfinance_news.py). It carries no
    # NEWS_STATUS token, so without this marker a vendor that answered "no
    # articles" would read as *news present* (audit D-1).
    "no news found",
    # Every failure class is rendered as ``NEWS_STATUS=<CLASS>: ...`` (see
    # dataflows/news_status.py). Only SUCCESS_REAL_CONTENT asserts content, so
    # any *other* NEWS_STATUS line must count as unavailable. The helper below
    # implements that precisely rather than matching the bare prefix.
)


def _news_status_is_failure(text: str) -> bool:
    """Whether tool text carries a NEWS_STATUS line that is not success."""
    marker = "NEWS_STATUS="
    start = 0
    while True:
        idx = text.find(marker, start)
        if idx == -1:
            return False
        token = text[idx + len(marker):].split(None, 1)[0].strip(":;,.")
        if token and token != "SUCCESS_REAL_CONTENT":
            return True
        start = idx + len(marker)


def _has_news_body(text: str) -> bool:
    """Whether rendered news text contains at least one actual record.

    Each vendor that can serve ``get_news`` renders content in its own shape, so
    this recognises every one that returns *real* records:

    * the markdown vendors (``yfinance_news``, ``gdelt_news``,
      ``historical_news``) put each article on a ``### Title (source: ...)`` line;
    * the raw Alpha Vantage adapter returns a JSON object with a ``feed`` (or
      ``articles``) array.

    Heading-only output, prose with no records, or a stray status sentence
    therefore counts as **no news**. This closes the "absence read as presence"
    hole: a vendor that answers with a formatted but empty page must not make
    the News Analyst's stance look informed.
    """
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        if isinstance(payload, dict):
            for key in ("feed", "articles"):
                records = payload.get(key)
                if isinstance(records, list) and records:
                    return True
            return False
        return isinstance(payload, list) and bool(payload)
    return any(line.lstrip().startswith("### ") for line in text.splitlines())


def classify_news_source_availability(messages: object) -> NewsSourceStatus:
    """Did any real company-news record reach the analyst?

    Scans the tool results in ``messages`` for the result of every ``get_news``
    call. A result counts as available only if it contains none of the
    unavailable markers. If ``get_news`` was never called, or every call
    returned a marker, the company-news source is ``UNAVAILABLE``.

    This is a presence test, not a quality judgement: it cannot tell a genuine
    empty window (vendor answered, no articles) from an outage. Both are
    "no company news", which is all the renderer needs to know.
    """
    for message in messages if isinstance(messages, (list, tuple)) else ():
        if getattr(message, "type", None) not in ("tool", "ToolMessage"):
            continue
        name = getattr(message, "name", None) or ""
        if name != "get_news":
            continue
        content = getattr(message, "content", None)
        text = content if isinstance(content, str) else str(content)
        # Empty or whitespace-only results are an absence of content, not news
        # (audit D-1). Same rule the sentiment classifier applies.
        if not text.strip():
            continue
        if any(marker in text for marker in _NEWS_UNAVAILABLE_MARKERS):
            continue
        if _news_status_is_failure(text):
            continue
        # A bare markdown header (e.g. "## NVDA News, from ...:") with no
        # article blocks is also an absence: the vendor formatted an empty
        # window. Require at least one article line before calling it news.
        if not _has_news_body(text):
            continue
        return NewsSourceStatus.AVAILABLE
    # Never called, or every call returned a marker: both mean "no company news".
    return NewsSourceStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Workstream 3 — Native structured analyst output
# ---------------------------------------------------------------------------
# The three tool-loop analysts (market, fundamentals, news) historically emit a
# free-form markdown blob: ~48 % of all output tokens in Control v4. These
# schemas let the *generation itself* produce typed fields, rather than parsing
# prose afterwards. Nothing here summarises or drops evidence: every schema
# carries a free-form body field alongside the typed ones, so the rendered
# report is a strict superset of what the model would otherwise have written.
#
# Three candidates were designed (see structured_output/candidates.md):
#   S1  NativeStructuredReport   — one generic typed skeleton, evidence-first
#   S2  Typed<Analyst>Report     — one bespoke schema per analyst
#   S3  CompactEvidenceReport    — typed headline + tight body, fewest tokens


class AnalystStance(str, Enum):
    """Directional stance an analyst's own evidence supports.

    ``UNKNOWN`` is a first-class member for the same reason it is in
    ``SentimentBand``: an analyst that could not obtain data must be able to say
    so, instead of being forced into a neutral verdict it did not reach.
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"
    MIXED = "Mixed"
    UNKNOWN = "Unknown"


class EvidenceItem(BaseModel):
    """One concrete, dated observation drawn from tool output.

    Typed separately from the prose so downstream agents can read *what was
    actually seen* without re-parsing markdown, while the prose keeps the
    argument that links the evidence together.
    """

    claim: str = Field(description="What the data shows, in one sentence.")
    evidence: str = Field(
        description=(
            "The exact number, date, or tool-output fragment supporting the claim. "
            "Quote the value as returned; never approximate or infer it."
        ),
    )
    source: str = Field(
        description="Which tool or dataset produced it, e.g. 'get_indicators: rsi'.",
    )


class NativeStructuredReport(BaseModel):
    """S1 — a generic typed skeleton shared by every analyst.

    One schema for all three analysts keeps the tool-definition payload (and so
    the input-token cost) identical regardless of which analyst is speaking.
    """

    stance: AnalystStance = Field(
        description=(
            "The directional stance the analyst's own evidence supports. "
            "Use Unknown when the required data could not be retrieved."
        ),
    )
    headline: str = Field(
        description="One sentence stating the single most important finding.",
    )
    key_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description=(
            "3–8 concrete, dated observations from tool output, most important "
            "first. Each must quote a real value; omit rather than invent."
        ),
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Concrete risks or contradicting evidence, each one line.",
    )
    body: str = Field(
        description=(
            "The full analyst report in markdown: the reasoning that connects the "
            "evidence, the caveats, and the closing summary table. Keep the detail "
            "and nuance of the prose report; do not merely restate the fields above."
        ),
    )


def render_native_structured_report(report: NativeStructuredReport) -> str:
    """Render S1 to markdown: typed header, evidence list, then the full body."""
    lines = [f"**Stance:** {report.stance.value}", f"**Headline:** {report.headline}"]
    if report.key_evidence:
        lines.append("")
        lines.append("**Key evidence:**")
        for item in report.key_evidence:
            lines.append(f"- {item.claim} — {item.evidence} ({item.source})")
    if report.risks:
        lines.append("")
        lines.append("**Risks / contradicting evidence:**")
        for risk in report.risks:
            lines.append(f"- {risk}")
    lines.append("")
    lines.append(report.body)
    return "\n".join(lines)


class CompactEvidenceReport(BaseModel):
    """S3 — evidence-first and deliberately terse, to test the token floor.

    The hypothesis: a large share of analyst output is prose that repeats the
    tool data already in context. Keeping only typed evidence plus a short
    interpretation may cut output materially. The risk this candidate exists to
    test is that it drops reasoning downstream agents need, which is why it is
    **not** adopted without a quality check.
    """

    stance: AnalystStance = Field(description="Directional stance, or Unknown without data.")
    key_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Up to 5 concrete dated observations, most important first.",
    )
    interpretation: str = Field(
        description=(
            "At most 120 words connecting the evidence to the stance. "
            "No repetition of the evidence items themselves."
        ),
    )


def render_compact_evidence_report(report: CompactEvidenceReport) -> str:
    """Render S3 to markdown."""
    lines = [f"**Stance:** {report.stance.value}", "", "**Key evidence:**"]
    for item in report.key_evidence:
        lines.append(f"- {item.claim} — {item.evidence} ({item.source})")
    lines += ["", report.interpretation]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# S2 — per-analyst native structured output (the adopted candidate)
# ---------------------------------------------------------------------------
# The generic shape tested first gave every analyst a `key_levels` field. For the
# market analyst that field is the point (actionable price levels). For the news
# analyst the model filled it with an analyst price target it had merely read
# from a headline, and for the fundamentals analyst it rightly stayed empty --
# so the field was either dead weight or an invitation to relabel a fact. S2
# therefore splits the shared skeleton from one analyst-specific block.
#
# Every schema keeps `key_evidence` (facts quoted from tool output),
# `interpretation` (the argument, capped), and `risks` (counter-evidence).
# This is *not* a strict superset of the free-text report: the independent
# Layer-2 blind review found the free text routinely stated what would falsify
# the view and weighed Bull/Base/Bear branches, and S2 had no field for either.
# `invalidation` and `scenario_set` were added for exactly those two gaps; they
# are not a claim that nothing else is lost.

INTERPRETATION_GUIDANCE = (
    "At most 140 words connecting the evidence to the stance. Do not restate "
    "the evidence or risk entries themselves; state what they mean together."
)


class InvalidationStatus(str, Enum):
    """Whether a basis for an invalidation condition was present at all."""

    PROVIDED = "provided"
    UNAVAILABLE = "unavailable"


class InvalidationCondition(BaseModel):
    """One observable development that would falsify the analyst's stance (not a stop-loss)."""

    condition: str = Field(
        description=(
            "What would falsify the current stance, as a factual development, "
            "e.g. 'price closes below the 50-day SMA on rising volume'."
        ),
    )
    observable_signal: str = Field(
        description=(
            "What a reader would look at to see it happening, e.g. "
            "'close_50_sma vs close in get_indicators output'."
        ),
    )
    threshold: str | None = Field(
        default=None,
        description="Trigger level quoted from tool output; null when no number is supported.",
    )
    evidence_basis: str = Field(
        description="The observation in key_evidence this condition rests on; omit the condition if none.",
    )
    invalidates: str = Field(
        description="Which part of the stance or interpretation this overturns.",
    )


class ScenarioType(str, Enum):
    BULL = "Bull"
    BASE = "Base"
    BEAR = "Bear"


class ScenarioStatus(str, Enum):
    """Whether a scenario distribution could be estimated from the evidence."""

    ESTIMATED = "estimated"
    NOT_ESTIMABLE = "not_estimable"


class Scenario(BaseModel):
    """One Bull/Base/Bear branch with an optional probability weight."""

    name: ScenarioType = Field(description="Which branch this is.")
    weight: float | None = Field(
        default=None,
        description=(
            "Probability of this branch in percent (0-100) that the evidence supports: "
            "how likely the scenario is, not how confident you feel. Null if unsupported."
        ),
    )
    supporting_evidence: str = Field(
        description="The observations in key_evidence that make this branch plausible.",
    )
    trigger_conditions: str = Field(
        description="What would make this branch the realised path.",
    )
    invalidation_conditions: str = Field(
        description="What would rule this branch out.",
    )


class ScenarioSet(BaseModel):
    """Bull/Base/Bear scenarios with an explicit estimability status."""

    status: ScenarioStatus = Field(
        default=ScenarioStatus.NOT_ESTIMABLE,
        description=(
            "'estimated' only when weights are supported and sum to 100; else "
            "'not_estimable' with null weights. Never split evenly by default."
        ),
    )
    scenarios: list[Scenario] = Field(
        default_factory=list,
        description="Up to three branches (Bull, Base, Bear); empty rather than fabricated.",
    )


class PriceLevel(BaseModel):
    """One actionable price level for the market analyst."""

    label: str = Field(
        description="One of: Resistance, Support, Breakout trigger, Stop zone.",
    )
    price: str = Field(
        description="The level as a price or range, copied from the tool output, e.g. '179.88'.",
    )
    why: str = Field(description="Short evidence for this level.")


class MarketAnalystReport(BaseModel):
    """Market analyst report: S2 skeleton plus technical price levels."""

    stance: AnalystStance = Field(
        description="Directional stance, or Unknown when the required data could not be retrieved.",
    )
    key_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Up to 6 concrete dated observations from tool output, most important first.",
    )
    key_levels: list[PriceLevel] = Field(
        default_factory=list,
        description=(
            "Actionable price levels visible in the tool output: support, resistance, "
            "breakout trigger, invalidation/stop. Omit rather than invent."
        ),
    )
    risks: list[str] = Field(
        default_factory=list, description="Concrete downside risks or contradicting signals, one line each."
    )
    invalidation: list[InvalidationCondition] = Field(
        default_factory=list,
        description=(
            "Observable price/indicator developments that would falsify the stance. "
            "Not a stop-loss; empty when no evidence basis exists."
        ),
    )
    scenario_set: ScenarioSet | None = Field(
        default=None,
        description="Bull/Base/Bear branches with optional weights, from price/indicator triggers.",
    )
    interpretation: str = Field(default="", description=INTERPRETATION_GUIDANCE)


def render_market_analyst_report(report: MarketAnalystReport) -> str:
    """Render the market analyst report to markdown."""
    return _render_s2_body(
        report,
        levels=[(lvl.label, lvl.price, lvl.why) for lvl in report.key_levels],
        invalidation=report.invalidation,
        scenario_set=report.scenario_set,
    )


class FundamentalFact(BaseModel):
    """One verified figure from the financial statements."""

    metric: str = Field(description="e.g. 'Revenue', 'Gross margin', 'Free cash flow'.")
    value: str = Field(description="The value exactly as reported, including period, e.g. '46.7B (Q2 FY2026)'.")
    read: str = Field(description="One short sentence on why it matters.")


class FundamentalsAnalystReport(BaseModel):
    """Fundamentals analyst report: S2 skeleton plus verified statement facts."""

    stance: AnalystStance = Field(
        description="Directional stance the fundamentals support, or Unknown when data was unavailable.",
    )
    key_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Up to 6 concrete dated observations from tool output, most important first.",
    )
    key_figures: list[FundamentalFact] = Field(
        default_factory=list,
        description=(
            "3-8 headline financial figures drawn from the statement tool output, with "
            "their period. Copy values exactly; never estimate or annualise by hand."
        ),
    )
    risks: list[str] = Field(
        default_factory=list, description="Concrete fundamental risks, one line each."
    )
    invalidation: list[InvalidationCondition] = Field(
        default_factory=list,
        description=(
            "Reported metric/guidance developments that would falsify the stance; "
            "empty when no evidence basis exists."
        ),
    )
    scenario_set: ScenarioSet | None = Field(
        default=None,
        description="Bull/Base/Bear branches with optional weights, from reported figures/guidance.",
    )
    interpretation: str = Field(default="", description=INTERPRETATION_GUIDANCE)


def render_fundamentals_analyst_report(report: FundamentalsAnalystReport) -> str:
    """Render the fundamentals analyst report to markdown."""
    return _render_s2_body(
        report,
        figures=[(f.metric, f.value, f.read) for f in report.key_figures],
        invalidation=report.invalidation,
        scenario_set=report.scenario_set,
    )


class Catalyst(BaseModel):
    """One dated news event and its likely market relevance."""

    date: str = Field(description="Publication date of the item, yyyy-mm-dd.")
    event: str = Field(description="What happened, one sentence.")
    relevance: str = Field(description="Why it matters for this instrument, one sentence.")


class NewsSourceStatus(str, Enum):
    """Whether company-specific news actually reached the analyst.

    Set in Python from the tool output, never chosen by the model. It exists
    because a news report can be *partly* blind: the company-news vendor can be
    down while FRED macro data still arrives. Prompting alone was not enough --
    the first shipped-config run returned ``stance=Mixed`` with a "trim
    exposure" bias while its own evidence said no NVDA news could be verified.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class NewsAnalystReport(BaseModel):
    """News analyst report: S2 skeleton plus dated catalysts."""

    stance: AnalystStance = Field(
        description="Directional stance the news flow supports, or Unknown when no news could be retrieved.",
    )
    # Not a model field to fill: ``render_news_analyst_report`` overwrites it from
    # the values the analyst node read out of the tool output. Declared here so
    # the forced value travels with the report object and cannot be lost.
    news_source_status: NewsSourceStatus = Field(
        default=NewsSourceStatus.AVAILABLE,
        exclude=True,
        description="Filled by the node from the tool output; ignored if the model sets it.",
    )
    key_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Up to 6 concrete dated observations from tool output, most important first.",
    )
    catalysts: list[Catalyst] = Field(
        default_factory=list,
        description=(
            "Company and macro events actually present in the tool output, newest first. "
            "Never list an event that is not in the retrieved news."
        ),
    )
    risks: list[str] = Field(
        default_factory=list, description="Concrete news-driven risks, one line each."
    )
    interpretation: str = Field(default="", description=INTERPRETATION_GUIDANCE)


def render_news_analyst_report(report: NewsAnalystReport) -> str:
    """Render the news analyst report to markdown.

    When the company-news source was unavailable, the stance is forced to
    ``Unknown`` regardless of what the model wrote. Macro data arriving does not
    make a directional view on the *company* supported: the same evidence set,
    in earlier runs, also produced ``Mixed`` plus an actionable bias, which is
    exactly the "missing data rendered as a signal" failure the sentiment path
    already blocks. The model's own view, when it had one, is kept below in
    ``interpretation`` rather than deleted.
    """
    if report.news_source_status is NewsSourceStatus.UNAVAILABLE:
        forced = report.model_copy(update={"stance": AnalystStance.UNKNOWN})
        body = _render_s2_body(
            forced,
            catalysts=[(c.date, c.event, c.relevance) for c in forced.catalysts],
        )
        return (
            "> **News source unavailable for this window.** The stance is"
            " **Unknown**, not Neutral: no company-specific news was retrieved,"
            " so the market's news flow cannot be read. Any macro observation"
            " below is context, not a news-driven view.\n\n" + body
        )
    return _render_s2_body(
        report,
        catalysts=[(c.date, c.event, c.relevance) for c in report.catalysts],
    )


def _normalise_scenario_weights(
    scenario_set: ScenarioSet,
) -> tuple[list[tuple[Scenario, float | None]], str]:
    """Return each scenario with its usable weight, plus a one-line weight summary.

    Weights are handled leniently on purpose. A hard ``model_validator`` that
    rejected weights not summing to 100 would raise, and ``finalize_analyst_report``
    turns any exception into the prose fallback -- so one sloppy weight would
    discard every typed field. Instead:

    * only finite weights in [0, 100] are kept; anything else is dropped;
    * weights are never rescaled (rescaling invents precision the model did not give);
      a set that does not sum to ~100 is rendered with its actual sum and a note;
    * when ``status`` is ``NOT_ESTIMABLE``, or no weight survived, the summary says
      so rather than showing an equal split.
    """
    rows: list[tuple[Scenario, float | None]] = []
    for scenario in scenario_set.scenarios:
        weight = scenario.weight
        usable = (
            isinstance(weight, (int, float))
            and not isinstance(weight, bool)
            and math.isfinite(weight)
            and 0.0 <= weight <= 100.0
        )
        rows.append((scenario, float(weight) if usable else None))

    # ``NOT_ESTIMABLE`` is an authoritative statement that no weights could be
    # grounded. A model can still leave numbers in the fields (e.g. a default
    # 33.3/33.3/33.3 it forgot to clear), so the status must SUPPRESS them --
    # otherwise the list shows an even split while the footer says the opposite
    # (audit D-2). Dropping the numbers here is what makes "never split evenly
    # by default" true at the renderer, not merely in the prompt.
    if scenario_set.status is ScenarioStatus.NOT_ESTIMABLE:
        rows = [(scenario, None) for scenario, _ in rows]
        return rows, "_Weights not estimable from the retrieved data._"

    kept = [w for _, w in rows if w is not None]
    if not kept:
        return rows, "_Weights not estimable from the retrieved data._"

    total = sum(kept)
    if len(kept) == len(rows) and abs(total - 100.0) <= 0.5:
        return rows, f"_Weights sum to {total:.0f}%._"
    missing = len(rows) - len(kept)
    detail = f"; {missing} branch{'es' if missing > 1 else ''} without a weight" if missing else ""
    return rows, (
        f"_Weights sum to {total:.0f}% across the branches that have one{detail}; "
        "not normalised._"
    )


def _render_s2_body(
    report: BaseModel,
    levels: list[tuple[str, str, str]] | None = None,
    figures: list[tuple[str, str, str]] | None = None,
    catalysts: list[tuple[str, str, str]] | None = None,
    invalidation: list[InvalidationCondition] | None = None,
    scenario_set: ScenarioSet | None = None,
) -> str:
    """Shared markdown layout for the S2 analyst reports.

    The section order matches what the free-text reports already produced
    (stance, evidence, the analyst-specific block, risks, then the closing
    argument), so downstream readers need no change. ``invalidation`` and
    ``scenario_set`` default to ``None`` so the news renderer, which passes
    neither, is byte-identical to before they existed.
    """
    lines = [f"**Stance:** {report.stance.value}", "", "**Key evidence:**"]
    for item in report.key_evidence:
        lines.append(f"- {item.claim} — {item.evidence} ({item.source})")

    if levels:
        lines += ["", "**Key levels:**"]
        for label, price, why in levels:
            lines.append(f"- {label}: {price} — {why}")
    if figures:
        lines += ["", "**Key figures:**"]
        for metric, value, read in figures:
            lines.append(f"- {metric}: {value} — {read}")
    if catalysts:
        lines += ["", "**Catalysts:**"]
        for date, event, relevance in catalysts:
            lines.append(f"- {date} — {event} ({relevance})")

    if report.risks:
        lines += ["", "**Risks:**"]
        for risk in report.risks:
            lines.append(f"- {risk}")

    if invalidation:
        lines += ["", "**Invalidation conditions:**"]
        for item in invalidation:
            threshold = item.threshold or "no fixed threshold"
            lines.append(
                f"- {item.condition.rstrip('.')} — signal: {item.observable_signal.rstrip('.')};"
                f" threshold: {threshold}; basis: {item.evidence_basis.rstrip('.')};"
                f" invalidates: {item.invalidates.rstrip('.')}"
            )
    elif invalidation is not None:
        lines += [
            "",
            "**Invalidation conditions:**",
            "- No invalidation condition could be grounded in the retrieved data.",
        ]

    if scenario_set is not None and scenario_set.scenarios:
        lines += ["", "**Scenarios (Bull / Base / Bear):**"]
        rows, summary = _normalise_scenario_weights(scenario_set)
        for scenario, weight in rows:
            shown = f"{weight:.0f}%" if weight is not None else "not estimated"
            lines.append(
                f"- {scenario.name.value} (weight: {shown}):"
                f" {scenario.supporting_evidence.rstrip('.')};"
                f" trigger: {scenario.trigger_conditions.rstrip('.')};"
                f" invalidated by: {scenario.invalidation_conditions.rstrip('.')}."
            )
        lines += ["", summary]

    lines += ["", report.interpretation]
    return "\n".join(lines)
