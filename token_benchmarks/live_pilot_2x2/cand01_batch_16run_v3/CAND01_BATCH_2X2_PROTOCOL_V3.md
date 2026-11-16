# CAND-01 × Batch-Macro 2×2 — Protocol V3 (attribution + memory isolation)

**Status:** pre-registration for the next paid batch. No paid call has been made
under V3.

V3 keeps the V2 **design** unchanged and adds two engineering contracts that the
2026-11-16 run proved necessary. Because both contracts are hashed, every V3
`config_sha256` is new by construction; no V2 value is reused or re-interpreted.

| Field | Value |
| --- | --- |
| Design | 2×2 over `batch_macro` × `single_pass`; `structured=true`, `s2_downstream=true` |
| Stocks | NVDA, AAPL, JPM, XOM |
| Trade date | 2026-09-23 (one date, four stocks, PIT) |
| Runs | 16 (one per cell), pre-registered order |
| Seed | 20261114 |
| Provider / endpoint | `openai_compatible` / CityU Foundry `https://llm.cs.cityu.edu.hk/v1` |
| Models | `CS5351/DeepSeek-V4-Flash` (quick and deep) |
| News | Finnhub only; GDELT excluded; global news `CONFIG_DISABLED` |
| Macro | FRED |
| Budget | `budget_mode=uncapped_authorized`, `max_total_tokens=null` |
| Memory | one immutable snapshot, one writable copy per run |
| Telemetry schema | 2 (adds system-component attribution) |

---

## 1. What changed from V2, and why

### 1.1 Reflector attribution

The product resolves pending decision-log entries *before* the graph starts:

```
propagate() → _resolve_pending_entries(ticker) → Reflector.reflect_on_final_decision()
           → quick_thinking_llm.invoke(...)          # outside every Agent node
```

In V2 that provider call had no attribution scope, so it was recorded as
`unattributed` and the run was voided (R06, 2026-11-16). V3 introduces a unified
attribution context with two legitimate kinds:

* `agent` — set by `attrib_agent_node` for every graph node;
* `system` — set by `system_component_scoped` for product components that call a
  provider outside a node. The pre-graph reflector is
  `component_id = "pre_graph_reflector"`.

A provider call made with **no** scope is `attribution_type="none"` and remains
an invalid sample. A system component is never relabelled as an agent.

### 1.2 Memory isolation

A run appends its decision to the developer log and the *next* run resolves it
(one extra provider call, and a different prompt context). In V2 the 16 runs
therefore shared mutable state: R05 changed R06's execution path. V3 fixes this:

* one **immutable baseline snapshot** (`memory/baseline_v3.md`) ships with the
  batch; its SHA-256 is recorded in every registration and hashed;
* every run gets its **own copy** at
  `specs/<run>/runs/run_01/attempt_MM/memory/trading_memory.md`;
* the child verifies, before constructing the graph, that the baseline still
  hashes to the registered value, that its copy exists, is byte-identical to the
  baseline, and lives inside its own attempt directory;
* after the run the child records `memory_state.json` (baseline before/after,
  run copy before/after, pending counts) and the run is **invalid** if the
  baseline changed;
* no run merges back into the baseline, so run order cannot change any other
  run's initial state.

Provenance of the baseline (what was kept, what was excluded, and why) is in
`memory/baseline_v3.provenance.json` and in `MEMORY_SNAPSHOT_PROVENANCE.md`.

## 2. Usage attribution validation

Every provider-usage event must carry:

| Field | Meaning |
| --- | --- |
| `attribution_type` | `agent` \| `system` \| `none` |
| `agent_id` | the agent, or `unattributed` for `none` |
| `component_id` | the system component for `system` |
| input / output / cached / reasoning tokens | provider-reported |
| `global_sequence` | call order within the run |

Validation (fail closed):

* `attribution_type="none"` anywhere → the run is **invalid**
  (`token_usage_incomplete`);
* a system component is legitimate and keeps the run valid, but it is reported
  in its own `system_components` bucket and never inside `agents`;
* `run_totals` must equal the sum over agents + system components + the
  unattributed bucket; per-event token sums must equal `run_totals`;
* a token field the provider did not report is `null`, never `0`.

## 3. Memory state validation

A run may start only when all of the following hold (checked before any paid
call):

1. the registration declares `memory.mode = "per_run_snapshot_copy"`;
2. `memory/baseline_v3.md` exists and hashes to the registration's
   `baseline_sha256`;
3. the run's copy exists, hashes to the baseline at start, and is inside the
   attempt directory;
4. the run's copy is not the baseline and not another run's copy;
5. the baseline contains no `pending` entries (a pending entry would trigger a
   pre-graph reflection; the baseline builder refuses to produce one).

Any failure is a `RunRefused` **before** the provider is called.

## 4. Failure classification

| Class | Meaning |
| --- | --- |
| `VALID` | completed, usage complete, attribution complete (agents and/or system components), memory baseline unchanged |
| `INVALID` | completed but failed a measurement requirement; retained, never a sample |
| `FAILED` | the run did not complete (provider/graph error) |
| `REFUSED` | a precondition failed before any paid call |

## 5. Retry policy

* No retry of a run whose paid outcome is unknown.
* A retry is allowed only for a **known** failed/invalid attempt with complete
  provider usage, in a new attempt directory, and only with explicit operator
  authorisation for that run.
* A retry never overwrites evidence; the failed attempt is retained.

## 6. Statistical analysis plan

* Primary outcome: `total_tokens` per run, decomposed into input/output/cached.
* Secondary: LLM calls, tool calls/rounds, runtime, per-agent tokens, structured
  failures/fallbacks.
* The 2×2 is analysed for NVDA (complete four-cell block) as **EXPLORATORY** at
  n=1 per cell; no significance test is reported for n=1.
* Cross-ticker comparisons are descriptive only.
* Classifications: `VERIFIED` (measurement mechanics), `EXPLORATORY` (4-cell
  observations), `INCONCLUSIVE` (effects with n=1), `NOT_MEASURED` (unexecuted).

## 7. Pre-assigned Run IDs and hashes

Run IDs are assigned before execution, in execution order.

| Run | Pos | Block | Arm | `batch_macro` | `single_pass` | `structured` | `s2_downstream` | `config_sha256` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `R01` | 1  | NVDA | C0 | false | true  | true  | true  | `5fc3a52d779da857badb52b644620b1bb987a744e0d065604f2568071bdbe550` |
| `R02` | 2  | NVDA | AB | true  | false | true  | true  | `082cb36ccfcaab1001a4c5479bc70551c4c847ce76da266295045a3c41366969` |
| `R03` | 3  | NVDA | CC | true  | true  | true  | true  | `a05775c5b62e7cfb937f1f354e081731048614dfe0fb81700527ac2dc5576a33` |
| `R04` | 4  | NVDA | B  | false | false | true  | true  | `5b5b2b10f94c9c699081aa92557006acbbbcd5a0a2e105036ae219652d346197` |
| `R05` | 5  | AAPL | C0 | false | true  | true  | true  | `69084a290d7304df68284648e15007a7cd1b167458e200ea0699443ed28e091e` |
| `R06` | 6  | AAPL | B  | false | false | true  | true  | `efccdc081e08c0cb013e752b084e342da68ab6b50907528318c57558560acd65` |
| `R07` | 7  | AAPL | CC | true  | true  | true  | true  | `6fc1ef8a440cb07ffbf587fc217567a0d31c0ef1d8cbb78f385b649f3647031c` |
| `R08` | 8  | AAPL | AB | true  | false | true  | true  | `38364cad01bc1ab12ba95518367651d76b16d517d1a717422a1635322d0d2248` |
| `R09` | 9  | JPM | C0 | false | true  | true  | true  | `4827f4115e811278b6d359e0e4deb3a794156f91a7e4a0262838093263e531cb` |
| `R10` | 10 | JPM | AB | true  | false | true  | true  | `ee050570a44ca9092908e89083f863edfc65eb8c8aaa28e7c6bda1b25ca4dcfe` |
| `R11` | 11 | JPM | B  | false | false | true  | true  | `0d10cea66afb111b1c9a255053a8563793a854601fe79e2edaf83639c5e441db` |
| `R12` | 12 | JPM | CC | true  | true  | true  | true  | `d8073546061751c2a9e4b0d669652446da55c668bb15f39ec1cb5e1fcc7c98db` |
| `R13` | 13 | XOM | C0 | false | true  | true  | true  | `089eac5c6d5426a5f11650ce827bfd515d77765c96a98eb85fdf7035189658be` |
| `R14` | 14 | XOM | CC | true  | true  | true  | true  | `60e7160a375aa53b4b116e2c77bd175ef9e5a6c17e35e159639fdf28ce572dab` |
| `R15` | 15 | XOM | B  | false | false | true  | true  | `275a2c1ac93e5362159207e95fbe1416e5a7225eb9f758200b22678c36bb0f8e` |
| `R16` | 16 | XOM | AB | true  | false | true  | true  | `81234d74106f3e59e4bf5e49f2dc130131d9d2e3decf037421840e39ae71264b` |

Machine-readable copies: `CONFIG_HASH_MANIFEST.csv`, `RUN_MANIFEST_TEMPLATE.csv`,
`SWITCH_MATRIX.csv` (all generated, never hand-edited).

## 8. `config_sha256` algorithm

Defined by `scripts/gen_cand01_batch_16run_specs_v3.py::config_sha256`.

| Element | Specification |
| --- | --- |
| Input | exactly the fields in `HASHED_FIELDS` |
| Canonicalisation | `json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))` |
| Encoding | UTF-8 |
| Digest | lowercase hex SHA-256 |
| Self-hashing | excluded |
| Excluded by design | `config_sha256`, `description`, `protocol_version`, `measured_runs`, absolute paths |

```python
HASHED_FIELDS = (
    "experiment_id", "schema_version", "switches_required", "provider",
    "quick_model", "deep_model", "output_language", "cache_policy",
    "checkpoint_enabled", "budget", "memory", "cases", "switches", "news_scope",
)
```

`memory` is hashed, so a changed snapshot (or a changed isolation mode) changes
every `config_sha256` and cannot run under an old registration.

## 9. Switch delivery and consumption

Unchanged from V2: the spec is authoritative for the four switches; the child
applies them to `config`, exports them to the child environment, and asks the
constructed `GraphSetup` what it consumed (`switches_observed_from_graph_setup`).
`s2_downstream=false` is refused because no OFF implementation exists. The
`effective_config.json` record is verified against the spec before `propagate`.

## 10. Preflight and per-run gate

Before each paid run:

```
python scripts/c3_preflight_gate.py --run-id R01 --spec <batch>/specs/R01_NVDA_C0/spec.json
```

The gate verifies the frozen commit/tag/tree/fingerprint, the release seal, the
spec hash and every shared field against the registration, the arm against both
the protocol arm table and `SWITCH_MATRIX.csv`, the news scope, the memory
snapshot, and the spec's location inside its registered directory.

## 11. Freeze statement

V3 is frozen by its own commit and annotated tag (`c3-v3-final-freeze`). The
verifier binds `HEAD`, the record, the tag and the append-only history to the
same commit, and recomputes the tree SHA, the working-tree fingerprint, every
`MANIFEST.sha256` entry, all 16 `config_sha256` values, the memory snapshot, the
protocol and generator hashes.

```
C3_BATCH_REL=token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3 \
C3_FREEZE_TAG=c3-v3-final-freeze \
C3_PROTOCOL_NAME=CAND01_BATCH_2X2_PROTOCOL_V3.md \
C3_GENERATOR=scripts/gen_cand01_batch_16run_specs_v3.py \
python scripts/c3_verify_final_freeze.py
```

## 12. Known limitations (unchanged from V2)

* n = 1 per cell; exploratory only.
* Finnhub is the only news vendor.
* Global news is disabled; no global-news effect is in scope.
* `s2_downstream` has no OFF implementation.
* PIT is day-granular.
* The model endpoint is addressed by name; no model-version pin is possible.
