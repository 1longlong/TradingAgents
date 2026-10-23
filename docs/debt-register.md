# Technical Debt Register

| ID | Category | Evidence / consequence | Next action / review trigger | Status |
| --- | --- | --- | --- | --- |
| DEBT-001 | Evaluation debt | Requirements registry and architecture artifacts are still empty | Populate through the requirements/design process; schema failure remains blocking | Open |
| DEBT-002 | Evaluation debt | No approved runtime semantic evaluator, fixed dataset, or quality thresholds | Approve these on a base revision before any runtime prompt/model change; the semantic gate fails closed until then | Open |
| DEBT-003 | Guardrail debt | GitHub branch protection/ruleset settings are external to repository files | Release already requires reviews, but its required-status-check list is empty; require `blocking-gate` after the reviewed workflow is pushed | Open |
| DEBT-004 | Evaluation debt | Four historical baseline failures, recorded in bug-diary.md | Reproduce and repair in a separately scoped change; do not waive them automatically | Open |
| DEBT-005 | Evaluation debt | Full-source mypy reports 202 errors in 27 files; Bandit reports 5 findings requiring triage | Record actual findings and fix them explicitly; do not suppress the checker or downgrade its result | Open |
| DEBT-006 | Human/cognitive debt | Preparation originally remained uncommitted by user instruction | User subsequently authorized a single preparation commit; commit authorization does not establish final governance review | Commit authorized; review pending |
| DEBT-007 | Hidden dependencies | Broad baseline runtime dependency ranges are not a locked environment | Capture resolved dependency versions in CI run artifacts and review updates and audit results | Open |
| DEBT-008 | Evaluation debt | Regular PR regression runs do not exercise credential-dependent live APIs | Plan authorized live verification before declaring those requirements verified; skipped API tests are not passing live evidence | Open |

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
