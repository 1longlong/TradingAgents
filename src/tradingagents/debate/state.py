"""Debate-state mutation helpers shared by the researchers and the evaluator.

Both Bull and Bear researchers must append a :class:`DebateTurn` and its
structured metadata to the ``investment_debate_state`` while keeping the
existing readable-argument fields (``history``, ``bull_history``,
``bear_history``, ``current_response``, ``count``) intact for backward
compatibility and the report writers.

These helpers operate purely on JSON-safe dicts (the serialized forms of the
models) so the resulting state survives LangGraph checkpointing.
"""

from __future__ import annotations

from typing import Any

from tradingagents.debate.models import DebateTurn
from tradingagents.debate.turn import extract_marker


def append_debate_turn(
    investment_debate_state: dict[str, Any],
    turn: DebateTurn,
) -> dict[str, Any]:
    """Return the updated ``investment_debate_state`` dict after appending a turn.

    Appends the serialized turn to ``turns``, folds every cited evidence ID into
    ``previously_cited_evidence_ids`` (deduped, stable order), increments the
    ``count``, and updates the readable-history fields exactly as the legacy
    researcher node did. Unknown Phase 3B auxiliary fields (conflicts, stances,
    budget, round_metrics, no_new_evidence_streak, metadata_parse_failed_count)
    are preserved.
    """
    state = dict(investment_debate_state or {})
    speaker = turn.speaker
    argument = argument_content(speaker, turn.content)

    previous_cited = list(state.get("previously_cited_evidence_ids") or [])
    for evidence_id in turn.cited_evidence_ids:
        if evidence_id and evidence_id not in previous_cited:
            previous_cited.append(evidence_id)

    turns = list(state.get("turns") or [])
    turns.append(turn.to_dict())

    metadata_failed = int(state.get("metadata_parse_failed_count") or 0)
    if turn.metadata_parse_status.value == "failed":
        metadata_failed += 1

    history = str(state.get("history", "") or "")
    bull_history = str(state.get("bull_history", "") or "")
    bear_history = str(state.get("bear_history", "") or "")
    count = int(state.get("count") or 0) + 1

    if speaker == "Bull":
        bull_history = (bull_history + "\n" + argument).strip()
    else:
        bear_history = (bear_history + "\n" + argument).strip()

    new_state = dict(state)
    new_state["turns"] = turns
    new_state["previously_cited_evidence_ids"] = previous_cited
    new_state["metadata_parse_failed_count"] = metadata_failed
    new_state["history"] = (history + "\n" + argument).strip()
    new_state["bull_history"] = bull_history
    new_state["bear_history"] = bear_history
    new_state["current_response"] = argument
    new_state["count"] = count
    return new_state


def argument_content(speaker: str, content: str) -> str:
    """The readable argument string, prefixed with the speaker label.

    The structured ``DEBATE_METADATA`` marker is stripped so history and any
    report never carry it.
    """
    label = "Bull Analyst" if speaker == "Bull" else "Bear Analyst"
    marker = extract_marker(content)
    clean = content
    if marker:
        clean = content[: content.find(marker)].rstrip()
    return f"{label}: {clean}".rstrip()
