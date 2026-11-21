import { ui, uiHolding, useUILanguage } from "../../i18n/ui";
// REQ-WEB-011, ADR-003: score displays use recorded counts and null semantics.
import { useTranslation } from "react-i18next";
import type { BacktestSummaryData } from "../../api/backtestClient";
import { Rating } from "../../components/Research";
export function BacktestSummary({
  summary,
  description,
}: {
  summary: BacktestSummaryData;
  description?: string;
}) {
  useUILanguage();
  const { t } = useTranslation(),
    scores = Object.entries(summary.by_rating ?? {});
  const alpha = (value: number) =>
    `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
  return (
    <>
      <div className="summary-metrics">
        {[
          [t("backtest.resolved"), summary.resolved],
          [t("backtest.pending"), summary.pending],
          [t("backtest.unscored"), summary.unscored],
        ].map(([label, value]) => (
          <div className="panel summary-metric" key={label}>
            <small>{ui(label)}</small>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      {description ? <p className="inline-note">{ui(description)}</p> : null}
      <section className="panel chart-panel">
        <div className="chart-heading">
          <div>
            <h2>{ui("Backtest results")}</h2>
            <p>
              {t("backtest.holding")}
              {ui(": ")}
              {uiHolding(summary.holding)}
            </p>
          </div>
        </div>
        <table>
          <caption className="sr-only">
            {ui("Recorded backtest results")}
          </caption>
          <thead>
            <tr>
              <th>{t("backtest.rating")}</th>
              <th>{t("backtest.count")}</th>
              <th>{t("backtest.hitRate")}</th>
              <th>{t("backtest.meanAlpha")}</th>
            </tr>
          </thead>
          <tbody>
            {scores.map(([rating, score]) => (
              <tr key={rating}>
                <td>
                  <Rating value={rating} />
                </td>
                <td>{score.count}</td>
                <td>
                  {!score.count
                    ? ui("—")
                    : rating === "Hold" || score.hit_rate == null
                      ? ui("No direction claimed")
                      : ui("{{value0}}%", {
                          value0: Math.round(score.hit_rate * 100),
                        })}
                </td>
                <td>{score.count ? ui(alpha(score.mean_alpha)) : ui("—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <details className="disclosure">
          <summary>{ui("How to read these results")}</summary>
          <p className="inline-note">
            {ui(
              "Mean alpha is relative to the configured benchmark over the recorded holding window. Hold has no directional hit rate. Zero-count groups have no score. A historical result is not a promise of future returns.",
            )}
          </p>
        </details>
      </section>
      {summary.failures?.length || summary.settlement_failures?.length ? (
        <section className="panel chart-panel">
          <h2>{ui("Unfinished cells stay visible")}</h2>
          <ul className="gap-list">
            {summary.failures?.map(([ticker, date, reason], index) => (
              <li key={`cell-${index}`}>
                {ui(ticker)} {ui(date)}
                {ui(": ")}
                {ui(reason)}
              </li>
            ))}
            {summary.settlement_failures?.map(([ticker, reason], index) => (
              <li key={`settlement-${index}`}>
                {ui(ticker)}
                {ui(" settlement: ")}
                {ui(reason)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
