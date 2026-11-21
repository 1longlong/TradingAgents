import { expect, test } from "@playwright/test";

// REQ-WEB-001: the same request fields are grouped into the reference's three steps.
async function advanceToPortfolio(page: import("@playwright/test").Page) {
  await expect(
    page.getByRole("heading", { name: "Team & models" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByRole("heading", { name: "Review setup" }),
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
    page.getByRole("tab", { name: /Research debate/ }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("E2E research argument")).toBeVisible();
  await page.getByRole("tab", { name: /Analyst team/ }).click();
  await expect(page.getByText("E2E price data")).toBeVisible();
  await expect(page.getByRole("tab", { name: /Trading plan/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText("E2E trader working")).toBeVisible();
  await expect(page.getByRole("tab", { name: /Risk review/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText("E2E risk argument")).toBeVisible();
  await expect(
    page
      .locator(".page-header-actions")
      .getByText("Completed", { exact: true }),
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
  await page.getByRole("tab", { name: /Analyst team/ }).click();
  await expect(page.getByText(/E2E market report/)).toBeVisible();
  await page
    .getByText("Agent status & analyst timing", { exact: true })
    .click();
  await expect(page.locator(".run-role-list").getByText("1.25s")).toBeVisible();
  await page
    .getByRole("button", { name: "Complete report", exact: true })
    .click();
  await expect(
    page.locator(".document-meta").getByText("Completed", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/E2E market report/)).toBeVisible();
  await page.getByRole("button", { name: "Run activity", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Run activity" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page
      .locator(".page-header-actions")
      .getByText("Completed", { exact: true }),
  ).toBeVisible();
  expect(
    (await (await request.get(`/api/runs/${runId}`)).json()).messages.some(
      (message: { content?: string }) =>
        message.content?.includes("E2E working"),
    ),
  ).toBe(true);
  await page.getByRole("tab", { name: /Analyst team/ }).click();
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

// REQ-WEB-007: failed snapshots must retain the process messages after reload.
test("failed analysis keeps tool activity on reload", async ({ page }) => {
  await page.goto("/new");
  await page.getByLabel(/ticker symbol/i).fill("MSFT");
  await page.getByRole("button", { name: /^continue$/i }).click();
  await advanceToPortfolio(page);
  await page.getByRole("button", { name: /start analysis/i }).click();
  await page.waitForURL(/\/runs\/r_/);
  await expect(page.getByRole("alert")).toContainText(
    "E2E market request failed",
  );
  await expect(page.getByText("E2E price data")).toBeVisible();
  await page.reload();
  await expect(page.getByText("E2E price data")).toBeVisible();
  await page.getByLabel("Filter activity").selectOption("Tool");
  await expect(page.getByText(/get_stock_data/)).toBeVisible();
  await expect(page.getByText("E2E price data")).toHaveCount(0);
  await page.getByRole("tab", { name: /Risk review/ }).click();
  await expect(page.getByText("This stage has not started.")).toBeVisible();
});
