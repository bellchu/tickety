"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { FetchOldTicketsResult } from "@/lib/types";
import { Download, CheckCircle2 } from "lucide-react";
import { Alert, Button, Dialog } from "@/components/ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function FetchTicketsModal({ open, onClose }: Props) {
  const queryClient = useQueryClient();
  const [preset, setPreset] = useState<"2_months" | "3_months" | "custom">("2_months");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FetchOldTicketsResult | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.fetchOldTickets({ preset, startDate, endDate }),
    onSuccess: (res) => {
      setResult(res.result);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });

  const reset = () => {
    setResult(null);
    setError(null);
  };

  const close = () => {
    if (mutation.isPending) return;
    reset();
    onClose();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => { if (!next) close(); }}
      title="Fetch old tickets"
      description="Queue an administrator-requested Freshservice range without changing the automatic 30-day sync window."
      dismissible={!mutation.isPending}
      footer={result ? <Button onClick={close}>Done</Button> : <><Button variant="secondary" onClick={close} disabled={mutation.isPending}>Cancel</Button><Button onClick={() => mutation.mutate()} disabled={preset === "custom" && (!startDate || !endDate)} pending={mutation.isPending} pendingLabel="Queueing…" leadingIcon={<Download className="h-4 w-4" />}>Queue old-ticket fetch</Button></>}
    >
        <div className="space-y-4">
          <p className="text-sm text-ink-500">
            Only administrators can request older records. The worker checkpoints
            each page and continues under Freshservice&apos;s reported rate limit.
          </p>

          <div>
            <span className="block text-xs font-medium text-ink-600 mb-1.5">Range</span>
            <div className="grid gap-2 sm:grid-cols-3">
              {([
                ["2_months", "Last 2 months"],
                ["3_months", "Last 3 months"],
                ["custom", "Custom dates"],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  disabled={mutation.isPending}
                  onClick={() => { setPreset(value); setError(null); }}
                  className={`min-h-10 rounded-md border px-3 text-xs font-semibold transition-colors disabled:opacity-50 ${preset === value ? "border-semantic-primary bg-semantic-primary/10 text-semantic-primary" : "border-linen-400 bg-linen-100 text-ink-600 hover:bg-linen-200"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {preset === "custom" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-medium text-ink-600">
                Start date
                <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} disabled={mutation.isPending} className="input-base mt-1.5" />
              </label>
              <label className="text-xs font-medium text-ink-600">
                End date
                <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} disabled={mutation.isPending} className="input-base mt-1.5" />
              </label>
            </div>
          )}

          {error && (
            <Alert variant="danger" title="Fetch failed">{error}</Alert>
          )}

          {result && (
            <div className="rounded-lg bg-linen-200 border border-linen-400 p-3">
              <div className="flex items-center gap-1.5 text-ink-600 text-sm font-medium mb-2">
                <CheckCircle2 className="w-4 h-4" /> Old-ticket fetch queued
              </div>
              <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                <span className="text-ink-500">Start</span><span className="text-right font-medium text-ink-700">{result.start_date}</span>
                <span className="text-ink-500">End</span><span className="text-right font-medium text-ink-700">{result.end_date}</span>
              </div>
            </div>
          )}
        </div>
    </Dialog>
  );
}
