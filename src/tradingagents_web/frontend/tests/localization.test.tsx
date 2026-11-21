// REQ-WEB-014/021, ADR-003, INV-WEB-001/007/012/014: language affects UI, never domain data.
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ts from "typescript";
import en from "../src/i18n/en.json";
import zh from "../src/i18n/zh.json";
import i18n, { normalizeLanguage } from "../src/i18n";
import { ui, uiHistoryTitle, uiHolding } from "../src/i18n/ui";
import { LanguageSwitch } from "../src/components/LanguageSwitch";
import { RunActivity } from "../src/components/RunActivity";
import { Markdown } from "../src/components/Markdown";
import { formatDate } from "../src/utils/workspace";

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});
const catalogue = en.workspace as Record<string, string>;

describe("English and Chinese interface", () => {
  it("retains matching interpolation variables and a translation for every static UI lookup", () => {
    const variables = (value: string) =>
      [...value.matchAll(/{{\s*([\w]+)\s*}}/g)].map((match) => match[1]).sort();
    for (const [key, value] of Object.entries(zh.workspace)) {
      expect(variables(value), key).toEqual(variables(catalogue[key]));
      expect(value.trim(), key).not.toBe("");
    }
    const sources = import.meta.glob("../src/**/*.tsx", {
      query: "?raw",
      import: "default",
      eager: true,
    });
    const missing = new Set<string>();
    for (const [file, raw] of Object.entries(sources)) {
      const source = ts.createSourceFile(
        file,
        String(raw),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX,
      );
      function visit(node: ts.Node) {
        if (
          ts.isCallExpression(node) &&
          node.expression.getText(source) === "ui" &&
          node.arguments[0] &&
          ts.isStringLiteral(node.arguments[0])
        ) {
          const key = node.arguments[0].text.trim();
          if (/[A-Za-z]/.test(key) && !(key in catalogue))
            missing.add(`${file}: ${key}`);
        }
        if (
          ts.isJsxAttribute(node) &&
          [
            "title",
            "copy",
            "eyebrow",
            "description",
            "placeholder",
            "aria-label",
            "closeLabel",
          ].includes(node.name.getText(source)) &&
          node.initializer &&
          ts.isStringLiteral(node.initializer)
        ) {
          const key = node.initializer.text.trim();
          if (/[A-Za-z]/.test(key) && !(key in catalogue))
            missing.add(`${file}: ${key}`);
        }
        if (ts.isJsxText(node) && /[A-Za-z]/.test(node.getText(source)))
          missing.add(
            `${file}: untranslated JSX text ${node.getText(source).trim()}`,
          );
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
    expect([...missing]).toEqual([]);
  });

  it("switches reactive stage controls, persists the preference and leaves report/tool text intact", async () => {
    await i18n.changeLanguage("en");
    render(
      <>
        <LanguageSwitch />
        <RunActivity
          state={{
            status: "running",
            connection: "live",
            stats: {},
            agents: { "Market Analyst": "in_progress" },
            sections: { market_report: "Research overview" },
            messages: [
              {
                id: "m",
                stage: "analysts",
                type: "Agent",
                content: "Market analysis",
              },
            ],
          }}
        />
        <Markdown>{"Research overview"}</Markdown>
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    await screen.findByRole("heading", { name: "运行动态" });
    expect(screen.getByRole("tab", { name: /分析团队/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByLabelText("筛选动态")).toBeVisible();
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(localStorage.getItem("ta.language")).toBe("zh");
    expect(document.querySelector(".run-message pre")?.textContent).toBe(
      "Market analysis",
    );
    expect(document.querySelector(".markdown")?.textContent).toBe(
      "Research overview",
    );
    expect(formatDate("2026-11-01")).toContain("11月");
    fireEvent.click(screen.getByRole("button", { name: "切换为英文" }));
    await screen.findByRole("heading", { name: "Run activity" });
    expect(document.documentElement.lang).toBe("en");
    expect(localStorage.getItem("ta.language")).toBe("en");
    expect(formatDate("2026-11-01")).toBe("Nov 1, 2026");
  });

  it("keeps canonical ratings distinct, preserves interpolation and safely falls back for opaque text", async () => {
    await i18n.changeLanguage("zh");
    expect(ui("REVIEW")).toBe("REVIEW");
    expect(ui("Hold")).toBe("持有");
    expect(ui("REVIEW")).not.toBe(ui("Hold"));
    expect(ui("{{ticker}} analysis", { ticker: "NVDA" })).toBe("NVDA 分析");
    expect(ui("  Research audit  ")).toBe("  研究审计  ");
    expect(uiHolding("5 trading days")).toBe("5 个交易日");
    expect(uiHolding("custom recorded window")).toBe("custom recorded window");
    expect(ui("deepseek-flash")).toBe("deepseek-flash");
    expect(uiHistoryTitle("NVDA saved report", "NVDA")).toBe("NVDA 已保存报告");
    expect(uiHistoryTitle("Research overview", "NVDA")).toBe(
      "Research overview",
    );
    expect(ui("<script>alert(1)</script>")).toBe("<script>alert(1)</script>");
  });

  it("handles plural labels and unavailable browser storage without failing the switch", async () => {
    await i18n.changeLanguage("en");
    expect(ui("{{count}} debate rounds", { count: 1 })).toBe("1 debate round");
    expect(ui("{{count}} debate rounds", { count: 3 })).toBe("3 debate rounds");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Storage disabled");
    });
    await act(async () => {
      await i18n.changeLanguage("zh");
    });
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(ui("{{count}} debate rounds", { count: 1 })).toBe("1 轮辩论");
  });

  it("normalizes existing Chinese preferences and rejects unsupported locales", () => {
    expect(normalizeLanguage("zh-CN")).toBe("zh");
    expect(normalizeLanguage("zh-HK")).toBe("zh");
    expect(normalizeLanguage("ja")).toBe("en");
    expect(normalizeLanguage(null)).toBe("en");
  });
});
