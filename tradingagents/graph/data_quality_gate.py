"""Data Quality Gate node for the LangGraph workflow (Phase 3A, Stage 2).

This node runs once after the last analyst has produced its report and before
the Bull Researcher opens the debate. It delegates to the deterministic
:mod:`tradingagents.evidence.multi_category_gate` engine, which builds the
verified market snapshot (the same ground-truth source the analyst was told to
trust), adapts it to ``EvidenceRecord`` objects, validates them against the five
deterministic classes, aggregates market quality, and produces a Stage 2
:class:`~tradingagents.evidence.models.GateDecision` over the critical ``market``
category plus the optional categories (``fundamentals``, ``news``, ``sentiment``).

Design rules (authoritative):

- **Multi-category by default**: the default node evaluates the market category
  (critical, fail-closed) and the optional categories. Trustworthy structured
  optional-category evidence enters **only** through the explicit state contract
  ``data_quality_optional_evidence`` (a mapping of category -> serialized
  ``EvidenceGroupQuality`` dict); it is never parsed from analyst prose. An absent
  optional category yields a deterministic unavailable/insufficient result that
  degrades the verdict under the versioned policy, never a fabricated one.
- **Dependency-injectable**: every component (snapshot builder, record adapter,
  validator, aggregator, run-id builder, ``decided_at`` provider, optional
  evidence reader) is passed to :func:`create_data_quality_gate_node` so tests
  can substitute a fixed snapshot and a fake/``None`` clock without touching a
  network or a paid LLM. The defaults are the real, deterministic production
  implementations.
- **Fail closed**: any exception raised while running the gate is caught and
  converted into a ``blocked`` :class:`GateDecision` whose human-readable
  context states the gate error. It is never turned into ``normal``, so a low
  quality run can never silently proceed as an unrestricted debate. The market
  category stays fail-closed: a missing/blocked market category always blocks.
- **Stable deterministic identifiers**: the ``run_id`` is derived from the
  current state inputs (``trade_date`` + normalized symbol) — never a random
  value — so evidence IDs and the gate output are identical for the same
  ``(symbol, requested_date)``.
- **JSON/checkpoint serializable**: the node only writes plain dicts/lists/
  strings into ``AgentState`` (the serialized ``to_dict()`` forms of the
  dataclasses), never the frozen dataclass objects themselves.

The node returns a dict with the gate-aware ``AgentState`` fields; the router
(:func:`tradingagents.graph.conditional_logic.ConditionalLogic.should_continue_after_data_gate`)
decides whether to proceed to ``Bull Researcher`` (normal/degraded) or route
straight to ``Research Manager`` (blocked / missing / malformed gate state).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from tradingagents.dataflows.market_data_validator import (
    StructuredSnapshot,
    build_verified_market_snapshot_data,
)
from tradingagents.evidence import (
    Criticality,
    EvidenceGroupQuality,
    GateDecision,
    QualityStatus,
    build_market_evidence_records,
    validate_market_records,
)
from tradingagents.evidence.adapter import MARKET_CATEGORY
from tradingagents.evidence.gate import (
    build_multi_category_gate_decision,
    build_unavailable_category,
)
from tradingagents.evidence.ingest import (
    INGEST_DROPPED_STATE_KEY,
    INGEST_ORIGIN_CONFLICTED_STATE_KEY,
)
from tradingagents.evidence.multi_category_gate import evaluate_multi_category_gate
from tradingagents.evidence.origin import ORIGIN_STATE_KEY, build_origin_map_from_records
from tradingagents.evidence.policy import (
    DEFAULT_MULTI_CATEGORY_POLICY,
    OPTIONAL_CATEGORIES,
    MultiCategoryPolicy,
)

logger = logging.getLogger(__name__)

# AgentState keys written by this node (stable, JSON-safe).
GATE_VERDICT_KEY = "data_quality_verdict"
GATE_EVIDENCE_RECORDS_KEY = "data_quality_evidence_records"
GATE_VALIDATION_KEY = "data_quality_validation_results"
GATE_GROUPS_KEY = "data_quality_group_statuses"
GATE_DECISION_KEY = "data_quality_gate_decision"
GATE_CONTEXT_KEY = "data_quality_context"
GATE_ERROR_KEY = "data_quality_error"

# Explicit structured optional-category evidence contract (JSON-safe). This is
# the ONLY channel by which trustworthy structured optional-category evidence
# (fundamentals, news, sentiment) enters the gate: a mapping of category name ->
# serialized ``EvidenceGroupQuality`` dict. It is never parsed from analyst
# prose. Absent values (the honest state today) yield deterministic
# unavailable/insufficient results that degrade under the policy.
GATE_OPTIONAL_EVIDENCE_KEY = "data_quality_optional_evidence"

# ADR-008: JSON-safe envelope for the run's captured vendor-origin evidence and
# source-attempt ledger (documented metadata channel; never nested in a record).
GATE_INGESTED_EVIDENCE_KEY = "data_quality_ingested_evidence"
GATE_SOURCE_ATTEMPTS_KEY = "data_quality_source_attempts"

# Human-readable routing verdicts (mirror GateVerdict values).
GATE_NORMAL = "normal"
GATE_DEGRADED = "degraded"
GATE_BLOCKED = "blocked"

_DEFAULT_ASSET_TYPE = "stock"

# Deterministic safe fallback timestamp used when the injected ``now_provider``
# itself fails mid-run. It is a fixed, valid ISO-8601 instant (the Unix epoch)
# so a blocked gate output stays reproducible and never depends on wall-clock
# time, and the failure handler never has to re-call the failing provider.
_FALLBACK_DECIDED_AT = "1970-01-01T00:00:00Z"


def _default_now_iso() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ`` (default ``decided_at``)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_gate_run_id(trade_date: str, symbol_normalized: str) -> str:
    """Stable deterministic run identifier derived from state inputs.

    ``trade_date`` + the normalized symbol uniquely identify a run; the evidence
    IDs derived from it are therefore reproducible for the same
    ``(symbol, requested_date)`` and never depend on wall-clock time.
    """
    return f"{str(trade_date)}/{symbol_normalized}"


def _gate_decision_to_dicts(decision: GateDecision) -> dict[str, Any]:
    """Serialize a ``GateDecision`` into plain JSON-safe primitives."""
    return decision.to_dict()


def _groups_to_dicts(groups: list[EvidenceGroupQuality]) -> list[dict[str, Any]]:
    """Serialize per-category group quality into plain JSON-safe dicts."""
    return [group.to_dict() for group in groups]


def _sentence(text: str) -> str:
    """Return ``text`` with exactly one trailing period, never two.

    The gate's human-readable reason and limitation strings are authored with a
    trailing period already; appending another would produce ``foo..``. Apply
    this before interpolation so the context stays clean without changing what
    it says.
    """
    return text.rstrip(".") + "."


def build_gate_context(decision: GateDecision) -> str:
    """Human-readable gate constraint/context string for the downstream prompts.

    The string is deterministic and states: the gate verdict, how confidence is
    bounded, which evidence IDs remain valid to cite, the recovery conditions,
    and (for degraded/blocked) the limitations that restrict the debate. It is
    intentionally plain so it can be interpolated verbatim into a prompt.
    """
    verdict = decision.decision.value
    limitations = decision.limitations or []
    ids = decision.critical_evidence_ids or []

    lines: list[str] = ["[Data Quality Gate]", f"Verdict: {verdict}."]

    if verdict == GATE_BLOCKED:
        lines.append(
            "Critical market data is missing or conflicting; the standard "
            "bull/bear debate was skipped. Only an evidence-insufficient "
            "conclusion may be produced. No directional Buy or Sell is permitted."
        )
        if decision.human_readable_reason:
            lines.append("Reason: " + _sentence(decision.human_readable_reason))
        if ids:
            lines.append("Affected/blocked evidence IDs: " + ", ".join(ids) + ".")
        if limitations:
            lines.append("Limitations: " + _sentence("; ".join(limitations)))
        lines.append(
            "Recovery: the block clears once critical market data is available "
            "and validates consistently on a later run."
        )
    elif verdict == GATE_DEGRADED:
        lines.append(
            "Market data has quality limitations. This is not unrestricted "
            "continuation: low-evidence claims cannot be decisive, only the "
            "evidence IDs listed below may be cited, and confidence is capped. "
            "If the core view is supported only by Low evidence, the manager "
            "must choose Hold / insufficient evidence."
        )
        if decision.human_readable_reason:
            lines.append("Reason: " + _sentence(decision.human_readable_reason))
        if ids:
            lines.append("Valid evidence IDs: " + ", ".join(ids) + ".")
        if limitations:
            lines.append("Limitations: " + _sentence("; ".join(limitations)))
        lines.append("Confidence: capped by the quality limitations above.")
    else:  # normal
        lines.append(
            "Market quality is adequate: the standard bull/bear debate may "
            "proceed with normal confidence, citing the validated evidence."
        )
        if decision.human_readable_reason:
            lines.append("Reason: " + _sentence(decision.human_readable_reason))

    return "\n".join(lines)


def build_blocked_decision(
    reason: str,
    *,
    decided_at: str | None = None,
    evidence_ids: list[str] | None = None,
    policy: MultiCategoryPolicy | None = None,
) -> GateDecision:
    """Build a fail-closed ``blocked`` ``GateDecision``.

    Used by the gate node whenever the pipeline cannot produce a genuine verdict
    (an exception, missing evidence, or malformed results). The decision is
    always ``blocked`` — never ``normal`` — and carries the failure reason in its
    human-readable text so downstream prompts state why the debate was skipped.

    The market category is marked ``blocked`` (fail closed) and each optional
    category is emitted as an explicit deterministic unavailable result (it never
    hides the block and never fabricates a source). The verdict is ``blocked``
    regardless of the optional categories, because the market is critical.
    """
    resolved_policy = policy or DEFAULT_MULTI_CATEGORY_POLICY
    category = MARKET_CATEGORY
    blocked_group = EvidenceGroupQuality(
        category=category,
        quality_status=QualityStatus.BLOCKED,
        criticality=Criticality.CRITICAL,
        evidence_ids=list(evidence_ids or []),
        source_count=0,
        independent_source_count=0,
        reason_codes=["gate_error" if not evidence_ids else "blocked_critical_failure"],
        human_readable_reason=reason,
    )
    groups = [blocked_group]
    for optional in OPTIONAL_CATEGORIES:
        category_policy = resolved_policy.optional.get(optional)
        groups.append(
            build_unavailable_category(
                optional,
                policy_version=(
                    category_policy.policy_version if category_policy else "1.0"
                ),
            )
        )
    return build_multi_category_gate_decision(
        groups,
        decided_at=decided_at or _default_now_iso(),
        policy=resolved_policy,
    )


def create_data_quality_gate_node(
    *,
    snapshot_builder: Callable[..., StructuredSnapshot] = build_verified_market_snapshot_data,
    record_builder: Callable = build_market_evidence_records,
    validator: Callable = validate_market_records,
    aggregator: Callable | None = None,
    gate_builder: Callable | None = None,
    run_id_builder: Callable[[str, str], str] = build_gate_run_id,
    now_provider: Callable[[], str] = _default_now_iso,
    category: str = MARKET_CATEGORY,
    policy: MultiCategoryPolicy | None = None,
    market_policy: Any | None = None,
    asset_type: str = _DEFAULT_ASSET_TYPE,
    look_back_days: int = 30,
    optional_evidence_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    captured_evidence_reader: Callable[[Mapping[str, Any]], tuple[dict, list]] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Build the Data Quality Gate LangGraph node with injectable components.

    Defaults are the real deterministic production components. Tests pass fixed
    versions (e.g. a snapshot that never touches ``load_ohlcv``) and a
    deterministic ``now_provider`` so the gate output is reproducible offline.

    The returned node reads ``company_of_interest`` / ``trade_date`` /
    ``asset_type`` from state. It runs the **Stage 2 multi-category engine**
    (:func:`evaluate_multi_category_gate`) which evaluates the critical market
    category plus the optional categories (fundamentals, news, sentiment). Any
    trustworthy structured optional-category evidence enters **only** through the
    explicit state contract ``data_quality_optional_evidence`` (a mapping of
    category -> ``EvidenceGroupQuality`` dict) — never parsed from analyst prose;
    an absent optional category yields a deterministic unavailable/insufficient
    result that degrades under the policy.

    The gate node is fully deterministic given those inputs and never needs an
    LLM or network beyond the default snapshot builder. Any exception in the gate
    pipeline is caught and converted to a fail-closed ``blocked`` decision (never
    ``normal``).

    Args:
        snapshot_builder: Builds the verified market snapshot (injectable).
        record_builder: Adapts a snapshot to ``EvidenceRecord`` objects.
        validator: Validates market records against the five classes.
        aggregator: Aggregates per-category quality (passed to the engine).
        gate_builder: Legacy single-category gate builder; retained for signature
            backward compatibility but the multi-category engine builds the
            decision, so it is not invoked by the default path.
        run_id_builder: Stable deterministic run-id builder from
            ``(trade_date, normalized symbol)``.
        now_provider: Deterministic ``decided_at`` provider.
        category: Legacy single-category label; retained for signature backward
            compatibility. The multi-category engine always uses the market
            category for the critical group.
        policy: The :class:`MultiCategoryPolicy` bundle (default
            ``DEFAULT_MULTI_CATEGORY_POLICY``).
        market_policy: The :class:`MarketPolicy` for market validation (defaults
            to the validator's own default).
        asset_type: Expected asset type (default ``stock``).
        look_back_days: History window for the market snapshot builder.
        optional_evidence_reader: Optional callable reading the explicit
            structured optional-category evidence contract from state; defaults
            to :func:`_read_optional_category_groups`.

    Returns:
        The LangGraph node (``state: Mapping -> dict`` of gate AgentState fields).
    """
    resolved_policy = policy or DEFAULT_MULTI_CATEGORY_POLICY
    read_optional = optional_evidence_reader or _read_optional_category_groups
    read_captured = captured_evidence_reader or _read_captured_evidence

    def data_quality_gate_node(state: Mapping[str, Any]) -> dict[str, Any]:
        symbol = str(state.get("company_of_interest", ""))
        trade_date = str(state.get("trade_date", ""))
        resolved_asset = str(state.get("asset_type") or asset_type)

        if not symbol or not trade_date:
            # Fail closed: without a symbol/date there is nothing to verify. The
            # clock provider may itself be broken, so guard it and fall back to
            # the deterministic safe timestamp rather than re-calling it.
            decided_at = _safe_now(now_provider, symbol, trade_date)
            decision = build_blocked_decision(
                "Gate cannot run: missing symbol or trade date in state.",
                decided_at=decided_at or _FALLBACK_DECIDED_AT,
                policy=resolved_policy,
            )
            return _blocked_node_output(decision, "Missing symbol or trade date.")

        try:
            optional_groups = read_optional(state, resolved_policy)
            captured_records, captured_attempts = read_captured(state)
            result = evaluate_multi_category_gate(
                trade_date=trade_date,
                symbol=symbol,
                asset_type=resolved_asset,
                look_back_days=look_back_days,
                snapshot_builder=snapshot_builder,
                record_builder=record_builder,
                validator=validator,
                aggregator=aggregator or _default_aggregator,
                policy=resolved_policy,
                now_provider=now_provider,
                market_policy=market_policy,
                run_id_builder=run_id_builder,
                optional_category_groups=optional_groups,
                captured_optional_records=captured_records,
            )
            decision = result.gate_decision
            output = {
                GATE_VERDICT_KEY: decision.decision.value,
                GATE_EVIDENCE_RECORDS_KEY: result.evidence_records,
                GATE_VALIDATION_KEY: result.validation_results,
                GATE_GROUPS_KEY: result.groups,
                GATE_DECISION_KEY: _gate_decision_to_dicts(decision),
                GATE_CONTEXT_KEY: result.context,
                GATE_ERROR_KEY: None,
                GATE_SOURCE_ATTEMPTS_KEY: captured_attempts,
            }
            # Persist the captured evidence into graph state so a checkpoint
            # taken after this gate survives a process restart and a resumed run
            # re-seeds from it. Excluded records are pruned so they cannot be
            # resurrected as decisive evidence on resume.
            persisted = _persist_ingest_state(state, pruned=result.pruned_record_ids)
            # Defect-1 (ADR-010 amendment): the AUTHORITATIVE origin map is merged
            # AFTER persistence, so the collector's (often empty-for-market) origin
            # delta can no longer overwrite the gate-derived/captured origins.
            # Genuine captured origins are preserved; a real captured conflict or a
            # lost-trust id is failed closed (removed from the trusted map and
            # recorded in the declared conflicted channel) — never re-derived, never
            # resurrected, never first/last-wins.
            if persisted is not None:
                output.update(
                    {
                        key: value
                        for key, value in persisted.items()
                        if key != ORIGIN_STATE_KEY
                        and key != INGEST_ORIGIN_CONFLICTED_STATE_KEY
                    }
                )
            # Defect-1: tombstone exclusion is authoritative across BOTH the durable
            # collector delta AND any pre-existing state tombstones (a no-collector
            # run has persisted=None but existing state may still carry drops).
            existing_dropped = (
                state.get(INGEST_DROPPED_STATE_KEY) if isinstance(state, Mapping) else None
            ) or []
            merged_origin_map, conflicted_ids = _merge_authoritative_origins(
                gate_origin_map=_origin_state_map(state, result.evidence_records),
                persisted_origin_map=(persisted or {}).get(ORIGIN_STATE_KEY) or {},
                persisted_conflicted_ids=(persisted or {}).get(
                    INGEST_ORIGIN_CONFLICTED_STATE_KEY
                )
                or [],
                pruned_ids=result.pruned_record_ids,
                dropped_ids=list(
                    set((persisted or {}).get(INGEST_DROPPED_STATE_KEY) or [])
                    | {str(eid) for eid in existing_dropped if isinstance(eid, str)}
                ),
            )
            output[ORIGIN_STATE_KEY] = merged_origin_map
            output[INGEST_ORIGIN_CONFLICTED_STATE_KEY] = conflicted_ids
            return output
        except Exception as exc:  # noqa: BLE001 — fail closed on any gate error
            logger.error(
                "Data Quality Gate failed for %s on %s; routing blocked: %s",
                symbol, trade_date, exc,
            )
            # Never re-call ``now_provider`` here (it may be the failing
            # component): use the deterministic safe fallback timestamp so the
            # blocked output stays reproducible and JSON-serializable.
            decision = build_blocked_decision(
                f"Gate exception: {type(exc).__name__}: {exc}. "
                "Validation could not complete; the run is blocked.",
                decided_at=_FALLBACK_DECIDED_AT,
                policy=resolved_policy,
            )
            return _blocked_node_output(
                decision,
                f"Gate exception: {type(exc).__name__}: {exc}",
            )

    return data_quality_gate_node


def _default_aggregator(category, records, results_by_id, policy=None):
    """The multi-category engine's default category aggregator.

    Imported lazily to avoid a top-of-module cost and to keep the graph node
    independent of the aggregator plumbing; this is the same deterministic
    market aggregator the engine uses by default.
    """
    from tradingagents.evidence.quality import aggregate_category_quality

    return aggregate_category_quality(category, records, results_by_id, policy=policy)


def _read_optional_category_groups(
    state: Mapping[str, Any],
    policy: MultiCategoryPolicy,
) -> dict[str, EvidenceGroupQuality]:
    """Read the explicit structured optional-category evidence contract from state.

    The contract lives in ``data_quality_optional_evidence``: a mapping of
    optional category name -> serialized ``EvidenceGroupQuality`` dict (the
    JSON-safe form the node writes/reads). Only trusted structured group quality
    is accepted; anything else is ignored so an unknown/malformed entry never
    fabricates a source or a confidence. Only categories the policy knows as
    optional are honoured.
    """
    raw = state.get(GATE_OPTIONAL_EVIDENCE_KEY) or {}
    if not isinstance(raw, Mapping):
        return {}
    groups: dict[str, EvidenceGroupQuality] = {}
    for category, value in raw.items():
        category = str(category)
        if category not in OPTIONAL_CATEGORIES:
            continue
        category_policy = policy.optional.get(category)
        if category_policy is None:
            continue
        if isinstance(value, EvidenceGroupQuality):
            groups[category] = value
        elif isinstance(value, Mapping):
            groups[category] = EvidenceGroupQuality.from_dict(dict(value))
        # Any other shape is rejected (never coerced or parsed from prose).
    return groups


def _read_captured_evidence(
    state: Mapping[str, Any],
) -> tuple[dict[str, list], list[dict]]:
    """Read the run's captured vendor-origin evidence, state + live collector.

    Reads **both** the durable persisted state channel (``data_quality_ingested_
    evidence`` / ``data_quality_source_attempts``, populated by the tool-node
    boundary and checkpointed) and the live request/run-scoped collector
    (ADR-008). This is what makes capture durable: on a resumed run the state
    channel survives the process boundary even though the ``ContextVar`` does
    not, so the gate still sees the evidence a prior checkpoint carried.

    The persisted channel is untrusted input from the checkpoint store; a record
    is only added if it re-parses as a typed ``EvidenceRecord`` (so a tampered or
    malformed persisted row can never become decisive evidence — it is skipped).
    Returns ``(records_by_category, attempts)`` where attempts are bare 7-field
    dicts (from the versioned envelope) and records are typed objects keyed by
    category.
    """
    from tradingagents.evidence.ingest import (
        INGEST_ATTEMPTS_STATE_KEY,
        INGEST_RECORDS_STATE_KEY,
        AttemptEnvelope,
        get_active_collector,
    )
    from tradingagents.evidence.models import EvidenceRecord

    typed_records: dict[str, EvidenceRecord] = {}
    attempts_by_index: dict[int, dict] = {}

    # 1) Durable persisted state channel (survives checkpoint/resume).
    for raw in state.get(INGEST_RECORDS_STATE_KEY) or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            record = EvidenceRecord.from_dict(dict(raw))
        except Exception:  # noqa: BLE001 — malformed persisted row is skipped
            logger.error("Skipping malformed persisted ingested-evidence row")
            continue
        if record.evidence_id:
            typed_records[record.evidence_id] = record
    for raw in state.get(INGEST_ATTEMPTS_STATE_KEY) or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            env = AttemptEnvelope.from_dict(dict(raw))
        except Exception:  # noqa: BLE001 — malformed persisted attempt is skipped
            continue
        attempts_by_index[env.attempt_index] = env.attempt.to_dict()

    # 2) Live run-scoped collector (authoritative, fresher capture).
    try:
        collector = get_active_collector()
    except Exception:  # noqa: BLE001 — a broken collector must not block the gate
        logger.error("Captured-evidence collector unavailable; using persisted state only")
        collector = None
    if collector is not None:
        for record in collector.all_records():
            typed_records[record.evidence_id] = record
        for env in collector.attempt_envelopes():
            attempts_by_index[env.attempt_index] = env.attempt.to_dict()

    records_by_category: dict[str, list] = {}
    for record in typed_records.values():
        records_by_category.setdefault(record.category, []).append(record)
    for category in records_by_category:
        records_by_category[category].sort(key=lambda r: r.evidence_id)
    attempts = [attempts_by_index[i] for i in sorted(attempts_by_index)]
    return records_by_category, attempts


def _persist_ingest_state(
    state: Mapping[str, Any], *, pruned: list[str]
) -> dict[str, Any] | None:
    """Merge the live collector's captured evidence into durable graph state.

    Returns the JSON-safe state keys (``data_quality_ingested_evidence``,
    ``data_quality_source_attempt_envelopes``, ``data_quality_ingest_metadata``,
    ``data_quality_dropped_evidence_ids``) that make capture survive a checkpoint,
    or ``None`` when there is no active collector (nothing to persist). Each
    pruned record id is EXPLICITLY tombstoned on the collector (dropped + recorded
    in ``data_quality_dropped_evidence_ids``) so a later resume/merge can never
    resurrect an excluded record as evidence.
    """
    try:
        from tradingagents.evidence.ingest import (
            get_active_collector,
            merge_into_state,
        )

        collector = get_active_collector()
        if collector is None:
            return None
        # Tombstone excluded records on the collector itself (explicit drop), so
        # the merged state both omits them and carries the tombstone.
        for evidence_id in pruned or []:
            collector.drop_record(evidence_id)
        delta = collector.state_delta()
        return merge_into_state(delta, state)
    except Exception:  # noqa: BLE001 — persistence must never block the gate
        logger.error("Persisting captured evidence failed; state channel unchanged")
        return None


def _record_id(record: Any) -> str:
    """The ``evidence_id`` of a typed record or its serialized dict form."""
    try:
        if isinstance(record, Mapping):
            return str(record.get("evidence_id", "") or "")
        return str(getattr(record, "evidence_id", "") or "")
    except Exception:  # noqa: BLE001 — an unreadable id is treated as absent
        return ""


def _origin_state_map(
    state: Mapping[str, Any], records: list[Any]
) -> tuple[dict[str, Any], set[str]]:
    """Serialized origin map for ``records`` (captured origin preferred).

    Reads captured origin from the durable state channel and the live collector
    (ADR-010), then derives an honest origin only for a record with none. A
    genuinely DIFFERING dual origin for the same id (state vs collector, or two
    collector captures) is a real conflict: the id is returned in the conflicted
    set so the caller fails it closed — it is never silently first/last-wins.

    The result is JSON-safe and deterministic (sorted by evidence id). Any failure
    degrades to derived-origin-only plus any known conflict set; it never blocks
    the gate.
    """
    from tradingagents.evidence.ingest import (
        INGEST_ORIGIN_CONFLICTED_STATE_KEY,
        _origin_canonical,
        get_active_collector,
    )
    from tradingagents.evidence.origin import (
        ORIGIN_DROPPED_STATE_KEY,
        origin_records_from_state,
        serialize_origin_map,
    )

    existing = origin_records_from_state(dict(state) if isinstance(state, Mapping) else {})
    # Seed the conflict set UNCONDITIONALLY from persisted state (Defect-1 fix):
    # with no active collector (e.g. a direct SQLite resume / imported report
    # state) a previously-conflicted id must stay untrusted and must NOT be
    # re-derived/re-trusted from a stale persisted origin.
    conflicted: set[str] = set()
    # Seed the tombstone set UNCONDITIONALLY from persisted state too: with no
    # active collector a previously-excluded id must never be re-derived/re-trusted
    # from a stale map (no resurrection).
    tombstoned: set[str] = set()
    if isinstance(state, Mapping):
        for evidence_id in state.get(INGEST_ORIGIN_CONFLICTED_STATE_KEY) or []:
            if isinstance(evidence_id, str) and evidence_id:
                conflicted.add(evidence_id)
        for evidence_id in state.get(ORIGIN_DROPPED_STATE_KEY) or []:
            if isinstance(evidence_id, str) and evidence_id:
                tombstoned.add(evidence_id)
    try:
        collector = get_active_collector()
    except Exception:  # noqa: BLE001 — a broken collector must not block the gate
        collector = None
    if collector is not None:
        for evidence_id, origin in collector.origins_map().items():
            prior = existing.get(evidence_id)
            if prior is None:
                existing[evidence_id] = origin
            elif _origin_canonical(prior) != _origin_canonical(origin):
                # State vs live collector genuinely disagree for the same id.
                conflicted.add(evidence_id)
        conflicted |= collector.conflicted_origin_ids()
        tombstoned |= set(collector.dropped_record_ids())
    # A conflicted/tombstoned id is untrustworthy: drop any stale origin BEFORE
    # derivation so the gate never re-trusts (nor re-derives a trusted replacement
    # for) it.
    for evidence_id in conflicted | tombstoned:
        existing.pop(evidence_id, None)
    # Also exclude tombstones from the derivation input so no replacement origin is
    # minted for a record that persists in the manifest but is explicitly dropped.
    derivable = [r for r in records if str(_record_id(r)) not in tombstoned]
    try:
        serialized = serialize_origin_map(build_origin_map_from_records(derivable, existing))
    except Exception:  # noqa: BLE001 — never block the gate on origin derivation
        logger.error("Origin-metadata derivation failed; using derived-only map")
        serialized = serialize_origin_map(build_origin_map_from_records(records, {}))
    return serialized, conflicted


def _merge_authoritative_origins(
    *,
    gate_origin_map: tuple[dict[str, Any], set[str]],
    persisted_origin_map: Mapping[str, Any],
    persisted_conflicted_ids: Any,
    pruned_ids: Any,
    dropped_ids: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Merge the gate-authoritative origin map AFTER ingestion persistence.

    Defect-1 (ADR-010 amendment): the gate-derived/captured origin map must be the
    authoritative LAST write to ``ORIGIN_STATE_KEY`` — a collector persistence delta
    (often with an empty origin map for market records) must never clobber it.

    Semantics:

    - The gate map (over ``records``) is the base; every manifest record keeps a
      typed origin (captured genuine roles preserved, else derived — never a
      fabricated date/currency).
    - A genuine captured origin from the persisted channel that the gate map lacks
      is added (preserves genuine captured SEC/news roles across persistence).
    - Any id in the gate conflict set OR the persisted conflict set OR whose two
      maps genuinely differ is FAILED CLOSED: removed from the trusted map and
      recorded in the returned conflicted list (unverifiable downstream). A
      conflicted id is NEVER re-derived or re-trusted.
    - Pruned/dropped/tombstoned ids are never resurrected (records or origins).
    - Deterministic order (sorted by evidence id), JSON-safe.
    """
    from tradingagents.evidence.ingest import _origin_dict_canonical

    base_map, gate_conflicted = gate_origin_map
    merged: dict[str, Any] = {
        str(eid): origin for eid, origin in base_map.items() if isinstance(origin, Mapping)
    }
    conflicted: set[str] = set(gate_conflicted)
    for eid in persisted_conflicted_ids or []:
        if isinstance(eid, str):
            conflicted.add(eid)
    for eid, origin in (persisted_origin_map or {}).items():
        if not isinstance(origin, Mapping):
            continue
        eid = str(eid)
        if eid in merged and _origin_dict_canonical(merged[eid]) != _origin_dict_canonical(origin):
            # Two genuine origins disagree across channels: fail closed, do not
            # prefer either side.
            conflicted.add(eid)
        else:
            merged.setdefault(eid, origin)
    excluded = {str(eid) for eid in (pruned_ids or []) if isinstance(eid, str)}
    excluded |= {str(eid) for eid in (dropped_ids or []) if isinstance(eid, str)}
    for eid in excluded:
        merged.pop(eid, None)
        conflicted.discard(eid)
    # A conflicted id is not a trusted origin: remove it from the trusted map so a
    # consumer sees it as unverifiable rather than as a silently-chosen origin.
    for eid in conflicted:
        merged.pop(eid, None)
    return (
        {eid: merged[eid] for eid in sorted(merged)},
        sorted(conflicted - excluded),
    )


def _safe_now(now_provider: Callable[[], str], symbol: str, trade_date: str) -> str | None:
    """Call ``now_provider`` once, returning ``None`` on any failure.

    Used where a timestamp is optional (the missing-symbol/date fail-closed
    branch). A failing clock is never propagated and never called twice: the
    caller supplies a deterministic fallback when ``None`` is returned.
    """
    try:
        return now_provider()
    except Exception as exc:  # noqa: BLE001 — fail closed on a failing clock
        logger.error(
            "Data Quality Gate timestamp provider failed for %s on %s; "
            "using deterministic fallback: %s",
            symbol, trade_date, exc,
        )
        return None


def _blocked_node_output(
    decision: GateDecision, error: str
) -> dict[str, Any]:
    """The ``AgentState`` delta a fail-closed gate node returns."""
    return {
        GATE_VERDICT_KEY: GATE_BLOCKED,
        GATE_EVIDENCE_RECORDS_KEY: [],
        GATE_VALIDATION_KEY: {},
        GATE_GROUPS_KEY: _groups_to_dicts(decision.group_statuses),
        GATE_DECISION_KEY: _gate_decision_to_dicts(decision),
        GATE_CONTEXT_KEY: build_gate_context(decision),
        GATE_ERROR_KEY: error,
    }
