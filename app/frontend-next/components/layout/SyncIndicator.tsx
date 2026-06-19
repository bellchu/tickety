"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RefreshCw, CheckCircle2, AlertTriangle, WifiOff } from "lucide-react";
import { formatTimeAgo } from "@/lib/utils";

export function SyncIndicator() {
  const { data: status, isLoading } = useQuery({
    queryKey: ["sync-status"],
    queryFn: api.getSyncStatus,
    refetchInterval: 30_000,
  });

  const icon = () => {
    if (isLoading)
      return <RefreshCw className="w-3.5 h-3.5 animate-spin text-slate-400" />;
    if (!status || status.last_status === "idle")
      return <WifiOff className="w-3.5 h-3.5 text-slate-400" />;
    if (status.last_status === "error")
      return <AlertTriangle className="w-3.5 h-3.5 text-slate-500" />;
    return <CheckCircle2 className="w-3.5 h-3.5 text-slate-500" />;
  };

  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-slate-400"
      title={
        status?.last_synced_at
          ? `Last sync: ${formatTimeAgo(status.last_synced_at)}`
          : "Sync status"
      }
    >
      {icon()}
      {status?.last_synced_at && formatTimeAgo(status.last_synced_at)}
    </span>
  );
}
