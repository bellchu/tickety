export type DateTimeValue = string | Date | null | undefined;

const NAIVE_ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;
const ISO_TIME_ZONE = /(?:z|[+-]\d{2}(?::?\d{2})?)$/i;

/**
 * Parse an instant returned by the Tickety OPS Tower API.
 *
 * Database datetimes are stored as UTC without an offset, so a naive ISO
 * datetime from the API must be made explicit before it reaches Date. Values
 * that already carry an offset retain it. Pure calendar dates are intentionally
 * outside this helper because applying a timezone to them can change the day.
 */
export function parseApiDateTime(value: DateTimeValue): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : new Date(value.getTime());
  }
  if (!value) return null;

  const trimmed = value.trim();
  if (!trimmed) return null;
  const normalized = NAIVE_ISO_DATE_TIME.test(trimmed) && !ISO_TIME_ZONE.test(trimmed)
    ? `${trimmed}Z`
    : trimmed;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatLocalDateTime(
  value: DateTimeValue,
  options: Intl.DateTimeFormatOptions = {
    dateStyle: "medium",
    timeStyle: "short",
  },
  fallback = "Date unavailable",
): string {
  const date = parseApiDateTime(value);
  if (!date) return fallback;
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

export function toLocalDateTimeInput(value: DateTimeValue): string {
  const date = parseApiDateTime(value);
  if (!date) return "";
  const localClock = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localClock.toISOString().slice(0, 16);
}

export function localDateKey(value: Date = new Date()): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function resolvedLocalTimeZone(): string {
  return new Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}
