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

## Authority boundaries (advice vs. authority)

The system produces **advice**; it never has **authority** to trade, commit, or
change governance on its own.

| Actor | Authority | Boundary |
| --- | --- | --- |
| Human (WANG Yiwen, 60536848) | Ultimate: scope, safety, git, network, approvals | Owns `.opencode/rules.md` (human-only) and every phase/review decision |
| Coding agent (OpenCode/Codex) | Read/analyze/implement within the active authorized scope | May suggest; must stop and ask on any denied action |
| Runtime graph (gate/evaluator/agents) | Emits a verdict/recommendation within deterministic rules | Cannot override a blocked verdict downstream (FR-DQG-006) |

Advice is never promoted to authority by an AI: human decisions cannot be
inferred, authored, or backfilled by an agent (see `Prompt.md`, ADR-004).

## End-to-end workflow and change controls

1. **Read instructions first** (`AGENTS.md`, this blueprint, `invariants.md`,
   `trace-matrix.md`, `pyproject.toml`, `tests/conftest.py`).
2. **Plan first** — output a traceable execution plan (scope, interfaces, tests,
   steps, risks) and **STOP for human approval** before any feature code/test edit
   (`prompts/prompt_v1.3.yaml`).
3. **Implement** only the approved, in-scope requirement.
4. **Verify** with the offline deterministic suite + validator + Ruff +
   `git diff --check`; record exact outcomes.
5. **Record** AI use (`docs/ai-use-log.yaml`) and human review
   (`docs/review-memo.md`); update the trace matrix in the same change.
6. **Human review at every phase boundary**; a phase without a recorded human
   decision is not complete.

Safety-critical changes (gate/evaluator/output-guard/fail-closed/budget
semantics, permission boundaries, prompts) require an **ADR + explicit human
approval** before merge (see `docs/code-governance/structural-constraints.md`).
Scope, safety, or plan changes trigger **reapproval**.

## Permissions and observability

- **Permissions:** a role-by-path, deny-by-default whitelist is specified in
  `docs/architecture/permission-model.md` (Human/Planner/Builder/Verifier) and a
  machine-readable **proposal** (not active) ships in
  `docs/code-governance/agent-permissions-proposal.yaml`. The **existing shipped**
  `.opencode/permissions.jsonc` is unchanged this turn, but its existence is not
  proof it is loaded/enforced: **loading/enforcement is unverified** (RISK-006 /
  DEBT-004). JSON-parses ≠ config-enforced.
- **Observability:** the runtime emits a gate summary (`0_quality/gate_summary.md`),
  evidence manifest (`0_quality/evidence_manifest.json`), debate trace
  (`2_research/debate_trace.json`), and run summary (`run_summary.json`), plus a
  decision trace in `AgentState`. A per-requirement runtime/audit-monitor mapping
  (real hooks vs. planned) is recorded in the trace matrix.

## Governance context design (PROPOSED — not implemented)

A layered, deterministic context-assembly design — immutable safety layer,
human-governance layer, stable ADR/invariant layer, task-plan layer, working
evidence layer, history layer — with a 131072-token school-context design budget,
proposed compaction thresholds, keep/drop rules, a provenance-preserving summary
schema, and critical-constraint re-injection after compaction/restart is
specified in `docs/architecture/adr/004-governance-context-design.proposed.md`.
It is **PROPOSED only**: no runtime assembly/compaction code exists, none is
enforced, and INV-14 is marked unverified. The existing `max_tokens` /
`reserved_summary_tokens` govern model *output*, not the context window.

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
The student identity is **confirmed** as WANG Yiwen (CS5351 ID 60536848); the
identity risk is resolved (RISK-004 / DEBT-005). Remaining open items include:
the OpenCode `permissions.jsonc` schema/enforcement against the installed
OpenCode version (RISK-006 / DEBT-004); the degraded confidence ceiling
(DEBT-014); automatic optional adapters (DEBT-015 / RISK-015); and the live-run
budget-accounting basis and claim-date semantics found on 2026-11-06 (DEBT-021 /
DEBT-022 / RISK-020 / RISK-021). This is **not** claimed to be the "only
remaining uncertainty"; the earlier single-item framing was stale and is
corrected here.