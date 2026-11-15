# Plan C3 — Execution Halt Report (2026-11-15)

**Status: HALTED before any paid run. Zero paid LLM calls. 0 of 16 runs executed.**
Branch: `exp/cand01-batch-v2` @ `1bba51f6568e2147c27b36cc83fbb551f2302bf9`.
Main repo `9948bf85…`, `rc1`, `72ae0f8`, `2e62ccb`, 3 stashes: **all intact, nothing pushed.**

---

## 1. Why they halted

I did not stop because the code was unready. I stopped because **I could not certify a
tree that I kept changing.** The three round-5 audits agree, and the most damaging
finding is procedural and mine:

| Audit | Round 5 verdict | Principal reason |
|---|---|---|
| A | NOT_READY | H-C case tampering (real, now fixed); R-5-B circular freeze; **H-E recurred: tree moved mid-audit** |
| B | READY (C1–C5) | B-15 genuinely closed; but B-20/B-21/B-23/B-26 found |
| C | NOT_READY | **C-12: tree moved under it, repeatedly**; U-1/U-2 still open |

Audit A recorded HEAD as `73849af → eaba4f7 → d7af7ea → f556bef` **during** the audit.
Audit C recorded the same, and stated the consequence exactly: there is no longer a
single clean commit to certify.

## 2. The self-tamper incident (disclosed in full)

While reproducing Audit A's R-5-B, I ran `cp -a planC2_wt _attest_probe` intending a
sandbox. A git **worktree's `.git` is a 64-byte pointer** into the real repository, so
the copy wrote two commits to the **audited branch**:

- `e1d018e` "tamper" — actually carried the genuine H-C fix, under a wrong message;
- `d7af7ea` "resign" — ran the freeze writer and committed a **re-sealed release record**
  that certified the *probe* tree's fingerprint and named
  `PYTHONPATH=/tmp/opencode/_attest_probe`.

The gate subsequently printed `GATE PASSED — safe to spend money` on that state.

Full record: `INCIDENT_20261115B_self_tamper.md`. The commits are **not** rewritten or
deleted; they remain in history.

## 3. What was genuinely fixed this round

| Finding | Severity | Fix | Mutation proof |
|---|---|---|---|
| **H-C** `case` sub-fields accepted | Critical | spec `case` now matched to registration `cases` by `case_id`, field by field | M14 → 7 tests red |
| **R-5-B** circular freeze check | High | append-only `c3/FREEZE_HISTORY.jsonl`; first entry designates the commit, later entries cannot retract it; tracked, so inside the fingerprint | new tests |
| **R-5-C** skip flag reached paid child | High | parent strips it from child env; refused outright for frozen-batch registrations | M15/M16 → red |
| **R-5-D** `C3_FROZEN_COMMIT` redirect | Medium | override may only *restate* the file, never replace it | M17 → red |
| **B-20** no test for protocol-arm authority | Med/High | two tests pin it against the protocol document | M10 → red |
| **B-21** guard test executed the *real* writer | Medium | test now runs a redirected copy; real seal verified untouched | M6 → red |
| **B-23** no spec/config hash recorded for a run | Medium | `effective_config.json` records them | M11 → red |
| **B-26** silent escape hatch | Low | announces itself; only `"1"` opts out | M12/M13 → red |

I also **refuted B-25**: removing `deep_model`/`case` from `_SPEC_REQUIRED_FIELDS` turns
exactly those two parameters red, so those tests are load-bearing. I refuted it in
writing rather than "fixing" a non-problem.

Suite: **2,099 passed, 2 skipped, 319 subtests**. Every mutated file restored
SHA-256-identical.

## 4. What is still open

- **U-1** `agrees_with_telemetry` is computed and never consumed; a disagreeing run still
  reports `valid=True`. Audit C requires such a run to be **void**, not flagged.
- **U-2** `max_total_tokens: null` is indistinguishable from a missing protocol file.
- **B-08/B-24/B-27**, **L-5** (raw vendor usage not preserved), **A-03/A-04/A-12**.
- **My own attestation is currently wrong**: it designates `eaba4f7`, which is now an
  ancestor of HEAD, so HEAD can never equal it and all 16 runs would be refused forever.
  That is my error, caught by testing rather than by reasoning.

## 5. Why I did not force a sixth re-freeze

Each fix requires re-freezing; re-freezing during an audit is precisely what Audits A and C
flag. Continuing to patch-and-re-seal in a loop would have produced a green gate and a
dishonest certification. **The gate refusing all 16 specs right now is the correct
behaviour**, and I am not going to circumvent it.

## 6. What is true and safe

- **Zero paid calls.** `live_run_ledger.jsonl` has no `cand01_batch_16run_v2` entries; 0
  `runs/` and 0 `attempt_*` directories under the batch.
- No historical experiment directory touched; no protected ref moved; nothing pushed.
- `.env` and its keys untouched and never printed.
- Untracked leftovers from my probes: a stray empty `0` file and an empty `NVDA/`
  directory at the worktree root (created 23:50 by a probe that resolved paths against
  cwd). Left in place and disclosed rather than quietly removed.

## 7. Recommendation

1. **Declare a freeze window with no writes at all** — including by me — and audit one
   immutable commit to completion.
2. Fix U-1/U-2 (both small: consume the flag and require the protocol file), correct the
   attestation to designate the *final* commit, then re-freeze **once**.
3. Re-run Audits A and C against that one commit, with no commits permitted until both
   have reported.
4. Only then run R01 and continue to R16.

`real investment returns` will remain **NOT_MEASURED** in any final report: these 16 runs
measure `total_tokens` (the pre-registered primary outcome), not P&L. No profitability or
alpha claim can be supported, and none should be made.

---

## Addendum (2026-11-16) — superseded by the final freeze

This halt report is preserved unmodified above as the record of why Plan C3
stopped. Its open items have since been closed in a single round; the detail and
the evidence are in `REMEDIATION.md` (Round 6) and `EXECUTION_READINESS.md`:

| Open item in §4 | State now |
| --- | --- |
| U-1 `agrees_with_telemetry` never consumed | **Fixed** — verdict gates validity; `MISSING`/`INCOMPLETE`/`MISMATCH` void the run |
| U-2 null cap indistinguishable from a missing file | **Fixed** — `budget_mode = uncapped_authorized` required; seven distinct refusal states |
| "my own attestation designates `eaba4f7`, an ancestor" | **Fixed** — designation is written after the final commit and must equal `HEAD`, the tag and the record |
| B-08 / B-24 / B-27, A-03 / A-04 / A-12 | B-08 (release-seal consistency) and B-23 (effective-config recording) are closed with executable checks. A-03 was already fixed. A-04 is the documented serial-fetch limitation (L-2). **B-24, B-27 and A-12 have no definition anywhere in this repository** — the audit reports that described them lived in a scratch worktree that no longer exists, so this round does *not* claim them closed by name. That absence is a recorded evidence gap, not a pass: what survives of their likely subject matter (seal/provenance consistency, spec/config recording) is covered by the new verifier, but a future reader should treat the three identifiers as unresolved history |
| L-5 raw usage / negative counts / empty-run attribution | **Fixed** |
| "the gate refusing all 16 specs right now is the correct behaviour" | Still correct *until* certification, and that is exactly what the new verifier enforces. After certification the gate passes for the certified commit only |

**0 paid LLM calls and 0 Pipeline runs were made in this round either.**
