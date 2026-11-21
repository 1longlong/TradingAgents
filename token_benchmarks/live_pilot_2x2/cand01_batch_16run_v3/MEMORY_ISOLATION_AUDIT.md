# Memory isolation — design and evidence

## 1. Problem

The product keeps one decision log. A run appends `[date | ticker | rating |
pending]`; the next run's `propagate()` resolves it first, which adds a provider
call and changes that run's prompt context. In V2 the 16 runs shared that state:
R05 (AAPL) changed R06's execution path and token cost.

## 2. Contract

| Element | Value |
| --- | --- |
| Baseline | `memory/baseline_v3.md` (immutable, tracked, hashed) |
| Baseline SHA-256 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Mode | `per_run_snapshot_copy` |
| Per-run copy | `specs/<run>/runs/run_01/attempt_MM/memory/trading_memory.md` |
| Write-back to baseline | never |
| Verification | before the graph: baseline hash, copy hash == baseline, copy inside its attempt dir, copy != baseline; after the graph: baseline hash unchanged |

The baseline contains no `pending` entries, so no run triggers the pre-graph
reflector. It is deliberately empty: both entries in the developer log were created
by prior experiment runs (NVDA by an earlier round, AAPL by the 2026-11-16
batch), so no ticker gets a memory advantage (provenance in
`memory/baseline_v3.provenance.json`).

## 3. Wiring

| Layer | Change |
| --- | --- |
| `build_run_spec` | attaches the registration's `memory` declaration |
| `prepare_run_spec` | copies the snapshot into the attempt dir, records `run_memory_path`, `run_initial_sha256`, pending/entry counts |
| `_config_for_spec` | sets `config["memory_log_path"] = run copy` **before** graph construction |
| `_preflight_gate` / `_guard_spending_path` | refuses a missing/changed snapshot, a modified copy, a copy outside the attempt, or a V3 spec without a memory block — before any paid call |
| `_run_single` | writes `memory_state.json`; a modified baseline makes the run `failed` |
| `execute_measured_run` / `_read_attempt` | records `memory` in metrics and metadata; a changed baseline is `memory_snapshot_modified` (INVALID) |

## 4. Evidence

`tests/test_memory_isolation.py` (17/17):

* every run gets a distinct copy of the same snapshot;
* a write to one copy leaves the baseline and every other run untouched;
* run order does not change any run's initial state;
* missing snapshot, changed snapshot, modified copy, copy == baseline, copy
  outside the attempt dir, missing memory block, wrong hash, wrong mode → all
  refused before the graph;
* `_resolve_pending_entries` on run A's copy calls the reflector once; run B's
  copy has no pending entry and calls it zero times;
* the harness records a clean run as valid and a tampered baseline as INVALID
  with `memory_snapshot_modified`.
