// REQ-WEB-010, ADR-003: full-list filtering retains the demo table contract.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { getAllHistory } from "../api/client";
import { Icon } from "../components/Icon";
import {
  HistoryFilters,
  HistoryTable,
  filterAnalyses,
} from "../components/HistoryTable";
export function HistoryPage() {
  const history = useQuery({
    queryKey: ["history", "workspace"],
    queryFn: getAllHistory,
  });
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState("all"),
    [descending, setDescending] = useState(true);
  const items = filterAnalyses(
    history.data?.items ?? [],
    search,
    status,
    descending,
  );
  return (
    <>
      <section className="page-header">
        <div>
          <p className="eyebrow">THE RESEARCH LIBRARY</p>
          <h1>Analysis history</h1>
          <p className="page-description">
            Every question leaves a paper trail. Revisit the research.
          </p>
        </div>
        <div className="page-header-actions">
          <Link className="button primary" to="/new">
            <Icon name="plus" />
            New analysis
          </Link>
        </div>
      </section>
      <div className="section-heading">
        <h2>
          All research{" "}
          <span className="count">
            {filterAnalyses(history.data?.items ?? [], "", "all").length}
          </span>
        </h2>
        <HistoryFilters
          search={search}
          status={status}
          onSearch={setSearch}
          onStatus={setStatus}
          onClear={() => {
            setSearch("");
            setStatus("all");
            setDescending(true);
          }}
        />
      </div>
      {history.isLoading ? (
        <div className="panel empty-state">Loading history...</div>
      ) : history.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>History is unavailable</strong>
          <p>{history.error.message}</p>
        </div>
      ) : (
        <HistoryTable
          items={items}
          full
          descending={descending}
          onSort={() => setDescending(!descending)}
        />
      )}
    </>
  );
}
