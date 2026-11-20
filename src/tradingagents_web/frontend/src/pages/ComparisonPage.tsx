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
          <p className="eyebrow">SAME CASE. TWO POLICIES.</p>
          <h1>Policy comparison</h1>
          <p className="page-description">
            Inspect the existing fixed-round vs dynamic offline replay. This is
            separate from financial backtesting.
          </p>
        </div>
        <div className="page-header-actions">
          {result ? (
            <a
              className="button ghost"
              href={comparisonDownload(selected, dynamicId)}
            >
              <Icon name="download" />
              Export comparison
            </a>
          ) : (
            <button className="button ghost" disabled>
              <Icon name="download" />
              Export comparison
            </button>
          )}
          <button
            className="button primary"
            disabled={!current || pending}
            onClick={() => void replay.refetch()}
          >
            <Icon name={pending ? "activity" : "refresh"} />
            {pending ? "Replaying fixtures…" : "Replay scripted fixtures"}
          </button>
        </div>
      </section>
      <div className="comparison-intro panel">
        <span>
          <Icon name="layers" />
        </span>
        <div>
          <h2>A controlled comparison, not a live benchmark.</h2>
          <p>
            {catalog.data
              ? `${catalog.data.representative_cases} representative scripted cases plus ${catalog.data.regression_cases} input-exhaustion regression.`
              : "Reading scripted case coverage."}{" "}
            Provider costs, latency savings and profitability are not measured
            here.
          </p>
        </div>
        <AuditBadge value="Scripted / estimated" tone="warn" />
      </div>
      {catalog.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>Comparison catalog unavailable</strong>
          <p>{catalog.error.message}</p>
        </div>
      ) : (
        <>
          <div className="audit-toolbar">
            <label className="audit-scenario">
              Inspect case
              <select
                aria-label="Inspect case"
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
              >
                {cases.map((row) => (
                  <option key={row.case_id} value={row.case_id}>
                    {row.case_id} · {row.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="audit-scenario">
              Pairing check
              <select
                aria-label="Pairing check"
                value={mismatch ? "mismatch" : "matched"}
                onChange={(event) =>
                  setMismatch(event.target.value === "mismatch")
                }
              >
                <option value="matched">Matching case identity</option>
                <option value="mismatch">
                  Different scripted case identity
                </option>
              </select>
            </label>
          </div>
          <section className="panel audit-card pairing-card">
            <p className="eyebrow">FOUR-PART IDENTITY CHECK</p>
            <div className="audit-identity-grid">
              {[
                ["Ticker", "ticker"],
                ["Target date", "target_date"],
                ["Evidence snapshot", "evidence_snapshot_id"],
                ["Policy version", "policy_version"],
              ].map(([label, key]) => (
                <div key={key}>
                  <small>{label}</small>
                  <code>{text(identity[key])}</code>
                </div>
              ))}
            </div>
            <p className="inline-note">
              Both strategies must match ticker, date, evidence snapshot and
              policy version. An identity mismatch blocks pairing.
              {mismatch
                ? ` Fixed uses case ${selected}; dynamic uses case ${dynamicId}.`
                : ""}
            </p>
          </section>
          {pending ? (
            <div className="report-state-banner" role="status">
              <Icon name="activity" />
              <div>
                <strong>Replaying local scripted fixtures</strong>
                <p>
                  The server calls the existing deterministic replay. No model
                  or market-data request is made.
                </p>
              </div>
            </div>
          ) : replay.isError ? (
            <div className="audit-verdict is-blocked" role="alert">
              <Icon name="warning" />
              <div>
                <h2>Comparison blocked.</h2>
                <p>{replay.error.message}</p>
                <span className="audit-code">
                  No comparative result or export is available.
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
                            ? "Fixed-round baseline"
                            : "Dynamic termination"}
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
                        <strong>{text(rounds)}</strong>
                        <span>scripted rounds</span>
                      </div>
                      {rounds != null ? (
                        <div
                          className="comparison-bar"
                          role="img"
                          aria-label={`${key} completed ${rounds} scripted rounds`}
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
                            <dt>{String(label)}</dt>
                            <dd>{text(value)}</dd>
                          </div>
                        ))}
                      </dl>
                    </section>
                  );
                })}
              </div>
              <div className="audit-two-col">
                <section className="panel audit-card">
                  <div className="audit-section-head">
                    <div>
                      <p className="eyebrow">CASE COVERAGE</p>
                      <h2>Inspect why the policy behaves differently.</h2>
                    </div>
                  </div>
                  <div className="comparison-case-list">
                    {cases.map((row) => (
                      <button
                        className={`comparison-case ${row.case_id === selected ? "selected" : ""}`}
                        key={row.case_id}
                        aria-pressed={row.case_id === selected}
                        onClick={() => setSelected(row.case_id)}
                      >
                        <span>{row.case_id}</span>
                        <div>
                          <strong>{row.title}</strong>
                          <small>
                            {row.case_id === selected
                              ? `${text(result.fixed.debate_rounds)} → ${text(result.dynamic.debate_rounds)} rounds · ${text(result.dynamic.stop_reason)}`
                              : row.role}
                          </small>
                        </div>
                        <Icon name="arrow" />
                      </button>
                    ))}
                  </div>
                  <p>
                    {current?.role === "regression"
                      ? "Input exhaustion is a regression case, not evidence of policy-driven early stopping."
                      : "Representative scripted behavior, not a production performance claim."}
                  </p>
                </section>
                <section className="panel audit-card">
                  <p className="eyebrow">HUMAN TRACEABILITY RUBRIC</p>
                  <h2>Unscored stays pending.</h2>
                  <p>
                    Source attribution, reasoning clarity, evidence groundedness
                    and decision auditability require actual human scoring. This
                    replay assigns no human score.
                  </p>
                  <div className="rubric-grid">
                    {result.rubric_dimensions.map((label) => (
                      <div key={label}>
                        <span>{label.replaceAll("_", " ")}</span>
                        <AuditBadge value="Pending" />
                      </div>
                    ))}
                  </div>
                  <p className="inline-note">
                    Policy version{" "}
                    {text(
                      result.policy.policy_version ??
                        result.identity.policy_version,
                    )}{" "}
                    · max rounds {text(result.policy.max_debate_rounds)}.
                    Estimated usage describes scripted execution only.
                  </p>
                </section>
              </div>
            </>
          ) : null}
        </>
      )}
    </>
  );
}
