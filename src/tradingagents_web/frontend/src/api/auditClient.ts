// REQ-WEB-008/009/010, NFR-CMP-001, ADR-002/003: real read-only audit/replay projections.
import { jsonRequest } from "./runClient";
export type AuditFamily =
  "evidence_manifest" | "gate_summary" | "debate_trace" | "run_summary";
export type JsonObject = Record<string, unknown>;
export type AuditView = {
  schema_version: string;
  artifact_id?: string;
  ticker?: string;
  trade_date?: string | null;
  source?: string;
  status?: string;
  rating?: string | null;
  available: boolean;
  artifact_availability: string;
  sanitized: boolean;
  consistency?: { status: string; issues: string[] };
  eligible_evidence_ids?: string[];
  artifacts: Array<{
    kind: AuditFamily;
    filename: string;
    status: string;
    available: boolean;
  }>;
  data: Partial<Record<AuditFamily, JsonObject | string>>;
};
export type ComparisonCatalog = {
  scope: string;
  representative_cases: number;
  regression_cases: number;
  rubric_dimensions: string[];
  cases: Array<{
    case_id: string;
    title: string;
    role: string;
    identity: Record<string, string>;
  }>;
};
export type ComparisonResult = {
  case_id: string;
  dynamic_case_id: string;
  title: string;
  role: string;
  scope: string;
  identity: Record<string, string>;
  policy: JsonObject;
  fixed: JsonObject;
  dynamic: JsonObject;
  report: JsonObject;
  rubric_dimensions: string[];
};
export const object = (value: unknown): JsonObject =>
  value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
export const records = (value: unknown): JsonObject[] =>
  Array.isArray(value)
    ? (value.filter(
        (item) =>
          item != null && typeof item === "object" && !Array.isArray(item),
      ) as JsonObject[])
    : [];
export const text = (value: unknown, missing = "Not recorded"): string =>
  value == null || value === ""
    ? missing
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
export const number = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
export function getAudit(artifactId: string) {
  return jsonRequest<AuditView>(
    `/api/history/${encodeURIComponent(artifactId)}/audit`,
  );
}
export function getRunAudit(runId: string) {
  return jsonRequest<AuditView>(`/api/runs/${encodeURIComponent(runId)}/audit`);
}
export function auditArtifactUrl(
  id: string,
  kind: AuditFamily,
  download = false,
) {
  return `/api/history/${encodeURIComponent(id)}/audit/artifacts/${kind}${download ? "?download=true" : ""}`;
}
export async function previewAudit(id: string, kind: AuditFamily) {
  const response = await fetch(auditArtifactUrl(id, kind));
  if (!response.ok)
    throw new Error(`Audit artifact unavailable (${response.status}).`);
  return response.text();
}
export function getComparisons() {
  return jsonRequest<ComparisonCatalog>("/api/comparisons");
}
export function getComparison(id: string, dynamicId: string) {
  return jsonRequest<ComparisonResult>(
    `/api/comparisons/${encodeURIComponent(id)}?dynamic_case_id=${encodeURIComponent(dynamicId)}`,
  );
}
export function comparisonDownload(id: string, dynamicId: string) {
  return `/api/comparisons/${encodeURIComponent(id)}/download?dynamic_case_id=${encodeURIComponent(dynamicId)}`;
}
