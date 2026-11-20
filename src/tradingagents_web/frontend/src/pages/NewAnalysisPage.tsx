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
  provider: string;
  quick: string;
  deep: string;
  checkpoint: boolean;
  portfolioEnabled: boolean;
  portfolio: string;
  endpoint: string;
  effort: string;
};
type FieldError = [string, string];
function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
function readDraft(): Partial<Values> {
  try {
    const saved = JSON.parse(
      localStorage.getItem("ta.analysisDraft") ?? "null",
    );
    if (!saved || typeof saved !== "object") return {};
    return Object.fromEntries(
      [
        "ticker",
        "date",
        "asset",
        "language",
        "analysts",
        "depth",
        "provider",
        "quick",
        "deep",
        "checkpoint",
      ]
        .filter((key) => key in saved)
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
  const dialog = useRef<HTMLDialogElement>(null),
    form = useRef<HTMLFormElement>(null),
    requestId = useRef(crypto.randomUUID()),
    latest = useRef(values);
  latest.current = values;
  const locked = (key: string) => Boolean(config?.env_locks[key]);
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
          provider: v.provider,
          quick: v.quick,
          deep: v.deep,
          checkpoint: v.checkpoint,
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
            !loaded.env_locks[
              key === "research_depth" ? "max_debate_rounds" : key
            ]
          )
            defaults[key] = value;
        }
        const draft = readDraft();
        const setup =
          (location.state as { setup?: Partial<Values> } | null)?.setup ?? {};
        const chosen = { ...draft, ...setup };
        const provider = loaded.env_locks.llm_provider
          ? String(loaded.defaults.llm_provider)
          : (chosen.provider ?? String(defaults.llm_provider ?? ""));
        const samePrefs = loaded.prefs.llm_provider === provider,
          sameDefaults = loaded.defaults.llm_provider === provider;
        setValues((current) => ({
          ...current,
          ...chosen,
          provider,
          quick: loaded.env_locks.quick_think_llm
            ? String(loaded.defaults.quick_think_llm ?? "")
            : chosen.provider === provider && chosen.quick
              ? chosen.quick
              : String(
                  (samePrefs
                    ? loaded.prefs.quick_think_llm
                    : sameDefaults
                      ? loaded.defaults.quick_think_llm
                      : "") ?? "",
                ),
          deep: loaded.env_locks.deep_think_llm
            ? String(loaded.defaults.deep_think_llm ?? "")
            : chosen.provider === provider && chosen.deep
              ? chosen.deep
              : String(
                  (samePrefs
                    ? loaded.prefs.deep_think_llm
                    : sameDefaults
                      ? loaded.defaults.deep_think_llm
                      : "") ?? "",
                ),
          language: loaded.env_locks.output_language
            ? String(loaded.defaults.output_language)
            : (chosen.language ??
              String(defaults.output_language ?? "English")),
          depth: Number(
            loaded.env_locks.max_debate_rounds
              ? loaded.defaults.research_depth
              : (chosen.depth ?? defaults.research_depth ?? 1),
          ),
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
    Promise.all([
      getRunModels(values.provider, "quick"),
      getRunModels(values.provider, "deep"),
    ])
      .then(([quick, deep]) => {
        if (!mounted) return;
        const next = {
          quick: quick.models.filter((item) => item.value !== "custom"),
          deep: deep.models.filter((item) => item.value !== "custom"),
        };
        setOptions(next);
        setValues((current) => ({
          ...current,
          quick: current.quick || next.quick[0]?.value || "",
          deep: current.deep || next.deep[0]?.value || "",
        }));
      })
      .catch((exc) => {
        if (mounted) setModelError(String(exc));
      })
      .finally(() => {
        if (mounted) setModelsLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [config, values.provider]);
  useEffect(() => {
    if (errors.length) document.getElementById("wizard-errors")?.focus();
  }, [errors]);
  function update<K extends keyof Values>(key: K, value: Values[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }
  function fieldError(id: string) {
    const error = errors.find(([key]) => key === id);
    return error ? (
      <small className="field-error" id={`${id}-error`}>
        {error[1]}
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
        aria-label="New analysis"
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
      >
        <div id="sheet-content">
          <div className="sheet-header">
            <div>
              <p className="eyebrow">NEW RESEARCH</p>
              <h2 id="sheet-title" tabIndex={-1}>
                A more considered perspective.
              </h2>
              <p>A few choices. An entire research team.</p>
            </div>
            <button
              className="icon-button"
              aria-label="Save draft and close"
              onClick={close}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="sheet-body">
            <div className="wizard-steps" aria-label="Analysis setup steps">
              {STEPS.map((label, index) => (
                <div
                  className={`wizard-step ${index === step ? "active" : ""}`}
                  aria-current={index === step ? "step" : undefined}
                  key={label}
                >
                  <span>
                    {index < step ? <Icon name="check" /> : index + 1}
                  </span>
                  {label}
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
                <strong>Please check the following:</strong>
                {errors.map(([field, message]) => (
                  <a
                    href={`#${field}`}
                    key={field}
                    onClick={(event) => {
                      event.preventDefault();
                      focusField(field);
                    }}
                  >
                    {message}
                  </a>
                ))}
              </div>
            ) : null}
            {configError ? (
              <p className="field-error" role="alert">
                {configError}
              </p>
            ) : null}
            {!config && !configError ? (
              <p className="inline-note">Loading server configuration...</p>
            ) : null}
            {modelError ? (
              <p className="field-error" role="alert">
                {modelError}
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
                    What is on your radar?
                  </h3>
                  <p className="wizard-section-description">
                    Choose an instrument and a point in time. We will bring the
                    perspectives.
                  </p>
                  <fieldset className="asset-choices unstyled-fieldset">
                    <legend className="sr-only">Asset type</legend>
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
                          <Icon name={icon} /> {label}
                        </span>
                      </label>
                    ))}
                  </fieldset>
                  <div className="form-field">
                    <label htmlFor="ticker">
                      Ticker symbol <span aria-hidden="true">*</span>
                    </label>
                    <input
                      id="ticker"
                      value={values.ticker}
                      maxLength={32}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="e.g. NVDA, 0700.HK or BTC-USD"
                      {...attrs("ticker")}
                      onChange={(event) =>
                        update("ticker", event.target.value.toUpperCase())
                      }
                      required
                    />
                    <small>
                      Include the exchange suffix where relevant. No live lookup
                      is performed.
                    </small>
                    {fieldError("ticker")}
                  </div>
                  <div className="field-row">
                    <div className="form-field">
                      <label htmlFor="date">
                        Analysis date <span aria-hidden="true">*</span>
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
                      <label htmlFor="language">Report language</label>
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
                          <option key={language}>{language}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <p className="inline-note">
                    A historical date keeps the research anchored to that point
                    in time. Report output language is a separate analysis
                    setting.
                  </p>
                </>
              ) : null}
              {step === 1 ? (
                <>
                  <h3 className="wizard-section-title">
                    Build your research team.
                  </h3>
                  <p className="wizard-section-description">
                    A single instrument. Independent lenses. You choose the
                    depth.
                  </p>
                  <fieldset
                    className="unstyled-fieldset"
                    id="analysts"
                    tabIndex={-1}
                    {...attrs("analysts")}
                  >
                    <legend className="form-label">Analyst perspectives</legend>
                    <div className="analyst-choices">
                      {ANALYSTS.map((key, index) => (
                        <label className="choice" key={key}>
                          <Icon
                            name={["chart", "users", "news", "building"][index]}
                          />
                          <span>{ANALYST_LABELS[key]}</span>
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
                      Company fundamentals are unavailable for crypto assets.
                    </p>
                  ) : null}
                  <p className="form-label research-depth-label">
                    Research depth
                  </p>
                  <fieldset className="depth-choices unstyled-fieldset">
                    <legend className="sr-only">Research depth</legend>
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
                          {label}
                          <small>
                            {value} debate round{value === 1 ? "" : "s"}
                          </small>
                        </span>
                      </label>
                    ))}
                  </fieldset>
                  <div className="form-field">
                    <label htmlFor="provider">Model provider</label>
                    <select
                      id="provider"
                      value={values.provider}
                      disabled={locked("llm_provider")}
                      onChange={(event) =>
                        setValues((current) => ({
                          ...current,
                          provider: event.target.value,
                          quick: "",
                          deep: "",
                          effort: "",
                        }))
                      }
                    >
                      {config?.providers.map((provider) => (
                        <option key={provider.key} value={provider.key}>
                          {provider.label}
                        </option>
                      ))}
                    </select>
                    <small>
                      <Icon name="shield" />{" "}
                      {status === "configured"
                        ? "Key configured"
                        : status === "not_required"
                          ? "No key required"
                          : "Server credentials not configured"}
                      . Credentials stay on the server.
                    </small>
                  </div>
                  <div className="field-row">
                    {(["quick", "deep"] as const).map((mode) => (
                      <div className="form-field" key={mode}>
                        <label htmlFor={`${mode}-model`}>
                          {mode === "quick" ? "Quick" : "Deep"} model
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
                              {item.label}
                            </option>
                          ))}
                        </datalist>
                        {fieldError(`${mode}-model`)}
                      </div>
                    ))}
                  </div>
                  <p className="helper">
                    The quick model handles analyst work. The deep model weighs
                    the debate and final assessment.
                  </p>
                  <details className="disclosure model-options">
                    <summary>Endpoint & model thinking</summary>
                    <div className="form-field">
                      <label htmlFor="endpoint">
                        Endpoint override (optional)
                      </label>
                      <input
                        id="endpoint"
                        type="url"
                        placeholder="Use server / provider default"
                        value={values.endpoint}
                        disabled={locked("backend_url")}
                        onChange={(event) =>
                          update("endpoint", event.target.value)
                        }
                        {...attrs("endpoint")}
                      />
                      <small>
                        HTTP(S) URL only. Never paste a key, username, query
                        token or fragment. Endpoint drafts are not persisted.
                      </small>
                      {fieldError("endpoint")}
                    </div>
                    {effort ? (
                      <div className="form-field">
                        <label htmlFor="effort">
                          {effort[0].replaceAll("_", " ")}
                        </label>
                        <select
                          id="effort"
                          value={values.effort}
                          disabled={locked(effort[0])}
                          onChange={(event) =>
                            update("effort", event.target.value)
                          }
                        >
                          <option value="">Server / model default</option>
                          {effort[1].map((value) => (
                            <option key={value}>{value}</option>
                          ))}
                        </select>
                        <small>
                          Only effective for supported models. Backend
                          capability checks remain authoritative.
                        </small>
                      </div>
                    ) : (
                      <p className="inline-note">
                        No provider-specific thinking override is exposed for
                        this selection.
                      </p>
                    )}
                    <p className="inline-note">
                      Effective server environment values take precedence over
                      request overrides.
                    </p>
                  </details>
                </>
              ) : null}
              {step === 2 ? (
                <>
                  <h3 className="wizard-section-title">
                    A final look before you begin.
                  </h3>
                  <p className="wizard-section-description">
                    Your question, your team, your research context.
                  </p>
                  <dl className="review-list">
                    {[
                      ["Instrument", values.ticker],
                      ["Analysis date", formatDate(values.date)],
                      [
                        "Analysts",
                        values.analysts
                          .map((key) => ANALYST_LABELS[key])
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
                        <dt>{key}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                  <label className="toggle-row">
                    <span>
                      Enable checkpoint recovery
                      <small>
                        Resume a matching interrupted run when a saved
                        checkpoint exists.
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
                      Include portfolio context
                      <small>
                        Optional holdings and cash for a more contextual
                        proposal.
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
                    <label htmlFor="portfolio">Portfolio JSON</label>
                    <textarea
                      id="portfolio"
                      placeholder='{"cash":10000,"currency":"USD","positions":[]}'
                      value={values.portfolio}
                      {...attrs("portfolio")}
                      onChange={(event) =>
                        update("portfolio", event.target.value)
                      }
                    />
                    <small>
                      An explicit empty positions list means a flat book.
                      Leaving context off means no portfolio was supplied.
                      Portfolio text is not saved as a draft.
                    </small>
                    {fieldError("portfolio")}
                    <label className="portfolio-upload">
                      Choose a portfolio JSON file
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
                    Research output is advisory. Starting an analysis contacts
                    your configured model and market-data providers; it does not
                    place a trade.
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
              {step ? "Back" : "Save draft & close"}
            </button>
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
                ? "Starting…"
                : step === 2
                  ? "Start analysis"
                  : "Continue"}
              {step < 2 ? <Icon name="arrow" /> : null}
            </button>
          </div>
        </div>
      </dialog>
      <Modal
        open={Boolean(active)}
        title="One perspective at a time."
        onClose={close}
      >
        <p>
          The workspace accepts one analysis or backtest at a time. Open the
          active task or keep exploring until it finishes.
        </p>
        <div className="modal-actions">
          <button className="button" onClick={close}>
            Keep exploring
          </button>
          <button
            className="button primary"
            onClick={() =>
              navigate(
                active?.kind === "backtest"
                  ? `/backtest/${active.run_id}`
                  : `/runs/${active?.run_id}`,
                { replace: true },
              )
            }
          >
            Open active run
          </button>
        </div>
      </Modal>
    </>
  );
}
