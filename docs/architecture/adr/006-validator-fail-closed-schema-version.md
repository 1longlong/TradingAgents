# ADR-006 — Governance validator fail-closed schema-version repair (subset fallback)

- **Status:** **APPROVED (scoped maintenance; plan and test cases approved)**
- **Date:** 2026-11-11
- **Deciders:** CS5351 project (student WANG Yiwen, 60536848); Builder agent
  implementation. The human **explicitly approved this round's repair plan AND
  test cases** in the controlling conversation on 2026-11-11. That approval is a
  plan/test authorization for the scoped CI/baseline repair; it is **NOT** a human
  acceptance or completion approval of the implemented change, which remains
  pending independent verification and later human review.
- **Trace:** `NFR-OFF-001`, `NFR-DET-001`; related invariant `INV-9`.
- **Related debt / risk:** `DEBT-034`, `RISK-030`.

## Context

CI run 42946358949 (PR #2, all four Python jobs at 3.10/3.11/3.12/3.13)
failed the **same** test:
`tests/test_governance_scaffold.py::TestDispatcherAgainstRealSchema::test_real_schema_rejects_bad_schema_version`
(1 failed, 1820 passed, 7 skipped). The Python test jobs do **not** install the
optional `jsonschema` package, so `validate_against_schema` falls back to the
deterministic subset validator in `scripts/validate/validate_requirements.py`.
The governance job **does** install `jsonschema` and passes.

The real schema constrains `project.schema_version` with the pattern
`^v[0-9]+\.[0-9]+$`. The subset fallback checked `schema_version` only as a
**non-empty string**, so the value `"1.0"` (which the real schema rejects) was
accepted. A forced-fallback mutation against the real registry reproduced
`errors=[]` — the fail-closed guarantee held on the real-schema path but was
silently weaker on the fallback path the CI Python jobs actually run.

## Decision

Repair the subset fallback so it enforces the `project.schema_version` pattern
that the **real schema declares**, rather than a hardcoded version or a bare
non-emptiness check:

- `_schema_string_pattern(schema, *path)` reads the `pattern` at
  `properties.project.properties.schema_version.pattern` from the supplied
  schema. The fallback uses `re.fullmatch(pattern, value)` and reports an error
  when it does not match.
- When the schema omits the pattern (e.g. a minimal `{"type": "object"}` schema),
  the fallback requires only a non-empty string and invents **no** stricter rule,
  so minimal-schema compatibility is preserved.
- Non-string and missing `schema_version` values remain rejected by the existing
  non-empty check.
- The subset fallback remains a **subset**: it is explicitly **not** a general
  JSON Schema implementation, and this ADR does not claim it is. Its documented
  fit-criterion limitations are unchanged; only the `schema_version` pattern fit
  is added, read from the actual schema.

The fix does **not** skip, weaken, or delete the failing test; it does **not**
edit dependencies, `pyproject.toml`, or `.github/**` to hide the failure. The
product code under test (`tradingagents/**`) is unchanged.

## Consequences

- The fallback and the real-schema path now **agree** on `schema_version`: both
  reject `"1.0"`, `"v1"`, `"v1.0.0"`, and other non-matching values, and both
  accept `vN.M`.
- A locally installed `jsonschema` can no longer hide the CI path: the new tests
  force the fallback by making `importlib.util.find_spec` report no `jsonschema`
  (exactly what `_detect_jsonschema` consults), and an isolated in-process
  blocker runs the entire governance module down the no-jsonschema path.
- No permission is expanded; no production behaviour changes; no runtime feature
  is added. This is a fail-closed correctness repair of a validation helper.

## Verification (offline, this change)

- Focused: `tests/test_governance_scaffold.py` (real + forced-fallback version
  acceptance/rejection, malformed/missing/non-string rejection, minimal-schema
  compatibility, real-jsonschema path when available).
- Full governance module under a faithful no-`jsonschema` simulation
  (`find_spec("jsonschema") -> None`): 52 passed, 6 skipped (the pre-existing
  real-schema branches).
- Full strict-offline suite and `scripts/validate/validate_requirements.py`
  (both with and without `jsonschema`) pass. Exact counts are recorded in
  `docs/architecture/evaluation-logbook.md`.
