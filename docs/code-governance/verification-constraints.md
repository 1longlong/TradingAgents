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

## Constraint: document-only changes

- Documentation/governance changes must still parse (JSON/JSONC/YAML) and pass
  `git diff --check`. They do not require the offline Python test suite unless
  they touch Python/behavior.