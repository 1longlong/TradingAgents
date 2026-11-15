# Remediation — CAND-01 × Batch-Macro 2×2 (V2)

Every defect found or fixed in this round, whether by the author, by a test, or
by an independent auditor. Each entry states the **symptom**, the **cause**, the
**fix**, and the **proof that it stays fixed**.

A defect that only appeared in test scaffolding is listed too: a test that passes
because it asserts the wrong thing is a defect.

---

## Part A — Defects found and fixed this round

### A-1 (High) — `get_news` was not Finnhub-only; GDELT was called twice per run

**Symptom.** The protocol and the previous round's report declared the news scope
"Finnhub-only", but the configuration was:

```text
get_news:        "finnhub,gdelt"
get_global_news: "gdelt"
```

**Cause.** Not only was GDELT a second entry in the chain: the `finnhub` route
itself resolved to `finnhub_news.get_news_combined`, which called **both**
`get_news_finnhub` and `get_news_gdelt` and merged the results. GDELT was
therefore contacted twice per run — once inside the merge, once as the explicit
second vendor — in **every** arm, regardless of what the protocol said. A
Finnhub outage could also be masked by GDELT, so a provider failure would have
looked like a normal run with news.

**Fix.**
* Added `get_news_finnhub_only` (Finnhub only; no GDELT anywhere in its body,
  including lazy imports) and bound it to the `finnhub` key.
* Added `get_global_news_finnhub`, which returns `NEWS_STATUS=CONFIG_DISABLED`
  and performs **no fetch**, instead of borrowing another provider.
* Defaults changed to `get_news: "finnhub"` and `get_global_news: "finnhub"`.
* `get_news_combined` is retained but is **not in the routing table**, so it is
  unreachable from the Pipeline while historical evidence scripts still run.
* GDELT itself is **not deleted**: it remains registered under the `gdelt` key
  for any future study that explicitly selects it.

**Proof.**
* `tests/test_finnhub_only_scope.py` — 9 tests; a tripwire on both the
  `gdelt_news` module attributes *and* the routing table asserts **0 GDELT
  calls**, including with Finnhub forced to fail.
* AST check: **no executable** GDELT reference in either Finnhub route function.
* Mutation: pointing `get_news` back at `get_news_combined` fails **3 tests** and
  the interceptor records the call (`logs/mutation_tests.txt`).
* `logs/finnhub_only_execution_proof.txt` — independent re-proof.

---

### A-2 (Medium) — the rendered news header claimed GDELT coverage unconditionally

**Symptom.** A Finnhub-only block still opened with
`(Finnhub company news + GDELT discovery, ...)`, and a single-provider failure
said "from any provider".

**Cause.** `merge_news_sections` hard-coded the two-provider wording from the
era when two providers were always merged.

**Fix.** The provenance line is now derived from the outcomes actually merged:
one provider → "Finnhub company news"; several → "… + GDELT discovery". The
failure sentence says "from the configured provider" when only one provider was
asked.

**Proof.** `test_single_provider_header_names_only_that_provider` asserts the
word GDELT does not appear; `test_header_lists_both_providers_when_both_are_merged`
and `test_single_provider_failure_says_the_configured_provider` pin the other
directions.

---

### A-3 (High) — the V1 spec generator is lost with no recoverable hash definition

**Symptom.** `scripts/gen_cand01_batch_16run_specs.py` could not be found in the
working tree, the frozen backup tree, the snapshot tarball, any git ref, the
bundle, any of the three stashes, or the removed scratch worktree. The hash
function it named (`token_benchmark.experiment_config_hash`) does not exist in
`scripts/token_benchmark.py`.

**Consequence.** The V1 `config_sha256` values cannot be reproduced. Seventeen
reconstruction attempts produced **0/16** matches against R01's recorded
`fa62c147…291f`.

**Fix.** Re-registration rather than fabrication:
`scripts/gen_cand01_batch_16run_specs_v2.py` is committed, stdlib-only and
deterministic, with the hash algorithm documented in protocol §6 and a frozen
field list. The experiment design (stocks, arms, date, models, seed, order) is
**identical** to V1; only the hashes are new.

**Proof.** `--check` reports *53 artefacts reproduce byte-identically*; all 16
V2 `cases` and `switches` blocks equal V1's; the execution order equals V1's
pre-registered order (asserted by a test).

---

### A-4 (Medium) — the switch-consumption guard did not exist in the delivered tree

**Symptom.** `verify_switches_consumed` was referenced by the protocol but
existed only in the lost generator bundle.

**Fix.** Committed as `tradingagents/graph/switch_verification.py`, with the two
traps the V1 remediation notes recorded:

* it intercepts in `tradingagents.graph.setup` (the namespace `GraphSetup`
  actually resolves factories from), not `tradingagents.agents`;
* it compares `single_pass` against `single_pass AND structured`, matching what
  `GraphSetup` really does.

A consumer that was never captured is an **error**, not a skip; non-`bool` values
are rejected; `s2_downstream=false` is refused.

**Proof.** `tests/test_switch_consumption.py` — 19 tests against the **real**
`GraphSetup`, all four arms. The namespace claim was measured: patching
`tradingagents.agents` intercepts **0** calls, patching
`tradingagents.graph.setup` intercepts **1**.

---

### A-5 (Low) — my own test guessed a non-existent symbol

**Symptom.** `test_switch_env_var_names_match_the_product_code` failed with
`ImportError: cannot import name 'ENV_OVERRIDES'`.

**Cause.** The product code names the mapping `_ENV_OVERRIDES` (private). The
test assumed a public name.

**Fix.** Read the real mapping and assert both the env-var name and the config
key it maps to.

**Note.** Recorded because it is exactly the class of defect — a test asserting
against an imagined API — that a passing suite can hide.

---

### A-6 (Low) — a generator guard-rail counted distinct tickers instead of runs

**Symptom.** The generator refused with *"block NVDA does not have all four
arms"* on a correct definition.

**Cause.** `len({r["ticker"] for r in runs if r["ticker"] == block})` collapses
to 1, since every run in the block has the same ticker.

**Fix.** Count the runs, not the distinct tickers.

**Note.** The guard failed safe (it refused rather than published bad specs),
which is the correct direction, but it was still wrong.

---

### A-7 (Low) — `--check` could not verify reproducibility

**Symptom.** `--check` reported drift on every `code_state.json` immediately
after generation.

**Cause.** `code_state.json` records `timestamp_utc` and
`git_working_tree_dirty`, which legitimately differ between two runs.

**Fix.** `--check` compares every non-volatile field and ignores exactly those
two, so real drift in the definition hash, generator hash or git head is still
caught.

**Proof.** `test_check_mode_detects_tampering` flips a switch and requires
exit code 1 with `DRIFT` in stderr.

---

### A-8 (Low) — a scratch worktree lost its `.git` pointer

**Symptom.** `git status` in the scratch worktree failed with *"not a git
repository"* after a content copy.

**Cause.** The rsync copy excluded `.git`, which for a linked worktree is a
**file** pointing at the admin directory, not a directory.

**Fix.** Re-created the pointer (`gitdir: …/.git/worktrees/planC2_wt`) and
verified `HEAD` and `git status` again. No content was lost: the ported Finnhub
edits were still present and were verified before continuing.

---

## Part B — Pre-existing problems, disclosed not fixed

### B-1 — `tests/test_cli_prefs.py` is not hermetic

Two tests fail in any environment whose `.env` sets
`TRADINGAGENTS_LLM_PROVIDER` and friends. The file is **byte-identical to RC1**
and fails on a pristine RC1 checkout, so this is pre-existing.

`TRADINGAGENTS_LLM_PROVIDER` alone reproduces both failures;
`TRADINGAGENTS_DEEP_THINK_LLM` alone one; `TRADINGAGENTS_QUICK_THINK_LLM` alone
none.

**Not fixed here, deliberately.** Fixing it means making the CLI tests hermetic —
a separate change that must not be smuggled into an experiment-preparation round,
and one that would otherwise require editing tests to make them pass.

---

### B-2 — the V1 protocol's `config_sha256` values are permanently void

No V1 artefact may be used as a numeric baseline for V2, because the algorithm
that produced those hashes cannot be reconstructed.

---

### B-3 — `s2_downstream` has no OFF implementation

Documented in V1 (`REM-5`) and confirmed again here: S2 field routing is
unconditional in `tradingagents/agents/utils/s2_context.py`. V2 keeps the field,
accepts only `true`, and refuses `false` loudly rather than inventing a no-op
toggle. The consequence — no S2-downstream estimate this round — is stated in the
protocol and the readiness report.

---

## Part C — Defects found by the independent audits

Three subagents audited the real tree independently (news/data path, Harness & specs,
usage/tests/safety). Full evidence, reproduction and re-verification:
`INDEPENDENT_AUDIT.md`. Summary of what was fixed **in this round**:

| ID | Severity | Defect | Status |
| --- | --- | --- | --- |
| A-01 | High | `_PASSTHROUGH_ENV` omitted `FINNHUB_API_KEY` → **all 16 runs would be `AUTH_MISSING`** | **Fixed.** Key added; reported by `credential_state()`. 3 mutation-verified tests. |
| A-02 | High | Empty `trade_date` dropped the point-in-time cutoff entirely → post-decision news admitted | **Fixed.** Falls back to the window's `end_date`. 2 mutation-verified tests. |
| A-03 | Medium | `CONFIG_DISABLED` reused the outage sentence "could not answer" | **Fixed.** Dedicated sentence; taxonomy invariant preserved. 4 mutation-verified tests. |
| **B1** | **High** | `_run_single` **never read `spec["switches"]`**; under a neutral env **12 of 16 specs ran with switches contradicting their arm** (all C0/CC — the whole CAND-01 factor — and all B) | **Fixed.** Spec is authoritative; child env exported; contradictory explicit export refused; post-construction verification on `graph_setup`. 3 tests drive the real `_run_single`. |
| B4 | Medium | Overwrite guard keyed on `experiment.json` only, silently clobbering a `specs/` tree | **Fixed.** `ensure_writable_out_dir()` checks all six markers. 3 tests. |
| **C-1** | **High** (pre-existing at RC1) | `on_llm_start(..., prompts=None)` raised inside the callback → **every non-chat LLM call vanished from telemetry** | **Fixed.** Real prompts forwarded. 3 mutation-verified tests. Fixed because the study is a *token* study. |
| C-3 | Medium | `ANALYST_CONSUMERS` never cross-checked against the real `GraphSetup`; deleting entries left all tests green | **Fixed.** Table now compared against real `GraphSetup` kwargs for all 4 arms. 2 mutations → 21 failures each. |

Remaining open items, deliberately not fixed this round: **B2** (apparatus is
untracked — needs an authorised commit), **A-00** (shared-venv editable install
points at the main checkout — launch discipline), **A-04/A-05/A-06**, **C-2**,
**C-4/5/6**. Each is recorded with its reason in `INDEPENDENT_AUDIT.md` §3 and as
a limitation (L-0 … L-6) in `EXECUTION_READINESS.md` §6.

### C-1 in detail, because it was invisible for a long time

```python
# before (identical at RC1)
def on_llm_start(self, serialized, prompts, *, run_id=None, ...):
    self._handle_llm_start(run_id, parent_run_id, serialized, prompts=None)
```

`_handle_llm_start` then did `for p in prompts:` → `TypeError: 'NoneType' object is
not iterable`. LangChain catches handler exceptions and logs them, so the run
**completed normally** while the LLM call was simply absent from the event list.
Measured before the fix: `llm_calls captured = 0` for a real
`FakeListLLM.invoke`. After: `1` event with `prompt_utf8_bytes == 31`.

The existing `tests/test_observability.py` could not catch it because its
`on_llm_start` block is dead code (the `run_id` is pre-registered) — Audit C-2.
Rather than edit that test, the behaviour is pinned by three new tests.
