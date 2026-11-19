# Review and Audit Memo — TradingAgents CAND-01 / Token Observability

Status of this memo: **course deliverable, written 2026-11-19 from committed
evidence**. It records reviews that actually happened; it is not itself a review.

> **NO HUMAN SIGN-OFF YET.**
> Every review below was performed by an AI subagent (separate context, read-only
> worktree) or by an offline test command. The audit reports were written by AI
> agents and committed by the `C3 Engine` author identity. No human has reviewed,
> approved, or signed off on any record in this memo.

## Sign-off register

| Record | Subject | Reviewer type | Sign-off |
| --- | --- | --- | --- |
| REC-01 | C3 apparatus audit, round 2 | AI subagent (A/B/C) | `PENDING_HUMAN_CONFIRMATION` |
| REC-02 | C3 apparatus audit, round 3 | AI subagent (B/C) | `PENDING_HUMAN_CONFIRMATION` |
| REC-03 | C3 apparatus audit, round 4 | AI subagent (A/B) | `PENDING_HUMAN_CONFIRMATION` |
| REC-04 | C3 apparatus audit, round 5 | AI subagent (A/B/C) | `PENDING_HUMAN_CONFIRMATION` |
| REC-05 | V2 final-freeze audit, rounds 2/3/3b | AI subagent (A/B/C) | `PENDING_HUMAN_CONFIRMATION` |
| REC-06 | V3 audit A/B/C | AI subagent (A/B/C) | `PENDING_HUMAN_CONFIRMATION` |
| REC-07 | Final-remediation audit A/B/C | AI subagent (A/B/C) | `PENDING_HUMAN_CONFIRMATION` |
| REC-08 | Full-suite offline verification | offline test | `PENDING_HUMAN_CONFIRMATION` |

Resolution rule used below: a record is `FIXED` only when a later commit and a
named test/command exist; otherwise the finding is marked `NOT_VERIFIED`.

---

## REC-01 — C3 apparatus audit, round 2 (pre-paid candidate)

- **Date:** 2026-11-15 evening; fix commits `24d488d` (21:44), `4eaf8cc`
  (22:13) and `538b2b8` (22:16). The exact audit start time is `NOT_VERIFIED`.
- **Reviewer type:** AI subagents Audit A, B and C, each a separate read-only
  session; no human reviewer.
- **Scope:** pre-paid CAND-01 × batch-macro apparatus: news extraction, harness,
  specs, switch delivery and test non-vacuity.
- **Findings:**
  - A-02, Critical: Finnhub truncation kept the **oldest** articles, not the
    newest. On the live NVDA 2026-09-23 sample the newest rendered article was
    2026-09-16, while 63 in-window articles from the final two days were dropped.
  - B-01, Critical: `prepare_run_spec` wrote a child spec with no `switches` and
    no `config_sha256`, so every arm would run `default_config` (the AB arm);
    all 16 labels would have produced one arm.
  - B-02, Critical: `config_sha256` was never recomputed, so a spec with
    `"0"*64` — or one edited after registration — was accepted.
  - B-03 (blocking): the 16 `spec.json` edits invalidated `MANIFEST.sha256` and
    the per-run `spec_body_sha256`; both were regenerated and verified 94/94.
  - C-01 (blocking): the gate recomputed the spec hash but compared no shared
    field, so a tampered `deep_model` passed.
  - Environment/safety (blocking): the secrets file named on the command line
    lost to the ambient environment; a probe was observed dialling the real paid
    endpoint for 120 s before it failed fast.
  - A-02b (severity not retained): truncation was not disclosed to the report
    reader (`4eaf8cc`).
  - Audit-B round-2 finding (severity not retained; non-vacuity): the rehearsal
    path could not fail, so a green rehearsal proved nothing (`538b2b8`).
- **Fix:** `24d488d` (A-02/B-01/B-02/B-03/C-01 and env precedence), `4eaf8cc`
  (disclosure), `538b2b8` (failing rehearsal).
- **Verification:** `PREFLIGHT_REPORT.md` 16-condition list; mutation log
  `logs/mutation_tests.txt`; final confirmation run 1,990 passed / 2 failed /
  2 skipped / 319 subtests (`logs/final_confirmation.txt`).
- **Evidence:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/PREFLIGHT_REPORT.md`,
  `.../logs/final_confirmation.txt`, `.../logs/mutation_tests.txt`, commits
  `24d488d`, `4eaf8cc`, `538b2b8`.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

## REC-02 — C3 apparatus audit, round 3

- **Date:** 2026-11-15; `41f6d90` (22:52, Audit B) and `97629cd` (23:02,
  Audit C). Both audits returned `NOT_READY` before the fixes.
- **Reviewer type:** AI subagents Audit B and C (separate read-only sessions).
- **Scope:** harness/spec reproduction, arm anchoring, usage accounting, budget
  wiring and safety.
- **Findings:** B's findings were blocking; C recorded two blocking items
  (C-02, C-08) and four further findings. All were fixed this round.
  - B-03 (blocking): `--check` treated `git_head_commit`/`git_branch` as stable, so it
    failed on every clean checkout that was not the registration commit.
  - B-10/B-11 (blocking): recomputing `config_sha256` proved only self-agreement; the arm
    was not anchored to the tracked `SWITCH_MATRIX.csv`, so an in-place rehash,
    a directory rename, or a rename plus matrix edit were accepted.
  - B-06 (blocking): a copy of `R01_NVDA_C0` in another directory carried the same name,
    switches and hash, and could have doubled one arm's weight.
  - B-07 (blocking): `_cmd_measure` wrote `code_state.json` before rehearsal, so a refused
    dry run left a state file behind.
  - C-02 (blocking): the delivered `specs/*/code_state.json` still named RC1 with a bare
    `git_working_tree_dirty: true`, so the shipped evidence read as generated
    from unfrozen code.
  - C-08 (blocking): a spec-only attempt directory was not counted as occupied, so the next
    attempt overwrote it.
  - C-04r (further finding; severity not retained): the budget gate tested `UNKNOWN_SPEND` before the cap, so an already
    blown cap did not block; `check()` was never called in production.
  - C-05p (further finding; severity not retained): an unmeasured per-agent total was reported as `0`, identical to a
    genuinely zero-token agent.
- **Fix:** `41f6d90` (B-series), `97629cd` (C-series), with provenance refresh
  `78c0140`/`f5e9051`.
- **Verification:** mutation results in both commit messages (each guard removed
  → exactly one named test red, file restored SHA-256-identical); full suite
  2,071 passed / 2 skipped / 319 subtests; release record sealed at `41f6d90`
  (`6748e76`).
- **Evidence:** commits `41f6d90`, `97629cd`, `6748e76`; `C3_HALT_REPORT_20261115.md`.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

## REC-03 — C3 apparatus audit, round 4

- **Date:** 2026-11-15; `90c7689` (23:18) and `2770789` (23:19). Audit A
  returned `NOT_READY` with **two Critical and three High** findings; Audit B
  returned `NOT_READY` with **one Blocker**.
- **Reviewer type:** AI subagents Audit A and B (separate read-only sessions).
- **Scope:** the spending child's freeze check, frozen-field guards, spec
  provenance and fingerprint coverage.
- **Findings:**
  - H-A, Critical: the child that spends money never checked the freeze; the
    commit/fingerprint checks lived only in the separate gate invocation, so a
    run could start from a dirty checkout that had never passed the gate.
  - H-B, Critical: every `_preflight_gate` guard was `if field is not None`, so
    **deleting** a frozen field skipped its check. A spec with no `switches` ran
    `DEFAULT_CONFIG` (AB) while its directory said C0.
  - H-C, High: the child hashed the registration, not the spec, so tampering
    with `deep_model`, `provider` or `case.trade_date` was accepted.
  - H-D, High: all 16 `code_state.json` claimed to precede the freeze while
    naming a descendant commit — the opposite of the truth.
  - H-E, High: the tree moved during the audit (the self-tamper incident; see
    `INCIDENT_20261115B_self_tamper.md`).
  - B-15, Blocker: the fingerprint covered **zero** registered artefacts
    (`specs/`, `SWITCH_MATRIX.csv`, protocol, manifests were outside it); after
    editing a registration and re-running the writer, the gate printed
    "GATE PASSED".
- **Fix:** `90c7689` (all of the above), `2770789` (provenance/counts/manifest).
- **Verification:** full suite 2,080 passed / 2 skipped / 319 subtests;
  mutations M5–M9 (fingerprint coverage, re-seal guard, mandatory fields, spec
  cross-check, child freeze check) each restored byte-identically.
- **Evidence:** commits `90c7689`, `2770789`; `C3_HALT_REPORT_20261115.md`.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

## REC-04 — C3 apparatus audit, round 5

- **Date:** 2026-11-15, 23:22–23:52 (round-5 fix commits `ff58fdc` 23:37,
  `f556bef` 23:48, `1bba51f` 23:52); halt report `4c00aea` 23:53.
- **Reviewer type:** AI subagents Audit A, B, C (three independent read-only
  sessions).
- **Scope:** the whole 16-run apparatus at the round-5 candidate.
- **Verdicts:** A `NOT_READY`, B `READY` (C1–C5), C `NOT_READY`.
- **Findings:**
  - H-C, Critical: spec `case` sub-fields were accepted without matching the
    registration field by field.
  - R-5-B, High: the freeze designation was circular — the writer could move
    what "the frozen commit" meant.
  - R-5-C, High: the skip-network flag reached a paid child process.
  - R-5-D, Medium: `C3_FROZEN_COMMIT` could replace, not merely restate, the
    frozen reference.
  - B-20 (Med/High), B-21 (Medium), B-23 (Medium), B-26 (Low): missing
    protocol-arm authority test; a guard test ran the real writer; no
    spec/config hash recorded; a silent escape hatch.
  - C-12 (procedural, release blocker): the tree moved under Audit C
    repeatedly. U-1/U-2 remained open at this point.
- **Fix:** `f556bef` (H-C, non-circular designation), `ff58fdc` (B-20/21/23/26),
  `a234f3e` (re-seal), `1bba51f` (R-5-C/R-5-D). U-1/U-2 were deliberately
  deferred to the single re-freeze round.
- **Verification:** 2,099 passed / 2 skipped / 319 subtests at the halt;
  mutation proofs M14–M17 for H-C/R-5-C/R-5-D and M10/M6/M11/M12–M13 for the
  B-series. The round-5 halt report records zero paid calls.
- **Evidence:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/C3_HALT_REPORT_20261115.md`,
  `.../INCIDENT_20261115B_self_tamper.md`, commits `f556bef`, `ff58fdc`,
  `a234f3e`, `1bba51f`.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

## REC-05 — V2 final-freeze audit, rounds 2/3/3b

- **Date:** 2026-11-16, 01:00–01:28 (`af45681` 01:00, `2f2f424` 01:10,
  `e2b0d4a` 01:21, `1406b37` 01:25, freeze `15270b1` 01:28).
- **Reviewer type:** AI subagents Audit A, B, C (separate read-only sessions).
- **Scope:** A — CAND-01, news path, PIT, F1/F2/F3, PF-01; B — harness, 16
  specs, switch delivery, freeze mechanism; C — usage, budget, telemetry,
  freeze integrity, safety.
- **Findings:** C2 Critical (freeze writer emitted prose after the SHA; the gate
  passed the whole string to `git merge-base`, exit 128); H1 High
  (`spec_body_sha256` omitted `registration_dir`/`switches_source`, so 16/16
  recorded digests differed from the released spec); H2 High (docstring falsely
  claimed `FREEZE_HISTORY.jsonl` was tracked and inside the fingerprint); M1
  Medium (no path containment: a rehashed `/tmp` copy passed); L1/L2 Low
  (`--expected-commit` replaced the reference; `--skip-network` still printed
  "safe to spend"); R3-01/R3-02 Low (non-container `llm_call_events` raised;
  unusable budget rendered as "uncapped").
- **Fix:** `2f2f424` (round 2), `e2b0d4a` (round 3), `1406b37` (3b guard), with
  `af45681` as the pre-audit remediation commit.
- **Verification:** round-3 confirmations on `1406b37`: A 469 passed + 142
  subtests, B 335 passed and MANIFEST 103/103, C 334 passed; fingerprints
  identical at start and end. Final audited code `1406b37`; the release-metadata
  commit `15270b1` changes only `c3/`, `MANIFEST.sha256` and the report, all
  excluded from the code fingerprint.
- **Evidence:** `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/INDEPENDENT_AUDIT.md`,
  `.../C3_PROTOCOL_FREEZE.md`, commits `2f2f424`, `e2b0d4a`, `1406b37`,
  `15270b1`.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

## REC-06 — V3 audit A/B/C

- **Date:** 2026-11-16, 12:39–12:52. Candidate `6e66dca` (tree `3119b075`),
  delta re-check `f19d6ed` (tree `5f6640ac`), final `c30700c` (tree
  `6082e2cf`), freeze `e3b5cca`.
- **Reviewer type:** AI subagents Audit A (product code and memory), Audit B
  (harness, protocol, specs), Audit C (usage, telemetry, security); all
  separate read-only sessions.
- **Scope:** V3 protocol: system-component attribution, per-run memory
  isolation, schema 3, 16 registrations and the pre-spend gate.
- **Findings:**
  - R1 (release blocker): worktree dirty during audit.
  - M1 (Medium, A and C): a missing `memory_state.json` still validated
    (fail-open).
  - A1/A2 (Low, A): scope API accepted an agent id as a system component; the
    harness trusted the attribution self-report.
  - M2 (Medium, A and B): baseline provenance was asymmetric (NVDA kept, AAPL
    excluded; NVDA was experiment-generated).
  - M3 (Info): non-registered `measure` specs still share the generic memory log.
  - B blockers on `afa0fc6`: schema 3 rejected; the preflight compared a
    9-field attempt block against a 3-field registration; a stripped spec was
    accepted.
  - B residuals: generic-child bypass (M1), arm matrix hardcoded to V2 (L1),
    `spec_body_sha256` not cross-root stable (L2), endpoint not hashed (L3),
    stale docstring (L4), readiness claimed PASS (L5).
  - C MEDIUM-1/MEDIUM-2: no-state fail-open; U-1 trusted the aggregate flag.
  - C LOW-1..LOW-4: sentinel semantics, per-agent lower bound, stale counts,
    budget fallback merges unreadable/malformed on a non-frozen path.
- **Fix:** `afa0fc6` (attribution + memory isolation), `6e66dca` (schema 3,
  memory bypass), `f19d6ed` (auditor findings), `c30700c` (stripped-spec guard).
- **Verification:** 33 focused tests on `f19d6ed`; 233 focused tests in the
  delta re-check; full suite on the candidate 2,204 passed / 2 pre-existing
  failures / 2 skipped / 319 subtests; final freeze `e3b5cca` (20 checks,
  tag `c3-v3-final-freeze`).
- **Evidence:**
  `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/INDEPENDENT_AUDIT_A.md`,
  `.../INDEPENDENT_AUDIT_B.md`, `.../INDEPENDENT_AUDIT_C.md`,
  `.../REFLECTOR_ATTRIBUTION_AUDIT.md`, `.../MEMORY_ISOLATION_AUDIT.md`,
  commits `afa0fc6`, `6e66dca`, `f19d6ed`, `c30700c`, `e3b5cca`.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

## REC-07 — Final-remediation audit A/B/C

- **Date:** 2026-11-16, 16:17–16:35. Candidate `e0ea1b0` (code fingerprint
  `b8ba9547…`), fixes `e9eed04` (16:28), `51edd41` (16:32), `eaeebab` (16:35),
  final `50b2ca3` (16:35).
- **Reviewer type:** AI subagents Audit A (product logic), Audit B (telemetry and
  experiment infrastructure), Audit C (regression and data safety); all
  separate read-only sessions on the same commit.
- **Scope:** R12 fallback, DSML markup sanitisation, single-pass `tool_rounds`,
  telemetry counters, regression safety.
- **Findings:**
  - A HIGH: the direct prose exit (markup with no tool_calls) was not sanitised.
  - A MEDIUM: the two `structured_llm is None` exits were not sanitised; a mixed
    data+schema turn left an unexecuted schema call dangling; the sanitiser was
    lossy and its field whitelist was too narrow.
  - A LOW: an all-failed round still recorded `status="ok"`.
  - B MEDIUM: `markup_sanitized` was also counted as a structured attempt
    (inflating `structured_attempts`); markup leaked at three exits.
  - B MEDIUM: the committed pre-fix probe lacked the `invoke` shim.
  - C HIGH: the committed probe could not run on the pre-fix tree.
  - C MEDIUM/LOW: the worktree moved during the audit; docs were untracked.
- **Fix:** `8536274` (probe), `e9eed04` (findings), `51edd41` (separate
  counter), `eaeebab` (run-level aggregation and doc alignment).
- **Verification:** `tests/test_final_remediation.py` 20/20; pre-fix probe
  4/4 detected on `e3b5cca`, 0/4 after; mutation 6/6 caught; full suite 2,227
  passed / 4 known failed / 2 skipped / 319 subtests; three audits PASS; no open
  High/Critical. Final code identical between `eaeebab` and `50b2ca3` for
  `tradingagents/` and `scripts/`.
- **Evidence:** `token_benchmarks/final_remediation_20261116/INDEPENDENT_AUDIT.md`,
  `.../REGRESSION_AUDIT.md`, `.../TEST_RESULTS.md`,
  `.../tests/pre_fix_detection_probe.py`, commits `e0ea1b0`, `e9eed04`,
  `51edd41`, `eaeebab`, `50b2ca3`.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

## REC-08 — Full-suite offline verification (this deliverable)

- **Date:** 2026-11-19 (re-executed for this submission).
- **Reviewer type:** offline test command; no human reviewer.
- **Scope:** repository tests at `50b2ca3`, cwd
  `/home/sky/cs5351/TradingAgents/.worktrees/cs5351_submission`, `TZ=UTC`,
  interpreter `.venv/bin/python`.
- **Command/result:** `TZ=UTC .venv/bin/python -m pytest -q` → exit 1 (the four
  known failures): **4 failed, 2,227 passed, 2 skipped, 26 warnings, 319
  subtests passed** (28.22 s), run before the uncommitted D7
  test-isolation patch. With D7, `docs/code-governance/verification-constraints.md`
  VC-01 records 2,233 passed / 2 skipped / 0 failed for the same worktree.
- **Known failures, all classified:** two
  `test_cand01_batch_16run_v3_infra.py` path-pinned tests (V3 specs embed the
  original worktree's absolute paths) and two `test_cli_prefs.py` tests
  (host-level `.env` / `~/.tradingagents/cli_prefs.json` leaks into the
  interactive flow). No new failure was introduced by this deliverable; no
  product file was modified.
- **Evidence:** `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md`
  (recorded run: same 2,227/4/2/319) and this re-run.
- **Human sign-off:** `PENDING_HUMAN_CONFIRMATION`

---

## Unverified / evidence gaps

1. **Rounds 2–4 C3 finding IDs and severities are lost.** The fix commits
   survive, but the full reports do not. `C3_HALT_REPORT_20261115.md` records
   that reports describing B-24, B-27 and A-12 lived in a scratch worktree that
   no longer exists. Those identifiers must not be read as "closed by name".
2. **No post-fix paid run.** R12, DSML and `tool_rounds` fixes were verified by
   offline fixtures, pre-fix probes and mutation only (see REC-07 and DEBT-005).
3. **No human review of any AI-authored audit.** All verdicts above are
   AI-generated; the sign-off register is entirely `PENDING_HUMAN_CONFIRMATION`.
