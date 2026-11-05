# TradingAgents WebUI Permission Model

Status: **Approved for documentation by the human owner on 2026-11-05.** Implementation still requires `[safety-approved]` and `[governance-approved]` where applicable. This document defines the WebUI runtime permission boundary and its relationship to the coding-agent roles.

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
