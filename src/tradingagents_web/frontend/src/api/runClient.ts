export type RunConfig = {
  defaults: Record<string, unknown>;
  providers: Array<{ key: string; label: string; default_url: string | null }>;
  env_locks: Record<string, boolean>;
  key_status: Record<string, string>;
  prefs: Record<string, unknown>;
};

export type RunSnapshot = {
  run_id: string;
  status: string;
  ticker: string;
  trade_date: string;
  last_seq: number;
  signal?: string | null;
  review: boolean;
  warnings: string[];
  error?: Record<string, unknown> | null;
};

let csrfToken: string | null = null;

export async function getSessionToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await fetch("/api/session", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`session failed: ${response.status}`);
  const payload = (await response.json()) as { csrf_token: string };
  csrfToken = payload.csrf_token;
  return csrfToken;
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return (await response.json()) as T;
}

export function getRunConfig() {
  return jsonRequest<RunConfig>("/api/config");
}

export function getRunModels(provider: string, mode: "quick" | "deep") {
  return jsonRequest<{ models: Array<{ value: string; label: string }> }>(
    `/api/config/models?provider=${encodeURIComponent(provider)}&mode=${mode}`,
  );
}

export async function startRun(body: Record<string, unknown>): Promise<RunSnapshot> {
  const token = await getSessionToken();
  return jsonRequest<RunSnapshot>("/api/runs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": token,
    },
    body: JSON.stringify(body),
  });
}

export function getRun(runId: string) {
  return jsonRequest<RunSnapshot>(`/api/runs/${encodeURIComponent(runId)}`);
}

export async function cancelRun(runId: string): Promise<RunSnapshot> {
  const token = await getSessionToken();
  return jsonRequest<RunSnapshot>(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: { "X-CSRF-Token": token },
  });
}

export function runEventsUrl(runId: string, afterSeq: number) {
  return `/api/runs/${encodeURIComponent(runId)}/events?after_seq=${afterSeq}`;
}
