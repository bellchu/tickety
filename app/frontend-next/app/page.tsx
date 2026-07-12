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
  Plus,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  TicketIcon,
  UserRound,
} from "lucide-react";
import { NewTicketModal } from "@/components/ticket/NewTicketModal";
import { Alert, Badge, Button, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { PrioritizedTicket, Ticket } from "@/lib/types";
import { cn } from "@/lib/utils";

const CLOSED_STATUSES = new Set(["closed", "resolved", "completed"]);
const PRIORITY_RANK: Record<string, number> = { P1: 0, P2: 1, P3: 2, P4: 3 };
const EMPTY_TICKETS: Ticket[] = [];

function isActive(ticket: Ticket) {
  return !CLOSED_STATUSES.has(ticket.status.toLowerCase());
}

function formatUpdatedAt(value: string | null) {
  if (!value) return "No activity yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Update time unavailable";
  return `Updated ${new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)}`;
}

function formatAge(hours: number) {
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
    ["Assignee", (ticket) => ticket.assignee_name],
    ["Category", (ticket) => ticket.category],
    ["Created", (ticket) => ticket.created_at],
    ["Updated", (ticket) => ticket.updated_at],
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

function MetricCard({
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
    <div className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</p>
        <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", tones[tone])} aria-hidden="true">{icon}</span>
      </div>
      {loading ? (
        <><Skeleton className="mt-4 h-8 w-20" /><Skeleton className="mt-3 h-3 w-32" /></>
      ) : (
        <>
          <p className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-ink-700 tabular-nums">{value}</p>
          <p className="mt-1 text-xs leading-5 text-ink-500">{supporting}</p>
        </>
      )}
    </div>
  );
}

function priorityVariant(priority: string): "danger" | "warning" | "info" | "neutral" {
  if (priority === "P1") return "danger";
  if (priority === "P2") return "warning";
  if (priority === "P3") return "info";
  return "neutral";
}

function statusVariant(status: string): "success" | "warning" | "info" | "neutral" {
  const normalized = status.toLowerCase();
  if (CLOSED_STATUSES.has(normalized)) return "success";
  if (["escalated", "pending", "awaiting review"].includes(normalized)) return "warning";
  if (["new", "open", "in progress"].includes(normalized)) return "info";
  return "neutral";
}

function queueReason(item: PrioritizedTicket | undefined, ticket: Ticket) {
  if (!item) return ticket.ai_reasoning || "Ordered by declared priority and age.";
  const factors = [
    `${item.priority} priority`,
    `${Math.round(item.escalation_risk)}% escalation risk`,
    `${formatAge(item.age_hours)} old`,
  ];
  if (item.sentiment) factors.push(`${item.sentiment.toLowerCase()} sentiment`);
  return factors.join(" · ");
}

export default function DashboardPage() {
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: api.getTickets });
  const meQuery = useQuery({ queryKey: ["me"], queryFn: api.getMe, retry: false });
  const priorityQuery = useQuery({ queryKey: ["intel-prioritize"], queryFn: api.getIntelPrioritize, retry: false });
  const slaQuery = useQuery({ queryKey: ["intel-sla"], queryFn: api.getIntelSla, retry: false });
  const servicesQuery = useQuery({ queryKey: ["services"], queryFn: () => api.getServices(), retry: false });
  const serviceRequestsQuery = useQuery({ queryKey: ["serviceRequests"], queryFn: api.getServiceRequests, retry: false });

  const tickets = ticketsQuery.data ?? EMPTY_TICKETS;
  const activeTickets = useMemo(() => tickets.filter(isActive), [tickets]);
  const latestUpdate = useMemo(() => {
    let latest = 0;
    for (const ticket of tickets) {
      const timestamp = new Date(ticket.updated_at || ticket.created_at || 0).getTime();
      if (Number.isFinite(timestamp) && timestamp > latest) latest = timestamp;
    }
    return latest ? new Date(latest).toISOString() : null;
  }, [tickets]);

  const rankedById = useMemo(
    () => new Map((priorityQuery.data?.ranked ?? []).map((item) => [item.ticket_id, item])),
    [priorityQuery.data]
  );
  const ticketById = useMemo(() => new Map(tickets.map((ticket) => [ticket.id, ticket])), [tickets]);
  const queue = useMemo(() => {
    if (priorityQuery.data?.ranked.length) {
      return priorityQuery.data.ranked
        .map((item) => ticketById.get(item.ticket_id))
        .filter((ticket): ticket is Ticket => Boolean(ticket))
        .slice(0, 6);
    }
    return [...activeTickets]
      .sort((a, b) => {
        const priorityDifference = (PRIORITY_RANK[a.priority] ?? 4) - (PRIORITY_RANK[b.priority] ?? 4);
        if (priorityDifference) return priorityDifference;
        return new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
      })
      .slice(0, 6);
  }, [activeTickets, priorityQuery.data, ticketById]);

  const slaItems = slaQuery.data?.items ?? [];
  const breached = slaItems.filter((item) => item.status === "breached").length;
  const atRisk = slaItems.filter((item) => item.status === "at_risk").length;
  const onTrack = slaItems.filter((item) => item.status === "on_track").length;
  const slaHealth = slaItems.length ? Math.round((onTrack / slaItems.length) * 100) : null;
  const p1Count = activeTickets.filter((ticket) => ticket.priority === "P1").length;
  const attentionCount = breached + atRisk;
  const activeServices = (servicesQuery.data ?? []).filter((service) => service.is_active).length;
  const openServiceRequests = (serviceRequestsQuery.data ?? []).filter(
    (request) => !["fulfilled", "cancelled"].includes(request.fulfillment_status.toLowerCase())
  ).length;
  const topRecommendation = priorityQuery.data?.ranked[0];
  const topTicket = topRecommendation ? ticketById.get(topRecommendation.ticket_id) : undefined;

  const pulse = slaQuery.isError
    ? { label: "Partial operational view", body: "SLA intelligence is unavailable; ticket volume remains current.", tone: "warning" as const }
    : breached > 0
    ? { label: "Intervention required", body: `${breached} open ${breached === 1 ? "request has" : "requests have"} breached an SLA target.`, tone: "danger" as const }
    : atRisk > 0 || p1Count > 0
      ? { label: "Attention recommended", body: `${atRisk} SLA ${atRisk === 1 ? "clock is" : "clocks are"} at risk and ${p1Count} P1 ${p1Count === 1 ? "ticket is" : "tickets are"} active.`, tone: "warning" as const }
      : activeTickets.length === 0
        ? { label: "Queue clear", body: "There are no active tickets in the current queue.", tone: "success" as const }
        : { label: "Operations stable", body: "No SLA risks or active P1 tickets are currently reported.", tone: "success" as const };

  const retryDashboard = () => {
    void Promise.all([
      ticketsQuery.refetch(),
      priorityQuery.refetch(),
      slaQuery.refetch(),
      servicesQuery.refetch(),
      serviceRequestsQuery.refetch(),
    ]);
  };

  if (ticketsQuery.isError) {
    return (
      <div className="mx-auto max-w-3xl py-12">
        <ErrorState
          title="Operations data could not be loaded"
          description="The dashboard has no current ticket data, so operational metrics would be misleading. Check the connection and try again."
          actionLabel="Retry dashboard"
          onRetry={retryDashboard}
          retrying={ticketsQuery.isFetching}
        />
      </div>
    );
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-ink-400">
            <Activity className="h-3.5 w-3.5 text-semantic-primary" aria-hidden="true" />
            Live operations
          </div>
          <h1 className="mt-2 font-serif text-3xl tracking-[-0.025em] text-ink-700 sm:text-4xl">Operations Overview</h1>
          <p className="mt-2 text-sm text-ink-500">
            {meQuery.data ? `Welcome back, ${meQuery.data.name.split(" ")[0]}. ` : ""}{ticketsQuery.isLoading ? "Loading latest activity…" : formatUpdatedAt(latestUpdate)}
          </p>
        </div>
        <div className="flex flex-col gap-2 xs:flex-row sm:flex-row">
          <Button
            variant="secondary"
            onClick={() => exportTickets(tickets)}
            disabled={ticketsQuery.isLoading || tickets.length === 0}
            leadingIcon={<Download className="h-4 w-4" />}
          >
            Export CSV
          </Button>
          <Button onClick={() => setNewTicketOpen(true)} leadingIcon={<Plus className="h-4 w-4" />}>New ticket</Button>
        </div>
      </header>

      <section aria-labelledby="operational-pulse-title" className="overflow-hidden rounded-2xl bg-ink-700 text-linen-50 shadow-[var(--shadow-raised)]">
        <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[1.3fr_0.7fr] lg:items-center">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.13em] text-linen-500">
              <span className={cn("h-2 w-2 rounded-full", pulse.tone === "danger" ? "bg-rust-400" : pulse.tone === "warning" ? "bg-amber-400" : "bg-moss-400")} aria-hidden="true" />
              Operational pulse
            </div>
            {ticketsQuery.isLoading || slaQuery.isLoading ? (
              <><Skeleton className="mt-5 h-8 w-56 bg-white/15" /><Skeleton className="mt-3 h-4 w-full max-w-md bg-white/15" /></>
            ) : (
              <>
                <h2 id="operational-pulse-title" className="mt-4 text-2xl font-semibold tracking-[-0.025em] text-white">{pulse.label}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-linen-400">{pulse.body}</p>
              </>
            )}
          </div>
          <div className="grid grid-cols-3 divide-x divide-white/15 rounded-xl border border-white/10 bg-white/[0.04] px-2 py-4">
            <div className="px-3 text-center"><p className="text-2xl font-semibold tabular-nums text-white">{ticketsQuery.isLoading ? "—" : activeTickets.length}</p><p className="mt-1 text-[11px] text-linen-500">Active</p></div>
            <div className="px-3 text-center"><p className="text-2xl font-semibold tabular-nums text-white">{slaQuery.isLoading || slaQuery.isError ? "—" : attentionCount}</p><p className="mt-1 text-[11px] text-linen-500">SLA attention</p></div>
            <div className="px-3 text-center"><p className="text-2xl font-semibold tabular-nums text-white">{ticketsQuery.isLoading ? "—" : p1Count}</p><p className="mt-1 text-[11px] text-linen-500">P1 active</p></div>
          </div>
        </div>
      </section>

      <section aria-label="Service and SLA metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Active queue" value={activeTickets.length} supporting={`${tickets.length} total tickets loaded`} icon={<TicketIcon className="h-4 w-4" />} loading={ticketsQuery.isLoading} />
        <MetricCard
          label="SLA on track"
          value={slaQuery.isError ? "Unavailable" : slaHealth == null ? "—" : `${slaHealth}%`}
          supporting={slaQuery.isError ? "SLA endpoint could not be reached" : slaItems.length ? `${onTrack} of ${slaItems.length} tracked clocks` : "No active SLA clocks"}
          icon={<ShieldCheck className="h-4 w-4" />}
          tone={slaQuery.isError ? "danger" : slaHealth != null && slaHealth < 80 ? "warning" : "success"}
          loading={slaQuery.isLoading}
        />
        <MetricCard
          label="SLA attention"
          value={slaQuery.isError ? "Unavailable" : attentionCount}
          supporting={slaQuery.isError ? "SLA endpoint could not be reached" : `${atRisk} at risk · ${breached} breached`}
          icon={<AlertTriangle className="h-4 w-4" />}
          tone={breached ? "danger" : atRisk ? "warning" : "success"}
          loading={slaQuery.isLoading}
        />
        <MetricCard
          label="Service operations"
          value={servicesQuery.isError ? "Unavailable" : activeServices}
          supporting={serviceRequestsQuery.isError ? "Request status unavailable" : `${openServiceRequests} open service ${openServiceRequests === 1 ? "request" : "requests"}`}
          icon={<ServerCog className="h-4 w-4" />}
          tone={servicesQuery.isError || serviceRequestsQuery.isError ? "danger" : openServiceRequests ? "warning" : "neutral"}
          loading={servicesQuery.isLoading || serviceRequestsQuery.isLoading}
        />
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.55fr_0.75fr]">
        <section aria-labelledby="priority-queue-title" className="min-w-0 overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-linen-300 px-5 py-4 sm:px-6">
            <div>
              <h2 id="priority-queue-title" className="text-base font-semibold text-ink-700">Priority queue</h2>
              <p className="mt-1 text-xs text-ink-500">
                {priorityQuery.isError ? "AI ranking unavailable; using priority and age." : "Ranked by priority, escalation risk, sentiment, age, and complexity."}
              </p>
            </div>
            <Link href="/tickets" className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold text-semantic-primary transition-colors hover:bg-[var(--color-primary-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
              View all <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </div>

          {ticketsQuery.isLoading || priorityQuery.isLoading ? (
            <div aria-label="Loading priority queue" aria-busy="true" className="space-y-3 p-5 sm:p-6">
              <span className="sr-only">Loading priority queue</span>
              {[0, 1, 2, 3].map((item) => <Skeleton key={item} className="h-16 w-full" />)}
            </div>
          ) : queue.length === 0 ? (
            <EmptyState title="The active queue is clear" description="New and reopened tickets will appear here in operational priority order." icon={<CheckCircle2 className="h-5 w-5" />} className="m-5" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left">
                <caption className="sr-only">Highest priority active tickets</caption>
                <thead className="bg-linen-100 text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-400">
                  <tr><th scope="col" className="w-12 px-5 py-3 text-center">Rank</th><th scope="col" className="px-3 py-3">Request</th><th scope="col" className="px-3 py-3">Owner</th><th scope="col" className="px-3 py-3">Status</th><th scope="col" className="px-5 py-3 text-right">Signal</th></tr>
                </thead>
                <tbody className="divide-y divide-linen-300">
                  {queue.map((ticket, index) => {
                    const ranked = rankedById.get(ticket.id);
                    return (
                      <tr key={ticket.id} className="group transition-colors hover:bg-linen-100">
                        <td className="px-5 py-4 text-center"><span className="inline-grid h-7 w-7 place-items-center rounded-full bg-linen-200 text-xs font-semibold text-ink-600">{index + 1}</span></td>
                        <td className="max-w-[24rem] px-3 py-4">
                          <div className="flex items-center gap-2"><Badge variant={priorityVariant(ticket.priority)}>{ticket.priority}</Badge><Link href={`/tickets/${ticket.id}`} className="truncate text-sm font-semibold text-ink-700 hover:text-semantic-primary hover:underline">{ticket.subject}</Link></div>
                          <p className="mt-1 truncate text-xs text-ink-400">{queueReason(ranked, ticket)}</p>
                        </td>
                        <td className="px-3 py-4"><span className="inline-flex items-center gap-1.5 text-xs text-ink-500"><UserRound className="h-3.5 w-3.5" aria-hidden="true" />{ticket.assignee_name || "Unassigned"}</span></td>
                        <td className="px-3 py-4"><Badge variant={statusVariant(ticket.status)} dot>{ticket.status}</Badge></td>
                        <td className="px-5 py-4 text-right">{ranked ? <><span className="text-sm font-semibold tabular-nums text-ink-700">{Math.round(ranked.score)}</span><span className="ml-1 text-[10px] uppercase text-ink-400">score</span></> : <span className="text-xs text-ink-400">Fallback</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <aside aria-labelledby="ai-recommendation-title" className="self-start rounded-2xl border border-clay-200 bg-[var(--color-primary-soft)] p-5 shadow-sm sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-semantic-primary text-white shadow-sm" aria-hidden="true"><Bot className="h-5 w-5" /></span>
            <Badge variant="info" dot>Explainable ranking</Badge>
          </div>
          <h2 id="ai-recommendation-title" className="mt-5 text-lg font-semibold tracking-[-0.015em] text-ink-700">Recommended next action</h2>
          {priorityQuery.isLoading ? (
            <div className="mt-4 space-y-3"><Skeleton className="h-5 w-5/6" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-3/4" /><Skeleton className="mt-5 h-10 w-full" /></div>
          ) : priorityQuery.isError ? (
            <Alert variant="warning" title="Recommendation unavailable" className="mt-4">The priority service could not be reached. The queue is using a deterministic fallback.</Alert>
          ) : !topRecommendation || !topTicket ? (
            <div className="mt-4"><EmptyState title="No action recommended" description="There are no ranked active tickets at this time." icon={<CheckCircle2 className="h-5 w-5" />} className="min-h-44 border-clay-200 bg-white/60" /></div>
          ) : (
            <>
              <p className="mt-4 text-sm font-semibold leading-5 text-ink-700">Review “{topTicket.subject}” first.</p>
              <p className="mt-2 text-sm leading-6 text-ink-500">It currently has the highest operational score in the active backlog. The ranking is based on the signals below—not an automated resolution decision.</p>
              <dl className="mt-5 grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-clay-200 bg-white/65 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-400"><Gauge className="h-3.5 w-3.5" aria-hidden="true" />Escalation risk</dt><dd className="mt-1 text-base font-semibold text-ink-700">{Math.round(topRecommendation.escalation_risk)}%</dd></div>
                <div className="rounded-xl border border-clay-200 bg-white/65 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-400"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />Age</dt><dd className="mt-1 text-base font-semibold text-ink-700">{formatAge(topRecommendation.age_hours)}</dd></div>
                <div className="rounded-xl border border-clay-200 bg-white/65 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-400"><AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />Priority</dt><dd className="mt-1 text-base font-semibold text-ink-700">{topRecommendation.priority}</dd></div>
                <div className="rounded-xl border border-clay-200 bg-white/65 p-3"><dt className="flex items-center gap-1.5 text-[11px] font-medium text-ink-400"><Layers3 className="h-3.5 w-3.5" aria-hidden="true" />Complexity</dt><dd className="mt-1 text-base font-semibold text-ink-700">{topRecommendation.complexity}/5</dd></div>
              </dl>
              <Link href={`/tickets/${topTicket.id}`} className="mt-5 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-semantic-primary px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-semantic-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2">
                Review ticket <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </>
          )}
        </aside>
      </div>

      {(slaQuery.isError || servicesQuery.isError || serviceRequestsQuery.isError) && (
        <Alert
          variant="warning"
          title="Some operational signals are unavailable"
          action={<Button variant="secondary" size="sm" onClick={retryDashboard} pending={slaQuery.isFetching || servicesQuery.isFetching || serviceRequestsQuery.isFetching} pendingLabel="Retrying…" leadingIcon={<RefreshCw className="h-3.5 w-3.5" />}>Retry</Button>}
        >
          Ticket data is current, but one or more SLA or service metrics could not be loaded. Unavailable values are labeled rather than estimated.
        </Alert>
      )}

      <NewTicketModal open={newTicketOpen} onClose={() => setNewTicketOpen(false)} />
    </div>
  );
}
