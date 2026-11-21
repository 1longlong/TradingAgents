// REQ-WEB-001/003/013/014, FR-DDT-004, ADR-001/007: core-backed per-run controls.
import { ui, useUILanguage } from "../i18n/ui";
import {
  DEBATE_FIELDS,
  readDebatePolicy,
  type DebateFieldError,
  type DebatePolicy,
} from "../utils/debateSettings";

export function DebateSettings({
  policy,
  riskRounds,
  locks,
  errors,
  onPolicy,
  onRisk,
}: {
  policy: DebatePolicy;
  riskRounds: number;
  locks: Record<string, boolean>;
  errors: DebateFieldError[];
  onPolicy: (value: DebatePolicy) => void;
  onRisk: (value: number) => void;
}) {
  useUILanguage();
  function feedback(id: string) {
    const error = errors.find(([key]) => key === id);
    return error ? (
      <small className="field-error" id={`${id}-error`}>
        {ui(error[1], error[2])}
      </small>
    ) : null;
  }
  function attrs(id: string) {
    return errors.some(([key]) => key === id)
      ? { "aria-invalid": true as const, "aria-describedby": `${id}-error` }
      : {};
  }
  return (
    <details className="debate-settings advanced-options">
      <summary>{ui("Debate rules & budgets")}</summary>
      <div className="form-field">
        <label htmlFor="debate-enabled">{ui("Debate mode")}</label>
        <select
          id="debate-enabled"
          value={policy.enabled ? "dynamic" : "fixed"}
          onChange={(event) =>
            onPolicy({ ...policy, enabled: event.target.value === "dynamic" })
          }
        >
          <option value="dynamic">{ui("Dynamic termination")}</option>
          <option value="fixed">{ui("Fixed-round baseline")}</option>
        </select>
        <small>
          {policy.enabled
            ? ui(
                "Continue while new evidence or meaningful disagreement warrants another round.",
              )
            : ui(
                "Fixed mode uses the round cap; data-quality and budget safeguards remain active.",
              )}
        </small>
      </div>
      {(["rounds", "thresholds", "budget"] as const).map((group) => (
        <fieldset className="debate-fieldset" key={group}>
          <legend>
            {ui(
              group === "rounds"
                ? "Round limits"
                : group === "thresholds"
                  ? "Dynamic termination thresholds"
                  : "Debate budgets & reserves",
            )}
          </legend>
          <div className="debate-control-grid">
            {DEBATE_FIELDS.filter((field) => field.group === group).map(
              (field) => {
                const id = `debate-${field.key}`;
                const locked =
                  field.key === "max_debate_rounds" && locks.max_debate_rounds;
                return (
                  <div className="form-field" key={field.key}>
                    <label htmlFor={id}>{ui(field.label)}</label>
                    <input
                      id={id}
                      type="number"
                      min={field.min}
                      max={field.max}
                      step={field.integer ? 1 : "any"}
                      value={policy[field.key]}
                      disabled={locked}
                      {...attrs(id)}
                      onChange={(event) =>
                        onPolicy({
                          ...policy,
                          [field.key]: Number(event.target.value),
                        })
                      }
                    />
                    {locked ? (
                      <small>
                        {ui("Configured by the server environment.")}
                      </small>
                    ) : null}
                    {feedback(id)}
                  </div>
                );
              },
            )}
            {group === "rounds" ? (
              <div className="form-field">
                <label htmlFor="debate-risk-rounds">
                  {ui("Risk discussion rounds")}
                </label>
                <input
                  id="debate-risk-rounds"
                  type="number"
                  min={1}
                  step={1}
                  value={riskRounds}
                  disabled={locks.max_risk_discuss_rounds}
                  {...attrs("debate-risk-rounds")}
                  onChange={(event) => onRisk(Number(event.target.value))}
                />
                {locks.max_risk_discuss_rounds ? (
                  <small>{ui("Configured by the server environment.")}</small>
                ) : null}
                {feedback("debate-risk-rounds")}
              </div>
            ) : null}
          </div>
          {group === "thresholds" && !policy.enabled ? (
            <small>{ui("These thresholds take effect in dynamic mode.")}</small>
          ) : null}
          {group === "budget" ? (
            <small>
              {ui(
                "Budgets cover the research debate. Admission uses estimates; this is not a monetary limit for the full analysis.",
              )}
            </small>
          ) : null}
        </fieldset>
      ))}
      <p className="helper">
        {ui("Checkpoint recovery requires matching debate settings.")}
      </p>
    </details>
  );
}

export function DebatePolicySummary({
  policy: raw,
  riskRounds,
  title = "Effective debate settings",
}: {
  policy: unknown;
  riskRounds?: number | null;
  title?: string;
}) {
  useUILanguage();
  const policy = readDebatePolicy(raw);
  if (!policy) return null;
  return (
    <details className="debate-policy-summary">
      <summary>
        {ui(title)} ·{" "}
        {ui(policy.enabled ? "Dynamic termination" : "Fixed-round baseline")} ·{" "}
        {ui("{{count}} debate rounds", { count: policy.max_debate_rounds })}
      </summary>
      <dl>
        {[
          [
            "Debate mode",
            policy.enabled ? "Dynamic termination" : "Fixed-round baseline",
          ],
          ...DEBATE_FIELDS.map((field) => [field.label, policy[field.key]]),
          ["Risk discussion rounds", riskRounds ?? "Not recorded"],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{ui(label)}</dt>
            <dd>{ui(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
