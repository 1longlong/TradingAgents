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
`test/offline/test_merge_execution_boundaries.py` checks production graph wiring,
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


## WebUI layout integration

The user requested updating local release and merging it into feature/webui,
including conflict resolution. Release 9a08e08 is imported into WebUI 977a22b.
The release source is mechanically mapped to src/tradingagents/ and its tests
to test/offline/ or the existing test/live/ location. No parallel root package
or test tree is restored. Core and CLI implementations remain identical to
release apart from the already-existing optional backtest progress observer.

Keep the v2 core execution identity and the existing Web custom-policy suffix;
a nondefault policy now changes both, and the tests verify both boundaries.
Keep release's DATA_UNAVAILABLE outcome for degradable data-vendor outages.
The actual Web graph test checks that Yahoo throttling is visible as tool data,
missing Gate evidence blocks a Buy to Hold, memory records Hold, and successful
completion clears checkpoint rows. Authentication/internal failures retain their
separate failure tests. These are merge compatibility checks, not new vendor,
Gate, model, trading or budget policies. Historical PR approval/verification
records above retain their original scope and do not approve this local merge.


## Authorized CI type/security repair

Scope: web-ci-types-security-20261121-v1. After the CI diagnosis and explicit
scope question, the user authorized repairing all type/security issues while
preserving business behavior. This covers existing core, CLI, simulated trading,
safety and WebUI source as necessary; it does not fabricate the separate GitHub
prior-test/safety/governance approvals or a base semantic evaluator.

Context: mypy reports 322 errors in 60 files and Bandit reports 10 medium/high
findings. Existing core logic is not replaced. Keep ratings, confidence caps,
evidence/time validation, usage budgets, execution authorizations, audit hashes,
checkpoint signatures, provider settings and retry behavior unchanged.

Decisions: express real optional/union values and heterogeneous SDK keyword
contracts; narrow already-validated values at their existing boundaries;
correct inaccurate return annotations and callback signatures; keep graph state
and runtime protocols explicit. Do not add ignore_errors, broad Any casts,
type-ignore/nosec exclusions, suppressions, dependency upgrades or disabled jobs.
SDK option dictionaries may use Any values because SDKs accept heterogeneous
provider-specific keyword values; their existing runtime validation remains.

Security: keep SHA1 conflict IDs byte-compatible and mark their non-security
purpose explicitly; replace fixed-name checkpoint SQL with literal statements;
assemble ledger placeholder clauses from fixed tokens only, binding every data
value separately. Rewrite the prompt's string assembly without changing its
rendered bytes. Add an HTTPS-only opener using existing urllib handlers that
validates the initial URL and redirects, preserving patchable transport seams.
In the existing Reddit fetcher, use an XMLParser/TreeBuilder that rejects all
DOCTYPE declarations before accepting untrusted XML. Preserve valid bounded
Atom feeds, predefined entities, response/error contracts and existing retries.
The shared HTTPS helper belongs in existing dataflows/utils.py. No new package,
framework, network service or dependency is introduced.

Prior test strategy: keep all existing regression/contract/safety tests; add
negative initial/redirect URL schemes and authorities, normal HTTPS behavior,
DTD/internal/external entity rejection and valid namespace/escaped feed data;
assert literal/parameterized SQL cannot broaden scopes with hostile IDs/phases;
assert stable conflict ID bytes. Run full mypy and Bandit over src, full Ruff,
registry validators, and then the complete socket-denied credential-free suite
plus frontend tests once changes are complete. Repeat only failed/affected
checks after repairs. No live provider, broker, user-state or credential access.

Consequences: source annotations become faithful to existing contracts; only
unsafe URL/XML inputs gain explicit rejection. No trading safety policy,
normal provider transport, business threshold or approval is relaxed. Actual
failures, checks and any remaining limitations are recorded separately.


Security implementation refinement: the installed defusedxml 0.7.1 provides the
standard hardened ElementTree API. Declare defusedxml>=0.7.1,<1 as a direct
runtime dependency (and in the existing requirements install path), using
forbid_dtd, forbid_entities and forbid_external. This replaces the proposed
stdlib custom parser, whose presence remains flagged by the complete security
scanner even with a rejecting TreeBuilder. No install/upgrade is needed in the
current environment. Explicit hardened parsing avoids suppressing B314 or
building another XML parser. The user-authorized complete security repair
covers this necessary dependency declaration; no separate release or platform
approval is inferred. Existing API/data semantics and tests stay authoritative.


## Simplify CI review and evaluation policy

Scope: web-ci-policy-simple-20261121-v1. The user explicitly asked to make the
two overly strict gates simpler after their failure modes were explained. This
authorizes a policy/test change, not fabricated historic approvals or quality
results. Existing implementation and business-safety acceptance remain unchanged.

Context: duplicated custom chronology/marker checks cannot recover approvals
that were never made on early test-only commits. Read-only GitHub inspection
confirms release already requires one approval, stale-review dismissal,
code-owner review and last-push approval with administrator enforcement. Remote
required-status contexts were empty at inspection; this change does not configure
branch protection or claim CI is remotely required. The empty semantic policy
has never supplied a reviewed evaluator, dataset or numeric thresholds.

Decisions:
- GitHub branch protection owns human merge reviews. Remove custom checks for
  prior test-only commit chronology and special review markers from CI; keep
  planning, authentic review records and required safety ADRs as human process.
  The approval CLI remains a compatibility notice only and never issues approval.
- Keep meaningful AI-use coverage as a blocking job, with a read-only content
  permission and no review API/token requirement. Keep all automatic regression,
  schema, structure, type, dependency and security checks and the aggregate.
- An absent/empty base semantic policy is optional: emit an explicit NOT RUN
  notice and exit zero without executing an evaluator or claiming evaluation
  passed. A partial/invalid policy still blocks. Once configured on the base,
  keep immutable evaluator/dataset, exact dataset coverage, credential filtering,
  socket isolation and quality thresholds; failures remain blocking. Do not
  introduce a continue-on-error flag, dummy evaluation or scope exemptions.

Allowlist: test/ci_gates.py, test/offline/test_ci_gates.py, existing workflow,
pyproject policy comment, AGENTS CI description, README and existing governance/
architecture/review/AI-use/evaluation/debt records. No product runtime, dependency
installation, permission widening, remote protection update or Git publication.

Test strategy: replace retired chronology/marker assertions with checks that
human review is delegated explicitly, no review API/token or automatic approval
is used, and the workflow retains meaningful AI logging and all aggregate
prerequisites. Test absent/empty policy produces NOT RUN without a subprocess;
malformed/partial policy fails; configured passing/failing thresholds, changed
fixtures and evaluator/report failures still block as appropriate. Run full
isolated regression once after edits plus Ruff/schema and scoped type checks.

Consequences: CI reflects executable automatic checks instead of impossible
historical metadata. Human merge review remains on GitHub and is not claimed by
a green CI result. Unconfigured evaluation is visibly unrun, not model-quality
proof. Prior recorded failures and approvals retain their historical truth.

## Required governance document layout

Governance-layout-v1 consolidates the gate and review specification in
verification-constraints.md and retains structural-constraints.md and
mcp-tool-manifest.md as the other code-governance artifacts. Roles and path
rights are specified by the existing permission-model.md and the actual
.opencode/permissions.jsonc configuration. Redundant inactive proposals do not
establish permission authority and are not required artifacts.

The validator and governance tests follow that ownership: require all three
retained documents and reject missing/empty required artifacts; check the actual
role policy rather than an inactive proposal. Effective permissions, prior-test
approval logic, semantic thresholds and business behavior remain unchanged.
Reopen if consolidation loses an active constraint or makes a mandatory check
optional. The fallback is to block verification and restore the missing contract
in its owning artifact, not to skip the failing check.
