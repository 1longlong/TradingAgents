# `test/live/` — pointer to opt-in live/integration tests

The course slide deck refers to a live test directory. This directory is a
pointer, not a second test tree; live checks, when present, live under
[`tests/`](../../tests/) and are gated by pytest markers. No source or test file
is copied or symlinked here.

## Rules for a live test

A live test is opt-in and must never run in the default suite or in CI:

1. **Marker.** Mark it `@pytest.mark.integration` (and `@pytest.mark.smoke` only
   if it is also a quick sanity check).
2. **Explicit skip.** Guard it with `pytest.mark.skipif` on the presence of the
   exact credential it needs, for example:

   ```python
   @pytest.mark.integration
   @pytest.mark.skipif(
       not os.environ.get("OPENAI_API_KEY"),
       reason="requires an explicitly provided OPENAI_API_KEY",
   )
   def test_live_provider_call():
       ...
   ```

3. **Explicit credentials.** The test must read a real key the operator supplied
   for that run. It must not read `.env`, a user's home configuration, or a key
   that happens to be present in the environment without being named.
4. **Explicit authorization.** A live run spends real provider quota. It needs a
   human authorization that names the run, provider, budget, and date. "The key
   is present" is not authorization.
5. **No CI.** Never add a live test to `.github/workflows/ci.yml`. CI runs the
   offline suite only and installs no real credential.

## Run a live test (only after authorization)

```bash
OPENAI_API_KEY=... pytest -q -m integration tests/
```

The default command remains:

```bash
pytest -q        # no network, no paid call
```

See [`test/offline/README.md`](../offline/README.md) for the offline suite and
[`docs/code-governance/verification-constraints.md`](../../docs/code-governance/verification-constraints.md)
for the evidence rules.
