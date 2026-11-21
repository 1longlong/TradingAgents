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

// REQ-WEB-007 / ADR-007: a refreshed page must recover already emitted results.
describe("run recovery", () => {
  it("hydrates reports, messages and failure details from a terminal snapshot", () => {
    const store = createRunStore();
    store.getState().applySnapshot({
      run_id: "r1",
      status: "failed",
      last_seq: 20,
      messages: [{ id: "r1:1", content: "existing message" }],
      sections: { market_report: "existing report" },
      error: {
        message: "Provider rejected the model",
        correlation_id: "c_123",
      },
      stats: { llm_calls: 3 },
      agents: { Trader: "completed" },
    });
    expect(store.getState().connection).toBe("closed");
    expect(store.getState().sections.market_report).toBe("existing report");
    expect(store.getState().messages[0].content).toBe("existing message");
    expect(store.getState().error).toContain("Provider rejected the model");
    expect(store.getState().error).toContain("c_123");
    store.getState().setConnection("reconnecting");
    expect(store.getState().connection).toBe("closed");
  });

  it("handles resumed runs and snapshot fallback after a buffer gap", () => {
    const store = createRunStore();
    store
      .getState()
      .applySnapshot({ run_id: "r1", status: "starting", last_seq: 0 });
    store.getState().applyEvent({ run_id: "r1", seq: 1, type: "run.resumed" });
    expect(store.getState().status).toBe("running");
    store.getState().applyEvent({
      run_id: "r1",
      seq: 50,
      type: "snapshot",
      payload: {
        run_id: "r1",
        last_seq: 50,
        status: "completed",
        signal: "Buy",
        sections: { final_trade_decision: "Buy with evidence" },
      },
    });
    expect(store.getState().sections.final_trade_decision).toBe(
      "Buy with evidence",
    );
    expect(store.getState().connection).toBe("closed");
  });
});
