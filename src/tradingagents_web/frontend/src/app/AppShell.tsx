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

const NAV = [
  { route: "overview", label: "Overview", icon: "grid" },
  { route: "history", label: "Analysis history", icon: "clock" },
  { route: "backtest", label: "Backtesting", icon: "sliders" },
  { route: "audit", label: "Research audit", icon: "shield" },
  { route: "comparison", label: "Policy comparison", icon: "layers" },
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
  audit: "Research audit",
  comparison: "Policy comparison",
  journal: "Decision journal",
  new: "New analysis",
  runs: "Live run",
};

export function AppShell({ children }: { children: ReactNode }) {
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
  const [clearState, setClearState] = useState<string | null>(null);

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
  const recent = items.slice(0, 3);
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
      setClearState(
        `${result.cleared} checkpoint ${result.cleared === 1 ? "file" : "files"} cleared.`,
      );
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
        Skip to workspace
      </a>
      <aside
        className={`sidebar ${mobileOpen ? "open" : ""}`}
        id="sidebar"
        inert={mobile && !mobileOpen}
        aria-label="Workspace navigation"
      >
        <Link className="brand" to="/overview">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32">
              <path d="M5 23V10h7v13M14 23V5h7v18M23 23V14h5v9" />
            </svg>
          </span>
          <span>
            TradingAgents
            <span className="brand-caption">A RESEARCH WORKSPACE</span>
          </span>
        </Link>
        <div className="workspace-selector">
          <span className="workspace-symbol">W</span>
          <span>
            Personal workspace
            <small>Local · Single user</small>
          </span>
          <span className="workspace-dot" aria-hidden="true" />
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav className="nav-list">
          {NAV.map((item) => (
            <Link
              key={item.route}
              to={`/${item.route}`}
              className={activeRoute === item.route ? "active" : ""}
              aria-current={activeRoute === item.route ? "page" : undefined}
            >
              <Icon name={item.icon} />
              {item.label}
              {item.route === "history" ? (
                <span className="nav-count">{items.length}</span>
              ) : null}
            </Link>
          ))}
        </nav>
        <div className="sidebar-divider" />
        <div className="nav-label nav-label-row">
          <span>RECENT RESEARCH</span>
          <Icon name="layers" />
        </div>
        <nav className="research-links" aria-label="Recent research">
          {recent.map((item) => (
            <Link key={item.artifact_id} to={`/history/${item.artifact_id}`}>
              <span className="research-symbol">{item.ticker}</span>
              <span>{item.title}</span>
              <Icon name="chevron" />
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
            Workspace settings
          </button>
          <button
            type="button"
            className="sidebar-button"
            onClick={() => setModal("help")}
          >
            <Icon name="help" />
            Help & shortcuts
            <span className="nav-shortcut">?</span>
          </button>
          <div className="sidebar-footer">
            <span className="local-indicator" />
            Runs locally. Thinks together.
            <span className="version">v0.5</span>
          </div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button mobile-menu"
              type="button"
              aria-label="Open navigation"
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen((open) => !open)}
            >
              <Icon name="menu" />
            </button>
            <span className="breadcrumb-icon">
              <Icon name="layers" />
            </span>
            <span>Workspace</span>
            <span className="breadcrumb-slash">/</span>
            <span>{breadcrumb}</span>
          </div>
          <div className="topbar-actions">
            <span className="preview-badge">
              <span />
              Local workspace
            </span>
            <button
              className="search-trigger"
              type="button"
              onClick={() => setModal("search")}
            >
              <Icon name="search" />
              <span>Find research...</span>
              <kbd>⌘ K</kbd>
            </button>
            <button
              className="icon-button notification-button"
              type="button"
              aria-label="View announcements"
              onClick={() => setModal("announcements")}
            >
              <Icon name="bell" />
              {announcements.data?.announcements.length ? <i /> : null}
            </button>
            <button
              className="avatar-button"
              type="button"
              aria-label="Open local workspace settings"
              onClick={() => setModal("settings")}
            >
              W
            </button>
          </div>
        </header>

        <main id="main" tabIndex={-1}>
          <div className="page-enter">
            <AnnouncementsGate />
            {children}
          </div>
        </main>

        <footer className="main-footer">
          <span>Built for research. Decisions remain yours.</span>
          <span>
            <span className="local-indicator" /> Runs locally
            <span className="footer-dot">·</span> Single user
          </span>
        </footer>
      </div>

      <Modal
        open={modal === "settings"}
        title="Workspace settings"
        onClose={() => setModal(null)}
      >
        <p>
          Local preferences and server-owned configuration. No credentials are
          read or accepted.
        </p>
        <div className="setting-row">
          <span>
            Appearance
            <small>Comfortable in daylight or after hours.</small>
          </span>
          <label className="sr-only" htmlFor="theme">
            Appearance
          </label>
          <select
            id="theme"
            value={theme}
            onChange={(event) => setTheme(event.target.value)}
          >
            <option value="light">Light / paper</option>
            <option value="dark">Dark / forest</option>
          </select>
        </div>
        <p className="setting-section">MODEL PROVIDERS · SERVER STATUS</p>
        {config.isLoading ? <p>Loading configuration...</p> : null}
        {config.isError ? (
          <p className="field-error">Configuration is unavailable.</p>
        ) : null}
        {config.data
          ? ["deepseek", "openai", "anthropic", "ollama"].map((provider) => {
              const status = config.data?.key_status[provider] ?? "unknown";
              return (
                <div className="setting-row" key={provider}>
                  <span>
                    {config.data?.providers.find(
                      (item) => item.key === provider,
                    )?.label ?? provider}
                    <small>
                      {provider === "ollama"
                        ? "Local model runtime"
                        : provider === config.data?.defaults.llm_provider
                          ? "Selected research provider"
                          : "Available provider"}
                    </small>
                  </span>
                  <span
                    className={`status-tag ${status === "configured" || status === "not_required" ? "" : "neutral"}`}
                  >
                    {KEY_STATUS_LABELS[status] ?? status}
                  </span>
                </div>
              );
            })
          : null}
        <p className="setting-section">RECOVERY</p>
        <div className="setting-row">
          <span>
            Checkpoint storage
            <small>
              Clearing never removes saved reports. No pre-clear inventory is
              exposed.
            </small>
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
            Clear all checkpoints
          </button>
        </div>
        {clearState ? <p className="inline-note">{clearState}</p> : null}
        <p className="inline-note">
          Provider configuration is server-owned. API keys and server filesystem
          paths never belong in this interface.
        </p>
      </Modal>

      <Modal
        open={modal === "help"}
        title="A workspace for considered decisions"
        onClose={() => setModal(null)}
      >
        <p>
          Choose an instrument, build an analyst team, follow the debate, then
          read the final assessment. Backtesting and the decision journal help
          you revisit your reasoning.
        </p>
        <div className="keyboard-row">
          <span>Find research</span>
          <kbd>⌘ / Ctrl K</kbd>
        </div>
        <div className="keyboard-row">
          <span>New analysis</span>
          <kbd>N</kbd>
        </div>
        <div className="keyboard-row">
          <span>Close a dialog</span>
          <kbd>Esc</kbd>
        </div>
        <p className="inline-note">
          Choose an instrument and date, select the research team, then review
          your setup. Reports, outcomes and reflections remain advisory.
        </p>
      </Modal>

      <Modal
        open={modal === "search"}
        title="Find a perspective"
        className="search-modal"
        onClose={() => setModal(null)}
      >
        <label className="sr-only" htmlFor="command-input">
          Search research by ticker
        </label>
        <input
          className="input"
          id="command-input"
          placeholder="Search a ticker..."
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
                  <small>{item.title}</small>
                </span>
                <Rating value={item.rating} />
              </button>
            ))
          ) : (
            <div className="empty-state">
              <strong>No matching research</strong>
              <p>Try another ticker.</p>
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={modal === "announcements"}
        title="Workspace notes"
        onClose={() => setModal(null)}
      >
        {announcements.data?.announcements.length ? (
          announcements.data.announcements.map((item, index) => (
            <p key={index}>{item}</p>
          ))
        ) : (
          <p>No announcements are available.</p>
        )}
        <div className="modal-actions">
          <button className="button primary" onClick={() => setModal(null)}>
            Got it
          </button>
        </div>
      </Modal>
      <Modal
        open={modal === "clear"}
        title="Clear checkpoints?"
        onClose={() => setModal("settings")}
      >
        <p>
          Type CLEAR to remove all checkpoints. The number cleared is known only
          after the action completes. Completed reports are retained.
        </p>
        <div className="form-field">
          <label htmlFor="clear-confirm">Confirmation</label>
          <input
            id="clear-confirm"
            autoComplete="off"
            spellCheck={false}
            placeholder="CLEAR"
            value={confirmClear}
            onChange={(event) => setConfirmClear(event.target.value)}
          />
        </div>
        {clearState ? (
          <p className="field-error" role="alert">
            {clearState}
          </p>
        ) : null}
        <div className="modal-actions">
          <button
            className="button"
            disabled={clearing}
            onClick={() => setModal("settings")}
          >
            Keep checkpoints
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
            {clearing ? "Clearing…" : "Clear checkpoints"}
          </button>
        </div>
      </Modal>
    </div>
  );
}
