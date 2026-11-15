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
| `R01` | 1  | NVDA | C0 | false | true  | true  | true  | `bdbd531ec8c0de14cce0db574f5a47cdef9ba6f8c0e62549b3982f0aad6df407` |
| `R02` | 2  | NVDA | AB | true  | false | true  | true  | `0c998239ac70316af6e0f59a860614c2a881548a8c0ee27d3257947715686e5e` |
| `R03` | 3  | NVDA | CC | true  | true  | true  | true  | `a9d2aff62baa5a6007b29c62d38f62ee028b4ad4383c3f74307708ef18a8bd19` |
| `R04` | 4  | NVDA | B  | false | false | true  | true  | `b2e780920ca89a85a5c7f2716d23b8e22c9e03120c794f764a239672ae04f900` |
| `R05` | 5  | AAPL | C0 | false | true  | true  | true  | `72cf570ce8f74b30aa0969435ce9cbca2a8554a4bf05fd5ad80a845f4902b173` |
| `R06` | 6  | AAPL | B  | false | false | true  | true  | `c88b6e3a174432e5e8cb37299891f2e6973510528703a0b856d7fddf159470db` |
| `R07` | 7  | AAPL | CC | true  | true  | true  | true  | `65c4086691ea9eb522ff64655fd1bed5434795c6a937cbd977cdc83e7cf22b1f` |
| `R08` | 8  | AAPL | AB | true  | false | true  | true  | `617d2b3c850a9a56f288ed590f1d8ea5f45964557cae1e295bb087d2ae6981c9` |
| `R09` | 9  | JPM | C0 | false | true  | true  | true  | `68a60ea4bc9ebb911db21a60e147cdc541f88880f51eab5a1135a1b0028df16b` |
| `R10` | 10 | JPM | AB | true  | false | true  | true  | `c57f7a18b87bb056d9a3dcce6648b770fc751e9d9e6f7eda4525ff064e4b476a` |
| `R11` | 11 | JPM | B  | false | false | true  | true  | `52985cb2896f675b2ca35a4eea245cafe5ded9ee2af4873c56efdc1df63ade6a` |
| `R12` | 12 | JPM | CC | true  | true  | true  | true  | `eeabfa7b25d20d293111a627c9a2b4d480df462ff9ccbf31845039cecafd7110` |
| `R13` | 13 | XOM | C0 | false | true  | true  | true  | `71a2cb376a0a8d845c19049f815364ca1062902b9c007f26cbb9fc1806d94cf1` |
| `R14` | 14 | XOM | CC | true  | true  | true  | true  | `ed53794d3fc340d38da413875011a672b3c6bdb98ead99a6f254604a9b82fbb3` |
| `R15` | 15 | XOM | B  | false | false | true  | true  | `98d3b0b99e1a48ba8494f1b285f995badf079a0d5621ce9e214b3b2e95df94e4` |
| `R16` | 16 | XOM | AB | true  | false | true  | true  | `4f8c6e8c84a7681780f19c1ed698298cef7d94c4030c0ed3ba917fa73c253ab2` |

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
  are recorded separately; the **raw vendor usage blob** is preserved per call
  (`reported_usage_raw`, bounded, no message content) so a parsed total can be
  re-examined against the provider's own numbers (limitation L-5, closed).
* **Negative counts are not counts.** A negative token count is rejected at
  extraction and recorded in `usage_checks.negative_token_counts`; it can never
  enter a sum or certify a run (limitation L-5, closed).
* **Partial runs keep their usage.** Interrupted runs retain every event already
  recorded. Completeness is *derived from the counts* on every read, not
  remembered from the newest event, so a later partial call cannot leave a flag
  reading "complete" (limitation L-5, closed).
* **The usage verdict gates validity (U-1).** Every telemetry payload is
  classified as one of:

  | Verdict | Meaning |
  | --- | --- |
  | `VALID` | every call reported usage, every field present, attribution complete, replay agrees with the totals |
  | `MISSING` | no provider usage at all (or no LLM call): nothing was measured |
  | `INCOMPLETE` | usage exists but not for every call / field, an event is unattributed, or the run did not finalize |
  | `MISMATCH` | the payload contradicts itself or the replay: counts that do not add up, negative totals, per-call events that do not sum to the run totals, or a replay total different from the telemetry total |

  Only `VALID` can produce a measured sample. `agrees_with_telemetry` is now
  **consumed**: it was computed and ignored, so a disagreeing run still reported
  `valid=True` (audit C round 5, U-1). A run with `MISSING` usage publishes
  `total_tokens: null`, never `0`.
* **Budget.** The registration states the contract explicitly:
  `budget_mode = "uncapped_authorized"` with `max_total_tokens = null` (U-2). A
  `null` cap is *only* "unlimited" when that mode is present; a missing file, a
  malformed block, a missing mode or a non-integer cap are each a distinct
  refusal (`BUDGET_PROTOCOL_MISSING`, `BUDGET_CONFIG_MALFORMED`,
  `BUDGET_MODE_MISSING`, `BUDGET_CAP_INVALID`, …), never an implicit uncapped
  run. The gate still distinguishes used / reserved / remaining /
  `UNKNOWN_SPEND` / `UNCAPPED` / `OK` / `EXHAUSTED`, and under `UNKNOWN_SPEND`
  spend is **not** reported as zero. See `BUDGET_GUARD_DESIGN.md`.

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
| `S9` | A run's usage verdict is `MISMATCH` or `MISSING` (U-1). The run is void, not a sample; a `MISMATCH` also means the harness and the provider disagree about what was spent, which is a round-level stop rather than a single bad sample |
| `S10` | The budget contract cannot be interpreted (U-2: missing file, malformed block, missing `budget_mode`, non-integer cap). Nothing may be spent against an unknown budget |
| `S11` | The final-freeze verification fails (`scripts/c3_verify_final_freeze.py`): `HEAD`, the record, the tag and the append-only designation must all name the same commit, and the tree must hash to the recorded fingerprint |

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
reproducible byte-for-byte. Run against the delivered directory,

```
python scripts/gen_cand01_batch_16run_specs_v2.py --out <batch> --check
```

reports *OK: 53 artefacts reproduce; 16 differ only in volatile fields* and
exits 0. The 16 `code_state.json` files are the volatile ones: they carry
`timestamp_utc`, `git_working_tree_dirty`, `generator_sha256`,
`git_head_commit` and `git_branch`, which are properties of *when*, *with which
generator file* and *on which checkout* the registration ran — not of the
design. Every hash-bearing artefact (`spec.json` bodies, `experiment.json`,
`SWITCH_MATRIX.csv`, `CONFIG_HASH_MANIFEST.csv`, `RUN_MANIFEST_TEMPLATE.csv`,
`EXECUTION_ORDER.txt`) reproduces byte-identically.

`RUN_MANIFEST_TEMPLATE.csv`'s `spec_body_sha256` column is the generator's own
definition — the canonical JSON of the spec body minus the machine-specific,
unhashed `results_dir` — and is checked against that function, not against the
`spec.json` file bytes. (An earlier revision of this column was rewritten with
the file-bytes formula and a test enshrined the error; audit B-03 found both.)
Any change to the design, the seed, the hash algorithm or the news scope
requires a **new protocol version**; V1 and V2 both remain on disk unmodified.

### 14.1 Amendment — budget contract and usage verdict (V2.1)

Two fields change how a run is validated, neither of which touches the design
(stocks, arms, trade date, models, seed, order):

1. `budget` now carries `budget_mode = "uncapped_authorized"` alongside
   `max_total_tokens = null`. `budget` was already a hashed field, so **every
   `config_sha256` moved**; the table in §5 was rewritten by
   `gen_cand01_batch_16run_specs_v2.py --write-protocol-table`, never edited by
   hand, and `CONFIG_HASH_MANIFEST.csv` / `RUN_MANIFEST_TEMPLATE.csv` were
   regenerated with it.
2. The usage verdict in §9 is consumed by the validity check (U-1).

`protocol_version` in every registration is `"V2.1"`. The V2 design is
unchanged; this amendment records *why the hashes are new* and keeps the
pre-registration honest instead of presenting hashes that no longer match their
registration.

### 14.2 What is certified, and by what

The final freeze is one commit, named by `c3/FROZEN_COMMIT` and by an annotated
tag `c3-final-freeze`, and recorded in `c3/FREEZE_RECORD.json` (commit, tree,
fingerprint, per-spec hashes, generator and protocol hashes). It is verified by

```
python scripts/c3_verify_final_freeze.py
```

which requires `HEAD`, the record, the tag and the append-only
`c3/FREEZE_HISTORY.jsonl` designation to name the **same** commit — a later
commit moves `HEAD` and fails the check. The previous record designated an
ancestor of `HEAD`, so `HEAD == FROZEN_COMMIT` could never hold again; that is
the defect this replaces.
