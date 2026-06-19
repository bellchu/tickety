"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { FetchTicketsResult } from "@/lib/types";
import { X, Download, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";

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

  if (!open) return null;

  const reset = () => {
    setResult(null);
    setError(null);
  };

  const close = () => {
    reset();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-lg bg-white shadow-xl border border-slate-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <Download className="w-5 h-5 text-slate-600" />
            <h2 className="text-base font-semibold text-slate-900">
              Fetch Tickets
            </h2>
          </div>
          <button
            onClick={close}
            className="text-slate-400 hover:text-slate-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          <p className="text-sm text-slate-500">
            Pull tickets updated in the last N days from your ITSM provider.
            Already-imported tickets are skipped unless overwrite is selected.
            Pagination and rate limits are handled automatically.
          </p>

          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1.5">
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
                  className="px-2.5 py-1 rounded-md text-xs font-medium bg-slate-100 text-slate-600 hover:bg-slate-200 disabled:opacity-50 transition-colors"
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
              className="mt-0.5 w-4 h-4 rounded border-slate-300 text-slate-600 focus:ring-slate-300"
            />
            <span className="text-sm text-slate-700">
              <span className="font-medium">Overwrite existing tickets</span>
              <span className="block text-xs text-slate-500 mt-0.5">
                Re-fetch and refresh tickets already imported from the source.
              </span>
            </span>
          </label>

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 text-red-700 text-sm">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {result && (
            <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
              <div className="flex items-center gap-1.5 text-slate-700 text-sm font-medium mb-2">
                <CheckCircle2 className="w-4 h-4" /> Fetch complete
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                <span className="text-slate-600">Fetched from source</span>
                <span className="text-right font-medium text-slate-900">
                  {result.fetched}
                </span>
                <span className="text-slate-600">New</span>
                <span className="text-right font-medium text-slate-700">
                  {result.new}
                </span>
                <span className="text-slate-600">Updated</span>
                <span className="text-right font-medium text-slate-600">
                  {result.updated}
                </span>
                <span className="text-slate-600">Skipped</span>
                <span className="text-right font-medium text-slate-500">
                  {result.skipped}
                </span>
                {result.errors > 0 && (
                  <>
                    <span className="text-slate-600">Errors</span>
                    <span className="text-right font-medium text-red-600">
                      {result.errors}
                    </span>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-5 py-4 border-t border-slate-100">
          {result ? (
            <button
              onClick={close}
              className="btn-primary text-xs"
            >
              Done
            </button>
          ) : (
            <>
              <button
                onClick={close}
                disabled={mutation.isPending}
                className="btn-secondary text-xs"
              >
                Cancel
              </button>
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending || days < 1}
                className="btn-primary text-xs"
              >
                {mutation.isPending ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Fetching…
                  </>
                ) : (
                  <>
                    <Download className="w-3.5 h-3.5" /> Fetch last {days}{" "}
                    day{days > 1 ? "s" : ""}
                  </>
                )}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
