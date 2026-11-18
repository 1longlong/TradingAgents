from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import NotRequired, TypedDict


# Researcher team state
class InvestDebateState(TypedDict):
    bull_history: Annotated[
        str, "Bullish Conversation history"
    ]  # Bullish Conversation history
    bear_history: Annotated[
        str, "Bearish Conversation history"
    ]  # Bullish Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    current_response: Annotated[str, "Latest response"]  # Last response
    judge_decision: Annotated[str, "Final judge decision"]  # Last response
    count: Annotated[int, "Length of the current conversation"]  # Conversation length

    # Phase 3B dynamic debate-termination bookkeeping. All plain JSON-safe
    # structures so the debate evaluator state survives LangGraph checkpointing.
    turns: NotRequired[
        Annotated[list, "Serialized DebateTurn dicts (readable + metadata) in speaker order"]
    ]
    conflicts: NotRequired[
        Annotated[list, "Serialized ConflictRecord dicts tracked across the debate"]
    ]
    stances: NotRequired[
        Annotated[dict, "Serialized StanceSnapshot dicts keyed by speaker (Bull/Bear)"]
    ]
    previously_cited_evidence_ids: NotRequired[
        Annotated[list, "Evidence IDs cited before the current round, in citation order"]
    ]
    round_metrics: NotRequired[
        Annotated[list, "Serialized RoundMetrics dicts, one per completed round"]
    ]
    metadata_parse_failed_count: NotRequired[Annotated[int, "Count of failed metadata parses"]]
    no_new_evidence_streak: NotRequired[Annotated[int, "Consecutive rounds with zero new evidence"]]
    budget: NotRequired[
        Annotated[dict, "Serialized BudgetState dict (limits + usage + estimates)"]
    ]


# Risk management team state
class RiskDebateState(TypedDict):
    aggressive_history: Annotated[
        str, "Aggressive Agent's Conversation history"
    ]  # Conversation history
    conservative_history: Annotated[
        str, "Conservative Agent's Conversation history"
    ]  # Conversation history
    neutral_history: Annotated[
        str, "Neutral Agent's Conversation history"
    ]  # Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[
        str, "Latest response by the aggressive analyst"
    ]  # Last response
    current_conservative_response: Annotated[
        str, "Latest response by the conservative analyst"
    ]  # Last response
    current_neutral_response: Annotated[
        str, "Latest response by the neutral analyst"
    ]  # Last response
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


class AgentState(MessagesState):
    company_of_interest: Annotated[str, "Company that we are interested in trading"]
    asset_type: Annotated[str, "Asset type under analysis such as stock or crypto"]
    instrument_context: Annotated[str, "Deterministic ticker identity resolved at run start"]
    trade_date: Annotated[str, "What date we are trading at"]
    # ADR-009: the real EXECUTION identity of this run (minted on a fresh start,
    # reused verbatim on resume, persisted through the real SQLite checkpoint). It
    # is distinct from the reproducible gate/evidence run_id. Used to scope the
    # durable usage ledger so a fresh run never inherits a prior finished run's
    # spend and a resume keeps its own.
    run_id: NotRequired[Annotated[str, "Execution identity for the durable usage ledger"]]
    # ADR-009 reporting-only whole-run usage (per-phase + totals + completeness).
    # Never a budget limit and never silently widens the debate budget.
    whole_run_usage: NotRequired[
        Annotated[dict, "Whole-run usage by phase plus totals and completeness"]
    ]
    # ADR-009 optional durable usage-ledger path; defaults under results_dir.
    usage_ledger_path: NotRequired[
        Annotated[str, "Durable SQLite usage-ledger path for this run"]
    ]
    # Optional results directory used to derive default durable audit paths
    # (failure ledger / partial-debate quarantine) when no explicit path is set.
    results_dir: NotRequired[Annotated[str, "Run results directory for default audit paths"]]

    sender: Annotated[str, "Agent that sent this message"]

    # research step
    market_report: Annotated[str, "Report from the Market Analyst"]
    sentiment_report: Annotated[str, "Report from the Sentiment Analyst"]
    news_report: Annotated[
        str, "Report from the News Researcher of current world affairs"
    ]
    fundamentals_report: Annotated[str, "Report from the Fundamentals Researcher"]

    # deterministic Data Quality Gate (Phase 3A). Plain JSON-safe primitives so
    # the gate result is checkpoint-serializable; see graph/data_quality_gate.py.
    data_quality_verdict: Annotated[str, "Gate verdict: normal/degraded/blocked"]
    data_quality_evidence_records: Annotated[
        list, "Serialized EvidenceRecord dicts for the verified market snapshot"
    ]
    data_quality_validation_results: Annotated[
        dict, "Serialized validation results keyed by evidence_id"
    ]
    data_quality_group_statuses: Annotated[
        list, "Serialized EvidenceGroupQuality dicts, one per evaluated category"
    ]
    data_quality_gate_decision: Annotated[
        dict, "Serialized GateDecision (verdict, limitations, reason codes)"
    ]
    data_quality_context: Annotated[
        str, "Human-readable gate constraint/context string for downstream prompts"
    ]
    data_quality_error: Annotated[
        str | None, "Gate error marker (None on a clean run; a message when fail-closed)"
    ]
    # Stage 2 STRUCTURED optional-category evidence contract (input-only). This
    # is the ONLY channel by which trustworthy structured optional-category
    # evidence (fundamentals, news, sentiment) enters the gate: a mapping of
    # category -> serialized EvidenceGroupQuality dict. Never parsed from analyst
    # prose; an absent value yields a deterministic unavailable/insufficient
    # result that degrades under the policy (see graph/data_quality_gate.py).
    data_quality_optional_evidence: NotRequired[
        Annotated[dict, "Optional-category EvidenceGroupQuality dicts by category"]
    ]
    # ADR-008: JSON-safe source-attempt ledger for actually-operating vendor
    # sources in this run (7-field SourceAttempt dicts, sanitized). Written by the
    # gate node; never a fabricated attempt for a feed that was not called.
    data_quality_source_attempts: NotRequired[
        Annotated[list, "Sanitized SourceAttempt dicts for operated vendor sources"]
    ]
    # ADR-008 durable capture channels. These MUST be declared on the production
    # AgentState or LangGraph silently discards the writes (a checkpoint update to
    # an undeclared key is dropped). The tool/analyst boundary and the gate write
    # them; a resumed run re-seeds the collector from them.
    data_quality_ingested_evidence: NotRequired[
        Annotated[list, "Serialized optional EvidenceRecord dicts captured from vendors"]
    ]
    data_quality_source_attempt_envelopes: NotRequired[
        Annotated[list, "Versioned attempt envelopes with explicit attempt_index"]
    ]
    data_quality_ingest_metadata: NotRequired[
        Annotated[dict, "Ingest run identity: symbol, target_date, next_attempt_index, schema_version"]
    ]
    data_quality_not_attempted_feeds: NotRequired[
        Annotated[list, "Configured-but-unoperated feeds (explicit, NOT attempts)"]
    ]
    data_quality_dropped_evidence_ids: NotRequired[
        Annotated[list, "Explicit tombstones for excluded records; never resurrected"]
    ]
    # ADR-010: typed origin/date-role/unit semantics per evidence ID (kept OUT of
    # the locked 20-field record). Enables exact-claim validation against genuine
    # observation/filed/published/retrieved roles. Declared so LangGraph persists
    # it across checkpoints (an undeclared key would be silently dropped).
    data_quality_origin_metadata: NotRequired[
        Annotated[dict, "evidence_id -> typed origin metadata (date roles + unit)"]
    ]
    # ADR-010 (Defect-1 amendment): evidence ids whose origin metadata was captured
    # more than once with DIFFERENT values (or lost trust). Such ids are failed
    # closed by the claim validator / output boundary (unverifiable) instead of
    # trusting a first/last-wins origin. Declared so LangGraph persists it across
    # checkpoints (an undeclared key would be silently dropped) and a resumed run
    # keeps the ambiguity rather than re-trusting a derived replacement.
    data_quality_origin_conflicted_ids: NotRequired[
        Annotated[list, "evidence ids with a conflicting/lost-trust origin (unverifiable)"]
    ]
    # ADR-011: versioned, JSON-safe audit of the deterministic degraded-run
    # confidence cap. One entry per boundary identity (debate turn / evaluator
    # round / manager / trader / portfolio / report), carrying the raw value, the
    # effective value, capped flag, reason and policy version. Declared so
    # LangGraph persists it across checkpoints (an undeclared key would be
    # silently dropped) and a resumed run recomputes the same effective values.
    confidence_cap_audit: NotRequired[
        Annotated[list, "Versioned confidence-cap audit entries (raw + effective)"]
    ]
    # ADR-011: the RAW readable debate text before confidence capping, keyed by
    # ``"<Speaker>:<turn_index>"``. NON-AUTHORITATIVE: audit only, never used in a
    # trusted prompt/history/report body or in usage accounting.
    confidence_cap_raw_transcript: NotRequired[
        Annotated[dict, "Non-authoritative raw debate text (pre-cap) keyed by turn"]
    ]

    # researcher team discussion step
    investment_debate_state: Annotated[
        InvestDebateState, "Current state of the debate on if to invest or not"
    ]
    # Phase 3B: deterministic run-level LLM usage {calls, tokens, seconds,
    # estimated, provenance, failed_calls, clock, transport_attempts}, updated
    # by every Bull/Bear researcher call and read by the Debate Evaluator to
    # enforce the budget/reserve rules. Plain JSON-safe.
    debate_usage: NotRequired[
        Annotated[dict, "Run-level usage {calls, tokens, seconds, estimated}"]
    ]
    # Optional sanitized append-only failure ledger path for aborted debate
    # invocations. Records only allow-listed fields (no prompts/bodies/auth) and
    # never advances a failed checkpoint (cross-resume accounting is NOT solved).
    debate_failure_log_path: NotRequired[
        Annotated[str, "Optional JSONL failure-ledger path for aborted debate calls"]
    ]
    investment_plan: Annotated[str, "Plan generated by the Analyst"]
    # ADR-009: set when the Research Manager summary was skipped to protect the
    # reserved summary budget (deterministic auditable fallback; no model call).
    summary_budget_denied: NotRequired[
        Annotated[bool, "True when the summary was skipped to protect the reserve"]
    ]
    summary_budget_denied_reason: NotRequired[
        Annotated[str, "Auditable constant reason when summary_budget_denied"]
    ]
    # Phase 3B: the deterministic Debate Evaluator's serialized RoutingDecision
    # plus the associated RoundMetrics, written after each complete Bull+Bear
    # round. Plain JSON-safe (list sentinel).
    debate_termination_decision: NotRequired[
        Annotated[dict, "Serialized RoutingDecision dict (route, stop_reason, trace)"]
    ]

    trader_investment_plan: Annotated[str, "Plan generated by the Trader"]

    # risk management team discussion step
    risk_debate_state: Annotated[
        RiskDebateState, "Current state of the debate on evaluating risk"
    ]
    final_trade_decision: Annotated[str, "Final decision made by the Risk Analysts"]
    past_context: Annotated[str, "Memory log context injected at run start (same-ticker decisions + cross-ticker lessons)"]
    portfolio_context: Annotated[str, "Caller-supplied holdings and cash, rendered at run start; empty when not provided"]
