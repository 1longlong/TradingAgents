// REQ-WEB-002/010/011, ADR-003: demo layout backed by recorded workspace data.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { listBacktests } from "../api/backtestClient";
import { getAllHistory, getHistoryDetail } from "../api/client";
import { getActiveRun, getRun } from "../api/runClient";
import { Icon } from "../components/Icon";
import {
  HistoryFilters,
  HistoryTable,
  filterAnalyses,
} from "../components/HistoryTable";
import { Pipeline, ResearchCard } from "../components/Research";
import { formatDate } from "../utils/workspace";
import { AuditOverview } from "./AuditPage";

export function OverviewPage() {
  const history = useQuery({
    queryKey: ["history", "workspace"],
    queryFn: getAllHistory,
  });
  const backtests = useQuery({
    queryKey: ["backtests", "workspace"],
    queryFn: listBacktests,
  });
  const active = useQuery({
    queryKey: ["runs", "active"],
    queryFn: getActiveRun,
    refetchInterval: 2000,
  });
  const run = useQuery({
    queryKey: ["runs", "overview", active.data?.run_id],
    queryFn: () => getRun(active.data!.run_id!),
    enabled: Boolean(
      active.data?.run_id &&
      "ticker" in active.data &&
      active.data.kind !== "backtest",
    ),
    refetchInterval: 2000,
  });
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState("all"),
    [descending, setDescending] = useState(true);
  const items = history.data?.items ?? [],
    analyses = filterAnalyses(items, "", "all");
  const latest = analyses[0];
  const detail = useQuery({
    queryKey: ["history", "detail", latest?.artifact_id],
    queryFn: () => getHistoryDetail(latest!.artifact_id),
    enabled: Boolean(latest),
  });
  const live =
    run.data && ["starting", "running", "cancelling"].includes(run.data.status)
      ? run.data
      : null;
  const record = live
    ? {
        ticker: live.ticker,
        date: live.trade_date,
        status: live.status,
        rating: live.signal,
        review: live.review,
        sections: live.sections,
        analysts: live.analysts,
        metadata: {
          llm_provider: live.llm_provider,
          research_depth: live.research_depth,
          output_language: live.output_language,
        },
      }
    : latest
      ? {
          ...latest,
          sections: detail.data?.sections,
          metadata: detail.data?.metadata,
        }
      : null;
  const recentBacktest = backtests.data?.items[0],
    scores = Object.values(recentBacktest?.summary?.by_rating ?? {});
  const date = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  return (
    <>
      <section className="page-header">
        <div>
          <p className="eyebrow">YOUR RESEARCH, IN FOCUS</p>
          <h1>Research overview</h1>
          <p className="page-description">
            Start with a question. Explore every perspective.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="button ghost"
            onClick={() =>
              window.dispatchEvent(new CustomEvent("workspace:help"))
            }
          >
            <Icon name="book" />
            How it works
          </button>
          <Link className="button primary" to="/new">
            <Icon name="plus" />
            New analysis
          </Link>
        </div>
      </section>
      <section className="stats-strip" aria-label="Workspace summary">
        {[
          [
            "Completed analyses",
            "file",
            analyses.filter((item) => item.status === "completed").length,
            `${new Set(analyses.map((item) => item.ticker)).size} instruments`,
            "in your research",
          ],
          [
            "Flagged for review",
            "users",
            analyses.filter((item) => item.review || item.rating === "REVIEW")
              .length,
            "A decision needs",
            "a second look",
          ],
          [
            "Backtest sweeps",
            "sliders",
            backtests.data?.items.length ?? 0,
            "Fixed-date evaluations",
            "saved together",
          ],
        ].map(([label, icon, count, bold, copy]) => (
          <div className="stat" key={label}>
            <div className="stat-label">
              {label}
              <Icon name={String(icon)} />
            </div>
            <div className="stat-value">{String(count).padStart(2, "0")}</div>
            <p className="stat-bottom">
              <b>{bold}</b> {copy}
            </p>
          </div>
        ))}
      </section>
      <div className="section-heading">
        <h2>Your latest perspective</h2>
        <span className="subtle">{date}</span>
      </div>
      {history.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>History is unavailable</strong>
          <p>{history.error.message}</p>
        </div>
      ) : record ? (
        <section className="research-grid">
          <ResearchCard
            record={record}
            running={Boolean(live)}
            href={
              live ? `/runs/${live.run_id}` : `/history/${latest.artifact_id}`
            }
          />
          <Pipeline record={record} />
        </section>
      ) : (
        <div className="panel empty-state">
          <Icon name="search" />
          <strong>
            {history.isLoading ? "Loading research..." : "No analysis yet"}
          </strong>
          <p>Start a new analysis to populate the workspace.</p>
        </div>
      )}
      <AuditOverview artifactId={live ? undefined : latest?.artifact_id} />
      <section className="history-section">
        <div className="section-heading">
          <h2>
            Recent analyses <span className="count">{analyses.length}</span>
          </h2>
          <HistoryFilters
            search={search}
            status={status}
            onSearch={setSearch}
            onStatus={setStatus}
          />
        </div>
        <HistoryTable
          items={filterAnalyses(items, search, status, descending).slice(0, 6)}
          descending={descending}
          onSort={() => setDescending(!descending)}
        />
      </section>
      <section className="bottom-grid">
        <div className="note-panel">
          <span className="note-icon">
            <Icon name="users" />
          </span>
          <div>
            <h3>Better questions. Broader perspectives.</h3>
            <p>
              Four analyst lenses, a research debate, and a dedicated risk
              review.
              <br />
              One considered assessment for you to explore.
            </p>
          </div>
        </div>
        <Link
          className="panel mini-backtest"
          to={
            recentBacktest ? `/backtest/${recentBacktest.run_id}` : "/backtest"
          }
        >
          <div>
            <p className="eyebrow">RECENT BACKTEST</p>
            <h3>The conviction check</h3>
            <p>
              {recentBacktest?.tickers?.join(", ") ?? "No sweep recorded"}
              {recentBacktest?.summary
                ? ` · ${recentBacktest.summary.resolved + recentBacktest.summary.pending + recentBacktest.summary.unscored} decisions`
                : ""}
            </p>
            <span className="text-button">
              Explore the results
              <Icon name="arrow" />
            </span>
          </div>
          {scores.length ? (
            <div
              className="mini-bars"
              role="img"
              aria-label="Recorded decision counts by rating"
            >
              {scores.map((score, index) => (
                <span
                  key={index}
                  style={{
                    height: `${(score.count / Math.max(1, ...scores.map((item) => item.count))) * 100}%`,
                  }}
                />
              ))}
            </div>
          ) : null}
        </Link>
      </section>
      <span className="sr-only">{latest ? formatDate(latest.date) : ""}</span>
    </>
  );
}
