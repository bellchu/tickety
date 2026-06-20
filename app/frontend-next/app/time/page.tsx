"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TimeEntry, Ticket } from "@/lib/types";
import {
  Timer, Plus, RefreshCw, X, Search, Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function TimePage() {
  const queryClient = useQueryClient();

  const [filterTicket, setFilterTicket] = useState("");
  const [showForm, setShowForm] = useState(false);

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["timeSummary"],
    queryFn: api.getTimeSummary,
  });

  const { data: entries, isLoading: entriesLoading } = useQuery({
    queryKey: ["timeEntries", filterTicket],
    queryFn: () => api.getTimeEntries(filterTicket || undefined),
  });

  const { data: tickets } = useQuery({
    queryKey: ["tickets"],
    queryFn: api.getTickets,
  });

  const createMut = useMutation({
    mutationFn: ({
      ticketId,
      description,
      minutes,
    }: {
      ticketId: string;
      description: string;
      minutes: number;
    }) => api.createTimeEntry(ticketId, description, minutes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeEntries"] });
      queryClient.invalidateQueries({ queryKey: ["timeSummary"] });
      setShowForm(false);
    },
  });

  const uniqueTicketCount = useMemo(() => {
    if (!entries) return 0;
    return new Set(entries.map((e) => e.ticket_id)).size;
  }, [entries]);

  const avgPerTicket =
    summary && uniqueTicketCount > 0
      ? (summary.total_hours / uniqueTicketCount).toFixed(1)
      : "—";

  const formatHours = (minutes: number) => {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Time Tracking</h1>
          <p className="text-[13px] text-ink-500">
            Log &amp; review time across tickets
          </p>
        </div>
        <button onClick={() => setShowForm(true)} className="btn-primary text-xs">
          <Plus className="w-4 h-4" strokeWidth={1.5} />
          Log Time
        </button>
      </div>

      {/* Summary bar */}
      {summaryLoading ? (
        <div className="grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="card-surface p-4 space-y-1.5">
              <div className="skeleton h-3 w-16" />
              <div className="skeleton h-6 w-10" />
            </div>
          ))}
        </div>
      ) : summary ? (
        <div className="grid grid-cols-3 gap-3">
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Total Hours</p>
            <p className="kpi-value">{summary.total_hours.toFixed(1)}</p>
          </div>
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Today</p>
            <p className="kpi-value">{summary.today_hours.toFixed(1)}h</p>
          </div>
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Avg per Ticket</p>
            <p className="kpi-value">{avgPerTicket}h</p>
          </div>
        </div>
      ) : null}

      {/* Filter */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="w-3.5 h-3.5 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <select
            value={filterTicket}
            onChange={(e) => setFilterTicket(e.target.value)}
            className="input-base input-search text-xs"
          >
            <option value="">All Tickets</option>
            {(tickets || []).map((t) => (
              <option key={t.id} value={t.id}>{t.subject}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Time entries table */}
      {entriesLoading ? (
        <div className="card-surface p-6 space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton h-12 w-full" />
          ))}
        </div>
      ) : !entries || entries.length === 0 ? (
        <div className="card-surface p-12 text-center text-ink-400">
          <Clock className="w-8 h-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No time entries logged</p>
        </div>
      ) : (
        <div className="card-surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-300 bg-linen-100">
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Ticket</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">User</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Description</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">Time</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Date</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100">
                  <td className="px-4 py-3">
                    <span className="font-medium text-ink-700 font-mono text-xs">{e.ticket_id.slice(0, 8)}</span>
                  </td>
                  <td className="px-4 py-3 text-ink-500">{e.user_name || e.user_id}</td>
                  <td className="px-4 py-3 text-ink-600 max-w-xs truncate">{e.description}</td>
                  <td className="px-4 py-3 text-right tabular-nums font-medium text-ink-600">
                    {formatHours(e.minutes)}
                  </td>
                  <td className="px-4 py-3 text-ink-500 text-xs">
                    {e.entry_date ? new Date(e.entry_date).toLocaleDateString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Log Time modal */}
      {showForm && (
        <LogTimeModal
          tickets={tickets || []}
          onClose={() => setShowForm(false)}
          onSubmit={(ticketId, description, minutes) =>
            createMut.mutate({ ticketId, description, minutes })
          }
          loading={createMut.isPending}
          error={createMut.error}
        />
      )}
    </div>
  );
}

function LogTimeModal({
  tickets,
  onClose,
  onSubmit,
  loading,
  error,
}: {
  tickets: Ticket[];
  onClose: () => void;
  onSubmit: (ticketId: string, description: string, minutes: number) => void;
  loading: boolean;
  error: unknown;
}) {
  const [ticketId, setTicketId] = useState("");
  const [description, setDescription] = useState("");
  const [hours, setHours] = useState("");
  const [mins, setMins] = useState("");

  const errorMsg = error instanceof Error ? error.message : error ? String(error) : null;

  const totalMinutes = (parseInt(hours) || 0) * 60 + (parseInt(mins) || 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="card-surface w-full max-w-md p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl text-ink-700">Log Time</h2>
          <button onClick={onClose} className="p-1 rounded text-ink-400 hover:bg-linen-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Ticket</span>
            <select value={ticketId} onChange={(e) => setTicketId(e.target.value)} className="input-base">
              <option value="">Select a ticket…</option>
              {tickets.map((t) => (
                <option key={t.id} value={t.id}>{t.subject}</option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Description</span>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input-base"
              placeholder="Worked on troubleshooting…"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Hours</span>
              <input
                type="number"
                min="0"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
                className="input-base"
                placeholder="0"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Minutes</span>
              <input
                type="number"
                min="0"
                max="59"
                value={mins}
                onChange={(e) => setMins(e.target.value)}
                className="input-base"
                placeholder="0"
              />
            </label>
          </div>
          {totalMinutes > 0 && (
            <p className="text-xs text-ink-400">
              Total: {Math.floor(totalMinutes / 60)}h {totalMinutes % 60}m
            </p>
          )}
        </div>
        {errorMsg && <p className="text-xs text-rust-500">Failed: {errorMsg}</p>}
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200">
            Cancel
          </button>
          <button
            onClick={() => onSubmit(ticketId, description, totalMinutes)}
            disabled={loading || !ticketId || !description.trim() || totalMinutes <= 0}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading ? (
              <RefreshCw className="w-3 h-3 animate-spin" />
            ) : (
              <Clock className="w-3 h-3" />
            )}
            Log Time
          </button>
        </div>
      </div>
    </div>
  );
}
