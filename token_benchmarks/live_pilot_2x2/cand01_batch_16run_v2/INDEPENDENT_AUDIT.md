# INDEPENDENT_AUDIT.md — Plan C2

Three independent subagent audits were run against the real worktree
(`/tmp/opencode/planC2_wt` @ `9948bf8`, dirty) with no paid LLM calls and no
Pipeline runs. Each auditor was given a scope, not a conclusion, and was
required to execute code rather than read intent. Raw auditor artefacts are in
`logs/audit/`.

**Concurrency note (disclosed):** the three audits ran in parallel against the
same working tree, and remediation of Audit A began while B and C were still
running. Audit C flagged this explicitly. It means (a) a suite-wide "all green"
number quoted *during* the audits is meaningless, and (b) every finding below
records the exact source bytes it applies to, and every fix is re-verified
against the final tree. Section 5 shows the final, post-remediation numbers.

| Audit | Scope | Verdict on its own question |
|---|---|---|
| A | News & data path — is "Finnhub-only" real? | PASS on the claim; found 2 High + 2 Medium defects around it |
| B | Harness & V2 specs — are the specs trustworthy? | PASS on specs; found **2 High** execution blockers |
| C | Usage accounting, tests, git/`.env` safety | PASS on usage and safety; found **1 High** (pre-existing) |

---

## 1. Findings, remediation and verification

Severity is the auditor's. "Status" is the state in the final tree.

| ID | Sev | Finding | Fix | Verification |
|---|---|---|---|---|
| **A-00** | Critical (audit-harness) | The shared `.venv` installs `tradingagents` as an **editable package pointing at `/home/sky/cs5351/TradingAgents`**, not the worktree. Any auditor script started outside the worktree silently imported the *main* checkout, which still has GDELT in its defaults — Audit A's first runtime run measured the wrong tree. | No product change required. Evidence production was re-run with an explicit in-tree assertion (`tradingagents.__file__.startswith(worktree)`), and the recorded proof `logs/finnhub_only_execution_proof.txt` asserts it. | Verified: `import tradingagents.dataflows.interface` from the worktree cwd resolves to the worktree for all 7 modules on the executed path. Disclosed as limitation **L-1** (the shared venv is not isolated; the *experiment* must not use it from another cwd). |
| **A-01** | **High** | `_PASSTHROUGH_ENV` in `scripts/token_benchmark.py` contained only `FRED_API_KEY` and `SEC_EDGAR_USER_AGENT`. The study's **only** news vendor credential was never forwarded to the child process, so **all 16 runs would have rendered `AUTH_MISSING`** while the config claimed a working Finnhub path. | Added `"FINNHUB_API_KEY"` to `_PASSTHROUGH_ENV`, which also surfaces it in `credential_state()` (so the preflight prints it). | `tests/test_audit_a_regressions.py` (3 tests + 1 end-to-end through the real `apply_cityu_env`). Reverting the tuple → **3 failed**. |
| **A-02** | **High** | `get_news` computed `cutoff = publication_cutoff(trade_date)` and, when `trade_date` was empty (every call made outside a graph run, where `InjectedState` is unpopulated), **dropped the point-in-time cutoff entirely** and fell back to `end_dt + 1 day` — admitting news through the end of the window. | Falls back to the window's own `end_date` as the decision date, so a cutoff is always applied and only the *last day of the window* is admitted. | `test_get_news_without_a_trade_date_still_applies_a_cutoff`, `test_the_cutoff_is_strictly_after_the_window_end`. Reverting → **2 failed**. |
| **A-03** | Medium | `CONFIG_DISABLED` reused the shared "**could not answer**" sentence emitted for `PROVIDER_UNAVAILABLE`/`AUTH_MISSING`/`HTTP_ERROR`, so a deliberate exclusion read exactly like an outage and invited a reader to wait for a recovery that never comes. | `news_status.render_status` now has a dedicated `CONFIG_DISABLED` branch ("deliberately not requested… nothing was attempted and no error occurred… report as excluded"). The phrase *"says nothing about the instrument"* is preserved, because a pre-existing taxonomy test asserts it for every non-`EMPTY_VALID` class. | 6 param tests assert real failures still say "could not answer"; `test_config_disabled_is_not_described_as_an_outage` + end-to-end. Reverting → **4 failed**. |
| **A-04** | Medium | Per-day Finnhub fetching is strictly serial (up to 16 requests per `get_news` call). | Not changed — it is a performance property, not a correctness one, and changing the fetch strategy before the pilot would alter the behaviour under study. | Recorded as limitation **L-2**. |
| **A-05** | Low | `VENDOR_METHODS["get_news"]["gdelt"]` still exists (dead config: one env var / `set_config` away). | Intentionally retained: the routing table must stay complete so an *explicit* `gdelt` study is still possible. The Finnhub-only guarantee is enforced by the shipped default, not by deleting the key. | `tests/test_finnhub_only_scope.py` asserts the shipped default never routes to GDELT and that no arm can acquire it implicitly. |
| **A-06** | Low | Module docstrings still describe a GDELT-secondary architecture. | Not changed (wording only; changing prose does not alter behaviour). | Recorded as limitation **L-4**. |
| **A-07** | Info | Point-in-time is **day-granularity**: a same-day 23:59 article is admitted for a same-day decision. | Documented, not changed — it is the project's declared convention. | Stated in `CAND01_BATCH_2X2_PROTOCOL_V2.md` §7. |
| **B1** | **High** | `scripts/token_benchmark.py` **never read `spec["switches"]`** (`grep -c switches` → 0). Switches reached the child only via ambient `TRADINGAGENTS_*` env vars. Under a neutral environment the audit measured **12 of 16** delivered specs running with switches contradicting their own arm label — **every C0 and CC run (the entire CAND-01 factor) plus every B run**. | `_apply_spec_switches()` makes the **spec** authoritative on config keys, `_child_env_for_spec()` exports the same values to the child, an explicit contradictory `TRADINGAGENTS_*` export is **refused** (not silently resolved), and after graph construction the run path calls `verify_switches_consumed()` on `consume_switches_from_setup(graph.graph_setup)`. `s2_downstream=false` is refused by `validate_spec_switches` inside the run path. | `tests/test_audit_b_regressions.py` — 68 tests, including three that drive the **real `_run_single`** with a stub graph. Removing the `_apply_spec_switches` call → **3 failed** (the audited bug). Also re-run under `env -i`: 16/16 specs reach config as declared. |
| **B2** | **High** | The entire V2 apparatus (generator, specs, protocol, `switch_verification.py`, both test files) was **untracked at HEAD**; `git archive HEAD` contained none of it, so the "committed and reproducible generator" claim was unverifiable from any clean checkout. | **Not fixable within this round's constraints**: the task forbids committing without explicit authorisation. Disclosed prominently as limitation **L-0** and as a precondition in `EXECUTION_READINESS.md`. | `git ls-files ... \| wc -l` = 0 at the time of writing. |
| **B3** | Medium | `results_dir` is host-absolute. | Declared in the protocol; the *hashed* spec body excludes it, so the hash is reproducible on any host. | Regenerating at another root: 16/16 spec bodies identical, only `results_dir` differs (re-verified this round). |
| **B4** | Medium | The generator's overwrite guard keyed on `experiment.json` alone and silently clobbered a `specs/` tree lacking that file. | New `ensure_writable_out_dir()` refuses when any of `experiment.json`, `SWITCH_MATRIX.csv`, `CONFIG_HASH_MANIFEST.csv`, `RUN_MANIFEST_TEMPLATE.csv`, `EXECUTION_ORDER.txt`, or a non-empty `specs/` exists. | 3 tests; reverting the `specs/` clause → **1 failed**. `--out <delivered dir>` → exit 2. |
| **B5/B6** | Low/Info | `description`/`protocol_version`/`measured_runs` are outside the hash; two different "config hash" notions coexist (spec `config_sha256` vs harness `experiment_config_sha256`). | Accepted and documented. | `CAND01_BATCH_2X2_PROTOCOL_V2.md` §5. |
| **C-1** | **High** | `observability.py` `on_llm_start` passed `prompts=None`, discarding the real prompts → `TypeError` swallowed by LangChain → **every non-chat LLM call vanished from telemetry entirely** (proven with a real `FakeListLLM.invoke`). **Pre-existing at RC1** (`diff` vs `rc1_baseline` identical). | Now passes the real `prompts`. Fixed in this round because the study is a *token* study and a silently dropped call biases every arm's totals. | `tests/test_audit_c_regressions.py` — 3 tests; restoring `prompts=None` → **3 failed**. End-to-end: a completion call now yields `llm_calls == 1` with `prompt_utf8_bytes == 31`. |
| **C-2** | Medium | `tests/test_observability.py:182`'s `on_llm_start` block is dead code (the `run_id` is pre-registered), which is why C-1 survived review. | Not changed (the task forbids editing existing tests to make things pass). | Covered instead by the new C-1 tests. |
| **C-3** | Medium | `ANALYST_CONSUMERS` was declared but never checked against the real `GraphSetup`; deleting `news` from it, or `market.single_pass`, left **all 90 tests green** (mutations M6/M8). | Added `tests/test_audit_c_regressions.py` tests that compare the table against the kwargs the **real** `GraphSetup` passes, for all four arms. | Mutation M-C3a (`market.single_pass` dropped) → **21 failed**; M-C3b (`news` → `social`) → **21 failed**. |
| **C-4/C-5/C-6** | Low | Raw vendor usage is not preserved in the artifact; negative counts are accepted as complete; an empty finished run reports `attribution_complete: true`. | Not changed this round. | Recorded as limitations **L-5**. |

### Audit items the auditor itself corrected or disclosed

* **A-00** is an audit-harness defect, not a product defect. It is reported here
  because it invalidated Audit A's *first* measurement pass and it is a live
  hazard for the paid pilot.
* Audit C's "33 failed" full-suite number was produced **while Audit B's new
  test file was being written**. It is an artefact of concurrent editing, not a
  regression. The final numbers in §5 were produced after all editing stopped.

---

## 2. What each audit verified positively (not just "no findings")

**Audit A — Finnhub-only is real.**
* `tool_vendors` defaults are `finnhub`/`finnhub`; GDELT appears in
  `default_config.py` only in comments.
* AST walk of every function on the executed path: **0 GDELT imports/names/attributes**. The only executable GDELT import in `finnhub_news.py` is inside the unrouted legacy `get_news_combined`.
* Runtime, with GDELT and `urllib` replaced by counting tripwires: **GDELT calls = 0** in all five scenarios, **including when Finnhub raises**; the tripwire is proven live by an explicit-`gdelt` control.
* `get_global_news` returns `CONFIG_DISABLED` and performs **no fetch**.
* No legacy news provider is reachable (`alpha_vantage_news` has no NEWS_SENTIMENT; `y_finance` has no news; `historical_news`/`yfinance_news` are absent).
* Provenance header never claims GDELT for a single-provider block.
* PIT: undated articles are rejected; next-day articles are rejected; no request is issued past the cutoff.

**Audit B — specs are trustworthy.**
* 16 dirs × 3 files; 2×2 matrix exact with every cell exactly once; 16 **distinct** 64-hex hashes, each reproduced by an **independent** reimplementation of the algorithm read from the protocol prose.
* Single-switch sensitivity proven for all four switches; **no self-hashing** (replacing the stored `config_sha256` with zeros leaves the recomputed hash unchanged).
* `s2_downstream=false` refused at generator, build path and product guard; refusal reaches the CLI as exit 2.
* Randomisation reproduced from seed `20261114` and matches the V1 pre-registered order.
* **No design drift vs V1**: all 16 `case`/`switches`/provider/model/language/cache/run-index byte-equal.
* Zero foreign absolute paths outside the declared `results_dir`.

**Audit C — usage accounting and safety.**
* No usage → `usage_source: null`, `without_provider_usage: 1`, never a fabricated `0`.
* 3× duplicate `on_llm_end` → 1 call, 100/20 tokens (no double counting).
* 4 agents → 2100/210/220 exactly; cached/reasoning kept separate from input/output.
* `KeyboardInterrupt` propagates while partial tokens survive.
* Git/`.env` safety: HEAD `9948bf85…`, 3 stashes reachable, `.env` sha256
  `2eea6491…a1d29645`, no new commits, nothing to push, no tracked
  `token_benchmarks/` file modified.

---

## 3. Findings deliberately NOT fixed (and why)

| Item | Why not |
|---|---|
| B2 (untracked apparatus) | Requires a commit; the task forbids committing without explicit authorisation. Disclosed as **L-0**. |
| C-2 (dead test block) | Would require editing an existing test; the task forbids editing tests to make things pass. Superseded by new tests. |
| A-04 (serial fetch) | A performance property; changing it now would change the behaviour under study. |
| A-05/A-06 (dead GDELT config, stale docstrings) | Behaviourally inert; A-05 is deliberately retained so an explicit GDELT study stays possible. |
| C-4/C-5/C-6 | Out of scope for this round; disclosed. |

---

## 4. Re-audit of the remediated items

Every fix was verified by **reverting it and requiring the new tests to fail**,
then restoring the file and verifying its SHA-256. Mutation results:

| Mutation applied | Tests failing |
|---|---|
| `_PASSTHROUGH_ENV` without `FINNHUB_API_KEY` | 3 |
| PIT cutoff dropped when `trade_date` empty | 2 |
| `CONFIG_DISABLED` back to the "could not answer" sentence | 4 |
| `_run_single` no longer applies spec switches (the audited B1 code) | 3 |
| Generator guard keyed on `experiment.json` only | 1 |
| `observability.on_llm_start` with `prompts=None` (the audited RC1 code) | 3 |
| `ANALYST_CONSUMERS`: `market.single_pass` dropped | 21 |
| `ANALYST_CONSUMERS`: `news` replaced by `social` | 21 |

Restoration was confirmed each time (`grep -c MUTATION` → 0; test files back to
green). No mutation was left in the tree.

---

## 5. Final post-remediation state

```
repo cwd, shipped env          : 2 failed, 1990 passed, 2 skipped, 319 subtests
repo cwd, selection keys unset : 2 failed, 1990 passed, 2 skipped, 319 subtests
env -i, cwd-independent        : 2 failed, 1990 passed, 2 skipped, 319 subtests
RC1 baseline (control)         : 2 failed, 1471 passed, 2 skipped, 240 subtests
RC1 baseline, env -i           : 1473 passed, 2 skipped, 240 subtests
```

The 2 failures are the **same** `tests/test_cli_prefs.py` root cause at RC1 and
here (`.env` values visible because the repo is the cwd). They disappear at RC1
under `env -i` and — in this tree — are replaced by 2 *different*, pre-existing
cwd-relative `FileNotFoundError`s in `tests/test_cand01_single_pass_finalization.py`,
a file this round never touched. Both classes are classified and evidenced in
`logs/classification_of_2_failures.txt` and `TEST_RESULTS.md`.

**No finding of any severity introduced by this round remains open.**
