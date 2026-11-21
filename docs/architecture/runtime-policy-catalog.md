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

# Runtime Policy Catalog

This catalog lists the deterministic policy/config surface that controls the
CS5351 feature behavior. It is the reference for the settings that are
validated before graph execution, plus their safe defaults. The authoritative
default values live in the source; this document records their meaning.

## Data Quality Gate policy (evidence)

`src/tradingagents/evidence/policy.py` defines `MarketPolicy`, `MarketRecordPolicy`,
and `MetricTolerance` using quantized `Decimal`. The `policy_version` is carried
on every `GateDecision` for auditability (`NFR-AUD-001`).

| Setting | Meaning | Default |
| --- | --- | --- |
| `policy_version` | Stamped policy version on every gate verdict | (recorded on the policy object) |
| `min_independent_sources` | Independently credible sources required for a `High` group | see `DEFAULT_MARKET_POLICY` |
| threshold tolerances | Per-metric Decimal tolerances for cross-source consistency | see `MetricTolerance` |

Semantics are confirmed by the policy object; the exact numeric defaults are in
`src/tradingagents/evidence/policy.py` and are not re-invented here.

## Debate termination policy (config)

`src/tradingagents/debate/config.py` defines `DEFAULT_DEBATE_TERMINATION_CONFIG`
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

`src/tradingagents/debate/budget.py` estimates and accounts for token/time/call
usage deterministically. Important corrections to earlier wording:

- The summary reserve is checked **before EVERY Bull/Bear admission** (a
  conservative pre-call guard in `can_afford_optional_call`), not merely before a
  `continue` verdict. The check requires
  `remaining >= reserved_summary + next_round_estimate`, with exact token/time
  boundaries tested before the first Bull and before Bear
  (`test/offline/test_debate_precall_budget.py`).
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

## WebUI extension

# TradingAgents WebUI Runtime Policy Catalog

Status: **Approved for documentation by the human owner on 2026-11-05.** These policies describe required runtime behaviour. No policy below is implemented. Each names an enforcement module and a fallback.

## WEB-POLICY-001 — Loopback-only listener

Trigger: server start.
Rule: bind `127.0.0.1` only; reject non-loopback `Host`; no wildcard CORS.
Enforcement: `settings.py`, `security.py`.
Fallback: refuse to start on a non-loopback address.

## WEB-POLICY-002 — Single active run

Trigger: a new analysis or backtest request.
Rule: if a run is `starting`, `running`, or `cancelling`, return `409` with the active run id. No queue.
Enforcement: `runtime/coordinator.py`.
Fallback: return the active run id so the client can reattach.

## WEB-POLICY-003 — Process-lifetime run state

Trigger: browser disconnect, refresh, or network loss.
Rule: continue the run; allow reattachment from the last sequence within the process lifetime. A restart loses the run.
Enforcement: `runtime/coordinator.py`, `runtime/event_buffer.py`.
Fallback: show "run no longer available"; on-disk artifacts and checkpoints remain.

## WEB-POLICY-004 — Analysis cancellation

Trigger: a same-origin cancel request for the active analysis.
Rule: set the cancel event; stop at the next chunk; do not call `record_decision`; do not call `clear_checkpoint_on_success`; `end_checkpoint()` in `finally`; keep partial artifacts; publish `run.cancelled`.
Enforcement: `runtime/coordinator.py`.
Fallback: if the worker does not stop in 30 s, report `cancelling` and keep the slot until it exits.

## WEB-POLICY-005 — Checkpoint controls

Trigger: checkpoint toggle or clear-all.
Rule: the toggle affects the next run only. Clear-all requires `{"confirm": "CLEAR"}` and is rejected while a run is active. Clear-all calls `clear_all_checkpoints`.
Enforcement: `api/runs.py`, `runtime/coordinator.py`.
Fallback: reject the clear, report the count cleared, never expose a path.

## WEB-POLICY-006 — Server-only provider keys

Trigger: configuration display or run start.
Rule: read keys only from the server environment; return `configured / not_configured / not_required`; never accept, store, return, log, or export a key. A missing key does not block start; the first provider call fails safely.
Enforcement: `api/config.py`, `models/responses.py`, `errors.py`.
Fallback: show a safe configuration error; keep the run record.

## WEB-POLICY-007 — Deterministic identifiers

Trigger: any ticker, run id, artifact id, or path component from a client.
Rule: validate with existing rules before filesystem use; reject absolute paths, `..`, backslashes, and values outside the allowlist.
Enforcement: `api/runs.py`, `artifacts/index.py`.
Fallback: reject; never widen the path.

## WEB-POLICY-008 — Artifact ids, not paths

Trigger: any response referencing an artifact.
Rule: return `sha256(relative_path)[:16]`; resolve server-side through a 5 s in-memory map; omit path fields.
Enforcement: `artifacts/index.py`, `models/responses.py`.
Fallback: omit the artifact and return a safe not-found.

## WEB-POLICY-009 — Read-only history

Trigger: history or backtest-history request.
Rule: read only; no delete, rename, move, rotation, migration, or index write.
Enforcement: `artifacts/index.py`, `artifacts/readers.py`, `api/history.py`.
Fallback: reject any mutating request.

## WEB-POLICY-010 — Backtest isolation

Trigger: backtest request.
Rule: use the backtest's own run directory and memory log; never read or write the live decision log. A backtest occupies the single-run slot.
Enforcement: `runtime/backtest_runner.py`.
Fallback: abort and report the isolation failure.

## WEB-POLICY-011 — Announcement handling

Trigger: page load or refresh.
Rule: fetch server-side; on failure use the CLI fallback; `require_attention=true` blocks until acknowledged; render as untrusted text.
Enforcement: `api/announcements.py`, `frontend/src/components/Announcements`.
Fallback: show the fallback link and do not block.

## WEB-POLICY-012 — Untrusted rendering

Trigger: model output, tool output, announcements, artifact text, portfolio text.
Rule: escaped text or sanitized Markdown; no raw HTML; no script; no `javascript:`/`data:` links; no server-side template evaluation.
Enforcement: `frontend/src/components/Markdown.tsx`, `security.py`.
Fallback: plain text.

## WEB-POLICY-013 — Error redaction

Trigger: any validation, upstream, storage, or internal error.
Rule: return category, safe message, correlation id; redact keys, tokens, cookies, authorization headers, paths, and stack traces.
Enforcement: `errors.py`, `security.py`.
Fallback: generic internal error with a correlation id.

## WEB-POLICY-014 — Bounded event buffer

Trigger: event publication or subscription.
Rule: bounded buffer (10,000 events or 8 MB), bounded subscriber queue (1,000), snapshot fallback, heartbeat every 15 s.
Enforcement: `runtime/event_buffer.py`.
Fallback: drop the subscriber to snapshot mode; keep the run alive.

## WEB-POLICY-015 — No execution authority

Trigger: any rating, report, or model output.
Rule: display only; no order/position endpoint; no brokerage dependency.
Enforcement: route inventory, `api/`.
Fallback: remove the endpoint or control.

## WEB-POLICY-016 — Honest run state

Trigger: completion, failure, cancellation.
Rule: derive state from actual stream completion and artifact writes; show partial artifacts as partial; do not report an unreadable rating as a position.
Enforcement: `runtime/coordinator.py`, `frontend/src/pages/Report`.
Fallback: show failed/review and preserve raw decision text.

## WEB-POLICY-017 — Backtest has no cancel control

Trigger: a backtest is running.
Rule: do not expose a cancel route or button. State that the backtest runs to completion and can be resumed with `run_id`.
Enforcement: `api/backtests.py`, `frontend/src/pages/Backtest`.
Fallback: remove any misleading control.

## WEB-POLICY-018 — Same-origin state-changing requests

Trigger: POST/DELETE from the browser.
Rule: require the per-process `X-CSRF-Token`; if `Origin` is present it must match the loopback origin; reject cross-origin; no wildcard CORS.
Enforcement: `security.py`.
Fallback: 403 with a safe message.

## WEB-POLICY-019 — Static asset presence

Trigger: server start.
Rule: if `static/index.html` is missing, start in API-only mode with a clear build instruction; never serve a broken UI silently.
Enforcement: `app.py`, `cli.py`.
Fallback: API-only mode; CI packaging test fails.

## WEB-POLICY-020 — Run artifact writing

Trigger: analysis run.
Rule: write `message_tool.log` and `reports/<section>.md` in the CLI layout; auto-save the complete tree on success; keep partial artifacts on cancel/failure; do not write `full_states_log`.
Enforcement: `runtime/artifacts_writer.py`.
Fallback: emit `storage` warning; keep the analysis result and partial artifacts.
