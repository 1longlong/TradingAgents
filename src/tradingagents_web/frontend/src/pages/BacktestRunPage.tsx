import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { downloadUrl } from "../api/client";
import { getBacktest } from "../api/backtestClient";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { BacktestSummary } from "./Backtest/BacktestSummary";

const TERMINAL = new Set(["completed", "failed"]);

export function BacktestRunPage() {
  const { t } = useTranslation();
  const { runId = "" } = useParams();
  const query = useQuery({
    queryKey: ["backtest", runId],
    queryFn: () => getBacktest(runId),
    enabled: Boolean(runId),
    refetchInterval: (current) =>
      current.state.data && TERMINAL.has(current.state.data.status) ? false : 1000,
  });

  const snapshot = query.data;

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/backtest">
            ← {t("backtest.title")}
          </Link>
          <h1 className="mt-3 text-3xl font-semibold text-slate-100">
            {t("backtest.title")}
          </h1>
          <p className="mt-2 font-mono text-xs text-slate-400">
            {t("live.runId")}: {runId}
            {snapshot ? ` · ${t("live.status")}: ${snapshot.status}` : null}
          </p>
        </div>
        <LanguageSwitch />
      </header>

      {query.isLoading ? (
        <p className="text-slate-400">{t("backtest.running")}</p>
      ) : query.isError ? (
        <p className="text-red-300">{t("detail.missing")}</p>
      ) : null}

      {snapshot?.status === "running" || snapshot?.status === "starting" ? (
        <section className="mb-6 rounded-md border border-slate-700 px-4 py-3 text-sm text-slate-300">
          <p>{t("backtest.running")}</p>
          <p className="mt-1 text-slate-400">{t("backtest.noCancel")}</p>
        </section>
      ) : null}

      {snapshot?.error ? (
        <p className="mb-6 rounded-md border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {String(snapshot.error.message ?? t("live.failed"))}
        </p>
      ) : null}

      {snapshot?.summary ? <BacktestSummary summary={snapshot.summary} /> : null}

      {snapshot?.summary?.log_artifact_id ? (
        <div className="mt-6">
          <a
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
            href={downloadUrl(snapshot.summary.log_artifact_id, "log")}
          >
            {t("backtest.log")}
          </a>
        </div>
      ) : null}
    </main>
  );
}
