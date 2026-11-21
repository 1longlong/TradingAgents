import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-008/009/010, NFR-AUD-001, ADR-002/003, INV-WEB-003/014: recorded audit data only.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode, KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getAllHistory } from "../api/client";
import {
  auditArtifactUrl,
  getAudit,
  getRunAudit,
  number,
  object,
  previewAudit,
  records,
  text,
  type AuditFamily,
  type AuditView,
  type JsonObject,
} from "../api/auditClient";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { formatDate } from "../utils/workspace";

const TABS = [
  ["evidence", "Evidence & checks"],
  ["debate", "Debate & safeguards"],
  ["usage", "Budget & usage"],
  ["artifacts", "Artifacts"],
];
export function AuditBadge({ value, tone }: { value: unknown; tone?: string }) {
  useUILanguage();
  const label = text(value, "Unknown");
  return (
    <span
      className={`audit-badge ${tone ?? (["normal", "High", "Medium", "verified", "pass", "complete", "executed"].includes(label) ? "good" : ["blocked", "Blocked", "rejected", "fail", "invalid", "inconsistent"].includes(label) ? "bad" : ["degraded", "Low", "partial", "estimated", "mixed", "unverified"].includes(label) ? "warn" : "")}`}
    >
      {ui(label)}
    </span>
  );
}
function Card({
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children: ReactNode;
}) {
  useUILanguage();
  return (
    <section className="panel audit-card">
      <h2>{ui(title)}</h2>
      {children}
    </section>
  );
}
function Values({ rows }: { rows: Array<[string, unknown]> }) {
  useUILanguage();
  return (
    <dl className="audit-key-values">
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{ui(key)}</dt>
          <dd>{ui(text(value))}</dd>
        </div>
      ))}
    </dl>
  );
}
function Empty({ title, copy }: { title: string; copy: string }) {
  useUILanguage();
  return (
    <div className="panel empty-state">
      <Icon name="folder" />
      <strong>{ui(title)}</strong>
      <p>{ui(copy)}</p>
    </div>
  );
}
export function AuditPage() {
  useUILanguage();
  const [params, setParams] = useSearchParams(),
    [tab, setTab] = useState("evidence"),
    [filter, setFilter] = useState("all"),
    [search, setSearch] = useState("");
  const [modal, setModal] = useState<{ title: string; body: ReactNode } | null>(
    null,
  );
  const history = useQuery({
    queryKey: ["history", "workspace"],
    queryFn: getAllHistory,
  });
  const choices = (history.data?.items ?? []).filter((item) =>
    ["run", "saved"].includes(item.source),
  );
  const runId = params.get("run_id"),
    selected = params.get("artifact_id") ?? choices[0]?.artifact_id;
  const audit = useQuery({
    queryKey: ["audit", runId ?? selected],
    queryFn: () => (runId ? getRunAudit(runId) : getAudit(selected!)),
    enabled: Boolean(runId || selected),
    retry: false,
    refetchInterval: (query) =>
      runId &&
      ["starting", "running", "cancelling"].includes(
        query.state.data?.status ?? "",
      )
        ? 2000
        : false,
  });
  const data = audit.data,
    manifest = object(data?.data.evidence_manifest),
    summary = object(data?.data.run_summary),
    trace = object(data?.data.debate_trace);
  const gate = object(manifest.gate_decision);
  const inconsistent = data?.consistency?.status === "inconsistent";
  const verdict = inconsistent
    ? "inconsistent"
    : text(manifest.verdict ?? summary.gate_verdict, "Unknown");
  const evidence = records(manifest.evidence_records),
    eligible = new Set(data?.eligible_evidence_ids ?? []);
  const title =
    data?.ticker ??
    choices.find((item) => item.artifact_id === selected)?.ticker;
  const reportUrl = runId
    ? `/runs/${encodeURIComponent(runId)}`
    : data?.artifact_id
      ? `/history/${data.artifact_id}`
      : selected
        ? `/history/${selected}`
        : "/history";
  async function preview(kind: AuditFamily, filename: string) {
    try {
      const content = await previewAudit(data!.artifact_id!, kind);
      setModal({
        title: filename,
        body: (
          <>
            <p className="inline-note">
              {ui(
                "Server-redacted artifact view. Structured audit metadata is distinct from a trusted final decision.",
              )}
            </p>
            <pre className="artifact-json" tabIndex={0}>
              {content}
            </pre>
          </>
        ),
      });
    } catch (error) {
      setModal({
        title: "Artifact unavailable",
        body: <p role="alert">{ui(String(error))}</p>,
      });
    }
  }
  function keyboard(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? TABS.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + TABS.length) %
            TABS.length;
    setTab(TABS[next][0]);
    document.getElementById(`audit-tab-${TABS[next][0]}`)?.focus();
  }
  return (
    <>
      <section className="page-header">
        <div>
          <h1>{ui("Research audit")}</h1>
        </div>
        <div className="page-header-actions">
          <Link className="button ghost" to={reportUrl}>
            <Icon name="book" />
            {ui("Research report")}
          </Link>
        </div>
      </section>
      <div className="audit-toolbar">
        <div>
          <strong>{ui(title ?? "Select a record")}</strong>
          <span className="subtle">
            {ui(" ")}
            {ui("· ")}
            {ui(formatDate(data?.trade_date))}
            {ui(" ·")}
            {ui(" ")}
            {data?.available
              ? ui("Policy {{value0}}", {
                  value0: text(
                    manifest.policy_version ?? summary.gate_policy_version,
                  ),
                })
              : ui("Structured data not available")}
          </span>
        </div>
        <label className="audit-scenario">
          {ui("Research record")}
          <select
            aria-label={ui("Research record")}
            value={runId ? "active" : (selected ?? "")}
            onChange={(event) => {
              setParams({ artifact_id: event.target.value });
              setFilter("all");
              setSearch("");
            }}
          >
            {runId ? (
              <option value="active">
                {ui("Current run · ")}
                {ui(runId)}
              </option>
            ) : null}
            {choices.map((item) => (
              <option key={item.artifact_id} value={item.artifact_id}>
                {item.ticker}
                {ui(" · ")}
                {ui(formatDate(item.date))}
                {ui(" · ")}
                {ui(item.source)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {audit.isLoading || history.isLoading ? (
        <Empty
          title={ui("Loading audit…")}
          copy="Reading the recorded artifact families."
        />
      ) : audit.isError ? (
        <Empty title={ui("Audit unavailable")} copy={audit.error.message} />
      ) : !data?.available ? (
        <section className="panel empty-state audit-missing">
          <Icon name="folder" />
          <strong>
            {data?.artifact_availability === "unavailable"
              ? ui("Audit artifacts could not be read")
              : data?.status && data.status !== "completed"
                ? ui("Audit is not ready")
                : ui("No structured audit recorded")}
          </strong>
          <p>
            {ui("No audit data is available. Missing fields remain unknown.")}
          </p>
        </section>
      ) : (
        <>
          <div
            className={`audit-verdict ${verdict === "blocked" || inconsistent ? "is-blocked" : ""}`}
          >
            <span className="audit-verdict-icon">
              <Icon name={verdict === "normal" ? "checkCircle" : "warning"} />
            </span>
            <div>
              <h2>
                {inconsistent
                  ? ui("Audit artifacts disagree.")
                  : verdict === "blocked"
                    ? ui("Hold is enforced. The debate did not run.")
                    : verdict === "normal"
                      ? ui("Checks passed for this recorded run.")
                      : verdict === "degraded"
                        ? ui("Proceed with recorded limitations.")
                        : ui("The gate verdict was not recorded.")}
              </h2>
              <p>
                {inconsistent
                  ? ui(data.consistency?.issues.join(" · "))
                  : ui(
                      text(
                        gate.human_readable_reason,
                        "No gate explanation recorded.",
                      ),
                    )}
              </p>
            </div>
          </div>
          {data.artifact_availability !== "complete" ? (
            <div className="report-state-banner warning">
              <Icon name="warning" />
              <div>
                <strong>{ui("Partial audit")}</strong>
                <p>
                  {ui(
                    data.artifacts
                      .filter((item) => !item.available)
                      .map((item) => `${item.filename}: ${item.status}`)
                      .join(" · "),
                  )}
                </p>
              </div>
            </div>
          ) : null}
          <div
            className="audit-tabs"
            role="tablist"
            aria-label={ui("Audit views")}
          >
            {TABS.map(([key, label], index) => (
              <button
                role="tab"
                id={`audit-tab-${key}`}
                aria-controls="audit-panel"
                tabIndex={tab === key ? 0 : -1}
                aria-selected={tab === key}
                key={key}
                onKeyDown={(event) => keyboard(event, index)}
                onClick={() => setTab(key)}
              >
                {ui(label)}
              </button>
            ))}
          </div>
          <section
            id="audit-panel"
            role="tabpanel"
            aria-labelledby={`audit-tab-${tab}`}
          >
            {tab === "evidence" ? (
              <EvidencePanel
                data={data}
                manifest={manifest}
                evidence={evidence}
                eligible={eligible}
                filter={filter}
                search={search}
                setFilter={setFilter}
                setSearch={setSearch}
                inspect={(record) =>
                  setModal({
                    title: "Evidence provenance",
                    body: (
                      <>
                        <p className="eyebrow">
                          {ui(text(record.category))}
                          {ui(" · RECORDED EVIDENCE")}
                        </p>
                        <h3>{ui(text(record.metric_name))}</h3>
                        <Values
                          rows={[
                            ["Evidence ID", record.evidence_id],
                            ["Source", record.source_name],
                            ["Observed at", record.observed_at],
                            ["Analysis cutoff", data.trade_date],
                            ["Recorded value", record.value_raw],
                            ["Normalized value", record.value_normalized],
                            ["Unit", record.unit_normalized],
                            ["Quality", record.quality_status],
                          ]}
                        />
                        <p className="inline-note">
                          {ui(
                            "Eligibility concerns quality and cutoff only. A cited ID does not verify an exact claim.",
                          )}
                        </p>
                        <pre className="artifact-json" tabIndex={0}>
                          {JSON.stringify(
                            {
                              validations: record.validation_results ?? null,
                              origin:
                                object(
                                  object(manifest.web_context)
                                    .data_quality_origin_metadata,
                                )[text(record.evidence_id, "")] ?? null,
                            },
                            null,
                            2,
                          )}
                        </pre>
                      </>
                    ),
                  })
                }
              />
            ) : null}
            {tab === "debate" ? (
              <DebatePanel trace={trace} summary={summary} verdict={verdict} />
            ) : null}
            {tab === "usage" ? (
              <UsagePanel trace={trace} summary={summary} />
            ) : null}
            {tab === "artifacts" ? (
              <>
                <div className="audit-section-head">
                  <div>
                    <h2>{ui("The reasoning has a record.")}</h2>
                    <p>
                      {ui(
                        "Core reporting artifacts, projected and redacted by the server.",
                      )}
                    </p>
                  </div>
                </div>
                <div className="artifact-grid">
                  {data.artifacts.map((item) => (
                    <article
                      className="panel audit-card artifact-card"
                      key={item.kind}
                    >
                      <span className="artifact-icon">
                        <Icon
                          name={
                            item.filename.endsWith(".json") ? "layers" : "file"
                          }
                        />
                      </span>
                      <code>{item.filename}</code>
                      <p>
                        <AuditBadge value={item.status} />
                      </p>
                      <div>
                        <button
                          className="button ghost"
                          disabled={!item.available}
                          onClick={() => void preview(item.kind, item.filename)}
                        >
                          {ui("Preview")}
                        </button>
                        {item.available && data.artifact_id ? (
                          <a
                            className="button"
                            href={auditArtifactUrl(
                              data.artifact_id,
                              item.kind,
                              true,
                            )}
                          >
                            <Icon name="download" />
                            {ui("Download")}
                          </a>
                        ) : (
                          <button className="button" disabled>
                            {ui("Unavailable")}
                          </button>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
                <div className="report-state-banner">
                  <Icon name="shield" />
                  <div>
                    <strong>
                      {ui(
                        "Trusted output and raw audit text have different authority.",
                      )}
                    </strong>
                    <p>
                      {ui(
                        "Final reports and memory apply deterministic guards. Audit metadata is not an executable instruction or a calibrated probability.",
                      )}
                    </p>
                  </div>
                </div>
              </>
            ) : null}
          </section>
        </>
      )}
      <Modal
        open={Boolean(modal)}
        title={ui(modal?.title ?? "Audit detail")}
        onClose={() => setModal(null)}
      >
        {modal?.body}
      </Modal>
    </>
  );
}
function EvidencePanel({
  data,
  manifest,
  evidence,
  eligible,
  filter,
  search,
  setFilter,
  setSearch,
  inspect,
}: {
  data: AuditView;
  manifest: JsonObject;
  evidence: JsonObject[];
  eligible: Set<string>;
  filter: string;
  search: string;
  setFilter: (value: string) => void;
  setSearch: (value: string) => void;
  inspect: (record: JsonObject) => void;
}) {
  useUILanguage();
  const rows = evidence.filter(
    (row) =>
      (filter === "all" ||
        (filter === "eligible" && eligible.has(text(row.evidence_id, ""))) ||
        (filter === "excluded" && !eligible.has(text(row.evidence_id, ""))) ||
        row.category === filter) &&
      (text(row.evidence_id) + text(row.metric_name) + text(row.source_name))
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const validations = evidence.flatMap((row) =>
    records(row.validation_results),
  );
  const classes = [
    ["completeness", "Completeness"],
    ["freshness_lookahead", "Freshness & look-ahead"],
    ["format_numeric", "Numeric format"],
    ["asset_applicability", "Asset applicability"],
    ["cross_source_consistency", "Cross-source consistency"],
  ];
  return (
    <>
      <div className="audit-section-head">
        <div>
          <h2>{ui("Evidence ledger")}</h2>
          <p>
            {ui(
              "One source remains one source, even when several tools read it.",
            )}
          </p>
        </div>
        <div className="audit-filters">
          <label className="sr-only" htmlFor="evidence-query">
            {ui("Search evidence by ID, metric or source")}
          </label>
          <input
            id="evidence-query"
            type="search"
            placeholder={ui("Find evidence...")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <label className="sr-only" htmlFor="evidence-filter">
            {ui("Filter evidence")}
          </label>
          <select
            id="evidence-filter"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            {[
              ["all", "All evidence"],
              ["eligible", "Eligible only"],
              ["excluded", "Excluded only"],
              ["market", "Market"],
              ["fundamentals", "Fundamentals"],
              ["news", "News"],
              ["sentiment", "Sentiment"],
            ].map(([key, label]) => (
              <option key={key} value={key}>
                {ui(label)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {rows.length ? (
        <div className="panel audit-table-wrap">
          <table className="audit-table">
            <caption className="sr-only">
              {ui("Recorded evidence, source, cutoff eligibility and quality")}
            </caption>
            <thead>
              <tr>
                <th>{ui("Evidence / metric")}</th>
                <th>{ui("Source / observed")}</th>
                <th>{ui("Quality")}</th>
                <th>{ui("Eligibility")}</th>
                <th>{ui("Details")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${text(row.evidence_id)}-${index}`}>
                  <td data-label="Evidence">
                    <code>{text(row.evidence_id)}</code>
                    <small>{ui(text(row.metric_name))}</small>
                  </td>
                  <td data-label="Provenance">
                    {ui(text(row.source_name))}
                    <small>{ui(text(row.observed_at))}</small>
                  </td>
                  <td data-label="Quality">
                    <AuditBadge value={row.quality_status} />
                  </td>
                  <td data-label="Eligibility">
                    {eligible.has(text(row.evidence_id, ""))
                      ? ui("Eligible")
                      : ui("Excluded")}
                  </td>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => inspect(row)}
                    >
                      {ui("Inspect")}
                      <Icon name="arrow" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="panel empty-state">
          <strong>{ui("No matching evidence")}</strong>
          <p>{ui("No matching records were returned.")}</p>
          <button
            className="button"
            onClick={() => {
              setFilter("all");
              setSearch("");
            }}
          >
            {ui("Clear evidence filters")}
          </button>
        </div>
      )}
      <div className="audit-two-col">
        <Card eyebrow="FIVE VALIDATION CLASSES" title={ui("What was checked?")}>
          <div className="audit-checks">
            {classes.map(([key, label]) => {
              const checks = validations.filter(
                (item) => item.validation_class === key,
              );
              return (
                <div key={key}>
                  <span className="audit-check-icon">
                    <Icon name={checks.length ? "checkCircle" : "help"} />
                  </span>
                  <span>
                    <strong>{ui(label)}</strong>
                    <small>
                      {checks.length
                        ? ui(
                            Array.from(
                              new Set(checks.map((item) => text(item.status))),
                            )
                              .map(
                                (status) =>
                                  `${checks.filter((item) => item.status === status).length} ${status}`,
                              )
                              .join(" · "),
                          )
                        : ui("No per-record check recorded")}
                    </small>
                  </span>
                  <AuditBadge
                    value={
                      checks.length
                        ? ui("{{value0}} checks", { value0: checks.length })
                        : "Not recorded"
                    }
                  />
                </div>
              );
            })}
          </div>
          <p className="inline-note">
            {ui(
              "Record-level check counts do not replace the authoritative gate verdict.",
            )}
          </p>
        </Card>
        <Card
          eyebrow="CATEGORY COVERAGE"
          title={ui("Limitations travel with the result.")}
        >
          <p>
            {ui(
              "The gate retains category quality, reason codes and source counts.",
            )}
          </p>
          <dl className="audit-key-values">
            {records(manifest.category_statuses).map((category, index) => (
              <div key={index}>
                <dt>{ui(text(category.category))}</dt>
                <dd>
                  <AuditBadge value={category.quality_status} />
                  <small>
                    {ui(text(category.independent_source_count))}
                    {ui(" independent sources")}
                  </small>
                </dd>
              </div>
            ))}
          </dl>
          <Values
            rows={[
              [
                "Policy / cutoff",
                `${text(manifest.policy_version)} · ${formatDate(data.trade_date)}`,
              ],
            ]}
          />
          <p className="inline-note">
            {ui(
              "High is a corroborated category result. An individual record and optional categories are at most Medium.",
            )}
          </p>
        </Card>
      </div>
      {records(object(manifest.web_context).data_quality_source_attempts)
        .length ? (
        <Card
          eyebrow="SOURCE ATTEMPTS"
          title={ui("Attempted sources stay distinct.")}
        >
          <div className="audit-checks">
            {records(
              object(manifest.web_context).data_quality_source_attempts,
            ).map((attempt, index) => (
              <div key={index}>
                <span>
                  <strong>{ui(text(attempt.source))}</strong>
                  <small>
                    {ui(text(attempt.tool))}
                    {ui(" · ")}
                    {ui(text(attempt.started_at))}
                  </small>
                </span>
                <AuditBadge value={attempt.result_status} />
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </>
  );
}
function DebatePanel({
  trace,
  summary,
  verdict,
}: {
  trace: JsonObject;
  summary: JsonObject;
  verdict: string;
}) {
  useUILanguage();
  const participation = object(trace.participation ?? summary.participation),
    cap = object(summary.confidence_cap),
    confidence = records(cap.entries)[0],
    rounds = records(trace.round_metrics),
    claims = object(trace.claim_validation),
    conflicts = records(object(trace.web_context).conflicts);
  return (
    <>
      <div className="audit-two-col">
        <Card
          eyebrow="STRUCTURED PARTICIPATION"
          title={ui("Who actually spoke?")}
        >
          <div className="speaker-grid">
            {["Bull", "Bear"].map((speaker) => (
              <div className="speaker-card" key={speaker}>
                <span>
                  <Icon name="users" />
                </span>
                <strong>{ui(speaker)}</strong>
                <small>
                  {ui(text(participation[speaker.toLowerCase()], "unverified"))}
                  {ui(" ·")}
                  {ui(" ")}
                  {ui(
                    text(
                      participation[`${speaker.toLowerCase()}_turns`],
                      "Unknown",
                    ),
                  )}
                  {ui(" ")}
                  {ui("turns")}
                </small>
              </div>
            ))}
          </div>
          <p className="inline-note">
            {verdict === "blocked"
              ? ui(
                  "Critical evidence blocked the directional debate. No Bull/Bear argument is invented.",
                )
              : ui(
                  "Participation is based on structured turns. A legacy transcript alone does not prove execution.",
                )}
          </p>
        </Card>
        <Card
          eyebrow="OUTPUT SAFEGUARDS"
          title={
            verdict === "degraded"
              ? ui("Degraded evidence limits confidence.")
              : ui("The authoritative verdict controls output.")
          }
        >
          <div className="confidence-flow">
            {confidence ? (
              <>
                <div>
                  <small>{ui("Raw recorded")}</small>
                  <strong>{ui(text(confidence.raw_value))}</strong>
                </div>
                <span>
                  <Icon name="arrow" />
                </span>
                <div>
                  <small>{ui("Effective")}</small>
                  <strong>{ui(text(confidence.effective_value))}</strong>
                </div>
              </>
            ) : (
              <strong>
                {verdict === "blocked"
                  ? ui("Hold · no directional debate")
                  : ui("No explicit confidence recorded")}
              </strong>
            )}
          </div>
          <Values
            rows={[
              ["Policy version", cap.policy_version],
              ["Ceiling", cap.cap],
              ["Cap applies", cap.cap_applies],
              [
                "Capped / quarantined",
                `${text(cap.capped_count)} / ${text(cap.quarantined_count)}`,
              ],
            ]}
          />
          <p className="inline-note">
            {ui(
              "An engineering constraint, not a calibrated probability or accuracy score. Raw audit values are not authoritative decisions.",
            )}
          </p>
        </Card>
      </div>
      {rounds.length ? (
        <Card
          eyebrow="DETERMINISTIC DECISION TRACE"
          title={ui("Why did it stop?")}
        >
          <div className="audit-rounds">
            {rounds.map((round, index) => (
              <article key={index}>
                <span className="round-number">
                  {ui(text(round.round_index))}
                </span>
                <div>
                  <strong>
                    {ui("Round ")}
                    {ui(text(round.round_index))}
                  </strong>
                  <p>
                    {ui(text(round.new_valid_evidence_count))}
                    {ui(" new eligible evidence items ·")}
                    {ui(" ")}
                    {ui(
                      text(round.unresolved_critical_or_major_conflict_count),
                    )}
                    {ui(" ")}
                    {ui("unresolved major/critical conflicts")}
                  </p>
                  <small>
                    {ui(text(round.calls))}
                    {ui(" calls · ")}
                    {ui(text(round.tokens))}
                    {ui(" tokens")}
                  </small>
                </div>
                <AuditBadge
                  value={round.estimated ? "estimated" : "recorded"}
                />
              </article>
            ))}
          </div>
        </Card>
      ) : (
        <Empty
          title={
            verdict === "blocked"
              ? ui("Debate skipped")
              : ui("No structured rounds recorded")
          }
          copy="Absent rounds do not prove that a two-sided debate executed."
        />
      )}
      <div className="audit-two-col">
        <Card
          eyebrow="CLAIMS & CONFLICTS"
          title={ui("Eligible citation does not prove a claim.")}
        >
          {["verified", "rejected", "unverified"].flatMap((status) =>
            records(claims[status]).map((claim, index) => (
              <div className="audit-claim" key={`${status}-${index}`}>
                <div>
                  <strong>{ui(text(claim.metric, "Claim"))}</strong>
                  <p>
                    {ui(text(claim.reason))}
                    {ui(" · ")}
                    {ui(text(claim.date))}
                    {ui(" ·")}
                    {ui(" ")}
                    {ui(text(claim.value))} {ui(text(claim.unit, ""))}
                  </p>
                </div>
                <AuditBadge value={status} />
              </div>
            )),
          )}
          {!["verified", "rejected", "unverified"].some(
            (status) => records(claims[status]).length,
          ) ? (
            <p>{ui("No per-claim descriptors recorded.")}</p>
          ) : null}
          {conflicts.map((conflict, index) => (
            <div className="audit-conflict" key={index}>
              <span>
                <Icon name="layers" />
              </span>
              <div>
                <strong>
                  {ui(text(conflict.kind))}
                  {ui(" conflict · ")}
                  {ui(text(conflict.conflict_id))}
                </strong>
                <p>
                  {ui(text(conflict.status))}
                  {ui(" · ")}
                  {ui(text(conflict.severity))}
                  {ui(" · rounds")}
                  {ui(" ")}
                  {ui(text(conflict.first_seen_round))}
                  {ui("–")}
                  {ui(text(conflict.last_seen_round))}
                </p>
              </div>
            </div>
          ))}
          {!conflicts.length ? (
            <p className="inline-note">
              {ui("No individual conflict lifecycle descriptors recorded.")}
            </p>
          ) : null}
        </Card>
        <Card
          eyebrow="STOP REASON"
          title={ui(
            text(trace.stop_reason ?? summary.debate_stop_reason).replaceAll(
              "_",
              " ",
            ),
          )}
        >
          <Values
            rows={[
              ["Route", trace.route ?? summary.debate_route],
              [
                "Recorded rounds",
                trace.round_count ?? summary.debate_round_count,
              ],
              ["Participation", participation.status],
              ["Skip reason", participation.skip_reason],
            ]}
          />
          <p className="inline-note">
            {ui(
              "A completed restricted Hold differs from REVIEW, cancellation and a provider failure.",
            )}
          </p>
        </Card>
      </div>
    </>
  );
}
function UsagePanel({
  trace,
  summary,
}: {
  trace: JsonObject;
  summary: JsonObject;
}) {
  useUILanguage();
  const usage = object(
      summary.whole_run_usage ?? object(trace.usage_provenance).whole_run_usage,
    ),
    totals = object(usage.totals),
    phases = object(usage.by_phase),
    budget = object(trace.budget),
    debate = object(trace.usage),
    unknown = !usage.completeness || usage.completeness === "unknown";
  const maximum = number(budget.max_tokens),
    used = number(budget.used_tokens ?? debate.tokens),
    reserve = number(budget.reserved_summary_tokens);
  return (
    <>
      <div className="audit-two-col">
        <Card
          eyebrow="WHOLE-RUN ACCOUNTING"
          title={ui("Every accounted model phase, kept separate.")}
        >
          <div className="usage-total">
            <strong>{unknown ? ui("—") : ui(text(totals.calls))}</strong>
            <span>
              {ui("accounted calls")}
              <br />
              <AuditBadge value={usage.completeness ?? "unknown"} />
            </span>
          </div>
          <p>
            <strong>{unknown ? ui("Unknown") : ui(text(totals.tokens))}</strong>
            {ui(" known token subtotal ·")}
            {ui(" ")}
            <AuditBadge value={totals.tokens_source ?? "unavailable"} />
          </p>
          <p className="inline-note">
            {ui(
              "Reporting only. Whole-run totals are not the debate budget or a monetary bill. Unknown telemetry is not zero cost.",
            )}
          </p>
        </Card>
        <Card
          eyebrow="DEBATE BUDGET · RECORDED POLICY"
          title={ui("Keep room for the final summary.")}
        >
          <Values
            rows={[
              [
                "Debate calls / cap",
                `${text(budget.used_calls ?? debate.calls)} / ${text(budget.max_calls)}`,
              ],
              ["Debate token use / cap", `${text(used)} / ${text(maximum)}`],
              [
                "Reserved summary",
                ui("{{value0}} tokens · {{value1}}s", {
                  value0: text(reserve),
                  value1: text(budget.reserved_summary_seconds),
                }),
              ],
              ["Next-round estimate", budget.next_round_estimate_tokens],
            ]}
          />
          {maximum != null && maximum > 0 && used != null && reserve != null ? (
            <>
              <div className="budget-legend">
                <span>{ui("Recorded debate use")}</span>
                <span>{ui("Protected summary reserve")}</span>
              </div>
              <div
                className="budget-bar"
                role="img"
                aria-label={ui("Recorded debate use and summary reserve")}
              >
                <span
                  style={{
                    width: `${Math.min(100, Math.max(0, (used / maximum) * 100))}%`,
                  }}
                />
                <i
                  style={{
                    width: `${Math.min(100, Math.max(0, (reserve / maximum) * 100))}%`,
                  }}
                />
              </div>
            </>
          ) : null}
          <p className="inline-note">
            {ui(
              "Read-only recorded policy. Missing limits are not replaced with production defaults.",
            )}
          </p>
        </Card>
      </div>
      <Card
        eyebrow="DURABLE USAGE LEDGER"
        title={ui("Known, estimated and unknown are different states.")}
      >
        <div className="ledger-flags">
          {[
            ["Unknown-cost calls", unknown ? null : totals.unknown_cost_calls],
            [
              "Unconfirmed reservations",
              unknown ? null : usage.reserved_unconfirmed_calls,
            ],
            [
              "Transport attempts",
              object(trace.usage_provenance).transport_attempts,
            ],
          ].map(([key, value]) => (
            <div key={String(key)}>
              <small>{ui(String(key))}</small>
              <strong>{ui(text(value))}</strong>
            </div>
          ))}
        </div>
        {Object.keys(phases).length ? (
          <div className="audit-table-wrap">
            <table className="audit-table">
              <caption className="sr-only">
                {ui("Recorded model-calling phase accounting")}
              </caption>
              <thead>
                <tr>
                  <th>{ui("Phase")}</th>
                  <th>{ui("Calls")}</th>
                  <th>{ui("Tokens")}</th>
                  <th>{ui("Provenance")}</th>
                  <th>{ui("Duration")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(phases).map(([phase, value]) => {
                  const row = object(value);
                  return (
                    <tr key={phase}>
                      <td data-label="Phase">
                        {ui(phase.replaceAll("_", " "))}
                      </td>
                      <td data-label="Calls">{ui(text(row.calls))}</td>
                      <td data-label="Tokens">{ui(text(row.tokens))}</td>
                      <td data-label="Provenance">
                        <AuditBadge value={row.tokens_source ?? row.source} />
                      </td>
                      <td data-label="Duration">{ui(text(row.seconds))}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p>{ui("No model-calling phases were accounted in this record.")}</p>
        )}
        <p className="inline-note">
          {ui(
            "A reservation is an estimated commitment, not proof a call completed. Missing or unreadable accounting does not imply free optional capacity.",
          )}
        </p>
        <Values
          rows={[
            [
              "Execution identity",
              summary.execution_run_id ??
                object(trace.usage_provenance).execution_run_id,
            ],
            ["Accounting unreadable", usage.accounting_unreadable],
            [
              "Unresolved invocations",
              unknown ? null : usage.unresolved_invocations,
            ],
          ]}
        />
      </Card>
    </>
  );
}
