// REQ-WEB-010, ADR-003: present only recorded history metadata.
import { Link } from "react-router-dom";
import type { HistoryItem } from "../api/client";
import { CompanyLogo, Rating } from "./Research";
import { Icon } from "./Icon";
import { ANALYST_LABELS, formatDate, statusLabel } from "../utils/workspace";
export function HistoryFilters({
  search,
  status,
  onSearch,
  onStatus,
  onClear,
}: {
  search: string;
  status: string;
  onSearch: (value: string) => void;
  onStatus: (value: string) => void;
  onClear?: () => void;
}) {
  return (
    <div className="history-controls">
      <label className="filter-input">
        <Icon name="search" />
        <span className="sr-only">Filter analyses by ticker</span>
        <input
          type="search"
          placeholder="Search symbol..."
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
      </label>
      <label>
        <span className="sr-only">Filter by status</span>
        <select
          className="select-small"
          value={status}
          onChange={(event) => onStatus(event.target.value)}
        >
          {[
            ["all", "All analyses"],
            ["completed", "Completed"],
            ["review", "Needs review"],
            ["failed", "Data unavailable"],
            ["cancelled", "Cancelled"],
            ["partial", "Partial report"],
          ].map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {onClear ? (
        <button
          className="icon-button"
          aria-label="Clear filters"
          onClick={onClear}
        >
          <Icon name="refresh" />
        </button>
      ) : null}
    </div>
  );
}
export function filterAnalyses(
  items: HistoryItem[],
  search: string,
  status: string,
  descending = true,
) {
  return items
    .filter(
      (item) =>
        ["run", "saved"].includes(item.source) &&
        item.ticker.toLowerCase().includes(search.trim().toLowerCase()) &&
        (status === "all" ||
          (status === "review"
            ? item.review || item.rating === "REVIEW"
            : item.status === status)),
    )
    .sort((a, b) =>
      descending
        ? (b.date ?? "").localeCompare(a.date ?? "")
        : (a.date ?? "").localeCompare(b.date ?? ""),
    );
}
export function HistoryTable({
  items,
  descending,
  onSort,
  full = false,
}: {
  items: HistoryItem[];
  descending: boolean;
  onSort: () => void;
  full?: boolean;
}) {
  if (!items.length)
    return (
      <div className="panel empty-state">
        <Icon name="search" />
        <strong>No matching research</strong>
        <p>Try another symbol or clear the current filters.</p>
      </div>
    );
  return (
    <>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">
            Analysis history. Open a row to read the report.
          </caption>
          <thead>
            <tr>
              <th>Instrument</th>
              <th aria-sort={descending ? "descending" : "ascending"}>
                <button onClick={onSort}>
                  Analysis date
                  <Icon name="sort" />
                </button>
              </th>
              <th className="hide-medium">Research team</th>
              <th className="hide-medium">Model provider</th>
              <th>Depth</th>
              <th>Assessment</th>
              <th>
                <span className="sr-only">Open report</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.artifact_id}>
                <td>
                  <Link
                    className="table-company"
                    to={`/history/${item.artifact_id}`}
                  >
                    <CompanyLogo ticker={item.ticker} small />
                    <span>
                      <strong>{item.ticker}</strong>
                      <small>{item.title}</small>
                    </span>
                  </Link>
                </td>
                <td className="table-date">{formatDate(item.date)}</td>
                <td className="hide-medium">
                  <span className="subtle">
                    {Array.isArray(item.metadata?.analysts)
                      ? item.metadata.analysts
                          .map(
                            (value) =>
                              ANALYST_LABELS[String(value)] ?? String(value),
                          )
                          .join(" · ")
                      : "Not recorded"}
                  </span>
                </td>
                <td className="hide-medium">
                  <span className="model-label">
                    {String(item.metadata?.llm_provider ?? "Not recorded")}
                  </span>
                </td>
                <td>
                  <span className="depth-label">
                    {String(item.metadata?.research_depth ?? "Not recorded")}
                  </span>
                </td>
                <td className="table-rating">
                  {item.rating ? (
                    <Rating value={item.rating} />
                  ) : (
                    <span className="subtle">{statusLabel(item.status)}</span>
                  )}
                </td>
                <td>
                  <Link
                    className="icon-button"
                    aria-label={`Read ${item.ticker} analysis from ${formatDate(item.date)}`}
                    to={`/history/${item.artifact_id}`}
                  >
                    <Icon name="arrow" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-caption">
        <span>
          {items.length} {full ? "matching analyses" : "recent analyses"}
        </span>
        {full ? (
          <span>All records shown</span>
        ) : (
          <Link className="text-button" to="/history">
            View all research
            <Icon name="arrow" />
          </Link>
        )}
      </div>
    </>
  );
}
