# ADR 005 — Per-run memory isolation for the measured 2×2

**Status:** Accepted (retrospective)
**Date:** Not recorded in the source material. Reconstructed from the V3 protocol and
the V3 freeze; no calendar date is asserted.
**Related invariants:** INV-7, INV-14.

## Context

The product keeps one append-only decision log. A run appends a pending entry; the
next same-ticker run resolves it before the graph starts, which makes one extra
provider call (the Reflector) and changes that run's prompt context. This is
deliberate product behaviour: the system is supposed to learn from settled decisions.

For a controlled 2×2, that behaviour is a confound. In V2 the 16 runs shared the
developer log: R05 (AAPL) wrote an entry that changed R06's execution path and token
cost. The measured effect of a switch could therefore include the effect of run
order. The V2 batch's own audit trail identifies this as a design flaw, not a model
variance issue.

The fix has to preserve the product path (the same `TradingMemoryLog`,
`_resolve_pending_entries`, and Reflector) while ensuring each measured run starts
from an identical memory state and cannot mutate another run's input.

## Options considered

### A. Disable memory entirely for the experiment

Set `memory_log_path` to a throwaway path and skip the pre-graph settlement.
**Rejected.** It changes the product under test: the Reflector call disappears from
the execution path, so the experiment would no longer measure the shipped run. It
also removes the very system-component call that ADR 001 was designed to attribute.

### B. Keep the shared log and randomise/rotate run order

**Rejected.** Randomisation does not remove contamination at n=1 per cell; it only
hides it. The runs are pre-registered in a fixed order, and the contamination is
deterministic (R05 → R06), so order randomisation is not a control.

### C. Give every run a writable copy of one immutable baseline snapshot

**Chosen.** A single empty baseline is shipped with the batch. Each run receives its
own copy inside its attempt directory; the graph's `memory_log_path` points at that
copy; the baseline is never written. The product code path is unchanged.

### D. Reset the shared log back to the baseline before every run

**Rejected.** It still uses one writable path, so a concurrent or interrupted run can
race the reset, and a post-run audit cannot prove which content a run saw. A copied
per-attempt file is independently hashable and survives the run.

### E. Use a fresh empty file per run but do not hash the baseline

**Rejected.** Without a declared baseline and hash, the "same initial state" claim is
not checkable and a doctored registration could silently change the starting log.

## Decision

- Ship one immutable baseline snapshot
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/memory/baseline_v3.md`
  (empty, SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
- Every run gets a writable copy at
  `specs/<run>/runs/run_01/attempt_MM/memory/trading_memory.md`.
- `_config_for_spec` sets `config["memory_log_path"]` to that copy before the graph
  is constructed (`scripts/token_benchmark.py:4161-4180`).
- Preflight verifies the baseline hash, the copy hash equals the baseline before the
  graph, the copy is inside its own attempt directory, and the copy is not the
  baseline (`scripts/token_benchmark.py:3784+`, `4230+`). A V3 registration without a
  memory block is refused.
- After the graph, `memory_state.json` records the baseline hash and whether it
  changed; a changed baseline makes the run `INVALID` with
  `memory_snapshot_modified` (`scripts/token_benchmark.py:2715`, `2878`).
- The memory declaration is part of `config_sha256`, so a snapshot change moves all
  16 registered hashes and cannot pass as the same experiment.

The baseline is deliberately empty. Two entries in the developer log had been created
by earlier runs of this study (NVDA from an earlier round, AAPL from 2026-11-16); keep-
ing either would give one ticker a memory advantage and break symmetry. The
provenance file records what was excluded and why
(`MEMORY_SNAPSHOT_PROVENANCE.md`).

## Rationale

- It isolates the *state*, not the *code path*. The same `TradingMemoryLog`,
  `_resolve_pending_entries`, and `Reflector` run, so the experiment still exercises
  the product and the system-component attribution.
- A copy is independently hashable. "All runs started from the same bytes" becomes a
  check rather than a promise.
- The baseline/copy distinction makes write-back detectable. A run that writes to the
  baseline is a visible failure, not a silent order effect.
- Hashing the memory block into `config_sha256` makes the isolation a registered part
  of the experiment, not a runtime convention.

## Consequences

### Positive

- V3 runs are order-independent by construction. `tests/test_memory_isolation.py`
  proves that a pending entry in run A's copy triggers one Reflector call for A and
  zero for B, using the product's own `_resolve_pending_entries`.
- The empty baseline removes ticker-specific memory advantage. The tests compare all
  16 registrations' snapshot hashes and assert the baseline has no pending entries.
- A doctored spec that drops the memory block, changes the hash, points the copy
  outside the attempt, or reuses the baseline is refused before spending.
- The auditor can recompute the baseline hash from the freeze manifest and compare it
  to every run's `memory_state.json`.

### Negative

- The harness gained a sizeable preflight surface: snapshot hashing, copy creation,
  path containment, post-run state, and invalidation. It is tested, but it is now a
  failure domain of its own.
- The isolation is experiment-only. A product user still has one shared log; this ADR
  does not change that.
- The empty baseline means V3 measures a system with no prior lessons. That is the
  right choice for a controlled comparison but it is not the same as a mature
  deployment with a populated log.
- A failed copy/verification aborts a paid run before the graph (by design), which
  means a harness bug can waste a scheduled experiment slot even though no tokens are
  spent.

## Evidence

- **Code:** `tradingagents/agents/utils/memory.py` (product log);
  `tradingagents/graph/trading_graph.py:360-408` (settlement, Reflector);
  `scripts/token_benchmark.py` (`prepare_run_spec`, `_config_for_spec`,
  `_preflight_gate`, `_guard_spending_path`, memory-state invalidation).
- **Commits:** the V2 freeze `15270b1` still had shared memory; the per-run contract
  is part of V3 and is frozen at `e3b5cca` (tag `c3-v3-final-freeze`). Final tree
  `50b2ca3`.
- **Tests:** `tests/test_memory_isolation.py` — 21 tests, including distinct copies,
  write isolation, order independence, all preflight refusals, the product
  `_resolve_pending_entries` order-independence proof, clean-run validity, tampered
  baseline invalidation, missing-evidence invalidation, doctored-registration refusal,
  and baseline provenance. See also `tests/test_memory_pointintime.py`,
  `tests/test_memory_log.py`, `tests/test_memory_isolation.py::TestBaselineProvenance`.
- **Reports:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/MEMORY_ISOLATION_AUDIT.md`,
  `MEMORY_SNAPSHOT_PROVENANCE.md`, `CAND01_BATCH_2X2_PROTOCOL_V3.md` §1.2;
  `BRANCH_HISTORY_REPORT.txt` §3.5; `FINAL_ENGINEERING_REPORT_CN.md` §1.2
  (21/21 tests at the time, 17/17 in the earlier audit record).

## What this ADR does not claim

It does not claim the product has per-run memory isolation, and it does not claim
memory has no effect on a run. It claims the *measured* V3 runs each began from the
same immutable bytes and could not write each other's input, and that this property is
checked before and after each run.
