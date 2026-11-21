import { ui, uiHistoryTitle, useUILanguage } from "../i18n/ui";
// REQ-WEB-010, ADR-003: present only recorded history metadata.
import { Link } from "react-router-dom";
import type { HistoryItem } from "../api/client";
import { CompanyLogo, Rating } from "./Research";
import { Icon } from "./Icon";
import { formatDate, statusLabel } from "../utils/workspace";
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
  useUILanguage();
  return (
    <div className="history-controls">
      <label className="filter-input">
        <Icon name="search" />
        <span className="sr-only">{ui("Filter analyses by ticker")}</span>
        <input
          type="search"
          placeholder={ui("Search symbol...")}
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
      </label>
      <label>
        <span className="sr-only">{ui("Filter by status")}</span>
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
              {ui(label)}
            </option>
          ))}
        </select>
      </label>
      {onClear ? (
        <button
          className="icon-button"
          aria-label={ui("Clear filters")}
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
  useUILanguage();
  if (!items.length)
    return (
      <div className="panel empty-state">
        <Icon name="search" />
        <strong>{ui("No matching research")}</strong>
        <p>{ui("Try another symbol or clear the current filters.")}</p>
      </div>
    );
  return (
    <>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">
            {ui("Analysis history. Open a row to read the report.")}
          </caption>
          <thead>
            <tr>
              <th>{ui("Instrument")}</th>
              <th aria-sort={descending ? "descending" : "ascending"}>
                <button onClick={onSort}>
                  {ui("Analysis date")}
                  <Icon name="sort" />
                </button>
              </th>
              <th>{ui("Assessment")}</th>
              <th>
                <span className="sr-only">{ui("Open report")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.artifact_id}>
                <td>
                  <div className="table-company">
                    <CompanyLogo ticker={item.ticker} small />
                    <span>
                      <strong>{item.ticker}</strong>
                      <small>{uiHistoryTitle(item.title, item.ticker)}</small>
                    </span>
                  </div>
                </td>
                <td className="table-date">{ui(formatDate(item.date))}</td>
                <td className="table-rating">
                  {item.rating ? (
                    <Rating value={item.rating} />
                  ) : (
                    <span className="subtle">
                      {ui(statusLabel(item.status))}
                    </span>
                  )}
                </td>
                <td>
                  <Link
                    className="icon-button"
                    aria-label={ui("Read {{value0}} analysis from {{value1}}", {
                      value0: item.ticker,
                      value1: formatDate(item.date),
                    })}
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
          {items.length}{" "}
          {full ? ui("matching analyses") : ui("recent analyses")}
        </span>
        {!full ? (
          <Link className="text-button" to="/history">
            {ui("View all research")}
            <Icon name="arrow" />
          </Link>
        ) : null}
      </div>
    </>
  );
}
