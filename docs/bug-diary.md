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


## WEB-ANALYSIS-001 — Configuration and provider/model mismatch

- Observed: 2026-11-06, read-only review and isolated reproduction.
- Cause: browser defaults overwrote environment settings; the wizard did not load server configuration or change models with the provider. An omitted endpoint erased the server endpoint.
- Repair: preserve omitted values, apply server locks, initialize the wizard from projected configuration and matching preferences, and load provider-specific model options. Include existing regional providers and identify key-optional local endpoints correctly.
- Coverage: REQ-WEB-001/013; `test_web_analysis_flow.py` configuration cases and frontend `analysis-flow.test.tsx`.

## WEB-ANALYSIS-002 — Reload loses reports and errors

- Cause: the snapshot omitted display state but advanced the cursor past all prior events; terminal pages reopened an empty SSE stream. Failure details were also omitted or not rendered.
- Repair: atomic complete display snapshots, bounded message history, expired-cursor snapshot fallback, terminal connection closure, and visible safe errors/correlation IDs.
- Coverage: REQ-WEB-007, INV-WEB-003; backend snapshot/failure cases and frontend store/page cases.

## WEB-ANALYSIS-003 — Startup failure strands the active slot

- Cause: artifact-writer construction ran outside the worker exception/finally boundary.
- Repair: handle artifact initialization failures, report a terminal storage error, and release the slot after worker cleanup. Correlate redacted diagnostics instead of silently discarding exceptions.
- Coverage: INV-WEB-009; `test_artifact_initialization_failure_releases_slot`.

## WEB-ANALYSIS-004 — Repeated runs mix old and new results

- Cause: all runs for a ticker/date shared the CLI artifact directory, and history inferred completion from a potentially stale final decision file.
- Repair: isolate each Web run and persist its lifecycle in an artifact sidecar. Keep legacy CLI artifacts unchanged and readable.
- Coverage: REQ-WEB-009, INV-WEB-001; `test_repeated_analysis_keeps_each_run_and_legacy_artifacts`.

## WEB-ANALYSIS-005 — Real execution lacks progress and resume status

- Cause: fake runners emitted progress that the real adapter did not; neither state machine handled `run.resumed`.
- Repair: publish real model/tool counters, infer agent progress from graph state, display preparation phases, and transition resumed tasks to running.
- Coverage: REQ-WEB-002/007; real-core integration and resumed-run cases.

All five repair groups are implemented. Verification results and outstanding live-validation limitations are recorded in `docs/architecture/evaluation-logbook.md`; final human review remains pending. Existing baseline defects above are unchanged.


## WEB-ANALYSIS-006 — Yahoo throttling mislabeled as a model-provider failure

- Reported: 2026-11-06. The user supplied the traceback for correlation `c_6c77fd7723f2`, using DeepSeek with `deepseek-flash` for both roles.
- Confirmed failure: `YFRateLimitError` from Yahoo Finance, through `get_stock_data` and `tools_market`, after the existing 2/4/8-second backoff retries. This traceback does not establish an LLM authentication or model-selection failure.
- Root cause of the misleading UI: the Web exception mapper assigned every unrecognized exception the generic provider-contact message. The core vendor router lets the raw Yahoo exception propagate when no configured fallback succeeds.
- Repair scope: map raw Yahoo throttling, typed market-data unavailability, missing data, and vendor configuration failures to safe distinct messages; use a neutral default for unknown execution failures. Preserve correlation logging and credential redaction.
- Regression: `test_real_market_tool_rate_limit_is_not_reported_as_llm_failure` uses the actual graph, ToolNode, market tool and vendor router, replacing only the model/identity/Yahoo boundaries. It verifies failure classification, no final decision/memory write, and retained checkpoint artifacts. Additional parameterized cases cover typed data errors and neutral internal failures.
- External condition: this presentation-layer repair does not remove Yahoo's rate limit or make unavailable data available. No automatic resubmission, extra provider retry, new data source, or fallback-vendor selection is introduced. The existing configured vendor chain remains authoritative.
- Status: error mapping repaired; actual Yahoo availability remains an external prerequisite for a successful Yahoo-backed run.
