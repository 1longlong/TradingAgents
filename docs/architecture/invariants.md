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
- **Enforcer:** `tradingagents/evidence/gate.py` (exception → `blocked`),
  `tradingagents/graph/data_quality_gate.py` (`data_quality_error` → blocked),
  `tradingagents/debate/evaluator.py` (error → `summarize`/`insufficient_evidence`),
  `tradingagents/agents/utils/output_guard.py` (`is_blocked_run` fail-closed),
  `tradingagents/graph/signal_processing.py` (blocked → Hold).
- **Positive verification:** `tests/test_data_quality_gate_graph.py`,
  `tests/test_market_evidence_gate.py`, `tests/test_debate_evaluator.py`,
  `tests/test_output_guard.py` (missing/malformed gate state → Hold).
- **Negative verification:** `tests/test_output_guard.py` asserts a mutated
  missing/malformed gate cannot yield Buy; `tests/test_market_evidence_gate.py`
  asserts a raised exception becomes `blocked`, not `normal`.
- **Fallback:** verdict is `blocked`; router routes to Research Manager; output
  pinned to Hold; final signal Hold.
- **Enforcement gap / status:** **Enforced (code, offline)** on the covered path (blocked path proven offline; the 2026-11-06 live run was degraded, not blocked). 2026-11-10 D2 adds a narrow **controlled-fixture** blocked-path live proof (real gate + real downstream nodes; zero Bull/Bear invokes; Hold throughout) — not exhaustive/live-vendor. Degraded
  confidence ceiling (DEBT-014) is a separate OPEN item, not a fail-closed gap.

## INV-2 Determinism of the gate and evaluator

- **Source requirements:** NFR-DET-001, FR-DQG-001, FR-DDT-001.
- **Enforcer:** `tradingagents/evidence/{quality,gate,multi_category_gate}.py`,
  `tradingagents/debate/{evaluator,conflicts}.py` (pure, no clock/RNG/network).
- **Positive verification:** `tests/test_evidence_models.py`,
  `tests/test_debate_evaluator.py`, `tests/test_debate_conflicts.py`
  (repeat/shuffled-order equality).
- **Negative verification:** shuffled-evidence ordering tests assert identical
  output; no test observes a clock/RNG dependency.
- **Fallback:** only injected validated ISO-8601 `decided_at`; absent → fixed UTC string.
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-3 Point-in-time integrity (no look-ahead)

- **Source requirements:** NFR-PIT-001, FR-DDT-005, NFR-CMP-001.
- **Enforcer:** `tradingagents/evidence/validate.py` (look-ahead class),
  `tradingagents/dataflows/market_data_validator.py` (`as_of` boundary),
  `tradingagents/debate/conflicts.py` (future ID never creates/keeps a conflict).
- **Positive verification:** `tests/test_fundamentals_lookahead.py`,
  `tests/test_news_lookahead.py`, `tests/test_social_lookahead.py`,
  `tests/test_memory_pointintime.py`.
- **Negative verification:** conflict tests assert a future-dated ID drops an
  open conflict; look-ahead tests assert future rows are rejected.
- **Fallback:** record rejected / conflict dropped (fail closed).
- **Enforcement gap / status:** **Partial** — the PIT tests are date-sensitive
  (RISK-001); a live Bull claim mislabelled a Nov-4 close as Nov-5 despite citing
  the valid close ID (RISK-020): an allowlist verifies record eligibility, not the
  semantic truth of every claim's date.

## INV-4 Acyclic, JSON-safe serialization

- **Source requirements:** FR-DQG-001, FR-DQG-003, FR-DQG-005, NFR-AUD-001.
- **Enforcer:** `tradingagents/evidence/models.py` (fixed 20-field
  `EvidenceRecord`; separate 7-field `SourceAttempt`; `ValidationResult` refs by
  `evidence_id`), `tradingagents/report_artifacts.py` (`to_dict` forms only).
- **Positive verification:** `tests/test_evidence_models.py`,
  `tests/test_evidence_step2_regressions.py`, `tests/test_report_artifacts_audit.py`.
- **Negative verification:** round-trip JSON tests assert no cycles / no frozen
  dataclass written into `AgentState`.
- **Fallback:** serialization error is a fail-closed gate error.
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-5 Stable, deterministic identifiers

- **Source requirements:** FR-DQG-003, FR-DDT-005.
- **Enforcer:** `tradingagents/evidence/adapter.py` (`run_id` from
  `(trade_date, normalized symbol)`), `tradingagents/debate/conflicts.py`
  (conflict ID from normalized topic/kind).
- **Positive verification:** `tests/test_evidence_models.py`,
  `tests/test_debate_conflicts.py`.
- **Negative verification:** ID tests assert no random component; same input →
  same ID.
- **Fallback:** none needed (pure derivation).
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-6 Auditability of every decision

- **Source requirements:** NFR-AUD-001, FR-DQG-005.
- **Enforcer:** `tradingagents/evidence/models.py` (reason codes, policy
  version, critical evidence IDs), `tradingagents/debate/{models,evaluator}.py`
  (decision trace), `tradingagents/report_artifacts.py` (artifact export).
- **Positive verification:** `tests/test_evidence_models.py`,
  `tests/test_debate_evaluator.py`, `tests/test_report_artifacts_audit.py`.
- **Negative verification:** artifact audit asserts per-evidence validation
  association and identity/provenance are present (never silently dropped).
- **Fallback:** absent state → safe defaults; never invented values.
- **Enforcement gap / status:** **Enforced (code, offline)**. ADR-007 adds deterministic debate participation truth (structured-only; legacy prose = unverified) surfaced in reports, and a sanitized allow-listed failure ledger (`docs`/`tests/test_debate_participation.py`) — never exception text, prompts, bodies or auth. Confirmed by the 2026-11-10 bounded live D2 run: participation explicitly `data_quality_blocked`, zero absent-opponent attribution in the trusted report.

## INV-7 Budget safety

- **Source requirements:** NFR-BUD-001, FR-DDT-003.
- **Enforcer:** `tradingagents/debate/{budget,config}.py`,
  `can_afford_optional_call` (remaining ≥ reserved_summary + next-call estimate),
  `tradingagents/graph/{setup,conditional_logic}.py`.
- **Positive verification:** `tests/test_debate_budget.py`,
  `tests/test_debate_precall_budget.py` (exact token/time boundaries).
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
  (`tests/test_debate_budget.py`, `test_debate_researcher_timing.py`) and
  confirmed by the 2026-11-10 bounded live D1 run (real Bull+Bear, measured
  seconds, provider tokens, `transport_attempts` null; stop `max_rounds_reached`,
  not premature `budget_exhausted`). REMAINING GAP (explicit): cross-resume
  hard-budget accounting is NOT solved (a failed node's usage is not persisted;
  the sanitized failure ledger is the only durable record of an aborted call).
  All-agent production usage totals remain untracked in the product.

## INV-8 Backward compatibility

- **Source requirements:** NFR-BC-001, FR-DDT-004.
- **Enforcer:** `tradingagents/debate/config.py` (`enabled=False` retains legacy
  routing), `tradingagents/graph/setup.py`.
- **Positive verification:** `tests/test_debate_config.py`, `tests/test_debate_graph.py`.
- **Negative verification:** disabled-config tests assert the legacy fixed-round
  path; new config groups default to safe values.
- **Fallback:** safe defaults.
- **Enforcement gap / status:** **Enforced (code, offline)**.

## INV-9 Offline, deterministic testing

- **Source requirements:** NFR-OFF-001.
- **Enforcer:** `tests/conftest.py` (offline fixtures, marker registration),
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
- **Negative verification:** `tests/test_governance_scaffold.py` proves the
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
- **Enforcer:** `tradingagents/debate/conflicts.py` (create/observe/resolve/
  escalate; structured assertions only; fail-closed evidence validation),
  `tradingagents/debate/evaluator_node.py` (persist), `research_manager.py` (inject).
- **Positive verification:** `tests/test_debate_conflicts.py`,
  `tests/test_debate_turn.py`, `tests/test_debate_graph.py`.
- **Negative verification:** unknown/low/future ID never creates a conflict and
  drops an open one; a no-op resolve of a non-open conflict records no second
  reason; no assertion → no conflict.
- **Fallback:** conflict dropped / no-op (fail closed).
- **Enforcement gap / status:** **Enforced (code, offline)**.

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
