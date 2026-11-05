import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { startRun } from "../api/runClient";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { validateStep, type WizardStep } from "./NewAnalysis/validation";

const STEPS: WizardStep[] = [
  "ticker",
  "date",
  "language",
  "analysts",
  "depth",
  "provider",
  "models",
  "portfolio",
];

const ANALYSTS = ["market", "social", "news", "fundamentals"] as const;
const PROVIDERS = [
  "openai",
  "anthropic",
  "google",
  "deepseek",
  "xai",
  "qwen",
  "glm",
  "minimax",
  "openrouter",
  "mistral",
  "kimi",
  "groq",
  "nvidia",
  "ollama",
  "openai_compatible",
];

type Values = {
  ticker: string;
  date: string;
  language: string;
  analysts: string[];
  depth: number;
  provider: string;
  quick: string;
  deep: string;
  checkpoint: boolean;
  portfolio: string;
};

function today() {
  return new Date().toISOString().slice(0, 10);
}

export function NewAnalysisPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [stepIndex, setStepIndex] = useState(0);
  const [values, setValues] = useState<Values>({
    ticker: "",
    date: today(),
    language: "English",
    analysts: [...ANALYSTS],
    depth: 1,
    provider: "openai",
    quick: "gpt-5.6-luna",
    deep: "gpt-5.6",
    checkpoint: false,
    portfolio: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const step = STEPS[stepIndex];

  function update<K extends keyof Values>(key: K, value: Values[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function toggleAnalyst(name: string) {
    setValues((current) => ({
      ...current,
      analysts: current.analysts.includes(name)
        ? current.analysts.filter((item) => item !== name)
        : [...current.analysts, name],
    }));
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const run = await startRun({
        client_request_id: crypto.randomUUID(),
        ticker: values.ticker,
        trade_date: values.date,
        asset_type: values.ticker.toUpperCase().includes("-USD") ? "crypto" : "stock",
        output_language: values.language,
        analysts: values.analysts,
        research_depth: values.depth,
        llm_provider: values.provider,
        quick_think_llm: values.quick,
        deep_think_llm: values.deep,
        checkpoint: values.checkpoint,
        portfolio_json: values.portfolio.trim() ? values.portfolio : null,
      });
      navigate(`/runs/${run.run_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSubmitting(false);
    }
  }

  async function next() {
    const result = validateStep(step, {
      ticker: values.ticker,
      date: values.date,
      analysts: values.analysts,
    });
    if (!result.ok) {
      setError(result.error ?? t("wizard.invalid"));
      return;
    }
    setError(null);
    if (stepIndex < STEPS.length - 1) {
      setStepIndex(stepIndex + 1);
    } else {
      await submit();
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/history">
            ← {t("nav.history")}
          </Link>
          <h1 className="mt-3 text-3xl font-semibold text-slate-100">
            {t("wizard.title")}
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            {stepIndex + 1} / {STEPS.length}
          </p>
        </div>
        <LanguageSwitch />
      </header>

      <section className="space-y-5 rounded-lg border border-slate-800 p-6">
        {step === "ticker" ? (
          <div>
            <label className="block text-sm text-slate-300" htmlFor="ticker">
              {t("wizard.ticker")}
            </label>
            <input
              id="ticker"
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={values.ticker}
              onChange={(event) => update("ticker", event.target.value)}
              placeholder="NVDA"
            />
          </div>
        ) : null}

        {step === "date" ? (
          <div>
            <h2 className="text-lg font-medium text-slate-100">{t("wizard.date")}</h2>
            <label className="mt-4 block text-sm text-slate-300" htmlFor="date">
              {t("wizard.date")}
            </label>
            <input
              id="date"
              type="date"
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={values.date}
              onChange={(event) => update("date", event.target.value)}
            />
          </div>
        ) : null}

        {step === "language" ? (
          <div>
            <h2 className="text-lg font-medium text-slate-100">{t("wizard.language")}</h2>
            <select
              className="mt-4 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={values.language}
              onChange={(event) => update("language", event.target.value)}
            >
              {["English", "Chinese", "Japanese", "Korean", "Spanish", "French", "German"].map(
                (language) => (
                  <option key={language} value={language}>
                    {language}
                  </option>
                ),
              )}
            </select>
          </div>
        ) : null}

        {step === "analysts" ? (
          <div>
            <h2 className="text-lg font-medium text-slate-100">{t("wizard.analysts")}</h2>
            <div className="mt-4 space-y-2">
              {ANALYSTS.map((analyst) => (
                <label key={analyst} className="flex items-center gap-3 text-slate-300">
                  <input
                    type="checkbox"
                    checked={values.analysts.includes(analyst)}
                    onChange={() => toggleAnalyst(analyst)}
                  />
                  {analyst}
                </label>
              ))}
            </div>
          </div>
        ) : null}

        {step === "depth" ? (
          <div>
            <h2 className="text-lg font-medium text-slate-100">{t("wizard.depth")}</h2>
            <select
              className="mt-4 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={values.depth}
              onChange={(event) => update("depth", Number(event.target.value))}
            >
              <option value={1}>{t("wizard.shallow")}</option>
              <option value={3}>{t("wizard.medium")}</option>
              <option value={5}>{t("wizard.deep")}</option>
            </select>
          </div>
        ) : null}

        {step === "provider" ? (
          <div>
            <h2 className="text-lg font-medium text-slate-100">{t("wizard.provider")}</h2>
            <select
              className="mt-4 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={values.provider}
              onChange={(event) => update("provider", event.target.value)}
            >
              {PROVIDERS.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {step === "models" ? (
          <div className="space-y-4">
            <h2 className="text-lg font-medium text-slate-100">{t("wizard.models")}</h2>
            <label className="block text-sm text-slate-300" htmlFor="quick-model">
              {t("wizard.quickModel")}
            </label>
            <input
              id="quick-model"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={values.quick}
              onChange={(event) => update("quick", event.target.value)}
            />
            <label className="block text-sm text-slate-300" htmlFor="deep-model">
              {t("wizard.deepModel")}
            </label>
            <input
              id="deep-model"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              value={values.deep}
              onChange={(event) => update("deep", event.target.value)}
            />
          </div>
        ) : null}

        {step === "portfolio" ? (
          <div className="space-y-4">
            <h2 className="text-lg font-medium text-slate-100">{t("wizard.portfolio")}</h2>
            <label className="flex items-center gap-3 text-slate-300">
              <input
                type="checkbox"
                checked={values.checkpoint}
                onChange={(event) => update("checkpoint", event.target.checked)}
              />
              {t("wizard.checkpoint")}
            </label>
            <label className="block text-sm text-slate-300" htmlFor="portfolio">
              {t("wizard.pastePortfolio")}
            </label>
            <textarea
              id="portfolio"
              className="min-h-40 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100"
              value={values.portfolio}
              onChange={(event) => update("portfolio", event.target.value)}
              placeholder={'{"cash": 1000, "positions": []}'}
            />
          </div>
        ) : null}

        {error ? <p className="text-sm text-red-300">{error}</p> : null}

        <div className="flex justify-between gap-3">
          <button
            type="button"
            className="rounded-md border border-slate-700 px-4 py-2 text-slate-300 disabled:opacity-40"
            disabled={stepIndex === 0 || submitting}
            onClick={() => setStepIndex(Math.max(0, stepIndex - 1))}
          >
            {t("wizard.back")}
          </button>
          <button
            type="button"
            className="rounded-md bg-cyan-400 px-4 py-2 font-medium text-slate-950 disabled:opacity-40"
            disabled={submitting}
            onClick={() => void next()}
          >
            {stepIndex === STEPS.length - 1 ? t("wizard.submit") : t("wizard.next")}
          </button>
        </div>
      </section>
    </main>
  );
}
