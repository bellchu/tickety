/** Browser-only, user-scoped durable outbox cursor for notification replay. */
const CURSOR_PREFIX = "tickety.notifications.cursor.";
export const MAX_NOTIFICATION_CURSOR = Number.MAX_SAFE_INTEGER;

function storageKey(userId: string) {
  return `${CURSOR_PREFIX}${userId}`;
}

export function parseNotificationCursor(value: unknown): number {
  if (typeof value !== "string" || !/^(?:0|[1-9][0-9]{0,15})$/.test(value)) return 0;
  const cursor = Number(value);
  return Number.isSafeInteger(cursor) && cursor >= 0 && cursor <= MAX_NOTIFICATION_CURSOR ? cursor : 0;
}

export function readNotificationCursor(userId: string | null | undefined): number {
  if (!userId || typeof window === "undefined") return 0;
  try {
    return parseNotificationCursor(window.localStorage.getItem(storageKey(userId)));
  } catch {
    return 0;
  }
}

export function rememberNotificationCursor(userId: string, eventId: number | undefined): void {
  if (typeof window === "undefined" || typeof eventId !== "number" || !Number.isSafeInteger(eventId) || eventId < 1 || eventId > MAX_NOTIFICATION_CURSOR) return;
  try {
    const previous = readNotificationCursor(userId);
    if (eventId > previous) window.localStorage.setItem(storageKey(userId), String(eventId));
  } catch {
    // Storage is an optimization only; replay remains safe and idempotent.
  }
}

export function clearNotificationCursor(userId: string | null | undefined): void {
  if (!userId || typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(storageKey(userId));
  } catch {
    // Private-mode storage failures must not break logout.
  }
}
