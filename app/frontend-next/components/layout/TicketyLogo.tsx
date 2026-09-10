import { cn } from "@/lib/utils";
import { PRODUCT_LOCKUP_NAME, PRODUCT_NAME } from "@/lib/brand";

type MarkTone = "gradient" | "solid" | "dark" | "reversed";
type LogoSize = "sm" | "md" | "lg" | "xl";
type LogoLayout = "inline" | "stacked";

/** Compact product mark used where the full Tickety wordmark cannot fit. */
export function TicketyMark({
  className,
  tone = "gradient",
}: {
  className?: string;
  tone?: MarkTone;
}) {
  const monochrome = tone === "solid" || tone === "dark" || tone === "reversed";

  return (
    <span
      className={cn(
        "inline-grid aspect-square shrink-0 place-items-center overflow-hidden rounded-[22%]",
        monochrome ? (tone === "reversed" ? "bg-white text-ink-700" : "bg-ink-700 text-white") : "tickety-accent text-white",
        className
      )}
      aria-hidden="true"
    >
      <svg className="h-[62%] w-[62%]" viewBox="0 0 24 24" fill="none">
        <path
          d="M6 5h12v4a3 3 0 0 0 0 6v4H6v-4a3 3 0 0 0 0-6V5Z"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <path d="M10 9h4M10 13h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </span>
  );
}

const logoSizes: Record<
  LogoSize,
  { mark: string; product: string; descriptor: string; gap: string }
> = {
  sm: { mark: "h-5 w-5", product: "text-[8px]", descriptor: "text-[6px]", gap: "gap-2" },
  md: { mark: "h-6 w-6", product: "text-[9px]", descriptor: "text-[7px]", gap: "gap-2.5" },
  lg: { mark: "h-7 w-7", product: "text-[10px]", descriptor: "text-[7px]", gap: "gap-3" },
  xl: { mark: "h-8 w-8", product: "text-[11px]", descriptor: "text-[8px]", gap: "gap-3" },
};

/** Tickety product identity. */
export function TicketyLogo({
  className,
  inverse = false,
  layout = "inline",
  showDescriptor = false,
  size = "lg",
}: {
  className?: string;
  inverse?: boolean;
  layout?: LogoLayout;
  showDescriptor?: boolean;
  size?: LogoSize;
}) {
  const sizing = logoSizes[size];
  const stacked = layout === "stacked";

  return (
    <span
      aria-label={PRODUCT_LOCKUP_NAME}
      className={cn(
        "inline-flex",
        stacked ? "flex-col items-start gap-1.5" : cn("items-center", sizing.gap),
        inverse && "rounded-md bg-white px-2.5 py-2 shadow-sm",
        className
      )}
      role="img"
    >
      <TicketyMark className={sizing.mark} />
      <span
        aria-hidden="true"
        className={cn(
          "shrink-0 bg-ink-700/20",
          stacked ? "h-px w-full" : "h-6 w-px"
        )}
      />
      <span aria-hidden="true" className="flex min-w-0 flex-col justify-center leading-none">
        <span className={cn("whitespace-nowrap font-mono font-medium uppercase tracking-[0.18em] text-ink-700", sizing.product)}>
          {PRODUCT_NAME}
        </span>
        {showDescriptor && (
          <span className={cn("mt-1 whitespace-nowrap font-mono uppercase tracking-[0.08em] text-ink-400", sizing.descriptor)}>
            Service ops
          </span>
        )}
      </span>
    </span>
  );
}
