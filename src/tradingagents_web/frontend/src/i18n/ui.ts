// REQ-WEB-014, ADR-003, INV-WEB-001/007/012: localize interface text only.
import { useTranslation } from "react-i18next";
import i18n from "./index";

export function useUILanguage() {
  return useTranslation("workspace");
}

export function ui(value: string, values?: Record<string, unknown>): string;
export function ui<T>(value: T, values?: Record<string, unknown>): T;
export function ui(value: unknown, values?: Record<string, unknown>): unknown {
  if (typeof value !== "string" || !value) return value;
  const [, before, key, after] = value.match(/^(\s*)([\s\S]*?)(\s*)$/)!;
  if (!key) return value;
  const localized =
    values &&
    Object.fromEntries(
      Object.entries(values).map(([name, item]) => [
        name,
        typeof item === "string" ? ui(item) : item,
      ]),
    );
  return (
    before +
    i18n.t(key, {
      ...localized,
      ns: "workspace",
      keySeparator: false,
      nsSeparator: false,
      defaultValue: key,
    }) +
    after
  );
}

// Localize the application's generated title, preserving custom/source titles.
export function uiHistoryTitle(title: string, ticker: string): string {
  return title === `${ticker} saved report`
    ? ui("{{ticker}} saved report", { ticker })
    : title;
}

// Format a recorded holding-window label without changing its stored value.
export function uiHolding(
  value: string | null | undefined,
  missing = "Not recorded",
): string {
  if (!value) return ui(missing);
  const days = /^(\d+) trading days?$/.exec(value);
  return days
    ? ui("{{count}} trading days", { count: Number(days[1]) })
    : value;
}
