# TradingAgents WebUI Risk List

Status: **Approved for documentation by the human owner on 2026-11-05.** No risk is accepted or waived. Each mitigation is planned, not executed. A risk remains open until its verification is recorded in `docs/architecture/evaluation-logbook.md`.

| ID | Category | Risk | Impact | Likelihood | Mitigation | Status |
| --- | --- | --- | --- | --- | --- | --- |
| WEB-RISK-001 | Security | A localhost UI without authentication is reachable by a malicious page or DNS rebinding. | Unauthorized runs, artifact reads, provider spend. | Medium | Loopback bind; Host/Origin checks; CSRF token; no wildcard CORS; CSP. | Open — mitigation planned |
| WEB-RISK-002 | Security | Provider keys leak through an event, error, log, report, or download. | Credential compromise and financial loss. | Medium | Server-only source; allowlisted serialization; redaction; response scans. | Open — mitigation planned |
| WEB-RISK-003 | Security | A client-supplied identifier escapes the artifact root. | Arbitrary file read or overwrite. | Medium | Hash ids; root allowlist; `safe_ticker_component`; traversal tests. | Open — mitigation planned |
| WEB-RISK-004 | Security | Model, tool, or announcement text injects HTML/script. | Session compromise or misleading UI. | High | `rehype-sanitize`; no raw HTML; URL allowlist; CSP; XSS tests. | Open — mitigation planned |
| WEB-RISK-005 | Concurrency | Two runs race on the global configuration or decision log. | Corrupted memory, cross-run config. | Medium | Single-run lock; 409; one worker; invariant test. | Open — mitigation planned |
| WEB-RISK-006 | Correctness | The web stream path drifts from the CLI in sections, cancellation, or artifacts. | Different results for the same inputs. | Medium | Contract tests against CLI behavior; reuse `write_report_tree`; artifact matrix. | Open — mitigation planned |
| WEB-RISK-007 | Correctness | The web layer infers a rating or converts `REVIEW` to `Hold`. | Review becomes a tradeable signal. | Low | Reuse `process_signal`/`is_review`; no alternate parser; negative test. | Open — mitigation planned |
| WEB-RISK-008 | Correctness | An absent portfolio is treated as a flat book. | Wrong sizing advice. | Low | `PortfolioContext`; three-state request model; invariant test. | Open — mitigation planned |
| WEB-RISK-009 | Recovery | Server restart loses an active run while the browser shows stale state. | Duplicate runs; misinterpretation. | Medium | Process-lifetime policy; "run no longer available"; checkpoints remain. | Open — mitigation planned |
| WEB-RISK-010 | Recovery | Cancellation clears a checkpoint or writes a decision. | Lost recovery point; corrupted memory. | Low | Skip both calls; `finally end_checkpoint`; invariant test. | Open — mitigation planned |
| WEB-RISK-011 | Operations | SSE buffer grows for a slow/disconnected client. | Memory exhaustion. | Medium | Count and byte caps; bounded subscriber queue; snapshot fallback. | Open — mitigation planned |
| WEB-RISK-012 | Operations | Long analyses hit browser or proxy idle limits. | Dropped event streams. | Medium | Loopback direct; 15 s heartbeat; reattachment. | Open — mitigation planned |
| WEB-RISK-013 | Dependencies | FastAPI/Uvicorn or the npm tree adds supply-chain/license risk. | Vulnerabilities, license issues, packaging breakage. | Medium | Dependency approval; lockfile; audit; minimal package set. | Open — approval pending |
| WEB-RISK-014 | Packaging | The package or static assets are missing from the wheel. | Clean install fails or UI is absent. | Medium | `package-data`; wheel inspection; clean-install health check; loud API-only mode. | Open — mitigation planned |
| WEB-RISK-015 | Governance | Documentation claims approval, tests, or implementation that did not occur. | False completion evidence. | Low | Status labels; planned vs actual separation; honest logbook. | Open — mitigation planned |
| WEB-RISK-016 | Data integrity | History presents a partially written run as complete. | Misleading result. | Medium | Derive status from explicit artifacts; show partial; no synthesis. | Open — mitigation planned |
| WEB-RISK-017 | Concurrency | The worker thread blocks the event loop or the cancel path. | UI freezes; cancellation delayed. | Medium | Single-worker executor; `call_soon_threadsafe`; 30 s `cancelling` state; no thread kill. | Open — mitigation planned |
| WEB-RISK-018 | Operations | A backtest runs for a long time with no stop control. | Slot occupied; user confusion. | Medium | Explicit UI copy; `run_id` resume; single-run policy. | Open — design choice with residual risk |
| WEB-RISK-019 | Frontend | React/Vite/Tailwind/Radix dependency drift or build breakage. | UI unavailable or insecure. | Medium | Lockfile; Node 22 LTS; CI build; dependency audit. | Open — mitigation planned |
| WEB-RISK-020 | Contract | OpenAPI-generated types drift from the backend. | Runtime type errors. | Medium | CI regenerates and fails on diff; contract tests. | Open — mitigation planned |
| WEB-RISK-021 | Evaluation | Architecture experiments (latency, packaging, browser matrix) are not run. | Unverified performance/packaging claims. | High | Record as planned; run before claiming verified. | Open — not evaluated |
| WEB-RISK-022 | Security | Another local process can reach the loopback port. | Unauthorized local access. | Medium | No secrets in responses; Host/Origin/CSRF; document the boundary; no network bind. | Open — residual risk |

## Review triggers

- Any new dependency, packaging change, or CI change.
- Any change to the single-run rule, cancellation, checkpoint handling, or history reads.
- Any change to the key, path, Host/Origin/CSRF, or rendering boundary.
- Any proposal to add concurrency, persistence, authentication, execution, or network exposure.
- Any claim of passing latency, packaging, browser, or security evaluation without a recorded result.
