// REQ-WEB-001/003/013/014, FR-DDT-004, ADR-001/007: real request-to-snapshot/history integration.
import { expect, test } from "@playwright/test";

async function setup(page: import("@playwright/test").Page) {
  await page.goto("/new");
  await page.getByLabel(/Ticker symbol/).fill("NVDA");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByText("Debate rules & budgets", { exact: true }).click();
}

test("custom debate settings reach the real API and remain visible after completion and reload", async ({
  page,
  request,
}) => {
  await setup(page);
  await page.getByLabel("Debate mode", { exact: true }).selectOption("fixed");
  for (const [label, value] of [
    ["Risk discussion rounds", "2"],
    ["Maximum debate rounds", "4"],
    ["Rounds without new evidence before stopping", "2"],
    ["Stance distance threshold (0–4)", "0.5"],
    ["Confidence change threshold (0–1)", "0.1"],
    ["Maximum debate model calls", "20"],
    ["Debate token budget", "50000"],
    ["Debate time budget (seconds)", "900"],
    ["Summary token reserve", "5000"],
    ["Summary time reserve (seconds)", "120"],
    ["Next-round token estimate", "3000"],
    ["Next-round time estimate (seconds)", "45"],
  ])
    await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(
    page.getByText(/Selected debate settings.*Fixed-round baseline/),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Start analysis", exact: true })
    .click();
  await page.waitForURL(/\/runs\/r_/);
  await expect(
    page.getByText(/Effective debate settings.*Fixed-round baseline/),
  ).not.toBeVisible();
  await page.getByText("Analysis settings", { exact: true }).click();
  await expect(
    page.getByText(/Effective debate settings.*Fixed-round baseline/),
  ).toBeVisible();
  await expect(
    page
      .locator(".page-header-actions")
      .getByText("Completed", { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  const runId = page.url().split("/").pop();
  const snapshot = await (await request.get(`/api/runs/${runId}`)).json();
  expect(snapshot).toMatchObject({
    research_depth: 4,
    max_risk_discuss_rounds: 2,
    debate_termination: {
      enabled: false,
      max_debate_rounds: 4,
      no_new_evidence_patience: 2,
      max_tokens: 50000,
      reserved_summary_tokens: 5000,
    },
  });
  await page.reload();
  await page.getByText("Analysis settings", { exact: true }).click();
  await page.getByText(/Effective debate settings/).click();
  await expect(
    page
      .locator(".debate-policy-summary")
      .getByText("Risk discussion rounds", { exact: true }),
  ).toBeVisible();
  await page.goto(`/history/${snapshot.artifact_id}`);
  await page.getByText("Analysis settings", { exact: true }).click();
  await page
    .getByText(/Effective debate settings.*Fixed-round baseline/)
    .click();
  await expect(page.locator(".debate-policy-summary")).toContainText("50000");
  const detail = await (
    await request.get(`/api/history/${snapshot.artifact_id}`)
  ).json();
  expect(detail.metadata.debate_termination).toEqual(
    snapshot.debate_termination,
  );
});

test("Chinese budget/risk validation blocks submission before starting a worker", async ({
  page,
}) => {
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/runs$/.test(request.url()))
      posts++;
  });
  await setup(page);
  await page
    .locator(".sheet[open]")
    .getByRole("button", { name: "Switch to Chinese" })
    .click();
  await page.getByLabel("风险讨论轮数", { exact: true }).fill("0");
  await page.getByLabel("辩论词元预算", { exact: true }).fill("4000");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "风险讨论轮数必须为正整数。",
  );
  await expect(page.getByRole("alert")).toContainText(
    "总结词元预留必须小于辩论词元预算。",
  );
  expect(posts).toBe(0);
  await page
    .locator(".sheet[open]")
    .getByRole("button", { name: "切换为英文" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Summary token reserve must be below the debate token budget.",
  );
  await expect(
    page.getByLabel("Risk discussion rounds", { exact: true }),
  ).toHaveValue("0");
});

test("server-locked caps remain disabled in the form on narrow screens", async ({
  page,
}) => {
  await page.route("**/api/config", async (route) => {
    const response = await route.fetch();
    const config = await response.json();
    config.defaults.research_depth = 4;
    config.defaults.debate_termination.max_debate_rounds = 4;
    config.defaults.max_risk_discuss_rounds = 2;
    config.env_locks.max_debate_rounds = true;
    config.env_locks.max_risk_discuss_rounds = true;
    await route.fulfill({ json: config });
  });
  await setup(page);
  await expect(
    page.getByLabel("Maximum debate rounds", { exact: true }),
  ).toHaveValue("4");
  await expect(
    page.getByLabel("Maximum debate rounds", { exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByLabel("Risk discussion rounds", { exact: true }),
  ).toHaveValue("2");
  await expect(
    page.getByLabel("Risk discussion rounds", { exact: true }),
  ).toBeDisabled();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
