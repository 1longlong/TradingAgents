import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-001/003/004/013, ADR-003, INV-WEB-006/014: three-step sheet; server validation is authoritative.
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ApiError,
  getActiveRun,
  getRunConfig,
  getRunModels,
  startRun,
  validatePortfolio,
  type RunConfig,
} from "../api/runClient";
import { Icon } from "../components/Icon";
import { LanguageSwitch } from "../components/LanguageSwitch";
import {
  DebateSettings,
  DebatePolicySummary,
} from "../components/DebateSettings";
import {
  readDebatePolicy,
  validateDebateSettings,
  type DebatePolicy,
  type DebateFieldError,
} from "../utils/debateSettings";
import { Modal } from "../components/Modal";
import { ANALYST_LABELS, formatDate } from "../utils/workspace";
import { validateStep } from "./NewAnalysis/validation";

const ANALYSTS = ["market", "social", "news", "fundamentals"];
const STEPS = ["Instrument", "Research setup", "Review & run"];
type Values = {
  ticker: string;
  date: string;
  asset: string;
  language: string;
  analysts: string[];
  depth: number;
  debatePolicy: DebatePolicy | null;
  riskRounds: number | null;
  riskIndependent: boolean;
  provider: string;
  quick: string;
  deep: string;
  checkpoint: boolean;
  portfolioEnabled: boolean;
  portfolio: string;
  endpoint: string;
  effort: string;
};
type FieldError = DebateFieldError;
function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
function modelDefaultSignature(config: RunConfig): string {
  return JSON.stringify([
    config.defaults.llm_provider,
    config.defaults.quick_think_llm,
    config.defaults.deep_think_llm,
  ]);
}
function readDraft(config: RunConfig): Partial<Values> {
  try {
    const saved = JSON.parse(
      localStorage.getItem("ta.analysisDraft") ?? "null",
    );
    if (!saved || typeof saved !== "object") return {};
    const staleModels =
      Object.values(config.env_defaults ?? {}).some(Boolean) &&
      saved.modelDefaults !== modelDefaultSignature(config);
    return Object.fromEntries(
      [
        "ticker",
        "date",
        "asset",
        "language",
        "analysts",
        "depth",
        "debatePolicy",
        "riskRounds",
        "riskIndependent",
        "provider",
        "quick",
        "deep",
        "checkpoint",
      ]
        .filter(
          (key) =>
            key in saved &&
            !(staleModels && ["provider", "quick", "deep"].includes(key)),
        )
        .map((key) => [key, saved[key]]),
    );
  } catch {
    return {};
  }
}
export function NewAnalysisPage({
  returnTo = "/overview",
}: {
  returnTo?: string;
}) {
  useUILanguage();
  const navigate = useNavigate(),
    location = useLocation();
  const [step, setStep] = useState(0),
    [values, setValues] = useState<Values>({
      ticker: "",
      date: today(),
      asset: "stock",
      language: "English",
      analysts: [...ANALYSTS],
      depth: 1,
      debatePolicy: null,
      riskRounds: null,
      riskIndependent: false,
      provider: "",
      quick: "",
      deep: "",
      checkpoint: false,
      portfolioEnabled: false,
      portfolio: "",
      endpoint: "",
      effort: "",
    });
  const [errors, setErrors] = useState<FieldError[]>([]),
    [submitting, setSubmitting] = useState(false);
  const [config, setConfig] = useState<RunConfig | null>(null),
    [configError, setConfigError] = useState<string | null>(null);
  const [modelWarning, setModelWarning] = useState<string | null>(null);
  const [modelRefresh, setModelRefresh] = useState(0);
  const refreshRequested = useRef(false);
  const [modelError, setModelError] = useState<string | null>(null),
    [modelsLoading, setModelsLoading] = useState(true);
  const [options, setOptions] = useState<{
    quick: Array<{ value: string; label: string }>;
    deep: Array<{ value: string; label: string }>;
  }>({ quick: [], deep: [] });
  const [active, setActive] = useState<{
    run_id: string;
    kind?: string;
  } | null>(null);
  const initialized = useRef(false);
  const initialModelDefaults = useRef<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null),
    form = useRef<HTMLFormElement>(null),
    requestId = useRef(crypto.randomUUID()),
    latest = useRef(values);
  latest.current = values;
  const locked = (key: string) => {
    if (["llm_provider", "quick_think_llm", "deep_think_llm"].includes(key))
      return false;
    if (
      key === "backend_url" &&
      values.provider !== config?.defaults.llm_provider
    )
      return false;
    return Boolean(config?.env_locks[key]);
  };
  function close() {
    navigate(returnTo, { replace: true });
  }
  function saveDraft() {
    if (!initialized.current) return;
    const v = latest.current;
    try {
      localStorage.setItem(
        "ta.analysisDraft",
        JSON.stringify({
          ticker: v.ticker,
          date: v.date,
          asset: v.asset,
          language: v.language,
          analysts: v.analysts,
          depth: v.depth,
          debatePolicy: v.debatePolicy,
          riskRounds: v.riskRounds,
          riskIndependent: v.riskIndependent,
          provider: v.provider,
          quick: v.quick,
          deep: v.deep,
          checkpoint: v.checkpoint,
          modelDefaults: initialModelDefaults.current,
        }),
      );
    } catch {
      /* Draft storage is optional. */
    }
  }
  useEffect(() => {
    const node = dialog.current;
    if (node) {
      if (active) {
        node.close?.();
      } else if (!node.open) {
        if (node.showModal) node.showModal();
        else node.setAttribute("open", "");
      }
    }
    return () => {
      saveDraft();
      node?.close?.();
    };
  }, [active]);
  useEffect(() => {
    let mounted = true;
    getRunConfig()
      .then((loaded) => {
        if (!mounted) return;
        const defaults = { ...loaded.defaults };
        for (const [key, value] of Object.entries(loaded.prefs)) {
          if (
            !loaded.env_defaults?.[key] &&
            !loaded.env_locks[
              key === "research_depth" ? "max_debate_rounds" : key
            ]
          )
            defaults[key] = value;
        }
        const draft = readDraft(loaded);
        const setup =
          (location.state as { setup?: Partial<Values> } | null)?.setup ?? {};
        const chosen = { ...draft, ...setup };
        const provider = chosen.provider ?? String(defaults.llm_provider ?? "");
        const samePrefs = loaded.prefs.llm_provider === provider,
          sameDefaults = loaded.defaults.llm_provider === provider;
        function modelValue(
          key: "quick_think_llm" | "deep_think_llm",
          field: "quick" | "deep",
        ) {
          if (chosen.provider === provider && chosen[field])
            return chosen[field]!;
          if (sameDefaults && loaded.env_defaults?.[key])
            return String(loaded.defaults[key] ?? "");
          return String(
            (samePrefs ? loaded.prefs[key] : undefined) ??
              (sameDefaults ? loaded.defaults[key] : undefined) ??
              "",
          );
        }
        const serverPolicy = readDebatePolicy(
          loaded.defaults.debate_termination,
        );
        const savedPolicy = readDebatePolicy(chosen.debatePolicy);
        const depth = Number(
          loaded.env_locks.max_debate_rounds
            ? loaded.defaults.research_depth
            : (savedPolicy?.max_debate_rounds ??
                chosen.depth ??
                defaults.research_depth ??
                1),
        );
        const serverRisk =
          typeof loaded.defaults.max_risk_discuss_rounds === "number"
            ? loaded.defaults.max_risk_discuss_rounds
            : depth;
        const riskIndependent =
          chosen.riskIndependent === true ||
          Boolean(loaded.env_locks.max_risk_discuss_rounds) ||
          (serverPolicy != null &&
            serverRisk !== serverPolicy.max_debate_rounds);
        const savedRisk =
          typeof chosen.riskRounds === "number" &&
          Number.isFinite(chosen.riskRounds)
            ? chosen.riskRounds
            : null;
        const riskRounds = serverPolicy
          ? loaded.env_locks.max_risk_discuss_rounds
            ? serverRisk
            : riskIndependent
              ? (savedRisk ?? serverRisk)
              : depth
          : null;
        setValues((current) => ({
          ...current,
          ...chosen,
          provider,
          quick: modelValue("quick_think_llm", "quick"),
          deep: modelValue("deep_think_llm", "deep"),
          language: loaded.env_locks.output_language
            ? String(loaded.defaults.output_language)
            : (chosen.language ??
              String(defaults.output_language ?? "English")),
          depth,
          debatePolicy: serverPolicy
            ? { ...(savedPolicy ?? serverPolicy), max_debate_rounds: depth }
            : null,
          riskRounds,
          riskIndependent,
          analysts: Array.isArray(chosen.analysts)
            ? chosen.analysts
            : ((defaults.analysts as string[]) ?? ANALYSTS),
          checkpoint: loaded.env_locks.checkpoint_enabled
            ? Boolean(loaded.defaults.checkpoint)
            : (chosen.checkpoint ?? Boolean(defaults.checkpoint)),
          portfolioEnabled: false,
          portfolio: "",
          endpoint: "",
          effort: "",
        }));
        initialModelDefaults.current = modelDefaultSignature(loaded);
        initialized.current = true;
        setConfig(loaded);
      })
      .catch((exc) => {
        if (mounted) setConfigError(String(exc));
      });
    getActiveRun()
      .then((run) => {
        if (mounted && run.run_id) setActive(run);
      })
      .catch(() => {
        /* Creation still enforces the server's active slot. */
      });
    return () => {
      mounted = false;
    };
  }, [location.state]);
  useEffect(() => {
    if (!config || !values.provider) return;
    let mounted = true;
    setModelsLoading(true);
    setModelError(null);
    setModelWarning(null);
    const refresh = refreshRequested.current;
    refreshRequested.current = false;
    Promise.all([
      getRunModels(values.provider, "quick", refresh),
      getRunModels(values.provider, "deep", refresh),
    ])
      .then(([quick, deep]) => {
        if (!mounted) return;
        const next = {
          quick: quick.models.filter((item) => item.value !== "custom"),
          deep: deep.models.filter((item) => item.value !== "custom"),
        };
        setOptions(next);
        setModelWarning(quick.warning ?? deep.warning ?? null);
        setValues((current) => ({
          ...current,
          quick: current.quick || next.quick[0]?.value || "",
          deep: current.deep || next.deep[0]?.value || "",
        }));
      })
      .catch((exc) => {
        if (mounted) {
          if (values.provider === "openrouter") {
            setOptions({ quick: [], deep: [] });
            setModelWarning(
              "OpenRouter model list is unavailable. Enter a model ID manually.",
            );
          } else setModelError(String(exc));
        }
      })
      .finally(() => {
        if (mounted) setModelsLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [config, values.provider, modelRefresh]);
  useEffect(() => {
    if (errors.length) document.getElementById("wizard-errors")?.focus();
  }, [errors]);
  function update<K extends keyof Values>(key: K, value: Values[K]) {
    setValues((current) => ({
      ...current,
      [key]: value,
      ...(key === "depth"
        ? {
            debatePolicy: current.debatePolicy
              ? { ...current.debatePolicy, max_debate_rounds: Number(value) }
              : null,
            riskRounds:
              current.riskIndependent || locked("max_risk_discuss_rounds")
                ? current.riskRounds
                : Number(value),
          }
        : {}),
    }));
  }
  function fieldError(id: string) {
    const error = errors.find(([key]) => key === id);
    return error ? (
      <small className="field-error" id={`${id}-error`}>
        {ui(error[1], error[2])}
      </small>
    ) : null;
  }
  function attrs(id: string) {
    return errors.some(([key]) => key === id)
      ? { "aria-invalid": true as const, "aria-describedby": `${id}-error` }
      : {};
  }
  function focusField(id: string) {
    const field = document.getElementById(id);
    const details = field?.closest("details");
    if (details) details.open = true;
    field?.focus();
  }
  async function next() {
    const found: FieldError[] = [];
    if (step === 0) {
      for (const [name, field] of [
        ["ticker", "ticker"],
        ["date", "date"],
      ] as const) {
        const result = validateStep(name, {
          ticker: values.ticker,
          date: values.date,
        });
        if (!result.ok) found.push([field, result.error!]);
      }
      const date = new Date(`${values.date}T12:00:00Z`);
      if (
        !Number.isNaN(date.valueOf()) &&
        date.toISOString().slice(0, 10) !== values.date
      )
        found.push(["date", "Choose a valid calendar date."]);
    }
    if (step === 1) {
      found.push(
        ...validateDebateSettings(values.debatePolicy, values.riskRounds),
      );
      if (!values.analysts.length)
        found.push(["analysts", "Choose at least one analyst."]);
      if (!values.quick.trim() || !values.deep.trim())
        found.push(["quick-model", "Enter both the quick and deep model IDs."]);
      if (values.endpoint) {
        try {
          const url = new URL(values.endpoint);
          if (
            !["http:", "https:"].includes(url.protocol) ||
            url.username ||
            url.password ||
            url.search ||
            url.hash
          )
            throw Error();
        } catch {
          found.push([
            "endpoint",
            "Use an HTTP(S) endpoint without credentials, query parameters or fragments.",
          ]);
        }
      }
    }
    if (found.length) {
      setErrors(found);
      return;
    }
    setErrors([]);
    saveDraft();
    if (step < 2) {
      setStep(step + 1);
      document.getElementById("sheet-title")?.focus();
      return;
    }
    setSubmitting(true);
    try {
      if (values.portfolioEnabled) {
        if (!values.portfolio.trim()) {
          setErrors([
            [
              "portfolio",
              "Provide a JSON object, or turn off portfolio context.",
            ],
          ]);
          return;
        }
        try {
          await validatePortfolio(values.portfolio);
        } catch (exc) {
          setErrors([
            ["portfolio", exc instanceof Error ? exc.message : String(exc)],
          ]);
          return;
        }
      }
      const thought = {
        openai: "openai_reasoning_effort",
        google: "google_thinking_level",
        anthropic: "anthropic_effort",
      }[values.provider as "openai" | "google" | "anthropic"];
      const run = await startRun({
        client_request_id: requestId.current,
        ticker: values.ticker.trim().toUpperCase(),
        trade_date: values.date,
        asset_type: values.asset,
        output_language: values.language,
        analysts:
          values.asset === "crypto"
            ? values.analysts.filter((key) => key !== "fundamentals")
            : values.analysts,
        research_depth: values.depth,
        ...(values.debatePolicy
          ? {
              debate_termination: values.debatePolicy,
              max_risk_discuss_rounds: values.riskRounds ?? values.depth,
            }
          : {}),
        llm_provider: values.provider,
        quick_think_llm: values.quick.trim(),
        deep_think_llm: values.deep.trim(),
        checkpoint: values.checkpoint,
        portfolio_json: values.portfolioEnabled ? values.portfolio : null,
        ...(values.endpoint && !locked("backend_url")
          ? { backend_url: values.endpoint.trim() }
          : {}),
        ...(thought && values.effort && !locked(thought)
          ? { [thought]: values.effort }
          : {}),
      });
      navigate(`/runs/${run.run_id}`, { replace: true });
    } catch (exc) {
      if (exc instanceof ApiError && exc.activeRunId)
        setActive({ run_id: exc.activeRunId });
      else
        setErrors([
          ["submit", exc instanceof Error ? exc.message : String(exc)],
        ]);
    } finally {
      setSubmitting(false);
    }
  }
  const effort = (
    {
      openai: ["openai_reasoning_effort", ["minimal", "low", "medium", "high"]],
      google: ["google_thinking_level", ["minimal", "low", "medium", "high"]],
      anthropic: ["anthropic_effort", ["low", "medium", "high", "max"]],
    } as Record<string, [string, string[]]>
  )[values.provider];
  const providerLabel =
    config?.providers.find((item) => item.key === values.provider)?.label ??
    values.provider;
  const status = config?.key_status[values.provider];
  return (
    <>
      <dialog
        className="sheet"
        ref={dialog}
        aria-labelledby="sheet-title"
        aria-label={ui("New analysis")}
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
      >
        <div id="sheet-content">
          <div className="sheet-header">
            <div>
              <h2 id="sheet-title" tabIndex={-1}>
                {ui("New analysis")}
              </h2>
            </div>
            <button
              className="icon-button"
              aria-label={ui("Save draft and close")}
              onClick={close}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="sheet-body">
            <div
              className="wizard-steps"
              aria-label={ui("Analysis setup steps")}
            >
              {STEPS.map((label, index) => (
                <div
                  className={`wizard-step ${index === step ? "active" : ""}`}
                  aria-current={index === step ? "step" : undefined}
                  key={label}
                >
                  <span>
                    {index < step ? <Icon name="check" /> : index + 1}
                  </span>
                  {ui(label)}
                </div>
              ))}
            </div>
            {errors.length ? (
              <div
                className="error-summary"
                id="wizard-errors"
                tabIndex={-1}
                role="alert"
              >
                <strong>{ui("Please check the following:")}</strong>
                {errors.map(([field, message, parameters]) => (
                  <a
                    href={`#${field}`}
                    key={field}
                    onClick={(event) => {
                      event.preventDefault();
                      focusField(field);
                    }}
                  >
                    {ui(message, parameters)}
                  </a>
                ))}
              </div>
            ) : null}
            {configError ? (
              <p className="field-error" role="alert">
                {ui(configError)}
              </p>
            ) : null}
            {!config && !configError ? (
              <p className="inline-note">
                {ui("Loading server configuration...")}
              </p>
            ) : null}
            {modelError ? (
              <p className="field-error" role="alert">
                {ui(modelError)}
              </p>
            ) : null}
            <form
              id="analysis-form"
              ref={form}
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                void next();
              }}
            >
              {step === 0 ? (
                <>
                  <h3 className="wizard-section-title">
                    {ui("Instrument & date")}
                  </h3>
                  <fieldset className="asset-choices unstyled-fieldset">
                    <legend className="sr-only">{ui("Asset type")}</legend>
                    {[
                      ["stock", "Stocks & ETFs", "building"],
                      ["crypto", "Crypto assets", "globe"],
                    ].map(([key, label, icon]) => (
                      <label className="choice" key={key}>
                        <input
                          type="radio"
                          name="asset"
                          value={key}
                          checked={values.asset === key}
                          onChange={() =>
                            setValues((current) => ({
                              ...current,
                              asset: key,
                              analysts:
                                key === "crypto"
                                  ? current.analysts.filter(
                                      (item) => item !== "fundamentals",
                                    )
                                  : current.analysts,
                            }))
                          }
                        />
                        <span>
                          <Icon name={icon} /> {ui(label)}
                        </span>
                      </label>
                    ))}
                  </fieldset>
                  <div className="form-field">
                    <label htmlFor="ticker">
                      {ui("Ticker symbol ")}
                      <span aria-hidden="true">{ui("*")}</span>
                    </label>
                    <input
                      id="ticker"
                      value={values.ticker}
                      maxLength={32}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={ui("e.g. NVDA, 0700.HK or BTC-USD")}
                      {...attrs("ticker")}
                      onChange={(event) =>
                        update("ticker", event.target.value.toUpperCase())
                      }
                      required
                    />
                    <small>
                      {ui(
                        "Include the exchange suffix where relevant. No live lookup is performed.",
                      )}
                    </small>
                    {fieldError("ticker")}
                  </div>
                  <div className="field-row">
                    <div className="form-field">
                      <label htmlFor="date">
                        {ui("Analysis date ")}
                        <span aria-hidden="true">{ui("*")}</span>
                      </label>
                      <input
                        id="date"
                        type="date"
                        max={today()}
                        value={values.date}
                        onChange={(event) => update("date", event.target.value)}
                        {...attrs("date")}
                        required
                      />
                      {fieldError("date")}
                    </div>
                    <div className="form-field">
                      <label htmlFor="language">{ui("Report language")}</label>
                      <select
                        id="language"
                        disabled={locked("output_language")}
                        value={values.language}
                        onChange={(event) =>
                          update("language", event.target.value)
                        }
                      >
                        {[
                          ...new Set([
                            "English",
                            "Chinese",
                            "Japanese",
                            "Spanish",
                            "French",
                            "German",
                            values.language,
                          ]),
                        ].map((language) => (
                          <option key={language} value={language}>
                            {ui(language)}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </>
              ) : null}
              {step === 1 ? (
                <>
                  <h3 className="wizard-section-title">
                    {ui("Team & models")}
                  </h3>
                  <fieldset
                    className="unstyled-fieldset"
                    id="analysts"
                    tabIndex={-1}
                    {...attrs("analysts")}
                  >
                    <legend className="form-label">
                      {ui("Analyst perspectives")}
                    </legend>
                    <div className="analyst-choices">
                      {ANALYSTS.map((key, index) => (
                        <label className="choice" key={key}>
                          <Icon
                            name={["chart", "users", "news", "building"][index]}
                          />
                          <span>{ui(ANALYST_LABELS[key])}</span>
                          <input
                            type="checkbox"
                            name="analysts"
                            value={key}
                            checked={values.analysts.includes(key)}
                            disabled={
                              values.asset === "crypto" &&
                              key === "fundamentals"
                            }
                            onChange={() =>
                              update(
                                "analysts",
                                values.analysts.includes(key)
                                  ? values.analysts.filter(
                                      (item) => item !== key,
                                    )
                                  : [...values.analysts, key],
                              )
                            }
                          />
                        </label>
                      ))}
                    </div>
                    {fieldError("analysts")}
                  </fieldset>
                  {values.asset === "crypto" ? (
                    <p className="helper">
                      {ui(
                        "Company fundamentals are unavailable for crypto assets.",
                      )}
                    </p>
                  ) : null}
                  <p className="form-label research-depth-label">
                    {ui("Research depth")}
                  </p>
                  <fieldset className="depth-choices unstyled-fieldset">
                    <legend className="sr-only">{ui("Research depth")}</legend>
                    {[
                      [1, "Shallow"],
                      [3, "Medium"],
                      [5, "Deep"],
                      ...(![1, 3, 5].includes(values.depth)
                        ? [[values.depth, "Custom"]]
                        : []),
                    ].map(([value, label]) => (
                      <label className="choice" key={value}>
                        <input
                          type="radio"
                          name="depth"
                          value={value}
                          checked={values.depth === value}
                          disabled={locked("max_debate_rounds")}
                          onChange={() => update("depth", Number(value))}
                        />
                        <span>
                          {ui(label)}
                          <small>
                            {ui("{{count}} debate rounds", { count: value })}
                          </small>
                        </span>
                      </label>
                    ))}
                  </fieldset>
                  {values.debatePolicy && values.riskRounds != null ? (
                    <DebateSettings
                      policy={values.debatePolicy}
                      riskRounds={values.riskRounds}
                      locks={config?.env_locks ?? {}}
                      errors={errors}
                      onPolicy={(policy) =>
                        setValues((current) => ({
                          ...current,
                          debatePolicy: policy,
                          depth: policy.max_debate_rounds,
                          riskRounds:
                            current.riskIndependent ||
                            locked("max_risk_discuss_rounds")
                              ? current.riskRounds
                              : policy.max_debate_rounds,
                        }))
                      }
                      onRisk={(riskRounds) =>
                        setValues((current) => ({
                          ...current,
                          riskRounds,
                          riskIndependent: true,
                        }))
                      }
                    />
                  ) : null}
                  <div className="form-field">
                    <label htmlFor="provider">{ui("Model provider")}</label>
                    <select
                      id="provider"
                      value={values.provider}
                      disabled={locked("llm_provider")}
                      aria-describedby={
                        config?.env_defaults?.llm_provider &&
                        values.provider === config.defaults.llm_provider
                          ? "provider-default"
                          : undefined
                      }
                      onChange={(event) =>
                        setValues((current) => ({
                          ...current,
                          provider: event.target.value,
                          quick:
                            event.target.value === config?.defaults.llm_provider
                              ? String(config.defaults.quick_think_llm ?? "")
                              : "",
                          deep:
                            event.target.value === config?.defaults.llm_provider
                              ? String(config.defaults.deep_think_llm ?? "")
                              : "",
                          endpoint: "",
                          effort: "",
                        }))
                      }
                    >
                      {config?.providers.map((provider) => (
                        <option key={provider.key} value={provider.key}>
                          {ui(provider.label)}
                        </option>
                      ))}
                    </select>
                    <small>
                      <Icon name="shield" />
                      {ui(" ")}
                      {status === "configured"
                        ? ui("Key configured")
                        : status === "not_required"
                          ? ui("No key required")
                          : ui("Server credentials not configured")}
                      {ui(". Credentials stay on the server.")}
                      {config?.env_defaults?.llm_provider &&
                      values.provider === config.defaults.llm_provider ? (
                        <span id="provider-default">
                          {" "}
                          · {ui("Server default")}
                        </span>
                      ) : null}
                    </small>
                  </div>
                  {values.provider === "openrouter" ? (
                    <div className="model-discovery">
                      <small>
                        {ui(
                          "Latest OpenRouter text models; custom IDs remain available.",
                        )}
                      </small>
                      <button
                        type="button"
                        className="button ghost"
                        disabled={modelsLoading}
                        onClick={() => {
                          refreshRequested.current = true;
                          setModelRefresh((value) => value + 1);
                        }}
                      >
                        {ui(
                          modelsLoading
                            ? "Loading models…"
                            : "Refresh model list",
                        )}
                      </button>
                    </div>
                  ) : null}
                  {modelWarning ? (
                    <p className="inline-note" role="status">
                      {ui(modelWarning)}
                    </p>
                  ) : null}
                  <div className="field-row">
                    {(["quick", "deep"] as const).map((mode) => (
                      <div className="form-field" key={mode}>
                        <label htmlFor={`${mode}-model`}>
                          {ui(mode === "quick" ? "Quick model" : "Deep model")}
                        </label>
                        <input
                          id={`${mode}-model`}
                          list={`${mode}-options`}
                          value={values[mode]}
                          disabled={
                            locked(`${mode}_think_llm`) || modelsLoading
                          }
                          onChange={(event) => update(mode, event.target.value)}
                          {...attrs(`${mode}-model`)}
                          required
                        />
                        <datalist id={`${mode}-options`}>
                          {options[mode].map((item) => (
                            <option value={item.value} key={item.value}>
                              {ui(item.label)}
                            </option>
                          ))}
                        </datalist>
                        {fieldError(`${mode}-model`)}
                      </div>
                    ))}
                  </div>
                  <p className="helper">
                    {ui(
                      "The quick model handles analyst work. The deep model weighs the debate and final assessment.",
                    )}
                  </p>
                  <details className="disclosure model-options">
                    <summary>{ui("Endpoint & model thinking")}</summary>
                    <div className="form-field">
                      <label htmlFor="endpoint">
                        {ui("Endpoint override (optional)")}
                      </label>
                      <input
                        id="endpoint"
                        type="url"
                        placeholder={ui("Use server / provider default")}
                        value={values.endpoint}
                        disabled={locked("backend_url")}
                        onChange={(event) =>
                          update("endpoint", event.target.value)
                        }
                        {...attrs("endpoint")}
                      />
                      <small>
                        {ui(
                          "HTTP(S) URL only. Never paste a key, username, query token or fragment. Endpoint drafts are not persisted.",
                        )}
                      </small>
                      {fieldError("endpoint")}
                    </div>
                    {effort ? (
                      <div className="form-field">
                        <label htmlFor="effort">
                          {ui(effort[0].replaceAll("_", " "))}
                        </label>
                        <select
                          id="effort"
                          value={values.effort}
                          disabled={locked(effort[0])}
                          onChange={(event) =>
                            update("effort", event.target.value)
                          }
                        >
                          <option value="">
                            {ui("Server / model default")}
                          </option>
                          {effort[1].map((value) => (
                            <option key={value} value={value}>
                              {ui(value)}
                            </option>
                          ))}
                        </select>
                        <small>
                          {ui(
                            "Only effective for supported models. Backend capability checks remain authoritative.",
                          )}
                        </small>
                      </div>
                    ) : (
                      <p className="inline-note">
                        {ui(
                          "No provider-specific thinking override is exposed for this selection.",
                        )}
                      </p>
                    )}
                    <p className="inline-note">
                      {ui(
                        "Effective server environment values take precedence over request overrides.",
                      )}
                    </p>
                  </details>
                </>
              ) : null}
              {step === 2 ? (
                <>
                  <h3 className="wizard-section-title">{ui("Review setup")}</h3>
                  <dl className="review-list">
                    {[
                      ["Instrument", values.ticker],
                      ["Analysis date", formatDate(values.date)],
                      [
                        "Analysts",
                        values.analysts
                          .map((key) => ui(ANALYST_LABELS[key]))
                          .join(", "),
                      ],
                      [
                        "Research depth",
                        (
                          { 1: "Shallow", 3: "Medium", 5: "Deep" } as Record<
                            number,
                            string
                          >
                        )[values.depth] ?? values.depth,
                      ],
                      ["Model provider", providerLabel],
                      [
                        "Quick / deep models",
                        `${values.quick} / ${values.deep}`,
                      ],
                      [
                        "Endpoint",
                        values.endpoint || "Server/provider default",
                      ],
                      [
                        "Model thinking",
                        values.effort || "Server/model default",
                      ],
                      ["Report language", values.language],
                    ].map(([key, value]) => (
                      <div className="review-item" key={key}>
                        <dt>{ui(key)}</dt>
                        <dd>{ui(value)}</dd>
                      </div>
                    ))}
                  </dl>
                  <DebatePolicySummary
                    policy={values.debatePolicy}
                    riskRounds={values.riskRounds}
                    title="Selected debate settings"
                  />
                  <label className="toggle-row">
                    <span>
                      {ui("Enable checkpoint recovery")}
                      <small>
                        {ui(
                          "Resume a matching interrupted run when a saved checkpoint exists.",
                        )}
                      </small>
                    </span>
                    <input
                      type="checkbox"
                      checked={values.checkpoint}
                      disabled={locked("checkpoint_enabled")}
                      onChange={(event) =>
                        update("checkpoint", event.target.checked)
                      }
                    />
                  </label>
                  <label className="toggle-row">
                    <span>
                      {ui("Include portfolio context")}
                      <small>
                        {ui(
                          "Optional holdings and cash for a more contextual proposal.",
                        )}
                      </small>
                    </span>
                    <input
                      type="checkbox"
                      checked={values.portfolioEnabled}
                      onChange={(event) =>
                        update("portfolioEnabled", event.target.checked)
                      }
                    />
                  </label>
                  <div className="form-field" hidden={!values.portfolioEnabled}>
                    <label htmlFor="portfolio">{ui("Portfolio JSON")}</label>
                    <textarea
                      id="portfolio"
                      placeholder={ui(
                        '{"cash":10000,"currency":"USD","positions":[]}',
                      )}
                      value={values.portfolio}
                      {...attrs("portfolio")}
                      onChange={(event) =>
                        update("portfolio", event.target.value)
                      }
                    />
                    <small>
                      {ui(
                        "An explicit empty positions list means a flat book. Leaving context off means no portfolio was supplied. Portfolio text is not saved as a draft.",
                      )}
                    </small>
                    {fieldError("portfolio")}
                    <label className="portfolio-upload">
                      {ui("Choose a portfolio JSON file")}
                      <input
                        type="file"
                        accept="application/json,.json"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file)
                            void file
                              .text()
                              .then((text) => update("portfolio", text))
                              .catch(() =>
                                setErrors([
                                  [
                                    "portfolio",
                                    "The selected file could not be read.",
                                  ],
                                ]),
                              );
                        }}
                      />
                    </label>
                  </div>
                  <p className="inline-note">
                    {ui(
                      "Research output is advisory. Starting an analysis contacts your configured model and market-data providers; it does not place a trade.",
                    )}
                  </p>
                </>
              ) : null}
            </form>
          </div>
          <div className="sheet-footer">
            <button
              className="button ghost"
              disabled={submitting}
              onClick={() => {
                if (step) {
                  setErrors([]);
                  setStep(step - 1);
                } else close();
              }}
            >
              {step ? ui("Back") : ui("Save draft & close")}
            </button>
            <LanguageSwitch />
            <button
              className="button primary"
              form="analysis-form"
              type="submit"
              disabled={
                submitting || !config || modelsLoading || Boolean(modelError)
              }
            >
              {step === 2 && !submitting ? <Icon name="play" /> : null}
              {submitting
                ? ui("Starting…")
                : step === 2
                  ? ui("Start analysis")
                  : ui("Continue")}
              {step < 2 ? <Icon name="arrow" /> : null}
            </button>
          </div>
        </div>
      </dialog>
      <Modal
        open={Boolean(active)}
        title={ui("One perspective at a time.")}
        onClose={close}
      >
        <p>
          {ui(
            "The workspace accepts one analysis or backtest at a time. Open the active task or keep exploring until it finishes.",
          )}
        </p>
        <div className="modal-actions">
          <button className="button" onClick={close}>
            {ui("Keep exploring")}
          </button>
          <button
            className="button primary"
            onClick={() =>
              navigate(
                active?.kind === "simulation"
                  ? "/simulation"
                  : active?.kind === "backtest"
                    ? `/backtest/${active.run_id}`
                    : `/runs/${active?.run_id}`,
                { replace: true },
              )
            }
          >
            {ui("Open active run")}
          </button>
        </div>
      </Modal>
    </>
  );
}
