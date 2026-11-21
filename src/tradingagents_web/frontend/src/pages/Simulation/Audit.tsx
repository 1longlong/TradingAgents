// FR-TRD-004, INV-TRD-003; ADR-001-simulated-trading-system.md: read-only audit.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ui } from "../../i18n/ui";
import {
  getSimulationAudit,
  type SimAuditEvent,
  type SimJob,
} from "../../api/simulationClient";
import { Modal } from "../../components/Modal";

const EVENTS = [
  "DECISION_RECEIVED",
  "RULE_EVALUATED",
  "APPROVAL_POLICY_EVALUATED",
  "DECISION_EVALUATED",
  "HUMAN_APPROVAL_REQUESTED",
  "HUMAN_APPROVAL",
  "DECISION_APPROVED",
  "DECISION_REJECTED",
  "EXECUTION_STARTED",
  "ORDER_EXECUTED",
  "INVARIANT_VIOLATION",
  "BANKRUPT",
  "STATE_LOADED",
  "STATE_SAVED",
  "STATE_RESET",
  "BACKTEST_STARTED",
  "BACKTEST_DAY_STARTED",
  "BACKTEST_DAY_COMPLETED",
  "BACKTEST_COMPLETED",
];
export function SimulationAudit({ jobs }: { jobs: SimJob[] }) {
  const [run, setRun] = useState(""),
    [kind, setKind] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<SimAuditEvent | null>(null);
  const query = useQuery({
    queryKey: ["simulation", "audit", run, kind, offset],
    queryFn: () => getSimulationAudit(run, kind, offset),
    retry: false,
  });
  function download() {
    if (!query.data) return;
    const blob = new Blob([JSON.stringify(query.data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob),
      link = document.createElement("a");
    link.href = url;
    link.download = "simulation-audit-page.json";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className="panel sim-panel">
      <div className="sim-section-heading">
        <div>
          <h2>{ui("Trading audit")}</h2>
        </div>
        <button className="button" disabled={!query.data} onClick={download}>
          {ui("Download this page")}
        </button>
      </div>
      <div className="field-row">
        <div className="form-field">
          <label htmlFor="sim-audit-account">{ui("Audit account")}</label>
          <select
            id="sim-audit-account"
            value={run}
            onChange={(event) => {
              setRun(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">{ui("Interactive account")}</option>
            {jobs.map((job) => (
              <option key={job.run_id} value={job.run_id}>
                {job.parameters.symbol} · {job.run_id}
              </option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="sim-audit-type">{ui("Event type")}</label>
          <select
            id="sim-audit-type"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">{ui("All event types")}</option>
            {EVENTS.map((type) => (
              <option key={type} value={type}>
                {ui(type)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {query.isLoading ? <p role="status">{ui("Loading audit…")}</p> : null}
      {query.isError ? (
        <p role="alert" className="field-error">
          {ui(query.error.message)}
        </p>
      ) : null}
      {query.data ? (
        <>
          <p className="inline-note">
            {query.data.verified
              ? ui("Verified audit · {{count}} matching events", {
                  count: query.data.total,
                })
              : ui("Create an account before inspecting its audit.")}
          </p>
          <div className="sim-table-wrap">
            <table>
              <thead>
                <tr>
                  {["Recorded at", "Event type", "Details"].map((label) => (
                    <th key={label}>{ui(label)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((event) => (
                  <tr key={event.event_id}>
                    <td>{event.timestamp}</td>
                    <td>{ui(event.event_type)}</td>
                    <td>
                      <button
                        className="button ghost"
                        onClick={() => setSelected(event)}
                      >
                        {ui("Inspect event")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!query.data.items.length ? (
            <p className="sim-empty">
              {ui("No audit events match these filters.")}
            </p>
          ) : null}
          <div className="sim-action-row">
            <button
              className="button"
              disabled={offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - 50))}
            >
              {ui("Previous")}
            </button>
            <span>
              {ui("Events {{from}}–{{to}} of {{total}}", {
                from: query.data.total ? offset + 1 : 0,
                to: Math.min(offset + 50, query.data.total),
                total: query.data.total,
              })}
            </span>
            <button
              className="button"
              disabled={offset + 50 >= query.data.total}
              onClick={() => setOffset((value) => value + 50)}
            >
              {ui("Next")}
            </button>
          </div>
        </>
      ) : null}
      <Modal
        open={selected !== null}
        title="Trading audit event"
        onClose={() => setSelected(null)}
      >
        {selected ? (
          <>
            <p>
              {ui(selected.event_type)} · {selected.timestamp}
            </p>
            <dl className="sim-definition-grid">
              {[
                ["Event ID", selected.event_id],
                ["Previous hash", selected.prev_hash],
                ["Entry hash", selected.entry_hash],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{ui(label)}</dt>
                  <dd className="sim-mono">{value}</dd>
                </div>
              ))}
            </dl>
            <pre className="sim-json">
              {JSON.stringify(selected.payload, null, 2)}
            </pre>
          </>
        ) : null}
      </Modal>
    </section>
  );
}
