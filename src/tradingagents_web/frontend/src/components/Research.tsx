// REQ-WEB-002/008/010, ADR-003: presentation of recorded reports; no inferred facts.
import { useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { Icon } from "./Icon";
import { Markdown } from "./Markdown";
import {
  ANALYST_LABELS,
  formatDate,
  ratingClass,
  sectionLabel,
  statusClass,
  statusLabel,
  visibleSectionKeys,
} from "../utils/workspace";

export function CompanyLogo({
  ticker,
  small = false,
}: {
  ticker: string;
  small?: boolean;
}) {
  return (
    <span className={`company-logo ${small ? "small" : ""}`}>
      {ticker === "NVDA" ? <Icon name="chip" /> : ticker.slice(0, 1)}
    </span>
  );
}
export function Rating({ value }: { value?: string | null }) {
  return value ? (
    <span className={ratingClass(value)}>{value}</span>
  ) : (
    <span className="subtle">—</span>
  );
}
export function Status({
  status,
  review,
}: {
  status: string;
  review?: boolean;
}) {
  const name =
    status === "completed"
      ? "checkCircle"
      : status === "running" || status === "starting"
        ? "activity"
        : status === "cancelled"
          ? "pause"
          : "warning";
  return (
    <span className={review ? "status-tag warning" : statusClass(status)}>
      <Icon name={name} />
      {review ? "Needs review" : statusLabel(status)}
    </span>
  );
}
export const ANALYST_SECTIONS = [
  "market_report",
  "sentiment_report",
  "news_report",
  "fundamentals_report",
];
export type ResearchRecord = {
  ticker: string;
  date?: string | null;
  status: string;
  rating?: string | null;
  review?: boolean;
  sections?: Record<string, string>;
  metadata?: Record<string, unknown>;
  analysts?: string[];
};
export function recordedStages(
  sections: Record<string, string> = {},
  rating?: string | null,
) {
  const keys = Object.keys(sections),
    has = (...matches: string[]) =>
      keys.some((key) =>
        matches.some((match) => key === match || key.startsWith(match + "/")),
      );
  return [
    has(...ANALYST_SECTIONS, "1_analysts"),
    has("investment_plan", "2_research"),
    has("trader_investment_plan", "3_trading"),
    has("risk_debate", "4_risk"),
    has("final_trade_decision", "5_portfolio") || Boolean(rating),
  ];
}
export function Pipeline({
  record,
  agents = {},
  wallTimes = {},
}: {
  record: ResearchRecord;
  agents?: Record<string, string>;
  wallTimes?: Record<string, number>;
}) {
  const stages = recordedStages(record.sections, record.rating);
  const running = ["starting", "running", "cancelling"].includes(record.status);
  const titles = [
    "Analyst team",
    "Quality gate & debate",
    "Trading plan",
    "Risk review",
    "Final assessment",
  ];
  const copies = [
    record.analysts?.map((key) => ANALYST_LABELS[key] ?? key).join(", ") ||
      "Independent evidence and perspectives",
    "Verify evidence, then debate",
    "Portfolio-aware proposal",
    "Three competing perspectives",
    "Portfolio manager decision",
  ];
  const current = stages.findIndex((done) => !done);
  return (
    <aside className="panel pipeline">
      <p className="panel-kicker">
        A COLLECTIVE PERSPECTIVE <Icon name="layers" />
      </p>
      <h3>From evidence to assessment</h3>
      <div className="pipeline-list">
        {titles.map((title, index) => (
          <div
            className={`pipeline-step ${stages[index] ? "done" : running && current === index ? "active" : ""}`}
            key={title}
          >
            <span className="step-dot">
              {stages[index] ? <Icon name="check" /> : index + 1}
            </span>
            <div className="step-copy">
              <strong>{title}</strong>
              <small>{copies[index]}</small>
              {index === 0 && Object.keys(agents).length ? (
                <small>
                  {Object.entries(agents)
                    .map(
                      ([agent, status]) =>
                        `${agent}: ${status.replaceAll("_", " ")}`,
                    )
                    .join(" · ")}
                </small>
              ) : null}
            </div>
            <span className="step-time">
              {wallTimes[title] == null
                ? "—"
                : `${wallTimes[title].toFixed(1)}s`}
            </span>
          </div>
        ))}
      </div>
      <div className="pipeline-bottom">
        <span>Stages completed</span>
        <strong>{stages.filter(Boolean).length} / 5</strong>
      </div>
    </aside>
  );
}
export function ResearchCard({
  record,
  href,
  running = false,
  onCancel,
}: {
  record: ResearchRecord;
  href: string;
  running?: boolean;
  onCancel?: () => void;
}) {
  const [tab, setTab] = useState("");
  const sections = record.sections ?? {};
  const keys = visibleSectionKeys(sections);
  const available = keys.filter(
    (key) => ANALYST_SECTIONS.includes(key) || key.startsWith("1_analysts/"),
  );
  const active = available.includes(tab) ? tab : (available[0] ?? keys[0]);
  const metadata = record.metadata ?? {};
  const stages = recordedStages(sections, record.rating).filter(Boolean).length;
  function keyboard(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? available.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + available.length) %
            available.length;
    setTab(available[next]);
    event.currentTarget.parentElement
      ?.querySelectorAll<HTMLButtonElement>("button")
      [next]?.focus();
  }
  return (
    <article className="panel featured">
      <div className="featured-top">
        <p className="eyebrow">LATEST RESEARCH</p>
        <Status status={record.status} review={record.review} />
      </div>
      <div className="featured-info">
        <div className="company-heading">
          <CompanyLogo ticker={record.ticker} />
          <div>
            <h2 className="ticker-heading">{record.ticker}</h2>
            <p className="company-name">
              {String(metadata.company_name ?? "Company details not recorded")}
            </p>
          </div>
        </div>
        <div className="rating-box">
          <small>Final assessment</small>
          <Rating value={record.rating} />
        </div>
      </div>
      <div className="research-meta">
        <span>
          <Icon name="calendar" />
          {formatDate(record.date)}
        </span>
        <span>
          <Icon name="layers" />
          {metadata.research_depth == null
            ? "Depth not recorded"
            : `${metadata.research_depth} research`}
        </span>
        <span>
          <Icon name="chip" />
          {String(metadata.llm_provider ?? "Provider not recorded")}
        </span>
        <span>
          <Icon name="globe" />
          {String(metadata.output_language ?? "Language not recorded")}
        </span>
      </div>
      {available.length ? (
        <div
          className="report-tabs"
          role="tablist"
          aria-label="Research perspective"
        >
          {available.map((key, index) => (
            <button
              key={key}
              role="tab"
              type="button"
              className={key === active ? "active" : ""}
              tabIndex={key === active ? 0 : -1}
              aria-selected={key === active}
              onKeyDown={(event) => keyboard(event, index)}
              onClick={() => setTab(key)}
            >
              {sectionLabel(key).replace(/ analysis$/i, "")}
            </button>
          ))}
        </div>
      ) : null}
      <div className="report-preview">
        {running ? (
          <>
            <p className="report-kicker">
              <Icon name="activity" />
              RESEARCH IN PROGRESS
            </p>
            <h3>
              {record.status === "cancelling"
                ? "Stopping the research safely."
                : "Weighing both sides of the thesis."}
            </h3>
            <p>
              The research continues while you explore the workspace. Your
              current report will become available here as each stage finishes.
            </p>
            <div className="progress-track">
              <span style={{ width: `${(stages / 5) * 100}%` }} />
            </div>
            <div className="running-copy">
              <span>{stages} of 5 stages complete</span>
              {onCancel ? (
                <button
                  className="text-button"
                  disabled={record.status === "cancelling"}
                  onClick={onCancel}
                >
                  {record.status === "cancelling"
                    ? "Stopping…"
                    : "Cancel analysis"}
                </button>
              ) : null}
            </div>
            <p className="inline-note">
              The active slot stays occupied until the worker exits. A provider
              call already in flight may finish first.
            </p>
          </>
        ) : (
          <>
            <p className="report-kicker">
              <Icon name="spark" />
              {record.status === "partial"
                ? "PARTIAL REPORT"
                : "THE RESEARCH BRIEF"}
            </p>
            {active ? (
              <div className="research-prose">
                <Markdown>{sections[active]}</Markdown>
              </div>
            ) : (
              <>
                <h3>
                  {record.status === "failed"
                    ? "No final decision is available."
                    : "Read the evidence that is available."}
                </h3>
                <p>No report sections have been recorded for this run.</p>
              </>
            )}
          </>
        )}
      </div>
      <div className="report-footer">
        <span className="team-stack">
          {(
            record.analysts ??
            available.map(
              (key) => key.split("/").pop()?.replace("_report", "") ?? key,
            )
          ).map((key) => (
            <span
              className="team-avatar"
              key={key}
              title={ANALYST_LABELS[key] ?? key}
            >
              {(
                {
                  market: "MK",
                  sentiment: "SE",
                  social: "SE",
                  news: "NW",
                  fundamentals: "FN",
                } as Record<string, string>
              )[key] ?? key.slice(0, 2).toUpperCase()}
            </span>
          ))}
          <span className="team-caption">
            Independent voices. Shared context.
          </span>
        </span>
        <Link className="text-button" to={href}>
          {running ? "Follow analysis" : "Read full analysis"}
          <Icon name="arrow" />
        </Link>
      </div>
    </article>
  );
}

export function ReportDocument({
  record,
  prefix = "section",
}: {
  record: ResearchRecord;
  prefix?: string;
}) {
  const keys = visibleSectionKeys(record.sections),
    metadata = record.metadata ?? {};
  return (
    <div className="report-layout">
      <article className="panel document-panel">
        <div className="company-heading">
          <CompanyLogo ticker={record.ticker} />
          <div>
            <h2 className="ticker-heading">{record.ticker}</h2>
            <p className="company-name">ANALYSIS REPORT</p>
          </div>
        </div>
        <h2>
          {record.status !== "completed"
            ? "The research is incomplete."
            : record.rating === "REVIEW"
              ? "An assessment for your review."
              : "Evidence, examined from every angle."}
        </h2>
        <div className="document-meta">
          <Status status={record.status} review={record.review} />
          <span>{formatDate(record.date)}</span>
          <span>
            {metadata.research_depth == null
              ? "Depth not recorded"
              : `${metadata.research_depth} research`}
          </span>
          <span>
            {String(metadata.llm_provider ?? "Provider not recorded")}
          </span>
          <Rating value={record.rating} />
        </div>
        {keys.length ? (
          keys.map((key) => (
            <section
              className="document-section"
              id={`${prefix}-${key}`}
              key={key}
            >
              <p className="report-kicker">
                <Icon name="file" />
                {sectionLabel(key).toUpperCase()}
              </p>
              <Markdown>{record.sections![key]}</Markdown>
              {key === "final_trade_decision" ? (
                <p className="inline-note">
                  Research output is advisory. A rating is not an order, a
                  guarantee, or an executed position.
                </p>
              ) : null}
            </section>
          ))
        ) : (
          <div className="empty-state">
            <Icon name="file" />
            <strong>No final report available</strong>
            <p>
              No saved sections are available. A failed, cancelled or partial
              run is not a successful analysis.
            </p>
          </div>
        )}
      </article>
      <aside className="panel toc-panel">
        <p className="eyebrow">IN THIS REPORT</p>
        {keys.map((key) => (
          <a key={key} href={`#${prefix}-${key}`}>
            {sectionLabel(key)}
          </a>
        ))}
        <div className="toc-divider" />
        <p className="inline-note">
          Independent perspectives. One considered assessment. Research output
          is advisory.
        </p>
      </aside>
    </div>
  );
}
