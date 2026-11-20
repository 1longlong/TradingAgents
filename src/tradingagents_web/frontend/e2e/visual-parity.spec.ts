// REQ-WEB-001/002/010/021, ADR-003: reference geometry and real local API interactions.
import { expect, test } from "@playwright/test";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

test("workspace and three-step sheet retain the demo geometry", async ({
  page,
  browser,
}) => {
  const reference = await browser.newPage({
    viewport: { width: 1512, height: 1060 },
  });
  await page.setViewportSize({ width: 1512, height: 1060 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await reference.emulateMedia({ reducedMotion: "reduce" });
  await reference.goto(pathToFileURL(resolve("../../../demo/index.html")).href);
  await page.goto("/overview");
  await expect(
    page.getByRole("heading", { name: "Research overview" }),
  ).toBeVisible();
  for (const selector of [
    ".brand",
    ".topbar",
    ".page-header",
    ".stats-strip",
  ]) {
    const actual = await page.locator(selector).boundingBox(),
      expected = await reference.locator(selector).boundingBox();
    expect(actual).not.toBeNull();
    expect(expected).not.toBeNull();
    for (const field of ["x", "y", "width", "height"] as const)
      expect(
        Math.abs(actual![field] - expected![field]),
        `${selector}.${field}`,
      ).toBeLessThan(0.75);
  }
  await reference
    .getByRole("button", { name: "New analysis", exact: true })
    .click();
  await page
    .getByRole("link", { name: "New analysis", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeEnabled();
  for (let step = 0; step < 3; step++) {
    for (const selector of [
      ".sheet",
      ".sheet-header",
      ".wizard-steps",
      ".sheet-footer",
    ]) {
      const actual = await page.locator(selector).boundingBox(),
        expected = await reference.locator(selector).boundingBox();
      for (const field of ["x", "y", "width", "height"] as const)
        expect(
          Math.abs(actual![field] - expected![field]),
          `step ${step}: ${selector}.${field}`,
        ).toBeLessThan(0.75);
    }
    if (step === 0) {
      await page.getByLabel(/ticker symbol/i).fill("NVDA");
      await reference.getByLabel(/ticker symbol/i).fill("NVDA");
    }
    if (step < 2) {
      await page.getByRole("button", { name: "Continue", exact: true }).click();
      await reference
        .getByRole("button", { name: "Continue", exact: true })
        .click();
    }
  }
  await page.getByRole("button", { name: "Save draft and close" }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await reference.close();
});

test("sheet keeps errors, explicit asset selection, thinking controls and private drafts", async ({
  page,
}) => {
  await page.goto("/new");
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeEnabled();
  await page.getByLabel(/ticker symbol/i).fill("../bad");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("unsupported");
  await expect(page.getByLabel(/ticker symbol/i)).toHaveValue("../BAD");
  await page.getByLabel(/ticker symbol/i).fill("BTC-USD");
  await page.getByLabel("Crypto assets").check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Fundamentals", { exact: true })).toBeDisabled();
  await expect(
    page.getByLabel("Fundamentals", { exact: true }),
  ).not.toBeChecked();
  await page.getByText("Endpoint & model thinking", { exact: true }).click();
  await page
    .getByLabel("Endpoint override (optional)")
    .fill("https://user:secret@example.test/v1");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("without credentials");
  await page.getByRole("alert").getByRole("link").click();
  await expect(page.getByLabel("Endpoint override (optional)")).toBeFocused();
  await page
    .getByLabel("Endpoint override (optional)")
    .fill("https://example.test/v1");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Include portfolio context").check();
  await page
    .getByLabel("Portfolio JSON", { exact: true })
    .fill('{"positions":null}');
  await page
    .getByRole("button", { name: "Start analysis", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("Choose a portfolio JSON file").setInputFiles({
    name: "flat.json",
    mimeType: "application/json",
    buffer: Buffer.from('{"positions":[],"cash":10000}'),
  });
  await expect(page.getByLabel("Portfolio JSON", { exact: true })).toHaveValue(
    '{"positions":[],"cash":10000}',
  );
  await page.getByRole("button", { name: "Save draft and close" }).click();
  const draft = await page.evaluate(() =>
    localStorage.getItem("ta.analysisDraft"),
  );
  expect(draft).not.toContain("example.test");
  expect(draft).not.toContain("positions");
  expect(draft).not.toContain("portfolioEnabled");
});

test("history, journal, settings and supported downloads are interactive", async ({
  page,
}) => {
  await page.goto("/history");
  await page.getByRole("searchbox").fill("not-present");
  await expect(page.getByText("No matching research")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await page
    .getByRole("row")
    .filter({ hasText: "NVDA 2026-11-01" })
    .first()
    .getByRole("link", { name: /Read .* analysis/ })
    .click();
  await expect(
    page.getByText("Evidence, examined from every angle."),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Export report" })).toHaveCount(
    0,
  );
  const archive = page.waitForEvent("download");
  await page.getByRole("link", { name: "Archive", exact: true }).click();
  expect((await archive).suggestedFilename()).toContain(".zip");
  await page.goto("/history");
  await page
    .getByRole("row")
    .filter({ hasText: "AAPL saved report" })
    .first()
    .getByRole("link", { name: /Read .* analysis/ })
    .click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export report" }).click();
  expect((await download).suggestedFilename()).toContain(".md");
  await page.goto("/journal");
  await page
    .getByRole("button", { name: "Read decision & outcome" })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Original decision" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Reflection", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Open local workspace settings" })
    .click();
  await page.getByLabel("Appearance").selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Clear all checkpoints" }).click();
  await expect(
    page.getByRole("button", { name: "Clear checkpoints", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Confirmation").fill("clear");
  await expect(
    page.getByRole("button", { name: "Clear checkpoints", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Keep checkpoints" }).click();
  await expect(
    page.getByRole("heading", { name: "Workspace settings", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.keyboard.press("?");
  await expect(
    page.getByRole("heading", {
      name: "A workspace for considered decisions",
    }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
});

test("all supported surfaces reflow in both themes and mobile navigation is inert", async ({
  page,
}) => {
  const errors: string[] = [],
    remote: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.protocol.startsWith("http") && url.hostname !== "127.0.0.1") {
      remote.push(url.href);
      return route.abort();
    }
    return route.continue();
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const theme of ["light", "dark"]) {
    for (const width of [375, 768, 1024, 1512]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of [
        "overview",
        "history",
        "backtest",
        "journal",
        "audit",
        "comparison",
      ]) {
        await page.goto(`/${path}`);
        await page.evaluate(
          (value) => (document.documentElement.dataset.theme = value),
          theme,
        );
        await expect(page.locator(".page-header h1")).toBeVisible();
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          `${theme} ${width} ${path}`,
        ).toBe(true);
      }
    }
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/overview");
  await expect(page.locator("#sidebar")).toHaveAttribute("inert", "");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.locator("#sidebar")).not.toHaveAttribute("inert", "");
  await page.keyboard.press("Escape");
  await expect(page.locator("#sidebar")).toHaveAttribute("inert", "");
  await page.setViewportSize({ width: 812, height: 375 });
  await page.goto("/backtest");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
  expect(remote).toEqual([]);
});
