# Memory Design Notes

Scope: this document records how the CS5351 feature work interacts with the
"memory" of the system — the point-in-time integrity of stored dated data, the
state carried through the graph, the decision/memory log, and the persistence,
ownership, retention, privacy, and cross-session/version behavior of that
memory. It is a design note; the upstream product memory design lives upstream.

## 1. Point-in-time integrity for dated data

The framework evaluates every dated data path "as of" the requested trade date.
A stored object (OHLCV cache entry, FRED macro series, news article, social
post, decision-log memory row) is read and validated with an `as_of` boundary so
no future data is used. This is preserved from upstream.

- `tradingagents/dataflows/market_data_validator.py` — the verified snapshot
  builder applies the `as_of` boundary when it builds `StructuredSnapshot`.
- `tradingagents/evidence/validate.py` — the deterministic look-ahead validation
  class rejects any evidence whose timestamp is after the requested date.
- **Gap (recorded, not hidden):** an allowlist/citation check verifies record
  *eligibility*, not the *semantic truth* of a claim's date. The 2026-11-06 live
  run produced a Bull claim that relabelled a Nov-4 close (observed_at
  `2026-11-04`) as Nov-5 while citing the valid close ID (`RISK-020` /
  `DEBT-022`, OPEN, not fixed).

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

## 4. Decision / memory log and blocked-run hold tagging

The upstream memory-log row write is **no longer unchanged** — the CS5351 work
changed it, and the earlier "unchanged" claim was stale. Concretely
(`tradingagents/agents/utils/memory.py`):

- `TradingMemoryLog(...).record_pending(..., blocked: bool = False)` now takes a
  structured `blocked` flag. On a blocked run the row tag is forced to
  `Hold` (`HOLD if blocked else parse_rating(...)`) so the memory log agrees with
  the authoritative final signal, regardless of how the decision text rendered
  (`FR-DQG-006`).
- The decision body is still the (guarded) final trade decision text; the guard
  (`tradingagents/agents/utils/output_guard.py`) pins executable decision fields
  to Hold while preserving rationale as non-executable prose.
- This behavior is covered by `tests/test_memory_log.py` and
  `tests/test_output_guard.py`.
- **Ownership / access:** the memory log is written only by the owning user's
  session into a local file (default path resolved by config); it is not a
  shared or multi-tenant store. There is no cross-user read path in this
  codebase.
- **Retention / deletion / privacy (current state, not invented policy):**
  entries are append-only and idempotency-guarded by
  `[trade_date | ticker | rating | pending]`; there is **no** automatic
  retention window, redaction pass over stored bodies, or deletion API in this
  codebase. Because the body can contain model-produced prose, the log should be
  treated as potentially sensitive local data. A concrete retention/deletion and
  redaction policy is a **human/team decision that has not been made**; it is
  recorded as pending, not fabricated here.
- **Cross-session / version handling:** the log records a `pending` tag with no
  embedded schema version; a later scoring/version change must tolerate older
  rows by treating unknown fields/tags conservatively (do not rewrite history).
  `run_id` reproducibility across sessions depends on `(trade_date, normalized
  symbol)` only, so the same symbol/date is comparable across sessions; the log
  does not persist provider/model version, so cross-version comparisons are
  best-effort and unverified.

## 5. Relation to upstream memory / decision log

The upstream memory-log / decision-log row writes and the Trader price grounding
are otherwise preserved; look-ahead fixes on the memory log (from upstream
v0.4.0/v0.5.0) remain. The only CS5351 change to persistence is the blocked-run
`Hold` tag described in §4. The Graph checkpoint/resume machinery is inherited
and unchanged; its JSON-safety relies on the gate writing only serialized
dict/list/string forms (§2).
