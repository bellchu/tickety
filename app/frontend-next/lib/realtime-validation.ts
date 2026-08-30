import type {
  PointsNotification,
  Recognition,
  RecommendedSolution,
  ResolverGroup,
  ResolutionPlan,
  RouteRecommendation,
  TicketAnalysisResult,
  TriageResult,
  TriageStep,
} from "./types";

const MIN_PIPELINE_TIMEOUT_SECONDS = 120;
const MAX_PIPELINE_TIMEOUT_SECONDS = 3600;
const DEFAULT_PIPELINE_TIMEOUT_SECONDS = 900;
const WATCHDOG_MARGIN_SECONDS = 30;

type UnknownRecord = Record<string, unknown>;

const RESOLVER_GROUPS = new Set<ResolverGroup>([
  "SERVICE_DESK",
  "ENDPOINT_SUPPORT",
  "IDENTITY_ACCESS",
  "NETWORK_OPERATIONS",
  "INFRASTRUCTURE_OPERATIONS",
  "CLOUD_PLATFORM",
  "SECURITY_OPERATIONS",
  "BUSINESS_APPLICATIONS",
  "APPLICATION_OPERATIONS",
  "DATA_SERVICES",
  "INTEGRATION_SERVICES",
  "AUTOMATION_SERVICES",
  "SOFTWARE_ENGINEERING",
  "SERVICE_DELIVERY",
]);
const ROUTE_LINE_BREAKS = [
  "\n", "\r", "\v", "\f", "\u001c", "\u001d", "\u001e", "\u0085", "\u2028", "\u2029",
];

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isTriageStep(value: unknown): value is TriageStep {
  if (!isRecord(value)) return false;
  return typeof value.step === "string"
    && typeof value.label === "string"
    && (value.status === "pending" || value.status === "active" || value.status === "done" || value.status === "error");
}

function isTriageResult(value: unknown): value is TriageResult {
  if (!isRecord(value)) return false;
  return typeof value.ticket_id === "string"
    && typeof value.sentiment === "string"
    && typeof value.category === "string"
    && typeof value.priority === "string"
    && typeof value.mood === "string"
    && isFiniteNumber(value.complexity)
    && typeof value.action === "string"
    && typeof value.recommended_team === "string"
    && typeof value.reasoning === "string"
    && isNullableString(value.suggested_response)
    && isFiniteNumber(value.escalation_risk);
}

function isResolverGroup(value: unknown): value is ResolverGroup {
  return typeof value === "string" && RESOLVER_GROUPS.has(value as ResolverGroup);
}

function isRoutingText(value: unknown, maxLength: number): value is string {
  return typeof value === "string"
    && value.trim().length > 0
    && value === value.trim()
    && value.length <= maxLength
    && !ROUTE_LINE_BREAKS.some((separator) => value.includes(separator));
}

export function isRouteRecommendation(value: unknown): value is RouteRecommendation {
  if (!isRecord(value)) return false;
  const exactKeys = [
    "primary_group", "secondary_group", "confidence",
    "scope", "affected_service", "failure_domain", "reason",
  ];
  const keys = Object.keys(value);
  const unknownEvidence = (
    typeof value.affected_service === "string"
    && value.affected_service.toLocaleLowerCase("en-US") === "unknown"
  ) || (
    typeof value.failure_domain === "string"
    && value.failure_domain.toLocaleLowerCase("en-US") === "unknown"
  );
  return keys.length === exactKeys.length
    && exactKeys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
    && isResolverGroup(value.primary_group)
    && (value.secondary_group === null || isResolverGroup(value.secondary_group))
    && value.secondary_group !== value.primary_group
    && value.secondary_group !== "SERVICE_DESK"
    && isFiniteNumber(value.confidence)
    && value.confidence >= 0
    && value.confidence <= 1
    && (!unknownEvidence || value.confidence < 0.60)
    && (value.scope === "single_user" || value.scope === "multiple_users" || value.scope === "service_wide" || value.scope === "unknown")
    && isRoutingText(value.affected_service, 255)
    && isRoutingText(value.failure_domain, 255)
    && isRoutingText(value.reason, 1_000);
}

function isResolutionPlan(value: unknown): value is ResolutionPlan {
  if (!isRecord(value)) return false;
  return typeof value.root_cause_hypothesis === "string"
    && Array.isArray(value.resolution_steps)
    && value.resolution_steps.every((step) => typeof step === "string")
    && (value.confidence === "high" || value.confidence === "medium" || value.confidence === "low")
    && (value.estimated_effort === "high" || value.estimated_effort === "medium" || value.estimated_effort === "low")
    && typeof value.escalation_advice === "string"
    && typeof value.preventive_note === "string";
}

function isRecommendedSolution(value: unknown): value is RecommendedSolution {
  if (!isRecord(value)) return false;
  return typeof value.ticket_id === "string"
    && isResolutionPlan(value.plan)
    && typeof value.cached === "boolean";
}

function isAnalysisError(value: unknown): value is { step: string; error: string } {
  return isRecord(value) && typeof value.step === "string" && typeof value.error === "string";
}

export function isTicketAnalysisResult(value: unknown, ticketId: string): value is TicketAnalysisResult {
  if (!isRecord(value) || value.ticket_id !== ticketId) return false;
  return isTriageResult(value.triage)
    && value.triage.ticket_id === ticketId
    && (value.summary === null || typeof value.summary === "string")
    && (value.route === null || isRouteRecommendation(value.route))
    && (value.recommended_solution === null || (
      isRecommendedSolution(value.recommended_solution)
      && value.recommended_solution.ticket_id === ticketId
    ))
    && isFiniteNumber(value.documents_changed)
    && Array.isArray(value.errors)
    && value.errors.every(isAnalysisError)
    && typeof value.cached === "boolean";
}

export interface TriageProgressMessage {
  type: "progress";
  steps: TriageStep[];
  timeout_seconds: number;
}

export function isTriageProgressMessage(value: unknown): value is TriageProgressMessage {
  return isRecord(value)
    && value.type === "progress"
    && Array.isArray(value.steps)
    && value.steps.every(isTriageStep)
    && isFiniteNumber(value.timeout_seconds);
}

function isRecognition(value: unknown): value is Recognition {
  if (!isRecord(value)) return false;
  return isInteger(value.id)
    && typeof value.user_id === "string"
    && typeof value.recognition_key === "string"
    && typeof value.unlocked_at === "string"
    && isNullableString(value.ticket_id)
    && isNullableString(value.display_name)
    && isNullableString(value.description)
    && isNullableString(value.icon);
}

export function isPointsNotification(value: unknown): value is PointsNotification {
  if (!isRecord(value)) return false;
  return typeof value.ticket_id === "string"
    && typeof value.ticket_subject === "string"
    && typeof value.user_id === "string"
    && typeof value.user_name === "string"
    && isFiniteNumber(value.points_earned)
    && isFiniteNumber(value.new_total)
    && isFiniteNumber(value.new_tier)
    && typeof value.tier_promoted === "boolean"
    && isFiniteNumber(value.new_momentum)
    && Array.isArray(value.recognitions_unlocked)
    && value.recognitions_unlocked.every(isRecognition);
}

export function triageWatchdogDelayMs(timeoutSeconds: unknown): number {
  const seconds = isFiniteNumber(timeoutSeconds)
    ? Math.min(MAX_PIPELINE_TIMEOUT_SECONDS, Math.max(MIN_PIPELINE_TIMEOUT_SECONDS, timeoutSeconds))
    : DEFAULT_PIPELINE_TIMEOUT_SECONDS;
  return (seconds + WATCHDOG_MARGIN_SECONDS) * 1000;
}
