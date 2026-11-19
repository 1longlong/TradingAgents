// REQ-WEB-002/007, ADR-007: restore snapshots before consuming subsequent events.
import { useEffect, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { cancelRun, getRun, runEventsUrl } from "../api/runClient";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { Markdown } from "../components/Markdown";
import { createRunStore, type RunEvent } from "../stores/runStore";

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

  const status = state.status;
  const canCancel = !TERMINAL.has(status);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <Link
            className="text-sm text-cyan-300 hover:text-cyan-200"
            to="/history"
          >
            ← {t("nav.history")}
          </Link>
          <h1 className="mt-3 text-3xl font-semibold text-slate-100">
            {t("live.title")}
          </h1>
          <p className="mt-2 font-mono text-xs text-slate-400">
            {t("live.runId")}: {runId} · {t("live.status")}: {status} ·{" "}
            {t("live.connection")}: {state.connection}
          </p>
        </div>
        <LanguageSwitch />
      </header>

      {state.review ? (
        <p className="mb-5 rounded-md border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {t("live.review")}
        </p>
      ) : null}
      {state.error ? (
        <p role="alert" className="mb-5 text-sm text-red-300">
          {state.error}
        </p>
      ) : null}
      {state.warnings.map((warning) => (
        <p key={warning} className="mb-3 text-amber-300">
          {warning}
        </p>
      ))}
      {state.signal ? (
        <p className="mb-4 text-lg text-slate-100">
          {t("history.rating")}: {state.signal}
        </p>
      ) : null}
      <p className="mb-4 text-sm text-slate-400">
        {t(`live.phases.${state.phase}`, { defaultValue: state.phase })}
      </p>
      {Object.keys(state.agents).length > 0 ? (
        <ul className="mb-4 flex flex-wrap gap-3 text-sm text-slate-300">
          {Object.entries(state.agents).map(([agent, status]) => (
            <li key={agent}>
              {agent}: {status}
            </li>
          ))}
        </ul>
      ) : null}
      {Object.keys(state.stats).length > 0 ? (
        <p className="mb-4 text-sm text-slate-300">
          {t("live.stats")}:{" "}
          {Object.entries(state.stats)
            .map(([key, value]) => `${key}: ${value}`)
            .join(" · ")}
        </p>
      ) : null}
      {state.artifactId ? (
        <Link
          className="mb-5 block text-cyan-300"
          to={`/history/${state.artifactId}`}
        >
          {t("report.complete")}
        </Link>
      ) : null}
      {actionError ? (
        <p className="mb-5 text-sm text-red-300">{actionError}</p>
      ) : null}

      <div className="mb-6 flex flex-wrap gap-3">
        <button
          type="button"
          className="rounded-md border border-red-500/60 px-3 py-1.5 text-sm text-red-200 hover:bg-red-500/10 disabled:opacity-40"
          disabled={!canCancel}
          onClick={() => void handleCancel()}
        >
          {status === "cancelling" ? t("live.cancelling") : t("live.cancel")}
        </button>
        <Link
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
          to="/history"
        >
          {t("nav.history")}
        </Link>
      </div>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-800 p-5">
          <h2 className="mb-3 text-sm uppercase tracking-wide text-cyan-300">
            {t("live.messages")}
          </h2>
          {state.messages.length === 0 ? (
            <p className="text-sm text-slate-400">{t("live.waiting")}</p>
          ) : (
            <ul className="max-h-[28rem] space-y-2 overflow-auto text-sm">
              {state.messages.map((message) => (
                <li key={message.id} className="border-b border-slate-800 pb-2">
                  <span className="font-mono text-xs text-slate-500">
                    {message.timestamp ?? ""} {message.type ?? ""}
                  </span>
                  <p className="mt-1 text-slate-300">{message.content}</p>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-lg border border-slate-800 p-5">
          <h2 className="mb-3 text-sm uppercase tracking-wide text-cyan-300">
            {t("live.progress")}
          </h2>
          {Object.keys(state.sections).length === 0 ? (
            <p className="text-sm text-slate-400">{t("live.waiting")}</p>
          ) : (
            <div className="max-h-[28rem] space-y-4 overflow-auto">
              {Object.entries(state.sections).map(([section, content]) => (
                <article key={section}>
                  <h3 className="mb-2 font-mono text-xs text-slate-400">
                    {section}
                  </h3>
                  <Markdown>{content}</Markdown>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
