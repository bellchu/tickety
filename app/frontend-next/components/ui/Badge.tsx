import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export type BadgeVariant = "neutral" | "info" | "success" | "warning" | "danger";

const variantClasses: Record<BadgeVariant, string> = {
  neutral: "border-linen-400 bg-linen-200 text-ink-500",
  info: "border-clay-200 bg-[var(--color-info-soft)] text-clay-700",
  success: "border-moss-400/40 bg-[var(--color-success-soft)] text-moss-600",
  warning: "border-amber-400/40 bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
  danger: "border-rust-400/40 bg-[var(--color-danger-soft)] text-rust-600",
};

const dotClasses: Record<BadgeVariant, string> = {
  neutral: "bg-ink-400",
  info: "bg-semantic-info",
  success: "bg-semantic-success",
  warning: "bg-semantic-warning",
  danger: "bg-semantic-danger",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  dot?: boolean;
  icon?: ReactNode;
}

export function Badge({
  variant = "neutral",
  dot = false,
  icon,
  className,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-none",
        variantClasses[variant],
        className
      )}
      {...props}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", dotClasses[variant])} aria-hidden="true" />}
      {icon && <span className="shrink-0" aria-hidden="true">{icon}</span>}
      {children}
    </span>
  );
}
