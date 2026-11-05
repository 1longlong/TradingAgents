import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getHistory } from "../api/client";
import { LanguageSwitch } from "../components/LanguageSwitch";

export function HistoryPage() {
  const { t } = useTranslation();
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => getHistory({ limit: 50 }),
  });

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-cyan-300">
            {t("app.title")}
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-100">
            {t("history.title")}
          </h1>
          <p className="mt-2 text-sm text-slate-400">{t("app.subtitle")}</p>
        </div>
        <LanguageSwitch />
      </header>

      {history.isLoading ? (
        <p className="text-slate-400">{t("history.loading")}</p>
      ) : history.isError ? (
        <p className="text-red-300">{t("history.error")}</p>
      ) : history.data && history.data.items.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-4 py-3">{t("history.ticker")}</th>
                <th className="px-4 py-3">{t("history.date")}</th>
                <th className="px-4 py-3">{t("history.source")}</th>
                <th className="px-4 py-3">{t("history.status")}</th>
                <th className="px-4 py-3">{t("history.rating")}</th>
                <th className="px-4 py-3">{t("history.actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {history.data.items.map((item) => (
                <tr key={item.artifact_id} className="hover:bg-slate-900/60">
                  <td className="px-4 py-3 font-mono text-slate-200">{item.ticker}</td>
                  <td className="px-4 py-3 text-slate-400">{item.date ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-400">{item.source}</td>
                  <td className="px-4 py-3 text-slate-300">{item.status}</td>
                  <td className="px-4 py-3">
                    <span className={item.review ? "text-amber-300" : "text-slate-300"}>
                      {item.rating ?? "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      className="text-cyan-300 hover:text-cyan-200"
                      to={`/history/${item.artifact_id}`}
                    >
                      {t("history.open")}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-slate-400">{t("history.empty")}</p>
      )}
    </main>
  );
}
