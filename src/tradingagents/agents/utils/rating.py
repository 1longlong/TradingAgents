"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.

``extract_rating`` returns ``None`` when no rating can be found, and every
caller turns that into ``REVIEW`` rather than a tradeable position: a decision
nobody can read is not a Hold, and a Hold recorded in its place is quoted back to
the next run as a call that was never made (#1170).
"""

from __future__ import annotations

import re
import unicodedata

# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

# Signal emitted when the model's decision has no recognizable rating. It is not
# a tradeable position: it flags output that needs a human/re-run rather than
# silently degrading to Hold. Callers that map the signal onto the 5-tier enum
# (e.g. ``PortfolioRating(signal)``) should guard with ``is_review`` first.
RATING_REVIEW = "REVIEW"

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Matches "Rating: X" / "rating - X" / "Rating — **X**" — tolerates markdown
# bold wrappers and any dash or colon a model writes as the separator.
_RATING_LABEL_RE = re.compile(r"rating\b[^:\-\u2010-\u2015]*[:\-\u2010-\u2015][\s*]*(\w+)",
                              re.IGNORECASE)

# A line presenting the scale rather than a decision ("Rating Scale: Buy, ...").
_RATING_SCALE_RE = re.compile(r"rating\s*(scale|options|legend)", re.IGNORECASE)

# Standalone 5-tier word anywhere (word boundaries so "Buyer"/"Holding" don't match).
_RATING_WORD_RE = re.compile(
    r"\b(" + "|".join(RATINGS_5_TIER) + r")\b", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Shared decision-header recognition
#
# The output guard and this parser read the SAME grammar: NFKC-first, an optional
# Markdown bullet/heading, an arbitrary plain descriptor prefix, then the decision
# label and a separator and a single-word value. Recognition is a single linear
# left-to-right scan (no nested/ambiguous quantifiers, so it stays fast on long
# ordinary rationale lines) and there is deliberately NO cap on the descriptor
# length: ``"My final carefully reviewed overall investment committee consensus
# recommendation rating: Buy"`` is still a decision.
#
# A label embedded inside running prose (``"... we rejected the earlier Action:
# Buy ..."``) or a blockquote (``> Action: Sell was an alternative``) is quoted
# commentary, not a live decision, and is deliberately not matched. The shared
# recognizers add no new vocabulary: the value is always one word and the
# ``Rating`` variant is validated against :data:`RATINGS_5_TIER`.
# ---------------------------------------------------------------------------

# Markdown emphasis that may wrap a label (``**Rating**`` / ``__Rating__``) or a
# value (``**Buy**``).
_WRAP = r"(?:\*{1,2}|_{1,2})?"

# Separators a model may write between a label and its value (the normalized line
# already turned a fullwidth colon U+FF1A into ``:``).
_SEPARATOR_CHARS = ":-\u2010\u2011\u2012\u2013\u2014\u2015"

# A header may start with a Markdown bullet / numbered / ATX-heading marker.
_HEADER_BULLET_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)?[ \t]*"
)

# One descriptor token: a word (optionally emphasised, optionally followed by a
# comma). Matching one token at a time keeps the scan linear.
_DESCRIPTOR_TOKEN_RE = re.compile(r"[*_]*[A-Za-z][\w'\-]*[*_]*[ \t]*,?[ \t]*")

# A blockquote (`> ...`) is a quoted alternative, never a live decision header.
_BLOCKQUOTE_RE = re.compile(r"^[ \t]*(?:>[ \t]*)+")

# A word (the decision value): letters only, so "Buy," / "**Buy**" both parse.
_WORD_RE = re.compile(r"[A-Za-z]+")
_SPACE_RE = re.compile(r"[ \t]*")
_ANY_SPACE_RE = re.compile(r"\s+")
_WRAP_RE = re.compile(_WRAP)


def _skip_spaces(norm_line: str, pos: int) -> int:
    return _SPACE_RE.match(norm_line, pos).end()


def _match_wrap(norm_line: str, pos: int) -> int:
    return _WRAP_RE.match(norm_line, pos).end()


def _label_end(norm_line: str, pos: int, label: str) -> int | None:
    """End offset of ``label`` starting at ``pos`` (emphasis/whitespace tolerant)."""
    i = pos
    for index, part in enumerate(label.split(" ")):
        if index:
            space = _ANY_SPACE_RE.match(norm_line, i)
            if space is None:
                return None
            i = space.end()
        i = _match_wrap(norm_line, i)
        if norm_line[i:i + len(part)].lower() != part.lower():
            return None
        i += len(part)
        i = _match_wrap(norm_line, i)
    return i


def _value_span(norm_line: str, pos: int) -> tuple[int, int] | None:
    """``(start, end)`` of the single-word value after a REQUIRED separator.

    The separator must follow the label, so running prose that merely contains
    the label words ("the analyst said the Rating Buy case was weak") is not a
    header. A missing value after the separator means this is not a decision.
    """
    i = _skip_spaces(norm_line, pos)
    if i >= len(norm_line) or norm_line[i] not in _SEPARATOR_CHARS:
        return None
    i = _match_wrap(norm_line, _skip_spaces(norm_line, i + 1))
    value = _WORD_RE.match(norm_line, i)
    if value is None:
        return None
    # End at the word itself; a closing emphasis marker belongs to the tail so
    # the recognized value is a bare 5-tier / decision word (``**Buy**`` -> ``Buy``).
    return value.start(), value.end()


def _split_header(norm_line: str, label: str) -> tuple[str, str, str, str] | None:
    """Split a normalized line at a structural ``label`` header.

    Returns ``(prefix, label_text, value, tail)`` -- the bullet/descriptor text
    before the label, the label exactly as written (emphasis included), the
    single-word value, and everything after the value (the caller keeps the tail
    verbatim as explanation) -- or ``None`` when the line is not a decision
    header. Because the value is returned explicitly, an empty tail (``Rating:
    Buy``) is a valid recognized decision, never a missing match.

    The scan is linear and has no descriptor-length cap: every descriptor word is
    consumed one token at a time until the label (or a non-descriptor character)
    is reached. A blockquote or a label buried inside a sentence is not a header.
    """
    if not norm_line or _BLOCKQUOTE_RE.match(norm_line):
        return None
    pos = _HEADER_BULLET_RE.match(norm_line).end()
    while True:
        label_at = _label_end(norm_line, pos, label)
        if label_at is not None:
            span = _value_span(norm_line, label_at)
            if span is not None:
                return (
                    norm_line[:pos],
                    norm_line[pos:label_at],
                    norm_line[span[0]:span[1]],
                    norm_line[span[1]:],
                )
            # The label word is itself part of a longer descriptor ("...
            # recommendation rating: Buy"); keep scanning instead of failing.
        token = _DESCRIPTOR_TOKEN_RE.match(norm_line, pos)
        if token is None or token.end() == pos:
            return None
        pos = token.end()


def _decision_tail(norm_line: str, label: str) -> str | None:
    """Verbatim tail after a structural ``label`` value, or ``None``."""
    split = _split_header(norm_line, label)
    if split is None:
        return None
    _prefix, _label_text, _value, tail = split
    if re.match(r"^[ \t]*(scale|options|legend)\b", tail, re.IGNORECASE):
        return None
    return tail


def decision_header(
    norm_line: str, label: str
) -> tuple[str, str, str, str] | None:
    """``(prefix, label_text, value, tail)`` for a structural header, or ``None``.

    Public accessor over the internal splitter so the output guard can rebuild a
    pinned line while preserving the model's original label markup (``Action`` vs
    ``**Action**``). ``norm_line`` must already be NFKC-normalized; a blockquote,
    prose-embedded label, or missing separator/value returns ``None``.
    """
    return _split_header(norm_line, label)


def labelled_field_tail(norm_line: str, label: str) -> str | None:
    """Tail after a labelled ``Recommendation`` / ``Action`` value (or ``None``).

    ``norm_line`` must already be NFKC-normalized. A label is a header only when
    it starts the line (after an optional bullet/heading and any plain descriptor
    prefix) and is followed by a separator and a single-word value; a label inside
    running prose or a blockquote is a quoted mention and returns ``None``. The
    tail (separator and prose included) is returned verbatim so a rationale like
    ``"because momentum improved"`` is never lost; an empty tail is still a
    recognized decision. A ``... Scale/Options/Legend`` legend is not a decision.
    """
    return _decision_tail(norm_line, label)


_RATING_HEADER_LABEL = "Rating"


def _rating_header_tail(norm_line: str) -> str | None:
    """Verbatim tail after a structural, 5-tier ``Rating`` value, or ``None``.

    Only a value from :data:`RATINGS_5_TIER` is a call; any other value (for
    example the ``Rating Scale`` legend's words) is not a decision, and a
    blockquote is a quoted mention. The tail is the text after the value.
    """
    split = _split_header(norm_line, _RATING_HEADER_LABEL)
    if split is None:
        return None
    _prefix, _label_text, value, tail = split
    if value.lower() not in _RATING_SET:
        return None
    if re.match(r"^[ \t]*(scale|options|legend)\b", tail, re.IGNORECASE):
        return None
    return tail


# Trader executable sizing fields (a Hold cannot carry a fill instruction). The
# value is everything after the label separator so nothing active survives.
_SIZING_LABELS = ("Entry Price", "Stop Loss", "Position Sizing")


def _sizing_split(norm_line: str, label: str) -> str | None:
    """The value text after a structural sizing ``label`` separator, or ``None``.

    Unlike a decision value (a single word), a sizing value may be numeric or a
    percentage (``189.5`` / ``6% of portfolio``), so everything after the required
    separator is returned. Same structural grammar otherwise: a plain descriptor
    prefix and the label at the header position; a quoted mention or blockquote is
    not a field.
    """
    if not norm_line or _BLOCKQUOTE_RE.match(norm_line):
        return None
    pos = _HEADER_BULLET_RE.match(norm_line).end()
    while True:
        label_at = _label_end(norm_line, pos, label)
        if label_at is not None:
            i = _skip_spaces(norm_line, label_at)
            if i >= len(norm_line) or norm_line[i] not in _SEPARATOR_CHARS:
                return None
            value = norm_line[_skip_spaces(norm_line, i + 1):].strip()
            return value or None
        token = _DESCRIPTOR_TOKEN_RE.match(norm_line, pos)
        if token is None or token.end() == pos:
            return None
        pos = token.end()


def labelled_sizing_tail(norm_line: str) -> tuple[str, str] | None:
    """``(label, value)`` for a blocked-run executable sizing field, or ``None``.

    Returns the canonical label spelling and the field's value text so the output
    guard can neutralise it while keeping the line readable. The same structural
    header grammar applies: a plain descriptor prefix and a required separator,
    while a quoted mention inside prose or a blockquote is not a field.
    """
    if _BLOCKQUOTE_RE.match(norm_line):
        return None
    for label in _SIZING_LABELS:
        value = _sizing_split(norm_line, label)
        if value is not None:
            return label, value
    return None


# The trailing compatibility marker the Trader renders, recognized with the same
# structural header grammar and with ANY value and explanation tail, so an
# executable "FINAL TRANSACTION PROPOSAL: BUY because momentum improved" cannot
# survive. The split is computed from the SAME normalized string that was
# matched, so the caller never mixes offsets from two different normalizations.
_FINAL_PROPOSAL_LABEL = "FINAL TRANSACTION PROPOSAL"


def final_proposal_header(norm_line: str) -> tuple[str, str] | None:
    """``(prefix, tail)`` for a FINAL TRANSACTION PROPOSAL header, or ``None``.

    ``prefix`` is the Markdown bullet/descriptor text before the marker (possibly
    empty) and ``tail`` starts at the executable value on the normalized line, so
    the caller can replace the value while keeping any explanation after it.
    """
    split = _split_header(norm_line, _FINAL_PROPOSAL_LABEL)
    if split is None:
        return None
    prefix, _label_text, value, after = split
    return prefix, value + after


def extract_rating(text: str) -> str | None:
    """Extract a 5-tier rating from prose, or ``None`` if none is present.

    Two-pass strategy on the NFKC-normalized text (so fullwidth punctuation like
    ``Rating：Overweight`` is matched the same as ASCII):
    1. An explicit "Rating: X" label (tolerant of markdown bold).
    2. The first standalone 5-tier rating word found anywhere.
    """
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", text)
    lines = norm.splitlines()

    # The authoritative labelled rating: a STRUCTURAL header (label at the start
    # of a line, after an optional bullet/descriptor prefix) is the decision, and
    # it takes precedence over any mention elsewhere. This is the same grammar
    # the output guard pins, so a blockquoted or narrative alternative ("...
    # rejected the earlier rating: Sell") can never override the decision line,
    # while the decision line itself is still read. The last structural header
    # wins, matching "a decision states its rating after discussing options".
    structural = None
    for line in lines:
        if _RATING_SCALE_RE.search(line):
            continue
        tail = _rating_header_tail(line)
        if tail is None:
            continue
        head = _split_header(line, _RATING_HEADER_LABEL)
        structural = head[2].capitalize()
    if structural:
        return structural

    # No structural header. Fall back to the looser within-line search so a
    # labelled decision embedded mid-sentence ("... Final rating — Underweight")
    # is still read; the last mention wins.
    labelled = None
    for line in lines:
        if _RATING_SCALE_RE.search(line):
            continue
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            labelled = m.group(1).capitalize()
    if labelled:
        return labelled

    # No label. A single rating word in the text is the call; several are an
    # argument, and picking one of them reports a direction nobody decided --
    # prose that rejects a Buy before concluding Underweight read as Buy.
    named = {m.group(1).capitalize() for m in _RATING_WORD_RE.finditer(norm)}
    return named.pop() if len(named) == 1 else None


def labelled_decision_line_indices(text: str) -> list[int]:
    """Indices of lines this module's parser reads as a *labelled* rating call.

    This shares :data:`_RATING_LABEL_RE`/:data:`_RATING_SCALE_RE` and the same
    per-line NFKC normalization :func:`extract_rating` uses, so the output guard
    and the parser can never disagree about which line carries the decision. A
    line is reported only when it presents a labelled rating whose value is one
    of the five tiers (the scale legend is skipped). The index refers to
    ``text.splitlines()`` (original text), which is safe because NFKC of a single
    line never changes the number of lines.

    Any number/kind of descriptor before the ``rating`` label, and fullwidth
    characters anywhere, are handled because matching happens on the normalized
    line rather than on a bounded prefix list.
    """
    if not text:
        return []
    indices: list[int] = []
    for index, line in enumerate(text.splitlines()):
        norm = unicodedata.normalize("NFKC", line)
        if _rating_header_tail(norm) is not None:
            indices.append(index)
    return indices


def labelled_decision_tail(norm_line: str) -> str | None:
    """The normalized trailing text after a labelled rating value, or ``None``.

    ``norm_line`` must already be NFKC-normalized (as :func:`extract_rating`
    operates). Returns the text the author wrote after the rating value (e.g.
    ``" because the outlook is good."``), so the output guard can pin the
    decision while preserving a natural-language rationale tail as
    non-executable explanation. Returns ``None`` when the line is not a labelled
    tiered rating (or is a scale legend). The return value keeps its own leading
    whitespace so a caller can preserve the semantic separator.
    """
    return _rating_header_tail(norm_line)


def parse_rating(text: str, default: str = RATING_REVIEW) -> str:
    """Extract a 5-tier rating, or ``REVIEW`` when the decision has none.

    For callers that need a string for every decision, such as the memory log's
    entry tag. The default is the review sentinel, never a tradeable rating.
    """
    rating = extract_rating(text)
    return rating if rating is not None else default


def is_review(signal: str) -> bool:
    """Whether a signal is the non-tradeable REVIEW sentinel (#1170)."""
    return signal == RATING_REVIEW
