import { Star } from "lucide-react";
import type { TicketSignalRating } from "@/lib/ticket-intelligence";
import { cn } from "@/lib/utils";

export function TicketSignalStrip({ ratings }: { ratings: TicketSignalRating[] }) {
  return (
    <section className="mt-5 border-t border-linen-300 pt-4" aria-labelledby="operational-signals-title">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
        <h2 id="operational-signals-title" className="text-sm font-semibold text-ink-700">
          Operational signals
        </h2>
        <p className="max-w-2xl text-xs leading-5 text-ink-500">
          More filled stars mean more attention or effort. Colors identify signals; AI-assisted values are advisory.
        </p>
      </div>

      <div className="mt-3 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {ratings.map((rating) => (
          <div
            key={rating.key}
            role="group"
            aria-label={rating.accessibleLabel}
            className="min-w-0 rounded-xl border border-linen-300 bg-white p-3 last:sm:col-span-2 last:xl:col-span-1"
          >
            <div className="flex min-w-0 flex-col items-start gap-1.5">
              <h3 className="text-[11px] font-semibold uppercase leading-4 tracking-[0.08em] text-ink-500">
                {rating.label}
              </h3>
              <span className="shrink-0 rounded-full border border-linen-300 bg-linen-100 px-2 py-0.5 text-[9px] font-semibold text-ink-500">
                {rating.sourceLabel}
              </span>
            </div>

            <div className="mt-2 flex items-center gap-0.5" aria-hidden="true">
              {[1, 2, 3, 4, 5].map((position) => {
                const filled = rating.score !== null && position <= rating.score;
                return (
                  <Star
                    key={position}
                    className={cn(
                      "h-4 w-4 shrink-0",
                      filled ? cn("fill-current", rating.colorClass) : "text-ink-400",
                    )}
                    aria-hidden="true"
                    focusable="false"
                  />
                );
              })}
            </div>

            <p className="mt-2 break-words text-xs font-semibold leading-4 text-ink-700">
              {rating.displayValue}
            </p>
            <p className="mt-1 break-words text-[10px] leading-4 text-ink-500">
              {rating.detail}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
