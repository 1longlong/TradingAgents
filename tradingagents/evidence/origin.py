"""Typed, versioned, JSON-safe ORIGIN metadata for evidence records (ADR-010).

The locked :class:`~tradingagents.evidence.models.EvidenceRecord` has exactly 20
fields and the :class:`~tradingagents.evidence.models.SourceAttempt` exactly 7
(INV-4). Neither may grow a field, so the *semantics* of a record's dates and
units — which a claim must be validated against — are carried here as a separate,
versioned sibling keyed by ``evidence_id``.

The whole point of this module is that four dates that are easy to conflate stay
**explicitly distinct**:

- ``target_date`` — the requested trade date the run is evaluated "as of";
- ``observation_date`` — the fiscal period end / observation date the record is
  *about* (e.g. an SEC ``period_end``);
- ``availability_date`` — when the fact became public (e.g. an SEC **filed**
  date, a news **published** date), i.e. the earliest it could be known;
- ``published_at`` / ``filed_at`` — the vendor timestamp (datetime, timezone kept
  when the vendor supplies one), distinct from the bare availability *date*;
- ``retrieved_at`` — when this run fetched the record (``fetched_at``).

``date_basis`` names what the record's own ``observed_at`` means, so a consumer
never guesses. ``value_scale`` / ``unit`` / ``currency`` record the unit
semantics the value is expressed in (with no speculative FX).

This sibling never invents a date or a unit. A missing/unknown field stays
``None``; a default vendor row with no filing date (yfinance / Alpha Vantage
fundamentals) therefore stays unavailable for historical proof. An unknown
``schema_version`` is treated as unverifiable by the validator, never coerced.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from tradingagents.evidence.models import _json_safe, quantize_decimal

ORIGIN_SCHEMA_VERSION = "1.0"

# The state channel on the production AgentState. A mapping ``evidence_id ->
# serialized OriginMetadata``. An undeclared state key would be silently dropped
# by LangGraph checkpointing, so the graph integration declares this channel.
ORIGIN_STATE_KEY = "data_quality_origin_metadata"

# Defect-1 (ADR-010 amendment): evidence ids whose origin metadata was captured
# MORE THAN ONCE with different values, or which otherwise lost origin trust. A
# conflicted id is UNVERIFIABLE downstream: :func:`origin_records_from_state`
# drops it from the trusted map even if a stale origin value survives in
# ``ORIGIN_STATE_KEY``, so no consumer (claim validator / output boundary) can
# silently re-trust it. Declared on AgentState so a checkpoint/resume retains it.
ORIGIN_CONFLICTED_STATE_KEY = "data_quality_origin_conflicted_ids"

# The explicit tombstone channel (canonical value). A dropped/excluded record id
# is NEVER re-trusted as evidence or as a persisted origin (no resurrection). The
# canonical key lives here so :func:`origin_records_from_state` can exclude
# tombstoned ids without an import cycle; ``ingest`` re-exports it as
# ``INGEST_DROPPED_STATE_KEY``.
ORIGIN_DROPPED_STATE_KEY = "data_quality_dropped_evidence_ids"

# The stable role names a claim's date can take. Every one is a distinct role; a
# claim asserted against one role is NEVER validated against a different one.
DATE_ROLE_TARGET = "target_date"
DATE_ROLE_OBSERVATION = "observation_date"
DATE_ROLE_AVAILABILITY = "availability_date"
DATE_ROLE_FILED_AT = "filed_at"
DATE_ROLE_PUBLISHED_AT = "published_at"
DATE_ROLE_RETRIEVED_AT = "retrieved_at"
DATE_ROLES: tuple[str, ...] = (
    DATE_ROLE_TARGET,
    DATE_ROLE_OBSERVATION,
    DATE_ROLE_AVAILABILITY,
    DATE_ROLE_FILED_AT,
    DATE_ROLE_PUBLISHED_AT,
    DATE_ROLE_RETRIEVED_AT,
)

# What a record's ``observed_at`` means. ``unknown`` is honest for a legacy or
# undated record and is never upgraded by assumption.
BASIS_FILED = "filed"
BASIS_PUBLISHED = "published"
BASIS_PERIOD_END = "period_end"
BASIS_UNKNOWN = "unknown"
DATE_BASES: tuple[str, ...] = (BASIS_FILED, BASIS_PUBLISHED, BASIS_PERIOD_END, BASIS_UNKNOWN)


@dataclass(frozen=True)
class OriginMetadata:
    """Typed origin/unit semantics for one evidence record (keyed by evidence id).

    Constructor validates/normalizes each field so a malformed value is surfaced
    (as ``None`` for a date, which the validator treats as unverifiable) rather
    than silently trusted. ``value_scale`` is a ``Decimal`` (``1`` for one,
    ``1000000`` for "millions"); ``currency`` is present only for a monetary
    amount.
    """

    target_date: str | None = None
    observation_date: str | None = None
    availability_date: str | None = None
    published_at: str | None = None
    filed_at: str | None = None
    retrieved_at: str | None = None
    date_basis: str = BASIS_UNKNOWN
    # ``value_scale`` is the multiplier the value is expressed in (1 for base
    # units, 1e6 for "millions"). ``None`` means the scale is UNKNOWN, not "one":
    # the producer sets ``SCALE_UNKNOWN`` only when the source does NOT declare a
    # base-unit scale, and the validator then refuses to verify a magnitude rather
    # than guessing. A producer that genuinely knows the source uses base units
    # passes ``Decimal("1")`` explicitly (``SCALE_BASE``).
    value_scale: Decimal | None = None
    unit: str = ""
    currency: str = ""
    period_end_source: str = "absent"
    schema_version: str = ORIGIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for date_field in (
            "target_date",
            "observation_date",
            "availability_date",
            "published_at",
            "filed_at",
            "retrieved_at",
        ):
            object.__setattr__(
                self, date_field, _normalize_dateish(getattr(self, date_field))
            )
        basis = str(self.date_basis or BASIS_UNKNOWN).strip().lower()
        object.__setattr__(
            self, "date_basis", basis if basis in DATE_BASES else BASIS_UNKNOWN
        )
        # Normalize the scale but NEVER launder a malformed/non-positive/non-finite
        # one into ``1``. Only a genuinely absent scale (``None``) stays unknown;
        # a provided-but-invalid scale collapses to ``None`` (unknown) so the
        # validator rejects rather than verifies a possibly wrong magnitude.
        object.__setattr__(self, "value_scale", _normalize_scale(self.value_scale))
        object.__setattr__(self, "unit", str(self.unit or "").strip())
        object.__setattr__(self, "currency", str(self.currency or "").strip().upper())
        object.__setattr__(
            self, "period_end_source", str(self.period_end_source or "absent").strip()
        )
        object.__setattr__(self, "schema_version", str(self.schema_version or ""))

    @property
    def scale_known(self) -> bool:
        """True iff the value's scale is a valid, positive, finite multiplier."""
        return (
            self.value_scale is not None
            and self.value_scale.is_finite()
            and self.value_scale > 0
        )

    def value_for_date_role(self, date_role: str) -> str | None:
        """The typed date value for ``date_role`` (``None`` when absent/unknown).

        Never substitutes a different role's value: a claim on the observation
        date is answered only by ``observation_date``; if it is unknown the result
        is ``None`` (unverifiable), not the target or availability date.
        """
        role = str(date_role or "").strip().lower()
        if role == DATE_ROLE_TARGET:
            return self.target_date
        if role == DATE_ROLE_OBSERVATION:
            return self.observation_date
        if role == DATE_ROLE_AVAILABILITY:
            return self.availability_date
        if role == DATE_ROLE_FILED_AT:
            return self.filed_at
        if role == DATE_ROLE_PUBLISHED_AT:
            return self.published_at
        if role == DATE_ROLE_RETRIEVED_AT:
            return self.retrieved_at
        return None

    def has_known_availability(self) -> bool:
        return bool(self.availability_date)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date,
            "observation_date": self.observation_date,
            "availability_date": self.availability_date,
            "published_at": self.published_at,
            "filed_at": self.filed_at,
            "retrieved_at": self.retrieved_at,
            "date_basis": self.date_basis,
            "value_scale": (
                _json_safe(self.value_scale) if self.value_scale is not None else None
            ),
            "unit": self.unit,
            "currency": self.currency,
            "period_end_source": self.period_end_source,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OriginMetadata:
        data = data or {}
        return cls(
            target_date=data.get("target_date"),
            observation_date=data.get("observation_date"),
            availability_date=data.get("availability_date"),
            published_at=data.get("published_at"),
            filed_at=data.get("filed_at"),
            retrieved_at=data.get("retrieved_at"),
            date_basis=str(data.get("date_basis", BASIS_UNKNOWN)),
            # A missing key is unknown (None); a present-but-malformed scale is
            # normalized to None by ``__post_init__`` (never coerced to 1).
            value_scale=data.get("value_scale"),
            unit=str(data.get("unit", "") or ""),
            currency=str(data.get("currency", "") or ""),
            period_end_source=str(data.get("period_end_source", "absent") or "absent"),
            schema_version=str(data.get("schema_version", ORIGIN_SCHEMA_VERSION) or ""),
        )


def _normalize_scale(value: Any) -> Decimal | None:
    """Normalize ``value_scale`` without ever laundering a bad value into ``1``.

    - ``None`` -> ``None`` (unknown; the source did not declare a base-unit scale).
    - a valid positive finite ``Decimal``/``int``/numeric ``str`` -> quantized.
    - a bool / NaN / inf / missing / non-positive / unparseable value -> ``None``
      (UNKNOWN, which the validator treats as unverifiable) — never ``1``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    scale = quantize_decimal(value)
    if scale is None or not scale.is_finite() or scale <= 0:
        return None
    return scale


# Documented, explicit base-unit scale for a source that genuinely reports base
# units. Producers pass this (not an omitted/None scale) when they know the unit.
SCALE_BASE = Decimal("1")


def _normalize_dateish(value: Any) -> str | None:
    """Keep a valid ISO date/datetime value; otherwise ``None`` (fail closed).

    Only a ``str``/``date``/``datetime`` is a vendor date. A bare ``int`` (e.g. an
    epoch like ``20260510``) or a ``bool`` is rejected rather than stringified and
    parsed as a compact calendar date — an ambiguous type must not become a
    trusted date. Among strings, only an unambiguous ISO-8601 date/datetime
    (``YYYY-MM-DD`` or a full ``YYYY-MM-DDTHH:MM...``) is accepted; other formats
    (``MM/DD/YYYY``, compact ``YYYYMMDD``, loose text) are rejected as ambiguous.
    A tz-aware datetime keeps its offset (so a timestamp role can be compared as
    an instant); a bare date is kept as ``YYYY-MM-DD``.
    """
    if value is None:
        return None
    from datetime import date as _date, datetime as _datetime

    if isinstance(value, bool):
        return None
    if isinstance(value, _datetime):
        return value.isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    if not isinstance(value, str):
        # int/float/list/etc. are not a vendor date string; never stringify.
        return None
    text = value.strip()
    if not text:
        return None
    if not _is_unambiguous_iso(text):
        return None
    try:
        _datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _is_unambiguous_iso(text: str) -> bool:
    """True iff ``text`` is an unambiguous ISO-8601 date or datetime.

    Requiring the ``YYYY-MM-DD`` prefix (dashes at fixed positions) rejects a
    compact ``YYYYMMDD`` / ``YYYYMMDDTHHMMSS`` form that ``fromisoformat`` would
    otherwise accept, and rejects locale-specific orders like ``MM/DD/YYYY``.
    """
    import re as _re

    if not _re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return False
    # No slashes/dots/commas or other separator drift; ISO uses '-' and ':'/'T'.
    return not _re.search(r"[/.,]", text)


def _parse_instant(value: str | None):
    """Parse a typed role value to a ``(datetime, granularity)`` or ``None``.

    ``granularity`` is ``"date"`` for a date-only value (``YYYY-MM-DD``) and
    ``"instant"`` for a value carrying a time component. A tz-aware instant is
    normalized to UTC; a naive datetime is treated as not tz-qualified yet but its
    time component is still preserved (so a wrong hour still differs).
    """
    if not value:
        return None
    from datetime import datetime as _datetime, timezone as _timezone

    text = str(value).strip()
    try:
        parsed = _datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    has_time = "T" in text or " " in text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_timezone.utc).replace(tzinfo=None)
    granularity = "instant" if has_time else "date"
    return parsed, granularity


# Roles whose semantics are a *timestamp* rather than a calendar day. A
# date-only source value can never prove an exact timestamp, and a timestamp
# comparison must be at instant granularity (a wrong hour/timezone must not pass
# merely because the calendar day matches).
TIMESTAMP_ROLES: frozenset[str] = frozenset(
    {DATE_ROLE_PUBLISHED_AT, DATE_ROLE_FILED_AT, DATE_ROLE_RETRIEVED_AT}
)
CALENDAR_ROLES: frozenset[str] = frozenset(
    {DATE_ROLE_TARGET, DATE_ROLE_OBSERVATION, DATE_ROLE_AVAILABILITY}
)


def date_from_role_value(value: str | None):
    """Calendar :class:`date` for a typed role value; ``None`` when unparseable.

    Used for the explicit calendar-day roles (target/observation/availability). A
    tz-aware timestamp normalizes to UTC before its calendar day is taken.
    """
    parsed = _parse_instant(value)
    return parsed[0].date() if parsed is not None else None


def dates_match(date_role: str, asserted: str | None, actual: str | None) -> str:
    """Compare an asserted typed date with the record's matching role value.

    Returns one of:

    - ``"match"`` — same granularity and same value (see below);
    - ``"mismatch"`` — both comparable but they differ;
    - ``"unverifiable"`` — missing/unparseable value, or the claim asserts a
      precision the source cannot prove.

    Granularity rule (honest, no intraday over-claim):

    - **Calendar roles** (target/observation/availability): compared at explicit
      day granularity. Two date-only values must share the same calendar day. A
      date-only asserted value against a timestamp source value matches only if
      they share the same UTC calendar day (day-granular; this does NOT prove the
      intraday time).
    - **Timestamp roles** (published_at/filed_at/retrieved_at): compared as
      normalized instants. Both sides must carry a time component; a date-only
      asserted value (or a date-only source value) is **unverifiable** for a
      timestamp role — a date can never prove an exact time. Two instants must be
      equal to the second; a same-calendar-day but different hour/timezone is a
      **mismatch**, not a match.
    """
    asserted_parsed = _parse_instant(asserted)
    actual_parsed = _parse_instant(actual)
    if asserted_parsed is None or actual_parsed is None:
        return "unverifiable"
    a_dt, a_gran = asserted_parsed
    b_dt, b_gran = actual_parsed
    role = str(date_role or "").strip().lower()
    if role in TIMESTAMP_ROLES:
        # An exact timestamp cannot be proven by a date-only value on either side.
        if a_gran != "instant" or b_gran != "instant":
            return "unverifiable"
        return "match" if a_dt == b_dt else "mismatch"
    # Calendar roles: day granularity (documented; no intraday proof is claimed).
    return "match" if a_dt.date() == b_dt.date() else "mismatch"


def _field(record: Any, name: str, default: Any = None) -> Any:
    """Read a field from a typed record or its serialized dict form."""
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def derive_origin_for_record(record: Any) -> OriginMetadata:
    """Build an honest origin for a record that lacks one (e.g. market records).

    Used at the gate for records produced by adapters that attach no origin
    (the market OHLCV adapter). It reads only the record's OWN locked fields:

    - ``date_basis``: market records carry an observation (trading-row) date, so
      their ``observed_at`` is an observation date (calendar day granularity);
    - ``observation_date`` = ``observed_at`` when it is date-granular;
    - ``target_date`` = the record's ``target_date``;
    - ``retrieved_at`` = ``fetched_at`` (a timestamp when it carries a time);
    - ``value_scale`` is ``SCALE_BASE`` only when the record declares a
      recognized base unit (a currency / ``shares`` / ``percent``); otherwise
      ``None`` (unknown) so a numeric claim against it is not silently verified.

    A category whose own producer already recorded a genuine origin (SEC fiscal
    period end vs filed; news published; AV/yfinance period-end-only) is NOT
    overridden — the collector's origin wins in :func:`merge` precedence.
    """
    from tradingagents.evidence.origin import BASIS_UNKNOWN  # local alias

    category = str(_field(record, "category", "") or "")
    observed = _field(record, "observed_at", None)
    unit = str(
        _field(record, "unit_normalized", "") or _field(record, "unit_raw", "") or ""
    )
    upper = unit.strip().upper()
    currency = upper if upper in _CURRENCIES else ""
    base_units = {"SHARES", "SHARE", "PERCENT", "%", "EPS"}
    scale = SCALE_BASE if (currency or upper in base_units) else None
    # Market records: observed_at is the trading-row (observation) date. The value
    # is a raw magnitude in the record's OWN declared unit (the adapter already
    # normalizes prices/volume), so the scale is base (1) — an exact claim in the
    # same declared unit is verifiable. The currency stays unknown when the unit is
    # not a recognized currency (`native_quote_currency`), so no currency is
    # invented; a claim that names a currency will not match an empty one only if
    # the record genuinely declares none.
    if category == "market":
        return OriginMetadata(
            target_date=_field(record, "target_date"),
            observation_date=observed,
            availability_date=None,
            retrieved_at=_field(record, "fetched_at"),
            date_basis="period_end" if observed else BASIS_UNKNOWN,
            value_scale=SCALE_BASE,
            unit=unit,
            currency=currency,
            period_end_source="vendor" if observed else "absent",
        )
    # Unknown-category fallback: never invent a role; only what the record says.
    return OriginMetadata(
        target_date=_field(record, "target_date"),
        observation_date=None,
        availability_date=None,
        retrieved_at=_field(record, "fetched_at"),
        date_basis=BASIS_UNKNOWN,
        value_scale=scale,
        unit=unit,
        currency=currency,
        period_end_source="absent",
    )


_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "CNY", "HKD", "CAD", "AUD", "CHF"})


def build_origin_map_from_records(
    records: list[Any],
    existing: dict[str, OriginMetadata] | None = None,
) -> dict[str, OriginMetadata]:
    """The origin map for a set of records, preferring captured origin.

    A record that already has a captured origin (from the vendor adapter) keeps
    it; a record with none gets a derived origin. This is what the gate attaches
    so every manifest record has a typed (never invented) origin.
    """
    existing = existing or {}
    out: dict[str, OriginMetadata] = {}
    for record in records or []:
        evidence_id = str(_field(record, "evidence_id", "") or "")
        if not evidence_id:
            continue
        out[evidence_id] = existing.get(evidence_id) or derive_origin_for_record(record)
    return out


def origin_records_from_state(state: dict[str, Any] | None) -> dict[str, OriginMetadata]:
    """Read ``evidence_id -> OriginMetadata`` from state (malformed rows skipped).

    A malformed row is omitted (fail safe) — never coerced into a fabricated
    origin. An id recorded in the DECLARED conflict channel
    (``ORIGIN_CONFLICTED_STATE_KEY``, Defect-1 / ADR-010 amendment) is DROPPED from
    the trusted map even if a stale origin value survives in ``ORIGIN_STATE_KEY``,
    so every consumer (claim validator / output boundary) treats it as
    unverifiable rather than re-trusting a first/last-wins origin. Likewise an id
    listed in the explicit tombstone channel (``data_quality_dropped_evidence_ids``)
    is EXCLUDED from the trusted map — a pruned/excluded record must never be
    re-trusted from a stale persisted origin (no resurrection).
    """
    if not isinstance(state, dict):
        return {}
    raw = state.get(ORIGIN_STATE_KEY)
    if not isinstance(raw, dict):
        return {}
    conflicted: set[str] = set()
    for evidence_id in state.get(ORIGIN_CONFLICTED_STATE_KEY) or []:
        if isinstance(evidence_id, str):
            conflicted.add(evidence_id)
    # Explicit tombstones are authoritative: a dropped id is never trusted even if
    # a stale origin value survives in ``ORIGIN_STATE_KEY``.
    dropped: set[str] = set()
    for evidence_id in state.get(ORIGIN_DROPPED_STATE_KEY) or []:
        if isinstance(evidence_id, str):
            dropped.add(evidence_id)
    out: dict[str, OriginMetadata] = {}
    for evidence_id, value in raw.items():
        if str(evidence_id) in conflicted or str(evidence_id) in dropped:
            # A conflicted/tombstoned id is untrustworthy: never expose an origin.
            continue
        if not isinstance(value, dict):
            continue
        try:
            out[str(evidence_id)] = OriginMetadata.from_dict(value)
        except Exception:  # noqa: BLE001 — a bad persisted row is skipped
            continue
    return out


def serialize_origin_map(origin_by_id: dict[str, OriginMetadata]) -> dict[str, Any]:
    """JSON-safe serialization of an origin map for the state channel."""
    return {str(k): v.to_dict() for k, v in sorted(origin_by_id.items())}
