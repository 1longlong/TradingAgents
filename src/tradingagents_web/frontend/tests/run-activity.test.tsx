// REQ-WEB-002/007/021, ADR-003, INV-WEB-012/014: observable activity behavior.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RunActivity } from "../src/components/RunActivity";
import { createRunStore } from "../src/stores/runStore";
import { activityProgress, type ActivityState } from "../src/utils/runActivity";

afterEach(cleanup);
function initial(): ActivityState {
  return {
    status: "running",
    connection: "live",
    stats: {},
    sections: {},
    agents: {
      "Market Analyst": "in_progress",
      "Research Team": "pending",
      Trader: "pending",
      "Risk Team": "pending",
    },
    messages: [
      {
        id: "m1",
        type: "AIMessage",
        stage: "analysts",
        content: "Checking the market",
      },
    ],
  };
}

describe("stage-based run activity", () => {
  it("shows pending stages honestly and supports keyboard tab navigation", () => {
    render(<RunActivity state={initial()} />);
    const analyst = screen.getByRole("tab", { name: /Analyst team/ });
    expect(analyst).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Checking the market")).toBeVisible();
    analyst.focus();
    fireEvent.keyDown(analyst, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /Research debate/ })).toHaveFocus();
    expect(screen.getByText("This stage has not started.")).toBeVisible();
    expect(screen.queryByText("Checking the market")).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("tab", { name: /Research debate/ }), {
      key: "Home",
    });
    expect(analyst).toHaveFocus();
    expect(screen.getByText("Checking the market")).toBeVisible();
  });

  it("automatically opens each new stage and allows reviewing earlier messages/reports", () => {
    const state = initial();
    const { rerender } = render(<RunActivity state={state} />);
    const research: ActivityState = {
      ...state,
      sections: { market_report: "Recorded market report" },
      agents: { "Market Analyst": "completed", "Research Team": "in_progress" },
      messages: [
        ...state.messages,
        {
          id: "m2",
          type: "Agent",
          stage: "research",
          speaker: "Bull researcher",
          content: "Bull argument",
        },
      ],
    };
    rerender(<RunActivity state={research} />);
    expect(
      screen.getByRole("tab", { name: /Research debate/ }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Bull argument")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /Analyst team/ }));
    expect(screen.getByText("Recorded market report")).toBeVisible();
    expect(screen.getByText("Checking the market")).toBeVisible();
    // Another event in the same stage must not interrupt manual review.
    rerender(<RunActivity state={{ ...research, stats: { llm_calls: 2 } }} />);
    expect(screen.getByRole("tab", { name: /Analyst team/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const trading: ActivityState = {
      ...research,
      sections: {
        ...research.sections,
        investment_plan: "Research conclusion",
      },
      agents: { Trader: "in_progress" },
    };
    rerender(<RunActivity state={trading} />);
    expect(screen.getByRole("tab", { name: /Trading plan/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const risk: ActivityState = {
      ...trading,
      sections: {
        ...trading.sections,
        trader_investment_plan: "Trading proposal",
      },
      agents: { "Risk Team": "in_progress" },
    };
    rerender(<RunActivity state={risk} />);
    expect(screen.getByRole("tab", { name: /Risk review/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("keeps legacy and terminal activity accessible with tool result filters", () => {
    const state: ActivityState = {
      ...initial(),
      status: "failed",
      connection: "closed",
      messages: [
        { id: "old", type: "ToolMessage", content: "Recovered tool response" },
        {
          id: "call",
          type: "Tool",
          stage: "analysts",
          content: 'get_stock_data({"symbol":"NVDA"})',
        },
      ],
    };
    render(<RunActivity state={state} />);
    fireEvent.click(screen.getByRole("tab", { name: "All activity" }));
    expect(screen.getByText("Recovered tool response")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Filter activity"), {
      target: { value: "Data" },
    });
    expect(screen.getByText("Recovered tool response")).toBeVisible();
    expect(screen.queryByText(/get_stock_data/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("failed · Recorded");
  });

  it("does not infer unrecorded stages completed from a final report", () => {
    const progress = activityProgress({
      ...initial(),
      status: "completed",
      agents: {},
      sections: { final_trade_decision: "REVIEW" },
    });
    expect(progress.completed).toBe(1);
    expect(progress.stages[1].status).toBe("Not recorded");
  });

  it("renders message markup as text and expands long content on demand", () => {
    const text = '<img src=x onerror="alert(1)">';
    render(
      <RunActivity
        state={{
          ...initial(),
          messages: [
            {
              id: "x",
              stage: "analysts",
              type: "Agent",
              content: text + "a".repeat(900),
            },
          ],
        }}
      />,
    );
    const feed = screen.getByRole("region", { name: "Stage messages" });
    expect(feed.querySelector("img")).toBeNull();
    const details = feed.querySelector("details")!;
    expect(details.open).toBe(false);
    fireEvent.click(
      within(feed)
        .getByText(/Show full message/)
        .closest("summary")!,
    );
    expect(details.open).toBe(true);
    expect(details.querySelector("pre")?.textContent).toContain(text);
  });

  it("pauses following when reviewing older messages and resumes at the newest", () => {
    render(<RunActivity state={initial()} />);
    const list = screen.getByRole("region", { name: "Stage messages" });
    list.scrollTop = 50;
    fireEvent.scroll(list);
    expect(screen.getByLabelText("Follow latest")).not.toBeChecked();
    fireEvent.click(screen.getByLabelText("Follow latest"));
    expect(list.scrollTop).toBe(0);
  });

  it("preserves explicit stages and speakers across events and snapshot recovery", () => {
    const store = createRunStore();
    store.getState().applyEvent({
      run_id: "r1",
      seq: 1,
      type: "message",
      payload: {
        stage: "research",
        speaker: "Bear researcher",
        type: "Agent",
        content: "Bear view",
      },
    });
    expect(store.getState().messages[0]).toMatchObject({
      stage: "research",
      speaker: "Bear researcher",
    });
    const recovered = createRunStore();
    recovered.getState().applySnapshot({
      run_id: "r1",
      status: "cancelled",
      messages: store.getState().messages,
    });
    render(<RunActivity state={recovered.getState()} />);
    expect(screen.getByText("Bear view")).toBeVisible();
    expect(
      screen.getByRole("tab", { name: /Research debate/ }),
    ).toHaveAttribute("aria-selected", "true");
  });
});

it("keeps risk-role progress separate and restores timing after reconnect", () => {
  const store = createRunStore();
  store.getState().applySnapshot({
    run_id: "r_roles",
    status: "running",
    last_seq: 1,
    agents: {
      "Market Analyst": "completed",
      "Bull Researcher": "completed",
      "Research Manager": "completed",
      "Aggressive Analyst": "in_progress",
      "Portfolio Manager": "pending",
    },
    sections: {
      market_report: "market",
      investment_plan: "plan",
      trader_investment_plan: "trade",
    },
    wall_times: { "Market Analyst": 1.25 },
    stats: { reports_completed: 3, reports_total: 4 },
    messages: [],
  });
  const state = store.getState();
  expect(activityProgress(state).current).toBe("risk");
  render(<RunActivity state={state} />);
  fireEvent.click(screen.getByText("Agent status & analyst timing"));
  expect(screen.getByText("Aggressive Analyst")).toBeVisible();
  expect(screen.queryByText("Market Analyst")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: /Analyst team/ }));
  expect(screen.getByText("1.25s")).toBeVisible();
  expect(screen.getByText("3 / 4")).not.toBeVisible();
  fireEvent.click(screen.getByText("Run statistics", { exact: true }));
  expect(screen.getByText("3 / 4")).toBeVisible();
  store.getState().applyEvent({
    run_id: "r_roles",
    seq: 2,
    type: "analyst.timing",
    payload: { wall_times: { "News Analyst": 2.5 } },
  });
  expect(store.getState().wallTimes).toEqual({
    "Market Analyst": 1.25,
    "News Analyst": 2.5,
  });
  store.getState().applyEvent({
    run_id: "r_roles",
    seq: 3,
    type: "run.completed",
    payload: { wall_times: { total: 8 } },
  });
  expect(store.getState().wallTimes["Market Analyst"]).toBe(1.25);
});
