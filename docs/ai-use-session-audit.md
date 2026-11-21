# CS5351 D1 — AI-Use Session Audit and Integration Mapping

**Status: `PENDING_HUMAN_REVIEW`.** This document was written by an AI coding
agent (DeepSeek Harness / `dsh`, 2026-11-21) during the D1 documentation
integration. It is a *retrospective reading aid and mapping record*. It is not a
deliverable statement by the student, not an approval, and not a claim that the
underlying sessions were independently audited. Every human-only artifact (the
D5 transcript, the model-integrity statement, the `Report.md` reflections, the
review sign-offs) remains outstanding.

**Revision.** D1 integration revision (2026-11-21), written on top of the
personal worktree's revision 2 audit. Revision 2 recovered the pre-2026-10-20
OpenCode history and added `AIU-023`..`AIU-031`. This revision does **not**
rewrite either personal revision; it records where the personal requirements,
acceptance criteria and AI-use records were integrated into the Release
registry, and it records the D1 validation that was actually executed.

**Purpose.** Answer four questions with evidence instead of assertion:

1. Where did each of the 21 personal requirements go in the Release registry?
2. Where did each of the 64 personal acceptance criteria go?
3. Where did each of the 31 personal AI-use records (`AIU-001`..`AIU-031`) go in
   `docs/ai-use-log.yaml`, and how were its duplicate `AUL` IDs repaired?
4. Which claims are verified, which are not, and what remains for a human?

---

## 1. Sources compared

| Source | Location | Role in D1 | Mutated? |
| --- | --- | --- | --- |
| A — Release | Git merge stage 2 / commit `24adf97` | **Canonical**: structure, IDs, schema, priorities, verification | read-only |
| B — original personal feature | Git merge stage 3 / commit `57b93df` | historical comparison only (17 requirements, pre-V2) | read-only |
| C — latest personal feature | working tree of `/home/sky/cs5351/TradingAgents-token-latest` (uncommitted changes included) | personal 21 requirements / 64 ACs / 31 AIU records | **read-only** (never edited) |

The in-progress merge worktree is
`/home/sky/cs5351/TradingAgents-release` on `integrate/token-into-release-20261121`
(HEAD `24adf97`, MERGE_HEAD `57b93df`, merge base `2d17df8`).

**Recovery note.** The interrupted OpenCode D1 attempt had already produced a
resolved working-tree `docs/req/requirements.yaml`, `docs/req/req-schema.json`
and `docs/architecture/trace-matrix.md` without staging them: 49 requirements
(the 32 Release IDs byte-identical plus 17 new ones) and no conflict markers.
That work was preserved, verified, and completed — not restarted. See §9.

---

## 2. Requirements integration — result

- Original Release requirements retained: **32 / 32** (same IDs, same text, same
  fit criteria and thresholds). Two were extended additively
  (`NFR-PIT-001`, `NFR-SEC-001`) and one new row absorbed an extra personal
  requirement (`FR-ANL-001`).
- Personal requirements mapped: **21 / 21**.
- Personal acceptance criteria mapped: **64 / 64** (the personal worktree has 64,
  not 65; the revision-2 audit's "65" is a miscount and is corrected here).
- New requirement IDs: **20** — `FR-ANL-001..006`, `FR-ANL-008..010`,
  `FR-OBS-001..005`, `FR-HAR-001..003`, `FR-CAM-001`, `NFR-VER-001`,
  `NFR-VER-002`.
- **Final requirement count: 52** (32 + 20). It is neither 48 (all five
  "obvious" overlaps merged) nor 53 (all 21 personal requirements kept
  separately); it is the result of resolving each personal requirement against
  the Release text.
- Schema: `project.schema_version` stays `v1.3` (the Release convention, a
  `vX.Y` value). The only schema changes are narrow and additive: the ID
  pattern gains `ANL|OBS|HAR|CAM` in the three places it appears, and a new
  additive `$defs.retrospective_origin` object records "written after the fact"
  provenance. `NFR-VER-###` needed no pattern change because the existing
  `NFR-[A-Z]+` branch already admits it. No existing enum value, threshold,
  priority or origin meaning changed.

### 2.1 Semantic rule used for each of the 21 decisions

A personal requirement received a new ID unless the Release registry already
stated **the same obligation about the same subject**. If it did, the Release
row was retained and the personal paths, tests and evidence were added to it.
The distinction matters because merging two different enforcement points would
hide a capability, and adding a synonym would inflate the count.

Applied results:

- **Merged into established Release rows**: `FR-007` -> `NFR-PIT-001`
  (point-in-time integrity) and `NFR-003` -> `NFR-SEC-001` (secret safety).
- **Merged into the new pipeline row**: `FR-013` -> `FR-ANL-001`.
- **Kept separate although a related Release row exists**:
  `FR-010` (typed vendor failures) is NOT `NFR-FC-001` (gate/evaluator
  fail-closed); `FR-012` (paid-run spend contract) is NOT `NFR-BUD-001` (debate
  summary reserve); `NFR-001` (usage accounting) is NOT `NFR-AUD-001` (decision
  auditability). Each separation is recorded on the row itself and in §3.
- The former `FR-ANL-007` row created by the interrupted attempt was removed as a
  synonym. Its four source files, three additional tests and evidence line now
  live on `NFR-PIT-001`; nothing was discarded.

---

## 3. Personal requirement -> Release requirement mapping (21 rows)

### 3.1 Personal registry reconciliation (21 rows)

The personal registry (`docs/req/requirements.yaml` on
`feature/token-observability`, 21 requirements / 64 acceptance criteria)
was resolved requirement by requirement against the Release text. `add` =
a new Release-format ID; `merge` = integrated into an established Release
row; `merge-new` = integrated into a new row created for the same
obligation. No personal ID is left unmapped.

| Personal ID | Destination | Decision | Rationale |
| --- | --- | --- | --- | --- |
| FR-001 | FR-ANL-001 | add | No Release row states the agent topology. Personal FR-013 (final decision synthesis) is the same pipeline described from the decision end and is merged into this row. |
| FR-002 | FR-ANL-010 | add | No Release row states vendor-routed data acquisition. NFR-PIT-001 covers date integrity and FR-DQG-004 covers evidence gating, but neither covers acquisition. |
| FR-003 | FR-ANL-003 | add | No Release row states typed analyst reports or the labelled free-text fallback. |
| FR-004 | FR-ANL-004 | add | No Release row states per-agent/per-system-component usage attribution. NFR-AUD-001 audits decisions, not usage. |
| FR-005 | FR-ANL-005 | add | No Release row states Single-Pass structured finalisation. |
| FR-006 | FR-ANL-006 | add | No Release row states the batch-macro switch. |
| FR-007 | NFR-PIT-001 | merge | NFR-PIT-001 already states the same obligation (no future data reaches a decision; every dated path evaluated as of the trade date). Integrated: personal paths, 3 extra test files and a D1 evidence line were added to NFR-PIT-001; no FR-ANL-007 row remains. |
| FR-008 | FR-ANL-008 | add | No Release row states Finnhub-only news provenance; NFR-SEC-001 is about secrets and FR-DQG-004 about gating, not provenance. |
| FR-009 | FR-ANL-009 | add | No Release row states per-run memory isolation from a registered snapshot. |
| FR-010 | FR-ANL-002 | add | Kept separate from NFR-FC-001: NFR-FC-001 governs gate/evaluator fail-closed routing; this row governs the typed vendor/parser failure taxonomy. The shared principle is noted on the row. |
| FR-011 | FR-OBS-002 | add | No Release row states the VALID/MISSING/INCOMPLETE/MISMATCH usage verdict or its consumption by run validity. |
| FR-012 | FR-HAR-003 | add | Not merged into NFR-BUD-001: NFR-BUD-001 enforces the debate summary reserve, while this is the paid-run admission contract (null cap, refusal modes, unknown spend). Same word, different enforcement point. |
| FR-013 | FR-ANL-001 | merge-new | Merged into the new pipeline row: the single final decision, configured debate rounds and the portfolio manager as the only decision emitter are the same obligation as FR-ANL-001. |
| FR-014 | FR-HAR-001 | add | No Release row states a one-command archived measurement harness. |
| FR-015 | FR-OBS-005 | add | No Release row states telemetry selection integrity across repeated attempts. |
| FR-016 | FR-CAM-001 | add | No Release row states the optimisation campaign accept-or-revert loop. |
| NFR-001 | FR-OBS-001 | add | No Release row states event-level token accounting or the null-not-zero rule. Two derived rows (FR-OBS-003, FR-OBS-004) separate tool-round/component accounting and Single-Pass invocation settlement. |
| NFR-002 | FR-HAR-002 | add | No Release row states experiment freeze reproducibility. |
| NFR-003 | NFR-SEC-001 | merge | NFR-SEC-001 already states secret safety. Integrated: key-file permissions, no interactive prompt, no-sourcing wrapper and argv hygiene are recorded with their source files and tests on NFR-SEC-001. |
| NFR-004 | NFR-VER-001 | add | No Release row states that the delivered suite and independent audits are the verification of record. NFR-OFF-001 covers network isolation only. |
| NFR-005 | NFR-VER-002 | add | No Release row states the executed-verification (no simulated results) process obligation. |

### 3.2 Personal acceptance-criterion destinations (64 rows)

Every original personal acceptance criterion is listed. "Placement" says
where the criterion lives in the destination row; none was dropped, and a
criterion expressed through a named test is traceable to that file.

| Personal AC | Destination | Placement | Test / evidence |
| --- | --- | --- | --- |
| AC-FR-001-01 | FR-ANL-001 | fit_criterion | `tests/test_analyst_execution.py` |
| AC-FR-001-02 | FR-ANL-001 | fit_criterion | `tests/test_debate_opening.py` |
| AC-FR-001-03 | FR-ANL-001 | fit_criterion | `tests/test_c3_regressions.py` |
| AC-FR-002-01 | FR-ANL-010 | fit_criterion | `tests/test_dataflows_config.py` |
| AC-FR-002-02 | FR-ANL-010 | fit_criterion + evidence | `tests/test_fred.py; tests/test_finnhub_news.py` |
| AC-FR-002-03 | FR-ANL-010 | fit_criterion | `tests/test_vendor_errors.py` |
| AC-FR-003-01 | FR-ANL-003 | fit_criterion | `tests/test_structured_analyst_output.py` |
| AC-FR-003-02 | FR-ANL-003 | fit_criterion | `tests/test_structured_agents.py` |
| AC-FR-003-03 | FR-ANL-003 | fit_criterion | `tests/test_structured_agents.py` |
| AC-FR-004-01 | FR-ANL-004 | fit_criterion | `tests/test_system_attribution.py` |
| AC-FR-004-02 | FR-ANL-004 | fit_criterion | `tests/test_system_attribution.py` |
| AC-FR-004-03 | FR-ANL-004 | fit_criterion | `tests/test_system_attribution.py` |
| AC-FR-005-01 | FR-ANL-005 | fit_criterion | `tests/test_cand01_single_pass_finalization.py` |
| AC-FR-005-02 | FR-ANL-005 | fit_criterion | `tests/test_cand01_single_pass_finalization.py` |
| AC-FR-005-03 | FR-ANL-005 | tests + evidence | `tests/test_final_remediation.py` |
| AC-FR-006-01 | FR-ANL-006 | fit_criterion | `tests/test_macro_batch.py` |
| AC-FR-006-02 | FR-ANL-006 | fit_criterion | `tests/test_macro_batch.py` |
| AC-FR-006-03 | FR-ANL-006 | fit_criterion | `tests/test_switch_consumption.py` |
| AC-FR-007-01 | NFR-PIT-001 | tests + evidence | `tests/test_news_lookahead.py` |
| AC-FR-007-02 | NFR-PIT-001 | tests | `tests/test_tool_date_enforcement.py` |
| AC-FR-007-03 | NFR-PIT-001 | tests | `tests/test_pit_notice.py` |
| AC-FR-008-01 | FR-ANL-008 | fit_criterion | `tests/test_finnhub_only_scope.py` |
| AC-FR-008-02 | FR-ANL-008 | fit_criterion | `tests/test_finnhub_only_scope.py` |
| AC-FR-008-03 | FR-ANL-008 | fit_criterion | `tests/test_finnhub_only_scope.py` |
| AC-FR-009-01 | FR-ANL-009 | fit_criterion | `tests/test_memory_isolation.py` |
| AC-FR-009-02 | FR-ANL-009 | fit_criterion | `tests/test_memory_isolation.py` |
| AC-FR-009-03 | FR-ANL-009 | fit_criterion | `tests/test_memory_isolation.py` |
| AC-FR-010-01 | FR-ANL-002 | fit_criterion | `tests/test_news_error_classification.py` |
| AC-FR-010-02 | FR-ANL-002 | fit_criterion | `tests/test_market_data_validator.py` |
| AC-FR-010-03 | FR-ANL-002 | tests + evidence | `tests/test_c3_regressions.py` |
| AC-FR-011-01 | FR-OBS-002 | fit_criterion | `tests/test_c3_final_freeze.py` |
| AC-FR-011-02 | FR-OBS-002 | fit_criterion | `tests/test_c3_final_freeze.py` |
| AC-FR-011-03 | FR-OBS-002 | fit_criterion | `tests/test_c3_final_freeze.py` |
| AC-FR-012-01 | FR-HAR-003 | fit_criterion | `tests/test_budget_guard.py` |
| AC-FR-012-02 | FR-HAR-003 | fit_criterion | `tests/test_budget_guard.py; tests/test_c3_final_freeze.py` |
| AC-FR-012-03 | FR-HAR-003 | fit_criterion | `tests/test_budget_guard.py` |
| AC-FR-013-01 | FR-ANL-001 | fit_criterion (merged) | `tests/test_debate_opening.py` |
| AC-FR-013-02 | FR-ANL-001 | tests (merged) | `tests/test_structured_agents.py` |
| AC-FR-013-03 | FR-ANL-001 | tests (merged) | `tests/test_reporting.py` |
| AC-FR-014-01 | FR-HAR-001 | fit_criterion | `tests/test_run_token_benchmark_sh.py` |
| AC-FR-014-02 | FR-HAR-001 | fit_criterion | `tests/test_run_token_benchmark_sh.py` |
| AC-FR-014-03 | FR-HAR-001 | fit_criterion | `tests/test_token_benchmark.py` |
| AC-FR-015-01 | FR-OBS-005 | fit_criterion | `tests/test_token_benchmark.py` |
| AC-FR-015-02 | FR-OBS-005 | fit_criterion | `tests/test_token_benchmark.py` |
| AC-FR-015-03 | FR-OBS-005 | fit_criterion | `tests/test_token_benchmark.py` |
| AC-FR-016-01 | FR-CAM-001 | evidence (script) | `scripts/campaign_ablation_round.py` |
| AC-FR-016-02 | FR-CAM-001 | fit_criterion | `tests/test_ablation_switches.py` |
| AC-FR-016-03 | FR-CAM-001 | evidence (report) | `token_benchmarks/baseline_v2/notes.md` |
| AC-NFR-001-01 | FR-OBS-001 | fit_criterion | `tests/test_observability.py` |
| AC-NFR-001-02 | FR-OBS-001 | fit_criterion | `tests/test_observability.py` |
| AC-NFR-001-03 | FR-HAR-001 | fit_criterion (harness half) | `tests/test_token_benchmark.py` |
| AC-NFR-002-01 | FR-HAR-002 | fit_criterion | `tests/test_c3_final_freeze.py` |
| AC-NFR-002-02 | FR-HAR-002 | fit_criterion | `tests/test_cand01_batch_16run_v3_infra.py` |
| AC-NFR-002-03 | FR-HAR-002 | fit_criterion | `tests/test_c3_regressions.py` |
| AC-NFR-002-04 | FR-HAR-002 | evidence (known failure) | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/RUN_READINESS.md` |
| AC-NFR-003-01 | NFR-SEC-001 | tests (integrated) | `tests/test_api_key_env.py` |
| AC-NFR-003-02 | NFR-SEC-001 | tests (integrated) | `tests/test_api_key_env.py` |
| AC-NFR-003-03 | NFR-SEC-001 | tests (integrated) | `tests/test_run_token_benchmark_sh.py` |
| AC-NFR-004-01 | NFR-VER-001 | tests + evidence | `tests/test_final_remediation.py` |
| AC-NFR-004-02 | NFR-VER-001 | evidence (recorded counts) | `token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` |
| AC-NFR-004-03 | NFR-VER-001 | evidence (audits) | `token_benchmarks/final_remediation_20261116/INDEPENDENT_AUDIT.md` |
| AC-NFR-005-01 | NFR-VER-002 | evidence (offline guards) | `tests/conftest.py` |
| AC-NFR-005-02 | NFR-VER-002 | evidence (freeze verifier) | `scripts/c3_verify_final_freeze.py` |
| AC-NFR-005-03 | NFR-VER-002 | evidence (rehearsal paths) | `tests/test_c3_final_freeze.py` |

---

## 4. AIU -> AUL mapping (31 rows)

Every personal AI-use record is preserved as one Release-format `AUL` entry.
No personal entry was judged "truly redundant": round-2 entries
(`AIU-023`..`AIU-031`) explicitly extend round-1 entries rather than repeat
them, and the two correction pairs (`AIU-002`/`AIU-030`,
`AIU-018`/`AIU-029`) must both survive for the correction to stay auditable.
The D1 session itself is recorded last.

| Personal | Final AUL |
| --- | --- |
| AIU-001 | AUL-074 |
| AIU-002 | AUL-075 |
| AIU-003 | AUL-076 |
| AIU-004 | AUL-077 |
| AIU-005 | AUL-078 |
| AIU-006 | AUL-079 |
| AIU-007 | AUL-080 |
| AIU-008 | AUL-081 |
| AIU-009 | AUL-082 |
| AIU-010 | AUL-083 |
| AIU-011 | AUL-084 |
| AIU-012 | AUL-085 |
| AIU-013 | AUL-086 |
| AIU-014 | AUL-087 |
| AIU-015 | AUL-088 |
| AIU-016 | AUL-089 |
| AIU-017 | AUL-090 |
| AIU-018 | AUL-091 |
| AIU-019 | AUL-092 |
| AIU-020 | AUL-093 |
| AIU-021 | AUL-094 |
| AIU-022 | AUL-095 |
| AIU-023 | AUL-096 |
| AIU-024 | AUL-097 |
| AIU-025 | AUL-098 |
| AIU-026 | AUL-099 |
| AIU-027 | AUL-100 |
| AIU-028 | AUL-101 |
| AIU-029 | AUL-102 |
| AIU-030 | AUL-103 |
| AIU-031 | AUL-104 |
| this D1 session (DeepSeek Harness) | `AUL-105` |

`AUL-105` carries `human_review: requested`, not `approved`.

Field mapping used for every record: personal `date` -> `date`; personal
`tool_agent` -> `tool` (coding application only — see §6); personal `phase` is
kept verbatim; personal `scope` + `artifact` + `source` -> `scope`; personal
`human_review: pending` + `approval_status: PENDING_HUMAN_CONFIRMATION` ->
`human_review: pending` plus an explicit `PENDING_HUMAN_CONFIRMATION` sentence in
`outcome`. No personal session ID, commit hash, turn timestamp or artifact path
was dropped: they are in the `scope` field of the corresponding `AUL` entry.

---

## 5. AUL duplicate-ID repair

The Release log contained 73 record occurrences with 70 distinct IDs. `AUL-020`,
`AUL-021` and `AUL-022` each occurred twice. The **later** occurrence (the 46th,
47th and 48th record occurrences in the stage-2 file, all dated 2026-11-11)
was reassigned;
the earlier 2026-11-06 occurrence kept its ID.

| Old occurrence | Distinguishing activity | New ID | Preserved? |
| --- | --- | --- | --- |
| `AUL-020` #2 (46th) | OpenCode implementation: the two confirmed 2026-11-11 live-run defects (origin authority, structured raw usage) under plan/test approval | `AUL-106` | yes — only the ID changed |
| `AUL-021` #2 (47th) | Codex independent OFFLINE verification of Defect-1/Defect-2 metadata replay | `AUL-107` | yes — only the ID changed |
| `AUL-022` #2 (48th) | Codex independent technical review of the repaired tree; tombstone edge | `AUL-108` | yes — only the ID changed |

Deterministic check: the 73 original records were deep-compared against the
stage-2 list. Exactly three records differ, and in each case the only changed
field is `id`. All 73 original `scope` values are present in the final log, and
every non-ID field is identical.

**Final total: 105 record occurrences, 105 distinct IDs** (73 preserved original
occurrences, 31 integrated personal records, 1 D1-session record). The number was
computed, not assumed: grouping was evaluated and rejected for the reasons in §4.

---

## 6. Tool attribution

Two different coding applications were used on this project, and they are not
interchangeable.

- **OpenCode** — sessions in `~/.local/share/opencode/opencode.db`
  (`ses_...` identifiers). Used for the majority of the personal feature work.
- **DeepSeek Harness (`dsh`)** — sessions under
  `~/.dsh/sessions/--home-sky-cs5351-TradingAgents--/`
  (`session-...` identifiers). One root session runs 2026-11-16 00:22 to
  2026-11-20 01:28, plus 36 subagent streams.
- `CS5351/DeepSeek-V4-Flash` and `deepseek-flash` are **model identifiers**.
  They are recorded as models, never as the coding application.

Attribution decisions in the integrated log:

| Personal record | Attribution | Basis |
| --- | --- | --- |
| `AIU-003`, `AIU-019`, `AIU-020`, `AIU-022` | DeepSeek Harness (`dsh`) | the named `session-2f8abda5-...` root session, whose timestamps bracket the commits |
| `AIU-011`..`AIU-017`, `AIU-021`, `AIU-023`..`AIU-028`, `AIU-031` | OpenCode | each cites an OpenCode `ses_...` row |
| `AIU-010`, `AIU-006` | OpenCode, explicitly marked *inferred* | `/tmp/opencode` scratch-worktree paths and freeze-commit context; the reports do not name the runner |
| `AIU-001`, `AIU-002`, `AIU-018` | unresolved git author `WTQ` | no session names `WTQ`; no application is claimed |
| `AIU-005`, `AIU-008` | unresolved git author `C3 Engine` + read-only subagents | no session names `C3 Engine` |
| `AIU-029` | human operator | the content is human turns in transcripts; no application claimed |
| `AIU-030` | OpenCode with git author `t` | `t` is git's default single-character `user.name` inside the Plan C3 session |

**The 2026-11-16 to 2026-11-20 history is not reassigned to OpenCode.** The
OpenCode record has a hard gap over exactly that window (last project session
2026-11-15, next 2026-11-21), while the `dsh` root session covers it and 57 of 70
commits fall inside the gap. Recording those commits as OpenCode would be false.

**Unresolved authorship.** `WTQ` (29 commits) and `C3 Engine` (16 commits) are
git author strings that appear in neither session store. They are preserved as
unresolved, not resolved by inference. The `t` identity is resolved only as "git's
default identity", not as a person.

---

## 7. Human-review status and flagged approvals

- All 31 integrated personal records carry `human_review: pending` and their
  outcome says `PENDING_HUMAN_CONFIRMATION`. The owner's authorization of this
  D1 merge is **not** blanket approval of any historical AI-generated record.
- `AUL-105` (this D1 session) carries `human_review: requested`.
- The Release log's historical review states were preserved verbatim:
  `approved` (21), `requested` (26), `pending` (19), `noted` (4) and four
  free-text states. No approval was revoked.
- **Flagged for human verification, not changed:** every `approved` occurrence
  whose evidence is a transcript turn rather than a dated sign-off. The
  strongest example is the 2026-11-06 group (`AUL-020`/`AUL-021`/`AUL-022`, first
  occurrences) whose scopes say "operator technical review (not human phase
  approval)" while the `human_review` field reads differently for some adjacent
  records. A reviewer should confirm each `approved` value against
  `docs/review-memo.md`; this audit does not silently downgrade them.
- The personal worktree's `docs/review-memo.md`, `Report.md`,
  `docs/architecture/evaluation-logbook.md` and the transcript were **not**
  modified by D1; they remain out of scope and human-pending.

---

## 8. Historical gaps (preserved, not closed)

1. **cwd mismatch.** The authoritative project sessions ran in
   `/home/sky/cs5351/TradingAgents`, not in the personal submission worktree.
   The stores cannot witness edits made to the worktree except for the
   2026-11-21 session.
2. **`~/.dsh` starts 2026-11-16 00:22.** Whether `dsh` was used earlier is
   `NOT_VERIFIED`, not "no".
3. **Delegated sessions were counted, not read.** 509 OpenCode subagent sessions
   and 36 `dsh` subagent streams are attributed to their parent; no claim is made
   that every delegated session was read individually.
4. **Credential material was not inspected**, by policy.
5. **Quoted test counts are session self-reports** (114/1178, 243 news tests,
   1607 passed, 2,227/2,233 full-suite results). They were not re-run here and
   are labelled as self-reports wherever they appear.
6. **Sessions outside the two local stores** (other machines, browser chats) are
   out of reach and are not claimed.
7. **The 2026-11-21 D1 session** is recorded from its own transcript; a
   self-reporting conflict of interest applies to `AUL-105` exactly as it does to
   `AIU-021` and `AIU-031`.

---

## 9. Recovery of the interrupted D1 attempt

Found at startup in `/home/sky/cs5351/TradingAgents-release`:

- branch `integrate/token-into-release-20261121`, HEAD `24adf97`,
  MERGE_HEAD `57b93df`, merge base `2d17df8` — all as expected;
- 33 unmerged paths remained (`git ls-files -u`); the 19 product/test conflicts
  were already resolved and staged;
- the four D1 paths were still **unmerged in the index** (`AA`) but their
  working-tree files were already resolved and contained **no conflict
  markers**;
- `docs/req/requirements.yaml` held 49 requirements (32 Release IDs
  byte-identical, 17 new); `docs/req/req-schema.json` held the narrow namespace
  and `retrospective_origin` extension; `docs/architecture/trace-matrix.md` held
  the 17 D1 rows; `docs/ai-use-log.yaml` was still the untouched Release version;
  `docs/ai-use-session-audit.md` did not exist; no scratch or duplicate files
  were left behind.

Preserved as-is: the 32 Release rows, the 17 new rows, the schema extension and
the D1 trace rows. Completed: the `FR-002` gap (no destination existed), the
five remaining personal-requirement destinations, the `FR-013` merge, the
`FR-007` merge, the two new verification rows, the 64-AC mapping, the
`trace-matrix` reconciliation, the AI-use-log integration and this document.
Corrected: the `docs/req/requirements.yaml` header's "four namespaces" and its
implied 49-row total, and the revision-2 audit's "65 acceptance criteria".

---

## 10. Validation record

Section 11 records the exact commands and their actual results. Nothing there
is claimed that was not executed; everything not run is labelled `NOT_RUN`.

## 11. D1 validation (actual)

### 11.1 Environment

- Interpreter: `/usr/bin/python3` 3.14.4 with PyYAML and jsonschema 4.19.2.
- Test runner: pytest 9.1.1 loaded from the **existing** project virtualenv at
  `/home/sky/cs5351/TradingAgents/.venv/lib/python3.14/site-packages` via
  `PYTHONPATH`. No dependency was installed, no network was used, and that
  worktree was not modified.
- Working directory for every command:
  `/home/sky/cs5351/TradingAgents-release`.
- Environment override: `TZ=UTC` for the pytest runs (project convention).

### 11.2 Commands and actual results

| # | Command | Actual result |
| --- | --- | --- |
| P1 | `pwd; git branch --show-current; git rev-parse HEAD; git rev-parse MERGE_HEAD; git ls-files -u \| wc -l` | branch `integrate/token-into-release-20261121`, HEAD `24adf97`, MERGE_HEAD `57b93df`, 33 unmerged paths — **PASS** (matches the expected state) |
| V1 | `/usr/bin/python3 scripts/validate/validate_requirements.py` | **FAIL (3 errors)** — all three are parse failures of `prompts/prompt_v1.0.yaml`, `prompts/prompt_v1.1.yaml` and `.opencode/permissions.jsonc`, which still contain conflict markers from the in-progress merge (out of D1 scope). Required artifacts 43/43 present; secret scan clean; requirements schema/monotonic checks and product references produced **0 errors** |
| V2 | `/usr/bin/python3 scripts/validate/validate_submission.py` | **FAIL (12 errors)** — 5 from the same three conflicted files and 7 duplicate-ADR-numbering errors (the token branch added `adr/013-provider-usage-observability.md` … `006-structured-fallback-safety.md` beside the Release `adr/001`…`006`). `check_requirements` and `check_trace_matrix` produced **0 errors** |
| V3 | `TZ=UTC PYTHONPATH=".:/home/sky/cs5351/TradingAgents/.venv/lib/python3.14/site-packages" /usr/bin/python3 -m pytest tests/test_governance_scaffold.py -q` | **58 passed, 2 failed** — the 2 failures are `TestJsoncParsing::test_parses_actual_permissions_file` and `TestRequiredArtifactPresence::test_yaml_inventory_parses`, both reading the conflicted files above |
| V4 | same runner, D1-focused selection (`TestMappedTestTraceability`, `TestStableIdPattern`, `TestDispatcherAgainstRealSchema`, `TestSecretScan`, `TestSchemeValidation`, `tests/trading/test_traceability.py`) | **20 passed, 0 failed** (includes the real-jsonschema branch; `test_jsonschema_is_used_when_available` passed, so Draft 2020-12 was in force) |
| V5 | `TZ=UTC PYTHONPATH=… /usr/bin/python3 -m pytest tests/test_submission_compliance.py -q` | **1 failed** — it asserts that the whole submission validator exits 0, and that validator is blocked by the out-of-scope conflicts in V2. The failure cause is the conflict, not a D1 assertion |
| V6 | read-only D1 self-check script (12 assertions, listed in §11.3) | **12 PASS / 0 FAIL** |

### 11.3 D1 self-checks (V6)

| Check | Result | Evidence |
| --- | --- | --- |
| 1. YAML/JSON parsing | **PASS** | `requirements.yaml`, `req-schema.json`, `ai-use-log.yaml` parse; `ai-use-session-audit.md` present |
| 2. Draft 2020-12 requirements schema | **PASS** | `jsonschema` 4.19.2 `Draft202012Validator`: 0 errors |
| 3. Requirement ID uniqueness | **PASS** | 52 requirements, 52 unique IDs |
| 4. Original 32 Release IDs preserved | **PASS** | 32/32 retained; only `NFR-PIT-001` and `NFR-SEC-001` differ, and only in `source_files`/`tests`/`verification_evidence` (additive) |
| 5. Exact 21 personal-requirement mapping | **PASS** | 21/21 personal IDs mapped; every destination resolves to a registry ID |
| 6. All 64 personal acceptance criteria covered | **PASS** | 64/64 AC IDs, 64 unique rows, every destination resolves |
| 7. AUL uniqueness and original history | **PASS** | 108 records, 108 unique after the PR #5 merge; 73 originals preserved; `AUL-020/021/022` occurrence #2 now maps to `AUL-106/107/108`, while the PR #5 Release records use `AUL-071/072/073` |
| 8. All 31 AIU entries mapped | **PASS** | 31/31 map to existing `AUL` IDs (`AUL-074`…`AUL-104`) |
| 9. Traceability to real files | **PASS** | every `source_files` / `design_artifacts` / `tests` / `verification.references` path exists |
| 10. Submission-validator D1 functions | **PASS** | `check_requirements` + `check_trace_matrix`: 0 errors, 0 warnings |
| 11. Governance validator both paths | **PASS** | real-schema and deterministic-subset paths both accept the registry |
| 12. No conflict markers in the 5 D1 documents | **PASS** | 0 markers |

### 11.4 Blocking limitations (out of D1 scope, not worked around)

1. **Conflicted D2–D9 documents.** `prompts/prompt_v1.0.yaml`,
   `prompts/prompt_v1.1.yaml` and `.opencode/permissions.jsonc` still contain
   conflict markers, so the two full validators and two governance tests cannot
   pass in this worktree yet. They are unrelated to D1 and were deliberately not
   touched.
2. **Duplicate ADR numbering.** The merge places the token branch's
   `adr/001`…`006` beside the Release `adr/001`…`006`. Reconciling that requires
   renaming architecture documents and updating their references, which is
   outside the D1 file scope. It is reported as a merge-integration blocker.
3. **Full suite NOT_RUN.** The offline suite needs the D2–D9 conflicts resolved
   and a complete environment; running it now would test conflicted documents.
   No merged-tree green claim is made.
4. **No live run.** No provider, vendor or paid call was made. No token saving or
   performance figure is claimed.

### 11.5 What a reviewer should re-run

```bash
cd /home/sky/cs5351/TradingAgents-release
/usr/bin/python3 scripts/validate/validate_requirements.py
/usr/bin/python3 scripts/validate/validate_submission.py
TZ=UTC PYTHONPATH=".:/home/sky/cs5351/TradingAgents/.venv/lib/python3.14/site-packages" \
  /usr/bin/python3 -m pytest tests/test_governance_scaffold.py tests/trading/test_traceability.py -q
```

Expected once the D2–D9 conflicts are resolved: both validators exit 0 and the
governance suite is green. Until then, the requirement, trace-matrix and
secret-scan checks are the D1 result and they pass.

### 11.6 Status

`PENDING_HUMAN_REVIEW`. Nothing in this document is an approval. The D1
integration produced a Release-compatible, evidence-preserving, validated D1;
it did not create the merge commit and did not run anything paid.
