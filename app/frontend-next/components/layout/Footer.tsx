"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TicketyLogo } from "@/components/layout/TicketyLogo";

export function Footer() {
  const { data: version } = useQuery({
    queryKey: ["version"],
    queryFn: api.getVersion,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  return (
    <footer className="relative flex min-w-0 flex-wrap items-center justify-between gap-3 overflow-hidden border-t border-white/10 bg-[#010D1B] px-4 py-4 text-xs text-[#979DA5] sm:px-6">
      <span aria-hidden="true" className="tickety-accent absolute inset-x-0 top-0 h-[2px]" />
      <TicketyLogo inverse showDescriptor={false} size="sm" />
      <span className="flex min-w-0 items-center gap-2 sm:gap-3">
        {version && (
          <>
            <span>v{version.version}</span>
            <span className="text-white/25">·</span>
          </>
        )}
        <span className="font-mono text-[11px]">
          {version?.build_sha?.slice(0, 7) || "local"}
        </span>
      </span>
    </footer>
  );
}
