# EXPERIMENT_PROTOCOL_V3 — pointer and summary

The normative protocol is
[`CAND01_BATCH_2X2_PROTOCOL_V3.md`](CAND01_BATCH_2X2_PROTOCOL_V3.md) (hashed in
the freeze record as `protocol_sha256`). This file is the deliverable summary
required by the remediation brief.

## Design (unchanged from V2)

2×2 over `batch_macro` × `single_pass`; `structured=true`, `s2_downstream=true`;
16 runs (4 stocks × 4 arms), pre-registered order, one trade date (2026-09-23),
CityU Foundry `CS5351/DeepSeek-V4-Flash`, Finnhub-only news, FRED macro,
`uncapped_authorized` budget with `max_total_tokens=null`.

## New contracts (V3)

1. **Attribution**: `agent` | `system` | `none`; the pre-graph reflector is
   `system:pre_graph_reflector`; `none` invalidates the run; totals close over
   all three buckets.
2. **Memory**: one immutable snapshot; one writable copy per run; verification
   before and after the graph; no write-back; a changed snapshot invalidates.
3. **Registration**: schema 3; `memory` is hashed; 16 new `config_sha256`
   values; the V2 batch is untouched and remains reproducible.

## Freeze

Own commit, own annotated tag `c3-v3-final-freeze`, own verifier invocation
(`C3_BATCH_REL`, `C3_FREEZE_TAG`, `C3_PROTOCOL_NAME`, `C3_GENERATOR`). V2's
`c3-final-freeze` and every V2 artefact stay unchanged.
