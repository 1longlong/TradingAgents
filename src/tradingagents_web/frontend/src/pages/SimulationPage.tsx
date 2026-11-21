// FR-TRD-001..006, REQ-WEB-021; ADR-003-frontend-stack.md: simulated-only workspace.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ui, useUILanguage } from "../i18n/ui";
import { getActiveRun } from "../api/runClient";
import { getSimulation, getSimulationJobs } from "../api/simulationClient";
import { SimulationAccount } from "./Simulation/Account";
import { SimulationDecisions } from "./Simulation/Decisions";
import { SimulationBacktests } from "./Simulation/Backtests";
import { SimulationAudit } from "./Simulation/Audit";

const TABS = [
  { id: "account", label: "Account" },
  { id: "decisions", label: "Decisions & approvals" },
  { id: "backtests", label: "Walk-forward" },
  { id: "audit", label: "Trading audit" },
];
export function SimulationPage() {
  useUILanguage();
  const [params, setParams] = useSearchParams(),
    cache = useQueryClient();
  const tab = TABS.some((item) => item.id === params.get("tab"))
    ? params.get("tab")!
    : "account";
  const account = useQuery({
    queryKey: ["simulation", "state"],
    queryFn: getSimulation,
    retry: false,
    refetchInterval: 3000,
  });
  const jobs = useQuery({
    queryKey: ["simulation", "jobs"],
    queryFn: getSimulationJobs,
    retry: false,
    refetchInterval: 2000,
  });
  const active = useQuery({
    queryKey: ["simulation", "active"],
    queryFn: getActiveRun,
    retry: false,
    refetchInterval: 2000,
  });
  const selected =
    jobs.data?.items.find((job) => job.run_id === params.get("job")) ??
    jobs.data?.items[0];
  const busy = Boolean(active.data?.run_id);
  function changed() {
    void cache.invalidateQueries({ queryKey: ["simulation"] });
  }
  function switchTab(id: string) {
    setParams((current) => {
      current.set("tab", id);
      return current;
    });
  }
  function select(id: string) {
    setParams({ tab: "backtests", job: id });
  }
  return (
    <>
      <section className="page-header">
        <div>
          <h1>{ui("Simulated trading")}</h1>
        </div>
        <div className="page-header-actions">
          <span className="status-tag neutral">{ui("Simulation only")}</span>
          <button className="button ghost" onClick={changed}>
            {ui("Refresh")}
          </button>
        </div>
      </section>
      <p className="inline-note">
        {ui(
          "Simulated funds only. No broker connection or currency conversion.",
        )}
      </p>
      <div
        className="sim-tabs"
        role="tablist"
        aria-label={ui("Simulation views")}
        onKeyDown={(event) => {
          const index = TABS.findIndex((item) => item.id === tab);
          const next =
            event.key === "ArrowRight"
              ? (index + 1) % 4
              : event.key === "ArrowLeft"
                ? (index + 3) % 4
                : event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? 3
                    : null;
          if (next !== null) {
            event.preventDefault();
            switchTab(TABS[next].id);
            document.getElementById(`simulation-tab-${TABS[next].id}`)?.focus();
          }
        }}
      >
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`simulation-tab-${item.id}`}
            aria-selected={item.id === tab}
            aria-controls="simulation-panel"
            tabIndex={item.id === tab ? 0 : -1}
            onClick={() => switchTab(item.id)}
          >
            {ui(item.label)}
          </button>
        ))}
      </div>
      {busy ? (
        <p role="status" className="inline-note">
          {ui(
            "A workspace task is active. Simulated account changes and new runs will wait until it finishes.",
          )}
        </p>
      ) : null}
      <section
        id="simulation-panel"
        className="sim-tab-panel"
        role="tabpanel"
        aria-labelledby={`simulation-tab-${tab}`}
      >
        {account.isLoading && (tab === "account" || tab === "decisions") ? (
          <p role="status">{ui("Loading simulated account…")}</p>
        ) : null}
        {account.isError && (tab === "account" || tab === "decisions") ? (
          <p role="alert" className="field-error">
            {ui(account.error.message)}
          </p>
        ) : null}
        {tab === "account" && account.data ? (
          <SimulationAccount
            state={account.data}
            busy={busy}
            changed={changed}
          />
        ) : null}
        {tab === "decisions" && account.data ? (
          <SimulationDecisions
            state={account.data}
            busy={busy}
            changed={changed}
          />
        ) : null}
        {tab === "backtests" ? (
          <>
            <SimulationBacktests
              jobs={jobs.data?.items ?? []}
              selected={selected}
              busy={busy}
              changed={changed}
              select={select}
            />
            {jobs.isError ? (
              <p role="alert" className="field-error">
                {ui(jobs.error.message)}
              </p>
            ) : null}
          </>
        ) : null}
        {tab === "audit" ? (
          <SimulationAudit jobs={jobs.data?.items ?? []} />
        ) : null}
      </section>
    </>
  );
}
