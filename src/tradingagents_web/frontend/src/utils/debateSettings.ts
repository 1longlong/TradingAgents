// REQ-WEB-001/013, FR-DDT-004, ADR-001/007: form feedback; core validation is authoritative.
export type DebatePolicy = {
  enabled: boolean;
  max_debate_rounds: number;
  no_new_evidence_patience: number;
  stance_distance_threshold: number;
  confidence_delta_threshold: number;
  max_calls: number;
  max_tokens: number;
  max_time: number;
  reserved_summary_tokens: number;
  reserved_summary_seconds: number;
  next_round_estimate_tokens: number;
  next_round_estimate_seconds: number;
};
export type DebateNumberKey = Exclude<keyof DebatePolicy, "enabled">;
export type DebateFieldError = [string, string, Record<string, unknown>?];
export const DEBATE_FIELDS: Array<{
  key: DebateNumberKey;
  label: string;
  min: number;
  max?: number;
  integer?: boolean;
  positive?: boolean;
  group: "rounds" | "thresholds" | "budget";
}> = [
  {
    key: "max_debate_rounds",
    label: "Maximum debate rounds",
    min: 1,
    integer: true,
    group: "rounds",
  },
  {
    key: "no_new_evidence_patience",
    label: "Rounds without new evidence before stopping",
    min: 1,
    integer: true,
    group: "thresholds",
  },
  {
    key: "stance_distance_threshold",
    label: "Stance distance threshold (0–4)",
    min: 0,
    max: 4,
    group: "thresholds",
  },
  {
    key: "confidence_delta_threshold",
    label: "Confidence change threshold (0–1)",
    min: 0,
    max: 1,
    group: "thresholds",
  },
  {
    key: "max_calls",
    label: "Maximum debate model calls",
    min: 1,
    integer: true,
    group: "budget",
  },
  {
    key: "max_tokens",
    label: "Debate token budget",
    min: 1,
    integer: true,
    group: "budget",
  },
  {
    key: "max_time",
    label: "Debate time budget (seconds)",
    min: 0,
    positive: true,
    group: "budget",
  },
  {
    key: "reserved_summary_tokens",
    label: "Summary token reserve",
    min: 0,
    integer: true,
    group: "budget",
  },
  {
    key: "reserved_summary_seconds",
    label: "Summary time reserve (seconds)",
    min: 0,
    group: "budget",
  },
  {
    key: "next_round_estimate_tokens",
    label: "Next-round token estimate",
    min: 0,
    integer: true,
    group: "budget",
  },
  {
    key: "next_round_estimate_seconds",
    label: "Next-round time estimate (seconds)",
    min: 0,
    group: "budget",
  },
];

export function readDebatePolicy(value: unknown): DebatePolicy | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.enabled !== "boolean") return null;
  const result: Record<string, number | boolean> = { enabled: raw.enabled };
  for (const field of DEBATE_FIELDS) {
    const item = raw[field.key];
    if (typeof item !== "number" || !Number.isFinite(item)) return null;
    result[field.key] = item;
  }
  return result as DebatePolicy;
}

export function validateDebateSettings(
  policy: DebatePolicy | null,
  riskRounds: number | null,
): DebateFieldError[] {
  if (!policy) return [];
  const errors: DebateFieldError[] = [];
  for (const field of DEBATE_FIELDS) {
    const value = policy[field.key];
    let error: string | null = null;
    if (!Number.isFinite(value)) error = "{{field}} must be a finite number.";
    else if (
      field.integer &&
      (!Number.isSafeInteger(value) || value < field.min)
    )
      error =
        field.min === 0
          ? "{{field}} must be a nonnegative whole number."
          : "{{field}} must be a positive whole number.";
    else if (field.positive && value <= 0)
      error = "{{field}} must be greater than zero.";
    else if (value < field.min || (field.max != null && value > field.max))
      error =
        field.max != null
          ? "{{field}} must be between {{min}} and {{max}}."
          : "{{field}} must be a nonnegative number.";
    if (error)
      errors.push([
        `debate-${field.key}`,
        error,
        { field: field.label, min: field.min, max: field.max },
      ]);
  }
  if (riskRounds == null || !Number.isSafeInteger(riskRounds) || riskRounds < 1)
    errors.push([
      "debate-risk-rounds",
      "{{field}} must be a positive whole number.",
      { field: "Risk discussion rounds" },
    ]);
  if (policy.reserved_summary_tokens >= policy.max_tokens)
    errors.push([
      "debate-reserved_summary_tokens",
      "Summary token reserve must be below the debate token budget.",
    ]);
  if (policy.reserved_summary_seconds >= policy.max_time)
    errors.push([
      "debate-reserved_summary_seconds",
      "Summary time reserve must be below the debate time budget.",
    ]);
  return errors;
}
