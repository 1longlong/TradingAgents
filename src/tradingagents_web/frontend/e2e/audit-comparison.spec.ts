// REQ-WEB-008/009, NFR-CMP-001/002/003: real same-origin API browser contract.
import { expect, test } from "@playwright/test";

test("audit uses core artifacts, missing telemetry and sanitized previews/downloads", async ({
  page,
  request,
}) => {
  const history = await (await request.get("/api/history?limit=200")).json();
  const saved = history.items.find(
    (item: { ticker: string; source: string }) =>
      item.ticker === "AAPL" && item.source === "saved",
  );
  await page.goto(`/audit?artifact_id=${saved.artifact_id}`);
  await expect(
    page.getByRole("heading", { name: "Research audit", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".audit-verdict")).toContainText(
    "Proceed with recorded limitations.",
  );
  await expect(page.getByText("e2e-price", { exact: true })).toBeVisible();
  await page.getByLabel("Filter evidence").selectOption("excluded");
  await expect(page.getByText("e2e-price", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Inspect", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("e2e-future");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("tab", { name: "Debate & safeguards" }).click();
  await expect(page.getByText("No structured rounds recorded")).toBeVisible();
  await page.getByRole("tab", { name: "Budget & usage" }).click();
  await expect(page.locator(".usage-total strong")).toHaveText("—");
  await page.getByRole("tab", { name: "Artifacts" }).click();
  await expect(
    page.getByRole("link", { name: "Download", exact: true }),
  ).toHaveCount(4);
  await page
    .getByRole("button", { name: "Preview", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toContainText("evidence_records");
  await page.keyboard.press("Escape");
  const pending = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Download", exact: true })
    .first()
    .click();
  expect((await pending).suggestedFilename()).toBe("evidence_manifest.json");
  const legacy = history.items.find(
    (item: { ticker: string; source: string }) =>
      item.ticker === "NVDA" && item.source === "run",
  );
  await page.goto(`/audit?artifact_id=${legacy.artifact_id}`);
  await expect(page.getByText("No structured audit recorded")).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(0);
});

test("comparison replays D/E/F/G and refuses mismatched identities", async ({
  page,
}) => {
  await page.goto("/comparison");
  for (const [id, fixed, dynamic, reason] of [
    ["D", "3", "1", "no_new_evidence"],
    ["E", "3", "3", "max_rounds_reached"],
    ["F", "3", "1", "budget_exhausted"],
    ["G", "2", "2", "input_exhausted"],
  ]) {
    await page.getByLabel("Inspect case").selectOption(id);
    await expect(page.locator(".strategy-rounds strong").first()).toHaveText(
      fixed,
    );
    await expect(page.locator(".strategy-rounds strong").last()).toHaveText(
      dynamic,
    );
    await expect(page.locator(".strategy-dynamic")).toContainText(reason);
  }
  await expect(page.locator(".comparison-strategies")).not.toContainText(
    "Early stop",
  );
  await expect(page.locator(".rubric-grid")).not.toBeVisible();
  await page
    .getByText("Human scoring & policy details", { exact: true })
    .click();
  await expect(page.locator(".rubric-grid .audit-badge")).toHaveText([
    "Pending",
    "Pending",
    "Pending",
    "Pending",
  ]);
  const pending = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export comparison" }).click();
  expect((await pending).suggestedFilename()).toBe(
    "scripted-comparison-G.json",
  );
  await expect(page.getByLabel("Pairing check")).not.toBeVisible();
  await page.getByText("Pairing details", { exact: true }).click();
  await page.getByLabel("Pairing check").selectOption("mismatch");
  await expect(
    page.getByRole("heading", { name: "Comparison blocked." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Export comparison" }),
  ).toBeDisabled();
  await expect(page.locator(".comparison-strategies")).toHaveCount(0);
  await page.getByLabel("Pairing check").selectOption("matched");
  const response = page.waitForResponse(
    (response) =>
      response.url().includes("/api/comparisons/G?") &&
      response.status() === 200,
  );
  await page.getByRole("button", { name: "Replay scripted fixtures" }).click();
  await response;
  await expect(
    page.getByRole("link", { name: "Export comparison" }),
  ).toBeVisible();
});
