export type BacktestValidationResult = { ok: boolean; error?: string };

const TICKER_RE = /^[A-Za-z0-9._\-^=+]+$/;
const RUN_ID_RE = /^[A-Za-z0-9._\-^=+]+$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const ANALYSTS = new Set(["market", "social", "news", "fundamentals"]);

function parseDate(value: string): Date | null {
  if (!DATE_RE.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function validateTicker(value: string): string | null {
  const ticker = value.trim();
  if (!ticker) return "Ticker is required.";
  if (ticker.length > 32 || !TICKER_RE.test(ticker)) {
    return "Ticker contains unsupported characters.";
  }
  return null;
}

export function validateBacktest(
  values: Record<string, unknown>,
): BacktestValidationResult {
  const tickers = Array.isArray(values.tickers) ? values.tickers : [];
  if (tickers.length === 0) return { ok: false, error: "Add at least one ticker." };
  for (const raw of tickers) {
    const error = validateTicker(String(raw));
    if (error) return { ok: false, error };
  }

  const startText = String(values.start ?? "").trim();
  const endText = String(values.end ?? "").trim();
  const start = parseDate(startText);
  const end = parseDate(endText);
  if (!start || !end) return { ok: false, error: "Use YYYY-MM-DD for both dates." };
  if (end < start) return { ok: false, error: "End date must not be before start." };

  const every = Number(values.every);
  if (!Number.isInteger(every) || every < 1) {
    return { ok: false, error: "Interval must be a positive whole number of days." };
  }

  const analysts = Array.isArray(values.analysts) ? values.analysts : [];
  if (analysts.length === 0) return { ok: false, error: "Select at least one analyst." };
  if (analysts.some((name) => !ANALYSTS.has(String(name)))) {
    return { ok: false, error: "Unknown analyst." };
  }

  const assetType = String(values.assetType ?? "stock");
  if (assetType !== "stock" && assetType !== "crypto") {
    return { ok: false, error: "Asset type must be stock or crypto." };
  }

  const portfolio = String(values.portfolioJson ?? "").trim();
  if (portfolio) {
    try {
      const parsed: unknown = JSON.parse(portfolio);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { ok: false, error: "Portfolio must be a JSON object." };
      }
    } catch {
      return { ok: false, error: "Portfolio is not valid JSON." };
    }
  }

  const runId = String(values.runId ?? "").trim();
  if (runId) {
    if (
      runId.length > 32 ||
      !RUN_ID_RE.test(runId) ||
      [...runId].every((character) => character === ".")
    ) {
      return { ok: false, error: "Run ID contains unsupported characters." };
    }
  }

  return { ok: true };
}
