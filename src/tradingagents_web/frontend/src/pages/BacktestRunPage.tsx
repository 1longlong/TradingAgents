import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { downloadUrl } from "../api/client";
import { getBacktest } from "../api/backtestClient";
import { Icon } from "../components/Icon";
import { formatDate, ratingClass } from "../utils/workspace";

const TERMINAL = new Set(["completed", "failed"]);

export function BacktestRunPage() {
  const { runId = "" } = useParams();
  const query = useQuery({
    queryKey: ["backtest", runId],
    queryFn: () => getBacktest(runId),
    enabled: Boolean(runId),
    refetchInterval: (current) =>
      current.state.data && TERMINAL.has(current.state.data.status) ? false : 1000,
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
          <p className="eyebrow">BACKTEST / {snapshot?.status?.toUpperCase() ?? "LOADING"}</p>
          <h1>{snapshot?.tickers?.join(", ") ?? runId}</h1>
          <p className="page-description">
            Run ID: {runId} · {formatDate(snapshot?.start)} – {formatDate(snapshot?.end)}
          </p>
        </div>
        <div className="page-header-actions">
          <Link className="button ghost" to="/backtest">
            <Icon name="sliders" />
            Backtesting
          </Link>
          {summary?.log_artifact_id ? (
            <a className="button" href={downloadUrl(summary.log_artifact_id, "log")}>
              <Icon name="download" />
              Download log
            </a>
          ) : null}
        </div>
      </section>

      {query.isLoading ? (
        <div className="panel empty-state">Loading backtest...</div>
      ) : query.isError ? (
        <div className="panel empty-state">
          <Icon name="warning" />
          <strong>Backtest unavailable</strong>
          <p>{query.error instanceof Error ? query.error.message : "Request failed."}</p>
        </div>
      ) : null}

      {snapshot?.status === "running" || snapshot?.status === "starting" ? (
        <div className="report-state-banner">
          <Icon name="activity" />
          <div>
            <strong>Sweep in progress</strong>
            <p>
              Expected cells: {snapshot.expected_cells ?? "—"}. The sweep runs to
              completion; cancellation is not available.
            </p>
          </div>
        </div>
      ) : null}

      {snapshot?.error ? (
        <div className="report-state-banner warning">
          <Icon name="warning" />
          <div>
            <strong>Backtest failed</strong>
            <p>{String(snapshot.error.message ?? "Check the server log.")}</p>
          </div>
        </div>
      ) : null}

      {summary ? (
        <>
          <div className="summary-metrics">
            <div className="panel summary-metric">
              <small>Resolved decisions</small>
              <strong>{summary.resolved}</strong>
            </div>
            <div className="panel summary-metric">
              <small>Pending outcomes</small>
              <strong>{summary.pending}</strong>
            </div>
            <div className="panel summary-metric">
              <small>Unscored decisions</small>
              <strong>{summary.unscored}</strong>
            </div>
          </div>

          <section className="panel chart-panel">
            <div className="chart-heading">
              <div>
                <p className="eyebrow">THE CONVICTION CHECK</p>
                <h2>What followed each assessment?</h2>
                <p>
                  Cells run {snapshot?.cells_run ?? "—"} · Skipped{" "}
                  {snapshot?.skipped ?? "—"} · Holding {summary.holding || "—"}
                </p>
              </div>
              <span className="chart-legend">Mean alpha</span>
            </div>
            <div className="rating-bars">
              {Object.entries(byRating).map(([rating, score]) => (
                <div className="rating-bar" key={rating}>
                  <span>{rating}</span>
                  <div className="bar-track">
                    <div
                      className={`bar-fill ${score.mean_alpha < 0 ? "negative" : ""}`}
                      style={{ width: `${Math.min(100, Math.abs(score.mean_alpha) * 100)}%` }}
                    />
                  </div>
                  <b>{`${score.mean_alpha >= 0 ? "+" : ""}${(score.mean_alpha * 100).toFixed(2)}%`}</b>
                </div>
              ))}
            </div>
            <table>
              <thead>
                <tr>
                  <th>Assessment</th>
                  <th>Decisions</th>
                  <th>Hit rate</th>
                  <th>Mean alpha</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byRating).map(([rating, score]) => (
                  <tr key={rating}>
                    <td>
                      <span className={ratingClass(rating)}>{rating}</span>
                    </td>
                    <td>{score.count}</td>
                    <td>
                      {score.hit_rate == null
                        ? "No direction claimed"
                        : `${Math.round(score.hit_rate * 100)}%`}
                    </td>
                    <td>{`${score.mean_alpha >= 0 ? "+" : ""}${(score.mean_alpha * 100).toFixed(2)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="inline-note">
              Hold has no directional hit rate. Zero-count groups have no score.
              Mean alpha is relative to the configured benchmark over the
              recorded holding window.
            </p>
          </section>

          {failures.length || settlement.length ? (
            <section className="panel chart-panel">
              <p className="eyebrow">FAILURES</p>
              <h2>Unfinished cells stay visible</h2>
              <ul className="gap-list">
                {failures.map(([ticker, date, reason], index) => (
                  <li key={`cell-${index}`}>
                    {ticker} {date}: {reason}
                  </li>
                ))}
                {settlement.map(([ticker, reason], index) => (
                  <li key={`settle-${index}`}>
                    {ticker} settlement: {reason}
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
