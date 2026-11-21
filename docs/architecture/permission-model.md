# TradingAgents WebUI Permission Model

Status: **Approved for documentation by the human owner on 2026-11-05.** Implementation still requires human review of applicable safety/governance changes. Under the 2026-11-21 CI policy revision in ADR-012-error-handling-merge-integration.md, GitHub branch protection owns merge approval; special review markers are not required. This document defines the WebUI runtime permission boundary and its relationship to the coding-agent roles. Runtime permissions are unchanged by that CI revision.

## 1. Scope

This model covers:

1. What the browser, web service, run coordinator, artifact reader, and core may do.
2. Which data classes may cross which boundary.
3. Which actions require explicit confirmation.
4. How the coding-agent roles in `.opencode/permissions.jsonc` relate to the product boundary.

It does not replace the OS sandbox, the OpenCode permission configuration, or a human approval decision.

## 2. Subjects and ownership

| Subject | Owns | May read | May write | May execute |
| --- | --- | --- | --- | --- |
| Browser SPA | Presentation state | Same-origin API responses | Browser local storage only | No server code |
| FastAPI HTTP layer | Request parsing, validation, error mapping | Request body, config projection | HTTP response | No arbitrary command |
| Run coordinator | Active run record, worker future, cancel event, event buffer | Validated run request, graph state | Run record, event buffer, run artifacts through the writer | Calls existing Python APIs |
| Graph runner | One `TradingAgentsGraph` instance | Core config and state | Graph/checkpoint/decision-log through existing methods | Runs the analysis graph |
| Artifact read model | Read-only index cache | Allowlisted artifact roots | Nothing | No |
| Backtest runner | One backtest invocation | Backtest request, isolated run dir | Backtest log through `run_backtest` | Calls existing backtest |
| Core (`tradingagents`) | Business rules, ratings, data access, memory, checkpoints | Its own config/data | Its own artifacts | Existing behaviour only |
| CLI (`cli`) | Terminal interaction | Core API, prefs | CLI files/artifacts | Existing behaviour only |
| Operator | Server process, environment | Server logs and artifacts | Environment, filesystem | Starts/stops the server |

## 3. Runtime permission matrix

| Action | Browser | Web API | Coordinator | Artifact reader | Core/CLI |
| --- | --- | --- | --- | --- | --- |
| Read effective config | via API, redacted | allow | read | — | source |
| Read provider key value | **deny** | **deny** | **deny** | — | server env only |
| Read key status | allow | allow | — | — | — |
| Start analysis | allow | allow if validated | allow if no active run | — | — |
| Start backtest | allow | allow if validated | allow if no active run | — | — |
| Cancel analysis | allow | allow | allow | — | — |
| Cancel backtest | **deny** (no route) | **deny** | **deny** | — | no hook |
| Read live run state | allow | allow | own | — | — |
| Read history | allow | allow | — | allow | — |
| Delete/rename history | **deny** | **deny** | **deny** | **deny** | — |
| Download report | allow via id | allow via id | — | allow | writer source |
| Accept server path | **deny** | **deny** | **deny** | **deny** | — |
| Clear all checkpoints | allow with confirmation | allow with confirmation | allow if idle | — | clear method |
| Place an order | **deny** | **deny** | **deny** | — | **deny** |
| Change agent/prompt/rating rules | **deny** | **deny** | **deny** | — | out of scope |
| Write `.env` / keys | **deny** | **deny** | **deny** | — | CLI only, not web |

## 4. Data classification

| Class | Examples | Allowed destinations | Prohibited destinations |
| --- | --- | --- | --- |
| Secret | Provider API keys, tokens, cookies, authorization headers | Server process environment and provider SDK | Browser, events, logs, reports, downloads, errors, snapshots |
| Internal path | `results_dir`, `data_cache_dir`, `memory_log_path`, absolute paths | Server code and redacted logs | Browser responses, events, errors, downloads |
| User data | Ticker, date, portfolio, selected models | Browser ↔ API, run artifacts | Third-party services beyond the configured model/data providers |
| Model/external text | Reports, tool output, announcements | Sanitized rendering and stored artifacts | Executable HTML, server-side evaluation, permission decisions |
| Run metadata | Run id, status, rating, review flag, timestamps | Browser and artifacts | — |
| History artifact | Report sections, decision log entries | Read-only browser view and downloads | Mutation by the web layer |

## 5. Permission boundary enforcement

| Boundary | Rule | Enforcement | Fallback |
| --- | --- | --- | --- |
| Network | Loopback only; no auth | `settings.py` rejects non-loopback bind; `security.py` Host/Origin checks | Refuse to start or reject request |
| Request origin | Same-origin state-changing requests | CSRF token, Origin/`Sec-Fetch-Site`, no wildcard CORS | 403 |
| Secrets | Server-only | Config projection returns status; serializers allowlist; error redaction | Remove field / rotate credential |
| Filesystem | Artifact ids only | Hash index; root allowlist; `safe_ticker_component` | 404/400 |
| Uploads | Portfolio JSON text only | Size limit; parse; discard | 413/422 |
| Execution | No trading route | Route inventory; security test | Remove endpoint |
| History | Read-only | No mutating route; read model | Reject mutation |
| Checkpoints | Clear is destructive | `{"confirm":"CLEAR"}`; disabled while running | 409 |
| Rendering | Untrusted content is data | `rehype-sanitize`; no raw HTML; CSP; URL allowlist | Plain text |

## 6. Destructive and privileged actions

1. **Clear all checkpoints**: requires an explicit confirmation token, is disabled while a run is active, and reports only the count cleared.
2. **Cancel analysis**: requires a same-origin state-changing request; no decision is written and no checkpoint is cleared.
3. **Start a run**: may consume paid provider capacity; the UI must show provider/model and key status before submission.
4. **Read decision memory**: read-only; no rotation or deletion from the web.
5. **Download artifacts**: only through a resolved artifact id; filenames are sanitized; no path input.

## 7. Coding-agent role boundary

The development roles remain defined by `.opencode/permissions.jsonc` and `AGENTS.md`. This document does not grant additional tool or path access.

| Role | Product-code edits | Docs edits | Tests | Git/remote |
| --- | --- | --- | --- | --- |
| Plan | Denied | Denied | Read-only | Status only |
| Build | Allowlisted `src/` and `test/`; protected paths require review | Only authorized records | May add tests after approval | Status/diff only |
| Verify | Denied | Denied | Run only; no weakening | Status/diff only |
| Docs | Denied | Allowlisted docs | Data validators only | Status/diff only |

An ACL `allow` is not plan approval. `permission-model.md` itself is a documentation artifact; it does not authorize implementation.

## 8. Denials and fallback actions

- A denied action returns a safe error category; it is not retried through a shell or another tool.
- A missing key is a configuration state, not a permission bypass.
- A rejected Host/Origin/CSRF request is logged with a reason but no payload.
- A failed artifact resolution returns `not_found`; it never falls back to a broader root.
- A failed sanitizer render falls back to plain text.

## 9. Review and change control

- Changes to this model require human review and a corresponding update to `docs/architecture/invariants.md`, `docs/architecture/runtime-policy-catalog.md`, and the relevant ADR.
- Any proposal to add authentication, network exposure, new storage, execution, or browser key input is a scope change, not a configuration tweak.
- No agent may edit `.opencode/rules.md` or `.opencode/permissions.jsonc` to widen its own access.


## Release permission observations and proposals (historical context)

The following text describes the release environment and proposal status at
its recorded time. It does not replace the current `.opencode/permissions.jsonc`,
activate a proposed agent/MCP service, or widen access. The current path-scoped
V1 policy above applies to this branch; actual host loading/enforcement still
requires independent verification. Historical references to broad allow arrays
and schema expressibility are not claims about this branch's current policy.

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
| `src/tradingagents/**` (source) | R E X | R | R E (approved scope only) | R X (offline tests) |
| `src/cli/**` (source) | R E X | R | R E (approved scope only) | R X |
| `test/offline/**` (tests) | R E X | R | R E **only when the plan+test cases were human-approved first** | R X (run only) |
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
| Edit `test/offline/**` or any feature code | Human-approved execution plan covering scope/interfaces/tests/steps/risks **and** human-approved test cases (plan-first STOP contract, `prompts/prompt_v1.3.yaml`) |
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
| `src/safety/**` | ask in the retained V1 ACL | human-approved plan/tests and ADR required |
| `src/tradingagents/**`, `src/cli/**` | protected/read-only by subsystem work | do not modify |
| `test/offline/trading/**`, `test/live/trading/**` | approved test scope only | offline regression and separately authorized live smoke |
| real broker APIs | denied | simulated execution only |

The safety engine is the only module allowed to call the executor. A plain
`ExecutionAuthorization` without the engine token is rejected.
