import { useTranslation } from "react-i18next";

import type { BacktestSummaryData } from "../../api/backtestClient";

function percent(value: number | null): string {
  if (value === null || value === undefined) return "n/a";
  return `${Math.round(value * 100)}%`;
}

function alpha(value: number): string {
  const formatted = (value * 100).toFixed(2);
  return `${value >= 0 ? "+" : ""}${formatted}%`;
}

export function BacktestSummary({ summary }: { summary: BacktestSummaryData }) {
  const { t } = useTranslation();
  const byRating = summary.by_rating ?? {};

  return (
    <section className="space-y-5 rounded-lg border border-slate-800 p-5">
      <div className="grid grid-cols-2 gap-3 text-sm text-slate-200 sm:grid-cols-4">
        <p>
          {t("backtest.resolved")}: {summary.resolved}
        </p>
        <p>
          {t("backtest.pending")}: {summary.pending}
        </p>
        <p>
          {t("backtest.unscored")}: {summary.unscored}
        </p>
        <p>
          {t("backtest.holding")}: {summary.holding}
        </p>
      </div>

      <div className="overflow-hidden rounded-md border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2">{t("backtest.rating")}</th>
              <th className="px-3 py-2">{t("backtest.count")}</th>
              <th className="px-3 py-2">{t("backtest.hitRate")}</th>
              <th className="px-3 py-2">{t("backtest.meanAlpha")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {Object.entries(byRating).map(([rating, score]) => (
              <tr key={rating}>
                <td className="px-3 py-2 font-mono text-slate-200">{rating}</td>
                <td className="px-3 py-2 text-slate-300">{score.count}</td>
                <td className="px-3 py-2 text-slate-300">{percent(score.hit_rate)}</td>
                <td className="px-3 py-2 text-slate-300">{alpha(score.mean_alpha)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {summary.failures?.length ? (
        <div>
          <h3 className="text-sm font-medium text-amber-200">
            {t("backtest.failures")}
          </h3>
          <ul className="mt-2 space-y-1 text-sm text-slate-300">
            {summary.failures.map(([ticker, date, reason], index) => (
              <li key={`${ticker}-${date}-${index}`}>
                <span className="font-mono text-slate-200">
                  {ticker} {date}
                </span>
                : {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {summary.settlement_failures?.length ? (
        <div>
          <h3 className="text-sm font-medium text-amber-200">
            {t("backtest.settlementFailures")}
          </h3>
          <ul className="mt-2 space-y-1 text-sm text-slate-300">
            {summary.settlement_failures.map(([ticker, reason], index) => (
              <li key={`${ticker}-${index}`}>
                <span className="font-mono text-slate-200">{ticker}</span>: {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
