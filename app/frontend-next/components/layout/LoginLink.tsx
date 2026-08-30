"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogIn } from "lucide-react";
import { cn } from "@/lib/utils";

export function LoginLink({
  label = "Sign in",
  nextPath,
  onNavigate,
  className,
}: {
  label?: string;
  nextPath?: string;
  onNavigate?: () => void;
  className?: string;
}) {
  const pathname = usePathname();
  const destination = nextPath ?? pathname;
  const href = `/login?next=${encodeURIComponent(destination)}`;

  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={cn(
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2",
        className
      )}
    >
      <LogIn className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{label}</span>
    </Link>
  );
}
