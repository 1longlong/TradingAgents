# ADR-003 — Phase 4A Deterministic Offline Baseline Comparison

- **Status:** **Accepted — approved with limitations** (human review, 2026-10-23;
  `docs/review-memo.md`, logbook 056). The Phase 4A fail-closed correction and
  short re-review were reviewed and accepted subject to the recorded limitations
  (offline-only verification; the full suite is not completely green due to the
  known date-sensitive cache failures; human traceability scores remain
  `pending`; no final production threshold tuning performed). The prior
  **Changes requested** decision and the intervening correction rounds are
  retained verbatim as historical audit evidence and are not deleted.
- **Date:** 2026-10-21 (updated 2026-10-23: correction round + human approval)
- **Deciders:** CS5351 project (student), with coding-agent and human review
- **Trace:** `NFR-CMP-001`, `NFR-CMP-002`, `NFR-CMP-003`, `NFR-DET-001`, `NFR-FC-001`, `NFR-OFF-001`

## Context

Phase 3B introduced the dynamic, evidence-aware debate-termination policy
alongside the legacy fixed-`max_debate_rounds` baseline. To decide whether (and
when) the dynamic policy is worth its added complexity, the project needs an
**apples-to-apples measurement** of the two strategies. That measurement must
itself be deterministic, offline, and LLM-free so it can be recorded honestly
and re-run without a live provider; otherwise the "improvement" claim rests on
vendor-call quality and cannot be independently reproduced.

The measurement must be made on **identical inputs** so any difference is
attributable to the policy and not to a different case, evidence snapshot,
policy version, or debate input. In addition, the measurement must be clearly
distinguished from a live-provider benchmark: the numbers in Phase 4A are
deterministic scripted fixtures, not a real run signal, and human traceability
is a separate rubric scored by a human.

## Decision

Introduce a pure, LLM-free, network-free **comparison model/runner** under
`tradingagents/comparison/` with four roles:

1. **`schemas`** — typed, validated, JSON-safe records:
   - `CaseIdentity(ticker, target_date, evidence_snapshot_id, policy_version)`:
     the shared, validated quadruple both strategies must match **exactly**. A
     mismatch fails closed.
   - `CaseResult` / `CaseAggregate`: the measured + estimated outcome per
     strategy per case, and its derived per-case metrics.
   - `ComparisonReport`: the aggregate of the paired cases.
   - `PairingError`: raised (fail closed) when two results are not provably the
     same case.
   - `TraceabilityStatus` + `TRACEABILITY_DIMENSIONS`: a documented rubric with
     human-entered per-dimension scores in `[0, 1]`; an unscored case stays
     `pending` with `None` scores. A `SCORED` result requires exactly four
     non-null scores, one per `TRACEABILITY_DIMENSIONS` dimension, in that exact
     positional order; a missing, extra, null, duplicate, or reordered dimension
     set fails closed rather than silently mis-reporting a rating (correction
     round). The `CaseResult.stop_reason` field preserves the *actual*
     deterministic reason the run stopped (`StopReason.value` for a genuine
     stop, `max_rounds_reached` for the hard cap, `input_exhausted` when the
     scripted input ran out, `""` when no round executed); it is never
     substituted with a generic or inferred label.

2. **`metric_formulas`** — explicit pure metric functions:
   - `early_stop_rate = early_stopped / cases` (per case: `1.0` or `0.0`).
   - `evidence_citation_coverage = valid_cited_evidence_count /
     total_eligible_evidence_ids` — numerator is the count of **valid** cited
     evidence IDs (known, High/Medium, on-or-before target, linked to a claim);
     the denominator is the count of eligible IDs in the snapshot.
   - `false_strong_conclusion_rate = false_strong_conclusion_count /
     strong_conclusion_count` — derived from the explicit `strong_conclusion`
     flag ANDed with a gate/quality outcome that does not support a strong
     conclusion (never inferred from prose).
   - `traceability_mean` — arithmetic mean of the human-entered scores, `None`
     when pending.
   - Every ratio has an explicit denominator; a zero denominator returns `None`
     (never raises, never fabricates).

3. **`runner`** — the deterministic replay + aggregation:
   - `replay_scripted_case(ScriptedCase)` replays one scripted case through both
     strategies using the pure `evaluate_round` rules (dynamic) and the fixed
     cap (baseline), over the identical evidence snapshot and scripted turns.
   - `pair_and_aggregate(results)` pairs FIXED and DYNAMIC results by exact
     identity and derives the aggregate; any mismatch/missing/duplicate fails
     closed with `PairingError`.
   - `_valid_cited_ids` filters the union of cited evidence IDs through
     `is_valid_new_evidence` (the manifest allowlist) so only **valid** new
     cited evidence counts toward coverage.
   - **Correction round:** `replay_scripted_case` distinguishes a genuine
     dynamic-policy early stop from a scripted input that simply ran out of
     available rounds. A run with no non-`continue` policy decision is recorded
     as `stop_reason == input_exhausted` and `early_stopped == False` — it is
     never mislabelled as a dynamic early stop. The actual `stop_reason` is
     preserved end-to-end (per-case result, per-case and aggregate
     `CaseAggregate`/JSON, and the Markdown per-case + aggregate tables).

4. **`report`** — deterministic JSON + Markdown writers that consume a
   `ComparisonReport` and emit `comparison_results.json` +
   `comparison_report.md` without touching raw fixtures. The Markdown asserts an
   honest scope disclaimer (offline scripted, not a live-provider result, no
   final tuning, traceability pending). The aggregate and per-case output
   **visibly preserves the usage provenance** (`tool_usage_estimated` per case;
   `fixed/dynamic_estimated_cases` aggregate status) and includes **tool-call
   counts** (per case and aggregate) so an estimated value is never presented as
   measured and the tool footprint is never omitted. The per-case and aggregate
   output also preserve the **actual stop reason** per strategy so the
   termination decision stays auditable (never a generic/inferred label).

A `scripts/run_phase4a_comparison.py` replays the representative scripted
fixtures (scenarios D/E/F) and writes the `evaluation-output/` artifacts.

### Representative scripted scenarios (Phase 4A)

- **D — no new evidence:** snapshot has no valid citable IDs; the dynamic policy
  stops early on `no_new_evidence` while the fixed baseline runs the full
  `max_debate_rounds`.
- **E — new valid evidence extension:** a blocking interpretive conflict remains
  and a NEW High/Medium evidence ID appears mid-debate, so the dynamic policy
  **extends** the debate to absorb the new evidence (does not early-stop),
  while a no-new-evidence policy would have stopped.
- **F — budget protection:** the budget is nearly exhausted, so the dynamic
  policy genuinely stops on `budget_exhausted` (rule 2) to guarantee the summary
  reserve and never exceed the hard cap; the fixed baseline consumes far more
  budget than the reserve allows.

Full-fixture and scripted-run reprisal is offline and LLM-free.

### Correction round (Phase 4A human review, 2026-10-22 — implemented 2026-10-23)

The Phase 4A human review (`docs/review-memo.md`, WANG Yiwen 60536848) requested
corrections before approval. Four corrections were implemented and verified:

1. **Strict four-score traceability validation.** A `CaseResult` with
   `traceability_status == SCORED` now requires exactly four non-null scores, one
   per `TRACEABILITY_DIMENSIONS` dimension, in that exact positional order
   (source_attribution, reasoning_clarity, evidence_groundedness,
   decision_auditability). A missing, extra, null, duplicate, or reordered
   dimension set fails closed with `ValueError` instead of silently mis-reporting
   a rating. The `traceability_scores_for_dimensions` helper is the single entry
   point for a keyed/pairwise score set and enforces the same contract. A
   `PENDING` result keeps any score shape and reports no mean.
2. **Input exhaustion is not a dynamic early stop.** A short scripted input that
   simply runs out of rounds (with no non-`continue` policy decision) is recorded
   as `stop_reason == input_exhausted` and `early_stopped == False`, never
   mislabelled as a dynamic-policy early stop. Scenario G
   (`case_input_exhaustion`) is the regression fixture.
3. **Actual stop reason preserved.** The real deterministic `stop_reason`
   (`no_new_evidence`, `budget_exhausted`, `max_rounds_reached`,
   `input_exhausted`) is preserved in the `CaseResult`, the per-case/aggregate
   `CaseAggregate`/JSON, and the Markdown per-case + aggregate tables
   (`fixed/dynamic_stop_reasons`). `max_rounds_reached` (the hard cap) is not an
   early stop, and `input_exhausted` is not a policy decision.
4. **Regression coverage.** `tests/test_comparison_schemas.py` and
   `tests/test_comparison_runner.py` were extended; **73 focused comparison tests
   pass** (was 47) (logbook 054).

Human traceability scores remain **pending** — no scores were entered by this
change.

### Narrow fail-closed correction (short re-review, 2026-10-23)

A second, narrow correction was implemented and verified. Previously
`CaseResult.__post_init__` normalized fields but did **not** validate the
`strategy` / `early_stopped` / `stop_reason` interaction, so a contradictory
combination (e.g. a `FIXED` result claiming `early_stopped == True`, or an
early-stopped `DYNAMIC` result carrying an empty / `input_exhausted` /
`max_rounds_reached` / unknown stop reason) could be constructed and
propagated into the aggregate and reports. Now:

- `StrategyKey.FIXED` must never be `early_stopped == True`.
- `early_stopped == True` is permitted only for `StrategyKey.DYNAMIC` **and**
  only when `stop_reason` is a recognized genuine dynamic early-stop reason. The
  check reuses the existing `_DYNAMIC_STOP_REASONS` allowlist (no duplicate
  allowlist). `input_exhausted`, `max_rounds_reached`, an empty stop reason, and
  any unknown stop reason are rejected when `early_stopped == True`.

Because the fix fails closed at construction, a contradictory result can never
reach `compute_case_aggregate` / `pair_and_aggregate` / the report writer, so
`early_stop_rate` and the "yes"/"no" early-stop label can never be produced or
rendered for one. Valid runner outputs and JSON round trips are preserved: the
genuine dynamic early-stop reasons (`no_new_evidence`, `budget_exhausted`,
`insufficient_evidence`, `consensus_reached`, `diminishing_returns`) remain
accepted, and fixed / non-early / `input_exhausted` results are unaffected (they
are never early-stopped).

Verification: **90 focused comparison tests pass** (logbook 055), governance
validator PASS, governance scaffold tests 16 passed, Ruff clean (full repo),
`git diff --check` clean; full offline suite **3 known date-sensitive cache
failures** (network-reachability baseline did not fail this run), no new
regression. *(At this point Phase 4A was still recorded as "Changes requested /
pending human re-review"; that status was later superseded by the 2026-10-23
human review decision "Approved with limitations" — see the Status header
above and `docs/review-memo.md`.)*

Human traceability scores remain **pending** — no scores were entered by this
change.

## Consequences (positive)

- The two strategies are measured on identical inputs, so differences are
  attributable to the policy.
- Deterministic and offline; reproducible across runs and environments.
- Fail-closed pairing prevents comparing unequal cases.
- Measured vs estimated values are separated; human traceability stays pending
  until a human scores it.

## Consequences (negative / trade-offs)

- The Phase 4A numbers are **scripted offline fixtures**, not live-provider
  measurements, so they cannot support a production-grade performance claim on
  their own. This is stated honestly in the report and Report.md.
- Human traceability scores are not yet present — they require a human to score
  each case against the rubric; they are pending, not fabricated.
- The comparison model is a separate package; it must be kept in sync with the
  debate evaluator's rule ordering (rule precedence is subtle, NFR-DET-001).
- No production thresholds were tuned: the fixtures use test-pinned policy
  knobs (policy version `1.0`); production tuning is out of Phase 4A scope.

## Alternatives considered

- Live-provider comparison (rejected for Phase 4A: requires paid API and is not
  offline-reproducible). Live provider benchmarking is out of scope for the
  offline deterministic suite.
- Single-strategy instrumentation (rejected: does not give an apples-to-apples
  delta on identical inputs).

## Related

- `docs/architecture/adr/002-dynamic-debate-termination.md`
- `docs/architecture/invariants.md`
- `docs/architecture/trace-matrix.md`
- `docs/architecture/evaluation-logbook.md`