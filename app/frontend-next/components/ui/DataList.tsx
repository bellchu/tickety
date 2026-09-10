import type { HTMLAttributes, TableHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function DataTableViewport({
  label,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { label: string }) {
  return (
    <div className={cn("relative min-w-0 max-w-full", className)} {...props}>
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
        "w-full table-fixed text-left text-sm [&_td]:align-top [&_td]:whitespace-normal [&_td]:[overflow-wrap:anywhere] [&_th]:align-bottom [&_th]:whitespace-normal [&_th]:[overflow-wrap:anywhere]",
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
  lines = "wrap",
  className,
}: {
  text: string;
  lines?: 1 | 2 | 3 | "wrap";
  className?: string;
}) {
  return (
    <span
      title={text}
      data-preferred-lines={lines}
      className={cn(
        "block min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]",
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
        "min-w-0 rounded-xl border border-linen-300 bg-linen-50 p-4 shadow-[var(--shadow-card)] transition-[border-color,box-shadow,transform] hover:border-linen-500 hover:shadow-[0_10px_28px_rgba(1,13,27,0.07)]",
        className
      )}
      {...props}
    >
      {children}
    </article>
  );
}
