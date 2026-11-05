# Technical Debt Register

| ID | Category | Evidence / consequence | Next action / review trigger | Status |
| --- | --- | --- | --- | --- |
| DEBT-001 | Evaluation debt | Architecture design and Iteration-1 implementation are approved; the requirements registry remains `draft` and no GitHub test-plan/safety/governance markers are recorded | Align requirements statuses/evidence in a separate reviewed change; record GitHub review markers if CI gating is used | Implementation approved; registry/markers pending |
| DEBT-002 | Evaluation debt | No approved runtime semantic evaluator, fixed dataset, or quality thresholds | Approve these on a base revision before any runtime prompt/model change; the semantic gate fails closed until then | Open |
| DEBT-003 | Guardrail debt | GitHub branch protection/ruleset settings are external to repository files | Release already requires reviews, but its required-status-check list is empty; require `blocking-gate` after the reviewed workflow is pushed | Open |
| DEBT-004 | Evaluation debt | Four historical baseline failures, recorded in bug-diary.md | Reproduce and repair in a separately scoped change; do not waive them automatically | Open |
| DEBT-005 | Evaluation debt | Full-source mypy reports 202 errors in 27 files; Bandit reports 5 findings requiring triage | Record actual findings and fix them explicitly; do not suppress the checker or downgrade its result | Open |
| DEBT-006 | Human/cognitive debt | Preparation originally remained uncommitted by user instruction | User subsequently authorized a single preparation commit; commit authorization does not establish final governance review | Commit authorized; review pending |
| DEBT-007 | Hidden dependencies | Broad baseline runtime dependency ranges are not a locked environment | Capture resolved dependency versions in CI run artifacts and review updates and audit results | Open |
| DEBT-008 | Evaluation debt | Regular PR regression runs do not exercise credential-dependent live APIs | Plan authorized live verification before declaring those requirements verified; skipped API tests are not passing live evidence | Open |
| DEBT-009 | Architecture debt | Web framework, event transport, frontend stack, and package path were selected in ADR-002 through ADR-004 and implemented for Iteration 1 | No further design action for the read-only slice; later iterations still need their own ADRs | Resolved for Iteration 1 |
| DEBT-010 | Verification debt | The official requirements schema gate was unrun at drafting time; it has since passed in the iteration-1 test environment | No further action for the schema gate itself; rerun after any registry change | Resolved 2026-11-05 |
| DEBT-011 | Governance debt | `docs/architecture/permission-model.md` was filled but has not received a human review verdict | Review the runtime permission matrix and record the verdict before implementation | Documented; review pending |
| DEBT-012 | Evaluation debt | Architecture experiments EVAL-01 through EVAL-10 (latency, browser, clean install, full security/quality evaluation) have not been run; the WebUI test suite and frontend build have been executed | Execute and record the remaining experiments in `docs/architecture/evaluation-logbook.md`; do not claim planned checks as passing | Partially evaluated |
| DEBT-013 | Dependency debt | FastAPI, Uvicorn, and the npm tree are installed for local verification; npm audit reports 0 vulnerabilities, but project dependency/license approval and pip-audit are still pending | Complete dependency, license, and advisory approval before merge/release | Approval pending |
| DEBT-014 | Packaging debt | The wheel contains `static/index.html` and the `tradingagents-web` entry point, but a clean-install health check in a fresh environment has not been run | Run the clean-install smoke before release | Partially verified |
| DEBT-015 | Verification debt | Frontend Vitest and Playwright suites are not implemented/executed; behavioral browser XSS, browser matrix, and i18n report-language independence remain unverified | Add the frontend harness and execute it before claiming those criteria verified | Open |
| DEBT-016 | Environment debt | Local verification used Python 3.14.3, outside the CI matrix (3.10–3.13) | Run the CI matrix before merge/release | Open |
| DEBT-017 | Performance debt | Vite reports a 533 kB main JS chunk (above the 500 kB warning threshold) | Consider route-level code splitting; not required for Iteration 1 | Open |

Prompt rot, hallucinated dependencies, untouchable code, agent-induced bloat, and other categories should be recorded when supported by actual evidence. No entry implies a defect has been repaired or accepted.

## Security scanner evidence — 2026-10-24

These are inherited scanner findings requiring triage, not confirmed exploitability or approved exemptions.

| Check | Location | Finding |
| --- | --- | --- |
| B608 | `src/tradingagents/agents/analysts/market_analyst.py:25` | Possible SQL injection vector through string-based query construction. |
| B310 | `src/tradingagents/dataflows/reddit.py:190` | Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected. |
| B314 | `src/tradingagents/dataflows/reddit.py:191` | Using xml.etree.ElementTree.fromstring to parse untrusted XML data is known to be vulnerable to XML attacks. Replace xml.etree.ElementTree.fromstring with its defusedxml equivalent function or make sure defusedxml.defuse_stdlib() is called |
| B310 | `src/tradingagents/dataflows/stocktwits.py:90` | Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected. |
| B608 | `src/tradingagents/graph/checkpointer.py:99` | Possible SQL injection vector through string-based query construction. |

Dependency consistency and the current 122-version advisory audit passed. The application source has not been modified to clear type/security/regression findings.
