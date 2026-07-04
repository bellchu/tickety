"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { PortalTicket } from "@/lib/types";
import {
  Globe, Send, FileText, Search, RefreshCw, Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";

const PRIORITIES = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

const PRIORITY_COLORS: Record<string, string> = {
  urgent: "bg-rust-400/15 text-rust-500 border-rust-400/30",
  high: "bg-amber-400/15 text-amber-600 border-amber-400/30",
  medium: "bg-blue-400/15 text-blue-600 border-blue-400/30",
  low: "bg-moss-400/15 text-moss-600 border-moss-400/30",
  P1: "bg-rust-400/15 text-rust-500 border-rust-400/30",
  P2: "bg-amber-400/15 text-amber-600 border-amber-400/30",
  P3: "bg-blue-400/15 text-blue-600 border-blue-400/30",
  P4: "bg-moss-400/15 text-moss-600 border-moss-400/30",
};

const STATUS_COLORS: Record<string, string> = {
  open: "bg-blue-400/15 text-blue-600 border-blue-400/30",
  in_progress: "bg-violet-400/15 text-violet-600 border-violet-400/30",
  resolved: "bg-emerald-400/15 text-emerald-600 border-emerald-400/30",
  closed: "bg-ink-100 text-ink-600 border-ink-300",
};

export default function PortalPage() {
  const queryClient = useQueryClient();

  const [reporter, setReporter] = useState("");
  const [searchReporter, setSearchReporter] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [searchTicketId, setSearchTicketId] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("medium");

  const {
    data: tickets,
    isLoading: ticketsLoading,
    error: ticketsError,
  } = useQuery({
    queryKey: ["portalTickets", searchReporter, searchTicketId],
    queryFn: () => api.portalListTickets(searchReporter, searchTicketId),
    enabled: searchReporter.length > 0 && searchTicketId.length > 0,
  });

  const createMut = useMutation({
    mutationFn: () => api.portalCreateTicket(subject, description, reporter, priority),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["portalTickets", reporter, created.id] });
      setShowForm(false);
      setSubject("");
      setDescription("");
      setTicketId(created.id);
      setSearchReporter(reporter);
      setSearchTicketId(created.id);
    },
  });

  const handleLookup = () => {
    if (reporter.trim() && ticketId.trim()) {
      setSearchReporter(reporter.trim());
      setSearchTicketId(ticketId.trim());
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Self-Service Portal</h1>
          <p className="text-[13px] text-ink-500">
            Submit tickets and track your requests
          </p>
        </div>
        <button onClick={() => setShowForm(true)} className="btn-primary text-xs">
          <Plus className="w-4 h-4" strokeWidth={1.5} />
          New Ticket
        </button>
      </div>

      {/* Reporter lookup */}
      <div className="card-surface p-4">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-end">
          <label className="flex-1 space-y-1">
            <span className="text-xs font-medium text-ink-500">Your Email</span>
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="email"
                value={reporter}
                onChange={(e) => setReporter(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleLookup()}
                className="input-base input-search text-xs"
                placeholder="you@company.com"
              />
            </div>
          </label>
          <label className="flex-1 space-y-1">
            <span className="text-xs font-medium text-ink-500">Ticket ID</span>
            <input
              value={ticketId}
              onChange={(e) => setTicketId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLookup()}
              className="input-base text-xs"
              placeholder="portal-..."
            />
          </label>
          <button onClick={handleLookup} disabled={!reporter.trim() || !ticketId.trim()} className="btn-secondary text-xs">
            <Search className="w-3.5 h-3.5" strokeWidth={1.5} />
            Look Up
          </button>
        </div>
      </div>

      {/* Tickets list */}
      {!searchReporter || !searchTicketId ? (
        <div className="card-surface p-10 text-center space-y-2">
          <Globe className="w-10 h-10 text-ink-300 mx-auto" strokeWidth={1} />
          <p className="text-sm text-ink-500">Enter your email and ticket ID to view a request.</p>
        </div>
      ) : ticketsLoading ? (
        <div className="card-surface p-6 space-y-3">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-12 w-full" />)}</div>
      ) : ticketsError ? (
        <div className="card-surface p-6 text-center">
          <p className="text-sm text-rust-500">Failed to load the ticket. Check the email address and ticket ID.</p>
        </div>
      ) : (
        <div className="card-surface overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-linen-200 bg-linen-100">
            <p className="text-xs font-semibold text-ink-500 uppercase tracking-wider">
              Ticket <span className="text-ink-700">{searchTicketId}</span>
              <span className="ml-2 font-normal normal-case text-ink-400">({tickets?.length || 0})</span>
            </p>
            <div className="flex items-center gap-2">
              <button onClick={handleLookup} className="p-1 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200" title="Refresh">
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-300 bg-linen-100">
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Ticket</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Subject</th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">Priority</th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">Created</th>
              </tr>
            </thead>
            <tbody>
              {(tickets || []).length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-ink-400 text-sm">No ticket found for this email and ticket ID.</td>
                </tr>
              ) : (
                (tickets || []).map((t: PortalTicket) => (
                  <tr key={t.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileText className="w-3.5 h-3.5 text-ink-400" strokeWidth={1.5} />
                        <span className="text-xs font-mono text-ink-500">{t.id}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 font-medium text-ink-700 max-w-64 truncate">{t.subject}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                        PRIORITY_COLORS[t.priority] || PRIORITY_COLORS.medium
                      )}>
                        {t.priority}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                        STATUS_COLORS[t.status.toLowerCase()] || "bg-ink-100 text-ink-600 border-ink-300"
                      )}>
                        {t.status.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-ink-400 tabular-nums">
                      {t.created_at ? new Date(t.created_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* New ticket form modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm" onClick={() => setShowForm(false)}>
          <div className="card-surface w-full max-w-lg p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="font-serif text-xl text-ink-700">Submit a Ticket</h2>
              <button onClick={() => setShowForm(false)} className="p-1 rounded text-ink-400 hover:bg-linen-200">
                <Send className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              <label className="block space-y-1">
                <span className="text-xs font-medium text-ink-500">Your Email</span>
                <input
                  type="email"
                  value={reporter}
                  onChange={(e) => setReporter(e.target.value)}
                  className="input-base"
                  placeholder="you@company.com"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-ink-500">Subject</span>
                <input
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="input-base"
                  placeholder="Brief summary of your issue"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-ink-500">Description</span>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="input-base min-h-[100px]"
                  placeholder="Describe your issue in detail…"
                  rows={4}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-ink-500">Priority</span>
                <select value={priority} onChange={(e) => setPriority(e.target.value)} className="input-base">
                  {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </select>
              </label>
            </div>
            {createMut.error && (
              <p className="text-xs text-rust-500">
                Failed: {createMut.error instanceof Error ? createMut.error.message : String(createMut.error)}
              </p>
            )}
            <div className="flex items-center justify-end gap-2">
              <button onClick={() => setShowForm(false)} className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200">Cancel</button>
              <button
                onClick={() => createMut.mutate()}
                disabled={createMut.isPending || !reporter.trim() || !subject.trim() || !description.trim()}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-clay-500 text-linen-50 text-xs font-semibold hover:bg-clay-600 disabled:opacity-50"
              >
                {createMut.isPending && <RefreshCw className="w-3 h-3 animate-spin" />}
                <Send className="w-3 h-3" />
                Submit
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
