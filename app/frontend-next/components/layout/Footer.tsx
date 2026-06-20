"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function Footer() {
  const { data: version } = useQuery({
    queryKey: ["version"],
    queryFn: api.getVersion,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  return (
    <footer className="border-t border-linen-300 bg-linen-50/50 px-6 py-3 text-xs text-ink-400 flex items-center justify-between">
      <span className="font-serif italic">Tickety</span>
      <span className="flex items-center gap-3">
        {version && (
          <>
            <span>v{version.version}</span>
            <span className="text-linen-400">·</span>
          </>
        )}
        <span className="font-mono text-[11px]">
          {version?.build_sha?.slice(0, 7) || "local"}
        </span>
      </span>
    </footer>
  );
}