import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { downloadUrl, getHistoryDetail } from "../api/client";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { Markdown } from "../components/Markdown";

export function HistoryDetailPage() {
  const { t } = useTranslation();
  const { artifactId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["history", artifactId],
    queryFn: () => getHistoryDetail(artifactId),
    enabled: Boolean(artifactId),
  });

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/history">
            ← {t("detail.back")}
          </Link>
          <h1 className="mt-3 text-3xl font-semibold text-slate-100">
            {detail.data?.ticker ?? t("detail.title")}
          </h1>
          {detail.data ? (
            <p className="mt-2 text-sm text-slate-400">
              {detail.data.date ?? "—"} · {detail.data.source} · {detail.data.status}
            </p>
          ) : null}
        </div>
        <LanguageSwitch />
      </header>

      {detail.isLoading ? <p className="text-slate-400">{t("history.loading")}</p> : null}
      {detail.isError ? <p className="text-red-300">{t("detail.missing")}</p> : null}

      {detail.data ? (
        <section className="space-y-6">
          <div className="flex flex-wrap gap-3">
            {detail.data.artifacts?.some((item) => item.kind === "complete") ? (
              <a
                className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
                href={downloadUrl(detail.data.artifact_id, "complete")}
              >
                {t("detail.complete")}
              </a>
            ) : null}
            {detail.data.artifacts?.some((item) => item.kind === "archive") ? (
              <a
                className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
                href={downloadUrl(detail.data.artifact_id, "archive")}
              >
                {t("detail.archive")}
              </a>
            ) : null}
          </div>

          {detail.data.sections
            ? Object.entries(detail.data.sections).map(([section, content]) => (
                <article key={section} className="rounded-lg border border-slate-800 p-5">
                  <h2 className="mb-3 font-mono text-xs uppercase tracking-wide text-cyan-300">
                    {section}
                  </h2>
                  <Markdown>{content}</Markdown>
                </article>
              ))
            : null}

          {detail.data.summary ? (
            <article className="rounded-lg border border-slate-800 p-5">
              <h2 className="mb-3 text-sm uppercase tracking-wide text-cyan-300">
                {t("detail.title")}
              </h2>
              <pre className="overflow-auto text-xs text-slate-300">
                {JSON.stringify(detail.data.summary, null, 2)}
              </pre>
            </article>
          ) : null}

          {detail.data.entries ? (
            <article className="rounded-lg border border-slate-800 p-5">
              <h2 className="mb-3 text-sm uppercase tracking-wide text-cyan-300">
                {t("detail.title")}
              </h2>
              <ul className="space-y-3 text-sm text-slate-300">
                {detail.data.entries.map((entry, index) => (
                  <li key={index} className="border-b border-slate-800 pb-3">
                    <span className="font-mono text-slate-200">
                      {String(entry.ticker ?? "")} {String(entry.date ?? "")}
                    </span>
                    <span className="ml-3 text-slate-400">{String(entry.rating ?? "")}</span>
                  </li>
                ))}
              </ul>
            </article>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
