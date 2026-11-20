// REQ-WEB-010, ADR-003, INV-WEB-011: read-only decisions, outcomes and reflections.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Modal } from "../components/Modal";
import { Markdown } from "../components/Markdown";
import { CompanyLogo } from "../components/Research";
import { Link } from "react-router-dom";

import { getAllHistory, getHistoryDetail } from "../api/client";
import { Icon } from "../components/Icon";
import { formatDate, ratingClass } from "../utils/workspace";

export function JournalPage() {
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
          <p className="eyebrow">A RECORD OF YOUR REASONING</p>
          <h1>Decision journal</h1>
          <p className="page-description">
            Read-only decisions, outcomes and reflections from the live decision
            log.
          </p>
        </div>
        <div className="page-header-actions">
          <Link className="button ghost" to="/history">
            <Icon name="folder" />
            All research
          </Link>
        </div>
      </section>

      <div className="report-state-banner">
        <Icon name="book" />
        <div>
          <strong>Decisions and reports are separate records.</strong>
          <p>
            A log entry contains the final decision and any later outcome or
            reflection. It does not guarantee a full report or an exact report
            link. Backtest logs remain separate.
          </p>
        </div>
      </div>

      {history.isLoading || detail.isLoading ? (
        <div className="panel empty-state">Loading decision log...</div>
      ) : history.isError || detail.isError ? (
        <div className="panel empty-state" role="alert">
          <strong>Decision log unavailable</strong>
          <p>{(history.error ?? detail.error)?.message}</p>
        </div>
      ) : !decision ? (
        <div className="panel empty-state">
          <Icon name="book" />
          <strong>No decision log found</strong>
          <p>
            The configured live decision memory does not exist yet. Run an
            analysis to create the first entry.
          </p>
        </div>
      ) : entries.length === 0 ? (
        <div className="panel empty-state">
          <Icon name="book" />
          <strong>No decision entries</strong>
          <p>The decision log exists but contains no entries.</p>
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
                    {formatDate(String(entry.date ?? ""))} ·{" "}
                    {rating === "REVIEW"
                      ? "UNSCORED / REVIEW"
                      : entry.pending
                        ? "PENDING OUTCOME"
                        : `RESOLVED ${String(entry.resolved ?? "")}`}{" "}
                    {entry.holding ? `· ${String(entry.holding)}` : null}
                  </span>
                  <button
                    className="text-button"
                    onClick={() => setSelected(entry)}
                  >
                    Read decision & outcome
                    <Icon name="arrow" />
                  </button>
                </div>
                <span className={ratingClass(rating)}>{rating}</span>
              </article>
            );
          })}
        </section>
      )}
      <Modal
        open={Boolean(selected)}
        title={`${String(selected?.ticker ?? "")} decision`}
        onClose={() => setSelected(null)}
      >
        {selected ? (
          <>
            <p className="eyebrow">
              LIVE DECISION LOG · {formatDate(String(selected.date ?? ""))}
            </p>
            <span className={ratingClass(String(selected.rating ?? ""))}>
              {String(selected.rating ?? "—")}
            </span>
            <h3>Original decision</h3>
            <Markdown>{String(selected.decision ?? "Not recorded")}</Markdown>
            <h3>Outcome</h3>
            <p>
              {selected.pending
                ? "Pending. No realized return or alpha is available."
                : `Return ${String(selected.raw ?? "Not recorded")} · Alpha ${String(selected.alpha ?? "Not recorded")} · Holding ${String(selected.holding ?? "Not recorded")} · Resolved ${String(selected.resolved ?? "Not recorded")}`}
            </p>
            <h3>Reflection</h3>
            <Markdown>
              {String(selected.reflection || "No reflection recorded.")}
            </Markdown>
            <p className="inline-note">
              Read-only log entry. No report association or manual rating update
              is assumed.
            </p>
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
