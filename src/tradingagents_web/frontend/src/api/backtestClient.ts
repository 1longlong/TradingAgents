// REQ-WEB-006/011/012, ADR-003: preserve safe errors and real task conflicts.
import { getSessionToken, jsonRequest } from "./runClient";

export type BacktestRatingScore = {
  count: number;
  hit_rate: number | null;
  mean_alpha: number;
};

export type BacktestSummaryData = {
  resolved: number;
  pending: number;
  unscored: number;
  holding: string;
  by_rating: Record<string, BacktestRatingScore>;
  failures: Array<[string, string, string]>;
  settlement_failures: Array<[string, string]>;
  log_artifact_id?: string;
};

export type BacktestSnapshot = {
  run_id: string;
  kind?: "backtest";
  status: "starting" | "running" | "completed" | "failed" | string;
  ticker?: string;
  tickers?: string[];
  dates?: string[];
  start?: string | null;
  end?: string | null;
  every?: number | null;
  asset_type?: string;
  analysts?: string[];
  expected_cells?: number;
  cells_run?: number;
  skipped?: number;
  started_at?: string | null;
  finished_at?: string | null;
  summary?: BacktestSummaryData | null;
  error?: Record<string, unknown> | null;
};

export type BacktestList = { items: BacktestSnapshot[] };

export type AnnouncementPayload = {
  announcements: string[];
  require_attention: boolean;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  return jsonRequest<T>(url, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
}

export async function startBacktest(body: Record<string, unknown>) {
  const token = await getSessionToken();
  return requestJson<BacktestSnapshot>("/api/backtests", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": token,
    },
    body: JSON.stringify(body),
  });
}

export function getBacktest(runId: string) {
  return requestJson<BacktestSnapshot>(
    `/api/backtests/${encodeURIComponent(runId)}`,
  );
}

export function listBacktests() {
  return requestJson<BacktestList>("/api/backtests");
}

export function getAnnouncements() {
  return requestJson<AnnouncementPayload>("/api/announcements");
}
