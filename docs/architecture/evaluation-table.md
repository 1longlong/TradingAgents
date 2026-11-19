# Evaluation table

**Reading rule.** Part I compares the four V3 arms. It is **not** a significance
test: every cell is one run (n = 1), the three complete blocks are NVDA, AAPL and
XOM, and JPM/CC was never measured. Part II lists the batches and their cells.
A number without a cell is not a result.

**Primary metric.** `total_tokens = provider-reported input + output`. Cached
input is a subset of input and is not added again. "Valid" means the frozen U-1
usage/attribution verdict passed and, for V3, the memory baseline was unchanged.

---

## Part I — qualitative comparison of the V3 arms

### 1.1 Design

| Arm | `batch_macro` | `single_pass` | `structured` | `s2_downstream` | What it tests |
| --- | --- | --- | --- | --- | --- |
| B | off | off | on | on | Two-call baseline (prose then structured finalisation) |
| AB | on | off | on | on | Batch macro alone |
| C0 | off | on | on | on | Single-pass alone (CAND-01) |
| CC | on | on | on | on | Both switches on |

`structured=true` and `s2_downstream=true` are held constant; there is no OFF
implementation of S2 downstream.

### 1.2 Balanced arm means (NVDA, AAPL, XOM; n = 3 per arm)

These are the balanced means used for the factorial. They exclude JPM, whose CC
cell is missing, so that each arm sees the same three blocks.

| Arm | n | Mean total tokens | Mean LLM calls | Mean tool calls | Observed direction |
| --- | --- | --- | --- | --- | --- |
| B | 3 | 218,734 | 21.0 | 32.3 | Most expensive |
| AB | 3 | 206,338 | 21.0 | 25.0 | Cheaper than B on average, but not robust |
| C0 | 3 | 204,450 | 19.0 | 34.0 | Cheaper than B, more tool calls |
| CC | 3 | 181,443 | 18.7 | 25.0 | Cheapest, least reliable |

Pooled 15-sample means are different (B 216,092; AB 205,858; C0 192,612;
CC 181,443) because C0 has four cells and CC three. **Do not use the pooled
means for the factorial**; the balanced table is the one that supports the
effects below.

### 1.3 Factorial effects (tokens; negative = saving)

Definition: batch = mean(AB, CC) − mean(B, C0); single = mean(C0, CC) −
mean(B, AB); interaction = (CC − AB) − (C0 − B).

| Block | B | AB | C0 | CC | Batch effect | Single-pass effect | Interaction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NVDA | 233,199 | 186,378 | 229,187 | 172,577 | −51,716 | −8,907 | −9,789 |
| AAPL | 197,157 | 198,615 | 180,614 | 182,379 | +1,612 | −16,390 | +307 |
| XOM | 225,846 | 234,020 | 203,550 | 189,373 | −3,002 | −33,472 | −22,351 |
| **Mean (3 blocks)** | | | | | **−17,702** | **−19,589** | **−10,611** |

### 1.4 Sensitivity (what survives a defensible exclusion)

| Scenario | Complete blocks | Batch | Single-pass | Interaction |
| --- | --- | --- | --- | --- |
| S1 all 15 valid samples | NVDA, AAPL, XOM | −17,702 | −19,589 | −10,611 |
| S2 exclude R07/R14 (raw-markup `market_report`) | NVDA only | −51,716 | −8,907 | −9,789 |
| S3 exclude R01 (read-only cache: 14 `NO_DATA_AVAILABLE`, 2 `OSError`) | AAPL, XOM | −695 | −24,931 | −11,022 |
| S4 exclude all three | none | — | — | — |

**Interpretation.** The single-pass direction is negative in every estimable
scenario (−8,907 to −24,931), but the magnitude is not stable. The batch effect
is not robust: it is −51,716 only in NVDA, and −695 once the environment-degraded
NVDA C0 run is removed. The interaction is also driven by NVDA/XOM; AAPL is
+307. No confidence interval is reported because n = 1 per cell.

### 1.5 Qualitative comparison

| Arm | Observed behaviour | Reliability / quality signal |
| --- | --- | --- |
| B | Highest balanced mean; no batch tool; two-call path. All four PM ratings were `Underweight` (NVDA, AAPL, JPM, XOM). | No provider failure; no raw-markup report in the B block. |
| AB | Batch macro collapses 7–13 macro calls to one, but the larger batch payload is re-sent; V3 AB is 186,378 on NVDA and 198,615 / 204,421 / 234,020 on AAPL / JPM / XOM. All four PM ratings were `Hold`. | No provider failure in V3. The 339,738 NVDA/AB outlier belongs to V2 (long news loop: 8 `get_news`, 10 tool rounds), not to V3; do not mix the batches. |
| C0 | Single-pass is cheaper than B on average; output falls proportionally more than input (the duplicate prose turn is removed). Ratings mix `Underweight`, `Overweight`, `Hold`, `Hold`. | 5 market fallbacks, all in single-pass arms; R01 (NVDA) is environment-degraded; C0's higher character count is a format artefact (fallback prose), not more analysis. |
| CC | Cheapest balanced mean; lowest output mean; both switches active. Ratings `Hold`, `Hold`, `Underweight`; JPM/CC not measured. | R12 failed twice with provider 400; R07 (AAPL) and R14 (XOM) had raw DSML markup in `market_report` (1,922 and 346 chars). Cheapest on tokens, weakest on reliability. |

**Do not read the ratings as quality.** They are one sample per cell, produced by
one model on one date. The V3 quality review states that there is no ground
truth, no realised return, and no forward-looking return; no arm can be called
more accurate, safer, or better. The only defensible quality statement is
structural: 15/15 runs produced complete decision fields, except R07/R14 whose
`market_report` is markup and R12 which produced no decision.

### 1.6 What the table does not show

* No repeat runs, so run-to-run variance is inseparable from an arm effect.
* No confidence interval, p-value, or power calculation; n = 1 per cell.
* No S2-downstream effect (the switch has no OFF implementation).
* No global-news effect (the global path is `CONFIG_DISABLED` in every arm).
* No memory effect (the V3 baseline is empty, by design).
* No cost in currency, only provider-reported tokens.

---

## Part II — batches and per-block cells

### 2.1 Batch ledger

| Batch | Date / commit | Attempts | Valid | Failed / invalid | Tokens (total) | Tokens (valid) | LLM calls | Tool calls | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RC1 NVDA 2x2 pilot | 2026-11-13 / `9948bf8` | 8 | 8 | 0 | 1,685,450 | 1,685,450 | 160 | 221 | **(local)** `20261113_122951_NVDA_…_live_{A,AB,B,C0}` |
| `baseline_v2` token benchmark | last committed at `6057b52`; run date not recorded | 7 | 5 | 1 timeout + 1 interrupted | 1,076,190 | 1,076,190 | 101 | 157 | `token_benchmarks/baseline_v2/summary.*` |
| V2 2x2 batch | 2026-11-16 / `15270b1` | 7 | 5 | 1 env-failed, 1 invalid | 1,463,791 | 1,109,645 | 99 | 163 | **(local)** `RUN_LEDGER.csv`; canonical record |
| V3 2x2 batch | 2026-11-16 / `e3b5cca` | 18 | 15 | 1 invalid run (2 attempts), 1 env attempt | 3,067,669 | 3,002,579 | 298 | 432 | **(local)** `RUN_LEDGER_V3.csv`, `FINAL_EXPERIMENT_REPORT_V3.md`; canonical record |

Notes:

* **V2 failed tokens** are 354,146 (R05 attempt 01 163,678 + R06 attempt 01
  190,468). **V3 failed tokens** are 65,090 (R02 attempt 01 2,524 + R12
  attempts 31,176 + 31,390). Failed attempts are retained, never averaged.
* V3 valid LLM/tool calls are 298/432. The 16-row ledger reports 302/444 because
  it keeps R12 attempt 02 but not the R02/R12 attempt-01 rows; the all-attempt
  figures are 307/456. Use 298/432 when the denominator is "15 valid samples".
* The RC1 eight-run batch is local-only and is **not** a V2/V3 baseline; its
  news architecture and spec generation differ. It is listed to show the pilot
  that preceded the V2 halt, not for a numerical comparison.

### 2.2 V2 per-block cells (tokens)

V2 had only one complete block (NVDA) plus AAPL/C0; it was halted after R06.

| Block | B | AB | C0 | CC | Status |
| --- | --- | --- | --- | --- | --- |
| NVDA | 205,581 | 339,738 | 191,233 | 192,406 | complete; n = 1 per cell |
| AAPL | invalid (R06) | not executed | 180,687 | not executed | only C0 valid |
| JPM | not executed | not executed | not executed | not executed | not measured |
| XOM | not executed | not executed | not executed | not executed | not measured |

The NVDA arithmetic (for reference only; no significance): batch +67,665,
single −80,840, interaction −132,984. The AB cell (339,738) is the outlier; the
V2 report attributes it to a long news loop, not to a stable batch effect.

### 2.3 V3 per-block cells (tokens)

| Block | B | AB | C0 | CC | Valid cells |
| --- | --- | --- | --- | --- | --- |
| NVDA | 233,199 (R04) | 186,378 (R02) | 229,187 (R01) | 172,577 (R03) | 4 / 4 |
| AAPL | 197,157 (R06) | 198,615 (R08) | 180,614 (R05) | 182,379 (R07) | 4 / 4 |
| JPM | 208,168 (R11) | 204,421 (R10) | 157,095 (R09) | **not measured** (R12 failed twice) | 3 / 4 |
| XOM | 225,846 (R15) | 234,020 (R16) | 203,550 (R13) | 189,373 (R14) | 4 / 4 |

Cell-level caveats:

* R01 (NVDA/C0) is environment-degraded: 14 `NO_DATA_AVAILABLE` and 2 `OSError`
  from a read-only cache; its report used a 10-day proxy. It is a valid sample by
  the frozen U-1 rules but it contaminates the NVDA batch contrast.
* R07 (AAPL/CC) and R14 (XOM/CC) are valid samples but their `market_report` is
  raw DSML markup, not a report. Excluding them leaves only NVDA for the
  factorial.
* R12 (JPM/CC) never produced a decision; it is excluded from every mean.

### 2.4 Data provenance

| Evidence | Status |
| --- | --- |
| `token_benchmarks/baseline_v2/summary.{md,json,csv}`; V2/V3 protocols; V3 audits; final-remediation reports | Tracked in `50b2ca3` |
| Raw paid telemetry and per-run `runner_report.json` | Git-ignored; **(local)** under `.worktrees/` |
| RC1 eight-run pilot, Stage 1/2 campaign, V3 factorial tables | **(local)**; not deliverable evidence |

The table above separates "recorded" from "recomputed". The 1,685,450 RC1 total,
1,076,190 baseline total, 1,463,791 V2 total and 3,067,669 V3 total are
arithmetic sums of the rows cited; they are not estimates.
