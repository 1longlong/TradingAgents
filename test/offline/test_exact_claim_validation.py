"""ADR-010 Stage 3: pure deterministic exact-claim date/value/unit validation.

Approved test cases (2026-11-11 human plan/test approval; plan + tests ONLY, not
final human acceptance). These prove the *pure* validator and the typed origin
semantics it relies on, with NO network, NO paid LLM, NO clock:

- a correct cited ID does NOT launder a wrong exact date/value/unit;
- date roles are distinct (target vs observation vs availability vs timestamp);
- SEC filed != fiscal end; news publication is not the date of the financial
  figure; a date-only source cannot prove a timestamp; a same-calendar-day but
  different hour/timezone is a mismatch;
- stale/future/malformed/missing/ambiguous dates fail closed;
- exact values/currency/scales/units incl. NaN/bool are validated;
- malformed value_scale NEVER normalizes to 1; int/compact dates are rejected;
- mismatched ID/ticker/run, duplicate IDs with conflicting origin, an unknown
  schema version all fail closed.

Traceability: FR-DDT-002, FR-DDT-005, NFR-PIT-001, NFR-AUD-001, NFR-DET-001,
NFR-BC-001, INV-1/INV-3/INV-6/INV-13.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradingagents.debate.claims import (
    REASON_AVAILABILITY_FUTURE,
    REASON_DATE_MISMATCH,
    REASON_DATE_ROLE_UNKNOWN,
    REASON_DUPLICATE_ORIGIN,
    REASON_FOREIGN_RUN,
    REASON_FUTURE,
    REASON_INVALID_SCHEMA,
    REASON_INVALID_VALUE_CONSTRAINT,
    REASON_LOW_OR_BLOCKED,
    REASON_METRIC_MISMATCH,
    REASON_MISSING_ORIGIN,
    REASON_NO_TYPED_CONSTRAINT,
    REASON_OBSERVATION_UNKNOWN,
    REASON_ORIGIN_INCONSISTENT,
    REASON_RECORD_RUN_UNKNOWN,
    REASON_SCALE_INVALID,
    REASON_SCALE_UNKNOWN,
    REASON_TARGET_UNKNOWN,
    REASON_TICKER_MISMATCH,
    REASON_UNIT_MISMATCH,
    REASON_UNIT_UNKNOWN,
    REASON_UNKNOWN_DATE_ROLE,
    REASON_UNKNOWN_EVIDENCE,
    REASON_UNKNOWN_SCHEMA,
    REASON_VALUE_MISMATCH,
    STATUS_REJECTED,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    validate_claim,
)
from tradingagents.debate.models import ClaimRecord
from tradingagents.evidence.origin import (
    SCALE_BASE,
    OriginMetadata,
    dates_match,
)

TARGET = "2026-05-13"
SYMBOL = "COF"
RUN_ID = "2026-05-13/COF"


def _record(
    *,
    evidence_id="id1",
    quality="Medium",
    ticker=SYMBOL,
    run_id=RUN_ID,
    observed_at="2026-05-04",
    metric="close",
    value="200.13",
    unit="USD",
):
    return {
        "evidence_id": evidence_id,
        "quality_status": quality,
        "ticker_normalized": ticker,
        "run_id": run_id,
        "observed_at": observed_at,
        "metric_name": metric,
        "value_normalized": value,
        "unit_normalized": unit,
    }


def _origin(evidence_id, **overrides):
    base = {
        "target_date": TARGET,
        "observation_date": "2026-05-04",
        "availability_date": "2026-05-05",
        "filed_at": None,
        "published_at": None,
        "retrieved_at": "2026-05-13T12:00:00Z",
        "date_basis": "period_end",
        "value_scale": SCALE_BASE,
        "unit": "USD",
        "currency": "USD",
    }
    base.update(overrides)
    return evidence_id, OriginMetadata(**base)


def _validate(
    claim,
    *,
    records=None,
    origins=None,
    symbol=SYMBOL,
    run_id=RUN_ID,
    dup=None,
    target_override=TARGET,
):
    records = records if records is not None else {"id1": _record()}
    origins = origins if origins is not None else dict([_origin("id1")])
    return validate_claim(
        claim,
        origin_by_id=origins,
        records_by_id=records,
        target_date=target_override,
        expected_symbol=symbol,
        expected_run_id=run_id,
        duplicate_origin_ids=dup or set(),
    )


class TestCorrectWrongByRole:
    def test_correct_observation_date_and_value_verifies(self):
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["id1"],
                metric="close",
                date_role="observation_date",
                date="2026-05-04",
                value="200.13",
                unit="USD",
                currency="USD",
            )
        )
        assert verdict.status == STATUS_VERIFIED

    @pytest.mark.parametrize(
        "date,value,unit,reason",
        [
            ("2026-05-05", "200.13", "USD", REASON_DATE_MISMATCH),
            ("2026-05-04", "201.00", "USD", REASON_VALUE_MISMATCH),
            ("2026-05-04", "200.13", "percent", REASON_UNIT_MISMATCH),
        ],
    )
    def test_wrong_date_value_unit_rejected(self, date, value, unit, reason):
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["id1"],
                metric="close",
                date_role="observation_date",
                date=date,
                value=value,
                unit=unit,
                currency="USD",
            )
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == reason

    def test_target_not_observation_is_a_mismatch(self):
        # Claiming the observation value under the target-date role must fail: the
        # target role value (2026-05-13) is not the observation date (2026-05-04).
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["id1"],
                metric="close",
                date_role="target_date",
                date="2026-05-04",
                value="200.13",
                unit="USD",
            )
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_DATE_MISMATCH


class TestSecFiledNotFiscalEnd:
    def _sec_record_and_origin(self):
        rec = _record(observed_at="2026-05-02", metric="revenue", value="391000000000")
        origin = dict(
            [
                _origin(
                    "id1",
                    observation_date="2026-03-31",  # fiscal period end
                    availability_date="2026-05-02",  # filed date
                    filed_at="2026-05-02T09:30:00Z",
                    date_basis="filed",
                    value_scale=SCALE_BASE,
                    unit="USD",
                    currency="USD",
                )
            ]
        )
        return rec, origin

    def test_fiscal_end_is_observation_not_filing(self):
        rec, origin = self._sec_record_and_origin()
        # A claim about the fiscal-period observation date verifies...
        observed = _validate(
            ClaimRecord(
                evidence_ids=["id1"], metric="revenue", date_role="observation_date",
                date="2026-03-31", value="391000000000", unit="USD", currency="USD",
            ),
            records={"id1": rec}, origins=origin,
        )
        assert observed.status == STATUS_VERIFIED
        # ...and a claim that the fiscal END equals the FILED date is rejected.
        wrong = _validate(
            ClaimRecord(
                evidence_ids=["id1"], metric="revenue", date_role="observation_date",
                date="2026-05-02", value="391000000000", unit="USD", currency="USD",
            ),
            records={"id1": rec}, origins=origin,
        )
        assert wrong.status == STATUS_REJECTED
        assert wrong.reason == REASON_DATE_MISMATCH

    def test_observation_role_unknown_when_fiscal_end_absent(self):
        rec, origin = self._sec_record_and_origin()
        origin["id1"] = OriginMetadata.from_dict(
            {**origin["id1"].to_dict(), "observation_date": None}
        )
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["id1"], metric="revenue", date_role="observation_date",
                date="2026-03-31", value="391000000000", unit="USD", currency="USD",
            ),
            records={"id1": rec}, origins=origin,
        )
        # Observation role genuinely unknown -> UNVERIFIED (never guessed from the
        # filed date).
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_DATE_ROLE_UNKNOWN


class TestNewsPublishedIsNotClaimDate:
    def test_publication_date_cannot_prove_a_financial_figure_date(self):
        rec = _record(observed_at="2026-05-10", metric="headline", value="", unit="headline")
        origin = dict(
            [
                _origin(
                    "id1", observation_date=None, availability_date="2026-05-10",
                    published_at="2026-05-10T08:00:00Z", date_basis="published",
                )
            ]
        )
        # A news record has no financial observation value to verify.
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["id1"], metric="revenue", date_role="observation_date",
                date="2026-03-31", value="1000", unit="USD",
            ),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status != STATUS_VERIFIED


class TestTimestampsAndGranularity:
    def test_same_calendar_day_wrong_hour_is_a_mismatch(self):
        assert dates_match("filed_at", "2026-05-02T09:00:00Z", "2026-05-02T15:00:00Z") == "mismatch"

    def test_timezone_normalized_instant_matches(self):
        assert dates_match("filed_at", "2026-05-02T17:00:00+08:00", "2026-05-02T09:00:00Z") == "match"

    def test_date_only_cannot_prove_timestamp(self):
        assert dates_match("filed_at", "2026-05-02", "2026-05-02T15:00:00Z") == "unverifiable"

    def test_calendar_role_is_day_granular(self):
        assert dates_match("observation_date", "2026-05-04", "2026-05-04T15:00:00Z") == "match"
        assert dates_match("observation_date", "2026-05-03", "2026-05-04T15:00:00Z") == "mismatch"

    def test_timestamp_claim_against_absent_timestamp_role_unverified(self):
        # The claimed filed_at role value is genuinely absent (date-only source
        # carries no exact timestamp) -> UNVERIFIED, never guessed from the date.
        origin = dict([_origin("id1", filed_at=None, availability_date="2026-05-05")])
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["id1"], metric="close", date_role="filed_at",
                date="2026-05-05T09:00:00Z", value="200.13", unit="USD",
            ),
            origins=origin,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_DATE_ROLE_UNKNOWN

    def test_timestamp_claim_against_wrong_hour_instant_mismatch(self):
        origin = dict([_origin("id1", filed_at="2026-05-05T15:00:00Z")])
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["id1"], metric="close", date_role="filed_at",
                date="2026-05-05T09:00:00Z", value="200.13", unit="USD",
            ),
            origins=origin,
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_DATE_MISMATCH


class TestStaleFutureMalformedMissing:
    def test_future_observation_rejected(self):
        rec = _record(observed_at="2026-06-01")  # after TARGET
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-06-01", value="200.13", unit="USD"),
            records={"id1": rec},
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_FUTURE

    def test_future_claim_date_rejected(self):
        # A future observation is a look-ahead. The record's observed_at is kept
        # consistent with the origin so the look-ahead (not origin
        # inconsistency) is the rejection reason.
        rec = _record(observed_at="2026-06-01")
        origin = dict([_origin("id1", observation_date="2026-06-01")])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-06-01", value="200.13", unit="USD", currency="USD"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_FUTURE

    def test_malformed_claim_date_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="not-a-date", value="200.13", unit="USD")
        )
        assert verdict.status == STATUS_UNVERIFIED

    def test_missing_claim_date_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="", value="200.13", unit="USD")
        )
        assert verdict.status == STATUS_UNVERIFIED

    def test_missing_origin_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD"),
            origins={},
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_MISSING_ORIGIN


class TestValuesUnitsScales:
    def test_nan_value_rejected(self):
        claim = ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                            date="2026-05-04", value="NaN", unit="USD")
        # An asserted-but-invalid value is flagged and REJECTED, never dropped.
        assert claim.value_invalid is True
        verdict = _validate(claim)
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_INVALID_VALUE_CONSTRAINT

    def test_bool_value_is_rejected_not_dropped(self):
        claim = ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                            date="2026-05-04", value=True, unit="USD")
        # A bool is not a numeric magnitude: it is kept and flagged invalid (not
        # silently dropped) so validation rejects it rather than verifying on the
        # date alone.
        assert claim.value is not None
        assert claim.value_invalid is True
        verdict = _validate(claim)
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_INVALID_VALUE_CONSTRAINT

    def test_scaled_millions_match_real_producer_path(self):
        # REAL producer path: SEC stores value_normalized in BASE USD; the origin
        # scale is base (1). A claim of "391000 million USD" must normalize to
        # 391000*1e6 == 391000000000 and verify. The origin scale is NOT forced to
        # the claim's scale here.
        rec = _record(value="391000000000")
        origin = dict([_origin("id1", value_scale=SCALE_BASE)])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="391000", unit="USD", currency="USD",
                        value_scale="1000000"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status == STATUS_VERIFIED

    def test_base_equivalent_verifies_against_million_scale_record(self):
        # Both directions: a base-unit claim (391000000000 USD) verifies against a
        # record whose normalized value is base (391000000000) regardless of any
        # source-scale wording; the magnitude is what matters.
        rec = _record(value="391000000000")
        origin = dict([_origin("id1", value_scale=SCALE_BASE)])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="391000000000", unit="USD", currency="USD"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status == STATUS_VERIFIED

    def test_wrong_magnitude_rejected(self):
        # A wrong magnitude (1000-scale gives 391000000, not 391000000000) fails.
        rec = _record(value="391000000000")
        origin = dict([_origin("id1", value_scale=SCALE_BASE)])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="391000", unit="USD", currency="USD",
                        value_scale="1000"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_VALUE_MISMATCH

    def test_unknown_record_scale_unverifiable(self):
        origin = dict([_origin("id1", value_scale=None)])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="391000", unit="USD", currency="USD"),
            origins=origin,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_SCALE_UNKNOWN

    def test_currency_mismatch_no_fx(self):
        rec = _record(unit="EUR")
        origin = dict([_origin("id1", unit="EUR", currency="EUR")])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_UNIT_MISMATCH


class TestIdentityAndSchemaFailClosed:
    def test_mismatched_id_unknown(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["nope"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD")
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_UNKNOWN_EVIDENCE

    def test_foreign_ticker_rejected(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD"),
            symbol="AAPL",
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_TICKER_MISMATCH

    def test_foreign_run_rejected(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD"),
            run_id="2099-01-01/OTHER",
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_FOREIGN_RUN

    def test_low_evidence_rejected(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD"),
            records={"id1": _record(quality="Low")},
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_LOW_OR_BLOCKED

    def test_duplicate_conflicting_origin_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD"),
            dup={"id1"},
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_DUPLICATE_ORIGIN

    def test_unknown_schema_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", schema_version="9.9")
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNKNOWN_SCHEMA

    def test_unknown_date_role_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="moon_phase",
                        date="2026-05-04", value="200.13", unit="USD")
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNKNOWN_DATE_ROLE

    def test_legacy_untyped_not_verified(self):
        verdict = _validate(ClaimRecord(evidence_ids=["id1"]))
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_NO_TYPED_CONSTRAINT

    def test_metric_mismatch_rejected(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="volume", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD")
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_METRIC_MISMATCH


class TestMalformedScaleNeverNormalizesToOne:
    def test_bad_claim_scale_is_flagged_invalid_not_dropped(self):
        for bad in ("abc", "0", "-1", "NaN", "Infinity", True):
            claim = ClaimRecord(evidence_ids=["id1"], metric="close", value="200.13",
                                value_scale=bad)
            # An asserted-but-invalid scale is retained (raw) and flagged invalid so
            # validation REJECTS it — never silently dropped to base/omitted.
            assert claim.value_scale_invalid is True, bad
            verdict = _validate(claim)
            assert verdict.status == STATUS_REJECTED, bad
            assert verdict.reason == REASON_SCALE_INVALID, bad

    def test_origin_bad_scale_is_none_not_one(self):
        for bad in ("abc", 0, -5, "NaN", True):
            origin = OriginMetadata(value_scale=bad)
            assert origin.value_scale is None, bad
            assert origin.scale_known is False

    def test_origin_absent_scale_stays_none(self):
        assert OriginMetadata().value_scale is None
        assert OriginMetadata().scale_known is False

    def test_origin_explicit_base_scale_is_known(self):
        origin = OriginMetadata(value_scale=SCALE_BASE)
        assert origin.scale_known is True
        assert origin.value_scale == Decimal("1")


class TestAmbiguousDatesRejected:
    @pytest.mark.parametrize(
        "value",
        [
            20260510,          # int epoch that could look like a compact date
            20260510.0,        # float
            True,              # bool
            "20260510",        # compact ISO-y string
            "05/10/2026",      # locale-specific order
            "May 10 2026",     # loose text
            "2026.05.10",      # dot separators
            ["2026-05-10"],    # non-scalar
        ],
    )
    def test_non_date_types_and_ambiguous_formats_rejected(self, value):
        origin = OriginMetadata(observation_date=value)
        assert origin.observation_date is None

    def test_unambiguous_iso_accepted(self):
        assert OriginMetadata(observation_date="2026-05-10").observation_date == "2026-05-10"
        assert OriginMetadata(filed_at="2026-05-10T09:30:00Z").filed_at == "2026-05-10T09:30:00Z"


class TestGateDerivedOriginMarket:
    """Real gate attaches origin for market records; unknown default currency is
    honestly UNVERIFIABLE (not forced to USD)."""

    def _gate(self, monkeypatch):
        import pandas as pd

        import tradingagents.dataflows.market_data_validator as validator
        from tradingagents.evidence.origin import ORIGIN_STATE_KEY, OriginMetadata
        from tradingagents.graph.data_quality_gate import create_data_quality_gate_node

        dates = pd.bdate_range("2026-04-01", "2026-05-20")
        closes = [100 + i for i in range(len(dates))]
        df = pd.DataFrame(
            {
                "Date": dates,
                "Open": [c - 0.5 for c in closes],
                "High": [c + 1.0 for c in closes],
                "Low": [c - 1.0 for c in closes],
                "Close": closes,
                "Volume": [1_000_000 + i for i in range(len(dates))],
            }
        )
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d, fill_gaps=True: df)
        node = create_data_quality_gate_node(now_provider=lambda: "2026-05-13T12:00:00Z")
        out = node({"company_of_interest": "COF", "trade_date": "2026-05-13", "asset_type": "stock"})
        origin = out[ORIGIN_STATE_KEY]
        records = {r["evidence_id"]: r for r in out["data_quality_evidence_records"]}
        close_id = sorted(i for i in records if i.endswith("/close/0"))[0]
        return close_id, records, {k: OriginMetadata.from_dict(v) for k, v in origin.items()}

    def test_default_market_gate_unknown_currency_is_unverified(self, monkeypatch):
        # The default market adapter declares the neutral ``native_quote_currency``:
        # the dimension/currency is GENUINELY UNKNOWN, so an exact monetary claim
        # CANNOT be verified. This honestly asserts the real production limitation —
        # it does NOT assume ticker->USD or fabricate a currency.
        from tradingagents.debate.claims import validate_claim as _vc

        close_id, records, origins = self._gate(monkeypatch)
        rec = records[close_id]
        assert origins[close_id].observation_date == rec["observed_at"]
        verdict = _vc(
            ClaimRecord(
                evidence_ids=[close_id], metric="close", date_role="observation_date",
                date=rec["observed_at"], value=rec["value_normalized"], unit="USD",
                currency="USD",
            ),
            origin_by_id=origins, records_by_id=records, target_date="2026-05-13",
            expected_symbol="COF",
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNIT_UNKNOWN

    def test_injected_known_currency_fixture_can_verify(self, monkeypatch):
        # SEPARATE, clearly-labelled injected fixture: IF a source supplied a genuine
        # known currency, a correct claim verifies and a wrong date is rejected. This
        # proves the verification PATH; it is NOT a claim that the default market
        # path provides a known currency.
        from tradingagents.debate.claims import validate_claim as _vc

        close_id, records, origins = self._gate(monkeypatch)
        rec = dict(records[close_id], unit_normalized="USD", unit_raw="USD")
        records = {close_id: rec}
        origins = {
            close_id: OriginMetadata.from_dict(
                {**origins[close_id].to_dict(), "unit": "USD", "currency": "USD"}
            )
        }
        good = _vc(
            ClaimRecord(
                evidence_ids=[close_id], metric="close", date_role="observation_date",
                date=rec["observed_at"], value=rec["value_normalized"], unit="USD",
                currency="USD",
            ),
            origin_by_id=origins, records_by_id=records, target_date="2026-05-13",
            expected_symbol="COF",
        )
        assert good.status == STATUS_VERIFIED
        wrong = _vc(
            ClaimRecord(
                evidence_ids=[close_id], metric="close", date_role="observation_date",
                date="2026-05-05", value=rec["value_normalized"], unit="USD",
                currency="USD",
            ),
            origin_by_id=origins, records_by_id=records, target_date="2026-05-13",
            expected_symbol="COF",
        )
        assert wrong.status == STATUS_REJECTED
        assert wrong.reason == REASON_DATE_MISMATCH


class TestMultiRecordNoLaundering:
    """A good cited ID must NOT launder a mismatching co-cited ID (ADR-010)."""

    def _records(self):
        return {
            "good": _record(evidence_id="good", observed_at="2026-05-04", value="200.13"),
            "bad": _record(evidence_id="bad", observed_at="2026-05-05", value="200.13"),
        }

    def _origins(self):
        return dict(
            [
                _origin("good", observation_date="2026-05-04"),
                _origin("bad", observation_date="2026-05-05"),
            ]
        )

    def test_good_plus_bad_is_not_verified(self):
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["good", "bad"], metric="close",
                date_role="observation_date", date="2026-05-04",
                value="200.13", unit="USD", currency="USD",
            ),
            records=self._records(), origins=self._origins(),
        )
        # 'good' matches; 'bad' mismatches (05-05 vs 05-04). The set is
        # inconsistent -> NOT verified, and the passing ID is not promoted alone.
        assert verdict.status != STATUS_VERIFIED
        assert "good" not in verdict.support_evidence_ids

    def test_single_good_is_verified_with_support_id(self):
        verdict = _validate(
            ClaimRecord(
                evidence_ids=["good"], metric="close",
                date_role="observation_date", date="2026-05-04",
                value="200.13", unit="USD", currency="USD",
            ),
            records=self._records(), origins=self._origins(),
        )
        assert verdict.status == STATUS_VERIFIED
        assert verdict.support_evidence_ids == ["good"]


class TestIdentityAndPITFailClosed:
    def _rec(self, **over):
        base = _record()
        base.update(over)
        return base

    def test_empty_schema_version_rejected(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD",
                        schema_version="")
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_INVALID_SCHEMA

    def test_missing_target_date_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            target_override=None,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_TARGET_UNKNOWN

    def test_missing_record_observation_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            records={"id1": self._rec(observed_at=None)},
            origins=dict([_origin("id1", observation_date=None)]),
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason in (REASON_OBSERVATION_UNKNOWN, REASON_DATE_ROLE_UNKNOWN)

    def test_missing_record_run_id_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            records={"id1": self._rec(run_id="")},
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_RECORD_RUN_UNKNOWN

    def test_availability_after_target_rejected_regardless_of_role(self):
        # The claim asserts the OBSERVATION role (in-window), but the record's
        # availability/filed date is after the target -> look-ahead -> rejected.
        rec = self._rec(observed_at="2026-05-04")
        origin = dict(
            [_origin("id1", observation_date="2026-05-04", filed_at="2026-06-01T09:00:00Z")]
        )
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_AVAILABILITY_FUTURE

    def test_origin_contradicting_record_unverified(self):
        # Origin says observation 2026-05-04 but the record's observed_at is
        # 2026-05-06 -> the typed origin cannot vouch for a mismatching record.
        rec = self._rec(observed_at="2026-05-06")
        origin = dict([_origin("id1", observation_date="2026-05-04")])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_ORIGIN_INCONSISTENT


class TestUnitsFailClosed:
    def test_missing_currency_for_monetary_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD")
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNIT_UNKNOWN

    def test_missing_unit_for_monetary_unverified(self):
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="", currency="USD")
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNIT_UNKNOWN

    def test_million_unit_does_not_infer_usd(self):
        from tradingagents.debate.claims import _normalize_unit

        # A scale word must never be normalized into a currency.
        assert _normalize_unit("million") == "million"
        assert _normalize_unit("mn") == "mn"
        assert _normalize_unit("bn") == "bn"

    def test_million_unit_claim_against_usd_record_rejected(self):
        rec = _record(value="200130000")
        origin = dict([_origin("id1", value_scale=SCALE_BASE)])
        verdict = _validate(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="million"),
            records={"id1": rec}, origins=origin,
        )
        assert verdict.status != STATUS_VERIFIED


class TestRealProducerPathScaleAndDimensions:
    """Scale/magnitude and dimension semantics via the REAL adapter/origin path."""

    def _sec(self, value, unit="USD", filed="2026-05-02", period_end="2026-03-31"):
        from tradingagents.evidence.vendor_adapters import (
            build_sec_fundamentals_record,
            build_sec_origin,
        )

        rec = build_sec_fundamentals_record(
            run_id=RUN_ID, symbol_input=SYMBOL, symbol_normalized=SYMBOL,
            target_date=TARGET, metric_name="revenue", value_raw=str(value),
            value_normalized=value, unit_raw=unit, filed_date=filed,
            period_end=period_end, source_ref="sec:income_statement:accn:revenue",
            fetched_at="2026-05-13T12:00:00Z",
        )
        origin = build_sec_origin(
            target_date=TARGET, filed_date=filed, period_end=period_end, unit=unit,
            fetched_at="2026-05-13T12:00:00Z",
        )
        # The gate reclassifies a captured record after validation; a valid filed
        # SEC fact is Medium/High at the manifest. Mirror that here.
        rec_dict = rec.to_dict()
        rec_dict["quality_status"] = "Medium"
        return rec_dict, origin

    def test_sec_base_vs_millions_equivalence_both_directions(self):
        from decimal import Decimal as D

        # SEC stores the BASE magnitude (391000000000 USD); origin scale base.
        rec, origin = self._sec(D("391000000000"))
        origins = {rec["evidence_id"]: origin}
        records = {rec["evidence_id"]: rec}
        # "391000 million USD" normalizes to base and verifies...
        millions = validate_claim(
            ClaimRecord(evidence_ids=[rec["evidence_id"]], metric="revenue",
                        date_role="observation_date", date="2026-03-31",
                        value="391000", unit="USD", currency="USD", value_scale="1000000"),
            origin_by_id=origins, records_by_id=records, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        # ...and the base-unit equivalent also verifies.
        base = validate_claim(
            ClaimRecord(evidence_ids=[rec["evidence_id"]], metric="revenue",
                        date_role="observation_date", date="2026-03-31",
                        value="391000000000", unit="USD", currency="USD"),
            origin_by_id=origins, records_by_id=records, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert millions.status == STATUS_VERIFIED
        assert base.status == STATUS_VERIFIED

    def test_sec_observation_is_fiscal_end_not_filed(self):
        from decimal import Decimal as D

        rec, origin = self._sec(D("391000000000"))
        origins = {rec["evidence_id"]: origin}
        records = {rec["evidence_id"]: rec}
        # Claiming the FILED date as the fiscal period (observation) is rejected.
        wrong = validate_claim(
            ClaimRecord(evidence_ids=[rec["evidence_id"]], metric="revenue",
                        date_role="observation_date", date="2026-05-02",
                        value="391000000000", unit="USD", currency="USD"),
            origin_by_id=origins, records_by_id=records, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert wrong.status == STATUS_REJECTED

    def test_shares_vs_percent_are_different_dimensions(self):
        rec = _record(value="0.4", unit="percent")
        origin = dict([_origin("id1", unit="percent", currency="", value_scale=SCALE_BASE)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="0.4", unit="shares"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_UNIT_MISMATCH

    def test_bare_million_unit_does_not_guess_currency(self):
        # A claim whose UNIT is literally "million" must not be treated as USD; the
        # unit mismatch against a USD record is rejected (never inferred).
        rec = _record(value="391000000000", unit="USD")
        origin = dict([_origin("id1", unit="USD", currency="USD", value_scale=SCALE_BASE)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="391000", unit="million"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status != STATUS_VERIFIED


class TestDimensionAndScalePrimitives:
    """Dimension/normalization semantics must be KNOWN for all numeric claims."""

    def test_missing_unit_for_shares_unverified(self):
        rec = _record(value="1000", unit="shares")
        origin = dict([_origin("id1", unit="shares", currency="", value_scale=SCALE_BASE)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="1000"),  # no unit
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNIT_UNKNOWN

    def test_missing_unit_for_percent_unverified(self):
        rec = _record(value="0.4", unit="percent")
        origin = dict([_origin("id1", unit="percent", currency="", value_scale=SCALE_BASE)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="0.4"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNIT_UNKNOWN

    def test_record_without_dimension_unverified(self):
        rec = _record(value="200.13", unit="native_quote_currency")
        origin = dict([_origin("id1", unit="native_quote_currency", currency="", value_scale=SCALE_BASE)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_UNIT_UNKNOWN

    def test_explicit_claim_scale_with_unknown_origin_scale_unverified(self):
        # An explicit claim multiplier must not invent missing record magnitude
        # semantics: if the record's origin scale is unknown, unverified.
        rec = _record(value="391000000000")
        origin = dict([_origin("id1", value_scale=None)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="391000", unit="USD", currency="USD",
                        value_scale="1000000"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_SCALE_UNKNOWN

    def test_explicit_dimensionless_ratio_with_matching_record_verifies(self):
        rec = _record(value="0.42", unit="ratio")
        origin = dict([_origin("id1", unit="ratio", currency="", value_scale=SCALE_BASE)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="0.42", unit="ratio"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_VERIFIED

    def test_ratio_claim_vs_percent_record_rejected(self):
        rec = _record(value="0.42", unit="percent")
        origin = dict([_origin("id1", unit="percent", currency="", value_scale=SCALE_BASE)])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="0.42", unit="ratio"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_REJECTED
        assert verdict.reason == REASON_UNIT_MISMATCH

    def test_internally_consistent_but_foreign_target_record_unverified(self):
        # Record + origin agree with each other but name a DIFFERENT trade date than
        # the requested target -> not proof for this run.
        rec = _record(observed_at="2026-05-04")
        rec["target_date"] = "2026-04-30"  # foreign target
        origin = dict([_origin("id1", target_date="2026-04-30", observation_date="2026-05-04")])
        verdict = validate_claim(
            ClaimRecord(evidence_ids=["id1"], metric="close", date_role="observation_date",
                        date="2026-05-04", value="200.13", unit="USD", currency="USD"),
            origin_by_id=origin, records_by_id={"id1": rec}, target_date=TARGET,
            expected_symbol=SYMBOL, expected_run_id=RUN_ID,
        )
        assert verdict.status == STATUS_UNVERIFIED
        assert verdict.reason == REASON_ORIGIN_INCONSISTENT
