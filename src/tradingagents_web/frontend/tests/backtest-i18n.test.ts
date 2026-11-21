import { describe, expect, it } from "vitest";

import en from "../src/i18n/en.json";

const REQUIRED_KEYS = [
  "nav.backtest",
  "backtest.title",
  "backtest.tickers",
  "backtest.start",
  "backtest.end",
  "backtest.every",
  "backtest.analysts",
  "backtest.assetType",
  "backtest.portfolio",
  "backtest.runId",
  "backtest.submit",
  "backtest.running",
  "backtest.noCancel",
  "backtest.resolved",
  "backtest.pending",
  "backtest.unscored",
  "backtest.rating",
  "backtest.count",
  "backtest.hitRate",
  "backtest.meanAlpha",
  "backtest.holding",
  "backtest.failures",
  "backtest.settlementFailures",
  "backtest.history",
  "announcements.title",
  "announcements.acknowledge",
];

function hasKey(catalogue: unknown, key: string): boolean {
  let current: unknown = catalogue;
  for (const part of key.split(".")) {
    if (!current || typeof current !== "object") return false;
    current = (current as Record<string, unknown>)[part];
  }
  return current !== undefined;
}

describe("Iteration-3 i18n keys", () => {
  it("define every backtest and announcement string", () => {
    const missing = REQUIRED_KEYS.filter((key) => !hasKey(en, key));
    if (missing.length > 0) {
      throw new Error(
        `EXPECTED-UNIMPLEMENTED: missing i18n keys: ${missing.join(", ")}`,
      );
    }
    expect(missing).toEqual([]);
  });
});
