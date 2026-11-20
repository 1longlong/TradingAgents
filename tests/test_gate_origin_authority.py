"""Defect-1 (ADR-010 amendment): the gate's authoritative origin map survives
optional-evidence ingestion persistence, and genuine captured-origin conflicts are
failed closed (never first/last-wins, never a derived re-trust, never resurrected).

Root cause pinned here: ``data_quality_gate.py`` built the correct origin map for
the market records, then ``output.update(persisted)`` overwrote it with the live
collector's (empty-for-market) origin delta. The fix merges the authoritative map
AFTER persistence.

Covered offline with the REAL gate node (fixed market snapshot, no network), the
REAL run-scoped collector, and the REAL SQLite checkpointer/resume path:

- active collector with an EMPTY origin map no longer erases the five market
  origins (the exact live defect);
- genuine captured SEC/news origins are preserved (no invented date/currency);
- a REAL collector duplicate-origin insertion (two different origins for the same
  id) is retained and failed closed end-to-end through state;
- a real SQLite close/rebuild/resume keeps the ambiguity (no re-trust) and never
  resurrects pruned ids;
- legacy/no-collector derivation still yields honest origins.

All tests are socket-disabled offline (fixed snapshot); real-shaped data only.

Traceability: FR-DQG-004, NFR-PIT-001, NFR-AUD-001, INV-3, INV-4.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.debate.evaluator_node import _duplicate_origin_ids_from_state
from tradingagents.evidence import EvidenceRecord
from tradingagents.evidence.ingest import (
    INGEST_ORIGIN_CONFLICTED_STATE_KEY,
    get_active_collector,
    merge_into_state,
    use_collector,
)
from tradingagents.evidence.origin import (
    ORIGIN_STATE_KEY,
    OriginMetadata,
    origin_records_from_state,
)
from tradingagents.graph.checkpointer import get_checkpointer, thread_id
from tradingagents.graph.data_quality_gate import (
    GATE_EVIDENCE_RECORDS_KEY,
    create_data_quality_gate_node,
)

SYMBOL = "AAPL"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"


def _fixed_df() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )


@pytest.fixture
def fixed_snapshot(monkeypatch):
    monkeypatch.setattr(validator, "load_ohlcv", lambda s, d, fill_gaps=True: _fixed_df())


def _gate_node(snapshot_builder=None):
    if snapshot_builder is None:
        return create_data_quality_gate_node(now_provider=lambda: FETCHED)
    return create_data_quality_gate_node(
        snapshot_builder=snapshot_builder, now_provider=lambda: FETCHED
    )


def _state(**overrides):
    base = {
        "company_of_interest": SYMBOL,
        "trade_date": TARGET,
        "asset_type": "stock",
    }
    base.update(overrides)
    return base


def _market_records(snapshot_builder=None) -> list[EvidenceRecord]:
    """The real market records the gate derives from the fixed snapshot."""
    out = _gate_node(snapshot_builder)(
        _state(snapshot_builder=snapshot_builder) if False else _state()
    )
    return [EvidenceRecord.from_dict(r) for r in out[GATE_EVIDENCE_RECORDS_KEY]]


# ---------------------------------------------------------------------------
# The exact live defect: an active (empty) collector must not erase origins.
# ---------------------------------------------------------------------------


class TestOriginSurvivesActiveCollector:
    def test_market_origins_survive_active_empty_collector(self, fixed_snapshot):
        # No collector: 5 records -> 5 origins (baseline).
        out_no = _gate_node()(_state())
        assert len(out_no[GATE_EVIDENCE_RECORDS_KEY]) == 5
        assert len(out_no[ORIGIN_STATE_KEY]) == 5

        # ACTIVE collector whose origin map is EMPTY (market records are not
        # captured by it) — the live defect shape. The fix keeps all 5 origins.
        with use_collector(SYMBOL, TARGET):
            assert get_active_collector().origins_map() == {}
            out_active = _gate_node()(_state())
        assert len(out_active[GATE_EVIDENCE_RECORDS_KEY]) == 5
        assert len(out_active[ORIGIN_STATE_KEY]) == 5, (
            "the collector's empty origin delta must not overwrite the gate origins"
        )
        # Every manifest id has a typed origin; no fabricated currency.
        ids = {r["evidence_id"] for r in out_active[GATE_EVIDENCE_RECORDS_KEY]}
        assert ids == set(out_active[ORIGIN_STATE_KEY])
        for origin in out_active[ORIGIN_STATE_KEY].values():
            assert origin["schema_version"] == "1.0"

    def test_active_collector_seeded_from_real_checkpoint_shape(self, fixed_snapshot):
        # Seed the collector from a realistic persisted state that already carries
        # the 5 market origins; re-running the gate must keep them (resume shape).
        first = _gate_node()(_state())
        persisted = {ORIGIN_STATE_KEY: dict(first[ORIGIN_STATE_KEY])}
        with use_collector(SYMBOL, TARGET, prior_state=persisted):
            out = _gate_node()(_state(**persisted))
        assert len(out[ORIGIN_STATE_KEY]) == 5


# ---------------------------------------------------------------------------
# Genuine captured origin preserved; conflict retained and failed closed.
# ---------------------------------------------------------------------------


class TestCapturedOriginAndConflict:
    def test_genuine_captured_market_origin_preserved_not_derived(self, fixed_snapshot):
        # Capture a GENUINE origin for one market id (e.g. a real currency + filed
        # role) through the real collector, then run the real gate. The genuine
        # captured origin must win over the derived one (no invented currency).
        baseline = _gate_node()(_state())
        target_id = sorted(baseline[ORIGIN_STATE_KEY])[0]
        genuine = OriginMetadata(
            target_date=TARGET,
            observation_date="2026-05-12",
            availability_date="2026-05-13",
            filed_at="2026-05-13T09:30:00Z",
            date_basis="filed",
            unit="USD",
            currency="USD",
            period_end_source="vendor",
        )
        with use_collector(SYMBOL, TARGET) as col:
            col.capture_origin(target_id, genuine)
            out = _gate_node()(_state())
        kept = out[ORIGIN_STATE_KEY][target_id]
        assert kept["filed_at"] == "2026-05-13T09:30:00Z"
        assert kept["currency"] == "USD"
        assert kept["availability_date"] == "2026-05-13"

    def test_real_collector_duplicate_origin_conflict_retained_and_failed_closed(
        self, fixed_snapshot
    ):
        # DIRECT real-collector duplicate insertion (NOT a hand-built conflict map):
        # two DIFFERENT origins for the same id. The collector RETAINS the conflict;
        # the gate fails the id closed from the trusted origin map.
        baseline = _gate_node()(_state())
        target_id = sorted(baseline[ORIGIN_STATE_KEY])[0]
        origin_a = OriginMetadata(target_date=TARGET, observation_date="2026-05-12",
                                  date_basis="period_end", unit="USD", currency="USD")
        origin_b = OriginMetadata(target_date=TARGET, observation_date="2026-05-11",
                                  date_basis="period_end", unit="USD", currency="USD")
        with use_collector(SYMBOL, TARGET) as col:
            col.capture_origin(target_id, origin_a)
            col.capture_origin(target_id, origin_b)  # different -> real conflict
            assert target_id in col.conflicted_origin_ids()
            out = _gate_node()(_state())
        # Failed closed: removed from the trusted map, recorded as conflicted.
        assert target_id not in out[ORIGIN_STATE_KEY]
        assert target_id in out[INGEST_ORIGIN_CONFLICTED_STATE_KEY]
        # The other four market origins are still present (not globally lost).
        assert len(out[ORIGIN_STATE_KEY]) == 4
        # Not re-derived: no fabricated replacement origin for the ambiguous id.
        assert target_id not in out[ORIGIN_STATE_KEY]

    def test_state_vs_collector_conflict_retained(self, fixed_snapshot):
        # Persisted state carries origin A for an id; the live (resumed) collector
        # inserts a DIFFERENT origin B. This real resume-shape conflict is retained
        # and failed closed, never last-wins.
        baseline = _gate_node()(_state())
        target_id = sorted(baseline[ORIGIN_STATE_KEY])[0]
        state_origin = {
            **baseline[ORIGIN_STATE_KEY][target_id],
            "observation_date": "2026-05-10",
        }
        collector_origin = OriginMetadata(
            target_date=TARGET, observation_date="2026-05-12",
            date_basis="period_end", unit="USD",
        )
        persisted_state = _state(**{ORIGIN_STATE_KEY: {target_id: state_origin}})
        with use_collector(SYMBOL, TARGET, prior_state=persisted_state) as col:
            col.capture_origin(target_id, collector_origin)
            out = _gate_node()(persisted_state)
        assert target_id not in out[ORIGIN_STATE_KEY]
        assert target_id in out[INGEST_ORIGIN_CONFLICTED_STATE_KEY]

    def test_conflicted_id_is_consumed_by_claim_validator(self, fixed_snapshot):
        # The declared channel is consumed by the claim validator's duplicate set
        # (so an exact claim on that id is unverifiable, not silently verified).
        state = {INGEST_ORIGIN_CONFLICTED_STATE_KEY: ["id:x"], ORIGIN_STATE_KEY: {"id:x": {}}}
        assert "id:x" in _duplicate_origin_ids_from_state(state)

    def test_no_collector_conflicted_state_not_retrusted_or_rederived(self, fixed_snapshot):
        # Defect-1 fix: with NO active collector, an id already flagged conflicted in
        # persisted state must stay untrusted — the gate must neither keep a stale
        # trusted origin nor re-derive a replacement for it.
        baseline = _gate_node()(_state())
        target_id = sorted(baseline[ORIGIN_STATE_KEY])[0]
        stale_map = {target_id: dict(baseline[ORIGIN_STATE_KEY][target_id])}
        state = _state(**{
            ORIGIN_STATE_KEY: stale_map,
            INGEST_ORIGIN_CONFLICTED_STATE_KEY: [target_id],
        })
        # No collector active.
        assert get_active_collector() is None
        out = _gate_node()(state)
        assert target_id not in out[ORIGIN_STATE_KEY], (
            "a persisted conflict must not be re-trusted/re-derived with no collector"
        )
        assert target_id in out[INGEST_ORIGIN_CONFLICTED_STATE_KEY]

    def test_imported_state_stale_map_but_conflict_excludes_in_validator(self):
        # Imported report/state shape: a stale ORIGIN_STATE_KEY still carries an
        # origin for an id, and the conflict channel lists it. EVERY consumer must
        # treat it as unverifiable: origin_records_from_state drops it, and the
        # claim validator's duplicate set names it (fresh output boundary path).

        stale = {
            ORIGIN_STATE_KEY: {"id:x": OriginMetadata(target_date=TARGET, unit="USD").to_dict()},
            INGEST_ORIGIN_CONFLICTED_STATE_KEY: ["id:x"],
        }
        assert "id:x" not in origin_records_from_state(stale)
        assert "id:x" in _duplicate_origin_ids_from_state(stale)


# ---------------------------------------------------------------------------
# Pruning / tombstone: excluded ids never re-appear in origins or conflict set.
# ---------------------------------------------------------------------------


class TestPruningAndTombstone:
    def test_pruned_ids_not_in_origin_or_conflict(self, fixed_snapshot):
        # Capture a conflicting origin for an id that a real prune excludes: it
        # must not appear in the trusted map OR the conflicted set (no revival).
        origin_a = OriginMetadata(target_date=TARGET, observation_date="2026-05-12", unit="USD")
        origin_b = OriginMetadata(target_date=TARGET, observation_date="2026-05-11", unit="USD")
        pruned_id = "pruned/id/market/x"
        with use_collector(SYMBOL, TARGET) as col:
            col.capture_origin(pruned_id, origin_a)
            col.capture_origin(pruned_id, origin_b)
            # Simulate the gate pruning this id from decisive evidence.
            col.drop_record(pruned_id)
            delta = col.state_delta(pruned_record_ids=[pruned_id])
        merged = merge_into_state(delta, _state())
        assert pruned_id not in merged[ORIGIN_STATE_KEY]
        assert pruned_id not in merged[INGEST_ORIGIN_CONFLICTED_STATE_KEY]

    def test_no_collector_gate_never_retrusts_existing_dropped_id(self, fixed_snapshot):
        # The scoped edge: a prior gate output map + a state tombstone for one id,
        # run WITHOUT an active collector. Neither the gate output map nor the
        # direct consumer may re-trust the tombstoned id (persisted is None here,
        # so the fix must honour EXISTING state tombstones).
        base = _gate_node()(_state())
        dropped_id = sorted(base[ORIGIN_STATE_KEY])[0]
        state = _state(**{
            "data_quality_dropped_evidence_ids": [dropped_id],
            ORIGIN_STATE_KEY: dict(base[ORIGIN_STATE_KEY]),
        })
        assert get_active_collector() is None
        out = _gate_node()(state)
        assert dropped_id not in out[ORIGIN_STATE_KEY], "no-collector gate re-trusted a drop"
        # The other four are still present (scoped, not global).
        assert len(out[ORIGIN_STATE_KEY]) == 4
        # The direct consumer (origin_records_from_state) excludes it too.
        assert dropped_id not in origin_records_from_state(state)

    def test_direct_consumer_excludes_dropped_id_from_stale_map(self):
        # Imported/legacy shape: a stale ORIGIN_STATE_KEY still carries an origin
        # for an id that is explicitly tombstoned. The read choke point must drop
        # it (no stale-origin resurrection), independent of the gate.
        stale = {
            ORIGIN_STATE_KEY: {
                "id:kept": OriginMetadata(target_date=TARGET, unit="USD").to_dict(),
                "id:dropped": OriginMetadata(target_date=TARGET, unit="USD").to_dict(),
            },
            "data_quality_dropped_evidence_ids": ["id:dropped"],
        }
        trusted = origin_records_from_state(stale)
        assert "id:dropped" not in trusted
        assert "id:kept" in trusted


# ---------------------------------------------------------------------------
# Legacy / no-collector honest derivation and 20-field invariant.
# ---------------------------------------------------------------------------


class TestLegacyAndInvariants:
    def test_no_collector_derives_honest_origins(self, fixed_snapshot):
        out = _gate_node()(_state())
        assert len(out[ORIGIN_STATE_KEY]) == 5
        # Every origin is typed and parses back; no speculative currency is added
        # to a non-currency unit like shares.
        for payload in out[ORIGIN_STATE_KEY].values():
            OriginMetadata.from_dict(payload)
            assert payload["target_date"] == TARGET

    def test_evidence_record_still_exactly_20_fields(self):
        # INV-4: the frozen EvidenceRecord shape is unchanged by this defect fix.
        assert len(EvidenceRecord.__dataclass_fields__) == 20

    def test_origin_state_channel_declared_on_agent_state(self):
        # The ambiguity/conflict channel MUST be declared or LangGraph silently
        # drops the write on checkpoint.
        annotations = AgentState.__annotations__
        assert "data_quality_origin_metadata" in annotations
        assert "data_quality_origin_conflicted_ids" in annotations


# ---------------------------------------------------------------------------
# Real SQLite checkpoint close/rebuild/resume keeps origins + ambiguity.
# ---------------------------------------------------------------------------


def _epoch(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


class TestSqliteResumeKeepsOrigins:
    """Real INTERRUPTED resume (a PENDING production node executes after restart).

    These are NOT storage-reload-only tests: the first pass runs under
    ``interrupt_before`` so a downstream node is genuinely pending, the saver is
    closed and the graph rebuilt with the collector re-seeded from the REAL saved
    state, and ``invoke(None)`` EXECUTES that pending node (the real gate and/or a
    claim-consuming node). Origins/ambiguity/tombstones are pinned AFTER actual
    resumed work.
    """

    def _graph(self):
        # Real production AgentState schema so declared channels really persist. A
        # Gate node, then a Consumer node that consumes origins EXACTLY like the
        # claim validator / output boundary (origin_records_from_state + the
        # conflict set) and records what it trusted into a declared channel.
        from typing import Annotated, TypedDict

        from langgraph.graph import END, StateGraph
        from typing_extensions import NotRequired

        from tradingagents.graph.data_quality_gate import create_data_quality_gate_node

        annotations = dict(AgentState.__annotations__)
        annotations["consumer_trusted_origins"] = NotRequired[Annotated[list, "ids trusted"]]
        annotations["consumer_conflicted_ids"] = NotRequired[Annotated[list, "ids excluded"]]
        schema = TypedDict("OriginResumeState", annotations, total=False)

        def _seed(state):
            return {"consumer_trusted_origins": [], "consumer_conflicted_ids": []}

        def _consumer(state):
            # Mirrors a real consumer: reads the single origin choke point (which
            # drops conflicted ids) and the declared conflict channel.
            from tradingagents.debate.evaluator_node import _duplicate_origin_ids_from_state
            from tradingagents.evidence.origin import origin_records_from_state

            trusted = origin_records_from_state(dict(state))
            conflicted = _duplicate_origin_ids_from_state(state)
            return {
                "consumer_trusted_origins": sorted(trusted),
                "consumer_conflicted_ids": sorted(conflicted),
            }

        builder = StateGraph(schema)
        builder.add_node("Seed", _seed)
        builder.add_node("Gate", create_data_quality_gate_node(now_provider=lambda: FETCHED))
        builder.add_node("Consumer", _consumer)
        builder.set_entry_point("Seed")
        builder.add_edge("Seed", "Gate")
        builder.add_edge("Gate", "Consumer")
        builder.add_edge("Consumer", END)
        return builder

    def _conflict_for(self, target_id):
        origin_a = OriginMetadata(target_date=TARGET, observation_date="2026-05-12", unit="USD")
        origin_b = OriginMetadata(target_date=TARGET, observation_date="2026-05-11", unit="USD")
        return origin_a, origin_b

    def test_interrupt_before_consumer_resume_runs_consumer_after_work(self, fixed_snapshot, tmp_path):
        # First pass: Seed + Gate RUN, Consumer is PENDING (interrupted before it).
        baseline = _gate_node()(_state())
        target_id = sorted(baseline[ORIGIN_STATE_KEY])[0]
        origin_a, origin_b = self._conflict_for(target_id)

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with use_collector(SYMBOL, TARGET) as col:
            col.capture_origin(target_id, origin_a)
            col.capture_origin(target_id, origin_b)
            with get_checkpointer(data_dir, SYMBOL) as saver:
                g = self._graph().compile(checkpointer=saver, interrupt_before=["Consumer"])
                first = g.invoke(_state(), cfg)
            # Gate ran; Consumer did NOT (pending). Origins present, conflict closed.
            assert len(first[GATE_EVIDENCE_RECORDS_KEY]) == 5
            assert first.get("consumer_trusted_origins") in (None, [])
            assert target_id in first[INGEST_ORIGIN_CONFLICTED_STATE_KEY]
            assert target_id not in first[ORIGIN_STATE_KEY]

        # Fresh process: no collector survives; re-seed from the REAL saved state.
        assert get_active_collector() is None
        with get_checkpointer(data_dir, SYMBOL) as saver:
            saved = self._graph().compile(checkpointer=saver).get_state(cfg)
            saved_values = dict(saved.values)
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = self._graph().compile(checkpointer=saver)
            with use_collector(SYMBOL, TARGET, prior_state=saved_values):
                final = g2.invoke(None, cfg)  # executes the PENDING Consumer
        # The pending Consumer actually ran and consumed the post-gate truth.
        assert "consumer_trusted_origins" in final
        assert len(final[GATE_EVIDENCE_RECORDS_KEY]) == 5
        # 4 trusted market origins survive; the conflicted id is excluded.
        assert len(final["consumer_trusted_origins"]) == 4
        assert target_id not in final["consumer_trusted_origins"]
        assert target_id in final["consumer_conflicted_ids"]
        assert target_id in final[INGEST_ORIGIN_CONFLICTED_STATE_KEY]
        assert target_id not in final[ORIGIN_STATE_KEY]

    def test_interrupt_before_gate_resume_executes_gate_and_consumer(self, fixed_snapshot, tmp_path):
        # Strongest interrupted resume: first pass runs ONLY Seed (Gate PENDING);
        # the re-seeded collector supplies a real conflict, and invoke(None) runs the
        # REAL production gate + consumer.
        baseline = _gate_node()(_state())
        target_id = sorted(baseline[ORIGIN_STATE_KEY])[0]
        origin_a, origin_b = self._conflict_for(target_id)

        data_dir = str(tmp_path / "ckpt_gate")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = self._graph().compile(checkpointer=saver, interrupt_before=["Gate"])
            first = g.invoke(_state(), cfg)
            # Gate did NOT run yet (no evidence records); Seed ran.
            assert not first.get(GATE_EVIDENCE_RECORDS_KEY)
            assert first.get("consumer_trusted_origins") in (None, [])

        assert get_active_collector() is None
        with get_checkpointer(data_dir, SYMBOL) as saver:
            saved_values = dict(self._graph().compile(checkpointer=saver).get_state(cfg).values)
        # Re-seed a FRESH collector from the saved state and add a REAL conflict.
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = self._graph().compile(checkpointer=saver)
            with use_collector(SYMBOL, TARGET, prior_state=saved_values) as col:
                col.capture_origin(target_id, origin_a)
                col.capture_origin(target_id, origin_b)
                final = g2.invoke(None, cfg)  # executes PENDING Gate + Consumer
        # The real gate ran on resume and produced the 5 market records + origins.
        assert len(final[GATE_EVIDENCE_RECORDS_KEY]) == 5
        assert target_id in final[INGEST_ORIGIN_CONFLICTED_STATE_KEY]
        assert target_id not in final[ORIGIN_STATE_KEY]
        # The consumer executed after the resumed gate work and saw the truth.
        assert len(final["consumer_trusted_origins"]) == 4
        assert target_id in final["consumer_conflicted_ids"]

    def test_resume_after_gate_before_consumer_consumes_persisted_ambiguity(
        self, fixed_snapshot, tmp_path
    ):
        # Checkpoint AFTER the gate ran but BEFORE the consumer (post-gate pending);
        # resume executes the consumer on a fresh graph with NO collector, consuming
        # the persisted ambiguity (no re-trust) — the imported/post-gate resume path.
        baseline = _gate_node()(_state())
        target_id = sorted(baseline[ORIGIN_STATE_KEY])[0]
        origin_a, origin_b = self._conflict_for(target_id)

        data_dir = str(tmp_path / "ckpt_post")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with use_collector(SYMBOL, TARGET) as col:
            col.capture_origin(target_id, origin_a)
            col.capture_origin(target_id, origin_b)
            with get_checkpointer(data_dir, SYMBOL) as saver:
                g = self._graph().compile(checkpointer=saver, interrupt_before=["Consumer"])
                first = g.invoke(_state(), cfg)
            assert target_id in first[INGEST_ORIGIN_CONFLICTED_STATE_KEY]
            assert first.get("consumer_trusted_origins") in (None, [])

        assert get_active_collector() is None
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = self._graph().compile(checkpointer=saver)
            final = g2.invoke(None, cfg)  # NO collector: consumer reads persisted only
        assert len(final[GATE_EVIDENCE_RECORDS_KEY]) == 5
        assert "consumer_trusted_origins" in final
        assert target_id not in final["consumer_trusted_origins"]
        assert target_id in final["consumer_conflicted_ids"]
        json.dumps(final[INGEST_ORIGIN_CONFLICTED_STATE_KEY])

    def test_interrupt_resume_preserves_tombstone_exclusion(self, fixed_snapshot, tmp_path):
        # Scoped-edge interrupted resume: first pass runs Seed + Gate under
        # interrupt_before=["Consumer"]; a prior gate output map + a tombstone for
        # one id are durable; after close/rebuild/resume the PENDING Consumer must
        # NOT trust the tombstoned id (the resumed gate must not re-derive it).
        base = _gate_node()(_state())
        dropped_id = sorted(base[ORIGIN_STATE_KEY])[0]
        data_dir = str(tmp_path / "ckpt_drop")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}
        initial = _state(**{
            ORIGIN_STATE_KEY: dict(base[ORIGIN_STATE_KEY]),
            "data_quality_dropped_evidence_ids": [dropped_id],
        })

        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = self._graph().compile(checkpointer=saver, interrupt_before=["Consumer"])
            first = g.invoke(initial, cfg)
            # Gate ran (pending Consumer) and already excluded the tombstoned id.
            assert len(first[GATE_EVIDENCE_RECORDS_KEY]) == 5
            assert dropped_id not in first[ORIGIN_STATE_KEY]
            assert first.get("consumer_trusted_origins") in (None, [])

        assert get_active_collector() is None
        with get_checkpointer(data_dir, SYMBOL) as saver:
            saved = dict(self._graph().compile(checkpointer=saver).get_state(cfg).values)
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = self._graph().compile(checkpointer=saver)
            with use_collector(SYMBOL, TARGET, prior_state=saved):
                final = g2.invoke(None, cfg)  # executes the PENDING Consumer
        assert len(final[GATE_EVIDENCE_RECORDS_KEY]) == 5
        # The resumed gate kept the tombstone out of the trusted map, and the
        # consumer that actually ran excluded it.
        assert dropped_id not in final[ORIGIN_STATE_KEY]
        assert dropped_id not in final["consumer_trusted_origins"]
        assert len(final["consumer_trusted_origins"]) == 4
