# Live and external-service tests

External-service tests live here and require explicit network, credential and
cost authorization before execution. Offline runs must not be reported as live
verification. From the repository root, when separately authorized:

```bash
python -m pytest -q test/live
```

## Simulated-trading smoke test

After separate external-service and cost authorization, the imported three-day
simulated-execution smoke test is explicitly enabled with:

```bash
RUN_LIVE_TRADING_TESTS=1 python -m pytest -q test/live/trading -s
```

It remains opt-in and is not part of the default offline regression.
