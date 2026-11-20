# test/live/ — moved

The simulated trading subsystem's opt-in live smoke test now lives at
`tests/trading/live/`.

Run it only with explicit opt-in:

```bash
RUN_LIVE_TRADING_TESTS=1 pytest tests/trading/live -q -s
```

This directory is retained only as a pointer; it contains no test code.
