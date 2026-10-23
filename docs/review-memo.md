# Review Memo

## Preparation review — 2026-10-24

- Scope authorized by the user: development environment, document/permission workflow, transcript preservation, and repository CI blocking gates. At that stage, Git commits, pushes, merges, deployment, and product implementation were excluded.
- Source baseline: `release` at `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`; preparation branch: `feature/webui`.
- Existing migration and governance work is retained. No WebUI framework, product requirements, architecture decision, or quality threshold is invented.
- Implementation scope: developer dependencies/configuration, existing governance and record files, `test/ci_gates.py`, `test/offline/test_ci_gates.py`, and `.github/workflows/ci.yml`.
- Verification strategy: positive and negative gate tests; native configuration validation in a temporary project; actual schema/structure checks; lint, full-source type checks, dependency checks, and network-isolated regression. Do not turn baseline failures into passes.
- Plan/test approval evidence: the current conversation authorizes this preparation task. It is not a GitHub `[test-plan-approved]`, `[safety-approved]`, or `[governance-approved]` review, and it must not be represented as one.
- Human review status: pending. No final human verdict has been issued.

## Per-pull-request record format

For each real PR, append its URL, base/head commits, reviewer identity, review time, and scope. Cover requirements and architecture alignment, code and test quality, security, efficiency, operational metadata, actual commands/results, exceptions, and unresolved blockers. Record the actual human verdict: `APPROVE`, `CHANGES REQUIRED`, or `REJECT`. An agent recommendation must be identified separately.

## GitHub review protocol

Use a tests/design-only PR commit before product implementation. After reviewing the exact tests, requirements, and nonempty blueprint, a human collaborator with write/maintain/admin permission submits a `COMMENTED` review containing an explicit `[test-plan-approved]` decision. This dedicated test-plan decision is separate from merge approval and survives automatic dismissal of stale code approvals. An undismissed `APPROVED` review with the marker also qualifies, but is unsuitable for durable plan evidence when stale-review dismissal is enabled. Preserve that commit in history. Product implementation commits follow the plan decision; the bound tests, requirements, and blueprint must remain unchanged. A changed test/plan needs a new approved test-only revision before dependent implementation. Remove the marker to revoke the plan decision; dismissed reviews do not qualify.

For safety-relevant changes, update an ADR with `Context`, `Decision`, and `Consequences`, then obtain a human `[safety-approved]` approval on the final head. Changes to CI, permission/rule files, gate code, schema, or developer configuration need `[governance-approved]` on the final head. One real approval may contain both markers when the reviewer has assessed both scopes. Self-approval and bots do not qualify; an outstanding trusted request for changes blocks.

The gate verifies Git ancestry, exact reviewed content, server review records, and recorded commit chronology. It cannot prove when private or uncommitted coding began; Git timestamps and editable review bodies are not tamper-proof attestations. Trusted reviewers must submit plan markers before implementation rather than adding them retrospectively. Human oversight and protected branches remain necessary. Do not forge timestamps or review markers.

## First CI adoption

The existing base branch does not contain these new checks. Their first introduction requires explicit human inspection of the workflow and checker themselves. Subsequent changes are also protected by current-head governance review. This repository cannot protect its own unmerged workflow from every hostile edit; require the stable `blocking-gate` check and human review through GitHub rulesets/branch protection before relying on enforcement.

## Local verification evidence — 2026-10-24

- Environment used for these historical checks: Python 3.12.14 in an ignored `.venv`, subsequently removed during cleanup.
- Gate tests: 42 passed with real network disabled. Ruff, dependency consistency, permissions, and structural checks passed.
- Complete regression with Python sockets disabled: 984 passed, 4 inherited failures, 2 skipped, 88 subtests passed.
- Full-source mypy: 202 errors in 27 files (84 source files checked). These existing application findings were not suppressed or repaired by this preparation change.
- Bandit at medium severity and above: 5 findings; these require human triage, not an assumption that every result is exploitable.
- Schema gate correctly blocks the empty requirements registry. No product requirements were invented.
- Workflow syntax/expressions passed actionlint 1.7.12. Native OpenCode accepted the configuration and all four roles in a temporary project. A freshly built wheel installed into a clean temporary environment, imported outside the repository, and retained the CLI resource and working help command.
- Dependency audit passed for 122 exact installed third-party versions; only this local application was excluded. No other editable dependencies are accepted.
- Hosted workflow, real reviewer approvals, and live model/data API behavior have not been exercised by these local checks.
- Read-only GitHub inspection: default branch `release`, repository public, current account has admin permission, no rulesets. Existing release protection enforces admins, one human review, stale-review dismissal, last-push approval, and code-owner review; required-status-check contexts are empty. Remote settings have not been modified.

## Cleanup and commit authorization — 2026-10-24

- The user explicitly requested cleanup of generated intermediate files and caches, followed by one Git commit, and instructed that this preparation work does not need further tests.
- Removed local virtual environments, Python and tool caches, editable-install metadata, temporary build outputs, and task-specific temporary reports. Removed the verbose dependency inventory from this memo; the concise historical results above remain historical evidence.
- Retained source and CI implementation files, existing tests, governance documents, and intentional empty requirements/design placeholders. Preserved the existing deletion of `CHANGELOG.md` and removed its stale references.
- No tests were run for this cleanup. No new passing-check or human-review verdict is claimed. Commit authorization does not imply final governance approval.
- Push, merge, deployment, product development, and remote repository settings remain outside this cleanup scope.
