# test/live/ — deliverable mapping for live / vendor-dependent tests

The authoritative project slide lists `test/live/`. This inherited repository
uses the pytest `integration` marker (declared in `pyproject.toml`) for
tests that require external services. This `README` maps deliverable `test/live/`
onto the `@pytest.mark.integration` marker and documents that these tests are
**opt-in**.

## Rule: live tests are opt-in and never run by default

- The default `pytest -q` run must **not** require network access or a paid LLM.
- Any test that needs an external vendor/Live path MUST be marked
  `@pytest.mark.integration`.
- Live integration tests are **opt-in**: they are run explicitly and are not
  part of the default offline suite.

## Markers

Markers are declared in `pyproject.toml` (`[tool.pytest.ini_options]`):
`unit`, `integration`, `smoke`. The `conftest.py` registers/collects them.

## How live tests are selected to run (opt-in)

```bash
# Run only integration-marked tests (requires explicit authorization and
# reachable external services / credentials).
pytest -m integration

# Or run the whole suite explicitly including integration tests.
pytest -m "not unit"
```

> Invoking live tests requires explicit phase/invocation authorization and the
> relevant environment variables. Never hard-code credentials.

## Real-provider paths and mock coverage

The offline deterministic suite exercises the real-provider paths only through
mocks/stubs (see `docs/architecture/risk-list.md` RISK-003). Live, un-mocked
vendor calls are the province of `@pytest.mark.integration` tests, which are
not run in CI by default.

## Why this mapping exists (no duplicate test tree)

The inherited repository keeps all tests in `tests/`. There is no `test/` code
tree to relocate. This `README` documents the marker-based opt-in contract and
maps the slide deliverable `test/live/` onto the `@pytest.mark.integration`
marker.

## Governing constraints

- No network or paid API call without authorization
  (`docs/code-governance/verification-constraints.md`).
- No real secret in committed files; use `.env.example` placeholders.