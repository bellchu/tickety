export interface DeterministicQueueTicket {
  readonly id: string;
  readonly status: string;
  readonly priority: string;
  readonly created_at: string | null;
}

const INACTIVE_STATUSES = new Set([
  "canceled",
  "cancelled",
  "closed",
  "completed",
  "resolved",
]);

const PRIORITY_ORDER = {
  P1: 0,
  P2: 1,
  P3: 2,
  P4: 3,
} as const;

type CanonicalPriority = keyof typeof PRIORITY_ORDER;

function canonicalPriority(value: string): CanonicalPriority | null {
  const normalized = value.trim().toUpperCase();
  return normalized in PRIORITY_ORDER
    ? (normalized as CanonicalPriority)
    : null;
}

function timestamp(value: string | null): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  const isNaiveIsoDateTime = /^\d{4}-\d{2}-\d{2}T/.test(trimmed)
    && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  // The backend stores UTC datetimes without an offset. Interpret those values
  // as UTC rather than silently shifting ticket age to the browser timezone.
  const parsed = Date.parse(isNaiveIsoDateTime ? `${trimmed}Z` : trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function nowTimestamp(now: Date | number): number | null {
  const value = now instanceof Date ? now.getTime() : now;
  return Number.isFinite(value) ? value : null;
}

export function isActiveTicket(
  ticket: Pick<DeterministicQueueTicket, "status">,
): boolean {
  return !INACTIVE_STATUSES.has(ticket.status.trim().toLowerCase());
}

export function selectDeterministicQueue<T extends DeterministicQueueTicket>(
  tickets: readonly T[],
  limit = 6,
): T[] {
  const safeLimit = Number.isFinite(limit)
    ? Math.max(0, Math.trunc(limit))
    : 0;

  return tickets
    .filter(isActiveTicket)
    .slice()
    .sort((left, right) => {
      const leftPriority = canonicalPriority(left.priority);
      const rightPriority = canonicalPriority(right.priority);
      const priorityDifference =
        (leftPriority === null ? 4 : PRIORITY_ORDER[leftPriority]) -
        (rightPriority === null ? 4 : PRIORITY_ORDER[rightPriority]);
      if (priorityDifference !== 0) return priorityDifference;

      const leftCreatedAt = timestamp(left.created_at);
      const rightCreatedAt = timestamp(right.created_at);
      if (leftCreatedAt === null && rightCreatedAt !== null) return 1;
      if (leftCreatedAt !== null && rightCreatedAt === null) return -1;
      if (
        leftCreatedAt !== null &&
        rightCreatedAt !== null &&
        leftCreatedAt !== rightCreatedAt
      ) {
        return leftCreatedAt - rightCreatedAt;
      }

      if (left.id < right.id) return -1;
      if (left.id > right.id) return 1;
      return 0;
    })
    .slice(0, safeLimit);
}

export function formatQueueAge(
  createdAt: string | null,
  now: Date | number = Date.now(),
): string {
  const createdAtTimestamp = timestamp(createdAt);
  const currentTimestamp = nowTimestamp(now);
  if (createdAtTimestamp === null || currentTimestamp === null) {
    return "age unavailable";
  }

  const hours = Math.max(0, currentTimestamp - createdAtTimestamp) / 3_600_000;
  if (hours < 1) return "<1h";
  if (hours < 24) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

export function deterministicQueueReason(
  ticket: Pick<DeterministicQueueTicket, "priority" | "created_at">,
  now: Date | number = Date.now(),
): string {
  const priority = canonicalPriority(ticket.priority);
  const priorityLabel = priority ? `${priority} priority` : "Unranked priority";
  const age = formatQueueAge(ticket.created_at, now);
  return age === "age unavailable"
    ? `${priorityLabel} · age unavailable`
    : `${priorityLabel} · ${age} old`;
}
