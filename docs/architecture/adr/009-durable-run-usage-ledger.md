# ADR-009 — Durable Run-Scoped Usage Ledger and Truthful Whole-Run Aggregation

- **Status:** Proposed (Stage 2 implementation complete in the working tree;
  offline verification run; independent Codex review pending; human acceptance
  NOT claimed). Plan + test cases for the four-item repair were explicitly
  approved by WANG Yiwen (60536848) in the controlling conversation on
  2026-11-11; that approval authorizes the plan and the test cases ONLY and is
  not a final human acceptance. Stage 1 (ADR-008) and this Stage 2 are
  implemented; Stage 3 (exact claim date/value/unit validation) and Stage 4
  (degraded confidence cap 0.60) remain NOT implemented.

  **Offline verification (2026-11-11):** focused `tests/test_durable_usage_ledger.py`
  (28 passed) + `tests/test_whole_run_usage.py` (10 passed) via the strict
  socket-denied harness; full strict-offline suite 1935 passed / 1 skipped /
  1 deselected / 88 subtests / 0 forbidden socket attempts; `ruff check .` clean;
  governance validator PASS (43/43); `git diff --check` clean. This is the
  offline behavioral + regression tier only, NOT live behavior and NOT human
  acceptance.
- **Date:** 2026-11-11
- **Deciders:** CS5351 project (student); coding-agent (OpenCode Builder);
  independent reviewer (Codex); human review required before acceptance
- **Trace:** `FR-DDT-003` (budget-safe termination with summary reserve),
  `NFR-BUD-001` (budget safety), `NFR-AUD-001` (auditability), `FR-DQG-005`
  (report artifacts), `NFR-BC-001` (backward compatibility), `INV-6`/`INV-7`/
  `INV-8`. No new requirement ID is invented: this ADR resolves the durable
  cross-resume accounting gap recorded in DEBT-021 / RISK-020 and the
  all-agent-usage-untracked gap, under the existing IDs.

## Context

Phase 3B accounting has two connected defects exposed by the 2026-11-06 live run
and by the Stage 1 review:

1. **Failed calls are not durable.** When a Bull/Bear `llm.invoke` raises, the
   researcher re-raises, and LangGraph **discards the node's state update**, so
   the usage accrued before the exception (and the invocation that was actually
   attempted) never reaches the checkpoint. On resume the graph replays from the
   last committed node with the *stale* `debate_usage`, so
   a failed-but-billed call is effectively charged **zero** and can be re-tried
   as though it cost nothing. The sanitized failure ledger
   (`debate/failure_audit.py`) is an audit channel only; it explicitly is **not**
   a resume budget mechanism.
2. **Whole-run usage is not aggregated.** `debate_usage` only covers Bull/Bear.
   The analysts (including the structured-output → free-text fallback), the
   Research Manager, the Trader, the three risk analysts and the Portfolio
   Manager all call a model, but no unified, run-scoped total covers them. A
   reader could mistake `run_summary.usage` for a whole-run total when it is only
   the debate subset.

The Stage 2 repair must:

- make spend **durable** across a crash/checkpoint boundary, with an honest
  reservation (attempted/in-flight) so an attempt whose outcome is unknown is
  never silently reset to zero or re-tried as free;
- reconcile the ledger with the checkpoint **idempotently** on resume (never
  double-add the same cumulative totals);
- aggregate **all** model invocations into a run-scoped total, while keeping the
  existing **debate-scoped** limit (`max_calls`/`max_tokens`/`max_time` +
  summary reserve) intact and **never** silently widening it to analysts/risk;
- keep provenance honest: a token/time value is `provider`/`measured` only when
  actually observed; estimates stay `estimated`; an unknown failed/in-flight
  cost is `unavailable` (never `0`, never a fabricated provider count).

## Decision

### A. Dependency-free SQLite ledger

`tradingagents/debate/usage_ledger.py` holds a standard-library-only SQLite
ledger with two tables:

- `reservations(run_id, invocation_id, phase, speaker, reserved_tokens,
  reserved_seconds, state, created_at)` — one row per *attempted* model
  invocation, written **before** the outbound call. `state` transitions
  `in_flight` → `settled` (or `failed`). A reservation whose `state` is still
  `in_flight` at read time is **unresolved possible spend**;
- `usage_events(run_id, invocation_id, phase, speaker, status, input_tokens,
  output_tokens, total_tokens, tokens_source, seconds, seconds_source,
  token_source_partial, provider_conflict, transport_attempts, unresolved,
  created_at)` — one row per *settled* invocation with only allow-listed,
  JSON-safe scalars.

Writing the reservation before the call and the settlement after it means a
crash between them leaves the reservation `in_flight` (durably billed-unknown),
which the pre-call guard treats as unresolved spend (fail closed for further
OPTIONAL calls when the debate budget is enabled). No prompts, responses,
exception text, URLs, auth or query strings are ever written — only the
allow-listed numeric/constant fields above.

The ledger is opened per call with `PRAGMA journal_mode=WAL` and a process
thread lock; each reservation/settlement is a single SQLite transaction so
concurrent invocations (LangGraph runs the same node sequentially, but tools and
tests can interleave) cannot collide or lose an event. A corrupt database, an
unknown `schema_version`, or a run row missing its identity is surfaced as a
`LedgerError` (fail closed), never coerced into an empty ledger.

### B. Separate run identity from reproducible evidence IDs

The ledger keys on a **real execution identity** (`run_id`). A **resume of a run
keeps the SAME identity** as the original execution (read back from the
checkpoint), so the resumed execution retains its own accumulated spend and never
inherits some *other* run's spend. Only a **genuinely fresh execution** mints a
**new** identity: a re-run with the same ticker+date that starts from scratch
(after the prior run finished, or with no resumable checkpoint) is a distinct
execution and begins at zero spend — a fresh run never inherits a prior finished
run's totals. Two fresh executions of the same ticker+date therefore have two
distinct identities; an execution and its resume share one. This identity is
**distinct** from the deterministic gate/evidence `run_id`
(`build_gate_run_id(trade_date, symbol)` in `graph/data_quality_gate.py`) which
must stay reproducible for the evidence manifest.

Within one execution, each **model invocation** gets a **globally unique
`invocation_id`** (a per-capture UUID token + monotonic counter). This means a
resume that makes a **genuinely new provider call** can never collide with — and
be silently hidden behind — an already-settled invocation from a prior process;
that new call is a NEW counted attempt. Only *re-reading/settling the same
invocation* (same `invocation_id`) is idempotent. The execution `run_id` is:

- minted once at a fresh run start and persisted into the **production
  `AgentState`** (`run_id`) and thus into the real SQLite checkpoint;
- reused verbatim on resume (read back from the checkpoint) — the resume is the
  SAME execution and keeps its own spend;
- independent of the ticker/date, so a genuinely fresh re-run with the same
  ticker+date **starts a new identity** and begins at zero spend.

A version + policy hash is written with the run so a checkpoint/ledger pair made
under an incompatible ledger schema/policy is rejected rather than merged.

### C. Reservation vs. actual settlement (no physical-billing claim)

A reservation stores the conservative **next-call estimate**
(`next_call_estimate_*`) as an **estimated reservation** for an *attempted* call
whose outcome is not yet settled. This estimate is **NOT** a physical billing
bound or an upper bound on provider spend (a provider may bill/retry differently);
it is only a conservative estimate recorded so the pending attempt is not treated
as free. A settlement stores the **actual** observed outcome: provider tokens when
else a labelled character estimate, else `unavailable` for an unknown/failed
call. Reservation and actual are kept distinct — the report shows
`reserved` vs `actual` and never claims the estimate is a physical provider
guarantee. Hidden SDK transport retries are **not observed** here, so
`transport_attempts` is `null`/unknown unless a caller observes them; the ledger
records one *logical* invocation.

### D. Reconciliation is idempotent on resume

On resume the graph does **not** add the ledger totals to the checkpointed
cumulative totals (that would double-count). Instead, `debate_usage` (the
checkpoint field the evaluator reads) is **derived from the ledger** for the
run: each settled invocation contributes exactly once, each `in_flight`
reservation contributes a conservative unresolved amount, and re-deriving on a
second resume is identical (the same rows, the same totals). A crash after the
provider succeeded but before the node state update is recovered from the ledger
(the settlement was already written before the node returned, or — if the crash
is between the provider returning and the settlement — the reservation remains
`in_flight`, i.e. unresolved). Repeated `invoke(None)` therefore produces the
same totals; nothing is added twice.

### E. Whole-run aggregation, separate from the debate budget

`tradingagents/debate/budget.py` gains a `whole_run_usage` aggregation
(`aggregate_whole_run_usage`) that sums **all** invocations across phases into a
`whole_run_usage` structure with per-phase breakdown and an explicit
`completeness` (`complete` / `partial` / `unknown`). The **debate-scoped**
`debate_usage` / `can_afford_optional_call` remains the *only* budget that
lowers/limits the debate; whole-run totals are **reporting only** and never
silently expand (or shrink) the debate budget to analysts/risk nodes. The debate
invocation is counted **once** — through the run-scoped ledger — never both
through the node tracker and a second aggregate.

A unified `invoke` wrapper (`tradingagents/debate/usage_capture.py`) is bound for
each run (a `ContextVar`, mirroring the ADR-008 collector) and is used by every
model-calling node: the researchers, the analysts (via
`agents/utils/structured.py` `invoke_structured_or_freetext` — covering the
structured-then-freetext fallback as up to two logical attempts), the Research
Manager, the Trader, the three risk analysts and the Portfolio Manager. When no
run is bound (a bare node unit test) the wrapper is a transparent no-op that
returns the model response unchanged (backward compatible).

### F. Fail-closed admission when budget is enabled

`can_afford_optional_call` is extended: when the debate budget is enabled and the
ledger reports **unresolved possible spend** (an `in_flight` reservation) or an
**unreadable/corrupt** accounting, a further OPTIONAL debate call is refused
(stop reason stays the stable, auditable `budget_exhausted` semantics with an
explicit `unresolved_spend` detail), rather than being admitted as if the
unknown spend were zero. The summary reserve is preserved: if a safe summary
cannot be afforded the manager still runs on its deterministic known fallback
(the existing participation template), never exceeding policy unknowingly. A
budget-`disabled` config keeps the exact legacy behavior and gains **no** hidden
new global limit.

### G. Reporting and CLI

`report_artifacts.py` exports `whole_run_usage` (per-phase + total), the
execution `run_id`, and an explicit `completeness`. The Markdown summary and the
CLI read the same structure, so they cannot disagree. `usage_provenance` keeps
distinguishing `measured`/`provider`/`estimated`/`unavailable` per field and never
labels an estimate as measured/provider; an unknown failed/in-flight token cost
is `unavailable`, never `0`.

### H. Non-goals / explicit safety stops

- No exact claim date/value/unit semantic validation (Stage 3, DEBT-022).
- No degraded confidence cap 0.60 (Stage 4, DEBT-014).
- No new provider, paid call, data source, dependency, CI, permission or
  human-rule change; no production threshold tuning; no Phase 4B.
- No widening the debate budget to a whole-run spend cap; whole-run totals are
  reporting only.
- No claim that reservation estimates equal physical provider billing; hidden
  SDK retries stay `unknown`.

## Consequences

- Positive: a failed/billed attempt survives a crash as durable unresolved
  spend; resume reconciles idempotently; whole-run totals are truthful and
  explicit about completeness; provenance is honest per field.
- Negative/cost: introduces a local SQLite side file per run and a reconciliation
  step; every model-calling node gains a wrapper that must stay a transparent
  no-op when unbound.
- Risk: double-counting the debate call is mitigated by counting only via the
  ledger; a wrong reconciliation is pinned by idempotent-resume tests.

## Verification (this ADR's implementation)

Approved test cases in `tests/test_durable_usage_ledger.py` and
`tests/test_whole_run_usage.py` use fake scripted models plus the real production
graph/state and a real `SqliteSaver`: exception after an attempted model call,
cancellation, invalid ending clock, crash after the provider succeeds but before
the checkpoint/state update, restart with a fresh saver then `invoke(None)`,
repeated idempotent resume, unknown-token fail-closed before an optional call,
summary-reserve preservation, fresh-vs-resumed same ticker/date isolation, corrupt
ledger / unknown version / missing identity fail-closed, concurrent reservation,
provider exact/partial/conflicting/malformed telemetry and estimate provenance,
and an end-to-end mocked full-graph whole-run count covering the analysts + the
structured fallback + the debate + the Research Manager + the Trader + the three
risk analysts + the Portfolio Manager, with the report and CLI read-back and exact
expected totals (no permissive A-or-B). A source-privacy test asserts the ledger
contains no prompts/responses/exception text/URLs/secrets. The existing Stage 1
graph regression stays green.

See `docs/architecture/evaluation-logbook.md`, `docs/architecture/trace-matrix.md`,
`docs/debt-register.md`, `docs/architecture/risk-list.md`,
`docs/ai-use-log.yaml`, and `docs/review-memo.md` for the recorded evidence,
status changes and remaining gaps.

## Amendment — Defect-2: structured-output raw usage retained; honest aggregate labels (2026-11-11)

Offline fix for the confirmed live-run accounting gap: RM/Trader/PM structured
(Pydantic) results carried no `usage_metadata`, so their calls settled as
ESTIMATES even though the provider reported real usage, while plain risk calls
retained provider usage. On the blocked fixture, 6 real calls / 22,600 reported
tokens were recorded as 22,067 with `totals.tokens_source=provider` despite three
estimated structured calls — an undisclosed mixed label (the aggregate was marked
`estimated=true`, `completeness=partial`, but the per-total source was misleading).

- **Same single call, raw usage** (`agents/utils/structured.py`,
  `debate/usage_capture.py`): `bind_structured` binds `include_raw=True` where
  supported; `instrumented_model_call` settles provider usage from the RAW
  `AIMessage` (`usage_response`) while callers render/cap the parsed typed object.
  NEVER a second model call.
- **Binding-only fallback** : if `include_raw=True` is rejected (any exception,
  incl. `NotImplementedError`/`AttributeError`/`TypeError`), the LOCAL binding is
  retried without `include_raw` (no model call) so a working legacy typed provider
  keeps typed output with an honest ESTIMATE — no unnecessary free-text downgrade.
  Only a provider that rejects structured output entirely uses free text.
- **Settlement precedes downstream failures**: the billed boundary is ONLY the
  outbound transport invocation. A parser error, sanitizer error, or render error
  AFTER a known raw response settles that attempt with its EXACT provider usage
  (never an unknown cost, never a double count) and then falls back once as a
  separate counted attempt. An unknown transport exception stays unknown (never
  zero). Legacy estimates use a safe serialization length, not an arbitrary
  renderer inside the billed boundary.
- **Mixed is AGGREGATE/report-only** (`debate/budget.py`, `report_artifacts.py`):
  `SOURCE_MIXED` labels a whole-run/per-phase token total that combines
  provider-exact and estimated/unknown contributions, so it is never falsely
  `provider`. It is NOT a valid per-call source (not in `_ALLOWED_TOKEN_SOURCES`
  or `_SIDE_SOURCE_ALLOWED`) and never changes the locked schemas. Known token
  sums are unchanged (no omitted known tokens); all-provider runs stay `provider`.
- The typed confidence cap (ADR-011) still sees the EXACT raw parsed value before
  the lossy 2dp render; schema shape, fallback semantics and structured
  external-tool restrictions are unchanged (NFR-BC-001).

Tests: `tests/test_structured_raw_usage.py` (18 passed) — all four schemas
(RM/Trader/PM/Sentiment), raw envelope, include_raw-rejection rebind (one
invocation), truly-unsupported free text, parser-error-with-usage before fallback,
sanitizer/render error with known usage, unknown transport, mixed aggregate label,
all-provider stays provider, `mixed` not per-call, idempotent/concurrent
settlement, cap 0.60. Offline only; NOT a live proof.

### Status update (2026-11-11) — independent technical review COMPLETE

The Defect-2 structured-raw-usage fix (include_raw settlement + binding-only
fallback + mixed aggregate label) has been independently verified by Codex: full
strict-offline 2190 passed / 0 sockets; focused 18 passed / 0 sockets; Ruff clean;
governance 43/43. The prior independent block-fixture metadata replay (22,600
accounted = 22,600 expected, 6 provider calls, no double count) remains **OFFLINE
only**. This is **offline technical review only — NOT human acceptance and NOT a
live retest.** Explicit human acceptance and a separately authorized live retest
remain pending; the historical incomplete live run and prior stage reviews are not
relabelled.
