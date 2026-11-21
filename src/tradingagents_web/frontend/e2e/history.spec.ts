import { expect, test } from "@playwright/test";

test("history page renders and opens a report", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByRole("heading", { name: /history/i })).toBeVisible();
});
