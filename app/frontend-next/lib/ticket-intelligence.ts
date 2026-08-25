import type { Ticket, TicketAnalysisResult } from "@/lib/types";
import { parseApiDateTime } from "@/lib/date-time";

export type TicketSignalKey = "urgency" | "business-impact" | "requester-pressure" | "complexity" | "escalation-risk";
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
}

type TicketSignalSource = Pick<
  Ticket,
  "id" | "urgency" | "priority" | "sentiment" | "mood" | "complexity" | "escalation_risk" | "ai_status" | "ai_reasoning" | "ai_requested_artifacts"
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
}: Omit<TicketSignalRating, "unavailableReason"> & { score: TicketSignalScore }): TicketSignalRating {
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
  };
}

const URGENCY_LEVELS: Record<string, { score: TicketSignalScore; label: string }> = {
  critical: { score: 5, label: "Critical" },
  high: { score: 4, label: "High" },
  medium: { score: 3, label: "Medium" },
  low: { score: 2, label: "Low" },
};

const PRIORITY_URGENCY: Record<string, { score: TicketSignalScore; label: string }> = {
  p1: { score: 5, label: "Critical" },
  p2: { score: 4, label: "High" },
  p3: { score: 3, label: "Medium" },
  p4: { score: 2, label: "Low" },
};

function urgencySignal(ticket: Pick<Ticket, "urgency" | "priority">): TicketSignalRating {
  const declared = URGENCY_LEVELS[normalizeSignalValue(ticket.urgency)];
  if (declared) {
    return ratedSignal({
      key: "urgency",
      label: "Urgency",
      score: declared.score,
      displayValue: `${declared.label} - ${declared.score}/5 attention`,
      sourceLabel: "Declared",
      detail: "Declared urgency",
      accessibleLabel: `Urgency, ${declared.label}, ${declared.score} out of 5 attention, declared urgency`,
      colorClass: "text-rust-600",
    });
  }

  const normalizedPriority = normalizeSignalValue(ticket.priority);
  const fallback = PRIORITY_URGENCY[normalizedPriority];
  if (fallback) {
    const priority = originalSignalValue(ticket.priority).toUpperCase();
    return ratedSignal({
      key: "urgency",
      label: "Urgency",
      score: fallback.score,
      displayValue: `${fallback.label} - ${fallback.score}/5 attention`,
      sourceLabel: `From priority ${priority}`,
      detail: `Derived from current priority ${priority}`,
      accessibleLabel: `Urgency, ${fallback.label}, ${fallback.score} out of 5 attention, from priority ${priority}`,
      colorClass: "text-rust-600",
    });
  }

  return unavailableSignal(
    "urgency",
    "Urgency",
    "Declared",
    "text-rust-600",
    "Urgency and priority unavailable",
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

const REQUESTER_PRESSURE_LEVELS: Record<string, { score: TicketSignalScore; label: string }> = {
  critical: { score: 5, label: "Critical pressure" },
  urgent: { score: 4, label: "Urgent pressure" },
  concerned: { score: 3, label: "Concerned pressure" },
  neutral: { score: 2, label: "Neutral pressure" },
  satisfied: { score: 1, label: "Satisfied requester" },
};

function requesterPressureSignal(value: unknown, trusted: boolean, unavailableReason: string): TicketSignalRating {
  const pressure = trusted ? REQUESTER_PRESSURE_LEVELS[normalizeSignalValue(value)] : undefined;
  if (!pressure) {
    return unavailableSignal(
      "requester-pressure",
      "Requester pressure",
      "AI-assisted",
      "text-clay-600",
      unavailableReason,
    );
  }
  return ratedSignal({
    key: "requester-pressure",
    label: "Requester pressure",
    score: pressure.score,
    displayValue: `${pressure.label} - ${pressure.score}/5 pressure`,
    sourceLabel: "AI-assisted",
    detail: "Requester intensity, separate from business impact",
    accessibleLabel: `Requester pressure, ${pressure.label}, ${pressure.score} out of 5 pressure, AI-assisted`,
    colorClass: "text-clay-600",
  });
}

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
  });
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
    urgencySignal(ticket),
    businessImpactSignal(matchingFresh ? triage?.sentiment : ticket.sentiment, aiTrusted, unavailableReason),
    requesterPressureSignal(matchingFresh ? triage?.mood : ticket.mood, aiTrusted, unavailableReason),
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

export function routingLabel(ticket: Pick<Ticket, "recommended_team" | "recommended_team_basis">): string {
  if (ticket.recommended_team_basis === "not_applicable") return "No active route - ticket closed";
  if (ticket.recommended_team_basis === "source_group") {
    return "AI team analysis pending";
  }
  if (ticket.recommended_team_basis === "source_category") {
    return `Suggested team - ${ticket.recommended_team} (Freshservice category)`;
  }
  if (ticket.recommended_team_basis === "ai_team") {
    return `AI recommended team - ${ticket.recommended_team}`;
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
