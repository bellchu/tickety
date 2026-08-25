"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, ScrollText } from "lucide-react";
import { api } from "@/lib/api";
import { formatLocalDateTime } from "@/lib/date-time";
import type { OperationalDiagnosticArea } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button, Skeleton } from "@/components/ui";

export function DiagnosticReveal({
  area,
  ticketId,
  className,
}: {
  area?: OperationalDiagnosticArea;
  ticketId?: string;
  className?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  const query = useQuery({
    queryKey: ticketId ? ["ai-task-diagnostics", ticketId] : ["status-diagnostics", area],
    queryFn: () => ticketId
      ? api.getAITaskDiagnostics(ticketId)
      : api.getStatusDiagnostics(area as OperationalDiagnosticArea),
    enabled: revealed && Boolean(ticketId || area),
    retry: false,
  });

  return (
    <div className={cn("rounded-lg border border-linen-400 bg-linen-100 p-3", className)}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-ink-600">
          <ScrollText className="h-4 w-4 text-ink-400" /> Stored diagnostics
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setRevealed((current) => !current)}
          leadingIcon={revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        >
          {revealed ? "Hide logs" : "Reveal logs"}
        </Button>
      </div>
      {revealed && (
        <div className="mt-3" aria-live="polite">
          {query.isLoading && <div className="space-y-2"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>}
          {query.error && (
            <p role="alert" className="rounded-md border border-rust-400/30 bg-[var(--color-danger-soft)] px-3 py-2 text-xs text-rust-600">Diagnostic logs could not be loaded.</p>
          )}
          {query.data && query.data.entries.length === 0 && (
            <p className="rounded-md border border-linen-400 bg-linen-50 px-3 py-2 text-xs leading-5 text-ink-500">No durable diagnostic log was recorded for this condition. Process-level logs may still exist outside Tickety.</p>
          )}
          {query.data && query.data.entries.length > 0 && (
            <div className="max-h-72 space-y-2 overflow-auto rounded-lg bg-[#071322] p-3 text-slate-200 shadow-inner">
              {query.data.entries.map((entry, index) => (
                <div key={`${entry.source}-${entry.timestamp || index}`} className="border-b border-white/10 pb-2 last:border-0 last:pb-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] uppercase tracking-[0.08em]">
                    <span className={entry.severity === "error" ? "text-red-300" : entry.severity === "warning" ? "text-amber-300" : "text-sky-300"}>{entry.severity}</span>
                    <span className="break-all text-slate-400">{entry.source}</span>
                    <span className="text-slate-500">{formatLocalDateTime(entry.timestamp, undefined, "time unavailable")}</span>
                  </div>
                  <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-slate-200">{entry.message}</pre>
                </div>
              ))}
              {query.data.truncated && <p className="pt-1 text-[10px] text-amber-300">Only the newest 50 diagnostic entries are shown.</p>}
            </div>
          )}
          {query.data && <p className="mt-2 text-[10px] leading-4 text-ink-400">Sensitive credentials and personal identifiers are redacted before stored diagnostics leave the server.</p>}
        </div>
      )}
    </div>
  );
}
