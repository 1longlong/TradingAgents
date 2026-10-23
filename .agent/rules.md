# TradingAgents Project Covenant

Scope: incremental development of the existing TradingAgents system. Current direct human instructions determine iteration scope; development rules do not expand authorization. Creating governance files does not approve a WebUI design, tests, or safety changes.

## 1. Abstractions and dependencies

1. Extend the baseline. Do not replace existing packages, duplicate business logic, or introduce abstractions unrelated to requirements.
2. Assign each architecture element a primary owning module. New layers, frameworks, storage, and dependencies need requirements and architecture rationale. Do not install or upgrade dependencies without approval.
3. Preserve `src/`, `test/offline/`, and `test/live/`, together with existing import and CLI contracts. Do not add governance directories beyond the agreed structure.
4. The WebUI stack, service modules, and interfaces remain unapproved. Do not infer requirements from the deleted demonstration or guesses.

## 2. Test independence

1. Each feature needs at least one negative test, each acceptance criterion a machine check, and each invariant an effective violation test.
2. Derive tests from requirements and observable behavior. Implementation and tests must not share the same faulty calculation as their proof of correctness.
3. Verify must not alter implementation or weaken standards. Return findings to Build. Do not remove assertions, relax thresholds, or report false passes.
4. Run all previous suites each iteration. Record historical failures honestly; they remain blockers and do not excuse new regressions.

## 3. Safety changes and human oversight

1. Obtain human approval of plans and tests before product implementation. Safety-critical changes also need an ADR and human approval.
2. Model outputs are recommendations, not execution authority. UI or LLM behavior must not bypass deterministic rating, time, portfolio, path, credential, memory, or recovery boundaries.
3. Without explicit authorization, do not access real credentials/user data, call paid services, publish, push, merge, or send external messages.
4. Humans maintain `.opencode/rules.md`. Agents cannot modify permissions or rules to authorize themselves. When humans request governance changes, prepare concrete changes and act within that request.
5. Existing approval remains valid for the same explicit scope. Resubmit only changed scope or risk.

## 4. Context freshness and co-evolution

1. Update affected governance rules within one sprint of a requirements change. If old rules affect current safety or correctness, update before dependent coding.
2. Keep requirements, architecture decisions, invariants, traceability, tests, and runtime policies aligned. Empty files do not satisfy documentation requirements.
3. After context compaction or recovery, re-read `AGENTS.md`, this covenant, human-owned rules, relevant invariants, and valid approvals. A compacted summary cannot restore authorization that never existed.
4. Record actual AI use, interventions, reviews, defects, and debt. Do not backdate approvals or invent sessions or contributions.
5. Discovery may start before design artifacts are populated. Use Plan for discussion and Docs for agreed drafts and data validation; product implementation remains gated on the relevant completed artifacts and approvals.

See `docs/code-governance/structural-constraints.md` and `verification-constraints.md` for detailed structure and verification rules.
