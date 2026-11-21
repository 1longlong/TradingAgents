// FR-TRD-003/004, REQ-WEB-014/021; ADR-003-frontend-stack.md.
import { ui } from "../../i18n/ui";
import type { SimSnapshot } from "../../api/simulationClient";

export function SimBadge({ value }: { value: string }) {
  return (
    <span
      className={`status-tag ${["APPROVED", "completed", "pending"].includes(value) ? "" : "neutral"}`}
    >
      {ui(value)}
    </span>
  );
}
export function Positions({ snapshot }: { snapshot: SimSnapshot }) {
  return (
    <div className="sim-table-wrap">
      <table>
        <caption className="sr-only">{ui("Simulated positions")}</caption>
        <thead>
          <tr>
            {[
              "Instrument",
              "Quantity",
              "Average cost",
              "Last mark",
              "Market value",
              "Realized P&L",
              "Unrealized P&L",
            ].map((label) => (
              <th key={label}>{ui(label)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {snapshot.positions.map((position) => (
            <tr key={position.symbol}>
              <td className="strong-cell">{position.symbol}</td>
              {[
                position.quantity,
                position.average_cost,
                position.market_price,
                position.market_value,
                position.realized_pnl,
                position.unrealized_pnl,
              ].map((value, index) => (
                <td key={index}>{value ?? "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!snapshot.positions.length ? (
        <p className="sim-empty">{ui("No simulated holdings yet.")}</p>
      ) : null}
      {snapshot.valuation_incomplete ? (
        <p className="inline-note">
          {ui(
            "Some holdings have no market mark. Equity valuation is incomplete.",
          )}
        </p>
      ) : null}
    </div>
  );
}
export function SimMetrics({ snapshot }: { snapshot: SimSnapshot }) {
  return (
    <>
      {snapshot.bankrupt ? (
        <p className="field-error" role="alert">
          {ui("Bankrupt")}
        </p>
      ) : null}
      <div className="sim-metrics">
        {[
          ["Cash", snapshot.cash],
          ["Total equity", snapshot.total_equity],
          ["Unrealized P&L", snapshot.unrealized_pnl],
        ].map(([label, value]) => (
          <div className="panel" key={label}>
            <small>{ui(label)}</small>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <details className="disclosure">
        <summary>{ui("Account details")}</summary>
        <dl className="sim-definition-grid">
          {[
            ["Realized P&L", snapshot.realized_pnl],
            ["Total fees", snapshot.total_fees],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{ui(label)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <p className="helper">
          {ui("Version {{version}} · Snapshot at {{time}}", {
            version: snapshot.version,
            time: snapshot.as_of,
          })}
        </p>
      </details>
    </>
  );
}
export const decimalInput = /^\d{1,12}(?:\.\d{1,6})?$/;
export const moneyValid = (value: string) => decimalInput.test(value);
