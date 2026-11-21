// REQ-WEB-002/007, ADR-003, INV-WEB-014: group recorded state for presentation.
import type { RunMessage, RunState } from "../stores/runStore";

export const RUN_STAGES = [
  {
    id: "analysts",
    label: "Analyst team",
    sections: [
      "market_report",
      "sentiment_report",
      "news_report",
      "fundamentals_report",
    ],
  },
  { id: "research", label: "Research debate", sections: ["investment_plan"] },
  {
    id: "trading",
    label: "Trading plan",
    sections: ["trader_investment_plan"],
  },
  { id: "risk", label: "Risk review", sections: ["final_trade_decision"] },
] as const;
export type StageId = (typeof RUN_STAGES)[number]["id"];
export type ActivityState = Pick<
  RunState,
  "messages" | "sections" | "agents" | "status" | "connection" | "stats"
> & { wallTimes?: Record<string, number> };

export const RESEARCH_ROLES = [
  "Bull Researcher",
  "Bear Researcher",
  "Research Manager",
];
export const RISK_ROLES = [
  "Aggressive Analyst",
  "Conservative Analyst",
  "Neutral Analyst",
  "Portfolio Manager",
];

export function messageType(message: RunMessage): string {
  const aliases: Record<string, string> = {
    AIMessage: "Agent",
    HumanMessage: "User",
    ToolMessage: "Data",
    SystemMessage: "System",
  };
  const type = aliases[message.type ?? ""] ?? message.type ?? "System";
  return type === "User" && message.content.trim() === "Continue"
    ? "Control"
    : type;
}

export function stageForAgent(agent: string): StageId {
  return agent === "Research Team" || RESEARCH_ROLES.includes(agent)
    ? "research"
    : agent === "Trader"
      ? "trading"
      : agent === "Risk Team" || RISK_ROLES.includes(agent)
        ? "risk"
        : "analysts";
}

export function activityProgress(state: ActivityState) {
  const complete = RUN_STAGES.map((stage) => {
    if (stage.id !== "analysts")
      return stage.sections.some((key) => Boolean(state.sections[key]));
    const analysts = Object.entries(state.agents).filter(
      ([name]) => stageForAgent(name) === "analysts",
    );
    return (
      analysts.length > 0 &&
      analysts.every(([, status]) => status === "completed")
    );
  });
  const evidence = [0];
  Object.entries(state.agents).forEach(([name, status]) => {
    if (status !== "pending")
      evidence.push(
        RUN_STAGES.findIndex((stage) => stage.id === stageForAgent(name)),
      );
  });
  state.messages.forEach((message) => {
    const index = RUN_STAGES.findIndex((stage) => stage.id === message.stage);
    if (index >= 0) evidence.push(index);
  });
  RUN_STAGES.forEach((stage, index) => {
    if (stage.sections.some((key) => Boolean(state.sections[key])))
      evidence.push(index);
    if (complete[index] && index < RUN_STAGES.length - 1)
      evidence.push(index + 1);
  });
  const currentIndex = Math.max(...evidence);
  const terminal = ["completed", "failed", "cancelled"].includes(state.status);
  const stages = RUN_STAGES.map((stage, index) => ({
    ...stage,
    status: complete[index]
      ? "Complete"
      : index === currentIndex
        ? terminal
          ? state.status === "completed"
            ? "Recorded"
            : "Stopped"
          : state.status === "idle" || state.status === "starting"
            ? "Waiting"
            : "In progress"
        : index < currentIndex
          ? "Not recorded"
          : "Pending",
  }));
  return {
    stages,
    current: RUN_STAGES[currentIndex].id,
    completed: stages.filter((stage) => stage.status === "Complete").length,
  };
}
