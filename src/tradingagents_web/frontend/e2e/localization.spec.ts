// REQ-WEB-014/021, ADR-003, INV-WEB-001/007/012/014: Chinese presentation preserves contracts.
import { expect, test } from "@playwright/test";

test("language preference covers workspace routes, settings, reload and narrow layouts", async ({
  page,
}) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem("ta.language"))
      localStorage.setItem("ta.language", "unsupported");
  });
  await page.goto("/overview");
  await expect(
    page.getByRole("heading", { name: "Research overview", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("ta.language"))).toBe(
    "en",
  );
  await page.getByRole("button", { name: "Switch to Chinese" }).click();
  await expect(
    page.getByRole("heading", { name: "研究概览", exact: true }),
  ).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "研究概览", exact: true }),
  ).toBeVisible();
  for (const [route, heading] of [
    ["/history", "分析历史"],
    ["/audit", "研究审计"],
    ["/comparison", "策略比较"],
    ["/journal", "决策日志"],
    ["/backtest", "回测"],
  ]) {
    await page.goto(route);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }).first(),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.getByRole("button", { name: "工作区设置" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("界面语言", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "切换为英文" }).click();
  await expect(
    dialog.getByRole("heading", { name: "Workspace settings" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { name: "Backtesting", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole("button", { name: "Switch to Chinese" }).click();
  await expect(page.getByRole("button", { name: "切换为英文" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.goto("/new");
  await expect(page.locator(".sheet[open]")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("wizard switches in place, localizes validation and submits original model and language values", async ({
  page,
}) => {
  await page.goto("/new");
  const dialog = page.locator(".sheet[open]");
  await dialog.getByLabel(/Ticker symbol/).fill("NVDA");
  await dialog.getByRole("button", { name: "Switch to Chinese" }).click();
  await expect(dialog.getByLabel(/标的代码/)).toHaveValue("NVDA");
  await dialog.getByLabel(/标的代码/).fill("");
  await dialog.getByRole("button", { name: "继续", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("请输入标的代码。");
  await dialog.getByLabel(/标的代码/).fill("NVDA");
  await expect(dialog.getByLabel("报告语言")).toHaveValue("English");
  await dialog.getByLabel("报告语言").selectOption("English");
  await dialog.getByRole("button", { name: "继续", exact: true }).click();
  await expect(
    dialog.getByRole("heading", { name: "团队与模型" }),
  ).toBeVisible();
  const provider = await dialog.getByLabel("模型服务商").inputValue();
  const quick = await dialog
    .getByLabel("快速模型", { exact: true })
    .inputValue();
  const deep = await dialog
    .getByLabel("深度模型", { exact: true })
    .inputValue();
  await dialog.getByRole("button", { name: "切换为英文" }).click();
  await expect(dialog.getByLabel("Quick model", { exact: true })).toHaveValue(
    quick,
  );
  await dialog.getByRole("button", { name: "Continue", exact: true }).click();
  await dialog.getByRole("button", { name: "Switch to Chinese" }).click();
  await page.route("**/api/runs", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    expect(body).toMatchObject({
      ticker: "NVDA",
      output_language: "English",
      llm_provider: provider,
      quick_think_llm: quick,
      deep_think_llm: deep,
    });
    await route.fulfill({
      status: 422,
      json: {
        error: { message: "Fixture request captured", category: "validation" },
      },
    });
  });
  await dialog.getByRole("button", { name: "开始分析", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Fixture request captured",
  );
});

test("Chinese activity preserves report and tool text and does not reconnect on a language switch", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("ta.language", "zh"));
  const snapshot = {
    run_id: "r_locale",
    ticker: "NVDA",
    trade_date: "2026-11-01",
    status: "failed",
    last_seq: 5,
    error: { message: "Fixture market error", correlation_id: "c_locale" },
    agents: { "Market Analyst": "in_progress" },
    sections: { market_report: "Research overview" },
    messages: [
      {
        id: "r_locale:1",
        stage: "analysts",
        type: "Data",
        content: "Market analysis",
      },
    ],
    stats: {},
  };
  let snapshots = 0;
  await page.route("**/api/runs/r_locale", async (route) => {
    snapshots++;
    await route.fulfill({ json: snapshot });
  });
  await page.goto("/runs/r_locale");
  await expect(
    page.getByRole("heading", { name: "运行动态", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".run-message pre")
      .getByText("Market analysis", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".markdown")).toHaveText("Research overview");
  await page.getByRole("button", { name: "切换为英文" }).click();
  await expect(
    page.getByRole("heading", { name: "Run activity", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".run-message pre")
      .getByText("Market analysis", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".markdown")).toHaveText("Research overview");
  expect(snapshots).toBe(1);
});

test("switching language during a streamed run keeps the same connection and execution", async ({
  page,
}) => {
  let connections = 0;
  page.on("request", (request) => {
    if (/\/api\/runs\/[^/]+\/events\?/.test(request.url())) connections++;
  });
  await page.goto("/new");
  await page.getByLabel(/Ticker symbol/).fill("NVDA");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByRole("button", { name: "Start analysis", exact: true })
    .click();
  await page.waitForURL(/\/runs\/r_/);
  const runUrl = page.url();
  await expect(page.getByText("E2E working", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Switch to Chinese" }).click();
  await expect(
    page.getByRole("heading", { name: "运行动态", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: /研究辩论/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(
    page.locator(".page-header-actions").getByText("已完成", { exact: true }),
  ).toBeVisible({ timeout: 15_000 });
  expect(page.url()).toBe(runUrl);
  expect(connections).toBe(1);
  await page.getByRole("tab", { name: "全部动态", exact: true }).click();
  await expect(page.getByText("E2E working", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "切换为英文" }).click();
  await expect(
    page.getByRole("heading", { name: "Run activity", exact: true }),
  ).toBeVisible();
  expect(connections).toBe(1);
});
