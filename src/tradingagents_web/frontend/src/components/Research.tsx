import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-002/008/010, ADR-003: presentation of recorded reports; no inferred facts.
import { useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { Icon } from "./Icon";
import { Markdown } from "./Markdown";
import { DebatePolicySummary } from "./DebateSettings";
import {
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
  useUILanguage();
  return (
    <span className={`company-logo ${small ? "small" : ""}`}>
      {ticker === "NVDA" ? <Icon name="chip" /> : ticker.slice(0, 1)}
    </span>
  );
}
export function Rating({ value }: { value?: string | null }) {
  useUILanguage();
  return value ? (
    <span className={ratingClass(value)}>{ui(value)}</span>
  ) : (
    <span className="subtle">{ui("—")}</span>
  );
}
export function Status({
  status,
  review,
}: {
  status: string;
  review?: boolean;
}) {
  useUILanguage();
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
      {review ? ui("Needs review") : ui(statusLabel(status))}
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
  useUILanguage();
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
        <p className="eyebrow">{ui("LATEST RESEARCH")}</p>
        <Status status={record.status} review={record.review} />
      </div>
      <div className="featured-info">
        <div className="company-heading">
          <CompanyLogo ticker={record.ticker} />
          <div>
            <h2 className="ticker-heading">{record.ticker}</h2>
            {metadata.company_name ? (
              <p className="company-name">{String(metadata.company_name)}</p>
            ) : null}
          </div>
        </div>
        <div className="rating-box">
          <small>{ui("Final assessment")}</small>
          <Rating value={record.rating} />
        </div>
      </div>
      <div className="research-meta">
        <span>
          <Icon name="calendar" />
          {ui(formatDate(record.date))}
        </span>
        {metadata.llm_provider ? (
          <span>
            <Icon name="chip" />
            {String(metadata.llm_provider)}
          </span>
        ) : null}
      </div>
      {available.length ? (
        <div
          className="report-tabs"
          role="tablist"
          aria-label={ui("Research perspective")}
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
              {ui(sectionLabel(key).replace(/ analysis$/i, ""))}
            </button>
          ))}
        </div>
      ) : null}
      <div className="report-preview">
        {running ? (
          <>
            <p className="report-kicker">
              <Icon name="activity" />
              {ui("RESEARCH IN PROGRESS")}
            </p>
            <h3>
              {record.status === "cancelling"
                ? ui("Stopping the research safely.")
                : ui("Analysis in progress")}
            </h3>
            <div className="progress-track">
              <span style={{ width: `${(stages / 5) * 100}%` }} />
            </div>
            <div className="running-copy">
              <span>
                {stages}
                {ui(" of 5 stages complete")}
              </span>
              {onCancel ? (
                <button
                  className="text-button"
                  disabled={record.status === "cancelling"}
                  onClick={onCancel}
                >
                  {record.status === "cancelling"
                    ? ui("Stopping…")
                    : ui("Cancel analysis")}
                </button>
              ) : null}
            </div>
          </>
        ) : (
          <>
            <p className="report-kicker">
              <Icon name="spark" />
              {record.status === "partial"
                ? ui("PARTIAL REPORT")
                : ui("THE RESEARCH BRIEF")}
            </p>
            {active ? (
              <div className="research-prose">
                <Markdown>{sections[active]}</Markdown>
              </div>
            ) : (
              <>
                <h3>
                  {record.status === "failed"
                    ? ui("No final decision is available.")
                    : ui("Read the evidence that is available.")}
                </h3>
                <p>
                  {ui("No report sections have been recorded for this run.")}
                </p>
              </>
            )}
          </>
        )}
      </div>
      <div className="report-footer">
        <Link className="text-button" to={href}>
          {running ? ui("Follow analysis") : ui("Read full analysis")}
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
  useUILanguage();
  const keys = visibleSectionKeys(record.sections),
    metadata = record.metadata ?? {};
  return (
    <div className="report-layout">
      <article className="panel document-panel">
        <div className="company-heading">
          <CompanyLogo ticker={record.ticker} />
          <div>
            <h2 className="ticker-heading">{record.ticker}</h2>
            <p className="company-name">{ui("ANALYSIS REPORT")}</p>
          </div>
        </div>
        <div className="document-meta">
          <Status status={record.status} review={record.review} />
          <span>{ui(formatDate(record.date))}</span>
          <Rating value={record.rating} />
        </div>
        <details className="disclosure report-details">
          <summary>{ui("Analysis settings")}</summary>
          {metadata.llm_provider ? (
            <p>{String(metadata.llm_provider)}</p>
          ) : null}
          <DebatePolicySummary
            policy={metadata.debate_termination}
            riskRounds={
              typeof metadata.max_risk_discuss_rounds === "number"
                ? metadata.max_risk_discuss_rounds
                : undefined
            }
          />
        </details>
        <p className="helper">{ui("Research output is advisory.")}</p>
        {keys.length ? (
          keys.map((key) => (
            <section
              className="document-section"
              id={`${prefix}-${key}`}
              key={key}
            >
              <p className="report-kicker">
                <Icon name="file" />
                {ui(sectionLabel(key).toUpperCase())}
              </p>
              <Markdown>{record.sections![key]}</Markdown>
            </section>
          ))
        ) : (
          <div className="empty-state">
            <Icon name="file" />
            <strong>{ui("No final report available")}</strong>
            <p>
              {ui(
                "No saved sections are available. A failed, cancelled or partial run is not a successful analysis.",
              )}
            </p>
          </div>
        )}
      </article>
      <aside className="panel toc-panel">
        <p className="eyebrow">{ui("IN THIS REPORT")}</p>
        {keys.map((key) => (
          <a key={key} href={`#${prefix}-${key}`}>
            {ui(sectionLabel(key))}
          </a>
        ))}
      </aside>
    </div>
  );
}
