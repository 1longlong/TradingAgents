import { describe, expect, it } from "vitest";

import { validateStep } from "../src/pages/NewAnalysis/validation";

describe("wizard validation", () => {
  it("rejects an unsafe ticker", () => {
    expect(validateStep("ticker", { ticker: "../etc/passwd" }).ok).toBe(false);
  });

  it("requires at least one analyst", () => {
    expect(validateStep("analysts", { analysts: [] }).ok).toBe(false);
  });

  it("rejects a future analysis date", () => {
    expect(validateStep("date", { date: "2999-01-01" }).ok).toBe(false);
  });

  it("accepts a valid ticker and date", () => {
    expect(validateStep("ticker", { ticker: "NVDA" }).ok).toBe(true);
    expect(validateStep("date", { date: "2026-11-01" }).ok).toBe(true);
  });
});
