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

# System Invariants (non-negotiable) — Register

These invariants constrain every change to the CS5351 feature work. A change
that violates one is not acceptable, even if it makes a test pass. This is a
**register**: every invariant records its source requirement IDs, the actual
enforcer module, positive and negative verification, a concrete fail-closed /
degraded fallback, and the current enforcement gap. It is traced in
`docs/architecture/trace-matrix.md`.

Status vocabulary:
- **Enforced (code, offline)** — a module enforces it and offline unit/graph tests
  prove it on the covered path. This does NOT by itself prove live end-to-end
  runtime behavior; where a substantive runtime gap exists it is called out.
- **Enforced (process)** — enforced by governance/process (prompt, review,
  validator), not by runtime code.
- **Partial** — enforced on the covered path only; a named gap remains (offline
  vs. live, or one category vs. all).
- **Unverified** — stated intent not yet mechanically proven.
- **Not implemented** — no code exists.

No invariant is claimed globally "Enforced" for live runtime; the 2026-11-06
NVDA run was **degraded**, not blocked. A 2026-11-10 bounded validation added a
**narrow controlled-fixture blocked-path proof** (D2: real gate + real RM/Trader/
risk/Portfolio nodes, zero Bull/Bear invokes, Hold throughout) — this is not an
exhaustive or live-vendor blocked proof.

## INV-1 Fail closed on missing evidence or internal error

- **Source requirements:** FR-DQG-002, NFR-FC-001, FR-DDT-001, FR-DQG-006.
- **Enforcer:** `src/tradingagents/evidence/gate.py` (exception → `blocked`),
  `src/tradingagents/graph/data_quality_gate.py` (`data_quality_error` → blocked),
  `src/tradingagents/debate/evaluator.py` (error → `summarize`/`insufficient_evidence`),
  `src/tradingagents/agents/utils/output_guard.py` (`is_blocked_run` fail-closed),
  `src/tradingagents/graph/signal_processing.py` (blocked → Hold).
- **Positive verification:** `test/offline/test_data_quality_gate_graph.py`,
  `test/offline/test_market_evidence_gate.py`, `test/offline/test_debate_evaluator.py`,
  `test/offline/test_output_guard.py` (missing/malformed gate state → Hold).
- **Negative verification:** `test/offline/test_output_guard.py` asserts a mutated
  missing/malformed gate cannot yield Buy; `test/offline/test_market_evidence_gate.py`
  asserts a raised exception becomes `blocked`, not `normal`.
- **Fallback:** verdict is `blocked`; router routes to Research Manager; output
  pinned to Hold; final signal Hold.
- **Enforcement gap / status:** **Enforced (code, offline)** on the covered path (blocked path proven offline; the 2026-11-06 live run was degraded, not blocked). 2026-11-10 D2 adds a narrow **controlled-fixture** blocked-path live proof (real gate + real downstream nodes; zero Bull/Bear invokes; Hold throughout) — not exhaustive/live-vendor. The degraded-run confidence ceiling (DEBT-014) is now enforced by ADR-011 Stage 4 (0.60 engineering ceiling; offline-verified 2026-11-11, logbook 082; awaiting independent OpenCode review + human acceptance) — it is a confidence/audit control, not a fail-closed gap; `blocked` runs keep their Hold discipline.

## INV-2 Determinism of the gate and evaluator

- **Source requirements:** NFR-DET-001, FR-DQG-001, FR-DDT-001.
- **Enforcer:** `src/tradingagents/evidence/{quality,gate,multi_category_gate}.py`,
  `src/tradingagents/debate/{evaluator,conflicts}.py` (pure, no clock/RNG/network).
- **Positive verification:** `test/offline/test_evidence_models.py`,
  `test/offline/test_debate_evaluator.py`, `test/offline/test_debate_conflicts.py`
  (repeat/shuffled-order equality).
- **Negative verification:** shuffled-evidence ordering tests assert identical
  output; no test observes a clock/RNG dependency.
- **Fallback:** only injected validated ISO-8601 `decided_at`; absent → fixed UTC string.
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-3 Point-in-time integrity (no look-ahead)

- **Source requirements:** NFR-PIT-001, FR-DDT-005, NFR-CMP-001.
- **Enforcer:** `src/tradingagents/evidence/validate.py` (look-ahead class),
  `src/tradingagents/dataflows/market_data_validator.py` (`as_of` boundary),
  `src/tradingagents/debate/conflicts.py` (future ID never creates/keeps a conflict),
  `src/tradingagents/debate/claims.py` + `src/tradingagents/evidence/origin.py` (ADR-010:
  a typed exact claim's date is validated against the matching typed date role
  only; a matched-but-future role value is a look-ahead rejection).
- **Positive verification:** `test/offline/test_fundamentals_lookahead.py`,
  `test/offline/test_news_lookahead.py`, `test/offline/test_social_lookahead.py`,
  `test/offline/test_memory_pointintime.py`, `test/offline/test_exact_claim_validation.py`
  (role separation, target != observation, SEC filed != fiscal end, timestamp
  granularity).
- **Negative verification:** conflict tests assert a future-dated ID drops an
  open conflict; look-ahead tests assert future rows are rejected; the exact-claim
  tests assert a date-only source cannot prove a timestamp and a same-day-wrong-hour
  timestamp is a mismatch.
- **Fallback:** record rejected / conflict dropped / claim `unverified` (fail closed).
- **Enforcement gap / status:** **Partial → improved (code, offline).** The PIT
  tests are date-sensitive (RISK-001). The 2026-11-06 RISK-020 live defect (valid
  close ID, wrong claim date) is now ADDRESSED offline for **typed exact claims**
  (ADR-010, 2026-11-11): an exact claim's date/value/unit is validated against the
  record + typed origin metadata (distinct target/observation/availability/timestamp
  roles). This does NOT prove arbitrary natural-language semantics: prose beyond the
  conservative inline-exact-claim parser stays `unverified` (never "verified").

### D2 integration note — personal point-in-time invariant merged here (2026-11-21)

The token-observability delivery stated the same invariant as personal `INV-6` ("no dated
path may read after the trade date"). Its distinct covered behaviour is now part of this
invariant: `tradingagents/dataflows/date_window.py` (`as_of`, `as_of_window`,
`publication_cutoff`, half-open windows, undated exclusion in a historical run,
`withhold_live_profile`), injected `trade_date` in every dated tool, and the memory-log
`as_of` filter. Its status was `PARTIAL` for the same reason as above — there is no global
PIT middleware, so a new vendor or tool must opt in. Its named tests are added to this
invariant's positive verification: `tests/test_tool_date_enforcement.py`,
`tests/test_undated_tools_as_of.py`, `tests/test_pit_notice.py`, plus
`tests/test_memory_pointintime.py` and `tests/test_news_lookahead.py` already listed.
Historical ID: personal `INV-6`; it has no separate row and is not double-counted.


## INV-4 Acyclic, JSON-safe serialization

- **Source requirements:** FR-DQG-001, FR-DQG-003, FR-DQG-005, NFR-AUD-001.
- **Enforcer:** `src/tradingagents/evidence/models.py` (fixed 20-field
  `EvidenceRecord`; separate 7-field `SourceAttempt`; `ValidationResult` refs by
  `evidence_id`), `src/tradingagents/report_artifacts.py` (`to_dict` forms only).
- **Positive verification:** `test/offline/test_evidence_models.py`,
  `test/offline/test_evidence_step2_regressions.py`, `test/offline/test_report_artifacts_audit.py`.
- **Negative verification:** round-trip JSON tests assert no cycles / no frozen
  dataclass written into `AgentState`.
- **Fallback:** serialization error is a fail-closed gate error.
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-5 Stable, deterministic identifiers

- **Source requirements:** FR-DQG-003, FR-DDT-005.
- **Enforcer:** `src/tradingagents/evidence/adapter.py` (`run_id` from
  `(trade_date, normalized symbol)`), `src/tradingagents/debate/conflicts.py`
  (conflict ID from normalized topic/kind).
- **Positive verification:** `test/offline/test_evidence_models.py`,
  `test/offline/test_debate_conflicts.py`.
- **Negative verification:** ID tests assert no random component; same input →
  same ID.
- **Fallback:** none needed (pure derivation).
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-6 Auditability of every decision

- **Source requirements:** NFR-AUD-001, FR-DQG-005.
- **Enforcer:** `src/tradingagents/evidence/models.py` (reason codes, policy
  version, critical evidence IDs), `src/tradingagents/debate/{models,evaluator}.py`
  (decision trace), `src/tradingagents/report_artifacts.py` (artifact export).
- **Positive verification:** `test/offline/test_evidence_models.py`,
  `test/offline/test_debate_evaluator.py`, `test/offline/test_report_artifacts_audit.py`.
- **Negative verification:** artifact audit asserts per-evidence validation
  association and identity/provenance are present (never silently dropped).
- **Fallback:** absent state → safe defaults; never invented values.
- **Enforcement gap / status:** **Enforced (code, offline)**. ADR-007 adds deterministic debate participation truth (structured-only; legacy prose = unverified) surfaced in reports, and a sanitized allow-listed failure ledger (`docs`/`test/offline/test_debate_participation.py`) — never exception text, prompts, bodies or auth. Confirmed by the 2026-11-10 bounded live D2 run: participation explicitly `data_quality_blocked`, zero absent-opponent attribution in the trusted report.

## INV-7 Budget safety

- **Source requirements:** NFR-BUD-001, FR-DDT-003.
- **Enforcer:** `src/tradingagents/debate/{budget,config}.py`,
  `can_afford_optional_call` (remaining ≥ reserved_summary + next-call estimate),
  `src/tradingagents/graph/{setup,conditional_logic}.py`.
- **Positive verification:** `test/offline/test_debate_budget.py`,
  `test/offline/test_debate_precall_budget.py` (exact token/time boundaries).
- **Negative verification:** `max_calls=1` executes exactly one debate call; a
  reserve-only case is refused.
- **Fallback:** refuse the call → Research Manager with `budget_exhausted`.
- **Enforcement gap / status:** **Partial → improved (code, offline).** The
  2026-11-06 run showed the estimate (2171.77 s vs actual 12.72 s) exhausting the
  time budget before Bear (DEBT-021 / RISK-021). ADR-007 repair (2026-11-10):
  each real Bull/Bear call is now timed with an injectable monotonic clock and
  uses provider-reported token usage when valid, with explicitly-labelled
  estimate fallback; invalid/backwards/non-finite clocks abort (no char-time
  revival); per-field provenance and conflict originals are recorded; a
  sanitized failure ledger records aborted attempts. Offline-proven
  (`test/offline/test_debate_budget.py`, `test_debate_researcher_timing.py`) and
  confirmed by the 2026-11-10 bounded live D1 run (real Bull+Bear, measured
  seconds, provider tokens, `transport_attempts` null; stop `max_rounds_reached`,
  not premature `budget_exhausted`). **2026-11-11 Stage 2 (ADR-009, offline):** the
  cross-resume/failed-checkpoint accounting gap is now ADDRESSED offline by a
  durable run-scoped SQLite ledger (`src/tradingagents/debate/usage_ledger.py`): a
  reservation is written BEFORE every outbound call and a settlement after, so a
  crash after the provider succeeds (but before the node/checkpoint update) is
  recovered from the ledger; resume reconciles idempotently (never double-adds);
  an `in_flight`/failed unknown-cost attempt is unresolved possible spend (never
  zero / never free) and fails closed for further OPTIONAL calls; admission
  (call+token+time+reserve+unresolved) is re-read and evaluated INSIDE a
  `BEGIN IMMEDIATE` transaction so independent capture instances cannot both pass
  a stale preflight; a separate summary admission consumes the reserve without a
  second optional estimate. Whole-run usage is aggregated across all phases for
  reporting only (never a budget limit). Proven offline
  (`test/offline/test_durable_usage_ledger.py`, `test/offline/test_whole_run_usage.py`); NOT
  live-confirmed. REMAINING GAP (explicit): hidden SDK transport retries are
  unobserved (`transport_attempts` unknown); a pre-call reservation is an
  ESTIMATE, not a physical billing bound; live cross-process concurrency is
  offline-barrier-proven only.

## INV-8 Backward compatibility

- **Source requirements:** NFR-BC-001, FR-DDT-004.
- **Enforcer:** `src/tradingagents/debate/config.py` (`enabled=False` retains legacy
  routing), `src/tradingagents/graph/setup.py`.
- **Positive verification:** `test/offline/test_debate_config.py`, `test/offline/test_debate_graph.py`.
- **Negative verification:** disabled-config tests assert the legacy fixed-round
  path; new config groups default to safe values.
- **Fallback:** safe defaults.
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-9 Offline, deterministic testing

- **Source requirements:** NFR-OFF-001.
- **Enforcer:** `test/conftest.py` (offline fixtures, marker registration),
  `@pytest.mark.integration` opt-in convention.
- **Positive verification:** strict offline run
  (`pytest -q -p no:cacheprovider -m "not integration"` with sockets disabled).
- **Negative verification:** live/vendor tests are integration-marked; default run
  makes no network call.
- **Fallback:** network disabled in the strict run raises `OSError`.
- **Enforcement gap / status:** **Enforced (process+test)**; the default full
  suite is not all-green (known cache/network baselines) — recorded, not hidden.

## INV-10 Secret safety

- **Source requirements:** NFR-SEC-001.
- **Enforcer:** `scripts/validate/validate_requirements.py` (`scan_secrets`),
  `.gitignore` (`.env`), process rule (no secret read/print/commit).
- **Positive verification:** validator secret scan over governance artifacts.
- **Negative verification:** `test/offline/test_governance_scaffold.py` proves the
  scanner flags a secret-looking value and allows placeholders.
- **Fallback:** fail the governance gate (reports location only, never the value).
- **Enforcement gap / status:** **Partial** — the scanner is pattern-based and
  only scans a listed artifact set; live credentials stay in memory only and are
  never written into artifacts (observed in the 2026-11-06 run).

## INV-11 English-only governance text

- **Source requirements:** unmapped governance clause, registry extension pending
  (course clause; see AGENTS.md §2). No stable requirement ID is invented for it;
  it is a governance clause not yet in the 22-ID registry.
- **Enforcer:** process (AGENTS.md, prompts); no automated lint.
- **Positive verification:** manual review.
- **Negative verification:** none automated.
- **Fallback:** human review rejects non-English governance text.
- **Enforcement gap / status:** **Unverified (process only)** — no automated
  detector; recorded rather than claimed enforced.

## INV-12 No unapproved persistence of user changes

- **Source requirements:** unmapped governance clause, registry extension pending
  (AGENTS.md §3/§6/§12); relates indirectly to FR-DQG-006. No stable requirement
  ID is invented for it.
- **Enforcer:** process (prompt, review memo); no runtime code.
- **Positive verification:** 2026-11-06 maintenance preserved all pre-existing
  dirty changes (no revert/reformat of unrelated files).
- **Negative verification:** no commit/push/PR performed without a human request.
- **Fallback:** stop and ask the human.
- **Enforcement gap / status:** **Enforced (process)**. Actual machine-level deny
  of git mutation is NOT implemented (see `docs/code-governance/agent-permissions-proposal.yaml`).

## INV-13 Conflict lifecycle safety

- **Source requirements:** FR-DDT-005, INV-1/3/5, FR-DDT-002.
- **Enforcer:** `src/tradingagents/debate/conflicts.py` (create/observe/resolve/
  escalate; structured assertions only; fail-closed evidence validation),
  `src/tradingagents/debate/evaluator_node.py` (persist), `research_manager.py` (inject),
  `src/tradingagents/debate/claims.py` (ADR-010: a factual conflict on a valid ID whose
  typed exact claim did not validate is not created / drops an open one).
- **Positive verification:** `test/offline/test_debate_conflicts.py`,
  `test/offline/test_debate_turn.py`, `test/offline/test_debate_graph.py`,
  `test/offline/test_exact_claim_runtime.py::TestConflictLifecycle`.
- **Negative verification:** unknown/low/future ID never creates a conflict and
  drops an open one; a no-op resolve of a non-open conflict records no second
  reason; no assertion → no conflict; a wrong-date/value/unit exact claim on a
  valid ID cannot create or keep a factual conflict.
- **Fallback:** conflict dropped / no-op (fail closed).
- **Enforcement gap / status:** **Enforced (code, offline)**. ADR-010 (2026-11-11)
  additionally excludes a valid-but-misused exact-claim citation from factual
  conflict support; action/interpretive conflicts are unaffected.

## INV-14 Context assembly determinism and provenance (PROPOSED — not implemented)

- **Source requirements:** governance context design (see ADR-004, PROPOSED).
- **Enforcer:** none yet — PROPOSED design in `architecture-blueprint.md` and
  `docs/architecture/adr/004-governance-context-design.proposed.md`.
- **Positive verification:** none executable today.
- **Negative verification:** none executable today.
- **Fallback (proposed):** stop before generation when the assembled context or
  the human approval cannot be proven fresh.
- **Enforcement gap / status:** **Unverified / not implemented** — no runtime
  context-assembly or compaction code exists in this repository.


## WebUI extension

# TradingAgents WebUI Invariants

Status: **Approved for documentation by the human owner on 2026-11-05.** These invariants extend the baseline safety boundaries to the web presentation layer. The violation tests are planned; **none has been executed**. A planned test is not passing evidence.

## INV-WEB-001 — Core and CLI behaviour is unchanged

Statement: Adding the WebUI must not change the observable behaviour, arguments, defaults, output, exit codes, imports, or public contracts of `src/tradingagents/` or `src/cli/`.

Enforcement: `src/tradingagents_web/` is a sibling package. `tradingagents` and `cli` never import it. `test/offline/test_web_contracts.py` compares the exposed surface; the existing regression suite runs unchanged.

Violation test: `test/offline/test_web_contracts.py::test_core_and_cli_surface_unchanged` (planned).

Fallback: Revert the web change; do not modify the core or CLI to accommodate presentation needs.

## INV-WEB-002 — Model output is advisory, never execution authority

Statement: No web control, event, report, or model response may place an order, change a position, or be treated as an instruction to execute a trade. The final rating remains an analysis output.

Enforcement: No execution route exists in `api/`; no brokerage dependency; ratings are rendered only.

Violation test: `test/offline/test_web_security.py::test_no_execution_endpoint_exists` (planned).

Fallback: Remove the offending endpoint or control; keep the rating advisory.

## INV-WEB-003 — Secrets remain server-side

Statement: Provider keys, tokens, authorization headers, cookies, and credential-like values must never appear in browser responses, events, logs, reports, downloads, errors, or snapshots.

Enforcement: `api/config.py` returns key status only; `models/responses.py` uses explicit fields; `errors.py` redacts; `security.py` scans serialized payloads.

Violation test: `test/offline/test_web_security.py::test_secrets_never_serialized` (planned).

Fallback: Remove the leaking field, rotate the credential if exposed, and add a regression test.

## INV-WEB-004 — No server filesystem path reaches the browser

Statement: Browser-visible payloads contain artifact identifiers, never absolute or repository-relative filesystem paths.

Enforcement: `artifacts/index.py` returns hash ids; `artifacts/downloads.py` resolves ids server-side; response models omit path fields.

Violation test: `test/offline/test_web_security.py::test_responses_contain_no_filesystem_paths` (planned).

Fallback: Replace the path with an identifier and re-run the security tests.

## INV-WEB-005 — Path and identifier validation remains deterministic

Statement: Every ticker, run identifier, artifact identifier, and path component derived from user input is validated by the existing deterministic rules before filesystem use. User input never grants file-access authority.

Enforcement: `api/runs.py` uses `safe_ticker_component`; `artifacts/index.py` uses a root allowlist; unknown artifact ids are rejected.

Violation test: `test/offline/test_web_security.py::test_path_traversal_is_rejected` (planned).

Fallback: Reject the request; do not fall back to a broader path.

## INV-WEB-006 — Portfolio states remain distinct

Statement: An omitted portfolio, an explicitly empty book, and a populated book remain three different inputs across the web layer, the graph, checkpoint signatures, and stored artifacts.

Enforcement: `models/requests.py` distinguishes `null` from `{"positions": []}`; `api/runs.py` uses `PortfolioContext.model_validate`; the coordinator passes the object to the graph.

Violation test: `test/offline/test_web_portfolio.py::test_three_portfolio_states_remain_distinct` (planned).

Fallback: Reject the request rather than coercing an absent portfolio to flat.

## INV-WEB-007 — REVIEW is not Hold and not a position

Statement: When the final decision has no recognizable rating, the web layer displays and records `REVIEW`. It must not substitute `Hold`, a tradeable signal, or a fabricated rating.

Enforcement: `runtime/coordinator.py` calls `process_signal`; `is_review` drives the banner; no alternate parser exists.

Violation test: `test/offline/test_web_contracts.py::test_review_is_not_hold` (planned).

Fallback: Show the review warning and retain the raw decision text.

## INV-WEB-008 — Backtest and live artifacts stay isolated

Statement: A backtest uses its own run directory and memory log; it never reads or writes the live decision log, and live analysis never reads backtest artifacts as past context.

Enforcement: `runtime/backtest_runner.py` calls `run_backtest` with its isolated config; the artifact index treats backtest roots separately.

Violation test: `test/offline/test_web_backtest.py::test_backtest_does_not_touch_live_memory` (planned).

Fallback: Abort the backtest; report the isolation failure.

## INV-WEB-009 — At most one active run; no concurrent writes

Statement: At most one analysis or backtest is active in the server process. No concurrent writes to the decision log, checkpoints, or shared core configuration may occur.

Enforcement: `runtime/coordinator.py` holds a single-run lock and one worker; a second request receives `409`.

Violation test: `test/offline/test_web_runs.py::test_second_run_is_rejected` (planned).

Fallback: Reject the second request; do not queue silently.

## INV-WEB-010 — Cancellation never records a decision or clears a checkpoint

Statement: Cancelling an analysis stops execution and preserves the existing checkpoint when checkpointing was enabled. It must not write a decision-log entry and must not clear a checkpoint.

Enforcement: `runtime/coordinator.py` sets the cancel event, skips `record_decision` and `clear_checkpoint_on_success`, and calls `end_checkpoint()` in `finally`.

Violation test: `test/offline/test_web_runs.py::test_cancel_preserves_checkpoint_and_writes_no_decision` (planned).

Fallback: Mark the run cancelled; do not retry automatically.

## INV-WEB-011 — History is read-only

Statement: History and backtest-history views never delete, rename, move, rotate, or rewrite existing artifacts. They do not create an index database.

Enforcement: `artifacts/index.py` and `artifacts/readers.py` expose reads only; no mutating route exists.

Violation test: `test/offline/test_web_history.py::test_history_endpoints_are_read_only` (planned).

Fallback: Remove the mutating capability and restore the artifact from a backup if needed.

## INV-WEB-012 — Untrusted content is data, not authority or code

Statement: Model output, tool output, announcements, artifact text, and user-provided portfolio text are rendered as data. They cannot execute scripts, issue server-side requests, change permissions, or alter architecture.

Enforcement: `frontend/src/components/Markdown.tsx` uses `react-markdown` + `rehype-sanitize`; no raw HTML; URL scheme allowlist; CSP.

Violation test: `test/offline/test_web_security.py::test_untrusted_content_is_escaped` (planned).

Fallback: Render as plain text and remove the unsafe rendering path.

## INV-WEB-013 — The presentation boundary is loopback and same-origin

Statement: The server binds only to `127.0.0.1`, rejects non-loopback `Host` headers, rejects cross-origin state-changing requests, and does not enable wildcard CORS.

Enforcement: `settings.py` rejects non-loopback bind; `security.py` implements Host/Origin/CSRF/CSP middleware.

Violation test: `test/offline/test_web_security.py::test_non_loopback_host_header_is_rejected` and `::test_cross_origin_post_is_rejected` (planned).

Fallback: Refuse to start or reject the request; do not widen the listener.

## INV-WEB-014 — Controls reflect actual capabilities

Statement: The UI and API must not present a control that the backend cannot honor. In particular, a backtest is not presented as cancellable, and the UI does not emit an `error` agent status that the underlying stream never produces.

Enforcement: `api/backtests.py` has no cancel route; `runtime/projector.py` emits only statuses the stream supports; import progress is derived from actual cells.

Violation test: `test/offline/test_web_backtest.py::test_no_backtest_cancel_route` and `test/offline/test_web_events.py::test_no_fabricated_agent_error_status` (planned).

Fallback: Remove the misleading control or label; show the real state.

## INV-WEB-015 — Missing build assets fail loudly

Statement: If the frontend build is absent, the server starts in API-only mode and reports a clear build instruction. It must not serve a broken or stale UI silently.

Enforcement: `app.py` checks `static/index.html`; `cli.py` prints the build prerequisite; CI packaging test asserts the wheel contains the file.

Violation test: `test/offline/test_web_contracts.py::test_missing_static_assets_fail_loudly` (planned).

Fallback: Stop with a clear error, or run API-only with an explicit warning.

## Verification status

Iterations 1, 2, and 3 are implemented; Iteration 1 received a human implementation review **APPROVE** on 2026-11-06. The WebUI backend suite executes **147 passed**, frontend Vitest **25 passed**, Chromium Playwright E2E **6 passed**, and the full regression is **1131 passed, 4 historical failures, 2 skipped, 88 subtests passed**. This covers the backend/security/path/history/run-control/backtest/announcement invariants exercised by the suite. Firefox/WebKit were excluded by user instruction, and the real GraphRunner/live model path remains unrun. Requirements statuses remain `draft`; the approval is for Iteration-1 implementation, not a separate requirements-verification verdict. The execution record is in `docs/architecture/evaluation-logbook.md`.

## Simulated trading subsystem invariants (TRD)

### INV-TRD-001 — No execution without an APPROVED evaluation

- **Source requirements:** FR-TRD-001, INV-TRD-001.
- **Enforcer:** `src/safety/engine.py` (`execute()` requires `APPROVED`), `src/trading/pipeline.py`.
- **Verification:** `test/offline/trading/test_invariants.py`, `test/offline/trading/test_negative.py`, `test/offline/trading/test_executor.py`.
- **Fallback:** reject before executor; no portfolio mutation.

### INV-TRD-002 — Rule engine is the only executor entry point

- **Source requirements:** FR-TRD-001, INV-TRD-002.
- **Enforcer:** `src/safety/engine.py` issues a module-private provenance token; `src/trading/executor.py` verifies it.
- **Verification:** `test/offline/trading/test_structure.py` (AST import boundary), `test/offline/trading/test_invariants.py`, `test/offline/trading/test_executor.py`, `test/offline/trading/test_negative.py`.
- **Fallback:** `ExecutionNotAuthorizedError` before any fill.

### INV-TRD-003 — Audit log is append-only

- **Source requirements:** FR-TRD-004, INV-TRD-003.
- **Enforcer:** `src/trading/audit.py` (hash chain + `.head` truncation anchor).
- **Verification:** `test/offline/trading/test_audit.py`, `test/offline/trading/test_invariants.py`, `test/offline/trading/test_negative.py`.
- **Fallback:** `AuditIntegrityError`; modification, truncation, and deletion are detected.

---

## Token-observability invariants (INV-15 … INV-27) — personal delivery, renumbered

These invariants are the personal token-observability delivery's register, renumbered so
that the two branches' `INV-1…INV-14` no longer collide. The personal register's `INV-6`
was semantically the same point-in-time invariant as Release `INV-3` and is merged there
(see the D2 integration note above); the other thirteen keep their own identity and are
now `INV-15…INV-27`.

They are stated at the level a test can decide, with positive and negative evidence. Code
`file.py:line` citations from the pre-merge register were removed because the merge shifted
them; the enforcing symbols are named instead. Status values were re-checked against the
merged code and the named test modules, not assumed from the Feature branch.

| Personal ID | Final ID | Status |
| --- | --- | --- |
| personal INV-1 | INV-15 | ENFORCED |
| personal INV-2 | INV-16 | ENFORCED |
| personal INV-3 | INV-17 | PARTIAL (harness-enforced) |
| personal INV-4 | INV-18 | PARTIAL (known paths) |
| personal INV-5 | INV-19 | PARTIAL (known exits) |
| personal INV-6 | — | merged into INV-3 |
| personal INV-7 | INV-20 | ENFORCED (harness only) |
| personal INV-8 | INV-21 | ENFORCED |
| personal INV-9 | INV-22 | ENFORCED |
| personal INV-10 | INV-23 | ENFORCED |
| personal INV-11 | INV-24 | ENFORCED (config) |
| personal INV-12 | INV-25 | ENFORCED (new runs) |
| personal INV-13 | INV-26 | ENFORCED |
| personal INV-14 | INV-27 | ENFORCED |

## INV-15 — Missing provider usage is UNKNOWN, never zero

*Historical ID: personal `INV-1` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** A provider call that did not report a usage field is recorded with that
field `null`, and the run's totals do not add zero for it. An omitted field is counted
in `calls_missing_input_tokens` / `calls_missing_output_tokens`; it is not converted
into a measured zero. `usage_coverage.complete` is true only when every call reported
usage **and** both token fields were present.

**Source requirement.** FR-OBS-002 (U-1 verdict), FR-OBS-001 (measured accounting); ADR-013.

**Enforcer.**
- `tradingagents/observability.py` (`record_llm_call`: missing fields increment
  counters, the sum is not incremented).
- `tradingagents/observability.py` (`_extract_usage` / metadata parsing:
  absent values stay `None`).
- `tradingagents/observability.py` (usage coverage requires both fields).
- `scripts/token_benchmark.py` (`usage_verdict`: `MISSING` / `INCOMPLETE`).

**Positive test.**
`tests/test_observability.py::TestTokenUsage::test_missing_usage_is_unknown_not_zero`
and `::TestPartialUsageIsNotZero::test_omitted_input_tokens_are_counted_not_zeroed`;
`tests/test_c3_final_freeze.py::TestUsageVerdict::test_missing_usage_is_missing_and_totals_are_null_not_zero`.

**Negative test (guard).**
`tests/test_observability.py::TestPartialUsageIsNotZero::test_partial_payload_does_not_count_as_complete_coverage`
and `tests/test_c3_final_freeze.py::TestUsageVerdict::test_usage_counts_that_do_not_add_up_are_a_mismatch`
fail if a partial payload is promoted to complete; the mutation "use `or 0` when summing"
is caught by the missing-field assertion in the first test.

**Status.** ENFORCED.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-16 — Run totals close over agent + system + unattributed

*Historical ID: personal `INV-2` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** For every finished run, `run_totals.llm_calls` equals the sum of the
agent buckets, the system-component buckets, and the unattributed bucket; the same
holds for input and output tokens. No provider call is dropped from the total because
of who made it.

**Source requirement.** FR-ANL-004 AC-02, FR-OBS-001 AC-02; ADR-013.

**Enforcer.**
- `tradingagents/observability.py` (`_build_telemetry_dict`: every LLM/tool
  event is bucketed exactly once; `run_totals` sums all buckets).
- `tradingagents/observability.py` (`attribution_summary`: agent, system,
  unattributed counts and tokens).
- `scripts/token_benchmark.py` (the attribution summary must account for every
  call, otherwise `MISMATCH`).

**Positive test.**
`tests/test_system_attribution.py::TestReflectorAttribution::test_totals_close_across_agents_and_system_components`
and `tests/test_observability.py::TestRunAggregates::test_run_totals_are_sum_of_agents`.

**Negative test (guard).**
`tests/test_system_attribution.py::TestAttributionIntegrityGuards::test_a_tampered_flag_cannot_hide_an_unattributed_event`
and `tests/test_c3_final_freeze.py::TestUsageVerdict::test_unattributed_usage_fails_closed`
fail if an event is excluded from the totals or hidden by a flag.

**Status.** ENFORCED.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-17 — Every provider call is attributed to an agent or a declared system component

*Historical ID: personal `INV-3` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** A provider event carries exactly one attribution: a stable agent id
(`agent`), a declared component id (`system`), or `none`. There is no fourth state. An
`agent` id cannot be used as a system component and vice versa, and an event with no
scope remains `none`. A measured run with a `none` event is `INCOMPLETE` and is not
used as evidence.

**Source requirement.** FR-ANL-004 (all ACs); ADR-013.

**Enforcer.**
- `tradingagents/observability.py` (`AttributionContext`, `agent_scoped`,
  `system_component_scoped`, identity guards).
- `tradingagents/observability.py` (separate `system_components` bucket;
  `unattributed` pseudo-agent).
- `scripts/token_benchmark.py` (an event with `attribution_type="none"`, or a
  schema-1 event with `agent_id="unattributed"`, is `INCOMPLETE`).

**Positive test.**
`tests/test_system_attribution.py::TestReflectorAttribution::test_reflector_call_is_a_system_component_not_an_agent`
and `::test_an_unscoped_call_is_none_and_makes_the_run_incomplete`.

**Negative test (guard).**
`tests/test_system_attribution.py::TestAttributionIntegrityGuards::test_an_agent_id_cannot_be_used_as_a_system_component`
and `::test_a_system_component_id_cannot_be_used_as_an_agent`;
`::TestHarnessAcceptsSystemAttribution::test_an_unattributed_event_still_invalidates_it`.

**Status.** PARTIAL. The product records attribution and exposes the completeness flag;
it does not abort a run on an unattributed call. The measured-run invalidation is
enforced by `scripts/token_benchmark.py`, not by `TradingAgentsGraph`. A production run
that never reads the harness can still proceed with `none` events.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-18 — No provider request carries a dangling tool_call

*Historical ID: personal `INV-4` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** A request sent to a provider must not contain an assistant turn whose
`tool_calls` have no matching `ToolMessage` in the request. This covers the retry after
an invalid schema call, the terminal message sequence returned by a single-pass
analyst, and a mixed schema+data turn.

**Source requirement.** FR-ANL-005 AC-03; ADR-018.

**Enforcer.**
- `tradingagents/agents/utils/structured.py` (`_free_text_retry` drops only a
  trailing assistant turn that carries tool calls, then invokes through `prompt | llm`).
- `tradingagents/agents/utils/structured.py` (`_terminal_messages`: returns
  executed turns paired with their results and ends on a no-tool-call assistant turn).
- `tradingagents/agents/utils/structured.py` (mixed turn: keep only data calls
  on the assistant turn; strip the schema call).
- `tests/test_cand01_single_pass_finalization.py::CompiledGraphLoopTest::test_returned_state_has_no_dangling_tool_call`
  is the executable assertion over a compiled graph.

**Positive test.**
`tests/test_final_remediation.py::TestR12Fallback::test_invalid_stance_retry_has_no_dangling_tool_call`;
`tests/test_final_remediation.py::TestAuditAFollowUps::test_a_mixed_schema_plus_data_turn_leaves_no_dangling_call`;
`tests/test_cand01_single_pass_finalization.py::TerminalMessageRoutingTest::test_schema_after_a_tool_round_keeps_call_and_result_paired`.

**Negative test (mutation/guard).**
`tests/test_final_remediation.py::TestR12Fallback::test_a_complete_tool_pairing_is_not_broken`
guards the over-deletion direction (a legal pairing must survive). The documented
mutation "do not pop the dangling assistant turn" makes
`test_invalid_stance_retry_has_no_dangling_tool_call` fail
(`token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` §5).

**Status.** PARTIAL. The fix and the tests cover the four request-construction points
that exist (retry, terminal sequence, mixed turn, two-call fallback). There is no
global request builder that enforces pairing, so a new provider call path could
reintroduce a dangling call without an existing test failing.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-19 — Tool-call protocol markup never becomes an analyst report

*Historical ID: personal `INV-5` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** `market_report`, `news_report`, and `fundamentals_report` must not be
raw tool-call protocol markup (DeepSeek DSML or equivalent). If a model returns markup,
the report is either recovered analysis text or an explicit
`[REPORT UNAVAILABLE — …]` sentence; it is never the markup and never silently empty
because of markup.

**Source requirement.** FR-ANL-003, FR-ANL-005 AC-03; ADR-018.

**Enforcer.**
- `tradingagents/agents/utils/structured.py` (`looks_like_protocol_markup`,
  `sanitize_analyst_text`: prose-before-marker, parameter recovery, explicit
  unavailable template).
- Applied at the single-pass prose exit
  (`structured.py`), the retry
  (`structured.py`), both `structured_llm is None` exits
  (`structured.py`, `533-537`), and the two-call fallback
  (`structured.py`).

**Positive test.**
`tests/test_final_remediation.py::TestDsmlSanitizer::test_r07_markup_is_recovered_without_markers`,
`::test_r14_markup_becomes_an_explicit_unavailable_report`,
`::test_markup_in_the_single_pass_fallback_never_reaches_the_report`;
`::TestAuditAFollowUps::test_a_non_empty_prose_turn_is_sanitized_too`.

**Negative test (mutation/guard).**
`tests/test_final_remediation.py::TestDsmlSanitizer::test_clean_text_is_untouched` and
`::TestAuditAFollowUps::test_analysis_before_markup_is_kept` guard against over-stripping
(clean text and real prose must survive). The documented mutation "skip
`sanitize_analyst_text`" fails the markup-reaches-report test
(`TEST_RESULTS.md` §5).

**Status.** PARTIAL. Sanitation is applied at the four known report exits, not at a
single output chokepoint. A new analyst return path that bypasses those exits would not
be covered by an existing test.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-20 — Each measured run starts from one immutable memory snapshot and writes only its own copy

*Historical ID: personal `INV-7` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** In the experiment harness, every run begins from a byte-identical copy
of one registered baseline snapshot; the copy lives inside the run's own attempt
directory, differs from the baseline path, and the baseline hash is unchanged after the
run. A missing snapshot, a changed hash, a modified copy, a copy outside the attempt, or
a V3 registration without a memory block is refused before spending. A changed baseline
after the run marks the sample `INVALID` with `memory_snapshot_modified`.

**Source requirement.** FR-ANL-009 (all ACs); ADR-017.

**Enforcer.**
- `scripts/token_benchmark.py+` (`prepare_run_spec`: copy + hash + state).
- `scripts/token_benchmark.py` (`_config_for_spec`: `memory_log_path` is the
  run copy, set before graph construction).
- `scripts/token_benchmark.py+` (`_preflight_gate`) and `4230+`
  (`_guard_spending_path`).
- `scripts/token_benchmark.py`, `2878` (`memory_snapshot_modified` invalidation).
- Memory block hashed into `config_sha256` by `gen_cand01_batch_16run_specs_v3.py`.

**Positive test.**
`tests/test_memory_isolation.py::TestSnapshotAndCopy::test_every_run_gets_its_own_copy_of_the_same_snapshot`,
`::test_a_write_to_one_run_copy_leaves_the_others_untouched`,
`::test_run_order_does_not_change_any_run_initial_state`;
`::TestConfigAndReflector::test_a_pending_entry_in_one_run_copy_does_not_trigger_the_next_runs_reflector`.

**Negative test (guard).**
`tests/test_memory_isolation.py::TestValidationFailsClosed` — changed snapshot, missing
snapshot, modified copy, copy equal to baseline, copy outside the attempt, wrong hash,
missing mode, missing memory block are each refused;
`::TestHarnessRecordsMemory::test_a_modified_baseline_invalidates_the_run`.

**Status.** ENFORCED for the experiment harness. This is not product behaviour: a normal
`propagate()` run still uses one shared `~/.tradingagents/memory/trading_memory.md`.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-21 — Frozen specs, manifests, and tags are immutable and independently verified

*Historical ID: personal `INV-8` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** A frozen batch is reproducible from a commit + annotated tag + freeze
record + per-file manifest + per-run config hashes. The verifier must recompute every
recorded digest from the tree; a tampered manifest, a moved tag, a dirty tree, a
changed spec, or a missing record must fail the verification and block spending.

**Source requirement.** FR-HAR-002 (all ACs); ADR-017 (memory hash participates in the
freeze).

**Enforcer.**
- `scripts/c3_verify_final_freeze.py` (HEAD/tree/clean-tree/fingerprint/manifest/
  16 config hashes/protocol/generator/budget/path/tag checks).
- `scripts/c3_finalize_freeze.py` (writes the record from the tree).
- `scripts/c3_verify_protocol_freeze.py`, `scripts/c3_preflight_gate.py`,
  `scripts/c3_build_manifest.py`.
- `scripts/token_benchmark.py::verify_frozen_tree` and `verify_import_root`.

**Positive test.**
`tests/test_c3_final_freeze.py::TestFreezeDesignation::test_the_final_freeze_is_generated_from_the_tree_not_typed`,
`::test_the_verifier_recomputes_every_recorded_digest`,
`::TestManifestCoverage::test_the_manifest_covers_every_batch_file_that_ships`;
`tests/test_c3_regressions.py::test_a_sealed_release_is_not_resealed_by_accident`.

**Negative test (guard).**
`tests/test_c3_final_freeze.py::TestFreezeDesignation::test_a_tree_without_a_record_is_not_a_freeze`
and `::test_the_verifier_requires_head_to_equal_the_record`;
`tests/test_c3_final_freeze.py::TestEffectiveConfig::test_a_tampered_hash_is_refused`,
`::test_editing_a_registration_moves_the_fingerprint`,
`::test_deleting_a_frozen_field_is_refused`.

**Status.** ENFORCED. The verifier is executable and the freeze tests fail on tampering.
The residual is operational: the final tag is local (only the branch was pushed; the tags were not), and the verifier's
"clean tree" check means an uncommitted documentation edit can fail a freeze check even
when the code is correct.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-22 — Single-pass is off by default and requires structured output

*Historical ID: personal `INV-9` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** `single_pass_finalization_enabled` defaults to `False`. Enabling it
without `structured_analyst_output_enabled` has no effect: the analyst uses the RC1
two-call path. The shipped configuration is therefore the RC1 behaviour.

**Source requirement.** FR-ANL-005; ADR-014.

**Enforcer.**
- `tradingagents/default_config.py` (default `False`).
- `tradingagents/graph/setup.py` (single-pass requires structured).
- `tradingagents/agents/analysts/{market,news,fundamentals}_analyst.py` (the switch is
  read at construction; the default argument is `single_pass=False`).

**Positive test.**
`tests/test_cand01_single_pass_finalization.py::RegressionTest::test_single_pass_is_off_by_default_in_the_shipped_config`,
`::test_analyst_factories_default_to_the_two_call_path`,
`::test_setup_requires_structured_before_enabling_single_pass`.

**Negative test (guard).**
`tests/test_ablation_switches.py::StructuredSwitchTest::test_off_binds_no_schema_for_all_three`
and `tests/test_cand01_single_pass_finalization.py::RegressionTest::test_rc1_two_call_functions_are_unchanged_and_still_exported`
fail if the switch leaks into the shipped path or removes RC1.

**Status.** ENFORCED.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-23 — The batch-macro switch removes the tool from both the analyst and the ToolNode

*Historical ID: personal `INV-10` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** When `batch_macro_enabled` is false, the news analyst does not bind
`get_macro_indicators_batch` and does not advertise it in the prompt, and the news
`ToolNode` does not contain it. The single-series `get_macro_indicators` remains
available. An OFF run cannot execute a batch call even if the model emits one.

**Source requirement.** FR-ANL-006 (all ACs); ADR-015.

**Enforcer.**
- `tradingagents/graph/setup.py` (passes the switch to the analyst).
- `tradingagents/agents/analysts/news_analyst.py` (tool list + prompt hint).
- `tradingagents/graph/trading_graph.py` (ToolNode list follows the same
  config).
- `tradingagents/graph/switch_verification.py` (the spec's switch value is verified
  against the graph).

**Positive test.**
`tests/test_ablation_switches.py::BatchMacroSwitchTest::test_on_binds_batch_tool`,
`::test_off_does_not_bind_batch_tool`,
`::test_off_keeps_every_other_tool`,
`::ConfigPlumbingTest::test_toolnode_honours_batch_switch`;
`tests/test_macro_batch.py::BindingTest::test_single_series_tool_still_bound_as_fallback`.

**Negative test (guard).**
`tests/test_ablation_switches.py::BatchMacroSwitchTest::test_prompt_does_not_advertise_an_unbound_tool`
fails if the prompt names a tool the OFF arm cannot call;
`tests/test_switch_consumption.py` fails if the graph does not consume the spec's value.

**Status.** ENFORCED. This is a configuration invariant, not a code deletion: the batch
tool still exists in the package and can be enabled explicitly.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-24 — The configured news path is Finnhub-only and never contacts GDELT

*Historical ID: personal `INV-11` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** Under the shipped configuration, company news routes only to
`get_news_finnhub_only`, which has no GDELT dependency; global news under the Finnhub
route returns `CONFIG_DISABLED` and fetches nothing. A Finnhub outage, a missing key, or
a global-news request must not cause a GDELT contact. GDELT remains available only by
explicitly changing the vendor configuration.

**Source requirement.** FR-ANL-008 (all ACs); ADR-016.

**Enforcer.**
- `tradingagents/dataflows/interface.py` (route map).
- `tradingagents/dataflows/finnhub_news.py` (`get_news_finnhub_only`,
  `get_global_news_finnhub`/`CONFIG_DISABLED`).
- `tradingagents/default_config.py` (`data_vendors`/`tool_vendors`).

**Positive test.**
`tests/test_finnhub_only_scope.py::test_get_news_never_contacts_gdelt`,
`::test_a_finnhub_outage_is_not_rescued_by_gdelt`,
`::test_global_news_is_explicitly_disabled_not_borrowed`,
`::test_the_disabled_global_path_fetches_nothing` (all use a GDELT tripwire).

**Negative test (guard).**
`tests/test_finnhub_only_scope.py::test_default_config_has_no_gdelt_news_route`
fails if the default is changed to a GDELT route;
`::test_single_provider_header_names_only_that_provider` fails if provenance is
misreported.

**Status.** ENFORCED for the shipped configuration. The GDELT implementation and its
tests still exist; the invariant is about the configured route, not about removing the
source from the repository.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-25 — Tool rounds are counted once per non-empty model tool batch on both execution paths

*Historical ID: personal `INV-12` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** A graph `ToolNode` invocation and a single-pass `run_data_tools` batch
each produce exactly one tool round for the owning agent. An empty batch produces no
round. A batch in which every call failed still produces one round with
`status="error"`. The two paths do not double-count the same batch.

**Source requirement.** FR-OBS-001, FR-ANL-005; ADR-014, ADR-018.

**Enforcer.**
- `tradingagents/graph/setup.py` (graph ToolNode wrapped by
  `attrib_tool_round`).
- `tradingagents/observability.py` (`attrib_tool_round`, `record_tool_round`).
- `tradingagents/agents/utils/structured.py` (`run_data_tools._run`: one round
  per non-empty batch, error status when all calls failed).

**Positive test.**
`tests/test_final_remediation.py::TestToolRounds::test_one_model_turn_with_two_calls_is_one_round`,
`::test_two_rounds_are_two_rounds`,
`::test_a_failing_tool_still_counts_as_a_round`,
`::test_rounds_reach_the_telemetry_payload`;
`tests/test_observability.py::TestAttribToolRound::test_one_invocation_records_one_round`.

**Negative test (guard).**
`tests/test_final_remediation.py::TestToolRounds::test_no_tool_call_is_no_round`
guards against counting an empty batch; the documented mutation "delete the round hook"
fails four `TestToolRounds` tests (`TEST_RESULTS.md` §5).

**Status.** ENFORCED for runs after the fix. Historical V3 telemetry from `e3b5cca` has
`tool_rounds = 0` and is explicitly not rewritten; the invariant applies to new runs.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

**Integrated wrapper order (verified 2026-11-21).** `GraphSetup` composes
`attrib_tool_round(agent_id, EvidenceCapturingToolNode(tool_node))`
(`tradingagents/graph/setup.py`): the attribution wrapper is outermost and records one
round per graph tool-node invocation, while `EvidenceCapturingToolNode` delegates to the
inner `ToolNode` and does not increment tool-round accounting. The single-pass
`run_data_tools` path calls `record_tool_round` once per non-empty batch. The guarantee
covers these execution paths only.

---

## INV-26 — A fallback never presents prose as a typed report

*Historical ID: personal `INV-13` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** When a structured call fails or is unsupported, the report may be
free text, but the parsed report object is `None`. `report_obj` is non-`None` only when
the schema call succeeded and rendered a non-empty report. Downstream code can therefore
branch on the object without mistaking prose for data.

**Source requirement.** FR-ANL-003, FR-ANL-005; ADR-014, ADR-018.

**Enforcer.**
- `tradingagents/agents/utils/structured.py` (`finalize_analyst_report`: every
  fallback branch returns `(text, None)`).
- `tradingagents/agents/utils/structured.py` (`finalize_single_pass`: every
  non-success return sets `None`).
- `tradingagents/agents/analysts/{market,fundamentals}_analyst.py` (state keys receive
  the returned object unchanged).
- `tradingagents/agents/utils/s2_context.py` (`has_s2_fields` requires a real object).

**Positive test.**
`tests/test_cand01_single_pass_finalization.py::BlankReportResidualTest::test_blank_report_is_never_a_typed_object`,
`::SchemaValidationTest::test_schema_call_produces_the_typed_object`;
`tests/test_structured_agents.py`.

**Negative test (guard).**
`tests/test_cand01_single_pass_finalization.py::FallbackTest::test_prose_answer_is_returned_unchanged_as_in_rc1`
and `::test_structured_off_runs_the_plain_loop` fail if a fallback result is wrapped in
the schema type; the residual test also pins that a blank report stays blank and is not
silently typed.

**Status.** ENFORCED.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---

## INV-27 — Telemetry artifacts contain no raw prompt, message, tool-result, news, or memory content

*Historical ID: personal `INV-14` (renumbered by the D2 integration, 2026-11-21).*

**Statement.** A telemetry artifact may contain counts, byte sizes, hashes,
fingerprints, ids, model/provider names, error class names, and sanitized usage blobs.
It must not contain prompt text, message content, tool-result bodies, news article text,
agent output, or memory contents.

**Source requirement.** FR-OBS-001 (event-level observability without content);
ADR-013.

**Enforcer.**
- `tradingagents/observability.py` (event dataclasses store only sizes,
  fingerprints, hashes, ids, error classes).
- `tradingagents/observability.py` (`_build_telemetry_dict` serialises those
  fields only; no body fields exist to serialise).
- `tradingagents/observability.py` (`_sanitize_usage_raw` drops long strings
  and non-numeric values from the preserved usage blob).

**Positive test.**
`tests/test_observability.py::TestPromptDiagnostics::test_no_raw_content_persisted`,
`::TestToolExecution::test_raw_result_not_persisted`,
`::TestTelemetryPersistence::test_privacy_no_raw_content_in_artifact`,
`::test_privacy_excludes_wide_forbidden_content_set`.

**Negative test (guard).**
`tests/test_observability.py::TestTelemetryPersistence::test_privacy_excludes_wide_forbidden_content_set`
scans the artifact for a forbidden-content set (prompt text, tool bodies, state values,
memory text) and fails if any appears; adding a content field to an event would make the
artifact fail the scan.

**Status.** ENFORCED.

**Integrated-tree check (2026-11-21).** The named test modules pass in the merged worktree (see D2/D3 verification report); the status above is carried over unchanged and is not promoted by this renumbering.

---


## Simulated-trading Web entry enforcement — 2026-11-21

web-simulation-20261121-v1 maps the existing INV-TRD-001/002/003 and
INV-WEB-001/003/006/009/012/013/014 to the new Web composition. No invariant or
requirement ID/status is replaced. runtime/simulation.py invokes the existing
pipeline, issued approval gate and engine; no Web module imports the executor.
models/simulation_requests.py forbids arbitrary config, paths, quantity and
execution-authority fields; money is strict Decimal text. Account generation
and portfolio version jointly prevent reset ABA/stale requests. Pending human
approvals are process-owned, bound to issued evaluations, expiry and quote
freshness; persisted JSON cannot recreate execution authority. Account/audit
uncertainty blocks mutation and remains inspectable through the verified audit
read path. Fixed-root path checks, process ownership and the coordinator serial
lease protect state ownership. Each walk-forward run has separate core state,
audit, memory and cursor. No automatic human approval, fake cancellation or
real broker capability is exposed. Violation checks are in
`test/offline/test_web_simulation.py`, the unchanged trading suite, frontend
`tests/simulation.test.tsx` and local Chromium `e2e/simulation.spec.ts`.
Execution evidence will be recorded only after the requested final test phase.


## Backtest observation enforcement — 2026-11-21

web-backtest-progress-20261121-v1 maps REQ-WEB-011/026 and INV-WEB-003/009/014
without introducing new IDs. Optional core observation carries only event kind,
requested ticker/date and cannot alter a result or trigger a retry. Context reset
isolates subscribers; observer exceptions do not abort serial execution. Web
progress transitions require requested identities and valid prior states;
terminal outcomes are counted once. Record locking makes counters/current cell
and paginated rows consistent. Progress snapshots contain no raw exceptions,
keys or paths. Process records outrank disk log inference while running.

A processed-cell fraction includes failed/skipped cells and is not task success
or a time estimate. Settlement/summarization still owns the active slot. Missing
historical progress stays absent, and browser refresh is process-lifetime
reattachment only. The core/public signature, CLI, scoring, memory boundaries,
models, budgets and absence of cancellation remain unchanged. Verification is
linked in the trace matrix and results in the evaluation logbook.
