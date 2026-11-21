# AGENTS.md — Coding-Agent Governance

This file governs every coding agent (human, OpenCode, Codex, DeepSeek Harness, or
any other AI assistant) that edits this repository. It is the first document an
agent must read before making any change, per the static startup prompt
(`Prompt.md` and `prompts/prompt_v1.3.yaml`).

## Governance history and effective dates

- The Release governance (this document's sections 1–13) was established on
  **2026-10-23** for the CS5351 feature work and the approved simulated-trading
  subsystem.
- The expanded rules imported from the personal token-observability submission
  (roles, frozen artifacts, independent-audit discipline, definition of done,
  enforcement-status table, reporting shape) were introduced on **2026-11-19**.
  They are **not** retroactive: they did not govern the October or early-November
  work, and no entry in `docs/ai-use-log.yaml` for earlier dates is judged against
  them.
- The D1/D2/D3 documentation integration is dated **2026-11-21**. It reconciles the
  two rule sets; it does not invent or backdate any human approval.

Repository layout (authoritative): the main-system source trees are `tradingagents/`
and `cli/`; canonical tests are `tests/`. The approved independent simulated-trading
subsystem really lives in `src/trading/` and `src/safety/`, with canonical tests in
`tests/trading/`. `src/` is therefore **not** a pointer-only directory. Only
`test/offline/` and `test/live/` are pointer READMEs after their code moved to
`tests/trading/`.

## 1. Read the repository instructions first

- Read `AGENTS.md`, `architecture-blueprint.md`, `docs/architecture/invariants.md`,
  and `docs/architecture/trace-matrix.md` before editing source or tests.
- Read every document under `docs/architecture/` (the ADR set, memory design,
  permission model, risk list, runtime-policy catalog, evaluation logbook/table)
  and every document under `docs/code-governance/` before editing governance,
  architecture, source, or tests.
- Read `pyproject.toml` for the toolchain (Ruff, pytest markers) and the
  `tests/` conventions in `conftest.py` before adding or changing tests.
- Read `docs/architecture/permission-model.md` (role × path deny-by-default
  matrix) and `docs/code-governance/verification-constraints.md` before editing.
- `Prompt.md` is the static startup prompt; `prompts/prompt_v1.3.yaml` is the
  current prompt export. `prompts/prompt_v1.0.yaml` and `prompts/prompt_v1.1.yaml`
  are archival exports only and are **not** runtime configuration.
- If a required document is missing, say so explicitly and stop before editing.
  Do not substitute a document from another branch.
- **Plan first, then STOP.** Before generating or editing any feature code,
  tests, specifications, or governance files, output a traceable execution plan
  containing: scope; exact files; interfaces/data contracts touched; tests that
  will prove the change (new and existing); risks, non-goals and rollback; the
  verification commands and where evidence will be stored. Wait for explicit
  human approval (see `Prompt.md`, `prompts/prompt_v1.3.yaml`). Test cases must be
  human-approved before implementation; a scope, safety, frozen-artifact, or
  test-plan change requires reapproval. Trivial read-only work (inspection, test
  execution, reporting) needs no plan but still follows the read-only rules.

## 2. Language

- All prompts, commit messages, review comments, and code comments MUST be in
  **English**. Non-English text is only permitted where it is itself the object
  of study (e.g. localization fixtures/translations), never for agent
  instructions or documentation narrative.

## 3. Preserve user changes

- Do **not** revert, reformat, or rewrite unrelated user-authored code.
- Do **not** mass-reformat files not touched by the task. Ruff formatting
  adoption is intentionally deferred (see `pyproject.toml`).
- If a change is required for the task, keep the diff as small as possible and
  clearly scoped.
- Weekly and per-task: re-check context and rule freshness. A stale context or a
  changed governing prompt version must be re-read before any edit.

## 4. No secrets

- Never read, print, copy, commit, or transmit API keys, tokens, or
  `Bearer`/`sk-` strings. If a `.env` file is needed, use `.env.example`
  placeholders only.
- Never write a real secret into any committed file. Real secrets stay in
  environment variables or `.env` (gitignored). `.env`, `.env.enterprise` and
  `.envrc` are gitignored; `.env.example`/`.env.enterprise.example` are
  placeholders.
- Scan new files for secrets before finishing, and inspect the final diff for an
  accidental secret (see `docs/code-governance/verification-constraints.md`).
- A missing usage or cost value is reported as missing/`null`, never as `0`.

## 5. No network or paid API without authorization

- Offline, deterministic, LLM-free execution is the default. Do not call
  external data vendors, LLM providers, or paid APIs unless the task
  explicitly authorizes it.
- Tests that require external services MUST be marked `@pytest.mark.integration`
  and are opt-in. The default `pytest -q` run must not require network access.
- A paid run needs an explicit, written human authorization that names the run,
  the provider, the budget and the date. The mere presence of a key is **not**
  authorization. Prefer `--dry-run` and the preflight gate before any spend; an
  uncapped run is still a spend and still needs authorization. The budget gate
  refuses capped overspend; it does not grant permission to spend.
- Missing usage or cost data is reported as missing/`null`, never as `0`.

## 6. Git operations require explicit approval

- Never `git commit`, `git push`, open a PR, create a merge commit, create or move
  a tag, or create a release unless the human explicitly and unambiguously asks
  for it. The default is to leave all work as uncommitted working-tree changes.
- Staging is a write and needs the approved path list. Never `git add .` or
  `git add -A` on a dirty worktree.
- Never force-push, rewrite history, rebase a shared branch, amend an
  already-pushed commit, move or delete a tag, or run `git reset --hard` on
  published work.
- Do not change branch protection, CI triggers, or release tags as part of a code
  change.
- Do not commit, push, or otherwise publish another contributor's work without
  that contributor's approval.

## 7. Use offline deterministic tests

- Run the offline deterministic suite before finishing a change: this is the
  project's verification of record (see `docs/architecture/evaluation-logbook.md`).
  The project command is
  `TZ=UTC PYTHONPATH=. .venv/bin/python -m pytest tests -q`.
- Report the exact command, working directory, commit, environment overrides,
  exit code, and the relevant output tail. Do not paste credentials.
- Do not claim a green full suite when known date-sensitive cache failures or a
  network-reachability-sensitive baseline failure remain. Record exact outcomes
  with the commands that produce them. Label an unrun check `NOT_RUN` and an
  unverified mechanism `NOT_VERIFIED`.
- No behaviour change may be merged on the strength of a structural check alone;
  use the three-tier model in `docs/code-governance/verification-constraints.md`
  (structural / regression / behavioral) and never relabel an offline PASS as
  live proof.

## 8. Maintain traceability (requirements, ADRs, invariants)

- Every new or changed requirement must be mapped in
  `docs/architecture/trace-matrix.md` to its design artifacts, source files, and
  tests.
- Assign and re-use stable requirement IDs in the existing families: `FR-DQG-*`,
  `FR-DDT-*`, `FR-TRD-*`, `FR-ANL-*`, `FR-OBS-*`, `FR-HAR-*`, `FR-CAM-*`,
  `INV-TRD-*`, and `NFR-*`. Do not reuse or reassign an ID out of band.
- Update the trace matrix in the same change that adds the requirement.
- A safety-critical change (gate/evaluator/output-guard/fail-closed/budget/
  permission/prompt semantics) additionally needs an ADR and explicit human
  approval before merge. ADR numbers are unique and must match their filename and
  H1 heading; invariant numbers are unique across the merged register. Never
  introduce a second decision under an existing ADR or invariant number.
- Requirement/invariant IDs must appear in the tests that verify them (module
  docstring, a comment, or the test name) so traceability is mechanically
  checkable.

## 9. Record AI use and reviews

- Record each AI-tool use and each human review in `docs/ai-use-log.yaml` and
  `docs/review-memo.md`. Note tool, scope, date, and outcome; never copy secrets.
- Use the actual coding application (OpenCode, Codex, DeepSeek Harness, …); do not
  record a model identifier as the application. Preserve uncertain authorship as
  unresolved rather than inferring it.
- At phase boundaries, record a human review decision.

## 10. Fail closed on missing evidence

- If evidence, a decision, a requirement ID, or a verification result is
  missing or unknown, do **not** invent it. Mark it `TODO` with an owner and an
  action, and record it in `docs/debt-register.md` and `docs/architecture/risk-list.md`.
- Documentation claims must match the tree. If a referenced path does not exist,
  fix the reference or record the gap; do not leave a dead link.

## 11. Human review at phase boundaries

- Each project phase (analysis, contract, implementation, verification) requires
  an explicit human review before proceeding. Record the outcome in
  `docs/review-memo.md`. Without a recorded review, do not claim a phase
  complete.
- Explicit approval is required, and must be recorded with scope and date, before:
  1. any paid/LLM/network run or benchmark;
  2. any commit, push, PR, merge, tag, or release;
  3. editing a frozen artifact or changing a registered spec;
  4. moving/duplicating source trees or changing package layout;
  5. adding/removing a runtime dependency or an MCP server;
  6. changing CI, permissions, hooks, or governance rules;
  7. destructive operations or anything that touches credentials;
  8. widening scope or changing acceptance criteria.
- Approval for one item never implies approval for another.

## 12. Scope discipline

- The delivered tree contains the Release Phase 1–3B feature work, the Phase 4A
  deterministic offline baseline comparison (completed and human-approved with
  limitations: WANG Yiwen 60536848, 2026-10-23), and the token-observability
  delivery (2026-10-20 → 2026-11-16, documented retrospectively as ADR-012–ADR-018
  and requirements `FR-ANL-*`/`FR-OBS-*`/`FR-HAR-*`/`FR-CAM-*`/`NFR-VER-*`).
- **Phase 4B** (live-provider benchmarking), **production threshold tuning**, and
  **unrequested features** remain prohibited by default. The token-observability
  delivery's paid 16-run campaigns ran under dated, run-specific human
  authorizations recorded in `docs/ai-use-log.yaml` (V2/V3, 2026-11-15/16). Those
  authorizations do not authorize a new benchmark, a different provider, or
  production threshold tuning. An uncapped run is still a spend.
- Do **not** revert approved work, add features not requested, duplicate or
  relocate source trees, or invent team decisions/approvals.
- Do exactly the approved task: no drive-by refactors, mass formatting, renames,
  or "while I was there" fixes. If the task cannot be completed without touching
  an out-of-scope file, stop and ask.

## 13. Simulated trading subsystem

- The simulated trading subsystem is an approved independent subsystem:
  `src/trading/**` and `src/safety/**` are its source trees.
- Its tests are canonical under `tests/trading/**`; the old `test/offline` and
  `test/live` code trees were migrated there and are now pointer READMEs.
- The subsystem is invoked after graph output. The main-system trees
  `tradingagents/**` and `cli/main.py` must not be modified **by subsystem work**
  (this is a boundary on the subsystem, not a freeze on the main-system feature
  work described in section 12).
- `src/safety/**` writes still require `human_approval` and an
  `architecture_decision`; the safety engine remains the only executor gateway.
  Only `src/safety/engine.py` may issue an execution authorization; no module
  outside it may import the executor.
- Trading requirement IDs use `FR-TRD-*`, `INV-TRD-*`, and `NFR-TRD-*` in the
  unified requirements registry.
- Real broker execution and unattended live trading remain out of scope. Do not
  claim live trading or broker execution is implemented.

## 14. Roles and authority boundaries

| Role | Who | Authority | Prohibited |
| --- | --- | --- | --- |
| Project owner / instructor | Course staff | Final authority on scope, submissions, frozen artifacts, exceptions | — |
| Human maintainer | Repository owner / student maintainer | Authorizes paid runs, git writes, scope changes, dependency changes, merges | Approving their own unreviewed evidence as independent |
| Coding agent | OpenCode, Codex, DeepSeek Harness, or another assistant | Read, plan, edit in scope, run offline verification, report evidence | Self-authorizing any action in this file; approving its own work |
| Audit agent | A separate read-only reviewer (human or AI) | Inspect, run tests, run read-only commands, record findings | Editing product code, tests, specs, history, or git state |
| CI | GitHub Actions | Run the offline suite, scoped lint, import smoke, validators | Inferring intent or granting waivers |

An agent's authority never exceeds the task it was given. "The tool allowed it" is
not authorization. When two roles are held by one person, the approval must still
be recorded as an explicit human decision with a date and scope. A coding agent may
not authorize its own paid run, git write, or scope change, and may not certify its
own work as an independent audit.

## 15. Frozen artifacts and human-only files

- Frozen once registered: the `token_benchmarks/**/specs/**` trees, the batch
  `MANIFEST.sha256` files, the V3 protocol documents
  (`EXPERIMENT_PROTOCOL_V3.md`, `CAND01_BATCH_2X2_PROTOCOL_V3.md`),
  `CONFIG_HASH_MANIFEST.csv`, memory baselines, and freeze/attestation records.
  Verify with the freeze scripts and hash manifests; never edit them by hand.
- Release tags `rc1`, `c3-final-freeze`, `c3-v3-final-freeze` and
  `cand01-v3-final-remediation` must not be moved or deleted.
- `.opencode/rules.md` is designated **HUMAN-ONLY** by the Release governance
  (`docs/architecture/permission-model.md`, `docs/code-governance/human-rules-proposal.md`).
  Agents must not edit it; propose text instead. `.opencode/permissions.jsonc`
  is likewise a frozen/human-only governance artifact under the Release rules.
- A D1/D2/D3 documentation integration authorized by the human does not
  retroactively attest that an earlier edit to a human-only file was performed by
  a human. Record any such historical edit as unresolved until the human confirms
  or corrects it.

## 16. Independent audit and read-only verification

- An audit agent may run tests, read files, run `git show`/`git diff`/`git status`,
  and compute hashes. It may **not** edit the tree, commit, push, or change tags.
- Audit findings are written to `docs/` (or the audit logs under
  `token_benchmarks/**/logs/`) with file:line references and the command used.
- If an audit needs a write to prove a point, it must request a separate
  authorized change instead.
- A delegated reviewer must be able to fail a candidate; a review that cannot fail
  is not a review.

## 17. Definition of done

A task is done only when all of the following hold:

- the diff is limited to the approved scope and contains no secrets;
- new/changed behavior has tests, and the relevant tests were run;
- the offline suite result is reported exactly, including known failures;
- lint status on touched files is reported (`ruff check <paths>`), with baseline
  debt distinguished from new findings;
- frozen artifacts and tags are untouched;
- referenced paths exist and documentation matches the tree;
- the final report states what was verified, what was not, and how to reproduce it
  (commands, cwd, commit, timestamps).

## 18. Enforcement status (honest)

Status vocabulary: `ENFORCED_BY_TOOL` (a checked-in script/test blocks the action),
`ENFORCED_BY_CI` (CI would fail the build), `DOCUMENTED_ONLY` (no mechanical check),
`NOT_VERIFIED` (a mechanism exists or is claimed but its loading/effectiveness was
not verified here). `ENFORCED_BY_CI` means the check would run; CI is not currently
green while unrelated documentation conflicts remain.

| # | Rule | Mechanism / evidence | Status |
| --- | --- | --- | --- |
| R1 | No force push, history rewrite, tag moves | no hook or branch protection verified | `DOCUMENTED_ONLY` |
| R2 | No commit/push/PR/merge without approval | no hook; review only | `DOCUMENTED_ONLY` |
| R3 | No paid/LLM run without authorization | `--dry-run`, preflight gate, budget gate exist but do not authorize | `DOCUMENTED_ONLY` for authorization; `PARTIALLY_ENFORCED` for spend gates when used |
| R4 | Frozen specs/manifests immutable | `scripts/c3_verify_final_freeze.py`, `MANIFEST.sha256`, freeze tests | `ENFORCED_BY_TOOL` |
| R5 | No secrets read/printed/committed | `.gitignore`; pattern scanners in both validators (listed artifacts only) | `PARTIALLY_ENFORCED` |
| R6 | Missing usage never becomes 0 | `tests/test_c3_final_freeze.py` usage-verdict tests; `scripts/token_benchmark.py` | `ENFORCED_BY_TOOL` |
| R7 | No fabricated results/evidence | human review; no mechanical detector | `DOCUMENTED_ONLY` |
| R8 | Tests run after changes | CI pytest job (currently red) | `ENFORCED_BY_CI` |
| R9 | Ruff clean on submission files | scoped `ruff check` job | `ENFORCED_BY_CI` |
| R10 | Offline tests, no live APIs | `tests/conftest.py` dummy keys and vendor blocks | `ENFORCED_BY_TOOL` |
| R11 | Scope discipline / plan first | review only | `DOCUMENTED_ONLY` |
| R12 | Source tree not relocated/duplicated | review plus `structural-constraints.md` | `DOCUMENTED_ONLY` |
| R13 | Required reading completed | review only | `DOCUMENTED_ONLY` |
| R14 | `.opencode/permissions.jsonc` loaded/enforced by OpenCode | file is project governance, not a known OpenCode config path; loading/rule matching unverified | `NOT_VERIFIED` |
| R15 | MCP servers stay absent/approved | no MCP config exists; review only | `DOCUMENTED_ONLY` |
| R16 | Required artifacts exist/parse; refs resolve | `validate_submission.py`, `validate_requirements.py` | `ENFORCED_BY_CI` (currently red on unrelated conflicts) |
| R17 | ADR numbers unique, H1 matches filename | `validate_submission.py::check_adrs` | `ENFORCED_BY_CI` |
| R18 | Invariant numbers unique; invariant→requirement refs resolve | no check exists | `NOT_ENFORCED` (recorded gap) |
| R19 | Host sandbox scope (outside the repo) | DeepSeek Harness `workspace-write` + approvals | `ENFORCED` at runtime, not reproducible from the tree |

**Do not claim** that `.opencode` rules or `.opencode/permissions.jsonc` technically
prevent edits, network access, or secret reads. They do not, on the evidence
available. DeepSeek Harness uses its own sandbox/permission mechanism and does not
inherit OpenCode's configuration.

## 19. Reporting and escalation

Report in this shape: scope → files → commands and results → known failures →
residual risks → approval requests. Escalate rather than guess when a credential, a
frozen artifact, a paid run, a git write, or a scope change is involved. Never claim
a result you did not observe: say `NOT_RUN` if a command was not run and
`NOT_VERIFIED` if a mechanism could not be verified.
