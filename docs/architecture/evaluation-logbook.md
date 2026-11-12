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

### 058 — Blocked final-output enforcement (review finding 1) (2026-11-06)

```text
scope: Fix the 2026-11-06 independent-review High-priority defect reproduced in
       tradingagents_offline_demo.py: a blocked Data Quality Gate run routed
       correctly (Bull/Bear skipped, Research Manager rewrote Buy to Hold) but
       Trader -> risk debate -> Portfolio Manager still carried a model Buy into
       final_trade_decision, and SignalProcessor returned Buy. Added a single
       deterministic, LLM-free guard (tradingagents/agents/utils/output_guard.py)
       that (a) reads the gate state fail-closed (missing/malformed/inconsistent
       -> blocked) and (b) pins only the decision field (Recommendation / Rating
       / Action) to Hold on blocked runs, structured and free-text, preserving
       prose and recovery conditions. Wired into the Research Manager (via the
       shared guard; the prior local coercion was replaced), Trader, and Portfolio
       Manager. No numeric confidence ceiling was invented (review finding 4
       remains out of scope / recorded as debt). Adversarial Buy fixtures are
       deterministic enforcement tests, not a measured live incident.
command: .venv/bin/python -m pytest tests/test_output_guard.py -q
result: 47 passed in 0.48s (structured + free-text, full graph with a real
        blocked gate, missing/malformed gate state, normal/degraded preserved,
        report + final signal, legacy normal checkpoint, no invented cap)
command: .venv/bin/python -m pytest tests/test_research_manager_hold_contract.py \
  tests/test_structured_agents.py tests/test_structured_agent_prompts.py \
  tests/test_data_quality_gate_graph.py tests/test_debate_graph.py \
  tests/test_reporting.py tests/test_report_artifacts_stage2.py \
  tests/test_signal_processing.py tests/test_rating_integrity.py \
  tests/test_portfolio_context.py tests/test_cli_display.py \
  tests/test_debate_conflicts.py tests/test_researchers_verdict_gate.py \
  tests/test_output_guard.py -q
result: 294 passed in 1.67s
command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  /Users/wangyiwen/Documents/Codex/2026-10-19/https-github-com-1longlong-tradingagents-https/tradingagents_offline_demo.py
result: blocked_adversarial_model final_signal = "Hold" (was "Buy");
        manager_recommendation = "**Recommendation**: Hold" (unchanged)
command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
result: 3 failed, 1528 passed, 2 skipped, 22 warnings, 88 subtests in 5.49s.
        The 3 failures are the known pre-existing date-sensitive cache tests
        (RISK-001 / DEBT-001); the network-reachability baseline did not fail.
        No new regression. Full suite NOT claimed green.
command: .venv/bin/python -m ruff check tradingagents/agents tests/test_output_guard.py \
  tests/test_memory_log.py tests/test_research_manager_hold_contract.py \
  tests/test_structured_agents.py
result: All checks passed!
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: git diff --check
result: clean (exit 0)
status: Pass (expected)
source: Re-run
date: 2026-11-06
```

Three pre-existing tests were given an explicit trusted `normal` gate state
(`tests/test_memory_log.py::_make_pm_state`,
`tests/test_structured_agents.py::_make_trader_state`,
`tests/test_research_manager_hold_contract.py::test_non_blocked_run_is_not_forced_to_hold`)
because they drive the Trader/Portfolio Manager/Research Manager directly and
predate the gate; a bare or missing gate state now fails closed by design.
Their assertions are unchanged.

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

Re-run entries (2026-11-06): entry 058 (blocked final-output enforcement) showed
**3 failed (1528 passed, 2 skipped)**; entries 059–061 (guard edge cases,
pre-call budget guards, audit exports) raised the passing count to **1562**;
entry 063 (second-review budget boundary + audit compatibility) raises it to
**1578**, with the same 3 date-sensitive cache failures only (RISK-001). A
separate stricter fully offline run (entry 064, socket.connect disabled,
`-m "not integration"`) observed **4 failed / 1577 passed / 1 skipped / 1
deselected**, the four failures being the 3 date-sensitive cache tests plus the
known Yahoo reachability/exception-type baseline; that stricter run is recorded
separately and does not replace entry 063.
### 059 — Guard edge cases: compatibility marker + repeated headers + blocked sizing (2026-11-06)

```text
scope: Operator technical review (not human phase approval) reproduced two guard
       edge cases: (1) enforce_blocked_conclusion('FINAL TRANSACTION PROPOSAL:
       **BUY**', field='action') prepended Hold but left the executable BUY
       because the no-header branch returned before pinning the compatibility
       marker; (2) repeated decision headers kept later directional calls
       ('Action: Buy / Action: Sell' -> 'Action: Hold / Action: Sell'; two Rating
       headers likewise left Sell). Fix: pin EVERY recognized decision header and
       EVERY FINAL TRANSACTION PROPOSAL form regardless of whether a primary
       header exists; tolerate common Markdown bullet/heading/value markup around
       the decision field only (ordinary rationale prose is never rewritten); add
       a documented narrow rule neutralising executable entry/stop/position
       sizing on a blocked Trader while preserving quoted rationale; keep
       idempotence.
command: .venv/bin/python -m pytest tests/test_output_guard.py -q -p no:cacheprovider
result: 55 passed in 0.80s (adds compatibility-marker-without-header, markup
        tolerance, repeated-header, blocked-sizing, idempotence regressions)
command: .venv/bin/python -m pytest tests/test_output_guard.py \
  tests/test_research_manager_hold_contract.py tests/test_structured_agents.py \
  tests/test_memory_log.py -q -p no:cacheprovider
result: 184 passed in 0.71s
status: Pass (expected)
source: Re-run
date: 2026-11-06
```

### 060 — Pre-call budget guards (review finding 2) (2026-11-06)

```text
scope: The review reproduced an over-budget optional call: max_calls=1 executed
       Bull and Bear (2 calls) before the evaluator emitted budget_exhausted. Add
       a conservative pre-call admission guard (can_afford_optional_call) checked
       before every Bull and every Bear so an optional call that would breach the
       call hard limit or consume the reserved summary capacity is never made.
       A refused call writes a budget_exhausted admission decision and a new
       researcher-step router skips safely to the Research Manager for the
       incomplete round. enabled=False keeps the legacy fixed-round baseline and
       is not subject to the dynamic guard. Usage remains an honest estimate
       (estimated=True); no physical provider bounds are claimed.
command: .venv/bin/python -m pytest tests/test_debate_precall_budget.py -q -p no:cacheprovider
result: 14 passed (max_calls=1 runs exactly one call; zero remaining capacity
        refuses; two calls admits both then evaluates; disabled compatibility;
        summary reserve preserved; incomplete-round skip with budget_exhausted)
command: .venv/bin/python -m pytest tests/test_debate_precall_budget.py \
  tests/test_debate_budget.py tests/test_debate_graph.py \
  tests/test_debate_evaluator.py tests/test_debate_config.py \
  tests/test_debate_turn.py tests/test_debate_evidence_manifest.py \
  tests/test_debate_opening.py -q -p no:cacheprovider
result: 171 passed in 0.73s
command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  /Users/wangyiwen/Documents/Codex/2026-10-19/https-github-com-1longlong-tradingagents-https/tradingagents_offline_demo.py
result: budget_boundary -> configured_max_calls=1, actual_debate_calls=1 (was 2),
        stop_reason=budget_exhausted
status: Pass (expected)
source: Re-run
date: 2026-11-06
```

### 061 — Audit exports: per-evidence validations + run-summary identity/provenance (review finding 3) (2026-11-06)

```text
scope: The review reproduced an audit gap: data_quality_validation_results had 5
       evidence entries but every exported evidence_manifest record had empty
       validation_results, and run_summary omitted run_id, asset_type, snapshot
       ID, per-record quality counts, tool calls, and separate input/output token
       counts. Fix: evidence_manifest.json now attaches each record's own
       validations by evidence_id AND exports the separate
       validation_results_by_evidence_id map; run_summary.json adds run_id /
       asset_type / snapshot_id (null when unavailable), quality_counts (explicit
       zeros, unknown bucket), and usage_provenance where debate calls are
       reported separately from total-run calls and unmeasured tool /
       input-output counts are explicit None (never fabricated or conflated).
       Deterministic ordering, redaction, and legacy safe defaults preserved.
command: .venv/bin/python -m pytest tests/test_report_artifacts_audit.py -q -p no:cacheprovider
result: 12 passed (per-record validation association, separate map export,
        legacy empty, redaction, identity/quality/usage provenance, deterministic
        byte-identical roundtrip, no analyst prose)
command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  /Users/wangyiwen/Documents/Codex/2026-10-19/https-github-com-1longlong-tradingagents-https/tradingagents_offline_demo.py
result: audit -> state_records_with_validation=5,
        exported_record_validation_counts=[7,7,7,7,6] (was [0,0,0,0,0])
status: Pass (expected)
source: Re-run
date: 2026-11-06
```

### 062 — Maintenance verification after guard/budget/audit corrections (2026-11-06)

```text
command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
result: 3 failed, 1562 passed, 2 skipped, 22 warnings, 88 subtests in 6.12s.
        The 3 failures are the known pre-existing date-sensitive cache tests
        (RISK-001); no new regression; full suite NOT claimed green.
command: .venv/bin/ruff check .
result: All checks passed! (full repo)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: git diff --check
result: clean (exit 0)
status: Pass (expected)
source: Re-run
date: 2026-11-06
```

The autonomous multi-category adapters (broader original-design item 5) remain
explicitly out of scope and open; these maintenance milestones do not implement
them.

### 063 — Second review: budget reserve+estimate boundary + audit compatibility (2026-11-06)

```text
scope: An independent second review (81 new regression tests passed) reproduced
       one remaining budget bug and two audit-compatibility issues. (1) Budget:
       with max_tokens=10000, reserved_summary_tokens=1000,
       next_round_estimate_tokens=2000, max_time=100000, usage tokens=9000,
       can_afford_optional_call returned True though remaining tokens (1000) were
       exactly the reserve; the same held when remaining seconds equalled
       reserved_summary_seconds. The check compared remaining only to the reserve,
       not reserve + estimated next-call cost. Fixed: the preflight now requires
       remaining >= reserved_summary_* + next-call estimate (half the configured
       next-round estimate, rounded up for tokens), recorded as `estimated`
       `debate_calls_only`. (2) Audit: _records_with_validations overwrote a
       record's embedded validation_results with [] when the separate map lacked
       an entry, dropping legitimate legacy/embedded validations. Fixed: prefer a
       present authoritative map entry, otherwise preserve/normalize the record's
       own embedded validations; never attach another ID's result; keep
       deterministic record/key ordering. (3) Identity: disagreeing run_id /
       snapshot_id is now marked ambiguous (value None, `identity_ambiguous` flag)
       instead of silently choosing a first identity; removed the inaccurate
       comment that the adapter mints snapshot_id (null until a real snapshot
       identity is recorded).
command: .venv/bin/python -m pytest tests/test_debate_precall_budget.py -q -p no:cacheprovider
result: 22 passed (adds exact reserve-only refusal, reserve+estimate token and
        second boundaries, before-first-Bull and before-Bear graph boundaries,
        estimate_basis/scope tracing)
command: .venv/bin/python -m pytest tests/test_report_artifacts_audit.py -q -p no:cacheprovider
result: 20 passed (adds legacy embedded-only preservation, authoritative-map
        override, single-dict normalization, shuffle-invariant ordering,
        ambiguous run_id/snapshot_id, default snapshot_id null)
command: .venv/bin/python -m pytest tests/test_debate_precall_budget.py \
  tests/test_report_artifacts_audit.py tests/test_report_artifacts_stage2.py \
  tests/test_reporting.py tests/test_debate_budget.py tests/test_debate_graph.py \
  tests/test_debate_evaluator.py tests/test_output_guard.py -q -p no:cacheprovider
result: 185 passed in 0.71s
command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
result: 3 failed, 1578 passed, 2 skipped, 22 warnings, 88 subtests. The 3
        failures are the known pre-existing date-sensitive cache tests
        (RISK-001); the network baseline did not fail; no new regression; full
        suite NOT claimed green.
command: .venv/bin/ruff check .
result: All checks passed! (full repo)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: git diff --check
result: clean (exit 0)
status: Pass (expected)
source: Re-run
date: 2026-11-06
```

### 064 — Operator/AI technical verification: stricter fully offline suite (2026-11-06)

```text
scope: Operator/AI technical verification only (NOT a human approval). A stricter
       fully offline run was executed with socket.socket.connect patched to raise
       OSError('Network disabled for offline verification') and invoked via
       pytest.main(['-q','-p','no:cacheprovider','-m','not integration']).
       Independently verified prior to this note: 464 focused tests passed in
       1.82s across output guard, pre-call budget, audit, gate, debate, conflicts,
       reporting and comparison; the offline demo returns final_signal=Hold on the
       blocked adversarial-model run; max_calls=1 gives actual_debate_calls=1;
       evidence validation counts export as [7,7,7,7,6]; independent Ruff,
       governance validator (35/35, no likely secrets) and git diff --check pass.
command: pytest -q -p no:cacheprovider -m "not integration"
         (with socket.socket.connect -> OSError('Network disabled for offline verification'))
result: 4 failed, 1577 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
        passed in 4.76s.
        Failures: tests/test_no_data_handling.py::TestLoadOhlcvNoPoison::
        test_empty_download_raises_and_does_not_cache (known Yahoo
        reachability/exception-type baseline) and the 3 known
        tests/test_ohlcv_cache_freshness.py date-sensitive cache tests.
note: This is recorded as a SEPARATE run under stricter connectivity conditions
      from the earlier 3-failure run (entry 063, differing connectivity); history
      is not erased and neither run is claimed all-green. Operator/AI technical
      verification, not a human approval.
status: Partial (known pre-existing baseline failures; no new regression)
source: Supplied (independently verified by the operator; not re-run in this change)
date: 2026-11-06
```

### 065 — Independent recheck 2026-11-06: fixes for findings 1/2/3 (2026-11-06)

```text
scope: In-scope maintenance authorized by the operator: fix the three defects
       independently reproduced in the recheck review (blocked-signal escape for
       alternative rating headers; real gate -> manifest -> debate quality
       propagation; Hold/prose separator). Previous uncommitted guard/budget/
       audit changes preserved. No commit/push/merge/PR; no new providers; no
       production tuning; offline synthetic tests only.
command: .venv/bin/python -m pytest tests/test_output_guard.py tests/test_gate_debate_integration.py
         tests/test_data_quality_gate_graph.py tests/test_debate_graph.py
         tests/test_debate_evidence_manifest.py tests/test_debate_evaluator.py
         tests/test_debate_turn.py tests/test_researchers_verdict_gate.py
         tests/test_memory_log.py tests/test_signal_processing.py
         tests/test_rating_integrity.py tests/test_report_artifacts_audit.py
         tests/test_report_artifacts_stage2.py tests/test_debate_precall_budget.py -q
result: 412 passed (tests/test_output_guard.py 79, tests/test_gate_debate_integration.py 9)
command: pytest -q -p no:cacheprovider -m "not integration"
         (with socket.socket.connect -> OSError('Network disabled for offline verification'))
result: 4 failed, 1610 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
        passed in 4.87s. Failures: the SAME known baselines (the 3
        tests/test_ohlcv_cache_freshness.py date-sensitive cache tests and the
        Yahoo-reachability/exception-type baseline
        test_empty_download_raises_and_does_not_cache). No new failure; not
        claimed all-green.
command: .venv/bin/ruff check .
result: All checks passed! (full repo)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: git diff --check
result: clean (exit 0)
note: Phase 4A scripted numbers remain labelled scripted and are NOT presented as
      proof of runtime integration; finding 2's runtime integration is proven by
      tests/test_gate_debate_integration.py (real gate node), not by the Phase 4A
      scripted fixtures. These 2026-11-06 fixes await explicit human review.
status: Pass (expected; known baselines remain)
source: Re-run
date: 2026-11-06
```

### 066 — Operator recheck follow-up: parser/guard agreement (2026-11-06)

```text
scope: Independent operator review after logbook 065 found a residual in the
       CURRENT guard: enforce_blocked_conclusion('Ｒａｔｉｎｇ：Ｂｕｙ') and
       ('My final overall investment rating: Buy') still parsed as Buy on the
       plain (textual) signal because the guard matched a bounded descriptor list
       and only the fullwidth colon, not fullwidth letters/value; the structured
       signal was safe but the saved report text and memory DECISION body could
       contradict the Hold tag. Narrow correction: the guard now uses the rating
       parser's own shared NFKC/label recognition (labelled_decision_tail) to
       canonicalise every line the parser reads as a labelled rating call to
       '**Rating**: Hold', preserving a natural-language rationale tail. No
       policy or optional-adapter change. Note: cli/main.py is byte-identical to
       HEAD (the earlier state-argument edit was fully reverted); the signal
       boundary is reached via TradingAgentsGraph.process_signal(curr_state), so
       there is no CLI change in this tree.
command: .venv/bin/python -m pytest tests/test_output_guard.py tests/test_gate_debate_integration.py
         tests/test_data_quality_gate_graph.py tests/test_debate_graph.py
         tests/test_debate_evidence_manifest.py tests/test_debate_evaluator.py
         tests/test_debate_turn.py tests/test_researchers_verdict_gate.py
         tests/test_memory_log.py tests/test_signal_processing.py
         tests/test_rating_integrity.py tests/test_report_artifacts_audit.py
         tests/test_report_artifacts_stage2.py tests/test_debate_precall_budget.py
         tests/test_structured_agents.py tests/test_research_manager_hold_contract.py
         tests/test_cli_decision_log.py -q
result: 480 passed (tests/test_output_guard.py 90, tests/test_gate_debate_integration.py 9)
command: pytest -q -p no:cacheprovider -m "not integration"
         (with socket.socket.connect -> OSError('Network disabled for offline verification'))
result: 4 failed, 1621 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
        passed in 5.72s. Failures: the SAME known baselines (3 date-sensitive
        cache tests + Yahoo reachability/exception-type baseline). No new
        failure; not claimed all-green.
command: .venv/bin/ruff check .
result: All checks passed! (full repo)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: git diff --check
result: clean (exit 0)
note: Operator technical feedback recorded, NOT a human approval. Fullwidth
      label+value, arbitrarily prefixed labels, repeated/trailing labels,
      full-graph report+memory tag/body consistency covered; natural-language
      separator and idempotence retained; normal/degraded unchanged. Phase 4A
      scripted numbers remain labelled scripted. Degraded confidence ceiling
      (DEBT-014) and automatic optional adapters (DEBT-015/RISK-015) remain OPEN.
status: Pass (expected; known baselines remain)
source: Re-run
date: 2026-11-06
```

### 067 — Operator executable-instruction maintenance (2026-11-06)

```text
scope: Operator-authorized narrow maintenance: executable directional
       instructions (fullwidth/NFKC labels and values, long decision-label
       descriptors, repeated/trailing headers, fullwidth entry/stop/position
       sizing, and 'FINAL TRANSACTION PROPOSAL: BUY because ...' markers) must
       not survive a blocked Data Quality Gate in the stored intermediate
       Trader/Research plans. Fixed with one shared LINEAR recognizer
       (tradingagents/agents/utils/rating.py: decision_header/_split_header —
       NFKC-first, arbitrary plain descriptor with no cap, required separator,
       single-word value; blockquote/narrative mentions excluded). The guard
       pins every decision field to '**<Label>**: Hold', neutralises blocked
       sizing to 'not applicable', pins explained proposal markers preserving
       the tail, and stays idempotent; rationale/quoted alternatives/recovery
       are preserved. extract_rating now takes the last structural header as
       authoritative before its looser fallback so the plain textual signal,
       report decision and memory body agree. No CLI change (cli/main.py
       unchanged); no policy/optional-adapter change. Interruptions during the
       work (catastrophic backtracking in a first regex; empty-tail/cap design;
       parser/guard disagreement) were all corrected in this same pass.
command: .venv/bin/python -m pytest tests/test_output_guard.py -q
result: 130 passed
command: .venv/bin/python -m pytest tests/test_output_guard.py
         tests/test_gate_debate_integration.py tests/test_data_quality_gate_graph.py
         tests/test_debate_graph.py tests/test_debate_evidence_manifest.py
         tests/test_debate_evaluator.py tests/test_debate_turn.py
         tests/test_researchers_verdict_gate.py tests/test_memory_log.py
         tests/test_signal_processing.py tests/test_rating_integrity.py
         tests/test_report_artifacts_audit.py tests/test_report_artifacts_stage2.py
         tests/test_debate_precall_budget.py tests/test_structured_agents.py
         tests/test_research_manager_hold_contract.py tests/test_cli_decision_log.py -q
result: 520 passed
command: pytest -q -p no:cacheprovider -m "not integration"
         (with socket.socket.connect -> OSError('Network disabled for offline verification'))
result: 4 failed, 1661 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
        passed in ~6s. Failures: the SAME known baselines (3 date-sensitive
        cache tests + Yahoo reachability/exception-type baseline). No new
        failure; not claimed all-green.
command: .venv/bin/ruff check .
result: All checks passed! (full repo)
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no likely
        secrets found; RESULT: PASS
command: git diff --check
result: clean (exit 0)
note: Operator technical verification recorded, NOT a human approval. Fullwidth
      label/value and sizing separators, arbitrary/long prefixes, repeated/
      trailing labels, proposal 'BUY because ...', Markdown wrapping,
      rationale/recovery/quoted-alternative preservation, idempotence, long-line
      performance and a full blocked graph (stored Trader/Research plans + saved
      report) are covered. Phase 4A scripted numbers remain labelled scripted.
      CLI state-passing gap, degraded confidence ceiling (DEBT-014) and automatic
      optional adapters (DEBT-015/RISK-015) remain OPEN.
status: Pass (expected; known baselines remain)
source: Re-run
date: 2026-11-06
```

### 068 — Documentation/requirements revision: schema + PRD + register + prompt v1.3 (2026-11-06)

```text
scope: documentation-only revision authorized by the human (no source/tests/CI/
       active-config change). Extended docs/req/req-schema.json (product/PRD,
       per-requirement fit_criterion with type-consistency conditionals,
       priority_rationale, tradeoff, origin, category, deferred_scope) and
       docs/req/requirements.yaml (22 IDs preserved; schema_version v1.0 -> v1.1,
       additive). Expanded invariants register; added proposed ADR-004; role-by-
       path permission model + non-active proposal; human-only rules proposal;
       CI gate matrix (document only); authoritative prompts/prompt_v1.3.yaml
       (plan-first STOP); Prompt.md anchor updated. Fixed stale status (Phase 4A
       approved with limitations; 8abea81 pushed; current work uncommitted).
command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 35/35 valid, 0 invalid; secret scan: no
        likely secrets found; RESULT: PASS
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed
command: jsonschema Draft202012Validator over requirements.yaml (local probe)
result: 0 errors; negative mutations (count-threshold float/negative, boolean
        threshold as number, numeric-threshold string, boolean with >=, blank
        metric, missing fit_criterion/metric/unit/verification/priority_rationale/
        tradeoff) all REJECTED
command: .venv/bin/python -m ruff check .
result: All checks passed!
command: git diff --check
result: clean (exit 0)
status: Pass (expected; schema fallback limitation documented)
source: Re-run
date: 2026-11-06
```

Note: `prompt_v1.3.yaml` is authoritative in `Prompt.md` but is **not** yet in the
validator's `REQUIRED_FILES`/`YAML_FILES`; the validator/scripts were NOT edited
to force a change (DEBT-024). The shipped `.opencode/permissions.jsonc` is
UNCHANGED. No human approval or traceability score is recorded; the revision
awaits human review.

### 069 — Independent operator recheck of the 2026-11-06 documentation revision (AI technical, NOT human approval)

```text
scope: Independent operator recheck of the documentation/requirements revision
       (read-only helper at .../verify_governance_docs.py; source/tests/CI
       unchanged). Recorded as AI technical evidence, NOT human approval.
result: 22/22 requirements pass the real draft-2020-12 schema; 440 missing-field /
        invalid-type / threshold-consistency mutations REJECTED; all new YAML
        parses; 22 trace-matrix runtime/audit-monitor rows present.
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 16 passed
command: strict fully offline suite (socket.socket.connect disabled,
         pytest -q -p no:cacheprovider -m "not integration")
result: 4 failed, 1661 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests in 7.10s
        — the SAME four known baselines (3 date-sensitive cache tests +
        the known Yahoo reachability baseline). No new regression. NOT all-green.
status: Pass (technical; 4 known baselines remain)
source: Supplied (operator-verified) + Re-run
date: 2026-11-06
note: The four failures are UNRESOLVED; per the CI gate matrix (G8) a nonzero
      full-regression exit BLOCKS by default and no exception policy is granted.
```

Documentation-only corrections applied in this round (no feature/code/test/CI
change): corrected stale "active config" wording (blueprint/permission-model now
say existing shipped file, loading/enforcement unverified); corrected SDK/plugin
provenance (`~/.config/opencode/package.json` pins `@opencode-ai/plugin` at
1.18.25, not sdk; sdk present transitively; binary 1.18.25); strengthened CI
gates G4 (`pip check` + `deptry`; import smoke insufficient), G5 (tamperproof
external human approval provenance, no retrospective preapproval), G8 (nonzero
exit blocks; recorded failures do not make green); rewrote
`runtime-policy-catalog.md` to state reserve is checked before EVERY Bull/Bear
admission, debate-only scope, estimate-based accounting with the DEBT-021 live
discrepancy, and a trigger→action→audit→recovery table with explicit PENDING where
no fallback exists.

### 070 — November 10 repair batch: multiline guard containment, empty-map override, shared ID uniqueness (AI technical, NOT human acceptance)

```text
scope: Human-approved repair plan + test cases ("批准本轮修复计划和测试用例",
       2026-11-10). Plan/test authorization only, NOT acceptance. Three
       independently reproduced defects fixed with failing regression tests
       first. Branch feature/data-quality-debate-control, base HEAD 8abea81;
       all pre-existing dirty work preserved.

defect 1 (output_guard.py): a blocked Trader output's executable multiline
  instructions survived a prepended Hold. Reproduced on the current tree:
  '**Action**:\nBuy\n**Entry Price**: $100\n**Position Sizing**: 10%',
  'FINAL TRANSACTION PROPOSAL:\nBUY 100 shares at $100', and unsupported
  'Buy 100 shares at $100. Exit at $120.' all left executable direction/fill
  text in the stored plan. Fix: block-style label-only headers whose value is
  on a following physical line (blank lines skipped) are folded into a pinned
  Hold / HOLD marker / not-applicable sizing and the value line is dropped; an
  anchored executable-sentence fallback (trade verb at line start + quantity/
  price token) fails closed for unsupported formats, while quoted spans,
  rationale markers (rejected/considered/historical/not-executed/etc.) and
  blockquotes are preserved verbatim. Linear token scan; idempotent; LF/CRLF/
  whitespace/Markdown/fullwidth tested.

defect 2 (report_artifacts.py): _validation_map dropped explicitly empty
  authoritative per-evidence lists, so _records_with_validations preserved a
  stale embedded passed check. A PRESENT {id: []} (including a malformed value
  that cannot carry a validation) now overrides embedded to []; an ABSENT entry
  keeps the legacy embedded fallback. Nonempty overrides, no cross-ID leakage,
  deterministic ordering, redaction preserved; helper + saved artifact tested.

defect 3 (scripts/validate/validate_requirements.py): the real jsonschema path
  accepted duplicate requirement IDs the fallback rejected (uniqueItems compares
  whole objects). A shared validate_unique_requirement_ids() now runs on BOTH
  entry paths; the fallback uses the same helper (per-row loop only checks
  presence/shape). Duplicate IDs with differing objects rejected on the real and
  forced-fallback paths; valid unique registry still passes; malformed rows
  handled without crashing. The 22 existing IDs and schema constraints are
  untouched (no hardcoded count).

commands / results (all re-run on the working tree):
  pytest tests/test_output_guard.py tests/test_report_artifacts_audit.py
         tests/test_governance_scaffold.py -q
    -> 219 passed (includes 24 + 14 multiline/boundary regressions and 11
       report/validation regressions)
  focused affected suite (guard + audit + governance + gate-debate + memory +
         hold-contract + structured + pre-call)
    -> 379 passed
  strict fully offline suite (socket.socket.connect -> OSError,
         pytest -q -p no:cacheprovider -m "not integration")
    -> 4 failed, 1714 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
       in 6.40s — the SAME four known baselines (test_no_data_handling empty-
       download + 3 date-sensitive ohlcv-cache-freshness). No new regression.
       NOT all-green.
  ruff check (changed source + tests) -> All checks passed
  scripts/validate/validate_requirements.py -> PASS (35/35, no secrets)
  git diff --check -> clean

red-test evidence (honest): the three defects' failing regression tests were
  written and observed failing BEFORE each fix (e.g. defect-2 present-empty and
  defect-3 duplicate-object cases failed; the defect-1 multiline cases failed
  with the executable text surviving). The boundary variants requested in the
  in-progress review (blank physical line between label and value, direction+
  explanation value, split sizing, quoted/negated historical rationale, long
  repeated direction-token lines) were also written and observed FAILING (12
  failed) before the blank-line-skip and quoted-rationale guards were added;
  they pass after the fix. No test is retroactively claimed to have run before a
  fix it did not precede.

second in-progress review correction (2026-11-10): the reviewer reproduced that
  bulleted/numbered Markdown direction values (``Action:`` newline ``- Buy`` /
  ``1. Buy``) still survived, that the blanket ``any rationale keyword or any
  quote`` exemption was unsafe (``Buy 100 shares at $100 because the earlier
  forecast improved;`` and ``Buy 100 shares at $100; analyst says "good value"``
  remained live commands), and that a multiline ``Buy because ...`` explanation
  was silently discarded. Fix: (a) the bare-direction / direction-lead value
  recognisers tolerate a bullet/number/heading prefix; (b) exemption from the
  anchored executable-sentence containment is now STRUCTURAL only -- a command
  is exempt only when the leading trade verb sits *inside* a quoted span, or the
  line does not lead with a command verb (unanchored prose such as ``We rejected
  "Buy ..."`` / ``Earlier proposal: Buy ... It was not executed.``); a live
  command is contained even if it later mentions ``earlier``/``considered`` or an
  incidental quotation; (c) a direction value's explanation is preserved as the
  rationale tail (``**Action**: Hold because valuation is attractive.``). These
  new boundary tests were observed failing before the correction, then passing.
  Updated counts: guard suite 183 passed; focused affected suite 394 passed;
  strict fully offline suite 1729 passed / 1 skipped / 1 deselected / 4 known
  baselines. Ruff clean; validator PASS; diff-check clean.

final F1 review blockers (2026-11-10): the reviewer reproduced that
  `Action: Buy 100 shares at $100 because valuation is attractive` became
  `**Action**: Hold 100 shares at $100 because ...` (executable position/price
  kept in the decision field), same-line `Action: Buy 100 shares at $100` too, and
  `Action:` newline `**Strong Buy**` survived as a directive. Fix: (a)
  `_safe_decision_tail` strips an executable sizing/price/quantity tail (and a
  residual direction-word tail such as `Strong Buy` -> value `Strong`, tail `Buy`)
  from a recognised decision value, keeping only a clearly separated rationale
  clause (`because`/`since`/`as`/...): `Action: Buy 100 shares at $100 because
  valuation is attractive` -> `**Action**: Hold because valuation is attractive`;
  `Action: Buy 100 shares at $100` -> `**Action**: Hold`. (b) a bounded
  unsupported-value fail-closed policy (`_UNSUPPORTED_VALUE_RE`: <=3 emphasis-
  wrapped letters) drops an unrecognised value-like line in a recognised
  decision value position (`**Strong Buy**` / `Strong Buy` / `Strong Sell now`) and
  pins the header to Hold, rather than trusting an unrecognised direction variant.
  The executable-tail detector was tightened to quantity/price/size and a pure
  residual direction word (NOT bare rationale adjectives), so a long ordinary
  line (`The analyst said the Rating: Buy case was weak.`) keeps its rationale and
  the prior long-prose test still passes. New direct + fake-Trader regressions and
  a normal/degraded-unchanged assertion were added (observed failing before the
  fix, then passing). Final counts: `tests/test_output_guard.py` 197 passed;
  strict fully offline suite 1743 passed / 1 skipped / 1 deselected / 4 known
  baselines; Ruff clean; validator PASS; diff-check clean. F1 feature changes
  stop here; documentation/traceability consistency is deferred to the separately
  approved next batch.

status: Pass (technical; 4 known baselines remain; awaits independent review and
        later human acceptance — acceptance is NOT claimed)
date: 2026-11-10
```

### 071 — November 10 documentation/traceability consistency batch (AI technical, NOT human acceptance)

```text
scope: Second half of the HUMAN-APPROVED 2026-11-10 repair plan (plan/test
       authorization only, NOT acceptance). Documentation/traceability
       consistency repairs; NO feature rewrites. Branch
       feature/data-quality-debate-control, base HEAD 8abea81; all pre-existing
       dirty work (incl. the first batch's guard/report/validator fixes)
       preserved.

1. verification-constraints.md: the three verification TIERS are now
   Structural / Regression / Behavioral; offline-vs-live is a SEPARATE evidence
   AXIS (never a substitute tier, never proof of live behavior). No other doc
   used the old tier vocabulary, so no further correction was needed.

2. Traceability tags: all 29 test files mapped by the 22 requirements now carry
   an ACCURATE "Traceability:" declaration of their own ID (and only
   invariants that genuinely apply). No new acceptance/metric/ID invented.
   New deterministic governance regressions in tests/test_governance_scaffold.py
   (TestMappedTestTraceability) verify each mapped file exists, declares a
   resolvable tag, and declares the requirement's OWN ID; INV-11/12/14 honest
   status asserted.

3. permission-model.md aligned with agent-permissions-proposal.yaml: builder
   edit allowlist now includes the explicitly approved documentation/validator
   paths (AGENTS.md, architecture-blueprint.md, Prompt.md, prompts/**, adr/**,
   .agent/rules.md, scripts/validate/**); planner execute intent (read-only) vs
   the expressible deny-all bash map is documented as a deliberate conservative
   mismatch. Proposal ONLY, active_configuration false; .opencode JSONC/rules,
   .github/**, pyproject untouched. No role/path enforcement is claimed.

4. Requirements validator: narrow dangling-reference validation
   (validate_requirement_references) for the product priorities/tradeoffs
   requirement_id contract runs on BOTH the real-schema and fallback paths (no-op
   for minimal schemas). In-progress-review correction: forced-fallback tests now
   patch _detect_jsonschema itself in an ISOLATED monkeypatch.context (a plain flag
   patch is reset by _detect_jsonschema every call), spy the fallback helper to
   PROVE it is invoked, make the real Draft202012Validator raise if reached, and
   assert a SEPARATE restored context reaches the real validator (spy asserts it)
   and never the fallback; non-string/malformed IDs are routed through the actual
   dispatcher. Each branch asserts it was independently reached. Documented the
   combined entry point.

5. Validator required-artifact + YAML inventory now includes prompt_v1.3.yaml,
   ADR-004/ADR-005, and the permission/CI/human-rule PROPOSALS (presence/parse
   only, NOT enforcement/implementation). NFR-OFF-001 now uses a documented
   count-and-fail harness (scripts/validate/strict_offline_harness.py) that
   COUNTS and asserts forbidden socket attempts (and propagates pytest's own exit
   so a red suite is never hidden). structural-constraints.md now acknowledges the
   existing src/test pointer README dirs and that the course layout exception still
   requires human confirmation.

5b. Proposal consistency (in-progress-review correction): builder.edit included
   .agent/rules.md but builder.read omitted it (read-before-edit violation); all
   role read lists now include .agent/rules.md and README.md/Report.md, and every
   editable path is readable (excluding human-only/frozen). Documented as a
   process invariant (schema cannot enforce it); active config unchanged.

command: .venv/bin/python scripts/validate/validate_requirements.py
result: required artifact presence 42/42 valid, 0 invalid; secret scan: no
        likely secrets found; RESULT: PASS
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py -q
result: 48 passed (adds forced-fallback both-branch, dangling-reference,
        harness-logic, mapped-traceability, inventory and proposal-consistency
        regressions)
command: .venv/bin/python -m pytest <29 mapped files + governance> -q
result: 1000 passed, 2 warnings
command: .venv/bin/python -m pytest tests/test_governance_scaffold.py
        tests/test_output_guard.py tests/test_report_artifacts_audit.py
        tests/test_gate_debate_integration.py -q
result: 282 passed
command: .venv/bin/python scripts/validate/strict_offline_harness.py
         (counts socket.socket.connect/connect_ex/create_connection)
result: 4 failed, 1768 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
        passed — the SAME 4 known baselines (3 date-sensitive ohlcv cache +
        tests/test_no_data_handling empty-download vendor-reachability).
        NFR-OFF-001 VIOLATION: 1 forbidden network connection attempt observed
        (from tests/test_no_data_handling.py::TestLoadOhlcvNoPoison::
        test_empty_download_raises_and_does_not_cache via requests/urllib3
        vendor reachability) — NO connection was made, but the attempt count is
        NOT zero, so NFR-OFF-001 stays PARTIAL/OPEN (DEBT-002/RISK-002). The
        run is NOT all-green.
command: .venv/bin/python -m ruff check tests/ scripts/validate/ tradingagents/ cli/
result: All checks passed!
command: git diff --check
result: clean (exit 0)
status: Pass (technical documentation/traceability; 4 known baselines + 1
        intercepted-offline attempt remain; awaits independent review and later
        human acceptance — acceptance NOT claimed)
source: Re-run
date: 2026-11-10
```

Review-completeness corrections applied in-batch (no source behavior change):
`docs/review-memo.md` top "Current status" now says as of 2026-11-10 with the
plan-only human approval, present AI technical checks, final acceptance pending,
and the unresolved 4 baselines + 1 intercepted socket attempt (historical
sections preserved). Root `README.md`/`Report.md` synced to the same truthful
status. The INACTIVE permission proposal now reflects scoped approved root-doc
edit intent (README.md/Report.md editable only under the `builder.edit.root_docs`
precondition, read-before-edit holds); active_configuration stays false and no
actual permission was changed or activated.

### 072 — Independent Codex AI verification of the 2026-11-10 doc/traceability batch (AI technical, NOT human acceptance)

```text
scope: Independent Codex AI verification on the CURRENT files after the
       doc/traceability consistency batch. Recorded as AI technical evidence,
       NOT human acceptance. No code/test change in this record.
result (current final; supersedes earlier intermediate in-batch counts):
  - 14-file focused suite: 583 passed / 2 warnings
  - governance validator: 42/42 PASS; doc secret scan: no hits
  - Ruff: clean; git diff --check: clean
  - independent boundary checks: 39/39 passed
  - independent negative schema mutations: 440 passed (rejected as expected)
  - scripts/validate/strict_offline_harness.py (actual run):
      4 failed, 1768 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests
      NFR-OFF-001 VIOLATION: 1 intercepted vendor-reachability attempt
      (same known tests/test_no_data_handling baseline; no connection made)
status: Pass (technical; 4 known baselines + 1 intercepted attempt remain;
        NFR-OFF-001 PARTIAL/OPEN; NOT all-green; awaits human acceptance)
source: Supplied (independent Codex AI verification)
date: 2026-11-10
note: Earlier in-batch intermediate runs (e.g. 48/1000/282 passed, 1765/1768 at
      intermediate moments) are kept historical; THIS entry is the current final
      recorded result, which is AI technical verification only — NOT human
      acceptance.
```

### 073 — User-authorized school-model live end-to-end run, recorded by Codex (2026-11-10; AI technical, NOT acceptance)

```text
scope: DOCUMENTATION-ONLY RECORDING of a user-authorized live end-to-end run by
       Codex on 2026-11-10. No source/tests/config/dependencies/CI/permissions/
       active-category change; no commit/push/PR; all pre-existing dirty work
       preserved. This OpenCode turn executed the documentation recording only
       (it did NOT run the model or any vendor endpoint; see the ai-use-log
       OpenCode recorder entry AUL-031).

harness: the EXISTING external live_school_verification.py (NOT a new
         feature/test). Endpoint llm.cs.cityu.edu.hk, model
         CS5351/DeepSeek-V4-Flash, NVDA historical trade_date 2026-11-05, four
         analysts, the full existing graph through Portfolio Manager / report /
         memory. Isolated output directory (external, not in this repo):
         /Users/wangyiwen/Documents/Codex/2026-10-19/
           https-github-com-1longlong-tradingagents-https/
           school-live-verification-jpd81pkd
         Credentials/config/auth were NOT read; only public artifacts were
         consulted (verification.json, report/run_summary.json,
         report/evidence_manifest.json, offline-boundary-recheck.json). No full
         unbounded state dump was taken.

live outcome (from the external callback-measured verification.json):
  - 16 application model calls, gateway-reported total 170,665 tokens, 0 output
    truncations. (This EXCLUDES OpenCode documentation-tool inference tokens.)
  - final state signal = Overweight; report textual signal = Overweight; the two
    are consistent (report_signal_consistent = true).
  - live Gate verdict = DEGRADED (NOT blocked): market Medium (5 evidence
    records, single source), fundamentals/news/sentiment each Low with reason
    unavailable_no_structured_source.
  - because the live Gate was DEGRADED (not blocked), the harness boolean
    blocked_signal_is_hold = true is VACUOUS (it is not-blocked OR signal==Hold).
    It is NOT live proof that the blocked-path handling works.

raw-export checks (verified here from the public artifacts):
  - 5 market evidence records and 5 validation-map IDs; every per-record
    validation set equals the authoritative state map; run identity present
    (run_id 2026-11-05/NVDA; identity_ambiguous all false; snapshot_id null).
  - Medium quality count = 5; the actual dynamic stop_reason is preserved in the
    report (debate_stop_reason = budget_exhausted, route = summarize).
  - report/run_summary.json honestly leaves total_run_calls / input_tokens /
    output_tokens / tool_calls NULL and reports only debate-only estimates:
    calls 1, tokens 15183, seconds 2024.4, estimated true.
  - Optional fundamentals/news/sentiment remain unavailable_no_structured_source
    despite narrative prose reports: this is the EXISTING automatic-adapter
    limitation (DEBT-015 / RISK-015). It is NOT claimed fixed.

REMAINING CONFIRMED ISSUE DEBT-021 (still OPEN; accounting basis defect):
  - Bull actual callback: elapsed 19.70 s, gateway total 16,931 tokens
    (input 14,969 / output 1,962).
  - runtime debate_usage instead estimated 15,183 tokens and 2,024.4 seconds,
    against max_time 600 s with reserved_summary 90 s / next_call_estimate 30 s.
  - the pre-call guard CORRECTLY refused Bear, but the badly inflated time
    estimate caused it to STOP PREMATURELY: the Bear node was visited yet ZERO
    actual Bear model calls occurred and bear_history is empty; stop_reason =
    budget_exhausted. The ACTUAL runtime (~19.7 s Bull) did NOT exceed 600 s —
    only the faulty 2,024.4 s ESTIMATE did. Do NOT claim the real runtime
    exceeded the cap.
  - overall 16 calls / 170,665 tokens are callback-measured; the report honestly
    keeps total_run_calls/input/output null and reports debate-only
    estimated calls 1 / tokens 15183 / seconds 2024.4.

secondary observation (REVIEW only; NOT a proven separate code defect):
  - the Research Manager prose says "the bear overplayed its hand" although no
    actual Bear response exists. Treated as a potentially misleading attribution
    to an unexecuted opponent, NOT evidence that a Bear call occurred. Flagged
    for human review; not recorded as a confirmed bug.

supplemental OFFLINE evidence (NOT live; NOT a blocked-path live test):
  - the EXISTING independent offline-boundary script was re-run by Codex:
    39/39 checks passed (real_model_calls = 0), including blocked multiline/
    fullwidth/bullet/sizing containment, empty-authoritative-map precedence,
    and real + forced-fallback duplicate-ID validation.
  - This is OFFLINE evidence only. It does NOT prove live blocked-path behavior,
    and NEITHER the normal live path NOR a fixed-vs-dynamic live benchmark is
    newly claimed by this record.

evidence boundary / honest limits:
  - single authorized NVDA/2026-11-05 run that ended DEGRADED (not blocked), with
    0 complete Bull/Bear rounds; the normal multi-round live path and the live
    blocked path were NOT exercised (RISK-023). Live integration is NOT
    all-bug-proof; this run does NOT establish that all model claims are
    factually accurate nor that all bugs are fixed.
  - human final acceptance remains PENDING (unchanged); no new approval,
    traceability score, or reflection is recorded here.

source: Supplied (Codex external live verification; recorded here read-only from
        the public artifacts and the Codex summary), NOT re-run by this OpenCode
        turn.
status: Partial (live evidence recorded honestly; DEGRADED not blocked; DEBT-021
        and the optional-adapter limitation remain OPEN; 0 complete rounds)
date: 2026-11-10
```

### 074 — DEBT-021/033 measured-budget + participation repair: independent verification and bounded school-model validation (2026-11-10; AI technical, NOT acceptance)

```text
scope: Independent verification of the CURRENT frozen tree (source/tests
       unchanged; fingerprint of 214 files unchanged across the live
       verification) plus a bounded real school-model validation of ADR-007.
       Documentation-only recording in this entry; no source/test edit, no git
       mutation, no human acceptance claimed or invented.

offline (independent, Codex): 639 focused offline tests passed; 0 forbidden
       socket attempts; 19/19 external boundary probes. Full canonical
       scripts/validate/strict_offline_harness.py: 1817 passed, 4 SAME known
       baseline failures (3 date-sensitive OHLCV cache + the intercepted
       baseline network baseline), 1 skipped, 1 deselected, 22 warnings, 88
       subtests, 1 intercepted baseline socket attempt (no connection). Ruff /
       governance (42/42, no likely secrets) / git diff --check clean.

live guards (shared across both scenarios): 32 requests / 250000 observed tokens
       / 4096 output tokens per call / 120 s per request / 1200 s wall; retries
       disabled (0 retries); no trades; no threshold tuning. Selected-case only,
       NOT exhaustive and NOT a Phase-4B benchmark. Credentials used only in
       runtime memory; no credential value emitted or persisted. Total: 25
       actual application calls, 228903 reported gateway tokens, 0 length
       truncations. Evidence backup:
       /Users/wangyiwen/OpenCodeRecords/TradingAgents/
         2026-11-10-school-budget-attribution-lahiq22h/ (verification.json +
         D1, D2 subtrees).

D2 (ran first) — blocked, controlled fixture: an EMPTY critical-market-record
       fixture at the REAL gate boundary plus a synthetic market analyst report
       (clearly NOT live-vendor data) then REAL school RM/Trader/risk/Portfolio
       nodes. 6 real model calls; Gate blocked; ZERO Bull/Bear invokes; Hold at
       RM/Trader/Portfolio/final/memory; no executable blocked Trader sizing;
       report bodies agree; participation explicitly data_quality_blocked;
       14/14 scenario checks passed. This is a NARROW controlled-fixture proof of
       the blocked path, NOT exhaustive and NOT a live-vendor blocked proof.

D1 — degraded, real vendors NVDA 2026-11-05: Gate degraded; Bull+Bear actually
       invoked; one complete round; stop_reason max_rounds_reached (NOT a
       premature budget_exhausted). Production debate_usage: 2 calls / 34744
       tokens (30902 input + 3842 output) / 34.056785748922266 seconds /
       estimated false / tokens_source provider / seconds_source measured /
       transport_attempts null (honestly unknown). Independent callback elapsed
       14.38 + 19.67 s and gateway totals match. Report/state/participation/stop
       consistency 7/7 checks passed. No all-agent production-usage
       instrumentation is claimed: the external harness has a full-run meter
       only.

harness-setup note (honest, not hidden): a first HARNESS-SETUP attempt
       (backup ...-setup-incomplete-qjoo1bhs) stopped with an AttributeError in
       the synthetic analyst message shape BEFORE ANY model calls (calls = 0).
       The harness AIMessage contract was fixed and the original artifact
       retained. This is a harness-setup fault, NOT a product failure and NOT a
       retry of a failed product call. The successful subsequent run (lahiq22h)
       covers 21/21 checks. No additional live runs were authorized.

remaining limits (explicit): failed-checkpoint / cross-resume hard-budget
       accounting is unsolved; all-agent production usage totals are untracked in
       the product; the degraded confidence cap, optional-category adapters,
       claim-date semantics and other open debts remain OPEN. NOT full-suite
       green (4 known baseline failures remain); NOT final feature completeness.

source: Supplied by Codex (independent verification + bounded live scenarios),
        read-only here; NOT re-run by this documentation turn.
status: Technically verified offline + by bounded live scenarios; PENDING human
        acceptance. Narrow controlled-fixture blocked proof (not exhaustive).
date: 2026-11-10
```

### 075 — DEBT-021/033 follow-up: unknown/legacy template + default quarantine + malformed fail-closed (2026-11-10; AI technical, OFFLINE ONLY)

```text
scope: Follow-up correcting three deviations from the already-approved ADR-007
       plan (no new feature): (1) deterministic trusted partial-debate template +
       quarantine now apply whenever the debate is NOT authoritatively two-sided
       (partial OR unknown/legacy), incl. blocked (Hold re-pinned); (2) quarantine
       path resolved via resolve_audit_paths(state) so the real graph persists
       the redacted raw audit under results_dir/identity without an explicit
       override; (3) malformed structured state fails closed to unverified rather
       than raising (unhashable list-valued speaker / non-mapping turns guarded).

result (FRESH OFFLINE EVIDENCE ONLY — no new live run): focused suite 392 passed
       (10 files); full strict offline (socket patched) 1822 passed, 4 SAME known
       baseline failures (3 date-sensitive OHLCV cache + 1 intercepted baseline
       network), 1 skipped, 1 deselected, 88 subtests; Ruff clean; governance
       42/42 PASS; git diff --check clean. No new failures or waivers.

live-evidence boundary: the 2026-11-10 D1/D2 bounded live results (logbook 074)
       apply to the FROZEN PRE-FOLLOWUP tree and are NOT re-claimed for these
       follow-up branches; there is NO live audit-file-persistence claim and no
       claim that the 214-file fingerprint is unchanged after the follow-up.
       D1/D2 request/iteration and rating-policy behavior is unaffected by these
       branches. Human acceptance remains PENDING.

status: Offline-verified follow-up; PENDING human acceptance.
date: 2026-11-10
```

### 076 — POST-followup independent offline verification (final tree; 2026-11-10; AI technical, OFFLINE ONLY)

```text
scope: Independent POST-followup offline verification of the final tree
       (docs/AUL-036 follow-up branches: unknown/legacy template, default
       quarantine + run identity, malformed unhashable-speaker fail-closed).
       Offline only; no new live/model calls; no source/test change requested.

CURRENT FINAL OFFLINE EVIDENCE: 644 focused tests passed (2 warnings), 0
       forbidden socket attempts; updated external boundary probes 25/25 passed
       (now including the UNKNOWN adversary, default quarantine + run identity,
       and malformed unhashable-speaker cases); canonical full strict harness
       1822 passed, 4 SAME baseline failures (3 date-sensitive OHLCV cache + 1
       intercepted baseline network), 1 skipped, 1 deselected, 22 warnings, 88
       subtests, 1 intercepted baseline socket attempt (no connection).

supersedes for COUNTS ONLY (not history): the earlier live-time 639 focused /
       1817 full / 19 probes described the frozen PRE-FOLLOWUP tree (logbook
       074/AUL-035). The 25 live application calls / 228903 tokens and the
       D2+D1 scenario results remain explicitly PRE-FOLLOWUP; the follow-up
       branches are offline-only verified. No claim of a second live run and no
       claim that the old 214-file fingerprint is unchanged after the follow-up.

status: Offline-verified final tree; PENDING human acceptance (not all-green: 4
        known baseline failures remain).
date: 2026-11-10
```

## 077 — Final committed-source school-model rerun

- **Authorization:** the human explicitly requested a complete school-model
  rerun after the repair was pushed. Verification only; no implementation edits,
  commit/push, PR, merge, trades or threshold tuning.
- **Version:** `bda6e3a135976bcdb66f84e02ebda666167177e2`; clean starting tree;
  214-file source/test fingerprints matched before and after execution.
- **Command:** `.venv/bin/python
  /Users/wangyiwen/Documents/Codex/2026-10-19/https-github-com-1longlong-tradingagents-https/verify_budget_attribution_2026_11_10.py
  --run-live` (existing external, explicitly opt-in harness; not default pytest).
- **Guards:** shared 32 application calls / 250000 observed tokens / 4096 output
  tokens per call / 120-second request timeout / 1200-second wall time; retries
  disabled. Observed tokens are a stopping guard, not a physical future-cost
  guarantee. Credentials were used in runtime memory without emitted values.
- **Overall:** COMPLETE, 25 application calls, 219496 reported gateway tokens,
  zero output truncations. D2 ran first, followed by D1.
- **D2:** controlled empty critical-market records and synthetic analyst report;
  real gate, routers and downstream school-model nodes. Blocked, 6 real calls,
  zero Bull/Bear calls; manager/trader/portfolio/final signal/memory all Hold;
  no executable blocked Trader sizing. Standard checks **14/14** passed.
- **Additional D2 checks:** **9/9** passed. Default quarantine file actually
  exists without an explicit path override, preserves nonempty raw narrative,
  records `non_authoritative: true`, run ID `2026-11-05/NVDA` and
  `data_quality_blocked`, and keeps raw narrative out of the trusted manager,
  complete report and memory. Report participation accurately lists both
  researchers as skipped.
- **D1:** real analysts/vendors, NVDA as of 2026-11-05, gate degraded; both
  Bull/Bear invoked, one complete round, `max_rounds_reached`. Debate usage:
  **31120 provider tokens = 27066 input + 4054 output**, **31.924532042001374
  measured seconds**. Independent callback timing (15.52 + 16.40 seconds) and
  gateway token totals agree. Standard checks **7/7** passed.
- **Backup:** `/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-10-final-commit-school-live-hkmbgkqj/`
  contains verification JSON, state, report/memory trees and the additional
  quarantine checks. Console and before/after fingerprint logs are adjacent.
- **Interpretation:** this now supplies live full-workflow and default-audit
  persistence evidence for the final committed source. Earlier pre-follow-up
  runs stay historical; they are not retroactively relabeled. D2 is a synthetic
  missing-data fixture, not an observed live-vendor outage. UNKNOWN/legacy
  adversarial states, malformed metadata and failure/resume paths are not newly
  exercised by these two live scenarios. The four known baseline failures and
  other open debts remain; no all-green/all-bug-free claim or human approval.

## 078 — CI/baseline repair (validator fallback + TZ/socket tests)

- **Authorization:** WANG Yiwen explicitly approved this round's repair plan AND
  test cases in the controlling conversation on 2026-11-11. Plan/test
  authorization only; this is **NOT** a human completion acceptance. Scoped
  maintenance, not a new phase. No new runtime feature; `tradingagents/**`
  unchanged; no dependency / `.github/**` / permission edits; no commit/push/PR.
- **Reported CI evidence (independently verified by Codex, NOT re-run here):**
  PR #2 (release <- feature, HEAD `bda6e3a`), run 42946358949; all four Python
  jobs (3.10/3.11/3.12/3.13) failed the SAME test
  `tests/test_governance_scaffold.py::TestDispatcherAgainstRealSchema::test_real_schema_rejects_bad_schema_version`
  (1 failed, 1820 passed, 7 skipped, 22 warnings, 88 subtests). The test jobs do
  NOT install optional `jsonschema`; the governance job DOES and passed.
- **Root cause (reproduced offline):** the deterministic subset fallback checked
  `project.schema_version` only as non-empty and accepted `"1.0"`, which the real
  schema pattern `^v[0-9]+\.[0-9]+$` rejects. A forced-fallback mutation against
  the real registry reproduced `errors=[]`.
- **Repairs (within approved files):**
  - `scripts/validate/validate_requirements.py`: the subset fallback now reads the
    `schema_version` pattern from the actual schema
    (`_schema_string_pattern`) and rejects non-matching/non-string/missing values
    on BOTH paths; a minimal schema with no pattern still only requires
    non-emptiness (no invented constraint). Not a general JSON Schema
    implementation; documented limitation unchanged. ADR-006.
  - `tests/test_governance_scaffold.py`: direct + dispatcher version
    acceptance/rejection, forced fallback (`importlib.util.find_spec` reports no
    `jsonschema`), real-jsonschema path when available, malformed/missing/non-string
    rejection, minimal-schema compatibility. The failing test is NOT skipped or
    weakened.
  - `tests/test_ohlcv_cache_freshness.py`: fixture epoch fixed to the local
    wall-clock (`to_pydatetime().timestamp()`) matching production
    `pd.Timestamp.fromtimestamp`; per-day write uses the same conversion; new
    UTC / `Asia/Hong_Kong` / `America/New_York` summer+winter regression matrix
    (fresh accepted, expired rejected, previous-day rejected, historical
    same-day-cache behavior preserved), process TZ/`tzset` restored per test.
    Freshness/TTL semantics unchanged.
  - `tests/test_no_data_handling.py`: mocks `stockstats_utils.vendor_reachable`
    (True → genuine no-data → `NoMarketDataError`; False → outage →
    `VendorRateLimitError`), both leave no poisoned cache and retry on the second
    call; uses `tmp_path` (no shared `tests/_tmp_cache`); outage-vs-no-data
    production distinction preserved.
  - Docs/trace: ADR-006, trace-matrix NFR-OFF-001/NFR-DET-001, risk-list
    RISK-001/002 (mitigated) + RISK-030, debt-register DEBT-001/002 (resolved) +
    DEBT-034, harness docstring. Historical failures are preserved as history.
- **Focused runs (offline):**
  - `tests/test_no_data_handling.py` + `tests/test_ohlcv_cache_freshness.py`:
    **18 passed**; re-run under `TZ=UTC`, `TZ=Asia/Hong_Kong`,
    `TZ=America/New_York`: **76 passed** each (with the governance module).
  - `tests/test_governance_scaffold.py`: **58 passed** (jsonschema installed);
    forced no-jsonschema via a faithful `find_spec("jsonschema") -> None`
    simulation: **52 passed, 6 skipped** (the 6 are the pre-existing real-schema
    branches that legitimately skip without `jsonschema`).
- **Full strict-offline suite** (`scripts/validate/strict_offline_harness.py`,
  default command): **1844 passed, 1 skipped, 1 deselected, 22 warnings, 88
  subtests, 0 forbidden socket attempts**. The former four baseline failures are
  resolved; zero-attempt NFR-OFF-001 is achieved offline.
- **Validator:** `scripts/validate/validate_requirements.py`: RESULT PASS (with
  `jsonschema`) and PASS with the subset fallback (jsonschema hidden). **Ruff:**
  clean on all changed Python. **`git diff --check`:** clean.
- **Independent Codex verification (2026-11-11; AI technical evidence, NOT
  remote-green and NOT human acceptance):** focused three modules **76 passed /
  0 socket attempts**; forced-no-jsonschema governance **52 passed, 6 skipped /
  0 attempts**; full strict offline **1844 passed, 1 skipped, 1 deselected, 22
  warnings, 88 subtests / 0 attempts**; full strict suite with `jsonschema`
  hidden via a `find_spec` simulation **1838 passed, 7 skipped, 1 deselected, 22
  warnings, 88 subtests / 0 attempts**; separate `TZ=UTC`,
  `TZ=Asia/Hong_Kong`, `TZ=America/New_York` runs of the cache+no-data modules
  each **18 passed / 0 attempts**; Ruff, validator **43/43**, and `git diff
  --check` pass. This independently confirms the offline repair and the
  zero-socket guarantee on an all-green offline run.
- **Identifier-only correction (2026-11-11):** the historical regression node
  `TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache` was
  preserved (not removed) as a regular pytest class method with the same
  `tmp_path` + reachability mocks, retaining both parameterized
  reachable/unreachable checks; no duplicate/vacuous standalone wrapper remains.
  Re-verified: `tests/test_no_data_handling.py` **5 passed** (the historical node
  collects as 2 parameterized cases). Also fixed the RISK-030 row to the six
  table columns.
- **Limitations (honest):** remote GitHub CI was NOT re-run (push is not
  authorized), so this is NOT a remote-green claim. The repair proves the
  covered offline path, not live behavior; no live calls were made this round.

### 079 — ADR-008 Stage 1: automatic structured optional-evidence ingestion + source-attempt lifecycle (2026-11-11; AI technical, OFFLINE ONLY, NOT acceptance)

Plan + test cases explicitly approved by WANG Yiwen (60536848) in the controlling
conversation on 2026-11-11 (plan/tests ONLY, NOT final human acceptance). This
entry covers **Stage 1 only** of the four-item approved sequence; Stages 2–4 are
NOT implemented. Working-tree change (no commit/push/PR); backup handled by Codex
outside the repo.

Scope implemented (ADR-008): typed request/run-scoped evidence collector
(`tradingagents/evidence/ingest.py`), honest vendor-origin adapters
(`tradingagents/evidence/vendor_adapters.py`), dataflow capture bridge
(`tradingagents/dataflows/evidence_capture.py`), durable tool/analyst boundary
capture (`tradingagents/graph/evidence_tool_node.py`), gate merge + state
persistence (`tradingagents/graph/data_quality_gate.py`,
`tradingagents/evidence/multi_category_gate.py`, `tradingagents/evidence/quality.py`),
router attempt recording (`tradingagents/dataflows/interface.py`), capture wiring
in the SEC/AV/yfinance/news/StockTwits/Reddit dataflows, versioned production
`AgentState` channels, and run/CLI collector binding + resume seeding
(`tradingagents/graph/trading_graph.py`, `cli/main.py`).

Key properties proven offline:
- Automatic capture from REAL vendor-origin records (fundamentals SEC facts +
  default yfinance/AV statements; news Yahoo/AV; sentiment StockTwits/Reddit)
  through the REAL tool path and a compiled `StateGraph` built on the **production
  `AgentState` schema** (analyst → wrapped `ToolNode` → clear → gate → research →
  report), with no manual ingest-state injection.
- Durability: capture flushed at the tool-node boundary AND the analyst-node
  boundary (Sentiment Analyst prefetches in-node), so a checkpoint right after the
  tool/analyst retains it. Proven by `interrupt_after=["tools"]` + saver close +
  graph rebuild + `invoke(None, cfg)` resume on the real gate.
- Resume: collector seeds from the checkpoint state BEFORE any new tool call
  (identity/schema guarded; foreign-symbol state quarantined), so a new call
  appends a monotonic attempt instead of overwriting index 0 — both attempts kept
  exactly once.
- Attempt ledger: every actually-operated source attempt recorded (success/empty/
  failed/skipped) with a versioned `attempt_index` (thread-safe allocation), so
  two distinct `started_at=None` attempts never collapse; configured-but-unoperated
  feeds go only to the explicit `not_attempted` metadata (never attempts);
  failures sanitized (no URL/query/username/body/secret); no duplicate success
  (route_to_vendor records only non-success; the adapter records success with data).
- Manual `data_quality_optional_evidence` contract stays compatible but a grade
  without captured records is clamped to Low (no self-asserted High).
- Per-category deterministic validation with an explicit optional classifier that
  FAILS CLOSED (empty/all-NOT_APPLICABLE validation → Blocked; mandatory checks
  must PASS); qualitative text records are never forced through the OHLCV numeric
  schema; amount-like fundamentals with no finite magnitude FAIL.
- Independence counts distinct VALID eligible content lineages only (never provider
  wrapper names or invalid rows); an optional category is never graded above Medium.
- Excluded (future/malformed/undated/late-filed) records pruned AND tombstoned
  (`data_quality_dropped_evidence_ids`) so a resume cannot resurrect them.
- Preserves public tool prose and legacy non-feature behavior; Alpha Vantage
  reported currency preserved (never hardcoded USD); default yfinance/AV
  fundamentals are captured undated (no invented filing date) and honestly Low.

Verification (offline, re-run here):
- `tests/test_structured_evidence_ingestion.py`: **53 passed**.
- Full strict-offline suite (`scripts/validate/strict_offline_harness.py`,
  default command): **1897 passed, 1 skipped, 1 deselected, 22 warnings, 88
  subtests, 0 forbidden socket attempts** (baseline before this change was 1844
  passed; +53 new).
- `ruff check .`: clean. Governance validator: PASS (43/43). `git diff --check`:
  clean.

Limitations (honest): independent review (Codex) of the final Stage 1 tree is
pending; human acceptance is NOT claimed. Stages 2–4 (durable failed-call/
cross-resume budget accounting; claim-date/value/unit consistency check;
degraded numeric confidence cap 0.60) are NOT implemented. This is offline
behavioral evidence only, not live-vendor or remote-CI-green proof; remote CI was
not re-run (push not authorized). Residual gaps are recorded in
`docs/debt-register.md` DEBT-015/DEBT-035 and `docs/architecture/risk-list.md`.

### 080 — ADR-009 Stage 2: durable run-scoped usage ledger + truthful whole-run aggregation (2026-11-11; AI technical, OFFLINE ONLY, NOT acceptance)

Implementation (working tree; branch `feature/data-quality-debate-control`; HEAD
`5ecea91` baseline). Plan + test cases for all four repair items were explicitly
approved by WANG Yiwen (60536848) on 2026-11-11 (implementation approval only).
Only **Stage 2** implemented this turn; Stage 1 (ADR-008) preserved; Stage 3
(claim date/value/unit) and Stage 4 (degraded confidence cap 0.60) NOT started.

New modules: `tradingagents/debate/usage_ledger.py` (dependency-free SQLite
`reservations` + `usage_events`; versioned schema; strict resume open; atomic
admission), `tradingagents/debate/usage_capture.py` (ContextVar run-scoped
binding; uniquely-identified instrumented model calls), and
`tradingagents/debate/researcher_accounting.py` (researcher + summary accounting
glue). Edited: `tradingagents/debate/budget.py` (`can_afford_summary`,
`whole_run_usage` aggregation with unresolved reservations),
researcher/analyst/risk/manager node instrumentation, `agents/utils/structured.py`
(structured→free-text fallback counting + affordability/admission guards),
`graph/{trading_graph,propagation}.py`, `agents/utils/agent_states.py`,
`report_artifacts.py`, `cli/main.py`.

Key properties proven offline:
- A reservation is written BEFORE every outbound call and a settlement after, so
  a crash after the provider succeeds but before the node/checkpoint update is
  recovered from the ledger (spend is not lost; never reset to zero).
- Resume keeps the SAME execution identity (read from the checkpoint) and retains
  its own spend; a genuinely FRESH re-run of the same ticker+date mints a NEW
  identity and starts at zero. Every model invocation gets a globally unique id,
  so a resumed capture that makes a new provider call is a NEW counted attempt
  (never silently hidden behind a settled id); re-reading the same id is
  idempotent.
- Unknown failed/in-flight token cost is UNRESOLVED possible spend (never 0, never
  fabricated); it fails closed for further OPTIONAL debate calls. The summary
  reserve is preserved, and the Research Manager summary has its OWN admission
  (`can_afford_summary`) that consumes the reserve without a second optional
  estimate, requires a remaining call slot, and — when unaffordable — uses a
  deterministic auditable Hold/insufficient-evidence template with an explicit
  reason (no extra model call).
- Admission (call limit + token/time capacity + reserve + unresolved) is re-read
  and evaluated INSIDE a single `BEGIN IMMEDIATE` transaction from the CURRENT
  rows, so two independent capture/ledger instances on the same run cannot both
  pass a stale preflight (token-only / time-only one-call capacity + a
  settle-before-second-txn + unknown-failure interleave all admit exactly one).
- Whole-run usage is aggregated across analysts (incl. the structured→free-text
  fallback) + debate + Research Manager + Trader + 3 risk + Portfolio for
  REPORTING only (never a budget limit; the debate-scoped limit is unchanged); the
  debate call is counted once (via the ledger), not both through a tracker and a
  second aggregate. A structured (Pydantic) result is charged the rendered length
  (never estimated 0), and a structured→free-text fallback is two counted
  attempts. In-flight reservations / unresolved settlements are surfaced as
  `reserved_unconfirmed` and force `partial` (a run can never claim `complete`
  while possible billed spend is unresolved). Per-side provenance is preserved
  (a filled estimate is never relabelled provider); provider conflict originals
  are retained.
- The ledger is source-private: no prompt/response/exception text/URL/secret is
  stored (allow-listed scalars only; asserted by reading the raw DB bytes).

Verification (offline, re-run here):
- `tests/test_durable_usage_ledger.py`: **33 passed**.
- `tests/test_whole_run_usage.py`: **10 passed** (incl. exact 12-call default
  4-analyst run and the independent raw-model-counter equality).
- Full strict-offline suite (`scripts/validate/strict_offline_harness.py`,
  default command): **1940 passed, 1 skipped, 1 deselected, 22 warnings, 88
  subtests, 0 forbidden socket attempts** (baseline before this change 1897; +43
  new).
- `ruff check .`: clean. Governance validator: PASS (43/43). `git diff --check`:
  clean.

Limitations (honest): independent Codex review of the final Stage 2 tree is
pending; human acceptance is NOT claimed. This is offline behavioral + regression
evidence only (mocked models + real `SqliteSaver` + threading barriers), not live
providers/separate processes. Hidden SDK transport retries are unobserved
(`transport_attempts` unknown); a reservation is an ESTIMATE, not a physical
billing bound; whole-run usage is reporting only. Remote CI not re-run (push not
authorized). Residual gaps: DEBT-021 (live basis), DEBT-036 (live
concurrency/retry), RISK-020/RISK-029.

### 081 — ADR-010 Stage 3: exact claim date/value/unit validation (2026-11-11; AI technical, OFFLINE ONLY, NOT acceptance)

Human approval: WANG Yiwen (60536848) explicitly approved the four-item repair
plan AND test cases (degraded confidence cap 0.60) on 2026-11-11 in the
controlling conversation. This is plan/test authorization ONLY and is NOT a final
human acceptance of any item; no reapproval was required within that plan. Stage 3
ONLY was implemented in this change; Stage 4 (cap 0.60) is NOT started.

Problem (DEBT-022 / RISK-020): the citation allowlist verified a cited evidence
ID's *eligibility* (known, High/Medium, on-or-before target, linked to a claim),
not the *semantic truth* of a model-written exact claim. The 2026-11-06 NVDA run
cited a valid `observed_at=2026-11-04` close ID but described the 200.13 close as
"2026-11-05". A valid ID therefore could extend the debate, resolve a factual
conflict, and reach the trusted plan/report with a wrong exact fact.

What was built (all additive; the 20-field `EvidenceRecord` and 7-field
`SourceAttempt` are unchanged):
- `tradingagents/evidence/origin.py`: versioned, evidence-ID-keyed typed ORIGIN
  metadata with distinct date roles (target/observation/availability/filed_at/
  published_at/retrieved_at) + unit/currency/scale, and a granularity-aware
  `dates_match` (calendar roles compare at documented day granularity; timestamp
  roles compare as UTC instants; a date-only source can never prove a timestamp;
  same-day-wrong-hour is a mismatch). Malformed/absent `value_scale` is UNKNOWN,
  NEVER laundered to 1; non-date-typed/ambiguous dates (int, compact YYYYMMDD,
  slash order) are rejected. Persisted on `data_quality_origin_metadata`; the gate
  attaches an origin for EVERY manifest record (captured vendor origin preferred,
  else derived honestly; no filing date invented).
- Producers record genuine origins: SEC (fiscal `period_end` observation + `filed`
  availability), Alpha Vantage/yfinance (period end only, availability None),
  news (published), sentiment (posted).
- `tradingagents/debate/models.py` + `turn.py`: additive typed `ClaimRecord`
  envelope and an optional structured `claim:` marker field plus a conservative
  inline exact-prose scan; the legacy v1.0 free-text `ClaimEvidenceLink` is
  preserved but is NEVER treated as verified exact evidence.
- `tradingagents/debate/claims.py`: pure `validate_claim` (identity/run/ticker,
  date role, exact value, unit/currency/scale, no speculative FX, future/Low/
  unknown-schema/duplicate-origin fail closed) + verified/rejected/unverified
  summary + prompt block.
- Runtime consumption (the integration that makes it real): the evaluator prunes
  invalid-claimed IDs from valid-new-evidence (no debate extension); `conflicts.py`
  never creates/keeps a factual conflict on an invalid-claimed ID; the Research
  Manager receives the verified/rejected/unverified summary; the trusted Research
  Manager plan, Trader plan and final decision have the wrong exact fact redacted
  (`contain_rejected_exact_claims`) WITHOUT a global Hold; `debate_trace.json`
  exports the redacted claim-validation summary.

Verifier early feedback (2026-11-11) incorporated: malformed/absent scale must not
normalize to 1; int/ambiguous dates rejected explicitly; timestamp roles compare
as instants (date-only cannot prove a timestamp; same-day-wrong-hour is a
mismatch); calendar roles use documented day granularity. Covered by
`TestMalformedScaleNeverNormalizesToOne`, `TestAmbiguousDatesRejected`,
`TestTimestampsAndGranularity`.

Verification (offline, re-run here):
- `tests/test_exact_claim_validation.py`: **73 passed** (pure validator + origin
  matrix).
- `tests/test_exact_claim_runtime.py`: **30 passed** (real production AgentState /
  GraphSetup graph with scripted models that cite a valid ID but a wrong
  date/value; real `SqliteSaver` interrupt/restart preserving origin + validation;
  public entry report propagation).
- Full strict-offline suite (`scripts/validate/strict_offline_harness.py`):
  **2044 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden
  socket attempts** (baseline before this change 1940; +104 new).
- `ruff check .`: clean. Governance validator: PASS (43/43). `git diff --check`:
  clean.

Second independent review round (2026-11-11) incorporated: (a) `enforce_trusted_boundary` now performs FRESH per-boundary extraction + validation of each boundary's OWN exact factual prose at clause/assertion granularity (a recommendation word in one clause no longer exempts a factual clause; every date+value assertion on a line is checked so a correct fact cannot launder a wrong one; a date/value split across adjacent lines is paired over a bounded window), applied at RM/Trader/Portfolio/memory/report with empty rejected list; (b) dimension semantics for ALL numeric claims (money/shares/percent/ratio) require a KNOWN matching dimension on BOTH sides and never infer a dimension; (c) `record.value_normalized` is BASE units and a claim magnitude is normalized by its own declared scale, so `391000 million USD` and `391000000000 USD` both verify against the real SEC base value while an explicit multiplier never invents a missing record scale; (d) origin/record/requested target must all agree (foreign-but-internally-consistent -> unverified); (e) the default market adapter's `native_quote_currency` is GENUINELY UNKNOWN, so an exact monetary claim on the real default market path is honestly `unverified` (a separate labelled known-currency fixture proves the verification path; real SEC USD provides the genuine positive monetary producer proof).

Limitations (honest): independent Codex review of the final Stage 3 tree is
pending; human acceptance is NOT claimed. This is offline behavioral + regression
evidence only, not live vendors/models. Only typed exact claims and common inline
exact prose are deterministically validated; arbitrary natural-language semantics
are NOT proven (unparseable prose stays `unverified`). Default yfinance/Alpha
Vantage fundamentals remain undated and unavailable for historical exact proof.
Remote CI not re-run (push not authorized). Stage 4 (DEBT-014, cap 0.60) NOT
started. Residual gaps: DEBT-022 (live validation), RISK-020.

### 082 — ADR-011 Stage 4: deterministic degraded-run confidence cap 0.60 (2026-11-11; AI technical, OFFLINE ONLY, NOT acceptance)

Closed DEBT-014 / RISK-014 finding 4: the degraded-run confidence ceiling was
previously only a prompt instruction. The human specified the ceiling as **0.60**
and approved the plan + tests (not final acceptance). A pure, deterministic,
LLM-free policy (`tradingagents/debate/confidence_policy.py`) now owns it.

What is enforced (all recomputed from the authoritative fail-closed gate verdict,
never trusted from a state audit field):

- Debate turns/stances: numeric `confidence` capped before entering the debate
  state; readable content confidence-labelled numerics capped before the next
  speaker/evaluator reads them.
- Evaluator snapshot, Research Manager, Trader, Portfolio Manager: typed numeric
  confidence AND prose capped; the typed RM/Trader/PM schema confidence is capped
  on its EXACT raw value BEFORE the lossy `:.2f` render, so a raw
  0.6000001 / 0.604 / 0.954321 is genuinely capped (and its exact raw recorded in
  the audit) rather than masked by the rounded rendered `.60` / `.95`.
- Post-gate read boundary: a shared `sanitize_state_inputs` / `with_sanitized_state`
  wraps every post-gate node (Bull, Bear, Evaluator, RM, Trader, risk×3, PM) and
  caps a per-read COPY of the persisted analyst reports, plans, debate+risk
  histories AND turn/stance numerics, so a legacy / direct-GraphSetup / SQLite
  resume cannot feed a raw 0.95 to any downstream prompt. The stored analyst
  reports (written before the gate) are exempt at analyst time but sanitized at
  every post-gate read.
- API resume (`TradingAgentsGraph._run_graph`) AND the CLI (`cli.main.run_analysis`
  streaming `graph.graph.stream`) both run the SAME fail-closed resume sanitizer
  before any model/stream call; a sanitizer/`update_state` failure raises so zero
  resumed model calls happen; repeated safe resume is idempotent (no audit
  duplication); malformed legacy numerics (bool/NaN/out-of-range) are quarantined.
- Report writer independently recomputes the cap from the imported/legacy state;
  the exported `run_summary.json` / `debate_trace.json` use effective values and a
  merged per-section/per-turn audit (raw `.95` appears only in an explicit
  raw_value audit/quarantine field); the memory log stores the effective decision.

Scope/safety: capping is deliberately NARROW — only explicit confidence-labelled
numerics (decimal/percent/fullwidth/leading-dot/scientific/JSON/Markdown/multiline/
duplicate) are capped; malformed/bool/NaN/out-of-range are quarantined; a missing
value stays missing; categorical low/medium/high stays distinct; a normal run and
ordinary financial figures are byte-for-byte unchanged; `blocked` runs keep their
non-numeric Hold discipline. 0.60 is an ENGINEERING ceiling, NOT a calibrated
probability and NOT production threshold tuning. No extra LLM call.

Verification (fresh final run, offline):
- `tests/test_confidence_cap_policy.py` + `tests/test_confidence_cap_runtime.py` +
  `tests/test_confidence_cap_cli.py`: **110 passed, 0 forbidden socket attempts**
  (real production AgentState / GraphSetup with a genuine production gate over a
  mocked raw OHLCV source; role-aware scripted over-confident models; structured
  AND free-text fallback; real SQLite interrupt/close/reconstruct/resume; a direct
  GraphSetup resume at the evaluator with a stale typed 0.95; fail-closed and
  idempotent resume; typed raw-precision 0.6000001/0.604/0.954321 regressions;
  public report/CLI/memory propagation; blocked Hold).
- PERSISTED STATE: a deterministic post-gate `Confidence Sanitizer` node writes the
  capped analyst-report / plan / history fields, and every post-gate node wrapper
  merges its changed sanitized INPUT deltas (node outputs win) and caps its own
  returned text (e.g. a raw risk argument), so the RETURNED state and `_log_state`
  / public JSON carry the effective values on FRESH and direct-legacy-resume paths
  alike (a direct SQLite resume that SKIPS the sanitizer node is covered); originals
  survive only in the explicit audit; a normal run's report is byte-for-byte
  unchanged.
- Full strict-offline suite (`scripts/validate/strict_offline_harness.py`):
  **2154 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden
  socket attempts**. Stage 4 entry baseline is the Stage 3 final 2044 passed;
  final 2154 = +110 vs that stage baseline, including the 13 typed-precision
  regression cases added on top of the intermediate 2138 run (the +13 is measured
  vs the intermediate 2138, NOT vs the stage-entry baseline 2044).
- `ruff check .`: clean. Governance validator: PASS (43/43). `git diff --check`:
  clean.

Limitations (honest): independent Codex review of the final Stage 4 tree is
pending; human acceptance is NOT claimed (this is implementation approval only).
Offline behavioral + regression evidence only, not live vendors/models; capping is
an engineering safety ceiling, not a calibration or accuracy claim; it caps
explicit numeric confidence only, not qualitative prose. Remote CI not re-run
(push not authorized). Residual gaps: DEBT-014 (awaiting human acceptance),
DEBT-015 (exchange-holiday calendar, researcher char-estimate usage, append-only
event types/audit_incomplete fallback), RISK-014.

## 2026-11-11 — Two confirmed live-run defect repairs (Defect-1 origin authority, Defect-2 structured raw usage) — implementation + offline verification (logbook 083)

Scope: WANG Yiwen explicitly approved this round's execution plan AND test cases
("批准这两项修复计划和测试用例", 2026-11-11) — implementation approval ONLY, NOT final
acceptance. Branch `feature/data-quality-debate-control`, HEAD 5ecea91; all dirty
Stage 1-4 work preserved. No live/vendor/model calls. English docs/comments.

Defect-1 (ADR-010 amendment) — origin metadata overwrite:
- Root cause: `graph/data_quality_gate.py` built the correct 5-origin map then
  `output.update(persisted)` overwrote it with the live collector's empty-for-market
  origin delta (task evidence `origin-overwrite-reproduction.json`: 5 records / 5
  origins without collector, 5 records / 0 with active collector).
- Fix: authoritative origin merge AFTER persistence (`_merge_authoritative_origins`);
  genuine captured roles preserved; real captured conflicts (collector duplicate
  insertion, or state-vs-collector disagreement) RETAINED and failed closed via the
  declared `data_quality_origin_conflicted_ids` channel; conflicted ids dropped at
  `origin_records_from_state` and passed to the claim validator by the evaluator and
  output boundary; conflict seeding unconditional from state (no-collector / direct
  resume / imported report state); no first/last-wins, no derived re-trust, no
  resurrection of pruned/tombstoned ids; 20/7 frozen records unchanged.

Defect-2 (ADR-009 amendment) — structured-output usage lost before settlement:
- Root cause: RM/Trader/PM/Sentiment typed results are Pydantic objects with no
  `usage_metadata`; `instrumented_model_call` settled them as estimates while plain
  risk calls retained provider usage. Blocked fixture: 6 real calls / 22,600 reported
  tokens vs 22,067 recorded with `totals.tokens_source=provider` despite three
  estimated structured calls.
- Fix: `bind_structured` binds `include_raw=True` where supported (same single
  call); usage settles from the RAW `AIMessage` (`usage_response`) while the parsed
  typed object is rendered/capped; BINDING-ONLY fallback (no model call) when only
  `include_raw` is rejected (any exception incl. NotImplementedError/AttributeError/
  TypeError) so a working legacy typed provider stays typed+estimated (no free-text
  downgrade); the billed boundary is ONLY the transport invocation so parser/
  sanitizer/render errors after a known raw response settle EXACT usage then fall
  back once (two distinct attempts, atomic guards); unknown transport stays unknown;
  `SOURCE_MIXED` aggregate/report-only label (never per-call; not in the durable
  ledger allowed sources) shown in `report_artifacts` markdown; known token sums
  preserved; all-provider stays provider; cap 0.60 on exact raw parsed value
  unchanged.

Verification (fresh, offline; socket-disabled):
- Focused: `tests/test_gate_origin_authority.py` 18 passed (incl. 4 real INTERRUPTED-resume tests — ambiguity and tombstone-exclusion variants — where a PENDING production Gate/Consumer node executes after saver close+rebuild+reseed, plus the scoped no-resurrection edge: a no-collector gate / direct consumer never re-trusts an already-dropped id) and `tests/test_structured_raw_usage.py` 18 passed (incl. a PUBLIC `TradingAgentsGraph._run_graph` end-to-end: real gate + mocked-raw OHLCV + role-aware raw-envelope model + real active collector + durable ledger, no manual attach; exact per-role/whole usage vs the independent invocation counter, 5 market origins, report; the memory write is exercised through a thin test adapter that calls the real `TradingMemoryLog.store_decision` (the production `record_decision`'s `_is_blocked_state`/trusted-boundary wrapper is NOT exercised here); cap 0.60 verified directly). +36 new (origin 18 + structured 18).
- Full strict-offline (`scripts/validate/strict_offline_harness.py`): **2190 passed, 1 skipped, 1 deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts** (baseline 2154 + 36). Real-shaped `AIMessage` token metadata; mocked models; real SQLite checkpoint/resume; no network.
- `ruff check .`: clean. Governance validator: PASS (43/43). `git diff --check`: clean.

Limitations (honest): independent Codex verification of this round's tree is
pending; human acceptance is NOT claimed (implementation approval only). These are
offline behavioral + regression repairs; the prior incomplete 2026-11-11 school-model
live run is NOT relabelled as a fixed live proof — both fixes remain offline-only
until a separately authorized future live verification. `mixed` is a report label,
not a per-call telemetry source; arbitrary prose claim semantics beyond the
conservative parser stay unverified; frozen `EvidenceRecord`(20)/`SourceAttempt`(7)
unchanged. Remote CI not re-run (push not authorized).

### Independent OFFLINE metadata replay (2026-11-11) — NOT a live proof

An independent offline replay (Codex) reproduced both fixes on a separate copy:
(a) with the cached SAME live NVDA OHLCV data and the **real gate**, the manifest
shows **5 records / 5 origins** both with and without an active collector
(previously 5 / 0); (b) a replay of the prior blocked-fixture's 6 actual
provider-usage metadata through the raw structured utility for RM/Trader/PM plus
the 3 risk calls, against a real durable ledger, accounted **22,600 = 22,600
expected**, 6 provider calls, `tokens_source=provider`, `estimated=false`,
completeness `complete`; reopening the ledger yielded the same totals with no
double count; typed `.6000001` / `.954321` / `.604` capped to `.6` with the exact
raw in the audit. No new live calls were made. Evidence:
`/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-11-independent-usage-replay-t6ls2eb5/verification.json`.
This is an **independent OFFLINE metadata replay only**; it is NEVER a current
live proof and does not relabel the prior incomplete live run as fixed.

### Independent Codex technical review of the two-defect repair tree — COMPLETED (logbook 084; NOT human acceptance, NOT a live retest)

Independent AI (Codex) technical verification of the repaired tree is complete.
No source/test changed for this record; no product/vendor/model calls; no Git
mutations.

- Full strict-offline (independent rerun): **2190 passed, 1 skipped, 1 deselected,
  22 warnings, 88 subtests, 0 forbidden socket attempts**.
- Focused two new files: **36 passed, 0 sockets** (18 `tests/test_gate_origin_authority.py`
  + 18 `tests/test_structured_raw_usage.py`).
- `ruff check .` clean; governance validator **43/43 PASS** (incl. likely-secret
  scan PASS); `git diff --check` clean; HEAD `5ecea91` unchanged; frozen
  governance/CI/dependency files untouched.
- Independently reran the stale-map + state-tombstone reproduction:
  `gate_retrusted=False`, `direct_consumer_retrusted=False` (previously True/True).
- Logs: `/Users/wangyiwen/OpenCodeRecords/TradingAgents/2026-11-11-live-findings-repair-independent-full-offline.log`
  and `.../2026-11-11-live-findings-repair-independent-focused.log`.

This independent AI technical review — and the prior independent OFFLINE metadata
replay — are **offline technical evidence only**. They are NOT a live retest and
do NOT relabel the historical incomplete 2026-11-11 live run or any earlier stage
review. Explicit human acceptance and a separately authorized live retest remain
pending.

### Two-defect repair (price-boundary + standalone typed claims) — IMPLEMENTED + offline-verified (logbook 085; NOT human acceptance, NOT a live retest)

Builder (OpenCode) implemented the human-approved (2026-11-12, "批准本轮修复计
划和测试用例" = approves this round's corrected plan AND test cases; implementation
approval only) two-defect repair from the approved plan plus its overriding
correction. Branch `feature/data-quality-debate-control`, HEAD `5ecea91` unchanged;
dirty Stage 1–4 work preserved; no commit/push/PR; no reset/revert/stash; no
product/vendor/model live calls; all product tests deterministic socket-disabled
offline.

- **Defect 1 (ADR-011 amendment):** suffix confidence literal no longer absorbs a
  trailing sentence period; terminators are boundaries not connectors; CRLF-aware
  soft-wrap still binds; left token boundary excludes currency/sign/date/path-clued
  numerics. `$204.38.` preserved byte-for-byte; bare `204.38 confidence` still
  invalid/quarantined; genuine forms still cap to 0.60.
- **Defect 2 (ADR-010 amendment):** shared strict `extract_standalone_typed_claims`
  recovers the 8 actual Bear lines (before/after/no-marker, no-stance FAILED branch)
  into the SAME validation; fenced (incl. unclosed) and quoted examples never
  admitted; contradictory `role`/`date_role` aliases unparseable; additive honest
  coverage serialized in `DebateTurn`, `claim_validation_summary`, and
  `debate_trace.json`; consumed at `enforce_trusted_boundary`; frozen
  `EvidenceRecord`(20)/`SourceAttempt`(7) unchanged.
- **Focused new files:** `tests/test_confidence_boundary.py` (49 passed) +
  `tests/test_standalone_claims.py` (40 passed) = 89 passed.
- **Related regressions:** confidence suites (110) + debate-turn/claims/conflicts/
  gate (376 incl. new files); broader debate/report/guard/memory/researcher suite
  425 passed; all 0 sockets.
- **Full strict-offline harness:** **2279 passed, 1 skipped, 1 deselected, 22
  warnings, 88 subtests, 0 forbidden socket attempts**
  (`.venv/bin/python scripts/validate/strict_offline_harness.py`).
- `ruff check` on changed source: **All checks passed**; governance validator
  **43/43 PASS** (incl. likely-secret scan PASS); YAML/JSON parse OK;
  `git diff --check` clean.

Offline built-in verification only. This is NOT a live retest; the preserved
2026-11-11 live evidence is unchanged and never relabelled as post-fix live proof.
Independent Codex review and explicit human acceptance remain pending.

### Two-defect repair — FINAL offlines (post independent second-pass feedback) (logbook 085, FINAL)

After independent first/second-pass verifier feedback (all within the approved
shared-contract/quoted/fence scope), the repair was tightened and re-gated on the
FINAL tree:

- **Confidence boundary** (ADR-011): CRLF soft-wrap caps (`0.95\r\nconfidence` →
  `0.6`); date/sign/path fragments (`2026-11-05`, `2026/11/05`, `-`) are not
  confidence candidates; `$204.38.` stays byte-for-byte; bare `204.38 confidence`
  still quarantined. `tests/test_confidence_boundary.py`: **51 passed** (incl. a
  real Trader-node test and a real `TradingAgentsGraph.record_decision`/memory test
  proving price preservation + genuine cap at production boundaries).
- **Standalone typed claims** (ADR-010): ONE shared strict grammar
  (`parse_strict_typed_claim_payload`) is used by BOTH the canonical
  `DEBATE_METADATA` `claim=` parser AND the standalone extractor, so a canonical
  contradictory `role`/`date_role` no longer launders into a trusted claim; ONE
  whole-document, fence/quote-aware walk
  (`extract_standalone_typed_claims_indexed`) is used by the turn parser AND the
  trusted output boundary (no per-line divergence); fence close requires the SAME
  char and length ≥ the opener (a shorter fence never closes a longer one); a
  narrow, documented explicit `Example:`/`Examples:`/`Example N:` block is
  excluded; the no-manifest boundary REDACTs an explicit typed line with a
  missing-evidence diagnostic (never silently passes it through) while ordinary
  prose is a no-op. `tests/test_standalone_claims.py`: **49 passed** (8 verbatim
  lines, marker/union/dedupe, fenced incl. four-backtick/unclosed/tilde, Example
  blocks, alias contradiction, fail-closed negatives, real SQLite resume asserting
  resumed evaluator coverage + verified summary, and malformed/rejected not stored
  at memory/report).
- **Related regressions:** 755 passed across confidence + debate-turn/claims/
  conflicts/gate + report/guard/memory/evaluator/graph/researcher suites.
- **Full strict-offline harness:** **2290 passed, 1 skipped, 1 deselected, 22
  warnings, 88 subtests, 0 forbidden socket attempts**.
- Ruff (changed source + tests): **All checks passed**; governance **43/43 PASS**;
  YAML/JSON parse OK; `git diff --check` clean.

Offline, deterministic verification only. NOT a live retest; preserved live
evidence unchanged and not relabelled. Independent Codex review and explicit human
acceptance remain pending.

### Independent Codex review of the two-defect repair — COMPLETE (logbook 086; NOT human acceptance, NOT a live retest)

Independent AI (Codex) technical verification of the final repair tree is
complete. Documentation-only record; no source/test changed, no product / vendor /
model calls, no Git mutations.

- **Independent rerun:** full strict-offline **2290 passed, 1 skipped, 1
  deselected, 22 warnings, 88 subtests, 0 forbidden socket attempts**; Ruff clean;
  governance **43/43 PASS** incl the artifact likely-secret scan; `git diff --check`
  clean; frozen governance/CI/dependency paths unchanged; HEAD `5ecea91` unchanged.
- **Independent OFFLINE replay of the actual prior-school Bear text** (no new
  product calls) now recovers all 8 claims: **1 verified (volume), 5 rejected
  (unknown optional evidence), 2 unverified (price currency/unit genuinely
  unknown)** — honest non-empty validation, NOT all-8-verified.
- Independently confirmed: historical price case (`$204.38.` preserved), LF/CRLF
  suffix soft-wraps, dates/currency/sign/path preservation, invalid bare suffix
  quarantine, long/unclosed fences, explicit `Example:` blocks, and conflicting
  canonical/outside `role`/`date_role` aliases.
- Independently confirmed at REAL boundaries with the real `_is_blocked_state` (no
  override): actual `create_trader`, report writer, and `record_decision` /
  `TradingMemoryLog` preserved `$204.38.` and capped a genuine `0.95`; a rejected
  wrong-volume claim was not stored in memory.
- **Saved evidence:** `.../2026-11-12-price-claim-independent-replay.json`,
  `.../2026-11-12-price-claim-independent-mnca0llp/`, and
  `.../2026-11-12-price-claim-independent-full-offline.log`.

This independent AI technical review — and the earlier independent OFFLINE replay
— are **offline technical evidence only**. They are NOT a live retest and do NOT
relabel the historical 2026-11-11 live run (which remains historical bug evidence)
or any earlier stage review. **Explicit human acceptance remains pending.**

### Verified-span repair (residual false-redaction) — IMPLEMENTED + offline-verified (logbook 087; NOT human acceptance, NOT a live rerun)

Approved plan + test cases: human WANG Yiwen, 2026-11-12 ("批准本轮修复计划和测试用例";
implementation approval ONLY). Builder (OpenCode); Codex independent verifier. Branch
`feature/data-quality-debate-control`, HEAD `5ecea91` unchanged; dirty Stage 1–4 work
preserved; no commit/push/PR; no dependencies/CI/permissions/prompt/human-only edits;
no product live LLM/vendor calls; offline deterministic (0 sockets).

- **Defect (evidence loss):** the 2026-11-12 school live run (26 calls / 202,941 tokens;
  historical bug evidence, NOT post-fix proof) showed a CORRECT long-decimal typed
  claim (`value=306127800.0000000000`, `unit=shares`) strictly VALIDATED as verified
  but then BLANKED by the generic prose scanner (`_nearest_unit` 24-char proximity;
  `shares` fell out of window → `claim_unit_or_currency_unknown`). Short value
  survived. Reproduced in report + `record_decision`/memory.
- **Fix (ADR-010 addendum):** occurrence-exact protection of a verified typed
  ClaimRecord's own `date=`/`value=` field spans (`claims.extract_claim_span_occurrences`),
  applied by `output_guard._verified_typed_protected_spans` to BOTH the per-line and
  cross-line prose passes; date+value pair kept together (no cross-pairing); one
  shared whole-document fence/Example exclusion walk for standalone AND canonical
  (fenced/Example canonical gains no protection). No window enlargement, no
  whole-line/document skip, no grammar widening; unparseable mixed line fails closed.
- **Verifier mid-review corrections incorporated (same approved scope):** (a) ties
  protection to the EXACT parsed payload occurrence, not a whole-line first match, so
  a later verified subclaim cannot authorize an earlier rejected sibling with the
  same date/value — mixed good/bad same-ID same-line tested in BOTH orders; (b)
  canonical protection uses the shared fence/Example walk, not a permissive
  per-substring parser, so fenced/Example canonical claims are never protected; (c)
  memory tests use the REAL `_is_blocked_state` (no monkeypatch); (d) equivalent
  numeric forms (long extra zeros, scientific `e`/`E`) are protected by locating the
  RAW payload token offset and proving equivalence via strict `ClaimRecord`
  normalization (not raw-text equality, float, or substring), with nearby wrong
  values redacted and duplicate identical payloads keeping distinct offsets; (e) a
  blockquote/quoted line (`> ...`) is excluded by the shared walker so a marker
  substring in quoted prose never becomes a protected occurrence (fenced/Example/
  quoted canonical AND standalone asserted to yield ZERO authorized occurrences).
- **Tests:** `tests/test_verified_span_boundary.py` **77 passed** (positive
  preservation of short/long/extra-zero/scientific/uppercase-key/spaced-key/
  canonical-backtick/NFKC forms, and negatives: wrong value/nearby-wrong-value/
  future/unit/currency/scale/unknown-ID/role-mismatch/Low/Blocked; same-line &
  adjacent cross-pair; canonical mixed both orders; fenced/Example/quoted incl.
  canonical (direct zero-occurrence assertions); fail-closed unparseable;
  idempotence incl. after redaction; REAL report + production memory).
- **Format-variant correction (final):** the raw field-offset locator now walks the
  ORIGINAL pipe segments with the SAME `key.strip().lower()` semantics as the strict
  parser and computes offsets against the RAW payload (including any backtick/
  whitespace wrapper), so supported variants (`DATE=`/`VALUE=` uppercase, `date = ...`
  spaced, canonical ``claim=`...` `` backticked) are protected — they were supported
  syntax, not new grammar. Standalone ``claim=`...` `` (backtick directly after
  `claim=`) is NOT accepted by the strict parser and is correctly not treated as a
  protected claim (no grammar expansion).
- **Field-order / wrapper-location correction (final):** the strict grammar is
  field-order independent, so offsets are now computed on the WRAPPER-STRIPPED
  payload the parser actually sees, then shifted back onto the ORIGINAL line by the
  MEASURED consumed prefix: the bullet/numeric-list prefix (`- ` / `1. `) length is
  measured (not assumed to be leading whitespace) and the canonical whitespace/
  backtick wrapper length is measured (``sub.find(stripped)``) — so a `date=`/`value=`
  field FIRST or LAST, with bullets/numeric-list or canonical whitespace/backticks,
  points at the exact token and is preserved. Regressions assert exact token offsets
  into the original text for date-first/value-last and value-first/date-last forms.
- **Duplicate-occurrence per-token authority (final):** the generic prose pass now
  decides blanking PER TOKEN (`_span_is_authorized`): a verified typed `date=`/`value=`
  token span is never erased, and an unauthorized span is always blanked — regardless
  of how the heuristic date↔value pairing associates them. This fixes two IDENTICAL
  verified canonical subclaims joined by ``||`` (exhaustive 720 field-order
  permutations: 0 false redactions; previously 176), where the heuristic re-paired a
  verified value with a sibling's date. Mixed verified+wrong siblings still redact
  ONLY the bad component (wrong value/date/unit), keeping the verified token.
- **Related regressions:** 716 passed (verified-span + standalone + confidence +
  exact-claim + output_guard + reporting + report-artifacts + memory + debate suites).
- **Full strict-offline harness:** **2367 passed, 1 skipped, 1 deselected, 22
  warnings, 88 subtests, 0 forbidden socket attempts**.
- Ruff clean; governance 43/43 PASS; YAML/JSON OK; `git diff --check` clean; scoped
  likely-secret scan 0.

Offline, deterministic verification only. Prior 26-call / 202,941-token school run
remains historical bug evidence; this is NOT a live rerun and NOT a claim that all
defects are fixed. Independent Codex review + explicit human acceptance pending.

### Independent Codex FINAL review of the verified-span repair — COMPLETE (logbook 088; NOT human acceptance, NOT a live rerun)

Documentation/comment sync only; no behaviour/test change, no new product live call,
no Git mutation.

- **Independent rerun (supplied):** full strict-offline **2367 passed, 1 skipped
  (optional `langchain_aws` absent), 1 deselected, 22 warnings, 88 subtests, 0 socket
  attempts**; focused specified **8 modules = 556 passed / 0 sockets** (a DIFFERENT
  subset from the builder's 716 related suite — counts not conflated); `ruff check .`
  clean; governance **43/43 PASS**; `git diff --check` clean.
- **Independent exhaustive format check:** **4320 cases** (720 field orders × 6
  formats incl. duplicate canonical) all preserved / 0 sockets.
- **Independent replay of the SAVED real school response:**
  `long-value-independent-replay.json` has **19 TOTAL checks INCLUDING the 5
  equivalent numeric variants — all 19 true** (corrected: not a 17+5 split) / 0
  sockets. Real `write_report_tree` (trader + complete) and real
  `record_decision`/`TradingMemoryLog` preserve the correct long typed line while
  future-dated and unknown-ID claims are removed.
- **Evidence saved (outside repo):** `long-value-independent-full-offline.log`,
  `long-value-independent-focused.log`, `long-value-format-results.json`,
  `long-value-independent-replay.json`; artifacts under
  `2026-11-12-long-value-independent-fsd_ad80/`.
- **Authority semantics (docs/comment sync):** final protection is PER VERIFIED TOKEN
  OCCURRENCE, not heuristic date↔value pair membership; the unprotected partner is
  still checked/redacted; no whole-line bypass. Stale "ONE pair" source/doc/test
  comments were corrected (no behaviour change).

Offline technical review only. **Explicit human final acceptance and any post-fix
live retest remain pending.** The historical 2026-11-12 26-call / 202,941-token school
run remains bug evidence only, never relabelled as post-fix live proof.

### Python 3.10 CI repair — terminal UTC `Z` normalization — IMPLEMENTED + offline-verified (logbook 089; NOT human acceptance, NOT a real 3.10 run)

Human plan+test approval recorded 2026-11-12 (WANG Yiwen 60536848;
`docs/review-memo.md`), implementation approval only — **NOT final human feature
acceptance**.

- **CI evidence (observed, not guessed):** run 43151706957 / job 130962187295 on
  `668b46a`, job `tests (py3.10)` — exactly 2 failed / 2359 passed / 8 skipped / 22
  warnings / 88 subtests. Failures:
  `tests/test_structured_evidence_ingestion.py::TestSentimentIngestion::test_stocktwits_native_label_and_privacy`
  (line 317, sentiment `records == []`) and
  `...::TestRouting::test_all_three_categories_present_can_be_medium` (line 364,
  sentiment `Blocked` instead of `Medium`). Python 3.11/3.12/3.13, smoke, Ruff and
  governance passed.
- **Root cause:** `tradingagents/evidence/policy.py::to_date` parsed with a bare
  `datetime.fromisoformat(text)` and did not normalize a terminal uppercase `Z`.
  Pre-3.11 `fromisoformat` rejects a terminal `Z`, so a legitimate StockTwits
  `created_at` such as `2026-05-10T12:00:00Z` became `None`; the sentiment record
  then failed `_publication_vs_target` as `missing_date` and the category was
  Blocked. (The pre-3.11 terminal-`Z` rejection was independently observed on a
  local Python 3.9.25 interpreter; no PEP attribution is made or required.)
- **Repair (source, `policy.py` only):** a new `_normalize_terminal_utc_z` helper,
  guarded by `_TERMINAL_Z_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}.(?:\d{2}|.*[0-9])Z$")`
  (extended `YYYY-MM-DD` + exactly one separator character + a time payload of **at
  least an hour component**, a *date+time-shape* test independent of the separator
  character; the time body is `\d{2}` for HH-only OR a longer tail ending in a digit
  for HH:MM/HH:MM:SS/fractions), plus `_OFFSET_BEFORE_Z` (excludes a pre-existing
  offset before the `Z`), replaces only the terminal uppercase `Z` with `+00:00`; the
  final `datetime.fromisoformat` remains authoritative. `2026-05-10Z12:00:00Z` (Z as
  the one-character separator, terminal Z) is normalized with its separator preserved;
  date-only `2026-05-10Z`, repeated `ZZ`, `zZ`/`Zz`, `+00:00Z` and malformed
  dates/times are **not** rewritten; the raw parser behavior is then retained, so
  only *malformed suffix is not rewritten* is claimed (not universal rejection — the
  native 3.12 parser natively accepts raw `...zZ` while native 3.9 rejects it; see the
  honest wording below). Terminal lowercase `z` and repeated uppercase `ZZ` remain
  rejected on the tested versions. Offsets keep calendar-date
  (no UTC date-shift) semantics. Legacy non-`Z` `to_date`
  numeric/compact/separator behavior is **preserved per interpreter and unchanged**
  by this repair (compact `YYYYMMDD` acceptance itself expanded in 3.11; the
  observed 3.12 acceptance of `20260510` is historical baseline only, and on a
  parser that rejects it `to_date` returns `None`); the test asserts parity with the
  running interpreter's unpatched native parser, not a forced acceptance.
  Numeric/bool rejection remains an adapter (`_iso_date`) contract, tested there
  universally.
- **Independent native old-parser findings (fixed):** an independent review extracted
  the production guard/helper/`to_date` AST and ran it under the local standard-library
  **Python 3.9.25** interpreter (a *real older parser*, but **not** the project's 3.10
  and not a 3.10 proof). (1) The original `...Z$` guard rewrote a malformed
  `2026-05-10T12:00:00ZZ` into `2026-05-10T12:00:00Z+00:00`, which 3.9's
  `fromisoformat` **accepts** — i.e. the normalization *introduced* acceptance of a raw
  string the parser rejected. (2) A follow-up `\d{2}.*[0-9]Z` tightening then rejected
  the supported HH-only `2026-05-10T12Z`/HH:MM `2026-05-10T12:30Z` shapes (needing
  ≥3 time digits), contradicting the approved at-least-HH guard. The final guard keeps
  the two-hour-digit minimum and makes the pre-`Z` digit a separate alternative
  (`(?:\d{2}|.*[0-9])`), so HH-only, HH:MM, HH:MM:SS and fractions all normalize; the
  malformed `...ZZ`/`...zZ`/`...+00:00Z`/`...ZZZ` forms are still **not** rewritten, and
  the raw parser behavior is retained rather than newly changed (native 3.9 rejects raw
  `...zZ`; the unmodified native 3.12 accepts it — interpreter-native, NOT universally
  rejected). Re-running the extracted production code on 3.9.25 (a 22-case
  accepted/rejected matrix incl. HH-only/HH:MM, offsets, date-only, repeated-`Z`,
  legacy parity; `zZ` recorded as NATIVE PARITY, not universal `None`) gave **0
  failures**.
- **Tests (additive `tests/test_policy_to_date_python310.py`, 39 passed):**
  positive `Z`≡`+00:00`≡calendar date; separator variants (`T`, space, `Z`); time
  granularity variants (HH-only, HH:MM, HH:MM:SS, fraction) all normalized;
  date/datetime/offset inputs unchanged; negatives (date-only `Z`, `ZZ`, `Zz`,
  `+00:00Z`, lowercase `z`, malformed, empty, None); a **helper-boundary** regression
  asserting malformed repeated/lowercase-`Z`/offset-before-`Z` suffixes are **not
  rewritten** (and end-to-end rejected); legitimate terminal-`Z` helper rewrites;
  interpreter-native parity for non-terminal-`Z` forms (`20260510`, `...zZ`); legacy
  numeric/compact **per-interpreter parity** with the unpatched native parser (bool
  rejected universally); pre-3.11 simulation (monkeypatch of
  `policy.datetime.fromisoformat` rejecting terminal `Z`, NOT a real 3.10 run) still
  yields the correct date incl. HH-only/HH:MM; `_iso_date` numeric/bool/malformed
  boundary; real mocked StockTwits `fetch → capture → gate` proves sentiment
  ingested, category `Medium`, native labels preserved (`bullish`/`unlabeled`),
  allowlist reachable, username/body not persisted; future terminal-`Z` source
  evidence rejected as `lookahead` (source-validation boundary, not merely a future
  `to_date`).
- **Original CI failures under simulation:** the exact prior simulation harness
  (patch only `policy.datetime.fromisoformat` to reject terminal `Z`, socket-disabled)
  now runs the two original CI tests → **2 passed / 0 socket attempts**
  (`PYTEST_EXIT: 0`).
- **Verification commands and exact outcomes:**
  - `pytest -q -p no:cacheprovider tests/test_policy_to_date_python310.py` → 39 passed.
  - focused/regression `... test_policy_to_date_python310.py test_structured_evidence_ingestion.py test_market_evidence_gate.py test_evidence_step2_regressions.py`
    → **191 passed**.
  - `tests/test_structured_evidence_ingestion.py` alone → **53 passed**.
  - full strict-offline harness (`scripts/validate/strict_offline_harness.py`) →
    **2406 passed, 1 skipped (optional `langchain_aws` absent), 1 deselected, 22
    warnings, 88 subtests, 0 forbidden socket attempts**.
  - extracted production guard/helper/`to_date` under local **Python 3.9.25**
    (stdlib only; a real older parser, NOT project 3.10 proof) → 22-case
    accepted/rejected matrix, **0 failures** (HH-only/HH:MM included).
  - `ruff check .` → All checks passed.
  - `scripts/validate/validate_requirements.py` → **43/43 valid, secret scan clean,
    RESULT: PASS**.
  - `git diff --check` clean; the new untracked test file was separately checked for
    trailing whitespace / missing final newline (none).
- **Limits (honest):** the pre-3.11 behavior is proven by a deterministic simulated
  parser restriction plus extraction of the production guard/helper run under a local
  standard-library Python 3.9.25 interpreter (a real older parser, **not** the
  project's 3.10 and never labelled as 3.10 proof); **no actual Python 3.10 runtime is
  installed** here and none was installed. The actual remote Python 3.10 CI re-run on
  the repair **remains pending** (no push authorized). This is offline evidence only.

### Independent Codex technical verification of the Python 3.10 CI repair — COMPLETE (logbook 089; NOT human acceptance, NOT a real 3.10 run)

Independent Codex technical verification of the current covered offline scope is
**COMPLETE** (`docs/review-memo.md`, `docs/ai-use-log.yaml`). It confirms the tested
behavior; frozen files unchanged. Supplied independent results (recorded, not
re-guessed):

- full strict-offline → **2406 passed / 1 skipped / 1 deselected / 22 warnings / 88
  subtests / 0 forbidden socket attempts**;
- focused **5-module** subset (`test_policy_to_date_python310.py` +
  `test_structured_evidence_ingestion.py` + `test_market_evidence_gate.py` +
  `test_exact_claim_validation.py` + `test_debate_evidence_manifest.py`) → **240
  passed / 0 sockets** — a **different subset** than the builder's 191-module-focused
  run; the two are **not conflated**;
- the exact original 2 CI tests under the simulated pre-3.11 terminal-`Z` restriction →
  **2 passed / 0 sockets**;
- extracted actual production helper+`to_date` AST executed with real **Python 3.9.25**
  stdlib → **22/22 checks pass**; the same 22-case probe on **3.12.7** also passes
  (NOT actual 3.10 or full-project 3.9 proof);
- `ruff check .` clean; governance **43/43 PASS**; `git diff --check` clean; the new
  untracked test file separately checked for trailing whitespace / extra EOF blank and
  secrets → clean; SHA verification confirms the tested behavior.
- **Honest `zZ` wording (corrected, docs only):** the original **unmodified** 3.12
  `policy.to_date("2026-05-10T12:00:00zZ")` **already returns 2026-05-10**, whereas
  native 3.9 rejects it. The current helper correctly leaves `zZ` unchanged, preserving
  that interpreter-native legacy behavior; **no new rejection was introduced in
  source** and `zZ` is **not** claimed globally rejected across versions. The accurate
  claim is "malformed suffix is not rewritten and raw parser behavior is retained", with
  native-3.9 rejection documented specifically. Terminal lowercase `z` and repeated
  uppercase `ZZ` tested rejection still holds. The independent 22-case probe records
  `zZ` as **NATIVE PARITY** (not universal `None`).
- **Artifacts (backed up outside repo by the independent verifier to
  `/Users/wangyiwen/OpenCodeRecords/TradingAgents`):** `python310-independent-full-offline.log`,
  `python310-independent-focused.log`, `python310-original-ci-simulation.log`,
  `python310-native39-date-checks.json`, `python310-native312-date-checks.json`.
- **Status:** independent Codex technical review **COMPLETE**. Human plan+test approval
  remains **implementation-only**; **explicit final HUMAN acceptance and the actual new
  remote Python 3.10 CI remain PENDING** (no push authorized). This is offline technical
  evidence only — not a live/3.10 CI proof and not human acceptance.
