# Permission Model

This document defines what each automated actor role is and is not permitted to
do in this repository, **per path, deny by default**. It is the prose authority.
The machine-readable artifacts are:
- the on-disk `.opencode/permissions.jsonc` (broad `read`/`edit` allows;
  **unchanged this turn**). Its mere existence is **NOT** proof it is the
  loaded/enforced configuration — that is **UNVERIFIED**.
- a **PROPOSAL** in `docs/code-governance/agent-permissions-proposal.yaml`
  (role-by-path deny-by-default whitelist) that is **NOT active configuration**.

> **Honest status:** JSON that parses is not proof that the installed OpenCode
> version loads and enforces it. Actual runtime enforcement is **UNVERIFIED**
> (RISK-006 / DEBT-004). See the enforcement-test protocol at the end.

## Roles

| Role | Purpose | Authority |
| --- | --- | --- |
| **Human** (WANG Yiwen, 60536848) | Ultimate authority | All approvals, safety, git, network, scope, and human-only files |
| **Planner** | Produce a traceable plan; read-only otherwise | Read + **read-only** execute (inspect); **no** edit and **no** mutating execute |
| **Builder** | Implement an approved, in-scope change | Edit within the whitelisted editable paths only |
| **Verifier** | Run offline checks and record evidence | Execute offline read-only checks; **no** source edit |

The agent is prevented from holding more than one role's edit authority at a
time without records; it must not self-grant a role.

## Deny-by-default role × capability matrix

Legend: R = read, E = edit/write, X = execute. Blank = **denied**.

| Path / capability | Human | Planner | Builder | Verifier |
| --- | --- | --- | --- | --- |
| `tradingagents/**` (source) | R E X | R | R E (approved scope only) | R X (offline tests) |
| `cli/**` (source) | R E X | R | R E (approved scope only) | R X |
| `tests/**` (tests) | R E X | R | R E **only when the plan+test cases were human-approved first** | R X (run only) |
| `docs/**` (governance) | R E X | R | R E | R |
| `scripts/validate/**` (validator) | R E X | R | R E (in-scope maintenance) | R X (run only) |
| `docs/req/**`, `docs/architecture/**` | R E X | R | R E (in the same change as the requirement) | R |
| `adr/**`, `architecture-blueprint.md` | R E X | R | R E (with ADR + human approval for safety changes) | R |
| `README.md`, `Report.md` (root docs) | R E X | R | R E **only under an explicitly scoped approval that includes root-doc sync** (document the change truthfully; never expand scope) | R |
| `AGENTS.md`, `.agent/rules.md`, `Prompt.md`, `prompts/**` | R E X | R | R E (ADR + human approval; new versioned file for prompt changes) | R |
| `.opencode/permissions.jsonc` | R E X | R | **denied** (human-approved change only; not self-edited) | R |
| `.opencode/rules.md` (**HUMAN-ONLY**) | R E X | R | **denied** | R |
| `.github/**` (CI) | R E X | R | **denied** (human-approved change only) | R |
| `pyproject.toml`, dependency files | R E X | R | **denied** (human-approved change only) | R |
| `.env`, `.env.*`, `*.pem`, `*.key` (**secrets**) | (human only) | **denied** | **denied** | **denied** |
| Paths outside the repository | Human | **denied** | **denied** | **denied** |
| Execute: `pytest`, `ruff`, validators, `git diff/status`, read-only inspection | Human | X | X | X |
| Execute: `git commit/push/tag/rebase/reset`, PR, release | Human (X) | **denied** | **denied** (human approval required per action) | **denied** |
| Execute: network / paid API / live LLM | Human (only if authorized) | **denied** | **denied** (explicit human approval + integration marker) | **denied** |

Rules:

- **Everything not whitelisted is denied.** There is no implicit read/edit of the
  filesystem or of the environment.
- **Frozen / human-only areas** (`.opencode/rules.md`, `.opencode/permissions.jsonc`,
  `.github/**`, dependency files, secrets, outside-repo paths) may only change
  under an explicit human action; an agent proposes, never applies.
- **Scope reapproval:** changing scope, safety semantics, or the approved plan
  requires reapproval; a Builder may not widen its own editable set.
- **Read-before-edit:** every editable path must also be readable by the same
  role (a Builder cannot edit a path it may not read), excluding human-only/frozen
  paths which no agent may edit. Root `README.md`/`Report.md` are readable by all
  roles and are Builder-editable only under an explicitly scoped approval that
  includes root-doc sync (e.g. the 2026-11-10 approved plan); the check is
  process-enforced (the schema cannot express it).

## Approval gates for privileged actions

| Action | Required before proceeding |
| --- | --- |
| Edit `tests/**` or any feature code | Human-approved execution plan covering scope/interfaces/tests/steps/risks **and** human-approved test cases (plan-first STOP contract, `prompts/prompt_v1.3.yaml`) |
| Change a safety-critical path (gate/evaluator/output-guard/fail-closed/budget/permissions/prompts) | ADR + explicit human approval |
| Run network / integration / live LLM | Explicit human authorization; `@pytest.mark.integration`; no paid call in default run |
| `git commit` / `push` / tag / PR / release | Explicit, unambiguous human statement for that action |
| Start a new phase | Recorded human review in `docs/review-memo.md` |
| Introduce a new requirement | New stable ID + trace-matrix row in the same change |
| Change a human-only file | Human performs it directly (agent may not) |

## Denied-action handling

When a tool would perform a denied action (secret read, outside-path access,
network, git mutation, editing a frozen file), the agent MUST stop, explain, and
ask the human instead of performing it. Fail closed on missing or ambiguous
approval — default deny.

## Enforcement verification status (honest)

Evidence is reported in separate pieces; none of them alone proves enforcement.

- **On-disk file:** `.opencode/permissions.jsonc` exists (broad allows, not
  path-scoped) — **unchanged this turn**. Its existence is **NOT** evidence that
  it is the loaded/active configuration; that is **UNVERIFIED**.
- **Proposal:** `docs/code-governance/agent-permissions-proposal.yaml` — a
  machine-readable role-by-path deny-by-default whitelist, **NOT active**, marked
  as such (v0.2).
- **Expressibility gap (honest):** the inspected per-agent schema exposes a
  single `edit` verdict and a `bash` pattern map — it has **no per-path `edit`
  map** and **no plain `read` key**. Therefore the machine-readable
  `expressible_permission_maps` can only approximate this path-level model: the
  per-path edit allowlist and the read denials above are **process-enforced
  only**. In particular the planner's read-only *execute intent* is expressible
  only as a deny-all bash map (a prefix allowlist is not a security boundary, see
  the shell-pattern caveat), which is a deliberate conservative mismatch, not
  schema-enforced read-only execution. Nothing in the expressible subset proves
  the path rules are enforced; do not describe it as verified role/path
  enforcement.
- **Human-only rules:** `.opencode/rules.md` is **HUMAN-ONLY** under the course
  specification. It is **NOT edited by any agent**. Any proposed human text is in
  `docs/code-governance/human-rules-proposal.md`, marked *awaiting WANG Yiwen
  manual adoption*.
- **Version evidence (separate):**
  - OpenCode **binary** version: `1.18.25` (`opencode --version`).
  - `@opencode-ai/sdk` **package** version: `1.18.25` (static type package; not
    proof the binary runs this exact SDK).
  - **Static type shape** (from the SDK `.d.ts`): per-agent `permission` with
    `edit`/`bash`/`webfetch`/`doom_loop`/`external_directory`, each
    `ask|allow|deny` (bash may be a `{pattern: verdict}` map). No top-level
    allow/ask/deny array, no plain `read` key, no per-path `edit` map.
- **Load/enforcement:** **UNVERIFIED.** Do not infer enforcement from the type
  shape, the binary version, or a successful JSON parse.
- **JSON parses ≠ config enforced.** Passing a JSON/JSONC parse is not evidence
  of enforcement.

### Benign enforcement-test protocol (pending — not yet run)

A safe, reversible probe to determine whether the installed version actually
denies a prohibited action. **Do not run this without human approval; it is a
protocol description, not an executed test.**

1. Add a temporary *deny* for a harmless command (e.g. a throwaway `bash:echo`)
   in a **scratch copy** of the config, not the repository config.
2. In a fresh session, attempt that harmless command and an allowed read.
3. Observe: is the denied action blocked or asked? Is the allowed one permitted?
4. Record the observed behavior (blocked / asked / silently allowed) as the
   **actual** enforcement result, then discard the scratch config.
5. Until this runs, the enforcement status stays **UNVERIFIED**.

## Model uncertainty (recorded)

The exact per-path schema for `.opencode/permissions.jsonc` on the installed
OpenCode version could not be fully verified here. The **existing shipped file**
is a conservative, minimum documented form; that file exists but its **loading
and enforcement are UNVERIFIED** — it is not assumed to be the loaded/active
configuration. The uncertainty is recorded in `docs/debt-register.md` (DEBT-004)
and `docs/architecture/risk-list.md` (RISK-006). No unsupported key is invented
in the shipped file.

## SDK / plugin provenance (corrected 2026-11-06)

- `~/.config/opencode/package.json` pins **`@opencode-ai/plugin`** at `1.18.25`
  (not `@opencode-ai/sdk` directly).
- `node_modules/@opencode-ai/plugin/package.json` → version `1.18.25`.
- `node_modules/@opencode-ai/sdk/package.json` → version `1.18.25` (present
  transitively; **not** a direct pin in `~/.config/opencode/package.json`).
- OpenCode **binary**: `1.18.25` (`opencode --version`).
- These are **static package/type metadata and a binary version string**; none of
  them proves the binary uses this exact SDK at runtime or loads the shipped
  `.opencode/permissions.jsonc`. Load/enforcement remains **UNVERIFIED**.

## Simulated trading subsystem permissions

The independent subsystem remains deny-by-default and path-scoped:

| Path | Access | Rule |
| --- | --- | --- |
| `src/trading/**` | write | subsystem source |
| `src/safety/**` | write | requires `human_approval` + `architecture_decision` |
| `tests/trading/**` | write | subsystem tests |
| `tradingagents/**`, `cli/**` | frozen/read-only by subsystem work | do not modify |
| `test/offline/**`, `test/live/**` | pointer-only | no test code |
| real broker APIs | denied | simulated execution only |

The safety engine is the only module allowed to call the executor. A plain
`ExecutionAuthorization` without the engine token is rejected.

---

## Token-observability delivery — permission and credential status (2026-11-19)

The Release model above (roles, deny-by-default matrix, approval gates, honest enforcement
status, simulated-trading permissions) remains normative. The personal delivery added a
second, narrower statement of the same mechanisms plus its runtime-tool and API-access
constraints. Where the two disagree, the Release enforcement-status section governs; the
personal table supplies the additional status detail.

**Purpose.** This document separates four mechanisms that are often collapsed
into the word "permissions". They have different owners, different failure modes,
and different levels of enforcement. In particular, the repository's prose rules
for coding agents are **not** a technical access-control system, and the
`.opencode/permissions.jsonc` file must not be described as one.

**Status vocabulary used here**

| Status | Meaning |
| --- | --- |
| `ENFORCED` | A checked-in code path or test blocks the action on the path under discussion. |
| `PARTIALLY_ENFORCED` | Enforced on one path (for example the registered experiment), not on every path. |
| `DOCUMENTED_ONLY` | A rule exists only in prose or review; nothing mechanical blocks a violation. |
| `NOT_VERIFIED` | A mechanism exists or is claimed, but loading or effectiveness was not verified here. |

**Base.** Commit `50b2ca3` plus the submission-packaging files (the governance
files are dated 2026-11-19; they are not historical records of how earlier
commits were produced).

---

**Version evidence conflict (2026-11-21).** Release documents report OpenCode `1.18.25`; this
personal section reports `1.18.29`. `opencode --version` currently fails (`EROFS` opening its
log), so the exact version is `NOT_VERIFIED` and neither number is asserted here.

### 1. Coding-agent permissions (OpenCode / Codex / other assistants)

#### Declarative

| Artefact | What it declares |
| --- | --- |
| `AGENTS.md` | Roles, allowed/forbidden actions, approval points, frozen artifacts, definition of done, and the enforcement-status table. |
| `.opencode/rules.md`, `.agent/rules.md` | Short restatements of `AGENTS.md` for OpenCode and other coding agents. |
| `.opencode/permissions.jsonc` | A `permission` object with `allow` / `ask` / `deny` rules for `edit`, `webfetch`, and `bash` patterns. |
| `Prompt.md`, `prompts/prompt_v1.0.yaml`–`prompt_v1.3.yaml` | The static startup prompt and the four Release coding-agent startup prompts (historical v1.0–v1.2 and current v1.3; not runtime configuration). The separate Market Analyst runtime-prompt snapshots are historical exports under `prompts/archive/`. |

#### Enforced

There is **no verified technical enforcement of the repository's coding-agent
rules**:

* `permissions.jsonc` is a project governance artefact, not a file OpenCode is
  known to auto-load. OpenCode loads `opencode.json` / `opencode.jsonc`; whether
  this path is loaded, and how its patterns are matched, is `NOT_VERIFIED` on the
  installed OpenCode 1.18.29. The file itself says so.
* The rule syntax is best-effort. Command-pattern matching cannot reliably stop
  `python -c "open('.env')"`, shell redirection, an editor, or a different tool
  invocation. It is defense in depth, not a security boundary.
* The only boundary that was actually enforced while this document was written is
  the **host coding-agent sandbox** (workspace-write filesystem scope); it lives
  outside the repository, is not reproducible from the tree, and is not a
  substitute for the project rules.

#### Status

| Scope | Status |
| --- | --- |
| Project rules (`AGENTS.md`, `.opencode/rules.md`, `.agent/rules.md`) | `DOCUMENTED_ONLY` |
| `.opencode/permissions.jsonc` loading and matching | `DOCUMENTED_ONLY` in the repository; `NOT_VERIFIED` against OpenCode 1.18.29 |
| Host sandbox (outside the repo) | `PARTIALLY_ENFORCED`, not reproducible from the repo |

**Do not claim** that `.opencode` rules technically prevent edits, network
access, or secret reads. They do not, on the evidence available.

---

### 2. TradingAgents runtime tool permissions

This is *capability scoping inside the product*: which tools an analyst can call,
which vendor answers a tool, and which features are allowed to run. It is not an
OS sandbox.

#### Declarative

| Surface | Declaration | Where |
| --- | --- | --- |
| Analyst set | `selected_analysts` selects market / social / news / fundamentals | `tradingagents/graph/setup.py` |
| Tool binding | Each analyst factory receives a tool list; `GraphSetup` creates one `ToolNode` per analyst and edges only that node back to its analyst | `tradingagents/graph/setup.py` |
| Vendor routing | `tool_vendors` and `data_vendors` choose the exact vendor chain; `"finnhub"` is the company-news route and `get_global_news` is `CONFIG_DISABLED` | `tradingagents/default_config.py`, `tradingagents/dataflows/interface.py` |
| News scope | A registered spec's `news_scope` must name Finnhub, the disabled global path, and `gdelt: excluded` | `scripts/token_benchmark.py::_preflight_gate` |
| Feature gates | `single_pass` is only on when both `single_pass_finalization_enabled` and `structured_analyst_output_enabled` are true; `s2_downstream=false` is refused because no OFF implementation exists | `tradingagents/graph/setup.py`, `scripts/token_benchmark.py` |
| Switch consumption | The declared switches are compared with what `GraphSetup` actually passed to the factories and bound tools | `tradingagents/graph/switch_verification.py` |

#### Enforced

* The graph structure is real: a tool node is connected only to its analyst, and
  `should_continue_*` decides whether to enter it. An analyst cannot call a tool
  that was not bound to it through the normal graph path.
* `validate_spec_switches` fails when a consumer was never captured or a switch
  value is not a bool; the real graph is driven for all four arms in
  `tests/test_switch_consumption.py`.
* The preflight gate refuses a registered spec whose news scope is not the frozen
  one and whose arm disagrees with `SWITCH_MATRIX.csv`.

#### Not enforced

* Tool functions are ordinary Python functions. They can perform network I/O, read
  files, and use credentials; there is no capability token, seccomp profile,
  network namespace, or egress allowlist.
* A caller can construct a different `GraphSetup`, bind different tools, or call
  a tool function directly; the preflight gate is a harness gate, not a Python
  import guard.
* `tool_vendors` is configuration. Changing it changes routing; the product does
  not authenticate the config source.

**Status: `PARTIALLY_ENFORCED`** — the declared graph/vendor scoping is real on
the normal pipeline path; it is not a security boundary against arbitrary code.

---

### 3. API access constraints

This is *credential handling and provider access*, not user authorization.

#### Declarative

| Surface | Rule | Where |
| --- | --- | --- |
| Key-to-provider mapping | One env var per provider; `openai_compatible` uses `OPENAI_COMPATIBLE_API_KEY` | `tradingagents/llm_clients/api_key_env.py` |
| Credential files | `.env`, `.env.enterprise`, `.envrc` are git-ignored; examples are placeholders | `.gitignore`, `.env.example`, `.env.enterprise.example` |
| CLI key write | When the CLI saves a key it creates the file `0600` and tightens an existing file | `cli/utils.py` |
| No keys in evidence | The freeze credential audit records only metadata for `.env`; no key is read, printed, or hashed | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/env_credential_audit.txt` |
| Offline tests | `tests/conftest.py` installs dummy keys and blocks live news vendor hosts | `tests/conftest.py` |

#### Enforced

* The mapping is the single source of truth; a provider with no mapping is
  reported as "no key check possible", not silently given a key.
* `.env` is not tracked, and the audit records that no API key appears in the
  branch diff (`env_credential_audit.txt`).
* The CLI's saved-key file is owner-only; `tests/test_api_key_env.py` pins the
  `0600` behaviour.
* Tests replace live news transports with deterministic failures; a test cannot
  accidentally spend a live news quota through the default fixture.

#### Not enforced

* There is no least-privilege key, key rotation, per-run budget token, or egress
  allowlist. Any process that can read the environment can use the key.
* The endpoint is ambient (`TRADINGAGENTS_LLM_BACKEND_URL`) and is **not** in
  `config_sha256`; changing it does not change the registered hash. This is
  recorded as a V3 limitation, not a solved control.
* The local `.env` file was reported with mode `644` in the credential audit. The
  repository only guarantees "not tracked", not "unreadable by other local
  users".
* A secret scan does exist in both validator paths (`scan_secrets` in
  `scripts/validate/validate_requirements.py`, `check_secrets` in
  `scripts/validate/validate_submission.py`) and runs in CI when the respective
  job runs. It is pattern-based over a listed artifact set, not a full-history or
  full-tree scanner, so review plus `.gitignore` remain part of the control.

**Status: `PARTIALLY_ENFORCED`** — mapping, git-ignore, owner-only CLI file, and
offline test blocks are real; least privilege and egress control are not.

---

### 4. Experiment harness launch gates

This is the strongest of the four, but only on the path that actually uses the
harness.

#### Declarative

| Gate | What it requires | Where |
| --- | --- | --- |
| Registration/spec binding | `config_sha256`, `switches`, `registration_dir`, the case, and the registered directory | `scripts/token_benchmark.py::_preflight_gate` |
| Arm authority | Switches must equal `SWITCH_MATRIX.csv` for that Run ID | same |
| Freeze | `HEAD` must equal the recorded frozen commit; the tree must be clean; the release seal, manifest, protocol/generator hashes, 16 spec hashes, and tag must agree | `scripts/token_benchmark.py::verify_frozen_tree`, `scripts/c3_verify_final_freeze.py` |
| Budget contract | `budget_mode` must be explicit; a null cap is only "uncapped" under `uncapped_authorized`; a malformed block is a refusal | `scripts/token_benchmark.py::budget_state_from_experiment`, `require_budget_state`; `tradingagents/budget_guard.py` |
| Memory | Snapshot hash, per-run copy, containment, no pending entry | `scripts/token_benchmark.py::validate_memory_spec` |
| Spend authorization | The operator must authorize a paid run; the gates do not authorize by themselves | `AGENTS.md` §8/§12; runbook |

#### Enforced

* The harness raises `RunRefused` **before** the graph or any paid call when a
  required fact is missing or contradictory. The tests exercise the real
  `_run_single` and the real child path, not a mock of the gate.
* `TRADINGAGENTS_SKIP_FREEZE_CHECK=1` exists for test seams, but is explicitly
  refused for a run of the frozen batch (`verify_frozen_tree`), and the child
  strips the variable unless the test-only opt-in is present.
* A modified memory baseline makes the run INVALID; a missing `memory_state.json`
  for a memory-bearing spec is INVALID.
* A budget block that cannot be interpreted is a refusal, not an uncapped run.

#### Not enforced

* The gates apply to the **registered harness path**. Calling
  `TradingAgentsGraph.propagate()` or the CLI directly bypasses them; the product
  does not require a registration for a normal run.
* The freeze metadata (`c3/FROZEN_COMMIT`, `c3/FREEZE_RECORD.json`,
  `c3/FREEZE_HISTORY.jsonl`) is untracked release metadata. The tracked authority
  is `c3/code_freeze.txt`, `c3/RELEASE_SEAL.sha256`, and `MANIFEST.sha256`. At
  `HEAD = 50b2ca3`, the V3 freeze record names `e3b5cca`, so
  `c3_verify_final_freeze.py` cannot certify the current HEAD; this is expected
  for a post-freeze remediation branch but means "frozen" is a historical
  property, not a property of the working tree.
* The batch directory is selected by `TRADINGAGENTS_C3_BATCH` (default V3). A
  wrong or unset value can point the gate at a different batch; the runbook pins
  it, but the code does not infer the operator's intent.
* V3 specs embed absolute `experiment_root` / `results_dir` paths from the build
  worktree. Regenerating or checking them in a different checkout reports drift;
  this is a path-coupling risk, not a permission bypass.
* The gate chain does not create a human approval record. "The gate passed" is
  not "a human authorized the spend"; the authorization is an external,
  documented decision (see `AGENTS.md` §8/§12).

**Status: `PARTIALLY_ENFORCED`** — fail-closed and tested on the registered
harness path; bypassable through the product API/CLI and dependent on untracked
freeze metadata and path/env pinning.

---

### 5. Cross-mechanism matrix

| Mechanism | Declarative artefact | Actual enforcement point | Status | Main residual |
| --- | --- | --- | --- | --- |
| Coding-agent permissions | `AGENTS.md`, `.opencode/rules.md`, `.agent/rules.md`, `.opencode/permissions.jsonc` | None verified; host sandbox outside repo | `DOCUMENTED_ONLY` / `NOT_VERIFIED` | Pattern matching cannot stop arbitrary reads or shell tricks |
| Runtime tool permissions | `selected_analysts`, tool bindings, `tool_vendors`, `news_scope`, switch gates | `GraphSetup` graph construction; `validate_spec_switches`; preflight | `PARTIALLY_ENFORCED` | No capability sandbox or egress control |
| API access constraints | `api_key_env.py`, `.gitignore`, `cli/utils.py` `0600`, `tests/conftest.py` | Key mapping; git-ignore; owner-only file; offline fixtures | `PARTIALLY_ENFORCED` | No least privilege, no endpoint hash, no scanner |
| Harness launch gates | Preflight, freeze verifier, budget, memory, switch matrix | `RunRefused` in `scripts/token_benchmark.py`; `BudgetGate`; `c3_verify_final_freeze.py` | `PARTIALLY_ENFORCED` | Bypass via direct API/CLI; untracked freeze metadata; path/env coupling |

### 6. Approval boundary (no fabricated approvals)

The repository contains **no recorded human approval** for any paid run in this
submission. The experiment evidence is marked `Supplied` where it comes from the
canonical record and `Re-run` where the result was recomputed. Passing a gate is
a necessary condition, not an approval; this document does not claim that a
person reviewed or signed any specific run.

### 7. Evidence index

| Claim | Path |
| --- | --- |
| Coding-agent rules and status table | `AGENTS.md`; `.opencode/rules.md`; `.agent/rules.md`; `.opencode/permissions.jsonc` |
| OpenCode loading uncertainty | `.opencode/permissions.jsonc` header comment |
| Tool bindings and switch verification | `tradingagents/graph/setup.py`; `tradingagents/graph/switch_verification.py`; `tests/test_switch_consumption.py` |
| News scope and vendor routing | `tradingagents/default_config.py`; `tradingagents/dataflows/interface.py`; `tests/test_finnhub_only_scope.py` |
| API key mapping, owner-only CLI file | `tradingagents/llm_clients/api_key_env.py`; `cli/utils.py`; `tests/test_api_key_env.py` |
| Offline test guards | `tests/conftest.py` |
| Credential audit | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/env_credential_audit.txt` |
| Preflight / freeze / budget / memory gates | `scripts/token_benchmark.py`; `scripts/c3_preflight_gate.py`; `scripts/c3_verify_final_freeze.py`; `tradingagents/budget_guard.py` |
| Gate tests | `tests/test_c3_final_freeze.py`; `tests/test_c3_regressions.py`; `tests/test_budget_guard.py`; `tests/test_memory_isolation.py` |
