// REQ-WEB-008/009/010: totals/search cover all pages; absent metadata stays absent.
import { afterEach, describe, expect, it, vi } from "vitest";
import { getAllHistory, type HistoryItem } from "../src/api/client";
import { visibleSectionKeys } from "../src/utils/workspace";
import { filterAnalyses } from "../src/components/HistoryTable";
afterEach(() => vi.unstubAllGlobals());
const record = (id: string, ticker: string, date: string): HistoryItem => ({
  artifact_id: id,
  ticker,
  date,
  source: "run",
  status: "completed",
  rating: null,
  review: false,
  updated_at: date,
  title: `Research about ${ticker}`,
});
describe("workspace history", () => {
  it("includes later pages and preserves missing ratings", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [record("old", "NVDA", "2026-01-01")],
          next_cursor: "200",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [record("new", "AAPL", "2026-02-01")],
          next_cursor: null,
        }),
      });
    vi.stubGlobal("fetch", fetch);
    const result = await getAllHistory();
    expect(result.items.map((item) => item.artifact_id)).toEqual([
      "old",
      "new",
    ]);
    expect(fetch.mock.calls[1][0]).toContain("cursor=200");
    expect(result.items[1].rating).toBeNull();
    expect(
      filterAnalyses(result.items, "aapl", "all").map(
        (item) => item.artifact_id,
      ),
    ).toEqual(["new"]);
    expect(filterAnalyses(result.items, "research", "all")).toEqual([]);
  });
  it("rejects repeated cursors instead of hanging or showing a partial total", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ items: [], next_cursor: "200" }),
      }),
    );
    await expect(getAllHistory()).rejects.toThrow("pagination did not advance");
  });
  it("uses a complete report as a fallback without repeating existing sections", () => {
    expect(
      visibleSectionKeys({
        market_report: "Market",
        complete_report: "Whole report",
      }),
    ).toEqual(["market_report"]);
    expect(visibleSectionKeys({ complete_report: "Whole report" })).toEqual([
      "complete_report",
    ]);
  });
});
