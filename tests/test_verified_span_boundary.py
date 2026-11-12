"""ADR-010 amendment (2026-11-12): verified typed span is not re-redacted as prose.

Approved plan + test cases: human WANG Yiwen, 2026-11-12 (implementation approval
ONLY, NOT final human acceptance). This pins the residual false-redaction repair
found in the 2026-11-12 school live run: a CORRECT long-decimal typed claim that
strictly validates as ``verified`` was then re-parsed by the generic prose scanner,
which uses a lossy nearest-unit proximity; the explicit ``unit=shares`` fell beyond
the 24-character window for the long normalized value, so
``claim_unit_or_currency_unknown`` blanked the already-verified date/value (evidence
LOSS, not bad-claim acceptance).

The repair makes an AUTHORIZED date/value span from a VERIFIED typed ``ClaimRecord``
authoritative for that exact span, while every OTHER assertion (separate prose,
same-line/adjacent tails, non-verified/malformed/unsupported typed claims) is still
validated. The exemption is tied to exact ``date=``/``value=`` field positions of
that specific verified record on NFKC-normalized text — not whole lines, not a
matching evidence ID alone, not substring matches, not an enlarged unit window.
Authority is applied PER verified token occurrence (independent of any heuristic
date↔value pairing): a verified date/value token is never erased, and a wrong
value/date is a different (unauthorized) span that is still redacted even when the
heuristic pairs it with a protected token. There is no whole-line bypass.

No network, no paid LLM.

Traceability: FR-DDT-002, NFR-AUD-001, NFR-PIT-001, NFR-BC-001, INV-1/INV-3/INV-6.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradingagents.agents.utils.output_guard import enforce_trusted_boundary
from tradingagents.evidence.origin import OriginMetadata

SYMBOL = "NVDA"
TARGET = "2026-11-05"
ORG = f"{TARGET}/{SYMBOL}/market/yfinance/volume/0"

_RECORD = {
    "evidence_id": ORG,
    "run_id": f"{TARGET}/{SYMBOL}",
    "ticker_input": SYMBOL,
    "ticker_normalized": SYMBOL,
    "category": "market",
    "metric_name": "volume",
    "value_raw": "306127800",
    "value_normalized": "306127800.0000000000",
    "unit_normalized": "shares",
    "observed_at": TARGET,
    "target_date": TARGET,
    "quality_status": "Medium",
    "validation_results": [],
}
_ORIGIN = OriginMetadata(
    target_date=TARGET,
    observation_date=TARGET,
    availability_date=None,
    retrieved_at="2026-11-12T00:00:00Z",
    date_basis="period_end",
    value_scale=Decimal("1"),
    unit="shares",
    currency="",
)


def _state(records=None, origin=None):
    return {
        "data_quality_verdict": "normal",
        "data_quality_gate_decision": {"decision": "normal", "decided_at": "2026-11-12T00:00:00Z"},
        "company_of_interest": SYMBOL,
        "trade_date": TARGET,
        "data_quality_evidence_records": [dict(r) for r in (records or [_RECORD])],
        "data_quality_origin_metadata": {ORG: (origin or _ORIGIN).to_dict()},
    }


def _typed(value="306127800.0000000000", date=TARGET, unit="shares", evidence=ORG, role="observation_date"):
    return f"claim=metric=volume|role={role}|date={date}|value={value}|unit={unit}|evidence={evidence}"


class TestVerifiedLongValuePreserved:
    def test_exact_residual_long_value_preserved(self):
        line = _typed("306127800.0000000000")
        prov: list = []
        out = enforce_trusted_boundary(line, _state(), provenance=prov)
        assert out == line
        assert "306127800.0000000000" in out
        assert "claim_unit_or_currency_unknown" not in {p.get("reason") for p in prov}
        assert prov == []

    @pytest.mark.parametrize("value", ["306127800", "306127800.0000000000"])
    def test_equivalent_representations_both_preserved(self, value):
        line = _typed(value)
        assert enforce_trusted_boundary(line, _state()) == line

    @pytest.mark.parametrize(
        "value",
        [
            "306127800.000000000000000000000000",  # long extra zeros
            "3.061278e8",  # scientific (lower e)
            "3.061278E8",  # scientific (upper E)
            "306127800.0",
        ],
    )
    def test_equivalent_numeric_forms_preserved(self, value):
        # A raw token that differs from the normalized ClaimRecord.value but is
        # numerically equivalent MUST still be protected (span from the raw payload
        # occurrence; equivalence proven by strict ClaimRecord normalization).
        line = _typed(value)
        assert enforce_trusted_boundary(line, _state()) == line

    @pytest.mark.parametrize("value", ["306127801", "3.061279e8", "306127800.1"])
    def test_nearby_wrong_values_redacted(self, value):
        line = _typed(value)
        out = enforce_trusted_boundary(line, _state())
        assert "[unverified exact claim omitted]" in out

    def test_duplicate_identical_payloads_distinct_offsets(self):
        # Two identical claim payloads in one marker line must each get their own
        # occurrence offset (no line.find first-match collapse). Both are the same
        # valid claim, so both survive unchanged.
        sub = _typed()
        line = f"DEBATE_METADATA: stance=Hold; confidence=0.45; {sub};{sub}"
        out = enforce_trusted_boundary(line, _state())
        assert out == line

    @pytest.mark.parametrize(
        "line",
        [
            # Uppercase field keys (strict parser accepts case-insensitive stripped keys).
            f"claim=metric=volume|role=observation_date|DATE={TARGET}|VALUE=306127800.0000000000|unit=shares|evidence={ORG}",
            # Spaced keys around '='.
            f"claim=metric=volume|role=observation_date|date = {TARGET}|value = 306127800.0000000000|unit=shares|evidence={ORG}",
            # Canonical claim wrapped in backticks (turn/occurrence path strips them).
            f"DEBATE_METADATA: stance=Hold; confidence=0.45; claim=`metric=volume|role=observation_date|date={TARGET}|value=306127800.0000000000|unit=shares|evidence={ORG}`",
        ],
    )
    def test_supported_format_variants_preserved(self, line):
        # These are SUPPORTED syntax (not grammar expansion); the raw field-offset
        # locator uses the same key.strip().lower() semantics as the strict parser.
        assert enforce_trusted_boundary(line, _state()) == line

    @pytest.mark.parametrize(
        "line",
        [
            f"claim=metric=volume|role=observation_date|DATE={TARGET}|VALUE=999|unit=shares|evidence={ORG}",
            f"claim=metric=volume|role=observation_date|date = {TARGET}|value = 999|unit=shares|evidence={ORG}",
        ],
    )
    def test_supported_format_variants_wrong_value_redacted(self, line):
        out = enforce_trusted_boundary(line, _state())
        assert "[unverified exact claim omitted]" in out

    def test_idempotent(self):
        line = _typed()
        once = enforce_trusted_boundary(line, _state())
        twice = enforce_trusted_boundary(once, _state())
        assert once == twice == line

    def test_idempotent_after_redaction(self):
        # A wrong claim is redacted once; re-applying the boundary is stable.
        line = _typed(value="999.99")
        once = enforce_trusted_boundary(line, _state())
        twice = enforce_trusted_boundary(once, _state())
        assert once == twice
        assert "999.99" not in once

    def test_canonical_marker_claim_preserved(self):
        # Same verified claim inside DEBATE_METADATA is also protected.
        line = (
            "Argument.\n"
            f"DEBATE_METADATA: stance=Hold; confidence=0.45; cited={ORG}; "
            f"claim=metric=volume|role=observation_date|date={TARGET}|value=306127800.0000000000|unit=shares|evidence={ORG}"
        )
        out = enforce_trusted_boundary(line, _state())
        assert "value=306127800.0000000000" in out
        assert "date=2026-11-05" in out

    def test_fullwidth_digits_preserved_via_nfkc(self):
        line = _typed("３０６１２７８００")
        out = enforce_trusted_boundary(line, _state())
        # NFKC normalizes the emitted text; the value survives (not redacted).
        assert "306127800" in out
        assert "[unverified exact claim omitted]" not in out


class TestSeparateProseStillValidated:
    def test_typed_claim_kept_wrong_prose_on_adjacent_line_redacted(self):
        typed = _typed()
        prose = f"Separately, the close was 999.99 USD on {TARGET} per {ORG}."
        out = enforce_trusted_boundary(typed + "\n" + prose, _state())
        assert typed in out  # verified typed claim preserved
        assert "999.99" not in out  # separate wrong fact still redacted

    def test_same_line_protected_date_wrong_unprotected_value_redacted(self):
        # SAME physical line: a verified typed claim (protected date+value) followed by
        # a separate prose clause on the SAME line whose value is wrong. Per-token
        # authority never exempts the unprotected wrong value; the verified token is
        # retained.
        typed = _typed()
        line = typed + f". Separately the mark was 123 per {ORG} on {TARGET}."
        out = enforce_trusted_boundary(line, _state())
        # The whole line is a typed grammar line with a non-parseable tail -> fail
        # closed (the unverified tail alone is redacted too). Either way the wrong
        # 123 value and the unprotected fact cannot remain trusted.
        assert " 123 " not in out
        assert "the mark was 123" not in out

    def test_adjacent_cross_pair_wrong_value_not_exempted(self):
        typed = _typed()
        wrong = f"And on {TARGET} the volume was 123 shares per {ORG}."
        out = enforce_trusted_boundary(typed + "\n" + wrong, _state())
        assert typed in out
        assert " 123 " not in out


class TestCanonicalMixedSameLine:
    def _canonical(self, subclaims):
        return (
            "DEBATE_METADATA: stance=Hold; confidence=0.45; cited=" + ORG + ";"
            + ";".join(subclaims)
        )

    @pytest.mark.parametrize("order", ["good_first", "bad_first"])
    def test_mixed_good_bad_same_id_both_orders(self, order):
        good = _typed(unit="shares")
        bad = _typed(unit="USD")  # same date+value, wrong currency/unit
        subs = [good, bad] if order == "good_first" else [bad, good]
        line = self._canonical(subs)
        out = enforce_trusted_boundary(line, _state())
        # The verified 'shares' subclaim's date+value are preserved.
        assert "value=306127800.0000000000|unit=shares" in out
        # The wrong 'USD' subclaim's date+value are redacted (its unit alone is inert).
        assert "value=[unverified exact claim omitted]|unit=USD" in out
        # Exactly one subclaim keeps the trusted value; the other is redacted.
        assert out.count("value=306127800.0000000000") == 1

    def test_canonical_unvalidated_tail_prose_redacted(self):
        good = _typed()
        line = self._canonical([good]) + f" Then a wrong 999.99 close on {TARGET}."
        out = enforce_trusted_boundary(line, _state())
        assert "999.99" not in out

    def test_nfkc_fullwidth_good_sibling_preserved_bad_redacted(self):
        # A fullwidth-digit verified subclaim alongside a wrong unit subclaim: NFKC
        # normalization keeps offsets aligned so the good one is preserved and the
        # bad one redacted (occurrence-exact under NFKC).
        good_fw = _typed(value="３０６１２７８００")
        bad = _typed(unit="USD")
        line = self._canonical([good_fw, bad])
        out = enforce_trusted_boundary(line, _state())
        assert "306127800|unit=shares" in out  # normalized good value preserved
        assert "value=[unverified exact claim omitted]|unit=USD" in out


class TestNonVerifiedNeverProtected:
    @pytest.mark.parametrize(
        "line",
        [
            _typed(value="999"),  # wrong value
            _typed(date="2030-01-01"),  # future date / PIT
            _typed(unit="USD"),  # wrong unit
            _typed(evidence="unknown/id/0"),  # unknown id
            _typed(role="availability_date"),  # role mismatch (no origin value)
        ],
    )
    def test_bad_typed_claim_still_redacted(self, line):
        out = enforce_trusted_boundary(line, _state())
        assert "[unverified exact claim omitted]" in out
        # The specific bad bytes cannot remain as a trusted fact.
        assert out != line

    def test_wrong_value_never_survives(self):
        out = enforce_trusted_boundary(_typed(value="999.99"), _state())
        assert "999.99" not in out

    def test_wrong_currency_redacted(self):
        # currency=EUR mismatches the record/origin (empty currency, shares unit).
        line = _typed().replace("|unit=shares|", "|unit=USD|currency=EUR|")
        out = enforce_trusted_boundary(line, _state())
        assert "[unverified exact claim omitted]" in out

    def test_wrong_scale_redacted(self):
        line = _typed(value="306127800.0000000000").replace(
            f"|evidence={ORG}", f"|scale=1000|evidence={ORG}"
        )
        out = enforce_trusted_boundary(line, _state())
        assert "[unverified exact claim omitted]" in out

    @pytest.mark.parametrize("quality", ["Low", "Blocked"])
    def test_low_blocked_evidence_not_protected(self, quality):
        rec = dict(_RECORD)
        rec["quality_status"] = quality
        out = enforce_trusted_boundary(_typed(), _state(records=[rec]))
        assert "[unverified exact claim omitted]" in out

    def test_fenced_verified_claim_not_promoted(self):
        line = "````\nexample\n```\n" + _typed()
        # 4-backtick opener, 3-backtick line does NOT close; the claim is illustrative
        # and must NEVER be preserved as a verified trusted fact (redaction, if any,
        # also means not-trusted). Either way it is not promoted by the protection.
        out = enforce_trusted_boundary(line, _state())
        assert not (out == line and "value=306127800.0000000000" in out)

    def test_fenced_canonical_claim_not_protected(self):
        # A canonical claim inside a fence must not gain protection (consistent
        # whole-document exclusion, not a permissive substring parser).
        line = (
            "````\n"
            f"DEBATE_METADATA: stance=Hold; confidence=0.45; claim={_typed()[len('claim='):]}\n"
            "```"
        )
        out = enforce_trusted_boundary(line, _state())
        assert not (out == line and "value=306127800.0000000000" in out)

    def test_example_block_canonical_not_protected(self):
        line = "Example:\n" + f"DEBATE_METADATA: stance=Hold; confidence=0.45; {_typed()}"
        out = enforce_trusted_boundary(line, _state())
        assert not (out == line and "value=306127800.0000000000" in out)

    def test_example_block_not_promoted(self):
        line = "Example:\n" + _typed()
        out = enforce_trusted_boundary(line, _state())
        # Not preserved as a verified trusted fact (may be redacted).
        assert not (out == line and "value=306127800.0000000000" in out)


class TestAmbiguousGrammarFailsClosed:
    def test_conflicting_duplicate_value_unparseable_fail_closed(self):
        line = (
            f"claim=metric=volume|role=observation_date|date={TARGET}|value=306127800.0000000000"
            f"|value=123|unit=shares|evidence={ORG}"
        )
        out = enforce_trusted_boundary(line, _state())
        # Unparseable grammar -> the whole line is redacted (no widening/guessing).
        assert out == "[unverified exact claim omitted]"


class TestDuplicateVerifiedOccurrences:
    """Exact-span authority for DUPLICATE verified occurrences (no cross-pair loss).

    Two IDENTICAL verified canonical subclaims joined by ``||`` must both survive
    regardless of field order: a verified token must not be erased just because the
    heuristic date<->value pairing re-pairs it with a SIBLING's date. A wrong sibling
    component is still redacted (only the bad component is removed).
    """

    _FIELDS = [
        "metric=volume",
        "role=observation_date",
        f"date={TARGET}",
        "unit=shares",
        f"evidence={ORG}",
        "value=306127800.0000000000",
    ]

    def test_all_720_identical_duplicate_field_orders_preserved(self):
        import itertools

        failures = []
        for perm in itertools.permutations(self._FIELDS):
            sub = "|".join(perm)
            line = f"DEBATE_METADATA: stance=Hold; claims={sub}||{sub}"
            if enforce_trusted_boundary(line, _state()) != line:
                failures.append(sub)
        assert failures == [], f"{len(failures)} permutations falsely redacted"

    def test_reported_duplicate_input_preserved(self):
        sub = (
            f"metric=volume|role=observation_date|date={TARGET}|unit=shares|"
            f"evidence={ORG}|value=306127800.0000000000"
        )
        line = f"DEBATE_METADATA: stance=Hold; claims={sub}||{sub}"
        out = enforce_trusted_boundary(line, _state())
        assert out == line
        assert "[unverified exact claim omitted]" not in out

    @pytest.mark.parametrize(
        "bad",
        [
            f"metric=volume|role=observation_date|date={TARGET}|value=999|unit=shares|evidence={ORG}",
            f"metric=volume|role=observation_date|date=2030-01-01|value=306127800.0000000000|unit=shares|evidence={ORG}",
            f"metric=volume|role=observation_date|date={TARGET}|value=306127800.0000000000|unit=USD|evidence={ORG}",
        ],
    )
    def test_mixed_verified_and_wrong_sibling_only_bad_removed(self, bad):
        good = (
            f"metric=volume|role=observation_date|date={TARGET}|"
            f"value=306127800.0000000000|unit=shares|evidence={ORG}"
        )
        line = f"DEBATE_METADATA: stance=Hold; claims={good}||{bad}"
        out = enforce_trusted_boundary(line, _state())
        # The good sibling's verified value is preserved.
        assert "value=306127800.0000000000|unit=shares" in out
        # The bad sibling's date+value are redacted.
        assert "value=[unverified exact claim omitted]" in out
        # Exactly one subclaim retains the trusted value.
        assert out.count("value=306127800.0000000000") == 1


class TestFieldOrderAndWrapperOffsets:
    """Strict grammar is field-order independent; offsets must be location-exact.

    Regression for supported-format ordering/wrapper variants (bullet/numeric-list
    standalone, canonical whitespace/backticks, date/value FIRST or LAST): the raw
    field span must point at the exact token in the ORIGINAL line and the verified
    claim must be preserved.
    """

    _DATE_FIRST = (
        f"date={TARGET}|value=306127800.0000000000|metric=volume|"
        f"role=observation_date|unit=shares|evidence={ORG}"
    )
    _DATE_LAST = (
        f"value=306127800.0000000000|metric=volume|role=observation_date|"
        f"unit=shares|evidence={ORG}|date={TARGET}"
    )

    @pytest.mark.parametrize(
        "line",
        [
            "- claim=" + _DATE_FIRST,
            "1. claim=" + _DATE_FIRST,
            "claim=" + _DATE_FIRST,
            f"DEBATE_METADATA: stance=Hold; claim=`{_DATE_FIRST}`",
            f"DEBATE_METADATA: stance=Hold; claim={_DATE_FIRST}",
            "claim=" + _DATE_LAST,
            "- claim=" + _DATE_LAST,
            f"DEBATE_METADATA: stance=Hold; claim=`{_DATE_LAST}`",
        ],
    )
    def test_order_and_wrapper_variants_preserved_with_exact_offsets(self, line):
        from tradingagents.debate.claims import extract_claim_span_occurrences

        out = enforce_trusted_boundary(line, _state())
        assert out == line
        occs = extract_claim_span_occurrences(line)
        assert occs, "expected a parsed occurrence"
        for occ in occs:
            if occ.date_span is not None:
                assert line[occ.date_span[0]:occ.date_span[1]] == TARGET
            if occ.value_span is not None:
                assert line[occ.value_span[0]:occ.value_span[1]] == "306127800.0000000000"

    @pytest.mark.parametrize(
        "line",
        [
            f"- claim=date={TARGET}|value=999|metric=volume|role=observation_date|unit=shares|evidence={ORG}",
            f"DEBATE_METADATA: stance=Hold; claim=`value=999|date={TARGET}|unit=shares|evidence={ORG}`",
        ],
    )
    def test_order_and_wrapper_variants_wrong_value_redacted(self, line):
        out = enforce_trusted_boundary(line, _state())
        assert "[unverified exact claim omitted]" in out


class TestIllustrativeExclusionOccurrences:
    """Direct occurrence assertions: no AUTHORIZED span from fenced/Example/quoted.

    These assert the shared exclusion walker never emits a protected occurrence for
    illustrative/quoted canonical OR standalone forms — stronger than final-text
    inequality, so a redaction cannot mask a wrongly-authorized span.
    """

    def _occurrences(self, text):
        from tradingagents.debate.claims import extract_claim_span_occurrences

        return extract_claim_span_occurrences(text)

    @pytest.mark.parametrize(
        "text",
        [
            "````\nexample\n```\n" + _typed(),  # shorter fence must not close
            "~~~~\n" + _typed() + "\n~~~",  # tilde opener not closed by shorter
            "```\n" + _typed(),  # unclosed backtick fence
        ],
    )
    def test_fenced_standalone_no_occurrence(self, text):
        assert self._occurrences(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "````\nDEBATE_METADATA: stance=Hold; confidence=0.45; " + _typed() + "\n```",
            "~~~\nDEBATE_METADATA: stance=Hold; confidence=0.45; " + _typed() + "\n~~~",
        ],
    )
    def test_fenced_canonical_no_occurrence(self, text):
        assert self._occurrences(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "Example:\n" + _typed(),
            "Examples:\n" + _typed(),
            "Example 1:\nDEBATE_METADATA: stance=Hold; confidence=0.45; " + _typed(),
        ],
    )
    def test_example_block_no_occurrence(self, text):
        assert self._occurrences(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "> " + _typed(),
            "> DEBATE_METADATA: stance=Hold; confidence=0.45; " + _typed(),
            ">DEBATE_METADATA: stance=Hold; confidence=0.45; " + _typed(),
        ],
    )
    def test_quoted_blockquote_no_occurrence(self, text):
        assert self._occurrences(text) == []

    def test_real_line_still_yields_one_occurrence(self):
        # Sanity: exclusion does not over-exclude a legitimate actual claim.
        assert len(self._occurrences(_typed())) == 1


class TestNoManifestAndLegacy:
    def test_verified_claim_without_manifest_not_silently_trusted(self):
        # Without a manifest nothing can verify -> redacted (never silently passed).
        state = _state()
        state["data_quality_evidence_records"] = []
        out = enforce_trusted_boundary(_typed(), state)
        assert "[unverified exact claim omitted]" in out

    def test_legacy_prose_noop(self):
        text = "Revenue grew 12% and margin was 0.31 on 2026-11-05."
        assert enforce_trusted_boundary(text, _state()) == text

    @pytest.mark.parametrize("verdict", ["normal", "degraded", "blocked"])
    def test_no_typed_line_unchanged_across_verdicts(self, verdict):
        # The protection is orthogonal to the confidence cap; ordinary prose is a
        # byte-for-byte no-op regardless of verdict.
        state = _state()
        state["data_quality_verdict"] = verdict
        text = "The close was 200.13 but that is a separate figure."
        assert enforce_trusted_boundary(text, state) == text


class TestActualReportAndMemory:
    def test_write_report_tree_preserves_long_value(self, tmp_path):
        from pathlib import Path

        from tradingagents.reporting import write_report_tree

        state = _state()
        state["trader_investment_plan"] = (
            "Hold.\n" + _typed("306127800.0000000000") + "\nSeparately a wrong 999.99 "
            f"USD close on {TARGET} per {ORG}."
        )
        write_report_tree(state, SYMBOL, tmp_path / "run")
        trader_md = (Path(tmp_path) / "run" / "3_trading" / "trader.md").read_text(encoding="utf-8")
        complete_md = (Path(tmp_path) / "run" / "complete_report.md").read_text(encoding="utf-8")
        for body in (trader_md, complete_md):
            assert "value=306127800.0000000000" in body
            assert "999.99" not in body

    def _real_graph(self, tmp_path):
        # Build the graph object WITHOUT monkeypatching _is_blocked_state; the real
        # staticmethod reads the genuine gate fields in _state() (normal -> not
        # blocked), so the actual production memory logic executes.
        from tradingagents.agents.utils.memory import TradingMemoryLog
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {"memory_log_path": str(tmp_path / "mem.md"), "results_dir": str(tmp_path)}
        graph.memory_log = TradingMemoryLog(graph.config)
        return graph

    def test_record_decision_memory_preserves_long_value(self, tmp_path):
        graph = self._real_graph(tmp_path)
        state = _state()
        # Sanity: the REAL blocked reader agrees this is not blocked.
        assert graph._is_blocked_state(state) is False
        state["final_trade_decision"] = "**Action**: Hold\n\n" + _typed("306127800.0000000000")
        graph.record_decision(SYMBOL, TARGET, state)
        body = "\n".join(str(e) for e in graph.memory_log.load_entries())
        assert "306127800.0000000000" in body

    def test_record_decision_memory_wrong_claim_not_stored(self, tmp_path):
        graph = self._real_graph(tmp_path)
        state = _state()
        assert graph._is_blocked_state(state) is False
        state["final_trade_decision"] = "**Action**: Hold\n\n" + _typed(value="999.99")
        graph.record_decision(SYMBOL, TARGET, state)
        body = "\n".join(str(e) for e in graph.memory_log.load_entries())
        assert "999.99" not in body
