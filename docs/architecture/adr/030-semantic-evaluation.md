# ADR-030: Fixed-set semantic evaluation with candidate-bound evidence

- Scope: submission-fix-v1, approved in the current conversation on 2026-11-24.
- Requirements: NFR-GOV-002, NFR-SEC-001, NFR-VER-002; invariant INV-29.
- No provider spend, business-rule change or final human acceptance is implied.

## Context

An empty semantic policy currently succeeds without evaluating a prompt/model
change. Output contract tests alone cannot establish a new model's quality.
The approved repair must fail closed without inventing measurements or calling
a paid provider. Prior test approval (ADR-029) remains a separate obligation.

## Decision

Configure a fixed JSON evaluation set and an offline evaluator in the existing
test tree. Each case specifies a factual task, expected rating/safety behavior,
required factual text and prohibited claims. Evaluate real candidate responses,
then replay blocked-output, rating and confidence controls from production code.
Quality is explicit: raw-response task accuracy and factual fidelity must each
be 1.0, complete case coverage is required, and safety escapes must be zero.
This is a small engineering acceptance set, not investment-return accuracy or
an assertion of general natural-language correctness.

Evidence must be a tracked JSON artifact named by the base policy. It binds the
exact dataset bytes and all relevant candidate prompt/model source bytes via
SHA-256. It names the provider, quick/deep models and real run provenance.
Missing/mismatched evidence, duplicate/missing cases, malformed responses,
nonfinite metrics, altered base evaluator/dataset and failed thresholds block.
The runner validates provenance fields, not whether a provider actually ran;
real run provenance still needs human review. Unit-test fixtures are explicitly
synthetic and are never installed as production evaluation evidence.

The workflow uses the protected-base checker/evaluator/policy and executes
candidate production code without review tokens or provider credentials.
Python sockets are disabled and dotenv loading is disabled. Unknown/empty
policies block relevant changes; unrelated documentation/tests report NOT
REQUIRED. Candidate edits cannot disable an existing base policy.

Installation is separate from activation: the fixed evaluator/dataset/policy
must first enter the base in a reviewed change without runtime prompt/model
changes. No bootstrap exception is added to ADR-029. The existing first-gate
installation must be published separately before this batch. This branch is
not automatically merge-ready merely because local tests pass.

## Alternatives

- Empty-policy success: rejected because no evaluation has occurred.
- Treat scripted responses as real model evidence: rejected as fabricated proof.
- Paid PR inference: rejected without explicit run/provider/budget approval.
- Candidate-owned evaluator: rejected because a PR could lower its own bar.

## Consequences

No paid evaluation is performed by this repair. Until authentic observations
exist, prompt/model-changing PRs correctly remain blocked. Deterministic tests
exercise accepted evidence and each failure boundary with synthetic provenance.
The small fixed set must be expanded through review when new behavior requires
coverage. Reopen if providers change output contracts or the set ceases to
represent the application. Failure fallback: retain the existing release,
publish the failed metric, and request genuine candidate evaluation evidence.
