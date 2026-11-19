import { createStore } from "zustand/vanilla";

export type RunStatus =
  | "idle"
  | "starting"
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled";
export type Connection =
  "idle" | "connecting" | "live" | "reconnecting" | "closed";
export type RunMessage = {
  id: string;
  timestamp?: string;
  type?: string;
  content: string;
};
export type RunEvent = {
  run_id?: string;
  seq: number;
  type: string;
  payload?: Record<string, unknown>;
};
export type RunState = {
  runId: string | null;
  status: RunStatus;
  connection: Connection;
  lastSeq: number;
  messages: RunMessage[];
  sections: Record<string, string>;
  agents: Record<string, string>;
  stats: Record<string, number>;
  phase: string;
  signal?: string;
  review: boolean;
  error?: string;
  warnings: string[];
  artifactId?: string;
  applyEvent: (event: RunEvent) => void;
  applySnapshot: (snapshot: Record<string, unknown>) => void;
  setConnection: (connection: Connection) => void;
  reset: () => void;
};
const TERMINAL = new Set<RunStatus>(["completed", "failed", "cancelled"]);
const initial = () => ({
  runId: null,
  status: "idle" as RunStatus,
  connection: "idle" as Connection,
  lastSeq: 0,
  messages: [] as RunMessage[],
  sections: {},
  agents: {},
  stats: {},
  phase: "preparing",
  signal: undefined,
  review: false,
  error: undefined,
  warnings: [],
  artifactId: undefined,
});
function errorMessage(error: unknown): string | undefined {
  if (!error) return undefined;
  if (typeof error === "string") return error;
  const details = error as Record<string, unknown>;
  return `${String(details.message ?? "Analysis failed")}${details.correlation_id ? ` (${details.correlation_id})` : ""}`;
}
function snapshotState(snapshot: Record<string, unknown>): Partial<RunState> {
  const status = (snapshot.status as RunStatus) ?? "running";
  return {
    runId: String(snapshot.run_id ?? ""),
    status,
    connection: TERMINAL.has(status) ? "closed" : "connecting",
    lastSeq: Number(snapshot.last_seq ?? 0),
    messages: (snapshot.messages as RunMessage[]) ?? [],
    sections: (snapshot.sections as Record<string, string>) ?? {},
    agents: (snapshot.agents as Record<string, string>) ?? {},
    stats: (snapshot.stats as Record<string, number>) ?? {},
    phase: String(snapshot.phase ?? "preparing"),
    signal: snapshot.signal as string | undefined,
    review: Boolean(snapshot.review),
    error: errorMessage(snapshot.error),
    warnings: (snapshot.warnings as string[]) ?? [],
    artifactId: snapshot.artifact_id as string | undefined,
  };
}

// REQ-WEB-007: hydrate display state and its cursor atomically before SSE replay.
export function createRunStore() {
  return createStore<RunState>((set, get) => ({
    ...initial(),
    applyEvent(event) {
      const state = get();
      if (event.run_id && state.runId && event.run_id !== state.runId) return;
      if (event.seq <= state.lastSeq) return;
      const payload = event.payload ?? {};
      const patch: Partial<RunState> = { lastSeq: event.seq };
      switch (event.type) {
        case "run.started":
        case "run.resumed":
          patch.status =
            state.status === "cancelling" ? "cancelling" : "running";
          patch.phase = "analysis";
          patch.connection = "live";
          break;
        case "run.preparing":
        case "run.phase":
          patch.phase = String(payload.phase ?? "preparing");
          break;
        case "message":
        case "tool_call":
          patch.messages = [
            ...state.messages,
            {
              id: `${event.run_id ?? "run"}:${event.seq}`,
              timestamp: payload.timestamp as string | undefined,
              type:
                event.type === "tool_call"
                  ? "Tool"
                  : (payload.type as string | undefined),
              content:
                event.type === "tool_call"
                  ? `${String(payload.name ?? "tool")}(${JSON.stringify(payload.arguments ?? {})})`
                  : String(payload.content ?? ""),
            },
          ].slice(-500);
          break;
        case "report.section":
          patch.sections = {
            ...state.sections,
            [String(payload.section ?? "")]: String(payload.content ?? ""),
          };
          break;
        case "agent.status":
          patch.agents = {
            ...state.agents,
            [String(payload.agent)]: String(payload.status),
          };
          break;
        case "stats":
          patch.stats = payload as Record<string, number>;
          break;
        case "run.completed":
          patch.status = "completed";
          patch.signal = payload.signal as string | undefined;
          patch.review = Boolean(payload.review);
          patch.warnings = (payload.warnings as string[]) ?? [];
          patch.artifactId = payload.artifact_id as string | undefined;
          break;
        case "run.failed":
          patch.status = "failed";
          patch.error = errorMessage(payload);
          break;
        case "run.cancelled":
          patch.status = "cancelled";
          break;
        case "snapshot":
          Object.assign(patch, snapshotState(payload));
          break;
      }
      if (patch.status && TERMINAL.has(patch.status))
        patch.connection = "closed";
      set(patch);
    },
    applySnapshot(snapshot) {
      set(snapshotState(snapshot));
    },
    setConnection(connection) {
      set({ connection: TERMINAL.has(get().status) ? "closed" : connection });
    },
    reset() {
      set(initial());
    },
  }));
}
