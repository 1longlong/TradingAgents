# Evaluation Logbook — Verification of Record

This logbook records verification executions and their exact outcomes. A row is
added whenever a verification is run. Do not backfill a claim without the
command that produced it. "Supplied" rows are evidence provided to this task and
were not re-run in the current environment; they are labeled as such and are not
claimed as a green full suite.

## Conventions

- `status` is one of: `Pass` (expected), `Partial` (known failures remain),
  `Blocked`, `Error`.
- `source` is `Re-run` (executed here) or `Supplied` (previously observed,
  provided to this task).

## Log

### 031 — Debate-focused subset (current working tree)

```text
command: .venv/bin/python -m pytest tests/test_data_quality_gate_graph.py \
  tests/test_debate_budget.py tests/test_debate_config.py \
  tests/test_debate_evaluator.py tests/test_debate_evidence_manifest.py \
  tests/test_debate_graph.py tests/test_debate_turn.py \
  tests/test_evidence_models.py tests/test_evidence_step2_regressions.py \
  tests/test_market_data_validator_structured.py \
  tests/test_market_evidence_gate.py \
  tests/test_research_manager_hold_contract.py \
  tests/test_researchers_verdict_gate.py -q
result: 333 passed in 1.00s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

> Superseded by entry 040 below (which adds the Stage 2 multi-category gate,
> report-artifact, and governance test files). Entry 031 retained for audit
> history of the narrow debate subset.

### 040 — Stage-2 relevant suite (current working tree, supersedes 031)

```text
command: .venv/bin/python -m pytest \
  tests/test_data_quality_gate_graph.py tests/test_debate_budget.py \
  tests/test_debate_config.py tests/test_debate_evaluator.py \
  tests/test_debate_evidence_manifest.py tests/test_debate_graph.py \
  tests/test_debate_turn.py tests/test_debate_opening.py \
  tests/test_evidence_models.py tests/test_evidence_step2_regressions.py \
  tests/test_market_data_validator_structured.py \
  tests/test_market_evidence_gate.py tests/test_report_artifacts_stage2.py \
  tests/test_reporting.py tests/test_research_manager_hold_contract.py \
  tests/test_researchers_verdict_gate.py \
  tests/test_stage2_multicategory_gate.py tests/test_governance_scaffold.py -q
result: 402 passed in 1.16s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 041 — Stage 2 gate + report-artifact files (current working tree)

```text
command: .venv/bin/python -m pytest tests/test_stage2_multicategory_gate.py -q
result: 26 passed in 0.46s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

```text
command: .venv/bin/python -m pytest tests/test_report_artifacts_stage2.py -q
result: 16 passed in 0.39s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

```text
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.07s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 032 — Supplied: OpenCode-related suite

```text
result: 420 passed
status: Pass (expected) — provided, not re-run here
source: Supplied
date: 2026-10-21
```

### 033 — Supplied: independent full offline suite (sandbox)

```text
result: 1275 passed, 1 skipped, 1 deselected, 88 subtests
known failures: 3 date-sensitive cache tests; 1 network-reachability-dependent baseline test
status: Partial (known failures remain; NOT a clean full-suite green)
source: Supplied
date: 2026-10-21
```

### 034 — Supplied: earlier OpenCode environment full offline suite

```text
result: 1276 passed
known failures: 3 date-sensitive cache tests
status: Partial (known failures remain; NOT a clean full-suite green)
source: Supplied
date: 2026-10-21
```

### 035 — Governance/schema validator (current working tree)

```text
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 34/34 valid; JSON/JSONC/YAML parse OK;
        requirements validated against schema; secret scan: no likely secrets found.
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 036 — Governance scaffold unit tests (current working tree)

```text
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 10 passed in 0.02s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 037 — Ruff full-repo lint (current working tree)

```text
command: .venv/bin/ruff check .
result: All checks passed
note: includes the new scripts/validate/validate_requirements.py and tests/test_governance_scaffold.py
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 038 — Corrected real-draft-2020-12 schema validation (jsonschema installed)

```text
command: .venv/bin/pip install jsonschema ; .venv/bin/python scripts/validate/validate_requirements.py
result: jsonschema detected (Draft202012Validator); requirements.yaml validated against the
        REAL docs/req/req-schema.json (no subset-fallback warning); 34/34 artifacts present;
        secret scan: no likely secrets found. Referencing validators confirmed:
          - FR-DQG (bad id) rejected -> '...' does not match '^(FR-(DQG|DDT)|NFR-[A-Z]+)-[0-9]{3}$'
          - schema_version '1.0' rejected -> '...' does not match '^v[0-9]+\.[0-9]+$'
          - extra top-level key rejected (additionalProperties: false)
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 039 — Governance scaffold unit tests (16) after real-schema wiring

```text
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.07s
note: includes pattern tests (schema_version single-backslash, exact FR-DQG/FR-DDT/NFR-CATEGORY-NNN)
        and requirements-vs-real-schema tests.
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 042 — Full offline suite (current working tree)

```text
command: .venv/bin/python -m pytest tests/ -q
result: 4 failed, 1333 passed, 2 skipped, 22 warnings, 88 subtests passed
known failures (pre-existing, unrelated to Stage 2):
  - tests/test_ohlcv_cache_freshness.py (3 date-sensitive cache tests)
  - tests/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache
    (1 network-reachability-dependent baseline test)
status: Partial (pre-existing known failures remain; NOT a clean full-suite green)
source: Re-run
date: 2026-10-21
```

### 043 — Stage 2 runtime multi-category gate integration (current working tree)

```text
command: .venv/bin/python -m pytest tests/test_data_quality_gate_graph.py \
  tests/test_stage2_multicategory_gate.py tests/test_market_evidence_gate.py \
  tests/test_evidence_models.py tests/test_evidence_step2_regressions.py \
  tests/test_market_data_validator_structured.py tests/test_debate_budget.py \
  tests/test_debate_config.py tests/test_debate_evaluator.py \
  tests/test_debate_evidence_manifest.py tests/test_debate_graph.py \
  tests/test_debate_turn.py tests/test_report_artifacts_stage2.py \
  tests/test_governance_scaffold.py tests/test_research_manager_hold_contract.py \
  tests/test_researchers_verdict_gate.py tests/test_structured_agents.py \
  tests/test_market_evidence_gate.py -q
result: 442 passed in 1.99s
note: The runtime graph default (create_data_quality_gate_node) now delegates to the
      multi-category engine (evaluate_multi_category_gate) for the market + optional
      categories. New graph-level tests prove normal/degraded/blocked routing,
      structured-optional-evidence handling, absent-optional-evidence degrade,
      legacy compatibility, point-in-time rejection, and deterministic serialization.
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 044 — Full offline suite after runtime multi-category gate integration

```text
command: .venv/bin/python -m pytest -q
result: 4 failed, 1342 passed, 2 skipped, 22 warnings, 88 subtests passed
known failures (pre-existing, unrelated to this change, and unchanged from entry 042):
  - tests/test_ohlcv_cache_freshness.py (3 date-sensitive cache tests, RISK-001)
  - tests/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache
    (1 network-reachability-dependent baseline test, RISK-002)
status: Partial (pre-existing known failures remain; NOT a clean full-suite green)
source: Re-run
date: 2026-10-21
```

### 045 — Ruff + diff-check + governance validator after runtime integration

```text
command: .venv/bin/ruff check tradingagents/graph/data_quality_gate.py \
  tradingagents/evidence/multi_category_gate.py \
  tradingagents/agents/utils/agent_states.py tests/test_data_quality_gate_graph.py
result: All checks passed
command: git diff --check
result: clean (exit 0)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 34/34 valid; secret scan: no likely secrets found; PASS
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 046 — ConflictRecord runtime lifecycle + debated/graph/Stage-2 relevant suite (current working tree)

```text
command: .venv/bin/python -m pytest tests/test_debate_conflicts.py \
  tests/test_data_quality_gate_graph.py tests/test_stage2_multicategory_gate.py \
  tests/test_market_evidence_gate.py tests/test_evidence_models.py \
  tests/test_evidence_step2_regressions.py \
  tests/test_market_data_validator_structured.py tests/test_debate_budget.py \
  tests/test_debate_config.py tests/test_debate_evaluator.py \
  tests/test_debate_evidence_manifest.py tests/test_debate_graph.py \
  tests/test_debate_turn.py tests/test_report_artifacts_stage2.py \
  tests/test_governance_scaffold.py tests/test_research_manager_hold_contract.py \
  tests/test_researchers_verdict_gate.py tests/test_structured_agents.py -q
result: 490 passed in 1.82s
note: Adds tests/test_debate_conflicts.py (39 passed) which proves the deterministic
      ConflictRecord lifecycle: creation, stable IDs, dedup/merge, resolve/escalate
      with reason capture, evidence fail-closed (unknown/Low/future never creates;
      re-observation with such an ID drops the open conflict), legacy round-trip,
      malformed-state skipping, action-only-never-blocks, evaluator routing with
      runtime-derived conflicts, and the Research Manager's safe conflict-summary
      injection. Supersedes entry 043.
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

```text
command: .venv/bin/python -m pytest tests/test_debate_conflicts.py -q
result: 39 passed in 0.53s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 047 — Full offline suite after ConflictRecord runtime lifecycle

```text
command: .venv/bin/python -m pytest tests/ -q
result: 3 failed, 1391 passed, 2 skipped, 22 warnings, 88 subtests passed
known failures (pre-existing, unrelated to this change):
  - tests/test_ohlcv_cache_freshness.py (3 date-sensitive cache tests, RISK-001)
    : test_current_day_cache_past_ttl_is_not_fresh
    : test_a_download_from_an_earlier_day_is_not_fresh
    : test_load_ohlcv_refetches_stale_same_day_cache
status: Partial (pre-existing date-sensitive failures remain; NOT a clean full-suite green)
source: Re-run
date: 2026-10-21
```

### 048 — Ruff + diff-check + governance validator after ConflictRecord runtime lifecycle

```text
command: .venv/bin/ruff check tradingagents/debate/ \
  tradingagents/agents/managers/research_manager.py tests/test_debate_conflicts.py
  tests/test_debate_turn.py tests/test_debate_evaluator.py tests/test_debate_graph.py
result: All checks passed
command: .venv/bin/ruff check .
result: All checks passed (full repo)
command: git diff --check
result: clean (exit 0)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 34/34 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.07s
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 049 — Phase 4A comparison unit tests + scripted comparison run (current working tree)

```text
command: .venv/bin/python -m pytest tests/test_comparison_runner.py \
  tests/test_comparison_schemas.py -q
result: 47 passed in 0.40s
note: tests/test_comparison_runner.py (17 passed) + tests/test_comparison_schemas.py
      (30 passed) covering pairing/fail-closed, reproducible replay, deterministic
      JSON round-trip, scenarios D (no-new-evidence early stop), E (new-evidence
      extension), F (budget_exhausted summary-reserve/hard-cap protection), the
      metric formulas + zero-denominator behavior, measured-vs-estimated
      separation, tool-call sums + usage provenance (estimated vs measured),
      false-strong-conclusion derivation, report rendering including Tool
      calls / Source / Estimated (not measured) cases, zero-cases safety, and
      human-traceability pending semantics.
command: .venv/bin/python scripts/run_phase4a_comparison.py
result: Phase 4A offline comparison wrote 3 case(s) to evaluation-output/:
        comparison_json=comparison_results.json,
        comparison_markdown=comparison_report.md
note: Aggregate JSON carries fixed/dynamic_total_tool_calls and
      fixed/dynamic_estimated_cases; per-case aggregates carry tool_calls and
      tool_usage_estimated; Markdown per-case table carries Tool calls and
      Source (estimated/measured), and the aggregate table carries Total tool
      calls and Estimated (not measured) cases.
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 050 — Phase 4A scenario F budget-exhaustion route verification (current working tree)

```text
command: .venv/bin/python -c "evaluate_round(...) on case_budget_protection()"
result: route=DebateRoute.SUMMARIZE; stop_reason=StopReason.BUDGET_EXHAUSTED
        decision trace: gate_blocked activated False; budget activated True
note: Confirms scenario F dynamic policy genuinely stops on the budget rule
      (rule 2) BEFORE any new-evidence/material-change continue, so the summary
      reserve is preserved and the hard cap is never exceeded: used 9000 tokens +
      8000 reserved <= 20000 max; dynamic.llm_calls=2 <= 6; the fixed baseline
      spends 27000 tokens (> 20000 max).
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 051 — Phase 4A governance validator + governance tests (current working tree)

```text
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 34/34 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.07s
command: .venv/bin/ruff check tradingagents/comparison/ tests/test_comparison_runner.py
  tests/test_comparison_schemas.py scripts/run_phase4a_comparison.py
result: All checks passed
command: git diff --check
result: clean (exit 0)
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

### 052 — Full offline suite after Phase 4A integration (current working tree)

```text
command: .venv/bin/python -m pytest tests/ -q
result: 3 failed, 1432 passed, 2 skipped, 22 warnings, 88 subtests passed
known failures (pre-existing, unrelated to Phase 4A; unchanged from entry 047):
  - tests/test_ohlcv_cache_freshness.py::test_current_day_cache_past_ttl_is_not_fresh
  - tests/test_ohlcv_cache_freshness.py::test_a_download_from_an_earlier_day_is_not_fresh
  - tests/test_ohlcv_cache_freshness.py::test_load_ohlcv_refetches_stale_same_day_cache
note: all three are the known date-sensitive cache tests (RISK-001/DEBT-001). The
      network-reachability-dependent baseline did not fail on this run.
status: Partial (pre-existing known failures remain; NOT a clean full-suite green)
source: Re-run
date: 2026-10-21
```

### 053 — Phase 4A reporting-gap fix (independent review) (current working tree)

Independent review found the raw `CaseResult` stored `estimated` and `tool_calls`,
but `comparison_results.json` paired aggregates/sums and `comparison_report.md`
did not visibly preserve/report estimated-vs-measured status and omitted
tool-call counts. Fixed only that reporting gap:

```text
command: .venv/bin/python -m pytest tests/test_comparison_runner.py \
  tests/test_comparison_schemas.py -q
result: 47 passed in 0.40s
command: .venv/bin/python scripts/run_phase4a_comparison.py
result: 3 scripted cases written to evaluation-output/ (JSON + Markdown)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 34/34 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.08s
command: .venv/bin/ruff check .
result: All checks passed
command: git diff --check
result: clean (exit 0)
note: Added CaseAggregate.tool_usage_estimated (per-case usage provenance),
      ComparisonReport.fixed_total_tool_calls / dynamic_total_tool_calls and
      fixed_estimated_cases / dynamic_estimated_cases (honest aggregate status).
      compute_case_aggregate propagates CaseResult.estimated -> tool_usage_estimated;
      pair_and_aggregate sums tool calls and counts estimated cases; report.py
      Markdown per-case table adds Tool calls + Source (estimated/measured)
      columns and the aggregate table adds Total tool calls + Estimated (not
      measured) cases. Tests cover serialization, aggregation, report rendering,
      and zero cases. An estimated value is never presented as measured; the
      regenerated evaluation-output now reports all scripted fixtures as
      estimated (tool_calls=0) and Estimated (not measured) cases = 3 / 3.
status: Pass (expected)
source: Re-run
date: 2026-10-21
```

- **Correction round (Phase 4A human review, 2026-10-22 -> 2026-10-23):** the
  human review (`docs/review-memo.md`) requested corrections before Phase 4A
  approval. Implemented the four required corrections:
  1. `CaseResult` with `traceability_status == SCORED` requires exactly four
     non-null scores in `TRACEABILITY_DIMENSIONS` order; missing/extra/null/
     duplicate/reordered dimension sets raise (fail closed) via
     `CaseResult.__post_init__` and `traceability_scores_for_dimensions`.
  2. `input_exhausted` is a distinct, non-early-stop stop reason for a scripted
     run that ran out of available rounds without a policy termination decision
     (Scenario G / `case_input_exhaustion`); `early_stopped == False`, never
     reported as a dynamic early stop.
  3. The actual deterministic `stop_reason` is preserved end-to-end in the
     `CaseResult`, the per-case/aggregate `CaseAggregate`/JSON, and the Markdown
     per-case + aggregate tables (`fixed/dynamic_stop_reasons`).
  4. Regression tests added/extended: **73 focused comparison tests pass** (was
     47).

```text
command: .venv/bin/python scripts/run_phase4a_comparison.py
result: Phase 4A offline comparison wrote 3 case(s) to evaluation-output/:
        comparison_json=comparison_results.json,
        comparison_markdown=comparison_report.md
note: Regenerated output preserves the actual stop reasons: JSON
      sums_and_rates.dynamic_stop_reasons =
      {budget_exhausted: 1, max_rounds_reached: 1, no_new_evidence: 1};
      per-case dynamic stop_reason = no_new_evidence (ABC/D),
      max_rounds_reached (XYZ/E), budget_exhausted (DEF/F); the Markdown
      per-case and aggregate tables render the same actual reasons.
```

```text
command: .venv/bin/python -m pytest tests/test_comparison_runner.py \
  tests/test_comparison_schemas.py -q
result: 73 passed in 0.41s
note: Focused comparison tests after the correction round (was 47). Covers the
      strict four-non-null-score SCORED traceability validation
      (missing/extra/null/reordered rejection), the input_exhausted-not-an-
      early-stop distinction, per-case + aggregate stop-reason preservation in
      JSON and Markdown, and the extended regression coverage.
status: Pass (expected)
source: Re-run
date: 2026-10-23
```

```text
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 34/34 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.08s
command: .venv/bin/ruff check .
result: All checks passed (full repo)
command: git diff --check
result: clean (exit 0)
status: Pass (expected)
source: Re-run
date: 2026-10-23
```

```text
command: .venv/bin/python -m pytest tests/ -q
result: 4 failed, 1463 passed, 2 skipped, 22 warnings, 88 subtests passed
known failures (pre-existing baseline, unrelated to the Phase 4A correction
round; NO new regression):
  - tests/test_ohlcv_cache_freshness.py::test_current_day_cache_past_ttl_is_not_fresh (date-sensitive, RISK-001)
  - tests/test_ohlcv_cache_freshness.py::test_a_download_from_an_earlier_day_is_not_fresh (date-sensitive, RISK-001)
  - tests/test_ohlcv_cache_freshness.py::test_load_ohlcv_refetches_stale_same_day_cache (date-sensitive, RISK-001)
  - tests/test_no_data_handling.py::TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache
    (network-reachability-dependent baseline, RISK-002)
note: All four are the documented pre-existing known baselines; none are new
      regressions from the correction round. Full offline suite is NOT claimed
      fully green.
status: Partial (pre-existing known failures remain; NOT a clean full-suite green)
source: Re-run
date: 2026-10-23
```

### 055 — Phase 4A narrow fail-closed correction + short re-review (2026-10-23)

A second, narrow human-requested correction: `CaseResult` previously accepted a
contradictory `strategy`/`early_stopped`/`stop_reason` combination (e.g. a
`FIXED` result claiming an early stop, or an `early_stopped == True` dynamic
result with an empty / `input_exhausted` / `max_rounds_reached` / unknown stop
reason), which would otherwise propagate into the aggregate and reports. Added
fail-closed consistency validation in `CaseResult.__post_init__` reusing the
single `_DYNAMIC_STOP_REASONS` allowlist:
- `StrategyKey.FIXED` must never be `early_stopped == True`.
- `early_stopped == True` is permitted only for `StrategyKey.DYNAMIC` with a
  genuine dynamic stop reason (one of `_DYNAMIC_STOP_REASONS`).
- `input_exhausted`, `max_rounds_reached`, an empty stop reason, and any unknown
  stop reason are rejected when `early_stopped == True`.

Given the fix fails closed at construction, such a contradictory result can
never reach `compute_case_aggregate` / `pair_and_aggregate` / the report, so
`early_stop_rate` and the "yes"/"no" early-stop label can never render one.

```text
command: .venv/bin/python -m pytest tests/test_comparison_runner.py \
  tests/test_comparison_schemas.py -q
result: 90 passed in 0.46s
note: Focused comparison tests after the narrow fail-closed correction (was 73).
      New regression coverage: direct CaseResult construction rejects a FIXED
      early stop and an early_stopped DYNAMIC result with an empty /
      input_exhausted / max_rounds_reached / unknown stop reason; from_dict /
      JSON deserialization rejects the same contradictions; the aggregate /
      report cannot accept or render an inconsistent result; valid genuine
      dynamic early stops and fixed/non-early / input-exhaustion results still
      work and propagate correctly.
status: Pass (expected)
source: Re-run
date: 2026-10-23
```

```text
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 34/34 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.08s
command: .venv/bin/ruff check .
result: All checks passed (full repo)
command: git diff --check
result: clean (exit 0)
status: Pass (expected)
source: Re-run
date: 2026-10-23
```

```text
command: .venv/bin/python -m pytest tests/ -q
result: 3 failed, 1481 passed, 2 skipped, 22 warnings, 88 subtests passed
known failures (pre-existing date-sensitive baseline, RISK-001; unrelated to
this narrow correction, NO new regression):
  - tests/test_ohlcv_cache_freshness.py::test_current_day_cache_past_ttl_is_not_fresh
  - tests/test_ohlcv_cache_freshness.py::test_a_download_from_an_earlier_day_is_not_fresh
  - tests/test_ohlcv_cache_freshness.py::test_load_ohlcv_refetches_stale_same_day_cache
note: Only the three known date-sensitive cache tests failed. The network-
      reachability baseline (RISK-002) did NOT fail on this run, consistent with
      prior re-runs (logbook 047, 052) where it sometimes passes depending on the
      day/network. Focused comparison count grew 73 -> 90 (exactly 17 new
      focused tests added); the full-suite passed count grew 1463 -> 1481 (+18)
      because those 17 new focused tests are now in the suite AND the previously
      failing variable network-reachability baseline passed on this run. No new
      regression; full offline suite is NOT claimed fully green.
status: Partial (pre-existing known date-sensitive failures remain; NOT a clean full-suite green)
source: Re-run
date: 2026-10-23
```

### 056 — Human review decision: Phase 4A approved with limitations (2026-10-23)

```text
decision: Phase 4A approved with limitations (human review).
reviewer: WANG Yiwen (Student ID 60536848)
date: 2026-10-23
note: Documented in docs/review-memo.md under "Phase 4A — Post-correction human
      review decision (2026-10-23)". This supersedes the prior "Changes
      requested" decision for the current phase status; the prior decision and
      the intervening correction-round records are retained verbatim as
      historical audit evidence.
evidence reviewed and accepted:
  - CaseResult.enforces fail-closed consistency among strategy /
    early_stopped / stop_reason.
  - FIXED cannot set early_stopped == True.
  - Dynamic early_stopped == True rejects input_exhausted, max_rounds_reached,
    empty, and unknown stop reasons; accepts only legitimate dynamic reasons.
  - Regression coverage: direct construction, JSON/from_dict deserialization,
    aggregate/report propagation.
  - 90 focused comparison tests passed.
  - Adversarial checks rejected all contradictory combinations; accepted a
    genuine dynamic budget_exhausted early stop.
  - Governance validator PASS (34/34, no secrets); governance scaffold tests
    16 passed; full-repo Ruff clean; git diff --check clean.
  - Full offline suite after the correction: 1481 passed, 2 skipped, 3 known
    date-sensitive cache failures, 22 warnings, 88 subtests. Suite is NOT
    completely green; the variable network-reachability baseline passed this run.
accepted limitations:
  1. Deterministic and offline; no live-provider performance benchmark.
  2. Three known date-sensitive cache failures remain; suite not completely green.
  3. Human traceability scores remain pending; must not be invented or entered.
  4. Final production threshold tuning not performed.
status: Approved with limitations (human decision recorded; no scores entered)
source: Re-run
date: 2026-10-23
```

### 057 — Documentation-only: v1.2 authoritative prompt + truthful current scope (2026-10-23)

```text
command: /usr/bin/shasum -a 256 prompts/prompt_v1.0.yaml prompts/prompt_v1.1.yaml
result (before): prompt_v1.0.yaml=d93c7400c9dd754782621c15c9cafeb41b6770a128d8eff4d6a1f886affdd38c
                  prompt_v1.1.yaml=56c8a8869bd4601645bfbae07a452ecac5314340c3d007943f9033497406fd2a
result (after):  unchanged (identical hashes) — v1.0/v1.1 were NOT modified.
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
note: scripts/validate/validate_requirements.py updated to include
      prompts/prompt_v1.2.yaml in REQUIRED_FILES and YAML_FILES (v1.2 is a
      required artifact and is YAML-parsed) and in SCAN_FILES (v1.2 is included
      in the deterministic secret scan). Artifact count 34 -> 35. The existing
      test_required_files_exist_and_nonempty loops REQUIRED_FILES, so no test
      change was required. The v1.0/v1.1 artifacts still exist and parse.
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed in 0.07s
status: Pass (expected)
source: Re-run
date: 2026-10-23
scope: Created prompts/prompt_v1.2.yaml (authoritative) from v1.1 with the sole
       binding-rule change being scope discipline: Phase 4A offline comparison
       completed and human-approved with limitations (WANG Yiwen 60536848,
       2026-10-23); Phase 4B, production threshold tuning, and unrequested
       features remain prohibited without separate explicit human authorization.
       Applied the same truthful scope to Prompt.md, AGENTS.md, .agent/rules.md,
       .opencode/rules.md, architecture-blueprint.md, and
       docs/architecture/permission-model.md, plus the current/authoritative
       startup-prompt reference in README.md (Report.md's v1.0 reference is a
       genuinely historical Phase 1 description and was preserved), and the
       governance validator (scripts/validate/validate_requirements.py) now
       includes prompts/prompt_v1.2.yaml in REQUIRED_FILES, YAML_FILES, and
       SCAN_FILES (v1.2 is a required artifact, YAML-parsed, and secret-scanned;
       34 -> 35; test_required_files_exist_and_nonempty loops REQUIRED_FILES so
       no test change was needed). Documentation/governance-only; no feature
       code, tests, or traceability scores changed; no commit/push/PR.
```

```text
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py \
  tests/test_comparison_runner.py tests/test_comparison_schemas.py -q
result: 106 passed in 0.52s
note: governance scaffold (16) + focused comparison tests (90) re-verified
      unchanged by this documentation-only change.
command: .venv/bin/ruff check .
result: All checks passed! (full repo)
command: git diff --check
result: clean (exit 0)
status: Pass (expected)
source: Re-run
date: 2026-10-23
```

## Note

The full offline suite is **not** currently reproducible as a clean green run in
this environment because of the date-sensitive cache tests (and, on some days or
networks, a network-reachability-dependent baseline test). The honest position
is to state the exact observed outcomes and the known failures, as done above,
rather than claim a blanket pass. The most recent re-run (entry 055, Phase 4A
narrow fail-closed correction) shows **3 failed (1481 passed, 2 skipped)** — the
3 date-sensitive cache failures only (RISK-001); the network-reachability
baseline (RISK-002) did not fail on this run, consistent with prior re-runs
(entries 047, 052) where it sometimes passes. An earlier re-run (entry 054,
Phase 4A correction round) showed **4 failed (1463 passed, 2 skipped)** — the 3
date-sensitive cache failures plus the network-reachability baseline failure.
The human review decision on the Phase 4A correction (entry 056, 2026-10-23) is
**Approved with limitations** — recorded in `docs/review-memo.md`; the full
offline suite is still not claimed completely green, and human traceability
scores remain pending.