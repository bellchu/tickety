"use client";

import { useState, useEffect, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence } from "@/lib/auth";
import type { ResolutionPlan, Ticket, TicketAnalysisResult, TicketAuditEntry, TicketComment, UserOut } from "@/lib/types";
import { useParams } from "next/navigation";
import { AIThinkingStream } from "@/components/ticket/AIThinkingStream";
import {
  ArrowLeft, ArrowUpRight, User, Tag, Flag, MessageSquare,
  Gauge, Wrench, Inbox,
} from "lucide-react";
import Link from "next/link";
import {
  priorityColor, statusColor,
  formatTimeAgo, cn, safeExternalUrl,
} from "@/lib/utils";
import { Alert, Button, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { PageFrame } from "@/components/layout/PageLayout";
import { analysisLifecycleLabel, relatedStrength, routingLabel, sourceKindLabel } from "@/lib/ticket-intelligence";

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

  return (
    <PageFrame width="wide" className="max-w-[1280px] space-y-4 pb-8 sm:space-y-5">
      <Link
        href="/tickets"
        className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-xs font-semibold text-ink-500 hover:bg-linen-200 hover:text-ink-700"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Back to ticket queue
      </Link>

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm" aria-labelledby="ticket-title">
        <div className="bg-gradient-to-r from-linen-100 to-white px-5 py-5 sm:px-6">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-xs text-ink-400">
            <span className="font-mono font-semibold">#{ticket.external_id || ticket.id}</span>
            <span>· {sourceKindLabel(ticket)}</span>
            <span>· Created {formatTimeAgo(ticket.created_at)}</span>
            <span className={cn("badge ml-1", priorityColor(ticket.priority))}>
              {ticket.priority}
            </span>
            <span className={cn("badge", statusColor(ticket.status))}>
              {ticket.status}
            </span>
          </div>
          <h1 id="ticket-title" title={ticket.subject} className="mt-3 max-w-5xl truncate text-2xl font-semibold tracking-[-0.025em] text-ink-700 sm:text-3xl">
            {ticket.subject}
          </h1>
        </div>
      </section>

      <TicketBriefPanel
        ticket={ticket}
        latestAnalysis={latestAnalysis}
        analysisControl={
          <AIThinkingStream
            compact
            ticketId={ticket.id}
            hasExisting={Boolean(ticket.ai_reasoning || ticket.ai_status || ticket.ai_generated_at)}
            onComplete={setLatestAnalysis}
          />
        }
      />

      {ticket.external_source === "freshservice" ? (
        <FreshserviceSourcePanel ticket={ticket} />
      ) : (
        <AgentActionPanel ticket={ticket} />
      )}

    </PageFrame>
  );
}

function FreshserviceSourcePanel({ ticket }: { ticket: Ticket }) {
  const sourceUrl = safeExternalUrl(ticket.external_url);
  return (
    <details className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5">
      <summary className="cursor-pointer list-none" aria-labelledby="source-record-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-semantic-primary">System of record</p>
            <h2 id="source-record-title" className="text-base font-semibold text-ink-700">Freshservice · read only</h2>
          </div>
          <p className="mt-1 text-xs leading-5 text-ink-500">
            Replies, notes, attachments, and source fields are managed in Freshservice.
          </p>
        </div>
      </div>
      </summary>
      <div className="mt-4 border-t border-linen-300 pt-4">
        {sourceUrl && <div className="mb-4 flex justify-end"><a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-linen-400 bg-white px-3 text-xs font-semibold text-ink-700 hover:bg-linen-200">Open in Freshservice <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" /></a></div>}
        <p className="max-w-5xl whitespace-pre-wrap text-sm leading-6 text-ink-600">{ticket.description || "No description was provided for this ticket."}</p>
        <div className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
          <InfoItem icon={<User className="h-3.5 w-3.5" />} label="Reporter"><span className="break-all">{ticket.reporter || "—"}</span></InfoItem>
          <InfoItem icon={<Tag className="h-3.5 w-3.5" />} label="Source category">{ticket.category || "—"}</InfoItem>
          <InfoItem icon={<Flag className="h-3.5 w-3.5" />} label="Source status">{ticket.external_status || ticket.status}</InfoItem>
        </div>
      </div>
      <dl className="mt-4 grid divide-y divide-linen-300 overflow-hidden rounded-xl border border-linen-300 bg-linen-100 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="px-3 py-2.5"><dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Freshservice ID</dt><dd className="mt-0.5 font-mono text-sm font-medium text-ink-700">{ticket.external_id || "—"}</dd></div>
        <div className="px-3 py-2.5"><dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Tickety owner</dt><dd className="mt-0.5 text-sm font-medium text-ink-700">{ticket.assignee_name || "Unassigned"}</dd></div>
        <div className="px-3 py-2.5"><dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">ITSM assignee</dt><dd className="mt-0.5 text-sm font-medium text-ink-700">{ticket.external_assignee_name || ticket.external_assignee_id || "Unassigned"}</dd></div>
      </dl>
    </details>
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

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem] xl:items-start">
        <div className="min-w-0 space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold text-ink-700">Conversation</h3>
              <p className="mt-1 text-xs text-ink-500">Reply to the requester or add an internal note.</p>
            </div>
            <label className="inline-flex items-center gap-1.5 text-xs text-ink-500">
              <input type="checkbox" checked={isPrivate} onChange={(e) => setIsPrivate(e.target.checked)} />
              Private note
            </label>
          </div>
          {ticket.suggested_response && (
            <details className="rounded-xl border border-clay-200 bg-[var(--color-primary-soft)] p-4">
              <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold text-ink-700">
                <MessageSquare className="h-4 w-4 text-semantic-primary" aria-hidden="true" />
                Suggested response
              </summary>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink-600">{ticket.suggested_response}</p>
              <Button className="mt-3" size="sm" variant="secondary" onClick={() => setComment(ticket.suggested_response || "")}>Use in composer</Button>
            </details>
          )}
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
          ) : <div className="max-h-[28rem] space-y-2 overflow-auto pr-1">
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
          <details className="rounded-xl border border-linen-400 bg-linen-100 p-4">
            <summary className="cursor-pointer text-sm font-semibold text-ink-700">Audit trail{audit?.length ? ` (${audit.length})` : ""}</summary>
            <div className="mt-4">
              {auditQuery.isLoading ? (
                <div className="space-y-2" aria-label="Loading audit trail"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
              ) : auditQuery.isError ? (
                <Alert variant="warning" title="Audit trail unavailable" action={<Button size="sm" variant="secondary" onClick={() => void auditQuery.refetch()}>Retry</Button>}>Change history is not being shown.</Alert>
              ) : <div className="max-h-96 space-y-2 overflow-auto pr-1">
                {(audit || []).length === 0 ? (
                  <p className="text-xs text-ink-400">No audit entries yet.</p>
                ) : (audit || []).map((a) => (
                  <article key={a.id} className="rounded-xl border border-linen-300 bg-linen-50 p-3 text-xs">
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
          </details>
        </div>

        <aside className="rounded-xl border border-linen-300 bg-linen-100 p-4 xl:sticky xl:top-24" aria-label="Ticket properties">
          <div className="mb-4">
            <h3 className="text-sm font-semibold text-ink-700">Properties</h3>
            <p className="mt-1 text-xs text-ink-500">Status, ownership, timing, and classification.</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <label className="space-y-1">
              <span className="text-xs font-medium text-ink-500">Status</span>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className="input-base text-xs">
                {["New", "Open", "Awaiting Review", "Pending", "Escalated", "Resolved", "Closed"].map((s) => <option key={s} value={s}>{s}</option>)}
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
            <label className="space-y-1 sm:col-span-2 xl:col-span-1">
              <span className="text-xs font-medium text-ink-500">Tags</span>
              <input value={tags} onChange={(e) => setTags(e.target.value)} className="input-base text-xs" placeholder="vpn, vip" />
            </label>
          </div>
        </aside>
      </div>
    </section>
  );
}

function InfoItem({
  icon, label, children, className,
}: {
  icon: ReactNode;
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="mb-1 flex items-center gap-1.5 text-[11px] text-ink-400">
        {icon} {label}
      </div>
      <div className="text-sm font-medium text-ink-600">{children}</div>
    </div>
  );
}

/* ── Intelligence panel ── */

function parseResolutionPlan(value: string | null): ResolutionPlan | null {
  if (!value) return null;
  try {
    const candidate = JSON.parse(value) as Partial<ResolutionPlan>;
    if (!candidate || typeof candidate !== "object" || !Array.isArray(candidate.resolution_steps)) return null;
    return {
      root_cause_hypothesis: typeof candidate.root_cause_hypothesis === "string" ? candidate.root_cause_hypothesis : "",
      resolution_steps: candidate.resolution_steps.filter((step): step is string => typeof step === "string"),
      confidence: ["high", "medium", "low"].includes(candidate.confidence || "") ? candidate.confidence as ResolutionPlan["confidence"] : "medium",
      estimated_effort: ["high", "medium", "low"].includes(candidate.estimated_effort || "") ? candidate.estimated_effort as ResolutionPlan["estimated_effort"] : "medium",
      escalation_advice: typeof candidate.escalation_advice === "string" ? candidate.escalation_advice : "",
      preventive_note: typeof candidate.preventive_note === "string" ? candidate.preventive_note : "",
    };
  } catch {
    return null;
  }
}

function TicketBriefPanel({
  ticket,
  latestAnalysis,
  analysisControl,
}: {
  ticket: Ticket;
  latestAnalysis: TicketAnalysisResult | null;
  analysisControl: ReactNode;
}) {
  const queryClient = useQueryClient();
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [plan, setPlan] = useState<ResolutionPlan | null>(() => parseResolutionPlan(ticket.recommended_solution));
  const relatedQuery = useQuery({
    queryKey: ["ticket-related", ticket.id],
    queryFn: () => api.getRelatedTickets(ticket.id, 5),
    retry: false,
  });

  useEffect(() => {
    setPlan(parseResolutionPlan(ticket.recommended_solution));
  }, [ticket.id, ticket.recommended_solution]);

  useEffect(() => {
    if (latestAnalysis?.ticket_id === ticket.id) {
      setPlan(latestAnalysis.recommended_solution?.plan ?? null);
      void queryClient.invalidateQueries({ queryKey: ["ticket-related", ticket.id] });
    }
  }, [latestAnalysis, queryClient, ticket.id]);

  const resolveMut = useMutation({
    mutationFn: () => api.getRecommendedSolution(ticket.id, Boolean(plan)),
    onSuccess: (result) => {
      setPlan(result.plan);
      void queryClient.invalidateQueries({ queryKey: ["ticket", ticket.id] });
    },
  });

  const summary = latestAnalysis?.ticket_id === ticket.id
    ? latestAnalysis.summary || ticket.summary
    : ticket.summary;
  const issueType = latestAnalysis?.ticket_id === ticket.id
    ? latestAnalysis.triage.category
    : ticket.ai_suggested_category;
  const suggestedPriority = latestAnalysis?.ticket_id === ticket.id
    ? latestAnalysis.triage.priority
    : ticket.ai_suggested_priority;
  const risk = Math.min(100, Math.max(0, ticket.escalation_risk || 0));
  const riskLabel = risk >= 70 ? "High" : risk >= 40 ? "Medium" : "Low";
  const lifecycle = analysisLifecycleLabel(ticket);
  const detailOpen = ["partial", "failed", "dead_letter"].includes(ticket.ai_status || "");

  return (
    <section className="space-y-4 rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5" aria-labelledby="ticket-brief-title">
      <div className="flex items-start gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-soft)] text-semantic-primary"><Gauge className="h-[18px] w-[18px]" aria-hidden="true" /></div>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-semantic-primary">Decision support</p>
          <h2 id="ticket-brief-title" className="mt-0.5 text-lg font-semibold text-ink-700">AI ticket brief</h2>
          <p className="mt-0.5 text-xs text-ink-500">Review generated guidance before applying it.</p>
        </div>
      </div>

      <div className="rounded-xl border border-linen-300 bg-linen-100 p-4">
        <p className={cn("whitespace-pre-wrap text-sm leading-6 text-ink-600", !summaryExpanded && "line-clamp-3")}>
          {summary || "No generated summary is available yet."}
        </p>
        {summary && summary.length > 220 && (
          <button type="button" className="mt-2 text-xs font-semibold text-semantic-primary hover:underline" onClick={() => setSummaryExpanded((expanded) => !expanded)} aria-expanded={summaryExpanded}>
            {summaryExpanded ? "Show less" : "Expand summary"}
          </button>
        )}
      </div>

      <dl className="grid overflow-hidden rounded-xl border border-linen-300 bg-white sm:grid-cols-2 xl:grid-cols-5">
        <DecisionItem label="Issue" value={issueType || "Not available"} />
        <DecisionItem label="Suggested priority" value={suggestedPriority || "Not available"} />
        <DecisionItem label="Routing" value={routingLabel(ticket)} />
        <DecisionItem label="Escalation risk" value={`${risk}/100 · ${riskLabel}`} />
        <DecisionItem label="Analysis" value={ticket.ai_generated_at ? `${lifecycle} · ${formatTimeAgo(ticket.ai_generated_at)}` : lifecycle} />
      </dl>

      {analysisControl}

      <div className="border-t border-linen-300 pt-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink-700">Related tickets</h3>
            <p className="mt-0.5 text-xs text-ink-500">Advisory similarity only; source records remain authoritative.</p>
          </div>
          {relatedQuery.isError && <Button size="sm" variant="secondary" onClick={() => void relatedQuery.refetch()} pending={relatedQuery.isFetching}>Retry</Button>}
        </div>
        {relatedQuery.isLoading ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>
        ) : relatedQuery.isError ? (
          <p className="mt-3 text-xs text-ink-400">Related tickets are unavailable right now.</p>
        ) : !relatedQuery.data?.items.length ? (
          <p className="mt-3 text-xs text-ink-400">No related tickets found.</p>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {relatedQuery.data.items.map((related) => (
              <Link key={related.ticket_id} href={`/tickets/${related.ticket_id}`} className="min-w-0 rounded-lg border border-linen-300 bg-white px-3 py-2.5 transition-colors hover:border-linen-500 hover:bg-linen-100">
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <span className="truncate text-xs font-semibold text-ink-700">{related.subject}</span>
                  <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-ink-400">{relatedStrength(related.score, related.match_method)}</span>
                </div>
                <p className="mt-1 truncate text-[11px] text-ink-400">{related.priority} · {related.status}{related.category ? ` · ${related.category}` : ""}</p>
              </Link>
            ))}
          </div>
        )}
      </div>

      <details key={`${ticket.id}-${detailOpen}`} open={detailOpen || undefined} className="border-t border-linen-300 pt-4">
        <summary className="cursor-pointer text-sm font-semibold text-ink-700">Technical details</summary>
        <div className="mt-3 space-y-4 text-xs text-ink-500">
          <dl className="grid gap-3 sm:grid-cols-3">
            <div><dt className="text-ink-400">Model</dt><dd className="mt-1 break-all font-medium text-ink-600">{ticket.ai_model || "Not available"}</dd></div>
            <div><dt className="text-ink-400">Lifecycle</dt><dd className="mt-1 font-medium text-ink-600">{lifecycle}</dd></div>
            <div><dt className="text-ink-400">Generated</dt><dd className="mt-1 font-medium text-ink-600">{ticket.ai_generated_at ? formatTimeAgo(ticket.ai_generated_at) : "Not available"}</dd></div>
          </dl>
          {ticket.ai_reasoning && <div><p className="font-semibold text-ink-600">Reasoning</p><p className="mt-1 whitespace-pre-wrap leading-5">{ticket.ai_reasoning}</p></div>}
          <div>
            <div className="flex items-center justify-between gap-3"><p className="font-semibold text-ink-600">Recommended solution</p><Button size="sm" variant="secondary" onClick={() => resolveMut.mutate()} pending={resolveMut.isPending} pendingLabel="Generating…" leadingIcon={<Wrench className="h-3.5 w-3.5" />}>{plan ? "Regenerate" : "Generate"}</Button></div>
            {resolveMut.isError && <Alert className="mt-2" variant="danger" title="Solution generation failed">{resolveMut.error.message}</Alert>}
            {plan ? <ResolutionDetails plan={plan} /> : <p className="mt-2 text-ink-400">No generated solution is available.</p>}
          </div>
        </div>
      </details>
    </section>
  );
}

function DecisionItem({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 border-b border-linen-300 px-3 py-3 last:border-b-0 sm:[&:nth-last-child(-n+1)]:border-b-0 sm:border-r sm:[&:nth-child(2n)]:border-r-0 xl:border-b-0 xl:[&:nth-child(2n)]:border-r xl:last:border-r-0"><dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{label}</dt><dd className="mt-1 break-words text-xs font-semibold leading-4 text-ink-700">{value}</dd></div>;
}

function ResolutionDetails({ plan }: { plan: ResolutionPlan }) {
  return (
    <div className="mt-3 space-y-3 rounded-lg border border-linen-300 bg-linen-100 p-3">
      {plan.root_cause_hypothesis && <p><span className="font-semibold text-ink-600">Root cause: </span>{plan.root_cause_hypothesis}</p>}
      {plan.resolution_steps.length > 0 && <ol className="list-decimal space-y-1 pl-4">{plan.resolution_steps.map((step, index) => <li key={index}>{step}</li>)}</ol>}
      {plan.escalation_advice && <p><span className="font-semibold text-ink-600">Escalation: </span>{plan.escalation_advice}</p>}
      {plan.preventive_note && <p><span className="font-semibold text-ink-600">Prevention: </span>{plan.preventive_note}</p>}
    </div>
  );
}
