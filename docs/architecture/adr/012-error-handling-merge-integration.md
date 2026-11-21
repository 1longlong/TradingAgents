# ADR-012: Integrate execution protection with evidence and usage accounting

Date: 2026-11-21
Status: Implementation plan approved in the repository user's chat; final
acceptance and another contributor's PR review remain pending.

## Context and authorized scope

PR #5 integrates `feature/error-handling` with release commit `24adf97`.
The user explicitly authorized conflict resolution, preservation of both
implementations, corresponding integration tests, offline regression, commit,
push and subsequent PR merge subject to repository checks. This is integration
maintenance, not authorization to change Gate thresholds, confidence policy,
discussion termination, trading safety rules, or live-provider behavior.

## Decisions

- Keep the release Gate, confidence sanitizer, debate evaluator, durable usage
  admission/settlement, trusted-output redaction and report artifacts.
- Keep bounded vendor retries, circuit breakers and context isolation. Record
  source failures for vendors actually invoked; local budget/breaker refusals
  are not fabricated operated source attempts. A final retry success remains a
  successful vendor call, not a final failed-source claim.
- Bind structured output with raw responses when supported. Settle the raw
  provider usage before parsing, local recovery, confidence sanitation or
  rendering. Retain full-precision typed confidence sanitation before rendering.
  Only genuine parser/validation misses permit at most one free-text attempt;
  provider, budget, refusal, truncation, sanitizer and renderer errors propagate.
  The optional fallback still requires a separate atomic admission.
- Persist collector evidence at governed tool-execute and sentiment-prefetch
  checkpoints, as well as the existing legacy tool/analyst boundaries. Count
  the single governed wrap-up as an analyst model invocation in the same ledger.
- Keep the release trusted report transformations, then atomically replace each
  existing Markdown report file. This does not make the report directory or the
  release's additional artifact files a single transaction.
- Use `run-identity/v2` for the integrated Gate/evaluator graph. Include the
  resolved debate configuration in the explicit execution identity so changing
  the effective debate policy cannot reuse an incompatible checkpoint. Preserve
  all old checkpoints on disk; no migration or deletion is performed.
- Keep the independent simulated-trading source unchanged. Its POSIX `fcntl`
  dependency prevents the complete test tree from collecting on Windows;
  Linux CI is required for that subsystem. Never replace its lock with a stub.

## Verification and traceability

Existing requirements: NFR-AUD-001, NFR-BUD-001, NFR-BC-001, NFR-OFF-001,
NFR-PIT-001 and FR-DQG-006. No new requirement or safety threshold is introduced.
`tests/test_merge_execution_boundaries.py` checks production graph wiring,
SQLite evidence persistence, wrap-up ledger events, and debate-policy checkpoint
isolation. Existing structured error/usage, confidence, output-guard, vendor,
governance, prefetch, report and checkpoint suites remain regression coverage.
Exact command results and platform limitations belong in the evaluation logbook.

## Limits

Offline mocks are not live-provider proof. A process crash before a node returns
may repeat unfinished work. The strict socket-denial harness also blocks the
Windows asyncio event loop's local socketpair setup; its complete Windows result
must not be reported as zero-attempt success. Final PR merge still requires
repository review/check requirements; no approval is authored on behalf of a
different contributor.
