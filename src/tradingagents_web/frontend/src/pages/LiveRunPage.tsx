import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-002/007, ADR-007: restore snapshots before consuming subsequent events.
import { useEffect, useState, useSyncExternalStore } from "react";
import { Link, useParams } from "react-router-dom";

import { downloadUrl, getHistoryDetail } from "../api/client";
import { ReportDocument, Status } from "../components/Research";
import { DebatePolicySummary } from "../components/DebateSettings";
import { RunActivity } from "../components/RunActivity";
import { Modal } from "../components/Modal";
import {
  cancelRun,
  getRun,
  runEventsUrl,
  type RunSnapshot,
} from "../api/runClient";
import { Icon } from "../components/Icon";
import { createRunStore, type RunEvent } from "../stores/runStore";
import { formatDate } from "../utils/workspace";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export function LiveRunPage() {
  useUILanguage();
  const { runId = "" } = useParams();
  const [store] = useState(() => createRunStore());
  const state = useSyncExternalStore(
    store.subscribe,
    store.getState,
    store.getState,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [showComplete, setShowComplete] = useState(false);

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
          "analyst.timing",
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
    setShowComplete(false);
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
      debate_termination: snapshot?.debate_termination,
      max_risk_discuss_rounds: snapshot?.max_risk_discuss_rounds,
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
  return (
    <>
      <section className="page-header">
        <div>
          <h1>{ui("{{ticker}} analysis", { ticker: record.ticker })}</h1>
          <p className="page-description">
            {record.date ? ui(formatDate(record.date)) : ui("")}
            {snapshot?.llm_provider
              ? ui(" · {{value0}}", { value0: snapshot.llm_provider })
              : ui("")}
          </p>
        </div>
        <div className="page-header-actions">
          <Status status={status} review={state.review} />
          {running ? (
            <button
              className="button"
              disabled={status === "cancelling"}
              onClick={() => setConfirmCancel(true)}
            >
              <Icon name="stop" />
              {status === "cancelling"
                ? ui("Stopping…")
                : ui("Cancel analysis")}
            </button>
          ) : (
            <>
              {status === "completed" ? (
                <button
                  className="button"
                  onClick={() => setShowComplete(!showComplete)}
                >
                  <Icon name={showComplete ? "activity" : "file"} />
                  {showComplete ? ui("Run activity") : ui("Complete report")}
                </button>
              ) : null}
              <Link className="button ghost" to={`/audit?run_id=${runId}`}>
                <Icon name="shield" />
                {ui("Research audit")}
              </Link>
              {complete ? (
                <a
                  className="button"
                  href={downloadUrl(state.artifactId!, "complete")}
                >
                  <Icon name="download" />
                  {ui("Export report")}
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
            <strong>{ui("Analysis could not finish")}</strong>
            <p>{ui(state.error)}</p>
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
                  debatePolicy: snapshot?.debate_termination,
                  riskRounds: snapshot?.max_risk_discuss_rounds,
                  riskIndependent: true,
                  quick: snapshot?.quick_think_llm,
                  deep: snapshot?.deep_think_llm,
                },
              }}
            >
              {ui("Review setup")}
              <Icon name="arrow" />
            </Link>
          </div>
        </div>
      ) : null}
      {state.review ? (
        <div className="report-state-banner warning">
          <Icon name="warning" />
          <div>
            <strong>{ui("A human perspective is needed")}</strong>
            <p>{ui("REVIEW requires human assessment before acting.")}</p>
          </div>
        </div>
      ) : null}
      {status === "cancelled" ? (
        <div className="report-state-banner warning">
          <Icon name="pause" />
          <div>
            <strong>{ui("Stopped before a final decision")}</strong>
            <p>
              {ui("Available sections and enabled checkpoints are retained.")}
            </p>
          </div>
        </div>
      ) : null}
      {state.warnings.map((warning) => (
        <div className="report-state-banner warning" key={warning}>
          <Icon name="warning" />
          <div>
            <strong>{ui("Analysis completed; report needs attention")}</strong>
            <p>{ui(warning)}</p>
          </div>
        </div>
      ))}
      {actionError ? (
        <p className="field-error" role="alert">
          {ui(actionError)}
        </p>
      ) : null}
      {!showComplete ? (
        <>
          <details className="disclosure report-details">
            <summary>{ui("Analysis settings")}</summary>
            <DebatePolicySummary
              policy={snapshot?.debate_termination}
              riskRounds={snapshot?.max_risk_discuss_rounds}
            />
          </details>
          <RunActivity key={runId} state={state} />
        </>
      ) : null}
      {status === "completed" && showComplete ? (
        <ReportDocument record={record} prefix="live-section" />
      ) : null}
      <Modal
        open={confirmCancel}
        title={ui("Stop this analysis?")}
        onClose={() => setConfirmCancel(false)}
      >
        <p>
          {ui(
            "A provider call already in flight may finish first. The active slot remains occupied until the worker exits. Available sections and enabled checkpoints are retained.",
          )}
        </p>
        <div className="modal-actions">
          <button className="button" onClick={() => setConfirmCancel(false)}>
            {ui("Keep researching")}
          </button>
          <button
            className="button danger"
            onClick={() => {
              setConfirmCancel(false);
              void handleCancel();
            }}
          >
            {ui("Stop analysis")}
          </button>
        </div>
      </Modal>
    </>
  );
}
