"use client";

import { useState, useEffect, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence } from "@/lib/auth";
import type { RouteRecommendation, ResolutionPlan, Ticket, TicketAnalysisResult, TicketAuditEntry, TicketComment, UserOut } from "@/lib/types";
import { useParams } from "next/navigation";
import { AIThinkingStream } from "@/components/ticket/AIThinkingStream";
import { SentimentTag } from "@/components/engagement/SentimentTag";
import {
  ShieldCheck, AlertTriangle,
  ArrowLeft, ArrowUpRight, User, Tag, Flag, MessageSquare,
  CheckCircle2, Clock, Gauge, FileText, Users, Wrench, Inbox,
} from "lucide-react";
import { ReasoningLog } from "@/components/engagement/ReasoningLog";
import Link from "next/link";
import {
  priorityColor, statusColor, sentimentColor, complexityDots,
  formatTimeAgo, cn,
} from "@/lib/utils";
import { Alert, Button, EmptyState, ErrorState, Skeleton } from "@/components/ui";

export default function TicketDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [latestAnalysis, setLatestAnalysis] = useState<TicketAnalysisResult | null>(null);
  const { data: ticket, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ["ticket", id],
    queryFn: () => api.getTicket(id),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="space-y-5" aria-busy="true" aria-label="Loading ticket workbench">
        <Skeleton className="h-9 w-36" />
        <div className="rounded-2xl border border-linen-400 bg-linen-50 p-6">
          <Skeleton className="mb-4 h-7 w-2/3" />
          <Skeleton className="mb-2 h-4 w-full" />
          <Skeleton className="h-4 w-1/2" />
        </div>
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <ErrorState
        title="Ticket could not be loaded"
        description="The workbench is unavailable, so no ticket data or actions are being shown."
        actionLabel="Retry ticket"
        onRetry={() => void refetch()}
        retrying={isFetching}
      />
    );
  }

  if (!ticket) {
    return (
      <EmptyState
        title="Ticket not found"
        description="This ticket may have been removed or the link may be incorrect."
        icon={<Inbox className="h-5 w-5" />}
        action={<Link href="/tickets" className="inline-flex min-h-10 items-center rounded-lg border border-linen-500 bg-linen-50 px-4 text-sm font-semibold text-ink-700 hover:bg-linen-200">Back to queue</Link>}
      />
    );
  }

  const dots = complexityDots(ticket.complexity);

  return (
    <div className="space-y-6">
      <Link
        href="/tickets"
        className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-xs font-semibold text-ink-500 hover:bg-linen-200 hover:text-ink-700"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Back to ticket queue
      </Link>

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm" aria-labelledby="ticket-title">
        <div className="border-b border-linen-300 bg-gradient-to-r from-linen-100 to-white px-5 py-6 sm:px-7">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-ink-400">
            <span className="font-mono font-semibold">{ticket.id}</span>
            {ticket.ticket_type && <span className="capitalize">· {ticket.ticket_type}</span>}
            <span>· Created {formatTimeAgo(ticket.created_at)}</span>
          </div>
          <div className="flex items-start justify-between gap-4">
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
                  <span key={i} className="w-1 h-1 rounded-full bg-linen-500" />
                ))}
                {Array.from({ length: dots.empty }).map((_, i) => (
                  <span key={`e-${i}`} className="w-1 h-1 rounded-full bg-linen-400" />
                ))}
              </span>
            </div>
            <h1 id="ticket-title" className="max-w-4xl text-2xl font-semibold tracking-[-0.025em] text-ink-700 sm:text-3xl">
              {ticket.subject}
            </h1>
            {ticket.external_url && (
              <a
                href={ticket.external_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex min-h-8 items-center gap-1 rounded-md text-xs font-semibold text-semantic-primary hover:underline"
              >
                View source record <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
        </div>

        <div className="px-5 py-6 sm:px-7">
          <p className="max-w-5xl whitespace-pre-wrap text-sm leading-7 text-ink-600">
            {ticket.description || "No description was provided for this ticket."}
          </p>

        <div className="mt-6 grid grid-cols-2 gap-4 border-t border-linen-300 pt-5 md:grid-cols-4">
          <InfoItem icon={<User className="w-3.5 h-3.5" />} label="Reporter" value={ticket.reporter || "—"} />
          <InfoItem icon={<Tag className="w-3.5 h-3.5" />} label="Category" value={ticket.category || "—"} />
          <div>
            <div className="flex items-center gap-1.5 text-[11px] text-ink-400 mb-1">
              <Flag className="w-3.5 h-3.5" /> Sentiment
            </div>
            {ticket.sentiment ? (
              <span className={cn(
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border",
                sentimentColor(ticket.sentiment)
              )}>
                {ticket.sentiment}
              </span>
            ) : (
              <p className="text-sm text-ink-600">—</p>
            )}
          </div>
          <InfoItem icon={<Clock className="w-3.5 h-3.5" />} label="Created" value={formatTimeAgo(ticket.created_at)} />
        </div>

        <div className="mt-5 flex items-center gap-3 rounded-xl bg-linen-100 px-4 py-3">
          <span className="text-xs text-ink-400">Customer Mood:</span>
          <SentimentTag mood={ticket.mood} size="md" />
        </div>
        </div>
      </section>

      <AgentActionPanel ticket={ticket} />

      <AIThinkingStream
        ticketId={ticket.id}
        hasExisting={!!ticket.ai_reasoning}
        onComplete={setLatestAnalysis}
      />

      <IntelligencePanel
        ticketId={ticket.id}
        escalationRisk={ticket.escalation_risk ?? 0}
        summary={ticket.summary ?? null}
        latestAnalysis={latestAnalysis}
        aiStatus={ticket.ai_status}
        aiModel={ticket.ai_model}
        aiGeneratedAt={ticket.ai_generated_at}
        aiSynthetic={ticket.ai_synthetic}
        aiSuggestedPriority={ticket.ai_suggested_priority}
      />

      {ticket.ai_reasoning && <ReasoningLog text={ticket.ai_reasoning} />}

      {ticket.suggested_response && (
        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-3">
            <MessageSquare className="w-4 h-4 text-ink-500" />
            <h3 className="text-sm font-semibold text-ink-700">Suggested Response</h3>
          </div>
          <p className="text-sm text-ink-600 whitespace-pre-wrap bg-linen-200 rounded p-4 border border-linen-300">
            {ticket.suggested_response}
          </p>
        </div>
      )}

      {ticket.points_awarded > 0 && (
        <div className="card-surface p-4 flex items-center gap-3">
          <div className="w-8 h-8 rounded border border-linen-400 flex items-center justify-center shrink-0">
            <CheckCircle2 className="w-4 h-4 text-ink-500" />
          </div>
          <div>
            <p className="text-sm font-semibold text-ink-700">
              +{ticket.points_awarded} Impact Points
            </p>
            <p className="text-xs text-ink-500">
              Resolved {formatTimeAgo(ticket.resolved_at)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function toDateTimeLocal(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function AgentActionPanel({ ticket }: { ticket: Ticket }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState(ticket.status || "New");
  const [priority, setPriority] = useState(ticket.priority || "P3");
  const [assigneeId, setAssigneeId] = useState(ticket.assignee_id || "");
  const [dueBy, setDueBy] = useState(toDateTimeLocal(ticket.due_by || ticket.resolution_due_at));
  const [tags, setTags] = useState(ticket.tags || "");
  const [comment, setComment] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [saveNotice, setSaveNotice] = useState<{ variant: "success" | "danger"; message: string } | null>(null);
  const [commentNotice, setCommentNotice] = useState<string | null>(null);

  useEffect(() => {
    setStatus(ticket.status || "New");
    setPriority(ticket.priority || "P3");
    setAssigneeId(ticket.assignee_id || "");
    setDueBy(toDateTimeLocal(ticket.due_by || ticket.resolution_due_at));
    setTags(ticket.tags || "");
  }, [ticket]);

  const meQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManageAssignment = canAccessProtectedIntelligence(meQuery.data);
  const usersQuery = useQuery<UserOut[]>({ queryKey: ["users"], queryFn: api.getUsers, enabled: canManageAssignment, retry: false });
  const commentsQuery = useQuery<TicketComment[]>({
    queryKey: ["ticket-comments", ticket.id],
    queryFn: () => api.getComments(ticket.id),
  });
  const auditQuery = useQuery<TicketAuditEntry[]>({
    queryKey: ["ticket-audit", ticket.id],
    queryFn: () => api.getAuditLog(ticket.id),
  });
  const users = usersQuery.data;
  const comments = commentsQuery.data;
  const audit = auditQuery.data;

  const saveMut = useMutation({
    mutationFn: () => api.updateTicket(ticket.id, {
      status,
      workflow_status: status,
      priority,
      assignee_id: assigneeId || null,
      due_by: dueBy ? new Date(dueBy).toISOString() : null,
      tags,
    }),
    onSuccess: () => {
      setSaveNotice({ variant: "success", message: "Ticket fields were saved and added to the audit trail." });
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticket-audit", ticket.id] });
    },
    onError: (error) => setSaveNotice({ variant: "danger", message: error instanceof Error ? error.message : "Ticket changes could not be saved." }),
  });

  const commentMut = useMutation({
    mutationFn: () => api.addComment(ticket.id, comment, isPrivate),
    onSuccess: () => {
      setComment("");
      setIsPrivate(false);
      setCommentNotice(isPrivate ? "Private note added." : "Public reply added.");
      void queryClient.invalidateQueries({ queryKey: ["ticket-comments", ticket.id] });
    },
    onError: (error) => setCommentNotice(error instanceof Error ? error.message : "The comment could not be added."),
  });

  return (
    <section className="space-y-6 rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-6" aria-labelledby="agent-work-title">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-semantic-primary">Workflow</p>
          <h2 id="agent-work-title" className="mt-1 text-lg font-semibold text-ink-700">Agent workbench</h2>
        </div>
        <Button
          onClick={() => saveMut.mutate()}
          pending={saveMut.isPending}
          pendingLabel="Saving…"
        >
          Save changes
        </Button>
      </div>

      {saveNotice && <Alert variant={saveNotice.variant} title={saveNotice.variant === "success" ? "Changes saved" : "Save failed"}>{saveNotice.message}</Alert>}

      <div className="grid grid-cols-1 gap-4 rounded-xl border border-linen-300 bg-linen-100 p-4 sm:grid-cols-2 xl:grid-cols-5">
        <label className="space-y-1">
          <span className="text-xs font-medium text-ink-500">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="input-base text-xs">
            {["New", "Open", "Awaiting Review", "Pending", "Escalated", "Resolved", "Closed"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs font-medium text-ink-500">Priority</span>
          <select value={priority} onChange={(e) => setPriority(e.target.value)} className="input-base text-xs">
            {["P1", "P2", "P3", "P4"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs font-medium text-ink-500">Assignee</span>
          <select value={assigneeId} disabled={!canManageAssignment || usersQuery.isError} onChange={(e) => setAssigneeId(e.target.value)} className="input-base text-xs">
            <option value="">{!canManageAssignment ? "Supervisor access required" : usersQuery.isError ? "Assignees unavailable" : "Unassigned"}</option>
            {(users || []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs font-medium text-ink-500">Due</span>
          <input type="datetime-local" value={dueBy} onChange={(e) => setDueBy(e.target.value)} className="input-base text-xs" />
        </label>
        <label className="space-y-1">
          <span className="text-xs font-medium text-ink-500">Tags</span>
          <input value={tags} onChange={(e) => setTags(e.target.value)} className="input-base text-xs" placeholder="vpn, vip" />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-ink-500">Conversation</span>
            <label className="inline-flex items-center gap-1.5 text-xs text-ink-500">
              <input type="checkbox" checked={isPrivate} onChange={(e) => setIsPrivate(e.target.checked)} />
              Private note
            </label>
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="input-base min-h-[88px] text-sm"
            placeholder="Add a public reply or internal note"
            maxLength={10_000}
          />
          <Button
            variant="secondary"
            onClick={() => commentMut.mutate()}
            disabled={!comment.trim()}
            pending={commentMut.isPending}
            pendingLabel="Posting…"
          >
            {isPrivate ? "Add private note" : "Post public reply"}
          </Button>
          {commentNotice && <p role="status" className="text-xs text-ink-500">{commentNotice}</p>}
          {commentsQuery.isLoading ? (
            <div className="space-y-2" aria-label="Loading conversation"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
          ) : commentsQuery.isError ? (
            <Alert variant="warning" title="Conversation unavailable" action={<Button size="sm" variant="secondary" onClick={() => void commentsQuery.refetch()}>Retry</Button>}>Existing replies are not being shown.</Alert>
          ) : comments?.length === 0 ? (
            <p className="rounded-xl border border-dashed border-linen-400 px-4 py-6 text-center text-xs text-ink-400">No conversation yet.</p>
          ) : <div className="max-h-72 space-y-2 overflow-auto pr-1">
            {(comments || []).map((c) => (
              <article key={c.id} className="rounded-xl border border-linen-300 bg-linen-100 p-3">
                <div className="flex items-center justify-between text-[11px] text-ink-400">
                  <span>{c.author_name}{c.is_private ? " - private" : ""}</span>
                  <span>{formatTimeAgo(c.created_at)}</span>
                </div>
                <p className="text-sm text-ink-600 mt-1 whitespace-pre-wrap">{c.body}</p>
              </article>
            ))}
          </div>}
        </div>
        <div className="space-y-3">
          <span className="text-xs font-medium text-ink-500">Audit trail</span>
          {auditQuery.isLoading ? (
            <div className="space-y-2" aria-label="Loading audit trail"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
          ) : auditQuery.isError ? (
            <Alert variant="warning" title="Audit trail unavailable" action={<Button size="sm" variant="secondary" onClick={() => void auditQuery.refetch()}>Retry</Button>}>Change history is not being shown.</Alert>
          ) : <div className="max-h-96 space-y-2 overflow-auto pr-1">
            {(audit || []).length === 0 ? (
              <p className="text-xs text-ink-400">No audit entries yet.</p>
            ) : (audit || []).map((a) => (
              <article key={a.id} className="rounded-xl border border-linen-300 bg-linen-100 p-3 text-xs">
                <div className="flex items-center justify-between text-ink-400">
                  <span>{a.changed_by}</span>
                  <span>{formatTimeAgo(a.changed_at)}</span>
                </div>
                <p className="mt-1 text-ink-600">
                  <span className="font-semibold">{a.field}</span>: {a.old_value || "-"} -&gt; {a.new_value || "-"}
                </p>
              </article>
            ))}
          </div>}
        </div>
      </div>
    </section>
  );
}

function InfoItem({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11px] text-ink-400 mb-1">
        {icon} {label}
      </div>
      <p className="text-sm font-medium text-ink-600">{value}</p>
    </div>
  );
}

/* ── Intelligence panel ── */

function IntelligencePanel({
  ticketId, escalationRisk, summary, latestAnalysis, aiStatus, aiModel, aiGeneratedAt, aiSynthetic, aiSuggestedPriority,
}: {
  ticketId: string;
  escalationRisk: number;
  summary: string | null;
  latestAnalysis: TicketAnalysisResult | null;
  aiStatus: string | null;
  aiModel: string | null;
  aiGeneratedAt: string | null;
  aiSynthetic: boolean;
  aiSuggestedPriority: string | null;
}) {
  const queryClient = useQueryClient();
  const [summaryText, setSummaryText] = useState<string | null>(summary);
  const [route, setRoute] = useState<RouteRecommendation | null>(null);
  const [plan, setPlan] = useState<ResolutionPlan | null>(null);

  useEffect(() => {
    setSummaryText(summary);
  }, [summary, ticketId]);

  useEffect(() => {
    if (!latestAnalysis || latestAnalysis.ticket_id !== ticketId) return;
    setSummaryText(latestAnalysis.summary);
    setRoute(latestAnalysis.route);
    setPlan(latestAnalysis.recommended_solution?.plan ?? null);
  }, [latestAnalysis, ticketId]);

  const summaryMut = useMutation({
    mutationFn: () => api.generateTicketSummary(ticketId, !!summaryText),
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

  const riskTone = escalationRisk >= 70 ? "bg-rust-400" : escalationRisk >= 40 ? "bg-amber-400" : "bg-linen-500";
  const riskLabel = escalationRisk >= 70 ? "High" : escalationRisk >= 40 ? "Medium" : "Low";

  return (
    <section className="space-y-6 rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-6" aria-labelledby="ticket-intelligence-title">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-semantic-primary"><Gauge className="h-5 w-5" aria-hidden="true" /></div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-semantic-primary">Decision support</p>
          <h2 id="ticket-intelligence-title" className="mt-1 text-lg font-semibold text-ink-700">Ticket intelligence</h2>
          <p className="mt-1 text-xs leading-5 text-ink-500">AI actions run only when requested. Review generated guidance before applying it.</p>
          {(aiStatus || aiModel || aiGeneratedAt) && (
            <p className="mt-2 text-[11px] text-ink-400">
              {aiStatus ? `Status: ${aiStatus.replaceAll("_", " ")}` : ""}
              {aiModel ? ` · Model: ${aiModel}` : ""}
              {aiSynthetic ? " · Synthetic demo result" : ""}
              {aiSuggestedPriority ? ` · Suggested priority: ${aiSuggestedPriority}` : ""}
              {aiGeneratedAt ? ` · Generated ${formatTimeAgo(aiGeneratedAt)}` : ""}
            </p>
          )}
        </div>
      </div>

      {/* Escalation risk */}
      <div className="flex flex-col gap-2 rounded-xl border border-linen-300 bg-linen-100 p-4 sm:flex-row sm:items-center sm:gap-3">
        <span className="text-xs text-ink-500 w-28">Escalation risk</span>
        <div className="flex items-center gap-2 flex-1">
          <div className="h-1.5 flex-1 rounded-full bg-linen-300 overflow-hidden">
            <div className={`h-full rounded-full ${riskTone}`} style={{ width: `${escalationRisk}%` }} />
          </div>
          <span className="text-xs font-semibold text-ink-600 w-14 text-right">
            {escalationRisk}/100
          </span>
        </div>
        <span className="text-xs text-ink-500">{riskLabel}</span>
      </div>

      {/* Summarization */}
      <Section
        label="Summarization"
        onClick={() => summaryMut.mutate()}
        loading={summaryMut.isPending}
        actionLabel={summaryText ? "Regenerate" : "Summarize"}
        icon={FileText}
        error={summaryMut.error}
      >
        {summaryText ? (
          <p className="text-sm text-ink-600 bg-linen-200 rounded p-3 border border-linen-300">{summaryText}</p>
        ) : (
          <p className="text-xs text-ink-400">No summary yet.</p>
        )}
      </Section>

      {/* Routing */}
      <Section
        label="Routing"
        onClick={() => routeMut.mutate()}
        loading={routeMut.isPending}
        actionLabel="Recommend engineer"
        icon={Users}
        error={routeMut.error}
      >
        {route ? (
          <div className="space-y-1.5">
            {route.recommended_name ? (
              <p className="text-sm text-ink-600">
                Recommended: <span className="font-semibold">{route.recommended_name}</span>
                {route.reasoning && <span className="text-ink-500"> — {route.reasoning}</span>}
              </p>
            ) : <p className="text-xs text-ink-400">No engineers available.</p>}
            {route.candidate_pool_truncated && <Alert variant="warning" title="Candidate pool is sampled" className="text-xs">Compared {route.analyzed_users.toLocaleString()} of {route.total_users.toLocaleString()} user profiles; the recommendation is not global.</Alert>}
            <div className="flex flex-wrap gap-1.5">
              {route.candidates.map((c) => (
                <span key={c.user_id} className="text-xs px-2 py-1 rounded border border-linen-400 text-ink-600">
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
        error={resolveMut.error}
      >
        {plan ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="px-2 py-0.5 rounded border border-linen-400 text-ink-600">
                confidence: <span className="font-semibold capitalize">{plan.confidence}</span>
              </span>
              <span className="px-2 py-0.5 rounded border border-linen-400 text-ink-600">
                effort: <span className="font-semibold capitalize">{plan.estimated_effort}</span>
              </span>
            </div>
            {plan.root_cause_hypothesis && (
              <div className="text-sm text-ink-600 bg-linen-200 rounded p-3 border border-linen-300">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Root cause hypothesis</span>
                <p className="mt-1">{plan.root_cause_hypothesis}</p>
              </div>
            )}
            {plan.resolution_steps.length > 0 && (
              <div className="bg-linen-200 rounded p-3 border border-linen-300">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Resolution steps</span>
                <ol className="mt-1 space-y-1.5">
                  {plan.resolution_steps.map((s, i) => (
                    <li key={i} className="flex gap-2 text-sm text-ink-600">
                      <span className="shrink-0 w-5 h-5 rounded-full bg-linen-400 text-ink-600 text-xs font-bold flex items-center justify-center">{i + 1}</span>
                      <span>{s}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {plan.escalation_advice && (
              <div className="flex items-start gap-2 text-sm text-ink-600 bg-linen-200 rounded p-3 border border-linen-400">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-rust-500" />
                <div>
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">If unresolved, escalate</span>
                  <p className="mt-0.5">{plan.escalation_advice}</p>
                </div>
              </div>
            )}
            {plan.preventive_note && (
              <div className="flex items-start gap-2 text-sm text-ink-600 bg-linen-50 rounded p-3 border border-linen-400">
                <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0 text-ink-500" />
                <div>
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Prevent recurrence</span>
                  <p className="mt-0.5">{plan.preventive_note}</p>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </Section>
    </section>
  );
}

function Section({
  label, onClick, loading, actionLabel, icon: Icon, error, children,
}: {
  label: string;
  onClick: () => void;
  loading: boolean;
  actionLabel: string;
  icon: React.ComponentType<{ className?: string }>;
  error?: Error | null;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-linen-300 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-sm font-semibold text-ink-700">{label}</span>
        <Button
          variant="secondary"
          size="sm"
          onClick={onClick}
          pending={loading}
          pendingLabel="Generating…"
          leadingIcon={<Icon className="h-3.5 w-3.5" />}
        >
          {actionLabel}
        </Button>
      </div>
      {error && <Alert variant="danger" title={`${label} failed`}>{error.message || "The AI request could not be completed."}</Alert>}
      {children}
    </div>
  );
}
