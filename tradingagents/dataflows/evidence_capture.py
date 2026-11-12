"""Helpers that capture structured, vendor-origin evidence from dataflows.

The dataflow vendor functions fetch typed source objects (Yahoo/FactSet article
dicts, SEC facts JSON, StockTwits message dicts, Reddit Atom entries) and then
format a public prose string. This module turns those *original* records into
typed :class:`~tradingagents.evidence.models.EvidenceRecord`s and records a
:class:`~tradingagents.evidence.models.SourceAttempt` for each operated source.

It is the bridge between a dataflow and the run-scoped collector in
:mod:`tradingagents.evidence.ingest`; it never parses prose and never invents a
vendor field. Kept separate from the dataflows themselves so a bare tool test
(no active run) has no capture side effect and no import cycle.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.evidence.ingest import (
    capture_attempt,
    capture_origin,
    capture_record,
    get_active_collector,
)
from tradingagents.evidence.models import EvidenceRecord, SourceResultStatus
from tradingagents.evidence.vendor_adapters import (
    build_alpha_vantage_origin,
    build_news_origin,
    build_news_record,
    build_sec_fundamentals_record,
    build_sec_origin,
    build_sentiment_origin,
    build_sentiment_record,
    make_source_attempt,
)


def _run_identity() -> tuple[str, str] | None:
    """``(run_id, target_date)`` for the active run, or ``None`` when inactive."""
    collector = get_active_collector()
    if collector is None:
        return None
    target_date = collector.metadata.target_date
    symbol = collector.metadata.symbol
    if not target_date or not symbol:
        return None
    from tradingagents.graph.data_quality_gate import build_gate_run_id

    return build_gate_run_id(target_date, normalize_symbol(symbol)), target_date


def _stable_index(records: Iterable[EvidenceRecord]) -> list[tuple[int, EvidenceRecord]]:
    """Deterministic position for records that have no content identity.

    Sorted by (source_name, ticker, value_raw, observed_at) so two runs over the
    same vendor return assign the same index; never depends on dict order.
    """
    ordered = sorted(
        records,
        key=lambda r: (
            r.source_name,
            r.ticker_normalized,
            r.value_raw,
            r.observed_at or "",
            r.source_ref,
        ),
    )
    return list(enumerate(ordered))


# ---------------------------------------------------------------------------
# News (Yahoo + Alpha Vantage original article objects)
# ---------------------------------------------------------------------------


def capture_news_articles(
    ticker: str,
    articles: list[dict],
    *,
    source_name: str,
    tool: str,
    result_status: SourceResultStatus = SourceResultStatus.SUCCESS,
    error_type: str | None = None,
) -> None:
    """Capture one news source's original article objects into the run.

    ``articles`` are the vendor's original objects (already narrowed to the
    requested window by the caller) with at least ``title`` and, when known,
    ``published`` (ISO date/datetime string or ``None``). The record keeps the
    publisher/url lineage; missing dates stay ``None`` (the validator fails them
    closed, never assuming the target date). Always records the source attempt
    for the real call.
    """
    identity = _run_identity()
    started_at = None
    if identity is None:
        return
    run_id, target_date = identity
    canonical = normalize_symbol(ticker)
    records: list[EvidenceRecord] = []
    seen_lineage: set[str] = set()
    for article in articles or []:
        if not isinstance(article, dict):
            continue
        title = article.get("title")
        if not title:
            continue
        published = article.get("published") or article.get("pub_date")
        if hasattr(published, "isoformat"):
            published = published.isoformat()
        record = build_news_record(
            run_id=run_id,
            symbol_input=ticker,
            symbol_normalized=canonical,
            target_date=target_date,
            title=str(title),
            publisher=str(article.get("publisher") or ""),
            url=str(article.get("url") or article.get("link") or ""),
            published=published,
            source_name=source_name,
            index=0,
        )
        # Collapse syndicated duplicates within this source attempt.
        lineage = f"{record.metric_name.lower()}|{record.observed_at or ''}"
        if lineage in seen_lineage:
            continue
        seen_lineage.add(lineage)
        records.append(record)
    for record in records:
        capture_record(record)
        capture_origin(
            record.evidence_id,
            build_news_origin(
                target_date=target_date,
                published=record.observed_at,
                fetched_at=record.fetched_at,
            ),
        )
    capture_attempt(
        make_source_attempt(
            source=source_name,
            tool=tool,
            result_status=result_status if records else SourceResultStatus.EMPTY,
            started_at=started_at,
            error_type=error_type,
        )
    )


# ---------------------------------------------------------------------------
# Sentiment (StockTwits native labels + Reddit posts)
# ---------------------------------------------------------------------------


def capture_stocktwits_messages(ticker: str, messages: list[dict], *, tool: str = "stocktwits") -> None:
    """Capture StockTwits messages using their source-native sentiment label."""
    identity = _run_identity()
    if identity is None:
        return
    run_id, target_date = identity
    canonical = normalize_symbol(ticker)
    records: list[EvidenceRecord] = []
    seen: set[str] = set()
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        created = message.get("created_at")
        entities = message.get("entities") or {}
        sentiment_obj = entities.get("sentiment") if isinstance(entities, dict) else None
        native_label = None
        if isinstance(sentiment_obj, dict):
            native_label = sentiment_obj.get("basic")
        user = (message.get("user") or {}) if isinstance(message.get("user"), dict) else {}
        _author = str(user.get("username") or "")  # never persisted (privacy)
        body = str(message.get("body") or "")
        # Content identity: created_at + body hash basis; no invented id.
        lineage = f"stocktwits|{created}|{body[:64]}"
        if lineage in seen:
            continue
        seen.add(lineage)
        records.append(
            build_sentiment_record(
                run_id=run_id,
                symbol_input=ticker,
                symbol_normalized=canonical,
                target_date=target_date,
                source_name="stocktwits",
                native_label=native_label,
                body=body,
                posted_at=created,
                # Never persist the author handle; the source name already
                # identifies the provider. Usernames are personal data.
                author_ref="",
                lineage_key=lineage,
                index=0,
            )
        )
    for record in records:
        capture_record(record)
        capture_origin(
            record.evidence_id,
            build_sentiment_origin(
                target_date=target_date,
                posted_at=record.observed_at,
                fetched_at=record.fetched_at,
            ),
        )
    capture_attempt(
        make_source_attempt(
            source="stocktwits",
            tool=tool,
            result_status=SourceResultStatus.SUCCESS if records else SourceResultStatus.EMPTY,
            error_type=None if records else "empty",
        )
    )


def capture_reddit_posts(ticker: str, posts: list[dict], *, tool: str = "reddit") -> None:
    """Capture Reddit posts.

    Reddit's RSS feed carries no native sentiment label, so every post is a
    source-native *unlabeled* record; no sentiment value is invented. Post titles
    that cannot be dated are left undated (the validator fails them closed).
    """
    identity = _run_identity()
    if identity is None:
        return
    run_id, target_date = identity
    canonical = normalize_symbol(ticker)
    records: list[EvidenceRecord] = []
    seen: set[str] = set()
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        title = post.get("title")
        if not title:
            continue
        created = post.get("created_utc")
        posted = None
        if created:
            from datetime import datetime, timezone

            try:
                posted = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                posted = None
        subreddit = str(post.get("subreddit") or "")
        lineage = f"reddit|{title.lower()}|{created or ''}|{subreddit}"
        if lineage in seen:
            continue
        seen.add(lineage)
        records.append(
            build_sentiment_record(
                run_id=run_id,
                symbol_input=ticker,
                symbol_normalized=canonical,
                target_date=target_date,
                source_name="reddit",
                native_label=None,
                body=str(title),
                posted_at=posted,
                author_ref=f"r/{subreddit}" if subreddit else "",
                lineage_key=lineage,
                index=0,
            )
        )
    for record in records:
        capture_record(record)
        capture_origin(
            record.evidence_id,
            build_sentiment_origin(
                target_date=target_date,
                posted_at=record.observed_at,
                fetched_at=record.fetched_at,
            ),
        )
    capture_attempt(
        make_source_attempt(
            source="reddit",
            tool=tool,
            result_status=SourceResultStatus.SUCCESS if records else SourceResultStatus.EMPTY,
            error_type=None if records else "empty",
        )
    )


# ---------------------------------------------------------------------------
# Fundamentals (SEC facts with filed date)
# ---------------------------------------------------------------------------


def capture_sec_statement_facts(
    ticker: str,
    facts: dict,
    *,
    freq: str,
    tool: str,
) -> None:
    """Capture SEC statement facts, preserving the *filed* date per fact.

    ``facts`` is the typed return of
    :func:`tradingagents.dataflows.sec_edgar.structured_statement_facts`
    (``{kind: {metric_id: [{period_end, filed, value, unit, accn}, ...]}}``).
    Every metric uses the latest period as known on/before the target; the
    record's ``observed_at`` is the filed date, so the gate can prove
    availability. A missing filed date is left undated and fails closed later.
    """
    identity = _run_identity()
    if identity is None:
        return
    run_id, target_date = identity
    canonical = normalize_symbol(ticker)
    records: list[EvidenceRecord] = []
    from decimal import Decimal

    for kind, metrics in (facts or {}).items():
        if not isinstance(metrics, dict):
            continue
        for metric_id, rows in metrics.items():
            if not isinstance(rows, list):
                continue
            latest = _latest_as_of(rows, target_date)
            if latest is None:
                continue
            raw_value = latest.get("value")
            # Fail closed: a None/bool/non-finite/malformed value is skipped, never
            # coerced. This keeps capture from raising and never breaks the tool.
            if raw_value is None or isinstance(raw_value, bool):
                continue
            try:
                value = Decimal(str(raw_value))
            except (ArithmeticError, ValueError, TypeError):
                continue
            if not value.is_finite():
                continue
            try:
                record = build_sec_fundamentals_record(
                    run_id=run_id,
                    symbol_input=ticker,
                    symbol_normalized=canonical,
                    target_date=target_date,
                    metric_name=metric_id,
                    value_raw=str(raw_value),
                    value_normalized=value,
                    unit_raw=str(latest.get("unit") or ""),
                    filed_date=str(latest.get("filed") or ""),
                    period_end=str(latest.get("period_end") or ""),
                    source_ref=f"sec:{kind}:{latest.get('accn') or ''}:{metric_id}",
                )
            except Exception:  # noqa: BLE001 — a bad row is skipped, never fabricated
                continue
            records.append(record)
            # ADR-010: genuine fiscal period end (observation) + filed date
            # (availability) as distinct typed roles, plus the unit semantics.
            capture_origin(
                record.evidence_id,
                build_sec_origin(
                    target_date=target_date,
                    filed_date=str(latest.get("filed") or ""),
                    period_end=str(latest.get("period_end") or ""),
                    unit=str(latest.get("unit") or ""),
                    fetched_at=record.fetched_at,
                ),
            )
    for record in records:
        capture_record(record)
    capture_attempt(
        make_source_attempt(
            source="sec_edgar",
            tool=tool,
            result_status=SourceResultStatus.SUCCESS if records else SourceResultStatus.EMPTY,
            error_type=None if records else "empty",
        )
    )


def _latest_as_of(rows: list[dict], target_date: str) -> dict | None:
    """The row with the latest period end filed on or before ``target_date``."""
    from tradingagents.evidence.policy import to_date

    target = to_date(target_date)
    if target is None:
        return None
    eligible: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        filed = to_date(row.get("filed"))
        end = to_date(row.get("period_end"))
        if filed is None or end is None:
            continue
        if filed <= target:
            eligible.append(row)
    if not eligible:
        return None
    return max(eligible, key=lambda r: str(r.get("period_end")))

# ---------------------------------------------------------------------------
# Fundamentals (Alpha Vantage statement JSON — no filing date)
# ---------------------------------------------------------------------------

# Alpha Vantage statement fields worth capturing. Only stable, amount-like
# fields are captured; unknown fields are skipped (never invented as a metric).
_AV_STATEMENT_FIELDS = {
    "balance_sheet": ("totalAssets", "totalLiabilities", "totalShareholderEquity"),
    "income_statement": ("totalRevenue", "netIncome"),
    "cashflow": ("operatingCashflow",),
}


def capture_alpha_vantage_statement(
    ticker: str,
    response,
    kind: str,
    tool: str,
) -> None:
    """Capture Alpha Vantage statement reports as typed fundamentals evidence.

    The statement JSON carries a ``fiscalDateEnding`` but **no filing date**, so
    each captured record is left undated (``observed_at`` None); the per-record
    validator then fails it closed (a period end is not availability), rather
    than assuming the figure was public on the target date. A non-JSON body, a
    non-dict payload, or no usable amount is a no-op (the caller still receives
    its value unchanged).
    """
    identity = _run_identity()
    if identity is None:
        return

    def _empty(error_type: str) -> None:
        # One generic unsupported/empty attempt for this operated source; the
        # caller still receives its value unchanged. Never a fabricated grade.
        capture_attempt(
            make_source_attempt(
                source="alpha_vantage", tool=tool,
                result_status=SourceResultStatus.EMPTY, error_type=error_type,
            )
        )

    if not isinstance(response, str):
        _empty("unsupported")
        return
    try:
        payload = json.loads(response)
    except (ValueError, TypeError):
        _empty("malformed")
        return
    if not isinstance(payload, dict):
        _empty("malformed")
        return
    reports = payload.get("quarterlyReports") or payload.get("annualReports")
    if not isinstance(reports, list) or not reports:
        _empty("empty")
        return
    run_id, target_date = identity
    canonical = normalize_symbol(ticker)
    fields = _AV_STATEMENT_FIELDS.get(kind, ())
    # Use only the most recent report already on or before the target date.
    eligible = [r for r in reports if isinstance(r, dict)]
    latest = _av_latest_report(eligible, target_date)
    if latest is None:
        _empty("empty")
        return
    from decimal import Decimal

    from tradingagents.evidence.vendor_adapters import build_alpha_vantage_fundamentals_record

    # Preserve the vendor-reported currency; never assume USD. Each report may
    # carry ``reportedCurrency``; fall back to the payload-level value, and if
    # neither is present leave it empty (not hardcoded) so the unit is honest.
    payload_currency = str(payload.get("reportedCurrency") or "").strip()
    records = []
    for field_name in fields:
        raw = latest.get(field_name)
        if raw in (None, "", "None", "-"):
            continue
        try:
            value = Decimal(str(raw))
        except ArithmeticError:
            continue
        currency = str(latest.get("reportedCurrency") or payload_currency).strip()
        records.append(
            build_alpha_vantage_fundamentals_record(
                run_id=run_id,
                symbol_input=ticker,
                symbol_normalized=canonical,
                target_date=target_date,
                metric_name=field_name,
                value_raw=str(raw),
                value_normalized=value,
                unit_raw=currency,
                fiscal_period_end=str(latest.get("fiscalDateEnding") or ""),
                source_ref=f"alpha_vantage:{kind}:{field_name}",
            )
        )
    for record in records:
        capture_record(record)
        # ADR-010: period end only (no filing date), so availability stays None
        # (unavailable for historical proof); the genuine fiscal end is kept as
        # the observation date.
        capture_origin(
            record.evidence_id,
            build_alpha_vantage_origin(
                target_date=target_date,
                fiscal_period_end=str(latest.get("fiscalDateEnding") or ""),
                unit=str(currency),
                fetched_at=record.fetched_at,
            ),
        )
    capture_attempt(
        make_source_attempt(
            source="alpha_vantage",
            tool=tool,
            result_status=SourceResultStatus.SUCCESS if records else SourceResultStatus.EMPTY,
            error_type=None if records else "unsupported",
        )
    )


def _av_latest_report(reports: list[dict], target_date: str) -> dict | None:
    """The most recent AV statement report on or before ``target_date``."""
    from tradingagents.evidence.policy import to_date

    target = to_date(target_date)
    if target is None:
        return None
    eligible = []
    for report in reports:
        end = to_date(report.get("fiscalDateEnding"))
        if end is None:
            continue
        if end <= target:
            eligible.append(report)
    if not eligible:
        return None
    return max(eligible, key=lambda r: str(r.get("fiscalDateEnding")))


# ---------------------------------------------------------------------------
# Fundamentals (yfinance statement DataFrames — period-end only, NO filing date)
# ---------------------------------------------------------------------------

# yfinance statement DataFrame row labels worth capturing, mapped to stable ids.
_YF_STATEMENT_METRICS = {
    "balance_sheet": {"Total Assets": "total_assets", "Total Liabilities Net Minority Interest": "total_liabilities"},
    "income_statement": {"Total Revenue": "revenue", "Net Income": "net_income"},
    "cashflow": {"Operating Cash Flow": "operating_cash_flow"},
}


def capture_yfinance_statement(
    ticker: str,
    data,
    kind: str,
    tool: str,
) -> None:
    """Capture a yfinance statement DataFrame's latest period as fundamentals.

    yfinance statements are dated by **fiscal period end** only and carry no
    filing date, so no availability date exists. The record is therefore captured
    with ``observed_at=None`` (availability unknown) and the period end kept only
    in the ``source_ref`` lineage; the per-record validator then fails it
    undated/Low. A filing date is NEVER invented. A missing/empty/garbage frame or
    a non-numeric cell is a no-op for that row (never fabricated).
    """
    identity = _run_identity()
    if identity is None:
        return
    try:
        import pandas as pd
    except Exception:  # noqa: BLE001 — pandas is a runtime dep, but fail safe
        pd = None
    if pd is None or data is None or getattr(data, "empty", True):
        capture_attempt(
            make_source_attempt(
                source="yfinance", tool=tool,
                result_status=SourceResultStatus.EMPTY, error_type="empty",
            )
        )
        return
    run_id, target_date = identity
    canonical = normalize_symbol(ticker)
    metrics = _YF_STATEMENT_METRICS.get(kind, {})
    # Latest period column on/before the target (period end is not availability,
    # so the target filter never *adds* availability — it only bounds look-ahead).
    from tradingagents.evidence.policy import to_date
    from tradingagents.evidence.vendor_adapters import build_alpha_vantage_fundamentals_record

    columns = list(getattr(data, "columns", None) if getattr(data, "columns", None) is not None else [])
    eligible = []
    target = to_date(target_date)
    for col in columns:
        end = to_date(col if isinstance(col, str) else str(col)[:10])
        if end is not None and (target is None or end <= target):
            eligible.append((end, col))
    records = []
    if eligible:
        end, col = max(eligible, key=lambda x: x[0])
        for label, metric_id in metrics.items():
            if label not in data.index:
                continue
            raw = data.loc[label, col]
            try:
                from decimal import Decimal

                if raw is None or isinstance(raw, bool):
                    continue
                value = Decimal(str(raw))
                if not value.is_finite():
                    continue
            except Exception:  # noqa: BLE001 — a bad cell is skipped, not fabricated
                continue
            records.append(
                build_alpha_vantage_fundamentals_record(
                    run_id=run_id,
                    symbol_input=ticker,
                    symbol_normalized=canonical,
                    target_date=target_date,
                    metric_name=metric_id,
                    value_raw=str(raw),
                    value_normalized=value,
                    unit_raw="USD",
                    fiscal_period_end=end.isoformat(),
                    source_ref=f"yfinance:{kind}:{metric_id}",
                )
            )
    for record in records:
        capture_record(record)
        # ADR-010: yfinance carries a period end but no filing date; availability
        # stays None (never invented from the target/fetch time).
        capture_origin(
            record.evidence_id,
            build_alpha_vantage_origin(
                target_date=target_date,
                fiscal_period_end=end.isoformat(),
                unit="USD",
                fetched_at=record.fetched_at,
            ),
        )
    capture_attempt(
        make_source_attempt(
            source="yfinance",
            tool=tool,
            # The 7-field SourceAttempt enum is frozen (success/empty/failed/
            # skipped); "no usable structured rows" is encoded as EMPTY with a
            # generic ``unsupported`` classification, never a fabricated grade.
            result_status=SourceResultStatus.SUCCESS if records else SourceResultStatus.EMPTY,
            error_type=None if records else "unsupported",
        )
    )


def capture_not_attempted(feeds: Iterable[str]) -> None:
    """Record configured-but-unoperated feeds in a SEPARATE non-attempt channel.

    These are NOT operated attempts: they never enter the SourceAttempt ledger and
    never count toward ``source_count``. They are kept only as explicit
    ``not_attempted`` metadata for audit honesty.
    """
    collector = get_active_collector()
    if collector is None:
        return
    for feed in feeds or []:
        collector.note_not_attempted(str(feed))


def capture_sentiment_source_failure(ticker: str, source: str, tool: str, *, error_type: str) -> None:
    """Record a failed/unsupported sentiment source attempt (sanitized).

    Used when a StockTwits/Reddit fetch fails or returns nothing usable: the data
    was genuinely operated but produced no evidence, so exactly ONE generic
    ``failed``/``empty`` attempt is recorded (never a fabricated success, never an
    attempt for a feed that was not called). ``error_type`` is a short
    classification only; no URL/body/exception text is stored.
    """
    identity = _run_identity()
    if identity is None:
        return
    capture_attempt(
        make_source_attempt(
            source=source,
            tool=tool,
            result_status=SourceResultStatus.FAILED,
            error_type=error_type,
        )
    )
