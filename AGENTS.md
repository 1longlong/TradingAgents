# AGENTS.md — Coding-Agent Governance (CS5351 / TradingAgents)

Status: **established 2026-11-19** for the CS5351 final-submission tree (branch
`fix/cs5351-final-submission`, base commit `50b2ca3`). This is a governance
document written now; it is not a historical record of how earlier commits were
produced.

This file is normative for every coding agent — human-driven or AI (OpenCode,
Codex, or any other assistant) — that edits this repository. `MUST`, `MUST NOT`,
`SHOULD`, and `MAY` are used in the RFC 2119 sense. A rule marked
`DOCUMENTED_ONLY` is not mechanically enforced; see §14 before relying on it.

## 1. Roles and authority boundaries

| Role | Who | Authority | Prohibited |
| --- | --- | --- | --- |
| Project owner / instructor | Course staff | Final authority on scope, submissions, frozen artifacts, and exceptions | — |
| Human maintainer | Repository owner / student maintainer | Authorizes paid runs, git writes, scope changes, dependency changes, and merges | Approving their own unreviewed evidence as independent |
| Coding agent | OpenCode, Codex, or another AI assistant | Reads, plans, edits in-scope files, runs offline verification, reports evidence | Self-authorizing any action in §12; approving its own work |
| Audit agent | A separate read-only reviewer (human or AI) | Inspects, runs tests and read-only commands, records findings | Editing product code, tests, specs, history, or git state |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | Runs `pytest -q`, a scoped ruff lint of the submission files, a clean-install import smoke test, and the offline submission validator | Inferring intent or granting waivers |

An agent's authority never exceeds the task it was given. "The tool allowed it"
is not authorization. When two roles are held by one person, the approval must
still be recorded as an explicit human decision with a date and scope.

## 2. Required reading (in order)

Before the first edit, read:

1. this file (`AGENTS.md`);
2. `architecture-blueprint.md` (root) — system boundaries and the CAND-01 design;
3. every file under `docs/architecture/` — invariants, trace matrix, memory
   design, permission model, risk list, and the ADR set;
4. `docs/code-governance/structural-constraints.md`,
   `docs/code-governance/verification-constraints.md`, and
   `docs/code-governance/mcp-tool-manifest.md`;
5. `Prompt.md` (static startup prompt) and the archival prompt exports
   `prompts/prompt_v1.0.yaml` and `prompts/prompt_v1.1.yaml` (archive only — not
   runtime configuration);
6. `pyproject.toml` and `tests/conftest.py` for the toolchain and the offline
   test guards.

If a required document is missing, say so explicitly and stop before editing.
Do not silently substitute an upstream README or a document from another branch.

## 3. Plan first, then implement

Before changing code, tests, specs, or governance files, post a plan containing:

- the task and the exact files in scope;
- interfaces and data contracts touched;
- the tests that will prove the change (new and existing);
- risks, non-goals, and rollback;
- the verification commands that will be run and where evidence will be stored.

Wait for explicit human approval of the plan before implementation. A change to
scope, safety behavior, a frozen artifact, or the test plan requires re-approval.
Trivial read-only work (inspection, test execution, reporting) does not require a
plan, but still follows the read-only rules in §11.

## 4. Allowed actions

- Read any tracked repository file **except** credential material (§7).
- Run offline, deterministic checks: `pytest`, `ruff`, Python one-liners, and
  read-only inspection commands.
- Edit only the files named in the approved plan; keep the diff minimal.
- Add or strengthen tests for behavior that actually changed.
- Use read-only git commands (`git status`, `git log`, `git show`, `git diff`).
- Run dry-run/preflight tooling (`--dry-run`, `scripts/c3_preflight_gate.py`,
  `scripts/token_benchmark.py validate`) without contacting providers.
- Record evidence under `docs/` or the relevant
  `token_benchmarks/**/logs/` directory, without secrets.

## 5. Forbidden actions

- Running a paid LLM, vendor, or benchmark pipeline without explicit written
  authorization for that run (see §8).
- Editing, regenerating, or reformatting frozen artifacts: the registered
  `specs/`, `MANIFEST.sha256`, protocol/freeze records, memory baselines, or
  release tags (§11).
- Force-pushing, rewriting history, rebasing shared branches, deleting or moving
  tags, or `git reset --hard` on published work (§10).
- Reading, printing, copying, committing, or transmitting credentials: `.env`,
  `.env.enterprise`, API keys, tokens, `Bearer`/`sk-` strings, or private keys.
- Committing, pushing, opening a PR, or creating a release without explicit
  approval.
- Fabricating or "repairing" test results, logs, hashes, metrics, or usage
  numbers. Missing usage stays missing; it never becomes `0`.
- Deleting, skipping, or `xfail`-ing tests to obtain a green run.
- Modifying tests to match a bug, or editing frozen specs to match generated
  output.
- Moving or duplicating the source tree (`tradingagents/`, `cli/`, `tests/`)
  without instructor approval; see
  `docs/code-governance/structural-constraints.md`.
- Adding a network or LLM dependency, an MCP server, or a new runtime dependency
  without approval.
- Destructive shell operations (`rm -rf` outside build temp dirs, `sudo`,
  `chmod`/`chown` on repository roots, `dd`, disk formatting), or editing `.git/`
  internals.
- Disabling, bypassing, or weakening CI, hooks, or governance checks.

## 6. Scope discipline

- Do exactly the approved task. No drive-by refactors, mass formatting, renames,
  or "while I was there" fixes.
- Preserve user-authored changes. If the working tree is dirty, inspect the diff
  first and never revert work you did not create.
- If the task cannot be completed without touching an out-of-scope file, stop and
  ask. Do not silently widen scope.
- Documentation claims must match the tree. If a referenced path does not exist,
  fix the reference or record the gap; do not leave a dead link.

## 7. Credentials and secrets

- Use `.env.example` and `.env.enterprise.example` placeholders only.
- Never read or print `.env`, `.env.enterprise`, shell history, key files, or
  environment dumps. If a value is needed for a test, use a dummy placeholder.
- Never write a real secret into a tracked file, a log, a prompt, or an evidence
  artifact.
- Before finishing, inspect the diff for accidental secrets and redact them.
- `.gitignore` covers `.env`, `.envrc`, `.venv`, and `.env.enterprise`, but this
  is not a scanner and does not prevent `git add -f`. Review is mandatory.

## 8. Network, LLMs, and paid pipelines

- The default is offline and deterministic. Tests must not require network or a
  real API key; `tests/conftest.py` installs dummy keys and blocks live news
  vendors, and live tests carry `@pytest.mark.integration`.
- No paid pipeline, live benchmark, or vendor call may run without an explicit
  human authorization that names the run, the provider, the budget, and the
  date. "The key is present" is not authorization.
- Prefer `--dry-run`, the preflight gate, and schema validation before any
  authorized spend. The budget gate refuses capped overspend; an uncapped run is
  still a spend and still needs authorization.
- Missing usage or cost data is reported as missing/`null`, never as `0`.

## 9. Tests and evidence

- Every behavior change needs a test that fails without the change. Bug fixes
  need a regression test.
- Run the offline suite after changes. Minimum gate:
  `TZ=UTC PYTHONPATH=. .venv/bin/python -m pytest tests -q`.
- Report the exact command, working directory, commit, environment overrides,
  exit code, and the relevant tail of the output. Do not paste credentials.
- Known failures must be named, with cause and evidence; a run with known
  failures is not reported as "all tests pass". See
  `docs/code-governance/verification-constraints.md`.
- Audits are read-only. An audit agent may run tests and read files, but may not
  edit the tree or git state.
- Never claim a result you did not observe. If a command was not run, say
  `NOT_RUN`; if it could not be verified, say `NOT_VERIFIED`.

## 10. Git rules

- No `git push --force` / `--force-with-lease`, no history rewrite, no
  `git rebase` of shared branches, no tag moves or deletions, no
  `git reset --hard` on published work.
- Never rewrite or amend commits that are already pushed.
- No commit, push, PR, merge, or release without explicit human approval.
- The default is to leave work uncommitted. If asked to commit, stage only the
  approved paths and write an English, scoped message.
- Do not change branch protection, CI triggers, or release tags as part of a code
  change.

## 11. Frozen artifacts

The following are immutable once registered: the CAND-01 `specs/` trees,
`MANIFEST.sha256`, `CONFIG_HASH_MANIFEST.csv`,
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/EXPERIMENT_PROTOCOL_V3.md`,
`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`,
memory baselines, freeze/attestation records,
and the tags `rc1`, `c3-final-freeze`, `c3-v3-final-freeze`, and
`cand01-v3-final-remediation`. To change a frozen artifact, stop: it requires a
new protocol version, a documented ADR/exception, and instructor approval.
Verification uses the freeze scripts and hash manifests, never manual edits.

## 12. Human approval points

Explicit approval is required, and must be recorded with scope and date, before:

1. any paid/LLM/network run or benchmark;
2. any commit, push, PR, merge, tag, or release;
3. editing a frozen artifact or changing a registered spec;
4. moving/duplicating source trees or changing package layout;
5. adding/removing a runtime dependency or an MCP server;
6. changing CI, permissions, hooks, or governance rules;
7. destructive operations or anything that touches credentials;
8. widening scope or changing acceptance criteria.

Approval for one item never implies approval for another.

## 13. Definition of Done

A task is done only when all of the following hold:

- the diff is limited to the approved scope and contains no secrets;
- new/changed behavior has tests, and the relevant tests were run;
- the offline suite result is reported exactly, including known failures;
- lint status on touched files is reported (`ruff check <paths>`), with baseline
  debt distinguished from new findings;
- frozen artifacts and tags are untouched;
- referenced paths exist and documentation matches the tree;
- the final report states what was verified, what was not, and how to reproduce
  it (commands, cwd, commit, timestamps).

## 14. Enforcement status

Status vocabulary:

- `ENFORCED_BY_TOOL` — a checked-in script/test blocks the action.
- `ENFORCED_BY_CI` — `.github/workflows/ci.yml` would fail the build.
- `DOCUMENTED_ONLY` — no mechanical check; review and discipline only.
- `NOT_VERIFIED` — the mechanism exists or is claimed, but loading/effectiveness
  was not verified in this environment.

| # | Rule | Mechanism / evidence | Status |
| --- | --- | --- | --- |
| R1 | No force push, history rewrite, tag moves | No hook or branch protection verified; review only | `DOCUMENTED_ONLY` |
| R2 | No commit/push/PR without approval | No hook; review only | `DOCUMENTED_ONLY` |
| R3 | No paid/LLM run without authorization | `--dry-run`, preflight gate, budget gate exist but do not authorize; no hard block | `DOCUMENTED_ONLY` |
| R4 | Frozen specs/manifests immutable | `scripts/c3_verify_protocol_freeze.py`, `MANIFEST.sha256`, freeze tests | `ENFORCED_BY_TOOL` |
| R5 | No secrets read/printed/committed | `.gitignore` covers `.env*`; the submission validator scans new docs for obvious secrets; no full-history scanner; review only | `DOCUMENTED_ONLY` |
| R6 | Missing usage never becomes 0 | `tests/test_c3_final_freeze.py` usage-verdict tests; `scripts/token_benchmark.py` | `ENFORCED_BY_CI` |
| R7 | No fabricated results/evidence | Human review; no mechanical detector | `DOCUMENTED_ONLY` |
| R8 | Tests run after changes | `pytest -q` job in CI; local runs are self-reported | `ENFORCED_BY_CI` |
| R9 | Ruff clean on submission files | `ruff check` on the files this submission adds/changes (CI job, green). The whole-repo baseline (233 findings under ruff 0.17.1 on 2026-11-19 22:45 HKT) is tracked as DEBT-010 and is NOT gated | `ENFORCED_BY_CI` |
| R10 | Offline tests, no live APIs | `tests/conftest.py` dummy keys and vendor blocks; integration markers | `ENFORCED_BY_TOOL` |
| R11 | Scope discipline / plan first | Review only | `DOCUMENTED_ONLY` |
| R12 | Source tree not relocated/duplicated | Review plus `docs/code-governance/structural-constraints.md` checks | `DOCUMENTED_ONLY` |
| R13 | Required reading completed | Review only | `DOCUMENTED_ONLY` |
| R14 | Edit/bash/webfetch restrictions in `.opencode/permissions.jsonc` | File is a project artifact; JSONC syntax is checked by the validator, but OpenCode auto-loading and exact matching are not verified | `NOT_VERIFIED` |
| R15 | MCP servers stay absent/approved | No MCP config exists; review only | `DOCUMENTED_ONLY` |
| R16 | Required artifacts exist and parse; referenced requirement/trace paths resolve | `scripts/validate/validate_submission.py` course-compliance job in CI | `ENFORCED_BY_CI` |

CI exists but its current result is not green (see
`docs/code-governance/verification-constraints.md` §6). `ENFORCED_BY_CI` means
the check would run, not that it currently passes.

## 15. Reporting and escalation

Report in this shape: scope → files → commands and results → known failures →
residual risks → approval requests. Escalate rather than guess when a credential,
a frozen artifact, a paid run, a git write, or a scope change is involved. The
static startup prompt is `Prompt.md`; the prompt files in `prompts/` are
archival exports of hardcoded runtime prompts, not configuration this repository
loads.
