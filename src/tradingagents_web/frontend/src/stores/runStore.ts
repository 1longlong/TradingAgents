import { createStore } from "zustand/vanilla";

export type RunStatus =
  | "idle"
  | "starting"
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled";

export type Connection = "idle" | "connecting" | "live" | "reconnecting" | "closed";

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
  signal?: string;
  review: boolean;
  error?: string;
  applyEvent: (event: RunEvent) => void;
  applySnapshot: (snapshot: Record<string, unknown>) => void;
  setConnection: (connection: Connection) => void;
  reset: () => void;
};

const TERMINAL = new Set<RunStatus>(["completed", "failed", "cancelled"]);

export function createRunStore() {
  return createStore<RunState>((set, get) => ({
    runId: null,
    status: "idle",
    connection: "idle",
    lastSeq: 0,
    messages: [],
    sections: {},
    review: false,

    applyEvent(event) {
      const state = get();
      if (typeof event.seq === "number" && event.seq <= state.lastSeq) return;
      const payload = event.payload ?? {};
      const patch: Partial<RunState> = { lastSeq: event.seq };

      switch (event.type) {
        case "run.started":
          patch.status = "running";
          patch.connection = "live";
          break;
        case "message":
          patch.messages = [
            ...state.messages,
            {
              id: `${event.run_id ?? "run"}:${event.seq}`,
              timestamp: payload.timestamp as string | undefined,
              type: payload.type as string | undefined,
              content: String(payload.content ?? ""),
            },
          ];
          break;
        case "report.section":
          patch.sections = {
            ...state.sections,
            [String(payload.section ?? "")]: String(payload.content ?? ""),
          };
          break;
        case "run.completed":
          patch.status = "completed";
          patch.connection = "closed";
          patch.signal = payload.signal as string | undefined;
          patch.review = Boolean(payload.review);
          break;
        case "run.failed":
          patch.status = "failed";
          patch.connection = "closed";
          patch.error = String(payload.message ?? "run failed");
          break;
        case "run.cancelled":
          patch.status = "cancelled";
          patch.connection = "closed";
          break;
        case "snapshot":
          patch.status = (payload.status as RunStatus) ?? state.status;
          patch.lastSeq = Number(payload.last_seq ?? event.seq);
          patch.sections = (payload.sections as Record<string, string>) ?? state.sections;
          patch.signal = payload.signal as string | undefined;
          patch.review = Boolean(payload.review);
          break;
        default:
          break;
      }

      if (patch.status && TERMINAL.has(patch.status)) {
        patch.connection = "closed";
      }
      set(patch);
    },

    applySnapshot(snapshot) {
      set({
        runId: String(snapshot.run_id ?? ""),
        status: (snapshot.status as RunStatus) ?? "running",
        connection: "connecting",
        lastSeq: Number(snapshot.last_seq ?? 0),
        signal: snapshot.signal as string | undefined,
        review: Boolean(snapshot.review),
      });
    },

    setConnection(connection) {
      set({ connection });
    },

    reset() {
      set({
        runId: null,
        status: "idle",
        connection: "idle",
        lastSeq: 0,
        messages: [],
        sections: {},
        signal: undefined,
        review: false,
        error: undefined,
      });
    },
  }));
}
