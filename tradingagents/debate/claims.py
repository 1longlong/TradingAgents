"""Deterministic exact-claim validation (ADR-010).

A cited evidence ID being *eligible* (known, High/Medium, on-or-before target) is
not proof that a model-written exact claim about that record — a specific date, a
specific amount, a specific unit — is correct. This module validates a typed
:class:`~tradingagents.debate.models.ClaimRecord` against the **actual manifest
record** and the record's **typed origin metadata** (genuine date roles + unit
semantics), and returns a deterministic verdict.

Design rules (authoritative):

- **Pure and deterministic.** No clock, no RNG, no network, no LLM. The same
  inputs yield the same :class:`ClaimValidation` regardless of insertion order.
- **Fail closed.** A missing/unknown/ambiguous date, an unknown schema version, a
  missing origin, a duplicate evidence ID with conflicting origin, a foreign
  ticker/run id, a Low/Blocked/future record, a non-finite/bool/unknown value, or a
  unit/currency/scale mismatch is ``rejected`` or ``unverified`` — never
  ``verified`` by default.
- **Date roles are distinct.** A claim on one role is compared only with that
  role's typed value (target vs observation vs availability vs timestamp). An SEC
  filed date is never treated as the fiscal period end, a news publication date is
  never the date of the financial figure it discusses, and a date-only source
  cannot prove a timestamp.
- **No speculative FX / unit coercion.** Exact currency/unit/scale compatibility is
  required; a mismatch is rejected, never converted.
- **Legacy is not verified.** A claim with no typed constraint is ``unverified``
  (the legacy free-text path); it can never be treated as verified exact evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from tradingagents.debate.models import CLAIM_SCHEMA_VERSION, ClaimRecord
from tradingagents.evidence.origin import (
    DATE_ROLES,
    OriginMetadata,
    date_from_role_value,
    dates_match,
)
from tradingagents.evidence.policy import to_date

# Stable verdicts.
STATUS_VERIFIED = "verified"
STATUS_REJECTED = "rejected"
STATUS_UNVERIFIED = "unverified"

# Stable reason codes (auditable; consumed by the trace/report).
REASON_OK = "claim_matches_evidence"
REASON_NO_TYPED_CONSTRAINT = "claim_untyped_legacy"
REASON_UNKNOWN_SCHEMA = "claim_unknown_schema_version"
REASON_NO_EVIDENCE = "claim_no_cited_evidence"
REASON_UNKNOWN_EVIDENCE = "claim_evidence_unknown"
REASON_LOW_OR_BLOCKED = "claim_evidence_not_valid_status"
REASON_FUTURE = "claim_evidence_future"
REASON_FOREIGN_RUN = "claim_evidence_foreign_run"
REASON_TICKER_MISMATCH = "claim_ticker_mismatch"
REASON_DUPLICATE_ORIGIN = "claim_duplicate_conflicting_origin"
REASON_MISSING_ORIGIN = "claim_origin_unknown"
REASON_UNKNOWN_DATE_ROLE = "claim_unknown_date_role"
REASON_DATE_MISSING = "claim_date_missing_or_unparseable"
REASON_DATE_ROLE_UNKNOWN = "claim_date_role_value_unknown"
REASON_DATE_MISMATCH = "claim_date_mismatch"
REASON_DATE_UNVERIFIABLE = "claim_date_unverifiable"
REASON_VALUE_MISSING = "claim_value_missing_or_invalid"
REASON_VALUE_MISMATCH = "claim_value_mismatch"
REASON_UNIT_MISMATCH = "claim_unit_or_currency_mismatch"
REASON_UNIT_UNKNOWN = "claim_unit_or_currency_unknown"
REASON_SCALE_UNKNOWN = "claim_value_scale_unknown"
REASON_SCALE_MISMATCH = "claim_value_scale_mismatch"
REASON_SCALE_INVALID = "claim_value_scale_invalid"
REASON_METRIC_MISMATCH = "claim_metric_mismatch"
REASON_METRIC_MISSING = "claim_metric_missing"
REASON_TARGET_UNKNOWN = "claim_target_date_unknown"
REASON_OBSERVATION_UNKNOWN = "claim_record_observation_unknown"
REASON_RECORD_RUN_UNKNOWN = "claim_record_run_id_unknown"
REASON_ORIGIN_INCONSISTENT = "claim_origin_inconsistent_with_record"
REASON_AVAILABILITY_FUTURE = "claim_record_availability_future"
REASON_INCONSISTENT_SUPPORT = "claim_inconsistent_multi_evidence_support"
REASON_INVALID_VALUE_CONSTRAINT = "claim_invalid_value_constraint"
REASON_INVALID_SCHEMA = "claim_invalid_schema_version"


# Date roles whose typed value denotes when the fact became public / was observed
# for availability; these must not be after the target regardless of which role a
# claim asserts (point-in-time integrity). ``retrieved_at`` is deliberately NOT in
# this set: a historical run may legitimately retrieve data later than the target.
_AVAILABILITY_ROLES = ("availability_date", "filed_at", "published_at")


@dataclass(frozen=True)
class ClaimValidation:
    """The deterministic verdict for one typed exact claim."""

    status: str
    reason: str
    evidence_ids: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    # The cited IDs that ACTUALLY validated this claim (only populated for a
    # ``verified`` verdict). A failed cited ID is never in this list, so a good ID
    # can never launder a mismatching co-cited ID into verified evidence.
    support_evidence_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", str(self.status))
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "evidence_ids", list(self.evidence_ids or []))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))
        object.__setattr__(
            self, "support_evidence_ids", list(self.support_evidence_ids or [])
        )

    @property
    def is_verified(self) -> bool:
        return self.status == STATUS_VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
            "support_evidence_ids": list(self.support_evidence_ids),
            "provenance": dict(self.provenance),
        }


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        magnitude = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if not magnitude.is_finite():
        return None
    return magnitude


# Unit aliases normalize SHAPE only — never a currency from a scale word. Mapping
# ``million``/``mn``/``bn`` to USD would invent a currency; scale is a separate
# field and is never inferred from the unit text.
_UNIT_ALIASES = {
    "us$": "usd",
    "usd": "usd",
    "dollars": "usd",
    "$": "usd",
    "shares": "shares",
    "share": "shares",
    "percent": "percent",
    "%": "percent",
    "pct": "percent",
    "ratio": "ratio",
    "dimensionless": "ratio",
    "unitless": "ratio",
}


def _normalize_unit(unit: str) -> str:
    text = str(unit or "").strip().lower().replace(" ", "")
    return _UNIT_ALIASES.get(text, text)


_CURRENCY_UNITS = frozenset({"usd", "eur", "gbp", "jpy", "cny", "hkd", "cad", "aud", "chf"})

# Numeric DIMENSIONS. Two exact numbers may only be compared when they share a
# dimension: money (a currency), ``shares``, ``percent``, or an explicit
# dimensionless ``ratio``. A ratio and a percent are NOT the same dimension (50%
# != 0.5 as a bare ratio value) and neither is shares — this is never inferred.
DIM_MONEY = "money"
DIM_SHARES = "shares"
DIM_PERCENT = "percent"
DIM_RATIO = "ratio"


def _dimension(normalized_unit: str) -> str | None:
    """The dimension of a normalized unit, or ``None`` when unknown."""
    if normalized_unit in _CURRENCY_UNITS:
        return DIM_MONEY
    if normalized_unit == "shares":
        return DIM_SHARES
    if normalized_unit == "percent":
        return DIM_PERCENT
    if normalized_unit == "ratio":
        return DIM_RATIO
    return None


def validate_claim(
    claim: ClaimRecord,
    *,
    origin_by_id: dict[str, OriginMetadata],
    records_by_id: dict[str, dict[str, Any]],
    target_date: str | None,
    expected_symbol: str | None = None,
    expected_run_id: str | None = None,
    duplicate_origin_ids: set[str] | None = None,
) -> ClaimValidation:
    """Validate one typed exact claim against manifest records + typed origin.

    Args:
        claim: the typed exact claim.
        origin_by_id: ``evidence_id -> OriginMetadata`` for this run.
        records_by_id: ``evidence_id -> serialized EvidenceRecord dict``.
        target_date: the requested trade date (for future look-ahead rejection).
        expected_symbol: the run's normalized ticker (mismatch -> rejected).
        expected_run_id: the run's reproducible evidence run id (foreign -> rejected).
        duplicate_origin_ids: evidence IDs whose origin metadata is duplicated with
            conflicting values (-> unverifiable).

    Returns:
        A :class:`ClaimValidation` with a stable status + reason + provenance.
    """
    duplicate_origin_ids = duplicate_origin_ids or set()
    provenance: dict[str, Any] = {
        "metric": claim.metric,
        "date_role": claim.date_role,
        "asserted_date": claim.date,
        "asserted_value": claim.value,
        "unit": claim.unit,
        "currency": claim.currency,
        "value_scale": claim.value_scale,
        "schema_version": claim.schema_version,
    }

    # The envelope must declare a KNOWN, non-empty claim-contract version. An
    # empty/unknown version is unverifiable (never assume a shape).
    if not claim.schema_version or claim.schema_version != CLAIM_SCHEMA_VERSION:
        reason = REASON_INVALID_SCHEMA if not claim.schema_version else REASON_UNKNOWN_SCHEMA
        return ClaimValidation(STATUS_UNVERIFIED, reason, claim.evidence_ids, provenance)

    # Legacy/untyped claim: not verified exact evidence.
    if not claim.has_typed_constraint:
        return ClaimValidation(
            STATUS_UNVERIFIED, REASON_NO_TYPED_CONSTRAINT, claim.evidence_ids, provenance
        )

    # An ASSERTED-but-invalid value/scale constraint is REJECTED, never dropped
    # (dropping it would let a malformed magnitude verify by omission).
    if claim.value_invalid:
        return ClaimValidation(
            STATUS_REJECTED, REASON_INVALID_VALUE_CONSTRAINT, claim.evidence_ids, provenance
        )
    if claim.value_scale_invalid:
        return ClaimValidation(
            STATUS_REJECTED, REASON_SCALE_INVALID, claim.evidence_ids, provenance
        )

    evidence_ids = [eid for eid in claim.evidence_ids if eid]
    if not evidence_ids:
        return ClaimValidation(STATUS_REJECTED, REASON_NO_EVIDENCE, [], provenance)

    # Identity + point-in-time gating needs a valid target date; a missing/invalid
    # target makes look-ahead unprovable -> unverified (fail closed, not skipped).
    target = to_date(target_date)
    if target is None:
        return ClaimValidation(STATUS_UNVERIFIED, REASON_TARGET_UNKNOWN, evidence_ids, provenance)

    verified_origins: list[tuple[str, OriginMetadata, dict[str, Any]]] = []
    for evidence_id in evidence_ids:
        if evidence_id in duplicate_origin_ids:
            return ClaimValidation(
                STATUS_UNVERIFIED, REASON_DUPLICATE_ORIGIN, evidence_ids, provenance
            )
        record = records_by_id.get(evidence_id)
        if record is None:
            return ClaimValidation(
                STATUS_REJECTED, REASON_UNKNOWN_EVIDENCE, evidence_ids, provenance
            )
        status = str(record.get("quality_status", "") or "")
        if status not in ("High", "Medium"):
            return ClaimValidation(
                STATUS_REJECTED, REASON_LOW_OR_BLOCKED, evidence_ids, provenance
            )
        # Run/ticker identity: a record from another symbol/run is never a proof.
        if expected_symbol and str(
            record.get("ticker_normalized", "") or ""
        ).upper() != expected_symbol.upper():
            return ClaimValidation(
                STATUS_REJECTED, REASON_TICKER_MISMATCH, evidence_ids, provenance
            )
        # A record with NO run id cannot be tied to this run -> cannot prove
        # membership (previously a missing run_id bypassed the foreign-run check).
        record_run_id = record.get("run_id")
        if not record_run_id:
            return ClaimValidation(
                STATUS_UNVERIFIED, REASON_RECORD_RUN_UNKNOWN, evidence_ids, provenance
            )
        if expected_run_id and str(record_run_id) != str(expected_run_id):
            return ClaimValidation(
                STATUS_REJECTED, REASON_FOREIGN_RUN, evidence_ids, provenance
            )
        # Point in time: a valid, known observation date is REQUIRED (a missing /
        # malformed observed_at cannot prove the fact was known by the target).
        observed = to_date(record.get("observed_at"))
        if observed is None:
            return ClaimValidation(
                STATUS_UNVERIFIED, REASON_OBSERVATION_UNKNOWN, evidence_ids, provenance
            )
        if observed > target:
            return ClaimValidation(STATUS_REJECTED, REASON_FUTURE, evidence_ids, provenance)
        origin = origin_by_id.get(evidence_id)
        if origin is None:
            return ClaimValidation(
                STATUS_UNVERIFIED, REASON_MISSING_ORIGIN, evidence_ids, provenance
            )
        # Point-in-time integrity independent of the asserted role: whatever role a
        # claim names, the record's availability/filed/published instant must not
        # be after the target (a historical run retrieving later is fine; the
        # RETRIEVED instant is a distinct role and is NOT checked here).
        for role in _AVAILABILITY_ROLES:
            role_day = date_from_role_value(origin.value_for_date_role(role))
            if role_day is not None and role_day > target:
                return ClaimValidation(
                    STATUS_REJECTED, REASON_AVAILABILITY_FUTURE, evidence_ids, provenance
                )
        # Origin must AGREE with the actual record on the shared facts it carries,
        # so a typed-but-wrong origin cannot vouch for a mismatching record.
        consistency = _origin_record_consistency(origin, record, target)
        if consistency is not None:
            provenance["origin_inconsistent"] = consistency
            return ClaimValidation(
                STATUS_UNVERIFIED, REASON_ORIGIN_INCONSISTENT, evidence_ids, provenance
            )
        verified_origins.append((evidence_id, origin, record))

    # EVERY cited ID used as support must independently corroborate the asserted
    # facts. A single mismatching co-cited ID means the whole support set is
    # inconsistent: never promote the passing ID alone (no laundering of a wrong B
    # by a good A). Conservative: the claim is rejected / unverified, not verified.
    support: list[str] = []
    first_failure: tuple[str, str] | None = None
    for evidence_id, origin, record in verified_origins:
        verdict = _validate_one(claim, origin, record, target)
        if verdict is None:
            support.append(evidence_id)
        elif first_failure is None:
            first_failure = verdict
    if first_failure is not None or not support:
        if len(verified_origins) > 1:
            # Multiple cited IDs where at least one fails: the support set is
            # inconsistent. Conservative: unverified (never promote the passing
            # ID alone — that would launder a wrong co-cited ID).
            return ClaimValidation(
                STATUS_UNVERIFIED, REASON_INCONSISTENT_SUPPORT, evidence_ids, provenance
            )
        status, reason = first_failure or (STATUS_UNVERIFIED, REASON_INCONSISTENT_SUPPORT)
        return ClaimValidation(status, reason, evidence_ids, provenance)
    return ClaimValidation(
        STATUS_VERIFIED, REASON_OK, evidence_ids, provenance, support_evidence_ids=support
    )


def _origin_record_consistency(
    origin: OriginMetadata, record: dict[str, Any], target=None
) -> str | None:
    """Return a short inconsistency reason when the origin contradicts the record.

    Checks the shared facts a typed origin repeats from the record so a typed (but
    wrong) origin cannot vouch for a mismatching record:

    - ``target_date`` (when both known) must agree;
    - an ``observation_date`` that duplicates the record's ``observed_at`` role
      must agree with ``observed_at`` when the origin basis is a period end / the
      record's observed_at is present;
    - a declared ``unit`` must agree with the record's unit (shape-normalized);
    - a declared non-empty ``currency`` must be consistent with the record unit.
    Returns ``None`` when consistent or the shared fact is genuinely absent.
    """
    origin_target = to_date(origin.target_date)
    record_target = to_date(record.get("target_date"))
    if origin_target is not None and record_target is not None and origin_target != record_target:
        return "target_date_mismatch"
    # The REQUESTED target (the run's as-of date) must agree with what the origin
    # and the record declare as the target — an internally-consistent but FOREIGN
    # record/origin (e.g. built for a different trade date) must not verify.
    if target is not None:
        if origin_target is not None and origin_target != target:
            return "origin_target_foreign"
        if record_target is not None and record_target != target:
            return "record_target_foreign"
    # The record's observed_at has ONE documented meaning named by ``date_basis``.
    # Require the origin's matching role to agree with it — not to invent a
    # different role. For SEC the record's observed_at is the FILED (availability)
    # date while observation_date is the fiscal period end, so they legitimately
    # differ and must be checked against the RIGHT role:
    observed = to_date(record.get("observed_at"))
    if observed is not None:
        basis = (origin.date_basis or "").strip().lower()
        if basis == "filed":
            role_day = to_date(origin.filed_at) or to_date(origin.availability_date)
        elif basis == "published":
            role_day = to_date(origin.published_at) or to_date(origin.availability_date)
        elif basis == "period_end":
            role_day = to_date(origin.observation_date)
        else:
            role_day = None
        if role_day is not None and role_day != observed:
            return "observed_at_role_mismatch"
    record_unit = _normalize_unit(
        str(record.get("unit_normalized", "") or record.get("unit_raw", "") or "")
    )
    origin_unit = _normalize_unit(origin.unit)
    if origin_unit and record_unit and origin_unit != record_unit:
        return "unit_mismatch"
    if origin.currency:
        record_currency = (
            record_unit.upper() if record_unit in _CURRENCY_UNITS else ""
        )
        if record_currency and record_currency != origin.currency:
            return "currency_mismatch"
    return None




def _validate_one(
    claim: ClaimRecord,
    origin: OriginMetadata,
    record: dict[str, Any],
    target,
) -> tuple[str, str] | None:
    """Return ``None`` when this record verifies every asserted fact, else a
    ``(status, reason)`` failure."""
    # 1) Metric name. A monetary/numeric value claim must name a metric and the
    # record must carry the SAME metric; a mismatch or a missing metric when a
    # value is asserted cannot verify.
    record_metric = str(record.get("metric_name", "") or "").strip().lower()
    if claim.metric:
        if record_metric and record_metric != claim.metric.strip().lower():
            return (STATUS_REJECTED, REASON_METRIC_MISMATCH)
    elif claim.value is not None and record_metric:
        # A value claim with no metric can still be checked against the record's
        # value (the date role scopes it), so a missing metric is not itself fatal.
        pass

    # 2) Date against the MATCHING role only.
    if claim.date_role or claim.date:
        role = claim.date_role
        if role not in DATE_ROLES:
            return (STATUS_UNVERIFIED, REASON_UNKNOWN_DATE_ROLE)
        if not claim.date:
            return (STATUS_UNVERIFIED, REASON_DATE_MISSING)
        actual = origin.value_for_date_role(role)
        if actual is None:
            return (STATUS_UNVERIFIED, REASON_DATE_ROLE_UNKNOWN)
        outcome = dates_match(role, claim.date, actual)
        if outcome == "mismatch":
            return (STATUS_REJECTED, REASON_DATE_MISMATCH)
        if outcome == "unverifiable":
            return (STATUS_UNVERIFIED, REASON_DATE_UNVERIFIABLE)
        matched_day = date_from_role_value(actual)
        if target is not None and matched_day is not None and matched_day > target:
            return (STATUS_REJECTED, REASON_FUTURE)

    # 3) Value + unit/currency/scale (only when the claim asserts a value).
    if claim.value is not None:
        asserted = _decimal(claim.value)
        if asserted is None:
            return (STATUS_REJECTED, REASON_VALUE_MISSING)
        record_value = _decimal(record.get("value_normalized"))
        if record_value is None:
            return (STATUS_REJECTED, REASON_VALUE_MISSING)

        claim_unit = _normalize_unit(claim.unit)
        claim_currency = str(claim.currency or "").strip().upper()
        record_unit = _normalize_unit(
            str(record.get("unit_normalized", "") or record.get("unit_raw", "") or "")
        )
        record_currency = str(origin.currency or "").strip().upper()

        # The record MUST declare a known dimension (its unit). Without it, no exact
        # numeric claim can be corroborated — for money OR shares OR percent OR a
        # ratio. A bare number must never silently vouch for any dimension.
        record_dim = _dimension(record_unit)
        if record_dim is None:
            return (STATUS_UNVERIFIED, REASON_UNIT_UNKNOWN)

        # The claim MUST ALSO declare a dimension. Finance uses an explicit
        # dimensionless declaration (``ratio``) for a pure ratio; an ABSENT unit is
        # never assumed to be any dimension. Money additionally carries a currency.
        claim_dim = _dimension(claim_unit)
        if claim_dim is None:
            return (STATUS_UNVERIFIED, REASON_UNIT_UNKNOWN)

        # Dimensions must match exactly (shares vs percent vs ratio vs money never
        # corroborate one another). Money also requires an exact currency (no FX).
        if claim_dim != record_dim:
            return (STATUS_REJECTED, REASON_UNIT_MISMATCH)
        if record_dim == DIM_MONEY:
            if not claim_currency:
                return (STATUS_UNVERIFIED, REASON_UNIT_UNKNOWN)
            if record_currency:
                if claim_currency != record_currency:
                    return (STATUS_REJECTED, REASON_UNIT_MISMATCH)
            else:
                # A record with no known currency cannot confirm a specific currency.
                return (STATUS_UNVERIFIED, REASON_UNIT_UNKNOWN)

        # MAGNITUDE: ``record.value_normalized`` is in BASE units (the producer
        # stores the base-normalized magnitude — e.g. SEC stores 391000000000 USD,
        # not 391000 million). The claim's asserted number is in ITS OWN declared
        # ``value_scale`` (base when omitted) and is normalized to base
        # (asserted * claim_scale) before comparison, so ``391000 million USD`` and
        # ``391000000000 USD`` are the SAME magnitude and both verify against the
        # real base value. An EXPLICIT claim scale is only accepted when the record
        # itself declares a known scale — an explicit multiplier must never invent
        # missing record magnitude semantics. No FX is ever applied.
        if claim.value_scale is not None:
            claim_scale = _decimal(claim.value_scale)
            if claim_scale is None:
                return (STATUS_REJECTED, REASON_SCALE_INVALID)
            if not origin.scale_known:
                return (STATUS_UNVERIFIED, REASON_SCALE_UNKNOWN)
        else:
            # Omitted claim scale means "base units" ONLY when the record declares a
            # known base-unit scale; otherwise a bare number could be millions or
            # single units — never guess.
            if not origin.scale_known:
                return (STATUS_UNVERIFIED, REASON_SCALE_UNKNOWN)
            claim_scale = _decimal("1")
        if _decimal(claimed_scaled(asserted, claim_scale)) != record_value:
            return (STATUS_REJECTED, REASON_VALUE_MISMATCH)
    return None


def claimed_scaled(value: Decimal, scale: Decimal) -> Decimal:
    """The asserted magnitude expressed in the record's base units."""
    return value * scale


def validated_evidence_ids(
    turns: list[Any],
    *,
    origin_by_id: dict[str, OriginMetadata],
    records_by_id: dict[str, dict[str, Any]],
    target_date: str | None,
    expected_symbol: str | None = None,
    expected_run_id: str | None = None,
    duplicate_origin_ids: set[str] | None = None,
) -> tuple[set[str], list[ClaimValidation], list[ClaimValidation]]:
    """Aggregate exact-claim validation across a round's turns.

    Returns ``(fully_verified_ids, verified, rejected_or_unverified)`` where
    ``fully_verified_ids`` is the set of cited ids whose EVERY exact claim on them
    validates as ``verified`` (a wrong claim on an id excludes that id), and the
    two lists carry the per-claim audit records (verified vs not).
    """
    claimed_ids: dict[str, list[ClaimValidation]] = {}
    verified_list: list[ClaimValidation] = []
    failed_list: list[ClaimValidation] = []
    for turn in turns or []:
        for claim in getattr(turn, "exact_claims", []) or []:
            verdict = validate_claim(
                claim,
                origin_by_id=origin_by_id,
                records_by_id=records_by_id,
                target_date=target_date,
                expected_symbol=expected_symbol,
                expected_run_id=expected_run_id,
                duplicate_origin_ids=duplicate_origin_ids,
            )
            if verdict.is_verified:
                verified_list.append(verdict)
            else:
                failed_list.append(verdict)
            for evidence_id in claim.evidence_ids or []:
                claimed_ids.setdefault(evidence_id, []).append(verdict)
    fully_verified: set[str] = set()
    for evidence_id, verdicts in claimed_ids.items():
        if verdicts and all(v.is_verified for v in verdicts):
            fully_verified.add(evidence_id)
    return fully_verified, verified_list, failed_list


def claimed_ids_with_failed_claims(
    turns: list[Any],
    *,
    origin_by_id: dict[str, OriginMetadata],
    records_by_id: dict[str, dict[str, Any]],
    target_date: str | None,
    expected_symbol: str | None = None,
    expected_run_id: str | None = None,
    duplicate_origin_ids: set[str] | None = None,
) -> set[str]:
    """IDs targeted by at least one exact claim that is NOT verified.

    Such an ID must not count as valid new evidence nor support a factual
    conflict: a valid-but-misused citation never extends a debate. An ID with no
    exact claim at all is not included (the legacy qualitative path is unaffected).
    """
    invalid: set[str] = set()
    for turn in turns or []:
        for claim in getattr(turn, "exact_claims", []) or []:
            verdict = validate_claim(
                claim,
                origin_by_id=origin_by_id,
                records_by_id=records_by_id,
                target_date=target_date,
                expected_symbol=expected_symbol,
                expected_run_id=expected_run_id,
                duplicate_origin_ids=duplicate_origin_ids,
            )
            if not verdict.is_verified:
                for evidence_id in claim.evidence_ids or []:
                    invalid.add(evidence_id)
    return invalid


def summarize_claim_validations(
    turns: list[Any],
    *,
    origin_by_id: dict[str, OriginMetadata],
    records_by_id: dict[str, dict[str, Any]],
    target_date: str | None,
    expected_symbol: str | None = None,
    expected_run_id: str | None = None,
    duplicate_origin_ids: set[str] | None = None,
) -> dict[str, Any]:
    """A JSON-safe, prose-free summary of exact-claim validation for a round.

    Returns ``{"verified": [...], "rejected": [...], "unverified": [...]}`` where
    each entry is a stable, audit-safe descriptor of a claim verdict (status,
    reason, metric, date_role, asserted date/value/unit, cited ids). It never
    embeds the raw claim prose, so the Research Manager receives a redacted,
    deterministic picture of which exact claims held up. Deterministic ordering
    (by evidence id + reason) so a shuffled input yields identical output.

    ADR-010 amendment: an additive ``coverage`` block reports standalone typed-line
    recovery honesty (``typed_lines_found`` / ``parsed`` / ``unparseable``), and is
    present ONLY when at least one standalone typed line was seen. A legacy turn
    with no typed lines keeps the exact prior shape (no ``coverage`` key), so
    backward compatibility is preserved; a turn whose typed lines were present but
    yielded no claim can never read as an empty success.
    """
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    standalone_rows: list[dict[str, Any]] = []
    for turn in turns or []:
        for claim in getattr(turn, "exact_claims", []) or []:
            verdict = validate_claim(
                claim,
                origin_by_id=origin_by_id,
                records_by_id=records_by_id,
                target_date=target_date,
                expected_symbol=expected_symbol,
                expected_run_id=expected_run_id,
                duplicate_origin_ids=duplicate_origin_ids,
            )
            entry = {
                "status": verdict.status,
                "reason": verdict.reason,
                "metric": claim.metric,
                "date_role": claim.date_role,
                "date": claim.date,
                "value": claim.value,
                "unit": claim.unit,
                "evidence_ids": list(claim.evidence_ids),
            }
            if verdict.status == STATUS_VERIFIED:
                verified.append(entry)
            elif verdict.status == STATUS_REJECTED:
                rejected.append(entry)
            else:
                unverified.append(entry)
        standalone_found = int(getattr(turn, "standalone_typed_claim_count", 0) or 0)
        unparsed = int(getattr(turn, "unparsed_typed_claim_count", 0) or 0)
        if standalone_found or unparsed:
            speaker = str(getattr(turn, "speaker", "") or "")
            standalone_rows.append(
                {
                    "speaker": speaker,
                    "typed_lines_found": standalone_found,
                    "parsed": max(standalone_found - unparsed, 0),
                    "unparseable": unparsed,
                }
            )
    key = lambda e: (tuple(e["evidence_ids"]), e["reason"], e["metric"], e["date"])  # noqa: E731
    summary: dict[str, Any] = {
        "verified": sorted(verified, key=key),
        "rejected": sorted(rejected, key=key),
        "unverified": sorted(unverified, key=key),
    }
    if standalone_rows:
        summary["coverage"] = {
            "typed_lines_found": sum(r["typed_lines_found"] for r in standalone_rows),
            "parsed": sum(r["parsed"] for r in standalone_rows),
            "unparseable": sum(r["unparseable"] for r in standalone_rows),
            "source": "standalone_typed_lines",
            "turns": sorted(
                standalone_rows,
                key=lambda r: (r["speaker"], r["typed_lines_found"], r["unparseable"]),
            ),
        }
    return summary


def claim_summary_prompt_block(summary: dict[str, Any]) -> str:
    """A deterministic, prose-free prompt block for the Research Manager.

    Empty when no exact claim was made AND no standalone typed line was seen (the
    qualitative/legacy path is unchanged). When standalone typed lines were seen
    but produced no verified/rejected/unverified entry (e.g. only unparseable
    lines), a coverage-only block is emitted — an out-of-contract typed claim can
    never read as an empty success.
    """
    verified = summary.get("verified") or []
    rejected = summary.get("rejected") or []
    unverified = summary.get("unverified") or []
    coverage = summary.get("coverage") or {}
    coverage_only = not (verified or rejected or unverified) and isinstance(coverage, dict) and coverage
    if not (verified or rejected or unverified) and not coverage_only:
        return ""
    lines = ["[Exact claim validation (deterministic)]"]
    if coverage_only:
        found = int(coverage.get("typed_lines_found", 0) or 0)
        unparseable = int(coverage.get("unparseable", 0) or 0)
        lines.append(
            f"Standalone typed claims were present ({found}) but none could be "
            f"validated ({unparseable} unparseable); treat them as UNVERIFIED and "
            "do not present them as verified facts."
        )
    if verified:
        lines.append("Verified exact claims (safe to rely on):")
        for entry in verified:
            lines.append(
                f"- {entry['date_role']}={entry['date']} value={entry['value']} "
                f"unit={entry['unit'] or 'n/a'} ids={','.join(entry['evidence_ids'])}"
            )
    if rejected:
        lines.append(
            "REJECTED exact claims (DO NOT repeat or rely on these; the cited ID "
            "is valid but the date/value/unit is wrong):"
        )
        for entry in rejected:
            lines.append(
                f"- {entry['date_role']}={entry['date']} value={entry['value']} "
                f"unit={entry['unit'] or 'n/a'} ids={','.join(entry['evidence_ids'])} "
                f"({entry['reason']})"
            )
    if unverified:
        lines.append(
            "UNVERIFIED exact claims (cannot be proven against the evidence; treat "
            "as unconfirmed and do not present as a verified fact):"
        )
        for entry in unverified:
            lines.append(
                f"- {entry['date_role']}={entry['date']} value={entry['value']} "
                f"unit={entry['unit'] or 'n/a'} ids={','.join(entry['evidence_ids'])} "
                f"({entry['reason']})"
            )
    if isinstance(coverage, dict) and coverage and int(coverage.get("unparseable", 0) or 0) > 0:
        lines.append(
            f"Coverage: {int(coverage.get('typed_lines_found', 0) or 0)} standalone "
            f"typed line(s); {int(coverage.get('unparseable', 0) or 0)} unparseable and "
            "excluded from the counts above (never verified)."
        )
    return "\n".join(lines)


def duplicate_origin_id_set(origin_dicts: list[Any]) -> set[str]:
    """Evidence IDs that appear more than once with DIFFERENT origin metadata.

    Feed the raw serialized origin rows (as a list of ``(evidence_id, dict)`` or
    state list forms) to detect a hostile/legacy duplicate with conflicting
    origin; such an id is unverifiable (fail closed).
    """
    seen: dict[str, str] = {}
    duplicates: set[str] = set()
    for entry in origin_dicts or []:
        if not isinstance(entry, dict):
            continue
        evidence_id = str(entry.get("evidence_id", "") or "")
        payload = entry.get("origin")
        if not evidence_id or payload is None:
            continue
        import json

        canonical = json.dumps(payload, sort_keys=True, default=str)
        if evidence_id in seen and seen[evidence_id] != canonical:
            duplicates.add(evidence_id)
        else:
            seen[evidence_id] = canonical
    return duplicates


# ---------------------------------------------------------------------------
# Standalone typed-claim recovery (ADR-010 amendment, 2026-11-12)
# ---------------------------------------------------------------------------
#
# A model may emit the pipe-delimited typed ``claim=metric=...|role=...|date=...|
# value=...|unit=...|evidence=...`` form OUTSIDE the ``DEBATE_METADATA`` marker
# (before it, after it, or with no marker at all). The marker-only parser silently
# dropped those lines into an empty-success summary. This extractor recovers an
# UNAMBIGUOUS standalone typed line so it enters the SAME date/value/unit
# validation as a marker claim. Extraction is NOT trust: a recovered record still
# fails closed in ``validate_claim`` when its date/value/unit/origin/ID is wrong.
#
# Strict grammar (no guessing):
# - a record begins (after optional list bullets / whitespace) with ``claim=`` /
#   ``claims=`` as a whole token, not the ``claim=`` substring of another word;
# - every pipe-separated segment is ``key=value`` (a bare segment makes the record
#   ``unparseable``, never a silently-dropped success);
# - a record with NO typed constraint is ``unparseable`` (not a fabricated claim).
# An ambiguous line (quotes / fenced / example prose) is never promoted: only a
# line whose FIRST non-bullet token is the ``claim=`` keyword is a record.

_STANDALONE_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?")
_STANDALONE_CLAIM_START_RE = re.compile(r"(?<![\w-])claims?=", re.IGNORECASE)

# A Markdown code fence (``` or ~~~ with at least three chars). A line inside a
# fence is an ILLUSTRATIVE example, never a real typed claim: fenced code is
# tracked (including an UNCLOSED fence to end-of-text) so a copy-pasted example can
# never become a trusted claim.
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# Marker + claim-field literals used by the shared exclusion walk so a canonical
# ``claim=`` marker line inside an explicit Example: block is illustrative.
_MARKER_LITERAL = "DEBATE_METADATA:"
_CLAIM_FIELD_LITERAL = re.compile(r"(?<![\w-])claims?=", re.IGNORECASE)
# Multi-claim separator inside one canonical ``claims=`` field value.
_CLAIM_CHUNK_SEP = "||"

# A narrow, documented illustrative-block label: a line that starts with a
# case-insensitive ``example`` word followed by an optional number and a colon
# (e.g. ``Example:`` / ``Examples:`` / ``Example 1:``). Following typed lines are
# treated as illustrative until a blank line or a non-typed line ends the block.
# This is deterministic pattern matching, NOT arbitrary natural-language
# understanding: only this explicit label form is supported.
_EXAMPLE_LABEL_RE = re.compile(r"^examples?(?:\s+\d+)?\s*:", re.IGNORECASE)

# Known keys of the typed-claim grammar. A segment whose key is NOT here makes the
# line ambiguous (it is not our strict grammar), so it is surfaced as unparseable.
_TYPED_CLAIM_KEYS = frozenset(
    {"metric", "role", "date_role", "date", "value", "unit", "currency", "scale", "evidence"}
)

# Keys that are ALIASES of one another. Two alias keys with DIFFERENT values are a
# contradiction (never silently first-wins) -> the line is unparseable.
_ALIAS_GROUPS: tuple[frozenset[str], ...] = (frozenset({"role", "date_role"}),)


@dataclass
class ClaimExtraction:
    """Result of :func:`extract_standalone_typed_claims`.

    ``records`` are the parsed :class:`ClaimRecord` objects (in source order);
    ``unparseable`` is the list of raw standalone typed-looking lines that did NOT
    parse strictly (kept for an honest diagnostic, never dropped). ``found`` is the
    total number of standalone typed-looking lines seen, so ``found > 0`` with an
    empty ``records`` can never read as an empty success.
    """

    records: list[ClaimRecord] = field(default_factory=list)
    unparseable: list[str] = field(default_factory=list)

    @property
    def found(self) -> int:
        return len(self.records) + len(self.unparseable)

    def coverage(self) -> dict[str, Any]:
        return {
            "typed_lines_found": self.found,
            "parsed": len(self.records),
            "unparseable": len(self.unparseable),
        }


def parse_strict_typed_claim_payload(payload: str) -> ClaimRecord | None:
    """Parse the pipe-delimited typed-claim grammar STRICTLY, or ``None``.

    Shared by the standalone extractor AND the canonical ``DEBATE_METADATA``
    ``claim=`` parser so a malformed/conflicting typed field can never be laundered
    through the canonical marker with different rules. Every segment must be a
    known ``key=value``; a bare segment, an unknown key, a duplicate key with a
    conflicting value, or a contradictory alias pair (``role`` vs ``date_role``)
    yields ``None`` (unparseable, never guessed). A record with no typed constraint
    is also ``None``.
    """
    payload = (payload or "").strip()
    if not payload:
        return None
    fields: dict[str, str] = {}
    for pair in payload.split("|"):
        if "=" not in pair:
            # A bare segment breaks the strict grammar (ambiguous) -> unparseable.
            return None
        key, _, value = pair.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if not key or key not in _TYPED_CLAIM_KEYS:
            return None
        if key in fields and fields[key] != value:
            # A duplicate key with a CONFLICTING value is ambiguous (never merged).
            return None
        fields[key] = value
    # A contradictory alias pair (``role`` vs ``date_role`` with different values)
    # is ambiguous; never silently pick one.
    for group in _ALIAS_GROUPS:
        present = {fields[k].strip().lower() for k in group if k in fields}
        if len(present) > 1:
            return None
    evidence_ids = [
        eid.strip() for eid in fields.get("evidence", "").split(",") if eid.strip()
    ]
    record = ClaimRecord(
        evidence_ids=evidence_ids,
        metric=fields.get("metric", ""),
        date_role=fields.get("role", fields.get("date_role", "")),
        date=fields.get("date", ""),
        value=fields.get("value") if fields.get("value") else None,
        unit=fields.get("unit", ""),
        currency=fields.get("currency", ""),
        value_scale=fields.get("scale") if fields.get("scale") else None,
    )
    if not record.has_typed_constraint:
        return None
    return record


def _parse_standalone_typed_line(line: str) -> ClaimRecord | None:
    """Parse ONE strict standalone typed line, or return ``None`` (unparseable).

    The line must, after optional bullets/whitespace, START with ``claim=`` /
    ``claims=``; the keyword is stripped and the remaining payload is parsed with
    the shared strict :func:`parse_strict_typed_claim_payload`.
    """
    body = _STANDALONE_BULLET_RE.sub("", line).strip().strip("`").strip()
    match = _STANDALONE_CLAIM_START_RE.match(body)
    if match is None:
        return None
    return parse_strict_typed_claim_payload(body[match.end():])


def extract_standalone_typed_claims(text: str) -> ClaimExtraction:
    """Recover standalone ``claim=...|...`` typed lines from arbitrary ``text``.

    Returns a :class:`ClaimExtraction`. Each line is considered independently: a
    line whose first non-bullet token is ``claim=``/``claims=`` is either parsed to
    a :class:`ClaimRecord` or recorded as ``unparseable`` (never dropped). A line
    that does not begin with the typed keyword — including quoted examples, fenced
    code, or ordinary prose — is ignored. Deterministic (source order, no clock).
    """
    extraction, _indexed = extract_standalone_typed_claims_indexed(text)
    return extraction


def _iter_non_illustrative_lines(text: str):
    """Yield ``(line_index, line)`` for every line NOT in a fence/Example block.

    The ONE shared whole-document exclusion walk (Markdown fences with opener-length
    semantics, explicit ``Example:`` blocks) used by every typed-claim extractor, so
    standalone and canonical detection never diverge on what is illustrative.
    """
    if not isinstance(text, str) or not text:
        return
    fence_char: str | None = None
    fence_len = 0
    in_example_block = False
    for line_index, raw_line in enumerate(text.splitlines()):
        line = raw_line.rstrip()
        fence_match = _FENCE_RE.match(line)
        if fence_match is not None:
            token = fence_match.group(1)
            char = token[0]
            suffix = line[fence_match.end(1):].strip()
            if fence_char is None:
                fence_char, fence_len = char, len(token)
                in_example_block = False
            elif char == fence_char and len(token) >= fence_len and not suffix:
                fence_char, fence_len = None, 0
            continue
        if fence_char is not None:
            continue
        stripped = line.strip()
        if _EXAMPLE_LABEL_RE.match(stripped):
            in_example_block = True
            continue
        if in_example_block:
            if stripped == "":
                in_example_block = False
                continue
            # A typed-looking standalone line OR a canonical ``claim=`` marker line
            # inside an explicit Example: block is illustrative.
            if _STANDALONE_CLAIM_START_RE.match(
                _STANDALONE_BULLET_RE.sub("", line)
            ) or (_MARKER_LITERAL in line and _CLAIM_FIELD_LITERAL.search(line)):
                continue
            in_example_block = False
        # A blockquote/quoted line (``> ...``) is illustrative/quoted prose: a marker
        # substring inside it must never become a protected/real claim.
        if stripped.startswith(">"):
            continue
        yield (line_index, line)


def extract_standalone_typed_claims_indexed(
    text: str,
) -> tuple[ClaimExtraction, list[tuple[int, str, ClaimRecord | None]]]:
    """Whole-document, fence-aware extraction returning per-line results.

    Walks the document ONCE through :func:`_iter_non_illustrative_lines` (the shared
    fence/Example exclusion), then parses each non-excluded typed-looking ``claim=``
    line. Returns ``(extraction, indexed)`` where ``indexed`` is
    ``[(line_index, raw_line, record_or_None), ...]`` for every typed-looking line
    (``record`` is ``None`` for an unparseable line).
    """
    extraction = ClaimExtraction()
    indexed: list[tuple[int, str, ClaimRecord | None]] = []
    if not isinstance(text, str) or not text:
        return extraction, indexed
    for line_index, line in _iter_non_illustrative_lines(text):
        if not _STANDALONE_CLAIM_START_RE.match(_STANDALONE_BULLET_RE.sub("", line)):
            continue
        record = _parse_standalone_typed_line(line)
        indexed.append((line_index, line, record))
        if record is not None:
            extraction.records.append(record)
        else:
            extraction.unparseable.append(line.strip())
    return extraction, indexed


@dataclass
class ClaimSpanOccurrence:
    """One parsed typed-claim occurrence with its EXACT field offsets in a line.

    ``date_span`` / ``value_span`` are ``(start, end)`` column offsets within the
    whole line for that specific occurrence's ``date=`` / ``value=`` value tokens
    (``None`` when the field is absent). Tying protection to the occurrence offset
    (not a whole-line first match) means one verified subclaim can never authorize a
    DIFFERENT subclaim that happens to share a date/value.
    """

    line_index: int
    record: ClaimRecord
    date_span: tuple[int, int] | None
    value_span: tuple[int, int] | None
    source: str  # "standalone" | "canonical"


def _occurrence_field_spans(raw_payload: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """``(date_span, value_span)`` offsets within ``raw_payload`` (as written).

    Walks the ORIGINAL pipe-delimited segments with the SAME key semantics as
    :func:`parse_strict_typed_claim_payload` (``key.strip().lower()``), so a
    supported variant — uppercase ``DATE=``/``VALUE=``, spaced ``date = ...``, or a
    backtick/whitespace wrapper — gets an EXACT raw offset for its value token. The
    returned span points at the RAW value text (whatever numeric form) in the
    ORIGINAL payload, so wrapper stripping never shortens the offset. Numeric
    equivalence is proven later by ``validate_claim`` (strict normalization), never
    by raw-text/float/substring comparison.
    """
    date_span: tuple[int, int] | None = None
    value_span: tuple[int, int] | None = None
    cursor = 0
    for segment in raw_payload.split("|"):
        seg_start = cursor
        cursor += len(segment) + 1  # +1 for the '|' separator
        if "=" not in segment:
            continue
        key, sep, value = segment.partition("=")
        normalized_key = key.strip().lower()
        if not sep:
            continue
        # Value token start within the original segment (after ``key=``).
        value_raw_start = seg_start + len(key) + len(sep)
        value_token = value.strip()
        if not value_token:
            continue
        leading_ws = len(value) - len(value.lstrip())
        span = (value_raw_start + leading_ws, value_raw_start + leading_ws + len(value_token))
        if normalized_key == "date" and date_span is None:
            date_span = span
        elif normalized_key == "value" and value_span is None:
            value_span = span
    return (date_span, value_span)


def extract_claim_span_occurrences(text: str) -> list[ClaimSpanOccurrence]:
    """All typed-claim occurrences (standalone AND canonical) with exact offsets.

    Uses the SAME shared fence/Example exclusion walk as the standalone extractor,
    so a fenced/``Example:`` canonical or standalone claim is never returned (never
    eligible for protection). For each non-excluded line it yields:
    - a standalone ``claim=...`` occurrence;
    - every ``claim=``/``claims=`` ``;``-delimited field inside a
      ``DEBATE_METADATA`` marker, located at its EXACT offset within the line.

    Field spans are located from the RAW payload token (regardless of numeric form:
    extra decimals / scientific notation), and the offset is computed per occurrence
    positionally — a duplicate identical payload never collapses onto the first
    match. Numeric equivalence is decided by the parsed record's ``validate_claim``,
    not by comparing raw text.
    """
    occurrences: list[ClaimSpanOccurrence] = []
    if not isinstance(text, str) or not text:
        return occurrences
    marker_start = "DEBATE_METADATA:"
    claim_field_re = re.compile(r"(?:(?<=;)|(?<=:))\s*claims?=", re.IGNORECASE)
    for line_index, line in _iter_non_illustrative_lines(text):
        stripped_line = _STANDALONE_BULLET_RE.sub("", line)
        if _STANDALONE_CLAIM_START_RE.match(stripped_line):
            record = _parse_standalone_typed_line(line)
            if record is not None:
                # Offset of the bullet-stripped body within the ORIGINAL line: the
                # bullet/numeric-list prefix removed by _STANDALONE_BULLET_RE.sub is
                # measured exactly (not assumed to be leading whitespace only).
                bullet_consumed = len(line) - len(stripped_line)
                stub = _STANDALONE_CLAIM_START_RE.match(stripped_line)
                after_keyword = stripped_line[stub.end():] if stub else stripped_line
                payload_text = after_keyword.strip().strip("`").strip()
                # Offset of the parser's payload within after_keyword (exact wrapper
                # length: leading whitespace/backticks the parser removed).
                wrapper_len = after_keyword.find(payload_text) if payload_text else 0
                if wrapper_len < 0:
                    wrapper_len = 0
                payload_off = bullet_consumed + (stub.end() if stub else 0) + wrapper_len
                date_local, value_local = _occurrence_field_spans(payload_text)
                occurrences.append(
                    ClaimSpanOccurrence(
                        line_index,
                        record,
                        (payload_off + date_local[0], payload_off + date_local[1])
                        if date_local
                        else None,
                        (payload_off + value_local[0], payload_off + value_local[1])
                        if value_local
                        else None,
                        "standalone",
                    )
                )
            continue
        if marker_start not in line:
            continue
        # Canonical ``claim=`` fields inside the marker line; walk each occurrence and
        # compute per-subclaim offsets positionally (no line.find first-match).
        for field_match in claim_field_re.finditer(line):
            payload_start = field_match.end()
            payload_end = line.find(";", payload_start)
            if payload_end < 0:
                payload_end = len(line)
            payload_slice = line[payload_start:payload_end]
            cursor = 0
            for sub in payload_slice.split(_CLAIM_CHUNK_SEP):
                sub_idx = payload_slice.find(sub, cursor)
                if sub_idx < 0:
                    sub_idx = cursor
                cursor = sub_idx + len(sub) + len(_CLAIM_CHUNK_SEP)
                # The parser sees the wrapper-stripped payload; measure the wrapper
                # (leading whitespace + backticks) so spans shift back onto raw bytes
                # and the first key's leading backtick never breaks key normalization.
                stripped_sub = sub.strip().strip("`").strip()
                record = parse_strict_typed_claim_payload(stripped_sub)
                if record is None:
                    continue
                wrapper_len = sub.find(stripped_sub) if stripped_sub else 0
                if wrapper_len < 0:
                    wrapper_len = 0
                sub_off = payload_start + sub_idx + wrapper_len
                date_local, value_local = _occurrence_field_spans(stripped_sub)
                occurrences.append(
                    ClaimSpanOccurrence(
                        line_index,
                        record,
                        (sub_off + date_local[0], sub_off + date_local[1])
                        if date_local
                        else None,
                        (sub_off + value_local[0], sub_off + value_local[1])
                        if value_local
                        else None,
                        "canonical",
                    )
                )
    return occurrences


def canonical_claim_key(claim: ClaimRecord) -> tuple:
    """A stable identity tuple for deduping the SAME canonical claim.

    Two claims are the same claim only when EVERY typed field AND the cited-ID set
    match exactly. A claim differing in any field is DISTINCT and is never dropped
    by dedupe.
    """
    return (
        tuple(sorted(claim.evidence_ids)),
        claim.metric,
        claim.date_role,
        claim.date,
        claim.value,
        claim.unit,
        claim.currency,
        claim.value_scale,
        claim.value_invalid,
        claim.value_scale_invalid,
    )
