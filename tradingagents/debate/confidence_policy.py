"""Deterministic degraded-run confidence cap (ADR-011).

A degraded (not blocked) Data Quality Gate verdict restricts conviction. Before
this module that restriction was only a prompt instruction, so a ``DebateTurn``,
a decision schema, or free-text prose could still state a raw over-cap
confidence (e.g. ``0.95`` / ``95% confidence``) and that value could reach the
evaluator, the intermediate plans, the final decision, the report or the memory
log.

This module is the single pure, deterministic, LLM-free place that owns the
ceiling:

- :func:`current_trusted_verdict` reads the authoritative gate verdict through
  the fail-closed :func:`tradingagents.agents.utils.output_guard.effective_gate_verdict`.
  A missing/malformed/mismatched gate state is ``blocked``; the cap applies to a
  *trusted* (``normal`` / ``degraded``) verdict only. The verdict is **never**
  taken from a caller-supplied / state-supplied confidence audit value.
- :func:`cap_value` caps a valid numeric confidence on a ``degraded`` run at
  :data:`DEGRADED_CONFIDENCE_CAP`; a ``normal`` (or ``blocked``) run never
  changes a valid numeric value.
- :func:`apply_confidence_cap` returns a JSON-safe audit dict (raw value,
  effective value, whether it was capped, reason, policy/version and boundary
  identity) so the raw original is preserved in audit/quarantine only.
- :func:`rewrite_confidence_text` rewrites **only explicit confidence-labelled**
  numerics in prose to their effective value on a degraded run. An ordinary
  financial figure (a share count, return, margin, position size, price or date)
  is **never** treated as a confidence and remains byte-for-byte unchanged.

Confidence extraction is deliberately NARROW: a numeric token counts only when
it is an explicit confidence statement

- a **percent** token attached to a confidence label
  (``confidence: 95%`` / ``confidence of 95%`` / ``95% confidence``);
- a **fraction in ``[0, 1]``** attached to a confidence label
  (``confidence: 0.95`` / ``confidence of 0.62`` / ``0.62 confidence``).

A bare ``confidence: 95`` (no ``%``) is **outside** the approved fraction
contract and is not silently reinterpreted as ``95%``: it is rejected/quarantined
on a degraded run. There is no arbitrary "percent anywhere means confidence"
inference. The only unambiguous patterns are an explicit confidence label (a
prefix or suffix phrase), the ``DEBATE_METADATA`` ``confidence=`` field, and a
Markdown-wrapped label (``**Confidence:**``).

This is an engineering safety ceiling, NOT a calibrated probability, NOT an
accuracy claim and NOT production threshold tuning. The cap value 0.60 is an
approved policy constant (WANG Yiwen, 2026-11-11).

Cap comparison and rendering are separate, deterministic rules:

- **Cap decision** compares the *original finite value* against
  :data:`DEGRADED_CONFIDENCE_CAP` with a strict ``>`` using an exact ``Decimal``,
  so ``0.6000001`` genuinely exceeds the cap and is capped while ``0.60`` and any
  smaller valid value are unchanged.
- **Rendering** of a capped value into prose/number form is the constant cap
  (``0.6`` / ``60%``) and never feeds back into the decision.

NFKC safety: matching runs on the NFKC-normalized string, but NFKC can change
length (ligatures, circled digits). Edits are therefore applied by mapping each
normalized match index back to the ORIGINAL text via a per-character index map,
so a prefix whose length changed under NFKC never shifts an edit onto the wrong
bytes.

Repeated application is idempotent: an already capped text has no labelled token
above the cap, so a second pass rewrites nothing and adds no new entry.

ADR-011 amendment (2026-11-12) — structural token/sentence boundaries: a suffix
confidence value may not absorb a sentence-ending period (a numeric literal's
fractional part is all-or-nothing, so ``$204.38. Confidence`` never yields a
``38.`` candidate) and a sentence terminator (``. ! ? ;``) or currency-glued symbol
(``$``/``€``/``£``/``¥``) between the value and its label is a BOUNDARY, not a
connector. Soft vertical whitespace (``0.95\nconfidence``) still binds as a
genuine suffix. A bare ``204.38 confidence`` (no currency, no ``%``, value ``> 1``)
remains an INVALID labelled value and is quarantined — it is not blanket-exempted
as a "price"; only unambiguously currency-glued figures are excluded from being a
confidence candidate. Ordinary prices/dates remain byte-for-byte unchanged.
"""

from __future__ import annotations

import contextlib
import math
import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from tradingagents.agents.utils.output_guard import effective_gate_verdict

CONFIDENCE_POLICY_VERSION = "1.0"

# The approved degraded-run confidence ceiling. This is an engineering
# constraint; it is NOT a calibrated probability and NOT an accuracy claim.
DEGRADED_CONFIDENCE_CAP = 0.60

# The exact decimal form of the cap used for the strict comparison, so a value
# such as ``0.6000001`` is compared exactly and never misclassified by binary
# float rounding.
_CAP_DECIMAL = Decimal("0.60")

# Decimal places an effective value is rounded to for DISPLAY/number rendering
# only (never for the cap decision).
CONFIDENCE_DISPLAY_DECIMALS = 6

# Stable reason codes. They never embed a raw free-form string.
REASON_NOT_CAPPED = "within_cap"
REASON_CAPPED = "capped_to_degraded_ceiling"
REASON_NORMAL = "normal_verdict_unchanged"
REASON_BLOCKED = "blocked_verdict_unchanged"
REASON_INVALID = "invalid_numeric_rejected"

# The explicit marker an invalid/quarantined confidence token is replaced with on
# a degraded run, so a malformed/oversized/invalid numeric never remains an
# authoritative-looking confidence. The raw token is recorded in the audit only.
QUARANTINE_MARKER = "unknown (invalid confidence quarantined)"

_VERDICT_NORMAL = "normal"
_VERDICT_DEGRADED = "degraded"
_VERDICT_BLOCKED = "blocked"

# A categorical sentiment confidence is a LABEL, not a calibrated number. It is
# recognised only so callers can keep it distinct and clearly labelled; it is
# never converted to a numeric value.
CATEGORICAL_CONFIDENCE_LABELS: tuple[str, ...] = ("low", "medium", "high")

# ---------------------------------------------------------------------------
# Explicit confidence-label grammar (the ONLY things that may be capped)
# ---------------------------------------------------------------------------
#
# A confidence value is recognised only when a confidence LABEL is adjacent to
# the number, in one of these forms (NFKC-normalized):
#
#   - prefix label:  confidence: 95% | confidence of 0.95 | Confidence level - 1
#                    **Confidence:** 0.9 | confidence=0.95  (DEBATE_METADATA field)
#   - suffix label:  95% confidence | 0.95 confidence
#   - bare metadata: confidence=0.95 inside a DEBATE_METADATA marker
#
# An ordinary figure ("Revenue increased 95%", "margin 0.31", "200 shares",
# "close 200.13", "2026-05-04") is NOT adjacent to a confidence label and is left
# untouched.

# A confidence label optionally followed by a small set of connectors, then the
# numeric value. The percent sign is OPTIONAL here so the caller can decide
# whether a bare number is a fraction or an out-of-contract percentage.
#
# The label also accepts a QUOTED JSON key form (``"confidence": 0.95`` /
# ``'confidence': 0.95``) so a machine-readable confidence field is capped too.
_CONF_WORD = r"(?:confidence|confident|certain)"
_CONFIDENCE_LABEL = (
    r'(?:["\']?)'
    r"(?:\*\*|__|\*|_)?_CONF_WORD_(?:\s+(?:level|score|rating|is|of|at))?"
    r'(?:\*\*|__|\*|_)?(?:["\']?)'
    r"(?:\s*[:=]|(?<![\\w\"'])-\s*|(?<![\\w\"'])\s+)"
    r'(?:\*\*|__|\*|_)?'
)
_CONFIDENCE_LABEL = _CONFIDENCE_LABEL.replace("_CONF_WORD_", _CONF_WORD)

# A strict numeric literal: an optional sign, then ``123`` / ``123.4`` / ``.95``
# with an optional exponent. The FRACTIONAL PART is all-or-nothing: a trailing dot
# is only consumed when digits follow (``\d+(?:\.\d+)?``), so a sentence-ending
# period (``... 204.38. Confidence``) is NEVER absorbed into the literal. A bare
# ``123.`` therefore no longer matches as a confidence literal, which is what stops
# a sentence period from being read as a decimal point (ADR-011 amendment).
_NUM_LITERAL = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUM_LITERAL_FULL_RE = re.compile(r"^" + _NUM_LITERAL + r"$")

# A confidence literal may NOT begin in the middle of a larger financial/date
# token: it must not be immediately preceded by a digit, a decimal point, a
# thousands separator, a currency symbol glued to the digits (``$204.38``), a
# date/sign/path separator (``-`` ``/`` ``:`` — so ``2026-11-05`` / ``2026/11/05``
# never yields an ``05`` candidate) or any other word character. This is the LEFT
# token boundary that keeps ``$204.38`` / ``204.38`` / a date fragment out of the
# suffix grammar.
_NUM_LEFT_BOUNDARY = r"(?<![\w.,\-/:$€£¥])"

# Vertical/soft whitespace between a confidence value and its suffix label is a
# GENUINE connector (``0.95\nconfidence`` / ``0.95\r\nconfidence`` soft-wraps to
# the same claim). A sentence terminator (``. ! ? ;``) is a STRUCTURAL boundary,
# NOT a connector, so ``$204.38. Confidence`` never binds ``38.`` to
# ``Confidence``. Horizontal soft whitespace and at most ONE newline (CRLF-aware)
# are permitted between the value and the label.
_CONF_SOFT_GAP = r"[ \t]*\r?\n?[ \t]*"

# prefix: <label> <literal>[%]
_PREFIX_NUMERIC_RE = re.compile(
    _CONFIDENCE_LABEL + r"\s*(?P<num>" + _NUM_LITERAL + r")\s*(?P<pct>[%％])?",
    re.IGNORECASE,
)

# suffix: <literal>[%] <label>  (e.g. "95% confidence", "0.95 confidence level").
#
# The left boundary (:data:`_NUM_LEFT_BOUNDARY`) stops a numeric that is part of a
# larger money/date token from being read as a confidence; the gap between the
# value and the label is SOFT whitespace only (:data:`_CONF_SOFT_GAP`), so a
# sentence period (``$204.38. Confidence``) is a boundary, not a connector, while a
# soft line wrap (``0.95\nconfidence``) still binds.
_SUFFIX_NUMERIC_RE = re.compile(
    _NUM_LEFT_BOUNDARY
    + r"(?P<num>"
    + _NUM_LITERAL
    + r")(?P<pct>[%％])?"
    + _CONF_SOFT_GAP
    + r'(?:["\']?)(?:\*\*|__|\*|_)?'
    + _CONF_WORD
    + r"\b",
    re.IGNORECASE,
)

# A MALFORMED labelled confidence: the label is followed by a numeric-looking run
# that is not a clean full literal (e.g. ``confidence: 9e-1x`` or
# ``confidence: 0.9foo``). The WHOLE run is captured so it can be quarantined as
# one token (never split into ``9`` + ``e-1x`` debris). This must NOT match an
# ordinary figure elsewhere because it is anchored to the explicit label.
_MALFORMED_LABELLED_RE = re.compile(
    # A numeric-looking run that ends in a LETTER (e.g. ``9e-1x`` / ``0.9foo``) or
    # has an embedded letter before the terminator — a sentence period or a clean
    # trailing literal does NOT count as malformed.
    _CONFIDENCE_LABEL + r"\s*(?P<tok>[+-]?(?:\d|\.\d)[\w.+\-]*[A-Za-z_][\w.+\-]*)\s*(?P<pct>[%％])?",
    re.IGNORECASE,
)

# A labelled NON-numeric invalid token (confidence: NaN / inf / true / false /
# null / none) so the degraded path can quarantine it instead of leaving it
# authoritative.
_LABELLED_INVALID_RE = re.compile(
    _CONFIDENCE_LABEL + r"\s*(?P<word>nan|inf|infinity|true|false|null|none)\b",
    re.IGNORECASE,
)

# A categorical label (confidence: low / medium / high) — kept distinct.
_CATEGORICAL_RE = re.compile(
    _CONFIDENCE_LABEL + r"\s*(?P<label>low|medium|high)\b",
    re.IGNORECASE,
)


def is_valid_numeric_confidence(value: Any) -> bool:
    """True for a finite, non-bool number in ``[0, 1]``.

    A ``bool`` is explicitly rejected (``True`` / ``False`` are not
    confidences), as are ``NaN`` / ``inf`` / out-of-range / non-numeric values.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(number):
        return False
    return 0.0 <= number <= 1.0


def exceeds_cap(value: float) -> bool:
    """True when a valid numeric value is strictly greater than the cap.

    The comparison is exact (``Decimal`` of the float), so ``0.6000001`` exceeds
    ``0.60`` while ``0.60`` exactly does not. Callers must pass a valid value.
    """
    try:
        exact = Decimal(repr(float(value)))
    except (InvalidOperation, ValueError):
        return False
    return exact > _CAP_DECIMAL


def current_trusted_verdict(state: Mapping[str, Any] | Any) -> str:
    """The authoritative gate verdict, failing closed to ``blocked``.

    Delegates to the shared :func:`effective_gate_verdict` so this module and the
    router/report guard can never disagree about whether a run was blocked. The
    verdict is derived ONLY from the authoritative gate fields, never from a
    confidence-audit field a caller / legacy state might carry.
    """
    return effective_gate_verdict(state)


def cap_value(value: Any, verdict: str) -> float | None:
    """Return the effective (possibly capped) numeric confidence, or ``None``.

    ``None`` is returned when ``value`` is absent or not a valid numeric
    confidence, so a missing value stays missing (never a fabricated cap). A
    ``normal`` / ``blocked`` verdict leaves a valid value unchanged; a
    ``degraded`` verdict caps a value that genuinely exceeds the cap.
    """
    if value is None or not is_valid_numeric_confidence(value):
        return None
    if verdict == _VERDICT_DEGRADED and exceeds_cap(float(value)):
        return DEGRADED_CONFIDENCE_CAP
    return float(value)


def _reason_for(value: Any, verdict: str) -> str:
    if value is None or not is_valid_numeric_confidence(value):
        return REASON_INVALID
    if verdict == _VERDICT_BLOCKED:
        return REASON_BLOCKED
    if verdict == _VERDICT_DEGRADED:
        return REASON_CAPPED if exceeds_cap(float(value)) else REASON_NOT_CAPPED
    return REASON_NORMAL


def apply_confidence_cap(
    value: Any,
    verdict: str,
    *,
    source: str,
    boundary: str,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe audit entry and the effective value for one boundary.

    Returns ``{raw_value, effective_value, capped, reason, policy_version,
    boundary, source}``. ``raw_value`` is the ORIGINAL (unrounded) input and is
    ``None`` when the input is absent or invalid; a missing value never becomes a
    fabricated ``0.60``. ``capped`` is True only when a valid raw value genuinely
    exceeded the cap on a degraded run.

    ``previous`` is a *prior audit entry for the same boundary identity*. It may
    only SUPPRESS noise on a genuine same-value re-entry: if the new ``value`` is
    ``None``/missing but the prior entry recorded a valid raw, the prior raw is
    retained for provenance. It may **never** override a NEW actual model value,
    and it can **never** forge or raise the effective value: the effective value
    is always recomputed from the new ``value`` (when present) or the retained
    prior raw, and re-capped ethically. A forged/stale ``previous["raw_value"]``
    lower than the real new value is ignored — the real evidence wins.
    """
    actual_is_valid = is_valid_numeric_confidence(value)
    prior_raw = previous.get("raw_value") if isinstance(previous, Mapping) else None
    prior_is_valid = is_valid_numeric_confidence(prior_raw)

    if actual_is_valid:
        # A real model value is always authoritative; any ``previous`` is ignored
        # for the raw so a forged/stale audit entry cannot replace actual evidence.
        raw: Any = value
    elif value is None and prior_is_valid:
        # Provenance-only re-entry with NO new value: retain the prior raw.
        raw = prior_raw
    else:
        raw = value

    effective = cap_value(raw, verdict)
    capped = (
        is_valid_numeric_confidence(raw)
        and verdict == _VERDICT_DEGRADED
        and exceeds_cap(float(raw))
    )
    raw_json: float | None = float(raw) if is_valid_numeric_confidence(raw) else None
    return {
        "raw_value": raw_json,
        "effective_value": effective,
        "capped": capped,
        "reason": _reason_for(raw, verdict),
        "policy_version": CONFIDENCE_POLICY_VERSION,
        "boundary": boundary,
        "source": str(source),
    }


# ---------------------------------------------------------------------------
# NFKC text <-> original index mapping (NFKC can change length)
# ---------------------------------------------------------------------------


def _nfkc_with_index_map(text: str) -> tuple[str, list[int]]:
    """Return ``(nfkc_text, index_map)`` mapping each NFKC char to its ORIGINAL start.

    NFKC normalization is applied per original character and concatenated, so the
    resulting string equals ``unicodedata.normalize("NFKC", text)`` for the
    characters we care about while making the mapping exact. ``index_map[i]`` is
    the original offset where the NFKC character ``nfkc_text[i]`` began; a
    multi-char expansion (``ﬁ`` → ``fi``) maps every produced char to the single
    original char's start. An end offset maps to ``index_map[end-1] + 1`` so an
    edit never spills past the original character(s) it covers.
    """
    normalized_parts: list[str] = []
    index_map: list[int] = []
    for original_index, char in enumerate(text):
        decomposed = unicodedata.normalize("NFKC", char)
        for sub in decomposed:
            normalized_parts.append(sub)
            index_map.append(original_index)
    return "".join(normalized_parts), index_map


def _original_span(
    index_map: list[int], start: int, end: int, original_len: int
) -> tuple[int, int]:
    """Map an NFKC ``[start, end)`` span back to an original ``[start, end)``."""
    if start >= end or start >= len(index_map):
        return (original_len, original_len)
    first = index_map[start]
    last_norm = end - 1
    if last_norm >= len(index_map):
        last_norm = len(index_map) - 1
    last = index_map[last_norm]
    return (first, last + 1)


# ---------------------------------------------------------------------------
# Extraction of explicit confidence tokens
# ---------------------------------------------------------------------------


def _token_to_fraction(token_text: str, pct: bool) -> tuple[float | None, bool]:
    """Parse a FULL numeric literal to a fraction in ``[0, 1]``.

    Returns ``(value, valid)``. The whole literal must parse as a single finite
    number; a malformed suffix (``9e-1x``), an overflow (``1e309``), or a
    non-finite value is invalid, so the caller quarantines the WHOLE token rather
    than leaving a partial literal (e.g. ``9`` followed by ``e-1`` debris). A ``%``
    token is a percentage; a non-percent token is ONLY valid as a fraction in
    ``[0, 1]`` (``0.95`` / ``.95``) — a bare ``95`` without ``%`` is OUT of the
    approved contract (``valid=False``) and must not be read as ``95%``.
    """
    try:
        # ``float`` accepts leading-dot / exponent; ``Decimal`` rejects trailing
        # junk so a partially-numeric token is not silently truncated.
        Decimal(token_text)
        number = float(token_text)
    except (InvalidOperation, ValueError):
        return (None, False)
    if not math.isfinite(number):
        return (None, False)
    if pct:
        number = number / 100.0
    if not math.isfinite(number) or not (0.0 <= number <= 1.0):
        return (None, False)
    return (number, True)


def _confidence_tokens(norm: str) -> list[dict[str, Any]]:
    """All explicit confidence tokens in the NFKC ``norm`` string.

    Each token is ``{start, end, raw, pct, valid}`` (NFKC indices; ``end``
    exclusive and includes a trailing ``%`` when present). Only explicit
    confidence-labelled numbers are matched; a number anywhere else is ignored.
    """
    tokens: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(start < e and s < end for s, e in taken)

    # First pass: a malformed labelled run (``9e-1x`` / ``0.9foo``) quarantines the
    # WHOLE run so a partial literal cannot leak as ``0.6x`` debris.
    for match in _MALFORMED_LABELLED_RE.finditer(norm):
        raw = match.group("tok")
        # A clean full literal is handled by the strict regexes below; only a
        # genuinely malformed run is captured here.
        if _NUM_LITERAL_FULL_RE.fullmatch(raw):
            continue
        end = match.end("pct") if match.group("pct") else match.end("tok")
        start = match.start("tok")
        if _overlaps(start, end):
            continue
        tokens.append(
            {"start": start, "end": end, "raw": raw, "pct": bool(match.group("pct")), "valid": False}
        )
        taken.append((start, end))

    for regex in (_PREFIX_NUMERIC_RE, _SUFFIX_NUMERIC_RE):
        for match in regex.finditer(norm):
            start, end = match.start("num"), match.end("num")
            if match.group("pct"):
                end = match.end("pct")
            if _overlaps(start, end):
                continue
            raw = match.group("num")
            pct = bool(match.group("pct"))
            value, valid = _token_to_fraction(raw, pct)
            tokens.append(
                {"start": start, "end": end, "raw": raw, "pct": pct, "valid": valid}
            )
            taken.append((start, end))
    tokens.sort(key=lambda t: t["start"])
    return tokens


def scan_confidence_text(text: Any) -> dict[str, Any]:
    """Describe the explicit confidence statements in ``text`` (never mutates).

    Returns ``{numeric: [{raw, value, percent, valid}], categorical: [label],
    invalid: [raw]}``. Only confidence-LABELLED numerics are reported. An ordinary
    financial figure elsewhere in the text is not reported. ``categorical`` is the
    sentiment-style label(s) present (``low`` / ``medium`` / ``high``), reported
    separately and never treated as numeric. An absent confidence yields empty
    lists — never a fabricated value.
    """
    if not isinstance(text, str) or not text:
        return {"numeric": [], "categorical": [], "invalid": []}
    norm, _index_map = _nfkc_with_index_map(text)
    numeric = [
        {
            "raw": token["raw"],
            "value": _token_to_fraction(token["raw"], token["pct"])[0],
            "percent": token["pct"],
            "valid": token["valid"],
        }
        for token in _confidence_tokens(norm)
    ]
    categorical = [m.group("label").lower() for m in _CATEGORICAL_RE.finditer(norm)]
    invalid = [m.group("word").lower() for m in _LABELLED_INVALID_RE.finditer(norm)]
    return {"numeric": numeric, "categorical": categorical, "invalid": invalid}


def rewrite_confidence_text(
    text: Any, verdict: str
) -> tuple[str, list[dict[str, Any]]]:
    """Rewrite explicit confidence-labelled numerics to their effective value.

    On a ``degraded`` verdict every valid labelled confidence above the cap is
    replaced by its effective value in the same representation (``0.95`` → ``0.6``,
    ``95%`` → ``60%``); a valid value within the cap is left byte-for-byte
    unchanged. An INVALID labelled confidence (a bare ``confidence: 95`` without a
    ``%``, ``101%``, ``NaN`` / ``inf`` / ``true`` / out-of-range) is replaced by
    :data:`QUARANTINE_MARKER` and recorded as quarantined. Ordinary financial
    figures are never touched. On a ``normal`` / ``blocked`` verdict the text is
    returned unchanged.

    Returns ``(rewritten_text, audit_entries)``. An entry is recorded only for a
    token actually capped (``capped=True``) or quarantined
    (``reason=invalid_numeric_rejected``); a missing confidence yields no entry.
    """
    if not isinstance(text, str) or not text:
        return (text if isinstance(text, str) else "", [])
    if verdict != _VERDICT_DEGRADED:
        return (text, [])

    norm, index_map = _nfkc_with_index_map(text)
    events: list[dict[str, Any]] = list(_confidence_tokens(norm))
    for match in _LABELLED_INVALID_RE.finditer(norm):
        events.append(
            {
                "start": match.start("word"),
                "end": match.end("word"),
                "raw": match.group("word"),
                "pct": False,
                "valid": False,
            }
        )
    if not events:
        return (text, [])
    events.sort(key=lambda e: e["start"])

    pieces: list[str] = []
    audit: list[dict[str, Any]] = []
    cursor = 0
    for event in events:
        o_start, o_end = _original_span(index_map, event["start"], event["end"], len(text))
        if o_start < cursor:
            continue
        pieces.append(text[cursor:o_start])
        if not event["valid"]:
            pieces.append(QUARANTINE_MARKER)
            audit.append(
                {
                    "raw_value": None,
                    "effective_value": None,
                    "capped": False,
                    "reason": REASON_INVALID,
                    "policy_version": CONFIDENCE_POLICY_VERSION,
                    "representation": "percent" if event["pct"] else "decimal",
                    "quarantined": True,
                }
            )
            cursor = o_end
            continue
        value = _token_to_fraction(event["raw"], event["pct"])[0]
        if value is not None and exceeds_cap(value):
            effective = DEGRADED_CONFIDENCE_CAP
            replacement = (
                _format_percent(effective) if event["pct"] else _format_decimal(effective)
            )
            pieces.append(replacement)
            audit.append(
                {
                    "raw_value": value,
                    "effective_value": effective,
                    "capped": True,
                    "reason": REASON_CAPPED,
                    "policy_version": CONFIDENCE_POLICY_VERSION,
                    "representation": "percent" if event["pct"] else "decimal",
                }
            )
            cursor = o_end
            continue
        # Valid and within cap: leave the original token bytes unchanged.
        pieces.append(text[o_start:o_end])
        cursor = o_end
    pieces.append(text[cursor:])
    return ("".join(pieces), audit)


def _format_percent(value: float) -> str:
    """Render a fraction as a stable percent string (``0.6`` → ``60%``)."""
    percent = value * 100.0
    text = f"{percent:.{CONFIDENCE_DISPLAY_DECIMALS}f}".rstrip("0").rstrip(".")
    return f"{text or '0'}%"


def _format_decimal(value: float) -> str:
    """Render a fraction as a stable compact decimal string (``0.6`` → ``0.6``)."""
    text = f"{value:.{CONFIDENCE_DISPLAY_DECIMALS}f}".rstrip("0").rstrip(".")
    return text or "0"


def merge_audit(
    existing: Any, new_entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge audit entries, collapsing a duplicate boundary identity.

    An entry's identity is ``(boundary, source)``. A re-entry that recomputes the
    same boundary replaces (never appends) the prior entry, so an imported legacy
    state or a repeated report write cannot accumulate phantom entries or
    double-count. A non-list ``existing`` value is treated as empty.
    """
    merged: list[dict[str, Any]] = []
    index: dict[tuple[str, str], int] = {}
    if isinstance(existing, list):
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            identity = (str(entry.get("boundary", "")), str(entry.get("source", "")))
            if identity in index:
                merged[index[identity]] = dict(entry)
            else:
                index[identity] = len(merged)
                merged.append(dict(entry))
    for entry in new_entries:
        identity = (str(entry.get("boundary", "")), str(entry.get("source", "")))
        if identity in index:
            merged[index[identity]] = dict(entry)
        else:
            index[identity] = len(merged)
            merged.append(dict(entry))
    merged.sort(key=lambda e: (str(e.get("boundary", "")), str(e.get("source", ""))))
    return merged


def confidence_cap_summary(state: Mapping[str, Any] | Any) -> dict[str, Any]:
    """A JSON-safe summary of the cap policy + audit block for the report.

    ``current_trusted_verdict`` is recomputed (never trusted from a state field),
    so an imported/legacy state cannot report a stale verdict. The audit entries
    are read for display only; they never influence the verdict or a recomputed
    effective value.
    """
    verdict = current_trusted_verdict(state)
    audit = state.get("confidence_cap_audit") if isinstance(state, Mapping) else None
    entries = [dict(e) for e in audit if isinstance(e, dict)] if isinstance(audit, list) else []
    capped = [e for e in entries if e.get("capped")]
    quarantined = [e for e in entries if e.get("quarantined")]
    return {
        "verdict": verdict,
        "policy_version": CONFIDENCE_POLICY_VERSION,
        "cap": DEGRADED_CONFIDENCE_CAP,
        "cap_applies": verdict == _VERDICT_DEGRADED,
        "entry_count": len(entries),
        "capped_count": len(capped),
        "quarantined_count": len(quarantined),
        "entries": entries,
        "note": (
            "Engineering confidence ceiling for a degraded run; NOT a calibrated "
            "probability and NOT an accuracy claim."
        ),
    }


# ---------------------------------------------------------------------------
# Runtime helpers (used by the researchers / managers / report writer)
# ---------------------------------------------------------------------------


def boundary_id(boundary: str, source: str, index: Any = None) -> str:
    """A stable, collision-free boundary identity for an audit entry.

    ``source`` is the speaker/agent name and ``index`` an optional per-turn/round
    ordinal, so two different turns (or two rounds) never collide, while a
    re-entry of the SAME turn/round overwrites its own entry (never double-counts).
    """
    if index is None:
        return f"{boundary}:{source}"
    return f"{boundary}:{source}:{index}"


def cap_debate_turn(
    turn: Any,
    state: Mapping[str, Any] | Any,
    *,
    index: Any = None,
    raw_transcript_sink: dict[str, Any] | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    """Return ``(turn, audit_entries)`` with the turn's confidence capped.

    Uses the authoritative verdict from ``state`` (recomputed, never trusted from
    an audit field). On a degraded run:

    - the numeric ``DebateTurn.confidence`` is replaced by its effective value;
    - the readable ``content`` is rewritten so any explicit confidence-labelled
      numeric in the argument/metadata is capped BEFORE the turn enters the
      trusted debate history / prompts (so the Bear and Research Manager never see
      a raw ``95%`` / ``confidence=0.95`` in readable text).

    When ``raw_transcript_sink`` is supplied, the ORIGINAL raw turn content is
    stored in it under the speaker key so the caller can persist it as an
    explicitly non-authoritative transcript; it never replaces the model response
    chars used for usage accounting (the caller keeps the original ``content``
    length for accounting).

    ``index`` is the REAL per-turn ordinal the caller knows (never derived from
    the frozen turn), so different Bull turns get distinct audit identities and
    never overwrite each other; a re-entry of the same index overwrites its own.

    A turn whose confidence is absent (``0.0`` parse-fallback default) with no
    labelled numeric in its content is left exactly as is and produces no audit
    entry: the absence is preserved, never fabricated into a capped value.
    """
    verdict = current_trusted_verdict(state)
    speaker = str(getattr(turn, "speaker", "") or "debate")

    entries: list[dict[str, Any]] = []
    numeric_confidence = getattr(turn, "confidence", None)
    effective_confidence = numeric_confidence
    if numeric_confidence is not None and is_valid_numeric_confidence(numeric_confidence):
        capped = cap_value(numeric_confidence, verdict)
        if capped is not None:
            effective_confidence = capped
        if verdict == _VERDICT_DEGRADED and exceeds_cap(float(numeric_confidence)):
            entries.append(
                apply_confidence_cap(
                    numeric_confidence,
                    verdict,
                    source=speaker,
                    boundary=boundary_id("debate_turn_numeric", speaker, index),
                )
            )

    content = getattr(turn, "content", "")
    rewritten_content, text_entries = rewrite_confidence_text(content, verdict)
    if text_entries and isinstance(content, str) and rewritten_content != content:
        if raw_transcript_sink is not None:
            raw_transcript_sink[speaker] = content
        # Per-occurrence audit for the readable text, anchored to the same turn
        # identity with a positional suffix so repeated/conflicting values are all
        # retained rather than collapsed into a single summary.
        for position, text_entry in enumerate(text_entries):
            record = dict(text_entry)
            record["boundary"] = boundary_id("debate_turn_text", speaker, index)
            record["source"] = speaker
            record["occurrence"] = position
            entries.append(record)

    if (
        effective_confidence == numeric_confidence
        and rewritten_content == content
    ):
        return (turn, entries)

    from dataclasses import replace

    capped_turn = replace(
        turn,
        confidence=float(effective_confidence),
        content=rewritten_content,
    )
    return (capped_turn, entries)


def update_audit(
    state: Mapping[str, Any] | Any, new_entries: list[dict[str, Any] | None]
) -> list[dict[str, Any]]:
    """Merge new audit entries into the state's existing audit block (deduped)."""
    existing = state.get("confidence_cap_audit") if isinstance(state, Mapping) else None
    clean = [e for e in new_entries if isinstance(e, dict)]
    return merge_audit(existing, clean)


def cap_agent_text(
    text: Any,
    state: Mapping[str, Any] | Any,
    *,
    source: str,
    boundary: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Cap explicit confidence-labelled numerics in a trusted agent output.

    Recomputed from the authoritative verdict (never from a state audit field).
    On a degraded run every labelled confidence above the cap is rewritten to its
    effective value and any invalid labelled confidence is quarantined. Ordinary
    financial figures are untouched. On a normal run the text is returned
    unchanged and no entry is produced.

    Returns ``(rewritten_text, audit_entries)`` with **one entry PER occurrence**
    (each carrying its own raw/effective/reason/representation and an
    ``occurrence`` ordinal), so repeated or conflicting confidences are all
    retained rather than collapsed into a single max. Each entry keeps the
    caller's ``boundary``/``source`` so multiple boundaries never collide.
    """
    verdict = current_trusted_verdict(state)
    if not isinstance(text, str) or verdict != _VERDICT_DEGRADED:
        return (text if isinstance(text, str) else "", [])
    rewritten, entries = rewrite_confidence_text(text, verdict)
    records: list[dict[str, Any]] = []
    for position, entry in enumerate(entries):
        record = dict(entry)
        record["boundary"] = boundary
        record["source"] = str(source)
        record["occurrence"] = position
        records.append(record)
    return (rewritten, records)


def sanitize_persisted_numeric(
    raw: Any, *, source: str, boundary: str
) -> tuple[Any, dict[str, Any] | None]:
    """Sanitize a persisted numeric confidence on a degraded resume.

    Returns ``(new_value, provenance_entry_or_None)``. A valid in-range value is
    capped; an INVALID legacy numeric (bool / NaN / inf / out-of-range / wrong
    type that ``float`` might accept) is replaced by ``None`` and recorded as
    quarantined — never left unchanged as an authoritative over-cap/NaN value. A
    value already effectively ``None`` produces no entry.
    """
    if raw is None:
        return (None, None)
    if is_valid_numeric_confidence(raw):
        effective = cap_value(raw, _VERDICT_DEGRADED)
        if effective is None:
            return (None, None)
        if exceeds_cap(float(raw)):
            entry = apply_confidence_cap(
                raw, _VERDICT_DEGRADED, source=source, boundary=boundary
            )
            return (effective, entry)
        return (float(raw), None)
    # An invalid legacy numeric (e.g. True, NaN, "0.95") is quarantined to None.
    entry = {
        "raw_value": None,
        "effective_value": None,
        "capped": False,
        "reason": REASON_INVALID,
        "policy_version": CONFIDENCE_POLICY_VERSION,
        "boundary": boundary,
        "source": str(source),
        "quarantined": True,
        "legacy_invalid": True,
    }
    return (None, entry)


def cap_typed_confidence(
    model: Any,
    state: Mapping[str, Any] | Any,
    *,
    source: str,
    boundary: str,
    sink: list[dict[str, Any]] | None = None,
) -> Any:
    """Cap a typed decision schema's OPTIONAL numeric ``confidence`` before render.

    The structured render helpers format the confidence with two decimal places
    (``:.2f``). If the cap only saw that rendered text, a raw ``0.6000001`` would
    render as ``0.60`` (looks within cap, no event) and ``0.954321`` would render
    as ``0.95`` (raw precision lost). This helper therefore caps the model's
    ORIGINAL full-precision numeric value — via :func:`apply_confidence_cap`, whose
    comparison is exact — and returns a copy carrying the EFFECTIVE value, so the
    subsequent render shows the capped value while the audit records the exact raw.

    Only a model whose ``confidence`` field is a valid non-``None`` numeric and
    whose verdict is ``degraded`` can change; a normal/blocked run or an
    absent/invalid value returns the model unchanged with no entry. The audit
    entry (raw exact / effective / reason) is appended to ``sink`` when supplied.
    """
    verdict = current_trusted_verdict(state)
    raw = getattr(model, "confidence", None)
    if verdict != _VERDICT_DEGRADED or raw is None:
        return model
    if not is_valid_numeric_confidence(raw):
        return model
    entry = apply_confidence_cap(raw, verdict, source=source, boundary=boundary)
    if sink is not None and (entry.get("capped") or entry.get("reason") == REASON_INVALID):
        sink.append(entry)
    effective = entry.get("effective_value")
    if effective is None or effective == raw or not exceeds_cap(float(raw)):
        # Within cap: leave the model untouched so the render is byte-identical.
        return model
    try:
        from pydantic import BaseModel

        if isinstance(model, BaseModel):
            return model.model_copy(update={"confidence": effective})
    except Exception:  # noqa: BLE001 — a non-Pydantic model is copied by attr
        pass
    with contextlib.suppress(AttributeError, TypeError, ValueError):
        model.confidence = effective
    return model


# The analyst report fields and debate/risk text fields a POST-gate node reads
# into its prompt. On a degraded run these are capped on a per-read COPY of the
# state so a raw analyst-authored confidence (stored BEFORE the gate verdict was
# known) can never reach a downstream model prompt.
_POST_GATE_REPORT_KEYS: tuple[str, ...] = (
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
)
_POST_GATE_PLAN_KEYS: tuple[str, ...] = (
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
)
_POST_GATE_DEBATE_HISTORY_KEYS: tuple[str, ...] = (
    "history",
    "bull_history",
    "bear_history",
    "current_response",
    "judge_decision",
)
_POST_GATE_RISK_HISTORY_KEYS: tuple[str, ...] = (
    "history",
    "aggressive_history",
    "conservative_history",
    "neutral_history",
    "current_aggressive_response",
    "current_conservative_response",
    "current_neutral_response",
    "judge_decision",
)


def sanitize_state_inputs(
    state: Mapping[str, Any] | Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``(sanitized_copy, audit_entries)`` for a POST-gate node read.

    A single deterministic place that caps the confidence-labelled numerics in the
    analyst reports, the plan/decision texts and the debate/risk histories that a
    post-gate node interpolates into its prompt. The stored analyst reports are
    written BEFORE the gate verdict is known, so they are only sanitized here at
    the read boundary (never at analyst time, which would exempt nothing and could
    cap a normal run).

    The caller's ``state`` is NEVER mutated: a shallow copy carries the capped
    report/history/plan strings (nested debate/risk dicts are copied one level).
    On a ``normal`` / ``blocked`` run the copy is byte-identical and no entry is
    produced. Financial figures elsewhere are untouched (only explicit labelled
    confidence tokens are rewritten). One audit entry PER occurrence, anchored to
    a stable ``input:<field>`` boundary, so a re-read recomputes the same identity
    (idempotent, never double-counted by :func:`merge_audit`).
    """
    verdict = current_trusted_verdict(state)
    if verdict != _VERDICT_DEGRADED or not isinstance(state, Mapping):
        return (dict(state) if isinstance(state, Mapping) else {}, [])

    sanitized: dict[str, Any] = dict(state)
    audit: list[dict[str, Any]] = []

    def _cap_field(field: str, *, source: str) -> None:
        value = sanitized.get(field)
        if isinstance(value, str) and value:
            text, entries = sanitize_persisted_text(
                value, source=source, boundary=f"input:{field}"
            )
            sanitized[field] = text
            audit.extend(entries)

    for key in _POST_GATE_REPORT_KEYS:
        _cap_field(key, source="report")
    for key in _POST_GATE_PLAN_KEYS:
        _cap_field(key, source="plan")

    debate = sanitized.get("investment_debate_state")
    if isinstance(debate, Mapping):
        new_debate = dict(debate)
        # Numeric confidence in persisted turns / stances is capped HERE too, not
        # only readable text: a direct (non-API) GraphSetup resume can hand a stale
        # typed turn ``confidence=0.95`` to the evaluator BEFORE any late write-time
        # cap runs. Sanitizing the numeric channel on the read copy ensures the
        # evaluator / stance snapshot / next prompt all see the effective value.
        turns = new_debate.get("turns")
        if isinstance(turns, list):
            new_turns = []
            for index, turn in enumerate(turns):
                if not isinstance(turn, Mapping):
                    new_turns.append(turn)
                    continue
                new_turn = dict(turn)
                speaker = str(new_turn.get("speaker", "") or "debate")
                value, entry = sanitize_persisted_numeric(
                    new_turn.get("confidence"),
                    source=speaker,
                    boundary=boundary_id("input_turn_numeric", speaker, index),
                )
                if new_turn.get("confidence") is not None:
                    new_turn["confidence"] = value
                if entry is not None:
                    audit.append(entry)
                new_turns.append(new_turn)
            new_debate["turns"] = new_turns
        stances = new_debate.get("stances")
        if isinstance(stances, Mapping):
            new_stances = {}
            for speaker, snap in stances.items():
                if not isinstance(snap, Mapping):
                    new_stances[speaker] = snap
                    continue
                new_snap = dict(snap)
                value, entry = sanitize_persisted_numeric(
                    new_snap.get("confidence"),
                    source=str(speaker),
                    boundary=boundary_id("input_stance_numeric", str(speaker)),
                )
                if new_snap.get("confidence") is not None:
                    new_snap["confidence"] = value
                if entry is not None:
                    audit.append(entry)
                new_stances[speaker] = new_snap
            new_debate["stances"] = new_stances
        for hist_key in _POST_GATE_DEBATE_HISTORY_KEYS:
            value = new_debate.get(hist_key)
            if isinstance(value, str) and value:
                text, entries = sanitize_persisted_text(
                    value,
                    source="debate",
                    boundary=f"input:investment_debate_state.{hist_key}",
                )
                new_debate[hist_key] = text
                audit.extend(entries)
        sanitized["investment_debate_state"] = new_debate

    risk = sanitized.get("risk_debate_state")
    if isinstance(risk, Mapping):
        new_risk = dict(risk)
        for hist_key in _POST_GATE_RISK_HISTORY_KEYS:
            value = new_risk.get(hist_key)
            if isinstance(value, str) and value:
                text, entries = sanitize_persisted_text(
                    value,
                    source="risk",
                    boundary=f"input:risk_debate_state.{hist_key}",
                )
                new_risk[hist_key] = text
                audit.extend(entries)
        sanitized["risk_debate_state"] = new_risk

    return (sanitized, audit)


def _sanitize_result_fields(
    result: dict[str, Any], state: Mapping[str, Any] | Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cap the confidence-labelled numerics in a node's OWN returned text fields.

    Applies the same degraded-run cap to the report/plan/decision strings and to the
    nested ``investment_debate_state`` / ``risk_debate_state`` readable histories
    AND their turn/stance numeric confidence that a node is about to persist. This
    never assumes a node caps its own output (e.g. a risk analyst appending a raw
    "93% confident" argument). The caller's ``state`` is not mutated; the result dict
    is shallow-copied and only changed fields are replaced. Returns
    ``(sanitized_result, audit_entries)``; a normal/blocked run returns the result
    unchanged with no entry.
    """
    if current_trusted_verdict(state) != _VERDICT_DEGRADED:
        return result, []
    out = dict(result)
    audit: list[dict[str, Any]] = []

    for key in (*_POST_GATE_REPORT_KEYS, *_POST_GATE_PLAN_KEYS):
        value = out.get(key)
        if isinstance(value, str) and value:
            text, entries = sanitize_persisted_text(
                value, source="node_output", boundary=f"out:{key}"
            )
            if text != value:
                out[key] = text
            audit.extend(entries)

    debate = out.get("investment_debate_state")
    if isinstance(debate, Mapping):
        new_debate = dict(debate)
        _sanitize_nested_history(
            new_debate, _POST_GATE_DEBATE_HISTORY_KEYS,
            namespace="investment_debate_state", audit=audit,
        )
        _sanitize_nested_turns(new_debate, "investment_debate_state", audit)
        out["investment_debate_state"] = new_debate

    risk = out.get("risk_debate_state")
    if isinstance(risk, Mapping):
        new_risk = dict(risk)
        _sanitize_nested_history(
            new_risk, _POST_GATE_RISK_HISTORY_KEYS,
            namespace="risk_debate_state", audit=audit,
        )
        out["risk_debate_state"] = new_risk

    return out, audit


def _sanitize_nested_history(
    container: dict[str, Any],
    keys: tuple[str, ...],
    *,
    namespace: str,
    audit: list[dict[str, Any]],
) -> None:
    for hist_key in keys:
        value = container.get(hist_key)
        if isinstance(value, str) and value:
            text, entries = sanitize_persisted_text(
                value, source="node_output", boundary=f"out:{namespace}.{hist_key}"
            )
            if text != value:
                container[hist_key] = text
            audit.extend(entries)


def _sanitize_nested_turns(
    container: dict[str, Any], namespace: str, audit: list[dict[str, Any]]
) -> None:
    turns = container.get("turns")
    if isinstance(turns, list):
        new_turns = []
        for index, turn in enumerate(turns):
            if not isinstance(turn, Mapping):
                new_turns.append(turn)
                continue
            new_turn = dict(turn)
            speaker = str(new_turn.get("speaker", "") or "debate")
            value, entry = sanitize_persisted_numeric(
                new_turn.get("confidence"),
                source=speaker,
                boundary=f"out:{namespace}.turn:{speaker}:{index}",
            )
            if new_turn.get("confidence") is not None:
                new_turn["confidence"] = value
            if entry is not None:
                audit.append(entry)
            new_turns.append(new_turn)
        container["turns"] = new_turns
    stances = container.get("stances")
    if isinstance(stances, Mapping):
        new_stances = {}
        for speaker, snap in stances.items():
            if not isinstance(snap, Mapping):
                new_stances[speaker] = snap
                continue
            new_snap = dict(snap)
            value, entry = sanitize_persisted_numeric(
                new_snap.get("confidence"),
                source=str(speaker),
                boundary=f"out:{namespace}.stance:{speaker}",
            )
            if new_snap.get("confidence") is not None:
                new_snap["confidence"] = value
            if entry is not None:
                audit.append(entry)
            new_stances[speaker] = new_snap
        container["stances"] = new_stances


def with_sanitized_state(node: Any, *, name: str | None = None) -> Any:
    """Wrap a POST-gate node so every prompt read uses effective confidence.

    The wrapped callable sanitizes a COPY of the incoming state (analyst reports,
    plans and debate/risk histories capped on a degraded run) BEFORE delegating to
    ``node``, so a raw analyst-authored over-cap confidence that was stored before
    the gate verdict cannot reach this node's model prompt. Any input-sanitization
    audit entries are merged into the node's returned update under
    ``confidence_cap_audit`` (deduped); a non-dict return is passed through
    unchanged. The graph interface (``node(state, ...)`` -> state delta) is
    preserved and the original state object is never mutated.
    """

    def _wrapped(state, *args, **kwargs):
        sanitized, in_entries = sanitize_state_inputs(state)
        result = node(sanitized, *args, **kwargs)
        if not isinstance(result, dict):
            return result
        result = dict(result)

        # Cap the node's OWN returned text fields (e.g. a risk analyst's newly
        # appended history, a manager plan, the final decision) and its returned
        # debate/risk nested dicts' turn/stance numerics. This does not assume a
        # node caps its own output: a raw "93% confident" risk argument persisted in
        # the returned risk_debate_state is capped HERE before it can survive in the
        # final state / JSON export.
        out_result, out_entries = _sanitize_result_fields(result, state)

        # Persist changed INPUT fields (analyst reports / plans / histories the node
        # did NOT re-emit) as deltas so a direct legacy resume — which can skip the
        # post-gate sanitizer node — still ends with effective report/history values.
        # A key the node itself set always WINS (the node's fresh output is
        # authoritative over the pre-read snapshot).
        if isinstance(state, Mapping):
            for key, value in sanitized.items():
                if key == "confidence_cap_audit":
                    continue
                if key in result:
                    continue
                if state.get(key) != value:
                    out_result[key] = value

        all_entries = list(in_entries) + list(out_entries)
        if all_entries:
            existing = out_result.get("confidence_cap_audit")
            if isinstance(existing, list):
                out_result["confidence_cap_audit"] = merge_audit(existing, all_entries)
            else:
                out_result["confidence_cap_audit"] = update_audit(sanitized, all_entries)
        return out_result

    if name is not None:
        with contextlib.suppress(AttributeError, TypeError):
            _wrapped.__name__ = f"sanitized_{name}"
    return _wrapped


def create_confidence_state_sanitize_node():
    """A deterministic POST-gate node that PERSISTS capped confidence deltas.

    The per-read :func:`with_sanitized_state` wrapper protects every downstream
    model prompt, but it only sanitizes a transient COPY; the analyst reports and
    plans that were written BEFORE the gate verdict is known would otherwise remain
    raw in the final graph state and in any ``_log_state`` / public JSON export. On
    a degraded run this node sanitizes the persisted analyst reports / plans /
    debate+risk histories AND the turn/stance numeric confidence and writes ONLY
    the fields that actually changed back as a state delta, so the RETURNED state
    carries the effective values. The originals are recoverable only from the
    explicit audit / non-authoritative channels, never as authoritative-looking
    ``confidence=0.95`` prose.

    It never mutates the caller's state object (a shallow/nested copy is used), it
    merges its own audit entries idempotently (deduped by boundary identity), and it
    returns an empty delta on a normal/blocked run or when nothing changed. It
    makes no model call.
    """

    def _node(state):
        sanitized, entries = sanitize_state_inputs(state)
        if not entries and sanitized == (dict(state) if isinstance(state, Mapping) else {}):
            return {}
        delta: dict[str, Any] = {}
        if isinstance(state, Mapping):
            for key, value in sanitized.items():
                if key == "confidence_cap_audit":
                    continue
                if state.get(key) != value:
                    delta[key] = value
        if entries:
            existing = state.get("confidence_cap_audit") if isinstance(state, Mapping) else None
            delta["confidence_cap_audit"] = merge_audit(existing, entries)
        return delta

    _node.__name__ = "confidence_state_sanitize_node"
    return _node


def sanitize_persisted_text(
    text: Any, *, source: str, boundary: str
) -> tuple[str, list[dict[str, Any]]]:
    """Sanitize a persisted readable text field on a degraded resume.

    Returns ``(capped_text, provenance_entries)`` with one entry PER capping
    occurrence at ``boundary`` (so an imported/legacy raw value keeps its
    raw/effective/reason provenance instead of a bare null). Ordinary text without
    a labelled confidence is unchanged with no entry.
    """
    if not isinstance(text, str) or not text:
        return (text if isinstance(text, str) else "", [])
    rewritten, entries = rewrite_confidence_text(text, _VERDICT_DEGRADED)
    records: list[dict[str, Any]] = []
    for position, entry in enumerate(entries):
        record = dict(entry)
        record["boundary"] = boundary
        record["source"] = str(source)
        record["occurrence"] = position
        records.append(record)
    return (rewritten, records)
