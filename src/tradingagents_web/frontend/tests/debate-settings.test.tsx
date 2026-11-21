// REQ-WEB-001/003/013/014, FR-DDT-004, ADR-001/007: form behavior and public values.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../src/i18n";
import {
  DebateSettings,
  DebatePolicySummary,
} from "../src/components/DebateSettings";
import {
  readDebatePolicy,
  validateDebateSettings,
  type DebatePolicy,
} from "../src/utils/debateSettings";

export const policy: DebatePolicy = {
  enabled: true,
  max_debate_rounds: 3,
  no_new_evidence_patience: 1,
  stance_distance_threshold: 1,
  confidence_delta_threshold: 0.25,
  max_calls: 30,
  max_tokens: 50000,
  max_time: 600,
  reserved_summary_tokens: 4000,
  reserved_summary_seconds: 90,
  next_round_estimate_tokens: 2000,
  next_round_estimate_seconds: 60,
};
afterEach(async () => {
  cleanup();
  await i18n.changeLanguage("en");
});

describe("debate settings", () => {
  it("only restores complete typed public settings and drops arbitrary draft fields", () => {
    expect(readDebatePolicy({ ...policy, trace_field: "private" })).toEqual(
      policy,
    );
    expect(readDebatePolicy({ enabled: true })).toBeNull();
    expect(readDebatePolicy({ ...policy, enabled: "false" })).toBeNull();
    expect(readDebatePolicy({ ...policy, max_time: Infinity })).toBeNull();
  });

  it("rejects malformed rounds, scalar limits and cross-budget constraints", () => {
    expect(validateDebateSettings(policy, 2)).toEqual([]);
    expect(
      validateDebateSettings(
        {
          ...policy,
          max_debate_rounds: 1.5,
          no_new_evidence_patience: 0,
          stance_distance_threshold: 5,
          confidence_delta_threshold: 2,
          max_time: Infinity,
        },
        0,
      ).map(([id]) => id),
    ).toEqual([
      "debate-max_debate_rounds",
      "debate-no_new_evidence_patience",
      "debate-stance_distance_threshold",
      "debate-confidence_delta_threshold",
      "debate-max_time",
      "debate-risk-rounds",
    ]);
    const errors = validateDebateSettings(
      {
        ...policy,
        reserved_summary_tokens: 50000,
        reserved_summary_seconds: 600,
      },
      2,
    );
    expect(errors.map(([id]) => id)).toEqual([
      "debate-reserved_summary_tokens",
      "debate-reserved_summary_seconds",
    ]);
  });

  it("changes mode using a boolean and keeps environment-locked caps read-only", () => {
    const onPolicy = vi.fn();
    render(
      <DebateSettings
        policy={policy}
        riskRounds={2}
        locks={{ max_debate_rounds: true, max_risk_discuss_rounds: true }}
        errors={[]}
        onPolicy={onPolicy}
        onRisk={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Debate rules & budgets"));
    expect(screen.getByLabelText("Maximum debate rounds")).toBeDisabled();
    expect(screen.getByLabelText("Risk discussion rounds")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Debate mode"), {
      target: { value: "fixed" },
    });
    expect(onPolicy).toHaveBeenCalledWith({ ...policy, enabled: false });
  });

  it("shows translated errors and recorded settings without inventing legacy data", async () => {
    await i18n.changeLanguage("zh");
    const { rerender } = render(
      <DebateSettings
        policy={policy}
        riskRounds={2}
        locks={{}}
        errors={[
          [
            "debate-max_calls",
            "{{field}} must be a positive whole number.",
            { field: "Maximum debate model calls" },
          ],
        ]}
        onPolicy={vi.fn()}
        onRisk={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("辩论规则与预算"));
    expect(screen.getByText("辩论模型调用上限必须为正整数。")).toBeVisible();
    rerender(<DebatePolicySummary policy={policy} riskRounds={2} />);
    fireEvent.click(screen.getByText(/实际生效的辩论设置/));
    expect(screen.getByText("风险讨论轮数")).toBeVisible();
    rerender(<DebatePolicySummary policy={null} />);
    expect(screen.queryByText(/实际生效/)).not.toBeInTheDocument();
  });
});
