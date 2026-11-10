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
