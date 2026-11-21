# Integrated core and WebUI records

The canonical layout is `src/` and `test/`. The core records below describe the
release data-quality gate, evidence, debate, usage ledger and output guards;
the WebUI records describe the presentation extension over that core. Existing
requirement and invariant IDs remain scoped to their original modules. An
unqualified core ADR number refers to the release ADR with its descriptive
filename; a WebUI ADR number refers to the WebUI ADR with its descriptive
filename. Both sets remain present. Historical approvals retain their original
scope and do not approve this merge or a new feature. Verification results are
historical unless explicitly identified as a merged-tree run.

## Release core

# Evaluation Table — Verification Summary

This document has two parts. **Part I** is the architecture-candidate comparison
(why this architecture was chosen against alternatives and drivers). **Part II**
is the verification-results table. Verification relies on
`docs/architecture/evaluation-logbook.md` for the exact commands and outcomes.
`Re-run` means executed in the current environment; `Supplied` means the outcome
was provided to this task and was not re-run here.

## Part I — Architecture candidate comparison

The selected architecture is described in `architecture-blueprint.md` (two
deterministic components: a Data Quality Gate and an evidence-aware debate
terminator). This comparison evaluates main candidates against the project's
drivers. **No fabricated numeric scores are used**: each cell is a qualitative
judgement tied to a driver, and measured performance is not claimed.

Drivers (D1–D7):

- **D1 Determinism** — same input → same output; offline-verifiable.
- **D2 Fail-closed safety** — missing/error cannot look like a clean normal run.
- **D3 Backward compatibility** — disabled feature reproduces legacy routing.
- **D4 Auditability** — reason codes, policy version, evidence IDs, trace.
- **D5 Budget safety** — never lose the summary report mid-debate.
- **D6 Testability/effort** — provable with offline deterministic tests.
- **D7 Point-in-time integrity** — no look-ahead leakage.

| Candidate | D1 Determinism | D2 Fail-closed | D3 Backward-compat | D4 Auditability | D5 Budget | D6 Effort | D7 PIT | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A. Deterministic gate + rule-based termination (selected)** | Inherent (pure) | Native (exception→blocked) | `enabled=False` retains legacy | Full trace, stable codes | Explicit reserve + pre-call guard | Offline-testable | As-of boundary preserved | **Selected** |
| B. LLM-judged gate / termination | Poor (nondeterministic) | Cannot guarantee | Risky default change | Opaque reasoning | Unbounded cost risk | Cannot regression-test offline | No new risk to PIT | Rejected (violates D1/D2/D4/D6) |
| C. Fixed-round with no gate | Native | No gate → no fail-closed on data quality | N/A (baseline) | Limited (no gate trace) | No reserve → can lose report | Simple | PIT preserved by upstream | Rejected (fails D2/D5; this is the DQG/Dynamic baseline) |
| D. Best-effort accounting, wall-clock only | Native | Partial | Compatible | Partial | Can overspend one call | Testable | Unchanged | Rejected (fails D5 guarantee) |
| E. Relocate code into `src/` to match slide layout | N/A | N/A | Breaks users | N/A | N/A | High (drift risk) | N/A | Rejected (out of scope; mapping retained as exception) |

Selection rationale: Candidate A is the only one that satisfies the determinism,
fail-closed, auditability, and budget guarantees simultaneously while remaining
offline-testable and backward-compatible. The measured evidence for A is the
offline test suite (Part II); **no live-performance advantage is claimed** — the
Phase 4A comparison is scripted fixtures, not a live benchmark.

Known weaknesses of A (honest, not hidden): (i) budget is enforced against
*estimated* usage, and the 2026-11-06 live run showed the estimate exhausted the
time budget before Bear (`DEBT-021`); (ii) an allowlist does not validate a
claim's date semantics (`DEBT-022`); (iii) automatic optional-category adapters
are limited (`DEBT-015`). These are open defects in an otherwise sound
architecture, not reasons to pick B/C/D/E.

## Part II — Verification results

| Area | Command / scope | Result (observed) | Source | Status |
| --- | --- | --- | --- | --- |
| ConflictRecord runtime lifecycle | `pytest test/offline/test_debate_conflicts.py` | 39 passed in 0.53s | Re-run | Pass (expected) |
| Conflict/debate/graph/Stage-2 relevant suite | `pytest` on gate + debate + evidence + conflicts + stage2 multi-category gate + report artifacts + governance tests | 490 passed in 1.82s | Re-run | Pass (expected) |
| Debate-focused subset | `pytest` on gate + debate + evidence tests | 333 passed in 1.00s | Re-run | Pass (expected) |
| Stage-2 relevant suite | `pytest` on gate + debate + evidence + stage2 multi-category gate + report artifacts + governance tests | 442 passed in 1.99s | Re-run | Pass (expected) |
| Stage 2 multi-category gate | `pytest test/offline/test_stage2_multicategory_gate.py` | 26 passed | Re-run | Pass (expected) |
| Stage 2 report artifacts | `pytest test/offline/test_report_artifacts_stage2.py` | 16 passed | Re-run | Pass (expected) |
| OpenCode-related suite | `pytest` (OpenCode-derived scope) | 420 passed | Supplied | Pass (expected) |
| Full offline suite (sandbox) | `pytest -q` | 1275 passed, 1 skipped, 1 deselected, 88 subtests; 3 date-sensitive failures, 1 network-reachability baseline failure | Supplied | Partial |
| Full offline suite (current tree) | `pytest -q` | 1391 passed, 2 skipped, 88 subtests; 3 failed (date-sensitive cache tests) | Re-run | Partial |
| Full offline suite (current tree, Phase 4A) | `pytest test/offline/ -q` | 1432 passed, 2 skipped, 88 subtests; 3 failed (date-sensitive cache tests) | Re-run | Partial |
| Full offline suite (current tree, prior) | `pytest -q` | 1342 passed, 2 skipped, 88 subtests; 4 failed (3 date-sensitive cache tests, 1 network-reachability baseline) | Re-run | Partial |
| Full offline suite (earlier OpenCode env) | `pytest -q` | 1276 passed; 3 date-sensitive failures | Supplied | Partial |
| PIT / look-ahead tests | point-in-time focused tests | Pass within offline suite; re-run date-sensitive | Re-run / Supplied | Partial |
| Doc/schema validation | `scripts/validate/validate_requirements.py` | 34/34 artifacts present; JSON/JSONC/YAML parse OK; requirements pass the REAL draft-2020-12 schema (jsonschema); no secrets | Re-run | Pass |
| Governance unit tests | `pytest test/offline/test_governance_scaffold.py` | 16 passed | Re-run | Pass |
| Ruff lint | `ruff check .` | All checks passed (full repo) | Re-run | Pass |
| Diff whitespace | `git diff --check` | No whitespace errors (tracked + intent-to-add) | Re-run | Pass |
| CI workflow structure | YAML parse of `.github/workflows/ci.yml` | Parses OK; governance job installs jsonschema + PyYAML and enforces the real schema offline | Re-run | Pass |
| Phase 4A comparison unit tests | `pytest test/offline/test_comparison_runner.py test/offline/test_comparison_schemas.py` | 47 passed in 0.40s (17 runner + 30 schemas) | Re-run | Pass (expected) |
| Phase 4A correction round (focused comparison tests) | `pytest test/offline/test_comparison_runner.py test/offline/test_comparison_schemas.py` | 73 passed in 0.41s (was 47; strict four-score traceability, input_exhaustion-not-an-early-stop, stop-reason preservation, regression coverage) | Re-run | Pass (expected) |
| Phase 4A correction round (final verification) | `validate_requirements.py` + `pytest test/offline/test_governance_scaffold.py` + `ruff check .` + `git diff --check` | validator PASS (34/34, no secrets); governance 16 passed; Ruff clean (full repo); diff-check clean | Re-run | Pass (expected) |
| Full offline suite (current tree, Phase 4A correction round) | `pytest test/offline/ -q` | 1463 passed, 2 skipped, 22 warnings, 88 subtests; 4 failed (3 date-sensitive cache tests + 1 network-reachability baseline) — pre-existing, NO new regression | Re-run | Partial |
| Phase 4A comparison script | `python scripts/run_phase4a_comparison.py` | 3 scripted cases written to `evaluation-output/` (comparison_results.json + comparison_report.md) | Re-run | Pass (expected) |
| Phase 4A reporting-gap fix (independent review) | `pytest` comparison tests + comparison script + governance validator + governance tests + `ruff check .` + `git diff --check` | 47 comparison tests passed; script wrote 3 cases; validator PASS; governance 16 passed; Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Phase 4A scenario F budget route | `evaluate_round(...)` on `case_budget_protection()` | route=SUMMARIZE, stop_reason=BUDGET_EXHAUSTED; reserve preserved (9000+8000 <= 20000; fixed spends 27000 > 20000) | Re-run | Pass (expected) |
| Phase 4A governance | `validate_requirements.py` + `pytest test/offline/test_governance_scaffold.py` + `ruff check` + `git diff --check` | PASS; 16 passed; ruff clean; diff-check clean | Re-run | Pass (expected) |
| Phase 4A narrow fail-closed correction (focused comparison tests) | `pytest test/offline/test_comparison_runner.py test/offline/test_comparison_schemas.py` | 90 passed in 0.46s (was 73; fail-closed strategy/early_stopped/stop_reason consistency via `_DYNAMIC_STOP_REASONS`) | Re-run | Pass (expected) |
| Phase 4A narrow fail-closed correction (governance + verification) | `validate_requirements.py` + `pytest test/offline/test_governance_scaffold.py` + `ruff check .` + `git diff --check` | validator PASS (34/34, no secrets); governance 16 passed; Ruff clean (full repo); diff-check clean | Re-run | Pass (expected) |
| Full offline suite (current tree, Phase 4A narrow fail-closed correction) | `pytest test/offline/ -q` | 1481 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (date-sensitive cache tests, RISK-001; network baseline RISK-002 did not fail this run) — pre-existing, NO new regression | Re-run | Partial |
| Phase 4A human review decision (post-correction) | human review recorded in `docs/review-memo.md` (WANG Yiwen 60536848, 2026-10-23) | Approved with limitations; subject to the four recorded limitations (offline only, cache baselines remain, traceability pending, no production threshold tuning). Full suite not claimed green. | Re-run | Approved with limitations |
| Blocked final-output guard (review finding 1) | `pytest test/offline/test_output_guard.py` | 47 passed in 0.48s (structured + free-text, full graph with real blocked gate, missing/malformed gate state, normal/degraded preserved, report + final signal, legacy normal checkpoint) | Re-run | Pass (expected) |
| Blocked final-output guard (affected suite) | `pytest` gate + debate + report + structured + rating + PM + output-guard tests | 294 passed in 1.67s | Re-run | Pass (expected) |
| Blocked final-output guard (independent review demo) | `tradingagents_offline_demo.py` | `final_signal` = Hold (was Buy); manager recommendation still Hold | Re-run | Pass (expected) |
| Full offline suite (current tree, blocked final-output guard) | `pytest -q -p no:cacheprovider` | 1528 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (known date-sensitive cache tests, RISK-001) — pre-existing, NO new regression | Re-run | Partial |
| Blocked final-output guard (governance) | `validate_requirements.py` + `ruff check` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |

## Interpretation

- The **Conflict/debate/graph/Stage-2 relevant suite is clean (490 passed,
  offline)**, including the deterministic ConflictRecord runtime lifecycle
  (`test/offline/test_debate_conflicts.py`: 39 passed). This is the strongest claim
  this scaffold makes.
- **Phase 4A correction round** (human review) implemented and verified: 73
  focused comparison tests passed; the actual dynamic stop reason is preserved
  in results, JSON/aggregates, and Markdown; a scripted input that runs out of
  rounds is `input_exhausted` (never a dynamic early stop); a `SCORED`
  traceability result requires exactly four non-null scores in
  `TRACEABILITY_DIMENSIONS` order.
- **Phase 4A narrow fail-closed correction** (short re-review) implemented and
  verified: `CaseResult.__post_init__` rejects a contradictory
  `strategy`/`early_stopped`/`stop_reason` combination — a `FIXED` result is
  never early-stopped, and an `early_stopped == True` dynamic result must carry
  a genuine `_DYNAMIC_STOP_REASONS` reason (empty / `input_exhausted` /
  `max_rounds_reached` / unknown are rejected). 90 focused comparison tests
  passed (was 73); the aggregate/report can no longer accept or render an
  inconsistent result.
- **Phase 4A human review decision (post-correction): Approved with
  limitations** (entry 056, `docs/review-memo.md`, WANG Yiwen 60536848,
  2026-10-23). This supersedes the prior "Changes requested" decision for the
  current status (the prior decision and correction-round records are retained
  as historical audit evidence). Human traceability scores remain `pending`, and
  the full offline suite is not claimed completely green.
- The **full offline suite is not claimed fully green** because of the known
  date-sensitive cache failures and the network-reachability-dependent baseline
  failure. The narrow-correction re-run (logbook 055) shows **1481 passed, 2
  skipped, 3 known date-sensitive baseline failures** (the network baseline did
  not fail on this run) with no new regression. They are recorded, not hidden.
- Doc/schema validation outcomes are recorded above and in
  `docs/architecture/evaluation-logbook.md` (entries 035-039, 051, 054, 056).| Guard edge cases (operator review) | `pytest test/offline/test_output_guard.py` | 55 passed (was 47; compatibility marker without header, repeated headers, markup tolerance, blocked sizing, idempotence) | Re-run | Pass (expected) |
| Guard edge cases (affected suite) | `pytest` output-guard + hold-contract + structured + memory-log | 184 passed | Re-run | Pass (expected) |
| Pre-call budget guards (review finding 2) | `pytest test/offline/test_debate_precall_budget.py` | 14 passed (max_calls=1 runs exactly one call; zero capacity refused; disabled compatibility; reserve preserved; incomplete-round skip) | Re-run | Pass (expected) |
| Pre-call budget (debate suite) | `pytest` pre-call + budget + graph + evaluator + config + turn + manifest + opening | 171 passed | Re-run | Pass (expected) |
| Audit exports (review finding 3) | `pytest test/offline/test_report_artifacts_audit.py` | 12 passed (per-evidence association, separate map, legacy empty, redaction, identity/quality/usage provenance, deterministic roundtrip) | Re-run | Pass (expected) |
| Full offline suite (current tree, maintenance corrections) | `pytest -q -p no:cacheprovider` | 1562 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (known date-sensitive cache tests, RISK-001) — pre-existing, NO new regression | Re-run | Partial |
| Maintenance corrections (governance) | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Second review — budget reserve+estimate boundary | `pytest test/offline/test_debate_precall_budget.py` | 22 passed (reserve-only refusal; reserve+estimate token & second exact boundaries; before-first-Bull and before-Bear graph boundaries; estimate_basis/scope tracing) | Re-run | Pass (expected) |
| Second review — audit compatibility | `pytest test/offline/test_report_artifacts_audit.py` | 20 passed (legacy embedded-only preserved; authoritative map overrides; shuffled-map determinism; ambiguous identity flagged; snapshot_id null by default) | Re-run | Pass (expected) |
| Full offline suite (current tree, second review) | `pytest -q -p no:cacheprovider` | 1578 passed, 2 skipped, 22 warnings, 88 subtests; 3 failed (known date-sensitive cache tests, RISK-001) — pre-existing, NO new regression | Re-run | Partial |
| Second review (governance) | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Stricter fully offline suite (operator/AI technical verification, socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError('Network disabled for offline verification')` | 1577 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (3 date-sensitive cache tests + known Yahoo reachability/exception-type baseline) — pre-existing, NO new regression; recorded separately from the 3-failure run, neither claimed all-green | Supplied (operator-verified) | Partial |
| Operator/AI technical verification summary | 464 focused tests + offline demo + Ruff + governance validator + `git diff --check` | 464 focused passed in 1.82s; demo `final_signal=Hold`, `max_calls=1` -> 1 debate call, validation counts [7,7,7,7,6]; validator PASS (35/35, no secrets); Ruff clean; diff-check clean. Technical verification only, NOT a human approval. | Supplied (operator-verified) | Pass (technical) |
| Recheck 2026-11-06 — finding 1/3 (output guard) | `pytest test/offline/test_output_guard.py` | 90 passed (fullwidth colon/labels/values, arbitrarily prefixed labels, unicode dashes, repeated/trailing alternative headers, separator preservation, idempotence, shared parser canonicalisation, complete-graph report+memory tag/body consistency, signal-boundary gate awareness) | Re-run | Pass (expected) |
| Recheck 2026-11-06 — finding 2 (real gate->debate) | `pytest test/offline/test_gate_debate_integration.py` | 9 passed (real gate node -> per-record Medium/High; manifest/allowlist valid IDs; report quality_counts Medium; cited+linked real ID counts as new; Low/Blocked/future do not) | Re-run | Pass (expected) |
| Recheck 2026-11-06 — focused affected suite | `pytest` output-guard + integration + gate graph + debate + manifest + evaluator + turn + verdict gate + memory + signal + rating + audit + reporting + pre-call | 480 passed | Re-run | Pass (expected) |
| Recheck 2026-11-06 — strict fully offline suite (socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError(...)` | 1621 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (same 3 date-sensitive cache tests + known Yahoo reachability baseline) — pre-existing, NO new regression; not claimed all-green | Re-run | Partial |
| Recheck 2026-11-06 — governance | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Operator executable-instruction maintenance 2026-11-06 (output guard) | `pytest test/offline/test_output_guard.py` | 130 passed (fullwidth label/value + sizing separators, arbitrary/long prefixes, repeated/trailing labels, proposal `BUY because ...`, Markdown wrapping, rationale/recovery/quoted-alternative preservation, idempotence, long-line performance, full blocked graph stored plans + saved report) | Re-run | Pass (expected) |
| Operator executable-instruction maintenance 2026-11-06 (focused affected suite) | `pytest` output-guard + integration + gate graph + debate + manifest + evaluator + turn + verdict gate + memory + signal + rating + audit + stage2 + pre-call + structured + hold-contract + cli-decision-log | 520 passed | Re-run | Pass (expected) |
| Operator executable-instruction maintenance 2026-11-06 (strict fully offline suite, socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError(...)` | 1661 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (same 3 date-sensitive cache tests + known Yahoo reachability baseline) — pre-existing, NO new regression; not claimed all-green | Re-run | Partial |
| Operator executable-instruction maintenance 2026-11-06 (governance) | `validate_requirements.py` + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| Documentation/requirements revision 2026-11-06 (schema + PRD + register + prompt v1.3) | `validate_requirements.py` + `pytest test/offline/test_governance_scaffold.py` + Draft202012 negative-mutation probes + `ruff check .` + `git diff --check` | validator PASS (35/35, no secrets); governance 16 passed; 0 baseline schema errors and all negative mutations rejected; Ruff clean; diff-check clean | Re-run | Pass (expected; doc-only, awaits human review) |
| Independent operator recheck 2026-11-06 (docs revision) | `verify_governance_docs.py` + `pytest test/offline/test_governance_scaffold.py` + strict socket-disabled suite | 22/22 real-schema positive; 440 mutations rejected; all new YAML parse; 22 trace monitor rows; governance 16 passed; strict offline 4 failed / 1661 passed / 1 skipped / 1 deselected (same 4 known baselines, not green) | Supplied (operator-verified) + Re-run | Partial (technical; known baselines remain) |
| November 10 repair batch — defect 1 output guard multiline containment | `pytest test/offline/test_output_guard.py` | 219 passed across guard+audit+governance at first review; re-run after the second in-progress review: guard suite 197 passed, guard+audit+governance incl. 24 multiline + 14 boundary + 15 second-review boundary (bulleted/numbered `- Buy`/`1. Buy` direct + fake-Trader, live command with `earlier`/quote keyword still contained, structural quoted/negated rationale preserved, direction+explanation tail kept, split sizing, long repeated direction-token linear time, LF/CRLF/fullwidth/Markdown, full blocked graph/report/memory) | Re-run | Pass (expected; 4 known baselines remain; awaits human acceptance) |
| November 10 repair batch — defect 2 empty-map override | `pytest test/offline/test_report_artifacts_audit.py` | present `{id: []}` overrides stale embedded passed checks; absent keeps legacy fallback; nonempty override, no cross-ID leak, deterministic order, redaction, helper + saved artifact | Re-run | Pass (expected) |
| November 10 repair batch — defect 3 shared ID uniqueness | `pytest test/offline/test_governance_scaffold.py` | real-jsonschema + forced-fallback both reject duplicate IDs with differing objects; valid 22-ID registry passes; malformed rows no crash | Re-run | Pass (expected) |
| November 10 repair batch — strict fully offline suite (socket disabled) | `pytest -q -p no:cacheprovider -m "not integration"` with `socket.socket.connect` -> `OSError(...)` | 1743 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests; 4 failed (same 3 date-sensitive cache tests + known no-data/Yahoo-reachability baseline) — pre-existing, NO new regression; not claimed all-green | Re-run | Partial |
| November 10 repair batch — governance | `validate_requirements.py` + `ruff check` (changed files) + `git diff --check` | validator PASS (35/35, no secrets); Ruff clean; diff-check clean | Re-run | Pass (expected) |
| November 10 doc/traceability consistency batch — governance/traceability | `validate_requirements.py` + `pytest tests/test_governance_scaffold.py` + mapped 29-file suite + strict-offline count-and-fail harness + `ruff check` + `git diff --check` | validator PASS (42/42, no secrets); governance 48 passed; mapped+focused 1000 passed; strict-offline 4 failed / 1768 passed / 1 skipped / 1 deselected (same 4 known baselines) with 1 intercepted vendor-reachability attempt (NFR-OFF-001 PARTIAL/OPEN, no connection made); Ruff clean; diff-check clean | Re-run | Partial (technical; 4 known baselines + 1 intercepted attempt remain; awaits human acceptance) |
| November 10 doc/traceability batch — independent Codex AI verification (current final) | 14-file focused suite + validator + boundary + 440 schema mutations + strict-offline harness + Ruff + diff-check | 14-file focused 583 passed / 2 warnings; validator 42/42 PASS + no secret hits; boundary 39/39; 440 negative schema mutations rejected; strict-offline 4 failed / 1768 passed / 1 skipped / 1 deselected / 22 warnings / 88 subtests with 1 intercepted vendor-reachability attempt (NFR-OFF-001 PARTIAL/OPEN, no connection made); Ruff clean; diff-check clean | Supplied (independent Codex AI) | Partial (technical; 4 known baselines + 1 intercepted attempt remain; NOT human acceptance) |
| November 10 school-model live end-to-end run (NVDA 2026-11-05, recorded by Codex; documentation-only record) | existing `live_school_verification.py`; endpoint llm.cs.cityu.edu.hk CS5351/DeepSeek-V4-Flash; full existing graph | 16 app model calls, gateway total 170,665 tokens, 0 truncations; final+textual signal Overweight; Gate DEGRADED (not blocked) so `blocked_signal_is_hold=true` is VACUOUS not live blocked proof; 5 market evidence records / 5 validation IDs all matching the authoritative map; Medium count 5; stop_reason preserved; usage total_run null / debate-only estimated 1 call / 15183 tokens / 2024.4 s. DEBT-021 confirmed OPEN: Bull actual 19.70 s / 16,931 tokens vs estimated 2,024.4 s / 15,183; Bear node visited but 0 actual Bear calls, bear_history empty, budget_exhausted (faulty estimate, actual runtime NOT > 600 s). Optional categories still unavailable_no_structured_source (DEBT-015/RISK-015, NOT fixed). Supplemental existing offline boundary 39/39 passed (OFFLINE only). | Supplied (Codex external live verification; docs-only record — NOT re-run here, NOT human acceptance) | Partial (live DEGRADED, 0 complete rounds; DEBT-021 + optional adapters OPEN; blocked/normal live paths not exercised; final acceptance PENDING) |

---

## Part III — Token-observability evaluation (personal delivery)

Parts I–II above are the Release verification summary and are unchanged. Part III is the
personal delivery's 2×2 evaluation table. It is **exploratory** (n=1 per cell for the factorial)
and its numbers are recorded telemetry, not re-run by this integration.

### Personal reading rules

**Reading rule.** Part I compares the four V3 arms. It is **not** a significance
test: every cell is one run (n = 1), the three complete blocks are NVDA, AAPL and
XOM, and JPM/CC was never measured. Part II lists the batches and their cells.
A number without a cell is not a result.

**Primary metric.** `total_tokens = provider-reported input + output`. Cached
input is a subset of input and is not added again. "Valid" means the frozen U-1
usage/attribution verdict passed and, for V3, the memory baseline was unchanged.

---

### Part I — qualitative comparison of the V3 arms

#### 1.1 Design

| Arm | `batch_macro` | `single_pass` | `structured` | `s2_downstream` | What it tests |
| --- | --- | --- | --- | --- | --- |
| B | off | off | on | on | Two-call baseline (prose then structured finalisation) |
| AB | on | off | on | on | Batch macro alone |
| C0 | off | on | on | on | Single-pass alone (CAND-01) |
| CC | on | on | on | on | Both switches on |

`structured=true` and `s2_downstream=true` are held constant; there is no OFF
implementation of S2 downstream.

#### 1.2 Balanced arm means (NVDA, AAPL, XOM; n = 3 per arm)

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

#### 1.3 Factorial effects (tokens; negative = saving)

Definition: batch = mean(AB, CC) − mean(B, C0); single = mean(C0, CC) −
mean(B, AB); interaction = (CC − AB) − (C0 − B).

| Block | B | AB | C0 | CC | Batch effect | Single-pass effect | Interaction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NVDA | 233,199 | 186,378 | 229,187 | 172,577 | −51,716 | −8,907 | −9,789 |
| AAPL | 197,157 | 198,615 | 180,614 | 182,379 | +1,612 | −16,390 | +307 |
| XOM | 225,846 | 234,020 | 203,550 | 189,373 | −3,002 | −33,472 | −22,351 |
| **Mean (3 blocks)** | | | | | **−17,702** | **−19,589** | **−10,611** |

#### 1.4 Sensitivity (what survives a defensible exclusion)

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

#### 1.5 Qualitative comparison

| Arm | Observed behaviour | Reliability / quality signal |
| --- | --- | --- |
| B | Highest balanced mean; no batch tool; two-call path. All four PM ratings were `Underweight` (NVDA, AAPL, JPM, XOM). | No provider failure; no raw-markup report in the B block. |
| AB | Batch macro collapses 7–9 single-series calls (up to 13 total on mixed runs) to one, but the larger batch payload is re-sent; V3 AB is 186,378 on NVDA and 198,615 / 204,421 / 234,020 on AAPL / JPM / XOM. All four PM ratings were `Hold`. | No provider failure in V3. The 339,738 NVDA/AB outlier belongs to V2 (long news loop: 8 `get_news`, 10 tool rounds), not to V3; do not mix the batches. |
| C0 | Single-pass is cheaper than B on average; output falls proportionally more than input (the duplicate prose turn is removed). Ratings mix `Underweight`, `Overweight`, `Hold`, `Hold`. | 5 market fallbacks, all in single-pass arms; R01 (NVDA) is environment-degraded; C0's higher character count is a format artefact (fallback prose), not more analysis. |
| CC | Cheapest balanced mean; lowest output mean; both switches active. Ratings `Hold`, `Hold`, `Underweight`; JPM/CC not measured. | R12 failed twice with provider 400; R07 (AAPL) and R14 (XOM) had raw DSML markup in `market_report` (1,922 and 346 chars). Cheapest on tokens, weakest on reliability. |

**Do not read the ratings as quality.** They are one sample per cell, produced by
one model on one date. The V3 quality review states that there is no ground
truth, no realised return, and no forward-looking return; no arm can be called
more accurate, safer, or better. The only defensible quality statement is
structural: 15/15 runs produced complete decision fields, except R07/R14 whose
`market_report` is markup and R12 which produced no decision.

#### 1.6 What the table does not show

* No repeat runs, so run-to-run variance is inseparable from an arm effect.
* No confidence interval, p-value, or power calculation; n = 1 per cell.
* No S2-downstream effect (the switch has no OFF implementation).
* No global-news effect (the global path is `CONFIG_DISABLED` in every arm).
* No memory effect (the V3 baseline is empty, by design).
* No cost in currency, only provider-reported tokens.

---

### Part II — batches and per-block cells

#### 2.1 Batch ledger

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

#### 2.2 V2 per-block cells (tokens)

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

#### 2.3 V3 per-block cells (tokens)

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

#### 2.4 Data provenance

| Evidence | Status |
| --- | --- |
| `token_benchmarks/baseline_v2/summary.{md,json,csv}`; V2/V3 protocols; V3 audits; final-remediation reports | Tracked in `50b2ca3` |
| Raw paid telemetry and per-run `runner_report.json` | Git-ignored; **(local)** under `.worktrees/` |
| RC1 eight-run pilot, Stage 1/2 campaign, V3 factorial tables | **(local)**; not deliverable evidence |

The table above separates "recorded" from "recomputed". The 1,685,450 RC1 total,
1,076,190 baseline total, 1,463,791 V2 total and 3,067,669 V3 total are
arithmetic sums of the rows cited; they are not estimates.

| November 10 doc/traceability consistency batch — governance/traceability | `validate_requirements.py` + `pytest test/offline/test_governance_scaffold.py` + mapped 29-file suite + strict-offline count-and-fail harness + `ruff check` + `git diff --check` | validator PASS (42/42, no secrets); governance 48 passed; mapped+focused 1000 passed; strict-offline 4 failed / 1768 passed / 1 skipped / 1 deselected (same 4 known baselines) with 1 intercepted vendor-reachability attempt (NFR-OFF-001 PARTIAL/OPEN, no connection made); Ruff clean; diff-check clean | Re-run | Partial (technical; 4 known baselines + 1 intercepted attempt remain; awaits human acceptance) |
| November 10 doc/traceability batch — independent OpenCode AI verification (current final) | 14-file focused suite + validator + boundary + 440 schema mutations + strict-offline harness + Ruff + diff-check | 14-file focused 583 passed / 2 warnings; validator 42/42 PASS + no secret hits; boundary 39/39; 440 negative schema mutations rejected; strict-offline 4 failed / 1768 passed / 1 skipped / 1 deselected / 22 warnings / 88 subtests with 1 intercepted vendor-reachability attempt (NFR-OFF-001 PARTIAL/OPEN, no connection made); Ruff clean; diff-check clean | Supplied (independent OpenCode AI) | Partial (technical; 4 known baselines + 1 intercepted attempt remain; NOT human acceptance) |
| November 10 school-model live end-to-end run (NVDA 2026-11-05, recorded by OpenCode; documentation-only record) | existing `live_school_verification.py`; endpoint llm.cs.cityu.edu.hk CS5351/DeepSeek-V4-Flash; full existing graph | 16 app model calls, gateway total 170,665 tokens, 0 truncations; final+textual signal Overweight; Gate DEGRADED (not blocked) so `blocked_signal_is_hold=true` is VACUOUS not live blocked proof; 5 market evidence records / 5 validation IDs all matching the authoritative map; Medium count 5; stop_reason preserved; usage total_run null / debate-only estimated 1 call / 15183 tokens / 2024.4 s. DEBT-021 confirmed OPEN: Bull actual 19.70 s / 16,931 tokens vs estimated 2,024.4 s / 15,183; Bear node visited but 0 actual Bear calls, bear_history empty, budget_exhausted (faulty estimate, actual runtime NOT > 600 s). Optional categories still unavailable_no_structured_source (DEBT-015/RISK-015, NOT fixed). Supplemental existing offline boundary 39/39 passed (OFFLINE only). | Supplied (OpenCode external live verification; docs-only record — NOT re-run here, NOT human acceptance) | Partial (live DEGRADED, 0 complete rounds; DEBT-021 + optional adapters OPEN; blocked/normal live paths not exercised; final acceptance PENDING) |


## WebUI extension

# TradingAgents WebUI Architecture Evaluation Table

Status: **Approved for documentation by the human owner on 2026-11-05.** This document separates the **evaluation plan** from **actual results**. Planned checks are not results. Iteration-1 verification has been executed; rows record their actual status.

## 1. Evaluation plan

| ID | Evaluation | Method | Environment | Pass criterion | Status |
| --- | --- | --- | --- | --- | --- |
| EVAL-01 | Dependency and license review | Inspect `fastapi`, `uvicorn`, and npm lockfile; run advisory audit | Approved dev/CI environment | No unapproved license; no unresolved high/critical advisory | Partially run: npm audit 0; pip-audit and license review pending |
| EVAL-02 | Backend contract | pytest + httpx/TestClient with fake graph runner | Offline, temp dirs | All API/event/error contracts pass | Executed: 147 passed |
| EVAL-03 | Security boundary | Host/Origin/CSRF, path traversal, secret scan, XSS payloads | Offline | Zero violations in the defined suite | Executed: 147 passed (backend/static contract suite) |
| EVAL-04 | Event latency | Local harness publishing N events; measure p95 delivery | Loopback, no model calls | p95 ≤ 1000 ms; no sequence gaps | Not run: no SSE in Iteration 1 |
| EVAL-05 | Packaging | Build wheel; inspect contents; install in clean venv; health check | Clean temp environment | `static/index.html` present; `/api/health` succeeds | Partially run: wheel contents verified; clean install pending |
| EVAL-06 | Browser matrix | Playwright on Chromium/Firefox/WebKit | Desktop, latest two stable majors | Core flows pass; no console errors | Partially run: Chromium 6 passed; Firefox/WebKit excluded by user instruction |
| EVAL-07 | CLI/core regression | Existing offline suite + CLI help/import | Network-isolated | No new regression; inherited failures reported honestly | Executed: 1131 passed, 4 historical failures |
| EVAL-08 | Artifact parity | Compare web-written `message_tool.log`/section files with CLI layout | Temp `results_dir` | Same names and formats; no `full_states_log` | Partially run: read-only fixtures use CLI/API formats; write parity belongs to the run iteration |
| EVAL-09 | Backtest parity | Compare structured summary fields with `summarize()` | Fake/temp backtest | All fields match; live log untouched | Executed offline: launch, summary, log download, and live-log isolation; real model run pending |
| EVAL-10 | Frontend contract | `tsc --noEmit`, OpenAPI type drift, i18n key parity | CI | No drift; no missing keys | Executed: typecheck/lint/build, Vitest 25, Chromium E2E 6; OpenAPI type generation pending |

## 2. Decision rationale (qualitative, not measured)

| Decision | Selected | Main alternative | Rationale |
| --- | --- | --- | --- |
| Backend | FastAPI + Uvicorn | Starlette-only; Flask; Django | Pydantic/OpenAPI/async/SSE fit the Python stack; single worker preserves the run model. |
| Transport | SSE | WebSocket; long polling | One-way events; built-in browser reconnection; less lifecycle code. |
| Frontend | React 19 + TS + Vite | Next.js; templates | Explicit user selection; SPA needs no SSR or second server. |
| UI | Tailwind + shadcn/Radix | MUI/Ant Design | Accessible primitives with controllable styling and no heavy lock-in. |
| Client state | Zustand + TanStack Query | Redux Toolkit | One active run needs a small store; server data benefits from query caching. |
| Run state | In-memory single run | File journal; database | Fits the confirmed process-lifetime reattachment and avoids new storage. |
| History | Read-only hash-id projection | Index database; raw paths | No second source of truth; no path leakage. |
| Keys | Server environment only | Browser input | Avoids transmitting plaintext credentials to a client. |
| Cancellation | Analysis only; backtest no-cancel | Fake backtest cancel | `run_backtest` has no hook; honest controls. |
| Downloads | Complete Markdown + zip | PDF/Word | Uses existing artifacts; no new renderer. |

These are design judgments, not benchmark results. They do not replace EVAL-01 through EVAL-10.

## 3. Actual results (executed checks only)

| Check | Method | Result | Date |
| --- | --- | --- | --- |
| Requirements YAML syntax and duplicate keys | Local Node `yaml` parser with `uniqueKeys: true` | Passed: 26 requirements parsed | 2026-11-05 |
| Requirements shape/IDs/enums/thresholds/invariant rules | Local targeted validator mirroring `req-schema.json` and `test/ci_gates.py` | Passed: 26 requirements, 69 unique criteria | 2026-11-05 |
| Source/architecture/invariant references and dependency cycles | Same local validator | Passed | 2026-11-05 |
| Blueprint anchor resolution | Local script over `architecture_refs` | Passed: all anchors resolve | 2026-11-05 |
| Official `python -m test.ci_gates schema` | Project entry point in `.venv` | **PASS** | 2026-11-05 |
| Official `python -m test.ci_gates structure` | Project entry point in `.venv` | **PASS** | 2026-11-05 |
| WebUI backend suite (Iteration 1–3) | `pytest test/offline/test_web_*.py` | **147 passed** | 2026-11-06 |
| CLI/reporting compatibility | `pytest test_cli_commands.py test_reporting.py` | **14 passed** | 2026-11-06 |
| Import smoke, web mypy, and ruff | `python -c ...`; `mypy src/tradingagents_web`; `ruff check ...` | **PASS** | 2026-11-06 |
| Full regression | `pytest --disable-socket --allow-unix-socket` | **1131 passed, 4 historical failures, 2 skipped, 88 subtests** | 2026-11-06 |
| Frontend Vitest | `npm run test` | **25 passed (8 files)** | 2026-11-06 |
| Frontend lint/typecheck/build | `npm run lint`, `npm run typecheck`, `npm run build` | **PASS** | 2026-11-06 |
| Frontend dependency audit | `npm audit --json` | **0 vulnerabilities** | 2026-11-06 |
| Wheel packaging | `pip wheel . --no-deps`; inspect archive | **Iteration-3 modules and built static assets present** | 2026-11-06 |
| Static/API smoke | TestClient with built static | **/, /history, /api/health, /api/history → 200** | 2026-11-06 |
| Architecture experiments EVAL-01 to EVAL-10 | — | **Partially run; see the individual rows and the logbook** | 2026-11-06 |
| Playwright Chromium E2E | `npm run e2e` | **6 passed** (history, announcements, backtest, wizard/live/report, cancel) | 2026-11-06 |
| Playwright Firefox/WebKit | — | **Not run**: excluded by user instruction | 2026-11-06 |
| Iteration-3 backend test version | `pytest test/offline/test_web_*.py` | **113 passed, 6 failed, 28 errors**; all 34 are `EXPECTED-UNIMPLEMENTED` | 2026-11-06 |
| Iteration-3 frontend test version | `npm run test` | **10 passed, 15 failed**; all 15 are `EXPECTED-UNIMPLEMENTED` | 2026-11-06 |
| Iteration-3 Chromium E2E | `npm run e2e` | **4 passed, 2 failed**; both failures were `EXPECTED-UNIMPLEMENTED` at review time | 2026-11-06 |
| Iteration-3 implementation backend | `pytest test/offline/test_web_*.py` | **147 passed** | 2026-11-06 |
| Iteration-3 implementation frontend | `npm run test` | **25 passed** | 2026-11-06 |
| Iteration-3 implementation E2E | `npm run e2e` | **6 passed** | 2026-11-06 |
| Real GraphRunner/live model path | — | **Not run**: requires credentials/cost authorization | 2026-11-06 |

The documentation validation above does not verify the architecture, the runtime, packaging, latency, browsers, or dependencies. It only checks the written registry.

## 4. Not evaluated

- FastAPI/Uvicorn dependency and advisory status.
- npm dependency tree, license, and bundle size.
- Event latency and buffer behavior under load.
- SSE reconnection and snapshot behavior in real browsers.
- Clean install in a fresh environment (wheel contents were verified).
- Browser matrix.
- Backtest long-run behavior and memory growth.
- Security middleware under a production server (TestClient coverage exists).
- Any model or data-provider call.

## 5. Rules

1. A planned check is never reported as passing.
2. Results include method, environment, date, and exact output; no estimated scores.
3. Failed checks remain failures; they are not converted to skips or waivers.
4. Architecture changes require updating this table and the logbook.
5. Only `docs/architecture/evaluation-logbook.md` may record executed results.
