// REQ-WEB-001/013, ADR-001: use effective server configuration and provider models.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import {
  getRunConfig,
  getRunModels,
  startRun,
  type RunConfig,
} from "../api/runClient";
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
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
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
    provider: "",
    quick: "",
    deep: "",
    checkpoint: false,
    portfolio: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [config, setConfig] = useState<RunConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelOptions, setModelOptions] = useState<{
    quick: Array<{ value: string; label: string }>;
    deep: Array<{ value: string; label: string }>;
  }>({ quick: [], deep: [] });

  useEffect(() => {
    let active = true;
    getRunConfig()
      .then((loaded) => {
        if (!active) return;
        const defaults = { ...loaded.defaults };
        for (const [key, value] of Object.entries(loaded.prefs)) {
          const lockKey = key === "research_depth" ? "max_debate_rounds" : key;
          if (!loaded.env_locks[lockKey]) defaults[key] = value;
        }
        const provider = String(defaults.llm_provider ?? "");
        // A model preference from another provider must never cross the boundary.
        if (loaded.prefs.llm_provider !== provider) {
          defaults.quick_think_llm = loaded.defaults.quick_think_llm;
          defaults.deep_think_llm = loaded.defaults.deep_think_llm;
        }
        setValues((current) => ({
          ...current,
          provider,
          quick: String(defaults.quick_think_llm ?? ""),
          deep: String(defaults.deep_think_llm ?? ""),
          language: String(defaults.output_language ?? "English"),
          analysts: (defaults.analysts as string[]) ?? [...ANALYSTS],
          depth: Number(defaults.research_depth ?? 1),
          checkpoint: Boolean(defaults.checkpoint),
        }));
        setConfig(loaded);
      })
      .catch((exc: unknown) => {
        if (active) setConfigError(String(exc));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!config || !values.provider) return;
    const loaded = config;
    let active = true;
    setModelsLoading(true);
    setModelError(null);
    Promise.all([
      getRunModels(values.provider, "quick"),
      getRunModels(values.provider, "deep"),
    ])
      .then(([quick, deep]) => {
        if (!active) return;
        const options = {
          quick: quick.models.filter((item) => item.value !== "custom"),
          deep: deep.models.filter((item) => item.value !== "custom"),
        };
        setModelOptions(options);
        setValues((current) => {
          function select(mode: "quick" | "deep", value: string) {
            const key = `${mode}_think_llm`;
            const remembered =
              loaded.prefs.llm_provider === current.provider &&
              loaded.prefs[key] === value;
            if (
              value &&
              (loaded.env_locks[key] ||
                remembered ||
                options[mode].some((item) => item.value === value))
            )
              return value;
            return options[mode][0]?.value ?? "";
          }
          return {
            ...current,
            quick: select("quick", current.quick),
            deep: select("deep", current.deep),
          };
        });
      })
      .catch((exc: unknown) => {
        if (active) setModelError(String(exc));
      })
      .finally(() => {
        if (active) setModelsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [config, values.provider]);

  const locked = (key: string) => Boolean(config?.env_locks[key]);
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
    if (!values.quick.trim() || !values.deep.trim()) {
      setError(t("wizard.modelsRequired"));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const run = await startRun({
        client_request_id: crypto.randomUUID(),
        ticker: values.ticker,
        trade_date: values.date,
        asset_type: values.ticker.toUpperCase().includes("-USD")
          ? "crypto"
          : "stock",
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
    if (step === "models" && (!values.quick.trim() || !values.deep.trim())) {
      setError(t("wizard.modelsRequired"));
      return;
    }
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
          <Link
            className="text-sm text-cyan-300 hover:text-cyan-200"
            to="/history"
          >
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

      {configError ? (
        <p role="alert" className="mb-4 text-red-300">
          {configError}
        </p>
      ) : null}
      {!config && !configError ? <p>{t("wizard.loadingConfig")}</p> : null}
      {modelError ? (
        <p role="alert" className="mb-4 text-red-300">
          {modelError}
        </p>
      ) : null}
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
            <h2 className="text-lg font-medium text-slate-100">
              {t("wizard.date")}
            </h2>
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
            <h2 className="text-lg font-medium text-slate-100">
              {t("wizard.language")}
            </h2>
            <select
              className="mt-4 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              disabled={locked("output_language")}
              value={values.language}
              onChange={(event) => update("language", event.target.value)}
            >
              {[
                "English",
                "Chinese",
                "Japanese",
                "Korean",
                "Spanish",
                "French",
                "German",
              ].map((language) => (
                <option key={language} value={language}>
                  {language}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {step === "analysts" ? (
          <div>
            <h2 className="text-lg font-medium text-slate-100">
              {t("wizard.analysts")}
            </h2>
            <div className="mt-4 space-y-2">
              {ANALYSTS.map((analyst) => (
                <label
                  key={analyst}
                  className="flex items-center gap-3 text-slate-300"
                >
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
            <h2 className="text-lg font-medium text-slate-100">
              {t("wizard.depth")}
            </h2>
            <select
              className="mt-4 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              disabled={locked("max_debate_rounds")}
              value={values.depth}
              onChange={(event) => update("depth", Number(event.target.value))}
            >
              <option value={1}>{t("wizard.shallow")}</option>
              <option value={3}>{t("wizard.medium")}</option>
              <option value={5}>{t("wizard.deep")}</option>
              {![1, 3, 5].includes(values.depth) ? (
                <option value={values.depth}>{values.depth}</option>
              ) : null}
            </select>
          </div>
        ) : null}

        {step === "provider" ? (
          <div>
            <h2 className="text-lg font-medium text-slate-100">
              {t("wizard.provider")}
            </h2>
            <select
              className="mt-4 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              disabled={locked("llm_provider")}
              value={values.provider}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  provider: event.target.value,
                  quick: "",
                  deep: "",
                }))
              }
            >
              {config?.providers.map((provider) => (
                <option key={provider.key} value={provider.key}>
                  {provider.label}
                </option>
              ))}
            </select>
            <p className="mt-3 text-sm text-slate-300">
              {t(
                `wizard.keyStatus.${config?.key_status[values.provider] ?? "unknown"}`,
              )}
            </p>
            {locked("llm_provider") ? (
              <p className="text-sm text-slate-400">{t("wizard.envLocked")}</p>
            ) : null}
          </div>
        ) : null}

        {step === "models" ? (
          <div className="space-y-4">
            <h2 className="text-lg font-medium text-slate-100">
              {t("wizard.models")}
            </h2>
            <label
              className="block text-sm text-slate-300"
              htmlFor="quick-model"
            >
              {t("wizard.quickModel")}
            </label>
            <input
              id="quick-model"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              list="quick-model-options"
              disabled={locked("quick_think_llm") || modelsLoading}
              value={values.quick}
              onChange={(event) => update("quick", event.target.value)}
            />
            <datalist id="quick-model-options">
              {modelOptions.quick.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </datalist>
            <label
              className="block text-sm text-slate-300"
              htmlFor="deep-model"
            >
              {t("wizard.deepModel")}
            </label>
            <input
              id="deep-model"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              list="deep-model-options"
              disabled={locked("deep_think_llm") || modelsLoading}
              value={values.deep}
              onChange={(event) => update("deep", event.target.value)}
            />
            <datalist id="deep-model-options">
              {modelOptions.deep.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </datalist>
          </div>
        ) : null}

        {step === "portfolio" ? (
          <div className="space-y-4">
            <h2 className="text-lg font-medium text-slate-100">
              {t("wizard.portfolio")}
            </h2>
            <p className="text-sm text-slate-300">
              {values.provider} · {values.quick} / {values.deep}
            </p>
            <p className="text-sm text-slate-300">
              {t(
                `wizard.keyStatus.${config?.key_status[values.provider] ?? "unknown"}`,
              )}
            </p>
            {config?.backend_url_configured ? (
              <p className="text-sm text-slate-400">
                {t("wizard.serverEndpoint")}
              </p>
            ) : null}
            <label className="flex items-center gap-3 text-slate-300">
              <input
                type="checkbox"
                disabled={locked("checkpoint_enabled")}
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
            disabled={
              submitting || !config || modelsLoading || Boolean(modelError)
            }
            onClick={() => void next()}
          >
            {stepIndex === STEPS.length - 1
              ? t("wizard.submit")
              : t("wizard.next")}
          </button>
        </div>
      </section>
    </main>
  );
}
