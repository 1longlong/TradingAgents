# ADR-016 — Finnhub-only company news, with GDELT excluded from the configured path

**Status:** Retrospective documentation — human acceptance pending
**Provenance:** Reconstructed from the news migration
in the CAND-01 apparatus and the V2/V3 protocols.
**Related invariants:** INV-24.

**D2 renumbering (2026-11-21):** formerly `ADR 004`. Renumbered during the Release-first integration because the
personal `ADR 004` collided with a different Release decision. Code `file.py:line` citations below describe the
tree at the time of writing and are not revalidated by this renumbering.

## Context

The experiment needs a news path that is (a) symbol-specific, (b) date-range capable,
and (c) point-in-time defensible. The upstream v0.5.0 news stack offered more than
one source, but not all of them satisfied those requirements:

- The Yahoo ticker news endpoint was retired (HTTP 404); keeping it in a fallback
  chain only produced a permanent error.
- Alpha Vantage `NEWS_SENTIMENT` requires a key this project does not provision for
  news.
- GDELT is a discovery-style feed: it is broad and can return articles about a
  company, but it does not take a symbol and explicit date range in the same
  operation, and its historical precision is weaker than a symbol-scoped feed.
- A mixed chain can silently add a second feed to a run when the primary is down,
  which changes both the token cost and the evidence a run saw. That would invalidate
  a measured 2×2 comparison.

The experiment protocol therefore needs one feed, and it needs the absence of a
second feed to be provable, not merely intended.

## Options considered

### A. Keep a multi-source chain (Finnhub + GDELT + others) with fallback

**Rejected.** A fallback can silently change the news corpus mid-run, makes the
"same inputs across arms" claim false, and makes an outage in Finnhub look like a
successful run with GDELT evidence. It also reintroduces the retired/unprovisioned
paths that generate errors on every run.

### B. Use GDELT as the company-news source

**Rejected for company news.** It is not symbol-scoped, so relevance would have to be
inferred from text/URLs, and the PIT window is less precise. GDELT remains useful for
a study that deliberately wants macro/discovery coverage; it is not the right primary
for a ticker-scoped analysis.

### C. Route company news to Finnhub only; disable global news under that route

**Chosen.** `get_news` has exactly one configured route, `get_news_finnhub_only`,
which does not import or call GDELT. `get_global_news` under the Finnhub route
returns an explicit `CONFIG_DISABLED` status instead of borrowing company news or
another provider.

### D. Fall back to GDELT only when Finnhub fails, but mark the run

**Rejected.** Marking the run does not make the comparison valid: the run's evidence
and token cost have already changed. A failed Finnhub call should be visible as a
failed/`Unknown` news feed, not silently repaired with a different corpus.

### E. Delete GDELT entirely

**Rejected.** It is a working, tested source and the code may be selected explicitly
for a study that wants global/macro news. The requirement is that the *configured*
CAND-01 path cannot reach it, not that the repository must not contain it.

## Decision

- `data_vendors.news_data` and `tool_vendors.get_news` are `"finnhub"`.
- `get_news` maps `finnhub` to `get_news_finnhub_only`; that function has no GDELT
  dependency.
- `get_global_news` maps `finnhub` to `get_global_news_finnhub`, which returns
  `NewsStatus.CONFIG_DISABLED` with an explicit statement that Finnhub has no global
  endpoint and the path was not filled from another provider.
- GDELT remains implemented and tested but is reachable only by explicitly changing
  the vendor configuration. The shipped default never routes to it.
- Every merged news block carries a per-source status, so an outage, rate limit,
  empty window, auth problem, and disabled configuration are distinguishable
  (`NewsStatus` in `tradingagents/dataflows/news_status.py`).

## Rationale

- One symbol-scoped, date-bounded feed is the only configuration in which the two
  experiment arms can be said to have seen the same news path.
- Explicitly disabling global news is more honest than filling it with a different
  provider. An agent told "no global feed is configured" can say so; an agent given
  GDELT headlines under a Finnhub label would be misled about provenance.
- Keeping GDELT code available preserves a legitimate research option without
  weakening the default. The test is a tripwire on the Finnhub path, not a deletion
  test.
- The status taxonomy turns "no news" into a checkable claim: a dead feed forces
  `Unknown`, not a fabricated Neutral.

## Consequences

### Positive

- The configured news path cannot silently acquire a second feed. V3's protocol
  states "Finnhub only; GDELT excluded; global news `CONFIG_DISABLED`".
- News availability is derived from the real `get_news` `ToolMessage`s, not from the
  model's prose, so a dead company feed forces an explicit `Unknown` stance
  (`news_analyst.py:24-157`).
- The PIT cutoff and the undated-article rule are implemented on the Finnhub path:
  an article with no provable timestamp is dropped rather than assumed safe.
- The GDELT tripwire tests make "does not contact GDELT" executable.

### Negative

- The news analyst has no macro-headline feed in the shipped configuration, so its
  macro context relies on FRED series and prediction markets. That is a deliberate
  scope reduction, not an accident.
- Finnhub becomes a single point of failure for company news. The run reports the
  failure and forces `Unknown`; it does not recover coverage.
- The code still contains a second news path, so a future operator can re-enable
  GDELT. That is intentional, but it means the "Finnhub-only" property is a
  configuration invariant, not a code-level impossibility.
- The retirement of the Yahoo/Alpha Vantage news paths changes what a user of the
  upstream product would see; it is a branch decision, not an upstream v0.5.0
  behaviour.

## Evidence

- **Code:** `tradingagents/dataflows/interface.py:132-149` (route map and
  `get_news_finnhub_only`), `tradingagents/dataflows/finnhub_news.py:700-766`
  (`get_news_finnhub_only`, `get_global_news_finnhub`, `CONFIG_DISABLED`);
  `tradingagents/default_config.py:168-193`; `tradingagents/dataflows/news_status.py`;
  `tradingagents/dataflows/news_merge.py`; `tradingagents/dataflows/news_relevance.py`.
- **Commits:** the Finnhub-only migration landed with the CAND-01 × batch-macro
  apparatus at `b00dd00`; the scope is frozen in the V2/V3 protocols and the final
  tree is `50b2ca3`.
- **Tests:** `tests/test_finnhub_only_scope.py` (default config has no GDELT route;
  Finnhub route is the only entry point; GDELT tripwire; Finnhub outage is not
  rescued; global path is explicitly disabled and fetches nothing; headers name only
  the providers actually merged); `tests/test_finnhub_news.py`;
  `tests/test_news_dual_source.py`; `tests/test_news_status_taxonomy.py`;
  `tests/test_news_lookahead.py`; `tests/test_cand01_news_positive_path.py`.
- **Reports:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`
  and `EXPERIMENT_PROTOCOL_V3.md` (Finnhub-only, GDELT excluded, global
  `CONFIG_DISABLED`); `BRANCH_HISTORY_REPORT.txt` §3.4.

## What this ADR does not claim

It does not claim GDELT is broken or removed, and it does not claim the Finnhub feed
is complete. It claims the configured CAND-01 path uses Finnhub only, that the global
feed is explicitly disabled rather than borrowed, and that a second feed cannot be
silently added by fallback. The scope is a configuration invariant; a future operator
who selects `gdelt` deliberately is outside it.
