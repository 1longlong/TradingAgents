// REQ-WEB-002/007, ADR-007: restore snapshots before consuming subsequent events.
import { useEffect, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { downloadUrl, getHistoryDetail } from "../api/client";
import { ResearchCard, Pipeline, ReportDocument } from "../components/Research";
import { Modal } from "../components/Modal";
import {
  cancelRun,
  getRun,
  runEventsUrl,
  type RunSnapshot,
} from "../api/runClient";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { createRunStore, type RunEvent } from "../stores/runStore";
import { sectionLabel } from "../utils/workspace";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export function LiveRunPage() {
  const { t } = useTranslation();
  const { runId = "" } = useParams();
  const [store] = useState(() => createRunStore());
  const state = useSyncExternalStore(
    store.subscribe,
    store.getState,
    store.getState,
  );
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let source: EventSource | null = null;
    let stopped = false;

    async function connect() {
      try {
        const snapshot = (await getRun(runId)) as unknown as Record<
          string,
          unknown
        >;
        if (stopped) return;
        setSnapshot(snapshot as unknown as RunSnapshot);
        store.getState().applySnapshot(snapshot);
        if (TERMINAL.has(String(snapshot.status))) return;
        store.getState().setConnection("connecting");
        source = new EventSource(
          runEventsUrl(runId, Number(snapshot.last_seq ?? 0)),
        );
        source.onopen = () => store.getState().setConnection("live");
        source.onerror = () => store.getState().setConnection("reconnecting");

        const handleEvent = (message: MessageEvent) => {
          try {
            const event = JSON.parse(message.data) as RunEvent;
            store.getState().applyEvent(event);
            if (TERMINAL.has(store.getState().status)) {
              source?.close();
              store.getState().setConnection("closed");
            }
          } catch {
            // Ignore malformed frames; the next valid event continues the stream.
          }
        };

        for (const eventType of [
          "run.preparing",
          "run.phase",
          "run.started",
          "run.resumed",
          "agent.status",
          "message",
          "tool_call",
          "report.section",
          "stats",
          "run.completed",
          "run.failed",
          "run.cancelled",
          "snapshot",
        ]) {
          source.addEventListener(eventType, handleEvent as EventListener);
        }
      } catch (exc) {
        store.getState().applySnapshot({
          run_id: runId,
          status: "failed",
          last_seq: 0,
          error: exc instanceof Error ? exc.message : String(exc),
        });
      }
    }

    store.getState().reset();
    setSnapshot(null);
    void connect();
    return () => {
      stopped = true;
      source?.close();
    };
  }, [runId, store]);

  async function handleCancel() {
    setActionError(null);
    try {
      const snapshot = await cancelRun(runId);
      store
        .getState()
        .applySnapshot(snapshot as unknown as Record<string, unknown>);
    } catch (exc) {
      setActionError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  const [filter, setFilter] = useState("all");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const status = state.status;
  const running = !TERMINAL.has(status);
  const record = {
    ticker: snapshot?.ticker ?? "Research",
    date: snapshot?.trade_date,
    status,
    rating: state.signal,
    review: state.review,
    sections: state.sections,
    analysts: snapshot?.analysts,
    metadata: {
      research_depth: snapshot?.research_depth,
      llm_provider: snapshot?.llm_provider,
      output_language: snapshot?.output_language,
    },
  };
  const [complete, setComplete] = useState(false);
  useEffect(() => {
    let mounted = true;
    setComplete(false);
    if (state.artifactId)
      void getHistoryDetail(state.artifactId)
        .then((detail) => {
          if (mounted)
            setComplete(
              Boolean(
                detail.artifacts?.some((item) => item.kind === "complete"),
              ),
            );
        })
        .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [state.artifactId]);
  const events = state.messages.filter(
    (message) =>
      filter === "all" ||
      (filter === "tool_call"
        ? message.type === "Tool"
        : message.type !== "Tool"),
  );
  return (
    <>
      <section className="page-header">
        <div>
          <p className="eyebrow">
            {running ? "ACTIVE RESEARCH" : "RESEARCH / " + record.ticker}
          </p>
          <h1>{record.ticker} analysis</h1>
          <p className="page-description">
            A collective review of {record.ticker}.
          </p>
        </div>
        <div className="page-header-actions">
          {running ? (
            <button
              className="button"
              disabled={status === "cancelling"}
              onClick={() => setConfirmCancel(true)}
            >
              <Icon name="stop" />
              {status === "cancelling" ? "Stopping…" : "Cancel analysis"}
            </button>
          ) : (
            <>
              <Link className="button ghost" to="/history">
                <Icon name="clock" />
                History
              </Link>
              <Link className="button ghost" to={`/audit?run_id=${runId}`}>
                <Icon name="shield" />
                Research audit
              </Link>
              {complete ? (
                <a
                  className="button"
                  href={downloadUrl(state.artifactId!, "complete")}
                >
                  <Icon name="download" />
                  Export report
                </a>
              ) : null}
            </>
          )}
        </div>
      </section>
      {state.error ? (
        <div className="report-state-banner warning" role="alert">
          <Icon name="warning" />
          <div>
            <strong>Analysis could not finish</strong>
            <p>{state.error}</p>
            <Link
              className="text-button"
              to="/new"
              state={{
                setup: {
                  ticker: record.ticker,
                  date: record.date,
                  asset: snapshot?.asset_type,
                  provider: snapshot?.llm_provider,
                  analysts: snapshot?.analysts,
                  depth: snapshot?.research_depth,
                  quick: snapshot?.quick_think_llm,
                  deep: snapshot?.deep_think_llm,
                },
              }}
            >
              Review setup
              <Icon name="arrow" />
            </Link>
          </div>
        </div>
      ) : null}
      {state.review ? (
        <div className="report-state-banner warning">
          <Icon name="warning" />
          <div>
            <strong>A human perspective is needed</strong>
            <p>
              The result is flagged as REVIEW. It has not been converted to Hold
              or treated as a position.
            </p>
          </div>
        </div>
      ) : null}
      {status === "cancelled" ? (
        <div className="report-state-banner warning">
          <Icon name="pause" />
          <div>
            <strong>Stopped before a final decision</strong>
            <p>
              Any sections and enabled checkpoint already written are retained;
              no final decision is recorded. Recovery requires matching inputs,
              including portfolio context.
            </p>
          </div>
        </div>
      ) : null}
      {state.warnings.map((warning) => (
        <div className="report-state-banner warning" key={warning}>
          <Icon name="warning" />
          <div>
            <strong>Analysis completed; report needs attention</strong>
            <p>{warning}</p>
          </div>
        </div>
      ))}
      {actionError ? (
        <p className="field-error" role="alert">
          {actionError}
        </p>
      ) : null}
      {running ? (
        <>
          <section className="research-grid">
            <ResearchCard
              record={record}
              href={`/runs/${runId}`}
              running
              onCancel={() => setConfirmCancel(true)}
            />
            <Pipeline
              record={record}
              agents={state.agents}
              wallTimes={snapshot?.wall_times}
            />
          </section>
          <div className="report-state-banner">
            <Icon name="activity" />
            <div>
              <strong>Research continues in the background</strong>
              <p>
                You can return to the overview without cancelling this run. The
                workspace accepts one active analysis or backtest at a time.
                Stage counts describe completed work, not a time estimate.
              </p>
            </div>
          </div>
        </>
      ) : null}
      {running ? (
        <section className="panel audit-card run-activity">
          <div className="audit-section-head">
            <div>
              <p className="eyebrow">RUN ACTIVITY</p>
              <h2>Follow the work as it happens.</h2>
              <p>
                Status: {status} · Connection: {state.connection} ·{" "}
                {t(`live.phases.${state.phase}`, { defaultValue: state.phase })}
              </p>
            </div>
            <label className="audit-scenario">
              <span className="sr-only">Filter activity</span>
              <select
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
              >
                <option value="all">All events</option>
                <option value="message">Messages</option>
                <option value="tool_call">Tool calls</option>
              </select>
            </label>
          </div>
          <div className="activity-stats">
            {[
              ["Model calls", state.stats.llm_calls],
              ["Tool calls", state.stats.tool_calls],
              ["Input tokens", state.stats.tokens_in],
              ["Output tokens", state.stats.tokens_out],
              [
                "Report stages",
                state.stats.reports_completed == null
                  ? undefined
                  : `${state.stats.reports_completed} / ${state.stats.reports_total ?? "—"}`,
              ],
              [
                "Elapsed",
                state.stats.elapsed == null
                  ? undefined
                  : `${state.stats.elapsed.toFixed(1)}s`,
              ],
            ].map(([key, value]) => (
              <div key={key}>
                <small>{key}</small>
                <strong>
                  {value == null
                    ? "—"
                    : typeof value === "number"
                      ? value.toLocaleString()
                      : value}
                </strong>
              </div>
            ))}
          </div>
          <div className="activity-events">
            {events.length ? (
              events.map((message) => (
                <article key={message.id}>
                  <span>
                    <Icon name={message.type === "Tool" ? "sliders" : "file"} />
                  </span>
                  <div>
                    <strong>
                      {message.type === "Tool"
                        ? "Tool call"
                        : (message.type ?? "Message")}
                    </strong>
                    <p>{message.content}</p>
                    <small>{message.timestamp}</small>
                  </div>
                  <span className="audit-badge">
                    {message.type === "Tool" ? "Tool" : "Message"}
                  </span>
                </article>
              ))
            ) : (
              <div className="empty-state">
                <strong>
                  {filter === "all"
                    ? "Waiting for activity"
                    : "No events of this type yet."}
                </strong>
                <p>Recorded activity will appear here as the run progresses.</p>
              </div>
            )}
          </div>
        </section>
      ) : null}
      {running ? (
        Object.keys(state.sections).length ? (
          <article className="panel document-panel">
            <p className="eyebrow">AVAILABLE SECTIONS · LIVE REPORT</p>
            {Object.entries(state.sections).map(([key, content]) => (
              <section
                className="document-section"
                id={`live-section-${key}`}
                key={key}
              >
                <p className="report-kicker">
                  <Icon name="file" />
                  {sectionLabel(key).toUpperCase()}
                </p>
                <Markdown>{content}</Markdown>
              </section>
            ))}
          </article>
        ) : null
      ) : (
        <ReportDocument record={record} prefix="live-section" />
      )}
      <Modal
        open={confirmCancel}
        title="Stop this analysis?"
        onClose={() => setConfirmCancel(false)}
      >
        <p>
          A provider call already in flight may finish first. The active slot
          remains occupied until the worker exits. Available sections and
          enabled checkpoints are retained.
        </p>
        <div className="modal-actions">
          <button className="button" onClick={() => setConfirmCancel(false)}>
            Keep researching
          </button>
          <button
            className="button danger"
            onClick={() => {
              setConfirmCancel(false);
              void handleCancel();
            }}
          >
            Stop analysis
          </button>
        </div>
      </Modal>
    </>
  );
}
