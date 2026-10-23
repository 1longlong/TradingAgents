"""Phase 3B offline tests for deterministic single-call turn metadata parsing."""

from __future__ import annotations

import pytest

from tradingagents.debate.models import (
    ConflictAction,
    ConflictAssertion,
    DebateTurn,
    MetadataParseStatus,
    Stance,
)
from tradingagents.debate.turn import (
    build_failed_turn,
    extract_marker,
    parse_turn_metadata,
)


class TestMarkerExtraction:
    def test_marker_found(self):
        content = "My argument.\nDEBATE_METADATA: stance=Buy; confidence=0.7;"
        assert extract_marker(content).startswith("DEBATE_METADATA:")

    def test_marker_absent(self):
        assert extract_marker("just an argument") == ""

    def test_empty_content(self):
        assert extract_marker("") == ""


class TestOKParse:
    def test_full_marker_parses_ok(self):
        content = (
            "Bull case here.\n"
            "DEBATE_METADATA: stance=Buy; confidence=0.7; "
            "cited=ev/1,ev/2; conflicts=c1; "
            "new_claims=growing revenue|ev/1; questions=is the margin durable?"
        )
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assert turn.speaker == "Bull"
        assert turn.stance == Stance.BUY
        assert turn.confidence == pytest.approx(0.7)
        assert turn.cited_evidence_ids == ["ev/1", "ev/2"]
        assert turn.addressed_conflict_ids == ["c1"]
        assert turn.new_claims == ["growing revenue"]
        assert turn.claim_evidence_links[0].evidence_ids == ["ev/1"]
        assert turn.unresolved_questions == ["is the margin durable?"]
        assert turn.metadata_parse_status == MetadataParseStatus.OK
        # The readable content is preserved exactly.
        assert turn.content == content

    def test_claim_without_evidence_link_has_empty_ids(self):
        content = (
            "argument\n"
            "DEBATE_METADATA: stance=Hold; confidence=0.5; "
            "new_claims=just an opinion;"
        )
        turn = parse_turn_metadata(speaker="Bear", content=content)
        assert turn.new_claims == ["just an opinion"]
        assert turn.claim_evidence_links[0].evidence_ids == []

    def test_multiple_claims(self):
        content = (
            "argument\n"
            "DEBATE_METADATA: stance=Sell; confidence=0.6; "
            "new_claims=claim1|ev/a; claim2|ev/b,ev/c;"
        )
        turn = parse_turn_metadata(speaker="Bear", content=content)
        assert len(turn.claim_evidence_links) == 2
        assert turn.claim_evidence_links[0].evidence_ids == ["ev/a"]
        assert turn.claim_evidence_links[1].evidence_ids == ["ev/b", "ev/c"]


class TestPartialParse:
    def test_missing_confidence_marks_partial(self):
        content = (
            "argument\n"
            "DEBATE_METADATA: stance=Buy; cited=ev/1;"
        )
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assert turn.stance == Stance.BUY
        assert turn.metadata_parse_status == MetadataParseStatus.PARTIAL

    def test_no_marker_falls_back_to_prose(self):
        content = "I am bullish. Buy it today."
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assert turn.stance == Stance.BUY
        assert turn.metadata_parse_status == MetadataParseStatus.PARTIAL
        # Prose fallback never fabricates a claim -> zero new evidence paths.
        assert turn.new_claims == []

    def test_prose_fallback_recovers_cited_ids(self):
        content = "I lean Buy. Consider evid/abc and run/xyz/metric/0 here."
        turn = parse_turn_metadata(speaker="Bull", content=content)
        # A stance word recovers the stance -> partial; cited IDs recovered too.
        assert turn.metadata_parse_status == MetadataParseStatus.PARTIAL
        assert "run/xyz/metric/0" in turn.cited_evidence_ids


class TestFailedParse:
    def test_no_recoverable_stance_is_failed(self):
        content = "There is no direction here, just commentary."
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assert turn.metadata_parse_status == MetadataParseStatus.FAILED
        assert turn.stance == Stance.HOLD
        assert turn.new_claims == []
        assert turn.claim_evidence_links == []

    def test_build_failed_turn_preserves_text(self):
        turn = build_failed_turn(speaker="Bear", content="quiet text")
        assert turn.metadata_parse_status == MetadataParseStatus.FAILED
        assert turn.content == "quiet text"
        assert turn.stance == Stance.HOLD

    def test_failed_turn_serializes_json_safe(self):
        import json

        turn = build_failed_turn(speaker="Bull", content="x")
        assert json.dumps(turn.to_dict())


class TestSerialization:
    def test_turn_round_trip(self):
        content = "x\nDEBATE_METADATA: stance=Buy; confidence=0.8; cited=ev/1;"
        t = parse_turn_metadata(speaker="Bull", content=content)
        assert DebateTurn.from_dict(t.to_dict()).to_dict() == t.to_dict()

    def test_enum_and_list_serialize_plain(self):
        import json

        t = parse_turn_metadata(
            speaker="Bear", content="x\nDEBATE_METADATA: stance=Hold; confidence=0.9;"
        )
        assert json.dumps(t.to_dict())
        assert t.to_dict()["stance"] == "Hold"
        assert t.to_dict()["metadata_parse_status"] == "ok"

    def test_debate_turn_coerces_enums(self):
        for raw in (Stance.BUY, "Buy", "buy"):
            t = DebateTurn(
                speaker="Bull",
                content="c",
                stance=raw,  # type: ignore[arg-type]
                confidence=0.5,
            )
            assert t.stance == Stance.BUY

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            DebateTurn(speaker="Bull", content="c", stance="Buy", confidence=1.5)
        with pytest.raises(ValueError):
            DebateTurn(speaker="Bull", content="c", stance="Buy", confidence=-0.1)


class TestConflictAssertionParsing:
    """Parse ``conflict_a`` (the structured conflict marker) only, never prose."""

    def test_assertion_parses_structured_fields(self):
        content = (
            "Bull case.\n"
            "DEBATE_METADATA: stance=Buy; confidence=0.7; cited=run:1; "
            "conflict_a=action=assert|kind=interpretive|severity=critical|"
            "topic=valuation|bull=the bull|bear=the bear|evidence=run:1"
        )
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assert len(turn.conflict_assertions) == 1
        a = turn.conflict_assertions[0]
        assert a.action == ConflictAction.ASSERT
        assert a.kind.value == "interpretive"
        assert a.severity.value == "critical"
        assert a.topic == "valuation"
        assert a.bull_claim == "the bull"
        assert a.bear_claim == "the bear"
        assert a.evidence_ids == ["run:1"]

    def test_multiple_assertions_are_split(self):
        content = (
            "x\nDEBATE_METADATA: stance=Hold; confidence=0.5; "
            "conflict_a=action=assert|topic=t1; action=resolve|id=c1|reason=done"
        )
        turn = parse_turn_metadata(speaker="Bear", content=content)
        assert len(turn.conflict_assertions) == 2
        assert turn.conflict_assertions[0].action == ConflictAction.ASSERT
        assert turn.conflict_assertions[1].action == ConflictAction.RESOLVE
        assert turn.conflict_assertions[1].conflict_id == "c1"
        assert turn.conflict_assertions[1].reason == "done"

    def test_action_request_resolve_defaults(self):
        # A resolve/escalate assertion omits default severity/kind, which stay
        # at their documented defaults (never a fabricated critical).
        content = (
            "x\nDEBATE_METADATA: stance=Buy; confidence=0.8; "
            "conflict_a=action=escalate|id=c1|reason=manager needed"
        )
        turn = parse_turn_metadata(speaker="Bull", content=content)
        a = turn.conflict_assertions[0]
        assert a.action == ConflictAction.ESCALATE
        assert a.kind.value == "interpretive"
        assert a.severity.value == "major"

    def test_malformed_action_less_chunk_is_dropped(self):
        # A chunk with no ``action`` key is dropped (fail closed) — the tracker
        # records nothing for it rather than guessing an action.
        content = (
            "x\nDEBATE_METADATA: stance=Hold; confidence=0.5; "
            "conflict_a=kind=interpretive|topic=t; action=assert|topic=t2"
        )
        turn = parse_turn_metadata(speaker="Bear", content=content)
        assert len(turn.conflict_assertions) == 1
        assert turn.conflict_assertions[0].action == ConflictAction.ASSERT
        assert turn.conflict_assertions[0].topic == "t2"

    def test_unknown_action_is_dropped(self):
        content = (
            "x\nDEBATE_METADATA: stance=Hold; confidence=0.5; "
            "conflict_a=action=frobnicate|topic=t"
        )
        turn = parse_turn_metadata(speaker="Bear", content=content)
        assert turn.conflict_assertions == []

    def test_empty_field_yields_no_assertion(self):
        content = "x\nDEBATE_METADATA: stance=Buy; confidence=0.6; conflict_a="
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assert turn.conflict_assertions == []

    def test_prose_never_yields_assertion(self):
        # A turn with no marker / no conflict_a field records no conflict even if
        # prose mentions a disagreement (missing metadata -> no conflict).
        turn = parse_turn_metadata(
            speaker="Bull", content="There is a disagreement about valuation."
        )
        assert turn.conflict_assertions == []

    def test_assertion_serializes_json_safe(self):
        import json

        content = (
            "x\nDEBATE_METADATA: stance=Buy; confidence=0.7; "
            "conflict_a=action=assert|topic=t|evidence=run:1"
        )
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assert json.dumps(turn.conflict_assertions[0].to_dict())

    def test_conflict_assertion_round_trips(self):
        content = (
            "x\nDEBATE_METADATA: stance=Buy; confidence=0.7; "
            "conflict_a=action=assert|topic=t|bull=b|bear=s|evidence=run:1"
        )
        turn = parse_turn_metadata(speaker="Bull", content=content)
        assertion = turn.conflict_assertions[0]
        assert ConflictAssertion.from_dict(assertion.to_dict()).to_dict() == assertion.to_dict()
