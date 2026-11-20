import { expect, test } from "@playwright/test";

// REQ-WEB-001: the same request fields are grouped into the reference's three steps.
async function advanceToPortfolio(page: import("@playwright/test").Page) {
  await expect(
    page.getByRole("heading", { name: "Build your research team." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByRole("heading", { name: "A final look before you begin." }),
  ).toBeVisible();
}

test("history page loads existing artifacts and opens a report", async ({
  page,
}) => {
  await page.goto("/history");
  await expect(
    page.getByRole("heading", { name: /analysis history/i }),
  ).toBeVisible();
  const row = page.getByRole("row", { name: /NVDA/ }).first();
  await expect(row).toBeVisible();
  await row.getByRole("link", { name: /read .* analysis/i }).click();
  await expect(
    page.getByRole("heading", { name: "NVDA analysis", exact: true }),
  ).toBeVisible();
});

test("wizard starts a run and shows the completed live report", async ({
  page,
  request,
}) => {
  await page.goto("/new");
  await expect(page.locator(".sheet[open]")).toBeVisible();
  await page.getByLabel(/ticker symbol/i).fill("NVDA");
  await page.getByRole("button", { name: /^continue$/i }).click();
  await expect(page.getByLabel("Model provider")).toBeVisible();

  await advanceToPortfolio(page);
  await page.getByRole("button", { name: /start analysis/i }).click();
  await page.waitForURL(/\/runs\/r_/);
  await expect(
    page.getByRole("heading", { name: /analysis$/i }).first(),
  ).toBeVisible();
  await expect(page.getByText(/E2E working/)).toBeVisible();
  await expect(
    page.locator(".document-meta").getByText("Completed", { exact: true }),
  ).toBeVisible({
    timeout: 15_000,
  });
  const runId = page.url().split("/").pop();
  expect(
    (await (await request.get(`/api/runs/${runId}`)).json()).messages.some(
      (message: { content?: string }) =>
        message.content?.includes("E2E working"),
    ),
  ).toBe(true);
  await expect(page.getByText(/E2E market report/)).toBeVisible();
  await page.reload();
  await expect(
    page.locator(".document-meta").getByText("Completed", { exact: true }),
  ).toBeVisible();
  expect(
    (await (await request.get(`/api/runs/${runId}`)).json()).messages.some(
      (message: { content?: string }) =>
        message.content?.includes("E2E working"),
    ),
  ).toBe(true);
  await expect(page.getByText(/E2E market report/)).toBeVisible();
});

test("live run can be cancelled", async ({ page }) => {
  await page.goto("/new");
  await page.getByLabel(/ticker symbol/i).fill("AAPL");
  await page.getByRole("button", { name: /^continue$/i }).click();
  await advanceToPortfolio(page);
  await page.getByRole("button", { name: /start analysis/i }).click();
  await page.waitForURL(/\/runs\/r_/);
  await expect(
    page.getByRole("heading", { name: /analysis$/i }).first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /^cancel analysis$/i })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Stop analysis", exact: true })
    .click();
  await expect(
    page.getByText("Stopped before a final decision", { exact: true }),
  ).toBeVisible({
    timeout: 15_000,
  });
});
