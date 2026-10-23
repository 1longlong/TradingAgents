# Bug Diary

## BASELINE-001 — OHLCV cache freshness tests

- Observed: 2026-10-23, during source-layout verification.
- Symptoms: three cache-freshness tests fail in both the migrated checkout and untouched release in the same temporary Python environment.
- Reproduction: `python -m pytest -q test/offline/test_ohlcv_cache_freshness.py`.
- Failing cases: `test_current_day_cache_past_ttl_is_not_fresh`, `test_a_download_from_an_earlier_day_is_not_fresh`, and `test_load_ohlcv_refetches_stale_same_day_cache`.
- Classification: inherited baseline behavior or test/environment compatibility; root cause is not yet established.
- Fix: not attempted as part of environment/CI preparation. No production assertion or test threshold has been relaxed.
- Boundary exposed: freshness and point-in-time correctness; formal requirement/invariant IDs have not yet been assigned.
- Status: unresolved; remains a regression/merge blocker where reproduced.

## BASELINE-002 — Empty-download test performs a real reachability probe

- Observed: 2026-10-23, in both the migrated checkout and untouched release.
- Symptom: the test expects `NoMarketDataError`, while an unreachable Yahoo endpoint causes `VendorRateLimitError`.
- Reproduction: `python -m pytest -q test/live/test_no_data_handling.py`.
- Classification: test isolation/environment dependence. The download is mocked but the separate vendor-reachability probe is not.
- Root cause evidence: `raise_for_empty()` checks `vendor_reachable()` before deciding between outage and absent-data errors.
- Fix: not attempted; the file was placed under `test/live/` during migration. A subsequent dedicated change should test the two deterministic outcomes independently.
- Boundary exposed: distinguish vendor failure from absent market data; do not erase that distinction to satisfy the test.
- Status: unresolved. Network-isolated CI will report the problem rather than enabling real external access.

## Record format

For each significant bug, append the symptom, exact reproduction, classification, evidence-backed root cause, fix, affected requirement/invariant, verification, and status. Mark hypotheses as hypotheses; never invent a repair or approval.
