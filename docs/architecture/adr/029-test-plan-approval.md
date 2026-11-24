# ADR-029: Auditable prior approval of test plans

- Status: plan and positive/negative cases approved by the human owner in the
  current conversation on 2026-11-24; implementation and hosted verification
  must be reported separately, without claiming final human acceptance.
- Scope: test-approval-v1, feature/fix from release ac47e1f.
- Requirements: NFR-GOV-001, NFR-SEC-001, NFR-VER-002; invariant INV-28.

## Context

The compatibility approval command currently issues a notice only. Native PR
merge reviews do not establish prior test approval. The user requested an
executable gate with a simple human operation and retained automation checks.

## Decision

Use a submitted PR review of type Comment, not an ordinary Conversation
comment and not a native Approve. The exact review body is:

```text
Test plan approved for commit <full 40-character SHA>.
Scope: <requirement or plan identifier>
```

The review's actual commit must equal the body SHA. Its author must be an allowed
User database ID from the base policy. The PR author may review AI-written tests
if allowlisted; no agent may submit the human decision. Review edits use the later
of submittedAt/updatedAt. Dismissed, malformed, unauthorized or revoked reviews
never authorize implementation. Existing submitted/edited/dismissed review
workflow events re-run checks; Conversation comments have no approval effect.

Validate every implementation commit, not only the final tree. Each must have an
earlier matching test/design review on an ancestor before that commit. Earlier
approved implementation may precede a later test-only revision: each implementation
epoch still needs its own prior matching evidence. An unrelated base-branch advance
does not invalidate reviews reachable through the PR ancestry. The final test/design snapshot
also needs a valid review, so a later test-only weakening cannot escape review.
Snapshots include Python fixtures, frontend tests/e2e/test setup/config, the
blueprint and a semantic requirements projection excluding verification/status
bookkeeping. Gate implementation is not misclassified as a test artifact.

Implementation includes production source, executable scripts, runtime prompts,
CI code, runtime/dependency configuration (including Docker and requirements.txt),
and substantive non-test Python configuration. Documentation-only or
pure test-preparation changes report NOT REQUIRED, never an approval claim.
Policy/checker removal is rejected. GitHub API errors, pagination truncation,
invalid data, stale PR heads and missing evidence fail closed.

The workflow exports the checker and its validator imports from the protected
PR base into a temporary directory, with isolated Python import paths. It does
not import candidate code while holding the review token. The token has only
contents/read and pull-requests/read. No new package or privileged PR trigger is
introduced. Human review of workflow changes remains necessary: an unmerged
workflow cannot attest its own integrity against every privileged edit.

## Initial installation

Only the exact known release ac47e1f07bcf13508be83b4f6276afc80cc449a5 may enter
an explicit BOOTSTRAP installation state. It is limited to this gate's named
source/test/config/design files and cannot alter runtime dependencies or business
files. The installation is governed by the authentic conversation plan/test
approval recorded in the review memo, followed by the maintainer's review before
publication/merge. It is NOT an automatically certified GitHub test-plan approval.
Any other missing base policy blocks. Once installed, candidate policy/checker
removal blocks and a candidate cannot authorize itself by changing reviewers.

## Alternatives

- Native Approve only: rejected; authors cannot approve their own PR and a final
  merge review does not prove test-plan chronology.
- Ordinary issue comments: rejected for v1; correct revocation needs additional
  event/head-status handling and privileged API writes.
- A local approved: true file: rejected; it has no independent reviewer/time.
- A single immutable test-only revision for the entire PR: rejected; it prevents
  legitimate later test-plan revisions after earlier approved work.

## Consequences and verification

The normal human action is reviewing tests, then submitting the two-line Comment
review before implementation. Changing tests/design requires reviewing that new
revision before subsequent implementation. Do not edit old approvals to backdate
new text; preserve them and submit a new review. Git committer times are audit
metadata, not proof of when private uncommitted editing began.

Offline Git fixtures and mocked GitHub metadata cover both acceptance and
violations; the workflow contract pins base-sourced execution and retained gates.
No real paid service or real human review is synthesized in tests. Hosted review
behavior remains NOT_RUN until a separately authorized publication exercises it.
Reopen this decision if platform review metadata changes or evidence shows a
chronology or classification escape. Failure fallback: block the PR, retain
existing history and request a genuine revised test-plan review; never forge it.
