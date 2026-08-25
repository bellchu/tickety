"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  Download,
  Gauge,
  Layers3,
  ListOrdered,
  Plus,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  TicketIcon,
  UserRound,
} from "lucide-react";
import { NewTicketModal } from "@/components/ticket/NewTicketModal";
import { Alert, Badge, Button, EmptyState, ErrorState, ListText, Skeleton } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";
import { api } from "@/lib/api";
import {
  canAccessProtectedIntelligence,
  canCreateTickets,
  isDemoContext,
} from "@/lib/auth";
import {
  deterministicQueueReason,
  formatQueueAge,
  isActiveTicket,
  selectDeterministicQueue,
} from "@/lib/dashboard";
import type { PrioritizedTicket, Ticket } from "@/lib/types";
import { cn, formatTimeAgo } from "@/lib/utils";
import {
  requesterEmail,
  requesterName,
  ticketCreatedAt,
  ticketLastCommunicationAt,
} from "@/lib/ticket-display";

const CLOSED_STATUSES = new Set(["canceled", "cancelled", "closed", "resolved", "completed"]);
const EMPTY_TICKETS: Ticket[] = [];

function formatRefreshedAt(value: number) {
  if (!value) return "Refreshing current data…";
  return `Refreshed ${new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))}`;
}

function formatDurationHours(hours: number) {
  if (hours < 1) return "<1h";
  if (hours < 24) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

function csvCell(value: unknown) {
  let text = value == null ? "" : String(value);
  // Prevent spreadsheet applications from evaluating exported user content.
  if (/^[\t\r ]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function exportTickets(tickets: Ticket[]) {
  const columns: Array<[string, (ticket: Ticket) => unknown]> = [
    ["Ticket ID", (ticket) => ticket.id],
    ["Subject", (ticket) => ticket.subject],
    ["Status", (ticket) => ticket.status],
    ["Priority", (ticket) => ticket.priority],
    ["Reporter", (ticket) => ticket.reporter],
    ["Requester name", (ticket) => requesterName(ticket)],
    ["Requester email", (ticket) => requesterEmail(ticket)],
    ["Requester title", (ticket) => ticket.requester_title],
    ["Assignee", (ticket) => ticket.assignee_name || ticket.external_assignee_name],
    ["Category", (ticket) => ticket.category],
    ["Created", (ticket) => ticketCreatedAt(ticket)],
    ["Last communication", (ticket) => ticketLastCommunicationAt(ticket)],
  ];
  const rows = [
    columns.map(([label]) => csvCell(label)).join(","),
    ...tickets.map((ticket) => columns.map(([, getValue]) => csvCell(getValue(ticket))).join(",")),
  ];
  const blob = new Blob([`\uFEFF${rows.join("\r\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `tickety-operations-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function ContextMetric({
  label,
  value,
  supporting,
  icon,
  tone = "neutral",
  loading = false,
}: {
  label: string;
  value: string | number;
  supporting: string;
  icon: React.ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
  loading?: boolean;
}) {
  const tones = {
    neutral: "bg-linen-200 text-ink-500",
    success: "bg-[var(--color-success-soft)] text-semantic-success",
    warning: "bg-[var(--color-warning-soft)] text-semantic-warning",
    danger: "bg-[var(--color-danger-soft)] text-semantic-danger",
  };

  return (
    <div className="min-w-0 p-4 sm:p-5 xl:p-4">
      <div className="flex items-center gap-3">
        <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", tones[tone])} aria-hidden="true">{icon}</span>
        <p className="font-mono text-[10px] font-medium uppercase tracking-[0.11em] text-ink-500">{label}</p>
      </div>
      {loading ? (
        <><Skeleton className="mt-3 h-7 w-20" /><Skeleton className="mt-2 h-3 w-32 max-w-full" /></>
      ) : (
        <>
          <p className="mt-3 break-words text-2xl font-semibold tracking-[-0.035em] text-ink-700 tabular-nums [overflow-wrap:anywhere]">{value}</p>
          <p className="mt-1 text-xs leading-5 text-ink-500">{supporting}</p>
        </>
      )}
    </div>
  );
}

function priorityVariant(priority: string): "danger" | "warning" | "info" | "neutral" {
  const normalized = priority.trim().toUpperCase();
  if (normalized === "P1") return "danger";
  if (normalized === "P2") return "warning";
  if (normalized === "P3") return "info";
  return "neutral";
}

function statusVariant(status: string): "success" | "warning" | "info" | "neutral" {
  const normalized = status.trim().toLowerCase();
  if (CLOSED_STATUSES.has(normalized)) return "success";
  if (["escalated", "pending", "awaiting review"].includes(normalized)) return "warning";
  if (["new", "open", "in progress"].includes(normalized)) return "info";
  return "neutral";
}

function TicketPriorityBadge({ priority, className }: { priority: string; className?: string }) {
  return (
    <Badge variant={priorityVariant(priority)} className={cn("min-w-0 max-w-full overflow-hidden", className)} title={priority}>
      <span className="truncate">{priority}</span>
    </Badge>
  );
}

function TicketStatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge variant={statusVariant(status)} dot className={cn("min-w-0 max-w-full overflow-hidden [&>span:first-child]:shrink-0", className)} title={status}>
      <span className="truncate">{status}</span>
    </Badge>
  );
}

function intelligenceQueueReason(item: PrioritizedTicket) {
  const factors = [
    `${item.priority} priority`,
    `${Math.round(item.escalation_risk)}% escalation risk`,
    `${formatDurationHours(item.age_hours)} old`,
  ];
  if (item.sentiment) factors.push(`${item.sentiment.toLowerCase()} sentiment`);
  return factors.join(" · ");
}

export default function DashboardPage() {
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canUseIntelligence = canAccessProtectedIntelligence(authQuery.data);
  const canCreateTicket = canCreateTickets(authQuery.data);
  const demoWorkspace = isDemoContext(authQuery.data);

  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: api.getTickets });
  const priorityQuery = useQuery({
    queryKey: ["intel-prioritize"],
    queryFn: api.getIntelPrioritize,
    retry: false,
    enabled: canUseIntelligence,
  });
  const slaQuery = useQuery({
    queryKey: ["intel-sla"],
    queryFn: api.getIntelSla,
    retry: false,
    enabled: canUseIntelligence,
  });
  const servicesQuery = useQuery({ queryKey: ["services"], queryFn: () => api.getServices(), retry: false });
  const serviceRequestsQuery = useQuery({ queryKey: ["serviceRequests"], queryFn: api.getServiceRequests, retry: false });

  const tickets = ticketsQuery.data ?? EMPTY_TICKETS;
  const activeTickets = useMemo(() => tickets.filter(isActiveTicket), [tickets]);
  const ticketById = useMemo(() => new Map(tickets.map((ticket) => [ticket.id, ticket])), [tickets]);

  // Never surface cached protected data after the capability is lost or a refresh fails.
  const priorityData = canUseIntelligence && !priorityQuery.isError ? priorityQuery.data : undefined;
  const slaData = canUseIntelligence && !slaQuery.isError ? slaQuery.data : undefined;
  const rankedById = useMemo(
    () => new Map((priorityData?.ranked ?? []).map((item) => [item.ticket_id, item])),
    [priorityData]
  );
  const rankedQueue = useMemo(() => (
    (priorityData?.ranked ?? [])
      .map((item) => ticketById.get(item.ticket_id))
      .filter((ticket): ticket is Ticket => Boolean(ticket && isActiveTicket(ticket)))
      .slice(0, 6)
  ), [priorityData, ticketById]);
  const usesIntelligenceQueue = rankedQueue.length > 0;
  const queue = useMemo(() => {
    return usesIntelligenceQueue ? rankedQueue : selectDeterministicQueue(tickets, 6);
  }, [rankedQueue, tickets, usesIntelligenceQueue]);

  const slaItems = slaData?.items ?? [];
  const breached = slaItems.filter((item) => item.status === "breached").length;
  const atRisk = slaItems.filter((item) => item.status === "at_risk").length;
  const onTrack = slaItems.filter((item) => item.status === "on_track").length;
  const slaHealth = slaItems.length ? Math.round((onTrack / slaItems.length) * 100) : null;
  const p1Count = activeTickets.filter((ticket) => ticket.priority.trim().toUpperCase() === "P1").length;
  const escalatedCount = activeTickets.filter((ticket) => ticket.status.trim().toLowerCase() === "escalated").length;
  const unassignedCount = activeTickets.filter((ticket) => !ticket.assignee_id && !ticket.assignee_name && !ticket.external_assignee_name).length;
  const inactiveCount = tickets.length - activeTickets.length;
  const attentionCount = breached + atRisk;
  const activeServices = (servicesQuery.data ?? []).filter((service) => service.is_active).length;
  const openServiceRequests = (serviceRequestsQuery.data ?? []).filter(
    (request) => !["fulfilled", "cancelled"].includes(request.fulfillment_status.toLowerCase())
  ).length;

  const topTicket = queue[0];
  const topRecommendation = topTicket ? rankedById.get(topTicket.id) : undefined;
  const hasIntelligenceRanking = Boolean(topRecommendation && topTicket);
  const queueLoading = ticketsQuery.isLoading || authQuery.isLoading || (canUseIntelligence && priorityQuery.isLoading);

  const pulse = breached > 0
    ? { label: "Intervention required", body: `${breached} open ${breached === 1 ? "request has" : "requests have"} breached an SLA target.`, tone: "danger" as const }
    : p1Count > 0 || atRisk > 0
      ? {
          label: "Attention recommended",
          body: [
            p1Count > 0 ? `${p1Count} active P1 ${p1Count === 1 ? "ticket" : "tickets"}` : null,
            atRisk > 0 ? `${atRisk} SLA ${atRisk === 1 ? "clock" : "clocks"} at risk` : null,
          ].filter(Boolean).join(" · "),
          tone: "warning" as const,
        }
      : activeTickets.length === 0
        ? { label: "Queue clear", body: "There are no active tickets in the current queue.", tone: "success" as const }
        : canUseIntelligence && slaQuery.isError
          ? { label: "Core queue is current", body: "Ticket data is available; SLA intelligence needs to be refreshed.", tone: "warning" as const }
          : demoWorkspace
            ? { label: "Sample queue stable", body: "No active P1 tickets are present in the sample queue.", tone: "success" as const }
            : slaData
              ? { label: "Operations stable", body: "No SLA risks or active P1 tickets are currently reported.", tone: "success" as const }
              : { label: "Core queue is current", body: "No active P1 tickets are present; SLA status is not included in this view.", tone: "success" as const };

  const pulseLoading = ticketsQuery.isLoading
    || authQuery.isLoading
    || (canUseIntelligence && slaQuery.isLoading && p1Count === 0);

  const unavailableSignals = [
    authQuery.isError ? "session capabilities" : null,
    canUseIntelligence && priorityQuery.isError ? "priority ranking" : null,
    canUseIntelligence && slaQuery.isError ? "SLA intelligence" : null,
    servicesQuery.isError ? "service catalog" : null,
    serviceRequestsQuery.isError ? "service request status" : null,
  ].filter((item): item is string => Boolean(item));
  const retryingUnavailable = authQuery.isFetching
    || (canUseIntelligence && (priorityQuery.isFetching || slaQuery.isFetching))
    || servicesQuery.isFetching
    || serviceRequestsQuery.isFetching;

  const retryUnavailableData = () => {
    const requests: Array<Promise<unknown>> = [];
    if (ticketsQuery.isError) requests.push(ticketsQuery.refetch());
    if (authQuery.isError) requests.push(authQuery.refetch());
    if (canUseIntelligence && priorityQuery.isError) requests.push(priorityQuery.refetch());
    if (canUseIntelligence && slaQuery.isError) requests.push(slaQuery.refetch());
    if (servicesQuery.isError) requests.push(servicesQuery.refetch());
    if (serviceRequestsQuery.isError) requests.push(serviceRequestsQuery.refetch());
    void Promise.all(requests);
  };

  if (ticketsQuery.isError) {
    return (
      <div className="mx-auto max-w-3xl py-12">
        <ErrorState
          title="Operations data could not be loaded"
          description="The dashboard has no current ticket data, so operational metrics would be misleading. Check the connection and try again."
          actionLabel="Retry dashboard"
          onRetry={retryUnavailableData}
          retrying={ticketsQuery.isFetching}
        />
      </div>
    );
  }

  const secondaryPulse = slaData
    ? { label: "SLA attention", value: attentionCount }
    : { label: "Unassigned", value: unassignedCount };

  return (
    <PageFrame width="wide">
      <PageHeader
        eyebrow={demoWorkspace ? "Demo workspace" : "Operations workspace"}
        icon={<Activity className="h-3.5 w-3.5" />}
        title="Operations Overview"
        description={
          <>
            {demoWorkspace
              ? "Sample ticket and service data"
              : authQuery.data?.name
                ? `Welcome back, ${authQuery.data.name.split(" ")[0]}`
                : "Current ticket and service data"}
            {" · "}{formatRefreshedAt(ticketsQuery.dataUpdatedAt)}
          </>
        }
        actions={
          <>
          <Button
            variant="secondary"
            onClick={() => exportTickets(tickets)}
            disabled={ticketsQuery.isLoading || tickets.length === 0}
            leadingIcon={<Download className="h-4 w-4" />}
          >
            Export CSV
          </Button>
          {canCreateTicket && <Button onClick={() => setNewTicketOpen(true)} leadingIcon={<Plus className="h-4 w-4" />}>New ticket</Button>}
          </>
        }
      />

      {(priorityData?.truncated || slaData?.truncated) && (
        <Alert role="note" variant="warning" title="Operational intelligence is sampled" className="text-xs">
          {priorityData?.truncated ? `Priority ranking covers ${priorityData.analyzed_tickets.toLocaleString()} of ${priorityData.backlog_size.toLocaleString()} open tickets. ` : ""}
          {slaData?.truncated ? `SLA figures cover ${slaData.analyzed_tickets.toLocaleString()} of ${slaData.count.toLocaleString()} open tickets.` : ""}
        </Alert>
      )}

      {unavailableSignals.length > 0 && (
        <Alert
          variant="warning"
          title="Some current data needs attention"
          action={<Button variant="secondary" size="sm" onClick={retryUnavailableData} pending={retryingUnavailable} pendingLabel="Retrying…" leadingIcon={<RefreshCw className="h-3.5 w-3.5" />}>Retry</Button>}
        >
          Could not refresh {unavailableSignals.join(", ")}. Available ticket data remains visible and unavailable values are not estimated.
        </Alert>
      )}

      <section
        aria-labelledby="operational-pulse-title"
        data-overview-section="operational-pulse"
        className="relative overflow-hidden rounded-2xl bg-ink-700 text-linen-50 shadow-[var(--shadow-raised)]"
      >
        <span aria-hidden="true" className="nexora-spectrum absolute inset-x-0 top-0 h-[3px]" />
        <div className="grid gap-5 p-5 pt-6 sm:p-6 sm:pt-7 lg:grid-cols-[1.35fr_0.65fr] lg:items-center">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.13em] text-linen-400">
              <span className={cn("h-2 w-2 rounded-full", pulse.tone === "danger" ? "bg-rust-400" : pulse.tone === "warning" ? "bg-amber-400" : "bg-moss-400")} aria-hidden="true" />
              Operational pulse
            </div>
            {pulseLoading ? (
              <><Skeleton className="mt-5 h-8 w-56 bg-white/15" /><Skeleton className="mt-3 h-4 w-full max-w-md bg-white/15" /></>
            ) : (
              <>
                <h2 id="operational-pulse-title" className="mt-3 text-xl font-semibold tracking-[-0.02em] text-white">{pulse.label}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-linen-400">{pulse.body}</p>
              </>
            )}
          </div>
          <div className="grid min-w-0 grid-cols-3 divide-x divide-white/15 rounded-xl border border-white/10 bg-white/[0.04] px-1 py-4 sm:px-2">
            <div className="min-w-0 px-1.5 text-center sm:px-3"><p className="font-mono text-2xl font-medium tabular-nums text-white">{ticketsQuery.isLoading ? "—" : activeTickets.length}</p><p className="mt-1 break-words text-[10px] leading-4 text-linen-400 sm:text-[11px]">Active</p></div>
            <div className="min-w-0 px-1.5 text-center sm:px-3"><p className="font-mono text-2xl font-medium tabular-nums text-white">{ticketsQuery.isLoading || (canUseIntelligence && slaQuery.isLoading) ? "—" : secondaryPulse.value}</p><p className="mt-1 break-words text-[10px] leading-4 text-linen-400 sm:text-[11px]">{secondaryPulse.label}</p></div>
            <div className="min-w-0 px-1.5 text-center sm:px-3"><p className="font-mono text-2xl font-medium tabular-nums text-white">{ticketsQuery.isLoading ? "—" : p1Count}</p><p className="mt-1 break-words text-[10px] leading-4 text-linen-400 sm:text-[11px]">P1 active</p></div>
          </div>
        </div>
      </section>

      <div
        data-overview-decision-grid
        className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(18rem,0.75fr)] xl:items-start"
      >
        <aside
          aria-labelledby="queue-guidance-title"
          data-overview-section="next-action"
          className="relative min-w-0 self-start overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-6 xl:col-start-2 xl:row-start-1"
        >
          <span aria-hidden="true" className="nexora-spectrum absolute inset-x-0 top-0 h-[3px]" />
          <div className="flex items-center justify-between gap-3">
            <span className={cn("grid h-10 w-10 place-items-center rounded-xl", hasIntelligenceRanking ? "bg-semantic-primary text-white" : "bg-linen-300 text-ink-600")} aria-hidden="true">
              {hasIntelligenceRanking ? <Bot className="h-5 w-5" /> : <ListOrdered className="h-5 w-5" />}
            </span>
            <Badge variant={hasIntelligenceRanking ? "info" : "neutral"} dot>
              {hasIntelligenceRanking ? "Decision support" : demoWorkspace ? "Demo queue" : "Queue policy"}
            </Badge>
          </div>
          <p className="mt-5 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-400">Priority guidance</p>
          <h2 id="queue-guidance-title" className="mt-1 text-xl font-semibold tracking-[-0.02em] text-ink-700">Next action</h2>
          <div id="priority-recommendation-summary" className="mt-4">
            {queueLoading ? (
              <div className="space-y-3" aria-busy="true"><Skeleton className="h-5 w-5/6" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-3/4" /><Skeleton className="mt-5 h-10 w-full" /></div>
            ) : !topTicket ? (
              <EmptyState title="No action suggested" description="There are no active tickets at this time." icon={<CheckCircle2 className="h-5 w-5" />} className="min-h-40 bg-linen-100" />
            ) : hasIntelligenceRanking && topRecommendation ? (
              <>
                <p className="break-words text-sm font-semibold leading-5 text-ink-700 [overflow-wrap:anywhere]">Review “{topTicket.subject}” first.</p>
                <p className="mt-2 text-sm leading-6 text-ink-500">It has the highest protected operational score in the active backlog. Review the evidence before acting.</p>
                <dl className="mt-5 grid grid-cols-2 gap-2.5">
                  <div className="rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500"><Gauge className="h-3.5 w-3.5" aria-hidden="true" />Escalation risk</dt><dd className="mt-1 font-mono text-base font-medium text-ink-700">{Math.round(topRecommendation.escalation_risk)}%</dd></div>
                  <div className="rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />Age</dt><dd className="mt-1 font-mono text-base font-medium text-ink-700">{formatDurationHours(topRecommendation.age_hours)}</dd></div>
                  <div className="min-w-0 rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500"><AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />Priority</dt><dd><ListText text={topRecommendation.priority} lines={2} className="mt-1 font-mono text-base font-medium text-ink-700" /></dd></div>
                  <div className="rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500"><Layers3 className="h-3.5 w-3.5" aria-hidden="true" />Complexity</dt><dd className="mt-1 font-mono text-base font-medium text-ink-700">{topRecommendation.complexity}/5</dd></div>
                </dl>
              </>
            ) : (
              <>
                <p className="break-words text-sm font-semibold leading-5 text-ink-700 [overflow-wrap:anywhere]">Review “{topTicket.subject}” first.</p>
                <p className="mt-2 text-sm leading-6 text-ink-500">Selected by declared priority, then oldest first. AI-generated ticket content is not used for this queue policy.</p>
                <dl className="mt-5 grid grid-cols-2 gap-2.5">
                  <div className="min-w-0 rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="text-[11px] font-medium text-ink-500">Priority</dt><dd><ListText text={topTicket.priority} lines={2} className="mt-1 font-mono text-base font-medium text-ink-700" /></dd></div>
                  <div className="rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="text-[11px] font-medium text-ink-500">Age</dt><dd className="mt-1 font-mono text-base font-medium text-ink-700">{formatQueueAge(topTicket.created_at)}</dd></div>
                  <div className="min-w-0 rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="text-[11px] font-medium text-ink-500">Status</dt><dd><ListText text={topTicket.status} lines={2} className="mt-1 text-sm font-semibold text-ink-700" /></dd></div>
                  <div className="min-w-0 rounded-xl border border-linen-300 bg-linen-100 p-3"><dt className="text-[11px] font-medium text-ink-500">Owner</dt><dd><ListText text={topTicket.assignee_name || topTicket.external_assignee_name || "Unassigned"} lines={2} className="mt-1 text-sm font-semibold text-ink-700" /></dd></div>
                </dl>
              </>
            )}
          </div>
          {topTicket && !queueLoading && (
            <Link href={`/tickets/${topTicket.id}`} className="mt-5 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-semantic-primary px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-semantic-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2">
              Review ticket <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          )}
        </aside>

        <section
          aria-labelledby="priority-queue-title"
          data-overview-section="priority-queue"
          className="min-w-0 self-start overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm xl:col-start-1 xl:row-span-2 xl:row-start-1"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-linen-300 px-5 py-4 sm:px-6">
            <div className="min-w-0">
              <p className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-400">Active work</p>
              <h2 id="priority-queue-title" className="mt-1 text-base font-semibold text-ink-700">Priority queue</h2>
              <p className="mt-1 text-xs text-ink-500">
                {usesIntelligenceQueue
                  ? "Ranked by protected operational intelligence."
                  : "Sorted by declared priority, then oldest first."}
              </p>
            </div>
            <Link href="/tickets" className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold text-semantic-primary transition-colors hover:bg-[var(--color-primary-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
              View all <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </div>

          {queueLoading ? (
            <div aria-label="Loading priority queue" aria-busy="true" className="space-y-3 p-5 sm:p-6">
              <span className="sr-only">Loading priority queue</span>
              {[0, 1, 2, 3].map((item) => <Skeleton key={item} className="h-16 w-full" />)}
            </div>
          ) : queue.length === 0 ? (
            <EmptyState title="The active queue is clear" description="New and reopened tickets will appear here in operational priority order." icon={<CheckCircle2 className="h-5 w-5" />} className="m-5" />
          ) : (
            <>
              <div className="divide-y divide-linen-300 xl:hidden">
                {queue.map((ticket, index) => {
                  const ranked = rankedById.get(ticket.id);
                  return (
                    <article
                      key={ticket.id}
                      aria-describedby={index === 0 ? "priority-recommendation-summary" : undefined}
                      className={cn("relative p-4", index === 0 && "bg-[var(--color-primary-soft)]")}
                    >
                      {index === 0 && <span aria-hidden="true" className="nexora-spectrum absolute inset-y-0 left-0 w-[3px]" />}
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="inline-grid h-7 w-7 shrink-0 place-items-center rounded-full bg-linen-200 font-mono text-xs font-medium text-ink-600">{index + 1}</span>
                        <TicketPriorityBadge priority={ticket.priority} className="max-w-20 shrink" />
                        {index === 0 && <span className="font-mono text-[9px] font-medium uppercase tracking-[0.09em] text-semantic-primary">Recommended</span>}
                        <TicketStatusBadge status={ticket.status} className="ml-auto max-w-[8rem]" />
                      </div>
                      <Link href={`/tickets/${ticket.id}`} className="mt-2.5 block text-ink-700 hover:text-semantic-primary hover:underline"><ListText text={ticket.subject} lines={2} className="text-sm font-semibold leading-5" /></Link>
                      <ListText text={ranked ? intelligenceQueueReason(ranked) : deterministicQueueReason(ticket)} lines={2} className="mt-1 text-xs leading-5 text-ink-500" />
                      <p className="mt-2 flex min-w-0 items-start gap-1.5 text-xs text-ink-500"><UserRound className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><ListText text={`${requesterName(ticket)}${requesterEmail(ticket) ? ` · ${requesterEmail(ticket)}` : ""}`} lines={2} /></p>
                      <p className="mt-1 text-[11px] text-ink-400">Created {formatTimeAgo(ticketCreatedAt(ticket))} · Last contact {formatTimeAgo(ticketLastCommunicationAt(ticket))}</p>
                      <ListText text={`Owner: ${ticket.assignee_name || ticket.external_assignee_name || "Unassigned"}`} lines={2} className="mt-1 text-[11px] text-ink-400" />
                    </article>
                  );
                })}
              </div>
              <div className="hidden xl:block">
                <table className="w-full table-fixed text-left">
                  <caption className="sr-only">Highest priority active tickets</caption>
                  <colgroup>
                    <col className="w-16" />
                    <col />
                    <col className="w-[22%]" />
                    <col className="w-[19%]" />
                    {usesIntelligenceQueue ? <col className="w-20" /> : null}
                  </colgroup>
                  <thead className="bg-linen-100 font-mono text-[10px] font-medium uppercase tracking-[0.09em] text-ink-500">
                    <tr>
                      <th scope="col" className="px-3 py-3 text-center">Rank</th>
                      <th scope="col" className="px-3 py-3">Request</th>
                      <th scope="col" className="px-3 py-3">Owner</th>
                      <th scope="col" className="px-3 py-3">Status</th>
                      {usesIntelligenceQueue ? <th scope="col" className="px-3 py-3 text-right">Signal</th> : null}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-linen-300">
                    {queue.map((ticket, index) => {
                      const ranked = rankedById.get(ticket.id);
                      return (
                        <tr
                          key={ticket.id}
                          aria-describedby={index === 0 ? "priority-recommendation-summary" : undefined}
                          className={cn("group transition-colors hover:bg-linen-100", index === 0 && "bg-[var(--color-primary-soft)]")}
                        >
                          <td className="relative px-3 py-4 text-center">
                            {index === 0 && <span aria-hidden="true" className="nexora-spectrum absolute inset-y-0 left-0 w-[3px]" />}
                            <span className="inline-grid h-7 w-7 place-items-center rounded-full bg-linen-200 font-mono text-xs font-medium text-ink-600">{index + 1}</span>
                          </td>
                          <td className="min-w-0 px-3 py-4">
                            <div className="flex min-w-0 items-center gap-2">
                              <TicketPriorityBadge priority={ticket.priority} className="max-w-16 shrink" />
                              <Link href={`/tickets/${ticket.id}`} className="min-w-0 flex-1 text-ink-700 hover:text-semantic-primary hover:underline"><ListText text={ticket.subject} lines={2} className="text-sm font-semibold leading-5" /></Link>
                            </div>
                            <p className="mt-1 flex min-w-0 items-center gap-2 text-xs text-ink-500">
                              {index === 0 && <span className="shrink-0 font-mono text-[9px] font-medium uppercase tracking-[0.09em] text-semantic-primary">Recommended</span>}
                              <ListText text={ranked ? intelligenceQueueReason(ranked) : deterministicQueueReason(ticket)} lines={2} className="min-w-0 flex-1" />
                            </p>
                            <ListText text={`Requester: ${requesterName(ticket)}${requesterEmail(ticket) ? ` · ${requesterEmail(ticket)}` : ""}`} lines={2} className="mt-1 text-[11px] text-ink-500" />
                            <p className="mt-0.5 text-[10px] text-ink-400">Created {formatTimeAgo(ticketCreatedAt(ticket))} · Last contact {formatTimeAgo(ticketLastCommunicationAt(ticket))}</p>
                          </td>
                          <td className="min-w-0 px-3 py-4"><span className="flex min-w-0 items-start gap-1.5 text-xs text-ink-500"><UserRound className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><ListText text={ticket.assignee_name || ticket.external_assignee_name || "Unassigned"} lines={2} className="min-w-0 flex-1" /></span></td>
                          <td className="px-3 py-4"><TicketStatusBadge status={ticket.status} /></td>
                          {usesIntelligenceQueue ? (
                            <td className="px-3 py-4 text-right">{ranked ? <><span className="font-mono text-sm font-medium tabular-nums text-ink-700">{Math.round(ranked.score)}</span><span className="ml-1 text-[10px] uppercase text-ink-500">score</span></> : "—"}</td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>

        <aside
          aria-labelledby="workload-context-title"
          data-overview-section="workload-context"
          className="min-w-0 self-start overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm xl:col-start-2 xl:row-start-2"
        >
          <div className="border-b border-linen-300 px-5 py-4">
            <p className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-400">Operational context</p>
            <h2 id="workload-context-title" className="mt-1 text-base font-semibold text-ink-700">Workload context</h2>
            <p className="mt-1 text-xs leading-5 text-ink-500">Supporting signals for the current queue.</p>
          </div>
          <div className="grid divide-y divide-linen-300 sm:grid-cols-3 sm:divide-x sm:divide-y-0 xl:grid-cols-1 xl:divide-x-0 xl:divide-y">
            <ContextMetric
              label="Ticket volume"
              value={tickets.length}
              supporting={`${activeTickets.length} active · ${inactiveCount} inactive`}
              icon={<TicketIcon className="h-4 w-4" />}
              loading={ticketsQuery.isLoading}
            />
            {canUseIntelligence ? (
              <ContextMetric
                label="SLA on track"
                value={slaQuery.isError ? "Unavailable" : slaHealth == null ? "—" : `${slaHealth}%`}
                supporting={slaQuery.isError ? "SLA data needs to be refreshed" : slaItems.length ? `${onTrack} of ${slaItems.length} tracked clocks` : "No active SLA clocks"}
                icon={<ShieldCheck className="h-4 w-4" />}
                tone={slaQuery.isError ? "danger" : slaHealth != null && slaHealth < 80 ? "warning" : "success"}
                loading={slaQuery.isLoading}
              />
            ) : (
              <ContextMetric
                label="Escalated"
                value={escalatedCount}
                supporting={escalatedCount ? "Active tickets requiring attention" : "No active escalations"}
                icon={<AlertTriangle className="h-4 w-4" />}
                tone={escalatedCount ? "warning" : "success"}
                loading={ticketsQuery.isLoading || authQuery.isLoading}
              />
            )}
            <ContextMetric
              label="Active services"
              value={servicesQuery.isError ? "Unavailable" : activeServices}
              supporting={serviceRequestsQuery.isError ? "Request status needs to be refreshed" : `${openServiceRequests} open service ${openServiceRequests === 1 ? "request" : "requests"}`}
              icon={<ServerCog className="h-4 w-4" />}
              tone={servicesQuery.isError || serviceRequestsQuery.isError ? "danger" : openServiceRequests ? "warning" : "neutral"}
              loading={servicesQuery.isLoading || serviceRequestsQuery.isLoading}
            />
          </div>
        </aside>
      </div>

      {canCreateTicket && <NewTicketModal open={newTicketOpen} onClose={() => setNewTicketOpen(false)} />}
    </PageFrame>
  );
}
