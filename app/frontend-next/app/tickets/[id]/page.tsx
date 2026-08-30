"use client";

import { useState, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence, canCreateTickets } from "@/lib/auth";
import type { ResolutionPlan, Ticket, TicketAnalysisResult, TicketAuditEntry, TicketComment } from "@/lib/types";
import { useParams } from "next/navigation";
import { AIThinkingStream } from "@/components/ticket/AIThinkingStream";
import { FreshserviceConversationThread } from "@/components/ticket/FreshserviceConversationThread";
import { TicketSentimentSubtitle } from "@/components/ticket/TicketSentimentSubtitle";
import { TicketSignalStrip } from "@/components/ticket/TicketSignalStrip";
import {
  ArrowLeft, ArrowUpRight, BriefcaseBusiness, CalendarDays, Clock3, User, Tag, Flag, Mail, MessageSquare,
  Gauge, Wrench, Inbox,
} from "lucide-react";
import Link from "next/link";
import {
  priorityColor, statusColor,
  formatTimeAgo, cn, safeExternalUrl,
} from "@/lib/utils";
import { Alert, Button, EmptyState, ErrorState, ListText, Skeleton } from "@/components/ui";
import { PageFrame } from "@/components/layout/PageLayout";
import { analysisLifecycleLabel, relatedStrength, routingLabel, sourceKindLabel, ticketSignalRatings } from "@/lib/ticket-intelligence";
import { persistedAnalysisErrorDetails } from "@/lib/analysis-errors";
import { toLocalDateTimeInput } from "@/lib/date-time";
import {
  preserveTicketConfigValue,
  ticketPriorityOptions,
  ticketStatusOptions,
} from "@/lib/ticket-config-options";
import {
  formatOperationalTimestamp,
  requesterEmail,
  requesterName,
  safeMailto,
  ticketCreatedAt,
  ticketLastCommunicationAt,
} from "@/lib/ticket-display";

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
        action={<Link href="/tickets" className="inline-flex min-h-10 items-center rounded-lg border border-linen-500 bg-linen-50 px-4 text-sm font-semibold text-ink-700 hover:bg-linen-200">Back to All Tickets</Link>}
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
        Back to All Tickets
      </Link>

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm" aria-labelledby="ticket-title">
        <div className="bg-gradient-to-r from-linen-100 to-white px-5 py-5 sm:px-6">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-xs text-ink-400">
            <span className="font-mono font-semibold">#{ticket.external_id || ticket.id}</span>
            <span>· {sourceKindLabel(ticket)}</span>
            <time dateTime={ticketCreatedAt(ticket) || undefined} title={formatOperationalTimestamp(ticketCreatedAt(ticket))}>· Created {formatTimeAgo(ticketCreatedAt(ticket))}</time>
            <time dateTime={ticketLastCommunicationAt(ticket) || undefined} title={formatOperationalTimestamp(ticketLastCommunicationAt(ticket))}>· Last contact {formatTimeAgo(ticketLastCommunicationAt(ticket))}</time>
            <span className={cn("badge ml-1", priorityColor(ticket.priority))} title="Requester-reported priority">
              Reported {ticket.priority}
            </span>
            <span className={cn("badge", statusColor(ticket.status))}>
              {ticket.status}
            </span>
          </div>
          <h1 id="ticket-title" title={ticket.subject} className="mt-3 max-w-5xl break-words text-2xl font-semibold tracking-[-0.025em] text-ink-700 [overflow-wrap:anywhere] sm:text-3xl">
            {ticket.subject}
          </h1>
          <TicketSentimentSubtitle ticket={ticket} latestAnalysis={latestAnalysis} />
          <TicketSignalStrip
            ratings={ticketSignalRatings(ticket, latestAnalysis)}
            reasoning={latestAnalysis?.ticket_id === ticket.id ? latestAnalysis.triage.reasoning : ticket.ai_reasoning}
          />
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
            recoveryState={ticket.ai_status}
            onComplete={setLatestAnalysis}
          />
        }
      />

      {ticket.external_source === "freshservice" ? (
        <>
          <FreshserviceConversationThread ticket={ticket} />
          <FreshserviceSourcePanel ticket={ticket} />
        </>
      ) : (
        <InternalTicketPanel ticket={ticket} />
      )}

    </PageFrame>
  );
}

function InternalTicketPanel({ ticket }: { ticket: Ticket }) {
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canEditInternalTicket = !authQuery.isError && canCreateTickets(authQuery.data);

  return canEditInternalTicket ? (
    <AgentActionPanel ticket={ticket} />
  ) : (
    <InternalTicketReadOnlyPanel ticket={ticket} accessPending={authQuery.isLoading} />
  );
}

function InternalTicketReadOnlyPanel({ ticket, accessPending }: { ticket: Ticket; accessPending: boolean }) {
  return (
    <section className="space-y-5 rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-6" aria-labelledby="internal-ticket-read-only-title">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-semantic-primary">Workflow</p>
        <h2 id="internal-ticket-read-only-title" className="mt-1 text-lg font-semibold text-ink-700">Internal ticket · Read only</h2>
        <p className="mt-1 text-xs leading-5 text-ink-500">
          {accessPending
            ? "Edit access is being checked. Ticket details remain available while you wait."
            : "Editing and comments are available only to an authenticated administrator in the demo environment."}
        </p>
      </div>

      <div className="rounded-xl border border-linen-300 bg-linen-100 p-4">
        <h3 className="text-sm font-semibold text-ink-700">Description</h3>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-ink-600 [overflow-wrap:anywhere]">
          {ticket.description || "No description was provided."}
        </p>
      </div>

      <div className="grid gap-4 rounded-xl border border-linen-300 bg-white p-4 sm:grid-cols-2 lg:grid-cols-3">
        <InfoItem icon={<Flag className="h-3.5 w-3.5" />} label="Status">{ticket.status || "—"}</InfoItem>
        <InfoItem icon={<Gauge className="h-3.5 w-3.5" />} label="Priority">{ticket.priority || "—"}</InfoItem>
        <InfoItem icon={<User className="h-3.5 w-3.5" />} label="Assignee">{ticket.assignee_name || "Unassigned"}</InfoItem>
        <InfoItem icon={<CalendarDays className="h-3.5 w-3.5" />} label="Due">{formatOperationalTimestamp(ticket.due_by || ticket.resolution_due_at)}</InfoItem>
        <InfoItem icon={<Tag className="h-3.5 w-3.5" />} label="Tags">{ticket.tags || "—"}</InfoItem>
        <InfoItem icon={<Mail className="h-3.5 w-3.5" />} label="Reporter">{ticket.reporter || "—"}</InfoItem>
      </div>
    </section>
  );
}

function FreshserviceSourcePanel({ ticket }: { ticket: Ticket }) {
  const sourceUrl = safeExternalUrl(ticket.external_url);
  const email = requesterEmail(ticket);
  const emailHref = safeMailto(email);
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
        <div className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <InfoItem icon={<User className="h-3.5 w-3.5" />} label="Requester">{requesterName(ticket)}</InfoItem>
          <InfoItem icon={<Mail className="h-3.5 w-3.5" />} label="Email">{emailHref ? <a href={emailHref} className="break-all text-semantic-primary hover:underline">{email}</a> : <span className="text-ink-400">Not provided</span>}</InfoItem>
          <InfoItem icon={<BriefcaseBusiness className="h-3.5 w-3.5" />} label="Title">{ticket.requester_title || <span className="text-ink-400">Not provided by Freshservice</span>}</InfoItem>
          <InfoItem icon={<Tag className="h-3.5 w-3.5" />} label="Source category">{ticket.category || "—"}</InfoItem>
          <InfoItem icon={<Flag className="h-3.5 w-3.5" />} label="Source status">{ticket.external_status || ticket.status}</InfoItem>
          <InfoItem icon={<CalendarDays className="h-3.5 w-3.5" />} label="Created">{formatOperationalTimestamp(ticketCreatedAt(ticket))}</InfoItem>
          <InfoItem icon={<Clock3 className="h-3.5 w-3.5" />} label="Last communication">{formatOperationalTimestamp(ticketLastCommunicationAt(ticket))}</InfoItem>
        </div>
      </div>
      <dl className="mt-4 grid divide-y divide-linen-300 overflow-hidden rounded-xl border border-linen-300 bg-linen-100 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="px-3 py-2.5"><dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Freshservice ID</dt><dd className="mt-0.5 font-mono text-sm font-medium text-ink-700">{ticket.external_id || "—"}</dd></div>
        <div className="px-3 py-2.5"><dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Tickety OPS Tower owner</dt><dd className="mt-0.5 text-sm font-medium text-ink-700">{ticket.assignee_name || "Unassigned"}</dd></div>
        <div className="px-3 py-2.5"><dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">ITSM assignee</dt><dd className="mt-0.5 text-sm font-medium text-ink-700">{ticket.external_assignee_name || ticket.external_assignee_id || "Unassigned"}</dd></div>
      </dl>
    </details>
  );
}

function AgentActionPanel({ ticket }: { ticket: Ticket }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState(ticket.status || "New");
  const [priority, setPriority] = useState(ticket.priority || "P3");
  const [assigneeId, setAssigneeId] = useState(ticket.assignee_id || "");
  const [dueBy, setDueBy] = useState(toLocalDateTimeInput(ticket.due_by || ticket.resolution_due_at));
  const [tags, setTags] = useState(ticket.tags || "");
  const [comment, setComment] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [saveNotice, setSaveNotice] = useState<{ variant: "success" | "danger"; message: string } | null>(null);
  const [commentNotice, setCommentNotice] = useState<string | null>(null);

  useEffect(() => {
    setStatus(ticket.status || "New");
    setPriority(ticket.priority || "P3");
    setAssigneeId(ticket.assignee_id || "");
    setDueBy(toLocalDateTimeInput(ticket.due_by || ticket.resolution_due_at));
    setTags(ticket.tags || "");
  }, [ticket]);

  const meQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManageAssignment = canAccessProtectedIntelligence(meQuery.data);
  const usersQuery = useQuery({ queryKey: ["users", "ticket-detail-options"], queryFn: () => api.getUsersPage({ limit: 200 }), enabled: canManageAssignment, retry: false });
  const statusConfigQuery = useQuery({ queryKey: ["status-config"], queryFn: api.getStatusConfig, retry: false });
  const priorityConfigQuery = useQuery({ queryKey: ["priority-config"], queryFn: api.getPriorityConfig, retry: false });
  const commentsQuery = useQuery<TicketComment[]>({
    queryKey: ["ticket-comments", ticket.id],
    queryFn: () => api.getComments(ticket.id),
  });
  const auditQuery = useQuery<TicketAuditEntry[]>({
    queryKey: ["ticket-audit", ticket.id],
    queryFn: () => api.getAuditLog(ticket.id),
  });
  const users = usersQuery.data?.users;
  const comments = commentsQuery.data;
  const audit = auditQuery.data;
  const configuredStatusOptions = useMemo(
    () => ticketStatusOptions(statusConfigQuery.isError ? undefined : statusConfigQuery.data),
    [statusConfigQuery.data, statusConfigQuery.isError],
  );
  const configuredPriorityOptions = useMemo(
    () => ticketPriorityOptions(priorityConfigQuery.isError ? undefined : priorityConfigQuery.data),
    [priorityConfigQuery.data, priorityConfigQuery.isError],
  );
  const statusOptions = useMemo(
    () => preserveTicketConfigValue(configuredStatusOptions, status),
    [configuredStatusOptions, status],
  );
  const priorityOptions = useMemo(
    () => preserveTicketConfigValue(configuredPriorityOptions, priority),
    [configuredPriorityOptions, priority],
  );

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
          <label htmlFor="ticket-comment-composer" className="block text-xs font-medium text-ink-500">
            {isPrivate ? "Private note" : "Public reply"}
          </label>
          <textarea
            id="ticket-comment-composer"
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
          {(statusConfigQuery.isError || priorityConfigQuery.isError) && (
            <p role="status" className="mb-4 rounded-lg border border-linen-400 bg-white px-3 py-2 text-xs leading-5 text-ink-500">
              Custom status or priority choices are temporarily unavailable. Default choices remain available, and the workbench can still be used.
            </p>
          )}
          {usersQuery.data?.hasMore && <p role="status" className="mb-4 rounded-lg border border-linen-400 bg-white px-3 py-2 text-xs leading-5 text-ink-500">The directory has more than 200 accounts. The current assignee remains visible, but only the first 200 directory choices are available here.</p>}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <label className="space-y-1">
              <span className="text-xs font-medium text-ink-500">Status</span>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className="input-base text-xs">
                {statusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs font-medium text-ink-500">Priority</span>
              <select value={priority} onChange={(e) => setPriority(e.target.value)} className="input-base text-xs">
                {priorityOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs font-medium text-ink-500">Assignee</span>
              <select value={assigneeId} disabled={!canManageAssignment || usersQuery.isError} onChange={(e) => setAssigneeId(e.target.value)} className="input-base text-xs">
                <option value="">{!canManageAssignment ? "Supervisor access required" : usersQuery.isError ? "Assignees unavailable" : "Unassigned"}</option>
                {ticket.assignee_id && !(users || []).some((user) => user.id === ticket.assignee_id) && <option value={ticket.assignee_id}>{ticket.assignee_name || ticket.assignee_id} (current)</option>}
                {(users || []).filter((user) => user.is_active || user.id === ticket.assignee_id).map((user) => <option key={user.id} value={user.id}>{user.name}{user.is_active ? "" : " (deactivated)"}</option>)}
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
  const priorityRating = ticketSignalRatings(ticket, latestAnalysis)[0];
  const risk = Math.min(100, Math.max(0, ticket.escalation_risk || 0));
  const riskLabel = risk >= 70 ? "High" : risk >= 40 ? "Medium" : "Low";
  const lifecycle = analysisLifecycleLabel(ticket);
  const failureDetail = persistedAnalysisErrorDetails(ticket.ai_error);
  const detailOpen = Boolean(failureDetail) || ["partial", "failed", "dead_letter"].includes(ticket.ai_status || "");

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
        <DecisionItem label="Content priority" value={priorityRating.score === null ? "Analysis pending" : priorityRating.displayValue} />
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
                  <ListText text={related.subject} lines={2} className="min-w-0 text-xs font-semibold text-ink-700" />
                  <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-ink-400">{relatedStrength(related.score, related.match_method)}</span>
                </div>
                <ListText text={`${related.priority} · ${related.status}${related.category ? ` · ${related.category}` : ""}`} lines={2} className="mt-1 text-[11px] text-ink-400" />
              </Link>
            ))}
          </div>
        )}
      </div>

      <details key={`${ticket.id}-${detailOpen}`} open={detailOpen || undefined} className="border-t border-linen-300 pt-4">
        <summary className="cursor-pointer text-sm font-semibold text-ink-700">Technical details</summary>
        <div className="mt-3 space-y-4 text-xs text-ink-500">
          <dl className="grid gap-3 sm:grid-cols-3 xl:grid-cols-4">
            <div><dt className="text-ink-400">Model</dt><dd className="mt-1 break-all font-medium text-ink-600">{ticket.ai_model || "Not available"}</dd></div>
            <div><dt className="text-ink-400">Lifecycle</dt><dd className="mt-1 font-medium text-ink-600">{lifecycle}</dd></div>
            <div><dt className="text-ink-400">Generated</dt><dd className="mt-1 font-medium text-ink-600">{ticket.ai_generated_at ? formatTimeAgo(ticket.ai_generated_at) : "Not available"}</dd></div>
            {failureDetail && <div><dt className="text-ink-400">Last failure</dt><dd className="mt-1 font-medium text-ink-600">{failureDetail}</dd></div>}
          </dl>
          {ticket.ai_reasoning && <div className="min-w-0"><p className="font-semibold text-ink-600">Reasoning</p><p className="mt-1 whitespace-pre-wrap break-words leading-5 [overflow-wrap:anywhere]">{ticket.ai_reasoning}</p></div>}
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
  return <div className="min-w-0 border-b border-linen-300 px-3 py-3 last:border-b-0 sm:[&:nth-last-child(-n+1)]:border-b-0 sm:border-r sm:[&:nth-child(2n)]:border-r-0 xl:border-b-0 xl:[&:nth-child(2n)]:border-r xl:last:border-r-0"><dt className="break-words text-[10px] font-semibold uppercase tracking-wide text-ink-400 [overflow-wrap:anywhere]">{label}</dt><dd className="mt-1 break-words text-xs font-semibold leading-4 text-ink-700 [overflow-wrap:anywhere]">{value}</dd></div>;
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
