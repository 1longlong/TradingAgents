# Plan C3 — Protocol Freeze Declaration

**Status: FROZEN — no paid call was made before this document was committed.**

| Field | Value |
| --- | --- |
| Protocol | [`CAND01_BATCH_2X2_PROTOCOL_V2.md`](./CAND01_BATCH_2X2_PROTOCOL_V2.md) (V2, unchanged from registration) |
| Branch | `exp/cand01-batch-v2` (off RC1 `9948bf85…`) |
| Frozen commit | `c3/FROZEN_COMMIT` (untracked release metadata; see "Why the SHA is not in this file") |
| Code fingerprint | whatever `c3/code_freeze.txt` currently says — recomputed by `c3_preflight_gate.py` on every run, never copied here (see §4) |
| Trade date | `2026-09-23` for every ticker in every arm (one date, four stocks) |
| Seed | `20261114` |
| Models | `CS5351/DeepSeek-V4-Flash` (quick and deep, identical across arms) |
| `max_total_tokens` | `null` — uncapped by design; usage recorded in full, never estimated |
| Paid calls at freeze time | **0** |

## 1. Design under test (unchanged from V2)

A 2×2 over **`batch_macro` × `single_pass`**, four arms, four stocks, one run
each — 16 runs. `structured` and `s2_downstream` are **held constant**, not
varied (protocol §3).

| Arm | `batch_macro` | `single_pass` | `structured` | `s2_downstream` | Stocks |
| --- | --- | --- | --- | --- | --- |
| `B`  | false | false | true | true | NVDA, AAPL, JPM, XOM |
| `AB` | true  | false | true | true | NVDA, AAPL, JPM, XOM |
| `C0` | false | true  | true | true | NVDA, AAPL, JPM, XOM |
| `CC` | true  | true  | true | true | NVDA, AAPL, JPM, XOM |

`structured=true` everywhere because CAND-01 only takes effect when structured
output is enabled (`GraphSetup` computes `single_pass AND structured`), so an arm
with `structured=false` would silence the factor under test rather than vary it.
`s2_downstream=true` everywhere because **no OFF implementation exists**; the
spec refuses `false` instead of inventing a no-op toggle. Consequence, stated
plainly: **this round cannot estimate an S2-downstream effect and does not claim
to.**

Verified: all 16 registrations carry `structured=true` and `s2_downstream=true`,
and each arm's `batch_macro`/`single_pass` pair matches the table above exactly.

### Run IDs

`R01…R16`, pre-assigned in the protocol (§5) and hashed into `config_sha256`.
Each ID names exactly one run; a duplicated ID is refused by the gate.

### Execution order (pre-registered, from seed `20261114`)

```
NVDA: ['C0', 'AB', 'CC', 'B']
AAPL: ['C0', 'B', 'CC', 'AB']
JPM:  ['C0', 'AB', 'B', 'CC']
XOM:  ['C0', 'CC', 'B', 'AB']
```

`EXECUTION_ORDER.txt` is authority; a test asserts this table equals it.

**R01 is executed first regardless of order**, as the C3 validation run. It is
`NVDA / C0`, which is also the first block's first arm, so the exception does not
perturb the pre-registered sequence: R01 is already first.

## 2. What was verified before the freeze

| Check | Result |
| --- | --- |
| 16 specs reproduce from the generator | OK — 53 artefacts reproduce; 16 differ only in volatile `timestamp_utc` |
| `MANIFEST.sha256` | 94/94 verify |
| All 16 `config_sha256` recomputed and compared field-by-field | 16/16 match |
| Gate, offline, all 16 runs | 16 pass, 0 fail |
| Gate, live, R01 | PASS (Finnhub `NVDA: 8582 chars`; FRED `fed_funds_rate` real observations) |
| News scope | Finnhub-only in every spec; `gdelt: excluded`; `get_global_news` disabled |
| Imports | `tradingagents` resolves under the worktree, not the shared checkout |
| Full test suite | 2083 passed, 2 skipped, 319 subtests |

## 3. Stopping conditions (from protocol §11, restated)

A run is stopped, and the round halted, on any of:

1. a PIT violation (news or macro dated after the trade date);
2. a Finnhub-only breach (any GDELT or non-Finnhub news call);
3. a FRED failure that makes the macro arm invalid;
4. a switch mismatch (an arm that runs as a different arm);
5. an unexpected duplicate tool execution;
6. lost or unattributable usage (tokens that cannot be tied to an agent and a run);
7. a run importing the wrong code (the imported `tradingagents` outside the frozen tree);
8. data-integrity loss (a historical artefact changed or an attempt deleted);
9. a fabricated or unverifiable evidence artefact;
10. a newly discovered High or Critical defect.

A run that fails condition 1–3, 7 or 8 is retained and reported as failed. It is
never deleted, and it is never counted as a valid sample.

## 4. Why the SHA is not in this file

A commit cannot contain its own hash. Naming one here would freeze a value that
is false the moment the file is committed — exactly the stale-provenance defect
audit A-07 found. The authority is therefore:

* `c3/FROZEN_COMMIT` — the untracked release tag, written once and read by the gate;
* `code_freeze.txt` — the code fingerprint, which is *stable* across the commit
  because the `c3/` directory is excluded from fingerprinting.

`c3_preflight_gate.check_fingerprint_matches_record` recomputes the fingerprint
and refuses if the record describes a different tree.

## 5. Amendment policy

Any change to the design, the seed, the hash algorithm, the news scope, the arms
or the trade date requires a **new protocol version**. V1 and V2 both stay on
disk unmodified. This freeze declaration may be *added to* (append-only) to
record execution, but its design fields may not be edited.
