import { ui, uiHolding, useUILanguage } from "../i18n/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { downloadUrl } from "../api/client";
import { getBacktest } from "../api/backtestClient";
import { Icon } from "../components/Icon";
import { formatDate, ratingClass } from "../utils/workspace";

const TERMINAL = new Set(["completed", "failed"]);

export function BacktestRunPage() {
  useUILanguage();
  const { runId = "" } = useParams();
  const query = useQuery({
    queryKey: ["backtest", runId],
    queryFn: () => getBacktest(runId),
    enabled: Boolean(runId),
    refetchInterval: (current) =>
      current.state.data && TERMINAL.has(current.state.data.status)
        ? false
        : 1000,
  });
  const snapshot = query.data;
  const summary = snapshot?.summary;
  const byRating = summary?.by_rating ?? {};
  const failures = summary?.failures ?? [];
  const settlement = summary?.settlement_failures ?? [];

  return (
    <>
      <section className="page-header">
        <div>
          <p className="eyebrow">
            {ui("BACKTEST / ")}
            {ui(snapshot?.status?.toUpperCase() ?? "LOADING")}
          </p>
          <h1>{ui(snapshot?.tickers?.join(", ") ?? runId)}</h1>
          <p className="page-description">
            {ui("Run ID: ")}
            {ui(runId)}
            {ui(" · ")}
            {ui(formatDate(snapshot?.start))}
            {ui(" – ")}
            {ui(formatDate(snapshot?.end))}
          </p>
        </div>
        <div className="page-header-actions">
          <Link className="button ghost" to="/backtest">
            <Icon name="sliders" />
            {ui("Backtesting")}
          </Link>
          {summary?.log_artifact_id ? (
            <a
              className="button"
              href={downloadUrl(summary.log_artifact_id, "log")}
            >
              <Icon name="download" />
              {ui("Download log")}
            </a>
          ) : null}
        </div>
      </section>

      {query.isLoading ? (
        <div className="panel empty-state">{ui("Loading backtest...")}</div>
      ) : query.isError ? (
        <div className="panel empty-state">
          <Icon name="warning" />
          <strong>{ui("Backtest unavailable")}</strong>
          <p>
            {query.error instanceof Error
              ? ui(query.error.message)
              : ui("Request failed.")}
          </p>
        </div>
      ) : null}

      {snapshot?.status === "running" || snapshot?.status === "starting" ? (
        <div className="report-state-banner">
          <Icon name="activity" />
          <div>
            <strong>{ui("Sweep in progress")}</strong>
            <p>
              {ui("Expected cells: ")}
              {ui(snapshot.expected_cells ?? "—")}
              {ui(
                ". The sweep runs to completion; cancellation is not available.",
              )}
            </p>
          </div>
        </div>
      ) : null}

      {snapshot?.error ? (
        <div className="report-state-banner warning">
          <Icon name="warning" />
          <div>
            <strong>{ui("Backtest failed")}</strong>
            <p>
              {ui(String(snapshot.error.message ?? "Check the server log."))}
              {snapshot.error.correlation_id
                ? ` (${String(snapshot.error.correlation_id)})`
                : null}
            </p>
          </div>
        </div>
      ) : null}

      {summary ? (
        <>
          <div className="summary-metrics">
            <div className="panel summary-metric">
              <small>{ui("Resolved decisions")}</small>
              <strong>{summary.resolved}</strong>
            </div>
            <div className="panel summary-metric">
              <small>{ui("Pending outcomes")}</small>
              <strong>{summary.pending}</strong>
            </div>
            <div className="panel summary-metric">
              <small>{ui("Unscored decisions")}</small>
              <strong>{summary.unscored}</strong>
            </div>
          </div>

          <section className="panel chart-panel">
            <div className="chart-heading">
              <div>
                <p className="eyebrow">{ui("THE CONVICTION CHECK")}</p>
                <h2>{ui("What followed each assessment?")}</h2>
                <p>
                  {ui("Cells run ")}
                  {ui(snapshot?.cells_run ?? "—")}
                  {ui(" · Skipped")}
                  {ui(" ")}
                  {ui(snapshot?.skipped ?? "—")}
                  {ui(" · Holding ")}
                  {uiHolding(summary.holding, "—")}
                </p>
              </div>
              <span className="chart-legend">{ui("Mean alpha")}</span>
            </div>
            <div className="rating-bars">
              {Object.entries(byRating).map(([rating, score]) => (
                <div className="rating-bar" key={rating}>
                  <span>{ui(rating)}</span>
                  <div className="bar-track">
                    <div
                      className={`bar-fill ${score.mean_alpha < 0 ? "negative" : ""}`}
                      style={{
                        width: `${Math.min(100, Math.abs(score.mean_alpha) * 100)}%`,
                      }}
                    />
                  </div>
                  <b>
                    {ui("{{value0}}{{value1}}%", {
                      value0: score.mean_alpha >= 0 ? "+" : "",
                      value1: (score.mean_alpha * 100).toFixed(2),
                    })}
                  </b>
                </div>
              ))}
            </div>
            <table>
              <thead>
                <tr>
                  <th>{ui("Assessment")}</th>
                  <th>{ui("Decisions")}</th>
                  <th>{ui("Hit rate")}</th>
                  <th>{ui("Mean alpha")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byRating).map(([rating, score]) => (
                  <tr key={rating}>
                    <td>
                      <span className={ratingClass(rating)}>{ui(rating)}</span>
                    </td>
                    <td>{score.count}</td>
                    <td>
                      {score.hit_rate == null
                        ? ui("No direction claimed")
                        : ui("{{value0}}%", {
                            value0: Math.round(score.hit_rate * 100),
                          })}
                    </td>
                    <td>
                      {ui("{{value0}}{{value1}}%", {
                        value0: score.mean_alpha >= 0 ? "+" : "",
                        value1: (score.mean_alpha * 100).toFixed(2),
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="inline-note">
              {ui(
                "Hold has no directional hit rate. Zero-count groups have no score. Mean alpha is relative to the configured benchmark over the recorded holding window.",
              )}
            </p>
          </section>

          {failures.length || settlement.length ? (
            <section className="panel chart-panel">
              <p className="eyebrow">{ui("FAILURES")}</p>
              <h2>{ui("Unfinished cells stay visible")}</h2>
              <ul className="gap-list">
                {failures.map(([ticker, date, reason], index) => (
                  <li key={`cell-${index}`}>
                    {ui(ticker)} {ui(date)}
                    {ui(": ")}
                    {ui(reason)}
                  </li>
                ))}
                {settlement.map(([ticker, reason], index) => (
                  <li key={`settle-${index}`}>
                    {ui(ticker)}
                    {ui(" settlement: ")}
                    {ui(reason)}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </>
  );
}
