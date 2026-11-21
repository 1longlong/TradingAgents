# Personal Contribution Documentation Audit — V2 to PR #8

**Auditor:** DeepSeek Harness (AI-assisted evidence review)
**Date:** 2026-11-21
**Scope:** WangTianQi's token-observability work, V2/V3 experiments, final
remediation, D1–D9 integration, the two Release merge commits, and PR #8.
**Mode:** read-only audit. Only this file was created. No product code, existing
document, experiment evidence, Git history, approval state or remote branch was
modified.

---

## A. Executive summary

**Verdict:** the personal contribution is technically substantial and its core
evidence is traceable, but the final documentation is **not historically
complete or internally current**. The most serious problems are stale status
claims left over from the pre-integration state (D7–D9 "unresolved", full suite
"NOT_RUN", Ruff "244/blocking", AUL "105") and the complete absence of the final
delivery record (two merge commits, upload, PR #8 and its seven green checks).
No fabricated human approval or forged signature was found.

| Count | Value |
|---|---|
| Files reviewed (docs, transcripts, governance, experiment summaries, Git/PR metadata) | 46 |
| Substantive findings | 23 |
| CRITICAL | 0 |
| HIGH | 9 |
| MEDIUM | 8 |
| LOW | 6 |
| Suspected missing-content items | 9 |
| Contradictions / outdated statements | 11 |
| Unsupported or unverifiable current claims | 4 |
| Primary evidence gaps | V2/V3 raw telemetry absent; no paid-run authorization artefact; AI-only audits; missing REC-09 artefact |

**Most important submission risks**

1. Evaluators reading `README.md`/`Report.md` are told the integration is
   unfinished and the full suite was never run — both false as of `94755cf`.
2. The final delivery (PR #8 `OPEN`, `MERGEABLE`, 7/7 checks green, not merged)
   is not documented anywhere in the deliverables.
3. AUL and Ruff numbers in the current-state documents are stale, which makes the
   evidence index look inconsistent with the actual tree.
4. Historical V2/V3 token totals cannot be independently re-derived from the
   delivered tree because raw telemetry is git-ignored/absent (properly disclosed
   in the transcript but not consistently in the report).

---

## B. Document inventory (material files reviewed)

| File | Purpose | Coverage | Issues | Audit status |
|---|---|---|---|---|
| `Report.md` | Main integrated report | Full | Stale D7–D9/NOT_RUN; AUL range | Reviewed |
| `transcripts/60726054-WangTianQi.md` | Student AI-use transcript | Full (20 entries) | One stale NOT_RUN line; signature pending | Reviewed |
| `transcripts/README.md` | Transcript rules | Full | None material | Reviewed |
| `README.md` | Project/integration overview | Relevant sections | Stale merge/NOT_RUN/AUL 105 | Reviewed |
| `docs/ai-use-log.yaml` | Canonical AUL log | Count/IDs | 108 records, correct | Reviewed |
| `docs/ai-use-session-audit.md` | Session/ID mapping | Full | Stale "full suite NOT_RUN" gap text | Reviewed |
| `docs/review-memo.md` | Reviews + REC.01–10 | Full | V3 summary omits invalid/env counts; AI assessments added | Reviewed |
| `docs/bug-diary.md` | BUG-001–018 | Full | No material contradiction found | Reviewed |
| `docs/debt-register.md` | DEBT-001–055 | Full | DEBT-052/053/054 correctly open | Reviewed |
| `docs/architecture/adr/001–019` | Decisions | All 19 files | ADR-012 vs ADR-019 corrected | Reviewed |
| `docs/architecture/evaluation-logbook.md` | Execution history | Relevant entries | Historical counts only; current run absent | Reviewed |
| `docs/architecture/invariants.md` | INV register | Full | None material | Reviewed |
| `docs/architecture/trace-matrix.md` | Requirement traceability | Relevant rows | FR-HAR-001/NFR-VER-001 stale NOT_RUN | Reviewed |
| `docs/req/requirements.yaml` | 52 requirements | Schema/completeness | 52 unique, schema valid | Reviewed |
| `docs/code-governance/verification-constraints.md` | Verification rules | Relevant rows | VC-01/VC-03/VC-11 stale | Reviewed |
| `token_benchmarks/.../v2/TEST_RESULTS.md` | V2 evidence | Summary | No raw token ledger in tree | Reviewed |
| `token_benchmarks/.../v3/TEST_RESULTS.md` | V3 evidence | Summary | Pre-fix; raw telemetry absent | Reviewed |
| `token_benchmarks/final_remediation_20261116/` | Remediation evidence | Summary/tests | No post-fix paid rerun | Reviewed |
| `token_benchmarks/**/MANIFEST.sha256` | Freeze integrity | Checked | Intact; audit scripts hashed | Reviewed |
| `docs/audits/PERSONAL_V2_TO_PR8_DOCUMENTATION_AUDIT.md` | This audit | — | New | Created |

Git/remote evidence: branch `integrate/token-into-release-20261121` at
`94755cfec821df88a7cfb901ce4ce00e065d1dd2`; parents `702d957` and `9a08e08`;
`origin/release = 9a08e08`; PR #8 `OPEN`, `MERGEABLE`, head branch matches,
7/7 checks `SUCCESS`; branch is ahead 76, behind 0.

---

## C. Reconstructed timeline (evidence-first)

| Phase | Event | Evidence |
|---|---|---|
| Pre-V2 | RC1/CAND-01 design; Single-Pass and Batch-Macro switches; Finnhub-only decision; pre-V2 audits | ADR-013–018, `docs/bug-diary.md`, review-memo entries, `AUL-074`–`AUL-095` |
| V2 | Protocol, switch matrix, config hash/freeze; C3 rounds 2–5; self-tamper finding; halt before paid calls; re-freeze; V2 batch | v2 protocol/freeze/`TEST_RESULTS.md`, REC-01–05, transcript Entry 17 |
| V3 | System-component attribution, telemetry schema, memory isolation; freeze `e3b5cca`; audits; 2×2 paid batch; reattempts | v3 protocol/manifests/`TEST_RESULTS.md`, AUDIT A/B/C, REC-06, transcript Entry 18 |
| Remediation | R12 retry, DSML sanitisation, `tool_rounds`, one-round-per-batch, probes/mutation tests | `final_remediation_20261116/`, `tests/test_final_remediation.py`, REC-07 |
| Course docs | D1–D9 requirements/ADR/AUL/risk/debt reconciliation | `docs/req`, `docs/architecture`, `docs/ai-use-log.yaml` |
| Integration | Old-base merge `702d957`; new Release `9a08e08` merge `f2220a6`; docs commit `94755cf` | `git log`, parents, PR #8 |
| Delivery | Upload branch; PR #8 open; 7 CI checks green; **not merged** | `git ls-remote`, `gh pr view 8` |

V2/V3 figures in the narrative are **recorded claims**, not numbers this audit
recomputed: the delivered tree does not carry the raw provider telemetry
(git-ignored/absent). They are consistently quoted as V2 7 attempts / 5 valid /
1 env-failed / 1 invalid / 1,463,791 tokens; V3 18 attempts / 16 Run IDs / 15
valid / 1 env-failed / 2 invalid / 3,067,669 tokens. Confidence: **PROBABLE**
(consistent across report, transcript and review memo; primary data unavailable).

---

## D. Master findings register

| ID | Severity | Category | Phase | File:line | Current claim / missing content | Evidence | Proposed correction | Confidence |
|---|---|---|---|---|---|---|---|---|
| DOC-AUD-001 | HIGH | Outdated status | Integration | `README.md:416-422` | Says merge is in progress, uncommitted, unpushed, D1–D9 "staged" | `git log`: `702d957`, `f2220a6`, `94755cf`; PR #8 exists | Replace with current integration/delivery status; keep historical snapshot under a dated heading | CONFIRMED |
| DOC-AUD-002 | HIGH | Outdated status | Integration | `Report.md:353-354` | "full suite is NOT_RUN while unrelated D7–D9 conflicts remain" | Full local suite 5,132 passed; no conflicts | State current green run and date; retain historical NOT_RUN as history | CONFIRMED |
| DOC-AUD-003 | HIGH | Outdated status | Integration | `README.md:553-554` | "merged-tree full suite is NOT_RUN" | 5,132 passed / 3 skipped at `94755cf` | Update current result; keep pre-integration value labelled | CONFIRMED |
| DOC-AUD-004 | HIGH | Outdated status | Docs | `docs/code-governance/verification-constraints.md:142,189,377,383` | Full suite `NOT_RUN`; Ruff 233/244; "CI gates submission files only" | Current: suite green; `ruff check .` passes; full-repo gate with 12 per-file exceptions | Update VC-01/VC-03/VC-11 and the summary table | CONFIRMED |
| DOC-AUD-005 | HIGH | Outdated status | Docs | `docs/architecture/trace-matrix.md:246,251,374` | FR-HAR-001 and NFR-VER-001 `NOT_RUN`; "D2–D9 unmerged" | `tests/test_run_token_benchmark_sh.py` and full suite pass now | Update rows; keep historical values labelled | CONFIRMED |
| DOC-AUD-006 | HIGH | Outdated status | Docs | `docs/ai-use-session-audit.md:456` | "Full suite NOT_RUN ... conflicts resolved" | Suite green; conflicts resolved | Update D1 gap statement | CONFIRMED |
| DOC-AUD-007 | HIGH | Missing delivery record | PR/delivery | whole repo | No statement that branch was pushed, PR #8 opened, 7 checks green, or that it is **not merged** | `gh pr view 8`: OPEN/MERGEABLE, base `release`, 7 SUCCESS | Add a dated delivery section to README/Report | CONFIRMED |
| DOC-AUD-008 | HIGH | Incorrect count/range | AI use | `README.md:586`; `Report.md:827` | "105 integrated AI-use records"; `AUL-074`–`AUL-105` | `docs/ai-use-log.yaml` has 108 unique; PR #5 uses 071–073; personal repaired trio is 106–108 | Update to 108 and `AUL-074`–`AUL-108`, noting 071–073 are Release records | CONFIRMED |
| DOC-AUD-009 | HIGH | Outdated status | Transcript | `transcripts/60726054-WangTianQi.md:503` | "merged-tree full suite is NOT_RUN (`DEBT-054`)" | Suite green; DEBT-054 superseded for current tree | Add dated current result; preserve historical statement | CONFIRMED |
| DOC-AUD-010 | MEDIUM | Incomplete result disclosure | V3 | `docs/review-memo.md:1335` | V3 summarized as "18 attempts/15 valid/3,067,669" without 1 env-failed and 2 invalid | README/transcript include those categories | Add the missing categories to the summary row | CONFIRMED |
| DOC-AUD-011 | MEDIUM | Unverifiable current claim | V2/V3 | README/Report/transcript totals | Token totals quoted as fact | Raw telemetry absent; transcript says git-ignored | Add "archived ledger value; raw telemetry not in delivered tree" caveat where totals appear | CONFIRMED |
| DOC-AUD-012 | MEDIUM | Missing current verification | Integration | `docs/architecture/evaluation-logbook.md` | No entry for the final local 5,132-run or PR #8 CI | Run exists; PR checks exist | Add dated integration/delivery entry | CONFIRMED |
| DOC-AUD-013 | MEDIUM | Missing policy record | Integration | `pyproject.toml:76-88`; docs | 12 per-file Ruff exceptions exist only in config | Config diff; manifest hashes | Document the exception rationale and exact protected paths in README/Report | CONFIRMED |
| DOC-AUD-014 | MEDIUM | Missing delivery metadata | PR/delivery | — | No PR number/base/head/CI result recorded | `gh pr view 8` | Add PR #8 metadata and "open, not merged" status | CONFIRMED |
| DOC-AUD-015 | MEDIUM | Incomplete historical record | V2 | V2 summary | Exact invalid-run identity and environment failure are summarized but not itemised in the report | v2 results/transcript | Add a short V2 run-disposition table | PROBABLE |
| DOC-AUD-016 | MEDIUM | Incomplete historical record | V3 | V3 summary | 2 invalid runs (R12a01/a02, provider 400) and 1 env-failed are not itemised in the report | transcript Entry 18; v3 results | Add V3 run-disposition table | PROBABLE |
| DOC-AUD-017 | MEDIUM | Evidence gap not surfaced | V2/V3 | Report limitations | No explicit "no raw ledger in tree" sentence in Report | transcript known-gaps | Add the caveat to Report limitations | CONFIRMED |
| DOC-AUD-018 | LOW | Contradictory wording | Integration | `Report.md:781-785` | Says protected conflicts remain and validators fail, then says "integrated D7–D9 content" | Current tree clean; validators pass | Rewrite as historical or delete stale bullet | CONFIRMED |
| DOC-AUD-019 | LOW | Stale statement | Docs | `docs/code-governance/verification-constraints.md:383` | Ruff baseline numbers only | Current 0 findings with exceptions | Add current line; keep historical baseline | CONFIRMED |
| DOC-AUD-020 | LOW | Missing PR #5 CI context | Delivery | — | PR #5 checks (3,799/9 per version) quoted without noting the merged-tree PR #8 run | PR #8 7/7 checks | Distinguish PR #5 and PR #8 evidence | CONFIRMED |
| DOC-AUD-021 | LOW | Pending status clarity | Human | Report §7; transcript | AI-assisted drafts and unsigned transcript correctly marked | Text | Keep pending; add a one-line checklist of remaining human items | CONFIRMED |
| DOC-AUD-022 | LOW | Missing audit-trail pointer | Governance | README/docs index | This audit file is not indexed | New file | Add to the artifact index when corrections are made | CONFIRMED |
| DOC-AUD-023 | LOW | Wording | V2/V3 | Report limitations | "no paid rerun after final remediation" is present but easy to miss | README/DEBT | Keep; cross-reference DEBT-046/052 | CONFIRMED |

---

## E. Missing content by phase

### V2
1. **Run disposition table** — the exact 7 attempts (5 valid, 1 env-failed
   R05a01, 1 invalid) and the 1,463,791-token ledger are in the transcript but not
   the report; the raw run directories are the stronger evidence.
2. **Authorization record** — no dated paid-run authorization artefact exists
   (`DEBT-052`). This is disclosed, but the V2 section should state it explicitly.
3. **Self-tamper finding** — documented in REC-01–04 and bug diary, but not
   summarised in the report's V2 narrative.

### V3
4. **Run disposition table** — 18 attempts / 16 Run IDs / 15 valid / 1 env-failed
   / 2 invalid; the review-memo summary omits the invalid/env counts.
5. **Attribution schema evolution** — ADR-013/FR-OBS explains it; the report
   should connect the schema change to the V2 reflector blind spot.
6. **Memory isolation evidence** — 18/18 baseline unchanged; present in option
   ledger but only briefly in the report.

### Final remediation
7. **What was not re-measured** — R12 retry, DSML sanitisation and `tool_rounds`
   fixes have offline tests/probes, but no post-fix paid benchmark. This is
   stated in README/DEBT-046; the report should say it in the remediation section.

### Release integration / delivery
8. **Two merge commits and upload** — `702d957`, `f2220a6`, `94755cf`, branch push,
   PR #8, 7/7 CI checks, not merged. Absent from all deliverables.
9. **Ruff policy** — full-repo gate is now green with 12 evidence-preserving
   per-file exceptions; the docs still describe a red 244-finding gate.

---

## F. Cross-document contradictions

| Topic | One document says | Another says | Evidence supports |
|---|---|---|---|
| Merge state | README "in progress/unpushed"; Report "D7–D9 conflicts remain" | Git/PR: merged, pushed, PR #8 open | Current integration state |
| Full suite | README/Report/trace/verification "NOT_RUN" | Local run: 5,132 passed | Green current run; historical NOT_RUN only for pre-integration |
| Ruff | verification-constraints 233/244, submission-only gate | Current `ruff check .` passes | Current 0 with 12 exceptions |
| AUL count | README 105; Report range ends 105 | Log 108; PR #5 071–073; personal repaired 106–108 | 108 |
| V3 dispositions | review-memo omits invalid/env | README/transcript include | Full disposition 15/1/2 |
| PR state | docs silent | PR #8 OPEN/MERGEABLE/7 checks, not merged | Open, unmerged |

---

## G. Evidence and provenance gaps

- **Raw V2/V3 telemetry** is not in the delivered tree (git-ignored); token totals
  are archived ledger values, not recomputable here. `NOT_VERIFIED` for
  independent recomputation.
- **No formal paid-run authorization artefact** (`DEBT-052`); the V2/V3 prose
  records human authorization but the dated document is absent.
- **AI-only audits** (REC-01–07, 10) are not independent human reviews; now
  explicitly recorded as AI evidence checks.
- **REC-09** has no committed early-review artefact — `INSUFFICIENT_EVIDENCE`.
- **Commit authors** `WTQ`, `Plan C3`, `C3 Engine`, `t` remain unresolved
  (`DEBT-053`); no human identity is inferred.
- **Post-remediation paid performance** was never re-measured; offline tests do
  not replace it (`DEBT-046`).
- **PR #8 CI** is green but does not certify historical completeness or the
  correctness of the V2/V3 narrative.

---

## H. Recommended changes

### 1. Automatically correctable factual errors
- `README.md:416-422`, `README.md:553-554`, `README.md:586`: current merge,
  upload, PR #8, suite 5,132 and AUL 108.
- `Report.md:353-354`, `Report.md:781-785`, `Report.md:827`: current suite,
  resolved conflicts, AUL 108/range 074–108.
- `docs/code-governance/verification-constraints.md:142,189,377,383`: current
  VC-01 (5,132/3), VC-03 (0 with 12 exceptions), VC-11 pass.
- `docs/architecture/trace-matrix.md:246,251,374`: current test status.
- `docs/ai-use-session-audit.md:456`: current suite/conflict status.
- `transcripts/60726054-WangTianQi.md:503`: add dated current result, keep
  historical NOT_RUN.

### 2. Missing content reconstructable from evidence
- Add a **Delivery** section to README/Report: branch, commits `702d957`,
  `f2220a6`, `94755cf`, upload URL, PR #8 base/head, 7/7 checks, **not merged**.
- Add **V2/V3 run-disposition tables** (attempts, valid, env-failed, invalid,
  tokens, ledger source).
- Document the **12 per-file Ruff exceptions** and why sealed evidence is not
  rewritten.
- Add the **raw-telemetry absence** caveat to Report limitations.
- Index this audit in README/docs.

### 3. Human-only confirmations
- Student confirmation of the four AI-assisted §7 paragraphs.
- Transcript signature/date.
- REC-01–10 acceptance.
- ADR/risk/debt confirmations.
- Paid-run authorization artefact or explicit "none exists" statement.
- Commit-author resolution.

### 4. Evidence gaps that must remain disclosed
- No raw V2/V3 telemetry in the tree.
- No post-remediation paid rerun.
- REC-09 insufficient evidence.
- PR #8 open/unmerged; CI green ≠ historical completeness.

---

## I. Top priorities

1. DOC-AUD-001 — stale README integration/delivery status.
2. DOC-AUD-007/014 — missing PR #8 delivery record and CI result.
3. DOC-AUD-002/003 — stale NOT_RUN in Report/README.
4. DOC-AUD-004/005/006 — stale NOT_RUN/Ruff rows in governance docs.
5. DOC-AUD-008 — AUL 105 vs 108 and 074–105 vs 074–108.
6. DOC-AUD-009 — stale transcript NOT_RUN line.
7. DOC-AUD-013 — undocumented 12-file Ruff exception.
8. DOC-AUD-010/016 — V3 disposition omission in review-memo.
9. DOC-AUD-011/017 — raw-telemetry caveat not in Report.
10. DOC-AUD-012 — no final local/CI entry in logbook.
11. DOC-AUD-015 — V2 run disposition not tabulated.
12. DOC-AUD-018 — contradictory stale "protected conflicts" bullet.
13. DOC-AUD-019 — Ruff baseline line only.
14. DOC-AUD-020 — PR #5 vs PR #8 CI distinction.
15. DOC-AUD-021/022 — human checklist/audit index.

(The remaining findings are lower-value wording or completeness items.)

---

## J. Coverage and limitations

Reviewed: `Report.md`, transcript (20 entries), README, AUL log/session audit,
review memo, bug diary, debt register, all 19 ADRs, logbook, invariants, trace
matrix, requirements, verification constraints, v2/v3/final-remediation
`TEST_RESULTS.md` and manifests, Git history/parents, remote refs, PR #8 metadata
and check rollup. Not reviewed: full raw provider telemetry (absent), all 509
delegated OpenCode sessions and 36 dsh streams (only aggregates/AUL records),
GitHub check logs beyond conclusions, and any uncommitted local session context.

This audit is therefore **not exhaustive over all historical sessions**; it is
exhaustive over the accessible delivered evidence and the current Git/PR state.

---

## K. Remediation tracking (2026-11-21)

Original findings above are preserved. Status vocabulary: `FIXED`,
`ALREADY_CORRECT`, `HISTORICAL_CONTEXT_PRESERVED`, `BLOCKED_HUMAN_ACTION`,
`NOT_VERIFIED`.

| ID | Status | Changed file / section | Supporting evidence | Remaining limitation |
|---|---|---|---|---|
| DOC-AUD-001 | `FIXED` | `README.md` “Current integration status” | Git commits, PR #8 | None |
| DOC-AUD-002 | `FIXED` | `Report.md` limitations paragraph | Local suite 5,132 | Historical `NOT_RUN` retained as history |
| DOC-AUD-003 | `FIXED` | `README.md` results/limitations | Local suite 5,132 | None |
| DOC-AUD-004 | `FIXED` | `docs/code-governance/verification-constraints.md` VC-01/VC-03/VC-11 | Current suite/Ruff/validators | Historical 233/244 retained |
| DOC-AUD-005 | `FIXED` | `docs/architecture/trace-matrix.md` FR-HAR-001/NFR-VER-001 | Final suite | Historical note retained |
| DOC-AUD-006 | `FIXED` | `docs/ai-use-session-audit.md` D1 gap note | Final suite | Historical D1 state retained |
| DOC-AUD-007 | `FIXED` | `README.md`, `Report.md` delivery sections | PR #8 metadata/checks | PR not merged |
| DOC-AUD-008 | `FIXED` | `README.md`, `Report.md` | `ai-use-log.yaml` 108 unique | None |
| DOC-AUD-009 | `FIXED` | transcript Entry 20 | Local suite | Signature still pending |
| DOC-AUD-010 | `FIXED` | `docs/review-memo.md` V2/V3 chronology | README/transcript | None |
| DOC-AUD-011 | `FIXED` | `Report.md` V2/V3 evidence table | Transcript known-gaps | Raw telemetry still absent |
| DOC-AUD-012 | `FIXED` | `docs/architecture/evaluation-logbook.md` new entry | Local run + PR #8 | None |
| DOC-AUD-013 | `FIXED` | `README.md`, `Report.md` delivery | `pyproject.toml` 12 entries | Exact paths listed in preflight reports |
| DOC-AUD-014 | `FIXED` | `README.md`, `Report.md`, logbook | `gh pr view 8` | None |
| DOC-AUD-015 | `NOT_VERIFIED` | V2 table identifies counts but not the invalid run ID | v2 results/transcript | Invalid-attempt identity not established from primary evidence |
| DOC-AUD-016 | `FIXED` | `Report.md` V3 table | Transcript/REC-06 | None |
| DOC-AUD-017 | `FIXED` | `Report.md` evidence table caveat | Transcript | None |
| DOC-AUD-018 | `FIXED` | `Report.md` D7–D9/delivery bullet | Git/PR | None |
| DOC-AUD-019 | `FIXED` | `verification-constraints.md` Ruff row | Current `ruff check .` | Historical baseline retained |
| DOC-AUD-020 | `FIXED` | `Report.md` delivery section | PR #5 vs PR #8 | None |
| DOC-AUD-021 | `FIXED` | `Report.md` §7/§8, transcript, README, review memo | Student reviewed/confirmed documentation 2026-11-21 | Formal signature/REC acceptance still pending |
| DOC-AUD-022 | `FIXED` | `README.md` artifact index | This file | None |
| DOC-AUD-023 | `FIXED` | `Report.md` V2/V3 evidence table | `DEBT-046`, `DEBT-052` | No paid rerun |
