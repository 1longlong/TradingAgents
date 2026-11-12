# ADR-010 — Exact Claim Date/Value/Unit Validation Against Cited Evidence

- **Status:** Proposed (Stage 3 implementation complete in the working tree;
  offline verification run; independent Codex review pending; human acceptance
  NOT claimed). Plan + test cases for the four-item repair were explicitly
  approved by WANG Yiwen (60536848) in the controlling conversation on
  2026-11-11; that approval authorizes the plan and the test cases (cap 0.60)
  ONLY and is **not** a final human acceptance of any item. Stage 1 (ADR-008) and
  Stage 2 (ADR-009) are implemented; this **Stage 3** is implemented; **Stage 4**
  (degraded confidence cap 0.60, DEBT-014) remains NOT implemented.

  **Offline verification (2026-11-11):** `tests/test_exact_claim_validation.py`
  (73 passed, pure validator/origin matrix) + `tests/test_exact_claim_runtime.py`
  (30 passed, real production graph + real `SqliteSaver`) via the strict
  socket-denied harness; full strict-offline suite **2044 passed / 1 skipped / 1
  deselected / 22 warnings / 88 subtests / 0 forbidden socket attempts** (baseline
  1940; +104 new); `ruff check .` clean; governance validator PASS (43/43);
  `git diff --check` clean. This is the offline behavioral + regression tier only,
  NOT live behavior and NOT human acceptance.

  **Verifier review fixes (2026-11-11, incorporated):** (1) a malformed/absent
  `value_scale` NEVER normalizes to 1, and non-date-typed/ambiguous dates are
  rejected; (2) an invalid exact claim never ERASES an open/escalated conflict —
  the attempted observation/resolution is REJECTED and the prior record + history
  are KEPT with a recorded denial (see §D); (3) a turn may carry MULTIPLE typed
  claims and a good ID can never launder a mismatching co-cited ID or a second
  wrong claim on the same ID (per-claim coverage, no first-claim-wins — see §B/§C);
  (4) the trusted redaction is enforced at EVERY trusted plan/decision/report/
  memory boundary (not only the Research Manager) and raw debate transcripts are
  explicitly NON-AUTHORITATIVE (see §D).
- **Date:** 2026-11-11
- **Deciders:** CS5351 project (student); coding-agent (OpenCode Builder);
  independent reviewer (Codex); human review required before acceptance
- **Trace:** `FR-DDT-002` (valid-new-evidence manifest / citation allowlist),
  `FR-DDT-005` (deterministic ConflictRecord lifecycle — evidence validation),
  `NFR-PIT-001` (point-in-time integrity), `NFR-AUD-001` (auditability),
  `FR-DQG-005` (report artifacts), `NFR-DET-001` (determinism),
  `NFR-BC-001` (backward compatibility), `INV-1`/`INV-3`/`INV-6`/`INV-8`/`INV-13`.
  No new requirement ID is invented: this ADR resolves the claim-date/value/unit
  semantic gap recorded in DEBT-022 / RISK-020 under the existing IDs.

## Context

The Stage 2 citation allowlist (`ADR-002`,
`tradingagents/debate/evidence_manifest.py`) verifies that a cited evidence ID is
**eligible**: known to the gate manifest, High/Medium quality, and observed on or
before the target date, and explicitly linked to a claim. That is a check on the
**record**, not on the **claim**. A model-written claim that cites a perfectly
valid ID but states a *different* observation date, amount, or unit still passes
today. This is the exact defect recorded from the 2026-11-06 NVDA run (DEBT-022 /
RISK-020): the Bull cited the valid `observed_at=2026-11-04` close evidence ID but
described the `200.13` close as "2026-11-05" in prose and in the structured
`new_claims` link. The record was valid; the claim was wrong. Because a
"valid_new_evidence" ID can extend the debate (evaluator rule 6) and can resolve
or keep a `ConflictRecord` open, a wrong date/value/unit can improperly extend the
debate or resolve a factual conflict, and the wrong fact can then reach the
Research Manager prompt and the saved report/memory.

Two structural facts constrain the repair:

1. **Locked schemas.** `EvidenceRecord` has exactly 20 locked fields and
   `SourceAttempt` exactly 7; both are frozen (INV-4). The exact claim metadata
   cannot be smuggled in by adding fields to either.
2. **The Stage 1 SEC builder sets `observed_at = filed date`** and keeps
   `period_end` only inside the ID hash / `source_ref`, not as a separate typed
   field. Genuine fiscal-period/observation dates and the published/filed/
   retrieved instants are **not** currently distinguishable as typed values, and
   the target trade date is a fourth, distinct role. Merging any of them silently
   is precisely how a "Nov-4 close" becomes a "Nov-5 close".

The repair must (a) stop treating a correct cited ID as proof that model-written
exact dates/amounts/units are correct; (b) validate structured exact claims
against the actual manifest record **and** typed origin metadata; and (c) be
**consumed at runtime** — not a helper that is never called.

## Decision

### A. Typed origin metadata sibling (evidence-ID-keyed, never locked fields)

A new module `tradingagents/evidence/origin.py` defines a **versioned,
JSON-safe origin-metadata record** keyed by evidence ID
(`ORIGIN_SCHEMA_VERSION = "1.0"`). It carries, as *distinct typed fields*:

- `target_date` — the requested trade date the run is evaluated "as of";
- `observation_date` — the fiscal period end / observation date the record is
  about (e.g. SEC `period_end`), when the vendor genuinely provides it;
- `availability_date` — when the fact became public (e.g. SEC **filed** date,
  news **published** date);
- `published_at` / `filed_at` — the vendor timestamp (ISO datetime with an
  explicit timezone when the vendor supplies one), distinct from the bare
  availability *date*;
- `retrieved_at` — when this run fetched the record (`fetched_at`);
- `date_basis` — the stable role name of the record's own `observed_at`
  (`filed` / `published` / `period_end` / `unknown`) so a consumer never has to
  guess what `observed_at` means;
- `value_scale` / `unit` / `currency` — the record's unit semantics
  (`currency` present only for monetary amounts; `value_scale` e.g.
  `1`/`SCALE_BASE` for base units, `1e6` for "millions"), never invented. An
  **absent** scale (`None`) means UNKNOWN, not "one": a source that does not
  declare a base-unit scale stays unknown, and a provided-but-invalid scale
  (bool/NaN/inf/non-positive/unparseable) normalizes to UNKNOWN — it is **never**
  laundered into `1`, so a malformed scale can never verify a wrong magnitude.
  A producer that genuinely knows the source uses base units passes
  `SCALE_BASE` explicitly;
- `period_end_source` — `vendor` / `absent` so empty values are honest.

The sibling is **additive and versioned**. It never mutates the 20 locked
`EvidenceRecord` fields; a missing/unknown/legacy origin record is a **hard
"cannot verify"** (fail closed), never a guessed date or unit. The producer
(`evidence_capture.py` / `vendor_adapters.py`) fills it from the *same* vendor
row it already adapted; a default yfinance/Alpha Vantage fundamentals record
with no filing date stays `availability_date = None` (`date_basis` still carries
`unknown`), so it remains **unavailable for historical proof** — a filing date is
never invented from the target/fetch time. The Stage 1 SEC path now records the
genuine `period_end` (observation) **and** the `filed` date (availability) as
separate typed fields in the sibling, keyed to the same `evidence_id`, while
`observed_at` stays the filed date (unchanged) for backward compatibility.

Origin metadata is persisted on the production `AgentState`
(`data_quality_origin_metadata`, keyed by evidence ID) alongside the existing
gate output, so it survives checkpointing and is re-seeded on resume, and it is
exported for audit. A duplicate evidence ID with **conflicting** origin metadata
is a fail-closed condition: the record is not verifiable and any dependent claim
is `unverified`.

### B. Typed exact-claim envelope (additive, versioned) + conservative prose

`tradingagents/debate/claims.py` defines the claim contract. The structured
`DEBATE_METADATA` marker gains an **optional** typed field carrying one OR MORE
exact claims per turn: repeated `claim=` fields (the primary multi-claim channel),
or a single `claims=` field with `||`-separated claims. Each typed claim, e.g.
`claim=metric=close|role=observation_date|date=2026-11-04|value=200.13|unit=USD|currency=USD`,
is parsed into a `ClaimRecord` (additive/versioned; `CLAIM_SCHEMA_VERSION = "1.0"`).
A turn making several exact claims MUST emit one per claim; otherwise one correct
claim could stand in for a second wrong claim on the same ID. Each claim is
validated independently and any mismatch rejects that claim. The typed claim has:

- `evidence_ids` — the cited IDs it must be validated against;
- `metric` — the metric name it asserts;
- `date_role` — `target_date` / `observation_date` / `availability_date` /
  `filed_at` / `published_at` / `retrieved_at` (explicitly distinct);
- `date` — the asserted date value;
- `value` — a finite, non-bool `Decimal` (parsed via the shared
  `quantize_decimal`; a NaN/bool/unknown/malformed value never becomes a claim);
- `unit`, `currency`, `value_scale` — the asserted unit semantics.

The legacy version-1.0 free-text `claim` in `ClaimEvidenceLink` remains parseable
and backward compatible, but a **legacy untyped exact claim is never treated as
verified**: it cannot count as verified new evidence, cannot resolve a factual
conflict, cannot justify a strong conclusion, and is never emitted as trusted
verified report data merely because the IDs are valid.

For **common exact prose claims** (`inline date + number + unit + a cited ID`)
the turn parser also extracts a **conservative** typed claim via a bounded
deterministic parser (e.g. `on 2026-11-04 ... $200.13` with a citation), and a
mismatch is rejected/quarantined. This parser is explicitly **not** claimed to
prove arbitrary natural-language semantics: a prose claim that cannot be
deterministically parsed is labelled **unverified** and omitted from the
authoritative narrative (it is not "verified" and it does not become trusted
report data). Supported qualitative analysis is never rejected merely because it
is prose; the global Hold path and existing blocked guards/budgets/optional
evidence/report attribution are unchanged.

### C. Deterministic exact validation (pure, LLM-free)

`validate_claim(claim, origin_by_id, manifest, target_date)` returns a
`ClaimValidation` (status `verified` / `rejected` / `unverified`, plus a stable
`reason` code and a redacted `provenance` block). It validates:

- **Identity/run IDs.** Every cited ID must be in the manifest, High/Medium, and
  tied to this run's ticker/`run_id`; a different ticker, a foreign run ID, an
  unknown ID, or a Low/Blocked ID is `rejected`. A record with NO `run_id` is
  `unverified` (it cannot be tied to this run). A missing/malformed target_date or
  record `observed_at` is `unverified` (point-in-time cannot be proven — never
  skipped). The claim envelope must declare a KNOWN, non-empty claim-contract
  version (an empty/unknown version is `unverified`). The typed origin must AGREE
  with the actual record on the shared facts (target_date, the record's
  observed_at-as-named-by-`date_basis`, unit and currency), else `unverified`
  (a typed-but-wrong origin cannot vouch for a mismatching record).
- **Availability point-in-time.** Regardless of which date role a claim asserts,
  the record's availability/filed/published instant must NOT be after the target
  (a look-ahead is `rejected`); the RETRIEVED instant is a distinct role and is
  NOT checked (a historical run may legitimately retrieve later).
- **No laundering across multiple cited IDs.** EVERY cited ID used as support must
  independently corroborate the asserted facts. A single mismatching co-cited ID
  makes the support set inconsistent → `unverified` (the passing ID is never
  promoted alone). The verified `support_evidence_ids` list is returned explicitly
  and never includes a failed ID.
- **Date role.** The asserted date is compared with the **matching role's** typed
  origin value (never a different role). A `target_date` claim compared to
  `target_date`; an `observation_date` claim against the record's genuine
  observation date — a **target != observation** mismatch (or an SEC **filed !=
  fiscal end** mismatch) is `rejected`. Granularity is explicit and honest:
  **calendar roles** (target/observation/availability) compare at documented
  *day* granularity (no intraday-time proof is claimed); **timestamp roles**
  (published_at/filed_at/retrieved_at) compare as normalized UTC instants and a
  date-only source value can **never** prove an exact timestamp (→
  `unverified`), while a same-calendar-day but different hour/timezone is a
  **mismatch**. A non-date-typed value (int/float/bool/list), a compact
  `YYYYMMDD`, or a locale-order/slash date is rejected at construction (never
  stringified and parsed as a calendar date); an ambiguous/unparseable/missing
  claim date is `unverified` (not guessed); a matched-but-future role value is a
  look-ahead and is `rejected`.
- **Value.** A finite non-bool `Decimal` is required; an ASSERTED-but-invalid
  value (NaN/bool/non-numeric) is flagged and `rejected` (never silently dropped).
  The asserted amount is compared with the record's normalized value under the
  record's declared `value_scale`; a mismatch beyond a deterministic
  exact-equality tolerance is `rejected`.
- **Dimension/unit/currency/scale (ALL numeric claims, not only money).** Every
  exact number has a dimension — money (a currency), `shares`, `percent`, or an
  explicit dimensionless `ratio` — and the RECORD and the CLAIM must BOTH declare a
  known dimension that MATCHES exactly (shares/percent/ratio/money never
  corroborate one another; a pure ratio must be declared `ratio`, never inferred
  from a bare number). A record with an unknown dimension (the default market
  adapter's `native_quote_currency`) or an absent claim unit is `unverified`
  (never inferred). Unit SHAPE is normalized (`USD`≈`us$`≈`dollars`); scale words
  (`million`/`mn`/`bn`) are NEVER mapped to a currency. For money the claim MUST
  declare a matching currency (**no speculative FX**). `record.value_normalized`
  is BASE units; the claim's asserted number is normalized by its OWN declared
  `value_scale` (base when omitted) and compared to the base value, so
  `391000 million USD` and `391000000000 USD` are the same magnitude and both
  verify against the real base value — but an EXPLICIT claim scale is only
  accepted when the record declares a KNOWN scale (an explicit multiplier never
  invents missing record semantics), and an ASSERTED-but-invalid scale/value is
  flagged and `rejected` (never treated as omitted/base-1).

The validator is pure and deterministic given its inputs (repeat/shuffled-order
equality), never reads a clock/RNG/network, and records the validation result,
the reason, and redacted provenance so any run is auditable (INV-6).

### D. Runtime consumption (the integration that makes it real)

1. **Turn parsing** (`tradingagents/debate/turn.py`) parses EVERY typed `claim=`
   field (and optional `claims=` with `||` separators) plus the conservative prose
   claim into `DebateTurn.exact_claims` — a turn supports MULTIPLE claims.
2. **Valid-new-evidence** (`evidence_manifest.py` / `evaluator.py`): an ID that is
   the target of an exact claim only counts as new valid evidence when that claim
   **validates as `verified`**. A cited, eligible ID whose *claim* is wrong
   (date/value/unit mismatch) does **not** extend the debate (no improper
   `no_new_evidence` avoidance / rule-6 continuation).
3. **Conflict lifecycle** (`conflicts.py`): a factual `ConflictAssertion` that
   cites an invalid (unknown/low/future/wrong-claim) ID is REJECTED, but it NEVER
   erases an already open/escalated conflict — the prior record and history are
   KEPT and an auditable denial is recorded (a bad citation cannot manufacture
   convergence). An attempted `resolve`/`escalate` that cites invalid evidence is
   likewise rejected with the prior status kept. Action/interpretive conflicts are
   unaffected.
4. **Research Manager** (`research_manager.py`): receives a **verified claim
   summary** and an explicit **rejected/unverified list** (a prose-free block, no
   chain-of-thought), so it can weigh the debate without trusting an invalid exact
   fact.
5. **Fresh per-boundary exact-fact validation at EVERY trusted boundary**
   (`agents/utils/output_guard.py` `enforce_trusted_boundary`): this does NOT merely
   look up facts the debate already rejected — it extracts each boundary's OWN
   exact factual prose and re-validates it against the state manifest + origin. It
   is applied at the **Research Manager** plan, the **Trader** plan, the
   **Portfolio Manager** `final_trade_decision`, the **memory** decision
   (`record_decision`), AND every trusted **report** section
   (`reporting.write_report_tree`), so a downstream model that HALLUCINATES a brand
   new wrong date/amount/unit (even with NO prior rejected debate claim) is
   contained at its own boundary. It works at **clause/magnitude granularity**: a
   recommendation word in one clause never exempts a factual clause on the same
   line, and a clause that recommends *because* of a HISTORICAL dated fact is
   treated as a fact clause (only a genuine forward-looking/target clause is
   exempt); EVERY numeric magnitude in a clause is paired with its date and checked
   (an initially-correct amount cannot launder a second wrong one, and each value
   carries its own adjacent unit); and a citation is associated over a BOUNDED
   multi-line window (a date and value split across adjacent lines are still
   paired). A genuine forward-looking price-target/recommendation clause and
   ordinary qualitative prose are preserved. Each rejected fact has date+value
   spans blanked to an explicit unverified marker and an auditable provenance
   record. This never globally forces Hold. Scope is FINITE and explicit — supported
   dated numerical facts with an associated citation — and no arbitrary
   natural-language-completeness claim is made.
6. **Raw transcripts are non-authoritative.** The Bull/Bear debate transcript is
   the model's argument as spoken and may contain a claim that later failed
   validation; it is written to the report under an explicit NON-AUTHORITATIVE
   notice so it is never read as a verified fact. The audit artifact
   (`report_artifacts.py` `2_research/debate_trace.json` `claim_validation`) carries
   the verified/rejected/unverified summary (redacted, no raw prose).

### E. Non-goals / explicit safety stops

- No claim that a regex/heuristic proves arbitrary natural-language semantics;
  unparseable prose is `unverified`, never "verified".
- No change to the 20 locked `EvidenceRecord` fields or 7 locked `SourceAttempt`
  fields; origin/claim data is additive, versioned siblings.
- No speculative FX, no invented dates/units, no trust of a model-written grade.
- No global Hold for non-exact prose; existing blocked guards, budgets, optional
  evidence and report attribution never regress.
- No degraded confidence cap 0.60 (Stage 4, DEBT-014), no production threshold
  tuning, no new provider/paid call/dependency/CI/permission/human-rule change,
  no Phase 4B.

## Consequences

- Positive: a correct cited ID no longer launders a wrong exact date/value/unit;
  a wrong exact fact cannot extend the debate, resolve a factual conflict, or
  reach the trusted plan/report/memory; point-in-time date roles are explicit and
  auditable; the manifest record and typed origin metadata are the source of
  truth.
- Negative/cost: producers must attach typed origin metadata; the turn adds an
  optional claim field; the evaluator/conflict tracker/manager each gain a modest,
  deterministic validation hook; new state/report channels must stay JSON-safe.
- Risk: an over-eager prose parser could reject a correct qualitative statement.
  Mitigated by strict scope (only inline exact claims with a cited ID), a
  conservative parser, an explicit `unverified` label instead of rejection, and
  negative tests that pin supported qualitative prose as unchanged.

## Verification (this ADR's implementation)

Approved test cases live in `tests/test_exact_claim_validation.py` (pure matrix)
and `tests/test_exact_claim_runtime.py` (real runtime), using the REAL production
`AgentState` / `GraphSetup`, mocked raw vendors and scripted models that
deliberately cite a valid ID but a wrong date/value/unit, and a REAL
`SqliteSaver` interrupt/restart. They cover: correct/incorrect dates by role;
target != observation; SEC filed != fiscal end; timestamps/timezones/ambiguous
dates; stale/future/malformed/missing; exact values/currency/scales/units incl.
NaN/bool; mismatched ID/ticker/run; duplicate IDs / conflicting origin metadata;
unknown schema fail closed; no valid-new-evidence and no improper conflict
resolution on a wrong claim; an auditable manager input; a trusted final
plan/report/memory that cannot repeat a wrong verified fact; valid typed exact
claims staying usable and unchanged; the qualitative/no-claim legacy path
unchanged; and a real-checkpoint resume that preserves origin metadata /
validation / denials and cannot resurrect a prior wrong claim via the public
entry report propagation. All tests are socket-disabled offline with mocked
vendors/models; no live vendor/model call is made.

See `docs/architecture/evaluation-logbook.md`, `docs/architecture/trace-matrix.md`,
`docs/debt-register.md`, `docs/architecture/risk-list.md`,
`docs/ai-use-log.yaml`, and `docs/review-memo.md` for the recorded evidence,
status changes and remaining gaps.

## Amendment — Defect-1: origin survives ingestion persistence; conflicts fail closed (2026-11-11)

Offline fix for the confirmed live-run defect where the gate built the correct
origin map for the five market records but then `output.update(persisted)`
overwrote it with the live collector's (empty-for-market) origin delta, leaving
`data_quality_origin_metadata` empty and all exact claims `claim_origin_unknown`.

- **Authoritative merge AFTER persistence** (`graph/data_quality_gate.py`
  `_merge_authoritative_origins`): the gate-derived/captured origin map is the
  last write to `ORIGIN_STATE_KEY`. Genuine captured origins (SEC filed / news
  published / real date roles) are preserved; the collector's empty market delta
  can no longer erase them. No invented date/currency.
- **Conflicts fail closed, never first/last-wins** (`evidence/ingest.py`,
  `evidence/origin.py`): a real collector duplicate-origin insertion, or a
  state-vs-collector disagreement for the same id, is RETAINED and the id is
  removed from the trusted map and recorded in a DECLARED state channel
  `data_quality_origin_conflicted_ids` (`ORIGIN_CONFLICTED_STATE_KEY`). Seeding is
  UNCONDITIONAL from persisted state (not only via an active collector), so a
  direct SQLite resume / imported report state cannot re-derive/re-trust it.
  `origin_records_from_state` drops conflicted ids at the single read choke point
  every consumer uses; the evaluator and output boundary additionally pass the
  conflict set to the claim validator (`_duplicate_origin_ids_from_state`,
  `output_guard`), so an exact claim on a conflicted id is `unverified` at both the
  debate and trusted-output boundaries. A conflicted id is never re-derived.
- **No resurrection**: pruned/dropped/tombstoned ids are excluded from the trusted
  map AND the conflicted set. `EvidenceRecord` (20 fields) and `SourceAttempt`
  (7 fields) are unchanged; the conflict channel is a separate declared
  `AgentState` key that persists across a real SQLite checkpoint/resume.
- The gate verdict is NOT globally forced to `blocked` merely because an origin is
  unknown/ambiguous (origin is a claim-validation aid, not a category-criticality
  input).

Tests: `tests/test_gate_origin_authority.py` (18 passed) — active empty collector,
real checkpoint-seeded collector, genuine captured-origin preservation, REAL
collector duplicate-origin conflict, state-vs-collector conflict, no-collector
conflicted-state re-trust refusal, imported stale-map + conflict exclusion,
pruning/tombstone, 20-field invariant, declared channel, and real SQLite
close/rebuild/resume (incl. resume AFTER the gate). Offline only; NOT a live proof.

### Addendum — no-resurrection edge: existing state tombstones honoured without a collector (2026-11-11)

Independent review found one scoped gap within the no-resurrection requirement:
with NO active collector (`persisted=None`) but a pre-existing state
`data_quality_dropped_evidence_ids` tombstone and a stale
`data_quality_origin_metadata` map, both the gate output map and
`origin_records_from_state(state)` still trusted the tombstoned id (final merge
used only `persisted` dropped ids). Fixed:

- `origin_records_from_state` now ALSO excludes ids in
  `data_quality_dropped_evidence_ids` (`ORIGIN_DROPPED_STATE_KEY`, canonical key
  now in `origin.py`) at the single read choke point — a stale persisted origin is
  never re-trusted for a dropped id.
- `_origin_state_map` seeds the tombstone set UNCONDITIONALLY from state (and the
  live collector), drops tombstoned ids from `existing` AND from the derivation
  input, so no replacement origin is minted for an excluded record.
- the gate final merge unions existing-state tombstones with the collector delta's
  tombstones, so a no-collector run cannot resurrect a dropped id.

Regression tests (`tests/test_gate_origin_authority.py`, 18 passed): no-collector
gate + direct stale-map consumer exclude a dropped id; and REAL interrupted resumes
(ambiguity and tombstone variants) preserve exclusion after the pending node runs.
Locked `EvidenceRecord`(20)/`SourceAttempt`(7) unchanged.

### Status update (2026-11-11) — independent technical review COMPLETE

The Defect-1 origin-authority fix (and its no-resurrection tombstone addendum) has
been independently verified by Codex: full strict-offline 2190 passed / 0 sockets;
focused 18 passed / 0 sockets; the stale-map + state-tombstone reproduction now
yields `gate_retrusted=False`, `direct_consumer_retrusted=False` (previously
True/True); Ruff clean; governance 43/43. This is **offline technical review only —
NOT human acceptance and NOT a live retest.** Explicit human acceptance and a
separately authorized live retest remain pending; the historical incomplete live
run and prior stage reviews are not relabelled.

### Amendment (2026-11-12) — standalone typed-claim recovery + honest coverage (Defect 2)

Approved plan + test cases: human WANG Yiwen, 2026-11-12 (implementation approval,
NOT final human acceptance). A completed 2026-11-11 school-model live run showed the
Bear model wrote **8** `claim=metric=...|role=...|date=...|value=...|unit=...|
evidence=...` lines **BEFORE** `DEBATE_METADATA:`; the marker-only parser stored
`metadata_parse_status=ok` with `exact_claims=[]` and an empty claim-validation
summary — an out-of-contract typed claim that never entered date/value/unit
validation (it was NOT proof that wrong claims were verified).

- **Shared strict extractor (`claims.extract_standalone_typed_claims`)** used at the
  turn boundary AND the trusted output/report boundary. A line is a record only
  when, after optional bullets/whitespace, its FIRST token is `claim=`/`claims=` and
  every pipe segment is a known `key=value`; a record with no typed constraint, a
  bare segment, an unknown key, a duplicate conflicting key, or a contradictory
  `role`/`date_role` alias pair is `unparseable` (surfaced, never dropped).
- **Not trust:** recovered records flow through the SAME `validate_claim`
  (unknown-ID / future (PIT) / Low/Blocked / foreign-run/ticker / wrong
  date/value/unit/currency/scale / role-mismatch all fail closed → rejected/
  unverified, never verified). No guessing of missing fields.
- **Marker integration:** marker claims are kept first; a standalone claim is
  appended unless it is the SAME canonical claim; marker presence NEVER hides an
  outside claim (both collected, dedupe only by canonical identity). Recovery is
  independent of a successful stance parse — the prose-fallback and parse-FAILED
  branches also recover/diagnose standalone lines (no-marker / no-stance included).
- **Shared strict grammar (canonical parity):** ONE
  `parse_strict_typed_claim_payload` is used by BOTH the canonical
  `DEBATE_METADATA` `claim=` parser AND the standalone extractor, so a canonical
  claim with a contradictory `role`/`date_role` (or any malformed/conflicting typed
  field) is unparseable/PARTIAL rather than laundered into a trusted 1-claim turn;
  valid canonical behavior is unchanged.
- **Quoted/examples never trusted:** fenced code blocks are tracked and skipped.
  The OPEN fence length and character are remembered: a close must use the SAME
  char and a length ≥ the opener with no non-whitespace suffix, so a SHORTER fence
  does NOT close a longer one (` ```` ` open + ` ```` ` triple close stays open) and
  an UNCLOSED fence runs to end-of-text. A narrow, documented explicit illustrative
  block is also excluded: a line matching `^examples?(?:\s+\d+)?\s*:`
  (e.g. `Example:` / `Examples:` / `Example 1:`) opens a block whose following
  typed lines are illustrative until a blank line or a non-typed line ends it. This
  is deterministic pattern matching, NOT arbitrary natural-language understanding.
  A quoted/`>`/backtick-wrapped line does not begin with the typed keyword and is
  ignored. Legitimate UNLABELLED actual claim lines are still recovered.
- **Honest coverage:** `DebateTurn` carries additive `standalone_typed_claim_count`
  and `unparsed_typed_claim_count` (serialized; backward-compatible defaults 0);
  `claim_validation_summary` gains an additive `coverage` block
  (`typed_lines_found`/`parsed`/`unparseable`/`source`/`turns`) present ONLY when
  typed lines were seen (legacy/qualitative turns are byte-identical); a
  coverage-only summary produces a non-empty RM prompt block (never an empty
  success). The coverage block is exported (redacted) in
  `2_research/debate_trace.json`.
- **WHOLE-document trusted boundary, no-manifest safe:** ONE fence/quote-aware walk
  (`extract_standalone_typed_claims_indexed`) is used by the turn parser AND the
  trusted output boundary — the boundary validates the WHOLE document, not line by
  line, so a fenced/Example line is never treated as real and the fence context
  cannot diverge between callers. When the state carries NO evidence manifest, an
  explicit standalone typed line is REDACTED with a missing-evidence/unverified
  diagnostic (never silently passed through); ordinary non-typed prose is a
  byte-for-byte no-op (legacy no-op preserved).
- **Frozen schemas unchanged:** `EvidenceRecord`(20) / `SourceAttempt`(7) untouched.
- **Tests:** `tests/test_standalone_claims.py` (49 passed) covers the 8 verbatim
  live lines, marker before/after/hidden, no-marker/no-stance FAILED branch, dedupe,
  malformed/conflicting/alias contradictions (canonical AND standalone), fenced
  (incl. unclosed, tilde, and four-backtick opener where a shorter fence does not
  close it) and `Example:` block / quoted examples (a known-valid copy can never
  verify), the no-manifest boundary redaction, fail-closed negatives, the
  coverage-only RM block, the report trace coverage/rejection, malformed/rejected
  claims not stored at the memory/report boundary, and a REAL SQLite
  checkpoint→resume asserting the RESUMED evaluator summary (verified close claim)
  plus recovered claims + coverage.
- **Scope/limits:** offline, deterministic verification only; extraction ≠ trust;
  arbitrary prose semantics are NOT claimed proven. This is an ADR-010 amendment,
  NOT human acceptance and NOT a live retest.
- **Status (2026-11-12):** independent Codex technical review **COMPLETE**
  (full strict-offline 2290 passed / 0 sockets; independent OFFLINE replay of the
  actual prior-school Bear text recovers all 8 claims as 1 verified (volume) /
  5 rejected (unknown optional evidence) / 2 unverified (price currency/unit
  genuinely unknown) — honest non-empty validation, NOT all-8-verified; fences,
  Example blocks, and canonical/outside alias conflicts all confirmed). Explicit
  **human acceptance remains pending**; the old real live run remains historical bug
  evidence, never post-fix live proof.

### Addendum (2026-11-12) — verified typed span not re-redacted as prose (residual false-redaction repair)

Approved plan + test cases: human WANG Yiwen, 2026-11-12 (implementation approval
ONLY, NOT final human acceptance). The 2026-11-12 school live run (26 calls /
202,941 tokens; historical bug evidence, NOT post-fix proof) exposed a residual
**evidence-loss** defect: a CORRECT long-decimal typed claim
(`value=306127800.0000000000`, explicit `unit=shares`, real volume evidence ID +
typed origin) strictly validated as **verified**, but `enforce_trusted_boundary`
then fed the same typed line to its generic prose scanner, whose `_nearest_unit`
uses a 24-character proximity; the long normalized value pushed `shares` out of the
window, so `claim_unit_or_currency_unknown` BLANKED the already-verified date/value.
Short `306127800` survived, confirming a representation-length-dependent false
rejection (not missing vendor evidence).

- **Fix (occurrence-exact span; no window enlargement, no whole-line/document skip):**
  a verified typed `ClaimRecord`'s OWN ``date=`` and ``value=`` token spans are made
  authoritative for that exact occurrence at the trusted boundary. Protection is
  tied to the EXACT parsed payload occurrence (via
  `claims.extract_claim_span_occurrences`), NOT a whole-line first match — so one
  verified subclaim can never authorize an earlier/later subclaim that shares the
  same date/value but a wrong unit/currency/scale/evidence. The generic prose pass
  decides blanking PER TOKEN (`_span_is_authorized`): a span that is exactly a
  verified typed ``date=``/``value=`` token is never erased, and an unauthorized span
  is always blanked — independent of how the heuristic date↔value pairing associates
  them. This prevents a verified token from being lost because the heuristic
  re-paired it with a SIBLING's date (e.g. two IDENTICAL verified canonical subclaims
  joined by ``||``: exhaustive 720 field-order permutations preserved, previously 176
  false redactions), while a wrong value/date/unit is a DIFFERENT (unauthorized) span
  and is still redacted even when heuristically paired to a protected token. Every
  separate prose/adjacent/tail assertion and any non-verified/unparseable/absent typed
  claim is still fully validated. A mixed typed line whose grammar no longer parses
  fails CLOSED (whole line redacted), never by widening the grammar.
- **Occurrence-exact raw token + numeric equivalence:** each protected occurrence's
  ``date=``/``value=`` span is located from the RAW payload token (whatever numeric
  form: extra zeros, scientific), not by comparing raw text to the normalized
  `ClaimRecord.value`; numeric equivalence is proven by strict `ClaimRecord`
  normalization inside `validate_claim`, never by float/fuzzy/substring. Duplicate
  identical payloads keep distinct positional offsets (no first-match collapse).
- **Canonical parity + consistent exclusion:** a verified ``claim=`` field inside a
  ``DEBATE_METADATA`` marker is protected identically to a standalone line, and is
  located at its OWN occurrence offset within the marker line. Both standalone and
  canonical detection share ONE whole-document fence/Example/blockquote exclusion
  walk (`claims._iter_non_illustrative_lines`), so a fenced, `Example:`, or
  blockquote/quoted (`> ...`) canonical claim can NEVER gain protection (no permissive
  per-substring parser bypasses the walk).
- **No contract change:** `validate_claim`, the 24-char `_nearest_unit` proximity
  (still used for genuine prose), and the frozen `EvidenceRecord`(20)/
  `SourceAttempt`(7) are unchanged; the strict extractor's public result type is
  unchanged. `contain_unverified_exact_facts` gains one private helper
  (`_verified_typed_protected_spans`) used by both the per-line and cross-line
  passes. `debate/claims.py` gains an additive shared exclusion walk
  (`_iter_non_illustrative_lines`, now also used by the existing standalone
  extractor) and an additive occurrence extractor
  (`extract_claim_span_occurrences`) that locates raw field tokens per occurrence,
  so standalone and canonical detection never diverge on fences/Example/blockquote
  blocks.
- **Tests:** `tests/test_verified_span_boundary.py` (77 passed) — exact residual
  reproduction preserves `306127800.0000000000` and the real date; equivalent
  short/long/extra-zero/scientific(`e`/`E`) numeric forms preserved (raw payload token
  offset located; equivalence proven by strict `ClaimRecord` normalization, not
  raw-text equality/float/substring) with nearby wrong values redacted and duplicate
  identical payloads keeping distinct offsets; canonical-marker form; fullwidth/NFKC
  (offset-aligned); same-line and adjacent prose assertions with a wrong value still
  redacted (no cross-pairing, both orders); canonical mixed good/bad same-ID/same-line
  (verified `shares` sibling preserved, wrong `USD` sibling date+value redacted,
  both orders); wrong value/future-date/wrong-unit/wrong-currency/wrong-scale/
  unknown-ID/role-mismatch and Low/Blocked evidence still redacted; fenced (incl.
  four-backtick/short-close/unclosed), `Example:` blocks AND blockquote/quoted (`>`)
  lines never promoted for standalone OR canonical (direct assertions that ZERO
  authorized occurrences are produced); conflicting-grammar fail-closed; no-manifest
  and legacy no-op; idempotence including after redaction; duplicate verified
  occurrences (two identical canonical subclaims joined by ``||``: exhaustive 720
  field-order permutations preserved, and mixed verified+wrong siblings redact only
  the bad component); REAL `write_report_tree`
  (`trader.md` + `complete_report.md`) and REAL `record_decision`/`TradingMemoryLog`
  (real `_is_blocked_state`, no monkeypatch) preserve the long value and do not store
  a rejected wrong claim.
- **Supported-format variants:** the raw field-offset locator walks the ORIGINAL pipe
  segments with the SAME `key.strip().lower()` semantics as the strict parser and
  computes offsets against the RAW payload (including any backtick/whitespace
  wrapper); supported variants (`DATE=`/`VALUE=` uppercase, `date = ...` spaced,
  canonical ``claim=`...` `` backticked) are protected (supported syntax, NOT grammar
  expansion), while standalone ``claim=`...` `` (backtick directly after `claim=`) is
  not accepted by the strict parser and is correctly not protected.
- **Field-order / wrapper location:** the grammar is field-order independent, so
  offsets are computed on the wrapper-stripped payload the parser sees and shifted
  back onto the original line by the MEASURED consumed prefix (bullet/numeric-list
  prefix length + canonical whitespace/backtick wrapper length), so a `date=`/`value=`
  FIRST or LAST (with bullets/numeric-list/canonical backticks) points at the exact
  token; regressions assert exact token offsets into the original text.
- **Scope/limits:** offline, deterministic verification only. Prior 26-call /
  202,941-token school run remains historical bug evidence; this is NOT a live
  rerun and NOT a claim that all defects are fixed.
- **Status (2026-11-12):** independent Codex FINAL technical review **COMPLETE**
  (covered OFFLINE scope): full strict-offline 2367 passed / 0 sockets; focused
  specified 8 modules 556 / 0 sockets (different subset from the 716 related suite;
  not conflated); exhaustive 4320 format cases (720 field orders × 6 formats incl.
  duplicate canonical) preserved; saved-response replay 19 total checks incl. the 5
  equivalent numeric variants all true; real `write_report_tree`/`record_decision`
  preserve the correct long line while future/unknown-ID claims are removed.
  Authority is PER VERIFIED TOKEN OCCURRENCE (not heuristic date↔value pair); the
  unprotected partner is still checked/redacted; no whole-line bypass. **Explicit
  HUMAN FINAL ACCEPTANCE and any post-fix live retest remain PENDING**; independent
  technical review is NOT human approval and does not relabel the historical run.
