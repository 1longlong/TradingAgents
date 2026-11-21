// FR-TRD-001/002/004, INV-TRD-001/002; ADR-001-simulated-trading-system.md.
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ui } from "../../i18n/ui";
import {
  getSimulationReports,
  simulationPost,
  type SimPending,
  type SimState,
  type SimTransaction,
} from "../../api/simulationClient";
import { moneyValid, SimBadge } from "./shared";

function Approval({
  item,
  version,
  accountId,
  busy,
  changed,
}: {
  item: SimPending;
  version: number;
  accountId: string | null;
  busy: boolean;
  changed: () => void;
}) {
  const [approver, setApprover] = useState(""),
    [reason, setReason] = useState(""),
    [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null);
  async function decide(approved: boolean) {
    if (!approver.trim() || !reason.trim()) {
      setError("Provide your name and an approval reason.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await simulationPost(
        `/approvals/${encodeURIComponent(item.request_id)}`,
        {
          approved,
          approver: approver.trim(),
          reason: reason.trim(),
          expected_version: version,
          expected_account_id: accountId,
        },
      );
      changed();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      changed();
    } finally {
      setSaving(false);
    }
  }
  const order = item.evaluation.order_intent;
  return (
    <article className="sim-approval">
      <div className="sim-section-heading">
        <h3>{item.evaluation.decision.symbol}</h3>
        <SimBadge value={item.state} />
      </div>
      {order ? (
        <p className="sim-order-line">
          {ui(order.side)} · {order.quantity} × {order.price} · {ui("Fee")}:{" "}
          {order.fee}
        </p>
      ) : null}
      <p className="helper">
        {ui("Expires at {{time}}", { time: item.request.expires_at })}
      </p>
      <div className="field-row">
        <div className="form-field">
          <label htmlFor={`approver-${item.request_id}`}>
            {ui("Approver name")}
          </label>
          <input
            id={`approver-${item.request_id}`}
            value={approver}
            onChange={(event) => setApprover(event.target.value)}
            maxLength={120}
          />
        </div>
        <div className="form-field">
          <label htmlFor={`reason-${item.request_id}`}>{ui("Reason")}</label>
          <input
            id={`reason-${item.request_id}`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={1000}
          />
        </div>
      </div>
      {error ? (
        <p role="alert" className="field-error">
          {ui(error)}
        </p>
      ) : null}
      <div className="sim-action-row">
        <button
          className="button"
          disabled={busy || saving || item.state !== "pending"}
          onClick={() => void decide(false)}
        >
          {ui("Reject decision")}
        </button>
        <button
          className="button primary"
          disabled={busy || saving || item.state !== "pending"}
          onClick={() => void decide(true)}
        >
          {ui(saving ? "Saving…" : "Approve & simulate")}
        </button>
      </div>
      {item.state !== "pending" ? (
        <p className="inline-note">
          {ui(
            "This approval can no longer execute. Evaluate the report again with a fresh quote.",
          )}
        </p>
      ) : null}
    </article>
  );
}
export function SimulationDecisions({
  state,
  busy,
  changed,
}: {
  state: SimState;
  busy: boolean;
  changed: () => void;
}) {
  const reports = useQuery({
    queryKey: ["simulation", "reports"],
    queryFn: getSimulationReports,
    retry: false,
  });
  const [artifact, setArtifact] = useState(""),
    [price, setPrice] = useState(""),
    [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 16));
  const [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null),
    [result, setResult] = useState<SimTransaction | null>(null);
  const attempt = useRef<Record<string, unknown> | null>(null);
  function edit() {
    attempt.current = null;
    setResult(null);
  }
  async function submit() {
    if (!artifact || !moneyValid(price) || Number(price) <= 0 || !asOf) {
      setError("Choose a report, a positive scenario price and a quote time.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      attempt.current ??= {
        client_request_id: crypto.randomUUID(),
        artifact_id: artifact,
        quote_price: price,
        quote_as_of: new Date(asOf + "Z").toISOString(),
        expected_version: state.snapshot?.version,
        expected_account_id: state.account_id,
      };
      const value = await simulationPost<SimTransaction>(
        "/decisions",
        attempt.current,
      );
      setResult(value);
      changed();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <div className="sim-two-columns">
        <section className="panel sim-panel">
          <h2>{ui("Evaluate a report")}</h2>
          <p>
            {ui(
              "Quantity comes from deterministic sizing. Approved decisions may fill immediately; larger orders wait for your approval.",
            )}
          </p>
          {!state.initialized ? (
            <p className="inline-note">
              {ui("Create a simulated account first.")}
            </p>
          ) : null}
          {reports.isError ? (
            <p role="alert" className="field-error">
              {ui("Completed reports could not be loaded.")}
            </p>
          ) : null}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="form-field">
              <label htmlFor="sim-report">
                {ui("Completed analysis report")}
              </label>
              <select
                id="sim-report"
                value={artifact}
                onChange={(event) => {
                  setArtifact(event.target.value);
                  edit();
                }}
              >
                <option value="">{ui("Choose a completed report")}</option>
                {reports.data?.items.map((item) => (
                  <option key={item.artifact_id} value={item.artifact_id}>
                    {item.ticker} · {item.date} · {item.rating ?? "REVIEW"}
                  </option>
                ))}
              </select>
            </div>
            <div className="field-row">
              <div className="form-field">
                <label htmlFor="sim-price">{ui("Scenario price")}</label>
                <input
                  id="sim-price"
                  inputMode="decimal"
                  value={price}
                  onChange={(event) => {
                    setPrice(event.target.value);
                    edit();
                  }}
                  required
                />
              </div>
              <div className="form-field">
                <label htmlFor="sim-quote-time">
                  {ui("Scenario quote time (UTC)")}
                </label>
                <input
                  id="sim-quote-time"
                  type="datetime-local"
                  value={asOf}
                  onChange={(event) => {
                    setAsOf(event.target.value);
                    edit();
                  }}
                  required
                />
              </div>
            </div>
            <p className="helper">
              {ui(
                "This is a user-supplied simulation quote, not a live market feed. Its timestamp must satisfy the account freshness rule.",
              )}
            </p>
            {error ? (
              <p role="alert" className="field-error">
                {ui(error)}
              </p>
            ) : null}
            <button
              className="button primary"
              disabled={
                !state.initialized ||
                busy ||
                saving ||
                !reports.data?.items.length
              }
            >
              {ui(saving ? "Evaluating…" : "Evaluate & simulate")}
            </button>
          </form>
        </section>
        <section className="panel sim-panel">
          <h2>{ui("Evaluation result")}</h2>
          {result ? (
            <>
              <SimBadge value={result.result.evaluation.status} />
              <p>
                {result.ticker} · {ui(result.result.evaluation.decision.action)}
              </p>
              {result.result.evaluation.order_intent ? (
                <dl className="sim-definition-grid">
                  {Object.entries(result.result.evaluation.order_intent)
                    .filter(([key]) =>
                      ["quantity", "price", "notional", "fee"].includes(key),
                    )
                    .map(([key, value]) => (
                      <div key={key}>
                        <dt>
                          {ui(
                            (
                              {
                                quantity: "Quantity",
                                price: "Scenario price",
                                notional: "Order value",
                                fee: "Fee",
                              } as Record<string, string>
                            )[key] ?? key,
                          )}
                        </dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                </dl>
              ) : null}
              <details className="disclosure">
                <summary>{ui("Rule checks")}</summary>
                <ul className="sim-rule-list">
                  {result.result.evaluation.rule_results.map((rule) => (
                    <li key={rule.rule_id}>
                      <strong>{rule.rule_id}</strong>
                      <span>{ui(rule.passed ? "Passed" : "Rejected")}</span>
                      {rule.reason ? <small>{rule.reason}</small> : null}
                    </li>
                  ))}
                </ul>
              </details>
              {result.result.evaluation.reasons.map((reason, index) => (
                <p className="inline-note" key={index}>
                  {reason}
                </p>
              ))}
            </>
          ) : (
            <p className="sim-empty">
              {ui(
                "Choose research and a scenario quote to see the deterministic verdict.",
              )}
            </p>
          )}
        </section>
      </div>
      <section className="panel sim-panel">
        <div className="sim-section-heading">
          <h2>{ui("Human approvals")}</h2>
        </div>

        {state.pending.length ? (
          state.pending.map((item) => (
            <Approval
              key={item.request_id}
              item={item}
              version={state.snapshot!.version}
              accountId={state.account_id}
              busy={busy}
              changed={changed}
            />
          ))
        ) : (
          <p className="sim-empty">
            {ui("No pending approvals in this server session.")}
          </p>
        )}
      </section>
      <details className="panel sim-panel compact-details">
        <summary>{ui("Decision receipts")}</summary>
        <div className="sim-table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  "Instrument",
                  "Recorded at",
                  "Decision",
                  "Status",
                  "Order ID",
                ].map((label) => (
                  <th key={label}>{ui(label)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {state.transactions.map((item) => (
                <tr key={item.id}>
                  <td>{item.ticker}</td>
                  <td>{item.created_at}</td>
                  <td>{ui(item.result.evaluation.decision.action)}</td>
                  <td>
                    <SimBadge value={item.result.evaluation.status} />
                  </td>
                  <td>{item.result.execution?.order_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!state.transactions.length ? (
          <p className="sim-empty">{ui("No simulated decisions recorded.")}</p>
        ) : null}
      </details>
    </>
  );
}
