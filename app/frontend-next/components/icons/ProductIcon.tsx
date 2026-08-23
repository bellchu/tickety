import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface ProductIconProps {
  icon: LucideIcon;
  active?: boolean;
  className?: string;
}

/**
 * Optically normalized product-navigation glyph with a minimal active rail.
 * The parent navigation item supplies the `group` state for the hover treatment.
 */
export function ProductIcon({
  icon: Icon,
  active = false,
  className,
}: ProductIconProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative inline-flex h-5 w-5 shrink-0 items-center justify-center",
        className
      )}
    >
      {active && (
        <span className="nexora-spectrum absolute -left-3 h-4 w-0.5" />
      )}
      <Icon
        className={cn(
          "h-[19px] w-[19px] transition-colors duration-150",
          active
            ? "text-white"
            : "text-[#979DA5] group-hover:text-white"
        )}
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </span>
  );
}
