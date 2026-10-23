# Memory Design Notes

Scope: this document records how the CS5351 feature work interacts with the
"memory" of the system — the point-in-time integrity of stored dated data and
the state carried through the graph — and how the gate/evaluator keep that
integrity. It is a design note, not the upstream product memory design, which
lives upstream.

## 1. Point-in-time integrity for dated data

The framework evaluates every dated data path "as of" the requested trade date.
A stored object (OHLCV cache entry, FRED macro series, news article, social
post, decision-log memory row) is read and validated with an `as_of` boundary so
no future data is used. This is preserved from upstream.

- `tradingagents/dataflows/market_data_validator.py` — the verified snapshot
  builder applies the `as_of` boundary when it builds `StructuredSnapshot`.
- `tradingagents/evidence/validate.py` — the deterministic look-ahead validation
  class rejects any evidence whose timestamp is after the requested date.

## 2. Gate-aware state carried through the graph

The Data Quality Gate node writes only JSON-safe fields into `AgentState`:

- `data_quality_verdict` — `normal` / `degraded` / `blocked`.
- `data_quality_evidence_records` — the serialized `EvidenceRecord` list.
- `data_quality_validation_results` — the serialized `ValidationResult` list.
- `data_quality_group_statuses` — the serialized `EvidenceGroupQuality` list.
- `data_quality_gate_decision` — the serialized `GateDecision`.
- `data_quality_context` — human-readable context.
- `data_quality_error` — populated only on a fail-closed internal error.

The router `should_continue_after_data_gate` reads these fields to decide whether
to proceed to the Bull Researcher (`normal`/`degraded`) or route straight to the
Research Manager (`blocked` / missing / malformed gate state). This is a
deliberate fail-closed design: malformed or missing gate state cannot proceed to
a full-strength debate.

## 3. Debate turn state

`tradingagents/debate/state.py` mutates debate state on the researcher side; the
evaluator node reads the gate manifest (evidence records) and the accumulated
turn state off `AgentState` to produce a `RoutingDecision`. The `run_id` used
for evidence IDs is derived from `(trade_date, normalized symbol)`, so the
"memory" of a given run is reproducible for the same symbol/date.

## 4. Relation to upstream memory / decision log

The upstream memory-log / decision-log row writes and the Trader price grounding
remain unchanged; the CS5351 work does not alter how rows are persisted, only
what the gate and debate do with the evidence before a decision. Look-ahead
fixes on the memory log (from upstream v0.4.0/v0.5.0) are preserved.