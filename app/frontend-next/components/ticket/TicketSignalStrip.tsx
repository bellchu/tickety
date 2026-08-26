import { Sparkles, Star } from "lucide-react";
import type { TicketSignalRating } from "@/lib/ticket-intelligence";
import { cn } from "@/lib/utils";

export function TicketSignalStrip({ ratings, reasoning }: { ratings: TicketSignalRating[]; reasoning?: string | null }) {
  return (
    <section className="mt-5 border-t border-linen-300 pt-5" aria-labelledby="content-intelligence-title">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-soft)] text-semantic-primary" aria-hidden="true">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <h2 id="content-intelligence-title" className="text-sm font-semibold text-ink-700">
            Content intelligence
          </h2>
        </div>
        <p className="max-w-2xl text-xs leading-5 text-ink-500">
          Assessed from the issue narrative and affected scope—not the requester&apos;s selected urgency. Advisory until reviewed.
        </p>
      </div>

      <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {ratings.map((rating) => (
          <div
            key={rating.key}
            role="group"
            aria-label={rating.accessibleLabel}
            className={cn(
              "relative min-w-0 overflow-hidden rounded-xl border p-3.5",
              rating.highlighted
                ? "border-clay-300 bg-[var(--color-primary-soft)]/55 shadow-[0_8px_24px_rgba(87,34,159,0.08)]"
                : "border-linen-300 bg-white",
            )}
          >
            {rating.highlighted && <span className="nexora-spectrum absolute inset-y-0 left-0 w-[3px]" aria-hidden="true" />}
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
              <h3 className="min-w-0 text-[10px] font-semibold uppercase leading-4 tracking-[0.1em] text-ink-500">
                {rating.label}
              </h3>
              <span className="max-w-full rounded-full border border-linen-300 bg-linen-100 px-2 py-0.5 text-[9px] font-semibold leading-4 text-ink-500 [overflow-wrap:anywhere]">
                {rating.sourceLabel}
              </span>
            </div>

            <SignalStars rating={rating} />

            <p className={cn("mt-2 break-words font-semibold leading-5 text-ink-700 [overflow-wrap:anywhere]", rating.highlighted ? "text-sm" : "text-xs")}>
              {rating.displayValue}
            </p>
            <p className="mt-1 break-words text-[10px] leading-4 text-ink-500 [overflow-wrap:anywhere]">
              {rating.detail}
            </p>
          </div>
        ))}
      </div>
      {reasoning && ratings[0]?.score !== null && (
        <details className="mt-3 rounded-xl border border-linen-300 bg-white/75 px-3.5 py-2.5">
          <summary className="cursor-pointer text-xs font-semibold text-ink-600">Why this content priority?</summary>
          <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-ink-500 [overflow-wrap:anywhere]">{reasoning}</p>
        </details>
      )}
    </section>
  );
}

function SignalStars({ rating }: { rating: TicketSignalRating }) {
  return (
    <div className="mt-2 flex items-center gap-0.5" aria-hidden="true" data-signal-visual="stars">
      {[1, 2, 3, 4, 5].map((position) => {
        const filled = rating.score !== null && position <= rating.score;
        return (
          <Star
            key={position}
            className={cn(
              rating.highlighted ? "h-[18px] w-[18px]" : "h-4 w-4",
              "shrink-0",
              filled ? "fill-current text-amber-500" : "text-ink-400/35",
            )}
            aria-hidden="true"
            focusable="false"
          />
        );
      })}
    </div>
  );
}
