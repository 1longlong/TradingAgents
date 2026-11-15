# CAND-01 × Batch-Macro 2×2 — Experiment Protocol **V2**

| | |
| --- | --- |
| Protocol version | **V2** (re-registration of V1) |
| Directory | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/` |
| Supersedes | `cand01_batch_16run/CAND01_BATCH_2X2_PROTOCOL.md` (V1) — **kept unchanged** |
| Generator | `scripts/gen_cand01_batch_16run_specs_v2.py` |
| Registered | 2026-11-15 |
| Status | **FROZEN** — any change requires a new protocol version |
| Runs | 16 (4 stocks × 4 arms), one measured run each |
| Paid calls made under this protocol so far | **0** |

---

## 1. Why V2 exists

V1's specs were produced by `scripts/gen_cand01_batch_16run_specs.py`, which was
**never committed**. It existed only as an untracked file in a scratch worktree
that no longer exists. It is not recoverable from:

* any git ref, branch, tag, commit or the git bundle;
* any of the three stashes;
* the frozen backup tree or the snapshot tarball;
* the still-present V1 spec directories (which contain only its *output*).

The consequence is specific and severe: **the `config_sha256` algorithm that
produced the 16 V1 hashes is unknown.** The V1 protocol names the function
`token_benchmark.experiment_config_hash`, and that name does not exist in
`scripts/token_benchmark.py` or anywhere else in the tree. Seventeen attempts to
reconstruct the algorithm from the stored hash values (varying field sets,
serialisation, key ordering and path handling) produced **0/16** matches against
the recorded target `fa62c147…291f` for R01.

Two options were available:

1. **Hand-write** the 16 specs so they carry the old hashes. This is forbidden:
   V1 §4.6 requires specs to be *derived, never hand-written*, and a
   hand-written hash is a fabricated hash.
2. **Re-register** the experiment under a new protocol whose generator and hash
   algorithm are committed, documented and tested.

Option 2 was taken. **No V1 hash is reused, and no attempt was made to make V2
hashes match V1 hashes.** All 16 V2 hashes are new. That is the intended and
recorded outcome of re-registration, not a defect.

V1 is **not deleted and not modified**. Its specs remain on disk at
`cand01_batch_16run/generated/` as historical evidence.

---

## 2. What changed between V1 and V2

| Aspect | V1 | V2 |
| --- | --- | --- |
| Generator | lost, uncommitted | committed, stdlib-only, deterministic |
| Hash algorithm | undocumented, unrecoverable | documented in §6, reimplementable from prose |
| Hashed field list | unknown | explicit frozen tuple (`HASHED_FIELDS`) |
| `config_sha256` values | 16 pre-registered values | **16 new values** (§5) |
| `switches_required` | `false` in the round file, `true` per-run | `true` everywhere |
| News scope | declared Finnhub-only, but `get_news` was `"finnhub,gdelt"` and GDELT was called twice per run | genuinely Finnhub-only; GDELT excluded (§4) |
| Switch delivery | undocumented | documented: `TRADINGAGENTS_*` env vars (§7) |
| Switch verification | lost with the generator | committed module + tests (§7) |
| Provenance wording | hard-coded "Finnhub + GDELT" header | header states only the providers actually merged |

**Held constant:** stocks, arms, trade date, models, seed, execution order,
rounds, language, cache policy, and the (unset) token budget. V2 reproduces the
V1 *design* exactly — this is verified by
`tests/test_cand01_batch_16run_v2_infra.py::test_execution_order_matches_the_v1_pre_registered_order`
and by a comparison of all 16 V1 and V2 `cases` and `switches` blocks.

---

## 3. Experimental design (2×2)

Two factors, each on/off:

* **`single_pass`** — CAND-01: the analyst emits its structured report on the
  call that would have written prose, instead of prose then a regeneration.
* **`batch_macro`** — the news analyst is given the batched macro tool.

| Arm | `batch_macro` | `single_pass` | `structured` | `s2_downstream` |
| --- | --- | --- | --- | --- |
| `B`  | false | false | true | true |
| `AB` | true  | false | true | true |
| `C0` | false | true  | true | true |
| `CC` | true  | true  | true | true |

`structured` and `s2_downstream` are **held constant** across all four arms. This
is a deliberate design choice, stated plainly here:

* `structured = true` everywhere, because CAND-01 only has an effect when the
  structured output is enabled (`GraphSetup` computes `single_pass AND structured`).
* `s2_downstream = true` everywhere because **there is no OFF implementation**.
  S2 field routing is unconditional in `tradingagents/agents/utils/s2_context.py`.
  The spec accepts only `true` and **refuses** `false` with an explicit message
  rather than inventing a no-op toggle. Consequence: **this round cannot estimate
  an S2-downstream effect**, and it does not claim to.

### Stocks and dates

| Block | Ticker | Trade date | Rationale |
| --- | --- | --- | --- |
| 1 | `NVDA` | 2026-09-23 | high-beta growth / AI semis |
| 2 | `AAPL` | 2026-09-23 | mega-cap tech, index-heavy |
| 3 | `JPM`  | 2026-09-23 | financials, rate-sensitive |
| 4 | `XOM`  | 2026-09-23 | energy, commodity-linked |

All four share one trade date, so the market regime is held constant and the
stock is used as a **block**, never as an independent replicate.

Analysts: `market`, `news`, `fundamentals` (the `social` analyst is excluded, so
every arm runs the same agent set). `research_rounds = 1`, `risk_rounds = 1`,
`output_language = English`, `cache_policy = preserve_existing`,
`checkpoint_enabled = false`, `max_total_tokens = null`.

Models: `provider = openai_compatible`, both `quick_model` and `deep_model` are
`CS5351/DeepSeek-V4-Flash`.

---

## 4. News scope: Finnhub-only, GDELT excluded

This is the scope the 16 runs execute under.

| Tool | Route | Behaviour |
| --- | --- | --- |
| `get_news` | `finnhub` → `get_news_finnhub_only` | Finnhub symbol-scoped company news only. Never contacts GDELT. |
| `get_global_news` | `finnhub` → `get_global_news_finnhub` | **Explicitly disabled**: returns `NEWS_STATUS=CONFIG_DISABLED`. |

### 4.1 Why GDELT is excluded

V1 declared "Finnhub-only" but shipped `get_news: "finnhub,gdelt"`, and the
`finnhub` route resolved to `get_news_combined`, which called **both** Finnhub
and `get_news_gdelt` and merged them. GDELT was therefore called **twice per
run** (once via the merge, once via the explicit chain), in every arm. That
makes the news input a two-provider feed while the protocol claims one, and it
lets a Finnhub outage be masked by a second provider. Both are unacceptable for
a cost comparison where the news prompt is a measured input.

### 4.2 Why global news is disabled rather than filled

Finnhub's free tier serves **symbol-scoped company news only**; it has no
global/macro endpoint. The two dishonest alternatives were rejected:

* presenting Finnhub company news as "global news" — mislabels a company feed; and
* quietly substituting GDELT — contradicts the declared scope.

`NewsStatus.CONFIG_DISABLED` is the project's existing semantic for "the vendor
is switched off in configuration". It is distinct from `EMPTY_VALID` (a genuine
absence), from `RATE_LIMITED`, and from every error class, so a deliberate
absence can never be read as an outage or as a quiet market. The disabled path
performs **no fetch of any kind**.

Since independent audit A-03, `render_status` gives `CONFIG_DISABLED` its **own
sentence** ("deliberately not requested … nothing was attempted and no error
occurred … report the news as excluded"). Before that fix it reused the shared
"**could not answer**" wording that every real failure class emits, which made a
deliberate exclusion read exactly like an outage and invited a reader to wait
for a recovery that never comes. The phrase *"says nothing about the
instrument"* is retained, because it is the taxonomy's invariant for every
non-`EMPTY_VALID` class.

### 4.3 Proof obligation

The scope is verified on the **execution path**, not by grepping config strings:

* `tests/test_finnhub_only_scope.py` installs a GDELT tripwire on both
  `gdelt_news` module attributes *and* the routing table, then invokes the real
  analyst tools; it asserts **0 GDELT calls**, including when Finnhub is forced
  to fail.
* An AST walk of `get_news_finnhub_only` and `get_global_news_finnhub` confirms
  there is **no executable** GDELT reference (lazy imports included).
* A mutation test points `get_news` back at `get_news_combined`; **3 tests fail**
  and the interceptor records the GDELT call.

Legacy providers are unreachable: the Alpha Vantage `NEWS_SENTIMENT` and Yahoo
news paths were removed from the routing table, and `historical_news` /
`yfinance_news` are deleted.

---

## 5. Pre-assigned Run IDs and hashes

Run IDs are assigned **before** execution, in execution order, so an ID can never
later be reused for a different (stock, arm) cell. `Rnn` == execution position.

| Run | Pos | Block | Arm | `batch_macro` | `single_pass` | `structured` | `s2_downstream` | `config_sha256` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `R01` | 1  | NVDA | C0 | false | true  | true | true | `3d5500170779a90284f3869d745bcdafdcee8b57800a22e6d7f42062dbb71a03` |
| `R02` | 2  | NVDA | AB | true  | false | true | true | `9cd7241382233fd40c28fc0588463cd5ed51e9432666139e64030f11bd994efe` |
| `R03` | 3  | NVDA | CC | true  | true  | true | true | `80367bf3d532abccf974bb22c4834d7ec2ab556c1ce4d0d229d79803e225a27d` |
| `R04` | 4  | NVDA | B  | false | false | true | true | `dbab594d30fb906cd269402a59046d4ce1932423953841e5d720240b1f5771ec` |
| `R05` | 5  | AAPL | C0 | false | true  | true | true | `d1ea84c6c61bc7eb1890eaef38a8989edf6e3f980e5ffa797d91ed8837cc17d7` |
| `R06` | 6  | AAPL | B  | false | false | true | true | `7179532fc5826b0fc8ef3803c72d63cc3f925db5513c38ae4ea41fd49d163ce7` |
| `R07` | 7  | AAPL | CC | true  | true  | true | true | `8658b8a1018938cb24cfc0f5a3225b0d65b9819453061c9dbb58fb3f05e4079b` |
| `R08` | 8  | AAPL | AB | true  | false | true | true | `b07f7deb710dcca2b92f5af2f16714a8f7a91f5cfb0a07f18093d5f93ab18937` |
| `R09` | 9  | JPM  | C0 | false | true  | true | true | `e74be5b613f4ef1a4b134ddcf4edd0b89339599a7e772c00ceba43be004bc7d3` |
| `R10` | 10 | JPM  | AB | true  | false | true | true | `fbc6991e902ac4b63dc034ed43dd7fe35d6b27af9698c3a9cb9b5bc1e5f4de15` |
| `R11` | 11 | JPM  | B  | false | false | true | true | `ecaf062211a22bc993263bc7658bb67bd43c66c2fe58b79a1a6c96f67d91211c` |
| `R12` | 12 | JPM  | CC | true  | true  | true | true | `beb4bcb49776427dbbcc07965d5033f18ba382a22cf1c4b92385c25c123c31f7` |
| `R13` | 13 | XOM  | C0 | false | true  | true | true | `0f6ae6639ab4a2e1b334d35e33dc0a7f71f51c0195ef8eef1b44cde19490e8bc` |
| `R14` | 14 | XOM  | CC | true  | true  | true | true | `a2fae64deebd314796d4b0f18c1467496890a5e7f291b23c9b7aa90edfb09c80` |
| `R15` | 15 | XOM  | B  | false | false | true | true | `df852fb531915549ec1cb67cc26e7853dbfd83655ebacb99d7f5b290b58a7108` |
| `R16` | 16 | XOM  | AB | true  | false | true | true | `eb478d2b5337a8a6729ecc6cf5c399bed9319f541bf27d3ef46aa197839f6ffe` |

Machine-readable copies: `CONFIG_HASH_MANIFEST.csv`, `RUN_MANIFEST_TEMPLATE.csv`,
`SWITCH_MATRIX.csv` (all generated, never hand-edited).

---

## 6. The `config_sha256` algorithm

Defined by `scripts/gen_cand01_batch_16run_specs_v2.py::config_sha256`.

| Element | Specification |
| --- | --- |
| Input | exactly the fields in `HASHED_FIELDS` (below) |
| Canonicalisation | `json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))` |
| Encoding | UTF-8 |
| Digest | lowercase hex SHA-256 |
| Self-hashing | **excluded** — `config_sha256` is not in `HASHED_FIELDS` |
| Excluded by design | `config_sha256`, `description` (prose), `protocol_version`, `measured_runs`, and any absolute path |

```python
HASHED_FIELDS = (
    "experiment_id", "schema_version", "switches_required", "provider",
    "quick_model", "deep_model", "output_language", "cache_policy",
    "checkpoint_enabled", "budget", "cases", "switches", "news_scope",
)
```

Because the field list is a frozen tuple, adding a non-configuration key cannot
change a hash, and changing any configuration key always does. A missing hashed
field raises `KeyError` rather than silently hashing a default.

**Machine-checked properties** (`tests/test_cand01_batch_16run_v2_infra.py`):

* all 16 values distinct, all 64 lowercase hex;
* recomputation matches the stored value for every run;
* flipping **any** of the four switches changes the hash (4 parametrised cases);
* changing provider / either model / language / cache policy / checkpoint /
  `switches_required` / the case / the news scope changes the hash;
* changing an excluded field does **not** change the hash;
* dropping a hashed field raises;
* non-vacuity: deleting `"switches"` from the field list makes **6 tests fail**.

`spec_body_sha256` is a separate, secondary identity: SHA-256 of the run spec
minus `results_dir`, so two checkouts on different machines agree.

---

## 7. Switch delivery and consumption

Switches reach the child process as environment variables, which
`tradingagents/default_config.py` applies as config overrides **before** the
graph is built:

| Switch | Environment variable | Config key |
| --- | --- | --- |
| `batch_macro` | `TRADINGAGENTS_BATCH_MACRO_ENABLED` | `batch_macro_enabled` |
| `single_pass` | `TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED` | `single_pass_finalization_enabled` |
| `structured` | `TRADINGAGENTS_STRUCTURED_ANALYST_OUTPUT_ENABLED` | `structured_analyst_output_enabled` |

Verified per arm in a **fresh interpreter** (as the harness spawns it) by
`test_switch_env_vars_reach_the_child_configuration`.

Switches are also written into every spec (`switches`, `switches_source:
"declared"`, `config_sha256`) so the child can verify what it was asked to run.

### 7.1 Consumption verification

`tradingagents/graph/switch_verification.py` compares the declared switches with
the kwargs `GraphSetup` actually passes to each analyst factory, and with the
news `ToolNode`'s bound tools. It fails loudly on any mismatch.

Two traps are pinned by tests:

1. **Namespace.** `GraphSetup` binds the analyst factories into its own module
   globals at import time, so interception must patch
   `tradingagents.graph.setup`. Patching `tradingagents.agents` intercepts
   **0** calls — measured, not assumed.
2. **The AND.** `GraphSetup` computes `single_pass AND structured`, so an arm
   declaring `single_pass=true, structured=false` runs single-pass OFF. The
   verifier compares against the AND, not the raw flag.

A consumer that was never captured is an **error**, never a skip; a non-`bool`
switch value is rejected. `tests/test_switch_consumption.py` drives the **real**
`GraphSetup` for all four arms.

---

## 8. Randomised execution order

| Parameter | Value |
| --- | --- |
| Seed | `20261114` (unchanged from V1) |
| Algorithm | one `random.Random(20261114)` created **once**; `shuffle(["B","AB","C0","CC"])` called once per block; blocks visited in `NVDA, AAPL, JPM, XOM` |
| Implementation | CPython stdlib `random.shuffle` (Mersenne Twister), stable in CPython ≥ 3.11 |
| Rebuild | `execution_order()` in the generator; recorded in `EXECUTION_ORDER.txt` |

```
NVDA: ['C0', 'AB', 'CC', 'B']
AAPL: ['C0', 'B', 'CC', 'AB']
JPM:  ['C0', 'AB', 'B', 'CC']
XOM:  ['C0', 'CC', 'B', 'AB']
```

This **is** V1's corrected pre-registered order; a test asserts equality so the
re-registration cannot silently re-randomise the study.

---

## 9. Usage accounting rules

The authoritative implementation is `tradingagents/observability.py`.

* **MISSING is never 0.** A call with no provider usage increments
  `llm_calls_without_provider_usage` and leaves token fields `None`. `None` is
  never coerced to `0`; an unknown consumption is never reported as a known one.
* **No double counting.** Duplicate `on_llm_end` delivery for the same LangChain
  `run_id` is dropped once the event has been emitted (`_llm_starts` +
  `emitted`).
* **Separate fields.** prompt / completion / total / cached / reasoning tokens
  are recorded separately; raw vendor usage is preserved via `usage_source`.
* **Partial runs keep their usage.** Interrupted runs retain every event already
  recorded; a run is only `usage_complete` when the newest event asserts
  completeness, and completeness is never downgraded by a later partial.
* **Budget.** `max_total_tokens = null` this round: the cap is **unset by
  design**. The gate distinguishes used / reserved / remaining / `UNKNOWN_SPEND`
  / `UNCAPPED` / `OK` / `EXHAUSTED`; under `UNKNOWN_SPEND` spend is **not**
  reported as zero. See `BUDGET_GUARD_DESIGN.md`.

---

## 10. Data quality control

| ID | Check | On failure |
| --- | --- | --- |
| `DQ1` | Run produced a complete graph ending in a final decision | run recorded `INVALID`, excluded |
| `DQ2` | Telemetry present and parseable | run recorded `INVALID` |
| `DQ3` | Provider usage present for every LLM call | run flagged `USAGE_INCOMPLETE`, excluded from token means but retained |
| `DQ4` | No LLM error events beyond the retry allowance | run flagged, reported separately |
| `DQ5` | Effective switches equal the spec's declared switches (AND rule applied) | run **aborted before any further call** |
| `DQ6` | News block reports a real status (not a silent empty) | recorded; the status is part of the observation |

---

## 11. Stopping conditions

The round stops (rather than continuing to spend) on:

| ID | Condition |
| --- | --- |
| `S1` | Any run's effective config disagrees with its spec → abort **before** the paid call |
| `S2` | Auth failure (`AUTH_MISSING` / `AUTH_INVALID`) on a run. **Check this before spending:** audit A-01 found the harness never forwarded `FINNHUB_API_KEY` (fixed this round). If the preflight does not list it as configured, all 16 runs would fail identically — stop and fix the credential, do not start |
| `S3` | Sustained provider throttling (`RATE_LIMITED`) that would skew an arm |
| `S4` | Switch-consumption verification refuses the graph |
| `S5` | A run produces no valid telemetry |
| `S6` | Working-tree fingerprint drifts between runs |
| `S7` | Any evidence that GDELT was contacted |
| `S8` | Operator stop request |

---

## 12. Statistical analysis plan

**n = 4. This is an exploratory study.** No significance test is performed and no
claim of statistical significance is made, at any point, in any report.

Every quantity is reported as a **descriptive estimate with its per-stock
values**:

1. **Four cell means** — mean across the four stocks for each arm.
2. **CAND-01 main effect** — within each stock, `mean(CC, C0) − mean(AB, B)`,
   reported per stock and as the mean of the four stock-level differences.
3. **Batch-Macro main effect** — within each stock, `mean(CC, AB) − mean(C0, B)`.
4. **Interaction** — `(CC − C0) − (AB − B)` per stock, then averaged. A large
   interaction means the two features are not additive and the main effects
   alone would misdescribe the system.
5. **Per-stock paired differences** — the four paired values behind each effect,
   always shown, never only the mean, because n = 4 makes a single stock able to
   dominate an average.
6. **Agent-level token differences** — per agent, not just per pipeline, since
   CAND-01 and batch-macro act on different agents.
7. **Pipeline-level token differences** — total tokens per run.
8. **Stock as a block** — stocks are a blocking factor, not replicates; the four
   stock-level differences are the unit of description.

Primary outcome: `total_tokens` per run (provider-reported). Secondary:
per-agent tokens, wall-clock duration, and decision agreement across arms.

---

## 13. Known limitations

1. **n = 4, exploratory.** No inferential statistics; four stocks in one regime
   on one date cannot support generalisation.
2. **No S2-downstream estimate.** `s2_downstream` has no OFF implementation and
   is refused when `false`.
3. **Global news is disabled.** All arms run without macro news, so any effect
   attributable to global news is outside this study's scope; this is a property
   of every arm, so it cannot bias the arm comparison.
4. **Single provider.** News depends on Finnhub availability; a provider outage
   affects all arms and is not compensated by a second feed.
5. **V1 hashes are void.** The 16 V1 `config_sha256` values cannot be
   reproduced, so no V1 artefact may be used as a comparison baseline for V2.
6. **V2 has not been executed.** Zero paid calls have been made under this
   protocol; these specifications are pre-registration, not results.
7. **Generator provenance.** `code_state.json` records the generating commit and
   branch; at registration time the changes were uncommitted in the working
   tree, so the recorded `git_working_tree_dirty` flag is `true`.

---

## 14. Freeze statement

This protocol and the 16 generated specs are frozen as of registration. The 16
specs are **derived** by `scripts/gen_cand01_batch_16run_specs_v2.py` and
reproducible byte-for-byte. `--check` reports *53 artefacts reproduce; 16 differ
only in volatile fields* — the 16 `code_state.json` files carry `timestamp_utc`,
`git_working_tree_dirty` and `generator_sha256`, which are properties of *when*
and *with which generator file* the registration ran. Every hash-bearing
artefact (`spec.json` bodies, `experiment.json`, `SWITCH_MATRIX.csv`,
`CONFIG_HASH_MANIFEST.csv`, `RUN_MANIFEST_TEMPLATE.csv`, `EXECUTION_ORDER.txt`)
reproduced byte-identically in a full regeneration at a different root; the only
difference in the 16 `spec.json` files was the declared, unhashed `results_dir`.
Any change to the design, the seed, the hash algorithm or the news scope
requires a **new protocol version**; V1 and V2 both remain on disk unmodified.
