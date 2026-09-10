import type { TicketPriorityConfig, TicketStatusConfig } from "@/lib/types";

export interface TicketConfigOption {
  value: string;
  label: string;
  sortOrder: number;
}

type ConfigEntry = Pick<TicketStatusConfig | TicketPriorityConfig, "name" | "label" | "sort_order">;

const FALLBACK_STATUSES: TicketConfigOption[] = [
  { value: "New", label: "New", sortOrder: 0 },
  { value: "Open", label: "Open", sortOrder: 1 },
  { value: "Awaiting Review", label: "Awaiting Review", sortOrder: 2 },
  { value: "Pending", label: "Pending", sortOrder: 3 },
  { value: "Escalated", label: "Escalated", sortOrder: 4 },
  { value: "Resolved", label: "Resolved", sortOrder: 5 },
  { value: "Closed", label: "Closed", sortOrder: 6 },
];

const FALLBACK_LIST_STATUSES: TicketConfigOption[] = [
  { value: "Open", label: "Open", sortOrder: 0 },
  { value: "Escalated", label: "Escalated", sortOrder: 1 },
  { value: "Awaiting Review", label: "Awaiting Review", sortOrder: 2 },
  { value: "Closed", label: "Closed", sortOrder: 3 },
];

const FALLBACK_PRIORITIES: TicketConfigOption[] = [
  { value: "P1", label: "P1", sortOrder: 0 },
  { value: "P2", label: "P2", sortOrder: 1 },
  { value: "P3", label: "P3", sortOrder: 2 },
  { value: "P4", label: "P4", sortOrder: 3 },
];

const FALLBACK_CREATION_PRIORITIES: TicketConfigOption[] = [
  { value: "P3", label: "P3 — Low", sortOrder: 0 },
  { value: "P2", label: "P2 — Medium", sortOrder: 1 },
  { value: "P1", label: "P1 — High", sortOrder: 2 },
];

function configuredOptions(config: readonly ConfigEntry[] | null | undefined): TicketConfigOption[] {
  if (!config?.length) return [];

  return config
    .map((entry, index) => {
      const value = typeof entry.name === "string" ? entry.name : "";
      const label = typeof entry.label === "string" ? entry.label.trim() : "";
      return {
        value,
        label: label || value,
        sortOrder: Number.isFinite(entry.sort_order) ? entry.sort_order : Number.MAX_SAFE_INTEGER,
        originalIndex: index,
      };
    })
    .filter((entry) => entry.value.trim().length > 0)
    .sort((left, right) => left.sortOrder - right.sortOrder || left.originalIndex - right.originalIndex)
    .filter((entry, index, entries) => entries.findIndex((candidate) => candidate.value === entry.value) === index)
    .map(({ value, label, sortOrder }) => ({ value, label, sortOrder }));
}

export function ticketStatusOptions(config: readonly TicketStatusConfig[] | null | undefined): TicketConfigOption[] {
  const options = configuredOptions(config);
  return options.length > 0 ? options : FALLBACK_STATUSES.map((option) => ({ ...option }));
}

export function ticketListStatusOptions(config: readonly TicketStatusConfig[] | null | undefined): TicketConfigOption[] {
  const options = configuredOptions(config);
  return options.length > 0 ? options : FALLBACK_LIST_STATUSES.map((option) => ({ ...option }));
}

export function ticketPriorityOptions(config: readonly TicketPriorityConfig[] | null | undefined): TicketConfigOption[] {
  const options = configuredOptions(config);
  return options.length > 0 ? options : FALLBACK_PRIORITIES.map((option) => ({ ...option }));
}

export function ticketCreationPriorityOptions(config: readonly TicketPriorityConfig[] | null | undefined): TicketConfigOption[] {
  const options = configuredOptions(config);
  return options.length > 0 ? options : FALLBACK_CREATION_PRIORITIES.map((option) => ({ ...option }));
}

export function preserveTicketConfigValue(
  options: readonly TicketConfigOption[],
  currentValue: string | null | undefined,
): TicketConfigOption[] {
  if (!currentValue || options.some((option) => option.value === currentValue)) return [...options];

  return [
    ...options,
    {
      value: currentValue,
      label: `${currentValue} (current value)`,
      sortOrder: Number.MAX_SAFE_INTEGER,
    },
  ];
}

export function defaultTicketPriority(options: readonly TicketConfigOption[]): string {
  return options.find((option) => option.value === "P3")?.value ?? options[0]?.value ?? "P3";
}

export function visibleTicketStatusOptions(
  options: readonly TicketConfigOption[],
  currentValue: string | null | undefined,
  limit = 4,
): TicketConfigOption[] {
  const visible = options.slice(0, Math.max(0, limit));
  if (!currentValue || visible.some((option) => option.value === currentValue)) return visible;

  const current = preserveTicketConfigValue(options, currentValue).find((option) => option.value === currentValue);
  return current ? [...visible, current] : visible;
}
