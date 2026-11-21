import { expect, test } from "@playwright/test";

async function requireBacktestApi(
  request: import("@playwright/test").APIRequestContext,
) {
  const response = await request.get("/api/backtests");
  if (response.status() === 404) {
    throw new Error(
      "EXPECTED-UNIMPLEMENTED: /api/backtests is not implemented yet",
    );
  }
  expect(response.status()).toBe(200);
}

test("backtest form starts a sweep and renders the summary", async ({
  page,
  request,
}) => {
  await requireBacktestApi(request);
  await page.goto("/backtest");
  await expect(
    page.getByRole("heading", { name: "Backtesting", exact: true }),
  ).toBeVisible();

  await page.getByLabel(/instruments/i).fill("NVDA,AAPL");
  await page.getByLabel(/sample every/i).fill("5");
  await page.getByLabel(/start/i).fill("2026-06-01");
  await page.getByLabel(/end/i).fill("2026-06-08");
  const submitted = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/api/backtests"),
  );
  await page.getByRole("button", { name: /run backtest/i }).click();
  expect((await submitted).postDataJSON().every).toBe(5);

  await page.waitForURL(/\/backtest\/bt_/);
  await expect(page.getByText(/resolved/i)).toBeVisible({ timeout: 20_000 });
  await expect(
    page.locator(".summary-metrics").getByText(/pending/i),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /cancel/i })).toHaveCount(0);
});

// REQ-WEB-011, INV-WEB-003/014: safe correlated failures remain actionable, never an empty success.
test("backtest failure shows safe diagnostics and reference without an empty-state card", async ({
  page,
}) => {
  await page.route("**/api/backtests/bt_failed", (route) =>
    route.fulfill({
      json: {
        run_id: "bt_failed",
        kind: "backtest",
        status: "failed",
        tickers: ["NVDA"],
        summary: null,
        error: {
          category: "config",
          phase: "backtest",
          correlation_id: "c_012345abcdef",
          message:
            "The server's default model provider is missing its API key. Backtests use server defaults, not analysis-wizard selections.",
        },
      },
    }),
  );
  await page.goto("/backtest/bt_failed");
  const banner = page.getByRole("alert");
  await expect(banner).toContainText("server's default model provider");
  await expect(banner).toContainText("c_012345abcdef");
  await expect(
    page.getByText("No backtest sweeps yet", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Switch to Chinese" }).click();
  await expect(banner).toContainText("服务端默认模型服务商缺少 API Key");
  await expect(banner).toContainText("c_012345abcdef");
});

// REQ-WEB-007/011/021, ADR-007-run-controls.md: real polling while the local fixture remains active.
test("per-date progress survives refresh and stays running through settlement", async ({
  page,
}) => {
  await page.goto("/backtest");
  await page.getByLabel("Instruments", { exact: true }).fill("PROGRESS");
  await page.getByLabel("Start date", { exact: true }).fill("2026-11-02");
  await page.getByLabel("End date", { exact: true }).fill("2026-11-09");
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await page.waitForURL(/\/backtest\/bt_/);
  const progress = page.getByRole("region", {
    name: "Backtest progress",
    exact: true,
  });
  await expect(progress).toBeVisible();
  await expect(progress.getByRole("status")).toContainText("PROGRESS");
  await page.reload();
  await expect(progress).toBeVisible();
  await expect(
    progress.getByRole("row").filter({ hasText: "Nov 9, 2026" }),
  ).toContainText("Analyzing", { timeout: 10000 });
  await expect(progress.getByRole("progressbar")).toHaveAttribute("value", "1");
  await expect(progress.getByRole("status")).toContainText(
    "Settling outcomes",
    { timeout: 10000 },
  );
  await expect(progress.getByRole("progressbar")).toHaveAttribute("value", "2");
  await expect(
    page.getByRole("button", { name: "Sweep in progress", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Switch to Chinese" }).click();
  await expect(
    page.getByRole("region", { name: "回测进度", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect(
    page
      .getByRole("region", { name: "回测进度", exact: true })
      .getByRole("status"),
  ).toContainText("已完成", { timeout: 10000 });
  await expect(page.getByRole("button", { name: /cancel/i })).toHaveCount(0);
});
