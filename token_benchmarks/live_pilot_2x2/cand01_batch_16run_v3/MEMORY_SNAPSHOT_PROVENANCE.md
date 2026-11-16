# Memory snapshot provenance

**Snapshot:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/memory/baseline_v3.md`
**SHA-256:** `01102211cc012807956e3a31bafc587b90d518daa3335d07d33c571cfecf8c96`

## Source and transformation

| Step | Value |
| --- | --- |
| Source | `~/.tradingagents/memory/trading_memory.md` |
| Source SHA-256 | `6eb92fe1417a870a97f5c78e900278b53bbc4cb21360c09e2ab6cad4fea43dc3` |
| Source entries | 2 (NVDA settled, AAPL settled) |
| Excluded | `AAPL 2026-09-23` (entry sha `5698209d84cc…`), created by the 2026-11-16 run, not pre-experiment history |
| Kept | `NVDA 2026-09-23` (historical, settled) |
| Result | 1 entry, 0 pending |
| Generator | `scripts/c3_build_memory_baseline.py` |
| Provenance file | `memory/baseline_v3.provenance.json` |

The source log was **not modified**. The exclusion is a documented
transformation: the AAPL entry is an artefact of the experiment being
baselined, and keeping it would inject that experiment's own decision as
"past context" into the new one. No other entry was removed, and no entry was
edited.

## Why no pending entry

A pending entry would make the first run of that ticker call the reflector
before the graph — exactly the cross-run coupling V3 isolates. The baseline
builder refuses to write a baseline containing `| pending]`, and the generator
refuses to register one.
