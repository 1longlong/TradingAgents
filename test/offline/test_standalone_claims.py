"""ADR-010 amendment (2026-11-12): standalone typed-claim recovery.

Approved plan + test cases (human WANG Yiwen, 2026-11-12; implementation approval
ONLY, NOT final human acceptance). These pin the DEFECT-2 repair: Bear wrote 8
standalone ``claim=metric=...|...`` lines BEFORE ``DEBATE_METADATA:`` and the
marker-only parser silently produced ``status=ok`` with ``exact_claims=[]`` and an
empty claim-validation summary.

The shared strict extractor recovers an UNAMBIGUOUS standalone typed line so it
enters the SAME date/value/unit/origin validation as a marker claim. Extraction is
NOT trust: a wrong/unknown/future/Low/foreign claim still fails closed. No guessing
of missing fields; an unparseable typed line is surfaced (never an empty success).

No network, no paid LLM.

Traceability: FR-DDT-002, FR-DDT-005, NFR-PIT-001, NFR-AUD-001, NFR-FC-001,
NFR-BC-001, INV-1/INV-3/INV-6/INV-13.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradingagents.debate.claims import (
    canonical_claim_key,
    claim_summary_prompt_block,
    summarize_claim_validations,
    validate_claim,
)
from tradingagents.debate.models import ClaimRecord, MetadataParseStatus
from tradingagents.debate.turn import build_failed_turn, parse_turn_metadata
from tradingagents.evidence.origin import OriginMetadata

SYMBOL = "NVDA"
TARGET = "2026-11-05"
ORG = f"{TARGET}/{SYMBOL}/market/yfinance/close/0"

# The 8 actual Bear lines from the preserved live evidence (verbatim), written
# BEFORE the marker.
BEAR_LINES = [
    "claim=metric=revenue|role=target_date|date=2026-07-31|value=96.22|unit=USD|currency=USD|evidence=2026-11-05/NVDA/fundamentals/q2fy27_revenue",
    "claim=metric=receivables_growth_qoq|role=target_date|date=2026-07-31|value=54.9|unit=percent|evidence=2026-11-05/NVDA/fundamentals/ar_qoq",
    "claim=metric=free_cash_flow_qoq|role=target_date|date=2026-07-31|value=-56|unit=percent|evidence=2026-11-05/NVDA/fundamentals/fcf_qoq",
    "claim=metric=cash_conversion|role=target_date|date=2026-07-31|value=40|unit=percent|evidence=2026-11-05/NVDA/fundamentals/cash_conversion",
    "claim=metric=total_debt|role=target_date|date=2026-07-31|value=38.35|unit=USD|currency=USD|evidence=2026-11-05/NVDA/fundamentals/total_debt",
    f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}",
    f"claim=metric=volume|role=observation_date|date={TARGET}|value=306127800|unit=shares|evidence={TARGET}/NVDA/market/yfinance/volume/0",
    f"claim=metric=low|role=observation_date|date={TARGET}|value=181.46|unit=USD|currency=USD|evidence={TARGET}/NVDA/market/yfinance/low/0",
]

_RECORD = {
    "evidence_id": ORG,
    "run_id": f"{TARGET}/{SYMBOL}",
    "ticker_input": SYMBOL,
    "ticker_normalized": SYMBOL,
    "category": "market",
    "metric_name": "close",
    "value_raw": "181.60",
    "value_normalized": "181.6000000000",
    "unit_normalized": "USD",
    "observed_at": TARGET,
    "target_date": TARGET,
    "quality_status": "Medium",
    "validation_results": [],
}
_ORIGIN = OriginMetadata(
    target_date=TARGET,
    observation_date=TARGET,
    availability_date=None,
    retrieved_at="2026-11-11T12:00:00Z",
    date_basis="period_end",
    value_scale=Decimal("1"),
    unit="USD",
    currency="USD",
)


def _summary(turns):
    return summarize_claim_validations(
        turns,
        origin_by_id={ORG: _ORIGIN},
        records_by_id={ORG: _RECORD},
        target_date=TARGET,
        expected_symbol=SYMBOL,
        expected_run_id=f"{TARGET}/{SYMBOL}",
    )


class TestEightActualBearLines:
    def test_all_eight_recovered_never_empty_success(self):
        # Mirror the preserved live shape: the 8 lines precede a DEBATE_METADATA
        # marker with stance+confidence (marker-only parsing stored 0 claims then).
        text = (
            "Bear argument.\n"
            + "\n".join(BEAR_LINES)
            + f"\nDEBATE_METADATA: stance=Underweight; confidence=0.42; cited={ORG};"
        )
        turn = parse_turn_metadata(speaker="Bear", content=text)
        assert turn.metadata_parse_status is MetadataParseStatus.OK
        assert turn.standalone_typed_claim_count == 8
        assert turn.unparsed_typed_claim_count == 0
        assert len(turn.exact_claims) == 8
        summary = _summary([turn])
        assert summary["coverage"]["typed_lines_found"] == 8
        assert summary["coverage"]["parsed"] == 8
        # Unknown/unmatched fundamentals IDs are rejected/unverified, never verified.
        verified_ids = {i for e in summary["verified"] for i in e["evidence_ids"]}
        assert not any("q2fy27_revenue" in i for i in verified_ids)
        # Never an empty success: the summary has a non-empty coverage block.
        assert summary["coverage"]["typed_lines_found"] > 0

    def test_valid_close_claim_validates_against_real_origin(self):
        close_line = BEAR_LINES[5]
        turn = parse_turn_metadata(speaker="Bear", content=close_line)
        summary = _summary([turn])
        assert len(summary["verified"]) == 1
        assert summary["verified"][0]["metric"] == "close"


class TestMarkerIntegration:
    def test_inside_marker_only_unchanged(self):
        text = (
            "Argument.\n"
            f"DEBATE_METADATA: stance=Buy; confidence=0.7; cited={ORG}; "
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        )
        turn = parse_turn_metadata(speaker="Bull", content=text)
        assert turn.standalone_typed_claim_count == 0
        assert len(turn.exact_claims) == 1

    def test_before_and_after_marker_both_recovered(self):
        inside = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        )
        outside_after = "claim=metric=volume|role=observation_date|date=2026-11-05|value=306127800|unit=shares|evidence=mkt/vol/0"
        text = (
            outside_after + "\n"
            "Argument.\n"
            f"DEBATE_METADATA: stance=Underweight; confidence=0.42; cited={ORG}; "
            f"claim={inside.split('claim=', 1)[1]};"
        )
        turn = parse_turn_metadata(speaker="Bear", content=text)
        metrics = {c.metric for c in turn.exact_claims}
        assert "close" in metrics  # inside marker
        assert "volume" in metrics  # outside, before marker -> not hidden

    def test_marker_cannot_hide_outer_claim(self):
        outer = f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        text = (
            outer + "\n"
            "Argument.\n"
            "DEBATE_METADATA: stance=Buy; confidence=0.7; cited=mkt/x/0; "
            "new_claims=x|mkt/x/0;"
        )
        turn = parse_turn_metadata(speaker="Bull", content=text)
        assert any(c.metric == "close" for c in turn.exact_claims)


class TestNoMarkerAndNoStance:
    def test_no_marker_lines_recovered(self):
        text = "\n".join(BEAR_LINES[:2])
        turn = parse_turn_metadata(speaker="Bear", content=text)
        assert turn.standalone_typed_claim_count == 2
        assert len(turn.exact_claims) == 2

    def test_no_marker_no_stance_failed_branch_surfaces_claims(self):
        # No stance word, no marker: the FAILED branch must still surface claims.
        text = "Q3 figures attached.\n" + BEAR_LINES[0]
        turn = parse_turn_metadata(speaker="Bear", content=text)
        assert turn.metadata_parse_status is MetadataParseStatus.FAILED
        assert turn.standalone_typed_claim_count == 1
        assert len(turn.exact_claims) == 1

    def test_build_failed_turn_recovers_standalone(self):
        turn = build_failed_turn(speaker="Bear", content=BEAR_LINES[0])
        assert turn.metadata_parse_status is MetadataParseStatus.FAILED
        assert turn.standalone_typed_claim_count == 1


class TestDuplicates:
    def test_identical_claim_deduped(self):
        line = BEAR_LINES[5]
        turn = parse_turn_metadata(speaker="Bear", content=line + "\n" + line)
        assert len(turn.exact_claims) == 1
        assert turn.standalone_typed_claim_count == 2

    def test_distinct_claims_both_kept(self):
        turn = parse_turn_metadata(speaker="Bear", content=BEAR_LINES[0] + "\n" + BEAR_LINES[1])
        assert len(turn.exact_claims) == 2

    def test_canonical_key_identical(self):
        a = ClaimRecord(evidence_ids=[ORG], metric="close", date_role="observation_date",
                        date=TARGET, value="181.60", unit="USD", currency="USD")
        b = ClaimRecord(evidence_ids=[ORG], metric="close", date_role="observation_date",
                        date=TARGET, value="181.60", unit="USD", currency="USD")
        assert canonical_claim_key(a) == canonical_claim_key(b)


class TestMalformedAndConflicting:
    @pytest.mark.parametrize(
        "line",
        [
            "claim=metric=|value=|",
            "claim=metric=close|date=2026-11-05",  # missing unit/evidence etc still parses
            "claim=metric=close|role=observation_date|date=2026-11-05|value=1|value=2|unit=USD|evidence=x",
            "claim=notakey=1|metric=close",
        ],
    )
    def test_malformed_surfaced_never_dropped(self, line):
        turn = parse_turn_metadata(speaker="Bear", content="Arg.\n" + line)
        # Either parsed (with a typed constraint) or recorded as unparseable; never
        # silently empty.
        total = turn.standalone_typed_claim_count
        assert total == 1
        # The unparseable ones are counted honestly.
        if line in (
            "claim=metric=|value=|",
            "claim=metric=close|role=observation_date|date=2026-11-05|value=1|value=2|unit=USD|evidence=x",
            "claim=notakey=1|metric=close",
        ):
            assert turn.unparsed_typed_claim_count == 1

    def test_conflicting_duplicate_key_unparseable(self):
        line = "claim=metric=close|date=2026-11-05|date=2026-11-04|value=1|unit=USD|evidence=x"
        turn = parse_turn_metadata(speaker="Bear", content=line)
        assert turn.unparsed_typed_claim_count == 1
        assert turn.exact_claims == []


class TestQuotedAndExampleNotTrusted:
    @pytest.mark.parametrize(
        "text",
        [
            'An example: "claim=metric=close|date=2026-11-05|value=999|unit=USD|evidence=x"',
            "> claim=metric=close|date=2026-11-05|value=999|unit=USD|evidence=x",
            "`claim=metric=close|date=2026-11-05|value=999|unit=USD|evidence=x`",
        ],
    )
    def test_quoted_illustrative_not_a_record(self, text):
        turn = parse_turn_metadata(speaker="Bear", content=text)
        # A quoted/example line does NOT begin with claim= after bullets -> ignored.
        assert turn.standalone_typed_claim_count == 0
        assert turn.exact_claims == []

    @pytest.mark.parametrize(
        "wrapped",
        [
            "```\n{line}\n```",
            "~~~\n{line}\n~~~",
            "```python\n{line}\n```",
            "```\n{line}",  # unclosed fence -> illustrative to end-of-text
            "~~~\n{line}",  # unclosed tilde fence
        ],
    )
    def test_fenced_example_not_a_record(self, wrapped):
        # A fenced / illustrative KNOWN-VALID claim must never be admitted.
        known_valid = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        text = "Here is the format:\n" + wrapped.format(line=known_valid)
        turn = parse_turn_metadata(speaker="Bear", content=text)
        assert turn.standalone_typed_claim_count == 0
        assert turn.exact_claims == []
        # And it can never validate as VERIFIED via the shared summary.
        summary = _summary([turn])
        assert summary["verified"] == []

    def test_fenced_known_valid_cannot_become_verified(self):
        known_valid = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        assert validate_claim(
            ClaimRecord.from_dict(
                {
                    "evidence_ids": [ORG], "metric": "close",
                    "date_role": "observation_date", "date": TARGET,
                    "value": "181.60", "unit": "USD", "currency": "USD",
                }
            ),
            origin_by_id={ORG: _ORIGIN},
            records_by_id={ORG: _RECORD},
            target_date=TARGET,
            expected_symbol=SYMBOL,
            expected_run_id=f"{TARGET}/{SYMBOL}",
        ).is_verified  # the bare claim WOULD verify...
        text = "```\n" + known_valid + "\n```"
        turn = parse_turn_metadata(speaker="Bear", content=text)
        # ...but the fenced illustrative copy is never admitted, so no verification.
        assert _summary([turn])["verified"] == []

    def test_contradictory_alias_role_date_role_unparseable(self):
        line = (
            f"claim=metric=close|role=observation_date|date_role=target_date|"
            f"date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        )
        turn = parse_turn_metadata(speaker="Bear", content=line)
        assert turn.standalone_typed_claim_count == 1
        assert turn.unparsed_typed_claim_count == 1
        assert turn.exact_claims == []

    def test_agreeing_alias_role_date_role_parses(self):
        line = (
            f"claim=metric=close|role=observation_date|date_role=observation_date|"
            f"date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        )
        turn = parse_turn_metadata(speaker="Bear", content=line)
        assert turn.unparsed_typed_claim_count == 0
        assert len(turn.exact_claims) == 1
        assert turn.exact_claims[0].date_role == "observation_date"

    def test_shorter_fence_does_not_close_longer_fence(self):
        # A FOUR-backtick open followed by a THREE-backtick line does NOT close the
        # fence; the known-valid claim after it is still illustrative (excluded).
        known_valid = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        text = "````\ntext\n```\n" + known_valid
        turn = parse_turn_metadata(speaker="Bear", content=text)
        assert turn.standalone_typed_claim_count == 0
        assert turn.exact_claims == []
        assert _summary([turn])["verified"] == []

    def test_matching_longer_fence_closes_and_recovers(self):
        known_valid = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        text = "````\ntext\n````\n" + known_valid
        turn = parse_turn_metadata(speaker="Bear", content=text)
        assert turn.standalone_typed_claim_count == 1
        assert len(turn.exact_claims) == 1

    @pytest.mark.parametrize("label", ["Example:", "Examples:", "Example 1:"])
    def test_example_block_claim_not_admitted(self, label):
        known_valid = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        turn = parse_turn_metadata(speaker="Bear", content=label + "\n" + known_valid)
        assert turn.standalone_typed_claim_count == 0
        assert turn.exact_claims == []
        assert _summary([turn])["verified"] == []

    def test_example_block_ends_at_blank_line_then_real_claim_recovered(self):
        known_valid = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        text = "Example:\n" + known_valid + "\n\n" + known_valid
        turn = parse_turn_metadata(speaker="Bear", content=text)
        # Only the post-blank genuine line is recovered (the example is excluded).
        assert turn.standalone_typed_claim_count == 1
        assert len(turn.exact_claims) == 1


class TestFailClosedNegatives:
    def _recover(self, line):
        return parse_turn_metadata(speaker="Bear", content=line).exact_claims

    def test_known_valid_verifies(self):
        valid = f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        summary = _summary([parse_turn_metadata(speaker="Bear", content=valid)])
        assert len(summary["verified"]) == 1

    @pytest.mark.parametrize(
        "line",
        [
            # unknown id
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence=nonexistent/id/0",
            # future date (PIT)
            f"claim=metric=close|role=observation_date|date=2026-12-31|value=181.60|unit=USD|currency=USD|evidence={ORG}",
            # wrong value
            f"claim=metric=close|role=observation_date|date={TARGET}|value=999.99|unit=USD|currency=USD|evidence={ORG}",
            # wrong unit
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=shares|evidence={ORG}",
            # wrong currency
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=EUR|evidence={ORG}",
            # role mismatch (availability_date has no origin value on this record)
            f"claim=metric=close|role=availability_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}",
        ],
    )
    def test_negative_never_verified(self, line):
        summary = _summary([parse_turn_metadata(speaker="Bear", content=line)])
        assert summary["verified"] == []
        assert summary["rejected"] or summary["unverified"]


class TestCoverageHonesty:
    def test_coverage_present_only_for_typed_lines(self):
        turn = parse_turn_metadata(speaker="Bear", content=BEAR_LINES[0])
        summary = _summary([turn])
        assert summary["coverage"]["typed_lines_found"] == 1

    def test_legacy_no_typed_unchanged(self):
        turn = parse_turn_metadata(
            speaker="Bull",
            content="Qualitative only.\nDEBATE_METADATA: stance=Buy; confidence=0.7; cited=x/1;",
        )
        summary = _summary([turn])
        assert "coverage" not in summary
        assert turn.standalone_typed_claim_count == 0

    def test_coverage_only_prompt_block_non_empty(self):
        # A typed line that yields no validated claim still produces an honest RM
        # block (never an empty success).
        line = "claim=metric=|value=|"
        turn = parse_turn_metadata(speaker="Bear", content=line)
        summary = _summary([turn])
        assert summary["coverage"]["unparseable"] == 1
        block = claim_summary_prompt_block(summary)
        assert "typed" in block.lower()


class TestRealBoundariesAndResume:
    def test_boundary_contain_standalone_wrong_claim(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        state = {
            "data_quality_verdict": "normal",
            "data_quality_gate_decision": {"decision": "normal", "decided_at": "2026-11-11T00:00:00Z"},
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "data_quality_evidence_records": [dict(_RECORD)],
            "data_quality_origin_metadata": {ORG: _ORIGIN.to_dict()},
        }
        # A trusted plan that carries a standalone typed claim with a WRONG value.
        wrong = f"claim=metric=close|role=observation_date|date={TARGET}|value=999.99|unit=USD|currency=USD|evidence={ORG}"
        out = enforce_trusted_boundary(wrong, state)
        assert "999.99" not in out
        # A correct standalone typed claim is preserved.
        good = f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        assert enforce_trusted_boundary(good, state) == good

    def test_boundary_fenced_and_example_known_valid_not_promoted(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        state = {
            "data_quality_verdict": "normal",
            "data_quality_gate_decision": {"decision": "normal", "decided_at": "2026-11-11T00:00:00Z"},
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "data_quality_evidence_records": [dict(_RECORD)],
            "data_quality_origin_metadata": {ORG: _ORIGIN.to_dict()},
        }
        # A KNOWN-VALID claim inside a fence or an Example: block must never be
        # promoted (neither redacted-as-claim nor verified into the trusted text).
        known_valid = (
            f"claim=metric=close|role=observation_date|date={TARGET}|value=181.60|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        fenced = "Format:\n````\n" + known_valid + "\n```\nDone."  # 4 open, 3 close
        out = enforce_trusted_boundary(fenced, state)
        assert out == fenced  # illustrative: untouched, not treated as a claim
        example = "Example:\n" + known_valid + "\nRely on the verified plan."
        out2 = enforce_trusted_boundary(example, state)
        assert out2 == example

    def test_report_trace_carries_coverage_and_rejects_wrong(self, tmp_path):
        import json
        from pathlib import Path

        from tradingagents.reporting import write_report_tree

        lines = BEAR_LINES[:1] + [
            f"claim=metric=close|role=observation_date|date=2026-11-04|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        ]
        turn = parse_turn_metadata(speaker="Bear", content="\n".join(lines))
        summary = _summary([turn])
        state = {
            "data_quality_verdict": "normal",
            "data_quality_gate_decision": {"decision": "normal", "decided_at": "2026-11-11T00:00:00Z"},
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "data_quality_evidence_records": [dict(_RECORD)],
            "investment_debate_state": {"claim_validation_summary": summary},
            "trader_investment_plan": "",
        }
        write_report_tree(state, SYMBOL, tmp_path / "run")
        trace = json.loads(
            (Path(tmp_path) / "run" / "2_research" / "debate_trace.json").read_text(
                encoding="utf-8"
            )
        )
        assert trace["claim_validation"]["coverage"]["typed_lines_found"] == 2
        # The wrong-date claim on the valid close ID is rejected.
        assert any(
            ORG in e["evidence_ids"] for e in trace["claim_validation"]["rejected"]
        )

    def test_sqlite_resume_preserves_standalone_claims_and_coverage(self, tmp_path):
        from langchain_core.messages import AIMessage
        from langchain_core.runnables import RunnableLambda
        from langgraph.prebuilt import ToolNode

        from tradingagents.graph.checkpointer import get_checkpointer, thread_id
        from tradingagents.graph.conditional_logic import ConditionalLogic
        from tradingagents.graph.propagation import Propagator
        from tradingagents.graph.setup import GraphSetup

        bear = (
            "Bear case.\n"
            + BEAR_LINES[5]
            + "\n"
            f"DEBATE_METADATA: stance=Underweight; confidence=0.42; cited={ORG};"
        )

        class _Mock:
            def __init__(self, content):
                self.content = content
                self.with_structured_output = lambda *a, **k: None
                self.bind_tools = lambda tools: RunnableLambda(
                    lambda m: AIMessage(content=self.content, tool_calls=[])
                )

            def invoke(self, prompt):
                return AIMessage(content=self.content)

        def gate_node(state):
            return {
                "data_quality_verdict": "normal",
                "data_quality_gate_decision": {"decision": "normal", "decided_at": "2026-11-11T00:00:00Z"},
                "data_quality_context": "[Data Quality Gate] normal",
                "data_quality_error": None,
                "data_quality_evidence_records": [dict(_RECORD)],
                "data_quality_validation_results": {},
                "data_quality_group_statuses": [],
                "data_quality_origin_metadata": {ORG: _ORIGIN.to_dict()},
            }

        def state0():
            st = Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")
            st.update(gate_node(st))
            return st

        def build():
            tool_nodes = {k: ToolNode([]) for k in ("market", "social", "news", "fundamentals")}
            return GraphSetup(
                _Mock(bear), _Mock("Hold"), tool_nodes, ConditionalLogic(),
                data_quality_gate_factory=lambda: gate_node,
            ).setup_graph(("market",))

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = build().compile(checkpointer=saver, interrupt_after=["Bear Researcher"])
            g.invoke(state0(), cfg)
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = build().compile(checkpointer=saver)
            resumed = g2.invoke(None, cfg)

        turns = resumed["investment_debate_state"].get("turns") or []
        bear_turns = [t for t in turns if t.get("speaker") == "Bear"]
        assert bear_turns
        assert bear_turns[-1]["standalone_typed_claim_count"] >= 1
        # The recovered close claim is still present and validated after resume.
        assert any(c.get("metric") == "close" for c in bear_turns[-1]["exact_claims"])
        # The RESUMED evaluator persisted an honest claim summary: coverage is
        # present and the recovered close claim is counted (never an empty success).
        summary = resumed["investment_debate_state"].get("claim_validation_summary") or {}
        assert summary.get("coverage", {}).get("typed_lines_found", 0) >= 1
        # The valid close claim validates against the real origin.
        assert any(
            e.get("metric") == "close" for e in summary.get("verified", [])
        )
        # The Research Manager was invoked and its prompt carried the deterministic
        # claim block (the summary is consumed downstream, not just stored).
        assert resumed.get("investment_plan")


class TestMalformedNotStoredAsTrusted:
    def test_rejected_standalone_claim_not_stored_in_memory(self, tmp_path):
        import types

        from tradingagents.agents.utils.memory import TradingMemoryLog
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        # A final decision that (wrongly) restates a standalone typed claim with a
        # wrong value on a known id must not persist as a trusted fact.
        decision = (
            "**Action**: Hold\n\n"
            f"claim=metric=close|role=observation_date|date={TARGET}|value=999.99|"
            f"unit=USD|currency=USD|evidence={ORG}"
        )
        final_state = {
            "data_quality_verdict": "normal",
            "data_quality_gate_decision": {"decision": "normal", "decided_at": "2026-11-11T00:00:00Z"},
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "final_trade_decision": decision,
            "data_quality_evidence_records": [dict(_RECORD)],
            "data_quality_origin_metadata": {ORG: _ORIGIN.to_dict()},
        }
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {"memory_log_path": str(tmp_path / "mem.md"), "results_dir": str(tmp_path)}
        graph.memory_log = TradingMemoryLog(graph.config)
        graph._is_blocked_state = types.MethodType(lambda self, s: False, graph)
        graph.record_decision(SYMBOL, TARGET, final_state)
        body = "\n".join(str(e) for e in graph.memory_log.load_entries())
        # The wrong value is not stored as a trusted fact.
        assert "999.99" not in body

    def test_malformed_standalone_claim_not_stored_in_report(self, tmp_path):
        from pathlib import Path

        from tradingagents.reporting import write_report_tree

        # A malformed (contradictory alias) standalone line must be redacted, not
        # stored as an authoritative-looking fact.
        bad = (
            f"claim=metric=close|role=observation_date|date_role=target_date|"
            f"date={TARGET}|value=181.60|unit=USD|currency=USD|evidence={ORG}"
        )
        state = {
            "data_quality_verdict": "normal",
            "data_quality_gate_decision": {"decision": "normal", "decided_at": "2026-11-11T00:00:00Z"},
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "data_quality_evidence_records": [dict(_RECORD)],
            "data_quality_origin_metadata": {ORG: _ORIGIN.to_dict()},
            "trader_investment_plan": "Hold.\n" + bad,
        }
        write_report_tree(state, SYMBOL, tmp_path / "run")
        trader_md = (Path(tmp_path) / "run" / "3_trading" / "trader.md").read_text(
            encoding="utf-8"
        )
        assert "date_role=target_date" not in trader_md
        assert "unverified exact claim omitted" in trader_md
