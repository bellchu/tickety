import type { HTMLAttributes, ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, type ButtonProps } from "./Button";

export type AlertVariant = "info" | "success" | "warning" | "danger";

const alertStyles: Record<AlertVariant, { container: string; icon: typeof Info }> = {
  info: { container: "border-clay-200 bg-[var(--color-info-soft)] text-clay-800", icon: Info },
  success: { container: "border-moss-400/40 bg-[var(--color-success-soft)] text-moss-600", icon: CheckCircle2 },
  warning: { container: "border-amber-400/40 bg-[var(--color-warning-soft)] text-[var(--color-warning)]", icon: TriangleAlert },
  danger: { container: "border-rust-400/40 bg-[var(--color-danger-soft)] text-rust-600", icon: AlertCircle },
};

export interface AlertProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  variant?: AlertVariant;
  title?: ReactNode;
  action?: ReactNode;
}

export function Alert({ variant = "info", title, action, className, children, ...props }: AlertProps) {
  const Icon = alertStyles[variant].icon;
  return (
    <div
      role={variant === "danger" ? "alert" : "status"}
      className={cn("flex min-w-0 flex-col items-start gap-3 rounded-xl border px-4 py-3 text-sm xs:flex-row", alertStyles[variant].container, className)}
      {...props}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={cn("break-words leading-5 [overflow-wrap:anywhere]", title && "mt-0.5 opacity-90")}>{children}</div>}
      </div>
      {action && <div className="max-w-full shrink-0 self-end xs:self-auto">{action}</div>}
    </div>
  );
}

interface StateProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ title, description, icon, action, className, ...props }: StateProps) {
  return (
    <div className={cn("flex min-h-52 flex-col items-center justify-center rounded-2xl border border-dashed border-linen-500 bg-linen-50 px-6 py-10 text-center", className)} {...props}>
      {icon && <div className="mb-4 grid h-11 w-11 place-items-center rounded-xl bg-linen-300 text-ink-500" aria-hidden="true">{icon}</div>}
      <h3 className="text-sm font-semibold text-ink-700">{title}</h3>
      {description && <div className="mt-1 max-w-md text-sm leading-5 text-ink-500">{description}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export interface ErrorStateProps extends Omit<StateProps, "action"> {
  actionLabel?: string;
  onRetry?: () => void;
  retrying?: boolean;
  actionProps?: Omit<ButtonProps, "children" | "onClick" | "pending">;
}

export function ErrorState({
  title,
  description,
  icon = <AlertCircle className="h-5 w-5" />,
  actionLabel = "Try again",
  onRetry,
  retrying = false,
  actionProps,
  className,
  ...props
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn("flex min-h-52 flex-col items-center justify-center rounded-2xl border border-rust-400/30 bg-[var(--color-danger-soft)] px-6 py-10 text-center", className)}
      {...props}
    >
      <div className="mb-4 grid h-11 w-11 place-items-center rounded-xl bg-white/70 text-semantic-danger" aria-hidden="true">{icon}</div>
      <h3 className="text-sm font-semibold text-ink-700">{title}</h3>
      {description && <div className="mt-1 max-w-md text-sm leading-5 text-ink-500">{description}</div>}
      {onRetry && (
        <Button className="mt-5" variant="secondary" onClick={onRetry} pending={retrying} pendingLabel="Retrying…" {...actionProps}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  rounded?: "sm" | "md" | "lg" | "full";
}

const skeletonRadius = {
  sm: "rounded",
  md: "rounded-lg",
  lg: "rounded-xl",
  full: "rounded-full",
};

export function Skeleton({ rounded = "md", className, ...props }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "relative overflow-hidden bg-linen-300 before:absolute before:inset-0 before:-translate-x-full before:animate-shimmer before:bg-gradient-to-r before:from-transparent before:via-white/60 before:to-transparent",
        skeletonRadius[rounded],
        className
      )}
      {...props}
    />
  );
}
