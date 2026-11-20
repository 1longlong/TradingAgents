// REQ-WEB-009/010, ADR-003: same-origin artifact queries and opaque identifiers.
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
  metadata?: Record<string, unknown>;
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
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getHistory(
  params: { limit?: number; cursor?: string | null } = {},
) {
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

// REQ-WEB-010: filters and totals cover every server page, not just the first.
export async function getAllHistory(): Promise<HistoryResponse> {
  const items: HistoryItem[] = [];
  const cursors = new Set<string>();
  let cursor: string | null = null;
  do {
    const page = await getHistory({ limit: 200, cursor });
    items.push(...page.items);
    cursor = page.next_cursor;
    if (cursor && cursors.has(cursor))
      throw new Error("History pagination did not advance.");
    if (cursor) cursors.add(cursor);
  } while (cursor);
  return {
    items: [...new Map(items.map((item) => [item.artifact_id, item])).values()],
    next_cursor: null,
  };
}
