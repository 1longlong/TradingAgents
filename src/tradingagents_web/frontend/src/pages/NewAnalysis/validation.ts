export type WizardStep =
  | "ticker"
  | "date"
  | "language"
  | "analysts"
  | "depth"
  | "provider"
  | "models"
  | "portfolio"
  | "review";

export type ValidationResult = { ok: boolean; error?: string };

const TICKER_RE = /^[A-Za-z0-9._\-^=]+$/;

export function validateStep(
  step: WizardStep,
  values: Record<string, unknown>,
): ValidationResult {
  if (step === "ticker") {
    const ticker = String(values.ticker ?? "").trim();
    if (!ticker) return { ok: false, error: "Ticker is required." };
    if (ticker.length > 32 || !TICKER_RE.test(ticker)) {
      return { ok: false, error: "Ticker contains unsupported characters." };
    }
    return { ok: true };
  }

  if (step === "date") {
    const date = String(values.date ?? "").trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      return { ok: false, error: "Use YYYY-MM-DD." };
    }
    const parsed = new Date(`${date}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) {
      return { ok: false, error: "Invalid date." };
    }
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (parsed > today) return { ok: false, error: "Date cannot be in the future." };
    return { ok: true };
  }

  if (step === "analysts") {
    const analysts = Array.isArray(values.analysts) ? values.analysts : [];
    return analysts.length > 0
      ? { ok: true }
      : { ok: false, error: "Select at least one analyst." };
  }

  return { ok: true };
}
