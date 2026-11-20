// REQ-WEB-005/007, INV-WEB-003: surface only safe server failure details.
export type RunConfig = {
  defaults: Record<string, unknown>;
  providers: Array<{ key: string; label: string; default_url: string | null }>;
  env_locks: Record<string, boolean>;
  key_status: Record<string, string>;
  prefs: Record<string, unknown>;
  backend_url_configured?: boolean;
};

export type RunSnapshot = {
  run_id: string;
  status: string;
  ticker: string;
  trade_date: string;
  last_seq: number;
  kind?: string;
  asset_type?: string;
  analysts?: string[];
  research_depth?: number;
  llm_provider?: string;
  quick_think_llm?: string;
  deep_think_llm?: string;
  output_language?: string;
  checkpoint_enabled?: boolean;
  started_at?: string;
  finished_at?: string | null;
  wall_times?: Record<string, number>;
  artifact_id?: string | null;
  sections?: Record<string, string>;
  signal?: string | null;
  review: boolean;
  warnings: string[];
  error?: Record<string, unknown> | null;
};

let csrfToken: string | null = null;

export async function getSessionToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await fetch("/api/session", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`session failed: ${response.status}`);
  const payload = (await response.json()) as { csrf_token: string };
  csrfToken = payload.csrf_token;
  return csrfToken;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public activeRunId?: string,
  ) {
    super(message);
  }
}

export async function jsonRequest<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: {
        message?: string;
        correlation_id?: string;
        fields?: { active_run_id?: string };
      };
      detail?: Array<{ msg: string }>;
    } | null;
    const message =
      body?.error?.message ??
      body?.detail?.map((item) => item.msg).join("; ") ??
      `Request failed: ${response.status}`;
    const reference = body?.error?.correlation_id;
    throw new ApiError(
      `${message}${reference ? ` (${reference})` : ""}`,
      response.status,
      body?.error?.fields?.active_run_id,
    );
  }
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

export async function startRun(
  body: Record<string, unknown>,
): Promise<RunSnapshot> {
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
  return jsonRequest<RunSnapshot>(
    `/api/runs/${encodeURIComponent(runId)}/cancel`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": token },
    },
  );
}

export function runEventsUrl(runId: string, afterSeq: number) {
  return `/api/runs/${encodeURIComponent(runId)}/events?after_seq=${afterSeq}`;
}

export async function clearCheckpoints(): Promise<{ cleared: number }> {
  const token = await getSessionToken();
  return jsonRequest<{ cleared: number }>("/api/checkpoints/clear", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": token,
    },
    body: JSON.stringify({ confirm: "CLEAR" }),
  });
}

export function getActiveRun() {
  return jsonRequest<RunSnapshot | { run_id: null }>("/api/runs/active");
}

export async function validatePortfolio(json: string) {
  const token = await getSessionToken();
  return jsonRequest<{ valid: boolean }>("/api/portfolio/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
    body: JSON.stringify({ json }),
  });
}
