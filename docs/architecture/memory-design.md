# Memory design

**Scope.** How TradingAgents' decision memory changed between RC1 (`9948bf8`),
the V2 batch (`15270b1`), the V3 batch (`e3b5cca`) and the final remediation
(`50b2ca3`). This document describes the *product* memory log and the
*experiment harness* that isolates it. It does not claim that memory improves
decisions; that question is `NOT_MEASURED` (see §6).

**Evidence base.** `tradingagents/agents/utils/memory.py`,
`tradingagents/graph/trading_graph.py`, `tradingagents/graph/reflection.py`,
`scripts/token_benchmark.py`, the V2/V3 protocols and the two memory audits in
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/`. The raw paid-run
telemetry is deliberately untracked; where a number comes only from that local
evidence it is marked **(local)**.

---

## 1. The original design: one shared append-only log

`TradingMemoryLog` (`tradingagents/agents/utils/memory.py`) is an append-only
Markdown file. The path is `config["memory_log_path"]`, defaulting to
`~/.tradingagents/memory/trading_memory.md`
(`tradingagents/default_config.py`). The lifecycle is:

1. At the end of a run, `record_decision()` calls `store_decision()`, which
   appends `[trade_date | ticker | rating | pending]` plus the final decision
   (`trading_graph.py`, `record_decision`; `memory.py`, `store_decision`).
2. On the **next run of the same ticker**, `propagate()` calls
   `_resolve_pending_entries(ticker)` *before* `graph.invoke()`
   (`trading_graph.py:360`). If the holding-period return is now resolvable, it
   calls `Reflector.reflect_on_final_decision()`, which makes a provider call
   (`reflection.py:41`), and rewrites the entry as resolved with a
   `REFLECTION:` section.
3. `get_past_context(ticker, as_of=...)` injects resolved lessons into the
   Portfolio Manager prompt, subject to the point-in-time filter
   (`memory.py:73`).

This is a *deferred reflection* design: no extra call at write time, one extra
call at the next same-ticker run, and a prompt whose content depends on what
earlier runs happened to write.

## 2. Why that design broke the V2 2x2: R05 → R06

V2 registered 16 runs, one per (stock, arm) cell, but did **not** isolate the
log. The 2026-11-16 execution made the coupling observable:

| Run | Stock / arm | What happened | Consequence |
| --- | --- | --- | --- |
| R05 attempt 01 | AAPL / C0 | `OSError EROFS` writing the log at the end (read-only sandbox); 18 LLM calls completed | `FAILED_ENV`; 163,678 tokens; not a sample |
| R05 attempt 02 | AAPL / C0 | completed, wrote `[2026-09-23 | AAPL | Hold | pending]` | valid; 180,687 tokens |
| R06 attempt 01 | AAPL / B | `_resolve_pending_entries` ran the reflector first; its provider call had no attribution scope | `INVALID`; 190,468 tokens; 1 of 21 calls `unattributed` |

R06 is the proof of two coupled defects, not one:

* **Attribution:** the pre-graph reflector call inherited no `agent_scoped`
  context, so the telemetry recorded `agent_id="unattributed"` at
  `global_sequence=0`. The frozen U-1 rule voids such a run.
* **Shared state:** R05's write changed R06's prompt and added a provider call.
  Even if the attribution had been fixed, the run order would still have changed
  the measured execution path.

V2 therefore stopped at 7 attempts: 5 valid, 1 environment failure, 1 invalid.
The 1,463,791 total tokens split into 1,109,645 valid and 354,146 failed
(163,678 + 190,468). The NVDA cells that did complete were B 205,581 /
AB 339,738 / C0 191,233 / CC 192,406. The V2 halt is documented in
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/C3_HALT_REPORT_20261115.md`
and the V2 limits in the local `EXPERIMENT_LIMITATIONS.md` **(local)**.

The diagnosis predicted the same defect for JPM and XOM: each ticker's first
valid run would write a pending entry, and the next run of that ticker would
resolve it. That is why "16 valid samples" was unreachable on the frozen V2
code, and why V3 changed the memory contract before spending.

## 3. The pre-graph reflector and attribution

The reflector is a product component, not an analyst. V3 keeps its prompt,
model, temperature and call logic unchanged and gives it a declared **system**
scope instead of pretending it is an agent:

```text
propagate()
  -> _resolve_pending_entries(ticker)
     -> Reflector.reflect_on_final_decision()
        -> with system_component_scoped("pre_graph_reflector"):
             quick_thinking_llm.invoke(messages)
```

`AttributionContext` is a `ContextVar` with three legitimate outcomes
(`tradingagents/observability.py`):

| Scope | `attribution_type` | Reporting bucket |
| --- | --- | --- |
| `agent_scoped(agent_id)` | `agent` | `agents[agent_id]` |
| `system_component_scoped(component_id)` | `system` | `system_components[component_id]` |
| no scope | `none` | `unattributed`; run is INVALID |

Telemetry schema 2 records `attribution_type` and `component_id` per event,
keeps system tokens out of every agent bucket, and makes `run_totals` the sum of
agents + system components + unattributed. A system call is never relabelled as
an analyst; a `none` call still fails closed.

Evidence: `REFLECTOR_ATTRIBUTION_AUDIT.md`,
`tests/test_system_attribution.py` (13 tests), and the V3 run report
**(local)**, where all 16 runs report `attribution_complete=true` with zero
unattributed calls. Because the V3 baseline is empty, the pre-graph reflector
does not actually run in this batch; the scope and the
`system_components["pre_graph_reflector"]` bucket are exercised by tests, not by
V3 paid calls.

## 4. The V3 contract: empty snapshot, one copy per run, hashes

V3's memory contract is deliberately small and checkable. It does **not** try to
make memory "better"; it makes the initial state identical for every run.

| Element | Value |
| --- | --- |
| Baseline | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/memory/baseline_v3.md` |
| Baseline SHA-256 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Entries / pending | 0 / 0 (empty file) |
| Mode | `per_run_snapshot_copy` |
| Per-run copy | `specs/<run>/runs/run_01/attempt_MM/memory/trading_memory.md` |
| Write-back to baseline | never |
| Hash in registration | `memory` is in `config_sha256` (`HASHED_FIELDS`) |

**Why empty.** The source developer log contained two settled entries, both
dated 2026-09-23 and both created by earlier rounds of this same study (NVDA by
an earlier round, AAPL by the V2 batch). Keeping either would have given one
ticker a memory advantage; the NVDA block is the only complete 2x2, so keeping
NVDA would have confounded exactly the comparison of interest. The baseline
builder (`scripts/c3_build_memory_baseline.py`) was therefore run with
`--allow-empty --reason`, and provenance is recorded in
`memory/baseline_v3.provenance.json` and `MEMORY_SNAPSHOT_PROVENANCE.md`. The
source log was not modified.

**Pre-run validation.** `scripts/token_benchmark.py` performs these checks
before any paid call (`memory_block_for_registration`, `prepare_run_memory`,
`validate_memory_spec`, `_preflight_gate`):

1. the registration declares `memory.mode = "per_run_snapshot_copy"`;
2. the baseline exists and hashes to `baseline_sha256`;
3. the run copy exists, is byte-identical to the baseline, and was initialised
   from it;
4. the copy is inside its own attempt directory and is not the baseline;
5. the baseline has no pending entries (a pending entry would trigger the
   pre-graph reflector).

Any failure is a `RunRefused`, before the graph is constructed. A V3 registration
that drops the `memory` block is refused both by the per-run gate and by the
batch contract (`_requires_memory_isolation`,
`_batch_requires_memory_isolation`), so deleting the field cannot downgrade a
registered run to the generic path.

**Post-run evidence.** `memory_state_after_run()` writes `memory_state.json`
with:

* `baseline_sha256` and `baseline_sha256_after`;
* `baseline_unchanged`;
* `run_initial_sha256`, `run_final_sha256`, `run_changed`;
* `pending_before`, `pending_after`, `entry_count_before`, `entry_count_after`.

A modified baseline makes the run `INVALID` with
`memory_snapshot_modified` (`INVALID_MEMORY_BASELINE_MODIFIED`); a missing
`memory_state.json` for a memory-bearing spec is `memory_state_missing`
(`INVALID_MEMORY_STATE_MISSING`). The result in V3 was **18/18 attempts with
`baseline_unchanged=true`** (16 runs plus the R02 and R12 retry attempts), and
**16/16 registrations** carry the contract. This is a measurement-mechanics
result (`VERIFIED`), not evidence that memory helps.

Evidence: `MEMORY_ISOLATION_AUDIT.md`, `tests/test_memory_isolation.py`
(21 tests), `tests/test_cand01_batch_16run_v3_infra.py`, and the V3 run report
**(local)**.

## 5. Registered experiments vs generic runs

Memory isolation is a property of the **registered V3 batch**, not of every way
the product can be run. The distinction is enforced by the presence of a
registration, not by a global switch.

| Path | Memory behaviour | Evidence |
| --- | --- | --- |
| Registered V3 run (`specs/<run>/spec.json` with `memory`, `config_sha256`, `registration_dir`) | Baseline snapshot copied into the attempt; `memory_log_path` points at the copy before graph construction; hash-gated before and after | `scripts/token_benchmark.py::prepare_run_memory`, `validate_memory_spec`, `_config_for_spec`; `tests/test_memory_isolation.py` |
| Registered V2 run (no `memory` block) | Shared developer log, as shipped; this is the R05→R06 case | V2 protocol §3; `C3_HALT_REPORT_20261115.md` |
| Generic measurement (`token_benchmark.py measure` on an arbitrary experiment) | No memory block, no copy; the product uses `DEFAULT_CONFIG["memory_log_path"]` (shared) | `_requires_memory_isolation` returns false; audit A finding M3 in `INDEPENDENT_AUDIT_A.md` |
| CLI / direct graph use | Shared log unless the caller sets `memory_log_path`; no experiment gate runs | `tradingagents/graph/trading_graph.py`; `cli/` |

Consequences:

* V3's 18/18 isolation result is **not** a product-wide guarantee. It says the 16
  registered runs were isolated; a generic run or a CLI session can still append
  to the shared log and can still change a later run's prompt.
* The V2 and V3 results are not directly comparable on memory grounds: V2's
  shared log is one of the differences, alongside the attribution schema and the
  news scope.
* The design keeps the product's memory semantics intact; it changes only which
  file a registered run reads and writes.

## 6. Limitations and what is not claimed

1. **No memory benefit is measured.** The baseline is empty, so every V3 run
   starts with no lessons. The study measures the *absence of confounding*, not
   the value of memory.
2. **No cross-run learning in V3.** Each run writes its own copy and nothing
   merges back. That is intentional for a controlled comparison, but it is not
   how a deployed system would accumulate experience.
3. **Isolation is file-level, not a sandbox.** A copy plus SHA-256 checks prove
   which file the product was pointed at and that the baseline did not change.
   They do not prove that no other code path could write elsewhere.
4. **`memory_state.json` is structural.** It checks hashes and pending counts,
   not whether a reflection is semantically correct.
5. **The empty baseline is a design judgement.** It is symmetric and documented,
   but it is not the only defensible choice; a future study that wants to measure
   memory must register a different baseline, and every `config_sha256` would
   change because `memory` is hashed.
6. **Generic runs remain shared.** The pre-existing `measure` path and CLI use
   the shared log; audit A recorded this as a known, out-of-scope residual. Do
   not cite V3 isolation for those paths.
7. **18/18 covers attempts, not independent runs.** The count includes retries
   (R02 attempt 01, R12 attempts 01/02); it is evidence about the gate, not
   about 18 independent samples.

## 7. Evidence index

| Claim | Path |
| --- | --- |
| Product log, pending entry, PIT context | `tradingagents/agents/utils/memory.py` |
| Pre-graph resolve / reflector call | `tradingagents/graph/trading_graph.py` (`_resolve_pending_entries`), `tradingagents/graph/reflection.py` |
| V3 memory contract and provenance | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md` §§1.2, 3; `MEMORY_ISOLATION_AUDIT.md`; `MEMORY_SNAPSHOT_PROVENANCE.md`; `memory/baseline_v3.provenance.json` |
| Pre/post-run enforcement | `scripts/token_benchmark.py` (`memory_block_for_registration`, `prepare_run_memory`, `validate_memory_spec`, `memory_state_after_run`); `scripts/c3_preflight_gate.py` |
| Tests | `tests/test_memory_isolation.py`; `tests/test_system_attribution.py`; `tests/test_cand01_batch_16run_v3_infra.py` |
| V2 halt and R06 diagnosis | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/C3_HALT_REPORT_20261115.md`; local `.worktrees/final_run_20261116/R06_DIAGNOSIS.md` **(local)** |
| V3 execution result | local `.worktrees/v3_runs_20261116/FINAL_EXPERIMENT_REPORT_V3.md` **(local)**; canonical counts in this repository's evaluation logbook |
