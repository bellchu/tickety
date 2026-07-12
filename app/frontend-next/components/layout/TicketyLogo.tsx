import { cn } from "@/lib/utils";

const PRECISION_WINDOW_LEFT_PATH =
  "M12 8H26Q28 8 28 10V14Q28 16 26 16H18Q16 16 16 18V46Q16 48 18 48H26Q28 48 28 50V54Q28 56 26 56H12Q8 56 8 52V12Q8 8 12 8Z";
const PRECISION_WINDOW_RIGHT_PATH =
  "M52 8H38Q36 8 36 10V14Q36 16 38 16H46Q48 16 48 18V46Q48 48 46 48H38Q36 48 36 50V54Q36 56 38 56H52Q56 56 56 52V12Q56 8 52 8Z";

type MarkTone = "gradient" | "solid" | "dark" | "reversed";
type LogoSize = "sm" | "md" | "lg" | "xl";

// Keep the earlier tone names as compatibility aliases. The identity itself
// is deliberately monochrome; cobalt is reserved for product UI.
const markToneClasses: Record<MarkTone, string> = {
  gradient: "text-[#0A0B0D]",
  solid: "text-[#0A0B0D]",
  dark: "text-[#0A0B0D]",
  reversed: "text-white",
};

export function TicketyMark({
  className,
  tone = "dark",
}: {
  className?: string;
  tone?: MarkTone;
}) {
  return (
    <span
      className={cn(
        "inline-flex aspect-square shrink-0 items-center justify-center",
        markToneClasses[tone],
        className
      )}
    >
      <svg
        aria-hidden="true"
        className="h-full w-full"
        focusable="false"
        viewBox="0 0 64 64"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path d={PRECISION_WINDOW_LEFT_PATH} fill="currentColor" />
        <path d={PRECISION_WINDOW_RIGHT_PATH} fill="currentColor" />
      </svg>
    </span>
  );
}

const logoSizeClasses: Record<
  LogoSize,
  { mark: string; word: string; descriptor: string }
> = {
  sm: { mark: "h-6 w-6", word: "text-[17px]", descriptor: "text-[7px]" },
  md: { mark: "h-8 w-8", word: "text-[21px]", descriptor: "text-[8px]" },
  lg: { mark: "h-9 w-9", word: "text-2xl", descriptor: "text-[8px]" },
  xl: { mark: "h-10 w-10", word: "text-[27px]", descriptor: "text-[9px]" },
};

export function TicketyLogo({
  className,
  inverse = false,
  showDescriptor = false,
  size = "lg",
}: {
  className?: string;
  inverse?: boolean;
  showDescriptor?: boolean;
  size?: LogoSize;
}) {
  const sizing = logoSizeClasses[size];

  return (
    <span
      aria-label="Tickety"
      className={cn("inline-flex items-center gap-2", className)}
      role="img"
    >
      <TicketyMark className={sizing.mark} tone={inverse ? "reversed" : "dark"} />
      <span
        aria-hidden="true"
        className="flex min-w-0 flex-col justify-center gap-0.5 leading-none"
      >
        <span
          className={cn(
            "whitespace-nowrap font-medium tracking-[-0.025em]",
            sizing.word,
            inverse ? "text-white" : "text-[#0A0B0D]"
          )}
          style={{ fontFamily: '"Geist", Arial, sans-serif' }}
        >
          Tickety
        </span>
        {showDescriptor && (
          <span
            className={cn(
              "whitespace-nowrap font-medium tracking-normal",
              sizing.descriptor,
              inverse ? "text-white/60" : "text-[#0A0B0D]/55"
            )}
          >
            Service operations
          </span>
        )}
      </span>
    </span>
  );
}
