# Budget Guard Design — CAND-01 × Batch-Macro 2×2 (V2)

Scope: the token-accounting and budget-gate semantics the 16 V2 runs are
measured under. This round's cap is **unset** by design; the gate still exists,
still distinguishes every state below, and is still exercised by mocked tests.

---

## 1. This round's cap is deliberately absent

```json
"budget": { "max_total_tokens": null }
```

`null` means **UNCAPPED**: no token ceiling aborts a run. This is intentional and
must not be "helpfully" restored to a default. Any hard-coded fallback cap would
change what the experiment measures and would silently make the 16 runs
incomparable with anything recorded under a cap.

The absence of a cap is not the absence of accounting: usage is still recorded
per call, per agent and per run, and the gate still reports its state — it simply
never transitions to `EXHAUSTED` while uncapped.

---

## 2. Gate states

| State | Meaning |
| --- | --- |
| `OK` | Spend is known and below the cap (or the cap is unset); the run may proceed. |
| `UNCAPPED` | No cap configured. Spend still reported; the gate never blocks. |
| `EXHAUSTED` | Spend is known and has reached the cap; further paid calls are refused. |
| `UNKNOWN_SPEND` | Spend **cannot** be determined (missing provider usage). |

### 2.1 The four quantities

| Quantity | Definition |
| --- | --- |
| `used` | Provider-reported tokens consumed so far, summed over deduplicated calls. |
| `reserved` | Tokens committed to in-flight work not yet reported. |
| `remaining` | `cap − used − reserved`, when the cap is known. `None` when `UNCAPPED`. |
| `UNKNOWN_SPEND` | Set when any call lacks provider usage, so `used` is a lower bound, not a total. |

**Invariant:** `used` counts each LangChain `run_id` **exactly once**. Duplicate
`on_llm_end` delivery is dropped after the event is emitted
(`tradingagents/observability.py`, `_llm_starts` + `emitted`), which prevents
double counting structurally rather than by arithmetic luck.

---

## 3. `UNKNOWN_SPEND` must never be reported as zero

This is the single most important rule in this document.

If a call reports no usage, the correct statement is **"spend is unknown"**. The
wrong statements are all worse than unknown:

* reporting `0` — understates cost and can hide an exhausted budget;
* reporting `used = 0` and then computing `remaining = cap` — falsely implies
  full headroom;
* treating a missing usage block as an empty response and continuing as if the
  call were free.

Accordingly:

* `None` is never coerced to `0` anywhere in the accounting path;
* a call without provider usage increments `llm_calls_without_provider_usage`
  and clears `usage_complete`;
* a run with any such call is flagged `USAGE_INCOMPLETE` (`DQ3`), excluded from
  token means, and **retained** (never deleted);
* the gate reports `UNKNOWN_SPEND`, and `used` is documented as a **lower
  bound**.

Because this round is `UNCAPPED`, `UNKNOWN_SPEND` cannot block a run — but it is
still reported, and any report of token totals must carry the count of
unmeasured calls that sit behind them.

---

## 4. Partial runs

An interrupted run keeps every usage event already recorded. Nothing is rolled
back and nothing is recomputed from a partial total. A resumed run is a distinct
`attempt`, identified by `(run_index, attempt)`, so its usage is never merged
with the interrupted attempt's.

---

## 5. What is tested (mocked, credential-free)

The gate and the accounting are exercised without any paid call:

| Property | Test surface |
| --- | --- |
| Missing usage stays `None` | `tradingagents/observability.py` collector, exercised directly |
| No double count for one `run_id` | duplicate `on_llm_end` delivery |
| Separate prompt / completion / total / cached fields | `LLMCallEvent` |
| Raw vendor usage preserved | `usage_source` |
| Interrupted run retains usage | collector snapshot after a partial sequence |
| `UNKNOWN_SPEND` ≠ `0` | gate state assertions |
| `UNCAPPED` never blocks | cap `None` |
| `EXHAUSTED` at the cap | mocked cap |

---

## 6. Honest limits

* The cap being `null` means an unbounded run is possible; the operator must
  watch the run. The gate protects against *misreporting*, this round not against
  *overspending*.
* `UNKNOWN_SPEND` cannot be resolved from inside the project: it is a fact about
  what the provider reported.
* No gate can recover tokens already spent before a stop condition fires; `S1`
  and `DQ5` are placed **before** the first paid call of a run for exactly that
  reason.
