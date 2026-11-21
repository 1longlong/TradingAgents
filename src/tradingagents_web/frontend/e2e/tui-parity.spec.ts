// REQ-WEB-001/002/006/007/013, ADR-001/003: bounded TUI integration.
import { expect, test } from "@playwright/test";

test("OpenRouter refresh preserves custom models and failure allows manual entry", async ({
  page,
}) => {
  let refreshes = 0;
  await page.route("**/api/config/models?**", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("provider") !== "openrouter")
      return route.continue();
    const refresh = url.searchParams.has("refresh");
    if (refresh) refreshes++;
    await route.fulfill({
      json: {
        models: [
          { value: "openai/offline-model", label: "Offline model" },
          { value: "custom", label: "Custom model ID" },
        ],
        ...(refresh
          ? {
              warning:
                "Model list unavailable; showing cached suggestions. You can still enter a model ID.",
            }
          : {}),
      },
    });
  });
  await page.goto("/new");
  await page.getByLabel(/Ticker symbol/).fill("NVDA");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByLabel("Model provider", { exact: true })
    .selectOption("openrouter");
  await expect(
    page.getByRole("button", { name: "Refresh model list" }),
  ).toBeEnabled();
  await page.getByLabel("Quick model", { exact: true }).fill("custom/quick");
  await page.getByLabel("Deep model", { exact: true }).fill("custom/deep");
  await page.getByRole("button", { name: "Refresh model list" }).click();
  await expect(page.getByText(/showing cached suggestions/)).toBeVisible();
  expect(refreshes).toBe(2);
  await expect(page.getByLabel("Quick model", { exact: true })).toHaveValue(
    "custom/quick",
  );
  await expect(page.getByLabel("Deep model", { exact: true })).toHaveValue(
    "custom/deep",
  );
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByText("custom/quick / custom/deep")).toBeVisible();
});

test("recorded role states, report counts and analyst times survive reload without confusing risk stages", async ({
  page,
}) => {
  await page.route("**/api/runs/r_roles", (route) =>
    route.fulfill({
      json: {
        run_id: "r_roles",
        status: "completed",
        ticker: "NVDA",
        trade_date: "2026-11-01",
        last_seq: 10,
        agents: {
          "Market Analyst": "completed",
          "Research Manager": "completed",
          "Aggressive Analyst": "completed",
          "Portfolio Manager": "completed",
        },
        sections: {
          market_report: "Market evidence",
          investment_plan: "Research plan",
          trader_investment_plan: "Trade plan",
          final_trade_decision: "**Rating**: Hold",
        },
        stats: {
          reports_completed: 4,
          reports_total: 4,
          agents_completed: 9,
          agents_total: 9,
        },
        wall_times: { "Market Analyst": 1.25 },
        messages: [],
      },
    }),
  );
  await page.goto("/runs/r_roles");
  await expect(page.getByRole("tab", { name: /Risk review/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page
    .getByText("Agent status & analyst timing", { exact: true })
    .click();
  await expect(
    page.locator(".run-role-list").getByText("Portfolio Manager"),
  ).toBeVisible();
  await page.getByRole("tab", { name: /Analyst team/ }).click();
  await expect(page.locator(".run-role-list").getByText("1.25s")).toBeVisible();
  await expect(page.locator(".activity-stats")).not.toBeVisible();
  await page.getByText("Run statistics", { exact: true }).click();
  await expect(page.locator(".activity-stats")).toBeVisible();
  await expect(page.locator(".activity-stats")).toContainText("4 / 4");
  await page.reload();
  await page.getByRole("tab", { name: /Analyst team/ }).click();
  await page
    .getByText("Agent status & analyst timing", { exact: true })
    .click();
  await expect(page.locator(".run-role-list").getByText("1.25s")).toBeVisible();
});

// REQ-WEB-001/003/013, ADR-001-choice.md: server defaults preselect without locking the analysis.
test("environment model defaults are preselected, editable and replaced by the explicit analysis request", async ({
  page,
  request,
}) => {
  await page.route("**/api/config", async (route) => {
    const response = await route.fetch();
    const config = await response.json();
    config.defaults.llm_provider = "deepseek";
    config.defaults.quick_think_llm = "deepseek-flash";
    config.defaults.deep_think_llm = "deepseek-flash";
    config.env_defaults = {
      llm_provider: true,
      quick_think_llm: true,
      deep_think_llm: true,
    };
    for (const key of Object.keys(config.env_defaults))
      config.env_locks[key] = false;
    config.prefs = {
      llm_provider: "openai",
      quick_think_llm: "stale-quick",
      deep_think_llm: "stale-deep",
    };
    await route.fulfill({ json: config });
  });
  await page.goto("/new");
  await page.getByLabel(/Ticker symbol/).fill("NVDA");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const provider = page.getByLabel("Model provider", { exact: true });
  await expect(provider).toHaveValue("deepseek");
  await expect(provider).toBeEnabled();
  await expect(page.getByLabel("Quick model", { exact: true })).toHaveValue(
    "deepseek-flash",
  );
  await expect(page.getByLabel("Deep model", { exact: true })).toHaveValue(
    "deepseek-flash",
  );
  await provider.selectOption("openai");
  await expect(page.getByLabel("Quick model", { exact: true })).toBeEnabled();
  await page.getByLabel("Quick model", { exact: true }).fill("chosen-quick");
  await page.getByLabel("Deep model", { exact: true }).fill("chosen-deep");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const submitted = page.waitForRequest(
    (req) => req.method() === "POST" && req.url().endsWith("/api/runs"),
  );
  await page
    .getByRole("button", { name: "Start analysis", exact: true })
    .click();
  expect((await submitted).postDataJSON()).toMatchObject({
    llm_provider: "openai",
    quick_think_llm: "chosen-quick",
    deep_think_llm: "chosen-deep",
  });
  await page.waitForURL(/\/runs\/r_/);
  await expect(
    page
      .locator(".page-header-actions")
      .getByText("Completed", { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  const runId = page.url().split("/").pop();
  const snapshot = await (await request.get(`/api/runs/${runId}`)).json();
  expect(snapshot.llm_provider).toBe("openai");
  expect(snapshot.quick_think_llm).toBe("chosen-quick");
  expect(snapshot.deep_think_llm).toBe("chosen-deep");
});
