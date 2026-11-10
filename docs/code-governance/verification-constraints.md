# Verification Constraints

This document defines how code changes must be verified before finishing. It
applies to every agent and to human edits. The verification of record is the
offline deterministic suite (see `docs/architecture/evaluation-logbook.md`).

## Default verification procedure

1. **Read the governance docs first**: `AGENTS.md`,
   `architecture-blueprint.md`, `docs/architecture/invariants.md`,
   `docs/architecture/trace-matrix.md`, and `pyproject.toml`.
2. **Run the offline deterministic tests** that cover the change. The debate
   and gate tests must be included when the change touches the feature work.
3. **Run Ruff** (`ruff check .`) if Python source is modified. The repo's
   `pyproject.toml` selects a specific rule set; the whole-repo formatter
   adoption is intentionally deferred, so do **not** mass-format files.
4. **Validate the requirement/schema artifacts** if they changed
   (`scripts/validate/validate_requirements.py` against `docs/req/req-schema.json`).
5. **Update the trace matrix** (`docs/architecture/trace-matrix.md`) with any
   new/changed requirement ID in the same change.

## Constraint: networks and paid APIs

- The default `pytest -q` run must require **no** network and **no** paid LLM.
- Any test that needs a vendor/Live path MUST be marked `@pytest.mark.integration`
  and be opt-in. `test/live/README.md` documents this.

## Constraint: never claim a green suite dishonestly

- Do not claim a fully-green full suite when known date-sensitive cache failures
  or a network-reachability-dependent baseline failure remain.
- Record exact outcomes and the producing command in
  `docs/architecture/evaluation-logbook.md`.

## Constraint: secrets

- Never read, print, copy, commit, or transmit API keys, tokens, or
  `Bearer`/`sk-` strings.
- Never write a real secret into a committed file; use `.env.example`
  placeholders only.
- Before finishing, scan new/modified files for likely secrets without printing
  the secret values. The deterministic scan (`scripts/validate/scan_secrets.py`
  or equivalent) reports only the presence/location of a match, not its value.

## Constraint: fail closed on missing evidence

- If a required verification or decision is missing, mark it `TODO` with an
  owner/action and record it in `docs/debt-register.md` and
  `docs/architecture/risk-list.md`. Do not invent it.

## Constraint: human review at phase boundaries

- Each phase (analysis, contract, implementation, verification) requires an
  explicit recorded human review in `docs/review-memo.md` before proceeding.

## Constraint: every fit criterion has a test; negative tests required

- Every requirement's `fit_criterion` in `docs/req/requirements.yaml` MUST name a
  verification command/test that exists; a criterion with no real check is
  labelled `pending`, never claimed `verified`.
- Every feature/requirement change MUST add at least one **negative** test that
  pins the fail-closed / invariant-violating behavior (e.g. a malformed input
  that must be rejected, a future-dated record that must be dropped). A positive
  test alone is insufficient.
- Requirement/invariant IDs MUST appear in the tests that verify them (in the
  test module docstring, a comment, or the test name) so traceability is
  mechanically checkable.

## Constraint: three-tier verification model

A change is verified at up to three tiers, and the claim must state which tier
it is making. The three tiers are:

1. **Structural** — files parse, the schema validates, `ruff`, and
   `git diff --check`. This proves *shape*, not behavior.
2. **Regression** — the change does not break previously-passing behavior: the
   focused regressions plus the offline deterministic suite still pass on the
   covered path. This proves *no regression on the covered path*, not that new
   behavior is correct.
3. **Behavioral** — deterministic unit/integration tests demonstrate the new
   behavior itself on the covered (mocked/injected) path, including the required
   negative / fail-closed cases. This proves behavior on the covered path only.

A structural PASS is **never** reported as regression proof; a regression PASS is
**never** reported as behavioral proof; and none of the three tiers proves live
behavior (see the separate evidence axis below).

### Separate evidence axis: offline vs. live (NOT a tier)

**Offline vs. live is a separate evidence axis, never a substitute tier and never
a proof of live behavior.** Every command above runs offline and deterministically
(no network, no paid LLM). A **live / runtime** end-to-end run is a distinct
evidence source that sits on the `live` end of this axis: it is opt-in,
`@pytest.mark.integration`-marked, and separately authorized. Only a real live run
(the `live` end of the axis) can evidence live behavior; no structural, regression,
or behavioral *offline* PASS may be relabelled as live proof. Conversely, a live
run does not replace the offline tiers — both are reported, keep their own names,
and offline success is never claimed as live success.

In short: **tier** (Structural / Regression / Behavioral) describes *what kind*
of claim is being made; **axis** (offline / live) describes *where* the evidence
was collected. Do not conflate them.

## Constraint: document-only changes

- Documentation/governance changes must still parse (JSON/JSONC/YAML) and pass
  `git diff --check`. They do not require the offline Python test suite unless
  they touch Python/behavior.