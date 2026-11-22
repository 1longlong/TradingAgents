# Audit C — Usage Accounting, Tests & Safety

**Repository:** `/tmp/opencode/planC2_wt` (scratch worktree of `/home/sky/cs5351/TradingAgents`)
**Baseline:** `/tmp/opencode/rc1_baseline` @ `9948bf8`
**Interpreter:** `/tmp/opencode/planC2_wt/.venv/bin/python` (3.14.7), `TZ=UTC`
**Rules honoured:** no LLM/network/pipeline calls; no repo file permanently modified; all temp artefacts under `/tmp/opencode/auditC/`.

> ### ⚠ Read this first — the worktree was being edited **concurrently** while I audited
> Auditors A and B were writing into the *same* worktree. Files appeared mid-audit:
>
> | Time | File | Author |
> |---|---|---|
> | 19:25:59 | `tests/test_audit_a_regressions.py` | Audit A |
> | 19:27 | `tradingagents/graph/switch_verification.py` (added `consume_switches_from_setup`) | Audit B |
> | 19:27 | `scripts/gen_cand01_batch_16run_specs_v2.py` (added `ensure_writable_out_dir`) | Audit B |
> | 19:28:06 | `tests/test_audit_b_regressions.py` | Audit B |
>
> Consequence: my **full-suite** result is **not reproducible by a single command** — it drifts. I recorded it twice (below). Targeted-suite and Part-1 results were unaffected (they pass both before and after the concurrent edits). All Part-3 mutations were re-run against the **current** file versions; my restores were byte-exact every time and I did **not** overwrite A's or B's edits (see Safety §S-4).

---

## Findings table

| ID | Severity | Area | Finding | Verified by |
|---|---|---|---|---|
| C-1 | **HIGH** | Usage accounting | `on_llm_start` discards `prompts` → `TypeError`, **every non-chat LLM call is silently unrecorded** (pre-existing in RC1) | Execution (real `LLM.invoke`) |
| C-2 | **MEDIUM** | Test non-vacuity | `test_duplicate_start_same_runid_no_double_count` masks C-1 by pre-registering the `run_id`; the `on_llm_start` line can never execute its real path | Execution + code trace |
| C-3 | **MEDIUM** | Non-vacuity | `ANALYST_CONSUMERS` is **not** cross-checked against what `GraphSetup` actually constructs; dropping an entry passes all 90 tests | Execution (mutation M6/M8) |
| C-4 | LOW | Usage accounting | Raw vendor usage blob is **not preserved** in the telemetry artifact (normalised fields only) | Execution |
| C-5 | LOW | Usage accounting | `_extract_usage_metadata` accepts **negative** token counts as "complete" provider usage | Execution |
| C-6 | LOW | Audit quality | An **empty** finished run reports `attribution_complete: true`, `telemetry_complete: true` with 0 LLM calls — vacuous-pass signature | Execution |
| C-7 | INFO | Repo hygiene | `tests/test_cli_prefs.py` is **not hermetic**: fails whenever `TRADINGAGENTS_LLM_PROVIDER` is in the environment. **Pre-existing in RC1**, byte-identical `cli/main.py` | Execution (both checkouts) |
| C-8 | INFO | Data integrity | 1/64 `spec_sha256` in `cand01_batch_16run/MANIFEST.sha256` does not match; **pre-existing**, already documented by the prior round | Execution (manifest verify) |

**Verdicts:** Usage accounting **PASS (with caveats C-1/C-4/C-5 for non-chat models)** · Test non-vacuity **PASS for the two mandated mutation goals**, **FAIL for C-3 (consumer list not pinned)**.

---

# PART 1 — Usage accounting (`tradingagents/observability.py`)

Script: `/tmp/opencode/auditC/p1_usage.py` (drives the **real** `RunMetricsCollector` + `ObservabilityCallbackHandler`).

### (a) No provider usage → MISSING, never 0 — **PASS**

Evidence (`observability.py`):
- `:1322-1350` `_extract_usage` → `return None` when no usage is present (never synthesises zeros).
- `:1151-1156` `reported_*_tokens=usage[...] if usage else None`, `usage_source=usage["source"] if usage else None`.
- `:784,793-794` `has_usage = event.usage_source is not None`; `else: self.llm_calls_without_provider_usage += 1`.
- `:1602` `usage_complete = bool(without_usage == 0 and total_llm > 0 and with_usage == total_llm)`.

Real output:
```
event   : {"reported_cached_input_tokens": null, "reported_input_tokens": null,
           "reported_output_tokens": null, "reported_reasoning_tokens": null,
           "usage_complete": false, "usage_source": null}
snapshot: llm_calls=1 llm_calls_with_provider_usage=0 llm_calls_without_provider_usage=1 usage_complete=false
usage_coverage: {"calls_with_provider_usage": 0, "calls_without_provider_usage": 1, "complete": false, "llm_calls": 1}
audit_quality : {"usage_complete": false, ...}
```
All 12 assertions PASS (`None` is never coerced to `0`; the run-level sums stay `0` because the fields are `None`, and coverage counts the call as *without* usage).

### (b) Duplicate `on_llm_end` for the same `run_id` does not double count — **PASS**

Mechanism: `_llm_starts` (`:1007`) + `emitted` flag (`:1099-1104` start, `:1119-1124` error). The entry is popped, so a third delivery finds `start is None`.

Real output — **3 deliveries, 1 run_id**:
```
after 3 on_llm_end deliveries: llm_calls=1, reported_input_tokens_sum=100, reported_output_tokens_sum=20,
                               llm_calls_with_provider_usage=1
PASS dup end -> _llm_starts entry popped (no leak)
```
Duplicate *start* (two `on_chat_model_start`) also collapses to 1 call/100 tokens (`:1062`).
Error-then-end → `1 call, 1 error, 0 success` (no second event). Orphan end → 0 calls.

### (c) Multi-agent aggregation — **PASS**

4 agents × ground-truth token totals; per-agent and run-level agreed exactly:
```
bull_researcher       calls=1 in=600 out=60  cached=0
fundamentals_analyst  calls=2 in=900 out=90  cached=70
market_analyst        calls=2 in=300 out=30  cached=90
news_analyst          calls=1 in=300 out=30  cached=60
run_totals: llm_calls=6 in=2100 out=210 cached=220 with_usage=6 without_usage=0
```
`attribution_complete: true`. Attribution is **frozen at start** (`:1066`): a call started under `market_analyst` and ended under `news_analyst` is credited to `market_analyst` (verified).

### (d) prompt/completion/total/cached recorded separately — **PASS** (raw blob: **C-4 FAIL**)

```
_extract_usage(usage_metadata w/ details) -> {"cached_input": 400, "complete": true,
    "input": 1000, "output": 200, "reasoning": 64, "source": "provider"}
```
`cached` is `cache_read + cache_creation` (`:1414-1420`), never folded into `input`; `reasoning` is a separate subset of `output` (`:1422-1428`). Three provider shapes verified: canonical `usage_metadata`, `response_metadata.token_usage`, `llm_output.token_usage` → `7/3`.

**C-4:** the artifact's LLM event carries only `reported_input_tokens / reported_output_tokens / reported_reasoning_tokens / reported_cached_input_tokens` — there is **no `raw_usage` / `total_tokens` / `prompt_tokens` field** (`:1632-1657`). The mission's "raw vendor usage is preserved" is therefore **not met**. No code or doc claims otherwise, so this is a **gap against the requirement**, not a contract violation.

### (e) Interruption retains usage already produced — **PASS**

- `finish_run("interrupted")` then read: 2 completed calls, `in=100 out=10` retained, `run_status="interrupted"`, event list still serialises.
- `run_telemetry` with a `KeyboardInterrupt` raised inside: exception **propagated**, partial `in=50, llm_calls=1` kept, run marked `failed / KeyboardInterrupt` (`:1862-1869`).
- A call started but never ended before interruption contributes **no** phantom usage (correct — it also contributes no phantom zeros).

### C-1 (HIGH) — `on_llm_start` crashes and silently drops the call

`observability.py:1041` passes `prompts=None` even though the signature receives `prompts`, so `:1076` runs `_collect_message_counts(None)`:

```python
def on_llm_start(self, serialized, prompts, *, run_id=None, parent_run_id=None, **kwargs):
    self._handle_llm_start(run_id, parent_run_id, serialized, prompts=None)   # <- prompts discarded
```

Reproduced through a **real LangChain invocation** (`FakeListLLM`, no network):
```
Error in ObservabilityCallbackHandler.on_llm_start callback: TypeError("'NoneType' object is not iterable")
LLM invoke returned: 'hello'          <- app unaffected (raise_error=False)
snapshot: llm_calls=0                  <- CALL VANISHES
usage_coverage: {'llm_calls': 0, ...}  <- absent from the denominator
```
**Why it matters for a token experiment:** the call is not recorded as "usage missing" — it is **not recorded at all**. The `llm_calls_without_provider_usage` safety net (a) cannot fire, and per-agent token totals silently under-count. Pre-existing: RC1 `observability.py:1041` is byte-identical and reproduces the same `TypeError`.

*Required fix:* pass `prompts=prompts`; add a regression test calling `on_llm_start` **first** for a fresh `run_id`.
*Verification:* script `p1_usage.py` flips `BUG-1 … must not raise` / `… records exactly 1 call` from FAIL to PASS once the argument is forwarded (asserted in-script, marked FAIL above).

---

# PART 2 — Tests (real output)

### Targeted suite — identical before and after the concurrent edits
```
$ TZ=UTC .venv/bin/python -m pytest tests/test_finnhub_only_scope.py \
    tests/test_cand01_batch_16run_v2_infra.py tests/test_switch_consumption.py \
    tests/test_cand01_single_pass_finalization.py tests/test_cand01_news_positive_path.py -q
187 passed, 86 subtests passed in 1.65s
```

### Full suite — **drifts** because of concurrent edits (see warning above)

| Run | When | Result |
|---|---|---|
| 1st | ~19:20, before A/B wrote their files | **2 failed, 1889 passed, 2 skipped, 319 subtests passed** |
| 2nd | 19:28, after `test_audit_b_regressions.py` appeared | **33 failed, 1938 passed, 2 skipped, 26 warnings, 318 subtests passed** |

Skips (both runs): `test_bedrock_provider.py:74` (`langchain_aws` absent), `test_deepseek_reasoning.py:209` (no `DEEPSEEK_API_KEY`).

**The 33-failure run is not a regression of the product.** All 31 extra failures are in `tests/test_audit_b_regressions.py`, a file created at **19:28:06** by Audit B, which imports `switch_verification.consume_switches_from_setup` — a function added to the source at **19:27**, i.e. while the suite was running. Failures include `DID NOT RAISE SwitchNotConsumed` and `arm AB is indistinguishable from a neutral environment`, consistent with a mid-authoring test file. Isolated at 19:28 the same file gave **29 failed, 35 passed**. This is a **concurrency artefact, not a product defect** — but it means the "full suite is green" claim **cannot be certified from this worktree while A and B are active**.

### `tests/test_cli_prefs.py` — baseline or newly introduced? **→ BASELINE (C-7)**

```
planC2_wt     : 2 failed, 10 passed      (3 consecutive runs, deterministic)
rc1_baseline  : 2 failed, 10 passed      (identical failure text)
```
Independent root-cause proof (not just "both fail"):
1. Failure is `assert 'CS5351/DeepSeek-V4-Flash' == 'gpt-5.6-mini'` — the **`.env` value**, not a code path.
2. Scrubbing the environment (`PYTHON_DOTENV_DISABLED=1`, no `TRADINGAGENTS_*`) → **12 passed in both checkouts**.
3. Injecting **only** `TRADINGAGENTS_LLM_PROVIDER=openai_compatible` → **2 failed / 10 passed** in both.
4. The triggering code is byte-identical: `diff` of the "Step 7: Thinking agents" env-skip block in `cli/main.py` between RC1 and planC2 is **empty**.

**Conclusion: pre-existing in RC1, not newly introduced.** Caveat on the framing: it is **not** an unconditional baseline failure — it only fails when `TRADINGAGENTS_LLM_PROVIDER` is exported (the project `.env` exports it). `test_cli_prefs.py`, `cli/prefs.py`, `cli/main.py` are unmodified by this port.

---

# PART 3 — Non-vacuity (mutation, byte-exact restore)

Method: copy to `/tmp/opencode/auditC/backups{,2}/` → record sha256 → mutate → run → `cp -p` backup back → re-verify sha256 → `trap … EXIT` guarantees restore even on failure. Every run printed `RESTORE OK`.

**Because A/B edited both target files mid-audit, every mutation below was re-run against the *current* bytes** (`switch_verification.py = a6516282…`, `gen_…_v2.py = 83c727d7…`).

| # | Mutation | Target | Result |
|---|---|---|---|
| M0 | none | both | **65 / 90 passed** (baseline) |
| **M1 (i)** | remove `"cache_policy"` from `HASHED_FIELDS` | generator | **2 failed, 44 passed** ✅ |
| **M2** | `config_sha256` stops hashing `switches_required` | generator | **1 failed, 45 passed** ✅ |
| **M3 (ii)** | `if got is not value:` → `if False:` — delivery never compared | switch_verification | **2 failed, 17 passed** ✅ |
| M4 | `single_pass and structured` → `bool(single_pass)` | switch_verification | **1 failed, 89 passed** ✅ |
| M5 | missing analyst consumer → `continue` | switch_verification | **1 failed, 18 passed** ✅ |
| M6 | delete `"news"` from `ANALYST_CONSUMERS` | switch_verification | **90 passed** ❌ **C-3** |
| M7 | invert market `structured` expectation | switch_verification | **10 failed** ✅ |
| M8 | `ANALYST_CONSUMERS["market"]` drops `"single_pass"` | switch_verification | **90 passed** ❌ **C-3** |

**(i) Hash-field break — reproduced**
```
FAILED test_cand01_batch_16run_v2_infra.py::test_hash_input_fields_are_recorded_explicitly
FAILED test_cand01_batch_16run_v2_infra.py::test_changing_any_hashed_field_changes_the_hash[cache_policy-clear]
2 failed, 44 passed
```
Pinned by an explicit tuple equality at `tests/test_cand01_batch_16run_v2_infra.py:191-198` **plus** one sensitivity test per field (`:360-394`). Breaking the field list is caught twice — good defence in depth.

**(ii) Switch-delivery break — reproduced**
```
FAILED test_switch_consumption.py::test_a_graph_built_with_the_wrong_switch_is_rejected
FAILED test_switch_consumption.py::test_a_graph_built_with_batch_macro_off_is_rejected
2 failed, 17 passed
```
The suite also rejects a **missing** consumer (`:157`), a **vacuous** observation set (`:165`), truthy non-bools (`:170`), and the `single_pass AND structured` trap (`:124`) — genuinely non-vacuous for these paths.

### C-3 (MEDIUM) — `ANALYST_CONSUMERS` is not pinned to `GraphSetup`

`expected_analyst_kwargs` iterates `wanted.items()` (`switch_verification.py:118`), and `wanted` is derived from the module's own `ANALYST_CONSUMERS` table — which is **declared, never verified**. `tests/test_switch_consumption.py:91` spies only `("market", "news", "fundamentals")` (`setup.py:96-112`), and no test asserts `set(observed) == set(ANALYST_CONSUMERS)`.

M6 (drop `news`) and M8 (drop `market.single_pass`) therefore pass all 90 tests: the verifier simply stops checking, and nothing notices. This is precisely the "a switch that was never checked proves nothing" failure the module's own docstring (`:29-30`) warns about.

*Required fix:* assert the consumer table against the factories actually invoked, e.g. `assert set(observed) == set(ANALYST_CONSUMERS)`, and pin `ANALYST_CONSUMERS` with an explicit tuple-equality test (mirroring `HASHED_FIELDS`).

---

# PART 4 — Safety (real repo `git -C /home/sky/cs5351/TradingAgents`)

| Check | Required | Observed | Result |
|---|---|---|---|
| RC1 HEAD | `9948bf8545cceeb0d7a60cda913a04826a06c007` | `9948bf8545cceeb0d7a60cda913a04826a06c007` (branch `feature/token-observability`, `refs/heads/rc1`) | ✅ |
| Stashes | 3 exist | 3 exist; trees reachable (`a52eb07…`, `0939a3c…`, `8c5f718…`) | ✅ |
| `.env` sha256 | `2eea649149…a1d29645` | `2eea649149af1d4c269603802abb830b57f9f6ed71061c7c30a1fa91a1d29645` | ✅ |
| No new commits | — | Reflog top = `9948bf8 commit: release(rc1)`; no commit dated 2026-11-15 on any ref | ✅ |
| No pushes | — | `origin/feature/token-observability` == local HEAD == `9948bf8` (nothing to push); no `2026-11-15` remote movement | ✅ |
| `token_benchmarks/` intact | not overwritten | **No tracked file under `token_benchmarks/` modified** (`git status --porcelain` empty for modified entries) | ✅ |
| Historical manifests | verify | 7/9 verify clean (15/15, 42/42, 11/11, 13/13, 18/18, 17/17, 19/19) | ✅ |
| `cand01_batch_16run/MANIFEST.sha256` | — | **63/64 OK, 1 mismatch** — see C-8 | ⚠ pre-existing |

**C-8 (INFO, pre-existing).** `generated/specs/R01_NVDA_C0/runs/run_01/attempt_01/spec.json` hashes to `b9c4c8fd…`; `MANIFEST.sha256:18` records `e55a93fb…`. mtime `2026-11-15 00:39` — ~18 h before this audit. Already recorded verbatim by the prior round (`PLANC_RESUME_20261115/HARNESS_RECOVERY_BLOCKER.md:92`, `STATUS.md:60-63`) as present in the frozen backup. I tried 8 canonicalisation variants; none reproduces `e55a93fb…`, confirming the manifest hash is **unreconstructible**, not a formatting artefact. **Not caused by this audit.**

**S-4 (audit footprint).** `find … -newermt "-45 minutes"` in the worktree returned only A/B's files; `git status | grep auditC` = 0. My two Part-3 targets are **byte-identical** to the versions that existed after A/B's edits:

```
a6516282106c1d10f5c06fa9c4a3aedcab5bb29fc15b3615e5d42066ac8936e7  tradingagents/graph/switch_verification.py
83c727d78868621924890c4604b35236860581d658378f56243f7634f8b30d58  scripts/gen_cand01_batch_16run_specs_v2.py
```
Note: B's *uncommitted* `switch_verification.py` now differs from my 19:22 backup (`5c0c3260…`), and B's code is **not covered by my mutation results** except where re-run (M1/M2/M3 above, all re-run on current bytes).

---

# Final verdict

### Usage accounting — **PASS** (with caveats)
(a) MISSING-not-zero ✅ · (b) dedup ✅ · (c) multi-agent aggregation ✅ · (d) separate fields ✅ — but **raw vendor blob not preserved (C-4)** · (e) interruption retention ✅.

Blocking caveat: **C-1** — `on_llm_start` discards `prompts` and raises, so for any non-chat model every call (and its tokens) is **dropped entirely** rather than flagged as missing-usage. This is pre-existing in RC1, silent (the app still succeeds), and defeats the `llm_calls_without_provider_usage` safeguard. It does **not** invalidate the accounting logic itself, but it means token totals are only trustworthy for chat-model traffic until fixed. **C-5** (negative tokens accepted) is cosmetic but should be clamped.

### Test non-vacuity — **PASS for the mandated goals, with one gap**
- (i) breaking the hash field list → `2 failed` ✅
- (ii) breaking switch delivery → `2 failed` ✅
- Both re-confirmed on the **current** post-concurrency bytes, with byte-exact restore.

Gap: **C-3** — `ANALYST_CONSUMERS` is not pinned to what `GraphSetup` constructs (M6/M8 pass all 90 tests). **C-2** — the `on_llm_start` line in `tests/test_observability.py:182` is dead code due to pre-registration, which is exactly why C-1 survived review.

### Test suite status
Targeted 5-file suite: **187 passed**. Full suite: **2 failed / 1889 passed / 2 skipped** when run before A/B's concurrent edits; the 2 failures are **pre-existing baselines (C-7)**, proven by root cause, not merely by "both red". The later **33-failure** run is a **concurrency artefact** (Audit B's mid-authoring `test_audit_b_regressions.py`), not a product regression — but the suite is **not currently certifiable** while A and B are writing to this worktree. Re-run the full suite from a quiescent checkout before drawing any "0 unexpected failures" conclusion.

### Safety — **PASS**
HEAD, 3 stashes, `.env` sha256, no commits, no pushes, `token_benchmarks/` untouched. The single manifest mismatch (C-8) is documented and pre-existing.
