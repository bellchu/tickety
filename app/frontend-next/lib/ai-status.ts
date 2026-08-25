import type { BadgeVariant } from "@/components/ui";
import type { AITaskLifecycle } from "@/lib/types";

export interface AITaskLifecycleMeta {
  label: string;
  description: string;
  variant: BadgeVariant;
}

const lifecycleMeta: Record<AITaskLifecycle, AITaskLifecycleMeta> = {
  not_analyzed: {
    label: "Not analyzed",
    description: "No AI task has been admitted for this ticket.",
    variant: "neutral",
  },
  queued: {
    label: "Queued",
    description: "Ready for the background worker to claim.",
    variant: "info",
  },
  retry_scheduled: {
    label: "Retry scheduled",
    description: "Waiting for the retry window after a recoverable failure.",
    variant: "warning",
  },
  running: {
    label: "Analyzing",
    description: "A worker holds an active analysis lease.",
    variant: "info",
  },
  lease_expired: {
    label: "Lease expired",
    description: "The prior worker stopped before releasing its claim; the task can be reclaimed.",
    variant: "danger",
  },
  completed: {
    label: "Completed",
    description: "The requested AI artifacts were generated successfully.",
    variant: "success",
  },
  partial: {
    label: "Partial results",
    description: "Some requested artifacts completed and at least one needs another attempt.",
    variant: "warning",
  },
  stale: {
    label: "Needs refresh",
    description: "Ticket input or pipeline provenance changed after the last analysis.",
    variant: "warning",
  },
  failed: {
    label: "Failed",
    description: "The analysis stopped and requires operator review.",
    variant: "danger",
  },
  dead_letter: {
    label: "Needs attention",
    description: "Automatic retries were exhausted.",
    variant: "danger",
  },
  paused: {
    label: "Paused",
    description: "Automatic AI was paused for this integration.",
    variant: "warning",
  },
  unknown: {
    label: "Unknown state",
    description: "The stored state is not recognized by this build.",
    variant: "neutral",
  },
};

export function aiTaskLifecycleMeta(lifecycle: AITaskLifecycle): AITaskLifecycleMeta {
  return lifecycleMeta[lifecycle];
}

export function aiArtifactLabel(artifact: string): string {
  const labels: Record<string, string> = {
    triage: "Triage",
    summary: "Summary",
    route: "Routing",
    resolution: "Resolution plan",
    refresh: "Search index refresh",
  };
  return labels[artifact] || artifact;
}

export function aiCallStatusMeta(status: string): Pick<AITaskLifecycleMeta, "label" | "variant"> {
  if (status === "success") return { label: "Success", variant: "success" };
  if (status === "capacity_deferred") return { label: "Capacity deferred", variant: "info" };
  if (status === "attempt_failed") return { label: "Attempt failed", variant: "warning" };
  if (status === "failed") return { label: "Failed", variant: "danger" };
  return { label: status.replaceAll("_", " ") || "Unknown", variant: "neutral" };
}

export function operationalCodeLabel(value: string | null): string {
  if (!value) return "None";
  return value
    .split(",")
    .map((part) => part.split(":").map((word) => word.replaceAll("_", " ")).join(": "))
    .join(" · ");
}
