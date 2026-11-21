// REQ-WEB-009/021, ADR-003, INV-WEB-012/014: report tables cannot cover the contents sidebar.
import { expect, test } from "@playwright/test";

test("wide report tables wrap text and scroll locally on desktop and mobile", async ({
  page,
}) => {
  const columns = Array.from(
    { length: 12 },
    (_, index) => `Evidence ${index + 1}`,
  );
  const content = `| ${columns.join(" | ")} |\n| ${columns.map(() => "---").join(" | ")} |\n| ${columns.map(() => "Long evidence " + "x".repeat(150)).join(" | ")} |`;
  await page.route("**/api/history/aaaaaaaaaaaaaaaa", (route) =>
    route.fulfill({
      json: {
        artifact_id: "aaaaaaaaaaaaaaaa",
        source: "saved",
        ticker: "NVDA",
        date: "2026-11-01",
        status: "completed",
        rating: "REVIEW",
        review: true,
        metadata: {},
        artifacts: [],
        sections: { market_report: content },
      },
    }),
  );
  await page.goto("/history/aaaaaaaaaaaaaaaa");
  const region = page.getByRole("region", { name: "Report table" });
  await expect(region).toBeVisible();
  await expect(region.locator("th")).toHaveCount(12);
  await expect(region.locator("td")).toHaveCount(12);
  for (const viewport of [
    { width: 1512, height: 982 },
    { width: 375, height: 812 },
    { width: 844, height: 390 },
  ]) {
    await page.setViewportSize(viewport);
    const bounds = await region.evaluate((element) => {
      const wrapper = element.getBoundingClientRect();
      const article = element
        .closest(".document-panel")!
        .getBoundingClientRect();
      const toc = document.querySelector(".toc-panel")!;
      return {
        overflowing: element.scrollWidth > element.clientWidth,
        wrapperRight: wrapper.right,
        articleRight: article.right,
        tocLeft:
          getComputedStyle(toc).display !== "none"
            ? toc.getBoundingClientRect().left
            : null,
        pageWidth: document.documentElement.scrollWidth,
        whiteSpace: getComputedStyle(element.querySelector("td")!).whiteSpace,
      };
    });
    expect(bounds.overflowing).toBe(true);
    expect(bounds.wrapperRight).toBeLessThanOrEqual(bounds.articleRight);
    expect(bounds.pageWidth).toBeLessThanOrEqual(viewport.width);
    expect(bounds.whiteSpace).toBe("normal");
    if (viewport.width === 1512)
      expect(bounds.wrapperRight).toBeLessThan(bounds.tocLeft!);
    await region.evaluate((element) => {
      element.scrollLeft = 0;
    });
    await region.focus();
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(() => region.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0);
  }
});
