import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-010, ADR-003, INV-WEB-011: read-only decisions, outcomes and reflections.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Modal } from "../components/Modal";
import { Markdown } from "../components/Markdown";
import { CompanyLogo } from "../components/Research";

import { getAllHistory, getHistoryDetail } from "../api/client";
import { Icon } from "../components/Icon";
import { formatDate, ratingClass } from "../utils/workspace";

export function JournalPage() {
  useUILanguage();
  const history = useQuery({
    queryKey: ["history", "journal"],
    queryFn: getAllHistory,
  });
  const decision = history.data?.items.find(
    (item) => item.source === "decision",
  );
  const detail = useQuery({
    queryKey: ["history", "decision", decision?.artifact_id],
    queryFn: () => getHistoryDetail(decision?.artifact_id ?? ""),
    enabled: Boolean(decision?.artifact_id),
  });

  const entries = detail.data?.entries ?? [];
  const [selected, setSelected] = useState<Record<string, unknown> | null>(
    null,
  );

  return (
    <>
      <section className="page-header">
        <div>
          <h1>{ui("Decision journal")}</h1>
        </div>
      </section>

      {history.isLoading || detail.isLoading ? (
        <div className="panel empty-state">{ui("Loading decision log...")}</div>
      ) : history.isError || detail.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>{ui("Decision log unavailable")}</strong>
          <p>{ui((history.error ?? detail.error)?.message)}</p>
        </div>
      ) : !decision ? (
        <div className="panel empty-state">
          <Icon name="book" />
          <strong>{ui("No decision log found")}</strong>
          <p>
            {ui(
              "The configured live decision memory does not exist yet. Run an analysis to create the first entry.",
            )}
          </p>
        </div>
      ) : entries.length === 0 ? (
        <div className="panel empty-state">
          <Icon name="book" />
          <strong>{ui("No decision entries")}</strong>
          <p>{ui("The decision log exists but contains no entries.")}</p>
        </div>
      ) : (
        <section className="journal-list">
          {entries.map((entry, index) => {
            const rating = String(entry.rating ?? "—");
            return (
              <article
                className="panel journal-entry"
                key={`${String(entry.ticker)}-${String(entry.date)}-${index}`}
              >
                <CompanyLogo ticker={String(entry.ticker ?? "?")} />
                <div>
                  <h2>{String(entry.ticker ?? "")}</h2>
                  <p>{decisionText(String(entry.decision ?? ""))}</p>
                  <span className="eyebrow">
                    {ui(formatDate(String(entry.date ?? "")))}
                    {ui(" ·")}
                    {ui(" ")}
                    {rating === "REVIEW"
                      ? ui("UNSCORED / REVIEW")
                      : entry.pending
                        ? ui("PENDING OUTCOME")
                        : ui("RESOLVED {{value0}}", {
                            value0: String(entry.resolved ?? ""),
                          })}
                    {ui(" ")}
                    {entry.holding
                      ? ui("· {{value0}}", { value0: String(entry.holding) })
                      : ui(null)}
                  </span>
                  <button
                    className="text-button"
                    onClick={() => setSelected(entry)}
                  >
                    {ui("Read decision & outcome")}
                    <Icon name="arrow" />
                  </button>
                </div>
                <span className={ratingClass(rating)}>{ui(rating)}</span>
              </article>
            );
          })}
        </section>
      )}
      <Modal
        open={Boolean(selected)}
        title={ui("{{value0}} decision", {
          value0: String(selected?.ticker ?? ""),
        })}
        onClose={() => setSelected(null)}
      >
        {selected ? (
          <>
            <p className="eyebrow">
              {ui("LIVE DECISION LOG · ")}
              {ui(formatDate(String(selected.date ?? "")))}
            </p>
            <span className={ratingClass(String(selected.rating ?? ""))}>
              {ui(String(selected.rating ?? "—"))}
            </span>
            <h3>{ui("Original decision")}</h3>
            <Markdown>
              {String(selected.decision ?? ui("Not recorded"))}
            </Markdown>
            <h3>{ui("Outcome")}</h3>
            <p>
              {selected.pending
                ? ui("Pending. No realized return or alpha is available.")
                : ui(
                    "Return {{value0}} · Alpha {{value1}} · Holding {{value2}} · Resolved {{value3}}",
                    {
                      value0: String(selected.raw ?? "Not recorded"),
                      value1: String(selected.alpha ?? "Not recorded"),
                      value2: String(selected.holding ?? "Not recorded"),
                      value3: String(selected.resolved ?? "Not recorded"),
                    },
                  )}
            </p>
            <h3>{ui("Reflection")}</h3>
            <Markdown>
              {String(selected.reflection || ui("No reflection recorded."))}
            </Markdown>
          </>
        ) : null}
      </Modal>
    </>
  );
}

function decisionText(value: string): string {
  return value
    .replace(/^\*\*Rating\*\*:.*\n?/i, "")
    .replace(/\*\*/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 280);
}
