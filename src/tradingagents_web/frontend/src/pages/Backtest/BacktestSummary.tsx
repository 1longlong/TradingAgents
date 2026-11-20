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
  const { t } = useTranslation(),
    scores = Object.entries(summary.by_rating ?? {}),
    scale = Math.max(
      0.025,
      ...scores
        .filter(([, score]) => score.count > 0)
        .map(([, score]) => Math.abs(score.mean_alpha)),
    );
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
            <small>{label}</small>
            <strong>
              {String(value).padStart(
                label === t("backtest.resolved") ? 1 : 2,
                "0",
              )}
            </strong>
          </div>
        ))}
      </div>
      {description ? <p className="inline-note">{description}</p> : null}
      <section className="panel chart-panel">
        <div className="chart-heading">
          <div>
            <p className="eyebrow">THE CONVICTION CHECK</p>
            <h2>What followed each assessment?</h2>
            <p>
              {t("backtest.holding")}: {summary.holding || "Not recorded"}
            </p>
          </div>
          <span className="chart-legend">Mean alpha</span>
        </div>
        <div
          className="rating-bars"
          role="img"
          aria-label="Recorded mean alpha by rating; exact values follow in the table"
        >
          {scores.map(([rating, score]) => (
            <div className="rating-bar" key={rating}>
              <span>{rating}</span>
              <div className="bar-track">
                <div
                  className={`bar-fill ${score.mean_alpha < 0 ? "negative" : ""}`}
                  style={{
                    width: `${score.count ? (Math.abs(score.mean_alpha) / scale) * 100 : 0}%`,
                  }}
                />
              </div>
              <b>{score.count ? alpha(score.mean_alpha) : "—"}</b>
            </div>
          ))}
        </div>
        <table>
          <caption className="sr-only">Recorded backtest results</caption>
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
                    ? "—"
                    : rating === "Hold" || score.hit_rate == null
                      ? "No direction claimed"
                      : `${Math.round(score.hit_rate * 100)}%`}
                </td>
                <td>{score.count ? alpha(score.mean_alpha) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="inline-note">
          Mean alpha is relative to the configured benchmark over the recorded
          holding window. Hold has no directional hit rate. Zero-count groups
          have no score. A historical result is not a promise of future returns.
        </p>
      </section>
      {summary.failures?.length || summary.settlement_failures?.length ? (
        <section className="panel chart-panel">
          <p className="eyebrow">FAILURES</p>
          <h2>Unfinished cells stay visible</h2>
          <ul className="gap-list">
            {summary.failures?.map(([ticker, date, reason], index) => (
              <li key={`cell-${index}`}>
                {ticker} {date}: {reason}
              </li>
            ))}
            {summary.settlement_failures?.map(([ticker, reason], index) => (
              <li key={`settlement-${index}`}>
                {ticker} settlement: {reason}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
