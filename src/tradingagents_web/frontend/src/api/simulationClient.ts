// FR-TRD-001..006, INV-TRD-001..003; ADR-001-simulated-trading-system.md.
import { getSessionToken, jsonRequest } from "./runClient";

export type SimPosition = {
  symbol: string;
  quantity: string;
  average_cost: string | null;
  market_price: string | null;
  market_value: string | null;
  realized_pnl: string;
  unrealized_pnl: string | null;
};
export type SimSnapshot = {
  cash: string;
  positions: SimPosition[];
  realized_pnl: string;
  unrealized_pnl: string;
  total_fees: string;
  total_equity: string;
  bankrupt: boolean;
  version: number;
  as_of: string;
  valuation_incomplete: boolean;
};
export type SimOrder = {
  symbol: string;
  side: string;
  quantity: string;
  price: string;
  notional: string;
  fee: string;
};
export type SimEvaluation = {
  evaluation_id: string;
  status: string;
  portfolio_version: number;
  decision: { action: string; symbol: string };
  order_intent: SimOrder | null;
  rule_results: { rule_id: string; passed: boolean; reason: string }[];
  reasons: string[];
};
export type SimPending = {
  request_id: string;
  state: string;
  receipt_id: string;
  evaluation: SimEvaluation;
  request: { expires_at: string };
};
export type SimTransaction = {
  id: string;
  ticker: string;
  created_at: string;
  result: {
    evaluation: SimEvaluation;
    execution: {
      order_id: string;
      executed_at: string;
      order: SimOrder;
    } | null;
  };
};
export type SimState = {
  initialized: boolean;
  account_id: string | null;
  snapshot: SimSnapshot | null;
  policy: Record<string, string | number | boolean | null>;
  pending: SimPending[];
  transactions: SimTransaction[];
};
export type ScenarioRow = {
  date: string;
  action: "BUY" | "SELL" | "HOLD" | "REVIEW";
  price: string;
};
export type SimJobInput = {
  source: "scenario" | "research";
  symbol: string;
  start: string;
  end: string;
  initial_cash: string;
  rows: ScenarioRow[];
  resume_id?: string;
};
export type SimJob = {
  run_id: string;
  status: string;
  created_at: string;
  parameters: SimJobInput;
  summary: {
    days_processed: number;
    days_skipped: number;
    executions: number;
    rejections: number;
    pending_approvals: number;
    no_actions: number;
    final_equity: string;
    bankrupt: boolean;
  } | null;
  snapshot: SimSnapshot | null;
  cursor?: { last_completed_date: string } | null;
  error: string | null;
};
export type SimAuditEvent = {
  event_id: string;
  timestamp: string;
  event_type: string;
  run_id: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  entry_hash: string;
};
const BASE = "/api/simulation";
export const getSimulation = () => jsonRequest<SimState>(BASE);
export const getSimulationReports = () =>
  jsonRequest<{
    items: {
      artifact_id: string;
      ticker: string;
      date: string;
      rating: string | null;
    }[];
  }>(`${BASE}/reports`);
export const getSimulationJobs = () =>
  jsonRequest<{ items: SimJob[] }>(`${BASE}/jobs`);
export const getSimulationJob = (id: string) =>
  jsonRequest<SimJob>(`${BASE}/jobs/${encodeURIComponent(id)}`);
export const getSimulationAudit = (
  runId: string,
  eventType: string,
  offset: number,
) => {
  const query = new URLSearchParams({ offset: String(offset), limit: "50" });
  if (runId) query.set("run_id", runId);
  if (eventType) query.set("event_type", eventType);
  return jsonRequest<{
    verified: boolean | null;
    items: SimAuditEvent[];
    total: number;
  }>(`${BASE}/audit?${query}`);
};
export async function simulationPost<T>(
  path: string,
  body: unknown,
): Promise<T> {
  return jsonRequest<T>(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": await getSessionToken(),
    },
    body: JSON.stringify(body),
  });
}
