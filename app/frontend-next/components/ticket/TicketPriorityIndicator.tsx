import { Sparkles, Star } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/ui";
import type { Ticket } from "@/lib/types";
import { ticketSignalRatings } from "@/lib/ticket-intelligence";
import { cn } from "@/lib/utils";

function priorityVariant(priority: string): BadgeVariant {
  switch (priority.trim().toUpperCase()) {
    case "P1": return "danger";
    case "P2": return "warning";
    case "P3": return "info";
    default: return "neutral";
  }
}

export function TicketPriorityIndicator({
  ticket,
  compact = false,
  className,
}: {
  ticket: Ticket;
  compact?: boolean;
  className?: string;
}) {
  const prioritySignal = ticketSignalRatings(ticket)[0];
  const assessedPriority = prioritySignal.score === null ? null : prioritySignal.visualValue;
  const reportedPriority = ticket.priority?.trim().toUpperCase() || "Unspecified";
  const differs = Boolean(assessedPriority && assessedPriority !== reportedPriority);

  return (
    <div className={cn("min-w-0 max-w-full", className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <Badge
          variant={priorityVariant(assessedPriority || reportedPriority)}
          icon={assessedPriority ? <Sparkles className="h-3 w-3" /> : undefined}
          title={assessedPriority ? prioritySignal.accessibleLabel : `Reported priority ${reportedPriority}; content analysis pending`}
          className={cn(assessedPriority && "ring-1 ring-current/10")}
        >
          {assessedPriority ? `${compact ? "AI" : "Content"} ${assessedPriority}` : `Reported ${reportedPriority}`}
        </Badge>
      </div>

      {assessedPriority && (
        <div className="mt-1.5 flex items-center gap-0.5" aria-label={`${prioritySignal.score} out of 5 attention stars`}>
          {[1, 2, 3, 4, 5].map((position) => (
            <Star
              key={position}
              className={cn(
                "h-2.5 w-2.5 shrink-0",
                prioritySignal.score !== null && position <= prioritySignal.score
                  ? cn("fill-current", prioritySignal.colorClass)
                  : "text-ink-400/35",
              )}
              aria-hidden="true"
            />
          ))}
        </div>
      )}

      {!compact && (
        <p className="mt-1 break-words text-[10px] leading-4 text-ink-400 [overflow-wrap:anywhere]">
          {assessedPriority
            ? differs
              ? `Reported ${reportedPriority}`
              : "Matches reported priority"
            : "Content analysis pending"}
        </p>
      )}
    </div>
  );
}
