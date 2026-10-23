"""Phase 3B offline tests for the ConflictRecord runtime tracker.

No network, no paid LLM, no clock dependency. Proves the deterministic
lifecycle of ``ConflictRecord`` objects derived **only** from the structured
``conflict_assertions`` a turn carries (parsed by ``turn.py`` from the
``DEBATE_METADATA`` ``conflict_a`` marker) and validated against the gate
manifest and the target trade date (fail closed):

- creation from a single ``assert``;
- stable deterministic conflict IDs (same topic/kind -> same ID);
- dedup / re-observation (merge evidence, raise severity, advance rounds);
- resolution and escalation with reason capture;
- invalid / unknown / future evidence never creates a conflict, and a
  re-observation with invalid / future evidence **drops** an open conflict;
- legacy checkpoints and manually-constructed records round-trip unchanged;
- malformed assertions / under-defined state are skipped, never guessed;
- action-only disagreement never blocks debate termination, but is tracked so
  the Research Manager can weigh it;
- evaluator routing with runtime-derived conflicts, and the Research Manager's
  safe conflict-summary injection (including preserve of resolution notes).
"""

from __future__ import annotations

import json

from tradingagents.agents.managers.research_manager import _conflict_summary_block
from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.conflicts import (
    build_conflict_summary,
    conflict_id_for,
    derive_conflicts,
)
from tradingagents.debate.evidence_manifest import EvidenceManifest
from tradingagents.debate.models import (
    ConflictAction,
    ConflictAssertion,
    ConflictKind,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    DebateTurn,
)
from tradingagents.debate.turn import parse_turn_metadata

# ---- Fixtures --------------------------------------------------------------

# A High/Medium, on-or-before-target evidence record for a valid conflict.
_RECORD_RUN1 = {
    "evidence_id": "run:1",
    "quality_status": "High",
    "observed_at": "2026-05-01",
    "value_raw": "190",
    "metric_name": "close",
    "unit_normalized": "USD",
}
_RECORD_RUN2 = {
    "evidence_id": "run:2",
    "quality_status": "Medium",
    "observed_at": "2026-05-01",
    "value_raw": "5",
    "metric_name": "volume",
}

TARGET = "2026-05-13"


def _manifest(*records: dict) -> EvidenceManifest:
    return EvidenceManifest.from_records(list(records))


def _assert_assert(
    *,
    topic: str = "valuation",
    bull: str = "bull claim",
    bear: str = "bear claim",
    kind: ConflictKind = ConflictKind.INTERPRETIVE,
    severity: ConflictSeverity = ConflictSeverity.CRITICAL,
    evidence: list[str] | None = None,
    conflict_id: str = "",
) -> ConflictAssertion:
    # Default to one valid evidence ID so a fresh assert creates a conflict;
    # pass evidence=[] explicitly to test the empty-evidence fail-closed case.
    evidence_list = ["run:1"] if evidence is None else evidence
    return ConflictAssertion(
        action=ConflictAction.ASSERT,
        conflict_id=conflict_id,
        topic=topic,
        bull_claim=bull,
        bear_claim=bear,
        kind=kind,
        severity=severity,
        evidence_ids=evidence_list,
    )


def _turn(
    speaker: str,
    *assertions: ConflictAssertion,
    linked_evidence: list[str] | None = None,
) -> DebateTurn:
    from tradingagents.debate.models import ClaimEvidenceLink

    links = [
        ClaimEvidenceLink(claim="claim", evidence_ids=linked_evidence)
    ] if linked_evidence else []
    return DebateTurn(
        speaker=speaker,
        content="argument",
        stance="Buy" if speaker == "Bull" else "Sell",
        confidence=0.7,
        cited_evidence_ids=list(linked_evidence or []),
        conflict_assertions=list(assertions),
        claim_evidence_links=links,
    )


# ---- Stable IDs and creation ----------------------------------------------


class TestConflictId:
    def test_stable_id_is_deterministic(self):
        a = conflict_id_for("Valuation is too high", ConflictKind.INTERPRETIVE)
        b = conflict_id_for("valuation is too high", ConflictKind.INTERPRETIVE)
        # Case / whitespace-folded topic maps to the same canonical ID.
        assert a == b
        assert a.startswith("conflict-")
        assert len(a) == len("conflict-") + 16

    def test_distinct_kind_differs(self):
        assert conflict_id_for("valuation", ConflictKind.INTERPRETIVE) != conflict_id_for(
            "valuation", ConflictKind.FACTUAL
        )

    def test_id_is_reproducible_across_calls(self):
        assert conflict_id_for("m", ConflictKind.INTERPRETIVE) == conflict_id_for(
            "m", ConflictKind.INTERPRETIVE
        )


class TestCreation:
    def test_single_assert_creates_open_blocking_conflict(self):
        conflicts, notes = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert())],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.status == ConflictStatus.OPEN
        assert c.kind == ConflictKind.INTERPRETIVE
        assert c.severity == ConflictSeverity.CRITICAL
        assert c.evidence_ids == ["run:1"]
        assert c.first_seen_round == 1
        assert c.last_seen_round == 1
        assert c.blocks_termination() is True
        assert notes == []

    def test_created_conflict_is_serialized_json_safe(self):
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert())],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert json.dumps([c.to_dict() for c in conflicts])

    def test_action_only_never_blocks_but_is_tracked(self):
        # BS/Bear both recommend different actions; tracked under ACTION kind so
        # the Research Manager can weigh it, but it must not block termination.
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[
                _turn("Bull", _assert_assert(kind=ConflictKind.ACTION, severity=ConflictSeverity.MAJOR)),
            ],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert len(conflicts) == 1
        assert conflicts[0].kind == ConflictKind.ACTION
        assert conflicts[0].blocks_termination() is False

    def test_missing_metadata_creates_nothing(self):
        # A turn with no conflict_assertions (missing metadata) creates no conflict.
        conflicts, notes = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull")],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert conflicts == []
        assert notes == []

    def test_explicit_assert_id_is_preserved(self):
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(conflict_id="custom-1"))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert conflicts[0].conflict_id == "custom-1"


# ---- Dedup / re-observation ------------------------------------------------


class TestDedup:
    def test_re_observation_merges_and_advances_round(self):
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert())],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        # Bear re-observes the same conflict in round 2 with extra evidence.
        conflicts2, _ = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", _assert_assert(evidence=["run:1", "run:2"]))],
            manifest=_manifest(_RECORD_RUN1, _RECORD_RUN2),
            target_date=TARGET,
            tracked=conflicts,
        )
        assert len(conflicts2) == 1
        c = conflicts2[0]
        assert c.conflict_id == conflicts[0].conflict_id
        assert c.evidence_ids == ["run:1", "run:2"]  # unioned
        assert c.last_seen_round == 2
        assert c.first_seen_round == 1
        assert "Bull" in c.participants
        assert "Bear" in c.participants

    def test_re_observation_raises_severity(self):
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(severity=ConflictSeverity.MINOR, evidence=["run:1"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        conflicts2, _ = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", _assert_assert(severity=ConflictSeverity.CRITICAL, evidence=["run:1"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
            tracked=conflicts,
        )
        assert conflicts2[0].severity == ConflictSeverity.CRITICAL

    def test_same_topic_and_kind_map_to_one_id(self):
        # Two separate assert turns on the same topic/kind dedup to one conflict.
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[
                _turn("Bull", _assert_assert(evidence=["run:1"])),
                _turn("Bear", _assert_assert(evidence=["run:1"])),
            ],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert len(conflicts) == 1


# ---- Resolution and escalation --------------------------------------------


class TestResolution:
    def test_resolve_closes_conflict_and_records_reason(self):
        created, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert())],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        cid = created[0].conflict_id
        resolved, notes = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", ConflictAssertion(action=ConflictAction.RESOLVE, conflict_id=cid, reason="evidence updated"))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
            tracked=created,
        )
        assert resolved[0].status == ConflictStatus.RESOLVED
        assert resolved[0].resolution_reason == "evidence updated"
        assert resolved[0].blocks_termination() is False
        assert notes == [f"{cid}: resolved (evidence updated)"]

    def test_escalate_promotes_to_manager_and_records_reason(self):
        created, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert())],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        cid = created[0].conflict_id
        escalated, notes = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", ConflictAssertion(action=ConflictAction.ESCALATE, conflict_id=cid, reason="needs manager"))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
            tracked=created,
        )
        assert escalated[0].status == ConflictStatus.ESCALATED_TO_MANAGER
        assert escalated[0].escalation_reason == "needs manager"
        assert escalated[0].blocks_termination() is False
        assert notes == [f"{cid}: escalated (needs manager)"]

    def test_resolving_unknown_conflict_is_noop(self):
        conflicts, notes = derive_conflicts(
            round_index=2,
            turns=[_turn("Bull", ConflictAssertion(action=ConflictAction.RESOLVE, conflict_id="nope", reason="x"))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert conflicts == []
        assert notes == []

    def test_resolving_already_resolved_is_noop(self):
        created, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert())],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        cid = created[0].conflict_id
        r1, _ = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", ConflictAssertion(action=ConflictAction.RESOLVE, conflict_id=cid, reason="first"))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
            tracked=created,
        )
        r2, notes = derive_conflicts(
            round_index=3,
            turns=[_turn("Bull", ConflictAssertion(action=ConflictAction.RESOLVE, conflict_id=cid, reason="again"))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
            tracked=r1,
        )
        # Already resolved -> no second reason recorded.
        assert notes == []
        assert r2[0].resolution_reason == "first"


# ---- Invalid / unknown / future evidence (fail closed) ---------------------


class TestInvalidEvidence:
    def test_unknown_evidence_never_creates_conflict(self):
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:999"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert conflicts == []

    def test_low_quality_evidence_never_creates_conflict(self):
        low = dict(_RECORD_RUN1, quality_status="Low")
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(low),
            target_date=TARGET,
        )
        assert conflicts == []

    def test_future_observed_evidence_never_creates_conflict(self):
        future = dict(_RECORD_RUN1, observed_at="2026-06-01")  # after TARGET
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(future),
            target_date=TARGET,
        )
        assert conflicts == []

    def test_empty_evidence_never_creates_factual_conflict(self):
        # Fail closed: a new factual/interpretive conflict with no cited valid
        # evidence cannot be created.
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=[]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert conflicts == []

    def test_re_observation_with_unknown_evidence_drops_open_conflict(self):
        created, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        dropped, _ = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", _assert_assert(evidence=["run:999"]))],
            manifest=_manifest(_RECORD_RUN1),  # run:999 unknown
            target_date=TARGET,
            tracked=created,
        )
        assert dropped == []

    def test_re_observation_with_future_evidence_drops_open_conflict(self):
        created, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        future = dict(_RECORD_RUN1, observed_at="2026-06-01")
        dropped, _ = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(future),
            target_date=TARGET,
            tracked=created,
        )
        assert dropped == []


# ---- Legacy compatibility and malformed state ------------------------------


class TestBackwardCompatibility:
    def test_legacy_record_without_new_fields_round_trips(self):
        # A record serialized before lifecycle fields existed defaults safely.
        legacy = {
            "conflict_id": "c1",
            "topic": "valuation",
            "bull_claim": "B",
            "bear_claim": "S",
            "evidence_ids": ["run:1"],
            "kind": "interpretive",
            "severity": "critical",
            "status": "open",
        }
        record = ConflictRecord.from_dict(legacy)
        assert record.conflict_id == "c1"
        assert record.participants == ["Bull", "Bear"]  # sensible default
        assert record.first_seen_round == 1
        assert record.last_seen_round == 1
        assert record.resolution_reason == ""
        assert record.status == ConflictStatus.OPEN

    def test_conflict_record_to_from_dict_round_trips(self):
        r = ConflictRecord(
            conflict_id="c2",
            topic="m",
            bull_claim="b",
            bear_claim="s",
            evidence_ids=["run:1"],
            kind=ConflictKind.FACTUAL,
            severity=ConflictSeverity.MAJOR,
            status=ConflictStatus.RESOLVED,
            participants=["Bull", "Bear"],
            first_seen_round=1,
            last_seen_round=3,
            resolution_reason="because",
        )
        assert ConflictRecord.from_dict(r.to_dict()).to_dict() == r.to_dict()


class TestMalformed:
    def test_malformed_tracked_entry_is_skipped(self):
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
            tracked=[{"no-conflict-id": 1}, "not-a-dict", None],
        )
        assert len(conflicts) == 1
        assert conflicts[0].conflict_id.startswith("conflict-")

    def test_malformed_assertion_is_skipped(self):
        # A malformed assertion (raw dict with no action) is dropped (fail closed).
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[DebateTurn(speaker="Bull", content="x", stance="Buy", confidence=0.7,
                              conflict_assertions=[{"no": "action"}])],  # type: ignore[arg-type]
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert conflicts == []

    def test_mismatched_target_date_fails_closed(self):
        # A target date before any observed evidence -> no conflict.
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date="2026-04-01",
        )
        assert conflicts == []


# ---- ConflictSummary and Research Manager safe injection -------------------


class TestConflictSummary:
    def test_summary_counts_only_open_blocking(self):
        open_critical = ConflictRecord(
            conflict_id="c1", topic="t", bull_claim="b", bear_claim="s",
            kind=ConflictKind.FACTUAL, severity=ConflictSeverity.CRITICAL,
            status=ConflictStatus.OPEN, evidence_ids=["run:1"],
        )
        resolved = ConflictRecord(
            conflict_id="c2", topic="t", bull_claim="b", bear_claim="s",
            kind=ConflictKind.INTERPRETIVE, severity=ConflictSeverity.CRITICAL,
            status=ConflictStatus.RESOLVED,
        )
        action_only = ConflictRecord(
            conflict_id="c3", topic="t", bull_claim="b", bear_claim="s",
            kind=ConflictKind.ACTION, severity=ConflictSeverity.MAJOR,
            status=ConflictStatus.OPEN,
        )
        summary = build_conflict_summary([open_critical, resolved, action_only])
        assert summary.open_blocking_count == 1
        assert len(summary.conflicts) == 3

    def test_summary_to_prompt_block_is_prose_free(self):
        summary = build_conflict_summary(
            [ConflictRecord(conflict_id="c1", topic="t", bull_claim="b", bear_claim="s")],
            ["c1: resolved (x)"],
        )
        block = summary.to_prompt_block()
        assert "[Tracked debate conflicts]" in block
        assert "c1" in block
        assert "resolved (x)" in block

    def test_empty_summary_block_is_empty(self):
        assert build_conflict_summary([]).to_prompt_block() == ""


class TestResearchManagerInjection:
    def test_manager_prefers_persisted_summary_with_notes(self):
        summary = build_conflict_summary(
            [ConflictRecord(conflict_id="c1", topic="t", bull_claim="b", bear_claim="s")],
            ["c1: resolved (updated)"],
        )
        block = _conflict_summary_block(
            {"conflicts": [summary.conflicts[0].to_dict()], "conflict_summary": summary.to_dict()}
        )
        assert "resolved (updated)" in block

    def test_manager_returns_empty_for_action_only_divergence(self):
        assert _conflict_summary_block({"conflicts": []}) == ""

    def test_manager_handles_legacy_and_malformed_safely(self):
        r = ConflictRecord(conflict_id="c1", topic="t", bull_claim="b", bear_claim="s")
        # Legacy state with no conflict_summary key still works (rebuilt from conflicts).
        assert "[Tracked debate conflicts]" in _conflict_summary_block({"conflicts": [r.to_dict()]})
        # Malformed conflicts are silently skipped.
        assert _conflict_summary_block({"conflicts": [{"bogus": 1}, None]}) == ""


# ---- Evaluator routing with runtime-derived conflicts ----------------------


class TestEvaluatorRouting:
    def _evaluate(self, *, turns_assertions, prior_conflicts=None, config=None, usage=None):
        from tradingagents.debate.evaluator import evaluate_round

        manifest = _manifest(_RECORD_RUN1)
        # Build two DebateTurn objects (Bull then Bear) for a completed round.
        bull_turn = _turn("Bull", *turns_assertions, linked_evidence=["run:1"])
        bear_turn = _turn("Bear")
        config = config or DebateTerminationConfig.from_dict(
            {"max_debate_rounds": 100, "max_calls": 1000, "max_tokens": 100000,
             "max_time": 600.0, "reserved_summary_tokens": 100,
             "next_round_estimate_tokens": 200}
        )
        usage = usage or {"calls": 2, "tokens": 100, "seconds": 2.0, "estimated": True}
        # Derive conflicts from the round's structured metadata, then route.
        tracked, notes = derive_conflicts(
            round_index=1, turns=[bull_turn, bear_turn], manifest=manifest,
            target_date=TARGET, tracked=prior_conflicts or [],
        )
        metrics, decision = evaluate_round(
            round_index=1,
            round_turns=[bull_turn, bear_turn],
            previously_cited=set(),
            manifest=manifest,
            target_date=TARGET,
            conflicts=tracked,
            bull_stance=bull_turn.stance,
            bear_stance=bear_turn.stance,
            bull_confidence=bull_turn.confidence,
            bear_confidence=bear_turn.confidence,
            config=config,
            usage=usage,
        )
        return metrics, decision, tracked, notes

    def test_open_conflict_with_new_evidence_routes_continue(self):
        metrics, decision, tracked, notes = self._evaluate(
            turns_assertions=[_assert_assert(evidence=["run:1"])],
        )
        # An open critical interpretive conflict + fresh evidence -> continue.
        assert decision.route.value == "continue"
        assert tracked[0].blocks_termination() is True

    def test_resolved_conflict_does_not_block(self):
        # First round creates and opens a critical conflict.
        created, notes = derive_conflicts(
            round_index=1,
            turns=[_turn("Bull", _assert_assert(evidence=["run:1"]))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        # Second round resolves it; the evaluator sees a non-blocking list.
        resolved, notes2 = derive_conflicts(
            round_index=2,
            turns=[_turn("Bear", ConflictAssertion(
                action=ConflictAction.RESOLVE, conflict_id=created[0].conflict_id, reason="ok"))],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
            tracked=created,
        )
        assert resolved[0].status == ConflictStatus.RESOLVED
        assert resolved[0].blocks_termination() is False
        metrics, decision, _, _ = self._evaluate(
            turns_assertions=[],
            prior_conflicts=resolved,
        )
        # No blocking conflict + (new evidence absent) -> the conflict never
        # holds the debate open on its own.
        assert metrics.unresolved_critical_or_major_conflict_count == 0

    def test_action_only_conflict_can_terminate(self):
        metrics, decision, tracked, notes = self._evaluate(
            turns_assertions=[_assert_assert(kind=ConflictKind.ACTION, severity=ConflictSeverity.MAJOR, evidence=["run:1"])],
        )
        # Action-only never blocks -> the debate is NOT held open by a conflict.
        assert all(not c.blocks_termination() for c in tracked)
        assert metrics.unresolved_critical_or_major_conflict_count == 0


# ---- End-to-end: turn metadata -> tracker ----------------------------------


class TestMetadataToTracker:
    def test_conflict_a_marker_drives_tracker(self):
        # A Bull turn whose marker carries a conflict_a assert is parsed by
        # parse_turn_metadata into a DebateTurn, which derive_conflicts consumes.
        content = (
            "Bull case.\n"
            "DEBATE_METADATA: stance=Buy; confidence=0.7; cited=run:1; "
            "new_claims=growth|run:1; "
            "conflict_a=action=assert|kind=interpretive|severity=critical|"
            "topic=valuation|bull=higher multiple|bear=overpaid|evidence=run:1"
        )
        bull_turn = parse_turn_metadata(speaker="Bull", content=content)
        assert bull_turn.conflict_assertions
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[bull_turn],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.topic == "valuation"
        assert c.bull_claim == "higher multiple"
        assert c.bear_claim == "overpaid"
        assert c.kind == ConflictKind.INTERPRETIVE
        assert c.severity == ConflictSeverity.CRITICAL
        assert c.evidence_ids == ["run:1"]
        assert c.blocks_termination() is True

    def test_tracker_ignores_prose_only_disagreement(self):
        # A prose-only mention of a disagreement (no conflict_a marker) produces
        # no conflict from the tracker (fail closed).
        turn = parse_turn_metadata(
            speaker="Bull", content="The valuation is genuinely contested."
        )
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[turn],
            manifest=_manifest(_RECORD_RUN1),
            target_date=TARGET,
        )
        assert conflicts == []


# ---- Evaluator node runtime derivation + persistence -----------------------


class TestEvaluatorNodePersistence:
    def test_runtime_node_persists_conflicts_and_summary(self):
        from tradingagents.debate.evaluator_node import create_debate_evaluator_node

        cfg = DebateTerminationConfig.from_dict(
            {"max_debate_rounds": 100, "max_calls": 1000, "max_tokens": 100000,
             "max_time": 600.0, "reserved_summary_tokens": 100,
             "next_round_estimate_tokens": 200}
        )
        node = create_debate_evaluator_node(config=cfg)
        bull_content = (
            "Bull case.\nDEBATE_METADATA: stance=Buy; confidence=0.7; cited=run:1; "
            "new_claims=growth|run:1; "
            "conflict_a=action=assert|kind=interpretive|severity=critical|"
            "topic=valuation|bull=b|bear=s|evidence=run:1"
        )
        bear_content = (
            "Bear case.\nDEBATE_METADATA: stance=Sell; confidence=0.7; "
            "cited=run:1; new_claims=decline|run:1;"
        )
        turns = [
            parse_turn_metadata(speaker="Bull", content=bull_content).to_dict(),
            parse_turn_metadata(speaker="Bear", content=bear_content).to_dict(),
        ]
        out = node({
            "investment_debate_state": {"turns": turns},
            "trade_date": TARGET,
            "data_quality_verdict": "normal",
            "data_quality_group_statuses": [],
            "data_quality_evidence_records": [_RECORD_RUN1],
        })
        debate = out["investment_debate_state"]
        conflicts = debate.get("conflicts") or []
        assert len(conflicts) == 1
        assert conflicts[0]["severity"] == "critical"
        assert conflicts[0]["status"] == "open"
        # The safe summary is persisted with the derived blocking count.
        summary = debate.get("conflict_summary") or {}
        assert summary.get("open_blocking_count") == 1
        assert "conflicts" in summary
        assert "resolution_notes" in summary
        # The derived open conflict drives a continue route.
        assert out["debate_termination_decision"]["route"] == "continue"

    def test_runtime_node_persists_empty_summary_when_no_conflicts(self):
        from tradingagents.debate.evaluator_node import create_debate_evaluator_node

        cfg = DebateTerminationConfig.from_dict(
            {"max_debate_rounds": 100, "max_calls": 1000, "max_tokens": 100000,
             "max_time": 600.0, "reserved_summary_tokens": 100,
             "next_round_estimate_tokens": 200}
        )
        node = create_debate_evaluator_node(config=cfg)
        turns = [
            parse_turn_metadata(speaker="Bull", content="Bull.\nDEBATE_METADATA: stance=Buy; confidence=0.7; cited=run:1; new_claims=growth|run:1;").to_dict(),
            parse_turn_metadata(speaker="Bear", content="Bear.\nDEBATE_METADATA: stance=Sell; confidence=0.7; cited=run:1;").to_dict(),
        ]
        out = node({
            "investment_debate_state": {"turns": turns},
            "trade_date": TARGET,
            "data_quality_verdict": "normal",
            "data_quality_group_statuses": [],
            "data_quality_evidence_records": [_RECORD_RUN1],
        })
        debate = out["investment_debate_state"]
        # No tracked conflict -> safe empty summary, nothing fabricated.
        assert debate.get("conflicts") == []
        assert debate.get("conflict_summary", {}).get("open_blocking_count") == 0
