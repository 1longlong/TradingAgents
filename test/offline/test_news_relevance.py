"""The shared company-relevance rule used by both news providers.

Relevance is the gate that decides whether an article reaches the analyst at
all, so it is the one place where a bug silently changes what the model reads.
Both providers reported relevance in ways measured to be false:

* Finnhub's ``related`` field is not article metadata. Measured live
  (2026-11-15): for the NVDA feed, **every one of 250 items** carried
  ``related="NVDA"`` — including IonQ, McDonald's and SCHD dividend stories —
  and 14 URLs returned under both the NVDA and IONQ queries flipped ``related``
  to whichever symbol was asked for. It is an echo of the query, so this module
  never consults it.
* GDELT matches free text, so a quoted ticker returns anything naming it.

The cases below are drawn from those live samples, which is why several
headlines look like clickbait: they are real.
"""

from __future__ import annotations

import pytest

from tradingagents.dataflows.news_relevance import (
    COMPANY_NAMES,
    company_name,
    is_about_company,
    ticker_patterns,
)

NVDA, AAPL, JPM, XOM = "NVDA", "AAPL", "JPM", "XOM"


def _about(headline: str, ticker: str, summary: str = "", url: str = "") -> bool:
    return is_about_company(headline, summary, url, ticker)


# --- rule 1: the symbol is the strongest signal -----------------------------


@pytest.mark.parametrize("headline", [
    "NVDA climbs after the data-center update",
    "Nvidia stock: $NVDA is the talk of the tape",
    "Upgrade watch: NASDAQ:NVDA gets a new target",
    "Earnings preview (NVDA)",
])
def test_the_symbol_in_the_headline_admits_the_article(headline):
    assert _about(headline, NVDA)


def test_a_lowercase_url_slug_naming_the_symbol_admits_the_article():
    # News URLs are almost always lowercase slugs; a case-sensitive match would
    # silently drop them.
    assert _about("Chipmaker rallies on demand", NVDA,
                  url="https://site.invalid/2026/09/nvda-rallies-on-demand")


def test_a_longer_token_containing_the_symbol_is_not_a_match():
    # NVDAX is a different instrument; NVDIA is a typo.
    assert not _about("NVDAX holds steady", NVDA)
    assert not _about("NVDIA reports results", NVDA)


@pytest.mark.parametrize("symbol", ["T", "C", "F", "V"])
def test_a_short_ticker_does_not_match_ordinary_prose(symbol):
    # "T", "C", "F" and "V" are real symbols; matching them as bare substrings
    # would admit essentially every article in the wire feed.
    for text in ("The Fed meets on Tuesday", "We think to hold", "if this is true"):
        assert not _about(text, symbol), (symbol, text)


@pytest.mark.parametrize("headline,symbol", [
    ("AT&T raises prices again", "T"),
    ("Ford to cut F-150 output", "F"),
    ("Citigroup names a new CFO", "C"),
])
def test_a_short_ticker_still_matches_its_company_name(headline, symbol):
    # The hazard above must not go so far as to drop real stories.
    assert _about(headline, symbol)


# --- rule 2: company name / alias -------------------------------------------


def test_the_company_name_carries_a_story_that_never_uses_the_symbol():
    assert _about("Exxon signals higher output", XOM)
    assert _about("JPMorgan Plans to Double India Finance Hub Business", JPM)
    assert _about("Exxon (XOM) Eyes a Return to Venezuela", XOM)


def test_an_unknown_ticker_falls_back_to_the_symbol_and_still_works():
    # No COMPANY_NAMES entry: only the symbol rule can fire, which is correct.
    assert company_name("ZZZZ") == "ZZZZ"
    assert _about("ZZZZ announces a buyback", "ZZZZ")
    assert not _about("Something unrelated entirely", "ZZZZ")


# --- the co-mention guard ---------------------------------------------------


@pytest.mark.parametrize("headline", [
    # Live NVDA-feed headlines whose subject is a *different* company. All were
    # admitted before the guard existed, because "Nvidia" appeared somewhere.
    "IonQ Surges 11% as NVIDIA Research Center Deal Follows Error-Decoder Breakthrough",
    "IonQ Wants to Be the Nvidia of Quantum. Now They Are Partners.",
    "Why Rackspace Technology (RXT) Is Up 15.8% After Joining NVIDIA's Cloud Partner Program",
    "IBM Once Held Nvidia's Spot as Tech's Biggest Name. The Stock Just Crashed 25%.",
])
def test_a_headline_led_by_another_company_is_not_about_ours(headline):
    assert not _about(headline, NVDA)


def test_the_subject_is_whoever_is_named_first_not_who_is_famous():
    assert not _about("Samsung ships more phones than Apple in Q3", AAPL)
    assert not _about("Goldman Sachs tops JPMorgan in dealmaking", JPM)
    assert not _about("Chevron and ExxonMobil Double Down on LNG", XOM)


def test_leading_with_our_company_and_listing_peers_keeps_the_article():
    # The guard must not become "any competitor mention disqualifies".
    assert _about("Nvidia and AMD both fell as chip stocks slid", NVDA)
    assert _about("Exxon and Chevron both raise dividends", XOM)
    assert _about("Visa and Mastercard face new fee rules", "V")
    assert _about("Nvidia gains as Apple pulls AI off the meter", NVDA)


# --- rule 3: the body channel -----------------------------------------------


def test_a_body_mention_with_a_subject_term_qualifies_a_generic_headline():
    assert _about("Market wrap", NVDA,
                  summary="Nvidia reported record earnings and raised guidance.")
    assert _about("Market wrap", NVDA,
                  summary="Nvidia and Micron both beat estimates.")


def test_a_bare_body_mention_does_not_qualify():
    # Inside a market wrap the company is just listed among movers.
    assert not _about("Market wrap", NVDA,
                      summary="Nvidia was among the decliners on Tuesday.")


@pytest.mark.parametrize("summary", [
    # The measured false positives: market-wide AI pieces whose summary names
    # Nvidia in passing. They passed before the subject term had to appear in
    # the same sentence as the company.
    "The artificial-intelligence trade is ripping once again, with tech stocks "
    "cresting fresh all-time highs, Wall Street bosses touting the scale of the "
    "investment. Nvidia was mentioned.",
    "The investor who called the subprime collapse now says the entire AI "
    "buildout depends on two companies, and one of them keeps me up at night.",
])
def test_a_market_wide_summary_is_not_about_the_company(summary):
    assert not _about("AI Stocks Can't Carry the Entire Market Forever", NVDA,
                      summary=summary)


def test_the_body_channel_applies_the_same_subject_guard_as_the_headline():
    # The sentence's subject is IonQ; NVIDIA is the counterparty.
    assert not _about("Quantum computing stocks jump", NVDA,
                      summary="IonQ rose after a deal with Nvidia.")


# --- metadata that must never be trusted ------------------------------------


def test_no_public_entry_point_accepts_a_related_field():
    # Guard against a future caller reintroducing the Finnhub ``related`` echo
    # as evidence: the rule takes text only.
    import inspect

    params = set(inspect.signature(is_about_company).parameters)
    assert params == {"headline", "summary", "url", "ticker"}


# --- the symbol/alias registry ---------------------------------------------


def test_the_display_name_is_the_first_alias():
    assert company_name("NVDA") == "NVIDIA"
    assert company_name("aapl") == "Apple"


def test_every_registered_company_names_itself_in_its_own_headline():
    # A table entry that cannot match its own name would silently disable both
    # the alias rule and the co-mention guard for that ticker.
    for symbol, names in COMPANY_NAMES.items():
        headline = f"{names[0]} announces a quarterly update"
        assert _about(headline, symbol), (symbol, names[0])


def test_ticker_patterns_are_case_insensitive():
    # Pattern 0 matches a bare symbol, so a lowercase slug must hit it. The
    # exchange-qualified patterns require their prefix, so they are exercised
    # with one.
    assert ticker_patterns("NVDA")[0].search("nvda")
    assert ticker_patterns("NVDA")[1].search("nyse:nvda")
    assert ticker_patterns("NVDA")[2].search("nvda.us")


# --- sector roundups are context, not company news --------------------------
#
# Measured live (2026-11-15): the XOM feed carried sector roundups whose only
# link to Exxon was group membership. Admitting them as XOM news is the exact
# "industry news leaks into the company feed" defect this gate exists to stop.


@pytest.mark.parametrize("headline", [
    "Oil majors Exxon, Chevron face pressure as crude slides",
    "4 Integrated Energy Stocks to Benefit From Industry Tailwinds",
    "Zacks Industry Outlook Highlights ExxonMobil, Chevron, BP and Eni",
])
def test_sector_roundup_naming_us_is_not_our_company_news(headline):
    assert not _about(headline, XOM)


def test_roundup_led_by_our_company_keeps_the_story():
    # The guard must not become "any sector noun disqualifies": when we lead,
    # the story is ours.
    assert _about("Nvidia and AMD both fell as chip stocks slid", NVDA)


def test_company_specific_story_survives_the_roundup_guard():
    assert _about("ExxonMobil boosts Guyana output", XOM)
    assert _about("ExxonMobil Nears a Venezuela Return After 19 Years", XOM)


def test_roundup_does_not_drop_a_genuine_body_match():
    # A roundup headline whose summary is about us is still our story.
    assert _about(
        "4 Integrated Energy Stocks to Benefit From Industry Tailwinds",
        XOM,
        summary="ExxonMobil raised its dividend after record refining margins.",
    )


# --- polysemous aliases -----------------------------------------------------


@pytest.mark.parametrize("headline", [
    "Apple growers warn of poor harvest",
    "Apple harvest in Washington looks strong",
    "Apples are in season, say farmers",
])
def test_fruit_sense_of_apple_is_not_the_company(headline):
    assert not _about(headline, AAPL)


@pytest.mark.parametrize("headline", [
    "Apple beats expectations with iPhone sales",
    "Apple Inc. reports record services revenue",
    "Apple Stock Falls After Analyst Downgrade",
])
def test_corporate_sense_of_apple_is_kept(headline):
    assert _about(headline, AAPL)


# --- subject terms must be whole words --------------------------------------


@pytest.mark.parametrize("summary", [
    "ExxonMobil operates in an era of market turmoil.",
    "ExxonMobil filed for bankruptcy protection.",
    "ExxonMobil shipped cardboard packaging.",
])
def test_subject_terms_do_not_match_inside_unrelated_words(summary):
    # "oil" in "turmoil", "bank" in "bankruptcy", "card" in "cardboard" used to
    # satisfy the body rule on bare substring matching.
    assert not _about("Energy news", XOM, summary=summary)


def test_subject_term_matches_as_a_whole_word():
    assert _about("Energy news", XOM, summary="ExxonMobil lifted oil output.")


# --- appositive openers are single-company stories, not roundups -------------
#
# Audit finding (2026-11-15): the sector guard first shipped rejected
# "Oil giant ExxonMobil reports record quarterly profit" because a group noun
# preceded our alias. An appositive that qualifies *our* name describes our
# story; a group noun introducing a different company does not.


@pytest.mark.parametrize("ticker,headline", [
    (XOM, "Oil giant ExxonMobil reports record quarterly profit"),
    (XOM, "Oil major ExxonMobil to cut 2,000 jobs"),
    (XOM, "Energy giant ExxonMobil beats earnings estimates"),
    (NVDA, "Chip giant Nvidia beats earnings estimates"),
    (NVDA, "Tech giant Nvidia to acquire AI startup"),
    (AAPL, "Tech giant Apple reports record revenue"),
    (JPM, "Bank giant JPMorgan reports record profit"),
    (JPM, "Banking giant JPMorgan raises dividend"),
])
def test_an_appositive_for_our_company_keeps_the_story(ticker, headline):
    assert _about(headline, ticker)


@pytest.mark.parametrize("headline", [
    "Oil majors Exxon, Chevron face pressure as crude slides",
    "Oil companies Exxon and Chevron report record profits",
    "Tech companies Apple and Microsoft report earnings",
])
def test_a_group_noun_introducing_several_companies_is_a_roundup(headline):
    ticker = XOM if "Exxon" in headline else AAPL
    assert not _about(headline, ticker)


# --- regressions from the 2026-11-15 real-corpus audit ---------------------
#
# Two defects were measured on the collected Finnhub corpus (1,195 articles,
# NVDA/AAPL/JPM/XOM), where the audit compared the shipped classifier against a
# manual A-E reading of the same headline. Both are pinned here.

def test_chase_is_recognised_as_jpmorgans_consumer_brand():
    # Measured miss: the JPM alias list had "Morgan Chase" but not the brand the
    # consumer press actually uses, so three genuine Chase product stories were
    # rejected for JPM.
    for headline in (
        "Chase Expands Ultimate Rewards with New Invest Your Points Feature",
        "Chase Builds on Freedom Flex's Everyday Rewards with More Travel Value",
        "Chase celebrates the Sapphire Reserve's 10th anniversary with new credits",
        "JPMorganChase to Host Third-Quarter 2026 Earnings Call",
    ):
        assert is_about_company(headline, "", "", "JPM"), headline


def test_a_suffix_inside_another_companys_name_does_not_mark_our_alias():
    # The company marker must be a standalone legal suffix: "Co" and "Inc" glued
    # inside a longer word are ordinary letters, not suffixes.
    from tradingagents.dataflows.news_relevance import _COMPANY_MARKER_RE

    for standalone in ("Acme Inc", "Acme Co", "Palo Alto Networks Inc", "Exxon Co"):
        assert _COMPANY_MARKER_RE.search(standalone), standalone
    for glued in ("Bioincubator Incubate", "JPMorganChase"):
        assert not _COMPANY_MARKER_RE.search(glued), glued
    # A standalone suffix after punctuation is still a suffix.
    assert _COMPANY_MARKER_RE.search("(Co)")


def test_qualcomm_is_a_known_competing_subject():
    # Measured miss: "Qualcomm Renews Deal With Apple" was *admitted* for Apple
    # before Qualcomm was registered as another company; the subject rule can
    # only reject a co-mention when the co-naming company is known.
    from tradingagents.dataflows.news_relevance import _OTHER_COMPANIES

    assert "Qualcomm" in _OTHER_COMPANIES
    assert not is_about_company(
        "Qualcomm Renews Deal With Apple. Why the Stock is Dropping Anyway.",
        "Qualcomm renewed its patent licence with Apple.",
        "",
        "AAPL",
    )


# --- round 2026-11-15 (b): multi-name framings measured in the live corpus ----
# Each of these was ADMITTED as company news before the guards below and is a
# sector/peer/comparison story, so each assertion is non-vacuous: reverting the
# matching engine makes it fail.


@pytest.mark.parametrize("headline,ticker", [
    # Pick lists that list our name FIRST. Membership, not subjecthood.
    ("Chip Trillionaires Club: Only One Clear Buy Among NVDA, AVGO, MU, AMD", "NVDA"),
    ("3 AI Hardware Stocks to Buy: Nvidia, AMD, Micron", "NVDA"),
    ("3 AI Hardware Stocks Linked To Nvidia And US China Trade Talks", "NVDA"),
    ("3 Large-Cap Tech Stocks With the Most Upside: Apple, Microsoft", "AAPL"),
    ("3 Stocks Tied To Apple And Nvidia Supply Chain Demand", "AAPL"),
    # Breadth statements led by our name.
    ("Exxon and Chevron lead oil majors higher as crude rallies", "XOM"),
    # Peer comparisons.
    ("Better Artificial Intelligence (AI) Stock Pick for 2027: Nvidia versus Micron", "NVDA"),
    ("NVIDIA Vs Intel Corporation (NASDAQ:INTC): Here's The One Jim Cramer Likes", "NVDA"),
    ("Credo vs. NVIDIA After Earnings: Which AI Stock Should You Buy Now?", "NVDA"),
    ("JPMorgan vs. Wells Fargo: Which Bank Stock Has More Upside Potential?", "JPM"),
    ("ExxonMobil vs. ConocoPhillips: Which Oil Major's Stock Buybacks Will Win?", "XOM"),
    # Multi-name commentary where our company is only the target.
    ("Billionaire Tim Draper takes aim at Apple, Meta's Bitcoin-free balance sheet", "AAPL"),
    ("Huawei Takes Aim at Nvidia, AMD with Over 10 new AI Chipsets", "NVDA"),
    # Plural group noun after our own name: "ExxonMobil Stock And Oil Majors…".
    ("ExxonMobil Stock And Oil Majors Facing New Pressure On Global Supply Routes", "XOM"),
])
def test_multi_name_framings_are_not_company_news(headline, ticker):
    assert not is_about_company(headline, "", "", ticker), headline


@pytest.mark.parametrize("headline,ticker", [
    # Our company as the *actor* of "takes aim at" is our own story.
    ("Apple Takes Aim at Nvidia's AI Economics: New Macs Have No Cost per Token", "AAPL"),
    # A singular group noun after our name qualifies us, not the group.
    ("Exxon Is Nearing A Preliminary Deal To Invest In Venezuela's Oil Fields; "
     "The U.S. Oil Major Is Negotiating A Return 19 Years After Its Exit", "XOM"),
    # A stated count is not a pick list.
    ("3 reasons Nvidia will beat estimates this quarter", "NVDA"),
    # Leading with our company and then peers is our story.
    ("Nvidia and AMD both fell as chip stocks slid", "NVDA"),
    ("Nvidia lifts guidance for 2027", "NVDA"),
    ("ExxonMobil beats on higher refining margins", "XOM"),
    ("Exxon signals higher output", "XOM"),
])
def test_genuine_company_framings_survive_the_multi_name_guards(headline, ticker):
    assert is_about_company(headline, "", "", ticker), headline


def test_an_analyst_firm_issuing_a_note_is_not_the_subject():
    # The broker is the actor, our company the subject: a note about us is our
    # news even though a different company is named first. This is the defect a
    # blanket "banks are competing subjects" rule caused.
    for headline, ticker in [
        ("Citi cuts ExxonMobil to neutral, sees limited upside", "XOM"),
        ("Goldman Sachs raises Nvidia price target to $250", "NVDA"),
        ("Morgan Stanley: Nvidia is the top pick for 2027", "NVDA"),
        ("BofA upgrades Apple to buy on iPhone 18 demand", "AAPL"),
        ("Citi downgrades JPMorgan as credit costs rise", "JPM"),
    ]:
        assert is_about_company(headline, "", "", ticker), headline


def test_a_competitor_named_before_us_still_wins_over_our_symbol():
    # The symbol shortcut must not override the subject rule: these carry our
    # ticker/name yet are another company's story.
    for headline, ticker in [
        ("AMD Stock Has Blown Past Nvidia This Year. Is It Still the Better Buy?", "NVDA"),
        ("IBM Once Held Nvidia's Spot as Tech's Biggest Name. The Stock Just Crashed 25%.", "NVDA"),
    ]:
        assert not is_about_company(headline, "", "", ticker), headline


# --- alternative-level pins for the multi-name framings ----------------------
# Each case below is rejected by ONE specific branch of the multi-name/sector
# machinery; reverting that branch (and only it) makes exactly this test fail.


def test_a_bare_ticker_list_starting_with_peers_is_not_ours():
    # "_peer_ticker_list_first": our ticker appears, but after peers, in a
    # sector-move list. The symbol shortcut must not claim it.
    assert not is_about_company("INTC, AMD, MU, NVDA: Chip Stocks Rally As "
                                "Investors Look Past AI Concerns", "", "", "NVDA")
    assert not is_about_company("AMD, NVDA rise after earnings", "", "", "NVDA")
    # A list that starts with *us* is still ours.
    assert is_about_company("NVDA, AMD and MU rally on AI demand", "", "", "NVDA")


@pytest.mark.parametrize("headline", [
    # "led by" breadth statement.
    "Tech stocks led by Nvidia and AMD rally on AI demand",
    # "lead ... higher" where the *sector* leads and no company does.
    "Chipmakers lead stocks higher as AI trade resumes",
    # "only one clear buy among" pick list (no colon).
    "Only One Clear Buy Among Nvidia, AMD and Micron",
    # "among XX, XX" ticker pick list.
    "Among NVDA, AMD and MU, which is the better AI stock?",
    # "feature highlights" roundup.
    "Zacks Feature Highlights Nvidia and AMD in Weekly Roundup",
])
def test_each_multi_name_branch_rejects_its_shape(headline):
    assert not is_about_company(headline, "", "", "NVDA"), headline


def test_a_sector_led_lead_statement_is_not_a_company_story():
    # "leads ... lower" with the sector as subject: XOM is a member only.
    assert not is_about_company("Energy majors lead stocks lower as crude slumps",
                                "", "", "XOM")
    # ...but our company as the driver keeps its own story.
    assert is_about_company("Nvidia leads chip stocks higher on AI demand",
                            "", "", "NVDA")


# --- direct unit pins on the private guards ---------------------------------
# The public-behaviour tests above can mask a broken branch because two guards
# often fire on the same headline. These assert each branch in isolation, so
# deleting that branch fails here even when another guard still rejects the
# sentence.


def test_the_peer_ticker_list_guard_detects_a_list_that_does_not_lead_with_us():
    from tradingagents.dataflows.news_relevance import _peer_ticker_list_first

    assert _peer_ticker_list_first("INTC, AMD, MU, NVDA: Chip Stocks Rally", "NVDA")
    assert _peer_ticker_list_first("AMD, NVDA rise after earnings", "NVDA")
    # Listing us first is not a peer list.
    assert not _peer_ticker_list_first("NVDA, AMD and MU rally", "NVDA")
    # A lone ticker is not a list.
    assert not _peer_ticker_list_first("NVDA beats on demand", "NVDA")


@pytest.mark.parametrize("headline", [
    "Tech stocks led by Nvidia and AMD rally",
    "Semiconductor rally led by Nvidia",
    "Chip stocks lead gains with Nvidia higher",
    "Chipmakers lead the market gains",
    "Energy shares lead the sector lower as crude slides",
])
def test_the_multi_name_grammar_matches_its_breadth_shapes(headline):
    from tradingagents.dataflows.news_relevance import _MULTI_NAME_RE

    assert _MULTI_NAME_RE.search(headline), headline


@pytest.mark.parametrize("headline", [
    "Nvidia beats on data-centre demand",
    "Nvidia leads chip stocks higher on AI demand",
    "ExxonMobil reports record quarterly profit",
])
def test_the_multi_name_grammar_ignores_plain_company_reports(headline):
    from tradingagents.dataflows.news_relevance import _MULTI_NAME_RE

    assert not _MULTI_NAME_RE.search(headline), headline


def test_the_plural_group_helper_distinguishes_majors_from_a_major():
    from tradingagents.dataflows.news_relevance import _is_plural_group

    assert _is_plural_group("Oil Majors")
    assert _is_plural_group("Energy Stocks")
    assert not _is_plural_group("Oil Major")
    assert not _is_plural_group("Chip Giant")


def test_the_takes_aim_helper_only_fires_when_someone_else_takes_aim():
    from tradingagents.dataflows.news_relevance import _takes_aim_elsewhere

    assert _takes_aim_elsewhere("Huawei Takes Aim at Nvidia, AMD", "NVDA")
    assert _takes_aim_elsewhere("Billionaire takes aim at Apple", "AAPL")
    assert not _takes_aim_elsewhere("Apple Takes Aim at Nvidia Economics", "AAPL")
    assert not _takes_aim_elsewhere("Nvidia reports record revenue", "NVDA")
