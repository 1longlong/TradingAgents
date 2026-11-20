"""ADR-011 Stage 4: deterministic degraded-run confidence cap — PURE matrix.

Approved test cases (2026-11-11 human plan/test approval, including cap 0.60;
plan + tests ONLY, not final human acceptance). These prove the central pure
policy (:mod:`tradingagents.debate.confidence_policy`) in isolation:

- normal / degraded / blocked verdict matrix;
- boundary values 0, 0.59, 0.60, 0.61, 1 and the exact-comparison case 0.6000001;
- invalid numeric inputs (bool / NaN / inf / negative / > 1 / wrong type);
- categorical (low/medium/high) and absent confidence unchanged and distinct;
- explicit confidence prose: prefix / suffix / Markdown bold / DEBATE_METADATA
  ``confidence=`` labels, fullwidth + NFKC-length-changing prefixes, repeated and
  conflicting values;
- ordinary financial figures (returns, margins, positions, prices, dates) are
  byte-for-byte unchanged;
- bare ``confidence: 95`` (no %) and malformed percentages / NaN / true are
  quarantined, not reinterpreted;
- idempotent repeated application;
- ``apply_confidence_cap(previous=...)`` cannot be forged to override a new value;
- the trusted verdict is derived from the authoritative gate, never from a
  caller-supplied confidence-audit field.

No network, no paid LLM.

Traceability: FR-DQG-006, NFR-AUD-001, NFR-DET-001, NFR-BC-001, INV-1/INV-2/INV-6.
"""

from __future__ import annotations

import pytest

from tradingagents.debate.confidence_policy import (
    CONFIDENCE_POLICY_VERSION,
    DEGRADED_CONFIDENCE_CAP,
    QUARANTINE_MARKER,
    REASON_CAPPED,
    REASON_INVALID,
    apply_confidence_cap,
    cap_value,
    confidence_cap_summary,
    current_trusted_verdict,
    exceeds_cap,
    is_valid_numeric_confidence,
    merge_audit,
    rewrite_confidence_text,
    scan_confidence_text,
)


def _state(verdict: str) -> dict:
    if verdict is None:
        return {}
    return {
        "data_quality_verdict": verdict,
        "data_quality_gate_decision": {"decision": verdict},
    }


# ---------------------------------------------------------------------------
# Numeric validation
# ---------------------------------------------------------------------------


class TestNumericValidation:
    @pytest.mark.parametrize("value", [0.0, 0.59, 0.60, 0.61, 1.0, 0.95, 0])
    def test_valid_finite_in_range(self, value):
        assert is_valid_numeric_confidence(value) is True

    @pytest.mark.parametrize(
        "value",
        [True, False, float("nan"), float("inf"), float("-inf"), -0.1, 1.1, None,
         "0.95", [0.5], {"x": 1}],
    )
    def test_invalid_rejected(self, value):
        assert is_valid_numeric_confidence(value) is False


# ---------------------------------------------------------------------------
# Verdict matrix + boundary values
# ---------------------------------------------------------------------------


class TestVerdictMatrix:
    def test_normal_never_changes_valid_value(self):
        for value in (0.0, 0.59, 0.60, 0.61, 1.0, 0.95):
            assert cap_value(value, "normal") == float(value)

    def test_degraded_caps_only_above_cap(self):
        assert cap_value(0.0, "degraded") == 0.0
        assert cap_value(0.59, "degraded") == 0.59
        assert cap_value(0.60, "degraded") == DEGRADED_CONFIDENCE_CAP
        assert cap_value(0.61, "degraded") == DEGRADED_CONFIDENCE_CAP
        assert cap_value(1.0, "degraded") == DEGRADED_CONFIDENCE_CAP
        assert cap_value(0.95, "degraded") == DEGRADED_CONFIDENCE_CAP

    def test_exact_comparison_case(self):
        # 0.6000001 genuinely exceeds 0.60 and MUST be capped (not truncated first).
        assert exceeds_cap(0.6000001) is True
        assert cap_value(0.6000001, "degraded") == DEGRADED_CONFIDENCE_CAP
        assert exceeds_cap(0.60) is False
        assert cap_value(0.60, "degraded") == 0.60
        assert exceeds_cap(0.599) is False

    def test_blocked_never_changes_valid_value(self):
        assert cap_value(0.95, "blocked") == 0.95

    def test_missing_stays_missing(self):
        assert cap_value(None, "degraded") is None
        assert cap_value(None, "normal") is None
        assert cap_value(True, "degraded") is None

    def test_cap_value_is_engineering_constant(self):
        assert DEGRADED_CONFIDENCE_CAP == 0.60


# ---------------------------------------------------------------------------
# Trusted verdict source
# ---------------------------------------------------------------------------


class TestTrustedVerdict:
    def test_reads_authoritative_gate(self):
        assert current_trusted_verdict(_state("normal")) == "normal"
        assert current_trusted_verdict(_state("degraded")) == "degraded"
        assert current_trusted_verdict(_state("blocked")) == "blocked"

    def test_missing_or_mismatched_fails_closed(self):
        assert current_trusted_verdict({}) == "blocked"
        assert current_trusted_verdict(
            {"data_quality_verdict": "normal", "data_quality_gate_decision": {"decision": "blocked"}}
        ) == "blocked"

    def test_caller_audit_field_cannot_override_verdict(self):
        # A caller-supplied "the cap was already applied / verdict normal" audit
        # field must NOT change the authoritative verdict.
        state = _state("degraded")
        state["confidence_cap_audit"] = [{"boundary": "x", "source": "y", "verdict": "normal"}]
        state["confidence_cap_verdict"] = "normal"
        assert current_trusted_verdict(state) == "degraded"


# ---------------------------------------------------------------------------
# apply_confidence_cap audit shape + previous safety
# ---------------------------------------------------------------------------


class TestApplyConfidenceCap:
    def test_audit_shape(self):
        entry = apply_confidence_cap(0.95, "degraded", source="Bull", boundary="turn:1")
        assert entry["raw_value"] == 0.95
        assert entry["effective_value"] == DEGRADED_CONFIDENCE_CAP
        assert entry["capped"] is True
        assert entry["reason"] == REASON_CAPPED
        assert entry["policy_version"] == CONFIDENCE_POLICY_VERSION
        assert entry["boundary"] == "turn:1"
        assert entry["source"] == "Bull"

    def test_normal_value_not_capped(self):
        entry = apply_confidence_cap(0.4, "normal", source="RM", boundary="plan")
        assert entry["capped"] is False
        assert entry["effective_value"] == 0.4

    def test_absent_not_fabricated(self):
        entry = apply_confidence_cap(None, "degraded", source="RM", boundary="plan")
        assert entry["raw_value"] is None
        assert entry["effective_value"] is None
        assert entry["capped"] is False

    def test_forged_previous_cannot_override_new_value(self):
        forged = {"raw_value": 0.1, "effective_value": 0.1}
        entry = apply_confidence_cap(
            0.95, "degraded", source="Bull", boundary="t", previous=forged
        )
        # The real new value wins; the forged low raw is ignored.
        assert entry["raw_value"] == 0.95
        assert entry["effective_value"] == DEGRADED_CONFIDENCE_CAP

    def test_previous_never_raises_effective(self):
        forged_high = {"raw_value": 0.95, "effective_value": 0.6}
        entry = apply_confidence_cap(
            0.2, "degraded", source="Bull", boundary="t", previous=forged_high
        )
        assert entry["raw_value"] == 0.2
        assert entry["effective_value"] == 0.2

    def test_previous_retains_provenance_on_no_new_value(self):
        entry = apply_confidence_cap(
            None, "degraded", source="Bull", boundary="t",
            previous={"raw_value": 0.95},
        )
        assert entry["raw_value"] == 0.95
        assert entry["effective_value"] == DEGRADED_CONFIDENCE_CAP


# ---------------------------------------------------------------------------
# Prose rewrite: scoped to explicit confidence labels only
# ---------------------------------------------------------------------------


class TestProseRewriteScoping:
    @pytest.mark.parametrize(
        "text",
        [
            "Revenue increased 95%; position 0.95 shares; close 200.13 on 2026-05-04",
            "Margin expanded to 0.31 and returns hit 12%; we hold 200 shares.",
            "The close of 200.13 on 2026-05-13 is above the 50-day average.",
            "Entry 189.5, stop 172.0, sizing 5% of portfolio.",
        ],
    )
    def test_financial_figures_unchanged(self, text):
        out, audit = rewrite_confidence_text(text, "degraded")
        assert out == text
        assert audit == []

    @pytest.mark.parametrize(
        "text",
        [
            "Confidence: 95%",
            "confidence of 0.95",
            "95% confidence",
            "0.95 confidence level",
            "**Confidence:** 0.9",
            "confidence=0.9",
            "DEBATE_METADATA: stance=Buy; confidence=0.95; cited=x/1",
        ],
    )
    def test_labelled_confidence_capped(self, text):
        out, audit = rewrite_confidence_text(text, "degraded")
        assert "0.6" in out or "60%" in out
        assert all(a["capped"] for a in audit if a.get("capped"))
        # No raw over-cap confidence token remains.
        assert "95%" not in out
        assert "0.95" not in out
        assert "confidence=0.9" not in out

    def test_fullwidth_labelled_capped(self):
        out, audit = rewrite_confidence_text("Confidence: ０.９５", "degraded")
        assert "0.6" in out
        assert "０.９５" not in out
        assert audit and audit[0]["capped"]

    def test_nfkc_length_changing_prefix_not_corrupted(self):
        # A ligature in the prefix expands under NFKC ("ﬁ" -> "fi"); the edit must
        # land on the confidence token, not shift into the prefix.
        text = "The ﬁrm noted confidence: 95% growth"
        out, _audit = rewrite_confidence_text(text, "degraded")
        assert out == "The ﬁrm noted confidence: 60% growth"

    def test_repeated_conflicting_both_capped(self):
        text = "Confidence: 0.95 then confidence: 0.9"
        out, audit = rewrite_confidence_text(text, "degraded")
        assert "0.95" not in out
        assert out.count("0.6") == 2
        assert len([a for a in audit if a["capped"]]) == 2

    def test_within_cap_labelled_unchanged(self):
        text = "Confidence: 0.55 and 60% confidence"
        out, audit = rewrite_confidence_text(text, "degraded")
        assert out == text
        assert audit == []

    def test_normal_verdict_unchanged(self):
        text = "Confidence: 95% and confidence: 0.95"
        out, audit = rewrite_confidence_text(text, "normal")
        assert out == text
        assert audit == []

    def test_blocked_verdict_unchanged(self):
        text = "Confidence: 95%"
        out, audit = rewrite_confidence_text(text, "blocked")
        assert out == text
        assert audit == []


# ---------------------------------------------------------------------------
# Invalid explicit confidence -> quarantine (not authoritative)
# ---------------------------------------------------------------------------


class TestInvalidQuarantine:
    @pytest.mark.parametrize(
        "text",
        [
            "Confidence: 95",          # bare, outside the fraction contract
            "Confidence: 101%",        # out of range percentage
            "Confidence: NaN",
            "Confidence: inf",
            "Confidence: true",
            "confidence: -5%",
        ],
    )
    def test_invalid_quarantined(self, text):
        out, audit = rewrite_confidence_text(text, "degraded")
        assert QUARANTINE_MARKER in out
        assert any(a["reason"] == REASON_INVALID and a.get("quarantined") for a in audit)

    def test_valid_then_invalid_duplicate(self):
        text = "Confidence: 0.95 and confidence: NaN"
        out, audit = rewrite_confidence_text(text, "degraded")
        assert "0.95" not in out
        assert "0.6" in out
        assert QUARANTINE_MARKER in out
        reasons = {a["reason"] for a in audit}
        assert REASON_CAPPED in reasons
        assert REASON_INVALID in reasons

    def test_bare_confidence_not_reinterpreted_as_percent(self):
        out, _audit = rewrite_confidence_text("confidence: 95", "degraded")
        assert "60%" not in out
        assert QUARANTINE_MARKER in out


# ---------------------------------------------------------------------------
# Categorical / absent unchanged and distinct
# ---------------------------------------------------------------------------


class TestCategoricalAndAbsent:
    @pytest.mark.parametrize("label", ["low", "medium", "high"])
    def test_categorical_unchanged(self, label):
        text = f"Confidence: {label}"
        out, audit = rewrite_confidence_text(text, "degraded")
        assert out == text
        assert audit == []

    def test_categorical_scan_distinct_from_numeric(self):
        scan = scan_confidence_text("Confidence: high")
        assert scan["numeric"] == []
        assert scan["categorical"] == ["high"]

    def test_absent_no_entry_no_fabrication(self):
        out, audit = rewrite_confidence_text("No confidence is stated here.", "degraded")
        assert audit == []
        assert out == "No confidence is stated here."

    def test_scan_reports_only_labelled_numerics(self):
        scan = scan_confidence_text("Revenue 95%; confidence: 0.9; margin 0.31")
        assert len(scan["numeric"]) == 1
        assert scan["numeric"][0]["value"] == 0.9


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_repeated_application_stable(self):
        text = "Confidence: 95% and confidence: 0.9"
        once, _ = rewrite_confidence_text(text, "degraded")
        twice, audit2 = rewrite_confidence_text(once, "degraded")
        assert once == twice
        assert audit2 == []

    def test_capped_audit_is_stable(self):
        first = apply_confidence_cap(0.95, "degraded", source="Bull", boundary="t")
        # A provenance-only re-entry (no NEW value) retains the original raw.
        second = apply_confidence_cap(
            None, "degraded", source="Bull", boundary="t", previous=first,
        )
        assert second["raw_value"] == first["raw_value"]
        assert second["effective_value"] == first["effective_value"]
        assert second["capped"] is True


# ---------------------------------------------------------------------------
# merge_audit / summary
# ---------------------------------------------------------------------------


class TestMergeAudit:
    def test_duplicate_identity_collapsed(self):
        a = {"boundary": "b", "source": "s", "raw_value": 0.95, "effective_value": 0.6}
        b = {"boundary": "b", "source": "s", "raw_value": 0.9, "effective_value": 0.6}
        merged = merge_audit([a], [b])
        assert len(merged) == 1
        assert merged[0]["raw_value"] == 0.9

    def test_distinct_identities_kept(self):
        a = {"boundary": "b", "source": "Bull", "effective_value": 0.6}
        b = {"boundary": "b", "source": "Bear", "effective_value": 0.6}
        assert len(merge_audit([], [a, b])) == 2

    def test_summary_degrades_correctly(self):
        state = _state("degraded")
        state["confidence_cap_audit"] = [
            {"boundary": "b", "source": "s", "capped": True, "quarantined": False},
            {"boundary": "c", "source": "s", "capped": False, "quarantined": True},
        ]
        summary = confidence_cap_summary(state)
        assert summary["verdict"] == "degraded"
        assert summary["cap_applies"] is True
        assert summary["capped_count"] == 1
        assert summary["quarantined_count"] == 1
        assert summary["cap"] == DEGRADED_CONFIDENCE_CAP

    def test_summary_normal_cap_not_applied(self):
        summary = confidence_cap_summary(_state("normal"))
        assert summary["cap_applies"] is False


# ---------------------------------------------------------------------------
# Typed decision schemas: cap at FULL raw precision BEFORE the lossy 2-decimal
# render (ADR-011 precision/audit fix).
# ---------------------------------------------------------------------------


class TestTypedSchemaPrecisionCap:
    """A typed ``confidence`` must be capped on its exact raw value, not the
    ``:.2f`` rendered text. ``0.6000001`` / ``0.604`` round to ``0.60`` and would
    otherwise never register as an over-cap event; ``0.954321`` rounds to ``0.95``
    and would lose the original raw. The central policy must see the exact value.
    """

    @pytest.mark.parametrize("raw", [0.6000001, 0.604, 0.954321])
    @pytest.mark.parametrize(
        "make_and_render",
        [
            "research_plan",
            "trader_proposal",
            "portfolio_decision",
        ],
    )
    def test_degraded_caps_raw_precision_and_audits_exact(self, raw, make_and_render):
        from tradingagents.agents.schemas import (
            PortfolioDecision,
            PortfolioRating,
            ResearchPlan,
            TraderAction,
            TraderProposal,
            render_pm_decision,
            render_research_plan,
            render_trader_proposal,
        )
        from tradingagents.debate.confidence_policy import cap_typed_confidence

        if make_and_render == "research_plan":
            model = ResearchPlan(
                recommendation=PortfolioRating.BUY,
                rationale="growth is durable",
                strategic_actions="accumulate",
                confidence=raw,
            )
            render = render_research_plan
        elif make_and_render == "trader_proposal":
            model = TraderProposal(
                action=TraderAction.BUY,
                reasoning="demand strong",
                confidence=raw,
            )
            render = render_trader_proposal
        else:
            model = PortfolioDecision(
                rating=PortfolioRating.BUY,
                executive_summary="enter",
                investment_thesis="momentum",
                confidence=raw,
            )
            render = render_pm_decision

        sink: list[dict] = []
        capped = cap_typed_confidence(
            model, _state("degraded"), source="t", boundary="b", sink=sink
        )
        # The model was genuinely capped (not merely the rounded text).
        assert float(capped.confidence) <= DEGRADED_CONFIDENCE_CAP
        # The rendered line is the effective capped value.
        rendered = render(capped)
        assert "**Confidence**: 0.60" in rendered or "**Confidence**: 0.6" in rendered
        # The audit entry preserves the EXACT original raw (not the 2dp rounded one).
        capped_entries = [e for e in sink if e.get("capped")]
        assert capped_entries, "expected a capped audit entry for the raw value"
        entry = capped_entries[0]
        assert entry["raw_value"] == raw
        assert entry["reason"] == REASON_CAPPED
        assert entry["effective_value"] == DEGRADED_CONFIDENCE_CAP

    @pytest.mark.parametrize("raw", [0.6000001, 0.604, 0.954321])
    def test_normal_run_unchanged(self, raw):
        from tradingagents.agents.schemas import (
            PortfolioRating,
            ResearchPlan,
            render_research_plan,
        )
        from tradingagents.debate.confidence_policy import cap_typed_confidence

        model = ResearchPlan(
            recommendation=PortfolioRating.BUY,
            rationale="growth",
            strategic_actions="accumulate",
            confidence=raw,
        )
        sink: list[dict] = []
        same = cap_typed_confidence(
            model, _state("normal"), source="t", boundary="b", sink=sink
        )
        # Unchanged value and no audit entry on a normal run.
        assert same.confidence == raw
        assert sink == []
        assert render_research_plan(same) == render_research_plan(model)

    def test_within_cap_high_precision_unchanged(self):
        from tradingagents.agents.schemas import (
            PortfolioRating,
            ResearchPlan,
        )
        from tradingagents.debate.confidence_policy import cap_typed_confidence

        model = ResearchPlan(
            recommendation=PortfolioRating.BUY,
            rationale="growth",
            strategic_actions="accumulate",
            confidence=0.5999999,
        )
        sink: list[dict] = []
        same = cap_typed_confidence(
            model, _state("degraded"), source="t", boundary="b", sink=sink
        )
        assert same.confidence == 0.5999999
        assert [e for e in sink if e.get("capped")] == []
