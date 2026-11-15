"""Shared, conservative company-relevance test for every news provider.

Why this is a separate module
-----------------------------
Finnhub and GDELT both *claim* to return news about a specific company, and both
claims were measured to be unreliable:

* Finnhub's ``related`` field lists every company a piece mentions, so a sector
  round-up carries ``related="NVDA"`` while being about the industry. Measured
  on 2026-11-15, the live NVDA/AAPL/JPM/XOM feeds contained such rows.
* GDELT matches on free text, so a query for a ticker returns anything that
  merely names the sector.

Both providers therefore share one rule, so a "relevant" article means the same
thing no matter which vendor produced it.

The rule, in order of strength
------------------------------
1. **Ticker in the headline or URL slug** — the strongest signal, and the only
   one that uses no external data. ``$NVDA`` and ``NYSE:NVDA`` count; a bare
   occurrence inside a longer word does not (``NVDAX`` is a different fund).
2. **Company name / alias from :data:`COMPANY_NAMES`** — ``Nvidia``, ``JPMorgan
   Chase``, ``Apple Inc``. This keeps genuinely relevant stories whose headline
   uses the name rather than the symbol, e.g. "Exxon signals higher output".
3. **Summary mentioning the company name AND a company-specific subject** — the
   weaker body rule, used only when the headline is generic. It requires the
   name and at least one distinctive term so a passing mention in a market wrap
   ("Apple was among the decliners") does not qualify an unrelated piece.

What is deliberately *not* used
-------------------------------
* ``related`` alone is never sufficient — it is kept on the record as metadata.
* For short symbols (``F``, ``T``, ``V``, ``C``, ``K``, ``M``, ``A``) a bare
  case-insensitive substring match would hit ordinary English ("Fed", "to",
  "we"). Those symbols must appear as ``$T``, ``T:US``, ``(T)``, or be the whole
  headline word — otherwise only the company-name rule applies.
"""

from __future__ import annotations

import re
from functools import lru_cache

__all__ = ["COMPANY_NAMES", "company_name", "is_about_company", "ticker_patterns"]

#: Longest symbol that is still treated as "short" and therefore requires a
#: delimited match rather than a plain substring.
_SHORT_SYMBOL = 2

#: Company names, legal suffixes and common short forms per ticker. The first
#: entry is the display name; the rest are aliases. Only names that unambiguously
#: denote *this* company belong here.
COMPANY_NAMES: dict[str, tuple[str, ...]] = {
    "NVDA": ("NVIDIA", "Nvidia", "NVIDIA Corporation"),
    "AAPL": ("Apple", "Apple Inc", "Apple Computer"),
    "MSFT": ("Microsoft", "Microsoft Corp", "Microsoft Corporation"),
    "AMZN": ("Amazon", "Amazon.com", "Amazon Inc"),
    "GOOGL": ("Alphabet", "Google", "Google LLC"),
    "GOOG": ("Alphabet", "Google", "Google LLC"),
    "META": ("Meta Platforms", "Meta", "Facebook"),
    "TSLA": ("Tesla", "Tesla Inc", "Tesla Motors"),
    "JPM": ("JPMorgan", "JPMorgan Chase", "JP Morgan", "J.P. Morgan", "Morgan Chase",
            "JPMorganChase", "Chase"),
    "XOM": ("Exxon", "Exxon Mobil", "ExxonMobil"),
    "CVX": ("Chevron", "Chevron Corp", "Chevron Corporation"),
    "BAC": ("Bank of America", "BofA"),
    "WFC": ("Wells Fargo",),
    "C": ("Citigroup", "Citi", "Citibank"),
    "GS": ("Goldman Sachs", "Goldman"),
    "MS": ("Morgan Stanley",),
    "V": ("Visa Inc", "Visa"),
    "MA": ("Mastercard", "MasterCard"),
    "INTC": ("Intel", "Intel Corp", "Intel Corporation"),
    "AMD": ("Advanced Micro Devices", "AMD"),
    "TSM": ("Taiwan Semiconductor", "TSMC"),
    "AVGO": ("Broadcom",),
    "QCOM": ("Qualcomm",),
    "MU": ("Micron", "Micron Technology"),
    "ASML": ("ASML", "ASML Holding"),
    "NFLX": ("Netflix",),
    "DIS": ("Walt Disney", "Disney"),
    "KO": ("Coca-Cola", "Coca Cola"),
    "PEP": ("PepsiCo", "Pepsi"),
    "MCD": ("McDonald's", "McDonalds"),
    "NKE": ("Nike",),
    "SBUX": ("Starbucks",),
    "WMT": ("Walmart", "Wal-Mart"),
    "COST": ("Costco",),
    "HD": ("Home Depot", "Home Depot Inc"),
    "TGT": ("Target Corp",),
    "BA": ("Boeing", "Boeing Co"),
    "CAT": ("Caterpillar",),
    "GE": ("General Electric", "GE Aerospace"),
    "F": ("Ford", "Ford Motor"),
    "GM": ("General Motors",),
    "T": ("AT&T", "AT and T", "AT&T Inc"),
    "VZ": ("Verizon",),
    "TMUS": ("T-Mobile", "T Mobile"),
    "ORCL": ("Oracle",),
    "CRM": ("Salesforce",),
    "ADBE": ("Adobe",),
    "IBM": ("IBM", "International Business Machines"),
    "CSCO": ("Cisco",),
    "PYPL": ("PayPal",),
    "UBER": ("Uber",),
    "ABNB": ("Airbnb",),
    "COIN": ("Coinbase",),
    "PLTR": ("Palantir",),
    "SNOW": ("Snowflake",),
    "SHOP": ("Shopify",),
    "BRK.B": ("Berkshire Hathaway", "Berkshire"),
    "LLY": ("Eli Lilly", "Lilly"),
    "PFE": ("Pfizer",),
    "MRK": ("Merck",),
    "JNJ": ("Johnson & Johnson", "Johnson and Johnson", "J&J"),
    "ABBV": ("AbbVie",),
    "UNH": ("UnitedHealth", "United Health"),
    "CVS": ("CVS Health", "CVS"),
}

#: Companies that appear often as the *subject* of a story that merely mentions
#: one of ours. They are not targets of this pipeline, so they are not in
#: :data:`COMPANY_NAMES`; they exist only so the co-mention guard can tell
#: "Samsung ships more phones than Apple" apart from an Apple story.
#:
#: Every entry was observed leading a real feed headline during live validation
#: (2026-09-15..2026-11-15). The list need not be exhaustive to be useful: it
#: only *increases* precision, and a miss degrades to the previous behaviour.
_OTHER_COMPANIES: tuple[str, ...] = (
    "IonQ", "Rigetti", "D-Wave", "Samsung", "SK Hynix", "CoreWeave", "Nebius",
    "SentinelOne", "Twist Bioscience", "Rackspace", "Dollar General", "Paychex",
    "Royal Caribbean", "General Mills", "Texas Instruments", "Lucid",
    "Wendy's", "CrowdStrike", "Arm Holdings", "Marvell", "Analog Devices",
    "Applied Materials", "Lam Research", "KLA", "ON Semiconductor",
    "Nokia", "Ericsson", "Alibaba", "Tencent", "Baidu", "JD.com", "BYD",
    "Toyota", "Honda", "Volkswagen", "Mercedes-Benz", "BMW", "Stellantis",
    "Boeing", "Lockheed Martin", "RTX", "Northrop Grumman", "Qualcomm",
    "Aramco", "Saudi Aramco", "ConocoPhillips", "Valero", "Hess", "Credo",
    "Huawei", "Enterprise Products", "Phillips 66", "Eni", "BP", "Occidental",
    "Devon Energy", "Diamondback Energy", "SLB", "Halliburton", "Schlumberger",
    "Shopify", "Spotify", "Block Inc", "Affirm", "Robinhood",
    "United Airlines", "Delta Air Lines", "Airbnb", "Booking Holdings",
    "Pfizer", "Moderna", "Novavax", "Viking Therapeutics",
    "Ultragenyx", "Regeneron", "Vertex Pharmaceuticals", "Biogen",
    "Anthropic", "OpenAI", "xAI", "SpaceX", "ByteDance",
    "Walmart", "Costco", "Kroger", "Dollar Tree", "Best Buy",
    "Goldman Sachs", "Citadel", "BlackRock", "Vanguard", "State Street",
    "NextEra Energy", "Constellation Energy", "Vistra", "Entergy",
)

#: Terms that make a *body* mention substantive. A market wrap that merely lists
#: a company among movers contains none of these.
#:
#: Deliberately excluded (measured as pure noise, 2026-09-22 live sample): ``ai``,
#: ``stock``, ``shares``, ``investment``, ``analyst``, ``valuation``, ``trading``.
#: Every market-wide piece contains them, so they proved a company's relevance
#: only about as often as they killed it — three separate AI-trade round-ups were
#: admitted solely on ``ai`` + ``stock``. What remains is language that describes
#: *a particular company's* affairs.
_SUBJECT_TERMS = (
    "earnings", "revenue", "guidance", "forecast", "outlook", "profit", "results",
    "beat", "beats", "miss", "misses", "raised", "lowered", "slashed",
    "quarter", "quarterly", "fiscal", "sales", "margin", "buyback", "dividend",
    "ceo", "cfo", "acquisition", "acquirer", "merger", "acquire", "lawsuit",
    "antitrust", "regulator", "investigation", "settlement", "product", "launch",
    "chip", "chips", "semiconductor", "gpu", "gpus", "data center",
    "datacenter", "contract", "partnership", "deal", "stake", "ipo", "layoff",
    "layoffs", "recall", "approval", "drug", "trial", "pipeline", "shareholders",
    "board", "upgrade", "downgrade", "price target", "rating",
    "bank", "banking", "lender", "loan", "loans", "deposit", "deposits", "credit",
    "card", "underwriting", "rules", "proposal", "policy", "tariff",
    "exports", "production", "output", "drilling", "refining", "crude", "oil",
    "gas", "well", "expansion",
)

#: Sentence boundary used to decide whether a subject term describes *our*
#: company. Splits on sentence punctuation only, so "Nvidia Inc.'s earnings"
#: stays one clause.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _subject_term_regex(terms) -> re.Pattern[str]:
    """Compile subject terms into one word-boundary alternation.

    Plain substring matching (``term in lowered``) accepted stems from unrelated
    words: ``oil`` matched "turmoil", ``bank`` matched "bankruptcy", ``card``
    matched "cardboard", ``trial`` matched "industrial" (audit, 2026-11-15).
    Terms are phrases, so they are matched as whole words with internal spaces
    allowed to be any whitespace.
    """
    ordered = sorted((t for t in terms if t), key=len, reverse=True)
    alternation = "|".join(
        r"\s+".join(re.escape(part) for part in term.split()) for term in ordered
    )
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alternation})(?![A-Za-z0-9])")


_SUBJECT_TERM_RE = _subject_term_regex(_SUBJECT_TERMS)

#: Headline shapes that mark a *sector or market roundup* rather than a story
#: about one company. A headline opening "Oil majors Exxon, Chevron face…" or
#: "4 Integrated Energy Stocks to Benefit…" is about a group, even when our name
#: appears in it, so it is sector context — not DIRECT_COMPANY evidence.
#: Matched case-insensitively against the headline only, and only consulted when
#: our company is *not* the leading subject (a leading company keeps the story:
#: "Nvidia and AMD both fell as chip stocks slid" is NVDA news).
_SECTOR_ROUNDUP_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:oil|energy|tech|technology|banking|bank|chip|semiconductor|airline|"
    r"retail|healthcare|pharma|auto|industrial|chemical|utility|insurance)s?\s+"
    r"(?:majors?|giants?|peers?|groups?|companies|players?)\b"
    r"|\b\d+\s+(?:high[- ]yielding|top|best|worst|integrated|inflated|cheap|"
    r"undervalued|unstoppable|dividend|energy|bank|tech|semiconductor)\s+"
    r"(?:stocks?|shares?|dividend\s+stocks?|buys?)\b"
    r"|\bmajors?\b.*\b(?:face|brace|slide|fall|rise)\b"
    r"|\b(?:stocks?|shares?)\s+(?:making|moving|to)\s+the\s+biggest\s+moves\b"
    r"|\btop\s+(?:gainers?|losers?|movers?)\b"
    r"|\bindustry\s+(?:outlook|tailwinds?|headwinds?)\b"
    # Listicles: "3 AI Hardware Stocks to Buy: Nvidia, AMD, Micron" leads with
    # our name but is a multi-name pick list, not a company report (measured
    # leak, 2026-11-15 audit). Requires the list colon or an "and"/comma peer
    # continuation so a plain "3 reasons Nvidia will beat estimates" is not hit.
    r"|\b\d+\s+(?:[a-z][a-z-]*\s+){0,3}(?:stocks?|shares?|buys?)\b[^:]{0,40}:"
    r"|\b(?:led|lead|led by)\s+by\b"
    r")"
)

#: Roundup shapes that are *never* a single-company story, even when our name is
#: listed first: multi-name pick lists and "led by" breadth statements. Our name
#: leading a list of peers is membership, not subjecthood (measured leak,
#: 2026-11-15 audit). Consulted before the :func:`_leads_headline` exemption.
_MULTI_NAME_RE = re.compile(
    r"(?i)(?:"
    r"\b\d+\s+(?:[a-z][a-z-]*\s+){0,3}(?:stocks?|shares?|buys?)\b[^:]{0,40}:"
    r"|\bled\s+by\b"
    r"|\blead\s+(?:[a-z][a-z-]*\s+){0,2}(?:higher|lower|gains?|losses?)\b"
    # A pick list invites a choice between several named subjects.
    r"|\b(?:only one|one) clear buy among\b"
    r"|\bamong\s+(?:[A-Z]{2,5}\s*,\s*){1,}[A-Z]{2,5}\b"
    # "3 AI Hardware Stocks Linked To Nvidia", "Stocks Tied To Apple": the list
    # are the subject, our company the reference point.
    r"|\b(?:linked|tied)\s+(?:to|in)\b"
    # "NVIDIA Vs Intel", "Nvidia versus Micron": a peer comparison is never a
    # single-company report.
    r"|\bvs\.?\s+[A-Z][a-z]"
    r"|\bversus\b"
    # "Billionaire Tim Draper takes aim at Apple and Meta": multi-name
    # commentary *when the actor is someone else*. "Apple takes aim at Nvidia"
    # is Apple's own strategy story, so this shape is decided by
    # :func:`_takes_aim_elsewhere`, not by a blind regex here.
    r"|\bfeature\s+highlights?\b"
    r")"
)

#: The "takes aim at" idiom. The text before it is the actor; when that actor is
#: a different party our company is only the target ("Huawei Takes Aim at
#: Nvidia"), and when it is ours the story is ours ("Apple Takes Aim at Nvidia").
_TAKES_AIM_RE = re.compile(r"(?i)\b(?:takes?|taking)\s+aim\s+at\b")


def _takes_aim_elsewhere(headline: str, ticker: str) -> bool:
    """Whether a "takes aim at" headline makes our company the target."""
    match = _TAKES_AIM_RE.search(headline or "")
    if match is None:
        return False
    actor = headline[: match.start()]
    symbol = (ticker or "").upper()
    own = _first_position(
        actor, list(_alias_patterns(symbol)) + list(ticker_patterns(symbol))
    )
    return own is None


#: An *appositive* is a singular sector phrase immediately describing our own
#: name: "Oil giant ExxonMobil reports…", "Chip giant Nvidia beats…". Plural
#: forms ("Oil majors Exxon, Chevron…") introduce a group and are not
#: appositives, even though our name follows them.
_APPOSITIVE_RE = re.compile(
    r"(?i)\b(?:oil|energy|tech|technology|banking|bank|chip|semiconductor|"
    r"airline|retail|healthcare|pharma|auto|industrial|chemical|utility|"
    r"insurance)\s+(?:giant|major|leader|company|player)\b"
)


def _is_sector_roundup(headline: str, ticker: str = "") -> bool:
    """Whether a headline frames a group/sector rather than one company.

    An appositive that qualifies *our own* name is not a roundup: "Oil giant
    ExxonMobil reports record quarterly profit" is a single-company story.
    A singular appositive *before* our name ("Oil giant ExxonMobil…") exempts
    the headline; a plural group noun anywhere validly frames the group even
    when our own name happens to appear first ("ExxonMobil Stock And Oil Majors
    Facing New Pressure…"). Multi-name pick lists are always roundups. The
    roundup shapes that do not involve our alias at all (numbered lists, "top
    gainers", "industry outlook") always count.
    """
    headline = headline or ""
    if _MULTI_NAME_RE.search(headline):
        return True
    match = _SECTOR_ROUNDUP_RE.search(headline)
    if match is None:
        return False
    if not ticker:
        return True
    # A *singular* appositive directly qualifying our own name describes us
    # ("Oil giant ExxonMobil reports…"). Plural group forms do not, even when
    # our name follows them ("Oil majors Exxon, Chevron…").
    alias = _alias_patterns((ticker or "").upper())
    appositive = _APPOSITIVE_RE.search(headline)
    if appositive is not None and any(
        p.match(headline[appositive.end():appositive.end() + 40].lstrip())
        for p in alias
    ):
        return False
    return True


#: Sector/group nouns that frame a whole group. When one of these introduces a
#: *different* company before ours, the headline is about the group. An
#: appositive that qualifies *our own* name ("Oil giant ExxonMobil reports…")
#: is not a roundup — it is a single-company story — so the noun must not be
#: immediately followed by our alias (see :func:`_is_sector_roundup`).
_GROUP_NOUN_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:oil|energy|tech|technology|banking|bank|chip|semiconductor|airline|"
    r"retail|healthcare|pharma|auto|industrial|chemical|utility|insurance)s?\s+"
    r"(?:majors?|giants?|peers?|groups?|companies|players?|stocks?|sectors?)"
    r"|industry\s+(?:outlook|tailwinds?|headwinds?)"
    r")\b"
)

#: Aliases that are ordinary English words and therefore need a domain
#: disambiguator before a bare mention counts as the company. Without this,
#: "Apple growers warn of poor harvest" was admitted as AAPL news (audit,
#: 2026-11-15). Only applies when the alias appears *without* a company marker
#: (``Inc``, ``Corp``, a ticker) — see :func:`_ambiguous_alias_only`.
_AMBIGUOUS_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "apples"),
}

#: Words that show the "apple" sense is agricultural, not corporate.
_APPLE_NON_COMPANY_RE = re.compile(
    r"(?i)\b(?:growers?|orchard|harvest|fruit|cider|vinegar|pie|pies|tree|trees|"
    r"crop|crops|bushel|farmers?|agricultural)\b"
)


def _compile_word(name: str) -> re.Pattern[str]:
    """A whole-word, case-insensitive pattern for one company name/alias."""
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])",
                      re.IGNORECASE)


@lru_cache(maxsize=512)
def _alias_patterns(symbol: str) -> tuple[re.Pattern[str], ...]:
    names = COMPANY_NAMES.get(symbol.upper(), ())
    return tuple(_compile_word(name) for name in names if name)


@lru_cache(maxsize=512)
def ticker_patterns(symbol: str) -> tuple[re.Pattern[str], ...]:
    """Delimited ticker forms that assert "this text names ``symbol``".

    Covered: plain ``NVDA`` as a whole word, ``$NVDA``, ``NYSE:NVDA``,
    ``NASDAQ:NVDA``, ``NVDA.US``/``NVDA:US``, and ``(NVDA)``. Word boundaries
    prevent ``NVDAX`` and ``NVDIA``-style longer tokens from matching.

    All patterns are case-insensitive: news URLs are almost always lowercase
    slugs (``/nvidia-beats-estimates``), and a case-sensitive symbol match would
    silently skip them.
    """
    s = re.escape(symbol.upper())
    return (
        re.compile(rf"(?<![A-Za-z0-9])(?:\$|\(|\[){{0,1}}{s}(?![A-Za-z0-9])", re.IGNORECASE),
        re.compile(rf"(?::|\bUS:|\bNYSE:|\bNASDAQ:|\bTSE:){s}\b", re.IGNORECASE),
        re.compile(rf"\b{s}\.(?:US|O|N|NQ|L|TO)\b", re.IGNORECASE),
    )


def company_name(ticker: str) -> str:
    """The display name for ``ticker``, or the symbol itself when unknown."""
    names = COMPANY_NAMES.get((ticker or "").upper(), ())
    return names[0] if names else (ticker or "").upper()


def _is_non_company_sense(headline: str, summary: str, ticker: str) -> bool:
    """Whether a polysemous alias is used in its non-company sense.

    Only ``AAPL`` is configured: "Apple" is a fruit before it is a company. A
    mention that carries a company marker (``Inc``/``Corp``), a ticker, or a
    technology-domain word is treated as the company; an agricultural word
    without any of those means the article is about fruit, not Apple Inc.
    """
    symbol = (ticker or "").upper()
    ambiguous = _AMBIGUOUS_ALIASES.get(symbol)
    if not ambiguous:
        return False
    text = f"{headline} {summary}"
    lowered = text.lower()
    if not any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in ambiguous):
        return False
    # A company marker or a technology word means the corporate sense.
    if _COMPANY_MARKER_RE.search(text) or _TECH_DOMAIN_RE.search(text):
        return False
    return bool(_APPLE_NON_COMPANY_RE.search(text))


#: Markers that resolve a bare alias to a corporate entity. Matched standalone
#: only: "Palo Alto Networks Inc" must not mark *Chase* as a company, so the
#: suffix must not be glued to a preceding capitalised word (live XOM/JPM run,
#: 2026-11-15).
_COMPANY_MARKER_RE = re.compile(
    r"(?i)(?:(?<![A-Za-z])|(?<=[a-z0-9]))(?:inc|corp|corporation|company|ltd|plc|co)"
    r"(?![A-Za-z])"
)

#: Broker/dealer names. Almost all of COMPANY_NAMES banks are the *analyst* in
#: a headline ("Citi cuts ExxonMobil to neutral", "Morgan Stanley: Nvidia is the
#: top pick"): the bank issues the note, the other company is the subject. So
#: these must not be treated as a competing subject by the co-mention guard
#: (measured defect, 2026-11-15 audit). A bank can still be the *subject* of its
#: own story, because when it is the requested ticker its own aliases apply.
_ANALYST_FIRM_RE = re.compile(
    r"(?i)^(?:jpmorgan(?: chase)?|jp morgan|j\.p\. morgan|morgan chase|chase|"
    r"goldman sachs|goldman|morgan stanley|citi(?:group)?|citibank|"
    r"bank of america|bofa|wells fargo|deutsche bank|barclays|ubs|"
    r"credit suisse|hsbc|jefferies|evercore|raymond james)$"
)

#: Domain words that resolve "Apple"/"Amazon" to the technology company.
_TECH_DOMAIN_RE = re.compile(
    r"(?i)\b(?:iphone|ipad|mac|macbook|ios|stock|shares?|earnings|revenue|"
    r"nasdaq|analysts?|investors?|quarter|guidance|services|app\s+store|"
    r"siri|tim\s+cook|device|devices|hardware|software)\b"
)


def _is_plural_group(match_text: str) -> bool:
    """Whether a group-noun match is plural ("Oil Majors", not "Oil Major")."""
    text = (match_text or "").strip()
    return bool(re.search(r"(?i)s$", text))


def _leads_headline(headline: str, ticker: str) -> bool:
    """Whether our company is the earliest-named subject in ``headline``.

    Used only to decide whether a roundup-shaped headline is nevertheless *our*
    story. A group noun first ("Oil majors Exxon…", "Energy stocks…") means we
    are group membership; naming us first ("Nvidia and AMD both fell…") means we
    lead. A *different* company named before us also means we do not lead.
    """
    symbol = (ticker or "").upper()
    own = _first_position(
        headline,
        list(_alias_patterns(symbol)) + list(ticker_patterns(symbol)),
    )
    if own is None:
        return False
    # A sector/group noun before our name means the headline is framed around
    # the group — unless it is a singular appositive for us ("Oil giant
    # ExxonMobil…"), which describes our own story. Plural group forms are not
    # appositives ("Oil majors Exxon, Chevron…").
    group = _GROUP_NOUN_RE.search(headline)
    if group is not None and group.start() < own:
        appositive = _APPOSITIVE_RE.search(headline[:group.end()])
        if appositive is None or not any(
            p.match(headline[appositive.end():appositive.end() + 40].lstrip())
            for p in _alias_patterns(symbol)
        ):
            return False
    if _another_company_comes_first(headline, symbol):
        return False
    # A *plural* group noun after our name still frames the group: "ExxonMobil
    # Stock And Oil Majors Facing New Pressure…" leads with our name yet the
    # subject of the sentence is the majors, our stock included (measured leak,
    # 2026-11-15 audit). A *singular* one after our name qualifies us ("…the
    # U.S. Oil Major Is Negotiating", about Exxon) and stays ours.
    for later in _GROUP_NOUN_RE.finditer(headline):
        if later.start() <= own:
            continue
        if not _is_plural_group(later.group(0)):
            continue
        return False
    return True


@lru_cache(maxsize=1)
def _all_company_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """``(name, pattern)`` for every known company name, for subject checks.

    Combines :data:`COMPANY_NAMES` (our investable universe) with
    :data:`_OTHER_COMPANIES` (frequent non-target subjects). Two-character names
    are skipped: a two-letter alias (``J&J``, ``BP``) collides with ordinary
    prose far more often than it identifies a subject. Three-character ones
    (``IBM``, ``KLA``) are unambiguous and stay.

    Broker/dealer names are kept, but :func:`_another_company_comes_first`
    discounts them when they are acting as an *analyst* ("Citi cuts ExxonMobil
    to neutral") — otherwise every analyst note about every ticker would be
    rejected. When the bank is the story's subject ("Goldman Sachs tops JPMorgan
    in dealmaking") the name still counts. All-CAPS ticker symbols stay in the
    set too: "AMD Stock Has Blown Past Nvidia", "IBM Once Held Nvidia's Spot"
    are competitor-led stories that name ours only as a yardstick. Symbol-only
    peer comparisons ("NVIDIA Vs Intel Corporation (NASDAQ:INTC)") are already
    caught by the ``vs`` shape in :data:`_MULTI_NAME_RE`.
    """
    seen: dict[str, re.Pattern[str]] = {}
    every = [n for names in COMPANY_NAMES.values() for n in names]
    every.extend(_OTHER_COMPANIES)
    for name in every:
        if len(name) < 3 or name in seen:
            continue
        seen[name] = _compile_word(name)
    return tuple(seen.items())


#: Verbs that make a preceding broker/dealer name an *analyst* rather than the
#: story's subject: "Citi cuts ExxonMobil…", "BofA upgrades Apple…".
_ANALYST_VERB_RE = re.compile(
    r"(?i)^\s*(?::|(?:raises?|cuts?|lowers?|upgrades?|downgrades?|initiates?|"
    r"reiterates?|maintains?|sets?|lifts?|slashes?|boots?|adds?)\b)"
)


def _actor_is_analyst(text: str, name_end: int) -> bool:
    """Whether the company ending at ``name_end`` is issuing an analyst note."""
    return bool(_ANALYST_VERB_RE.match(text[name_end:name_end + 24]))


def _first_position(text: str, patterns) -> int | None:
    """Character offset of the earliest match of ``patterns`` in ``text``."""
    best: int | None = None
    for pattern in patterns:
        match = pattern.search(text)
        if match and (best is None or match.start() < best):
            best = match.start()
    return best


def _another_company_comes_first(text: str, ticker: str) -> bool:
    """Whether ``text`` names a *different* known company before ours.

    Measured failure (live NVDA sample, 2026-11-15): stories whose subject is
    another firm and which name NVIDIA only as a counterparty — "IonQ Surges 11%
    as NVIDIA Research Center Deal…", "NVIDIA's Partner IonQ…", "Samsung ships
    more phones than Apple…" — were admitted because the alias matched anywhere
    in the headline. Whoever is named first is the headline's subject; a later
    mention of our company is a co-mention.

    Only applies when our own name/symbol is *not* first. A headline that leads
    with us and then lists peers ("Nvidia, AMD and Intel all fell") stays ours.
    """
    if not text:
        return False
    symbol = (ticker or "").upper()
    own_names = {n.upper() for n in COMPANY_NAMES.get(symbol, ())}
    own_patterns = list(_alias_patterns(symbol)) + list(ticker_patterns(symbol))
    own = _first_position(text, own_patterns)
    if own is None:
        # Our company is not in this text at all; the subject rule is moot.
        return False
    others = [
        (name, pattern)
        for name, pattern in _all_company_patterns()
        if name.upper() not in own_names
    ]
    # A broker/dealer that is merely issuing a note is not the subject: "Citi
    # cuts ExxonMobil to neutral" is XOM's story. A bank that is *doing*
    # something ("Goldman Sachs tops JPMorgan in dealmaking") still leads.
    # A shorter alias of the same firm ("Goldman" inside "Goldman Sachs") must
    # not resurrect the firm as a subject after its longer form was discounted.
    earliest: int | None = None
    analyst_spans: list[tuple[int, int]] = []
    for name, pattern in others:
        match = pattern.search(text)
        if match is None:
            continue
        if _ANALYST_FIRM_RE.match(name) and _actor_is_analyst(text, match.end()):
            analyst_spans.append(match.span())
            continue
        if any(start <= match.start() and match.end() <= end
               for start, end in analyst_spans):
            continue
        if earliest is None or match.start() < earliest:
            earliest = match.start()
    return earliest is not None and earliest < own


def _peer_ticker_list_first(headline: str, symbol: str) -> bool:
    """Whether a bare ticker list names peers before ``symbol``.

    "INTC, AMD, MU, NVDA: Chip Stocks Rally" is a sector move story listing the
    whole complex; our ticker appearing third does not make it ours.
    """
    match = re.match(r"\s*((?:[A-Z]{2,5}\s*,\s*)+)([A-Z]{2,5})\b", headline or "")
    if match is None:
        return False
    listed = [t.strip().upper() for t in match.group(1).split(",") if t.strip()]
    final = match.group(2).upper()
    return symbol.upper() in listed + [final] and (listed + [final]).index(
        symbol.upper()
    ) > 0


def _symbol_in(text: str, symbol: str) -> bool:
    """Whether ``text`` names ``symbol`` with an unambiguous delimiter."""
    if not text:
        return False
    symbol = symbol.upper()
    if len(symbol) > _SHORT_SYMBOL:
        # Ordinary-length tickers: a whole-word match is already unambiguous.
        return bool(ticker_patterns(symbol)[0].search(text))
    # Short tickers: require visual delimiters so "Fed"/"to"/"we" never match.
    if any(p.search(text) for p in ticker_patterns(symbol)[1:]):
        return True
    return bool(re.search(rf"(?:\$|\(|\[){re.escape(symbol)}(?![A-Za-z0-9])",
                          text, re.IGNORECASE))


def is_about_company(headline: str, summary: str, url: str, ticker: str) -> bool:
    """Whether the article is substantively about ``ticker``.

    Args:
        headline: Title text (any case; ``None`` tolerated).
        summary: Body/description text; may be empty.
        url: Article URL, used for its slug.
        ticker: Canonical symbol.

    Returns:
        True only when the symbol, a company alias, or a name-plus-subject body
        match is present. ``related`` metadata is deliberately not consulted.
    """
    symbol = (ticker or "").upper()
    if not symbol:
        return False
    headline = headline or ""
    summary = summary or ""
    url = url or ""
    alias = _alias_patterns(symbol)

    # 0. A headline that is structurally a multi-name list or a peer comparison
    #    is never a single-company story, whichever name (our symbol, our alias)
    #    it lists first: "Chip Trillionaires Club: Only One Clear Buy Among NVDA,
    #    AVGO, MU, AMD" names NVDA first and is still about the club, not NVDA.
    #    Checked before the symbol shortcut for exactly that reason. The "takes
    #    aim at" idiom is only a multi-name frame when the actor is someone else.
    if _MULTI_NAME_RE.search(headline):
        return False
    if _takes_aim_elsewhere(headline, symbol):
        return False

    # 1. Symbol in the headline or the URL slug (strongest, data-free).
    if _symbol_in(headline, symbol) or _symbol_in(url, symbol):
        # A competitor named before us still wins: "AMD Stock Has Blown Past
        # Nvidia" carries our symbol and is AMD's story. So does a bare ticker
        # list that starts with peers ("INTC, AMD, MU, NVDA: Chip Stocks Rally").
        if _another_company_comes_first(headline, symbol) or _peer_ticker_list_first(
            headline, symbol
        ):
            return False
        return True

    named = any(p.search(headline) or p.search(url) for p in alias)
    if named and _another_company_comes_first(headline, symbol):
        # The headline is about a different company; ours is a co-mention. Only
        # an explicit slug for our ticker (checked above) would override this.
        return False
    if named and _is_non_company_sense(headline, summary, symbol):
        # "Apple growers warn of poor harvest": the alias matched, but the text
        # is about the fruit, not the company.
        return False
    # 2. Company name / alias in the headline or the URL slug — unless the
    #    headline frames a sector/market roundup and our company is not its
    #    leading subject, in which case our name is group membership rather than
    #    the story ("Oil majors Exxon, Chevron face pressure as crude slides" is
    #    sector context for XOM). A company that leads a roundup keeps it:
    #    "Nvidia and AMD both fell as chip stocks slid" is NVDA news.
    #    Multi-name pick lists ("3 AI Hardware Stocks to Buy: Nvidia, AMD…") and
    #    "led by" breadth statements are membership no matter who is listed
    #    first, so they are not rescued by the lead exemption.
    if named and not (
        _MULTI_NAME_RE.search(headline)
        or (_is_sector_roundup(headline, symbol) and not _leads_headline(headline, symbol))
    ):
        return True
    # A headline that frames the group is settled by the headline itself: our
    # name in the *body* of a pick list ("... among NVDA, AVGO... Zacks
    # highlights NVIDIA...") does not turn membership into company news. The
    # body channel exists to rescue a *generic* headline, not to overturn an
    # explicit group frame.
    if named and _is_sector_roundup(headline, symbol):
        return False
    # A roundup headline can still be *about* us when our ticker is in it, which
    # step 1 handled; otherwise fall through to the body rule so a genuine
    # company-specific summary is not lost.
    # 3. Name in the body *and* a company-specific subject term *in the same
    #    sentence*, so a passing mention inside an unrelated market wrap is not
    #    admitted. Measuring the whole summary was too loose: "…tech stocks
    #    cresting highs… artificial-intelligence trade" satisfied it for NVDA
    #    without saying anything about Nvidia.
    if summary and any(p.search(summary) for p in alias):
        for sentence in _SENTENCE_SPLIT.split(summary):
            if not any(p.search(sentence) for p in alias):
                continue
            if _another_company_comes_first(sentence, symbol):
                # "IonQ rose after a deal with Nvidia." — the sentence's subject
                # is someone else, so our company is a co-mention here too. The
                # headline guard alone would miss the body channel.
                continue
            if _SUBJECT_TERM_RE.search(sentence):
                return True
    return False
