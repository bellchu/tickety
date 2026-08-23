import type { Ticket } from "@/lib/types";

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
    const leaseExpires = ticket.ai_lease_expires_at ? Date.parse(ticket.ai_lease_expires_at) : 0;
    return leaseExpires > now ? "Analyzing" : "Needs refresh";
  }
  if (status === "queued") {
    const nextAttempt = ticket.ai_next_attempt_at ? Date.parse(ticket.ai_next_attempt_at) : 0;
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
  return ticket.recommended_team_basis === "ai_category"
    ? `Recommended team - ${ticket.recommended_team}`
    : "Default route - Service Desk";
}

export function relatedStrength(score: number, method: string): "Strong match" | "Related" | "Possible" | "Keyword" {
  if (method === "keyword") return "Keyword";
  if (score >= 0.75) return "Strong match";
  if (score >= 0.5) return "Related";
  return "Possible";
}
