import { ui, uiHolding, useUILanguage } from "../i18n/ui";
// REQ-WEB-008/009, ADR-003, INV-WEB-014: recorded sections and available downloads only.
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { downloadUrl, getHistoryDetail } from "../api/client";
import { Icon } from "../components/Icon";
import { ReportDocument } from "../components/Research";
import { formatDate, ratingClass } from "../utils/workspace";

export function HistoryDetailPage() {
  useUILanguage();
  const { artifactId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["history", "detail", artifactId],
    queryFn: () => getHistoryDetail(artifactId),
    enabled: Boolean(artifactId),
  });

  if (detail.isLoading) {
    return <div className="panel empty-state">{ui("Loading report...")}</div>;
  }
  if (detail.isError || !detail.data) {
    return (
      <>
        <section className="page-header">
          <div>
            <p className="eyebrow">{ui("RESEARCH LIBRARY")}</p>
            <h1>{ui("Report unavailable")}</h1>
            <p className="page-description">
              {ui("This artifact is no longer available.")}
            </p>
          </div>
          <Link className="button" to="/history">
            {ui("Back to history")}
          </Link>
        </section>
        <div className="panel empty-state">
          <Icon name="file" />
          <strong>{ui("Artifact not found")}</strong>
          <p>
            {detail.error instanceof Error
              ? ui(detail.error.message)
              : ui("Request failed.")}
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
          <h1>{ui("{{ticker}} analysis", { ticker: data.ticker })}</h1>
        </div>
        <div className="page-header-actions">
          <Link
            className="button ghost"
            to={`/audit?artifact_id=${data.artifact_id}`}
          >
            <Icon name="shield" />
            {ui("Research audit")}
          </Link>
          {complete ? (
            <a
              className="button"
              href={downloadUrl(data.artifact_id, "complete")}
            >
              <Icon name="download" />
              {ui("Export report")}
            </a>
          ) : null}
          {archive ? (
            <a
              className="button"
              href={downloadUrl(data.artifact_id, "archive")}
            >
              <Icon name="download" />
              {ui("Archive")}
            </a>
          ) : null}
          {log ? (
            <a className="button" href={downloadUrl(data.artifact_id, "log")}>
              <Icon name="download" />
              {ui("Decision log")}
            </a>
          ) : null}
        </div>
      </section>

      {data.review || data.rating === "REVIEW" ? (
        <div className="report-state-banner warning">
          <Icon name="warning" />
          <div>
            <strong>{ui("A human perspective is needed")}</strong>
            <p>
              {ui(
                "The result is flagged as REVIEW. It has not been converted to Hold or treated as a position.",
              )}
            </p>
          </div>
        </div>
      ) : null}

      {data.status === "partial" ? (
        <div className="report-state-banner">
          <Icon name="file" />
          <div>
            <strong>{ui("Partial saved report")}</strong>
            <p>
              {ui(
                "Only available sections are listed. No final assessment or complete-report download is assumed.",
              )}
            </p>
          </div>
        </div>
      ) : null}
      {data.status === "cancelled" ? (
        <div className="report-state-banner warning">
          <Icon name="pause" />
          <div>
            <strong>{ui("Stopped before a final decision")}</strong>
            <p>
              {ui(
                "Available sections are retained; no final decision is recorded.",
              )}
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
  useUILanguage();
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
          <p className="eyebrow">{ui("BACKTEST RESULT")}</p>
          <h2>{ui("Recorded summary")}</h2>
          <p>
            {ui("Resolved ")}
            {ui(String(summary.resolved ?? "—"))}
            {ui(" · Pending")}
            {ui(" ")}
            {ui(String(summary.pending ?? "—"))}
            {ui(" · Unscored")}
            {ui(" ")}
            {ui(String(summary.unscored ?? "—"))}
            {ui(" · Holding")}
            {ui(" ")}
            {uiHolding(String(summary.holding ?? "—"), "—")}
          </p>
        </div>
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
              <td>{ui(rating)}</td>
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
      {failures.length ? (
        <p className="inline-note">
          {ui("Cell failures: ")}
          {failures.length}
          {ui(". Settlement failures:")}
          {ui(" ")}
          {settlement.length}
          {ui(".")}
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
  useUILanguage();
  if (!entries.length) {
    return (
      <div className="panel empty-state">
        <Icon name="book" />
        <strong>{ui("No decision entries")}</strong>
        <p>{ui("The decision log is empty.")}</p>
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
              {ui(String(entry.ticker ?? "?").slice(0, 1))}
            </span>
            <div>
              <h2>{String(entry.ticker ?? "")}</h2>
              <p>{ui(String(entry.decision ?? "").slice(0, 260))}</p>
              <span className="eyebrow">
                {ui(formatDate(String(entry.date ?? "")))}
                {ui(" ·")}
                {ui(" ")}
                {entry.pending ? ui("PENDING OUTCOME") : ui("RESOLVED")}
              </span>
            </div>
            <span className={ratingClass(rating)}>{ui(rating)}</span>
          </article>
        );
      })}
    </section>
  );
}
