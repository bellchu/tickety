import type { HTMLAttributes, TableHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function DataTableViewport({
  label,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { label: string }) {
  return (
    <div className={cn("relative", className)} {...props}>
      <div
        role="region"
        aria-label={label}
        tabIndex={0}
        className="overflow-x-auto overscroll-x-contain [scrollbar-gutter:stable] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]"
      >
        {children}
      </div>
    </div>
  );
}

export function DataTable({ className, children, ...props }: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <table
      className={cn(
        "w-full table-fixed text-left text-sm [&_td]:align-top [&_th]:align-bottom",
        className
      )}
      {...props}
    >
      {children}
    </table>
  );
}

export function ListText({
  text,
  lines = 2,
  className,
}: {
  text: string;
  lines?: 1 | 2 | 3 | "wrap";
  className?: string;
}) {
  return (
    <span
      title={text}
      className={cn(
        "block min-w-0 [overflow-wrap:anywhere]",
        lines === 1 && "truncate",
        lines === 2 && "line-clamp-2",
        lines === 3 && "line-clamp-3",
        lines === "wrap" && "whitespace-normal break-words",
        className
      )}
    >
      {text}
    </span>
  );
}

export function DataListCard({ className, children, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <article
      className={cn(
        "min-w-0 rounded-xl border border-linen-300 bg-linen-50 p-4 shadow-[0_1px_2px_rgba(1,13,27,0.03)] transition-colors hover:border-linen-500",
        className
      )}
      {...props}
    >
      {children}
    </article>
  );
}
