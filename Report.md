# CS5351 Course Process Report — TradingAgents Token Observability

## 1. Project Introduction
Work on `feature/token-observability`: making LLM token cost attributable, auditable and comparable in a multi-agent trading framework, then testing a single-pass finalisation optimisation. Base `2d17df8`; `rc1` `9948bf8` (2026-11-12); final `50b2ca3` (tag `cand01-v3-final-remediation`; the branch is pushed to `origin/feature/token-observability`, the tags are local-only); 68 commits `rc1..final`, 0 merges.

## 2. Original System and Motivation
TradingAgents (upstream `1longlong/TradingAgents`, release `2d17df8`) runs market/social/news/fundamentals analysts, a bull/bear debate, research manager, trader and risk team over a LangGraph state machine. Token totals existed, but could not answer "which agent spent this, did the provider report it, and is a missing value zero or unmeasured?" Without that, an optimisation cannot be trusted and a paid experiment cannot be audited.

## 3. Objectives
1. Attribute every LLM/tool call to an agent or declared system component; preserve provider usage and never coerce missing data to zero.
2. Register and freeze a 2×2 experiment (single-pass × batch-macro) with pre-spend gates and reproducible specs.
3. Measure token effects on a real model and report direction and uncertainty honestly.
4. Leave a verifiable, reproducible release rather than a demo.
`HUMAN_REFLECTION_REQUIRED`: state which objective motivated the student personally, and why.

## 4. Development Timeline
- 2026-10-19/20: clone upstream, branch from `2d17df8`; three early attempts stashed (reason undocumented, `NOT_VERIFIED`).
- 2026-11-02..14: observability infrastructure (`866133d`), `rc1` freeze; single-pass fixes (`e33ab2c`, `ebe81e3`, `ec629dd`, `72ae0f8`, `7832a90`); news migration and C3 apparatus.
- 2026-11-15: audit rounds 2–5, the self-tamper incident, and a deliberate halt before any paid run.
- 2026-11-16: V2 batch (7 attempts), V3 batch (18 attempts), V3 audits and final remediation (`e0ea1b0`..`50b2ca3`).
`HUMAN_REFLECTION_REQUIRED`: add the student's own account of the decisions behind the halt and the two re-freezes.

## 5. Architecture & Engineering Decisions
- **Attribution:** `ContextVar` scopes (`agent_scoped`, `system_component_scoped`); no scope is `none` and invalidates the run.
- **Measurement:** raw provider usage preserved; missing is `null`, never 0; `run_totals = agents + system_components + unattributed`; telemetry schema 2.
- **Single-pass:** the report schema is bound as a tool; one model turn can finalise the report, removing a second full-context rewrite.
- **Memory:** one immutable baseline, one copy per run, hash-checked before and after; a changed baseline invalidates the run.
- **Freeze/gate:** commit + annotated tag + seal + manifest + append-only designation; the gate re-hashes spec, switches, budget and memory before any spend.

## 6. Meaningful Technical Contributions
- A token accounting layer that rejects bad data (`VALID`/`MISSING`/`INCOMPLETE`/`MISMATCH`), separates agent/system/unattributed buckets and closes the totals.
- A single-pass structured finalisation path with protocol-markup sanitation, plus tests for dangling tool calls, blank reports and mixed turns.
- A reproducible 16-run apparatus: pre-registered specs, config hashes, pre-spend gate, per-run telemetry and manifests.
- Disclosed engineering failures (self-tamper, circular freeze) repaired additively instead of by history rewriting.

## 7. Token Optimization Experiments
2×2 within-run design: **B** = two-call baseline, **AB** = two-call + batch macro, **C0** = single-pass, **CC** = single-pass + batch macro. Sixteen pre-registered runs (NVDA, AAPL, JPM, XOM; case date 2026-09-23; model `CS5351/DeepSeek-V4-Flash`). V2 (freeze `15270b1`) attempted six Run IDs (seven attempts) and exposed unattributed calls and shared memory; V3 (freeze `e3b5cca`) ran the full design with schema 3, system attribution and memory isolation.

## 8. Experimental Results
- V2: 7 attempts / 5 valid / 1 environment failure (R05a01) / 1 invalid (R06, unattributed), 1,463,791 tokens.
- V3: 18 attempts / 15 valid (R02a01 environment; R12a01/R12a02 provider 400), 3,067,669 tokens; 298 LLM and 432 tool calls in valid runs.
- Combined: 25 attempts / 20 valid / 4,531,460 tokens (valid 4,112,224; failed 419,236).
- Single-pass: **−19,589 tokens/run** on the balanced three-block mean (**−8.96%**), all three blocks negative. Batch macro: mean −17,702 but not robust (≈ −695 excluding R01; AAPL +1,612); n=1 per cell, so exploratory only.

## 9. Unsuccessful/Abandoned Approaches
- V1 protocol: its spec generator was lost, so its hashes cannot be reproduced; abandoned and re-registered as V2/V2.1.
- Batch macro as a default optimisation: call count falls 7→1, but token savings are not stable; not recommended.
- CC as a default: cheapest mean, but 2/3 valid runs had degraded DSML reports and 1/3 crashed (R12).
- `exp/cand01-single-pass-finalization` was a dead end (not merged; code re-landed in `b00dd00`).

## 10. Bugs & Root-cause Analysis
Real defects and fixes: PF-01 (`7832a90`), F1/F2/F3 (`e33ab2c`, `ebe81e3`, `ec629dd`, `72ae0f8`), U-1/U-2 (`6057b52`), reflector attribution and memory pollution (`afa0fc6`), R12 provider 400, DSML leakage and `tool_rounds=0` (`e0ea1b0`, follow-ups `e9eed04`), plus worktree self-tamper and circular freeze. Symptoms, causes, tests and status: [docs/bug-diary.md](docs/bug-diary.md).

## 11. AI-assisted Development Workflow
AI coding/audit subagents (DeepSeek Harness) performed much of the implementation and test writing, and wrote all independent audit reports; many commits are authored as `C3 Engine <c3@local>`. Audits were AI-authored, not human review. The student's role, personal verification and approval of AI-generated evidence are `PENDING_HUMAN_CONFIRMATION`; no human sign-off exists yet.

## 12. Verification & Independent Audits
Final suite: **2,227 passed / 4 known failed / 2 skipped / 319 subtests**; 20 new tests in `tests/test_final_remediation.py`; pre-fix probe 4/4 detected; mutation 6/6 caught. Three final audits (A product logic, B telemetry, C regression/safety) returned **PASS** with no open High/Critical. This is the `50b2ca3` count; an uncommitted D7 test-isolation patch now in the worktree yields 2,233 passed / 0 failed. Records: [docs/review-memo.md](docs/review-memo.md).

## 13. Limitations & Technical Debt
n=1 per cell and one model/date; no ground truth or P&L; no post-fix live rerun; V3 specs embed absolute host paths; `cli_prefs` tests leak host `.env`/prefs; single-pass per-tool telemetry is incomplete; summary CSV lacks the markup counter; endpoint is not in the config hash; generic `measure` shares memory. Tracked as DEBT-001..010 in [docs/debt-register.md](docs/debt-register.md).

## 14. Engineering Reflections
`HUMAN_REFLECTION_REQUIRED`: what the student learned about measurement, freezing and audit independence; what they would do differently; whether AI-generated evidence is acceptable as their own submission, and why.
`HUMAN_REFLECTION_REQUIRED`: a candid assessment of the 30-commit freeze/audit overhead — was it worth it for a course project?

## 15. Final Deliverables & Reproducibility
Published code: `50b2ca3` (tree `e3c96b3d…`, code fingerprint `e8905252…`, tag `cand01-v3-final-remediation`) is the final code; this branch adds course-submission deliverables only. This branch adds the full course-deliverable set: `README.md`, `AGENTS.md`, `architecture-blueprint.md`, `Prompt.md`, `Report.md`, `docs/` (req, architecture, code-governance, records), `prompts/`, `src/README.md`, `test/offline|live/README.md`, `transcripts/` (human-pending), and the blocking CI gate. It changes no product code, spec, tag or experiment data.
Reproduce: `TZ=UTC .venv/bin/python -m pytest -q` (the branch's portability/isolation fixes make this hermetic: 2,233 passed, 0 failed, 2 skipped, 319 subtests, also from a .env-free cwd); `scripts/validate/validate_submission.py` checks the 34 required artifacts. Evidence index in `token_benchmarks/final_remediation_20261116/`. All approvals remain `PENDING_HUMAN_CONFIRMATION`.
