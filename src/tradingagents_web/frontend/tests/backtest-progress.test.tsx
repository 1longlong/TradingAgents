// REQ-WEB-007/011/021, INV-WEB-014, ADR-007-run-controls.md: truthful progress and settlement.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import "../src/i18n";
import { BacktestProgress } from "../src/pages/Backtest/BacktestProgress";
import type { BacktestSnapshot } from "../src/api/backtestClient";

afterEach(cleanup);
function snapshot(): BacktestSnapshot {
  return {
    run_id: "bt_progress",
    status: "running",
    progress: {
      phase: "analyzing",
      current_ticker: "NVDA",
      current_date: "2026-06-08",
      processed: 1,
      total: 3,
      completed: 1,
      failed: 0,
      skipped: 0,
      settlements_completed: 0,
      settlements_failed: 0,
      settlements_total: 1,
      observed: true,
      elapsed_seconds: 12.5,
      updated_at: "2026-06-08T12:00:00Z",
      offset: 0,
      limit: 25,
      cells: [
        {
          ticker: "NVDA",
          date: "2026-06-01",
          status: "completed",
          started_at: null,
          finished_at: null,
          elapsed_seconds: 8,
        },
        {
          ticker: "NVDA",
          date: "2026-06-08",
          status: "running",
          started_at: null,
          finished_at: null,
          elapsed_seconds: 4.5,
        },
        {
          ticker: "NVDA",
          date: "2026-06-15",
          status: "pending",
          started_at: null,
          finished_at: null,
          elapsed_seconds: null,
        },
      ],
    },
  };
}

it("shows current observed dates and does not confuse all cells processed with a completed backtest", () => {
  const current = snapshot();
  const { rerender } = render(
    <BacktestProgress snapshot={current} onPage={vi.fn()} />,
  );
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "1");
  expect(screen.getByRole("progressbar")).toHaveAttribute("max", "3");
  expect(screen.getByRole("status")).toHaveTextContent("NVDA · Jun 8, 2026");
  expect(screen.getByText("Pending", { exact: true })).toBeVisible();
  const p = current.progress!;
  p.phase = "settling";
  p.current_date = null;
  p.processed = 3;
  p.completed = 1;
  p.failed = 1;
  p.skipped = 1;
  p.cells[1].status = "failed";
  p.cells[2].status = "skipped";
  rerender(<BacktestProgress snapshot={current} onPage={vi.fn()} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "3");
  expect(screen.getByRole("status")).toHaveTextContent("Settling outcomes");
  expect(
    screen.getByText("All analysis dates processed. Settling outcomes 0 / 1."),
  ).toBeVisible();
  expect(screen.getByText("Failed", { exact: true })).toBeVisible();
  expect(screen.getByText("Skipped", { exact: true })).toBeVisible();
});

it("pages details in place and lets a manual page return to the current date", () => {
  const current = snapshot(),
    onPage = vi.fn();
  current.progress!.total = 50;
  const { rerender } = render(
    <BacktestProgress snapshot={current} onPage={onPage} />,
  );
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(onPage).toHaveBeenLastCalledWith(25);
  current.progress!.offset = 25;
  rerender(<BacktestProgress snapshot={current} offset={25} onPage={onPage} />);
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Follow current date" }));
  expect(onPage).toHaveBeenLastCalledWith(undefined);
});

it("does not invent per-date success for a legacy saved artifact", () => {
  const { container } = render(
    <BacktestProgress
      snapshot={{ run_id: "legacy", status: "completed" }}
      onPage={vi.fn()}
    />,
  );
  expect(container).toBeEmptyDOMElement();
});
