"""Deterministic quality policy for the Data Quality Gate.

This module holds the *policy*, not the *verdict*: the threshold numbers that
the five validation classes and the quality/gate layers compare against. Every
threshold is a :class:`decimal.Decimal` so comparisons are exact and
reproducible. Ranges and cross-constraints are validated at construction, so a
misconfigured policy fails loudly rather than silently weakening the gate.

Consistency tolerances are configured **per metric**: price metrics and volume
are independently configurable via :class:`MetricTolerance` (a ``normal`` and a
``severe`` fraction per group). The top-level ``normal_conflict_fraction`` /
``severe_conflict_fraction`` remain as a backward-compatible default/fallback
for metrics without an explicit mapping, so existing callers keep working.

To guarantee a *frozen* policy: a caller-supplied mutable ``Mapping`` is
defensively copied at construction into a read-only :class:`MappingProxyType`,
and every :class:`MetricTolerance` is itself a frozen dataclass with its own
cross-constraint validation. Mutating the source mapping after construction
therefore cannot change the policy.

The only intended non-decimal knob is the minimum number of **independent**
sources required for a ``High`` quality verdict (``min_independent_sources``).

Exchange calendar: there is **no exchange-calendar dependency** in this
package. Freshness and look-ahead checks therefore use an explicit,
deterministic **business-day approximation** (Mon-Fri are business days;
Saturdays/Sundays are not). This is documented as a limitation: it does not
model exchange holidays, half-days, or early closes, so a freshness boundary
that falls on a market holiday may be off by one day. We deliberately add no new
dependency to model an exchange calendar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType

# Business-day approximation, documented above. We deliberately do not pull in
# an exchange-calendar library; document the limitation in the class docstring.
BUSINESS_DAYS: tuple[int, ...] = (0, 1, 2, 3, 4)  # Mon..Fri

_DECIMAL = Decimal

# Metric-group keys used to resolve a per-metric tolerance. Price metrics map to
# the "price" group; volume maps to the "volume" group. Unknown metrics resolve
# to the top-level fallback fractions.
GROUP_PRICE = "price"
GROUP_VOLUME = "volume"


def to_decimal(value, default=None) -> Decimal | None:
    """Coerce ``value`` to a ``Decimal``, returning ``default`` on failure."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return default
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return default
    try:
        return Decimal(text)
    except ArithmeticError:
        return default


def _require_positive_decimal(value: object, name: str) -> Decimal:
    """Return ``value`` as a positive ``Decimal`` or raise ``ValueError``."""
    dec = to_decimal(value)
    if dec is None or not dec.is_finite() or dec <= _DECIMAL("0"):
        raise ValueError(f"{name} must be a positive finite Decimal, got {value!r}")
    return dec


def _require_nonnegative_decimal(value: object, name: str) -> Decimal:
    dec = to_decimal(value)
    if dec is None or not dec.is_finite() or dec < _DECIMAL("0"):
        raise ValueError(f"{name} must be a nonnegative finite Decimal, got {value!r}")
    return dec


@dataclass(frozen=True)
class MetricTolerance:
    """Normal and severe consistency tolerances for one metric group.

    ``severe_conflict_fraction`` must be **strictly greater** than
    ``normal_conflict_fraction``, and ``normal_conflict_fraction`` must be
    strictly positive. Validated at construction.
    """

    normal_conflict_fraction: Decimal
    severe_conflict_fraction: Decimal

    def __post_init__(self) -> None:
        normal = _require_positive_decimal(
            self.normal_conflict_fraction, "normal_conflict_fraction"
        )
        severe = _require_positive_decimal(
            self.severe_conflict_fraction, "severe_conflict_fraction"
        )
        if severe <= normal:
            raise ValueError(
                "severe_conflict_fraction must be strictly greater than "
                f"normal_conflict_fraction, got {severe!r} and {normal!r}"
            )
        object.__setattr__(self, "normal_conflict_fraction", normal)
        object.__setattr__(self, "severe_conflict_fraction", severe)


@dataclass(frozen=True)
class MarketPolicy:
    """Deterministic thresholds for market/OHLCV validation.

    Consistency tolerances are per metric group (``price`` / ``volume``) via
    :class:`MetricTolerance`, with the top-level ``normal_conflict_fraction`` /
    ``severe_conflict_fraction`` acting as a backward-compatible fallback for
    metrics without an explicit mapping. A caller-supplied mutable mapping is
    defensively copied; mutating it after construction cannot change this policy.

    Attributes:
        policy_version: stable policy version string emitted with every verdict.
        freshness_width: max business-day age for a fresh record (>=1).
        normal_conflict_fraction: fallback normal tolerance fraction (backward
            compatible default, used only when a metric has no explicit mapping).
        severe_conflict_fraction: fallback severe tolerance fraction; must be
            strictly greater than ``normal_conflict_fraction``.
        metric_tolerances: read-only mapping of metric-group -> MetricTolerance.
        price_tolerance: tolerance for price metrics (open/high/low/close).
        volume_tolerance: tolerance for the volume metric.
        min_independent_sources: minimum number of *independent* sources for a
            ``High`` category verdict. Must be >=1.
        look_ahead_tolerance_days: how many calendar days of ``observed_at``
            after ``target_date`` are tolerated as wall-clock (not look-ahead)
            noise before it is treated as genuine look-ahead. Must be >=0.
    """

    policy_version: str = "1.0"
    freshness_width: Decimal = _DECIMAL("7")
    normal_conflict_fraction: Decimal = _DECIMAL("0.02")
    severe_conflict_fraction: Decimal = _DECIMAL("0.10")
    metric_tolerances: Mapping[str, MetricTolerance] = field(default_factory=dict)
    min_independent_sources: int = 2
    look_ahead_tolerance_days: int = 0
    market_source_name: str = "yfinance"

    def __post_init__(self) -> None:
        freshness_width = _require_positive_decimal(
            self.freshness_width, "freshness_width"
        )
        normal = _require_nonnegative_decimal(
            self.normal_conflict_fraction, "normal_conflict_fraction"
        )
        severe = _require_positive_decimal(
            self.severe_conflict_fraction, "severe_conflict_fraction"
        )
        if severe <= normal:
            raise ValueError(
                "severe_conflict_fraction must be strictly greater than "
                f"normal_conflict_fraction, got {severe!r} and {normal!r}"
            )
        if normal <= _DECIMAL("0"):
            raise ValueError(
                "normal_conflict_fraction must be strictly greater than 0"
            )
        if self.min_independent_sources < 1:
            raise ValueError(
                f"min_independent_sources must be >= 1, got "
                f"{self.min_independent_sources}"
            )
        if self.look_ahead_tolerance_days < 0:
            raise ValueError(
                f"look_ahead_tolerance_days must be >= 0, got "
                f"{self.look_ahead_tolerance_days}"
            )

        # Defensive copy of a caller-supplied mutable mapping into a read-only,
        # stable view; also normalizes each entry to a frozen MetricTolerance.
        source: Mapping[str, MetricTolerance] = self.metric_tolerances or {}
        copied: dict[str, MetricTolerance] = {}
        for key, value in dict(source).items():
            if isinstance(value, MetricTolerance):
                copied[key] = MetricTolerance(
                    normal_conflict_fraction=value.normal_conflict_fraction,
                    severe_conflict_fraction=value.severe_conflict_fraction,
                )
            else:
                # Allow callers to pass a plain dict of fractions
                # {"normal": Decimal, "severe": Decimal}.
                if isinstance(value, Mapping):
                    copied[key] = MetricTolerance(
                        normal_conflict_fraction=value.get(
                            "normal_conflict_fraction", value.get("normal")
                        ),
                        severe_conflict_fraction=value.get(
                            "severe_conflict_fraction", value.get("severe")
                        ),
                    )
                else:
                    raise ValueError(
                        f"metric_tolerances[{key!r}] must be a MetricTolerance "
                        f"or a dict, got {type(value).__name__}"
                    )
        object.__setattr__(self, "metric_tolerances", MappingProxyType(copied))
        object.__setattr__(
            self,
            "price_tolerance",
            MetricTolerance(
                normal_conflict_fraction=self._resolve_normal(GROUP_PRICE, normal),
                severe_conflict_fraction=self._resolve_severe(GROUP_PRICE, severe),
            ),
        )
        object.__setattr__(
            self,
            "volume_tolerance",
            MetricTolerance(
                normal_conflict_fraction=self._resolve_normal(GROUP_VOLUME, normal),
                severe_conflict_fraction=self._resolve_severe(GROUP_VOLUME, severe),
            ),
        )
        object.__setattr__(self, "freshness_width", freshness_width)
        object.__setattr__(self, "normal_conflict_fraction", normal)
        object.__setattr__(self, "severe_conflict_fraction", severe)

    # These resolve against the already-copied mapping; safe because __post_init__
    # runs once and the mapping was set on `self` just above.
    def _resolve_normal(self, group: str, fallback: Decimal) -> Decimal:
        tol = getattr(self, "metric_tolerances", None)
        if tol and group in tol:
            return _require_positive_decimal(
                tol[group].normal_conflict_fraction, f"{group} normal_conflict_fraction"
            )
        return fallback

    def _resolve_severe(self, group: str, fallback: Decimal) -> Decimal:
        tol = getattr(self, "metric_tolerances", None)
        if tol and group in tol:
            return _require_positive_decimal(
                tol[group].severe_conflict_fraction, f"{group} severe_conflict_fraction"
            )
        return fallback

    def tolerance_for(self, metric_name: str) -> MetricTolerance:
        """Resolve the :class:`MetricTolerance` for a metric.

        Price metrics map to the ``price`` group, ``volume`` to the ``volume``
        group, and any other metric falls back to the top-level
        ``normal_conflict_fraction`` / ``severe_conflict_fraction``.
        """
        if metric_name == "volume":
            group = GROUP_VOLUME
        elif metric_name in ("open", "high", "low", "close"):
            group = GROUP_PRICE
        else:
            return MetricTolerance(
                normal_conflict_fraction=self.normal_conflict_fraction,
                severe_conflict_fraction=self.severe_conflict_fraction,
            )
        return MetricTolerance(
            normal_conflict_fraction=self._resolve_normal(group, self.normal_conflict_fraction),
            severe_conflict_fraction=self._resolve_severe(group, self.severe_conflict_fraction),
        )


@dataclass(frozen=True)
class MarketRecordPolicy:
    """Per-record criticality mapping for market OHLCV metrics.

    ``close`` and ``volume`` are *critical*; ``open``/``high``/``low`` are
    *important*. This is part of the policy so the gate is deterministic and the
    mapping is not duplicated across modules.
    """

    policy_version: str = "1.0"

    def criticality_for(self, metric_name: str):
        """Return the :class:`~tradingagents.evidence.models.Criticality` for a
        market metric name. Unknown metrics default to ``IMPORTANT``."""
        from tradingagents.evidence.models import Criticality

        if metric_name in ("close", "volume"):
            return Criticality.CRITICAL
        if metric_name in ("open", "high", "low"):
            return Criticality.IMPORTANT
        return Criticality.IMPORTANT


def to_date(value) -> date | None:
    """Parse ``YYYY-MM-DD`` (or ISO datetime) to a :class:`date` or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def count_business_days(start: date, end: date) -> int:
    """Count of business days representing **age** from ``start`` to ``end``.

    Counts business days strictly after ``start`` through ``end`` inclusive, so
    that ``start == end`` (or any two dates on the same business day) yields
    ``0`` — an observation made on the target day is not stale. This is the
    documented deterministic business-day approximation; it does not model
    exchange holidays or half-days.
    """
    if end < start:
        return 0
    count = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() in BUSINESS_DAYS:
            count += 1
        cursor += timedelta(days=1)
    return count


DEFAULT_MARKET_POLICY = MarketPolicy()
DEFAULT_MARKET_RECORD_POLICY = MarketRecordPolicy()


@dataclass(frozen=True)
class GatePolicySet:
    """Bundle of the policies the gate operates on."""

    market: MarketPolicy = field(default_factory=lambda: DEFAULT_MARKET_POLICY)
    records: MarketRecordPolicy = field(default_factory=lambda: DEFAULT_MARKET_RECORD_POLICY)


# ---------------------------------------------------------------------------
# Stage 2: multi-category gate policy (market critical + optional categories)
# ---------------------------------------------------------------------------

# Authoritative category names for the multi-category gate. ``market`` is the
# critical, fail-closed category carried over from the original gate;
# ``fundamentals``, ``news``, and ``sentiment`` are optional categories. These
# names are the stable topic-level identifiers used in the evidence model, the
# gate output, and the report artifacts.
CATEGORY_MARKET = "market"
CATEGORY_FUNDAMENTALS = "fundamentals"
CATEGORY_NEWS = "news"
CATEGORY_SENTIMENT = "sentiment"

# The optional categories that the Stage 2 gate evaluates when trustworthy
# structured evidence is available. Kept in stable output order.
OPTIONAL_CATEGORIES: tuple[str, ...] = (
    CATEGORY_FUNDAMENTALS,
    CATEGORY_NEWS,
    CATEGORY_SENTIMENT,
)


class CategoryRole(str, Enum):
    """Whether a category is fail-closed critical or an optional degrade-only.

    ``CRITICAL`` categories (only ``market``) drive a ``blocked`` verdict on a
    hard failure and are the gate's ground truth. ``OPTIONAL`` categories may
    never block a run on their own: when their structured evidence is missing or
    untrustworthy they degrade the run under a versioned policy, but they never
    fail it closed.
    """

    CRITICAL = "critical"
    OPTIONAL = "optional"


# Reason codes for an explicit, deterministic unavailable/insufficient category
# result. Stable identifiers consumed by the gate and serialized in the report
# artifacts. ``unavailable_no_structured_source`` is used when no trustworthy
# structured data exists for the category (the true state for fundamentals,
# news, and sentiment in this codebase, which only persist prose reports);
# ``insufficient_structured_evidence`` is used on the degraded path when a
# category is evaluated but does not reach the policy's adequacy threshold.
REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE = "unavailable_no_structured_source"
REASON_INSUFFICIENT_STRUCTURED_EVIDENCE = "insufficient_structured_evidence"


@dataclass(frozen=True)
class CategoryPolicy:
    """Versioned policy governing one optional category of the multi-category gate.

    ``category`` is the stable category name (one of the optional categories).
    ``role`` is always ``OPTIONAL``. ``policy_version`` is the version stamped on
    every categorised result so audits can tell which policy produced it, and
    ``min_independent_sources`` is the minimum number of *independent* credible
    structured sources required before the category can ever be considered
    adequate. ``degrade_on_unavailable`` says whether a category with no
    trustworthy structured evidence lowers the whole gate to ``degraded``
    (default, per the Stage 2 design) rather than being silently skipped.

    The policy is frozen; a caller-supplied mutable value is unusable because
    every field is validated at construction and the object cannot diverge
    afterward.
    """

    category: str
    role: CategoryRole = CategoryRole.OPTIONAL
    policy_version: str = "1.0"
    min_independent_sources: int = 1
    degrade_on_unavailable: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.role, CategoryRole):
            object.__setattr__(self, "role", CategoryRole(str(self.role)))
        if self.role != CategoryRole.OPTIONAL:
            raise ValueError(
                f"CategoryPolicy.for_optional only supports OPTIONAL categories, "
                f"got role={self.role.value} for {self.category!r}"
            )
        if not str(self.category).strip():
            raise ValueError("category must be a non-empty name")
        if self.min_independent_sources < 1:
            raise ValueError("min_independent_sources must be >= 1")
        object.__setattr__(self, "category", str(self.category))
        object.__setattr__(self, "policy_version", str(self.policy_version))


@dataclass(frozen=True)
class MultiCategoryPolicy:
    """Versioned policy bundle for the multi-category gate.

    Combines the market (critical) policy with one :class:`CategoryPolicy` per
    optional category. ``market_role`` is always ``CRITICAL`` (fail closed).
    ``optional`` maps each optional category name to its ``CategoryPolicy``; a
    mutable caller-supplied mapping is defensively copied into a read-only view
    so it cannot diverge after construction.

    ``policy_version`` is the version stamped on the gate decision produced by a
    multi-category evaluation, so an audit can distinguish a Stage 1
    (market-only) decision from a Stage 2 (multi-category) decision.
    """

    policy_version: str = "2.0"
    market_role: CategoryRole = CategoryRole.CRITICAL
    optional: Mapping[str, CategoryPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.market_role, CategoryRole):
            object.__setattr__(self, "market_role", CategoryRole(str(self.market_role)))
        if self.market_role != CategoryRole.CRITICAL:
            raise ValueError("market_role must be CRITICAL (fail closed)")
        source: Mapping[str, CategoryPolicy] = self.optional or {}
        copied: dict[str, CategoryPolicy] = {}
        for key, value in dict(source).items():
            if isinstance(value, CategoryPolicy):
                copied[str(key)] = CategoryPolicy(
                    category=str(key),
                    role=CategoryRole.OPTIONAL,
                    policy_version=value.policy_version,
                    min_independent_sources=value.min_independent_sources,
                    degrade_on_unavailable=value.degrade_on_unavailable,
                )
            elif isinstance(value, Mapping):
                copied[str(key)] = CategoryPolicy(
                    category=str(key),
                    role=CategoryRole.OPTIONAL,
                    policy_version=str(value.get("policy_version", "1.0")),
                    min_independent_sources=int(
                        value.get("min_independent_sources", 1)
                    ),
                    degrade_on_unavailable=bool(
                        value.get("degrade_on_unavailable", True)
                    ),
                )
            else:
                raise ValueError(
                    f"optional[{key!r}] must be a CategoryPolicy or a dict, "
                    f"got {type(value).__name__}"
                )
        object.__setattr__(self, "optional", MappingProxyType(copied))
        object.__setattr__(self, "policy_version", str(self.policy_version))

    def category_role(self, category: str) -> CategoryRole:
        """The role of ``category`` under this policy.

        ``market`` is always CRITICAL; a category present in ``optional`` is
        OPTIONAL; an unknown category defaults to OPTIONAL so an unexpected name
        can never escalate to a critical, fail-closed role.
        """
        if category == CATEGORY_MARKET:
            return CategoryRole.CRITICAL
        if category in self.optional:
            return CategoryRole.OPTIONAL
        return CategoryRole.OPTIONAL


# Default policy bundle: a single CategoryPolicy for every optional category,
# with the documented ``degrade_on_unavailable`` behavior.
def build_default_multi_category_policy() -> MultiCategoryPolicy:
    """Construct the default multi-category gate policy bundle.

    Every optional category (fundamentals, news, sentiment) defaults to
    ``degrade_on_unavailable=True`` because, in the current codebase, these
    categories persist only prose reports and no trustworthy structured
    evidence — so the honest, deterministic result is a ``degraded`` gate, never
    a silent skip and never a manufactured ``normal``.
    """
    return MultiCategoryPolicy(
        optional={
            category: CategoryPolicy(category=category)
            for category in OPTIONAL_CATEGORIES
        }
    )


DEFAULT_MULTI_CATEGORY_POLICY = build_default_multi_category_policy()
