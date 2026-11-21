// FR-TRD-005/006; ADR-001-simulated-trading-system.md: core serial walk-forward.
import { useState } from "react";
import { ui } from "../../i18n/ui";
import {
  simulationPost,
  type ScenarioRow,
  type SimJob,
  type SimJobInput,
} from "../../api/simulationClient";
import { moneyValid, Positions, SimBadge, SimMetrics } from "./shared";

export function validateSimulationJob(input: SimJobInput): string | null {
  if (
    !/^[A-Za-z0-9._^=+-]{1,32}$/.test(input.symbol) ||
    /^\.+$/.test(input.symbol)
  )
    return "Enter a supported instrument symbol.";
  const validDate = (value: string) =>
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value;
  if (
    !validDate(input.start) ||
    !validDate(input.end) ||
    input.start > input.end ||
    (Date.parse(input.end) - Date.parse(input.start)) / 86400000 > 365 ||
    !moneyValid(input.initial_cash)
  )
    return "Check the date range and initial cash.";
  if (input.source === "scenario") {
    const seen = new Set<string>();
    if (!input.rows.length || input.rows.length > 366)
      return "Add between 1 and 366 scenario days.";
    for (const row of input.rows) {
      if (
        !validDate(row.date) ||
        row.date < input.start ||
        row.date > input.end ||
        seen.has(row.date) ||
        !moneyValid(row.price) ||
        Number(row.price) <= 0 ||
        !["BUY", "SELL", "HOLD", "REVIEW"].includes(row.action)
      )
        return "Scenario days need unique in-range dates and positive prices.";
      seen.add(row.date);
    }
  }
  return null;
}
function pastDay(days: number) {
  return new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
}
function nextWeekday(day: string) {
  const value = new Date(`${day}T12:00:00Z`);
  if (Number.isNaN(value.valueOf())) return "";
  value.setUTCDate(value.getUTCDate() + 1);
  while ([0, 6].includes(value.getUTCDay()))
    value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}

export function SimulationBacktests({
  jobs,
  selected,
  busy,
  changed,
  select,
}: {
  jobs: SimJob[];
  selected?: SimJob;
  busy: boolean;
  changed: () => void;
  select: (id: string) => void;
}) {
  const [source, setSource] = useState<"scenario" | "research">("scenario"),
    [symbol, setSymbol] = useState("NVDA"),
    [start, setStart] = useState(pastDay(8)),
    [end, setEnd] = useState(pastDay(1)),
    [cash, setCash] = useState("10000.00");
  const [rows, setRows] = useState<ScenarioRow[]>([
    { date: pastDay(8), action: "BUY", price: "" },
  ]);
  const [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null);
  async function submit(resume?: SimJob) {
    const input: SimJobInput = resume
      ? { ...resume.parameters, resume_id: resume.run_id }
      : {
          source,
          symbol: symbol.trim().toUpperCase(),
          start,
          end,
          initial_cash: cash,
          rows: source === "scenario" ? rows : [],
        };
    const problem = validateSimulationJob(input);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const job = await simulationPost<SimJob>("/jobs", input);
      select(job.run_id);
      changed();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }
  function rowChange(index: number, key: keyof ScenarioRow, value: string) {
    setRows((current) =>
      current.map((row, position) =>
        position === index ? { ...row, [key]: value } : row,
      ),
    );
  }
  return (
    <>
      <div className="sim-two-columns">
        <form
          className="panel sim-panel"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <h2>{ui("Walk-forward simulation")}</h2>

          <div className="form-field">
            <label htmlFor="sim-source">{ui("Decision source")}</label>
            <select
              id="sim-source"
              value={source}
              onChange={(event) =>
                setSource(event.target.value as "scenario" | "research")
              }
            >
              <option value="scenario">{ui("Offline scenario")}</option>
              <option value="research">
                {ui("Research & historical quotes")}
              </option>
            </select>
          </div>
          <div className="field-row">
            <div className="form-field">
              <label htmlFor="sim-symbol">{ui("Instrument")}</label>
              <input
                id="sim-symbol"
                maxLength={32}
                value={symbol}
                onChange={(event) =>
                  setSymbol(event.target.value.toUpperCase())
                }
                required
              />
            </div>
            <div className="form-field">
              <label htmlFor="sim-job-cash">
                {ui("Simulation initial cash")}
              </label>
              <input
                id="sim-job-cash"
                inputMode="decimal"
                value={cash}
                onChange={(event) => setCash(event.target.value)}
                required
              />
            </div>
          </div>
          <div className="field-row">
            <div className="form-field">
              <label htmlFor="sim-start">{ui("Simulation start date")}</label>
              <input
                id="sim-start"
                type="date"
                value={start}
                onChange={(event) => setStart(event.target.value)}
                required
              />
            </div>
            <div className="form-field">
              <label htmlFor="sim-end">{ui("Simulation end date")}</label>
              <input
                id="sim-end"
                type="date"
                value={end}
                max={pastDay(0)}
                onChange={(event) => setEnd(event.target.value)}
                required
              />
            </div>
          </div>
          {source === "scenario" ? (
            <fieldset className="unstyled-fieldset">
              <legend>{ui("Daily scenario inputs")}</legend>
              <p className="helper">
                {ui(
                  "Enter the decisions and prices to replay. Weekends are excluded; weekdays without a quote are skipped.",
                )}
              </p>
              {rows.map((row, index) => (
                <div className="sim-scenario-row" key={index}>
                  <div className="form-field">
                    <label htmlFor={`sim-day-${index}`}>
                      {ui("Scenario date {{index}}", { index: index + 1 })}
                    </label>
                    <input
                      id={`sim-day-${index}`}
                      type="date"
                      value={row.date}
                      onChange={(event) =>
                        rowChange(index, "date", event.target.value)
                      }
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor={`sim-action-${index}`}>
                      {ui("Scenario action {{index}}", { index: index + 1 })}
                    </label>
                    <select
                      id={`sim-action-${index}`}
                      value={row.action}
                      onChange={(event) =>
                        rowChange(index, "action", event.target.value)
                      }
                    >
                      {["BUY", "SELL", "HOLD", "REVIEW"].map((action) => (
                        <option key={action} value={action}>
                          {ui(action)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-field">
                    <label htmlFor={`sim-close-${index}`}>
                      {ui("Closing price {{index}}", { index: index + 1 })}
                    </label>
                    <input
                      id={`sim-close-${index}`}
                      inputMode="decimal"
                      value={row.price}
                      onChange={(event) =>
                        rowChange(index, "price", event.target.value)
                      }
                    />
                  </div>
                  <button
                    className="button ghost"
                    type="button"
                    aria-label={ui("Remove scenario day {{index}}", {
                      index: index + 1,
                    })}
                    onClick={() =>
                      setRows((current) =>
                        current.filter((_, position) => position !== index),
                      )
                    }
                  >
                    {ui("Remove")}
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="button"
                disabled={rows.length >= 366}
                onClick={() =>
                  setRows((current) => [
                    ...current,
                    {
                      date: current.length
                        ? nextWeekday(current[current.length - 1].date || start)
                        : start,
                      action: "HOLD",
                      price: "",
                    },
                  ])
                }
              >
                {ui("Add scenario day")}
              </button>
            </fieldset>
          ) : (
            <p className="inline-note">
              {ui(
                "Research mode calls your configured model and market-data providers for each trading day. It can incur provider charges.",
              )}
            </p>
          )}
          <p className="helper">
            {ui(
              "Each run has a separate account. Approval-required orders remain unexecuted.",
            )}
          </p>
          {error ? (
            <p role="alert" className="field-error">
              {ui(error)}
            </p>
          ) : null}
          <button className="button primary" disabled={busy || saving}>
            {ui(saving ? "Starting…" : "Start simulation")}
          </button>
        </form>
        <section className="panel sim-panel">
          <h2>{ui("Simulation result")}</h2>
          {selected ? (
            <>
              <div className="sim-section-heading">
                <strong className="sim-mono">
                  {selected.parameters.symbol}
                </strong>
                <SimBadge value={selected.status} />
              </div>
              <p>
                {selected.parameters.start} — {selected.parameters.end}
              </p>
              <p className="helper">
                {ui(
                  selected.parameters.source === "scenario"
                    ? "Offline scenario"
                    : "Research & historical quotes",
                )}
              </p>

              {selected.summary ? (
                <dl className="sim-definition-grid">
                  {[
                    ["Days processed", selected.summary.days_processed],
                    ["Simulated fills", selected.summary.executions],
                    ["Rejected decisions", selected.summary.rejections],
                    [
                      "Approval-required decisions",
                      selected.summary.pending_approvals,
                    ],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <dt>{ui(label)}</dt>
                      <dd>{ui(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p role="status">
                  {ui(
                    ["starting", "running"].includes(selected.status)
                      ? "Simulation is running. Its state is saved after each day."
                      : "No completed summary is recorded.",
                  )}
                </p>
              )}
              {selected.summary ? (
                <details className="disclosure">
                  <summary>{ui("Attempt details")}</summary>
                  <p className="helper">
                    {ui(
                      "Summary counts describe this attempt; saved days are skipped on resume.",
                    )}
                  </p>
                  <dl className="sim-definition-grid">
                    {[
                      ["Days skipped", selected.summary.days_skipped],
                      ["No-action decisions", selected.summary.no_actions],
                    ].map(([label, value]) => (
                      <div key={String(label)}>
                        <dt>{ui(label)}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              ) : null}
              {selected.cursor?.last_completed_date ? (
                <p>
                  {ui("Last saved day: {{date}}", {
                    date: selected.cursor.last_completed_date,
                  })}
                </p>
              ) : null}
              {selected.error ? (
                <p className="field-error" role="alert">
                  {ui(selected.error)}
                </p>
              ) : null}
              {["interrupted", "failed"].includes(selected.status) &&
              (!selected.cursor?.last_completed_date ||
                selected.cursor.last_completed_date <
                  selected.parameters.end) ? (
                <button
                  className="button"
                  disabled={busy || saving}
                  onClick={() => void submit(selected)}
                >
                  {ui("Resume saved simulation")}
                </button>
              ) : null}
            </>
          ) : (
            <p className="sim-empty">
              {ui(
                "Start a simulation or open a saved run to inspect its outcome.",
              )}
            </p>
          )}
        </section>
      </div>
      {selected?.snapshot ? (
        <>
          <SimMetrics snapshot={selected.snapshot} />
          <section className="panel sim-panel">
            <h2>{ui("Simulated positions")}</h2>
            <Positions snapshot={selected.snapshot} />
          </section>
        </>
      ) : null}
      <section className="panel sim-panel">
        <h2>{ui("Saved simulations")}</h2>
        {jobs.length >= 100 ? (
          <p className="helper">
            {ui("The most recent 100 simulations are shown.")}
          </p>
        ) : null}
        <div className="sim-table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  "Instrument",
                  "Decision source",
                  "Date range",
                  "Status",
                  "Open",
                ].map((label) => (
                  <th key={label}>{ui(label)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.run_id}>
                  <td>{job.parameters.symbol}</td>
                  <td>
                    {ui(
                      job.parameters.source === "scenario"
                        ? "Offline scenario"
                        : "Research & historical quotes",
                    )}
                  </td>
                  <td>
                    {job.parameters.start} — {job.parameters.end}
                  </td>
                  <td>
                    <SimBadge value={job.status} />
                  </td>
                  <td>
                    <button
                      className="button ghost"
                      onClick={() => select(job.run_id)}
                    >
                      {ui("Open")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!jobs.length ? (
          <p className="sim-empty">{ui("No saved simulations.")}</p>
        ) : null}
      </section>
    </>
  );
}
