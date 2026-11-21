// FR-TRD-001..006, INV-TRD-001..003; ADR-003-frontend-stack.md.
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../src/i18n";
import { SimulationAccount } from "../src/pages/Simulation/Account";
import { SimulationDecisions } from "../src/pages/Simulation/Decisions";
import { SimulationAudit } from "../src/pages/Simulation/Audit";
import { validateSimulationJob } from "../src/pages/Simulation/Backtests";
import {
  getSimulationReports,
  getSimulationAudit,
  simulationPost,
  type SimState,
  type SimTransaction,
} from "../src/api/simulationClient";

vi.mock("../src/api/simulationClient", () => ({
  getSimulationReports: vi.fn(),
  getSimulationAudit: vi.fn(),
  simulationPost: vi.fn(),
}));
const accountId = "a".repeat(32);
const base: SimState = {
  initialized: false,
  account_id: null,
  snapshot: null,
  pending: [],
  transactions: [],
  policy: {
    hard_max_order_notional: "10000",
    soft_max_order_notional: "2500",
    max_position_fraction: "0.20",
    max_quote_age_seconds: 300,
    fee_bps: "5",
    min_fee: "0.00",
    approval_ttl_seconds: 900,
    allow_short: false,
  },
};
const ready: SimState = {
  ...base,
  initialized: true,
  account_id: accountId,
  snapshot: {
    cash: "100000.00",
    positions: [],
    realized_pnl: "0.00",
    unrealized_pnl: "0.00",
    total_fees: "0.00",
    total_equity: "100000.00",
    bankrupt: false,
    version: 0,
    as_of: "2026-11-21T00:00:00Z",
    valuation_incomplete: false,
  },
};
const evaluation = {
  evaluation_id: "eval",
  status: "PENDING_APPROVAL",
  portfolio_version: 0,
  decision: { action: "BUY", symbol: "NVDA" },
  order_intent: {
    symbol: "NVDA",
    side: "BUY",
    quantity: "50.000000",
    price: "100",
    notional: "5000",
    fee: "2.50",
  },
  rule_results: [],
  reasons: [],
};
function renderQuery(view: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{view}</QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  // jsdom omits native dialogs; Chromium verifies their actual modal behavior.
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.mocked(getSimulationReports).mockResolvedValue({
    items: [
      {
        artifact_id: "1".repeat(16),
        ticker: "NVDA",
        date: "2026-11-01",
        rating: "Buy",
      },
    ],
  });
  vi.mocked(getSimulationAudit).mockResolvedValue({
    verified: null,
    items: [],
    total: 0,
  });
});
afterEach(cleanup);

describe("simulated trading controls", () => {
  it("validates scenario rows without accepting invalid dates or duplicate days", () => {
    const input = {
      source: "scenario" as const,
      symbol: "NVDA",
      start: "2026-11-02",
      end: "2026-11-03",
      initial_cash: "10000",
      rows: [{ date: "2026-11-02", action: "BUY" as const, price: "100" }],
    };
    expect(validateSimulationJob(input)).toBeNull();
    expect(
      validateSimulationJob({ ...input, rows: [...input.rows, ...input.rows] }),
    ).toMatch(/unique/);
    expect(
      validateSimulationJob({
        ...input,
        rows: [{ ...input.rows[0], price: "0" }],
      }),
    ).toMatch(/positive/);
    expect(validateSimulationJob({ ...input, start: "2026-02-31" })).toMatch(
      /date range/,
    );
    expect(validateSimulationJob({ ...input, symbol: "../../secret" })).toMatch(
      /symbol/,
    );
    expect(
      validateSimulationJob({ ...input, source: "research", rows: [] }),
    ).toBeNull();
  });
  it("initializes with decimal strings only after valid input", async () => {
    const changed = vi.fn();
    render(<SimulationAccount state={base} busy={false} changed={changed} />);
    fireEvent.change(screen.getByLabelText("Initial cash"), {
      target: { value: "NaN" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create simulated account" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a nonnegative decimal amount.",
    );
    expect(simulationPost).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Initial cash"), {
      target: { value: "10000.00" },
    });
    await act(async () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Create simulated account" }),
      ),
    );
    expect(simulationPost).toHaveBeenCalledWith("/account", {
      initial_cash: "10000.00",
      confirm: "INITIALIZE",
    });
    expect(changed).toHaveBeenCalled();
  });
  it("requires typed reset confirmation and captures the account epoch and version", async () => {
    render(<SimulationAccount state={ready} busy={false} changed={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Reset account" }));
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByRole("button", { name: "Reset account" }),
    ).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Type RESET to confirm."), {
      target: { value: "RESET" },
    });
    await act(async () =>
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Reset account" }),
      ),
    );
    expect(simulationPost).toHaveBeenCalledWith(
      "/account",
      expect.objectContaining({
        confirm: "RESET",
        expected_version: 0,
        expected_account_id: accountId,
      }),
    );
  });
  it("retries an uncertain decision with the same request identity and never sends quantity or authority", async () => {
    vi.mocked(simulationPost).mockRejectedValue(
      new Error("Temporary response failure"),
    );
    renderQuery(
      <SimulationDecisions state={ready} busy={false} changed={vi.fn()} />,
    );
    await screen.findByRole("option", { name: /NVDA/ });
    fireEvent.change(screen.getByLabelText("Completed analysis report"), {
      target: { value: "1".repeat(16) },
    });
    fireEvent.change(screen.getByLabelText("Scenario price"), {
      target: { value: "100.00" },
    });
    await act(async () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Evaluate & simulate" }),
      ),
    );
    await screen.findByText("Temporary response failure");
    await act(async () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Evaluate & simulate" }),
      ),
    );
    const first = vi.mocked(simulationPost).mock.calls[0][1] as Record<
        string,
        unknown
      >,
      second = vi.mocked(simulationPost).mock.calls[1][1];
    expect(second).toEqual(first);
    expect(first).toMatchObject({
      quote_price: "100.00",
      expected_account_id: accountId,
      expected_version: 0,
    });
    expect(first).not.toHaveProperty("quantity");
    expect(first).not.toHaveProperty("status");
  });
  it("requires a human name and reason and submits only an issued approval identity", async () => {
    const pending = {
      request_id: "request-1",
      state: "pending",
      receipt_id: "receipt-1",
      evaluation,
      request: { expires_at: "2026-11-21T00:15:00Z" },
    };
    const result: SimTransaction = {
      id: "receipt-1",
      ticker: "NVDA",
      created_at: "2026-11-21T00:00:00Z",
      result: {
        evaluation: { ...evaluation, status: "APPROVED" },
        execution: null,
      },
    };
    vi.mocked(simulationPost).mockResolvedValue(result);
    renderQuery(
      <SimulationDecisions
        state={{ ...ready, pending: [pending] }}
        busy={false}
        changed={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve & simulate" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Provide your name");
    expect(simulationPost).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Approver name"), {
      target: { value: "Reviewer" },
    });
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Position size reviewed" },
    });
    await act(async () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Approve & simulate" }),
      ),
    );
    expect(simulationPost).toHaveBeenCalledWith("/approvals/request-1", {
      approved: true,
      approver: "Reviewer",
      reason: "Position size reviewed",
      expected_version: 0,
      expected_account_id: accountId,
    });
  });
  it("disables expired approvals and does not invent audit verification", async () => {
    const view = renderQuery(
      <SimulationDecisions
        state={{
          ...ready,
          pending: [
            {
              request_id: "expired",
              state: "expired",
              receipt_id: "old",
              evaluation,
              request: { expires_at: "2026-11-01T00:00:00Z" },
            },
          ],
        }}
        busy={false}
        changed={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Approve & simulate" }),
    ).toBeDisabled();
    view.unmount();
    renderQuery(<SimulationAudit jobs={[]} />);
    await screen.findByText("Create an account before inspecting its audit.");
    expect(screen.queryByText(/Verified audit/)).not.toBeInTheDocument();
  });
  it("renders event payloads as inert data and preserves server hash evidence", async () => {
    vi.mocked(getSimulationAudit).mockResolvedValue({
      verified: true,
      total: 1,
      items: [
        {
          event_id: "event",
          timestamp: "2026-11-21T00:00:00Z",
          event_type: "ORDER_EXECUTED",
          run_id: "sim_run",
          payload: { text: "<script>window.evil=true</script>" },
          prev_hash: "abc",
          entry_hash: "def",
        },
      ],
    });
    renderQuery(<SimulationAudit jobs={[]} />);
    await screen.findByRole("button", { name: "Inspect event" });
    fireEvent.click(screen.getByRole("button", { name: "Inspect event" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
    expect(document.querySelector(".sim-json")?.textContent).toContain(
      "<script>",
    );
    expect(document.querySelector(".sim-json script")).toBeNull();
    expect(screen.getByText("def")).toBeVisible();
  });
});
