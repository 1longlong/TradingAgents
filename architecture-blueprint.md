# Architecture Blueprint

Status: Implemented (Step 14).

## Purpose

The subsystem adds simulated, deterministic trade execution on top of the
existing TradingAgents analysis graph. The graph and its LLM agents remain
advisory. Every executable action passes through a deterministic rule engine,
a simulated executor, and an append-only audit log. No real broker API exists in
this codebase.

## Runtime Dataflow

```text
TradingAgentsGraph / final_state
        |
        v
decision_from_final_state()        # direction only; LLM numbers discarded
        |
        v
SizingPolicy                       # deterministic quantity from equity + caps
        |
        v
SafetyEngine.evaluate()            # SR-01..SR-10, then AP-01/AP-02
        |
        +-- REJECTED / NO_ACTION ----------------> AuditLog
        |
        +-- PENDING_APPROVAL -> HumanApprovalGate -> HumanApproval
        |                                              |
        |                                              v
        |                                       SafetyEngine.apply_approval()
        |
        +-- APPROVED ----------------------------------+
                                                       v
                                            SafetyEngine.execute()
                                                       |
                                                       v
                                            SimulatedExecutor
                                                       |
                                            atomic Portfolio fill
                                                       |
                                                       v
                                            EXECUTION_STARTED
                                            ORDER_EXECUTED
                                                       |
                                                       v
                                                   AuditLog
```

`TradingPipeline.process()` performs the adapter, sizing, evaluation, and
approved execution steps. It returns a `PipelineResult` containing the
decision, evaluation, optional execution, and optional approval request.

## Component Responsibilities

| Component | Module | Responsibility |
|---|---|---|
| Shared models/errors | `src/trading/models.py` | Frozen dataclasses, enums, Decimal helpers, `FeeModel`, `SafetyConfig`, `PortfolioSnapshot`, `ExecutionAuthorization`, audit event types, typed errors |
| Clock abstraction | `src/trading/clock.py` | `SystemClock` for live operation; `SimulationClock` pinned to a simulated market close |
| Portfolio ledger | `src/trading/portfolio.py` | Long-only cash, positions, fee-inclusive average cost, realized/unrealized PnL, marks, replay IDs, sticky `BANKRUPT` state |
| Append-only audit | `src/trading/audit.py` | JSONL append, SHA-256 hash chain, canonical payloads, `.head` truncation anchor, integrity verification |
| Persistence | `src/trading/persistence.py` | Atomic JSON state save/load/reset, `BacktestCursor`, restore-into-existing-portfolio support |
| Executor | `src/trading/executor.py` | Verifies engine-issued authorization, applies simulated fills atomically, writes execution audit events |
| Rule catalogue | `src/safety/rules.py` | SR-01..SR-10 hard rules and AP-01/AP-02 soft approval policies |
| Safety engine | `src/safety/engine.py` | State machine, rule/policy orchestration, approval transitions, sole executor gateway, provenance token issuer |
| Approval gate | `src/trading/approval.py` | TTL-bound approval requests and one-shot human approve/deny decisions |
| Graph adapter & sizing | `src/trading/pipeline.py` | Rating-to-direction mapping, deterministic sizing, pipeline orchestration |
| Backtest layer | `src/trading/backtest.py` | Weekday calendar, mock/real decision providers, mock/historical quote providers, resumable `BacktestRunner` |
| Startup composition | `src/trading/runtime.py` | Wires audit, state store, portfolio, engine, gate, and pipeline from `RuntimeConfig` |
| Standalone CLI | `src/trading/cli.py` | `--state`, `--audit`, `--initial-cash`, `--reset`; inspect or reset only |

## Decision State Machine

`SafetyEngine.evaluate()` returns one of:

- `APPROVED` — all SR rules passed and no AP policy triggered.
- `PENDING_APPROVAL` — all SR rules passed, but AP-01 or AP-02 triggered.
- `REJECTED` — at least one hard SR rule failed, including `BANKRUPT`.
- `NO_ACTION` — the decision is HOLD or REVIEW.

Only `APPROVED` may reach `SafetyEngine.execute()`. `apply_approval()` moves a
`PENDING_APPROVAL` result to `APPROVED` or `REJECTED`, once per evaluation.

## Authority Boundary

- The LLM supplies direction only. `decision_from_final_state()` imports the
  read-only `extract_rating` helper, maps Buy/Overweight to BUY,
  Sell/Underweight to SELL, Hold to HOLD, and missing/REVIEW to REVIEW. It sets
  `quantity=None` and ignores all LLM numeric fields.
- `SizingPolicy` chooses quantity from a fraction of total equity (default 5%),
  capped by `SafetyConfig.hard_max_order_notional` and floored to six decimal
  places.
- The rule engine is authoritative. A rule or policy failure cannot be
  overridden by LLM text.
- `SimulatedExecutor` is the only writer of portfolio fills. It accepts only an
  engine-issued `ExecutionAuthorization` carrying the module-private provenance
  token.
- All trade execution is simulated. No broker SDK, broker endpoint, or real
  order path exists.

## Persistence and Recovery

`StateStore` persists `cash`, `positions`, `realized_pnl`, `total_fees`,
`last_prices`, `applied_order_ids`, `bankrupt`, `bankruptcy_reason`, `version`,
`initial_cash`, and an optional `BacktestCursor`. Saves use a same-directory
temporary file, `fsync`, and `os.replace`. A missing file yields a fresh
portfolio at the requested initial cash; a corrupt file raises
`PersistenceError` rather than resetting silently. Reset clears the portfolio
and cursor and appends `STATE_RESET` to the audit log.

`BacktestRunner` saves state after each processed day. It restores into the
same live `Portfolio` instance used by the engine and executor, then resumes
after `last_completed_date`.

## Walk-Forward and Live Validation

`BacktestRunner` iterates a `TradingCalendar` (default `WeekdayCalendar`),
sets `SimulationClock` to each day, fetches a quote, marks the portfolio,
requests a decision, runs `TradingPipeline.process()`, and persists progress.
Missing quotes are skipped and still checkpointed. The runner supports
`MockDecisionProvider`/`MockQuoteProvider` for offline tests and
`RealDecisionProvider`/`HistoricalQuoteProvider` for opt-in live smoke tests.

Live tests are gated by `RUN_LIVE_TRADING_TESTS=1`, auto-load `.env`, and set a
process-local yfinance proxy. The executor remains simulated in live tests.

## Out of Scope

- Real broker integration or real order submission.
- An unattended live trading loop.
- Automatic revision of the frozen `tradingagents/` graph, agents, dataflows,
  or LLM clients.
