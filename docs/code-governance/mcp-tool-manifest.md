# MCP Tool Manifest

This document lists the Model Context Protocol (MCP) tools/tool surfaces the
CS5351 work expects and the policy governing their use. It is a governance
manifest, not a list of installed servers — no MCP server is added by this
project unless explicitly required.

## Policy summary

- **Read-only by default.** Offline, deterministic, LLM-free execution is the
  default. No tool may call a network, a data vendor, or a paid LLM unless the
  phase explicitly authorizes it.
- **No secret-bearing tool output** may be printed, copied, or committed.
- **No persistence** (commit/push/PR/release) without explicit human approval.
- **Fail closed** on missing or ambiguous permission: the tool is not run and
  the human is asked.

## Tool categories used in this repository

| Category | Examples | Allowed on default? |
| --- | --- | --- |
| File read | read file, glob, grep | Yes |
| File write/edit | write, edit | Yes (within phase scope) |
| Shell (read-only) | pytest, ruff, validators, git diff/status | Yes |
| Shell (network / paid API) | vendor curl, LLM API calls | No — requires phase authorization |
| Shell (git mutation) | commit, push, release, PR | No — requires explicit human approval |
| Secret read | read `.env`, print API keys, tokens | No — never |

## Handling

- A denied tool is **not run**. The agent explains why and asks the human.
- Tool use is logged in `docs/ai-use-log.yaml` with tool, scope, date, and
  outcome; secrets are never copied into the log.
- If exact schema support for a given permission is unverified, the minimal
  documented form is used and the uncertainty is recorded in
  `docs/debt-register.md` and `docs/architecture/risk-list.md`.

## Security constraints

- Keys toggles are governed by `docs/architecture/permission-model.md`.
- Real secrets stay in environment variables or gitignored `.env`; use
  `.env.example` placeholders in committed files.