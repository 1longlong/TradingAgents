"""Representative scripted fixtures for the Phase 4A comparison (scenarios D/E/F).

These are **pre-recorded / scripted fixture results** consumed by the pure
comparison runner. They never invoke an LLM or network. Each case provides the
*dynamic* policy config and the *fixed-round* ``max_debate_rounds``, and both
strategies are replayed over the identical evidence snapshot and scripted
Bull/Bear turns by :func:`~tradingagents.comparison.runner.replay_scripted_case`.

Scenario definitions (Phase 4A):

- **D — no new evidence** (:func:`case_no_new_evidence`): the snapshot has no
  HIGH/MEDIUM citable IDs, so both sides add no valid evidence each round. The
  dynamic policy stops early (``no_new_evidence``); the fixed baseline runs the
  full ``max_debate_rounds``.
- **E — new valid evidence extension** (:func:`case_new_evidence_extension`): a
  blocking interpretive conflict remains and a NEW HIGH/MEDIUM evidence ID
  appears mid-debate, so the dynamic policy *extends* the debate (consuming more
  rounds than the no-new-evidence path) to absorb the new evidence, while a
  block-capped fixed baseline would stop at its round count.
- **F — budget protection** (:func:`case_budget_protection`): budget is nearly
  exhausted, so the dynamic policy stops to guarantee the summary reserve and
  never exceed the hard call/token cap; the fixed-run replay honors the cap but
  is shown to consume far more budget than the reserved capacity allows.
- **G — input exhaustion** (:func:`case_input_exhaustion`): the scripted input
  runs out (2 rounds) before a `max_debate_rounds` cap of 5, and the evaluator
  still wants to continue. This is **not** a dynamic early stop; it records
  ``stop_reason == input_exhausted`` and ``early_stopped == False``, so a short
  scripted fixture is never mislabelled as a policy early stop.
"""

from __future__ import annotations

from typing import Any

from tradingagents.comparison.runner import ScriptedCase, ScriptedRound
from tradingagents.comparison.schemas import CaseIdentity
from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.models import (
    ClaimEvidenceLink,
    ConflictKind,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    DebateTurn,
    Stance,
)

# A shared policy version so every compared case is pinned to one policy.
POLICY_VERSION = "1.0"


def _identity(symbol: str, date: str, snapshot: str) -> CaseIdentity:
    return CaseIdentity(
        ticker=symbol,
        target_date=date,
        evidence_snapshot_id=snapshot,
        policy_version=POLICY_VERSION,
    )


def _config(
    *,
    enabled: bool = True,
    max_rounds: int = 3,
    max_calls: int = 1_000_000,
    max_tokens: int = 1_000_000,
    max_time: float = 600.0,
    reserved_summary_tokens: int = 4_000,
    reserved_summary_seconds: float = 90.0,
    next_round_estimate_tokens: int = 2_000,
    next_round_estimate_seconds: float = 60.0,
) -> DebateTerminationConfig:
    return DebateTerminationConfig.from_dict(
        {
            "enabled": enabled,
            "no_new_evidence_patience": 1,
            "stance_distance_threshold": 1.0,
            "confidence_delta_threshold": 0.25,
            "max_calls": max_calls,
            "max_tokens": max_tokens,
            "max_time": max_time,
            "reserved_summary_tokens": reserved_summary_tokens,
            "reserved_summary_seconds": reserved_summary_seconds,
            "next_round_estimate_tokens": next_round_estimate_tokens,
            "next_round_estimate_seconds": next_round_estimate_seconds,
            "max_debate_rounds": max_rounds,
        }
    )


def _turn(
    speaker: str,
    stance: Stance,
    confidence: float,
    *,
    cited: list[str] | None = None,
    claims: list[str] | None = None,
    links: list[ClaimEvidenceLink] | None = None,
) -> DebateTurn:
    return DebateTurn(
        speaker=speaker,
        content=f"{speaker} argument",
        stance=stance,
        confidence=confidence,
        cited_evidence_ids=list(cited or []),
        new_claims=list(claims or []),
        claim_evidence_links=list(links or []),
    )


def _blocking_conflict(conflict_id: str, topic: str) -> ConflictRecord:
    return ConflictRecord(
        conflict_id=conflict_id,
        topic=topic,
        bull_claim="bull",
        bear_claim="bear",
        kind=ConflictKind.INTERPRETIVE,
        severity=ConflictSeverity.CRITICAL,
        status=ConflictStatus.OPEN,
    )


def case_no_new_evidence() -> ScriptedCase:
    """Scenario D: snapshot has NO valid citable IDs; both sides add nothing."""
    # No HIGH/MEDIUM, on-or-before-target, linked evidence in the snapshot.
    evidence_records: list[dict[str, Any]] = [
        {
            "evidence_id": "2026-05-13/ABC/market/yfinance/close/0",
            "quality_status": "Low",
            "observed_at": "2026-05-13",
            "target_date": "2026-05-13",
            "value_raw": "1",
            "metric_name": "close",
            "unit_normalized": "",
        }
    ]
    rounds: list[ScriptedRound] = []
    for idx in range(1, 4):
        # Both sides cite the Low ID (never counts as valid new evidence).
        bull = _turn("Bull", Stance.HOLD, 0.5, cited=["2026-05-13/ABC/market/yfinance/close/0"])
        bear = _turn("Bear", Stance.HOLD, 0.5, cited=["2026-05-13/ABC/market/yfinance/close/0"])
        rounds.append(
            ScriptedRound(
                index=idx,
                bull=bull,
                bear=bear,
                calls=2,
                tokens=2000,
                seconds=30.0,
                estimated=True,
                gate_verdict="normal",
                quality_status="Low",
            )
        )
    return ScriptedCase(
        identity=_identity("ABC", "2026-05-13", "snapshot-D"),
        evidence_records=evidence_records,
        rounds=rounds,
        config=_config(max_rounds=3),
        target_date="2026-05-13",
    )


def case_new_evidence_extension() -> ScriptedCase:
    """Scenario E: HIGH/MEDIUM evidence appears mid-debate; dynamic extends."""
    # Two eligible IDs: one cited from round 1, one NEW in round 2.
    eligible = [
        "2026-05-13/XYZ/market/yfinance/close/0",
        "2026-05-13/XYZ/market/yfinance/volume/1",
    ]
    evidence_records: list[dict[str, Any]] = []
    for i, eid in enumerate(eligible):
        evidence_records.append(
            {
                "evidence_id": eid,
                "quality_status": "High",
                "observed_at": "2026-05-13",
                "target_date": "2026-05-13",
                "value_raw": str(i),
                "metric_name": "close" if i == 0 else "volume",
                "unit_normalized": "",
            }
        )
    # Round 1: only the close ID is linked; a blocking conflict remains open.
    r1_bull = _turn(
        "Bull", Stance.BUY, 0.7,
        cited=[eligible[0]], claims=["q1"],
        links=[ClaimEvidenceLink(claim="q1", evidence_ids=[eligible[0]])],
    )
    r1_bear = _turn("Bear", Stance.BUY, 0.65, cited=[eligible[0]], claims=["q1"],
                    links=[ClaimEvidenceLink(claim="q1", evidence_ids=[eligible[0]])])
    # Round 2: BOTH sides bring a NEW valid ID (volume/1) -> new evidence.
    r2_bull = _turn(
        "Bull", Stance.BUY, 0.8,
        cited=eligible, claims=["q1", "q2"],
        links=[ClaimEvidenceLink(claim="q2", evidence_ids=[eligible[1]])],
    )
    r2_bear = _turn(
        "Bear", Stance.BUY, 0.75,
        cited=eligible, claims=["q1", "q2"],
        links=[ClaimEvidenceLink(claim="q2", evidence_ids=[eligible[1]])],
    )
    # Round 3: no new ID (repetition) -> diminishing returns / consensus.
    r3_bull = _turn("Bull", Stance.BUY, 0.8, cited=eligible, claims=["q1", "q2"],
                    links=[ClaimEvidenceLink(claim="q2", evidence_ids=[eligible[1]])])
    r3_bear = _turn("Bear", Stance.BUY, 0.78, cited=eligible, claims=["q1", "q2"],
                    links=[ClaimEvidenceLink(claim="q2", evidence_ids=[eligible[1]])])
    conflict = _blocking_conflict("c-XYZ", "valuation")
    rounds = [
        ScriptedRound(1, r1_bull, r1_bear, calls=2, tokens=3000, seconds=40.0,
                      estimated=True, gate_verdict="normal", quality_status="High",
                      conflicts=[conflict]),
        ScriptedRound(2, r2_bull, r2_bear, calls=2, tokens=3000, seconds=40.0,
                      estimated=True, gate_verdict="normal", quality_status="High",
                      conflicts=[conflict]),
        ScriptedRound(3, r3_bull, r3_bear, calls=2, tokens=2500, seconds=35.0,
                      estimated=True, gate_verdict="normal", quality_status="High",
                      conflicts=[conflict]),
    ]
    return ScriptedCase(
        identity=_identity("XYZ", "2026-05-13", "snapshot-E"),
        evidence_records=evidence_records,
        rounds=rounds,
        config=_config(max_rounds=3),
        target_date="2026-05-13",
    )


def case_budget_protection() -> ScriptedCase:
    """Scenario F: budget nearly exhausted; dynamic stops to protect reserve.

    The config's hard ``max_calls``/``max_tokens`` are set just above what one
    round costs, and the summary reserve is significant. The dynamic policy
    stops on budget exhaustion before exceeding the hard cap or consuming the
    summary reserve; the fixed-run replay consumes every scripted round's usage
    (which the budget cannot sustain without exhausting the reserve).
    """
    # The hard token cap fits a single round plus the summary reserve, so a
    # *second* round would make the summary reserve impossible to guarantee
    # (rule 2). The dynamic policy stops after round 1; the fixed baseline runs
    # every round and blows past the cap.
    max_calls = 6
    max_tokens = 20_000
    max_time = 600.0
    reserved_summary_tokens = 8_000
    reserved_summary_seconds = 120.0
    next_round_estimate_tokens = 9_000
    next_round_estimate_seconds = 100.0

    eligible = ["2026-05-13/DEF/market/yfinance/close/0"]
    evidence_records = [
        {
            "evidence_id": eligible[0],
            "quality_status": "High",
            "observed_at": "2026-05-13",
            "target_date": "2026-05-13",
            "value_raw": "1",
            "metric_name": "close",
            "unit_normalized": "",
        }
    ]
    # Each round's usage approaches the hard cap quickly. A blocking conflict
    # remains open, so WITHOUT budget protection the dynamic policy would keep
    # continuing for new evidence (rule 6); the budget rule (rule 2) fires first
    # because the summary reserve can no longer be guaranteed.
    conflict = _blocking_conflict("c-DEF", "margin")
    rounds: list[ScriptedRound] = []
    for idx in range(1, 4):
        bull = _turn("Bull", Stance.BUY, 0.7, cited=eligible, claims=["q"],
                     links=[ClaimEvidenceLink(claim="q", evidence_ids=eligible)])
        bear = _turn("Bear", Stance.HOLD, 0.4, cited=eligible, claims=["q"],
                     links=[ClaimEvidenceLink(claim="q", evidence_ids=eligible)])
        rounds.append(
            ScriptedRound(
                index=idx,
                bull=bull,
                bear=bear,
                calls=2,
                tokens=9_000,  # per-round token spend (conservative next-est 9000)
                seconds=100.0,
                estimated=True,
                gate_verdict="degraded",
                quality_status="Medium",
                conflicts=[conflict],
            )
        )
    return ScriptedCase(
        identity=_identity("DEF", "2026-05-13", "snapshot-F"),
        evidence_records=evidence_records,
        rounds=rounds,
        config=_config(
            max_rounds=3,
            max_calls=max_calls,
            max_tokens=max_tokens,
            max_time=max_time,
            reserved_summary_tokens=reserved_summary_tokens,
            reserved_summary_seconds=reserved_summary_seconds,
            next_round_estimate_tokens=next_round_estimate_tokens,
            next_round_estimate_seconds=next_round_estimate_seconds,
        ),
        target_date="2026-05-13",
    )


def case_input_exhaustion() -> ScriptedCase:
    """Scenario G: scripted input runs out before the policy stops (NOT an early stop).

    Each scripted round brings a NEW High/Medium evidence ID and a blocking
    interpretive conflict stays open, so the dynamic policy (correctly) wants to
    CONTINUE. But the scripted input provides only 2 rounds while
    ``max_debate_rounds`` is 5. The replay therefore consumes all available
    rounds and records ``stop_reason == INPUT_EXHAUSTED_STOP_REASON`` with
    ``early_stopped == False`` — the policy made no termination decision, it
    simply ran out of scripted input. This is a fail-closed guard against a
    short scripted input being mislabelled as a dynamic-policy early stop.
    """
    eligible = ["2026-05-13/GHI/market/yfinance/close/0", "2026-05-13/GHI/market/yfinance/volume/1"]
    evidence_records: list[dict[str, Any]] = []
    for i, eid in enumerate(eligible):
        evidence_records.append(
            {
                "evidence_id": eid,
                "quality_status": "High",
                "observed_at": "2026-05-13",
                "target_date": "2026-05-13",
                "value_raw": str(i),
                "metric_name": "close" if i == 0 else "volume",
                "unit_normalized": "",
            }
        )
    conflict = _blocking_conflict("c-GHI", "growth")
    # Round 1 cites close/0; round 2 adds volume/1 -> a NEW valid ID each round,
    # so the evaluator returns CONTINUE (new evidence + open blocking conflict).
    rounds: list[ScriptedRound] = []
    for idx in range(1, 3):
        cited = eligible[:idx]
        linked = [ClaimEvidenceLink(claim="q", evidence_ids=[eligible[idx - 1]])]
        bull = _turn("Bull", Stance.BUY, 0.7, cited=cited, claims=["q"], links=linked)
        bear = _turn("Bear", Stance.HOLD, 0.4, cited=cited, claims=["q"], links=linked)
        rounds.append(
            ScriptedRound(
                index=idx,
                bull=bull,
                bear=bear,
                calls=2,
                tokens=2500,
                seconds=35.0,
                estimated=True,
                gate_verdict="normal",
                quality_status="High",
                conflicts=[conflict],
            )
        )
    return ScriptedCase(
        identity=_identity("GHI", "2026-05-13", "snapshot-G"),
        evidence_records=evidence_records,
        rounds=rounds,
        # The cap is HIGHER than the number of scripted rounds, so the policy
        # cannot itself "reach" the cap — it runs out of scripted input first.
        config=_config(max_rounds=5),
        target_date="2026-05-13",
    )


ALL_SCRIPTED_CASES = (
    case_no_new_evidence,
    case_new_evidence_extension,
    case_budget_protection,
)
