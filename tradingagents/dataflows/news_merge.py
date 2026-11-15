"""Combine the two news providers into one analyst-facing block, honestly.

Why a separate module
---------------------
Finnhub and GDELT do *not* serve the same thing and must not be merged as two
interchangeable feeds:

* **Finnhub** is asked about a specific ``symbol``. It is the primary source for
  company news, and its ``AUTH_MISSING`` / ``RATE_LIMITED`` / ``HTTP_ERROR``
  outcomes say something about the *credential or service*.
* **GDELT** is a keyless discovery index queried by text. It supplies global,
  industry and macro coverage, and every article's publisher timestamp is
  re-verified before it is admitted.

So the merge is a **union of two independently-classified sections**, not a
concatenation of raw payloads. Each section carries its own status, and the
overall status is derived by :func:`combine_status`.

Status rules (the part that must never lie)
-------------------------------------------
* ``AVAILABLE`` never means the news is positive — only that real, PIT-verified
  articles reached the analyst.
* ``UNAVAILABLE`` never means there is no bad news — only that no real article
  reached the analyst.
* ``UNKNOWN`` is never ``NEUTRAL``; it is the absence of a defensible read.
* One source failing does **not** make the node unavailable. If Finnhub fails and
  GDELT succeeds, the result is ``PARTIAL`` and the failure is stated for
  Finnhub alone.
* Both failing is reported as unavailable *with both reasons*, never as an empty
  news day.
* A genuine empty answer (``EMPTY_VALID``) is a fact about the instrument and is
  kept distinct from a request that failed.
"""

from __future__ import annotations

import re

from .news_status import ABSENCE_CLASSES as _ABSENCE_CLASSES
from .news_status import PROVES_REAL_NEWS, NewsStatus, is_status_token

__all__ = ["ProviderOutcome", "combine_status", "merge_news_sections"]

#: Markers every vendor uses to say "no usable company news". Mirrors
#: ``schemas._NEWS_UNAVAILABLE_MARKERS``; kept local so this module has no
#: import cycle with the agent layer.
_NO_NEWS_MARKERS = (
    "DATA_UNAVAILABLE",
    "NO_DATA_AVAILABLE",
    "no news found",
    "only serves newer items",
    "unavailable for",
)

_STATUS_TOKEN = re.compile(r"^[ \t]*NEWS_STATUS=([A-Z_]+)", re.MULTILINE)

#: Only a *rendered article* proves content. Vendors emit one ``### Title
#: (source: ...)`` block per article, which is the same rule
#: ``schemas._has_news_body`` applies.
_ARTICLE_LINE = re.compile(r"^\s*###\s+\S", re.MULTILINE)


class ProviderOutcome:
    """One provider's contribution: rendered text plus its classified status."""

    __slots__ = ("provider", "text", "status", "detail")

    def __init__(self, provider: str, text: str, status: NewsStatus | None = None,
                 detail: str = ""):
        self.provider = provider
        self.text = (text or "").strip()
        self.detail = detail
        self.status = status if status is not None else _classify(self.text)

    @property
    def has_articles(self) -> bool:
        return bool(_ARTICLE_LINE.search(self.text))

    @property
    def proves_real_news(self) -> bool:
        """True only when real, PIT-filtered articles are present."""
        return self.status in PROVES_REAL_NEWS and self.has_articles

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"ProviderOutcome({self.provider!r}, status={self.status}, "
                f"articles={self.has_articles})")


def _classify(text: str) -> NewsStatus:
    """Infer one provider's status from its rendered text.

    Order matters. An emitted ``NEWS_STATUS=`` line is authoritative when
    present, and a rendered article outranks any prose marker: a real headline
    may legitimately contain phrases like "unavailable for" ("Nvidia says cloud
    service is unavailable for Europe customers"), and scanning the whole
    article body for those markers turned a successful answer into a false
    "no articles were published" claim. Markers are therefore only consulted
    when no article is present.
    """
    text = text or ""
    tokens = _STATUS_TOKEN.findall(text)
    if tokens:
        if "SUCCESS_REAL_CONTENT" in tokens:
            return NewsStatus.SUCCESS_REAL_CONTENT
        if _ARTICLE_LINE.search(text):
            # Articles are attached despite the token: the provider answered
            # with content, so the article wins over a status it prefixed.
            return NewsStatus.SUCCESS_REAL_CONTENT
        # First non-success token is the specific reason the vendor gave.
        for token in tokens:
            if token != "SUCCESS_REAL_CONTENT":
                try:
                    return NewsStatus(token)
                except ValueError:
                    return NewsStatus.PARSE_ERROR
    if not text.strip():
        return NewsStatus.EMPTY_VALID
    if _ARTICLE_LINE.search(text):
        return NewsStatus.SUCCESS_REAL_CONTENT
    if any(marker in text for marker in _NO_NEWS_MARKERS):
        return NewsStatus.EMPTY_VALID
    if is_status_token(text):
        return NewsStatus.PARSE_ERROR
    return NewsStatus.EMPTY_VALID


def combine_status(outcomes) -> NewsStatus:
    """Overall status for a set of provider outcomes.

    * Every provider proves real content -> ``SUCCESS_REAL_CONTENT``.
    * Some do, some do not -> ``SUCCESS_REAL_CONTENT`` as well, because real news
      *did* reach the analyst. This is not a false positive: the caller renders
      each provider's own status next to its section, so the outage stays
      visible instead of being averaged away. See :func:`merge_news_sections`.
    * None do -> ``EMPTY_VALID`` **only when every** provider actually answered and
      had nothing. If any provider failed, the failure is reported instead: one
      provider saying "nothing" says nothing about the half of coverage the
      other provider failed to deliver, so calling that a genuine absence would
      hide an outage behind an affirmative claim about the instrument (audit
      M-1). Otherwise the first provider's failure is reported.
    """
    outcomes = [o for o in outcomes if o is not None]
    if not outcomes:
        return NewsStatus.EMPTY_VALID
    if any(o.proves_real_news for o in outcomes):
        return NewsStatus.SUCCESS_REAL_CONTENT
    if all(o.status is NewsStatus.EMPTY_VALID for o in outcomes):
        return NewsStatus.EMPTY_VALID
    # No articles anywhere and at least one provider did not answer: surface the
    # failure, not the other provider's emptiness.
    for outcome in outcomes:
        if outcome.status not in _ABSENCE_CLASSES:
            return outcome.status
    return outcomes[0].status


def _section(outcome: ProviderOutcome) -> str:
    """Render one provider's section with an explicit status header.

    Headers are ``####`` and bold, never ``###``: ``### `` is the article-line
    marker every downstream consumer uses to count real records
    (``schemas._has_news_body``, ``ProviderOutcome.has_articles``). A provider
    header rendered as ``###`` would be miscounted as an article and could make
    an empty window look like news.
    """
    label = outcome.provider
    if outcome.has_articles:
        return f"#### {label} — verified articles in window\n\n{outcome.text}"
    return (
        f"#### {label} — no usable company news (status: {outcome.status.value})"
        f"\n\n{outcome.text}"
    ).rstrip()


def _article_blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split rendered text into its preamble and ``(key, block)`` article blocks.

    An article block starts at a ``### `` line and runs until the next one. The
    key is the article's ``Link:`` URL when present, else the headline, so the
    same story arriving from two providers compares equal.
    """
    lines = (text or "").splitlines()
    preamble: list[str] = []
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    started = False
    for line in lines:
        if _ARTICLE_LINE.match(line):
            if started and current:
                blocks.append(_block_of(current))
            current = [line]
            started = True
        elif started:
            current.append(line)
        else:
            preamble.append(line)
    if started and current:
        blocks.append(_block_of(current))
    return "\n".join(preamble).strip(), blocks


def _block_of(lines: list[str]) -> tuple[str, str]:
    block = "\n".join(lines).strip()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Link:"):
            return _url_key(stripped[5:].strip()), block
    # No link: fall back to the headline so a repeated title still collapses.
    return _url_key(lines[0].removeprefix("###").strip()), block


#: Query parameters that carry *tracking* only. They are dropped from the dedup
#: key so the same story from two feeds matches. Every other parameter is
#: identity-bearing and is kept: Finnhub serves articles as
#: ``https://finnhub.io/api/news?id=<hash>``, so stripping the whole query
#: collapsed all 20 articles of one ticker onto a single key and 19 of them were
#: wrongly reported as duplicates (live run, 2026-11-15).
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "cmpid", "ncid", "ref", "ref_src", "src",
})


def _url_key(value: str) -> str:
    """Canonical key for a URL/headline.

    Scheme, ``www.``, trailing slash and *tracking-only* query parameters are
    dropped; identity-bearing parameters are preserved so two distinct stories
    never compare equal.
    """
    key = (value or "").strip().lower()
    key = re.sub(r"^https?://", "", key)
    key = re.sub(r"^www\.", "", key)
    path, _, query = key.partition("?")
    kept = [
        part for part in query.split("&")
        if part and part.partition("=")[0] not in _TRACKING_PARAMS
    ]
    path = path.rstrip("/")
    return f"{path}?{'&'.join(sorted(kept))}" if kept else path


def _strip_document_header(preamble: str) -> str:
    """Remove a provider's own ``## …`` document header from a merged section.

    Each provider renders a top-level ``## <ticker> News, from …`` heading. Once
    merged, the merged block already carries that heading, so keeping the inner
    one would nest a second document inside the section.
    """
    lines = [
        line for line in (preamble or "").splitlines()
        if not line.lstrip().startswith("## ")
    ]
    return "\n".join(lines).strip()


def merge_news_sections(outcomes, *, ticker: str = "", start_date: str = "",
                        end_date: str = "") -> str:
    """Merge one or more provider outcomes into one labelled block.

    The output keeps the ``### <article>`` article lines the News Analyst and
    ``classify_news_source_availability`` already recognise, so real news from
    any provider registers as news. Each provider's own status and reason is
    stated in a section header, so a single-source outage is visible as such and
    is never mistaken for an absence of news.

    The provenance line lists only the providers actually merged, so a
    single-provider (Finnhub-only) block never claims a second feed.

    An article whose URL (or, failing that, headline) already appeared in an
    earlier provider's section is dropped from the later one and counted in that
    section's header: the same story served by both feeds is one piece of
    evidence, not two (audit finding, 2026-11-15).
    """
    outcomes = [o for o in outcomes if o is not None]
    overall = combine_status(outcomes)
    # Provenance must describe what was actually asked, never a fixed pair:
    # the Finnhub-only scope merges a single provider and a hard-coded
    # "Finnhub + GDELT" line would misreport the experiment's data source.
    sources = [o.provider for o in outcomes if o.provider]
    if not sources:
        provenance = "no news provider"
    elif len(sources) == 1:
        provenance = f"{sources[0]} company news"
    else:
        provenance = f"{sources[0]} company news + {' + '.join(sources[1:])} discovery"
    head = [f"## {ticker} News, from {start_date} to {end_date} "
            f"({provenance}, publish time verified per article).",
            "",
            f"Overall status: {overall.value}"]
    if not any(o.proves_real_news for o in outcomes):
        # Nothing real anywhere: state every reason.
        reasons = "; ".join(f"{o.provider}: {o.status.value}" for o in outcomes)
        if overall is NewsStatus.EMPTY_VALID:
            # Every provider answered, and the answer was "nothing in this
            # window". That is a real absence, so no unavailable marker: adding
            # one would disguise emptiness as an outage.
            head += [
                f"NEWS_STATUS={overall.value}: no {ticker} articles were published "
                f"in this window ({reasons}). This is a genuine absence of news for "
                "the window, not a retrieval failure.",
                "",
            ]
        else:
            # ``DATA_UNAVAILABLE`` is the marker ``schemas`` / ``macro_data_tools``
            # already recognise as "could not be retrieved": without it a reader
            # could treat the block as an ordinary answer. The wording must not
            # say "every provider failed" when one merely answered "empty": the
            # per-provider reasons are what the reader acts on.
            failed = [
                f"{o.provider} ({o.status.value})"
                for o in outcomes
                if o.status not in _ABSENCE_CLASSES
            ]
            answered_empty = [
                f"{o.provider} ({o.status.value})"
                for o in outcomes
                if o.status in _ABSENCE_CLASSES
            ]
            detail = (
                f"DATA_UNAVAILABLE: {', '.join(failed)} could not answer"
                if failed else "DATA_UNAVAILABLE: no provider delivered articles"
            )
            if answered_empty:
                detail += (
                    f", and {', '.join(answered_empty)} answered with no usable "
                    "articles"
                )
            head += [
                f"NEWS_STATUS={overall.value}: no verifiable {ticker} news reached "
                f"this window from {'the configured provider' if len(outcomes) == 1 else 'any provider'} "
                f"({reasons}). "
                f"{detail}. This is not a confirmed absence of news about the "
                "instrument; report news as unavailable rather than neutral.",
                "",
            ]
    elif not all(o.proves_real_news for o in outcomes):
        # Distinguish an outage from an answered-but-empty provider: GDELT
        # returning EMPTY_VALID did answer, and saying it "could not answer"
        # would be simply false. Both cases still mean reduced coverage.
        parts = []
        for o in outcomes:
            if o.proves_real_news:
                continue
            if o.status in _ABSENCE_CLASSES:
                parts.append(f"{o.provider}: answered, no usable articles "
                             f"({o.status.value})")
            else:
                parts.append(f"{o.provider}: could not answer ({o.status.value})")
        head += [
            f"Partial coverage — {'; '.join(parts)}. The articles below come only "
            "from the provider(s) with content; do not read the rest as 'no news'.",
            "",
        ]
    # Cross-provider dedup: an article already rendered by an earlier provider
    # is not repeated, and the count of dropped duplicates is disclosed in that
    # provider's section header so the analyst is never misled about coverage.
    # Deduplication is strictly *between* providers: a provider's own repeated
    # key is its own content and is kept (Finnhub's link form once collapsed all
    # of one ticker's articles onto one key, and 19 were wrongly dropped as
    # "served by another provider"; live run, 2026-11-15).
    seen_keys: set[str] = set()
    sections: list[str] = []
    for outcome in outcomes:
        if outcome.has_articles:
            preamble, blocks = _article_blocks(outcome.text)
            kept: list[str] = []
            own_keys: set[str] = set()
            dropped = 0
            for key, block in blocks:
                if key and key in seen_keys and key not in own_keys:
                    dropped += 1
                    continue
                if key:
                    own_keys.add(key)
                kept.append(block)
            seen_keys.update(own_keys)
            text = ("\n\n".join(kept)).strip()
            # A provider renders its own document header (``## … News``); inside
            # a merged section that header is redundant and nests a second
            # document, so only the counts/notes below it are kept.
            preamble = _strip_document_header(preamble)
            if preamble:
                text = f"{preamble}\n\n{text}" if text else preamble
            note = (f" ({dropped} duplicate article(s) also served by another "
                    f"provider were not repeated)" if dropped else "")
            if kept:
                sections.append(
                    f"#### {outcome.provider} — verified articles in window{note}"
                    f"\n\n{text}"
                )
            else:
                # Its only articles were already shown, so this section has no
                # evidence of its own; do not borrow a status for the header.
                sections.append(
                    f"#### {outcome.provider} — no unique articles beyond the "
                    f"providers above{note}\n\n{text}"
                )
        else:
            sections.append(_section(outcome))
    body = "\n\n".join(sections)
    return "\n".join(head) + "\n" + body.rstrip() + "\n"
