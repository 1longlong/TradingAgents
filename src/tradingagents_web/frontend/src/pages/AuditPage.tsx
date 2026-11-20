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
  const label = text(value, "Unknown");
  return (
    <span
      className={`audit-badge ${tone ?? (["normal", "High", "Medium", "verified", "pass", "complete", "executed"].includes(label) ? "good" : ["blocked", "Blocked", "rejected", "fail", "invalid", "inconsistent"].includes(label) ? "bad" : ["degraded", "Low", "partial", "estimated", "mixed", "unverified"].includes(label) ? "warn" : "")}`}
    >
      {label}
    </span>
  );
}
export function AuditOverview({ artifactId }: { artifactId?: string }) {
  const audit = useQuery({
    queryKey: ["audit", artifactId],
    queryFn: () => getAudit(artifactId!),
    enabled: Boolean(artifactId),
    retry: false,
  });
  const data = audit.data;
  if (!data?.available) return null;
  const summary = object(data.data.run_summary),
    manifest = object(data.data.evidence_manifest),
    trace = object(data.data.debate_trace);
  const verdict =
    data.consistency?.status === "inconsistent"
      ? "inconsistent"
      : text(manifest.verdict ?? summary.gate_verdict);
  return (
    <section className="panel audit-overview">
      <div className="audit-overview-title">
        <Icon name="shield" />
        <div>
          <p className="eyebrow">BEHIND THIS ASSESSMENT</p>
          <h3>
            {verdict === "normal"
              ? "Evidence checked. Provenance retained."
              : verdict === "degraded"
                ? "Usable evidence, with explicit limits."
                : verdict === "blocked"
                  ? "Critical evidence blocked the directional debate."
                  : "Recorded audit, with explicit unknowns."}
          </h3>
        </div>
      </div>
      <div className="audit-overview-facts">
        <AuditBadge value={`Gate · ${verdict}`} />
        <AuditBadge
          value={`Debate · ${text(trace.round_count ?? summary.debate_round_count)} rounds`}
        />
        <AuditBadge
          value={`Accounting · ${text(object(summary.whole_run_usage).completeness, "unknown")}`}
        />
      </div>
      <Link className="text-button" to={`/audit?artifact_id=${artifactId}`}>
        Inspect the audit
        <Icon name="arrow" />
      </Link>
    </section>
  );
}
function Card({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="panel audit-card">
      {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
      <h2>{title}</h2>
      {children}
    </section>
  );
}
function Values({ rows }: { rows: Array<[string, unknown]> }) {
  return (
    <dl className="audit-key-values">
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{text(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
function Empty({ title, copy }: { title: string; copy: string }) {
  return (
    <div className="panel empty-state">
      <Icon name="folder" />
      <strong>{title}</strong>
      <p>{copy}</p>
    </div>
  );
}
export function AuditPage() {
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
  const gate = object(manifest.gate_decision),
    participation = object(trace.participation ?? summary.participation),
    usage = object(
      summary.whole_run_usage ?? object(trace.usage_provenance).whole_run_usage,
    );
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
              Server-redacted artifact view. Structured audit metadata is
              distinct from a trusted final decision.
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
        body: <p role="alert">{String(error)}</p>,
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
          <p className="eyebrow">EVIDENCE, WITH A PAPER TRAIL</p>
          <h1>Research audit</h1>
          <p className="page-description">
            Trace the inputs, decisions and resource accounting behind{" "}
            {title ?? "your research"}.
          </p>
        </div>
        <div className="page-header-actions">
          <Link className="button ghost" to={reportUrl}>
            <Icon name="book" />
            Research report
          </Link>
        </div>
      </section>
      <div className="audit-toolbar">
        <div>
          <strong>{title ?? "Select a record"}</strong>
          <span className="subtle">
            {" "}
            · {formatDate(data?.trade_date)} ·{" "}
            {data?.available
              ? `Policy ${text(manifest.policy_version ?? summary.gate_policy_version)}`
              : "Structured data not available"}
          </span>
        </div>
        <label className="audit-scenario">
          Research record
          <select
            aria-label="Research record"
            value={runId ? "active" : (selected ?? "")}
            onChange={(event) => {
              setParams({ artifact_id: event.target.value });
              setFilter("all");
              setSearch("");
            }}
          >
            {runId ? (
              <option value="active">Current run · {runId}</option>
            ) : null}
            {choices.map((item) => (
              <option key={item.artifact_id} value={item.artifact_id}>
                {item.ticker} · {formatDate(item.date)} · {item.source}
              </option>
            ))}
          </select>
        </label>
      </div>
      {audit.isLoading || history.isLoading ? (
        <Empty
          title="Loading audit…"
          copy="Reading the recorded artifact families."
        />
      ) : audit.isError ? (
        <Empty title="Audit unavailable" copy={audit.error.message} />
      ) : !data?.available ? (
        <section className="panel empty-state audit-missing">
          <Icon name="folder" />
          <strong>
            {data?.artifact_availability === "unavailable"
              ? "Audit artifacts could not be read"
              : data?.status && data.status !== "completed"
                ? "Audit is not ready"
                : "No structured audit recorded"}
          </strong>
          <p>
            Legacy or incomplete artifacts are not proof of participation, data
            quality or zero cost. Read the available report; missing audit
            fields remain unknown.
          </p>
          <div className="audit-empty-values">
            <AuditBadge value="Gate · not recorded" />
            <AuditBadge value="Participation · unverified" />
            <AuditBadge value="Accounting · unknown" />
          </div>
        </section>
      ) : (
        <>
          <div className="audit-summary-grid">
            {[
              ["Data quality gate", verdict, "Deterministic verdict"],
              [
                "Eligible evidence",
                `${eligible.size} / ${evidence.length}`,
                "Excluded items stay visible",
              ],
              [
                "Debate participation",
                text(participation.status, "Unverified"),
                "Structured execution records",
              ],
              [
                "Usage completeness",
                text(usage.completeness, "Unknown"),
                "Provenance is explicit",
              ],
            ].map(([label, value, note]) => (
              <div className="panel audit-stat" key={label}>
                <small>{label}</small>
                <strong>{value}</strong>
                <span>{note}</span>
              </div>
            ))}
          </div>
          <div
            className={`audit-verdict ${verdict === "blocked" || inconsistent ? "is-blocked" : ""}`}
          >
            <span className="audit-verdict-icon">
              <Icon name={verdict === "normal" ? "checkCircle" : "warning"} />
            </span>
            <div>
              <h2>
                {inconsistent
                  ? "Audit artifacts disagree."
                  : verdict === "blocked"
                    ? "Hold is enforced. The debate did not run."
                    : verdict === "normal"
                      ? "Checks passed for this recorded run."
                      : verdict === "degraded"
                        ? "Proceed with recorded limitations."
                        : "The gate verdict was not recorded."}
              </h2>
              <p>
                {inconsistent
                  ? data.consistency?.issues.join(" · ")
                  : text(
                      gate.human_readable_reason,
                      "No gate explanation recorded.",
                    )}
              </p>
              <span className="audit-code">
                {text(trace.stop_reason ?? summary.debate_stop_reason)}
              </span>
            </div>
          </div>
          {data.artifact_availability !== "complete" ? (
            <div className="report-state-banner warning">
              <Icon name="warning" />
              <div>
                <strong>Partial audit</strong>
                <p>
                  {data.artifacts
                    .filter((item) => !item.available)
                    .map((item) => `${item.filename}: ${item.status}`)
                    .join(" · ")}
                </p>
              </div>
            </div>
          ) : null}
          <div className="audit-tabs" role="tablist" aria-label="Audit views">
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
                {label}
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
                          {text(record.category)} · RECORDED EVIDENCE
                        </p>
                        <h3>{text(record.metric_name)}</h3>
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
                          Eligibility concerns quality and cutoff only. A cited
                          ID does not verify an exact claim.
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
                    <h2>The reasoning has a record.</h2>
                    <p>
                      Core reporting artifacts, projected and redacted by the
                      server.
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
                          Preview
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
                            Download
                          </a>
                        ) : (
                          <button className="button" disabled>
                            Unavailable
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
                      Trusted output and raw audit text have different
                      authority.
                    </strong>
                    <p>
                      Final reports and memory apply deterministic guards. Audit
                      metadata is not an executable instruction or a calibrated
                      probability.
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
        title={modal?.title ?? "Audit detail"}
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
          <h2>Evidence ledger</h2>
          <p>One source remains one source, even when several tools read it.</p>
        </div>
        <div className="audit-filters">
          <label className="sr-only" htmlFor="evidence-query">
            Search evidence by ID, metric or source
          </label>
          <input
            id="evidence-query"
            type="search"
            placeholder="Find evidence..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <label className="sr-only" htmlFor="evidence-filter">
            Filter evidence
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
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {rows.length ? (
        <div className="panel audit-table-wrap">
          <table className="audit-table">
            <caption className="sr-only">
              Recorded evidence, source, cutoff eligibility and quality
            </caption>
            <thead>
              <tr>
                <th>Evidence / metric</th>
                <th>Source / observed</th>
                <th>Quality</th>
                <th>Eligibility</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${text(row.evidence_id)}-${index}`}>
                  <td data-label="Evidence">
                    <code>{text(row.evidence_id)}</code>
                    <small>{text(row.metric_name)}</small>
                  </td>
                  <td data-label="Provenance">
                    {text(row.source_name)}
                    <small>{text(row.observed_at)}</small>
                  </td>
                  <td data-label="Quality">
                    <AuditBadge value={row.quality_status} />
                  </td>
                  <td data-label="Eligibility">
                    {eligible.has(text(row.evidence_id, ""))
                      ? "Eligible"
                      : "Excluded"}
                  </td>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => inspect(row)}
                    >
                      Inspect
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
          <strong>No matching evidence</strong>
          <p>No matching records were returned.</p>
          <button
            className="button"
            onClick={() => {
              setFilter("all");
              setSearch("");
            }}
          >
            Clear evidence filters
          </button>
        </div>
      )}
      <div className="audit-two-col">
        <Card eyebrow="FIVE VALIDATION CLASSES" title="What was checked?">
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
                    <strong>{label}</strong>
                    <small>
                      {checks.length
                        ? Array.from(
                            new Set(checks.map((item) => text(item.status))),
                          )
                            .map(
                              (status) =>
                                `${checks.filter((item) => item.status === status).length} ${status}`,
                            )
                            .join(" · ")
                        : "No per-record check recorded"}
                    </small>
                  </span>
                  <AuditBadge
                    value={
                      checks.length ? `${checks.length} checks` : "Not recorded"
                    }
                  />
                </div>
              );
            })}
          </div>
          <p className="inline-note">
            Record-level check counts do not replace the authoritative gate
            verdict.
          </p>
        </Card>
        <Card
          eyebrow="CATEGORY COVERAGE"
          title="Limitations travel with the result."
        >
          <p>
            The gate retains category quality, reason codes and source counts.
          </p>
          <dl className="audit-key-values">
            {records(manifest.category_statuses).map((category, index) => (
              <div key={index}>
                <dt>{text(category.category)}</dt>
                <dd>
                  <AuditBadge value={category.quality_status} />
                  <small>
                    {text(category.independent_source_count)} independent
                    sources
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
            High is a corroborated category result. An individual record and
            optional categories are at most Medium.
          </p>
        </Card>
      </div>
      {records(object(manifest.web_context).data_quality_source_attempts)
        .length ? (
        <Card
          eyebrow="SOURCE ATTEMPTS"
          title="Attempted sources stay distinct."
        >
          <div className="audit-checks">
            {records(
              object(manifest.web_context).data_quality_source_attempts,
            ).map((attempt, index) => (
              <div key={index}>
                <span>
                  <strong>{text(attempt.source)}</strong>
                  <small>
                    {text(attempt.tool)} · {text(attempt.started_at)}
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
  const participation = object(trace.participation ?? summary.participation),
    cap = object(summary.confidence_cap),
    confidence = records(cap.entries)[0],
    rounds = records(trace.round_metrics),
    claims = object(trace.claim_validation),
    conflicts = records(object(trace.web_context).conflicts);
  return (
    <>
      <div className="audit-two-col">
        <Card eyebrow="STRUCTURED PARTICIPATION" title="Who actually spoke?">
          <div className="speaker-grid">
            {["Bull", "Bear"].map((speaker) => (
              <div className="speaker-card" key={speaker}>
                <span>
                  <Icon name="users" />
                </span>
                <strong>{speaker}</strong>
                <small>
                  {text(participation[speaker.toLowerCase()], "unverified")} ·{" "}
                  {text(
                    participation[`${speaker.toLowerCase()}_turns`],
                    "Unknown",
                  )}{" "}
                  turns
                </small>
              </div>
            ))}
          </div>
          <p className="inline-note">
            {verdict === "blocked"
              ? "Critical evidence blocked the directional debate. No Bull/Bear argument is invented."
              : "Participation is based on structured turns. A legacy transcript alone does not prove execution."}
          </p>
        </Card>
        <Card
          eyebrow="OUTPUT SAFEGUARDS"
          title={
            verdict === "degraded"
              ? "Degraded evidence limits confidence."
              : "The authoritative verdict controls output."
          }
        >
          <div className="confidence-flow">
            {confidence ? (
              <>
                <div>
                  <small>Raw recorded</small>
                  <strong>{text(confidence.raw_value)}</strong>
                </div>
                <span>
                  <Icon name="arrow" />
                </span>
                <div>
                  <small>Effective</small>
                  <strong>{text(confidence.effective_value)}</strong>
                </div>
              </>
            ) : (
              <strong>
                {verdict === "blocked"
                  ? "Hold · no directional debate"
                  : "No explicit confidence recorded"}
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
            An engineering constraint, not a calibrated probability or accuracy
            score. Raw audit values are not authoritative decisions.
          </p>
        </Card>
      </div>
      {rounds.length ? (
        <Card eyebrow="DETERMINISTIC DECISION TRACE" title="Why did it stop?">
          <div className="audit-rounds">
            {rounds.map((round, index) => (
              <article key={index}>
                <span className="round-number">{text(round.round_index)}</span>
                <div>
                  <strong>Round {text(round.round_index)}</strong>
                  <p>
                    {text(round.new_valid_evidence_count)} new eligible evidence
                    items ·{" "}
                    {text(round.unresolved_critical_or_major_conflict_count)}{" "}
                    unresolved major/critical conflicts
                  </p>
                  <small>
                    {text(round.calls)} calls · {text(round.tokens)} tokens
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
              ? "Debate skipped"
              : "No structured rounds recorded"
          }
          copy="Absent rounds do not prove that a two-sided debate executed."
        />
      )}
      <div className="audit-two-col">
        <Card
          eyebrow="CLAIMS & CONFLICTS"
          title="Eligible citation does not prove a claim."
        >
          {["verified", "rejected", "unverified"].flatMap((status) =>
            records(claims[status]).map((claim, index) => (
              <div className="audit-claim" key={`${status}-${index}`}>
                <div>
                  <strong>{text(claim.metric, "Claim")}</strong>
                  <p>
                    {text(claim.reason)} · {text(claim.date)} ·{" "}
                    {text(claim.value)} {text(claim.unit, "")}
                  </p>
                </div>
                <AuditBadge value={status} />
              </div>
            )),
          )}
          {!["verified", "rejected", "unverified"].some(
            (status) => records(claims[status]).length,
          ) ? (
            <p>No per-claim descriptors recorded.</p>
          ) : null}
          {conflicts.map((conflict, index) => (
            <div className="audit-conflict" key={index}>
              <span>
                <Icon name="layers" />
              </span>
              <div>
                <strong>
                  {text(conflict.kind)} conflict · {text(conflict.conflict_id)}
                </strong>
                <p>
                  {text(conflict.status)} · {text(conflict.severity)} · rounds{" "}
                  {text(conflict.first_seen_round)}–
                  {text(conflict.last_seen_round)}
                </p>
              </div>
            </div>
          ))}
          {!conflicts.length ? (
            <p className="inline-note">
              No individual conflict lifecycle descriptors recorded.
            </p>
          ) : null}
        </Card>
        <Card
          eyebrow="STOP REASON"
          title={text(
            trace.stop_reason ?? summary.debate_stop_reason,
          ).replaceAll("_", " ")}
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
            A completed restricted Hold differs from REVIEW, cancellation and a
            provider failure.
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
          title="Every accounted model phase, kept separate."
        >
          <div className="usage-total">
            <strong>{unknown ? "—" : text(totals.calls)}</strong>
            <span>
              accounted calls
              <br />
              <AuditBadge value={usage.completeness ?? "unknown"} />
            </span>
          </div>
          <p>
            <strong>{unknown ? "Unknown" : text(totals.tokens)}</strong> known
            token subtotal ·{" "}
            <AuditBadge value={totals.tokens_source ?? "unavailable"} />
          </p>
          <p className="inline-note">
            Reporting only. Whole-run totals are not the debate budget or a
            monetary bill. Unknown telemetry is not zero cost.
          </p>
        </Card>
        <Card
          eyebrow="DEBATE BUDGET · RECORDED POLICY"
          title="Keep room for the final summary."
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
                `${text(reserve)} tokens · ${text(budget.reserved_summary_seconds)}s`,
              ],
              ["Next-round estimate", budget.next_round_estimate_tokens],
            ]}
          />
          {maximum != null && maximum > 0 && used != null && reserve != null ? (
            <>
              <div className="budget-legend">
                <span>Recorded debate use</span>
                <span>Protected summary reserve</span>
              </div>
              <div
                className="budget-bar"
                role="img"
                aria-label="Recorded debate use and summary reserve"
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
            Read-only recorded policy. Missing limits are not replaced with
            production defaults.
          </p>
        </Card>
      </div>
      <Card
        eyebrow="DURABLE USAGE LEDGER"
        title="Known, estimated and unknown are different states."
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
              <small>{String(key)}</small>
              <strong>{text(value)}</strong>
            </div>
          ))}
        </div>
        {Object.keys(phases).length ? (
          <div className="audit-table-wrap">
            <table className="audit-table">
              <caption className="sr-only">
                Recorded model-calling phase accounting
              </caption>
              <thead>
                <tr>
                  <th>Phase</th>
                  <th>Calls</th>
                  <th>Tokens</th>
                  <th>Provenance</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(phases).map(([phase, value]) => {
                  const row = object(value);
                  return (
                    <tr key={phase}>
                      <td data-label="Phase">{phase.replaceAll("_", " ")}</td>
                      <td data-label="Calls">{text(row.calls)}</td>
                      <td data-label="Tokens">{text(row.tokens)}</td>
                      <td data-label="Provenance">
                        <AuditBadge value={row.tokens_source ?? row.source} />
                      </td>
                      <td data-label="Duration">{text(row.seconds)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No model-calling phases were accounted in this record.</p>
        )}
        <p className="inline-note">
          A reservation is an estimated commitment, not proof a call completed.
          Missing or unreadable accounting does not imply free optional
          capacity.
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
