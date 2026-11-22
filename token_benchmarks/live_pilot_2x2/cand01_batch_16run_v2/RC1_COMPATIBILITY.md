# RC1 Compatibility — CAND-01 × Batch-Macro 2×2 (V2)

| | |
| --- | --- |
| RC1 commit | `9948bf8545cceeb0d7a60cda913a04826a06c007` |
| `rc1` tag | resolves to `9948bf8545cceeb0d7a60cda913a04826a06c007` |
| Branch at review time | `feature/token-observability` |
| RC1 HEAD modified this round | **No** |
| Commits made | **0** |
| Pushes made | **0** |

---

## 1. What RC1 is

RC1 is the frozen, validated baseline of the TradingAgents project. It is the
reference against which every change in this work is judged: any test that fails
on RC1 too is a **pre-existing** problem and must be reported as such, never
hidden or "fixed" by editing the test.

RC1 was not modified. All work happened in a scratch worktree whose content was
copied from the working tree, and the delivered artefacts sit in the working
tree as uncommitted changes awaiting review.

---

## 2. Test compatibility with RC1

Both the RC1 checkout and the current candidate were run with the **same**
interpreter, the same `.env` and `TZ=UTC`, after clearing `__pycache__`.

| Suite | Result |
| --- | --- |
| RC1 baseline (`/tmp/opencode/rc1_baseline`) | **2 failed, 1471 passed, 2 skipped** |
| Candidate (V2 tree) | **2 failed, 1889 passed, 2 skipped** |

### 2.1 The two failures are pre-existing, not introduced

| Test | Status |
| --- | --- |
| `tests/test_cli_prefs.py::test_selections_are_remembered_after_a_run` | FAILS on RC1 too |
| `tests/test_cli_prefs.py::test_a_remembered_endpoint_is_offered_back` | FAILS on RC1 too |

* `tests/test_cli_prefs.py` is **byte-identical to RC1** (`git diff --quiet 9948bf8 -- tests/test_cli_prefs.py` reports no difference).
* The same two tests fail in a pristine RC1 checkout with no candidate code
  present.

**Root cause.** `tradingagents/__init__.py` calls
`load_dotenv(find_dotenv(usecwd=True))` at import time, so the developer's
`.env` populates `DEFAULT_CONFIG`. The CLI therefore skips the interactive
model-selection prompt the tests expect to drive, and the recorded selections
differ.

Which keys matter:

| `.env` key | Effect on the two failures |
| --- | --- |
| `TRADINGAGENTS_LLM_PROVIDER` | reproduces **both** failures on its own |
| `TRADINGAGENTS_DEEP_THINK_LLM` | reproduces **one** |
| `TRADINGAGENTS_QUICK_THINK_LLM` | reproduces **none** |
| `TRADINGAGENTS_LLM_BACKEND_URL` | contributes with the provider key |

This is an environment-coupling defect in the tests, not a product defect. It
was **not** worked around: `.env` was not modified, and the tests were not
edited. Running with the four `TRADINGAGENTS_*` selection keys absent gives
**12 passed, 0 failed** for that file.

**Recorded position:** pre-existing, documented, not introduced by this work,
and not a gate for the pilot as long as it is disclosed. Fixing it would mean
making the CLI tests hermetic — a separate change that must not be smuggled into
an experiment-preparation round.

---

## 3. Product behaviour that changed relative to RC1

These are intentional, and each is covered by tests.

| Change | RC1 behaviour | V2 behaviour |
| --- | --- | --- |
| Company news routing | `finnhub` → `get_news_combined` (Finnhub **+ GDELT**) | `finnhub` → `get_news_finnhub_only` (Finnhub only) |
| Global news routing | `gdelt` only | `finnhub` → `CONFIG_DISABLED`; `gdelt` still registered but unselected |
| Default `tool_vendors["get_news"]` | `"finnhub,gdelt"` | `"finnhub"` |
| Default `tool_vendors["get_global_news"]` | `"gdelt"` | `"finnhub"` |
| News provenance header | hard-coded "Finnhub company news + GDELT discovery" | names only the providers actually merged |
| `get_news_combined` | reachable via routing | retained for historical scripts, **not** in the routing table |

RC1's GDELT path is **not deleted**: `gdelt_news.py` and its
`get_news_gdelt` / `get_global_news_gdelt` remain registered under the `gdelt`
vendor key and still pass their own test suites. Any future study that wants
macro news can select `gdelt` explicitly. The change is a **default and routing**
change, not a removal, so RC1 users who explicitly configure `gdelt` are
unaffected.

The removed-in-earlier-rounds Alpha Vantage `NEWS_SENTIMENT` and Yahoo news paths
stay removed; RC1 already lacked them in some paths and their providers are
either unprovisioned or retired.

---

## 4. Components carried forward unchanged

| Component | State |
| --- | --- |
| CAND-01 single-pass implementation (`agents/analysts/*`, `graph/setup.py`, `agents/utils/structured.py`) | present, tested |
| PF-01 news-source classification fix (`news_analyst.py`) | present, non-vacuity proven by mutation |
| `scripts/token_benchmark.py` (the real Harness) | present, unmodified by this round |
| `tradingagents/observability.py` | present, unmodified by this round |
| Three git stashes | present |
| `.env` | unmodified (`2eea6491…9645`) |
| Historical experiment data | unmodified |

---

## 5. Compatibility verdict

* RC1's commit and tag are intact.
* No test that passes on RC1 fails on the candidate.
* Every failure is present on RC1 as well, in a byte-identical test file.
* Every behaviour change is deliberate, documented in the V2 protocol, and
  covered by a test that fails if the change is reverted.

**Verdict: compatible with RC1, with one disclosed pre-existing test defect.**
