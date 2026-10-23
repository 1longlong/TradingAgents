"""Structured debate-turn metadata extraction for Phase 3B.

Each Bull/Bear turn must retain its readable argument (a string) *and* produce
structured metadata: stance in the five-tier scale, confidence in ``[0, 1]``,
cited evidence IDs (restricted to the gate/evidence manifest), addressed
conflict IDs, new claims mapped to evidence IDs, and unresolved questions.

The pattern mirrors the repository's structured-output convention: the
researcher is asked (via a compact, appended instruction) to end its single
response with a parseable ``DEBATE_METADATA`` marker. That marker is parsed
deterministically with exactly one LLM call — no separate extraction pass and no
extra cost. When the marker is absent or malformed, a best-effort prose
heuristic is used; if that also cannot recover a stance, the turn is marked
``metadata_parse_failed`` and contributes zero new valid evidence. A parse
failure can never extend the debate.
"""

from __future__ import annotations

import re
from typing import Any

from tradingagents.debate.models import (
    ClaimEvidenceLink,
    ConflictAction,
    ConflictAssertion,
    ConflictKind,
    ConflictSeverity,
    DebateTurn,
    MetadataParseStatus,
    Stance,
)

# Evidence IDs cited in the observable prose of a turn. This regex is
# deliberately conservative: an ID looks like ``run/.../metric/0`` (slash-path
# token), possibly with an exchange suffix.
_EVIDENCE_ID_RE = re.compile(r"(?:^|[\s,\[\(])(\S+/\S+)(?=[\s,\]\)]|[.,;:]|$)")
_EVIDENCE_ID_SINGLE_RE = re.compile(r"\b([\w.\-+/@]{3,})\b")

_STANCE_WORDS: dict[str, Stance] = {
    "sell": Stance.SELL,
    "underweight": Stance.UNDERWEIGHT,
    "hold": Stance.HOLD,
    "overweight": Stance.OVERWEIGHT,
    "buy": Stance.BUY,
}

# Marker block the researcher appends. Parseable and unambiguous.
_MARKER_START = "DEBATE_METADATA:"

# Compact appended instruction asking the model to end with the marker. Kept
# out of the main prompt so the readable argument stays unchanged in shape.
METADATA_INSTRUCTION = (
    "\n\nAfter your argument, on a new line, add this single machine-parseable "
    "line:\n"
    "DEBATE_METADATA: stance=<Sell|Underweight|Hold|Overweight|Buy>; "
    "confidence=<0.0..1.0>; cited=<comma-separated evidence IDs, only ones above>; "
    "conflicts=<comma-separated conflict IDs>; "

    "new_claims=<claim|evidenceID; claim2|evidenceID2>; "
    "questions=<question; question2>\n"
    "Example: DEBATE_METADATA: stance=Buy; confidence=0.7; "
    "cited=evid/1,evid/2; conflicts=c1; "
    "new_claims=growing revenue|evid/1; questions=is the margin durable?"
)

# The optional conflict-assignment field. Present only when a turn wants to
# assert/resolve/escalate a tracked conflict; a turn without it records no
# conflict (fail closed on missing metadata). Each assertion is a pipe-delimited
# key=value set; multiple assertions are split on ``;``.
CONFLICT_ASSERTION_FIELD = "conflict_a"


def _extract_evidence_ids(text: str) -> list[str]:
    """Pull evidence-looking ID tokens from prose (deduped, stable order)."""
    found: list[str] = []
    for match in _EVIDENCE_ID_RE.finditer(text or ""):
        token = match.group(1).strip()
        if token and token not in found:
            found.append(token)
    return found


def _extract_stance(text: str) -> Stance | None:
    lowered = (text or "").lower()
    for label, stance in _STANCE_WORDS.items():
        if re.search(rf"\b{label}\b", lowered):
            return stance
    return None


_FIELD_KEYS = (
    "stance",
    "confidence",
    "cited",
    "conflicts",
    "new_claims",
    "questions",
    CONFLICT_ASSERTION_FIELD,
)


def _is_field_start(token: str) -> bool:
    """True iff ``token`` begins a new field (``key=...``) rather than a value
    continuation. ``new_claims`` and ``questions`` legitimately contain ``;``, so
    a bare ``;`` is only a real field boundary when it precedes a known key."""
    stripped = token.strip().lower()
    return any(stripped == f"{key}" or stripped.startswith(f"{key}=") for key in _FIELD_KEYS)


def _split_marker_fields(body: str) -> list[str]:
    """Split the marker body into ``key=...`` field chunks.

    ``;`` separates fields, but ``new_claims`` (``claim|evid; claim2|evid2``) and
    ``questions`` (``q; q2``) intentionally contain ``;`` inside their values, so
    we only treat ``;`` as a boundary when the chunk that follows starts a known
    field. This keeps the documented single-marker format parseable.
    """
    raw_tokens = [t for t in (body or "").split(";") if t.strip()]
    fields: list[str] = []
    current: list[str] = []
    for token in raw_tokens:
        if current and _is_field_start(token):
            fields.append(";".join(current))
            current = [token]
        else:
            current.append(token)
    if current:
        fields.append(";".join(current))
    return [f.strip() for f in fields if f.strip()]


def _parse_marker(marker: str) -> dict[str, Any] | None:
    """Parse the ``DEBATE_METADATA`` marker into key/value fields."""
    if not marker:
        return None
    body = marker[len(_MARKER_START):].strip().strip("`").strip()
    fields: dict[str, Any] = {}
    for part in _split_marker_fields(body):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        fields[key.strip().lower()] = value.strip()
    return fields


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _parse_new_claims(value: str) -> list[ClaimEvidenceLink]:
    """Parse ``claim|evidenceID; claim2|evidenceID2`` into explicit links.

    The ``claim|evidenceID`` form is the authoritative claim-to-evidence
    linkage (rule 3). A claim with no ``|evidenceID`` part still appears as a
    new claim string, but with an empty ``evidence_ids`` set, so it can never
    count as new valid evidence. This enforces "a new claim must explicitly
    link to a valid evidence ID".
    """
    links: list[ClaimEvidenceLink] = []
    for pair in (value or "").split(";"):
        pair = pair.strip()
        if not pair:
            continue
        claim, _, evidence = pair.partition("|")
        claim = claim.strip()
        evidence_ids = [eid.strip() for eid in evidence.split(",") if eid.strip()]
        links.append(ClaimEvidenceLink(claim=claim, evidence_ids=evidence_ids))
    return links


def _parse_confidence(value: str) -> float | None:
    if value is None:
        return None
    text = value.strip()
    try:
        result = float(text)
    except ValueError:
        return None
    if result != result or result < 0.0 or result > 1.0:
        return None
    return result


def _parse_conflict_assertion(raw: str) -> ConflictAssertion | None:
    """Parse a single ``|``-delimited key=value conflict assertion.

    Recognised keys (all optional except ``action``): ``action``, ``id``,
    ``kind``, ``severity``, ``topic``, ``bull``, ``bear``, ``evidence``,
    ``reason``. An empty or action-less chunk yields ``None`` (fail closed), so
    a malformed assertion is dropped rather than guessed — the tracker records
    nothing for it. ``evidence`` is a comma-separated ID set.
    """
    raw = (raw or "").strip().strip("`").strip()
    if not raw:
        return None
    fields: dict[str, str] = {}
    for pair in raw.split("|"):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            fields[key] = value
    action_raw = fields.get("action", "").strip().lower()
    if not action_raw:
        return None
    try:
        action = ConflictAction(action_raw)
    except ValueError:
        return None
    try:
        kind = ConflictKind(fields.get("kind", ConflictKind.INTERPRETIVE.value).strip().lower())
    except ValueError:
        kind = ConflictKind.INTERPRETIVE
    try:
        severity = ConflictSeverity(
            fields.get("severity", ConflictSeverity.MAJOR.value).strip().lower()
        )
    except ValueError:
        severity = ConflictSeverity.MAJOR
    evidence_ids = [eid.strip() for eid in fields.get("evidence", "").split(",") if eid.strip()]
    return ConflictAssertion(
        action=action,
        conflict_id=fields.get("id", ""),
        topic=fields.get("topic", ""),
        bull_claim=fields.get("bull", ""),
        bear_claim=fields.get("bear", ""),
        kind=kind,
        severity=severity,
        evidence_ids=evidence_ids,
        reason=fields.get("reason", ""),
    )


def _parse_conflict_assertions(value: str) -> list[ConflictAssertion]:
    """Parse the ``conflict_a`` field into a list of :class:`ConflictAssertion`.

    Multiple assertions are split on ``;`` (each is a ``|``-delimited key=value
    set). Any malformed chunk is dropped; a turn with no assertion field (or an
    empty value) yields an empty list — the fail-closed "no metadata, no
    conflict" path.
    """
    if not value or not value.strip():
        return []
    result: list[ConflictAssertion] = []
    for chunk in str(value).split(";"):
        assertion = _parse_conflict_assertion(chunk)
        if assertion is not None:
            result.append(assertion)
    return result


def parse_turn_metadata(*, speaker: str, content: str) -> DebateTurn:
    """Deterministically extract a :class:`DebateTurn` from one researcher turn.

    Resolution order (single LLM call, no extra cost):

    1. Parse the ``DEBATE_METADATA`` marker the model was asked to append. When
       it yields a valid stance, the structured fields are used verbatim.
    2. Otherwise fall back to a best-effort prose heuristic (stance + cited
       IDs recovered from the text). This heuristic never fabricates new
       evidence: it has no ``new_claims`` link, so it never counts as new valid
       evidence.
    3. If neither recovers a stance, the turn is marked
       ``metadata_parse_failed`` with zero new claims -> zero new evidence.

    The readable ``content`` is always preserved exactly. Conflict assertions
    are parsed **only** from the structured ``conflict_a`` field (never from
    prose), so a prose-only turn records no conflict.
    """
    marker = extract_marker(content)
    fields = _parse_marker(marker) if marker else None

    if fields and "stance" in fields:
        stance = _normalize_stance(fields.get("stance"))
        if stance is not None:
            confidence = _parse_confidence(fields.get("confidence"))
            cited = _split_csv(fields.get("cited", ""))
            conflicts = _split_csv(fields.get("conflicts", ""))
            claim_links = _parse_new_claims(fields.get("new_claims", ""))
            new_claims = [link.claim for link in claim_links if link.claim]
            questions = [q.strip() for q in fields.get("questions", "").split(";") if q.strip()]
            conflict_assertions = _parse_conflict_assertions(fields.get(CONFLICT_ASSERTION_FIELD, ""))
            return DebateTurn(
                speaker=speaker,
                content=content,
                stance=stance,
                confidence=confidence if confidence is not None else 0.0,
                cited_evidence_ids=cited,
                addressed_conflict_ids=conflicts,
                new_claims=new_claims,
                claim_evidence_links=claim_links,
                unresolved_questions=questions,
                conflict_assertions=conflict_assertions,
                metadata_parse_status=(
                    MetadataParseStatus.OK
                    if confidence is not None
                    else MetadataParseStatus.PARTIAL
                ),
            )

    # Fallback heuristic: recover stance + cited IDs from prose only.
    stance = _extract_stance(content)
    if stance is not None:
        return DebateTurn(
            speaker=speaker,
            content=content,
            stance=stance,
            confidence=0.0,
            cited_evidence_ids=_extract_evidence_ids(content),
            addressed_conflict_ids=[],
            new_claims=[],
            unresolved_questions=[],
            metadata_parse_status=MetadataParseStatus.PARTIAL,
        )

    # Nothing recoverable -> failed turn, preserved text, zero new evidence.
    return DebateTurn(
        speaker=speaker,
        content=content,
        stance=Stance.HOLD,
        confidence=0.0,
        cited_evidence_ids=_extract_evidence_ids(content),
        addressed_conflict_ids=[],
        new_claims=[],
        unresolved_questions=[],
        metadata_parse_status=MetadataParseStatus.FAILED,
    )


def _normalize_stance(value: Any) -> Stance | None:
    if isinstance(value, Stance):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    return _STANCE_WORDS.get(text)


def extract_marker(content: str) -> str:
    """Return the ``DEBATE_METADATA`` marker substring, or ``""`` when absent."""
    if not content:
        return ""
    idx = content.find(_MARKER_START)
    if idx < 0:
        return ""
    return content[idx:]


def build_failed_turn(*, speaker: str, content: str, cited_ids: list[str] | None = None) -> DebateTurn:
    """Build a turn with metadata marked failed, preserving the readable text."""
    return DebateTurn(
        speaker=speaker,
        content=content,
        stance=Stance.HOLD,
        confidence=0.0,
        cited_evidence_ids=list(cited_ids or _extract_evidence_ids(content)),
        addressed_conflict_ids=[],
        new_claims=[],
        unresolved_questions=[],
        metadata_parse_status=MetadataParseStatus.FAILED,
    )
