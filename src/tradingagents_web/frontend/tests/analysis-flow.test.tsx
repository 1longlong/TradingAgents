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
  getActiveRun,
  validatePortfolio,
} from "../src/api/runClient";

vi.mock("../src/api/runClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/runClient")>()),
  getRunConfig: vi.fn(),
  getRunModels: vi.fn(),
  getRun: vi.fn(),
  startRun: vi.fn(),
  cancelRun: vi.fn(),
  runEventsUrl: vi.fn(),
  getActiveRun: vi.fn(),
  validatePortfolio: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(getActiveRun).mockResolvedValue({ run_id: null });
  vi.mocked(validatePortfolio).mockResolvedValue({ valid: true });
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
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
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
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText(/Ticker symbol/), {
      target: { value: "NVDA" },
    });
    await next();
    expect(screen.getByLabelText("Model provider")).toHaveValue("deepseek");
    expect(screen.getByText(/Key configured/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Model provider"), {
      target: { value: "openai" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
    );
    expect(screen.getByLabelText("Quick model")).toHaveValue("gpt-4o-mini");
    expect(screen.getByLabelText("Deep model")).toHaveValue("gpt-4o");
    await next();
    vi.mocked(startRun).mockRejectedValueOnce(
      new Error("The provider rejected authentication. (c_123)"),
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start analysis" }));
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

// REQ-WEB-001/013, FR-DDT-004: settings reach real-run requests, not the fixture comparison endpoint.
it("submits custom debate settings and preserves independent risk rounds across presets", async () => {
  const defaults = {
    enabled: true,
    max_debate_rounds: 1,
    no_new_evidence_patience: 1,
    stance_distance_threshold: 1,
    confidence_delta_threshold: 0.25,
    max_calls: 30,
    max_tokens: 50000,
    max_time: 600,
    reserved_summary_tokens: 4000,
    reserved_summary_seconds: 90,
    next_round_estimate_tokens: 2000,
    next_round_estimate_seconds: 60,
  };
  const config = await vi.mocked(getRunConfig)();
  vi.mocked(getRunConfig).mockResolvedValue({
    ...config,
    defaults: {
      ...config.defaults,
      debate_termination: defaults,
      max_risk_discuss_rounds: 1,
    },
  });
  render(
    <MemoryRouter>
      <NewAnalysisPage />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText(/Ticker symbol/), {
    target: { value: "NVDA" },
  });
  await next();
  fireEvent.click(screen.getByText("Debate rules & budgets"));
  fireEvent.change(screen.getByLabelText("Risk discussion rounds"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByLabelText(/Deep.*5 debate rounds/));
  expect(screen.getByLabelText("Maximum debate rounds")).toHaveValue(5);
  expect(screen.getByLabelText("Risk discussion rounds")).toHaveValue(2);
  fireEvent.change(screen.getByLabelText("Maximum debate rounds"), {
    target: { value: "4" },
  });
  fireEvent.change(screen.getByLabelText("Debate mode"), {
    target: { value: "fixed" },
  });
  fireEvent.change(screen.getByLabelText("Summary token reserve"), {
    target: { value: "50000" },
  });
  await next();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Summary token reserve must be below the debate token budget.",
  );
  expect(startRun).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Summary token reserve"), {
    target: { value: "3000" },
  });
  await next();
  expect(screen.getByText(/Selected debate settings/)).toBeVisible();
  vi.mocked(startRun).mockRejectedValueOnce(
    new Error("Offline request captured"),
  );
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "Start analysis" })),
  );
  expect(startRun).toHaveBeenCalledWith(
    expect.objectContaining({
      research_depth: 4,
      max_risk_discuss_rounds: 2,
      debate_termination: {
        ...defaults,
        enabled: false,
        max_debate_rounds: 4,
        reserved_summary_tokens: 3000,
      },
    }),
  );
  expect(JSON.stringify(vi.mocked(startRun).mock.calls)).not.toContain(
    "trace_field",
  );
});

it("restores safe debate drafts while current server round locks stay authoritative", async () => {
  const policy = {
    enabled: false,
    max_debate_rounds: 5,
    no_new_evidence_patience: 2,
    stance_distance_threshold: 0.5,
    confidence_delta_threshold: 0.1,
    max_calls: 20,
    max_tokens: 50000,
    max_time: 900,
    reserved_summary_tokens: 5000,
    reserved_summary_seconds: 120,
    next_round_estimate_tokens: 3000,
    next_round_estimate_seconds: 45,
  };
  localStorage.setItem(
    "ta.analysisDraft",
    JSON.stringify({
      ticker: "NVDA",
      depth: 5,
      debatePolicy: { ...policy, trace_field: "private" },
      riskRounds: 9,
      riskIndependent: true,
      endpoint: "private-endpoint",
      portfolio: "private-portfolio",
    }),
  );
  const config = await vi.mocked(getRunConfig)();
  vi.mocked(getRunConfig).mockResolvedValue({
    ...config,
    defaults: {
      ...config.defaults,
      research_depth: 4,
      debate_termination: {
        ...policy,
        enabled: true,
        max_debate_rounds: 4,
        max_calls: 30,
      },
      max_risk_discuss_rounds: 2,
    },
    env_locks: { max_debate_rounds: true, max_risk_discuss_rounds: true },
  });
  const view = render(
    <MemoryRouter>
      <NewAnalysisPage />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
  );
  await next();
  fireEvent.click(screen.getByText("Debate rules & budgets"));
  expect(screen.getByLabelText("Maximum debate rounds")).toHaveValue(4);
  expect(screen.getByLabelText("Maximum debate rounds")).toBeDisabled();
  expect(screen.getByLabelText("Risk discussion rounds")).toHaveValue(2);
  expect(screen.getByLabelText("Risk discussion rounds")).toBeDisabled();
  expect(screen.getByLabelText("Maximum debate model calls")).toHaveValue(20);
  expect(screen.getByLabelText("Debate mode")).toHaveValue("fixed");
  view.unmount();
  const saved = localStorage.getItem("ta.analysisDraft")!;
  expect(JSON.parse(saved).debatePolicy.max_debate_rounds).toBe(4);
  expect(saved).not.toMatch(/trace_field|private-endpoint|private-portfolio/);
});

it("refreshes OpenRouter without replacing custom IDs and allows manual entry after failure", async () => {
  const config = await vi.mocked(getRunConfig)();
  vi.mocked(getRunConfig).mockResolvedValue({
    ...config,
    providers: [
      ...config.providers,
      { key: "openrouter", label: "OpenRouter", default_url: null },
    ],
  });
  vi.mocked(getRunModels).mockImplementation(
    async (_provider, _mode, refresh) => ({
      models: [
        {
          value: refresh ? "openai/new-model" : "openai/model",
          label: "Suggestion",
        },
        { value: "custom", label: "Custom model ID" },
      ],
      ...(refresh
        ? {
            warning:
              "Model list unavailable; showing cached suggestions. You can still enter a model ID.",
          }
        : {}),
    }),
  );
  render(
    <MemoryRouter>
      <NewAnalysisPage />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText(/Ticker symbol/), {
    target: { value: "NVDA" },
  });
  await next();
  fireEvent.change(screen.getByLabelText("Model provider"), {
    target: { value: "openrouter" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Refresh model list" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText("Quick model"), {
    target: { value: "custom/quick" },
  });
  fireEvent.change(screen.getByLabelText("Deep model"), {
    target: { value: "custom/deep" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Refresh model list" }));
  await screen.findByText(/showing cached suggestions/);
  expect(getRunModels).toHaveBeenCalledWith("openrouter", "quick", true);
  expect(getRunModels).toHaveBeenCalledWith("openrouter", "deep", true);
  expect(screen.getByLabelText("Quick model")).toHaveValue("custom/quick");
  expect(screen.getByLabelText("Deep model")).toHaveValue("custom/deep");
  vi.mocked(getRunModels)
    .mockRejectedValueOnce(new Error("request failed"))
    .mockRejectedValueOnce(new Error("request failed"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh model list" }));
  await screen.findByText(
    "OpenRouter model list is unavailable. Enter a model ID manually.",
  );
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  expect(screen.getByLabelText("Quick model")).toHaveValue("custom/quick");
});

// REQ-WEB-001/003/013, ADR-001-choice.md: environment models preselect editable controls.
it("prefills configured models over stale preferences and drafts, then submits the user's selection", async () => {
  const config = await getRunConfig();
  config.defaults = {
    ...config.defaults,
    llm_provider: "deepseek",
    quick_think_llm: "deepseek-flash",
    deep_think_llm: "deepseek-flash",
  };
  config.env_defaults = {
    llm_provider: true,
    quick_think_llm: true,
    deep_think_llm: true,
  };
  config.env_locks = { backend_url: true };
  config.prefs = {
    llm_provider: "openai",
    quick_think_llm: "stale-quick",
    deep_think_llm: "stale-deep",
  };
  vi.mocked(getRunConfig).mockResolvedValue(config);
  localStorage.setItem(
    "ta.analysisDraft",
    JSON.stringify({
      ticker: "NVDA",
      provider: "openai",
      quick: "old-quick",
      deep: "old-deep",
    }),
  );
  vi.mocked(startRun).mockRejectedValueOnce(
    new Error("Offline request captured"),
  );
  render(
    <MemoryRouter>
      <NewAnalysisPage />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
  );
  await next();
  expect(screen.getByLabelText("Model provider")).toHaveValue("deepseek");
  expect(screen.getByLabelText("Model provider")).toBeEnabled();
  expect(screen.getByLabelText("Quick model")).toHaveValue("deepseek-flash");
  expect(screen.getByLabelText("Quick model")).toBeEnabled();
  expect(screen.getByLabelText("Deep model")).toHaveValue("deepseek-flash");
  expect(screen.getByLabelText("Deep model")).toBeEnabled();
  expect(screen.getByText(/Server default/)).toBeVisible();
  fireEvent.click(
    screen.getByText("Endpoint & model thinking", { exact: true }),
  );
  expect(screen.getByLabelText("Endpoint override (optional)")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Model provider"), {
    target: { value: "openai" },
  });
  await waitFor(() =>
    expect(screen.getByLabelText("Quick model")).toHaveValue("gpt-4o-mini"),
  );
  expect(screen.getByLabelText("Deep model")).toHaveValue("gpt-4o");
  expect(screen.getByLabelText("Endpoint override (optional)")).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Endpoint override (optional)"), {
    target: { value: "https://one-provider.test/v1" },
  });
  fireEvent.change(screen.getByLabelText("Model provider"), {
    target: { value: "deepseek" },
  });
  await waitFor(() =>
    expect(screen.getByLabelText("Quick model")).toBeEnabled(),
  );
  expect(screen.getByLabelText("Quick model")).toHaveValue("deepseek-flash");
  expect(screen.getByLabelText("Deep model")).toHaveValue("deepseek-flash");
  expect(screen.getByLabelText("Endpoint override (optional)")).toHaveValue("");
  expect(screen.getByLabelText("Endpoint override (optional)")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Model provider"), {
    target: { value: "openai" },
  });
  await waitFor(() =>
    expect(screen.getByLabelText("Quick model")).toHaveValue("gpt-4o-mini"),
  );
  await next();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Start analysis" }));
  });
  expect(startRun).toHaveBeenCalledWith(
    expect.objectContaining({
      llm_provider: "openai",
      quick_think_llm: "gpt-4o-mini",
      deep_think_llm: "gpt-4o",
    }),
  );
  expect(vi.mocked(startRun).mock.calls[0][0]).not.toHaveProperty(
    "backend_url",
  );
});

it("retains a deliberately changed provider in a matching draft but refreshes it when server model defaults change", async () => {
  const config = await getRunConfig();
  config.defaults = {
    ...config.defaults,
    llm_provider: "deepseek",
    quick_think_llm: "deepseek-flash",
    deep_think_llm: "deepseek-flash",
  };
  config.env_defaults = {
    llm_provider: true,
    quick_think_llm: true,
    deep_think_llm: true,
  };
  vi.mocked(getRunConfig).mockResolvedValue(config);
  localStorage.setItem(
    "ta.analysisDraft",
    JSON.stringify({
      ticker: "NVDA",
      provider: "openai",
      quick: "chosen-quick",
      deep: "chosen-deep",
      modelDefaults: JSON.stringify([
        "deepseek",
        "deepseek-flash",
        "deepseek-flash",
      ]),
    }),
  );
  const first = render(
    <MemoryRouter>
      <NewAnalysisPage />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
  );
  await next();
  expect(screen.getByLabelText("Model provider")).toHaveValue("openai");
  expect(screen.getByLabelText("Quick model")).toHaveValue("chosen-quick");
  first.unmount();
  const draft = localStorage.getItem("ta.analysisDraft")!;
  expect(JSON.parse(draft).modelDefaults).toBe(
    JSON.stringify(["deepseek", "deepseek-flash", "deepseek-flash"]),
  );
  expect(draft).not.toContain("endpoint");
  expect(draft).not.toContain("portfolio");
  config.defaults.deep_think_llm = "new-server-model";
  render(
    <MemoryRouter>
      <NewAnalysisPage />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
  );
  await next();
  expect(screen.getByLabelText("Model provider")).toHaveValue("deepseek");
  expect(screen.getByLabelText("Deep model")).toHaveValue("new-server-model");
});
