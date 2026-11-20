// REQ-WEB-008/009, NFR-CMP-001, ADR-002/003: observable projection states.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuditPage } from "../src/pages/AuditPage";
import { ComparisonPage } from "../src/pages/ComparisonPage";
import { getAllHistory } from "../src/api/client";
import {
  getAudit,
  getComparison,
  getComparisons,
  previewAudit,
  type AuditView,
} from "../src/api/auditClient";
import "../src/i18n";

vi.mock("../src/api/client", () => ({ getAllHistory: vi.fn() }));
vi.mock("../src/api/auditClient", async (original) => ({
  ...(await original<typeof import("../src/api/auditClient")>()),
  getAudit: vi.fn(),
  getRunAudit: vi.fn(),
  getComparison: vi.fn(),
  getComparisons: vi.fn(),
  previewAudit: vi.fn(),
}));
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  // jsdom does not implement the native dialog API; Chromium covers focus/modal behavior.
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.mocked(getAllHistory).mockResolvedValue({ items: [], next_cursor: null });
});
function mount(
  page: React.ReactNode,
  url = "/audit?artifact_id=aaaaaaaaaaaaaaaa",
) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[url]}>{page}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function audit(): AuditView {
  return {
    schema_version: "1.0",
    artifact_id: "aaaaaaaaaaaaaaaa",
    ticker: "NVDA",
    trade_date: "2026-11-01",
    available: true,
    artifact_availability: "partial",
    sanitized: true,
    eligible_evidence_ids: ["e-1"],
    consistency: { status: "recorded", issues: [] },
    artifacts: [
      {
        kind: "run_summary",
        filename: "run_summary.json",
        status: "available",
        available: true,
      },
      {
        kind: "debate_trace",
        filename: "2_research/debate_trace.json",
        status: "missing",
        available: false,
      },
    ],
    data: {
      evidence_manifest: {
        verdict: "degraded",
        evidence_records: [
          {
            evidence_id: "e-1",
            metric_name: "close",
            source_name: "yfinance",
            quality_status: "Medium",
            observed_at: "2026-11-01",
            validation_results: [],
          },
          {
            evidence_id: "e-2",
            metric_name: "future",
            quality_status: "Low",
            validation_results: [],
          },
        ],
      },
      run_summary: {
        whole_run_usage: {
          completeness: "unknown",
          totals: { calls: 0, tokens: 0 },
          by_phase: {},
        },
      },
    },
  };
}

it("keeps legacy absence distinct from a passed gate or zero usage", async () => {
  vi.mocked(getAudit).mockResolvedValue({
    ...audit(),
    available: false,
    data: {},
    artifacts: [],
    artifact_availability: "absent",
  });
  mount(<AuditPage />);
  expect(
    await screen.findByText("No structured audit recorded"),
  ).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(screen.getByText("Accounting · unknown")).toBeInTheDocument();
});

it("filters real records and previews only available families while unknown totals stay unknown", async () => {
  vi.mocked(getAudit).mockResolvedValue(audit());
  vi.mocked(previewAudit).mockResolvedValue('{"sanitized":true}');
  mount(<AuditPage />);
  expect(await screen.findByText("e-1")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Filter evidence"), {
    target: { value: "excluded" },
  });
  expect(screen.queryByText("e-1")).not.toBeInTheDocument();
  expect(screen.getByText("e-2")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Budget & usage" }));
  expect(screen.getByText("—")).toBeInTheDocument();
  expect(
    screen.getByText(/Unknown telemetry is not zero cost/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Artifacts" }));
  const previews = screen.getAllByRole("button", { name: "Preview" });
  expect(previews[1]).toBeDisabled();
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
    "href",
    "/api/history/aaaaaaaaaaaaaaaa/audit/artifacts/run_summary?download=true",
  );
  fireEvent.click(previews[0]);
  expect(await screen.findByText('{"sanitized":true}')).toBeInTheDocument();
});

it("surfaces artifact disagreement instead of presenting a trusted normal verdict", async () => {
  const data = audit();
  data.consistency = {
    status: "inconsistent",
    issues: ["gate_verdict_mismatch"],
  };
  vi.mocked(getAudit).mockResolvedValue(data);
  mount(<AuditPage />);
  expect(
    await screen.findByText("Audit artifacts disagree."),
  ).toBeInTheDocument();
  expect(screen.getByText("gate_verdict_mismatch")).toBeInTheDocument();
});

it("uses core replay results, keeps input exhaustion distinct from early stop, and blocks mismatched exports", async () => {
  vi.mocked(getComparisons).mockResolvedValue({
    scope: "scripted_offline",
    representative_cases: 3,
    regression_cases: 1,
    rubric_dimensions: ["source_attribution"],
    cases: [
      {
        case_id: "D",
        title: "No new evidence",
        role: "representative",
        identity: { ticker: "NVDA" },
      },
      {
        case_id: "G",
        title: "Input exhaustion",
        role: "regression",
        identity: { ticker: "NVDA" },
      },
    ],
  });
  vi.mocked(getComparison).mockImplementation(async (id, dynamic) => {
    if (id !== dynamic)
      throw new Error("Comparison case identities do not match.");
    return {
      case_id: id,
      dynamic_case_id: dynamic,
      title: id,
      scope: "scripted_offline",
      role: "regression",
      identity: { ticker: "NVDA" },
      policy: { max_debate_rounds: 3 },
      fixed: {
        debate_rounds: 2,
        llm_calls: 4,
        total_tokens: 120,
        stop_reason: "input_exhausted",
        early_stopped: false,
      },
      dynamic: {
        debate_rounds: 2,
        llm_calls: 4,
        total_tokens: 120,
        stop_reason: "input_exhausted",
        early_stopped: false,
      },
      report: { paired_cases: [] },
      rubric_dimensions: ["source_attribution"],
    };
  });
  mount(<ComparisonPage />, "/comparison");
  expect(
    await screen.findByRole("link", { name: "Export comparison" }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Inspect case"), {
    target: { value: "G" },
  });
  await waitFor(() => expect(getComparison).toHaveBeenCalledWith("G", "G"));
  expect(
    await screen.findByText(/Input exhaustion is a regression/),
  ).toBeInTheDocument();
  expect(screen.getAllByText("No early stop")).toHaveLength(2);
  expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
  fireEvent.change(screen.getByLabelText("Pairing check"), {
    target: { value: "mismatch" },
  });
  expect(await screen.findByText("Comparison blocked.")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Export comparison" }),
  ).toBeDisabled();
  expect(screen.queryByText("Dynamic termination")).not.toBeInTheDocument();
  expect(getComparison).toHaveBeenCalledWith("G", "D");
});
