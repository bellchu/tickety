"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SurveyTemplate, SurveyOut, Ticket } from "@/lib/types";
import {
  MessageSquareHeart, Plus, RefreshCw, X, Send, Star, BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";

const RATING_LABELS: Record<string, string> = {
  "5": "5 ★",
  "4": "4 ★",
  "3": "3 ★",
  "2": "2 ★",
  "1": "1 ★",
};

export default function SurveysPage() {
  const queryClient = useQueryClient();

  const [showForm, setShowForm] = useState(false);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["surveyStats"],
    queryFn: api.getSurveyStats,
  });

  const { data: surveys, isLoading: surveysLoading } = useQuery({
    queryKey: ["surveys"],
    queryFn: api.getSurveys,
  });

  const { data: templates } = useQuery({
    queryKey: ["surveyTemplates"],
    queryFn: api.getSurveyTemplates,
  });

  const { data: tickets } = useQuery({
    queryKey: ["tickets"],
    queryFn: api.getTickets,
  });

  const sendMut = useMutation({
    mutationFn: ({ ticketId, templateId }: { ticketId: string; templateId: number }) =>
      api.sendSurvey(ticketId, templateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["surveys"] });
      queryClient.invalidateQueries({ queryKey: ["surveyStats"] });
      setShowForm(false);
    },
  });

  const distribution = stats?.distribution || {};
  const maxDist = Math.max(1, ...Object.values(distribution));

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Surveys</h1>
          <p className="text-[13px] text-ink-500">
            CSAT &amp; feedback · measure satisfaction
          </p>
        </div>
        <button onClick={() => setShowForm(true)} className="btn-primary text-xs">
          <Send className="w-4 h-4" strokeWidth={1.5} />
          Send Survey
        </button>
      </div>

      {/* Stats bar */}
      {statsLoading ? (
        <div className="grid grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card-surface p-4 space-y-1.5">
              <div className="skeleton h-3 w-16" />
              <div className="skeleton h-6 w-10" />
            </div>
          ))}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-4 gap-3">
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Total Sent</p>
            <p className="kpi-value">{stats.total_sent}</p>
          </div>
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Response Rate</p>
            <p className="kpi-value">{stats.response_rate}%</p>
          </div>
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Avg Rating</p>
            <p className="kpi-value">{stats.avg_rating.toFixed(1)}</p>
          </div>
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Responded</p>
            <p className="kpi-value">{stats.responded}</p>
          </div>
        </div>
      ) : null}

      {/* Rating distribution + avg rating */}
      {stats && Object.keys(distribution).length > 0 && (
        <div className="card-surface p-6 flex gap-8">
          <div className="shrink-0 flex flex-col items-center justify-center w-24">
            <p className="text-4xl font-serif text-ink-700">{stats.avg_rating.toFixed(1)}</p>
            <div className="flex items-center gap-0.5 mt-1">
              {[1, 2, 3, 4, 5].map((s) => (
                <Star
                  key={s}
                  className={cn(
                    "w-3 h-3",
                    s <= Math.round(stats.avg_rating) ? "text-amber-500 fill-amber-500" : "text-linen-400"
                  )}
                />
              ))}
            </div>
            <p className="text-[11px] text-ink-400 mt-1">avg rating</p>
          </div>
          <div className="flex-1 space-y-2">
            {[5, 4, 3, 2, 1].map((r) => {
              const count = distribution[String(r)] || 0;
              const pct = maxDist > 0 ? (count / maxDist) * 100 : 0;
              return (
                <div key={r} className="flex items-center gap-3">
                  <span className="text-xs text-ink-500 w-8 text-right tabular-nums">{RATING_LABELS[String(r)]}</span>
                  <div className="flex-1 h-5 bg-linen-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-amber-400 rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs text-ink-400 w-6 tabular-nums">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Surveys table */}
      {surveysLoading ? (
        <div className="card-surface p-6 space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton h-12 w-full" />
          ))}
        </div>
      ) : !surveys || surveys.length === 0 ? (
        <div className="card-surface p-12 text-center text-ink-400">
          <MessageSquareHeart className="w-8 h-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No surveys sent yet</p>
        </div>
      ) : (
        <div className="card-surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-300 bg-linen-100">
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Ticket</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Sent</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Responded</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody>
              {surveys.map((s) => (
                <tr key={s.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100">
                  <td className="px-4 py-3 font-medium text-ink-700 max-w-xs truncate">
                    {s.ticket_subject || s.ticket_id}
                  </td>
                  <td className="px-4 py-3 text-ink-500 text-xs">
                    {s.sent_at ? new Date(s.sent_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-ink-500 text-xs">
                    {s.responded_at ? new Date(s.responded_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "badge",
                        s.responded_at
                          ? "bg-moss-400/15 text-moss-600 border-moss-400/30"
                          : "bg-amber-400/15 text-amber-600 border-amber-400/30"
                      )}
                    >
                      {s.responded_at ? "Responded" : "Sent"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Send Survey modal */}
      {showForm && (
        <SendSurveyModal
          tickets={tickets || []}
          templates={templates || []}
          onClose={() => setShowForm(false)}
          onSubmit={(ticketId, templateId) => sendMut.mutate({ ticketId, templateId })}
          loading={sendMut.isPending}
          error={sendMut.error}
        />
      )}
    </div>
  );
}

function SendSurveyModal({
  tickets,
  templates,
  onClose,
  onSubmit,
  loading,
  error,
}: {
  tickets: Ticket[];
  templates: SurveyTemplate[];
  onClose: () => void;
  onSubmit: (ticketId: string, templateId: number) => void;
  loading: boolean;
  error: unknown;
}) {
  const [ticketId, setTicketId] = useState("");
  const [templateId, setTemplateId] = useState("");

  const errorMsg = error instanceof Error ? error.message : error ? String(error) : null;
  const activeTemplates = templates.filter((t) => t.is_active);

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
          <h2 className="font-serif text-xl text-ink-700">Send Survey</h2>
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
            <span className="text-xs font-medium text-ink-500">Template</span>
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} className="input-base">
              <option value="">Select a template…</option>
              {activeTemplates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
          {templateId && (
            <p className="text-xs text-ink-400 bg-linen-100 rounded-lg p-3">
              {activeTemplates.find((t) => String(t.id) === templateId)?.question}
            </p>
          )}
        </div>
        {errorMsg && <p className="text-xs text-rust-500">Failed: {errorMsg}</p>}
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200">
            Cancel
          </button>
          <button
            onClick={() => onSubmit(ticketId, Number(templateId))}
            disabled={loading || !ticketId || !templateId}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
            <Send className="w-3 h-3" />
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
