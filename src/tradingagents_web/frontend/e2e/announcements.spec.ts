import { expect, test } from "@playwright/test";

test("announcements are displayed on the history page", async ({
  page,
  request,
}) => {
  const response = await request.get("/api/announcements");
  if (response.status() === 404) {
    throw new Error(
      "EXPECTED-UNIMPLEMENTED: /api/announcements is not implemented yet",
    );
  }
  expect(response.status()).toBe(200);

  await page.goto("/history");
  // REQ-WEB-012: the reference opens workspace notes from the bell.
  await page.getByRole("button", { name: "View announcements" }).click();
  await expect(page.getByRole("dialog")).toContainText("E2E announcement");
  await page.getByRole("button", { name: "Got it" }).click();
});
