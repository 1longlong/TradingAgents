import { expect, test } from "@playwright/test";

async function advanceToPortfolio(page: import("@playwright/test").Page) {
  // From the date step, six Next clicks reach the portfolio/submit step.
  for (let index = 0; index < 6; index += 1) {
    await page.getByRole("button", { name: /next/i }).click();
  }
}

test("history page loads existing artifacts and opens a report", async ({
  page,
}) => {
  await page.goto("/history");
  await expect(
    page.getByRole("heading", { name: /run history/i }),
  ).toBeVisible();
  const row = page.getByRole("row", { name: /NVDA/ }).first();
  await expect(row).toBeVisible();
  await row.getByRole("link", { name: /open/i }).click();
  await expect(page.getByRole("heading", { name: /NVDA/i })).toBeVisible();
});

test("wizard starts a run and shows the completed live report", async ({
  page,
}) => {
  await page.goto("/new");
  await expect(
    page.getByRole("heading", { name: /new analysis/i }),
  ).toBeVisible();
  await page.getByLabel(/ticker/i).fill("NVDA");
  await page.getByRole("button", { name: /next/i }).click();
  await expect(
    page.getByRole("heading", { name: /analysis date/i }),
  ).toBeVisible();

  await advanceToPortfolio(page);
  await page.getByRole("button", { name: /start analysis/i }).click();
  await page.waitForURL(/\/runs\/r_/);
  await expect(page.getByRole("heading", { name: /live run/i })).toBeVisible();
  await expect(page.getByText(/Status: completed/i)).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText(/E2E working/)).toBeVisible();
  await expect(page.getByText(/E2E market report/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/Status: completed/i)).toBeVisible();
  await expect(page.getByText(/E2E working/)).toBeVisible();
  await expect(page.getByText(/E2E market report/)).toBeVisible();
});

test("live run can be cancelled", async ({ page }) => {
  await page.goto("/new");
  await page.getByLabel(/ticker/i).fill("AAPL");
  await page.getByRole("button", { name: /next/i }).click();
  await advanceToPortfolio(page);
  await page.getByRole("button", { name: /start analysis/i }).click();
  await page.waitForURL(/\/runs\/r_/);
  await expect(page.getByRole("heading", { name: /live run/i })).toBeVisible();
  await page.getByRole("button", { name: /^cancel$/i }).click();
  await expect(page.getByText(/Status: cancelled/i)).toBeVisible({
    timeout: 15_000,
  });
});
