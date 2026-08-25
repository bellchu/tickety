export interface AnalysisStepError {
  step: string;
  error: string;
}

const STEP_LABELS: Record<string, string> = {
  triage: "Triage",
  summary: "Summary",
  route: "Routing",
  resolution: "Resolution plan",
  refresh: "Intelligence refresh",
  ticket_intelligence: "Intelligence refresh",
  pipeline: "AI pipeline",
};

const ERROR_LABELS: Record<string, string> = {
  invalid_input: "ticket input was rejected by the safety limits",
  invalid_output: "the provider returned an invalid structured response",
  provider_unavailable: "the AI provider was unavailable",
  provider_rejected: "the AI provider rejected this request",
  provider_capacity: "provider capacity is temporarily constrained; retry is scheduled",
  timeout: "the step timed out",
  pipeline_timeout: "the pipeline timed out",
  analysis_rejected: "the provider response was rejected",
  internal_error: "an internal processing error occurred",
  analysis_step_failed: "generation failed before a safe cause was recorded",
  triage_failed: "triage failed before a safe cause was recorded",
  artifact_failed: "artifact generation failed before a safe cause was recorded",
  analysis_failed: "analysis failed before a safe cause was recorded",
  legacy_failure: "failed before a safe cause was recorded",
};

function normalize(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase().replace(/[\s-]+/g, "_") : "";
}

function describe(error: AnalysisStepError): string {
  const step = normalize(error.step);
  const code = normalize(error.error);
  return `${STEP_LABELS[step] || "AI step"}: ${ERROR_LABELS[code] || "processing failed"}`;
}

export function analysisErrorDetails(errors: readonly AnalysisStepError[]): string {
  const details = errors.map(describe);
  return [...new Set(details)].join("; ");
}

export function persistedAnalysisErrorDetails(value: string | null | undefined): string | null {
  if (!value?.trim()) return null;
  if (normalize(value) === "operator_retry_queue_cleared") return null;
  const parsed = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item): AnalysisStepError => {
      const separator = item.indexOf(":");
      if (separator > 0) {
        return { step: item.slice(0, separator), error: item.slice(separator + 1) };
      }
      const normalized = normalize(item);
      if (STEP_LABELS[normalized]) {
        return { step: normalized, error: "legacy_failure" };
      }
      return { step: "pipeline", error: normalized };
    });
  return analysisErrorDetails(parsed) || null;
}
