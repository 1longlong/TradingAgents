import { expect, test } from "@playwright/test";

async function requireBacktestApi(request: import("@playwright/test").APIRequestContext) {
  const response = await request.get("/api/backtests");
  if (response.status() === 404) {
    throw new Error("EXPECTED-UNIMPLEMENTED: /api/backtests is not implemented yet");
  }
  expect(response.status()).toBe(200);
}

test("backtest form starts a sweep and renders the summary", async ({
  page,
  request,
}) => {
  await requireBacktestApi(request);
  await page.goto("/backtest");
  await expect(page.getByRole("heading", { name: /backtest/i })).toBeVisible();

  await page.getByLabel(/tickers/i).fill("NVDA,AAPL");
  await page.getByLabel(/start/i).fill("2026-06-01");
  await page.getByLabel(/end/i).fill("2026-06-08");
  await page.getByRole("button", { name: /run backtest/i }).click();

  await page.waitForURL(/\/backtest\/bt_/);
  await expect(page.getByText(/resolved/i)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/pending/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /cancel/i })).toHaveCount(0);
});
