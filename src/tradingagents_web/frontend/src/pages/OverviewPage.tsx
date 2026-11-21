import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-002/010/021, ADR-003-frontend-stack.md: prioritize current and recent research.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { getAllHistory, getHistoryDetail } from "../api/client";
import { getActiveRun, getRun } from "../api/runClient";
import { Icon } from "../components/Icon";
import {
  HistoryFilters,
  HistoryTable,
  filterAnalyses,
} from "../components/HistoryTable";
import { ResearchCard } from "../components/Research";

export function OverviewPage() {
  useUILanguage();
  const history = useQuery({
    queryKey: ["history", "workspace"],
    queryFn: getAllHistory,
  });
  const active = useQuery({
    queryKey: ["runs", "active"],
    queryFn: getActiveRun,
    refetchInterval: 2000,
  });
  const analysisActive = Boolean(
    active.data?.run_id &&
    active.data.kind !== "backtest" &&
    active.data.kind !== "simulation",
  );
  const run = useQuery({
    queryKey: ["runs", "overview", active.data?.run_id],
    queryFn: () => getRun(active.data!.run_id!),
    enabled: analysisActive,
    refetchInterval: analysisActive ? 2000 : false,
  });
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState("all"),
    [descending, setDescending] = useState(true);
  const items = history.data?.items ?? [],
    latest = filterAnalyses(items, "", "all")[0];
  const detail = useQuery({
    queryKey: ["history", "detail", latest?.artifact_id],
    queryFn: () => getHistoryDetail(latest!.artifact_id),
    enabled: Boolean(latest),
  });
  const live =
    analysisActive &&
    run.data &&
    ["starting", "running", "cancelling"].includes(run.data.status)
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
        metadata: { llm_provider: live.llm_provider },
      }
    : latest
      ? {
          ...latest,
          sections: detail.data?.sections,
          metadata: detail.data?.metadata,
        }
      : null;
  return (
    <>
      <section className="page-header">
        <h1>{ui("Research overview")}</h1>
        <Link className="button primary" to="/new">
          <Icon name="plus" />
          {ui("New analysis")}
        </Link>
      </section>
      {active.data?.run_id && !analysisActive ? (
        <div className="report-state-banner compact-banner" role="status">
          <Icon name="activity" />
          <Link
            className="text-button"
            to={
              active.data.kind === "simulation"
                ? "/simulation"
                : `/backtest/${active.data.run_id}`
            }
          >
            {ui("Open active run")}
            <Icon name="arrow" />
          </Link>
        </div>
      ) : null}
      {record ? (
        <ResearchCard
          record={record}
          running={Boolean(live)}
          href={
            live ? `/runs/${live.run_id}` : `/history/${latest!.artifact_id}`
          }
        />
      ) : history.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>{ui("History is unavailable")}</strong>
          <p>{ui(history.error.message)}</p>
        </div>
      ) : (
        <div className="panel empty-state">
          <Icon name="search" />
          <strong>
            {ui(history.isLoading ? "Loading research..." : "No analysis yet")}
          </strong>
        </div>
      )}
      <section className="history-section">
        <div className="section-heading">
          <h2>{ui("Recent analyses")}</h2>
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
    </>
  );
}
