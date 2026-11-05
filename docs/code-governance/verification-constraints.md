# Verification Constraints

## General Rules
- Every fit criterion must have at least one test.
- Every invariant must have at least one test that fails when the invariant is violated.
- Every test must reference the requirement or invariant ID it verifies.
- Every new round of work must run all previous test suites with zero regressions.

## Three-Tier Verification
1. Structural: Import boundaries, module boundaries, permissions.
2. Regression: All previous test suites must pass.
3. Behavioral: Quality thresholds, zero safety escapes, audit log integrity.

## Test Layout
- test/offline/: deterministic, no live network calls.
- test/live/: may call LLM or market data APIs.

## Required Negative Tests
- LLM decision violating a safety rule must be rejected.
- REJECT decision must not reach the executor.
- Attempt to modify audit log must fail.
- Attempt to bypass rule engine must fail.
