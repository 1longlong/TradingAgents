# Option Ledger — Alternative Designs and Why We Chose What We Did

Each row records an alternative we considered, why we did not take it, and the
decision we took. The decision columns are stable IDs; the gate and evaluator
ADRs are the authoritative decision records.

## Data Quality Gate

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DQG-ALT-1 | LLM-based quality judge (prompt an LLM to score data quality) | Non-deterministic, requires an LLM call, not offline-testable, costly, hard to audit a verdict. | Deterministic, LLM-free gate (`FR-DQG-001`). |
| DQG-ALT-2 | Inline `SourceAttempt` nested inside `EvidenceRecord` | Breaks acyclic serialization; hard to round-trip JSON; violates INV-4. | Separate `SourceAttempt` record (7 fields), never embedded. |
| DQG-ALT-3 | Float math for normalized financial values | Float noise breaks deterministic comparisons and point-in-time reproducibility. | `Decimal` (quantized via `quantize_decimal`). |
| DQG-ALT-4 | Gate raises the whole run on any low quality | Too aggressive; blocks runs a human would tolerate (degraded). | Tiered verdicts `blocked > degraded > normal` (`FR-DQG-002`). |
| DQG-ALT-5 | Random `run_id` for evidence IDs | Breaks reproducibility; evidence differs per run. | `run_id` derived from `(trade_date, normalized symbol)` (`FR-DQG-003`). |
| DQG-ALT-6 | Gate writes frozen dataclasses into AgentState | Not checkpoint/JSON serializable; LangGraph state is dicts. | Write serialized `to_dict()` forms only (`FR-DQG-001`). |

## Dynamic debate termination

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DDT-ALT-1 | Always run a fixed `max_debate_rounds` (upstream default) | Wastes tokens/turns after convergence or no-new-evidence; no summary reserve guarantee. | Dynamic, evidence-aware evaluator (`FR-DDT-001`). |
| DDT-ALT-2 | LLM-judged "is the debate over?" | Non-deterministic, adds cost and an extra LLM call, not auditable deterministically. | Deterministic `evaluate_round` rule ordering (`FR-DDT-001`). |
| DDT-ALT-3 | Prose-only turn metadata parsed opportunistically | Unreliable; a missed stance could extend or shorten debate arbitrarily. | Structured `DEBATE_METADATA` marker with a best-effort prose fallback; a parse failure contributes zero new evidence and cannot extend the debate (`FR-DDT-002`). |
| DDT-ALT-4 | No summary reserve; rely on wall-clock only | A run could exhaust budget mid-debate and lose its report. | Explicit summary tokens/time reserve + hard max tokens/time/calls (`FR-DDT-003`). |
| DDT-ALT-5 | Break upstream by defaulting to dynamic always | Regresses legacy behavior and default `pytest -q`. | `debate_termination.enabled` default; `False` reproduces fixed-round routing (`FR-DDT-004`). |
| DDT-ALT-6 | Incomplete router path map relying on fall-through | A fall-through could hit a missing edge and crash LangGraph (#1088). | Complete `DEBATE_PATH_MAP` / `DEBATE_EVALUATOR_PATH_MAP` (`FR-DDT-001`). |

## Documentation / delivery

| Option ID | Alternative | Rejected because | Decision |
| --- | --- | --- | --- |
| DOC-ALT-1 | Duplicate source into `src/` to match the slide | Duplicates code, risk of drift, out of scope. | Map the slide layout onto `tradingagents/` + `cli/` via `src/README.md` and `test/*/README.md`. |
| DOC-ALT-2 | Claim a green full suite | False; known date-sensitive and network-reachability failures remain. | Record exact observed outcomes and note failures (`evaluation-logbook.md`, `risk-list.md`). |