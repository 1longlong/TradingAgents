import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { listBacktests, startBacktest } from "../api/backtestClient";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { validateBacktest } from "./Backtest/validation";

const ANALYSTS = ["market", "social", "news", "fundamentals"] as const;

export function BacktestPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tickers, setTickers] = useState("NVDA");
  const [start, setStart] = useState("2026-06-01");
  const [end, setEnd] = useState("2026-06-08");
  const [every, setEvery] = useState("7");
  const [analysts, setAnalysts] = useState<string[]>([...ANALYSTS]);
  const [assetType, setAssetType] = useState("stock");
  const [portfolioJson, setPortfolioJson] = useState("");
  const [runId, setRunId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const existing = useQuery({
    queryKey: ["backtests"],
    queryFn: listBacktests,
    retry: false,
  });

  function toggleAnalyst(name: string) {
    setAnalysts((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  }

  async function submit() {
    const names = tickers
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const result = validateBacktest({
      tickers: names,
      start,
      end,
      every: Number(every),
      analysts,
      assetType,
      portfolioJson,
      runId,
    });
    if (!result.ok) {
      setError(result.error ?? t("wizard.invalid"));
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const snapshot = await startBacktest({
        tickers: names,
        start,
        end,
        every: Number(every),
        analysts,
        asset_type: assetType,
        portfolio_json: portfolioJson.trim() || null,
        run_id: runId.trim() || null,
      });
      navigate(`/backtest/${snapshot.run_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/history">
            ← {t("nav.history")}
          </Link>
          <h1 className="mt-3 text-3xl font-semibold text-slate-100">
            {t("backtest.title")}
          </h1>
          <p className="mt-2 text-sm text-slate-400">{t("backtest.noCancel")}</p>
        </div>
        <LanguageSwitch />
      </header>

      <section className="space-y-5 rounded-lg border border-slate-800 p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm text-slate-300" htmlFor="backtest-tickers">
              {t("backtest.tickers")}
            </label>
            <input
              id="backtest-tickers"
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={tickers}
              onChange={(event) => setTickers(event.target.value)}
              placeholder="NVDA,AAPL"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-300" htmlFor="backtest-run-id">
              {t("backtest.runId")}
            </label>
            <input
              id="backtest-run-id"
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
              placeholder="optional"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-300" htmlFor="backtest-start">
              {t("backtest.start")}
            </label>
            <input
              id="backtest-start"
              type="date"
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={start}
              onChange={(event) => setStart(event.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm text-slate-300" htmlFor="backtest-end">
              {t("backtest.end")}
            </label>
            <input
              id="backtest-end"
              type="date"
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm text-slate-300" htmlFor="backtest-every">
              {t("backtest.every")}
            </label>
            <input
              id="backtest-every"
              type="number"
              min={1}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={every}
              onChange={(event) => setEvery(event.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm text-slate-300" htmlFor="backtest-asset">
              {t("backtest.assetType")}
            </label>
            <select
              id="backtest-asset"
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={assetType}
              onChange={(event) => setAssetType(event.target.value)}
            >
              <option value="stock">stock</option>
              <option value="crypto">crypto</option>
            </select>
          </div>
        </div>

        <fieldset>
          <legend className="text-sm text-slate-300">{t("backtest.analysts")}</legend>
          <div className="mt-2 flex flex-wrap gap-4">
            {ANALYSTS.map((name) => (
              <label key={name} className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={analysts.includes(name)}
                  onChange={() => toggleAnalyst(name)}
                />
                {name}
              </label>
            ))}
          </div>
        </fieldset>

        <div>
          <label className="block text-sm text-slate-300" htmlFor="backtest-portfolio">
            {t("backtest.portfolio")}
          </label>
          <textarea
            id="backtest-portfolio"
            className="mt-2 h-24 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100"
            value={portfolioJson}
            onChange={(event) => setPortfolioJson(event.target.value)}
            placeholder='{"cash": 0, "positions": []}'
          />
        </div>

        {error ? <p className="text-sm text-red-300">{error}</p> : null}

        <button
          type="button"
          className="rounded-md bg-cyan-400 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-40"
          disabled={submitting}
          onClick={() => void submit()}
        >
          {submitting ? t("backtest.running") : t("backtest.submit")}
        </button>
      </section>

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-medium text-slate-100">
          {t("backtest.history")}
        </h2>
        {existing.isLoading ? (
          <p className="text-sm text-slate-400">{t("history.loading")}</p>
        ) : existing.isError ? (
          <p className="text-sm text-red-300">{t("history.error")}</p>
        ) : existing.data && existing.data.items.length > 0 ? (
          <ul className="divide-y divide-slate-800 rounded-lg border border-slate-800">
            {existing.data.items.map((item) => (
              <li key={item.run_id} className="flex items-center justify-between px-4 py-3">
                <span className="font-mono text-sm text-slate-200">{item.run_id}</span>
                <Link
                  className="text-sm text-cyan-300 hover:text-cyan-200"
                  to={`/backtest/${item.run_id}`}
                >
                  {t("history.open")}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">{t("history.empty")}</p>
        )}
      </section>
    </main>
  );
}
