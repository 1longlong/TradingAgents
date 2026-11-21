import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-006/011, ADR-003: reference sweep layout with real task and summary state.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  getBacktest,
  listBacktests,
  startBacktest,
} from "../api/backtestClient";
import { ApiError, getActiveRun } from "../api/runClient";
import { Modal } from "../components/Modal";
import { Icon } from "../components/Icon";
import { validateBacktest } from "./Backtest/validation";
import { BacktestSummary } from "./Backtest/BacktestSummary";
import { BacktestProgress } from "./Backtest/BacktestProgress";
import { downloadUrl } from "../api/client";
import { ANALYST_LABELS, formatDate } from "../utils/workspace";

const ANALYSTS = ["market", "social", "news", "fundamentals"] as const;

export function BacktestPage() {
  useUILanguage();
  const navigate = useNavigate();
  const { runId: selectedId } = useParams();
  const [tickers, setTickers] = useState("NVDA");
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [start, setStart] = useState(() =>
    new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10),
  );
  const [every, setEvery] = useState("7");
  const [analysts, setAnalysts] = useState<string[]>([...ANALYSTS]);
  const [asset, setAsset] = useState("stock");
  const [portfolio, setPortfolio] = useState("");
  const [runId, setRunId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [progressPage, setProgressPage] = useState<{
    runId: string;
    offset: number;
  } | null>(null);

  const existing = useQuery({
    queryKey: ["backtests", "page"],
    queryFn: listBacktests,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ["starting", "running"].includes(item.status),
      )
        ? 1000
        : false,
  });
  const activeFromList = existing.data?.items.find((item) =>
    ["starting", "running"].includes(item.status),
  );
  const displayedId =
    selectedId ?? progressPage?.runId ?? activeFromList?.run_id;
  const progressOffset =
    progressPage?.runId === displayedId ? progressPage?.offset : undefined;
  const selected = useQuery({
    queryKey: ["backtest", displayedId, progressOffset],
    queryFn: () => getBacktest(displayedId!, progressOffset),
    enabled: Boolean(displayedId),
    placeholderData: (previous) =>
      previous?.run_id === displayedId ? previous : undefined,
    refetchInterval: (query) =>
      query.state.data &&
      ["completed", "failed"].includes(query.state.data.status)
        ? false
        : 1000,
  });
  const recent = displayedId
    ? (selected.data ?? (selectedId ? undefined : activeFromList))
    : existing.data?.items[0];
  const running = Boolean(
    recent && ["starting", "running"].includes(recent.status),
  );
  const summary = recent?.summary;

  function toggleAnalyst(name: string) {
    setAnalysts((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  }

  async function submit() {
    const names = [
      ...new Set(
        tickers
          .split(",")
          .map((item) => item.trim().toUpperCase())
          .filter(Boolean),
      ),
    ];
    const result = validateBacktest({
      tickers: names,
      start,
      end,
      every: Number(every),
      analysts:
        asset === "crypto"
          ? analysts.filter((name) => name !== "fundamentals")
          : analysts,
      assetType: asset,
      portfolioJson: portfolio,
      runId,
    });
    if (!result.ok) {
      setError(result.error ?? "Check the sweep configuration.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const snapshot = await startBacktest({
        tickers: names,
        start,
        end,
        every: Number(every),
        analysts:
          asset === "crypto"
            ? analysts.filter((name) => name !== "fundamentals")
            : analysts,
        asset_type: asset,
        portfolio_json: portfolio.trim() || null,
        run_id: runId.trim() || null,
      });
      navigate(`/backtest/${snapshot.run_id}`);
    } catch (exc) {
      if (exc instanceof ApiError && exc.activeRunId)
        setActiveRunId(exc.activeRunId);
      else setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <section className="page-header">
        <div>
          <h1>{ui("Backtesting")}</h1>
          <p className="page-description">
            {ui("Evaluate historical ratings across instruments and dates.")}
          </p>
        </div>
        <div className="page-header-actions">
          {summary?.log_artifact_id ? (
            <a
              className="button ghost"
              href={downloadUrl(summary.log_artifact_id, "log")}
            >
              <Icon name="download" />
              {ui("Export log")}
            </a>
          ) : null}
        </div>
      </section>

      <div className="backtest-layout">
        <form
          className="panel config-panel"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
          noValidate
        >
          <h2>{ui("Configure a sweep")}</h2>
          <p>{ui("Uses server model defaults.")}</p>
          <div className="form-field">
            <label htmlFor="bt-tickers">{ui("Instruments")}</label>
            <input
              id="bt-tickers"
              value={tickers}
              onChange={(event) => setTickers(event.target.value)}
              placeholder={ui("NVDA,AAPL")}
              required
            />
            <small>{ui("Comma-separated ticker symbols.")}</small>
          </div>
          <div className="form-field">
            <label htmlFor="bt-every">{ui("Sample every")}</label>
            <input
              type="number"
              min="1"
              step="1"
              list="bt-intervals"
              id="bt-every"
              value={every}
              onChange={(event) => setEvery(event.target.value)}
            />
            <datalist id="bt-intervals">
              <option value="7" />
              <option value="14" />
              <option value="30" />
            </datalist>
            <small>
              {ui("Enter a positive whole number of calendar days.")}
            </small>
          </div>
          <div className="form-field">
            <label htmlFor="bt-start">{ui("Start date")}</label>
            <input
              id="bt-start"
              type="date"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              required
            />
          </div>
          <div className="form-field">
            <label htmlFor="bt-end">{ui("End date")}</label>
            <input
              id="bt-end"
              type="date"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              required
            />
          </div>
          <details className="disclosure">
            <summary>{ui("Analysts & advanced options")}</summary>
            <fieldset className="unstyled-fieldset">
              <legend className="sr-only">{ui("Backtest analysts")}</legend>
              {ANALYSTS.map((name) => (
                <label className="toggle-row" key={name}>
                  <span>{ui(ANALYST_LABELS[name])}</span>
                  <input
                    type="checkbox"
                    checked={
                      analysts.includes(name) &&
                      !(asset === "crypto" && name === "fundamentals")
                    }
                    disabled={asset === "crypto" && name === "fundamentals"}
                    onChange={() => toggleAnalyst(name)}
                  />
                </label>
              ))}
            </fieldset>
            <div className="form-field">
              <label htmlFor="bt-asset">{ui("Asset type")}</label>
              <select
                id="bt-asset"
                value={asset}
                onChange={(event) => setAsset(event.target.value)}
              >
                <option value="stock">{ui("Stock")}</option>
                <option value="crypto">{ui("Crypto")}</option>
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="bt-portfolio">
                {ui("Portfolio context (optional)")}
              </label>
              <textarea
                id="bt-portfolio"
                value={portfolio}
                onChange={(event) => setPortfolio(event.target.value)}
                placeholder={ui('{"cash":10000,"positions":[]}')}
              />
              <small>
                {ui(
                  "Omitted and explicitly flat portfolios remain different inputs.",
                )}
              </small>
            </div>
            <div className="form-field">
              <label htmlFor="bt-resume">
                {ui("Existing run ID (optional)")}
              </label>
              <input
                id="bt-resume"
                value={runId}
                onChange={(event) => setRunId(event.target.value)}
                placeholder={ui("Resume a previous sweep")}
              />
              <small>
                {ui(
                  "Recorded cells are skipped; pending outcomes are settled again.",
                )}
              </small>
            </div>
          </details>
          {error ? (
            <p className="field-error" role="alert">
              {ui(error)}
            </p>
          ) : null}
          <button
            className="button primary"
            type="submit"
            disabled={submitting || running}
          >
            <Icon name={submitting || running ? "activity" : "play"} />
            {submitting || running
              ? ui("Sweep in progress")
              : ui("Run backtest")}
          </button>
        </form>

        <div>
          {selected.isError || existing.isError ? (
            <div className="panel empty-state" role="alert">
              <strong>{ui("Backtest unavailable")}</strong>
              <p>{ui((selected.error ?? existing.error)?.message)}</p>
            </div>
          ) : null}
          {recent?.progress ? (
            <BacktestProgress
              snapshot={recent}
              offset={progressOffset}
              onPage={(offset) =>
                setProgressPage(
                  offset === undefined
                    ? null
                    : { runId: recent.run_id, offset },
                )
              }
            />
          ) : running ? (
            <div className="report-state-banner">
              <Icon name="activity" />
              <div>
                <strong>{ui("Sweep in progress")}</strong>
                <p>
                  {ui("Runs to completion · Expected cells:")}
                  {ui(" ")}
                  {ui(recent?.expected_cells ?? "Not recorded")}
                  {ui(".")}
                </p>
              </div>
            </div>
          ) : null}
          {recent?.error ? (
            <div className="report-state-banner warning" role="alert">
              <Icon name="warning" />
              <div>
                <strong>{ui("Backtest failed")}</strong>
                <p>
                  {ui(
                    String(
                      recent.error.message ?? "The sweep could not finish.",
                    ),
                  )}
                  {recent.error.correlation_id
                    ? ` (${String(recent.error.correlation_id)})`
                    : null}
                </p>
              </div>
            </div>
          ) : null}
          {recent && summary ? (
            <BacktestSummary
              summary={summary}
              description={ui("{{tickers}} · {{start}} – {{end}}", {
                tickers: recent.tickers?.join(", ") ?? "",
                start: formatDate(recent.start),
                end: formatDate(recent.end),
              })}
            />
          ) : !recent?.error && !running ? (
            <div className="panel empty-state">
              <Icon name="sliders" />
              <strong>{ui("No backtest sweeps yet")}</strong>
              <p>
                {ui(
                  "Configure a sweep to create the first read-only backtest artifact.",
                )}
              </p>
            </div>
          ) : null}

          <details className="panel chart-panel past-sweeps">
            <summary>{ui("Saved results")}</summary>
            {existing.isLoading ? (
              <p className="inline-note">{ui("Loading backtests...")}</p>
            ) : existing.data?.items.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{ui("Run ID")}</th>
                      <th>{ui("Tickers")}</th>
                      <th>{ui("Status")}</th>
                      <th>
                        <span className="sr-only">{ui("Open")}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {existing.data.items.map((item) => (
                      <tr key={item.run_id}>
                        <td className="strong-cell">{ui(item.run_id)}</td>
                        <td>
                          {ui(item.tickers?.join(", ") ?? item.ticker ?? "—")}
                        </td>
                        <td>{ui(item.status)}</td>
                        <td>
                          <Link
                            className="text-button"
                            to={`/backtest/${item.run_id}`}
                          >
                            {ui("Open ")}
                            <Icon name="arrow" />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="inline-note">{ui("No previous sweeps.")}</p>
            )}
          </details>
        </div>
      </div>
      <Modal
        open={Boolean(activeRunId)}
        title={ui("One perspective at a time.")}
        onClose={() => setActiveRunId(null)}
      >
        <p>
          {ui(
            "An analysis or backtest is already running. There is no hidden queue. Open the active run, or finish it before starting another.",
          )}
        </p>
        <div className="modal-actions">
          <button className="button" onClick={() => setActiveRunId(null)}>
            {ui("Keep exploring")}
          </button>
          <button
            className="button primary"
            onClick={() =>
              void getActiveRun()
                .then((run) => {
                  if (run.run_id) {
                    setActiveRunId(null);
                    navigate(
                      run.kind === "simulation"
                        ? "/simulation"
                        : run.kind === "backtest"
                          ? `/backtest/${run.run_id}`
                          : `/runs/${run.run_id}`,
                    );
                  } else {
                    setActiveRunId(null);
                    setError(
                      "The previous task has finished. You can start a new sweep.",
                    );
                  }
                })
                .catch((exc) => {
                  setActiveRunId(null);
                  setError(String(exc));
                })
            }
          >
            {ui("Open active run")}
          </button>
        </div>
      </Modal>
    </>
  );
}
