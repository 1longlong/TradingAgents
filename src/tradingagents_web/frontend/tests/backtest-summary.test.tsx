import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";

import i18n from "../src/i18n";
import { unimplemented } from "./iteration3-support";

type Summary = {
  resolved: number;
  pending: number;
  unscored: number;
  holding: string;
  by_rating: Record<
    string,
    { count: number; hit_rate: number | null; mean_alpha: number }
  >;
  failures: Array<[string, string, string]>;
  settlement_failures: Array<[string, string]>;
};

type SummaryModule = {
  BacktestSummary: (props: { summary: Summary }) => ReactElement;
};

const modules = import.meta.glob<SummaryModule>(
  "../src/pages/Backtest/BacktestSummary.tsx",
);

async function loadSummary(): Promise<SummaryModule> {
  const loader = modules["../src/pages/Backtest/BacktestSummary.tsx"];
  if (!loader) unimplemented("src/pages/Backtest/BacktestSummary.tsx");
  return loader();
}

const summary: Summary = {
  resolved: 2,
  pending: 1,
  unscored: 1,
  holding: "5 trading days",
  by_rating: {
    Buy: { count: 2, hit_rate: 1, mean_alpha: 0.0123 },
    Hold: { count: 1, hit_rate: null, mean_alpha: 0.001 },
  },
  failures: [["NVDA", "2026-06-08", "vendor unavailable"]],
  settlement_failures: [["AAPL", "settlement unavailable"]],
};

describe("BacktestSummary", () => {
  it("renders the CLI summary fields", async () => {
    const { BacktestSummary } = await loadSummary();
    render(
      <I18nextProvider i18n={i18n}>
        <BacktestSummary summary={summary} />
      </I18nextProvider>,
    );

    expect(screen.getByText(/resolved/i)).toBeInTheDocument();
    expect(screen.getByText(/pending/i)).toBeInTheDocument();
    expect(screen.getByText(/unscored/i)).toBeInTheDocument();
    expect(screen.getByText(/5 trading days/i)).toBeInTheDocument();
    expect(screen.getByText(/Buy/)).toBeInTheDocument();
    expect(screen.getByText(/100%/)).toBeInTheDocument();
    expect(screen.getByText(/1\.23%/)).toBeInTheDocument();
    expect(screen.getByText(/vendor unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/settlement unavailable/i)).toBeInTheDocument();
  });

  it("does not offer backtest cancellation", async () => {
    const { BacktestSummary } = await loadSummary();
    render(
      <I18nextProvider i18n={i18n}>
        <BacktestSummary summary={summary} />
      </I18nextProvider>,
    );
    expect(screen.queryByRole("button", { name: /cancel/i })).toBeNull();
  });
});
