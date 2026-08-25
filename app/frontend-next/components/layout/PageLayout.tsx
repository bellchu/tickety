import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PageFrame({
  width = "default",
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { width?: "default" | "wide" }) {
  return (
    <div
      className={cn(
        "mx-auto min-w-0 w-full space-y-6 sm:space-y-7",
        width === "default" ? "max-w-7xl" : "max-w-[1440px]",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  icon,
  title,
  description,
  meta,
  actions,
  className,
}: {
  eyebrow?: ReactNode;
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "relative flex flex-col gap-5 border-b border-linen-400 pb-6 sm:flex-row sm:items-end sm:justify-between",
        className
      )}
    >
      <div className="min-w-0 max-w-3xl">
        {eyebrow && (
          <div className="flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.13em] text-ink-400">
            {icon && <span className="text-semantic-primary" aria-hidden="true">{icon}</span>}
            <span>{eyebrow}</span>
          </div>
        )}
        <h1 className={cn("break-words text-3xl font-medium tracking-[-0.035em] text-ink-700 [overflow-wrap:anywhere] sm:text-4xl", eyebrow && "mt-2")}>
          {title}
        </h1>
        {description && <div className="mt-2 text-sm leading-6 text-ink-500">{description}</div>}
        {meta && <div className="mt-2 text-xs text-ink-400">{meta}</div>}
      </div>
      {actions && <div className="flex min-w-0 max-w-full shrink-0 flex-col gap-2 xs:flex-row xs:flex-wrap sm:flex-row">{actions}</div>}
      <span aria-hidden="true" className="nexora-spectrum absolute -bottom-px left-0 h-[2px] w-36" />
    </header>
  );
}

export function SummaryStrip({
  label,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLElement> & { label: string }) {
  return (
    <section
      aria-label={label}
      className={cn("grid gap-3 sm:grid-cols-2 xl:grid-cols-4", className)}
      {...props}
    >
      {children}
    </section>
  );
}

export function SectionHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        <h2 className="text-base font-medium tracking-[-0.01em] text-ink-700">{title}</h2>
        {description && <div className="mt-1 text-xs leading-5 text-ink-500">{description}</div>}
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </div>
  );
}

export function DataToolbar({
  label,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLElement> & { label: string }) {
  return (
    <section
      aria-label={label}
      className={cn("rounded-xl border border-linen-400 bg-linen-50 p-4 shadow-[var(--shadow-card)] sm:p-5", className)}
      {...props}
    >
      {children}
    </section>
  );
}

export function ContentSurface({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn("overflow-hidden rounded-xl border border-linen-400 bg-linen-50 shadow-[var(--shadow-card)]", className)}
      {...props}
    >
      {children}
    </section>
  );
}
