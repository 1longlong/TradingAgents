// REQ-WEB-007/011/021, INV-WEB-014, ADR-007-run-controls.md: observed work, never an ETA.
import { ui, useUILanguage } from "../../i18n/ui";
import type { BacktestSnapshot } from "../../api/backtestClient";
import { Icon } from "../../components/Icon";
import { formatDate } from "../../utils/workspace";

export function BacktestProgress({
  snapshot,
  offset,
  onPage,
}: {
  snapshot: BacktestSnapshot;
  offset?: number;
  onPage: (offset: number | undefined) => void;
}) {
  useUILanguage();
  const p = snapshot.progress;
  const running = ["starting", "running"].includes(snapshot.status);
  if (!p || (!running && !p.observed)) return null;
  const phases: Record<string, string> = {
    preparing: "Preparing models",
    analyzing: "Analyzing",
    settling: "Settling outcomes",
    summarizing: "Summarizing results",
    completed: "Completed",
    failed: "Failed",
  };
  const statuses: Record<string, string> = {
    pending: "Pending",
    running: "Analyzing",
    completed: "Completed",
    failed: "Failed",
    skipped: "Skipped",
    interrupted: "Interrupted",
  };
  return (
    <section
      className="panel backtest-progress"
      aria-label={ui("Backtest progress")}
    >
      <div className="backtest-progress-heading">
        <h2>{ui("Backtest progress")}</h2>
        <span className="subtle">
          {ui("Elapsed")} ·{" "}
          {ui("{{value0}}s", { value0: Math.floor(p.elapsed_seconds) })}
        </span>
      </div>
      <div
        className="backtest-current"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <Icon
          name={
            running
              ? "activity"
              : snapshot.status === "failed"
                ? "warning"
                : "checkCircle"
          }
        />
        <strong>{ui(phases[p.phase] ?? p.phase)}</strong>
        {p.current_ticker ? (
          <span>
            {p.current_ticker}
            {p.current_date ? ` · ${formatDate(p.current_date)}` : ""}
          </span>
        ) : null}
      </div>
      <div className="backtest-progress-count">
        <span>
          {ui("{{done}} / {{total}} analyses processed", {
            done: p.processed,
            total: p.total,
          })}
        </span>
        <span>
          {p.failed ? ui("{{count}} failed", { count: p.failed }) : null}
          {p.failed && p.skipped ? " · " : ""}
          {p.skipped ? ui("{{count}} skipped", { count: p.skipped }) : null}
        </span>
      </div>
      <progress
        max={Math.max(1, p.total)}
        value={p.processed}
        aria-label={ui("Analysis dates processed")}
      />
      {p.phase === "settling" ? (
        <p className="helper">
          {ui(
            "All analysis dates processed. Settling outcomes {{done}} / {{total}}.",
            {
              done: p.settlements_completed + p.settlements_failed,
              total: p.settlements_total,
            },
          )}
        </p>
      ) : null}
      <div className="table-wrap">
        <table>
          <caption className="sr-only">
            {ui("Per-date analysis progress")}
          </caption>
          <thead>
            <tr>
              <th>{ui("Instrument")}</th>
              <th>{ui("Analysis date")}</th>
              <th>{ui("Status")}</th>
              <th>{ui("Elapsed")}</th>
            </tr>
          </thead>
          <tbody>
            {p.cells.map((cell) => (
              <tr
                key={`${cell.ticker}/${cell.date}`}
                className={
                  cell.status === "running" ? "backtest-active-date" : ""
                }
              >
                <td className="strong-cell">{cell.ticker}</td>
                <td>{formatDate(cell.date)}</td>
                <td>
                  <span className={`backtest-date-status ${cell.status}`}>
                    {cell.status === "running" ? (
                      <Icon name="activity" />
                    ) : null}
                    {ui(statuses[cell.status] ?? cell.status)}
                  </span>
                </td>
                <td>
                  {cell.elapsed_seconds == null
                    ? "—"
                    : ui("{{value0}}s", {
                        value0: Math.floor(cell.elapsed_seconds),
                      })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {p.total > p.limit ? (
        <div className="backtest-progress-pages">
          <button
            className="button ghost"
            disabled={p.offset === 0}
            onClick={() => onPage(Math.max(0, p.offset - p.limit))}
          >
            {ui("Previous")}
          </button>
          <span className="subtle">
            {p.offset + 1}–{Math.min(p.offset + p.limit, p.total)} / {p.total}
          </span>
          <button
            className="button ghost"
            disabled={p.offset + p.limit >= p.total}
            onClick={() => onPage(p.offset + p.limit)}
          >
            {ui("Next")}
          </button>
          {offset !== undefined && running ? (
            <button className="text-button" onClick={() => onPage(undefined)}>
              {ui("Follow current date")}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
