# Memory snapshot provenance

**Snapshot:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/memory/baseline_v3.md`
**SHA-256:** `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty file, 0 entries)

## Source and transformation

| Step | Value |
| --- | --- |
| Source | `~/.tradingagents/memory/trading_memory.md` |
| Source SHA-256 | `6eb92fe1417a870a97f5c78e900278b53bbc4cb21360c09e2ab6cad4fea43dc3` |
| Source entries | 2 (NVDA 2026-09-23, AAPL 2026-09-23; both settled) |
| Excluded | **both** entries |
| Result | 0 entries, 0 pending, empty file |
| Generator | `scripts/c3_build_memory_baseline.py` (with `--allow-empty --reason`) |
| Provenance file | `memory/baseline_v3.provenance.json` |

The source log was **not modified**.

## Why both entries are excluded

Audit B (2026-11-16) observed that the kept NVDA entry was not documented,
organic pre-experiment history: both entries are dated 2026-09-23 — the
study's own frozen trade date — and the NVDA decision was produced by an earlier
round of this same study. Keeping it would have given the NVDA four-cell block
(exactly the block with a complete 2×2) a prior decision and a prior reflection
in its Portfolio Manager prompt, while AAPL, JPM and XOM started with none.

The brief allows a documented new baseline when the original state cannot be
restored. An **empty** snapshot is the honest symmetric choice: no ticker gets
memory context, so the 2×2 contrast is not confounded by a memory asymmetry.
The change is recorded here, in the provenance JSON (`empty_baseline: true`,
`empty_reason`), and in the protocol.

## Why no pending entry

A pending entry would make the first run of that ticker call the reflector
before the graph — exactly the cross-run coupling V3 isolates. The baseline
builder refuses to write a baseline containing `| pending]` unless it is
deliberately empty, and the generator refuses to register one.
