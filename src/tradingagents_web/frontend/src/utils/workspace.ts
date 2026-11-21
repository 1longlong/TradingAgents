import i18n from "../i18n";
export const ANALYST_LABELS: Record<string, string> = {
  market: "Market",
  social: "Sentiment",
  news: "News",
  fundamentals: "Fundamentals",
};

export const SECTION_LABELS: Record<string, string> = {
  market_report: "Market analysis",
  sentiment_report: "Sentiment analysis",
  news_report: "News analysis",
  fundamentals_report: "Fundamentals analysis",
  investment_plan: "Research plan",
  trader_investment_plan: "Trading plan",
  final_trade_decision: "Portfolio decision",
  complete_report: "Complete report",
};

export const SECTION_ORDER = [
  "market_report",
  "sentiment_report",
  "news_report",
  "fundamentals_report",
  "investment_plan",
  "trader_investment_plan",
  "final_trade_decision",
];

export function formatDate(value?: string | null): string {
  if (!value) return "Not recorded";
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(
    i18n.language.startsWith("zh") ? "zh-CN" : "en-US",
    {
      month: "short",
      day: "numeric",
      year: "numeric",
    },
  );
}

export function formatTimestamp(value?: string | null): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(
    i18n.language.startsWith("zh") ? "zh-CN" : "en-US",
    {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    },
  );
}

export function ratingClass(rating?: string | null): string {
  if (rating === "REVIEW") return "rating review";
  if (rating === "Hold") return "rating hold";
  if (rating === "Sell" || rating === "Underweight") return "rating sell";
  return "rating";
}

export function statusClass(status?: string | null): string {
  if (status === "failed") return "status-tag danger";
  if (status === "partial" || status === "cancelled")
    return "status-tag warning";
  if (status === "running" || status === "cancelling") return "status-tag";
  return "status-tag neutral";
}

export function statusLabel(status?: string | null): string {
  switch (status) {
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    case "partial":
      return "Partial";
    case "running":
      return "Running";
    case "cancelling":
      return "Stopping";
    default:
      return status ?? "Unknown";
  }
}

export function letterFor(ticker: string): string {
  return ticker.trim().slice(0, 1).toUpperCase() || "?";
}

export function sectionLabel(key: string): string {
  if (SECTION_LABELS[key]) return SECTION_LABELS[key];
  const [folder, name] = key.split("/");
  if (folder === "1_analysts") {
    const analyst =
      name === "sentiment" ? ANALYST_LABELS.social : ANALYST_LABELS[name];
    return `${analyst ?? name ?? "Analyst"} analysis`;
  }
  const saved: Record<string, string> = {
    "2_research/bull": "Bull case",
    "2_research/bear": "Bear case",
    "2_research/manager": "Research manager plan",
    "3_trading/trader": "Trading plan",
    "4_risk/aggressive": "Aggressive risk view",
    "4_risk/conservative": "Conservative risk view",
    "4_risk/neutral": "Neutral risk view",
    "5_portfolio/decision": "Portfolio decision",
  };
  return saved[key] ?? key.replaceAll("_", " ").replaceAll("/", " / ");
}

function sectionRank(key: string): number {
  const exact = SECTION_ORDER.indexOf(key);
  if (exact >= 0) return exact;
  if (key.startsWith("1_analysts/"))
    return 10 + SECTION_ORDER.indexOf(`${key.split("/")[1]}_report`);
  if (key.startsWith("2_research/")) return 30;
  if (key.startsWith("3_trading/")) return 40;
  if (key.startsWith("4_risk/")) return 50;
  if (key.startsWith("5_portfolio/")) return 60;
  if (key === "complete_report") return 70;
  return 80;
}

export function visibleSectionKeys(
  sections?: Record<string, string>,
): string[] {
  if (!sections) return [];
  // REQ-WEB-009: a combined report is a fallback, not a duplicate of its sections.
  const keys = Object.keys(sections);
  const visible = keys.some((key) => key !== "complete_report")
    ? keys.filter((key) => key !== "complete_report")
    : keys;
  return visible.sort((left, right) => {
    const delta = sectionRank(left) - sectionRank(right);
    return delta === 0 ? left.localeCompare(right) : delta;
  });
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export function alpha(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}
