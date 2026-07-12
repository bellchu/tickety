"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { FetchTicketsResult } from "@/lib/types";
import { Download, CheckCircle2 } from "lucide-react";
import { Alert, Button, Dialog } from "@/components/ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function FetchTicketsModal({ open, onClose }: Props) {
  const queryClient = useQueryClient();
  const [days, setDays] = useState(7);
  const [overwrite, setOverwrite] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FetchTicketsResult | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.fetchTickets(days, overwrite),
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
      title="Fetch tickets from ITSM"
      description="Import recently updated source records. Pagination and provider rate limits are handled automatically."
      dismissible={!mutation.isPending}
      footer={result ? <Button onClick={close}>Done</Button> : <><Button variant="secondary" onClick={close} disabled={mutation.isPending}>Cancel</Button><Button onClick={() => mutation.mutate()} disabled={days < 1} pending={mutation.isPending} pendingLabel="Fetching…" leadingIcon={<Download className="h-4 w-4" />}>Fetch last {days} day{days > 1 ? "s" : ""}</Button></>}
    >
        <div className="space-y-4">
          <p className="text-sm text-ink-500">
            Pull tickets updated in the last N days from your ITSM provider.
            Already-imported tickets are skipped unless overwrite is selected.
            Pagination and rate limits are handled automatically.
          </p>

          <div>
            <label className="block text-xs font-medium text-ink-600 mb-1.5">
              Days to fetch
            </label>
            <input
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) =>
                setDays(Math.max(1, Math.min(365, Number(e.target.value) || 1)))
              }
              disabled={mutation.isPending}
              className="input-base"
            />
            <div className="flex flex-wrap gap-1.5 mt-2">
              {[1, 7, 30, 90].map((d) => (
                <button
                  key={d}
                  type="button"
                  disabled={mutation.isPending}
                  onClick={() => setDays(d)}
                  className="px-2.5 py-1 rounded-md text-xs font-medium bg-linen-300 text-ink-600 hover:bg-linen-400 disabled:opacity-50 transition-colors"
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>

          <label className="flex items-start gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(e) => setOverwrite(e.target.checked)}
              disabled={mutation.isPending}
              className="mt-0.5 w-4 h-4 rounded border-linen-400 text-clay-500 focus:ring-clay-400/30"
            />
            <span className="text-sm text-ink-600">
              <span className="font-medium">Overwrite existing tickets</span>
              <span className="block text-xs text-ink-500 mt-0.5">
                Re-fetch and refresh tickets already imported from the source.
              </span>
            </span>
          </label>

          {error && (
            <Alert variant="danger" title="Fetch failed">{error}</Alert>
          )}

          {result && (
            <div className="rounded-lg bg-linen-200 border border-linen-400 p-3">
              <div className="flex items-center gap-1.5 text-ink-600 text-sm font-medium mb-2">
                <CheckCircle2 className="w-4 h-4" /> Fetch complete
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                <span className="text-ink-600">Fetched from source</span>
                <span className="text-right font-medium text-ink-700">
                  {result.fetched}
                </span>
                <span className="text-ink-600">New</span>
                <span className="text-right font-medium text-ink-600">
                  {result.new}
                </span>
                <span className="text-ink-600">Updated</span>
                <span className="text-right font-medium text-ink-600">
                  {result.updated}
                </span>
                <span className="text-ink-600">Skipped</span>
                <span className="text-right font-medium text-ink-500">
                  {result.skipped}
                </span>
                {result.errors > 0 && (
                  <>
                    <span className="text-ink-600">Errors</span>
                    <span className="text-right font-medium text-rust-500">
                      {result.errors}
                    </span>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
    </Dialog>
  );
}
