// FR-TRD-001..006, INV-TRD-001..003: actual offline simulated-core UI/API integration.
import { expect, test } from "@playwright/test";

test("account initialization, human approval, audit and confirmed reset use the actual simulated core", async ({
  page,
  request,
}) => {
  await page.goto("/simulation");
  await expect(
    page.getByRole("heading", { name: "Simulated trading", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Initial cash", { exact: true }).fill("100000.00");
  await page.getByRole("button", { name: "Create simulated account" }).click();
  await expect(
    page.getByRole("heading", { name: "Simulated positions", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("tab", { name: "Decisions & approvals", exact: true })
    .click();
  const reports = await (await request.get("/api/simulation/reports")).json();
  const report = reports.items.find(
    (item: { ticker: string }) => item.ticker === "NVDA",
  );
  expect(report).toBeTruthy();
  await page
    .getByLabel("Completed analysis report")
    .selectOption(report.artifact_id);
  await page.getByLabel("Scenario price", { exact: true }).fill("100");
  await page
    .getByRole("button", { name: "Evaluate & simulate", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve & simulate", exact: true }),
  ).toBeVisible();
  const before = await (await request.get("/api/simulation")).json();
  expect(before.snapshot.positions).toHaveLength(0);
  await page.getByLabel("Approver name").fill("Browser reviewer");
  await page
    .getByLabel("Reason", { exact: true })
    .fill("Reviewed simulated order and position size.");
  await page
    .getByRole("button", { name: "Approve & simulate", exact: true })
    .click();
  await expect(
    page.getByText("No pending approvals in this server session.", {
      exact: true,
    }),
  ).toBeVisible();
  const filled = await (await request.get("/api/simulation")).json();
  expect(filled.snapshot.positions[0].quantity).toBe("50.000000");
  expect(filled.snapshot.cash).toBe("94997.50");
  await page.getByRole("tab", { name: "Trading audit", exact: true }).click();
  await page
    .getByLabel("Event type", { exact: true })
    .selectOption("ORDER_EXECUTED");
  await expect(page.getByRole("button", { name: "Inspect event" })).toHaveCount(
    1,
  );
  await page.getByRole("button", { name: "Inspect event" }).click();
  await expect(page.locator(".sim-json")).toContainText("50.000000");
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  await page.getByRole("tab", { name: "Account", exact: true }).click();
  await page
    .getByRole("button", { name: "Reset account", exact: true })
    .click();
  const modal = page.getByRole("dialog");
  await expect(
    modal.getByRole("button", { name: "Reset account", exact: true }),
  ).toBeDisabled();
  await modal.getByLabel("New initial cash").fill("10000.00");
  await modal
    .getByLabel("Type RESET to confirm.", { exact: true })
    .fill("RESET");
  await modal
    .getByRole("button", { name: "Reset account", exact: true })
    .click();
  await expect(
    page.getByText("No simulated holdings yet.", { exact: true }),
  ).toBeVisible();
  const reset = await (await request.get("/api/simulation")).json();
  expect(reset.snapshot.cash).toBe("10000.00");
  expect(reset.account_id).not.toBe(before.account_id);
  const audit = await (
    await request.get("/api/simulation/audit?event_type=ORDER_EXECUTED")
  ).json();
  expect(audit.verified).toBe(true);
  expect(audit.total).toBe(1);
});

test("offline walk-forward changes its own portfolio and completed runs need no resume", async ({
  page,
  request,
}) => {
  const account = await (await request.get("/api/simulation")).json();
  await page.goto("/simulation?tab=backtests");
  await page.getByLabel("Simulation start date").fill("2026-11-02");
  await page.getByLabel("Simulation end date").fill("2026-11-03");
  await page.getByLabel("Scenario date 1", { exact: true }).fill("2026-11-02");
  await page.getByLabel("Closing price 1", { exact: true }).fill("100");
  await page
    .getByRole("button", { name: "Add scenario day", exact: true })
    .click();
  await page
    .getByLabel("Scenario action 2", { exact: true })
    .selectOption("SELL");
  await page.getByLabel("Closing price 2", { exact: true }).fill("105");
  await page
    .getByRole("button", { name: "Start simulation", exact: true })
    .click();
  await expect(
    page.getByText("Last saved day: 2026-11-03", { exact: true }),
  ).toBeVisible();
  const jobId = new URL(page.url()).searchParams.get("job");
  const job = await (await request.get(`/api/simulation/jobs/${jobId}`)).json();
  expect(job.summary.executions).toBe(2);
  expect(job.parameters.source).toBe("scenario");
  const after = await (await request.get("/api/simulation")).json();
  expect(after.snapshot.cash).toBe(account.snapshot.cash);
  expect(after.snapshot.positions).toEqual(account.snapshot.positions);
  await expect(
    page.getByRole("button", { name: "Resume saved simulation", exact: true }),
  ).toHaveCount(0);
  const finalEquity = job.summary.final_equity;
  await page.reload();
  await expect(
    page.getByText("Last saved day: 2026-11-03", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Resume saved simulation", exact: true }),
  ).toHaveCount(0);
  const reloaded = await (
    await request.get(`/api/simulation/jobs/${jobId}`)
  ).json();
  expect(reloaded.summary.executions).toBe(2);
  expect(reloaded.summary.final_equity).toBe(finalEquity);
  await expect(page.getByRole("button", { name: /cancel/i })).toHaveCount(0);
});

test("invalid quotes and scenario prices never submit, and simulation views reflow in both themes", async ({
  page,
}) => {
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/simulation/")
    )
      posts++;
  });
  await page.goto("/simulation?tab=decisions");
  await page.getByLabel("Scenario price", { exact: true }).fill("-1");
  await page
    .getByRole("button", { name: "Evaluate & simulate", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Choose a report");
  expect(posts).toBe(0);
  await page.getByRole("tab", { name: "Walk-forward", exact: true }).click();
  await page.getByLabel("Closing price 1", { exact: true }).fill("0");
  await page
    .getByRole("button", { name: "Start simulation", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("positive prices");
  expect(posts).toBe(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(
      (theme) => (document.documentElement.dataset.theme = theme),
      theme,
    );
    await page.setViewportSize({ width: 375, height: 812 });
    for (const label of [
      "Account",
      "Decisions & approvals",
      "Walk-forward",
      "Trading audit",
    ]) {
      await page.getByRole("tab", { name: label, exact: true }).click();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  }
});
