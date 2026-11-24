# TradingAgents: Supervised Development of an AI Research Application

**Team project report**

**Team:** Fanlin Meng (60749983, team leader); Shengjin Duan (60599024); Yiwen Wang (60536848); Tianqi Wang (60726054); Zhuoran Ruan (60946340).

**Project foundation:** TradingAgents v0.5.0, extended with research controls, usage observability, a browser workspace, simulated trading and fault-tolerance improvements.

## 1. Executive summary

TradingAgents is an AI-enabled investment research application. It combines specialist analysis, an investment debate, a trading proposal and risk review into an advisory assessment. We extended the existing open-source TradingAgents system to improve research controls, execution visibility and usability while preserving its command-line and Python interfaces. Alongside the product work, the project established a supervised OpenCode development process linking requirements, architecture, implementation, verification and human decisions.

The project has four connected workstreams. The core work adds deterministic evidence-quality controls and evidence-aware debate termination. The observability work records provider usage and supports controlled experiments on finalisation and tool batching. The WebUI exposes analysis, reports, historical artifacts, backtests and simulated account operations through a browser. The governance work defines role permissions, review boundaries and CI checks, including prior test approval and fixed-set semantic evaluation.

The most important design decision is the separation of authority. Language models interpret evidence and generate arguments; deterministic components decide whether evidence is usable, whether further calls fit a budget, whether a final signal is permitted and whether a simulated order may execute. A persuasive explanation cannot grant itself execution permission or turn missing evidence into a verified fact.

Verification combined deterministic offline regression, interface checks, native permission probes and controlled model experiments. A complete maintenance regression on 25 November 2026 passed **5,643 tests and 323 subtests**, with three skips. A later governance-cleanup run exposed two failures; the new path assertion was corrected and its module passed, while a submission-layout failure remains open. Section 14 separates these runs and their results. Historical model experiments identified opportunities to reduce token use alongside reliability problems requiring further work.

The resulting application brings research, progress monitoring, historical reports, backtesting and simulated account workflows into a single browser workspace. Further development will focus on service resilience, long-running task recovery and broader evaluation of research quality and resource use.

<div style="break-after: page; page-break-after: always;"></div>

## 2. Team, responsibilities and contribution accounting

### 2.1 Responsibilities and coordination

The five-member team organized development into complementary workstreams covering research controls, observability, WebUI integration, simulated trading and fault tolerance. Fanlin Meng led coordination across these areas, aligning requirements, integration dependencies and delivery priorities. OpenCode supported implementation, verification and documentation, with team members directing development and reviewing the results.

**Fanlin Meng (60749983) — team leader, WebUI requirements and project coordination.** Led WebUI requirements discovery, TUI capability mapping and browser workflow design; coordinated task allocation, scope decisions, integration, review readiness and delivery organization. Supervised the analysis wizard, live activity and reconnection, history/reports, backtest progress, bilingual interface and Web adapters, including the simulated-account interface. This work brought the team's core capabilities together in the browser workspace.

**Shengjin Duan (60599024) — simulated-trading requirements and subsystem.** Developed the deterministic path from an advisory research output to simulated execution: safety rules, engine-issued authorization, human approval, sizing, portfolio accounting, audit integrity, persistence/reset and clock-driven walk-forward backtesting. Maintained the boundary between research recommendations and execution authority.

**Yiwen Wang (60536848) — evidence quality and debate-control requirements.** Developed the Data Quality Gate, evidence validation and provenance, deterministic dynamic debate termination, conflict handling, truthful participation, budget/usage controls and downstream output/confidence restrictions. Connected requirements and invariants to offline verification and the Phase 4A comparison.

**Tianqi Wang (60726054) — token observability and controlled optimization.** Developed per-agent/tool usage attribution, single-pass structured finalization, batch-macro evaluation, experimental memory isolation and the benchmark measurement and registration workflow. Analyzed token consumption, fallback behavior and reliability across experimental configurations.

**Zhuoran Ruan (60946340) — fault tolerance, degradation and execution reliability.** Developed vendor-failure classification, bounded retries and circuit breakers, request-context isolation, structured-output recovery, bounded analyst tool loops and explicit fallback behavior. Added compatible checkpoints, atomic report/state writes and integration checks while preserving data-quality and trading controls.

Fanlin coordinated dependencies across the five workstreams: evidence and debate controls feed the research graph; fault tolerance protects its execution; the simulated subsystem consumes accepted research output through its safety gateway; the WebUI exposes those capabilities; observability supports diagnosis and controlled evaluation. Each member remained responsible for explaining and reviewing their own contribution. The Plan, Build, Verify and Docs roles describe process activities, while individual review decisions remain recorded in the review memo.

<div style="break-after: page; page-break-after: always;"></div>

### 2.2 Recorded effort and relative contribution

Contribution is assessed on a common effort-unit scale across five sprints. The allocation covers requirements analysis, design, implementation, verification, documentation and project coordination. Fanlin Meng's contribution includes the additional coordination and organization responsibilities of the team leader. The table summarizes each member's effort and relative contribution.

| Student        | Sprint 1 | Sprint 2 | Sprint 3 | Sprint 4 | Sprint 5 |   Total |   Weight |
| -------------- | -------: | -------: | -------: | -------: | -------: | ------: | -------: |
| Fanlin Meng    |       12 |       12 |       10 |       10 |       12 |      56 |     1.12 |
| Shengjin Duan  |       10 |       10 |       10 |       10 |       10 |      50 |     1.00 |
| Yiwen Wang     |       10 |       10 |       10 |       10 |       10 |      50 |     1.00 |
| Tianqi Wang    |        8 |        9 |       10 |       10 |       10 |      47 |     0.94 |
| Zhuoran Ruan   |        8 |        9 |       10 |       10 |       10 |      47 |     0.94 |
| **Team total** |   **48** |   **50** |   **50** |   **50** |   **52** | **250** | **5.00** |

The mean effort is (56 + 50 + 50 + 47 + 47) / 5 = **50 effort units**. A member's relative contribution equals that member's total effort divided by the mean:

- Fanlin Meng: 56 / 50 = **1.12**.
- Shengjin Duan: 50 / 50 = **1.00**.
- Yiwen Wang: 50 / 50 = **1.00**.
- Tianqi Wang: 47 / 50 = **0.94**.
- Zhuoran Ruan: 47 / 50 = **0.94**.


<div style="break-after: page; page-break-after: always;"></div>

## 3. Application problem, users and scope

A user researching a stock needs to inspect market evidence, understand competing arguments and see how a recommendation was reached. An LLM can summarize and compare information, but it can also overstate confidence, cite unavailable material, confuse dates or continue consuming resources without producing a useful final assessment. The project therefore treats research quality, operational visibility and controlled failure as engineering concerns alongside the model-generated explanation.

The application serves a local, single-user workflow. The user selects an instrument and analysis date, chooses relevant analysts and model settings, supplies optional portfolio context and starts research. Progress and intermediate reports remain visible as the workflow advances. The result can be inspected as a report, saved through the existing artifact layout and revisited through history. A separate serial backtest runs the established analysis across ticker/date cells. These features support investigation; they do not promise profitable decisions.

Development began with TradingAgents v0.5.0. Preserving its CLI and Python interfaces allowed existing workflows to continue while new modules added browser access and stronger controls. Integration brought the research, observability, simulated-trading and fault-tolerance workstreams together behind a consistent user experience. Experiment records retain the configuration and implementation versions used for each measurement to support reproducibility.

The simulated-trading subsystem is an independent extension with a simulated portfolio, deterministic checks, human approvals, audit records and walk-forward execution. Its browser integration composes the existing subsystem. It does not connect the project to a real brokerage, and its approvals must not be confused with the application's advisory investment ratings.

The project scope focuses on local research and simulated execution. Production threshold tuning, real broker execution, unattended live trading and multi-user deployment remain outside this scope. Provider changes and further live benchmarking require a separate review of compatibility, cost and verification needs.

A useful scope correction arose during development: prototype controls needed to match available business operations. We checked the browser design against existing core capabilities and identified the adapters needed for integration. This prioritized capability parity, error visibility and clear workflows over decorative dashboard content.

<div style="break-after: page; page-break-after: always;"></div>

## 4. Requirements engineering and change control

The requirements registry combines a machine-readable product description with individually identified requirements. Its schema validates structure; the entries describe behavior, invariants, verification, priority and sources. The registry contains 80 requirements covering product behavior and development governance, including prior test approval and protected semantic evaluation. These governance requirements extend the review process while preserving the existing product acceptance thresholds.

Requirements are grouped by responsibility: evidence quality, debate control and conflict handling, browser capabilities, simulated trading and usage observability. Cross-cutting requirements cover measurement, compatibility, cost, security and offline verification. Stable identifiers connect these workstreams to architecture decisions, implementation responsibilities and acceptance checks.

MoSCoW priorities guided scope decisions. Evidence gating, fail-closed behavior and credential protection were classified as Must requirements because they establish essential safety boundaries. Compatibility and presentation refinements were assessed against user value, implementation cost and acceptance criteria. This helped separate the basic working analysis chain from improvements that could follow in later iterations.

A fit criterion must identify something a machine can check. Examples include a blocked gate never yielding a directional final signal, an invalid API request being rejected without leaking submitted secrets, and a malformed semantic report blocking the change. General aspirations such as understandable research or lower cost need a defined rubric, measurement method and scope before becoming verified results.

Change control follows the chain from requirement to design, source, test and observation. The trace matrix records enforcing components and evidence. The invariant register adds operational fallback actions. When a test exposes an architectural weakness, the correction updates the relevant decision and trace rather than only patching the immediate symptom.

Requirement changes were most visible in per-analysis debate configuration, editable provider defaults, per-date backtest progress and stronger CI evidence checks. These changes came from usage feedback and exposed ambiguities in the original interaction design. Volatility was reviewed through individual change episodes; a sprint-level numerical series was not collected. The next iteration should record accepted additions, modifications and removals at each requirement baseline, together with their reasons and owners, to support quantitative process evaluation.

<div style="break-after: page; page-break-after: always;"></div>

## 5. Architecture candidates and system boundaries

The selected architecture retains the existing LangGraph research flow and adds deterministic control components around model-generated work. It separates domain policy from UI presentation, provider adaptation and evidence persistence. This choice allowed the team to test safety behavior without requiring a paid model to produce the same sentence twice.

| Candidate                                              | Main benefit                                                        | Principal weakness                                                         | Outcome                                                             |
| ------------------------------------------------------ | ------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Deterministic evidence gate and rule-based termination | Auditable decisions, offline testing and explicit fallback behavior | Requires careful adapters and boundary tests; cannot guarantee model truth | Selected                                                            |
| LLM judges evidence quality and decides when to stop   | Flexible natural-language reasoning                                 | Nondeterministic authority, weak reproducibility and additional cost       | Rejected for authoritative controls                                 |
| Fixed-round research without an evidence gate          | Simple and close to the inherited workflow                          | Weak control of evidence failures and optional debate spend                | Retained only as an applicable comparison or compatibility baseline |
| Best-effort usage accounting with a wall-clock limit   | Small implementation effort                                         | Missing usage can hide overspend; summaries may be stranded                | Rejected as the sole budget mechanism                               |

The architecture evaluation used determinism, fail-closed safety, compatibility, auditability, budget behavior, testability and point-in-time integrity as qualitative decision criteria. These criteria favored explicit policy components over model-controlled authority. Integration also standardized component ownership and the organization of implementation and verification work across the separate workstreams.

The system separates responsibilities into five main areas. The research core owns orchestration, evidence, debate, provider clients, reporting and memory. The terminal interface preserves established workflows. The WebUI owns browser interactions, public API contracts and execution-state presentation. The simulated-trading subsystem manages account behavior, while the safety gateway controls execution authorization. Offline and live verification are organized around the same boundaries.

The dependency direction matters: the research core does not import browser presentation logic. The WebUI adapts core interfaces and projects execution state into public snapshots and events. The simulated subsystem consumes research output through its own deterministic pipeline rather than treating prose as an executable instruction.

The architecture trades concurrency for simpler correctness. A single active operation protects shared configuration and state in the local application. Increasing concurrency would require an explicit design for configuration isolation, persistence and memory ownership, not merely removing the active-slot check.

<div style="break-after: page; page-break-after: always;"></div>

## 6. AI context, assembly and authority

The research pipeline uses language models for interpretation and argument generation. Analysts interpret tool results; researchers compare bullish and bearish arguments; downstream roles generate a plan and assess risk. The context supplied to those roles includes identity, standing constraints, retrieved evidence, conversation history, resumable state and the current task. Separating these layers preserves their different provenance and authority.

Identity and role instructions originate in the agent factories. Standing constraints include date, language, schema and permitted-evidence instructions. Tool responses and evidence manifests supply external material. Graph state carries prior reports, debate history and unresolved conflicts. Checkpoints and filtered decision memory support continuity. The current ticker, date and optional portfolio context define the immediate task. External text cannot override the standing constraints or grant tool permissions.

Current context assembly is distributed across factories, prompt templates, graph state and structured-output helpers. Analysts receive system text and messages; researchers receive gate-aware evidence and debate history; managers receive plans, portfolio context and risk discussion. Optional-call budgets control debate resource use, while context-window management addresses the amount of material in an individual request. A universal token-aware compactor remains a proposed extension.

The proposed context-management design defines W as the documented model context limit, capped at 131,072 tokens. It reserves 8,192 tokens for output and 4,096 for critical constraints. Compaction begins at 70% of the remaining input budget and becomes mandatory at 85% before further history is appended. These initial design parameters provide a concrete basis for future implementation and evaluation.

The proposed assembly pipeline validates inputs, deduplicates by identity, preserves conflicting evidence, prioritizes constraints and task data, counts the rendered context, compacts old history and recounts. After compaction or resume, it re-injects role, date, gate authority, output schema and task constraints verbatim. If those cannot fit, the target behavior is to stop before the model call, rather than truncate the safety instructions. Implementing and validating this target needs a future approved task.

Development instructions and application prompts have separate lifecycles. A static startup instruction establishes the OpenCode development workflow, while agent factories and runtime helpers assemble the research requests. Recording the source version of active prompts makes application behavior traceable and supports targeted semantic evaluation when those prompts change.

<div style="break-after: page; page-break-after: always;"></div>

## 7. Deterministic safety boundaries

The data-quality gate turns validated evidence and policy into an explicit quality result. Missing, contradictory, stale or failed input must not silently become normal evidence. The gate's result and reason codes are propagated downstream so that later model prose cannot erase the original limitation. Its value lies in the complete path to the final report, rather than the existence of a gate node alone.

A blocked result must prevent a directional final recommendation. Output guards constrain ratings and executable-looking content, while confidence policies prevent degraded evidence from retaining unjustifiably strong confidence. An unreadable or unrecognized rating is handled as `REVIEW`, which must remain distinct from a valid `Hold`. This avoids converting a parsing failure into an apparently deliberate neutral investment judgment.

Citation allowlists and evidence identifiers provide traceability, but a model can cite an existing identifier while misstating the date, unit or implication of an observation. This defect led to a stronger emphasis on preserving identity, time and factual roles in claim checks. It also showed why a citation-presence check alone cannot establish factual fidelity.

The simulated-trading boundary is separate. A research rating is input to a deterministic pipeline, not permission to execute. The safety engine remains the executor gateway, and only its approved path can reach the simulated executor. Human approval, quote validity, portfolio state, sizing rules and idempotency are evaluated independently of the model's confidence. Real broker operations remain outside the implemented project scope.

| Boundary              | Authoritative mechanism                           | Failure response                                |
| --------------------- | ------------------------------------------------- | ----------------------------------------------- |
| Evidence acceptance   | Validation and gate policy                        | Block or degrade with explicit reasons          |
| Final research output | Rating parser, output guard and confidence policy | Restrict unsafe signal; retain uncertainty      |
| Optional debate work  | Budget admission and termination rules            | Stop further optional work and preserve wrap-up |
| Simulated execution   | Safety engine and issued approval                 | Reject or leave pending; do not execute prose   |
| Files and credentials | Validated paths, redaction and permission checks  | Deny access or return a safe categorized error  |

Positive and violation cases exercise these boundaries, including blocked evidence, malformed ratings, exhausted budgets and unauthorized execution attempts. Operational fallback actions and ownership are recorded in the invariant register and runtime policy catalog.

<div style="break-after: page; page-break-after: always;"></div>

## 8. Debate termination, budgets and observability

A fixed number of debate rounds is easy to understand but can repeat old arguments or spend resources after useful evidence has stopped changing. The project's dynamic evaluator observes structured debate state, evidence novelty, conflicts and budget conditions. It produces an explicit stop reason instead of asking a model to decide whether further reasoning is worth its own cost.

Evidence-aware termination must preserve enough capacity to summarize. Optional-call admission therefore considers reserve requirements before work begins. Token and time estimates are not relabeled as exact provider measurements. Actual usage, missing attribution and provider behavior remain observable even when execution terminates early. A stop should leave an inspectable result or explicit failure, not a silently incomplete report.

The conflict lifecycle records observed disagreements using structured inputs. Identity generation, deduplication, resolution and escalation are deterministic. A disagreement invented by model prose does not automatically become a trusted conflict record; references need to satisfy the evidence contract. The evaluator can then distinguish repeated unresolved material from genuinely new supported information.

Backward compatibility is deliberate. Disabling the dynamic feature retains the established fixed-round behavior where specified. Custom policy settings must affect run identity and checkpoint compatibility, while unchanged default settings preserve the corresponding baseline behavior. This protects users from accidentally resuming a run under a materially different debate policy.

Usage observability serves a different purpose from termination. The ledger and attribution machinery record which model role generated usage, including raw structured attempts, fallbacks and otherwise easy-to-miss calls. Missing usage is not zero usage. Cached input is already part of input usage and must not be added again when calculating totals. Reliable attribution is a prerequisite for meaningful optimization claims.

The single-pass and batch-macro experiments examine two possible reductions in repeated work: combining prose and structured finalization, and reducing repeated tool-call overhead. Their runtime switches, measurement apparatus and historical results must remain distinct from the dynamic-termination feature. A token saving measured for one switch and one model does not establish an improvement for every debate policy.

<div style="break-after: page; page-break-after: always;"></div>

## 9. WebUI and backend integration

The WebUI translates existing research capabilities into browser interactions. It is not a second implementation of the agents. FastAPI endpoints validate public requests; runtime adapters invoke the core graph; a coordinator controls the active operation; projectors convert internal events into bounded public data; artifact readers expose supported historical results. The React frontend renders those contracts and handles user navigation, drafts and progress.

The analysis form loads server configuration and credential status without exposing keys. Provider and model environment values are defaults for interactive analysis, rather than a restriction that forces a single provider into the selector. Model changes must remain consistent with provider-specific settings: an endpoint or thinking option belonging to one provider must not silently migrate to another. Backtests retain the documented server-default behavior, which is a different interface contract.

Execution visibility developed from a simple running state into stage-aware activity. Users can follow messages, tool calls, role activity and completed reports, switch stage tabs and inspect earlier content. Reload and reconnect restore the authoritative snapshot rather than starting another analysis. Closing a page does not mean cancellation; cancelling does not guarantee that an already-running provider request is interrupted immediately.

The UI also exposes report history, research-audit details, policy comparison and analysis backtests. These views have different meanings. Audit explains recorded evidence and gate decisions. Policy comparison replays predefined offline scenarios against policies and must be labelled as such. It is not a comparison of real investment strategies or a substitute for configuring a live analysis. Analysis backtesting executes serial ticker/date cells and reports their actual progress and settlement.

Simulated account screens connect to the existing trading core through necessary APIs. Account balances, decisions, approval expiry, reset confirmation, audit entries and walk-forward results are represented as operations with authority boundaries. A browser button cannot bypass an engine-issued approval. Presentation simplification keeps material warnings and confirmation steps while removing decorative counts and repetitive explanation.

The interface supports Chinese and English labels. Instrument symbols, source reports, provider diagnostics and literal control tokens retain their identities instead of being mistranslated. Markdown tables and long content are contained so that reports cannot expand over the navigation panel.

<div style="break-after: page; page-break-after: always;"></div>

## 10. State, persistence and recovery

Long research runs need continuity, but persistent state can also preserve mistakes. The design distinguishes model conversation, decision memory, graph checkpoints, saved reports, usage records and simulated account data. Each has a different owner and lifetime. Treating them as one general-purpose memory store would weaken both reproducibility and recovery safety.

Graph checkpoints support resuming interrupted analysis. Run identity includes relevant configuration and policy information so that an incompatible run is not resumed accidentally. Portfolio fingerprints distinguish absent portfolio context from an explicitly empty portfolio. On restore, confidence and gate-related state are sanitized before downstream use. Recovery must not turn a previous partial result into a newly authorized decision.

Decision memory is relevant only when its identity and point-in-time constraints match the requested analysis. Later knowledge must not leak into an earlier analysis date. Experimental memory isolation is particularly important: one measured arm must not inherit another arm's decisions, and a supposedly empty baseline must remain unchanged. Historical memory-pollution defects motivated stronger ownership and manifest checks.

Saved reports and historical artifacts are read through constrained paths. User-provided JSON content is input data, not a capability to open an arbitrary server path. Artifact discovery, downloads and checkpoint operations require validation and redaction. Readers validate supported formats and expose parsing errors explicitly, keeping missing data distinguishable from available report content.

For browser continuity, event buffers and snapshots restore the current view after reconnecting to the running server. This design supports navigation and temporary connection loss during a long analysis. Durable background execution across server restarts would require a persistent job service and remains outside the current implementation.

The simulated subsystem owns account state and append-only audit records. Resume parameters, account identity and execution epochs protect walk-forward continuation. Audit corruption, state ownership conflicts and post-fill persistence failures must fail closed or surface explicitly. A restart does not restore stale pending approval as new execution authority.

Atomic file replacement protects individual writes, while the local single-active-operation design limits overlapping research tasks. Account and audit rules handle the simulated subsystem's separate persistence boundaries. Retention, privacy and ownership are documented in the memory/state design. Concrete error responses and recovery actions are listed in the runtime policy catalog.

<div style="break-after: page; page-break-after: always;"></div>

## 11. Supervised development process

The development workflow separates discovery, planning, implementation and verification. OpenCode first examines the current system, requirements and architecture constraints, then proposes a bounded plan covering affected interfaces, requirement identifiers, positive and negative cases, steps and risks. Human approval is required before implementation and when scope or safety assumptions change. This workflow provides a consistent structure for subsequent development; the historical evidence gaps are discussed below.

Build then changes only the approved ownership paths. The team uses the existing baseline as a constraint, preserving user changes and public contracts. Tests evaluate required behavior and violation cases. A separate verification role checks evidence rather than trusting the implementation's self-description. Human review at the relevant boundary records what was accepted and what remains unresolved.

A typical maintenance example was the WebUI's misleading failure message. The symptom initially appeared to be a model-provider problem, but the traceback identified Yahoo market-data throttling. Investigation narrowed the correction to error classification and visibility while preserving data-source behavior. The revised message distinguished temporary vendor failure from a missing model key. Diagnosing the failing layer before changing code reduced unnecessary implementation work.

Another example concerned configuration semantics. The analysis selector initially offered only the provider configured in the environment. Usage feedback clarified that these values should define defaults while retaining provider selection. The resulting contract separates default values from available choices and prevents incompatible provider options from carrying across a change. Request handling, UI drafts, tests and documentation were updated together.

Governance maintenance followed a separate approved scope. The native permission-path repair required explicit authorization because it affected a protected configuration file. The repair preserved the existing access rights and added bounded compatibility checks. Team members retained ownership of raw session exports and final review decisions, keeping development assistance separate from human accountability.

Process review identified gaps in earlier evidence: some audits were tool-generated, some approval artifacts were missing and some original sessions remained outside the repository. In response, the project introduced stronger approval and logging requirements for future changes. These findings reinforced the distinction between automated diagnosis and human acceptance, and informed stronger traceability controls for subsequent development.

<div style="break-after: page; page-break-after: always;"></div>

## 12. Coding permissions and tool governance

The permission model is deny-by-default and role-specific. Plan and Verify inspect approved material without editing source. Build can change approved implementation paths, while Docs can maintain allowlisted artifacts. Protected rules, secrets, external directories and safety-sensitive changes retain additional restrictions. A file permission is not human approval of a feature or permission to spend money.

Machine-readable permissions alone are insufficient evidence. During maintenance, OpenCode 1.18.29 loaded the configuration but native reads did not match relative whitelist paths. Slash-prefixed absolute paths also failed. A bounded diagnostic showed that the V1 matching resource used a canonical absolute path without the initial slash. This was a configuration compatibility problem, not evidence that broader access was needed.

The repair binds read and edit permissions to the canonical project location at startup. It preserves secret denials, external-directory restrictions, protected-resource behavior and role distinctions. File discovery and content search retain their own permission rules. Explicit configuration loading and root binding ensure that a missing or incorrect binding leaves access denied.

Verification used isolated temporary state, synthetic files and a deterministic local scripted transport. It did not use a real model or student session. All four roles loaded. Sixteen final file operations had the expected outcomes: seven permitted and nine denied. Plan and Verify did not expose editing. Build could perform approved source operations but could not edit protected rules; secret and external reads were rejected. Docs could edit permitted documentation.

The probes established native file-operation compatibility for OpenCode 1.18.29. Filesystem and network isolation remain the responsibility of the execution host, and shell confinement requires separate controls. Runtime upgrades or changes to resource-path formatting therefore require the permission checks to be repeated.

The MCP tool manifest defines allowed capabilities by role. Default verification uses isolated data and excludes real credentials, user runtime data and paid calls. If a configuration becomes incompatible, native editing stops until a reviewed correction restores the intended access rules.

<div style="break-after: page; page-break-after: always;"></div>

## 13. Verification strategy and blocking gates

Verification has structural, regression and behavioral tiers. Structural checks examine imports, ownership, schema, API boundaries and permissions. Regression replays previous suites under network isolation. Behavioral checks examine defined output quality and safety thresholds. A green structural check cannot stand in for a measured model-quality result, and a plausible model answer cannot substitute for a deterministic invariant test.

| Gate                | Implementation and expected blocking behavior                                                                                                                                           |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prior test approval | Independently controlled policy and checks validate authentic approval of the exact test/design snapshot before implementation. Missing, late, revoked or unverifiable evidence blocks. |
| Static analysis     | Lint, source type checking and dependency checks run in CI; architecture, API contracts, security and permission checks cover relevant boundaries.                                      |
| Requirements schema | The consolidated registry validates against its JSON schema, with required references and structural checks.                                                                            |
| Semantic evaluation | Prompt/model changes require fixed-set, candidate-bound observations and passing task, factual and safety thresholds. Missing evidence blocks.                                          |
| Regression          | The prior test suites run; failed prerequisites prevent the aggregate gate from succeeding.                                                                                             |
| AI-use logging      | Relevant changes require meaningful new use records covering the changed paths.                                                                                                         |

The prior-test checker and reviewer policy are controlled independently of the proposed change, reducing the risk of self-authorization. Rollout separates initial gate installation from the changes it will subsequently govern. This establishes the review mechanism before broader maintenance proceeds and keeps the installation exception limited to its intended purpose.

Semantic evaluation uses eight fixed cases and the application's output guards. Evaluation observations identify the provider, quick and deep models, run reference and the versions of the dataset and implementation. The acceptance thresholds are task accuracy 1.0, factual fidelity 1.0 and zero safety escapes on that bounded set. Synthetic observations verify the evaluator's behavior; research quality against real provider outputs has not yet been established through this gate.

Repository protection complements the workflow checks. The last configuration verification confirmed a required aggregate CI check, strict status checks, administrator enforcement and one independent approving review. Merge approval and prior test approval serve different purposes: one accepts a change for integration, while the other establishes that its test/design snapshot was reviewed before implementation.

Together, the gates make structural correctness, regression behavior, semantic quality and human oversight explicit integration criteria. Hosted execution of the pending workflow changes remains part of the delivery plan.

<div style="break-after: page; page-break-after: always;"></div>

## 14. Verification results and interpretation

Maintenance verification on 25 November 2026 used an isolated Python environment with the project source selected explicitly. Provider environment values were cleared, dotenv and bytecode generation disabled, and Python sockets denied. This made the regression deterministic and kept it independent of model credentials, market-data availability and external service costs.

The regression ran with network access blocked, cache creation disabled and concise failure reporting. Keeping external calls out of this suite made failures attributable to application behavior and integration rather than service availability.

| Check                                            | Recorded result                                                                    | Interpretation                                                                                    |
| ------------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Submission-maintenance full regression           | 5,643 passed; 3 skipped; 73 warnings; 323 subtests passed; 87.74 seconds           | Successful full run before the later governance cleanup                                           |
| Governance-cleanup full regression               | 5,654 passed; 2 failed; 3 skipped; 74 warnings; 323 subtests passed; 93.35 seconds | Found a path assertion error and a submission-layout mismatch                                     |
| Governance module after path correction          | 91 passed; 16.96 seconds                                                           | Confirmed the corrected assertion and affected governance checks                                  |
| Earlier checker/evaluator and integration checks | 220 passed; semantic evaluator module 13 passed                                    | Covered approval validation, clock/import behavior and synthetic semantic observations            |
| Whole-tree Ruff, schema and structure            | Pass after governance cleanup                                                      | Static and structural verification                                                                |
| Checker/evaluator scoped mypy                    | Pass, two modules in the maintenance run                                           | Type verification of the changed checker/evaluator scope                                          |
| Independent requirements validator               | Pass, 40/40 items after cleanup                                                    | Required-artifact checks with the three mandatory governance documents retained                   |
| Submission validator                             | 33/34 items; one pending-transcript warning                                        | Open mismatch between expected session-support materials and the simplified deliverable structure |

The three skips covered a DeepSeek-key-dependent test, opt-in live simulated-trading testing and the optional Bedrock dependency. These tests remain outside the offline result. The requirements validator and submission validator examine different artifact inventories, so their totals describe different checks.

Earlier maintenance runs exposed outdated requirement-count expectations, missing traceability, incorrect test-environment resolution and a date-sensitive news-data fixture. Corrections aligned the checks with the requirements, isolated the intended implementation and supplied a fixed test clock. A later verification run also caught inconsistent path normalization in an artifact check. Correcting the comparison restored the affected checks while preserving their acceptance criteria.

The remaining submission-layout failure concerns session-support materials that the validator expects but the simplified deliverable structure omits. A second full regression has not followed the path-assertion correction, so the latest full run remains a failed run despite the successful focused check. Browser verification belongs to the earlier WebUI workstream and was not repeated during governance maintenance. The evaluation logbook preserves the commands, failed attempts and scoped results.

<div style="break-after: page; page-break-after: always;"></div>

## 15. Experimental findings and limits

Evaluation used two complementary approaches. Phase 4A compares the fixed-round baseline with the evidence-gated, dynamically controlled flow through deterministic scripted fixtures. These cases isolate policy behavior, stop reasons and traceability without calling an LLM. They establish control-flow behavior; measuring live-provider savings and assessing human traceability require separate observations.

The token-observability work contains historical live experiments on single-pass finalization and batch-macro tooling. The V3 design used four arms: B, the two-call baseline; AB, batch macro alone; C0, single pass alone; and CC, both switches. Structured output and the downstream setting were held constant. These experiments measured provider-reported usage, not realized investment returns.

For the balanced NVDA, AAPL and XOM blocks, mean total tokens were 218,734 for B, 206,338 for AB, 204,450 for C0 and 181,443 for CC. Each ticker/arm cell had one measured sample. JPM was excluded from the balanced comparison because its CC cell was missing. Keeping the balanced subset separate from pooled observations maintained a consistent basis for comparing the four configurations.

Lower usage did not imply stronger reliability. The historical CC block included provider errors and raw markup in reports; single-pass arms also encountered fallbacks. A failed cell cannot be replaced by a convenient successful retry without preserving the experimental rule and attempt history. Structural completion of a decision field also does not establish factual or investment quality.

The measurements were exploratory and preceded later remediation. With one sample per ticker/arm cell, they provide neither confidence intervals nor a strong basis for statistical ranking. No post-remediation paid rerun or investment-outcome evaluation has been completed. The results therefore guide further engineering work rather than establish the performance of the application or its investment recommendations.

The engineering value of the experiments was discovering measurement requirements: consistent arm configuration, complete attribution, stable memory baselines, verifiable manifests and honest failed-cell accounting. Future live work requires an approved protocol, spending authorization, authentic observations and repeatability.

<div style="break-after: page; page-break-after: always;"></div>

## 16. Defects, human oversight and process improvement

The defect diary records symptoms, reproduction steps, classifications, causes, fixes and invariant gaps. Reviewing these cases helped identify recurring integration weaknesses and improve the development workflow. Defect analysis was qualitative; normalized per-sprint counts and severity-adjusted escape rates were not collected. The following episodes illustrate the changes driven by supervision and verification.

| Observed problem                                                     | What supervision or verification caught                           | Engineering response                                                          |
| -------------------------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Blocked research still exposed unsafe final content                  | A correct gate result did not guarantee safe final output         | Strengthen downstream guards and multiline violation tests                    |
| Yahoo rate limiting appeared as model authentication/contact failure | The traceback identified market-data access, not the selected LLM | Categorize errors, retain correlation references and avoid fabricated data    |
| Backtest failure hid its traceback                                   | A generic banner was not actionable diagnostic evidence           | Log the underlying exception safely and return categorized failure            |
| Long backtests appeared stalled                                      | Serial ticker/date work was invisible between completion events   | Expose per-cell progress and settlement without claiming instant cancellation |
| Experimental arms could share incorrect settings or memory           | Valid-looking labels did not prove distinct execution             | Verify effective configuration, identity, memory isolation and manifests      |
| Permissions parsed but denied intended native reads                  | Syntax and simulator checks did not prove actual matching         | Run bounded native probes and bind the canonical root explicitly              |

These cases reveal a recurring pattern: a correct local component can still fail at an interface. Gate-to-report propagation, environment-to-form defaults, source-to-installed-import resolution and policy-to-native-tool matching all needed integration evidence. The process improved when checks exercised those transitions rather than reproducing only the implementation's internal steps.

Several human interventions clarified business intent. The browser should show the actual execution messages, provider settings should be selectable defaults, per-date backtest work should be visible and unnecessary descriptions should be removed. Such feedback converted ambiguous presentation choices into testable contracts. Review also protected the distinction between simulated and real execution, and between a synthetic comparison and a measured strategy result.

Governance overhead itself became a lesson. Repeated audits and freeze paperwork can consume time without adding independent evidence. The proportionate approach is to retain exact specifications, essential hashes, negative tests and authentic decisions while avoiding duplicate summaries. Documentation was simplified by removing duplicate generated summaries while retaining formal evaluation records, frozen experiment evidence and human decisions.

<div style="break-after: page; page-break-after: always;"></div>

## 17. Individual reflections

### Fanlin Meng — 60749983

In this project, I was responsible for WebUI requirements and overall coordination. My most important lesson was learning to integrate OpenCode into a software engineering process. Initially, I tended to describe an outcome and let it analyze and implement changes. As tasks grew, I found that unspecified scope, constraints and acceptance criteria could be filled in through assumptions. A locally reasonable result could therefore conflict with the project's overall goals. Developers need to define execution boundaries and check whether the implementation preserves their intent. Requirements discussions showed that using an agent makes precise requirements more important. For ambiguous tasks, asking OpenCode to inspect the system, explain its understanding and propose an approach was more effective than immediately requesting code. Expressions such as matching existing capabilities or simplifying an interface needed explicit preservation rules, modification boundaries and observable acceptance conditions. Requirements, architecture constraints and interface descriptions became shared working references rather than documents written after development. As team leader, I also had to connect separate tasks. OpenCode could complete an individual task quickly, but conclusions from one conversation did not necessarily carry into subsequent work. Recording agreed responsibilities, design decisions and critical constraints reduced repeated explanation and context drift. However, documentation introduced its own maintenance cost: duplicated or contradictory instructions could mislead later development. A smaller set of authoritative documents, updated alongside requirements and verification criteria, was more useful than accumulating summaries. Verification changed how I assessed agent output. Executable code, passing checks and satisfied requirements represent different judgments. When OpenCode assists with both implementation and tests, they may share the same mistaken assumption. Human review should therefore examine whether tests follow the requirements, cover negative cases and protect existing behavior. Reviewing the proposed approach and verification method before implementation helped expose misunderstandings earlier and discouraged acceptance based solely on a completion message. If I organized a similar project again, I would use smaller iterations, establish acceptance scenarios and cross-module constraints earlier, and reduce records that add little practical value. OpenCode's contribution extends beyond coding speed to problem analysis, option comparison and defect diagnosis. These capabilities become dependable only when requirements management, architecture constraints, version control and independent verification form a coherent feedback loop. The project clarified the division of responsibility in effective collaboration: the agent performs work that can be inspected and checked, while developers remain accountable for objectives, tradeoffs and final acceptance.

### Shengjin Duan — 60599024

### Yiwen Wang — 60536848

### Tianqi Wang — 60726054

The objective that interested me most was making token usage measurable and attributable, rather than simply trying to reduce the total number of tokens. In a multi-agent trading system, a lower token count is not meaningful unless we know which components generated the usage and whether retries, tool interactions and final decisions were measured consistently. I therefore focused on establishing reliable observability before evaluating optimisation. The frozen 2×2 experiment provided a structured way to examine single-pass finalisation while controlling the experimental configuration. For me, the main value of this work was developing a transparent measurement approach, not claiming that one optimisation would always save tokens or improve trading performance. The V2 preflight halt demonstrated why experimental reliability must take priority over execution speed. The audit identified blocking defects before any paid batch calls were made, including problems affecting the integrity of the experimental setup and its verification process. Continuing at that point could have consumed resources while producing results that were difficult to interpret or reproduce. Although the repeated corrections and re-freezes increased the schedule overhead, they established clearer boundaries between implementation changes and measured experiments. I came to see the halt as a necessary quality-control decision rather than simply a delay. A smaller set of trustworthy results is more useful than a larger set produced by an unreliable measurement process. This project helped me understand that passing tests, preserving frozen artifacts and obtaining audit reports are different forms of evidence. Automated tests establish whether specified behaviours hold in the tested environment, while manifests and hashes help establish artifact integrity. AI-generated audits can identify important defects, but several AI reviewers do not automatically provide independent human verification. I also learned to be cautious when interpreting the V3 measurements because the experiment had a small sample size and its results preceded the final remediation. In future work, I would place greater emphasis on independently checking representative usage records, verifying the links between raw observations and reported metrics, preserving approval records for paid experiments, and clearly separating exploratory findings from validated conclusions. The freeze and audit process was more extensive than I would ideally expect for a course project. It involved substantial documentation, repeated checks and many commits without directly producing additional experimental data. However, the process exposed serious problems, including a configuration that could have executed the same experimental arm under different labels and a verification weakness that could have accepted altered registration evidence. Without those checks, the resulting comparisons might have appeared convincing while being fundamentally unreliable. If I repeated the project, I would retain reproducible experiment specifications, manifest verification, preflight checks, clear run identities and independent review. At the same time, I would simplify repetitive paperwork and avoid audit rounds that add little new evidence. The objective should be proportionate rigor, not maximum documentation.

### Zhuoran Ruan — 60946340

<div style="break-after: page; page-break-after: always;"></div>

## 18. Conclusions and future work

The project extended TradingAgents from an existing terminal-oriented research application into a browser-accessible workspace with stronger research controls and operational visibility. The main contributions combine evidence-quality assessment, dynamic debate control, usage attribution, fault tolerance and simulated trading. Browser workflows make intermediate reasoning, tool activity, reports and backtest progress accessible throughout execution. Together, these extensions improve the ability to inspect how an assessment was produced and understand why a run stopped or failed.

A central architectural outcome is the separation of model reasoning from deterministic authority. Language models interpret information and develop competing arguments, while explicit policies govern evidence acceptance, resource budgets, output restrictions and simulated execution. Shared interfaces preserve this separation across terminal and browser workflows. This approach made important failure conditions reproducible through offline tests and reduced dependence on a particular provider's wording or availability.

Development also showed that integration deserves as much attention as individual components. A correct evidence gate can lose its effect downstream, a valid configuration can be interpreted incorrectly by an interface, and an apparently complete experiment can contain inconsistent settings or shared state. Human feedback and negative tests helped expose these problems. Requirements, architecture decisions and verification improved when they evolved around observable behavior rather than isolated implementation details. OpenCode supported this process through analysis, implementation and diagnosis, with developers retaining responsibility for scope and acceptance.

The application still has practical limits. Market-data availability and model latency affect research completion. The local execution model favors a single active operation, and browser reconnection does not provide durable background execution across server restarts. Experimental token reductions came from small samples and were accompanied by reliability problems, so their findings remain exploratory. Simulated execution provides a controlled environment for exercising decisions and safety rules; investment effectiveness and real-world trading safety require different forms of evaluation.

Future work should prioritize broader and repeated research-quality evaluation, clearer measurement of latency and resource use, and recovery of long-running operations. Context management could be extended through the proposed compaction design while preserving critical constraints and evidence provenance. Concurrency would require explicit isolation of configuration, memory and persistent state. These directions build on the project's main lesson: useful AI capabilities depend on clear boundaries, visible execution and evidence that the complete workflow behaves as intended.
