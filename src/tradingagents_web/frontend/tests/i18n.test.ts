import { describe, expect, it } from "vitest";

import en from "../src/i18n/en.json";
import zh from "../src/i18n/zh.json";

function flatten(value: unknown, prefix = ""): string[] {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
      flatten(child, prefix ? `${prefix}.${key}` : key),
    );
  }
  return [prefix];
}

describe("i18n catalogues", () => {
  it("have identical keys", () => {
    expect(new Set(flatten(zh))).toEqual(new Set(flatten(en)));
  });

  it("are not empty", () => {
    expect(flatten(en).length).toBeGreaterThan(0);
  });
});
