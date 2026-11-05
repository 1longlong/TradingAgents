export type HistorySource = "run" | "saved" | "backtest" | "decision";

export type HistoryItem = {
  artifact_id: string;
  source: HistorySource;
  ticker: string;
  date: string | null;
  status: string;
  rating: string | null;
  review: boolean;
  updated_at: string;
  title: string;
};

export type HistoryResponse = {
  items: HistoryItem[];
  next_cursor: string | null;
};

export type ArtifactRef = { kind: string; section?: string };

export type HistoryDetail = {
  artifact_id: string;
  source: HistorySource;
  ticker: string;
  date: string | null;
  status: string;
  rating: string | null;
  review: boolean;
  metadata: Record<string, unknown>;
  sections?: Record<string, string>;
  artifacts?: ArtifactRef[];
  summary?: Record<string, unknown>;
  entries?: Array<Record<string, unknown>>;
};

async function requestJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getHistory(params: { limit?: number; cursor?: string | null } = {}) {
  const search = new URLSearchParams();
  search.set("limit", String(params.limit ?? 50));
  if (params.cursor) search.set("cursor", params.cursor);
  return requestJson<HistoryResponse>(`/api/history?${search.toString()}`);
}

export function getHistoryDetail(artifactId: string) {
  return requestJson<HistoryDetail>(
    `/api/history/${encodeURIComponent(artifactId)}`,
  );
}

export function downloadUrl(
  artifactId: string,
  kind: "complete" | "archive" | "section" | "log",
  section?: string,
) {
  const search = new URLSearchParams({ kind });
  if (section) search.set("section", section);
  return `/api/history/${encodeURIComponent(artifactId)}/download?${search.toString()}`;
}
