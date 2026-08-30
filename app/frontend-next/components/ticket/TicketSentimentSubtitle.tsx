import type { TicketAnalysisResult, Ticket } from "@/lib/types";
import { ticketSentimentPresentation } from "@/lib/ticket-intelligence";
import { cn } from "@/lib/utils";

export function TicketSentimentSubtitle({
  ticket,
  latestAnalysis = null,
  className,
}: {
  ticket: Ticket;
  latestAnalysis?: TicketAnalysisResult | null;
  className?: string;
}) {
  const sentiment = ticketSentimentPresentation(ticket, latestAnalysis);
  if (!sentiment) return null;

  return (
    <p className={cn("mt-1 flex min-w-0 items-center gap-1.5 break-words text-xs leading-5 text-ink-500 [overflow-wrap:anywhere]", className)}>
      <span className="shrink-0 text-base leading-none" aria-hidden="true">{sentiment.emoji}</span>
      <span>{`Sentiment · ${sentiment.label}`}</span>
    </p>
  );
}
