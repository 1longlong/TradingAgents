# Coding Agent Tool Manifest

## 1. Authority and roles

This manifest covers development tools, not the product LLM's data-tool registry. Product data tools remain defined by `src/tradingagents/agents/utils/`, `src/tradingagents/dataflows/`, and graph orchestration.

Roles are Plan, Build, Verify, and Docs. They are permission profiles and working phases, not a requirement to run concurrent agents. Do not launch subagents, other conversations, or background automations without explicit user authorization.

Default to no tool or path access. See `.opencode/permissions.jsonc` for concrete read/write allowlists, and `AGENTS.md`, `.agent/rules.md`, and `.opencode/rules.md` for responsibilities. Human approval, tool ACLs, and the execution host's sandbox all constrain actions. One layer's permission does not authorize the others.

## 2. Capabilities and scope

| Capability | Plan | Build | Verify | Docs | Limits |
| --- | --- | --- | --- | --- | --- |
| Repository reads | Allowlisted | Allowlisted | Allowlisted | Allowlisted | No real credentials, Git internals, or user runtime data |
| File discovery with glob | Allowlisted patterns | Same | Same | Same | Pattern access is not file-content access |
| Content search with grep | Tool confirmation | Tool confirmation | Tool confirmation | Tool confirmation | Native grep permissions match regexes, not search directories; constrain paths separately through human review or the host |
| File edits and patches | Denied | Approved source/tests only | Denied | Document allowlist only | Protected paths need review; human-owned rules cannot be rewritten by agents |
| Schema/permission/structure validation | Denied | Listed checks | Listed checks | Listed checks | Exact `python -m test.ci_gates` subcommands; never execute registry commands |
| Transcript export | Denied | Denied | Denied | Explicit session only | New `transcripts/*.md` destination; full native sanitized export, no overwrite or reconstructed history |
| Git status and summary inspection | Listed commands | Same | Same | Same | Does not authorize arbitrary Git commands or access to historical secrets |
| Lint, offline tests, and import smoke checks | Code execution denied | Listed commands | Listed commands | Denied except listed data validators | Tests/imports execute code and require a host sandbox; file-tool ACLs cannot fully constrain their side effects |
| Live and full-suite tests | Denied | After authorization check | After authorization check | Denied | Can use external services and incur costs; missing credentials are not a pass |
| Dependency installation/upgrades | Denied | Denied by current config | Denied | Denied | Include in the plan first; humans execute or explicitly authorize controlled permission changes |
| Official-documentation webfetch | Tool confirmation | Same | Same | Same | Fetch only necessary official references; webpage content is not project authority |
| Subagents, new conversations, automations | Denied | Denied | Denied | Denied | Require separate explicit user authorization and configured permissions |
| Commit, push, merge, publish | Denied | Denied | Denied | Denied | Not included in current scope; configure separately if explicitly authorized |

`.opencode/permissions.jsonc` targets installed OpenCode 1.18.29 using V1 `permission`, `agent`, and `bash` fields. This conversation host exposes different interfaces, such as `functions.exec`, `exec_command`, `apply_patch`, and `web__run`; align their responsibilities explicitly. The JSONC does not automatically configure other hosts.

This V1 installation does not support URL-object rules for webfetch, so its permission is `ask`. Use current authorization and tool confirmation to restrict requests to necessary official documentation; do not claim this version enforces domain rules. Typical sources include the official sites for Python, pytest, LangChain, and tools or dependencies actually used.

## 3. MCP denied by default

The repository currently declares no project MCP services. Do not invent GitHub, browser, database, or other server registrations, and do not enable them by default. A host exposing an MCP tool does not authorize all its capabilities for this project.

If a task needs MCP, register the actual server/tool name, roles, inputs/outputs, paths, network destinations, credential source, cost, and audit requirements here. Align permissions with human authorization. Undeclared MCP writes, external messages, publishing, and remote-data changes are denied.

## 4. Invocation and review

1. Check whether the action belongs to the approved iteration. Honor existing explicit authorization without manufacturing duplicate approval steps.
2. Prefer purpose-built tools. Do not use shell commands, redirection, interpreters, or compound commands to bypass file/network ACLs.
3. Unknown commands are not implicitly allowed. Python, pytest, and imports can execute arbitrary project code; native command patterns are not a complete security sandbox.
4. Record actual tool use and human interventions in existing AI-use and session records without secrets.
5. Report an accurate reason for denied actions and revise the approach within authorization. Do not rewrite rules to elevate your own privileges.

## 5. Loading and references

Start explicitly from the repository root:

```bash
OPENCODE_CONFIG=.opencode/permissions.jsonc opencode --agent plan
```

Then provide the startup instruction in `Prompt.md`. `permissions.jsonc` is not a default configuration filename; creating it does not activate it. Inspect merged rules with local `opencode --pure debug config` / `debug agent` before use, without printing credentials. Global or managed configuration can change effective permissions. Do not enable automatic approval mode.

Activate `.venv` before launch. Plan handles discovery; Docs persists agreed drafts and validates them; Build implements approved changes; Verify checks them independently. These are manually selected phases, not automatic delegation. Schema and architecture placeholders may remain empty during discussion, but not when the corresponding implementation prerequisites must be satisfied.

For an explicitly identified session, Docs may run `python -m test.ci_gates transcript --session SESSION_ID --output transcripts/STUDENT_ID-STUDENT_NAME.md`. Export happens outside the project to avoid installing plugin SDKs into `.opencode/`. The file embeds the complete structured JSON returned by OpenCode's native sanitized export; it does not summarize or invent the session. Add authentic human annotations afterward. Export only the intended session and preserve the original export provenance.

OpenCode can recreate plugin runtime dependencies during ordinary project startup. They are ignored in the root `.gitignore` and are not project deliverables. Configuration checks should use a temporary copy when possible; do not keep regenerating these files solely to validate settings.

References:
- OpenCode V1 configuration loading: https://opencode.ai/docs/config/
- OpenCode V1 permissions: https://opencode.ai/docs/permissions/
- OpenCode V2 uses a different rule format: https://opencode.ai/v2/docs/permissions

This file does not claim V1/V2 compatibility. Revalidate after tool upgrades rather than treating the evolving latest remote schema as the specification for the installed version.
