import type { Ticket } from "./types";
import { formatLocalDateTime } from "./date-time";

type RequesterTicket = Pick<
  Ticket,
  "reporter" | "requester_name" | "requester_email"
>;

type TimelineTicket = Pick<
  Ticket,
  | "created_at"
  | "external_created_at"
  | "external_conversation_updated_at"
  | "last_communication_at"
>;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function requesterEmail(ticket: RequesterTicket): string | null {
  const enriched = ticket.requester_email?.trim();
  if (enriched && EMAIL_PATTERN.test(enriched)) return enriched;
  const legacy = ticket.reporter?.trim();
  return legacy && EMAIL_PATTERN.test(legacy) ? legacy : null;
}

export function requesterName(ticket: RequesterTicket): string {
  const enriched = ticket.requester_name?.trim();
  if (enriched && !/^\d+$/.test(enriched)) return enriched;
  const email = requesterEmail(ticket);
  const legacy = ticket.reporter?.trim();
  if (legacy && legacy !== email && !/^\d+$/.test(legacy)) return legacy;
  return email || "Requester profile pending";
}

export function ticketCreatedAt(ticket: TimelineTicket): string | null {
  return ticket.external_created_at || ticket.created_at;
}

export function ticketLastCommunicationAt(ticket: TimelineTicket): string | null {
  return (
    ticket.last_communication_at
    || ticket.external_conversation_updated_at
    || ticket.external_created_at
    || ticket.created_at
  );
}

export function formatOperationalTimestamp(value: string | null | undefined): string {
  return formatLocalDateTime(value, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

export function safeMailto(value: string | null | undefined): string | null {
  const email = value?.trim();
  return email && EMAIL_PATTERN.test(email) ? `mailto:${email}` : null;
}
