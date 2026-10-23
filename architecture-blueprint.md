# Architecture Blueprint — Master Constraint / Design Document

This is the master design document for the CS5351 course project. It states the
hard constraints, the module layout, the two feature implementations, and the
non-functional contract that governs every change. It is authoritative for
design intent; the machine-readable PRD lives in `docs/req/requirements.yaml`,
and traceability lives in `docs/architecture/trace-matrix.md`.

## Repository context

- This is a downstream fork of the upstream `TradingAgents` framework (v0.5.0).
- Canonical source trees are `tradingagents/` and `cli/`. Tests live in `tests/`.
  There is **no** `src/` and **no** `test/` tree; the README pointers under
  `src/` and `test/` map the authoritative slide layout onto the real trees.
- The upstream product guide is preserved in `README.md`; the CS5351 overlay is
  a clearly separated appended section.

## Hard constraints (authoritative)

1. **Determinism.** The evidence gate and the debate evaluator must be pure and
   LLM-free. Identical inputs must yield identical outputs regardless of
   insertion order, clock, or environment. The only injected time value is the
   ISO-8601 `decided_at`, which is validated; when absent a deterministic UTC
   `YYYY-MM-DDTHH:MM:SSZ` string is used.
2. **Fail closed.** An internal error or missing evidence must never look like a
   clean `normal` run. The gate converts any exception into a `blocked` decision
   and the evaluator routes to `summarize`/`insufficient_evidence`.
3. **Point-in-time integrity.** Every dated data path must be evaluated "as of"
   the requested trade date. No future data (look-ahead) may reach a decision.
   This predates the gate work and is a preserved upstream invariant.
4. **Auditability.** Every gate verdict and debate decision carries a stable
   reason code set, a policy version, critical evidence IDs, and a human-readable
   reason; the debate evaluator emits an explicit decision trace.
5. **Budget safety.** Debate termination must reserve budget for the summary so a
   run never exhausts tokens/time/calls mid-debate and fails to produce a report.
6. **Backward compatibility.** New config groups must default to safe values and
   preserve the legacy fixed-round routing when `debate_termination.enabled` is
   `False` or when the gate decides `normal`/`degraded`.
7. **Offline testability.** No unit test may require network or a paid LLM. All
   live/vendor paths are `@pytest.mark.integration` and opt-in.
8. **Secret safety.** No API key, token, or `Bearer`/`sk-` string may appear in
   committed files.

## Phase 1–3B + Phase 4A scope (implemented)

- **Phase 1 (analysis):** read-only repository analysis; requirements frozen.
- **Phase 2 (contract):** evidence model + deterministic gate core (models,
  adapter, validate, policy, quality, gate); decimal-math cleanup.
- **Phase 3A (gate graph integration):** `data_quality_gate` node + router and
  the structured gate-aware `AgentState` fields.
- **Phase 3B (dynamic debate termination):** `debate` package (config, models,
  turn, budget, evidence_manifest, state, evaluator, evaluator_node) plus the
  researchers' verdict gate and the research-manager hold contract.

### Evidence package (`tradingagents/evidence/`)

| Module | Responsibility |
| --- | --- |
| `models.py` | Typed, deterministic, JSON-safe dataclasses (`EvidenceRecord`, `SourceAttempt`, `ValidationResult`, `EvidenceGroupQuality`, `GateDecision`) plus enums and the `quantize_decimal` helper. |
| `adapter.py` | Truthful `StructuredSnapshot` → `EvidenceRecord` adaption and stable evidence-ID generation. |
| `validate.py` | Five deterministic validation classes (completeness, format, freshness, look-ahead, cross-source consistency). |
| `policy.py` | Deterministic `Decimal`-threshold policy objects (`MarketPolicy`, `MarketRecordPolicy`, `MetricTolerance`). |
| `quality.py` | Per-record precedence and per-category aggregation. |
| `gate.py` | `GateDecision` generation with injected `decided_at`; precedence `blocked` > `degraded` > `normal`. |

### Debate package (`tradingagents/debate/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | Validated `debate_termination` config group; `enabled=False` reproduces fixed-round baseline. |
| `models.py` | `DebateTurn`, `ConflictRecord`, `StanceSnapshot`, `RoundMetrics`, `BudgetState`, `RoutingDecision`, etc. |
| `evidence_manifest.py` | Valid-new-evidence rules against the gate manifest (citation allowlist). |
| `budget.py` | Deterministic usage estimation / accounting. |
| `turn.py` | Structured `DEBATE_METADATA` parsing with a best-effort prose fallback; parse failure never extends the debate. |
| `state.py` | Debate-state mutation helpers (researcher side). |
| `evaluator.py` | Pure `evaluate_round` decision rules (authoritative ordering in its module docstring). |
| `evaluator_node.py` | LangGraph Debate Evaluator node factory reading gate manifest / turn state off `AgentState`. |

### Graph integration

- `tradingagents/graph/data_quality_gate.py` — dependency-injectable gate node.
- `tradingagents/graph/conditional_logic.py` — routers including
  `should_continue_after_data_gate`.
- `tradingagents/graph/setup.py` — registers the gate node and evaluator node;
  complete `DEBATE_PATH_MAP` / `DEBATE_EVALUATOR_PATH_MAP` to avoid router
  fall-through crashes.
- `tradingagents/agents/researchers/{bull,bear}_researcher.py`,
  `tradingagents/agents/managers/research_manager.py`,
  `tradingagents/agents/utils/agent_states.py` — verdict gate, citation
  allowlist enforcement, hold contract, and gate-aware state fields.

## Non-functional requirements (NFR) — summary

Referenced by ID; full list in `docs/req/requirements.yaml`:

- `NFR-DET-001` determinism, `NFR-FC-001` fail-closed, `NFR-PIT-001`
  point-in-time integrity, `NFR-AUD-001` auditability, `NFR-BUD-001` budget
  safety, `NFR-BC-001` backward compatibility, `NFR-OFF-001` offline
  testability, `NFR-SEC-001` secret safety.

## Phase 4A (implemented, approved with limitations)

- **Phase 4A — deterministic offline baseline comparison (NFR-CMP-*):** a pure,
  LLM-free, network-free comparison model/runner (`tradingagents/comparison/`)
  that contrasts the legacy fixed-round debate-termination baseline with the
  dynamic policy over identical scripted case identity and turn sequences
  (`scripts/run_phase4a_comparison.py`). Completed and human-approved with
  limitations (WANG Yiwen 60536848, 2026-10-23): results are deterministic
  offline scripted fixtures, not live-provider measurements; the full offline
  suite is not completely green (three known date-sensitive cache failures
  remain); human traceability scores remain `pending`; no production thresholds
  were tuned.

## Out of scope

- **Phase 4B** (live-provider benchmarking) is not started and is not designed
  here; it remains prohibited without separate explicit human authorization.
- **Production threshold tuning** is not in scope and remains prohibited without
  separate explicit human authorization.
- No new data vendors, no new LLM providers, no UI/feature work beyond the two
  requested improvements and the approved Phase 4A offline comparison.
- No relocation or duplication of source trees.

## Open / uncertain items

Marked `TODO` in `docs/debt-register.md` and `docs/architecture/risk-list.md`.
The student identity is **confirmed** as WANG Yiwen (CS5351 ID 60536848);
the identity risk is resolved (RISK-004 / DEBT-005). The only remaining
uncertainty is the OpenCode `permissions.jsonc` schema against the installed
OpenCode version (RISK-006 / DEBT-004); both are recorded rather than invented.