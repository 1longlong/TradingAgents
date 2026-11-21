// FR-TRD-003/006, INV-TRD-003; ADR-001-simulated-trading-system.md.
import { useRef, useState } from "react";
import { ui } from "../../i18n/ui";
import { Modal } from "../../components/Modal";
import { simulationPost, type SimState } from "../../api/simulationClient";
import { moneyValid, Positions, SimMetrics } from "./shared";

export function SimulationAccount({
  state,
  busy,
  changed,
}: {
  state: SimState;
  busy: boolean;
  changed: () => void;
}) {
  const resetAccount = useRef<string | null>(null);
  const [cash, setCash] = useState("100000.00"),
    [reset, setReset] = useState<number | null>(null),
    [confirmation, setConfirmation] = useState("");
  const [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null);
  async function submit(clear: boolean) {
    if (!moneyValid(cash)) {
      setError("Enter a nonnegative decimal amount.");
      return;
    }
    if (clear && confirmation !== "RESET") {
      setError("Type RESET to confirm.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await simulationPost("/account", {
        initial_cash: cash,
        confirm: clear ? "RESET" : "INITIALIZE",
        ...(clear
          ? {
              expected_version: reset,
              expected_account_id: resetAccount.current,
            }
          : {}),
      });
      setReset(null);
      setConfirmation("");
      changed();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      {state.snapshot ? (
        <>
          <SimMetrics snapshot={state.snapshot} />
          <section className="panel sim-panel">
            <div className="sim-section-heading">
              <div>
                <h2>{ui("Simulated positions")}</h2>
              </div>
              <button
                className="button ghost"
                disabled={busy || saving}
                onClick={() => {
                  setError(null);
                  resetAccount.current = state.account_id;
                  setReset(state.snapshot!.version);
                }}
              >
                {ui("Reset account")}
              </button>
            </div>
            <Positions snapshot={state.snapshot} />
          </section>
        </>
      ) : (
        <section className="panel sim-panel">
          <h2>{ui("Create your simulated account")}</h2>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit(false);
            }}
          >
            <div className="form-field">
              <label htmlFor="sim-initial-cash">{ui("Initial cash")}</label>
              <input
                id="sim-initial-cash"
                inputMode="decimal"
                value={cash}
                onChange={(event) => setCash(event.target.value)}
                required
              />
            </div>
            <button className="button primary" disabled={busy || saving}>
              {ui(saving ? "Saving…" : "Create simulated account")}
            </button>
          </form>
        </section>
      )}
      <details className="panel sim-panel compact-details">
        <summary>{ui("Account rules")}</summary>
        <dl className="sim-definition-grid">
          {[
            ["Hard order limit", state.policy.hard_max_order_notional],
            ["Approval threshold", state.policy.soft_max_order_notional],
            ["Maximum position fraction", state.policy.max_position_fraction],
            ["Maximum quote age (seconds)", state.policy.max_quote_age_seconds],
            ["Fee (basis points)", state.policy.fee_bps],
            ["Minimum fee", state.policy.min_fee],
            ["Approval lifetime (seconds)", state.policy.approval_ttl_seconds],
            [
              "Short selling",
              state.policy.allow_short ? "Enabled" : "Disabled",
            ],
          ].map(([label, value]) => (
            <div key={String(label)}>
              <dt>{ui(label)}</dt>
              <dd>{ui(value)}</dd>
            </div>
          ))}
        </dl>
      </details>
      {error && reset === null ? (
        <p role="alert" className="field-error">
          {ui(error)}
        </p>
      ) : null}
      <Modal
        open={reset !== null}
        title="Reset simulated account?"
        onClose={() => {
          if (!saving) setReset(null);
        }}
      >
        <p>
          {ui(
            "Reset clears simulated holdings and starts with the cash below. The append-only trading audit is retained.",
          )}
        </p>
        <div className="form-field">
          <label htmlFor="sim-reset-cash">{ui("New initial cash")}</label>
          <input
            id="sim-reset-cash"
            inputMode="decimal"
            value={cash}
            onChange={(event) => setCash(event.target.value)}
          />
        </div>
        <div className="form-field">
          <label htmlFor="sim-reset-confirm">
            {ui("Type RESET to confirm.")}
          </label>
          <input
            id="sim-reset-confirm"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
          />
        </div>
        {error ? (
          <p role="alert" className="field-error">
            {ui(error)}
          </p>
        ) : null}
        <div className="modal-actions">
          <button
            className="button"
            disabled={saving}
            onClick={() => setReset(null)}
          >
            {ui("Keep account")}
          </button>
          <button
            className="button primary"
            disabled={saving || busy || confirmation !== "RESET"}
            onClick={() => void submit(true)}
          >
            {ui(saving ? "Saving…" : "Reset account")}
          </button>
        </div>
      </Modal>
    </>
  );
}
