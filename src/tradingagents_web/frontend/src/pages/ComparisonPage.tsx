import { ui, useUILanguage } from "../i18n/ui";
// NFR-CMP-001/002/003, ADR-002/003, INV-9: the core owns replay and pairing.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  comparisonDownload,
  getComparison,
  getComparisons,
  number,
  text,
} from "../api/auditClient";
import { Icon } from "../components/Icon";
import { AuditBadge } from "./AuditPage";

export function ComparisonPage() {
  useUILanguage();
  const [selected, setSelected] = useState("D"),
    [mismatch, setMismatch] = useState(false);
  const catalog = useQuery({
    queryKey: ["comparisons", "catalog"],
    queryFn: getComparisons,
  });
  const cases = catalog.data?.cases ?? [],
    current = cases.find((row) => row.case_id === selected);
  const dynamicId = mismatch
    ? (cases.find((row) => row.case_id !== selected)?.case_id ?? selected)
    : selected;
  const replay = useQuery({
    queryKey: ["comparisons", selected, dynamicId],
    queryFn: () => getComparison(selected, dynamicId),
    enabled: Boolean(current),
    retry: false,
  });
  const result = replay.isError || replay.isFetching ? undefined : replay.data;
  const pending = catalog.isLoading || replay.isFetching;
  const identity = current?.identity ?? {};
  const maximum = Math.max(
    1,
    number(result?.fixed.debate_rounds) ?? 0,
    number(result?.dynamic.debate_rounds) ?? 0,
  );
  return (
    <>
      <section className="page-header">
        <div>
          <h1>{ui("Policy comparison")}</h1>
          <p className="page-description">
            {ui("Preset cases only · fixed rounds vs dynamic termination")}
          </p>
        </div>
        <div className="page-header-actions">
          {result ? (
            <a
              className="button ghost"
              href={comparisonDownload(selected, dynamicId)}
            >
              <Icon name="download" />
              {ui("Export comparison")}
            </a>
          ) : (
            <button className="button ghost" disabled>
              <Icon name="download" />
              {ui("Export comparison")}
            </button>
          )}
          <button
            className="button primary"
            disabled={!current || pending}
            onClick={() => void replay.refetch()}
          >
            <Icon name={pending ? "activity" : "refresh"} />
            {pending
              ? ui("Replaying fixtures…")
              : ui("Replay scripted fixtures")}
          </button>
        </div>
      </section>
      {catalog.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>{ui("Comparison catalog unavailable")}</strong>
          <p>{ui(catalog.error.message)}</p>
        </div>
      ) : (
        <>
          <div className="audit-toolbar">
            <label className="audit-scenario">
              {ui("Inspect case")}
              <select
                aria-label={ui("Inspect case")}
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
              >
                {cases.map((row) => (
                  <option key={row.case_id} value={row.case_id}>
                    {ui(row.case_id)}
                    {ui(" · ")}
                    {ui(row.title)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <details className="panel audit-card compact-details pairing-card">
            <summary>{ui("Pairing details")}</summary>
            <label className="audit-scenario">
              {ui("Pairing check")}
              <select
                aria-label={ui("Pairing check")}
                value={mismatch ? "mismatch" : "matched"}
                onChange={(event) =>
                  setMismatch(event.target.value === "mismatch")
                }
              >
                <option value="matched">{ui("Matching case identity")}</option>
                <option value="mismatch">
                  {ui("Different scripted case identity")}
                </option>
              </select>
            </label>

            <div className="audit-identity-grid">
              {[
                ["Ticker", "ticker"],
                ["Target date", "target_date"],
                ["Evidence snapshot", "evidence_snapshot_id"],
                ["Policy version", "policy_version"],
              ].map(([label, key]) => (
                <div key={key}>
                  <small>{ui(label)}</small>
                  <code>{text(identity[key])}</code>
                </div>
              ))}
            </div>
            <p className="inline-note">
              {ui(
                "Both strategies must match ticker, date, evidence snapshot and policy version. An identity mismatch blocks pairing.",
              )}
              {mismatch
                ? ui(
                    " Fixed uses case {{value0}}; dynamic uses case {{value1}}.",
                    { value0: selected, value1: dynamicId },
                  )
                : ui("")}
            </p>
          </details>
          {pending ? (
            <div className="report-state-banner" role="status">
              <Icon name="activity" />
              <div>
                <strong>{ui("Replaying local scripted fixtures")}</strong>
                <p>
                  {ui(
                    "The server calls the existing deterministic replay. No model or market-data request is made.",
                  )}
                </p>
              </div>
            </div>
          ) : replay.isError ? (
            <div className="audit-verdict is-blocked" role="alert">
              <Icon name="warning" />
              <div>
                <h2>{ui("Comparison blocked.")}</h2>
                <p>{ui(replay.error.message)}</p>
                <span className="audit-code">
                  {ui("No comparative result or export is available.")}
                </span>
              </div>
            </div>
          ) : null}
          {result ? (
            <>
              <div className="comparison-strategies">
                {(["fixed", "dynamic"] as const).map((key) => {
                  const row = result[key],
                    rounds = number(row.debate_rounds);
                  return (
                    <section
                      className={`panel audit-card ${key === "dynamic" ? "strategy-dynamic" : ""}`}
                      key={key}
                    >
                      <div className="audit-section-head">
                        <h2>
                          {key === "fixed"
                            ? ui("Fixed-round baseline")
                            : ui("Dynamic termination")}
                        </h2>
                        <AuditBadge
                          value={
                            row.early_stopped === true
                              ? "Early stop"
                              : "No early stop"
                          }
                          tone={row.early_stopped === true ? "good" : ""}
                        />
                      </div>
                      <div className="strategy-rounds">
                        <strong>{ui(text(rounds))}</strong>
                        <span>{ui("scripted rounds")}</span>
                      </div>
                      {rounds != null ? (
                        <div
                          className="comparison-bar"
                          role="img"
                          aria-label={ui(
                            "{{value0}} completed {{value1}} scripted rounds",
                            { value0: key, value1: rounds },
                          )}
                        >
                          <span
                            style={{ width: `${(rounds / maximum) * 100}%` }}
                          />
                        </div>
                      ) : null}
                      <dl className="audit-key-values">
                        {[
                          ["Scripted model calls", row.llm_calls],
                          ["Estimated tokens", row.total_tokens],
                          ["Stop reason", row.stop_reason],
                        ].map(([label, value]) => (
                          <div key={String(label)}>
                            <dt>{ui(String(label))}</dt>
                            <dd>{ui(text(value))}</dd>
                          </div>
                        ))}
                      </dl>
                    </section>
                  );
                })}
              </div>
              <details className="panel audit-card compact-details">
                <summary>{ui("Human scoring & policy details")}</summary>

                <p>
                  {ui(
                    "Source attribution, reasoning clarity, evidence groundedness and decision auditability require actual human scoring. This replay assigns no human score.",
                  )}
                </p>
                <div className="rubric-grid">
                  {result.rubric_dimensions.map((label) => (
                    <div key={label}>
                      <span>{ui(label.replaceAll("_", " "))}</span>
                      <AuditBadge value="Pending" />
                    </div>
                  ))}
                </div>
                <p className="inline-note">
                  {ui("Policy version")}
                  {ui(" ")}
                  {ui(
                    text(
                      result.policy.policy_version ??
                        result.identity.policy_version,
                    ),
                  )}
                  {ui(" ")}
                  {ui("· max rounds ")}
                  {ui(text(result.policy.max_debate_rounds))}
                  {ui(". Estimated usage describes scripted execution only.")}
                </p>
              </details>
              <p className="inline-note">
                {current?.role === "regression"
                  ? ui(
                      "Input exhaustion is a regression case, not evidence of policy-driven early stopping.",
                    )
                  : ui(
                      "Scripted replay only; profitability, real cost and latency are not measured.",
                    )}
              </p>
            </>
          ) : null}
        </>
      )}
    </>
  );
}
