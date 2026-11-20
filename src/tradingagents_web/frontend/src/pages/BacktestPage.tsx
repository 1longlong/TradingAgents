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
import { downloadUrl } from "../api/client";
import { ANALYST_LABELS, formatDate } from "../utils/workspace";

const ANALYSTS = ["market", "social", "news", "fundamentals"] as const;

export function BacktestPage() {
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

  const existing = useQuery({
    queryKey: ["backtests", "page"],
    queryFn: listBacktests,
    retry: false,
  });
  const selected = useQuery({
    queryKey: ["backtest", selectedId],
    queryFn: () => getBacktest(selectedId!),
    enabled: Boolean(selectedId),
    refetchInterval: (query) =>
      query.state.data &&
      ["completed", "failed"].includes(query.state.data.status)
        ? false
        : 1000,
  });
  const recent = selectedId ? selected.data : existing.data?.items[0];
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
          <p className="eyebrow">PUT THE THESIS TO THE TEST</p>
          <h1>Backtesting</h1>
          <p className="page-description">
            Revisit past decisions on a fixed grid of instruments and dates.
          </p>
        </div>
        <div className="page-header-actions">
          {summary?.log_artifact_id ? (
            <a
              className="button ghost"
              href={downloadUrl(summary.log_artifact_id, "log")}
            >
              <Icon name="download" />
              Export log
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
          <h2>Configure a sweep</h2>
          <p>
            Uses server model, endpoint, language and depth defaults. Analysis
            wizard choices do not configure a backtest.
          </p>
          <div className="form-field">
            <label htmlFor="bt-tickers">Instruments</label>
            <input
              id="bt-tickers"
              value={tickers}
              onChange={(event) => setTickers(event.target.value)}
              placeholder="NVDA,AAPL"
              required
            />
            <small>Comma-separated ticker symbols.</small>
          </div>
          <div className="form-field">
            <label htmlFor="bt-every">Sample every</label>
            <select
              id="bt-every"
              value={every}
              onChange={(event) => setEvery(event.target.value)}
            >
              <option value="7">7 calendar days</option>
              <option value="14">14 calendar days</option>
              <option value="30">30 calendar days</option>
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="bt-start">Start date</label>
            <input
              id="bt-start"
              type="date"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              required
            />
          </div>
          <div className="form-field">
            <label htmlFor="bt-end">End date</label>
            <input
              id="bt-end"
              type="date"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              required
            />
          </div>
          <details className="disclosure">
            <summary>Analysts & advanced options</summary>
            <fieldset className="unstyled-fieldset">
              <legend className="sr-only">Backtest analysts</legend>
              {ANALYSTS.map((name) => (
                <label className="toggle-row" key={name}>
                  <span>{ANALYST_LABELS[name]}</span>
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
              <label htmlFor="bt-asset">Asset type</label>
              <select
                id="bt-asset"
                value={asset}
                onChange={(event) => setAsset(event.target.value)}
              >
                <option value="stock">Stock</option>
                <option value="crypto">Crypto</option>
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="bt-portfolio">Portfolio context (optional)</label>
              <textarea
                id="bt-portfolio"
                value={portfolio}
                onChange={(event) => setPortfolio(event.target.value)}
                placeholder='{"cash":10000,"positions":[]}'
              />
              <small>
                Omitted and explicitly flat portfolios remain different inputs.
              </small>
            </div>
            <div className="form-field">
              <label htmlFor="bt-resume">Existing run ID (optional)</label>
              <input
                id="bt-resume"
                value={runId}
                onChange={(event) => setRunId(event.target.value)}
                placeholder="Resume a previous sweep"
              />
              <small>
                Recorded cells are skipped; pending outcomes are settled again.
              </small>
            </div>
          </details>
          {error ? (
            <p className="field-error" role="alert">
              {error}
            </p>
          ) : null}
          <button
            className="button primary"
            type="submit"
            disabled={submitting || running}
          >
            <Icon name={submitting || running ? "activity" : "play"} />
            {submitting || running ? "Sweep in progress" : "Run backtest"}
          </button>
          <p className="inline-note">
            Backtests run to completion. Cancellation is not available.
          </p>
        </form>

        <div>
          {selected.isError || existing.isError ? (
            <div className="panel empty-state" role="alert">
              <strong>Backtest unavailable</strong>
              <p>{(selected.error ?? existing.error)?.message}</p>
            </div>
          ) : null}
          {running ? (
            <div className="report-state-banner">
              <Icon name="activity" />
              <div>
                <strong>Sweep in progress</strong>
                <p>
                  The fixed-date sweep runs to completion; cancellation is not
                  available. Expected cells:{" "}
                  {recent?.expected_cells ?? "Not recorded"}.
                </p>
              </div>
            </div>
          ) : null}
          {recent?.error ? (
            <div className="report-state-banner warning" role="alert">
              <Icon name="warning" />
              <div>
                <strong>Backtest failed</strong>
                <p>
                  {String(
                    recent.error.message ?? "The sweep could not finish.",
                  )}
                </p>
              </div>
            </div>
          ) : null}
          {recent && summary ? (
            <BacktestSummary
              summary={summary}
              description={`Displayed result: ${recent.run_id} · Cells run ${recent.cells_run ?? "Not recorded"} · Skipped ${recent.skipped ?? "Not recorded"} · ${formatDate(recent.start)} – ${formatDate(recent.end)} · ${recent.tickers?.join(", ") ?? ""} · Cell failures ${summary.failures?.length ?? 0} · Settlement failures ${summary.settlement_failures?.length ?? 0}`}
            />
          ) : (
            <div className="panel empty-state">
              <Icon name="sliders" />
              <strong>No backtest sweeps yet</strong>
              <p>
                Configure a sweep to create the first read-only backtest
                artifact.
              </p>
            </div>
          )}

          <details className="panel chart-panel past-sweeps">
            <summary>Saved results</summary>
            <div className="chart-heading">
              <div>
                <p className="eyebrow">PAST SWEEPS</p>
                <h2>Saved results</h2>
              </div>
            </div>
            {existing.isLoading ? (
              <p className="inline-note">Loading backtests...</p>
            ) : existing.data?.items.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Run ID</th>
                      <th>Tickers</th>
                      <th>Status</th>
                      <th>
                        <span className="sr-only">Open</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {existing.data.items.map((item) => (
                      <tr key={item.run_id}>
                        <td className="strong-cell">{item.run_id}</td>
                        <td>
                          {item.tickers?.join(", ") ?? item.ticker ?? "—"}
                        </td>
                        <td>{item.status}</td>
                        <td>
                          <Link
                            className="text-button"
                            to={`/backtest/${item.run_id}`}
                          >
                            Open <Icon name="arrow" />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="inline-note">No previous sweeps.</p>
            )}
          </details>
        </div>
      </div>
      <Modal
        open={Boolean(activeRunId)}
        title="One perspective at a time."
        onClose={() => setActiveRunId(null)}
      >
        <p>
          An analysis or backtest is already running. There is no hidden queue.
          Open the active run, or finish it before starting another.
        </p>
        <div className="modal-actions">
          <button className="button" onClick={() => setActiveRunId(null)}>
            Keep exploring
          </button>
          <button
            className="button primary"
            onClick={() =>
              void getActiveRun()
                .then((run) => {
                  if (run.run_id) {
                    setActiveRunId(null);
                    navigate(
                      run.kind === "backtest"
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
            Open active run
          </button>
        </div>
      </Modal>
    </>
  );
}
