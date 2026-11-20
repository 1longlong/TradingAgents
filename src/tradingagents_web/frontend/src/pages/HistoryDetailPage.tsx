// REQ-WEB-008/009, ADR-003, INV-WEB-014: recorded sections and available downloads only.
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { downloadUrl, getHistoryDetail } from "../api/client";
import { Icon } from "../components/Icon";
import { ReportDocument } from "../components/Research";
import { formatDate, ratingClass } from "../utils/workspace";

export function HistoryDetailPage() {
  const { artifactId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["history", "detail", artifactId],
    queryFn: () => getHistoryDetail(artifactId),
    enabled: Boolean(artifactId),
  });

  if (detail.isLoading) {
    return <div className="panel empty-state">Loading report...</div>;
  }
  if (detail.isError || !detail.data) {
    return (
      <>
        <section className="page-header">
          <div>
            <p className="eyebrow">RESEARCH LIBRARY</p>
            <h1>Report unavailable</h1>
            <p className="page-description">
              This artifact is no longer available.
            </p>
          </div>
          <Link className="button" to="/history">
            Back to history
          </Link>
        </section>
        <div className="panel empty-state">
          <Icon name="file" />
          <strong>Artifact not found</strong>
          <p>
            {detail.error instanceof Error
              ? detail.error.message
              : "Request failed."}
          </p>
        </div>
      </>
    );
  }

  const data = detail.data;
  const artifacts = data.artifacts ?? [];
  const complete = artifacts.some((item) => item.kind === "complete");
  const archive = artifacts.some((item) => item.kind === "archive");
  const log = artifacts.some((item) => item.kind === "log");
  const isBacktest = data.source === "backtest";
  const isDecision = data.source === "decision";

  return (
    <>
      <section className="page-header">
        <div>
          <p className="eyebrow">RESEARCH / {data.ticker}</p>
          <h1>{data.ticker} analysis</h1>
          <p className="page-description">
            A collective review of {data.ticker}.
          </p>
        </div>
        <div className="page-header-actions">
          <Link className="button ghost" to="/history">
            <Icon name="clock" />
            History
          </Link>
          <Link
            className="button ghost"
            to={`/audit?artifact_id=${data.artifact_id}`}
          >
            <Icon name="shield" />
            Research audit
          </Link>
          {complete ? (
            <a
              className="button"
              href={downloadUrl(data.artifact_id, "complete")}
            >
              <Icon name="download" />
              Export report
            </a>
          ) : null}
          {archive ? (
            <a
              className="button"
              href={downloadUrl(data.artifact_id, "archive")}
            >
              <Icon name="download" />
              Archive
            </a>
          ) : null}
          {log ? (
            <a className="button" href={downloadUrl(data.artifact_id, "log")}>
              <Icon name="download" />
              Decision log
            </a>
          ) : null}
        </div>
      </section>

      {data.review || data.rating === "REVIEW" ? (
        <div className="report-state-banner warning">
          <Icon name="warning" />
          <div>
            <strong>A human perspective is needed</strong>
            <p>
              The result is flagged as REVIEW. It has not been converted to Hold
              or treated as a position.
            </p>
          </div>
        </div>
      ) : null}

      {data.status === "partial" ? (
        <div className="report-state-banner">
          <Icon name="file" />
          <div>
            <strong>Partial saved report</strong>
            <p>
              Only available sections are listed. No final assessment or
              complete-report download is assumed.
            </p>
          </div>
        </div>
      ) : null}
      {data.status === "cancelled" ? (
        <div className="report-state-banner warning">
          <Icon name="pause" />
          <div>
            <strong>Stopped before a final decision</strong>
            <p>
              Available sections are retained; no final decision is recorded.
            </p>
          </div>
        </div>
      ) : null}
      {isBacktest ? (
        <BacktestArtifact summary={data.summary ?? {}} />
      ) : isDecision ? (
        <DecisionEntries entries={data.entries ?? []} />
      ) : (
        <ReportDocument record={{ ...data, metadata: data.metadata }} />
      )}
    </>
  );
}

function BacktestArtifact({ summary }: { summary: Record<string, unknown> }) {
  const byRating = (summary.by_rating ?? {}) as Record<
    string,
    { count: number; hit_rate: number | null; mean_alpha: number }
  >;
  const failures = (summary.failures ?? []) as Array<[string, string, string]>;
  const settlement = (summary.settlement_failures ?? []) as Array<
    [string, string]
  >;
  return (
    <div className="panel chart-panel">
      <div className="chart-heading">
        <div>
          <p className="eyebrow">BACKTEST RESULT</p>
          <h2>Recorded summary</h2>
          <p>
            Resolved {String(summary.resolved ?? "—")} · Pending{" "}
            {String(summary.pending ?? "—")} · Unscored{" "}
            {String(summary.unscored ?? "—")} · Holding{" "}
            {String(summary.holding ?? "—")}
          </p>
        </div>
      </div>
      <div className="rating-bars">
        {Object.entries(byRating).map(([rating, score]) => (
          <div className="rating-bar" key={rating}>
            <span>{rating}</span>
            <div className="bar-track">
              <div
                className={`bar-fill ${score.mean_alpha < 0 ? "negative" : ""}`}
                style={{
                  width: `${Math.min(100, Math.abs(score.mean_alpha) * 100)}%`,
                }}
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
              <td>{rating}</td>
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
      {failures.length ? (
        <p className="inline-note">
          Cell failures: {failures.length}. Settlement failures:{" "}
          {settlement.length}.
        </p>
      ) : null}
    </div>
  );
}

function DecisionEntries({
  entries,
}: {
  entries: Array<Record<string, unknown>>;
}) {
  if (!entries.length) {
    return (
      <div className="panel empty-state">
        <Icon name="book" />
        <strong>No decision entries</strong>
        <p>The decision log is empty.</p>
      </div>
    );
  }
  return (
    <section className="journal-list">
      {entries.map((entry, index) => {
        const rating = String(entry.rating ?? "—");
        return (
          <article
            className="panel journal-entry"
            key={`${entry.ticker}-${entry.date}-${index}`}
          >
            <span className="company-logo">
              {String(entry.ticker ?? "?").slice(0, 1)}
            </span>
            <div>
              <h2>{String(entry.ticker ?? "")}</h2>
              <p>{String(entry.decision ?? "").slice(0, 260)}</p>
              <span className="eyebrow">
                {formatDate(String(entry.date ?? ""))} ·{" "}
                {entry.pending ? "PENDING OUTCOME" : "RESOLVED"}
              </span>
            </div>
            <span className={ratingClass(rating)}>{rating}</span>
          </article>
        );
      })}
    </section>
  );
}
