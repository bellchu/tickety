"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { RouteRecommendation, ResolutionPlan } from "@/lib/types";
import { useParams } from "next/navigation";
import { AIThinkingStream } from "@/components/ticket/AIThinkingStream";
import { SentimentTag } from "@/components/engagement/SentimentTag";
import {
  ShieldCheck, AlertTriangle,
  ArrowLeft, ArrowUpRight, User, Tag, Flag, MessageSquare,
  CheckCircle2, Clock, Gauge, FileText, Users, RefreshCw, Wrench,
} from "lucide-react";
import { ReasoningLog } from "@/components/engagement/ReasoningLog";
import Link from "next/link";
import {
  priorityColor, statusColor, sentimentColor, complexityDots,
  formatTimeAgo, cn,
} from "@/lib/utils";

export default function TicketDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const { data: ticket, isLoading } = useQuery({
    queryKey: ["ticket", id],
    queryFn: () => api.getTicket(id),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-8 w-32" />
        <div className="card-surface p-6">
          <div className="skeleton h-6 w-2/3 mb-4" />
          <div className="skeleton h-4 w-full mb-2" />
          <div className="skeleton h-4 w-1/2" />
        </div>
      </div>
    );
  }

  if (!ticket) {
    return (
      <div className="card-surface p-12 text-center">
        <p className="text-slate-500">Ticket not found.</p>
        <Link href="/tickets" className="btn-secondary mt-4 inline-flex">
          Back to Tickets
        </Link>
      </div>
    );
  }

  const dots = complexityDots(ticket.complexity);

  return (
    <div className="space-y-5">
      <Link
        href="/tickets"
        className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Tickets
      </Link>

      {/* Main ticket card */}
      <div className="card-surface p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <span className={cn("badge", priorityColor(ticket.priority))}>
                {ticket.priority}
              </span>
              <span className={cn("badge", statusColor(ticket.status))}>
                {ticket.status}
              </span>
              <span className="flex items-center gap-1">
                {Array.from({ length: dots.filled }).map((_, i) => (
                  <span key={i} className="w-1 h-1 rounded-full bg-slate-400" />
                ))}
                {Array.from({ length: dots.empty }).map((_, i) => (
                  <span key={`e-${i}`} className="w-1 h-1 rounded-full bg-slate-200" />
                ))}
              </span>
            </div>
            <h1 className="text-lg font-bold text-slate-900">
              {ticket.subject}
            </h1>
            {ticket.external_url && (
              <a
                href={ticket.external_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-800 mt-2"
              >
                Open in Freshservice <ArrowUpRight className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>

        <p className="text-sm text-slate-600 whitespace-pre-wrap leading-relaxed">
          {ticket.description}
        </p>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-5 border-t border-slate-100">
          <InfoItem icon={<User className="w-3.5 h-3.5" />} label="Reporter" value={ticket.reporter || "—"} />
          <InfoItem icon={<Tag className="w-3.5 h-3.5" />} label="Category" value={ticket.category || "—"} />
          <div>
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-1">
              <Flag className="w-3.5 h-3.5" /> Sentiment
            </div>
            {ticket.sentiment ? (
              <span className={cn(
                "inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold border",
                sentimentColor(ticket.sentiment)
              )}>
                {ticket.sentiment}
              </span>
            ) : (
              <p className="text-sm text-slate-700">—</p>
            )}
          </div>
          <InfoItem icon={<Clock className="w-3.5 h-3.5" />} label="Created" value={formatTimeAgo(ticket.created_at)} />
        </div>

        <div className="flex items-center gap-3 mt-4">
          <span className="text-xs text-slate-400">Customer Mood:</span>
          <SentimentTag mood={ticket.mood} size="md" />
        </div>
      </div>

      <AIThinkingStream ticketId={ticket.id} hasExisting={!!ticket.ai_reasoning} />

      <IntelligencePanel
        ticketId={ticket.id}
        escalationRisk={ticket.escalation_risk ?? 0}
        summary={ticket.summary ?? null}
        autoFetch={!!ticket.ai_reasoning}
      />

      {ticket.ai_reasoning && <ReasoningLog text={ticket.ai_reasoning} />}

      {ticket.suggested_response && (
        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-3">
            <MessageSquare className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-900">Suggested Response</h3>
          </div>
          <p className="text-sm text-slate-700 whitespace-pre-wrap bg-slate-50 rounded p-4 border border-slate-100">
            {ticket.suggested_response}
          </p>
        </div>
      )}

      {ticket.points_awarded > 0 && (
        <div className="card-surface p-4 flex items-center gap-3">
          <div className="w-8 h-8 rounded border border-slate-200 flex items-center justify-center shrink-0">
            <CheckCircle2 className="w-4 h-4 text-slate-500" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900">
              +{ticket.points_awarded} Impact Points
            </p>
            <p className="text-xs text-slate-500">
              Resolved {formatTimeAgo(ticket.resolved_at)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function InfoItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-1">
        {icon} {label}
      </div>
      <p className="text-sm font-medium text-slate-700">{value}</p>
    </div>
  );
}

/* ── Intelligence panel ── */

function IntelligencePanel({
  ticketId, escalationRisk, summary, autoFetch,
}: {
  ticketId: string; escalationRisk: number; summary: string | null; autoFetch: boolean;
}) {
  const queryClient = useQueryClient();
  const [summaryText, setSummaryText] = useState<string | null>(summary);
  const [route, setRoute] = useState<RouteRecommendation | null>(null);
  const [plan, setPlan] = useState<ResolutionPlan | null>(null);

  // Auto-fetch all intelligence when the ticket is already processed
  useEffect(() => {
    if (autoFetch) {
      if (!summaryText) summaryMut.mutate();
      if (!route) routeMut.mutate();
      if (!plan && ticketId) resolveMut.mutate(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoFetch, ticketId]);

  const summaryMut = useMutation({
    mutationFn: () => api.generateTicketSummary(ticketId),
    onSuccess: (res) => {
      setSummaryText(res.summary);
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });
  const routeMut = useMutation({
    mutationFn: () => api.getIntelRoute(ticketId),
    onSuccess: (res) => setRoute(res),
  });
  const resolveMut = useMutation({
    mutationFn: (force: boolean) => api.getRecommendedSolution(ticketId, force),
    onSuccess: (res) => {
      setPlan(res.plan);
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });

  const riskTone = escalationRisk >= 70 ? "bg-red-400" : escalationRisk >= 40 ? "bg-amber-400" : "bg-slate-300";
  const riskLabel = escalationRisk >= 70 ? "High" : escalationRisk >= 40 ? "Medium" : "Low";

  return (
    <div className="card-surface p-6 space-y-5">
      <div className="flex items-center gap-2">
        <Gauge className="w-4 h-4 text-slate-600" />
        <h3 className="text-sm font-semibold text-slate-900">Intelligence</h3>
      </div>

      {/* Escalation risk */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-500 w-28">Escalation risk</span>
        <div className="flex items-center gap-2 flex-1">
          <div className="h-1.5 flex-1 rounded-full bg-slate-100 overflow-hidden">
            <div className={`h-full rounded-full ${riskTone}`} style={{ width: `${escalationRisk}%` }} />
          </div>
          <span className="text-xs font-semibold text-slate-600 w-14 text-right">
            {escalationRisk}/100
          </span>
        </div>
        <span className="text-xs text-slate-500">{riskLabel}</span>
      </div>

      {/* Summarization */}
      <Section
        label="Summarization"
        onClick={() => summaryMut.mutate()}
        loading={summaryMut.isPending}
        actionLabel={summaryText ? "Regenerate" : "Summarize"}
        icon={FileText}
      >
        {summaryText ? (
          <p className="text-sm text-slate-700 bg-slate-50 rounded p-3 border border-slate-100">{summaryText}</p>
        ) : (
          <p className="text-xs text-slate-400">No summary yet.</p>
        )}
      </Section>

      {/* Routing */}
      <Section
        label="Routing"
        onClick={() => routeMut.mutate()}
        loading={routeMut.isPending}
        actionLabel="Recommend engineer"
        icon={Users}
      >
        {route ? (
          <div className="space-y-1.5">
            {route.recommended_name ? (
              <p className="text-sm text-slate-700">
                Recommended: <span className="font-semibold">{route.recommended_name}</span>
                <span className="text-slate-500"> — {route.reasoning}</span>
              </p>
            ) : <p className="text-xs text-slate-400">No engineers available.</p>}
            <div className="flex flex-wrap gap-1.5">
              {route.candidates.map((c) => (
                <span key={c.user_id} className="text-xs px-2 py-1 rounded border border-slate-200 text-slate-600">
                  {c.name} · T{c.tier} · {c.score}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </Section>

      {/* Resolution */}
      <Section
        label="Recommended Solution"
        onClick={() => resolveMut.mutate(!!plan)}
        loading={resolveMut.isPending}
        actionLabel={plan ? "Regenerate" : "Resolve"}
        icon={Wrench}
      >
        {plan ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="px-2 py-0.5 rounded border border-slate-200 text-slate-600">
                confidence: <span className="font-semibold capitalize">{plan.confidence}</span>
              </span>
              <span className="px-2 py-0.5 rounded border border-slate-200 text-slate-600">
                effort: <span className="font-semibold capitalize">{plan.estimated_effort}</span>
              </span>
            </div>
            {plan.root_cause_hypothesis && (
              <div className="text-sm text-slate-700 bg-slate-50 rounded p-3 border border-slate-100">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Root cause hypothesis</span>
                <p className="mt-1">{plan.root_cause_hypothesis}</p>
              </div>
            )}
            {plan.resolution_steps.length > 0 && (
              <div className="bg-slate-50 rounded p-3 border border-slate-100">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Resolution steps</span>
                <ol className="mt-1 space-y-1.5">
                  {plan.resolution_steps.map((s, i) => (
                    <li key={i} className="flex gap-2 text-sm text-slate-700">
                      <span className="shrink-0 w-5 h-5 rounded-full bg-slate-200 text-slate-700 text-xs font-bold flex items-center justify-center">{i + 1}</span>
                      <span>{s}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {plan.escalation_advice && (
              <div className="flex items-start gap-2 text-sm text-slate-700 bg-slate-50 rounded p-3 border border-slate-200">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                <div>
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">If unresolved, escalate</span>
                  <p className="mt-0.5">{plan.escalation_advice}</p>
                </div>
              </div>
            )}
            {plan.preventive_note && (
              <div className="flex items-start gap-2 text-sm text-slate-600 bg-white rounded p-3 border border-slate-200">
                <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0 text-slate-500" />
                <div>
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Prevent recurrence</span>
                  <p className="mt-0.5">{plan.preventive_note}</p>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </Section>
    </div>
  );
}

function Section({
  label, onClick, loading, actionLabel, icon: Icon, children,
}: {
  label: string;
  onClick: () => void;
  loading: boolean;
  actionLabel: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">{label}</span>
        <button
          onClick={onClick}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          {loading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
          {actionLabel}
        </button>
      </div>
      {children}
    </div>
  );
}
