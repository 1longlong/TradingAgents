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

from tradingagents.debate.claims import (
    canonical_claim_key,
    extract_standalone_typed_claims_indexed,
    parse_strict_typed_claim_payload,
)
from tradingagents.debate.models import (
    ClaimEvidenceLink,
    ClaimRecord,
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
    "For EVERY exact numeric claim you make (a specific figure with a specific "
    "date and unit), add a typed field so each can be checked against the cited "
    "evidence: claim=metric=<name>|role=<observation_date|target_date|"
    "availability_date|filed_at|published_at>|date=<YYYY-MM-DD>|value=<number>|"
    "unit=<USD|shares|percent>|currency=<USD|... when the unit is money>|"
    "evidence=<evidenceID>. A turn making several exact claims MUST emit one "
    "repeated claim= field PER claim (do not combine them); each is validated "
    "separately and any mismatch is rejected. The date must match that role in "
    "the cited evidence exactly; do not restate a figure under a wrong date or "
    "unit.\n"
    "Example: DEBATE_METADATA: stance=Buy; confidence=0.7; "
    "cited=evid/1,evid/2; conflicts=c1; "
    "new_claims=growing revenue|evid/1; questions=is the margin durable?"
)

# The optional conflict-assignment field. Present only when a turn wants to
# assert/resolve/escalate a tracked conflict; a turn without it records no
# conflict (fail closed on missing metadata). Each assertion is a pipe-delimited
# key=value set; multiple assertions are split on ``;``.
CONFLICT_ASSERTION_FIELD = "conflict_a"

# The optional typed exact-claim field (ADR-010). A single pipe-delimited
# key=value set, e.g. ``claim=metric=close|role=observation_date|date=2026-11-04|
# value=200.13|unit=USD|evidence=run/.../0``. Absent -> no typed exact claim
# (the legacy/qualitative path). A malformed claim is dropped (fail closed),
# never guessed.
EXACT_CLAIM_FIELD = "claim"


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
    EXACT_CLAIM_FIELD,
    "claims",
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


# Fields a turn MAY repeat to carry MULTIPLE values. ``claim`` is the typed exact
# claim; a turn may assert more than one (e.g. a date and a value for two
# metrics). Repeated values are collected into a list under the field name; other
# fields keep last-wins semantics.
_REPEATABLE_FIELDS = frozenset({EXACT_CLAIM_FIELD, "claims"})


def _parse_marker(marker: str) -> dict[str, Any] | None:
    """Parse the ``DEBATE_METADATA`` marker into key/value fields.

    A repeatable field (``claim`` / ``claims``) accumulates EVERY occurrence into
    a list so a turn can carry multiple typed exact claims — one correct claim can
    never stand in for a second wrong claim on the same ID.
    """
    if not marker:
        return None
    body = marker[len(_MARKER_START):].strip().strip("`").strip()
    fields: dict[str, Any] = {}
    for part in _split_marker_fields(body):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key in _REPEATABLE_FIELDS:
            existing = fields.get(key)
            if isinstance(existing, list):
                existing.append(value)
            elif existing is not None:
                fields[key] = [existing, value]
            else:
                fields[key] = [value]
        else:
            fields[key] = value
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


# A single ``claims=`` value may carry several pipe-delimited claims separated by
# a double-semicolon (``;;``) — a separator that never appears inside a single
# claim's ``key=value|...`` form — so a turn can assert multiple exact claims in
# one field. Repeated ``claim=`` fields are the primary multi-claim channel.
_CLAIM_CHUNK_SEP = "||"


def _split_claim_chunks(raw: str) -> list[str]:
    """Split one typed-claim field value into per-claim pipe-delimited chunks."""
    text = str(raw or "").strip()
    if not text:
        return []
    return [chunk.strip() for chunk in text.split(_CLAIM_CHUNK_SEP) if chunk.strip()]


def _parse_exact_claim(raw: str) -> ClaimRecord | None:
    """Parse the pipe-delimited typed ``claim`` field into a :class:`ClaimRecord`.

    Uses the SHARED strict grammar (:func:`parse_strict_typed_claim_payload`) so a
    canonical-marker claim cannot be laundered with looser rules than a standalone
    line: a malformed/conflicting/contradictory-alias field yields ``None``
    (unparseable, never guessed). An untyped/empty chunk is also ``None``.
    """
    raw = (raw or "").strip().strip("`").strip()
    if not raw:
        return None
    return parse_strict_typed_claim_payload(raw)


# Conservative inline exact-prose scanner (ADR-010). Only recognizes the common
# "date + number + unit (+ cited id)" pattern; it is explicitly NOT a proof of
# arbitrary natural-language semantics. A prose exact claim it cannot parse is
# simply not extracted (stays unverified qualitative prose).
_PROSE_CLAIM_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})[^\n.;]{0,40}?"
    r"(?P<value>[-+]?\d[\d,]*\.?\d*)\s*"
    r"(?P<unit>USD|usd|shares?|percent|%|million|mn|bn)"
    r"(?P<tail>[^\n.;]*?)(?P<id>[\w.\-+/@]+/[\w.\-+/@]+)"
)

_UNIT_ALIASES = {
    "usd": ("USD", "USD"),
    "us$": ("USD", "USD"),
    "shares": ("shares", ""),
    "share": ("shares", ""),
    "percent": ("percent", ""),
    "%": ("percent", ""),
    "million": ("USD", "USD"),
    "mn": ("USD", "USD"),
    "bn": ("USD", "USD"),
}
_PROSE_SCALE = {
    "million": "1000000",
    "mn": "1000000",
    "bn": "1000000000",
}


def _scan_prose_exact_claim(content: str) -> list[ClaimRecord]:
    """Extract conservative inline exact prose claims (each with its cited id)."""
    text = _strip_marker(content or "")
    claims: list[ClaimRecord] = []
    for match in _PROSE_CLAIM_RE.finditer(text):
        unit_raw = match.group("unit").strip().lower()
        unit, currency = _UNIT_ALIASES.get(unit_raw, (match.group("unit"), ""))
        scale = _PROSE_SCALE.get(unit_raw)
        claims.append(
            ClaimRecord(
                evidence_ids=[match.group("id").strip()],
                metric="",
                # A prose claim is about the observation the number describes;
                # the validator rejects it if the cited record's role can't prove
                # it. Default to the observation role.
                date_role="observation_date",
                date=match.group("date").strip(),
                value=match.group("value").replace(",", ""),
                unit=unit,
                currency=currency,
                value_scale=scale,
            )
        )
    return claims


def _strip_marker(content: str) -> str:
    """Everything before the ``DEBATE_METADATA`` marker (readable prose only)."""
    if not content:
        return ""
    idx = content.find(_MARKER_START)
    return content[:idx] if idx >= 0 else content


def _merge_standalone_claims(
    marker_claims: list[ClaimRecord], content: str, *, marker_unparseable: int = 0
) -> tuple[list[ClaimRecord], int, int]:
    """Union marker claims with standalone typed ``claim=`` lines (ADR-010 amend).

    Returns ``(exact_claims, standalone_found, unparseable)``. Marker claims are
    kept first and in order; a standalone claim is appended UNLESS it is the SAME
    canonical claim as one already collected (dedupe by :func:`canonical_claim_key`
    only). Marker presence NEVER hides an outside claim: both are collected. The
    counts are honest coverage (``standalone_found`` counts standalone typed lines
    seen, ``unparseable`` counts typed-looking lines that failed strict parsing —
    standalone OR canonical-marker), so a malformed canonical claim surfaces too.
    """
    extraction = extract_standalone_typed_claims_indexed(_strip_marker(content))[0]
    merged: list[ClaimRecord] = list(marker_claims)
    seen = {canonical_claim_key(c) for c in merged}
    for claim in extraction.records:
        key = canonical_claim_key(claim)
        if key in seen:
            continue
        seen.add(key)
        merged.append(claim)
    return (merged, extraction.found, len(extraction.unparseable) + marker_unparseable)


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
            # ADR-010: explicit typed ``claim``/``claims`` fields are the
            # authoritative exact claims. A turn may carry MULTIPLE; every one is
            # parsed so one correct claim cannot stand in for a second wrong one.
            # When no typed claim field is present, fall back to the conservative
            # inline prose scan.
            exact_claims: list[ClaimRecord] = []
            raw_claims: list[str] = []
            for key in (EXACT_CLAIM_FIELD, "claims"):
                value = fields.get(key)
                if isinstance(value, list):
                    raw_claims.extend(value)
                elif value is not None:
                    raw_claims.append(value)
            marker_unparseable = 0
            if raw_claims:
                for raw in raw_claims:
                    for chunk in _split_claim_chunks(raw):
                        typed = _parse_exact_claim(chunk)
                        if typed is not None:
                            exact_claims.append(typed)
                        else:
                            # A malformed/conflicting canonical claim is surfaced
                            # (never laundered into a trusted claim).
                            marker_unparseable += 1
            else:
                exact_claims = _scan_prose_exact_claim(content)
            # ADR-010 amendment: a standalone typed ``claim=`` line the model wrote
            # OUTSIDE the marker (before/after/no-marker) is recovered into the SAME
            # exact-claim validation. Marker claims are kept; an outside claim is
            # never hidden because the marker is present.
            exact_claims, standalone_found, unparseable = _merge_standalone_claims(
                exact_claims, content, marker_unparseable=marker_unparseable
            )
            status = (
                MetadataParseStatus.OK
                if confidence is not None and unparseable == 0
                else MetadataParseStatus.PARTIAL
            )
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
                metadata_parse_status=status,
                exact_claims=exact_claims,
                standalone_typed_claim_count=standalone_found,
                unparsed_typed_claim_count=unparseable,
            )

    # Fallback heuristic: recover stance + cited IDs from prose only. Common
    # inline exact claims are still extracted conservatively (ADR-010) so a wrong
    # date/value/unit in prose can be caught, but they never fabricate a typed
    # claim the text does not contain.
    stance = _extract_stance(content)
    if stance is not None:
        exact_claims, standalone_found, unparseable = _merge_standalone_claims(
            _scan_prose_exact_claim(content), content
        )
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
            exact_claims=exact_claims,
            standalone_typed_claim_count=standalone_found,
            unparsed_typed_claim_count=unparseable,
        )

    # Nothing recoverable -> failed turn, preserved text, zero new evidence.
    # ADR-010 amendment: typed-looking standalone lines are STILL surfaced (never
    # silently dropped) even when no stance parses, so the failure branch cannot
    # hide an admitted/unparseable typed claim from the coverage diagnostics.
    exact_claims, standalone_found, unparseable = _merge_standalone_claims(
        _scan_prose_exact_claim(content), content
    )
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
        exact_claims=exact_claims,
        standalone_typed_claim_count=standalone_found,
        unparsed_typed_claim_count=unparseable,
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
    """Build a turn with metadata marked failed, preserving the readable text.

    ADR-010 amendment: standalone typed ``claim=`` lines are still recovered (into
    the same exact-claim validation) and their coverage counts surfaced, so a
    failed parse never silently drops a typed-looking claim.
    """
    exact_claims, standalone_found, unparseable = _merge_standalone_claims([], content)
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
        exact_claims=exact_claims,
        standalone_typed_claim_count=standalone_found,
        unparsed_typed_claim_count=unparseable,
    )
