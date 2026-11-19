# Permission model

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

## 1. Coding-agent permissions (OpenCode / Codex / other assistants)

### Declarative

| Artefact | What it declares |
| --- | --- |
| `AGENTS.md` | Roles, allowed/forbidden actions, approval points, frozen artifacts, definition of done, and the enforcement-status table. |
| `.opencode/rules.md`, `.agent/rules.md` | Short restatements of `AGENTS.md` for OpenCode and other coding agents. |
| `.opencode/permissions.jsonc` | A `permission` object with `allow` / `ask` / `deny` rules for `edit`, `webfetch`, and `bash` patterns. |
| `Prompt.md`, `prompts/prompt_v1.0.yaml`, `prompts/prompt_v1.1.yaml` | The static startup prompt and archival prompt exports (not runtime configuration). |

### Enforced

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

### Status

| Scope | Status |
| --- | --- |
| Project rules (`AGENTS.md`, `.opencode/rules.md`, `.agent/rules.md`) | `DOCUMENTED_ONLY` |
| `.opencode/permissions.jsonc` loading and matching | `DOCUMENTED_ONLY` in the repository; `NOT_VERIFIED` against OpenCode 1.18.29 |
| Host sandbox (outside the repo) | `PARTIALLY_ENFORCED`, not reproducible from the repo |

**Do not claim** that `.opencode` rules technically prevent edits, network
access, or secret reads. They do not, on the evidence available.

---

## 2. TradingAgents runtime tool permissions

This is *capability scoping inside the product*: which tools an analyst can call,
which vendor answers a tool, and which features are allowed to run. It is not an
OS sandbox.

### Declarative

| Surface | Declaration | Where |
| --- | --- | --- |
| Analyst set | `selected_analysts` selects market / social / news / fundamentals | `tradingagents/graph/setup.py` |
| Tool binding | Each analyst factory receives a tool list; `GraphSetup` creates one `ToolNode` per analyst and edges only that node back to its analyst | `tradingagents/graph/setup.py` |
| Vendor routing | `tool_vendors` and `data_vendors` choose the exact vendor chain; `"finnhub"` is the company-news route and `get_global_news` is `CONFIG_DISABLED` | `tradingagents/default_config.py`, `tradingagents/dataflows/interface.py` |
| News scope | A registered spec's `news_scope` must name Finnhub, the disabled global path, and `gdelt: excluded` | `scripts/token_benchmark.py::_preflight_gate` |
| Feature gates | `single_pass` is only on when both `single_pass_finalization_enabled` and `structured_analyst_output_enabled` are true; `s2_downstream=false` is refused because no OFF implementation exists | `tradingagents/graph/setup.py`, `scripts/token_benchmark.py` |
| Switch consumption | The declared switches are compared with what `GraphSetup` actually passed to the factories and bound tools | `tradingagents/graph/switch_verification.py` |

### Enforced

* The graph structure is real: a tool node is connected only to its analyst, and
  `should_continue_*` decides whether to enter it. An analyst cannot call a tool
  that was not bound to it through the normal graph path.
* `validate_spec_switches` fails when a consumer was never captured or a switch
  value is not a bool; the real graph is driven for all four arms in
  `tests/test_switch_consumption.py`.
* The preflight gate refuses a registered spec whose news scope is not the frozen
  one and whose arm disagrees with `SWITCH_MATRIX.csv`.

### Not enforced

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

## 3. API access constraints

This is *credential handling and provider access*, not user authorization.

### Declarative

| Surface | Rule | Where |
| --- | --- | --- |
| Key-to-provider mapping | One env var per provider; `openai_compatible` uses `OPENAI_COMPATIBLE_API_KEY` | `tradingagents/llm_clients/api_key_env.py` |
| Credential files | `.env`, `.env.enterprise`, `.envrc` are git-ignored; examples are placeholders | `.gitignore`, `.env.example`, `.env.enterprise.example` |
| CLI key write | When the CLI saves a key it creates the file `0600` and tightens an existing file | `cli/utils.py` |
| No keys in evidence | The freeze credential audit records only metadata for `.env`; no key is read, printed, or hashed | `token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/c3/env_credential_audit.txt` |
| Offline tests | `tests/conftest.py` installs dummy keys and blocks live news vendor hosts | `tests/conftest.py` |

### Enforced

* The mapping is the single source of truth; a provider with no mapping is
  reported as "no key check possible", not silently given a key.
* `.env` is not tracked, and the audit records that no API key appears in the
  branch diff (`env_credential_audit.txt`).
* The CLI's saved-key file is owner-only; `tests/test_api_key_env.py` pins the
  `0600` behaviour.
* Tests replace live news transports with deterministic failures; a test cannot
  accidentally spend a live news quota through the default fixture.

### Not enforced

* There is no least-privilege key, key rotation, per-run budget token, or egress
  allowlist. Any process that can read the environment can use the key.
* The endpoint is ambient (`TRADINGAGENTS_LLM_BACKEND_URL`) and is **not** in
  `config_sha256`; changing it does not change the registered hash. This is
  recorded as a V3 limitation, not a solved control.
* The local `.env` file was reported with mode `644` in the credential audit. The
  repository only guarantees "not tracked", not "unreadable by other local
  users".
* There is no secret scanner in CI; the only control is review plus the
  `.gitignore` entries.

**Status: `PARTIALLY_ENFORCED`** — mapping, git-ignore, owner-only CLI file, and
offline test blocks are real; least privilege and egress control are not.

---

## 4. Experiment harness launch gates

This is the strongest of the four, but only on the path that actually uses the
harness.

### Declarative

| Gate | What it requires | Where |
| --- | --- | --- |
| Registration/spec binding | `config_sha256`, `switches`, `registration_dir`, the case, and the registered directory | `scripts/token_benchmark.py::_preflight_gate` |
| Arm authority | Switches must equal `SWITCH_MATRIX.csv` for that Run ID | same |
| Freeze | `HEAD` must equal the recorded frozen commit; the tree must be clean; the release seal, manifest, protocol/generator hashes, 16 spec hashes, and tag must agree | `scripts/token_benchmark.py::verify_frozen_tree`, `scripts/c3_verify_final_freeze.py` |
| Budget contract | `budget_mode` must be explicit; a null cap is only "uncapped" under `uncapped_authorized`; a malformed block is a refusal | `scripts/token_benchmark.py::budget_state_from_experiment`, `require_budget_state`; `tradingagents/budget_guard.py` |
| Memory | Snapshot hash, per-run copy, containment, no pending entry | `scripts/token_benchmark.py::validate_memory_spec` |
| Spend authorization | The operator must authorize a paid run; the gates do not authorize by themselves | `AGENTS.md` §8/§12; runbook |

### Enforced

* The harness raises `RunRefused` **before** the graph or any paid call when a
  required fact is missing or contradictory. The tests exercise the real
  `_run_single` and the real child path, not a mock of the gate.
* `TRADINGAGENTS_SKIP_FREEZE_CHECK=1` exists for test seams, but is explicitly
  refused for a run of the frozen batch (`verify_frozen_tree`), and the child
  strips the variable unless the test-only opt-in is present.
* A modified memory baseline makes the run INVALID; a missing `memory_state.json`
  for a memory-bearing spec is INVALID.
* A budget block that cannot be interpreted is a refusal, not an uncapped run.

### Not enforced

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

## 5. Cross-mechanism matrix

| Mechanism | Declarative artefact | Actual enforcement point | Status | Main residual |
| --- | --- | --- | --- | --- |
| Coding-agent permissions | `AGENTS.md`, `.opencode/rules.md`, `.agent/rules.md`, `.opencode/permissions.jsonc` | None verified; host sandbox outside repo | `DOCUMENTED_ONLY` / `NOT_VERIFIED` | Pattern matching cannot stop arbitrary reads or shell tricks |
| Runtime tool permissions | `selected_analysts`, tool bindings, `tool_vendors`, `news_scope`, switch gates | `GraphSetup` graph construction; `validate_spec_switches`; preflight | `PARTIALLY_ENFORCED` | No capability sandbox or egress control |
| API access constraints | `api_key_env.py`, `.gitignore`, `cli/utils.py` `0600`, `tests/conftest.py` | Key mapping; git-ignore; owner-only file; offline fixtures | `PARTIALLY_ENFORCED` | No least privilege, no endpoint hash, no scanner |
| Harness launch gates | Preflight, freeze verifier, budget, memory, switch matrix | `RunRefused` in `scripts/token_benchmark.py`; `BudgetGate`; `c3_verify_final_freeze.py` | `PARTIALLY_ENFORCED` | Bypass via direct API/CLI; untracked freeze metadata; path/env coupling |

## 6. Approval boundary (no fabricated approvals)

The repository contains **no recorded human approval** for any paid run in this
submission. The experiment evidence is marked `Supplied` where it comes from the
canonical record and `Re-run` where the result was recomputed. Passing a gate is
a necessary condition, not an approval; this document does not claim that a
person reviewed or signed any specific run.

## 7. Evidence index

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
