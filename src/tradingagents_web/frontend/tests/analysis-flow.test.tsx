import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../src/i18n";
import { NewAnalysisPage } from "../src/pages/NewAnalysisPage";
import { LiveRunPage } from "../src/pages/LiveRunPage";
import {
  getRunConfig,
  getRunModels,
  getRun,
  startRun,
} from "../src/api/runClient";

vi.mock("../src/api/runClient", () => ({
  getRunConfig: vi.fn(),
  getRunModels: vi.fn(),
  getRun: vi.fn(),
  startRun: vi.fn(),
  cancelRun: vi.fn(),
  runEventsUrl: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getRunConfig).mockResolvedValue({
    defaults: {
      llm_provider: "deepseek",
      quick_think_llm: "deepseek-chat",
      deep_think_llm: "deepseek-reasoner",
      output_language: "English",
    },
    providers: [
      { key: "deepseek", label: "DeepSeek", default_url: null },
      { key: "openai", label: "OpenAI", default_url: null },
    ],
    env_locks: {},
    key_status: { deepseek: "configured", openai: "not_configured" },
    prefs: {},
  });
  vi.mocked(getRunModels).mockImplementation(async (provider, mode) => ({
    models: [
      {
        value:
          provider === "deepseek"
            ? mode === "quick"
              ? "deepseek-chat"
              : "deepseek-reasoner"
            : mode === "quick"
              ? "gpt-4o-mini"
              : "gpt-4o",
        label: mode,
      },
      { value: "custom", label: "Custom" },
    ],
  }));
});
async function next() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
  });
}

// REQ-WEB-001/013: submitted models must belong to the selected provider.
describe("analysis configuration", () => {
  it("loads defaults and changes models with the provider", async () => {
    render(
      <MemoryRouter>
        <NewAnalysisPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Next" })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText("Ticker"), {
      target: { value: "NVDA" },
    });
    for (let i = 0; i < 5; i++) await next();
    expect(screen.getByRole("combobox")).toHaveValue("deepseek");
    expect(screen.getByText("Key configured")).toBeVisible();
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "openai" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Next" })).toBeEnabled(),
    );
    await next();
    expect(screen.getByLabelText("Quick model")).toHaveValue("gpt-4o-mini");
    expect(screen.getByLabelText("Deep model")).toHaveValue("gpt-4o");
    await next();
    vi.mocked(startRun).mockRejectedValueOnce(
      new Error("The provider rejected authentication. (c_123)"),
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start Analysis" }));
    });
    expect(startRun).toHaveBeenCalledWith(
      expect.objectContaining({
        llm_provider: "openai",
        quick_think_llm: "gpt-4o-mini",
        deep_think_llm: "gpt-4o",
      }),
    );
    expect(screen.getByText(/rejected authentication/)).toBeVisible();
  });
});

// REQ-WEB-007: terminal snapshots are sufficient; do not open/reconnect SSE.
it("shows a completed report on reload without opening SSE", async () => {
  const eventSource = vi.fn();
  vi.stubGlobal("EventSource", eventSource);
  vi.mocked(getRun).mockResolvedValue({
    run_id: "r1",
    status: "completed",
    ticker: "NVDA",
    trade_date: "2026-11-01",
    last_seq: 10,
    signal: "Buy",
    review: false,
    warnings: [],
    sections: { market_report: "Restored report" },
  } as Awaited<ReturnType<typeof getRun>>);
  render(
    <MemoryRouter initialEntries={["/runs/r1"]}>
      <Routes>
        <Route path="/runs/:runId" element={<LiveRunPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText("Restored report")).toBeVisible();
  expect(getRun).toHaveBeenCalledWith("r1");
  expect(eventSource).not.toHaveBeenCalled();
});

it("displays failure details when reopening an already failed run", async () => {
  const eventSource = vi.fn();
  vi.stubGlobal("EventSource", eventSource);
  vi.mocked(getRun).mockResolvedValue({
    run_id: "r1",
    status: "failed",
    ticker: "NVDA",
    trade_date: "2026-11-01",
    last_seq: 3,
    review: false,
    warnings: [],
    error: {
      message: "The provider endpoint or model was not found.",
      correlation_id: "c_failure",
    },
  });
  render(
    <MemoryRouter initialEntries={["/runs/r1"]}>
      <Routes>
        <Route path="/runs/:runId" element={<LiveRunPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "model was not found",
  );
  expect(screen.getByRole("alert")).toHaveTextContent("c_failure");
  expect(eventSource).not.toHaveBeenCalled();
});
