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
  await expect(page.getByText(/E2E announcement/i)).toBeVisible();
});
