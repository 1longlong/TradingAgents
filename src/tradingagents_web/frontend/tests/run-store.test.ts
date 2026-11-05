import { describe, expect, it } from "vitest";

import { createRunStore } from "../src/stores/runStore";

describe("run store", () => {
  it("applies events in sequence and ignores older ones", () => {
    const store = createRunStore();
    store.getState().applyEvent({
      run_id: "r1",
      seq: 2,
      type: "message",
      payload: { content: "two" },
    });
    store.getState().applyEvent({
      run_id: "r1",
      seq: 1,
      type: "message",
      payload: { content: "one" },
    });
    expect(store.getState().lastSeq).toBe(2);
    expect(store.getState().messages).toHaveLength(1);
  });

  it("moves to a terminal state and closes the stream", () => {
    const store = createRunStore();
    store.getState().applyEvent({
      run_id: "r1",
      seq: 1,
      type: "run.completed",
      payload: { signal: "Buy", review: false },
    });
    expect(store.getState().status).toBe("completed");
    expect(store.getState().connection).toBe("closed");
  });
});
