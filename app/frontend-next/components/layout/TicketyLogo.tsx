import Image from "next/image";
import { cn } from "@/lib/utils";

type LogoSize = "sm" | "md" | "lg" | "xl";

const logoSizeClasses: Record<LogoSize, { logo: string; descriptor: string }> = {
  sm: { logo: "h-4 w-auto", descriptor: "text-[7px]" },
  md: { logo: "h-5 w-auto", descriptor: "text-[8px]" },
  lg: { logo: "h-6 w-auto", descriptor: "text-[8px]" },
  xl: { logo: "h-7 w-auto", descriptor: "text-[9px]" },
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
      aria-label="Nexora"
      className={cn("inline-flex min-w-0 flex-col justify-center gap-1", className)}
      role="img"
    >
      <Image
        alt=""
        aria-hidden="true"
        className={cn("block shrink-0", sizing.logo)}
        height="20"
        src={inverse ? "/brand/nexora-logo-reversed.svg" : "/brand/nexora-logo.svg"}
        width="105"
      />
      {showDescriptor && (
        <span
          aria-hidden="true"
          className={cn(
            "whitespace-nowrap font-mono font-medium uppercase tracking-[0.14em]",
            sizing.descriptor,
            inverse ? "text-white/60" : "text-[#59616B]"
          )}
        >
          Service operations
        </span>
      )}
    </span>
  );
}
