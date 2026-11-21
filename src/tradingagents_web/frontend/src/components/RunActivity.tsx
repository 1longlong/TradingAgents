import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-002/007/021, ADR-003, INV-WEB-012/014: recorded stage activity only.
import { useEffect, useRef, useState } from "react";
import { Markdown } from "./Markdown";
import { Icon } from "./Icon";
import {
  activityProgress,
  stageForAgent,
  messageType,
  type ActivityState,
  type StageId,
} from "../utils/runActivity";
import { sectionLabel } from "../utils/workspace";

export function RunActivity({ state }: { state: ActivityState }) {
  useUILanguage();
  const { stages, current, completed } = activityProgress(state);
  const [selection, setSelection] = useState<StageId | "all">(current);
  const [filter, setFilter] = useState("all");
  const [follow, setFollow] = useState(true);
  const previousStage = useRef(current);
  const list = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    if (previousStage.current !== current) {
      previousStage.current = current;
      setSelection(current);
      setFollow(true);
    }
  }, [current]);
  const selectedStage = stages.find((stage) => stage.id === selection);
  const messages = state.messages
    .filter((message) => {
      if (selection !== "all" && message.stage !== selection) return false;
      const type = messageType(message);
      return (
        filter === "all" ||
        (filter === "system"
          ? ["System", "Control", "User"].includes(type)
          : type === filter)
      );
    })
    .slice()
    .reverse();
  const sections = Object.entries(state.sections).filter(
    ([key]) =>
      selection === "all" ||
      selectedStage?.sections.some((section) => section === key),
  );
  useEffect(() => {
    if (follow && list.current) list.current.scrollTop = 0;
  }, [state.messages, selection, filter, follow]);
  const tabs = [
    ...stages.map((stage) => ({
      id: stage.id as StageId | "all",
      label: stage.label,
      status: stage.status,
    })),
    { id: "all" as const, label: "All activity", status: "" },
  ];
  function selectTab(index: number) {
    setSelection(tabs[index].id);
    setFollow(true);
    tabRefs.current[index]?.focus();
  }
  return (
    <section className="panel run-workspace" aria-label={ui("Run activity")}>
      <header className="run-workspace-head">
        <div>
          <h2>{ui("Run activity")}</h2>
          <p role="status">
            {ui("{{stage}} · {{status}} · {{connection}}", {
              stage: selectedStage?.label ?? "All activity",
              status: state.status,
              connection:
                state.connection === "live"
                  ? "Live"
                  : state.connection === "closed"
                    ? "Recorded"
                    : state.connection,
            })}
          </p>
        </div>
        <span className="run-stage-count">
          {ui("{{completed}} / {{total}} stages complete", {
            completed,
            total: stages.length,
          })}
        </span>
      </header>
      <div
        className="run-stage-tabs"
        role="tablist"
        aria-label={ui("Analysis stages")}
        onKeyDown={(event) => {
          const index = tabRefs.current.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          if (index < 0) return;
          const next =
            event.key === "ArrowRight"
              ? (index + 1) % tabs.length
              : event.key === "ArrowLeft"
                ? (index + tabs.length - 1) % tabs.length
                : event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? tabs.length - 1
                    : null;
          if (next != null) {
            event.preventDefault();
            selectTab(next);
          }
        }}
      >
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            ref={(element) => {
              tabRefs.current[index] = element;
            }}
            id={`run-tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={selection === tab.id}
            aria-controls="run-stage-panel"
            tabIndex={selection === tab.id ? 0 : -1}
            className={`run-stage-tab ${tab.status === "Complete" ? "is-complete" : ""}`}
            onClick={() => {
              setSelection(tab.id);
              setFollow(true);
            }}
          >
            {tab.id !== "all" ? (
              <span className="run-stage-number">
                {tab.status === "Complete" ? <Icon name="check" /> : index + 1}
              </span>
            ) : (
              <Icon name="activity" />
            )}
            <span>
              {ui(tab.label)}
              {tab.status ? <small>{ui(tab.status)}</small> : null}
            </span>
          </button>
        ))}
      </div>
      <details className="run-role-details run-stat-details">
        <summary>{ui("Run statistics")}</summary>
        <div className="activity-stats run-stats">
          {[
            ["Model calls", state.stats.llm_calls],
            [
              "Agents",
              state.stats.agents_completed == null
                ? undefined
                : `${state.stats.agents_completed} / ${state.stats.agents_total ?? "—"}`,
            ],
            ["Tool calls", state.stats.tool_calls],
            ["Input tokens", state.stats.tokens_in],
            ["Output tokens", state.stats.tokens_out],
            [
              "Reports",
              state.stats.reports_completed == null
                ? undefined
                : `${state.stats.reports_completed} / ${state.stats.reports_total ?? "—"}`,
            ],
            [
              "Elapsed",
              state.stats.elapsed == null
                ? undefined
                : ui("{{value0}}s", { value0: state.stats.elapsed.toFixed(1) }),
            ],
          ].map(([label, value]) => (
            <div key={label}>
              <small>{ui(label)}</small>
              <strong>
                {value == null
                  ? ui("—")
                  : typeof value === "number"
                    ? ui(value.toLocaleString())
                    : ui(value)}
              </strong>
            </div>
          ))}
        </div>
      </details>
      <details className="run-role-details">
        <summary>{ui("Agent status & analyst timing")}</summary>
        <ul className="run-role-list">
          {Object.entries(state.agents)
            .filter(
              ([name]) =>
                (selection === "all" || stageForAgent(name) === selection) &&
                (!["Research Team", "Risk Team"].includes(name) ||
                  !Object.keys(state.agents).some(
                    (role) =>
                      role !== name &&
                      stageForAgent(role) === stageForAgent(name),
                  )),
            )
            .map(([name, status]) => (
              <li key={name}>
                <span>{ui(name)}</span>
                <span>{ui(status.replaceAll("_", " "))}</span>
                <span>
                  {state.wallTimes?.[name] == null
                    ? "—"
                    : ui("{{value0}}s", {
                        value0: state.wallTimes[name].toFixed(2),
                      })}
                </span>
              </li>
            ))}
        </ul>
      </details>
      <div
        role="tabpanel"
        id="run-stage-panel"
        aria-labelledby={`run-tab-${selection}`}
        tabIndex={0}
      >
        <div className="run-feed-toolbar">
          <h3>{ui(selectedStage?.label ?? "All activity")}</h3>
          <div>
            <label className="run-follow">
              <input
                type="checkbox"
                checked={follow}
                onChange={(event) => setFollow(event.target.checked)}
              />
              {ui("Follow latest")}
            </label>
            <label className="audit-scenario">
              <span className="sr-only">{ui("Filter activity")}</span>
              <select
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
              >
                <option value="all">{ui("All events")}</option>
                <option value="Agent">{ui("Agent messages")}</option>
                <option value="Tool">{ui("Tool calls")}</option>
                <option value="Data">{ui("Tool results")}</option>
                <option value="system">{ui("System messages")}</option>
              </select>
            </label>
          </div>
        </div>
        <div
          className={`run-stage-content ${sections.length ? "has-reports" : ""}`}
        >
          <div
            className="run-message-list"
            role="region"
            ref={list}
            tabIndex={0}
            aria-label={ui("Stage messages")}
            onScroll={() => {
              if (list.current && list.current.scrollTop > 24) setFollow(false);
            }}
          >
            {messages.length ? (
              messages.map((message) => (
                <article className="run-message" key={message.id}>
                  <header>
                    <span
                      className={`run-message-kind kind-${messageType(message).toLowerCase()}`}
                    >
                      {messageType(message) === "Tool"
                        ? ui("Tool call")
                        : messageType(message) === "Data"
                          ? ui("Tool result")
                          : ui(messageType(message))}
                    </span>
                    {message.speaker ? (
                      <strong>{ui(message.speaker)}</strong>
                    ) : null}
                    <time>{ui(message.timestamp)}</time>
                  </header>
                  {message.content.length > 700 ? (
                    <details>
                      <summary>
                        {ui(message.content.slice(0, 200))}
                        {ui("…")}
                        {ui(" ")}
                        <span>{ui("Show full message")}</span>
                      </summary>
                      <pre>{message.content}</pre>
                    </details>
                  ) : (
                    <pre>{message.content}</pre>
                  )}
                </article>
              ))
            ) : (
              <div className="run-activity-empty">
                {selectedStage?.status === "Pending"
                  ? ui("This stage has not started.")
                  : filter !== "all"
                    ? ui("No matching events.")
                    : ["completed", "failed", "cancelled"].includes(
                          state.status,
                        ) || selectedStage?.status === "Complete"
                      ? ui("No recorded messages.")
                      : ui("Waiting for messages…")}
              </div>
            )}
          </div>
          {sections.length ? (
            <div
              key={selection}
              className="run-stage-reports"
              aria-label={ui("Stage reports")}
            >
              {sections.map(([key, content]) => (
                <section key={key}>
                  <h4>{ui(sectionLabel(key))}</h4>
                  <Markdown>{content}</Markdown>
                </section>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
