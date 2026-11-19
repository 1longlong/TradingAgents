# MCP and Tool Manifest

Status: **established 2026-11-19**; inventory verified against the tree at base
commit `50b2ca3` and the local OpenCode installation. This manifest lists only
tooling that actually exists. It does not invent MCP servers.

## 1. MCP servers

**No MCP servers are used in this project.**

Evidence (check, not assumption):

- no `opencode.json` / `opencode.jsonc`, `.mcp.json`, or `mcp*.json` in the
  repository;
- no `mcp`, `modelcontextprotocol`, or `mcp_server` reference in tracked Python,
  JSON, TOML, YAML, or CI files (repo-wide grep returned no matches outside
  `.venv`/caches);
- no MCP client dependency in `pyproject.toml`;
- the local OpenCode global config (`~/.config/opencode/opencode.jsonc`) contains
  no `mcp` block (checked by count only; no secrets printed);
- all agent tools in this project are ordinary Python functions bound through
  LangChain/LangGraph (e.g. `get_stock_data`, `get_indicators`,
  `get_verified_market_snapshot` in
  `tradingagents/agents/utils/agent_utils.py`), not MCP tools.

Consequences:

- The `.opencode/permissions.jsonc` file governs edit/bash/webfetch only; there
  are no MCP tool permissions to grant.
- Adding an MCP server is a new dependency and a network/integration surface. It
  requires explicit human approval, an entry in this manifest, a read-only scope
  by default, and a no-paid-call rule. Until then, an agent must not add one.

## 2. Real tooling and scripts

These are the tools an agent may actually use. "Cost" is the important column:
anything that can reach a provider is not part of the offline gate.

| Tool / script | Role | Invocation | Cost / risk |
| --- | --- | --- | --- |
| `pytest` (9.1.1 in `.venv`) | Offline test suite | `TZ=UTC PYTHONPATH=. .venv/bin/python -m pytest tests -q` | Free, offline; dummy keys and vendor blocks from `tests/conftest.py` |
| `ruff` (0.17.1 in `.venv`) | Lint (`ruff check .`) | `.venv/bin/python -m ruff check .` | Free; **233 baseline findings** at `50b2ca3` |
| `python` (3.14.7 in `.venv`) | Scripts, YAML/JSONC validation, AST extraction | `.venv/bin/python <script>` | Free |
| `git` | Read-only history/diff/tag inspection | `git status`, `git log`, `git show`, `git diff`, `git tag` | Read-only; write operations need approval (`AGENTS.md` §10) |
| `scripts/token_benchmark.py` | Benchmark harness; `validate` is offline, `run` spends money | `validate --experiment <path>`; `run ...` | `validate` free; `run` is a paid pipeline, authorization required |
| `scripts/c3_verify_protocol_freeze.py` | Protocol freeze verification | no arguments | Free, read-only |
| `scripts/c3_verify_final_freeze.py` | Final-freeze certificate check | `--quiet` / `--json` | Free, read-only |
| `scripts/c3_mutation_evidence.py` | Mutation evidence for critical guards | direct run | **Mutates tracked source** then restores; manual, authorized, clean tree only |
| `scripts/c3_preflight_gate.py` | Pre-spend preflight gate | see script help | Free; does not itself authorize a run |
| `scripts/validate/validate_submission.py` | Offline course-compliance gate (34 artifacts, YAML/JSONC, requirements schema, trace paths, prompts, ADRs, docs secret scan) | `python scripts/validate/validate_submission.py` | Free, offline |
| `scripts/gen_cand01_batch_16run_specs_v3.py` | Spec generator / `--check` | `--out <dir> --check` | Free; `--check` is path-sensitive on this checkout |
| `scripts/quality_evidence_check.py` | Evidence consistency check | see script help | Free |
| `scripts/c3_build_manifest.py` | Build `MANIFEST.sha256` | see script help | Free; changes frozen manifest only under an approved freeze |
| `sha256sum` | Frozen-byte verification | `sha256sum -c MANIFEST.sha256` | Free, read-only |
| `rg` / `grep` / `find` | Inspection | e.g. import-boundary greps | Free, read-only |
| OpenCode (1.18.29) | Coding agent runtime | `opencode` | Version read from `~/.opencode/package.json`; `opencode --version` failed with `EROFS` opening its log, so the runtime invocation is `NOT_VERIFIED` |

## 3. Prohibited tool use

- No `curl`, `wget`, or direct HTTP calls to vendors/LLM providers during
  verification.
- No `pip install`, `uv add`, `poetry add`, or dependency upgrade without
  approval.
- No `docker compose up`, no live benchmark, no provider SDK call, and no
  `scripts/token_benchmark.py run` without explicit paid-run authorization.
- No `git push --force`, history rewrite, tag move, or destructive shell command
  (see `AGENTS.md` §5/§10).
- No MCP server addition without approval and a manifest update.

## 4. Verification status

| Item | Status |
| --- | --- |
| MCP inventory empty | verified by config/file/dependency search |
| Tool commands in §2 | verified except `opencode --version` (`NOT_VERIFIED`, `EROFS` on its log path) |
| Permission enforcement of the tool list | `NOT_VERIFIED`; `.opencode/permissions.jsonc` is documented-only |
