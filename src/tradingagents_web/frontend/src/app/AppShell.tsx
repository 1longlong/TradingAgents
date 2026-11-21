import { ui, uiHistoryTitle, useUILanguage } from "../i18n/ui";
// REQ-WEB-003/006/010/012/013, ADR-003, INV-WEB-014: server-backed workspace controls.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

import { getAnnouncements } from "../api/backtestClient";
import { getAllHistory } from "../api/client";
import { clearCheckpoints, getActiveRun, getRunConfig } from "../api/runClient";
import { CompanyLogo, Rating } from "../components/Research";
import { AnnouncementsGate } from "../components/Announcements";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { LanguageSwitch } from "../components/LanguageSwitch";

const NAV = [
  { route: "overview", label: "Overview", icon: "grid" },
  { route: "history", label: "Analysis history", icon: "clock" },
  { route: "backtest", label: "Backtesting", icon: "sliders" },
  { route: "simulation", label: "Simulated trading", icon: "chart" },
  { route: "audit", label: "Research audit", icon: "shield" },
  { route: "journal", label: "Decision journal", icon: "book" },
] as const;

type ModalKind =
  "settings" | "help" | "search" | "announcements" | "clear" | null;

const KEY_STATUS_LABELS: Record<string, string> = {
  configured: "Configured",
  not_configured: "Not configured",
  not_required: "No key required",
};

const BREADCRUMBS: Record<string, string> = {
  overview: "Overview",
  history: "Analysis history",
  backtest: "Backtesting",
  simulation: "Simulated trading",
  audit: "Research audit",
  comparison: "Policy comparison",
  journal: "Decision journal",
  new: "New analysis",
  runs: "Live run",
};

export function AppShell({ children }: { children: ReactNode }) {
  useUILanguage();
  const location = useLocation();
  const navigate = useNavigate();
  const previousPath = useRef(location.pathname);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobile, setMobile] = useState(
    () => matchMedia("(max-width:760px)").matches,
  );
  const [clearing, setClearing] = useState(false);
  useEffect(() => {
    const media = matchMedia("(max-width:760px)");
    const changed = () => setMobile(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    const help = () => setModal("help");
    window.addEventListener("workspace:help", help);
    return () => window.removeEventListener("workspace:help", help);
  }, []);
  const [modal, setModal] = useState<ModalKind>(null);
  const [theme, setTheme] = useState(
    () => window.localStorage.getItem("ta.theme") ?? "light",
  );
  const [search, setSearch] = useState("");
  const [confirmClear, setConfirmClear] = useState("");
  const [clearState, setClearState] = useState<string | number | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("ta.theme", theme);
  }, [theme]);

  useEffect(() => {
    setMobileOpen(false);
    setModal(null);
    if (location.pathname !== "/new" && previousPath.current !== "/new")
      window.scrollTo({ top: 0 });
    previousPath.current = location.pathname;
  }, [location.pathname]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const editing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        target?.isContentEditable;
      if (event.key === "Escape" && mobileOpen) {
        setMobileOpen(false);
        document.querySelector<HTMLButtonElement>(".mobile-menu")?.focus();
      }
      if (editing || document.querySelector("dialog[open]")) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setModal("search");
        return;
      }
      if (
        (event.key === "n" || event.key === "N") &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey
      ) {
        event.preventDefault();
        navigate("/new");
      }
      if (event.key === "?") {
        event.preventDefault();
        setModal("help");
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, mobileOpen]);

  const history = useQuery({
    queryKey: ["history", "workspace"],
    queryFn: getAllHistory,
  });
  const config = useQuery({
    queryKey: ["config", "shell"],
    queryFn: getRunConfig,
    enabled: modal === "settings",
    retry: false,
  });
  const announcements = useQuery({
    queryKey: ["announcements"],
    queryFn: getAnnouncements,
    retry: false,
  });

  const active = useQuery({
    queryKey: ["runs", "active"],
    queryFn: getActiveRun,
    enabled: modal === "settings" || modal === "clear",
    refetchInterval: 1000,
  });
  const items = (history.data?.items ?? []).filter(
    (item) => item.source === "run" || item.source === "saved",
  );
  const top = location.pathname.split("/")[1] || "overview";
  const activeRoute = top === "history" || top === "runs" ? "history" : top;
  const breadcrumb =
    top === "history" && location.pathname.split("/")[2]
      ? "Research report"
      : (BREADCRUMBS[top] ?? "Overview");
  const matches = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return items.slice(0, 6);
    return items
      .filter((item) => item.ticker.toLowerCase().includes(query))
      .slice(0, 8);
  }, [items, search]);

  async function handleClear() {
    if (confirmClear !== "CLEAR") {
      setClearState("Type CLEAR to confirm.");
      return;
    }
    setClearing(true);
    try {
      const result = await clearCheckpoints();
      setClearState(result.cleared);
      setConfirmClear("");
      setModal("settings");
    } catch (exc) {
      setClearState(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        {ui("Skip to workspace")}
      </a>
      <aside
        className={`sidebar ${mobileOpen ? "open" : ""}`}
        id="sidebar"
        inert={mobile && !mobileOpen}
        aria-label={ui("Workspace navigation")}
      >
        <Link className="brand" to="/overview">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32">
              <path d="M5 23V10h7v13M14 23V5h7v18M23 23V14h5v9" />
            </svg>
          </span>
          <span>{ui("TradingAgents")}</span>
        </Link>
        <nav className="nav-list">
          {NAV.map((item) => (
            <Link
              key={item.route}
              to={`/${item.route}`}
              className={activeRoute === item.route ? "active" : ""}
              aria-current={activeRoute === item.route ? "page" : undefined}
            >
              <Icon name={item.icon} />
              {ui(item.label)}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button
            type="button"
            className="sidebar-button"
            onClick={() => setModal("settings")}
          >
            <Icon name="settings" />
            {ui("Workspace settings")}
          </button>
          <button
            type="button"
            className="sidebar-button"
            onClick={() => setModal("help")}
          >
            <Icon name="help" />
            {ui("Help & shortcuts")}
            <span className="nav-shortcut">{ui("?")}</span>
          </button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button mobile-menu"
              type="button"
              aria-label={ui("Open navigation")}
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen((open) => !open)}
            >
              <Icon name="menu" />
            </button>
            <span className="breadcrumb-icon">
              <Icon name="layers" />
            </span>
            <span>{ui("Workspace")}</span>
            <span className="breadcrumb-slash">{ui("/")}</span>
            <span>{ui(breadcrumb)}</span>
          </div>
          <div className="topbar-actions">
            <LanguageSwitch />
            <button
              className="search-trigger"
              type="button"
              onClick={() => setModal("search")}
            >
              <Icon name="search" />
              <span>{ui("Find research...")}</span>
              <kbd>{"⌘ K"}</kbd>
            </button>
            <button
              className="icon-button notification-button"
              type="button"
              aria-label={ui("View announcements")}
              onClick={() => setModal("announcements")}
            >
              <Icon name="bell" />
              {announcements.data?.announcements.length ? <i /> : null}
            </button>
          </div>
        </header>

        <main id="main" tabIndex={-1}>
          <div className="page-enter">
            <AnnouncementsGate />
            {children}
          </div>
        </main>
      </div>

      <Modal
        open={modal === "settings"}
        title={ui("Workspace settings")}
        onClose={() => setModal(null)}
      >
        <div className="setting-row">
          <span>{ui("Appearance")}</span>
          <label className="sr-only" htmlFor="theme">
            {ui("Appearance")}
          </label>
          <select
            id="theme"
            value={theme}
            onChange={(event) => setTheme(event.target.value)}
          >
            <option value="light">{ui("Light / paper")}</option>
            <option value="dark">{ui("Dark / forest")}</option>
          </select>
        </div>
        <div className="setting-row">
          <span>{ui("Interface language")}</span>
          <LanguageSwitch />
        </div>
        <p className="setting-section">
          {ui("MODEL PROVIDERS · SERVER STATUS")}
        </p>
        {config.isLoading ? <p>{ui("Loading configuration...")}</p> : null}
        {config.isError ? (
          <p className="field-error">{ui("Configuration is unavailable.")}</p>
        ) : null}
        {config.data
          ? ["deepseek", "openai", "anthropic", "ollama"].map((provider) => {
              const status = config.data?.key_status[provider] ?? "unknown";
              return (
                <div className="setting-row" key={provider}>
                  <span>
                    {ui(
                      config.data?.providers.find(
                        (item) => item.key === provider,
                      )?.label ?? provider,
                    )}
                  </span>
                  <span
                    className={`status-tag ${status === "configured" || status === "not_required" ? "" : "neutral"}`}
                  >
                    {ui(KEY_STATUS_LABELS[status] ?? status)}
                  </span>
                </div>
              );
            })
          : null}
        <p className="setting-section">{ui("RECOVERY")}</p>
        <div className="setting-row">
          <span>
            {ui("Checkpoint storage")}
            <small>{ui("Saved reports are retained.")}</small>
          </span>
          <button
            className="button"
            disabled={Boolean(active.data?.run_id) || active.isFetching}
            onClick={() => {
              setConfirmClear("");
              setClearState(null);
              setModal("clear");
            }}
          >
            {ui("Clear all checkpoints")}
          </button>
        </div>
        {clearState !== null ? (
          <p className="inline-note">
            {typeof clearState === "number"
              ? ui("{{count}} checkpoint files cleared.", { count: clearState })
              : ui(clearState)}
          </p>
        ) : null}
      </Modal>

      <Modal
        open={modal === "help"}
        title={ui("A workspace for considered decisions")}
        onClose={() => setModal(null)}
      >
        <p>
          {ui(
            "Choose an instrument, build an analyst team, follow the debate, then read the final assessment. Backtesting and the decision journal help you revisit your reasoning.",
          )}
        </p>
        <details className="disclosure">
          <summary>{ui("Diagnostic tools")}</summary>
          <p>
            {ui(
              "Replay preset cases to inspect debate rules. Your analysis results are not compared here.",
            )}
          </p>
          <Link
            className="text-button"
            to="/comparison"
            onClick={() => setModal(null)}
          >
            {ui("Policy comparison")}
            <Icon name="arrow" />
          </Link>
        </details>
        <div className="keyboard-row">
          <span>{ui("Find research")}</span>
          <kbd>{ui("⌘ / Ctrl K")}</kbd>
        </div>
        <div className="keyboard-row">
          <span>{ui("New analysis")}</span>
          <kbd>{"N"}</kbd>
        </div>
        <div className="keyboard-row">
          <span>{ui("Close a dialog")}</span>
          <kbd>{ui("Esc")}</kbd>
        </div>
      </Modal>

      <Modal
        open={modal === "search"}
        title={ui("Find a perspective")}
        className="search-modal"
        onClose={() => setModal(null)}
      >
        <label className="sr-only" htmlFor="command-input">
          {ui("Search research by ticker")}
        </label>
        <input
          className="input"
          id="command-input"
          placeholder={ui("Search a ticker...")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="search-results">
          {matches.length ? (
            matches.map((item) => (
              <button
                key={item.artifact_id}
                type="button"
                className="search-result"
                onClick={() => {
                  setModal(null);
                  navigate(`/history/${item.artifact_id}`);
                }}
              >
                <CompanyLogo ticker={item.ticker} />
                <span>
                  <strong>{item.ticker}</strong>
                  <small>{uiHistoryTitle(item.title, item.ticker)}</small>
                </span>
                <Rating value={item.rating} />
              </button>
            ))
          ) : (
            <div className="empty-state">
              <strong>{ui("No matching research")}</strong>
              <p>{ui("Try another ticker.")}</p>
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={modal === "announcements"}
        title={ui("Workspace notes")}
        onClose={() => setModal(null)}
      >
        {announcements.data?.announcements.length ? (
          announcements.data.announcements.map((item, index) => (
            <p key={index}>{ui(item)}</p>
          ))
        ) : (
          <p>{ui("No announcements are available.")}</p>
        )}
        <div className="modal-actions">
          <button className="button primary" onClick={() => setModal(null)}>
            {ui("Got it")}
          </button>
        </div>
      </Modal>
      <Modal
        open={modal === "clear"}
        title={ui("Clear checkpoints?")}
        onClose={() => setModal("settings")}
      >
        <p>
          {ui(
            "Type CLEAR to remove all checkpoints. Completed reports are retained.",
          )}
        </p>
        <div className="form-field">
          <label htmlFor="clear-confirm">{ui("Confirmation")}</label>
          <input
            id="clear-confirm"
            autoComplete="off"
            spellCheck={false}
            placeholder={ui("CLEAR")}
            value={confirmClear}
            onChange={(event) => setConfirmClear(event.target.value)}
          />
        </div>
        {clearState !== null ? (
          <p className="field-error" role="alert">
            {typeof clearState === "number"
              ? ui("{{count}} checkpoint files cleared.", { count: clearState })
              : ui(clearState)}
          </p>
        ) : null}
        <div className="modal-actions">
          <button
            className="button"
            disabled={clearing}
            onClick={() => setModal("settings")}
          >
            {ui("Keep checkpoints")}
          </button>
          <button
            className="button danger"
            disabled={
              confirmClear !== "CLEAR" ||
              clearing ||
              Boolean(active.data?.run_id) ||
              active.isFetching
            }
            onClick={() => void handleClear()}
          >
            {clearing ? ui("Clearing…") : ui("Clear checkpoints")}
          </button>
        </div>
      </Modal>
    </div>
  );
}
