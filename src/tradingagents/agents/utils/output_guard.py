"""Centralized deterministic Data Quality Gate output guard.

The 2026-11-06 offline review reproduced an end-to-end escape: on a *blocked*
Data Quality Gate run the Research Manager correctly rewrites its
recommendation to Hold, but the Trader, the risk debate, and the final Portfolio
Manager could still produce a model Buy. ``final_trade_decision`` then read Buy
and the signal processor returned Buy, so the blocked verdict was not
authoritative at the output boundary (design sections 3.6 and 7.3).

This module is the single place that enforces the restricted conclusion. It is
pure, LLM-free, and deterministic:

- :func:`effective_gate_verdict` reads the gate state and fails closed. Only a
  gate decision object whose ``decision`` and the state's
  ``data_quality_verdict`` agree on ``normal`` or ``degraded`` is trusted; a
  blocked verdict, a missing/malformed decision object, or a mismatch is
  ``blocked``. This mirrors the router's fail-closed contract so the router and
  the output guard can never disagree about whether a run was blocked.
- :func:`enforce_blocked_conclusion` pins every decision field (``Action`` /
  ``Recommendation`` / ``Rating``) to a canonical ``**<Label>**: Hold`` line and
  appends a short evidence-insufficient note. Recognition is the same shared,
  NFKC-first, *linear* header scan the rating parser uses
  (:func:`tradingagents.agents.utils.rating.decision_header`): an optional
  Markdown bullet/heading, an arbitrary plain descriptor prefix (no length cap),
  a required separator, and a single-word value. That covers fullwidth/NFKC
  labels and values, long descriptors, repeated/trailing labels and Markdown
  wrapping without a growing prefix list, while blockquoted alternatives and
  narrative mentions ("we rejected the earlier rating: Sell") are preserved and
  never treated as a decision. A blocked Trader's executable
  entry/stop/position-sizing fields are neutralised to ``not applicable`` and an
  ``FINAL TRANSACTION PROPOSAL: ... because ...`` marker is pinned to Hold with
  the explanation kept. Rationale, recovery conditions and quoted alternatives
  survive, and the operation is idempotent.

The final *signal* boundary is also gate-aware: ``SignalProcessor`` calls
:func:`is_blocked_run` on the run state and returns ``Hold`` on a blocked run, so
an unanticipated decision-header format can never turn a blocked run into a
directional final signal.

No numeric confidence ceiling is invented here: the degraded-run cap remains a
prompt instruction until a schema/policy defines one (recorded in
``docs/debt-register.md``), so a degraded run is never coerced to Hold.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from tradingagents.agents.utils.rating import (
    _BLOCKQUOTE_RE,
    _DESCRIPTOR_TOKEN_RE,
    _FINAL_PROPOSAL_LABEL,
    _HEADER_BULLET_RE,
    _SEPARATOR_CHARS,
    _label_end,
    _skip_spaces,
    decision_header,
    final_proposal_header,
    labelled_sizing_tail,
)

# The 5-tier directional labels that must never remain an executable call on a
# blocked run. ``Hold`` is the only permitted conclusion.
DIRECTIONAL_RATINGS: tuple[str, ...] = ("Buy", "Sell", "Overweight", "Underweight")

HOLD = "Hold"

_BLOCKED = "blocked"
_TRUSTED_VERDICTS = ("normal", "degraded")
_KNOWN_VERDICTS = ("normal", "degraded", "blocked")

# The decision field the guard pins, mapped to the markdown label each agent
# renders it with (see ``tradingagents.agents.schemas`` render helpers).
_FIELD_LABELS: dict[str, str] = {
    "recommendation": "Recommendation",
    "rating": "Rating",
    "action": "Action",
}

_NOTE = (
    "Note: the Data Quality Gate blocked this run; the conclusion is "
    "evidence-insufficient, not a directional call."
)

# Markdown bullet/heading prefix tolerated before a decision label. A header may
# be `## Action`, a bulleted `- Action`, or plain text. Only the prefix is
# preserved; the label/value recognition itself is shared with the rating parser.
_MARKUP_PREFIX_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)?[ \t]*)"
)

# A dangling Markdown emphasis marker that belonged to a rewritten label/value is
# dropped so the pinned line stays valid Markdown.
_EMPHASIS_TAIL_RE = re.compile(r"^(?:\*\*|__|\*|_)")


def effective_gate_verdict(state: Mapping[str, Any] | Any) -> str:
    """Return the authoritative gate verdict, failing closed to ``blocked``.

    A run is trusted as unblocked only when a non-empty gate decision object
    carries a known ``decision`` and the state's ``data_quality_verdict`` is the
    same known value. Absent fields, a non-dict/empty decision, an unknown value,
    or a verdict/decision mismatch all fail closed to ``blocked``. A genuinely
    supported legacy checkpoint (matching normal/degraded verdict and decision)
    is trusted and keeps its behavior.

    A state that is not a mapping at all is treated as ``blocked``.
    """
    if not isinstance(state, Mapping):
        return _BLOCKED
    decision = state.get("data_quality_gate_decision")
    if not isinstance(decision, dict) or not decision:
        return _BLOCKED
    decision_value = decision.get("decision")
    if decision_value not in _KNOWN_VERDICTS:
        return _BLOCKED
    verdict = state.get("data_quality_verdict")
    if not isinstance(verdict, str):
        return _BLOCKED
    verdict = verdict.strip()
    if verdict not in _KNOWN_VERDICTS:
        return _BLOCKED
    if verdict != decision_value:
        return _BLOCKED
    return verdict


def is_blocked_run(state: Mapping[str, Any] | Any) -> bool:
    """True when the authoritative gate verdict is ``blocked`` (fail-closed)."""
    return effective_gate_verdict(state) == _BLOCKED


def _clean_tail(tail: str) -> str:
    """Return a value's natural-language tail without markdown/separator debris.

    The caller currently keeps only the *label* and rewrites the value to a plain
    ``Hold``/``not applicable``/``**HOLD**``, so any emphasis that wrapped the old
    value (`**`/`__`/`*`/`_`) and the leading separator/whitespace are stripped.
    Keeping the semantic whitespace boundary is what stops ``Holdbecause ...``
    (review finding 3); returning an empty string when nothing but separator
    debris remains is what makes re-guarding idempotent (the canonical form has
    no dangling emphasis for the next pass to mistake for a value).
    """
    tail = tail.strip()
    tail = _EMPHASIS_TAIL_RE.sub("", tail)
    tail = tail.lstrip(" :-\u2010\u2011\u2012\u2013\u2014\u2015")
    return tail.strip()


# A rationale connector that clearly separates an explanation from an executable
# value (``... because valuation is attractive``). Only these markers initiate a
# rationale that is kept after an executable tail is stripped.
_RATIONALE_CONNECTOR_RE = re.compile(
    r"\b(?:because|since|as|given|due\s+to|owing\s+to|on\s+the\s+grounds\s+that)\b",
    re.IGNORECASE,
)

# An executable residual in a decision value's tail: a share/unit/position
# quantity, a price, or a percentage size. When the tail carries one of these the
# value line was more than a bare decision word (``Buy 100 shares at $100``) and
# the executable fragment must not be kept in the pinned Hold. Ordinary rationale
# prose (``case was weak``) is NOT flagged.
_EXECUTABLE_TAIL_RE = re.compile(
    r"(?:\b\d[\d,\.]*\b|\bshares?\b|\bunits?\b|\bposition\b|"
    r"\$\s*\d|\d+\s*%|\b\d+\s*(?:shares?|units?)\b)",
    re.IGNORECASE,
)

# A tail that is *only* a residual direction word (``Strong Buy`` -> value
# ``Strong``, tail `` Buy``): the value was a two-word direction variant, so the
# residual direction must not be kept.
_RESIDUAL_DIRECTION_TAIL_RE = re.compile(
    r"^(?:" + "|".join(DIRECTIONAL_RATINGS) + r"|Hold)[.!]?$",
    re.IGNORECASE,
)


def _safe_decision_tail(tail: str) -> str:
    """Keep a decision value's tail only when it is non-executable rationale.

    A recognised decision header captures a single-word value; anything after it
    is the ``tail``. For ``Action: Buy 100 shares at $100 because valuation is
    attractive`` the value is ``Buy`` and the tail begins with executable sizing/
    price text (``100 shares at $100``). Pinning that tail verbatim would leave an
    executable position/price in the decision field. This helper returns:

    - the *rationale clause only*, from a leading rationale connector
      (``because``/``since``/``as``/...), when the tail carries an executable
      residual (so a clearly separated explanation survives as
      ``Hold because valuation is attractive``);
    - ``""`` when the tail carries an executable residual but no rationale
      connector (so ``Buy 100 shares at $100`` / ``Strong Buy`` leave just Hold);
    - the tail unchanged when it is ordinary non-executable rationale.
    """
    if not tail:
        return ""
    executable = bool(_EXECUTABLE_TAIL_RE.search(tail)) or bool(
        _RESIDUAL_DIRECTION_TAIL_RE.match(tail)
    )
    if not executable:
        return tail
    connector = _RATIONALE_CONNECTOR_RE.search(tail)
    if connector is None:
        return ""
    rationale = _clean_tail(tail[connector.start():])
    return rationale


def _pin_field_lines(lines: list[str], field: str) -> bool:
    """Pin every decision line to Hold; return whether the field's own was found.

    Recognition is shared with the rating parser (``tradingagents.agents.utils.
    rating``), so fullwidth labels/values, arbitrarily prefixed labels, long
    decision-label descriptors, repeated/trailing labels and Markdown wrapping are
    all covered without a growing prefix list. Every matched line is rewritten to
    the canonical ``**<Label>**: Hold`` form (with a preserved rationale tail),
    which keeps the rendered decision and the textual parser in agreement and
    makes the operation idempotent. Rationale lines that merely *mention* a
    direction (including blockquoted alternatives and narrative "rejected the
    earlier ..." mentions) are not decision lines and are left untouched.

    The return value only reports whether the *field's own* label was pinned; a
    cross-field determination is still neutralised but does not suppress the
    caller's authoritative-Hold prepend when the agent's own field is absent.
    """
    # A blocked plan carries no executable directional decision in ANY of the
    # three decision fields, not only the one this agent renders: a Trader body
    # could end in a Recommendation header, and the terminal signal reads the
    # Rating field whatever agent wrote it. The field's own label is tried first
    # (so the canonical output keeps the right label), then the others; each
    # splitter requires the structural header grammar (a required separator and a
    # single-word value) and the rating variant only accepts a 5-tier value, so
    # ordinary prose and quoted mentions are still left untouched.
    own_label = _FIELD_LABELS[field]
    labels = [own_label] + [
        other for other in _FIELD_LABELS.values() if other != own_label
    ]
    found_own = False
    for index, line in enumerate(lines):
        norm = unicodedata.normalize("NFKC", line)
        for rendered in labels:
            header = decision_header(norm, rendered)
            if header is not None:
                break
        else:
            continue
        if rendered == own_label:
            found_own = True
        prefix, _label_text, _value, tail = header
        # Canonicalise to the parser-agreeing bold form so the rendered decision
        # and the textual parser can never disagree; this is also what makes
        # re-guarding idempotent (the label is matched the same way next time).
        # The tail may begin with executable sizing/price fragments
        # (``Buy 100 shares at $100``) or a residual direction variant
        # (``Strong Buy``); only a clearly separated rationale clause is kept.
        tail = _safe_decision_tail(_clean_tail(tail))
        pinned = f"{prefix}**{rendered}**: {HOLD}"
        lines[index] = f"{pinned} {tail}" if tail else pinned
    return found_own


def _pin_final_transaction_proposal(lines: list[str]) -> bool:
    """Pin every ``FINAL TRANSACTION PROPOSAL`` line to a Hold marker; return found.

    Recognition and slicing both operate on the *same* NFKC-normalized line, so a
    fullwidth marker (``ＦＩＮＡＬ ＴＲＡＮＳＡＣＴＩＯＮ ＰＲＯＰＯＳＡＬ：ＢＵＹ``)
    cannot be sliced with offsets taken from the raw string. Only a structurally
    leading marker counts; a quoted mention inside prose or a blockquote is left
    untouched. The bullet/heading/descriptor prefix is preserved, the executable
    value is replaced, and any explanation tail after it is kept as
    non-executable prose. Rewriting the line to a stable canonical form makes
    re-guarding idempotent.
    """
    found = False
    for index, line in enumerate(lines):
        header = final_proposal_header(unicodedata.normalize("NFKC", line))
        if header is None:
            continue
        found = True
        prefix, tail = header
        value = re.match(
            r"^(?:\*\*|__|\*|_)?[ \t]*[A-Za-z]+(?:[ \t]*(?:\*\*|__|\*|_))?",
            tail,
        )
        if value is not None:
            tail = tail[value.end():]
        tail = _clean_tail(tail).rstrip(" .")
        marker = f"FINAL TRANSACTION PROPOSAL: **{HOLD.upper()}**"
        lines[index] = f"{prefix}{marker} {tail}" if tail else f"{prefix}{marker}"
    return found


# Narrow blocked-run rule for the Trader's executable sizing: on a blocked run a
# Hold cannot carry entry/stop/position-sizing instructions, so those fields are
# marked not-applicable. The line is still recognized (structure, prefix and a
# readable tail) but the active value is replaced. Quoted rationale is untouched.
_NOT_APPLICABLE = "not applicable (blocked run: no executable position)"

# The structural prefix a decision value line may carry: a Markdown bullet /
# numbered / ATX-heading marker, then optional emphasis. Shared so a block-style
# value like ``- Buy`` or ``1. **Buy**`` is recognised the same way.
_VALUE_PREFIX = r"[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)?[ \t]*(?:\*\*|__|\*|_)?[ \t]*"

# A bare 5-tier direction word alone on a line (optionally bullet/numbered,
# Markdown-wrapped and punctuation-terminated). This is the executable *value* of
# a block-style ``**Action**:`` header whose value sits on the next line.
_BARE_DIRECTION_RE = re.compile(
    r"^" + _VALUE_PREFIX
    + r"(?:buy|sell|overweight|underweight)[ \t]*(?:\*\*|__|\*|_)?[ \t]*[.!]?[ \t]*$",
    re.IGNORECASE,
)

# A value line in the label's value position that *leads* with a direction word
# and may carry an explanation (``Buy because valuation is attractive.``). Only
# used directly after a recognised label-only header, so it is a live decision
# value, not ordinary prose. The captured tail is preserved as rationale.
_DIRECTION_LEAD_RE = re.compile(
    r"^" + _VALUE_PREFIX + r"(?:buy|sell|overweight|underweight)\b(?P<tail>.*)$",
    re.IGNORECASE,
)

# A bounded *unsupported value* in a recognised label's value position: a short
# value-like line (at most three emphasis-wrapped words, optional trailing
# punctuation) after a label-only header that does NOT begin with a known
# direction word -- e.g. ``**Strong Buy**`` / ``Strong Sell now``. A blocked run
# must not trust an unrecognised direction variant: the value line is dropped and
# the header pinned to Hold (fail closed). The bound (<=3 words, letters only)
# keeps ordinary prose/sentences from being mistaken for a value.
_UNSUPPORTED_VALUE_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)?[ \t]*"
    r"(?:\*\*|__|\*|_)?[ \t]*"
    r"(?:[A-Za-z]+[ \t]+){0,2}[A-Za-z]+[ \t]*"
    r"(?:\*\*|__|\*|_)?[ \t]*[.!]?[ \t]*$"
)

# An executable plain-prose instruction the header grammar does not model, e.g.
# ``Buy 100 shares at $100``, ``Exit at $120``, ``Stop at $90``, ``Sell 50
# shares``. It must carry BOTH a leading trade verb AND a share/position
# quantity or price/size token. The match is ANCHORED to the start of the line
# (after an optional bullet/number/heading prefix) so a nested mention inside
# running rationale -- ``Rationale: We rejected "Buy ..."``, ``We considered a
# Buy ... plan`` -- is never treated as a live instruction. A line that leads with
# a trade verb IS a live command even if it later mentions a rationale keyword
# or a quotation (``Buy 100 shares at $100 because the earlier forecast
# improved`` / ``... ; analyst says "good value"``); exemption is structural (the
# verb must be quoted/negated), never a blanket keyword immunity.
_EXECUTABLE_SENTENCE_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)?[ \t]*"
    r"(?:\*\*|__|\*|_)?[ \t]*"
    r"(?:buy|sell|short|exit|stop(?:\s*loss)?|take\s*profit|"
    r"enter|close|add|trim|reduce)\b[^\n]*?"
    r"(?:\b\d[\d,\.]*\b|\bshares?\b|\bunits?\b|\bat\b|\$\d|\d+%)",
    re.IGNORECASE,
)

# A quoted span (double-, curly-, or single-quoted). Used to decide whether an
# anchored command's verb is *inside* a quotation (a quoted alternative, hence
# commentary) rather than a live instruction. Only the verb position matters;
# a live ``Buy ...`` command that merely quotes a phrase later is still contained.
_QUOTED_SPAN_RE = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d|'[^']*'")

# A ``(prefix, label)`` whose label carries a separator but NO value on its own
# line — the block-style header whose value is on the following physical line.
_DECISION_LABELS_BY_FIELD = {
    "recommendation": "Recommendation",
    "rating": "Rating",
    "action": "Action",
}


def _line_has_label_without_value(norm_line: str, label: str) -> bool:
    """True when ``norm_line`` is a structural ``label`` + separator with no value.

    Uses the shared header grammar so the same prefix/label/separator rules
    apply; blockquotes and label words buried in prose are excluded. A label
    followed by a separator and nothing (or only emphasis debris) is a
    block-style header whose value is expected on the next physical line.
    """
    if not norm_line or _BLOCKQUOTE_RE.match(norm_line):
        return False
    pos = _HEADER_BULLET_RE.match(norm_line).end()
    while True:
        label_at = _label_end(norm_line, pos, label)
        if label_at is not None:
            i = _skip_spaces(norm_line, label_at)
            if i >= len(norm_line) or norm_line[i] not in _SEPARATOR_CHARS:
                return False
            rest = norm_line[_skip_spaces(norm_line, i + 1):].strip()
            rest = _EMPHASIS_TAIL_RE.sub("", rest).strip()
            return rest == ""
        token = _DESCRIPTOR_TOKEN_RE.match(norm_line, pos)
        if token is None or token.end() == pos:
            return False
        pos = token.end()


def _next_nonblank_index(lines: list[str], start: int) -> int | None:
    """Index of the first non-blank line at or after ``start`` (skips blanks).

    A block-style label's value may be separated from it by one or more blank
    physical lines (``**Action**:`` blank ``Buy``). Skipping blanks here keeps
    the continuation folding from silently missing the executable value line.
    Returns ``None`` when only blanks remain.
    """
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


def _neutralise_multiline_value_lines(lines: list[str], labels: list[str]) -> None:
    """Contain a value line that follows a block-style label-only header.

    A decision header's value normally shares its line. When it does not
    (``**Action**:`` newline ``Buy``), the label line has no value and the next
    physical line is a bare direction word — an executable call that a
    same-line recognizer would miss. Such a bare-direction value line is folded
    into the preceding label line as the canonical ``Hold`` and removed, so the
    stored plan no longer contradicts the authoritative Hold. Only a *bare*
    direction word directly after a recognised label-only header is touched;
    ordinary prose, quoted alternatives and rationale are left intact.
    """
    if len(lines) < 2:
        return
    drop: set[int] = set()
    for index in range(len(lines) - 1):
        if index in drop:
            continue
        norm = unicodedata.normalize("NFKC", lines[index])
        header_label = next(
            (label for label in labels if _line_has_label_without_value(norm, label)),
            None,
        )
        if header_label is None:
            continue
        value_index = _next_nonblank_index(lines, index + 1)
        if value_index is None:
            continue
        value_norm = unicodedata.normalize("NFKC", lines[value_index])
        prefix_match = _MARKUP_PREFIX_RE.match(norm)
        prefix = prefix_match.group("prefix") if prefix_match else ""
        pinned = f"{prefix}**{header_label}**: {HOLD}"
        # A direction value with an explanation (``Buy because valuation is
        # attractive``) keeps that explanation as a rationale tail; a bare
        # direction contributes no tail. A direction value that further carries
        # executable sizing/price text keeps only its rationale clause.
        lead = _DIRECTION_LEAD_RE.match(value_norm)
        if _BARE_DIRECTION_RE.match(value_norm) or lead:
            tail = _safe_decision_tail(_clean_tail(lead.group("tail"))) if lead else ""
            lines[index] = f"{pinned} {tail}" if tail else pinned
        elif (
            _UNSUPPORTED_VALUE_RE.match(value_norm)
            and _RATIONALE_CONNECTOR_RE.search(value_norm) is None
            and not _BLOCKQUOTE_RE.match(value_norm)
        ):
            # Bounded fail-closed policy: an unrecognised, value-like short line in
            # a recognised decision value position (``**Strong Buy**``) is not
            # trusted; the header is pinned to Hold and the value dropped.
            lines[index] = pinned
        else:
            continue
        # Drop the executable value line and any blank lines between it and the
        # label, so no stray decision value remains separated from the pinned Hold.
        for drop_index in range(index + 1, value_index + 1):
            drop.add(drop_index)
    if drop:
        kept = [line for i, line in enumerate(lines) if i not in drop]
        lines[:] = kept


def _leading_command_is_quoted(norm_line: str) -> bool:
    """True when the anchored command verb sits inside a quotation at line start.

    The executable-sentence match is anchored after an optional bullet/number/
    heading prefix. Exemption is *structural*: the line is commentary only when
    the trade verb that the anchor hits is inside a quoted span that begins at (or
    before) the verb. A live command that merely quotes a phrase later --
    ``Buy 100 shares at $100; analyst says "good value"`` -- is NOT exempt. This
    replaces a blanket rationale-keyword/any-quote immunity, which wrongly kept
    anchored commands live when they contained an ``earlier``/``considered``
    keyword or an incidental quotation.
    """
    stripped = norm_line.lstrip()
    # Drop a bullet / numbered / heading prefix the same way the anchor does.
    prefix = re.match(
        r"(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)?[ \t]*(?:\*\*|__|\*|_)?[ \t]*",
        stripped,
    )
    start = prefix.end() if prefix else 0
    verb = re.match(r"[A-Za-z]+", stripped[start:])
    if verb is None:
        return False
    verb_start = start
    for span in _QUOTED_SPAN_RE.finditer(stripped):
        if span.start() <= verb_start < span.end():
            return True
    return False


def _contain_executable_sentences(lines: list[str]) -> None:
    """Fail closed on an executable fill sentence the header grammar misses.

    A blocked plan cannot carry an executable instruction such as ``Buy 100
    shares at $100`` / ``Exit at $120`` / ``Stop at $90`` even when it is plain
    prose rather than a recognised header. Each such physical line is neutralised
    to a non-executable notice so no fill, exit or stop target survives. This is
    deliberately narrow: it requires a direction/exit/stop verb anchored at the
    line start *and* a quantity/price/size token. Exemption is structural only --
    a verb inside a quotation (``"Buy ..."`` quoted as an alternative) or a line
    that leads with prose (``We rejected "Buy ..."`` is un-anchored and never
    matches) is commentary. A genuine live command is contained even when it
    later mentions a rationale keyword or quotes a phrase, and blockquotes and
    already-neutralised lines are skipped.
    """
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        norm = unicodedata.normalize("NFKC", line)
        if _BLOCKQUOTE_RE.match(norm):
            continue
        if _NOT_APPLICABLE in line:
            continue
        if not _EXECUTABLE_SENTENCE_RE.search(norm):
            continue
        if _leading_command_is_quoted(norm):
            continue
        prefix_match = _MARKUP_PREFIX_RE.match(norm)
        prefix = prefix_match.group("prefix") if prefix_match else ""
        lines[index] = (
            f"{prefix}Instruction withheld on a blocked run: no executable "
            "fill, exit, or stop is permitted."
        )


_SIZING_LABEL_NAMES = ("Entry Price", "Stop Loss", "Position Sizing")


def _neutralise_action_sizing(lines: list[str]) -> None:
    """Suppress executable entry/stop/sizing values on a blocked Trader output.

    Handles both the same-line form (``**Entry Price**: $100``) and the
    block-style form (``**Entry Price**:`` newline ``$100``) by folding a bare
    value line into the preceding label-only sizing line as ``not applicable``
    and removing it, so no active price or size survives in the stored plan.
    """
    drop: set[int] = set()
    for index, line in enumerate(lines):
        norm = unicodedata.normalize("NFKC", line)
        recognised = labelled_sizing_tail(norm)
        if recognised is not None:
            label, tail = recognised
            if tail.strip().startswith("not applicable"):
                continue
            prefix_match = _MARKUP_PREFIX_RE.match(norm)
            prefix = prefix_match.group("prefix") if prefix_match else ""
            lines[index] = f"{prefix}**{label}**: {_NOT_APPLICABLE}"
            continue
        # Block-style: a label-only sizing line whose value is on the next line.
        header_label = next(
            (
                label
                for label in _SIZING_LABEL_NAMES
                if _line_has_label_without_value(norm, label)
            ),
            None,
        )
        if header_label is None:
            continue
        value_index = _next_nonblank_index(lines, index + 1)
        if value_index is None:
            continue
        prefix_match = _MARKUP_PREFIX_RE.match(norm)
        prefix = prefix_match.group("prefix") if prefix_match else ""
        lines[index] = f"{prefix}**{header_label}**: {_NOT_APPLICABLE}"
        # Drop the executable value line and any blank lines between it and the
        # label, so a split ``Entry Price:`` blank ``$100`` leaves no active price.
        for drop_index in range(index + 1, value_index + 1):
            drop.add(drop_index)
    if drop:
        lines[:] = [line for i, line in enumerate(lines) if i not in drop]


def _contain_multiline_proposal(lines: list[str]) -> None:
    """Pin a block-style ``FINAL TRANSACTION PROPOSAL:`` whose value is next line.

    ``FINAL TRANSACTION PROPOSAL:`` newline ``BUY 100 shares at $100`` has no
    same-line value, so :func:`_pin_final_transaction_proposal` (which requires a
    value) leaves it. The label-only marker is rewritten to the canonical HOLD
    marker and the following executable value line is removed, so no executable
    proposal survives.
    """
    drop: set[int] = set()
    for index in range(len(lines) - 1):
        if (index + 1) in drop:
            continue
        norm = unicodedata.normalize("NFKC", lines[index])
        if not _line_has_label_without_value(norm, _FINAL_PROPOSAL_LABEL):
            continue
        value_index = _next_nonblank_index(lines, index + 1)
        if value_index is None:
            continue
        prefix_match = _MARKUP_PREFIX_RE.match(norm)
        prefix = prefix_match.group("prefix") if prefix_match else ""
        lines[index] = f"{prefix}FINAL TRANSACTION PROPOSAL: **{HOLD.upper()}**"
        for drop_index in range(index + 1, value_index + 1):
            drop.add(drop_index)
    if drop:
        lines[:] = [line for i, line in enumerate(lines) if i not in drop]


_UNVERIFIED_FACT = "[unverified exact claim omitted]"


def _format_number_candidates(value: Any) -> list[str]:
    """String forms a number might appear as in prose (for a literal match)."""
    if value is None:
        return []
    from decimal import Decimal, InvalidOperation

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return []
    if not decimal_value.is_finite():
        return []
    normalized = format(decimal_value.normalize(), "f")
    with_commas = f"{decimal_value:,.2f}".rstrip("0").rstrip(".")
    out = [normalized, with_commas, str(value).strip()]
    # Also the raw integer part (e.g. 200 instead of 200.13) is too coarse to
    # match safely, so it is deliberately NOT included.
    seen: list[str] = []
    for candidate in out:
        if candidate and candidate not in seen:
            seen.append(candidate)
    return seen


def contain_rejected_exact_claims(text: Any, rejected_claims: list[dict[str, Any]] | None) -> str:
    """Remove a *rejected* exact fact from trusted text; never globally Hold.

    ADR-010: a strong dated numerical claim that failed validation (the cited ID
    is valid but the date/value/unit is wrong) must not remain in the trusted
    plan/report/memory as a verified fact. This is deliberately narrow and
    deterministic:

    - It acts only on a rejected claim whose cited evidence ID **literally appears
      in the same physical line** as the wrong fact; a claim with no visible
      citation is left for the "unverified" narrative label instead.
    - It replaces only the asserted date and/or the asserted numeric value (the
      exact strings the claim carries) with a neutral "unverified" marker, so the
      wrong number/date cannot read as a verified fact. Surrounding qualitative
      prose is preserved untouched.
    - It never rewrites an unrelated line, never touches a verified claim, and
      never turns the whole run into a Hold. An empty ``rejected_claims`` list is
      a no-op (the qualitative/legacy path is byte-for-byte unchanged).
    """
    if not rejected_claims or not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    lines = text.splitlines()
    for entry in rejected_claims:
        if not isinstance(entry, dict) or str(entry.get("status", "")) != "rejected":
            continue
        evidence_ids = [str(e) for e in entry.get("evidence_ids", []) if e]
        if not evidence_ids:
            continue
        date = str(entry.get("date", "") or "")
        numbers = _format_number_candidates(entry.get("value"))
        for index, line in enumerate(lines):
            cites_id = any(eid and eid in line for eid in evidence_ids)
            # Match a rejected exact fact on either (a) the same line citing the
            # evidence ID, or (b) the line carrying BOTH the asserted wrong date and
            # the asserted wrong value (a strong exact-fact fingerprint that cannot
            # be an unrelated qualitative sentence). A lone date or a lone number is
            # never redacted, so ordinary prose is preserved.
            date_present = bool(date) and date in line
            value_present = any(number and number in line for number in numbers)
            if not (cites_id or (date_present and value_present)):
                continue
            new_line = line
            replaced = False
            if date_present:
                new_line = new_line.replace(date, _UNVERIFIED_FACT)
                replaced = True
            if value_present:
                for number in numbers:
                    if number and number in new_line:
                        new_line = new_line.replace(number, _UNVERIFIED_FACT)
                        replaced = True
            if replaced:
                lines[index] = new_line
    return "\n".join(lines)


def rejected_claims_from_state(state: Mapping[str, Any] | Any) -> list[dict[str, Any]]:
    """The rejected exact-claim entries the evaluator persisted, or ``[]``.

    Read from ``investment_debate_state["claim_validation_summary"]["rejected"]``;
    a missing/malformed summary yields an empty list (the qualitative/legacy path
    is unaffected and no trusted text is touched).
    """
    if not isinstance(state, Mapping):
        return []
    debate = state.get("investment_debate_state")
    if not isinstance(debate, Mapping):
        return []
    summary = debate.get("claim_validation_summary")
    if not isinstance(summary, Mapping):
        return []
    rejected = summary.get("rejected")
    if not isinstance(rejected, list):
        return []
    return [entry for entry in rejected if isinstance(entry, dict)]


def contain_rejected_claims_from_state(text: Any, state: Mapping[str, Any] | Any) -> str:
    """Apply :func:`contain_rejected_exact_claims` using the run's rejected claims."""
    return contain_rejected_exact_claims(text, rejected_claims_from_state(state))


# ---------------------------------------------------------------------------
# Fresh, per-boundary exact-fact extraction + validation (ADR-010).
#
# The rejected-claim scrub above only removes facts the DEBATE already rejected.
# A downstream model (Research Manager, Trader, Portfolio) can HALLUCINATE a brand
# new wrong date/amount/unit that never appeared in the debate. This section
# extracts each boundary's OWN exact factual assertions, associates each with a
# cited evidence ID over a BOUNDED multi-line window, re-validates it against the
# state manifest + typed origin metadata, and replaces any NOT-verified fact with
# an explicit unverified marker. It works at CLAUSE/assertion granularity (a
# recommendation word in one clause never exempts a factual clause on the same
# line) and handles MULTIPLE assertions per line. Qualitative prose, genuine
# forward-looking recommendations and target prices are preserved.
# ---------------------------------------------------------------------------

# A citation association window: a fact and its cited evidence ID may be split
# across adjacent lines by wrapping; the window is bounded so a distant citation is
# never borrowed.
_MAX_ASSOC_LINES = 1
_MAX_ASSOC_CHARS = 240

# A cited evidence ID token (``run/.../metric/0``): a slash-path token.
_EVIDENCE_TOKEN_RE = re.compile(r"[\w.\-+/@]*/[\w.\-+/@/]+")

# Clause boundaries within a line: a factual clause is delimited by these so a
# recommendation in one clause never exempts a fact in another. The delimiter is
# KEPT in the emitted text (only the date/value spans are ever blanked).
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[;,.!?])\s+|\s+\b(?:therefore|however|but|while|yet|although|so)\b\s+", re.IGNORECASE)

# Forward-looking / recommendation semantics (a price TARGET is a view, not an
# observation to validate against a record). Applied per CLAUSE only.
_RECOMMENDATION_SEMANTICS_RE = re.compile(
    r"\b(?:price\s+target|target\s+price|price\s+objective|p/?t|forecast|"
    r"projection|projected|estimate[ds]?|guided?\s+to|outlook|expect(?:s|ed)?|"
    r"recommend(?:s|ed|ation)?|rating|upside|downside|fair\s+value|"
    r"we\s+(?:see|expect|forecast|project)|initiate|maintain|upgrade|downgrade|"
    r"model(?:s|ed)?\s+(?:a|to)|should\s+(?:be|reach|hit))\b",
    re.IGNORECASE,
)

# Date/amount detectors. Evidence-ID tokens are masked before matching so digits
# and dates inside an ID are never mistaken for a fact.
_BOUNDARY_DATE_RE = re.compile(r"(?<![\w/.-])(\d{4}-\d{2}-\d{2})(?![\w/.-])")
_BOUNDARY_NUMBER_RE = re.compile(r"(?<![\w/.A-Za-z])([-+]?\d[\d,]*\.?\d*)(?![\w/]|\.[\w])")
_BOUNDARY_UNIT_RE = re.compile(
    r"\b(USD|usd|EUR|eur|GBP|gbp|JPY|jpy|CNY|cny|HKD|hkd|CAD|cad|AUD|aud|CHF|chf|"
    r"shares?|percent|%|pct|million|billion|bn|mn)\b",
    re.IGNORECASE,
)
_GLUED_UNIT_NUMBER_RE = re.compile(
    r"(?i)\b(usd|eur|gbp|jpy|cny|hkd|cad|aud|chf|shares?|percent)\s*(?=\d)"
)


def _mask_evidence_tokens(text: str) -> str:
    """Replace cited-ID tokens with spaces (same length) so digits inside them are
    never mistaken for a date/value. Length is preserved so positions map back."""
    return _EVIDENCE_TOKEN_RE.sub(lambda m: " " * len(m.group(0)), text)


def _normalize_boundary_text(text: str) -> str:
    """NFKC-normalize fullwidth/compat forms and split glued unit+number.

    Both transforms change the string length, which is fine because ALL spans are
    computed on the NORMALIZED text that is emitted; nothing maps back to the raw
    input.
    """
    text = unicodedata.normalize("NFKC", text)
    # ``USD999`` -> ``USD 999`` so the value is extractable.
    return _GLUED_UNIT_NUMBER_RE.sub(lambda m: m.group(1) + " ", text)


def _iter_evidence_tokens(lines: list[str]):
    """Yield ``(line_index, start, end, token)`` for every cited evidence ID."""
    for index, line in enumerate(lines):
        for match in _EVIDENCE_TOKEN_RE.finditer(line):
            token = match.group(0).strip(".,;:()[]{}<>\"'")
            if token and "#" not in token:
                yield index, match.start(), match.end(), token


def _cited_ids_near(
    line_index: int, char_start: int, char_end: int, tokens: list
) -> list[str]:
    """Evidence IDs associated with a span, within the bounded window.

    A token associates when it is on the same line (any position) OR on an adjacent
    line within ``_MAX_ASSOC_LINES`` and no farther than ``_MAX_ASSOC_CHARS`` in a
    rough character distance. This tolerates wrapping while never borrowing a
    distant citation.
    """
    found: list[str] = []
    for t_index, t_start, _t_end, token in tokens:
        if token in found:
            continue
        if t_index == line_index:
            found.append(token)
            continue
        if abs(t_index - line_index) <= _MAX_ASSOC_LINES:
            # Rough distance: lines map to ~1 char each for ordering purposes; use a
            # small penalty per line plus the on-line offset gap.
            gap = abs(t_index - line_index) * 80 + abs(t_start - char_start)
            if gap <= _MAX_ASSOC_CHARS:
                found.append(token)
    return found


def _clause_spans(line: str):
    """Yield ``(start, end)`` spans of clauses in ``line`` (delimiters excluded)."""
    spans = []
    cursor = 0
    for match in _CLAUSE_SPLIT_RE.finditer(line):
        if match.start() > cursor:
            spans.append((cursor, match.start()))
        cursor = match.end()
    if cursor < len(line):
        spans.append((cursor, len(line)))
    return spans


def _unit_and_currency(text: str) -> tuple[str, str]:
    m = _BOUNDARY_UNIT_RE.search(text)
    if not m:
        return "", ""
    unit = m.group(1)
    up = unit.upper()
    currency = up if up in {"USD", "EUR", "GBP", "JPY", "CNY", "HKD", "CAD", "AUD", "CHF"} else ""
    return unit, currency


def _extract_clause_assertions(line: str):
    """Yield ``(date, value, value_unit, date_span, value_span)`` per MAGNITUDE.

    Works on the evidence-masked line so IDs are ignored. EVERY numeric magnitude in
    the clause is paired with the NEAREST date (each VALUE is the subject, not each
    date), so a clause with several amounts — e.g. ``... close was USD 200.13 and
    volume was 999 shares`` — has ALL of them extracted and checked: a correct first
    amount can never launder a second wrong one. A value must have a date to be a
    dated fact; each magnitude also carries its own adjacent unit (if any).
    """
    masked = _mask_evidence_tokens(line)
    date_spans = [(m.start(1), m.end(1), m.group(1)) for m in _BOUNDARY_DATE_RE.finditer(masked)]
    if not date_spans:
        return []
    # Mask the dates, then find every numeric token as a candidate magnitude.
    date_masked = _BOUNDARY_DATE_RE.sub(lambda m: " " * len(m.group(0)), masked)
    values = [
        (m.start(1), m.end(1), m.group(1).replace(",", ""))
        for m in _BOUNDARY_NUMBER_RE.finditer(date_masked)
    ]
    if not values:
        return []
    assertions = []
    for v_start, v_end, v_text in values:
        # Nearest date by character distance (ties -> the preceding date).
        best_date = min(
            date_spans,
            key=lambda d: (abs(d[0] - v_start), 0 if d[1] <= v_start else 1),
        )
        d_start, d_end, d_value = best_date
        # The value's own unit: the nearest unit token on either side of it.
        unit = _nearest_unit(masked, v_start)
        assertions.append((d_value, v_text, unit, (d_start, d_end), (v_start, v_end)))
    return assertions


def _nearest_unit(masked_line: str, value_start: int) -> str:
    """The nearest unit token to a value (within a short window), or ``""``."""
    best = ""
    best_gap = None
    for m in _BOUNDARY_UNIT_RE.finditer(masked_line):
        gap = abs(m.start() - value_start)
        if best_gap is None or gap < best_gap:
            best, best_gap = m.group(1), gap
    return best if (best_gap is not None and best_gap <= 24) else ""


def _has_historical_dated_fact(clause: str, target_date: Any) -> bool:
    """True iff the clause carries a dated fact on-or-before the target date.

    Used to decide whether a recommendation word may exempt a clause: only a
    forward-looking (target/future) recommendation clause is exempt; a clause that
    states a HISTORICAL dated observation (even with "... so I recommend Hold") is a
    fact clause and must be validated. When the target date is unknown, a clause with
    ANY dated fact is treated as historical (fail closed toward checking it).
    """
    from tradingagents.evidence.policy import to_date

    target = to_date(target_date) if target_date else None
    masked = _mask_evidence_tokens(clause)
    for m in _BOUNDARY_DATE_RE.finditer(masked):
        day = to_date(m.group(1))
        if day is None:
            continue
        if target is None or day <= target:
            return True
    return False


def _blank_spans(line: str, spans) -> str:
    """Blank the given ``(start, end)`` spans with the unverified marker."""
    for start, end in sorted(spans, key=lambda s: s[0], reverse=True):
        line = f"{line[:start]}{_UNVERIFIED_FACT}{line[end:]}"
    return line


def _verified_typed_protected_spans(
    lines: list[str],
    *,
    origin_by_id,
    records_by_id,
    target_date,
    expected_symbol,
    expected_run_id,
    duplicate_origin_ids,
) -> dict[int, list[tuple[tuple[int, int], tuple[int, int]]]]:
    """Per-line verified typed claim spans from VERIFIED typed claims.

    Walks each line's strict typed extraction (standalone AND canonical) and, for
    every record that `validate_claim` returns **verified** against the real manifest
    + typed origin, records that occurrence's EXACT date-token and value-token spans
    (from its own ``date=`` / ``value=`` field positions). Authority is applied
    PER TOKEN at the generic prose pass (`_span_is_authorized`): a span exactly equal
    to a verified token is never erased, and an unauthorized span is always blanked,
    independent of heuristic date↔value pairing — so a verified token is not lost
    because the heuristic re-pairs it with a sibling's date, while a wrong (different)
    value/date is still redacted even when heuristically paired to a protected token.
    A rejected/unverified/unparseable/absent typed claim contributes NO protected span,
    so its bytes remain fully checked. Whole lines, matching IDs alone, substring
    matches and the nearest-unit window are deliberately NOT used.
    """
    from tradingagents.debate.claims import extract_claim_span_occurrences, validate_claim

    protected: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] = {}
    if not lines:
        return protected
    for occurrence in extract_claim_span_occurrences("\n".join(lines)):
        if occurrence.date_span is None or occurrence.value_span is None:
            # Cannot prove the exact field positions for THIS occurrence -> do not
            # protect it (fail closed; the prose pass validates it normally).
            continue
        verdict = validate_claim(
            occurrence.record,
            origin_by_id=origin_by_id,
            records_by_id=records_by_id,
            target_date=target_date,
            expected_symbol=expected_symbol,
            expected_run_id=expected_run_id,
            duplicate_origin_ids=duplicate_origin_ids,
        )
        if not verdict.is_verified:
            continue
        # Occurrence-exact: only THIS verified subclaim's own date/value bytes are
        # protected, so an earlier/later sibling with identical date/value but a
        # wrong unit/currency/scale/evidence is never authorized.
        protected.setdefault(occurrence.line_index, []).append(
            (occurrence.date_span, occurrence.value_span)
        )
    return protected


def _span_within(span: tuple[int, int], container: tuple[int, int]) -> bool:
    """True iff ``span`` is fully contained in ``container`` (exact sub-span)."""
    return container[0] <= span[0] and span[1] <= container[1]


def _span_is_authorized(
    span: tuple[int, int],
    protected_pairs: list[tuple[tuple[int, int], tuple[int, int]]],
) -> bool:
    """True iff ``span`` is exactly a verified typed date OR value token span.

    Authorized spans are the verified ``ClaimRecord``'s OWN ``date=``/``value=``
    token positions. A wrong date/value is a DIFFERENT byte span, so it is never
    authorized — even when the generic heuristic pairs it with a protected token.
    Authorization is per-token (independent of the heuristic date↔value pairing), so
    a verified token is never erased merely because the prose scanner re-paired it
    with a sibling's date; and the unprotected partner of a bad pairing is still
    blanked.
    """
    return any(
        _span_within(span, pair_date) or _span_within(span, pair_value)
        for pair_date, pair_value in protected_pairs
    )


def _contain_standalone_typed_claims(
    text: str,
    *,
    origin_by_id,
    records_by_id,
    target_date,
    expected_symbol,
    expected_run_id,
    duplicate_origin_ids,
    provenance,
) -> str:
    """Validate standalone typed ``claim=`` lines in a trusted boundary's text.

    The WHOLE document is walked ONCE through the shared, fence/quote-aware
    :func:`extract_standalone_typed_claims_indexed` (the SAME walk the debate-turn
    parser uses), so a fenced / quoted / illustrative example is never treated as a
    real claim at this boundary and the fence context cannot diverge between callers.

    A typed line is left untouched only when EVERY recovered claim validates as
    ``verified`` (and there is nothing unparseable); otherwise the line is replaced
    by the explicit unverified marker. This applies even when the state carries NO
    evidence manifest: an explicit typed-looking fact with missing evidence is
    REDACTED (missing-evidence/unverified diagnostic), never silently passed through.
    Ordinary non-typed prose is untouched, so a legacy no-typed/no-manifest text is
    a byte-for-byte no-op.
    """
    from tradingagents.debate.claims import (
        extract_standalone_typed_claims_indexed,
        validate_claim,
    )

    extraction, indexed = extract_standalone_typed_claims_indexed(text)
    if extraction.found == 0:
        return text
    lines = text.splitlines()

    def _verified(claim) -> bool:
        return validate_claim(
            claim,
            origin_by_id=origin_by_id,
            records_by_id=records_by_id,
            target_date=target_date,
            expected_symbol=expected_symbol,
            expected_run_id=expected_run_id,
            duplicate_origin_ids=duplicate_origin_ids,
        ).is_verified

    # Group per-line so a line with several claims is redacted only if ANY is not
    # verified (a correct claim can never launder a wrong co-line claim).
    by_line: dict[int, list] = {}
    unparseable_lines: set[int] = set()
    for line_index, _line, record in indexed:
        if record is None:
            unparseable_lines.add(line_index)
            continue
        by_line.setdefault(line_index, []).append(record)

    for line_index in sorted(set(by_line) | unparseable_lines):
        claims = by_line.get(line_index, [])
        line_ok = line_index not in unparseable_lines and all(_verified(c) for c in claims)
        if line_ok:
            continue
        if provenance is not None:
            for claim in claims:
                verdict = validate_claim(
                    claim,
                    origin_by_id=origin_by_id,
                    records_by_id=records_by_id,
                    target_date=target_date,
                    expected_symbol=expected_symbol,
                    expected_run_id=expected_run_id,
                    duplicate_origin_ids=duplicate_origin_ids,
                )
                if not verdict.is_verified:
                    provenance.append(
                        {
                            "reason": verdict.reason,
                            "status": verdict.status,
                            "date": claim.date,
                            "value": claim.value,
                            "evidence_ids": list(claim.evidence_ids),
                            "line": line_index,
                            "boundary": "standalone_typed_claim",
                        }
                    )
            if line_index in unparseable_lines:
                provenance.append(
                    {
                        "reason": "standalone_typed_claim_unparseable",
                        "line": line_index,
                        "boundary": "standalone_typed_claim",
                    }
                )
        if 0 <= line_index < len(lines):
            lines[line_index] = _UNVERIFIED_FACT
    return "\n".join(lines)


def contain_unverified_exact_facts(
    text: Any, state: Mapping[str, Any] | Any, *, provenance: list | None = None
) -> str:
    """Validate each boundary's OWN exact facts; redact any that is not verified.

    Clause/assertion-level and deterministic. For every clause that carries one or
    more exact facts (date + value [+ unit]) and is associated with a cited evidence
    ID over a bounded multi-line window, EACH fact is re-validated against the state
    manifest + typed origin metadata:

    - a ``verified`` fact is kept unchanged;
    - a ``rejected``/``unverified`` fact (wrong date/value/unit, foreign/unknown id,
      ambiguous support) has its date+value spans replaced by an explicit unverified
      marker, so it can never read as a verified fact;
    - a factual clause is NEVER exempted because a *different* clause on the same
      line recommends something (recommendation semantics are judged per clause);
    - a genuine forward-looking recommendation / price-target clause is preserved;
    - an exact fact with NO associated cited id is left untouched (never invent an
      id-less proof).

    When ``provenance`` is supplied it is populated with an auditable record per
    rejected fact. The rejected-debate scrub is also applied. A no-op when the state
    carries no evidence manifest.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = contain_rejected_exact_claims(text, rejected_claims_from_state(state))
    if not isinstance(state, Mapping):
        return out
    records_raw = state.get("data_quality_evidence_records") or []
    if not isinstance(records_raw, list):
        records_raw = []

    from tradingagents.debate.claims import duplicate_origin_id_set, validate_claim
    from tradingagents.evidence.ingest import INGEST_ORIGIN_CONFLICTED_STATE_KEY
    from tradingagents.evidence.origin import origin_records_from_state

    records_by_id = {
        str(r.get("evidence_id", "")): r
        for r in records_raw
        if isinstance(r, Mapping) and r.get("evidence_id")
    }
    origin_by_id = origin_records_from_state(dict(state))
    # Defect-1 (ADR-010 amendment): an id whose origin conflicted/lost trust is
    # unverifiable at the trusted-output boundary too (never silently verified).
    duplicate_origin_ids: set[str] = set()
    for evidence_id in state.get(INGEST_ORIGIN_CONFLICTED_STATE_KEY) or []:
        if isinstance(evidence_id, str) and evidence_id:
            duplicate_origin_ids.add(evidence_id)
    raw_origin = state.get("data_quality_origin_metadata")
    if isinstance(raw_origin, list):
        legacy = []
        for entry in raw_origin:
            if isinstance(entry, Mapping) and "evidence_id" in entry:
                legacy.append(dict(entry))
        duplicate_origin_ids |= duplicate_origin_id_set(legacy)
    target_date = state.get("trade_date")
    expected_symbol = str(state.get("company_of_interest", "") or "")
    expected_run_id = _expected_evidence_run_id(state)

    out = _normalize_boundary_text(out)

    # ADR-010 amendment: a standalone typed ``claim=...`` line in this trusted
    # boundary's OWN text is validated with the SAME shared extractor/validator as
    # a debate turn, using the WHOLE document (fence/quote-aware). This runs even
    # when the state carries NO evidence manifest: an explicit typed-looking fact
    # with missing evidence is redacted as unverified (never silently passed
    # through); ordinary non-typed prose is untouched (legacy no-op).
    out = _contain_standalone_typed_claims(
        out,
        origin_by_id=origin_by_id,
        records_by_id=records_by_id,
        target_date=target_date,
        expected_symbol=expected_symbol,
        expected_run_id=expected_run_id,
        duplicate_origin_ids=duplicate_origin_ids,
        provenance=provenance,
    )

    # The per-clause prose validation needs a real manifest; with none, only the
    # explicit typed lines above are handled (no fabricated id-less checks).
    if not records_by_id:
        return out

    lines = out.splitlines()
    tokens = list(_iter_evidence_tokens(lines))

    # ADR-010 amendment (residual false-redaction repair): a claim whose strict
    # typed record already validated as VERIFIED must not be re-interpreted by the
    # generic prose scanner (which uses a lossy nearest-unit proximity). Its exact
    # date/value field spans are protected; every OTHER assertion — separate prose,
    # same-line tails, and any non-verified typed claim — is still fully validated.
    protected_spans = _verified_typed_protected_spans(
        lines,
        origin_by_id=origin_by_id,
        records_by_id=records_by_id,
        target_date=target_date,
        expected_symbol=expected_symbol,
        expected_run_id=expected_run_id,
        duplicate_origin_ids=duplicate_origin_ids,
    )

    for index, line in enumerate(lines):
        spans_to_blank = []
        protected_pairs = protected_spans.get(index, [])
        for c_start, c_end in _clause_spans(line):
            clause = line[c_start:c_end]
            assertions = _extract_clause_assertions(clause)
            if not assertions:
                continue
            # A recommendation/target clause is forward-looking ONLY when it has no
            # historical (on-or-before-target) dated fact. A clause that recommends
            # ``Hold`` *because* of a historical dated observation is a FACT clause —
            # the recommendation word must not exempt the historical fact.
            if _RECOMMENDATION_SEMANTICS_RE.search(clause) and not _has_historical_dated_fact(
                clause, target_date
            ):
                continue
            # Association is per-clause: cited IDs anywhere on this line or an
            # adjacent line within the bounded window.
            cited = _cited_ids_near(index, c_start, c_end, tokens)
            if not cited:
                for _d, _v, _u, d_sp, v_sp in assertions:
                    abs_d = (c_start + d_sp[0], c_start + d_sp[1])
                    abs_v = (c_start + v_sp[0], c_start + v_sp[1])
                    blank_d = not _span_is_authorized(abs_d, protected_pairs)
                    blank_v = not _span_is_authorized(abs_v, protected_pairs)
                    if provenance is not None and (blank_d or blank_v):
                        provenance.append(
                            {"reason": "unsupported_fact_no_citation",
                             "date": _d, "value": _v, "line": index}
                        )
                    if blank_d:
                        spans_to_blank.append(abs_d)
                    if blank_v:
                        spans_to_blank.append(abs_v)
                continue
            for d_value, v_text, v_unit, d_sp, v_sp in assertions:
                from tradingagents.debate.models import ClaimRecord

                abs_date_span = (c_start + d_sp[0], c_start + d_sp[1])
                abs_value_span = (c_start + v_sp[0], c_start + v_sp[1])
                # Per-token exact-span authority: a VERIFIED typed date/value token is
                # never erased (even if the heuristic re-pairs it with a sibling). An
                # UNAUTHORIZED span is always blanked below, regardless of pairing.
                date_authorized = _span_is_authorized(abs_date_span, protected_pairs)
                value_authorized = _span_is_authorized(abs_value_span, protected_pairs)
                if date_authorized and value_authorized:
                    continue
                unit, currency = _unit_and_currency(v_unit) if v_unit else ("", "")
                claim = ClaimRecord(
                    evidence_ids=cited,
                    metric="",
                    date_role="observation_date",
                    date=d_value,
                    value=v_text,
                    unit=unit,
                    currency=currency,
                )
                verdict = validate_claim(
                    claim,
                    origin_by_id=origin_by_id,
                    records_by_id=records_by_id,
                    target_date=target_date,
                    expected_symbol=expected_symbol,
                    expected_run_id=expected_run_id,
                    duplicate_origin_ids=duplicate_origin_ids,
                )
                if verdict.is_verified:
                    continue
                # Blank only the UNAUTHORIZED component(s): a verified token is never
                # removed because its heuristic partner failed.
                blanked = False
                if not date_authorized:
                    spans_to_blank.append(abs_date_span)
                    blanked = True
                if not value_authorized:
                    spans_to_blank.append(abs_value_span)
                    blanked = True
                if provenance is not None and blanked:
                    provenance.append(
                        {"reason": verdict.reason, "status": verdict.status,
                         "date": d_value, "value": v_text, "evidence_ids": cited,
                         "line": index}
                    )
        if spans_to_blank:
            lines[index] = _blank_spans(line, spans_to_blank)

    # Second pass: a date and its value may be SPLIT across adjacent lines by
    # wrapping (``On 2026-05-05`` / ``the close was 999 USD <id>``). Pair a line's
    # date with the nearest value on an adjacent line (within the window) and
    # validate it; blank both spans on a non-verified fact.
    lines = _contain_cross_line_facts(
        lines,
        tokens=_iter_evidence_tokens(lines),
        origin_by_id=origin_by_id,
        records_by_id=records_by_id,
        target_date=target_date,
        expected_symbol=expected_symbol,
        expected_run_id=expected_run_id,
        duplicate_origin_ids=duplicate_origin_ids,
        provenance=provenance,
        protected_spans=protected_spans,
    )
    return "\n".join(lines)


def _contain_cross_line_facts(
    lines: list[str],
    *,
    tokens,
    origin_by_id,
    records_by_id,
    target_date,
    expected_symbol,
    expected_run_id,
    duplicate_origin_ids,
    provenance,
    protected_spans: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] | None = None,
) -> list[str]:
    """Validate date/value facts whose date and value are on ADJACENT lines."""
    from tradingagents.debate.claims import validate_claim
    from tradingagents.debate.models import ClaimRecord

    tokens = list(tokens)
    protected_spans = protected_spans or {}
    for index, line in enumerate(lines):
        masked = _mask_evidence_tokens(line)
        if not _BOUNDARY_DATE_RE.search(masked):
            continue
        # Only lines whose local clause has a DATE but NO local value are candidates
        # (a both-on-line fact was already handled).
        date_masked = _BOUNDARY_DATE_RE.sub(lambda m: " " * len(m.group(0)), masked)
        if _BOUNDARY_NUMBER_RE.search(date_masked):
            continue
        date_match = _BOUNDARY_DATE_RE.search(masked)
        cited = _cited_ids_near(index, date_match.start(), date_match.end(), tokens)
        if not cited:
            continue
        # Find the nearest value on an adjacent line within the window.
        value_line = None
        value_span = None
        for j in (index + 1, index - 1):
            if not (0 <= j < len(lines)) or abs(j - index) > _MAX_ASSOC_LINES:
                continue
            nmasked = _mask_evidence_tokens(lines[j])
            nmasked_no_date = _BOUNDARY_DATE_RE.sub(lambda m: " " * len(m.group(0)), nmasked)
            vm = _BOUNDARY_NUMBER_RE.search(nmasked_no_date)
            if vm:
                value_line, value_span = j, (vm.start(1), vm.end(1))
                break
        if value_line is None:
            continue
        if _RECOMMENDATION_SEMANTICS_RE.search(line) and not _has_historical_dated_fact(
            line, target_date
        ):
            continue
        # Cross-line per-token authority: a verified date (on this line) or value
        # (on its own line) is never erased; only UNAUTHORIZED components are blanked.
        date_span_abs = (date_match.start(1), date_match.end(1))
        date_protected = _span_is_authorized(
            date_span_abs, protected_spans.get(index, [])
        )
        value_protected = _span_is_authorized(
            (value_span[0], value_span[1]), protected_spans.get(value_line, [])
        )
        if date_protected and value_protected:
            continue
        value_text = _mask_evidence_tokens(lines[value_line])[
            value_span[0]:value_span[1]
        ].replace(",", "")
        unit, currency = _unit_and_currency(line + " " + lines[value_line])
        claim = ClaimRecord(
            evidence_ids=cited,
            metric="",
            date_role="observation_date",
            date=date_match.group(1),
            value=value_text,
            unit=unit,
            currency=currency,
        )
        verdict = validate_claim(
            claim,
            origin_by_id=origin_by_id,
            records_by_id=records_by_id,
            target_date=target_date,
            expected_symbol=expected_symbol,
            expected_run_id=expected_run_id,
            duplicate_origin_ids=duplicate_origin_ids,
        )
        if verdict.is_verified:
            continue
        # Blank only the UNAUTHORIZED component(s).
        if not date_protected:
            lines[index] = _blank_spans(lines[index], [date_span_abs])
        if not value_protected:
            lines[value_line] = _blank_spans(lines[value_line], [value_span])
        if provenance is not None and (not date_protected or not value_protected):
            provenance.append(
                {"reason": verdict.reason, "status": verdict.status,
                 "date": date_match.group(1), "value": value_text,
                 "evidence_ids": cited, "line": index, "value_line": value_line}
            )
    return lines


def _expected_evidence_run_id(state: Mapping[str, Any]) -> str | None:
    """The reproducible gate/evidence run id for this state (or ``None``)."""
    try:
        from tradingagents.dataflows.symbol_utils import normalize_symbol
        from tradingagents.graph.data_quality_gate import build_gate_run_id
    except Exception:  # noqa: BLE001 — a missing helper never blocks the guard
        return None
    symbol = str(state.get("company_of_interest", "") or "")
    trade_date = str(state.get("trade_date", "") or "")
    if not symbol or not trade_date:
        return None
    try:
        return build_gate_run_id(trade_date, normalize_symbol(symbol))
    except Exception:  # noqa: BLE001
        return None


def enforce_trusted_boundary(
    text: Any, state: Mapping[str, Any] | Any, *, provenance: list | None = None
) -> str:
    """The single trusted-boundary enforcement used at every plan/decision/report.

    Combines the rejected-debate scrub with a fresh per-boundary extraction +
    validation of this boundary's OWN exact facts (ADR-010). Ordinary qualitative
    text and recommendations/target prices are preserved. When ``provenance`` is
    supplied it is populated with an auditable record per rejected fact.
    """
    return contain_unverified_exact_facts(text, state, provenance=provenance)


def enforce_blocked_conclusion(text: Any, *, field: str) -> str:
    """Pin a blocked run's decision field to a non-directional Hold.

    ``text`` is the rendered (structured or free-text) agent output; ``field``
    is one of ``recommendation``, ``rating``, or ``action``. Every recognized
    decision header is rewritten (not just the first), and every
    ``FINAL TRANSACTION PROPOSAL`` line is pinned for the action field, so a
    repeated or trailing directional call can never survive. Markdown
    bullet/header/value markup is tolerated around the decision field only, so
    ordinary rationale prose is never rewritten. A response that omitted the
    decision header entirely gets an authoritative Hold prepended.

    For the action field, a narrow documented rule also neutralises executable
    entry/stop/position-sizing values (a Hold cannot carry a fill instruction);
    the quoted rationale is preserved.

    The function is idempotent: guarding an already-guarded text returns it
    unchanged.
    """
    if field not in _FIELD_LABELS:
        raise ValueError(f"unknown decision field: {field!r}")

    body = text if isinstance(text, str) else ""

    lines = body.splitlines()
    # 1) Pin same-line decision headers, then fold block-style label-only headers
    #    whose bare direction value sits on the next physical line.
    found = _pin_field_lines(lines, field)
    labels = [_FIELD_LABELS[field]] + [
        other for other in _FIELD_LABELS.values() if other != _FIELD_LABELS[field]
    ]
    _neutralise_multiline_value_lines(lines, labels)
    # 2) The compatibility marker and the sizing fields are pinned regardless of
    #    whether a primary decision header was found (a free-text answer may omit
    #    the header yet still end with "FINAL TRANSACTION PROPOSAL: **BUY**").
    if field == "action":
        _pin_final_transaction_proposal(lines)
        _contain_multiline_proposal(lines)
        _neutralise_action_sizing(lines)
        # 3) Fail closed on any remaining unsupported executable fill sentence.
        _contain_executable_sentences(lines)

    result = "\n".join(lines).strip()
    if not found:
        label = _FIELD_LABELS[field]
        result = (
            f"**{label}**: {HOLD}\n\n"
            "Note: this run was blocked by the Data Quality Gate; only an "
            "evidence-insufficient conclusion is permitted.\n\n"
            + result
            + "\n\n" + _NOTE
        )
        return result

    if _NOTE not in result:
        result = result + "\n\n" + _NOTE
    return result
