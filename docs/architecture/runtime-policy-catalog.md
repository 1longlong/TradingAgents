# Runtime Policy Catalog

This catalog lists the deterministic policy/config surface that controls the
CS5351 feature behavior. It is the reference for the settings that are
validated before graph execution, plus their safe defaults. The authoritative
default values live in the source; this document records their meaning.

## Data Quality Gate policy (evidence)

`tradingagents/evidence/policy.py` defines `MarketPolicy`, `MarketRecordPolicy`,
and `MetricTolerance` using quantized `Decimal`. The `policy_version` is carried
on every `GateDecision` for auditability (`NFR-AUD-001`).

| Setting | Meaning | Default |
| --- | --- | --- |
| `policy_version` | Stamped policy version on every gate verdict | (recorded on the policy object) |
| `min_independent_sources` | Independently credible sources required for a `High` group | see `DEFAULT_MARKET_POLICY` |
| threshold tolerances | Per-metric Decimal tolerances for cross-source consistency | see `MetricTolerance` |

Semantics are confirmed by the policy object; the exact numeric defaults are in
`tradingagents/evidence/policy.py` and are not re-invented here.

## Debate termination policy (config)

`tradingagents/debate/config.py` defines `DEFAULT_DEBATE_TERMINATION_CONFIG`
(tuned by `resolve_debate_termination_config`). All fields are validated by
`DebateTerminationConfig.validate`; a frozen instance cannot diverge afterward.

| Setting | Meaning | Default |
| --- | --- | --- |
| `enabled` | `True` uses dynamic rules; `False` reproduces legacy fixed-round routing | `True` |
| `no_new_evidence_patience` | Rounds of no-new-valid-evidence before `no_new_evidence` stop | `1` |
| `stance_distance_threshold` | Max rating distance for "stances close" | `1.0` |
| `confidence_delta_threshold` | Max confidence delta for "close" and "material change" | `0.25` |
| `max_calls` | Hard limit on **debate** calls (NOT the whole-run call count) | `2_000_000` |
| `max_tokens` | Hard limit on **debate** tokens, compared against the deterministic estimate (NOT a measured provider bound) | `2_000_000` |
| `max_time` | Hard limit on **debate** elapsed seconds, compared against the deterministic estimate (NOT measured wall-clock) | `600.0` |
| `reserved_summary_tokens` | Reserved summary token reserve | `4_000` |
| `reserved_summary_seconds` | Reserved summary time reserve | `90.0` |
| `next_round_estimate_tokens` | Estimated next-round token cost for budget accounting | `2_000` |
| `next_round_estimate_seconds` | Estimated next-round time cost for budget accounting | `60.0` |
| `max_debate_rounds` | Legacy fixed-round cap (used when `enabled=False` / rule ordering) | `1` |
| `evidence_manifest_field` | AgentState field holding gate manifest evidence records | `data_quality_evidence_records` |
| `trace_field` | AgentState field holding the termination decision trace | `debate_termination_decision` |

## Budget accounting (corrected 2026-11-06)

`tradingagents/debate/budget.py` estimates and accounts for token/time/call
usage deterministically. Important corrections to earlier wording:

- The summary reserve is checked **before EVERY Bull/Bear admission** (a
  conservative pre-call guard in `can_afford_optional_call`), not merely before a
  `continue` verdict. The check requires
  `remaining >= reserved_summary + next_round_estimate`, with exact token/time
  boundaries tested before the first Bull and before Bear
  (`tests/test_debate_precall_budget.py`).
- The limits are **debate-scoped** (`max_calls`/`max_tokens`/`max_time` bound the
  debate optional calls), **not** whole-run limits. The call limit concerns debate
  calls, not total-run calls.
- Token/time figures are **deterministic ESTIMATES** (char-based), **not actual
  provider bounds**. The guard cannot be claimed to enforce physical provider
  usage.
- **Live discrepancy (OPEN, DEBT-021 / RISK-021):** a 2026-11-06 authorized live
  run showed the estimate is wildly off (Bull estimated 2,171.77 s vs actual
  12.72 s; 16,289 estimated vs 18,058 reported tokens), so the estimate exhausted
  the debate time budget and Bear was refused with `budget_exhausted` before any
  complete round. The guard is active and safe; the **accounting basis is the
  open defect**. It is NOT fixed in this documentation round.
- Therefore the truthful statement is: the reserve/admission guard is enforced
  against **estimates**; a run is **not** guaranteed against real-budget
  exhaustion until measured usage is wired in (an authorized implementation round).

## Enforcement

A misconfigured `debate_termination` block raises `ValueError` in `validate`
before graph execution, so a bad config is reported explicitly rather than
silently degrading to a default (`FR-DDT-004`, `NFR-BC-001`).

## Failure / degraded behavior: trigger → action → audit hook → recovery

This table records what the code **actually** does today (`REAL`), and marks
`PENDING` where no fallback/implementation exists (do not invent one). Where the
status is `PENDING`, the correct behavior is to **STOP and make no completed-report
claim** rather than proceed.

| Trigger | Action (actual) | Audit hook (actual) | Recovery / status |
| --- | --- | --- | --- |
| Missing **critical** market evidence / gate internal error | Fail closed → gate `blocked`; router skips debate → Research Manager; output pinned to Hold | `data_quality_error`, `data_quality_gate_decision`, gate_summary, `gate_blocked` reason | **REAL** (offline-tested). Live blocked-path not exercised (RISK-023). |
| Missing **optional** category (fundamentals/news/sentiment) with no trustworthy structured source | Deterministic `Low`/`unavailable_no_structured_source`; may degrade but never block (market is critical) | `data_quality_group_statuses`, gate_summary category table | **REAL** (observed live 2026-11-06: all optional Low → degraded). Automatic adapters OPEN (DEBT-015). |
| Malformed `DEBATE_METADATA` (missing marker) | Parse contributes **zero** new evidence; never extends the debate (best-effort prose fallback) | turn parse result / decision trace | **REAL** (offline-tested, FR-DDT-002). |
| Pre-call budget refusal (remaining < reserve + estimate) | Refuse the optional call; route to Research Manager with `budget_exhausted` for the incomplete round | `debate_usage` (estimated flag), `budget_exhausted` stop_reason, debate_trace | **REAL** (offline-tested). Basis is ESTIMATE (DEBT-021); live run refused Bear prematurely. |
| Evaluator internal error | Fail closed → `summarize`/`insufficient_evidence` | `debate_termination_decision` trace, `insufficient_evidence` reason | **REAL** (offline-tested). |
| Model / provider failure mid-run | Graph error propagates; no partial "completed report" is claimed | error surfaced by the run harness (no dedicated artifact field) | **PARTIAL / PENDING:** no dedicated in-repo recovery artifact; treat as STOP, do not claim a completed report. |
| Report write / artifact error | `write_report_tree` relies on redaction + safe defaults; a raised error surfaces | report artifacts absent/partial | **PENDING:** no dedicated audit_incomplete fallback artifact exists in this repo; STOP rather than claim a completed report. |
| `audit_incomplete` condition | (no explicit marker emitted by this codebase) | — | **PENDING — NOT IMPLEMENTED.** Recorded as a gap (DEBT-015); do not fabricate a fallback. |

## Still open (unchanged by this documentation round)

- Degraded-run numeric confidence ceiling: OPEN (DEBT-014), not invented.
- Automatic optional multi-category adapters / full source-attempt lifecycle:
  OPEN (DEBT-015 / RISK-015).
- Live measured latency/token budget accounting: OPEN (DEBT-021 / RISK-021).
- Claim-date semantic validation: OPEN (DEBT-022 / RISK-020).
- CLI state-passing hardening: OPEN (as recorded in prior milestones).