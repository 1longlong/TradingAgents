import { describe, expect, it } from "vitest";

import { unimplemented } from "./iteration3-support";

type ValidationResult = { ok: boolean; error?: string };
type ValidationModule = {
  validateBacktest: (values: Record<string, unknown>) => ValidationResult;
};

const modules = import.meta.glob<ValidationModule>(
  "../src/pages/Backtest/validation.ts",
);

async function loadValidation(): Promise<ValidationModule> {
  const loader = modules["../src/pages/Backtest/validation.ts"];
  if (!loader) unimplemented("src/pages/Backtest/validation.ts");
  return loader();
}

const valid = {
  tickers: ["NVDA", "AAPL"],
  start: "2026-06-01",
  end: "2026-06-08",
  every: 7,
  analysts: ["market", "news"],
  assetType: "stock",
  portfolioJson: "",
  runId: "",
};

describe("backtest validation", () => {
  it("accepts CLI-equivalent parameters", async () => {
    const { validateBacktest } = await loadValidation();
    expect(validateBacktest(valid).ok).toBe(true);
  });

  it("rejects an empty ticker list", async () => {
    const { validateBacktest } = await loadValidation();
    expect(validateBacktest({ ...valid, tickers: [] }).ok).toBe(false);
  });

  it("rejects an unsafe ticker", async () => {
    const { validateBacktest } = await loadValidation();
    expect(
      validateBacktest({ ...valid, tickers: ["../etc/passwd"] }).ok,
    ).toBe(false);
  });

  it("rejects a grid that ends before it starts", async () => {
    const { validateBacktest } = await loadValidation();
    expect(
      validateBacktest({ ...valid, start: "2026-08-01", end: "2026-06-01" }).ok,
    ).toBe(false);
  });

  it("rejects a non-positive interval", async () => {
    const { validateBacktest } = await loadValidation();
    expect(validateBacktest({ ...valid, every: 0 }).ok).toBe(false);
  });

  it("rejects an empty analyst list", async () => {
    const { validateBacktest } = await loadValidation();
    expect(validateBacktest({ ...valid, analysts: [] }).ok).toBe(false);
  });

  it("rejects an unknown analyst", async () => {
    const { validateBacktest } = await loadValidation();
    expect(validateBacktest({ ...valid, analysts: ["unknown"] }).ok).toBe(false);
  });

  it("rejects an invalid portfolio document", async () => {
    const { validateBacktest } = await loadValidation();
    expect(validateBacktest({ ...valid, portfolioJson: "{not json" }).ok).toBe(
      false,
    );
  });

  it("rejects an unsafe run id", async () => {
    const { validateBacktest } = await loadValidation();
    expect(validateBacktest({ ...valid, runId: "../escape" }).ok).toBe(false);
  });
});
