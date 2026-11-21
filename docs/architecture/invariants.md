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
