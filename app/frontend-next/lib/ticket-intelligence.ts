import type { Ticket, TicketAnalysisResult } from "@/lib/types";
import { parseApiDateTime } from "@/lib/date-time";

export type TicketSignalKey = "content-priority" | "business-impact" | "complexity" | "escalation-risk";
export type TicketSignalScore = 1 | 2 | 3 | 4 | 5;

export interface TicketSignalRating {
  key: TicketSignalKey;
  label: string;
  score: TicketSignalScore | null;
  displayValue: string;
  sourceLabel: string;
  detail: string;
  unavailableReason: string | null;
  accessibleLabel: string;
  colorClass: string;
  visualValue: string | null;
  highlighted: boolean;
}

export interface TicketSentimentPresentation {
  emoji: string;
  label: string;
  accessibleLabel: string;
}

type TicketSignalSource = Pick<
  Ticket,
  "id" | "priority" | "ai_suggested_priority" | "sentiment" | "mood" | "complexity" | "escalation_risk" | "ai_status" | "ai_reasoning" | "ai_requested_artifacts"
>;

const TRUSTED_TRIAGE_STATUSES = new Set(["completed", "triage-completed", "partial"]);

function normalizeSignalValue(value: unknown): string {
  if (typeof value !== "string") return "";
  return value.trim().toLowerCase().replace(/[\s_]+/g, "-").replace(/-+/g, "-");
}

function originalSignalValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function hasTrustedPersistedTicketAnalysis(
  ticket: Pick<Ticket, "ai_status" | "ai_reasoning"> & Partial<Pick<Ticket, "ai_requested_artifacts">>,
): boolean {
  if (typeof ticket.ai_reasoning !== "string" || ticket.ai_reasoning.trim().length === 0) {
    return false;
  }
  const status = normalizeSignalValue(ticket.ai_status);
  if (TRUSTED_TRIAGE_STATUSES.has(status)) return true;
  if (!["queued", "failed", "dead-letter"].includes(status)) return false;
  const requested = new Set(
    (ticket.ai_requested_artifacts || "")
      .split(",")
      .map(normalizeSignalValue)
      .filter(Boolean),
  );
  return requested.size > 0 && !requested.has("triage");
}

function unavailableSignal(
  key: TicketSignalKey,
  label: string,
  sourceLabel: string,
  colorClass: string,
  unavailableReason: string,
  highlighted = false,
): TicketSignalRating {
  return {
    key,
    label,
    score: null,
    displayValue: "Not rated",
    sourceLabel,
    detail: unavailableReason,
    unavailableReason,
    accessibleLabel: `${label}, Not rated, ${unavailableReason}`,
    colorClass,
    visualValue: null,
    highlighted,
  };
}

function ratedSignal({
  key,
  label,
  score,
  displayValue,
  sourceLabel,
  detail,
  accessibleLabel,
  colorClass,
  visualValue = null,
  highlighted = false,
}: Omit<TicketSignalRating, "unavailableReason" | "visualValue" | "highlighted"> & {
  score: TicketSignalScore;
  visualValue?: string | null;
  highlighted?: boolean;
}): TicketSignalRating {
  return {
    key,
    label,
    score,
    displayValue,
    sourceLabel,
    detail,
    unavailableReason: null,
    accessibleLabel,
    colorClass,
    visualValue,
    highlighted,
  };
}

const CONTENT_PRIORITY_LEVELS: Record<string, { score: TicketSignalScore; label: string }> = {
  p1: { score: 5, label: "Critical response" },
  p2: { score: 4, label: "High response" },
  p3: { score: 3, label: "Standard response" },
  p4: { score: 2, label: "Planned response" },
};

function contentPrioritySignal(
  reportedPriority: unknown,
  analyzedPriority: unknown,
  trusted: boolean,
  unavailableReason: string,
): TicketSignalRating {
  const reported = originalSignalValue(reportedPriority).toUpperCase();
  const normalizedAnalyzed = trusted ? normalizeSignalValue(analyzedPriority) : "";
  const assessed = CONTENT_PRIORITY_LEVELS[normalizedAnalyzed];
  if (assessed) {
    const priority = originalSignalValue(analyzedPriority).toUpperCase();
    const differs = Boolean(reported) && reported !== priority;
    const detail = differs
      ? `Content supports ${priority}; requester reported ${reported}`
      : reported
        ? `Content assessment aligns with reported ${reported}`
        : "Assessed from the ticket narrative and affected scope";
    return ratedSignal({
      key: "content-priority",
      label: "Content priority",
      score: assessed.score,
      displayValue: `${priority} · ${assessed.label}`,
      sourceLabel: "AI-assessed",
      detail,
      accessibleLabel: `Content priority ${priority}, ${assessed.label}, ${assessed.score} out of 5 attention. ${detail}`,
      colorClass: assessed.score >= 5 ? "text-rust-600" : assessed.score >= 4 ? "text-amber-600" : "text-clay-600",
      visualValue: priority,
      highlighted: true,
    });
  }

  const detail = reported
    ? `${unavailableReason}; reported priority is ${reported}`
    : unavailableReason;
  return unavailableSignal(
    "content-priority",
    "Content priority",
    "AI-assessed",
    "text-clay-600",
    detail,
    true,
  );
}

const BUSINESS_IMPACT_LEVELS: Record<string, { score: TicketSignalScore; label: string }> = {
  "business-critical": { score: 5, label: "Business critical" },
  "high-impact": { score: 4, label: "High impact" },
  moderate: { score: 3, label: "Moderate impact" },
  neutral: { score: 2, label: "Limited impact" },
  positive: { score: 1, label: "Positive impact" },
};

function businessImpactSignal(value: unknown, trusted: boolean, unavailableReason: string): TicketSignalRating {
  const sourceValue = originalSignalValue(value);
  const impact = trusted ? BUSINESS_IMPACT_LEVELS[normalizeSignalValue(value)] : undefined;
  if (!impact) {
    return unavailableSignal(
      "business-impact",
      "Business impact",
      "AI-assisted",
      "text-amber-600",
      unavailableReason,
    );
  }
  const detail = `Classification: ${sourceValue}`;
  return ratedSignal({
    key: "business-impact",
    label: "Business impact",
    score: impact.score,
    displayValue: `${impact.label} - ${impact.score}/5 impact`,
    sourceLabel: "AI-assisted",
    detail,
    accessibleLabel: `Business impact, ${impact.label}, ${impact.score} out of 5 impact, classification ${sourceValue}, AI-assisted`,
    colorClass: "text-amber-600",
  });
}

const CUSTOMER_SENTIMENT: Record<string, { emoji: string; label: string }> = {
  critical: { emoji: "😡", label: "Critical" },
  urgent: { emoji: "😣", label: "Urgent" },
  concerned: { emoji: "😟", label: "Concerned" },
  neutral: { emoji: "😐", label: "Neutral" },
  satisfied: { emoji: "😊", label: "Satisfied" },
};

const COMPLEXITY_LABELS: Record<TicketSignalScore, string> = {
  1: "Straightforward",
  2: "Low effort",
  3: "Moderate effort",
  4: "High effort",
  5: "Very high effort",
};

function complexitySignal(value: unknown, trusted: boolean, unavailableReason: string): TicketSignalRating {
  if (!trusted || typeof value !== "number" || !Number.isFinite(value) || value < 1 || value > 5) {
    return unavailableSignal(
      "complexity",
      "Complexity",
      "AI-assisted",
      "text-semantic-info",
      unavailableReason,
    );
  }
  const score = Math.round(value) as TicketSignalScore;
  const label = COMPLEXITY_LABELS[score];
  return ratedSignal({
    key: "complexity",
    label: "Complexity",
    score,
    displayValue: `${label} - ${score}/5 effort`,
    sourceLabel: "AI-assisted",
    detail: "Estimated handling effort",
    accessibleLabel: `Complexity, ${label}, ${score} out of 5 effort, AI-assisted`,
    colorClass: "text-semantic-info",
  });
}

function formatRisk(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}

function escalationRiskSignal(value: unknown, trusted: boolean, unavailableReason: string): TicketSignalRating {
  if (!trusted || typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 100) {
    return unavailableSignal(
      "escalation-risk",
      "Escalation risk",
      "AI-assisted",
      "text-[var(--brand-pink)]",
      unavailableReason,
    );
  }
  const score: TicketSignalScore = value <= 20 ? 1 : value <= 40 ? 2 : value <= 60 ? 3 : value <= 80 ? 4 : 5;
  const percent = formatRisk(value);
  return ratedSignal({
    key: "escalation-risk",
    label: "Escalation risk",
    score,
    displayValue: `${percent}% risk - ${score}/5 attention`,
    sourceLabel: "AI-assisted",
    detail: "Derived escalation outcome",
    accessibleLabel: `Escalation risk, ${percent} percent, ${score} out of 5 attention, AI-assisted`,
    colorClass: "text-[var(--brand-pink)]",
    visualValue: percent,
  });
}

export function ticketSentimentPresentation(
  ticket: TicketSignalSource,
  latestAnalysis: TicketAnalysisResult | null = null,
): TicketSentimentPresentation | null {
  const matchingFresh = latestAnalysis?.ticket_id === ticket.id ? latestAnalysis : null;
  const freshReasoning = matchingFresh?.triage?.reasoning;
  const trusted = matchingFresh
    ? typeof freshReasoning === "string" && freshReasoning.trim().length > 0
    : hasTrustedPersistedTicketAnalysis(ticket);
  if (!trusted) return null;

  const mood = matchingFresh ? matchingFresh.triage?.mood : ticket.mood;
  const sentiment = CUSTOMER_SENTIMENT[normalizeSignalValue(mood)];
  if (!sentiment) return null;
  return {
    ...sentiment,
    accessibleLabel: `Customer sentiment: ${sentiment.label}`,
  };
}

export function ticketSignalRatings(
  ticket: TicketSignalSource,
  latestAnalysis: TicketAnalysisResult | null = null,
): TicketSignalRating[] {
  const matchingFresh = latestAnalysis?.ticket_id === ticket.id ? latestAnalysis : null;
  const freshReasoning = matchingFresh?.triage?.reasoning;
  const freshTrusted = Boolean(
    matchingFresh
    && typeof freshReasoning === "string"
    && freshReasoning.trim().length > 0,
  );
  const persistedTrusted = hasTrustedPersistedTicketAnalysis(ticket);
  const aiTrusted = matchingFresh ? freshTrusted : persistedTrusted;
  const triage = matchingFresh?.triage;
  const unavailableReason = aiTrusted
    ? "Analysis value unavailable"
    : matchingFresh
      ? "Analysis value unavailable"
      : "Awaiting a completed AI analysis";

  return [
    contentPrioritySignal(
      ticket.priority,
      matchingFresh ? triage?.priority : ticket.ai_suggested_priority,
      aiTrusted,
      unavailableReason,
    ),
    businessImpactSignal(matchingFresh ? triage?.sentiment : ticket.sentiment, aiTrusted, unavailableReason),
    complexitySignal(matchingFresh ? triage?.complexity : ticket.complexity, aiTrusted, unavailableReason),
    escalationRiskSignal(matchingFresh ? triage?.escalation_risk : ticket.escalation_risk, aiTrusted, unavailableReason),
  ];
}

export type AnalysisLifecycleLabel =
  | "Not analyzed"
  | "Queued"
  | "Analyzing"
  | "Ready"
  | "Partial results"
  | "Needs refresh"
  | "Retry scheduled"
  | "Analysis failed"
  | "Needs attention";

export function analysisLifecycleLabel(
  ticket: Pick<Ticket, "ai_status" | "ai_lease_expires_at" | "ai_next_attempt_at" | "ai_generated_at" | "ai_reasoning" | "summary">,
  now = Date.now(),
): AnalysisLifecycleLabel {
  const status = (ticket.ai_status || "").toLowerCase();
  if (status === "dead_letter") return "Needs attention";
  if (status === "failed") return "Analysis failed";
  if (["stale", "legacy_stale", "provenance_unknown"].includes(status)) return "Needs refresh";
  if (status === "partial") return "Partial results";
  if (["completed", "triage_completed"].includes(status)) return "Ready";
  if (status === "running") {
    const leaseExpires = parseApiDateTime(ticket.ai_lease_expires_at)?.getTime() ?? 0;
    return leaseExpires > now ? "Analyzing" : "Needs refresh";
  }
  if (status === "queued") {
    const nextAttempt = parseApiDateTime(ticket.ai_next_attempt_at)?.getTime() ?? 0;
    return nextAttempt > now ? "Retry scheduled" : "Queued";
  }
  if (ticket.ai_generated_at || ticket.ai_reasoning || ticket.summary) return "Needs refresh";
  return "Not analyzed";
}

export function sourceKindLabel(ticket: Pick<Ticket, "external_source" | "ticket_type">): string {
  const kind = (ticket.ticket_type || "incident").replaceAll("_", " ");
  const formattedKind = kind.replace(/\b\w/g, (letter) => letter.toUpperCase());
  return ticket.external_source
    ? `${ticket.external_source.replace(/\b\w/g, (letter) => letter.toUpperCase())} ${formattedKind}`
    : formattedKind;
}

export function routingLabel(ticket: Pick<Ticket, "recommended_team" | "recommended_team_basis" | "routing_catalog_validated">): string {
  if (ticket.recommended_team_basis === "not_applicable") return "No active route - ticket closed";
  if (ticket.recommended_team_basis === "source_group") {
    return "AI team analysis pending";
  }
  if (ticket.recommended_team_basis === "source_category") {
    return `Suggested team - ${ticket.recommended_team} (Freshservice category)`;
  }
  if (ticket.recommended_team_basis === "ai_team") {
    return ticket.routing_catalog_validated
      ? `AI resolver recommendation - ${ticket.recommended_team}`
      : `AI resolver recommendation - ${ticket.recommended_team} (advisory; catalog mapping pending)`;
  }
  if (ticket.recommended_team_basis === "ai_category") {
    return `Suggested team - ${ticket.recommended_team} (catalog validation pending)`;
  }
  return "Unrouted - review required";
}

export function relatedStrength(score: number, method: string): "Strong match" | "Related" | "Possible" | "Keyword" {
  if (method === "keyword") return "Keyword";
  if (score >= 0.75) return "Strong match";
  if (score >= 0.5) return "Related";
  return "Possible";
}
