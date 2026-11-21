import { ui, useUILanguage } from "../i18n/ui";
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
  useUILanguage();
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
          <h1>{ui("Analysis history")}</h1>
        </div>
        <div className="page-header-actions">
          <Link className="button primary" to="/new">
            <Icon name="plus" />
            {ui("New analysis")}
          </Link>
        </div>
      </section>
      <div className="section-heading">
        <h2>{ui("All research")}</h2>
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
        <div className="panel empty-state">{ui("Loading history...")}</div>
      ) : history.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>{ui("History is unavailable")}</strong>
          <p>{ui(history.error.message)}</p>
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
