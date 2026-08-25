"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { useIsFetching, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Archive,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Gauge,
  Layers3,
  ListChecks,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Siren,
  Sparkles,
  TrendingDown,
  TrendingUp,
  UserRoundX,
  Users,
} from "lucide-react";
import { Alert, Badge, Button, EmptyState, ErrorState, ListText, Skeleton } from "@/components/ui";
import { PageFrame, PageHeader, SectionHeader, SummaryStrip } from "@/components/layout/PageLayout";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence, isDemoContext } from "@/lib/auth";
import { formatLocalDateTime } from "@/lib/date-time";
import type {
  AccountHealth,
  IntelligenceAttentionTicket,
  IntelligenceOverviewResponse,
  IntelTrendsResponse,
  IntelWorkloadResponse,
  SystemicIssuesResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const WINDOWS = [7, 30, 90] as const;
type WindowDays = (typeof WINDOWS)[number];

const postureConfig = {
  critical: {
    label: "Critical attention",
    description: "Immediate SLA or critical-priority intervention is required.",
    badge: "danger" as const,
    icon: Siren,
  },
  watch: {
    label: "Watch closely",
    description: "Risk is building; rebalance ownership before service degrades.",
    badge: "warning" as const,
    icon: AlertTriangle,
  },
  healthy: {
    label: "Operations stable",
    description: "No critical exception is present in the selected activity window.",
    badge: "success" as const,
    icon: CheckCircle2,
  },
};

function IntelligenceHeader() {
  return (
    <PageHeader
      eyebrow="Admin & supervisor command center"
      icon={<Sparkles className="h-4 w-4" />}
      title="Intelligence cockpit"
      description="A decision-first view of current service risk, queue health, team capacity, and emerging demand. Legacy records are isolated from live operational signals."
      meta="Recommendations are advisory and always link back to source tickets for human review."
    />
  );
}

export default function IntelligencePage() {
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canAccessIntelligence = canAccessProtectedIntelligence(authQuery.data);

  if (authQuery.isLoading) {
    return (
      <PageFrame width="wide">
        <IntelligenceHeader />
        <div aria-busy="true" aria-label="Checking intelligence access" className="space-y-3">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-72 w-full" />
          <span className="sr-only">Checking intelligence access</span>
        </div>
      </PageFrame>
    );
  }

  if (authQuery.isError) {
    return (
      <PageFrame width="wide">
        <IntelligenceHeader />
        <ErrorState
          title="Intelligence access could not be checked"
          description="Your session and access level could not be verified, so no intelligence requests were sent."
          actionLabel="Retry access check"
          onRetry={() => void authQuery.refetch()}
          retrying={authQuery.isFetching}
        />
      </PageFrame>
    );
  }

  if (!canAccessIntelligence) {
    const demo = isDemoContext(authQuery.data);
    return (
      <PageFrame width="wide">
        <IntelligenceHeader />
        <EmptyState
          icon={<ShieldCheck className="h-5 w-5" />}
          title={demo ? "Demo administrator access required" : "Administrator or supervisor access required"}
          description={demo
            ? "Sign in with an active demo administrator account to view protected intelligence."
            : "This cockpit is available only to authenticated administrators and supervisors in production."}
        />
      </PageFrame>
    );
  }

  return <IntelligenceCockpit />;
}

function IntelligenceCockpit() {
  const [windowDays, setWindowDays] = useState<WindowDays>(30);
  const queryClient = useQueryClient();
  const fetchingCount = useIsFetching({ queryKey: ["intelligence"] });
  const overviewQuery = useQuery({
    queryKey: ["intelligence", "overview", windowDays],
    queryFn: () => api.getIntelOverview(windowDays),
    refetchInterval: 30_000,
  });
  const trendsQuery = useQuery({
    queryKey: ["intelligence", "trends", windowDays],
    queryFn: () => api.getIntelTrendsForWindow(windowDays),
  });
  const workloadQuery = useQuery({
    queryKey: ["intelligence", "workload", windowDays],
    queryFn: () => api.getIntelWorkload(windowDays),
  });
  const systemicQuery = useQuery({
    queryKey: ["intelligence", "systemic", windowDays],
    queryFn: () => api.getIntelSystemicForWindow(2, windowDays),
  });

  const refreshAll = () => queryClient.invalidateQueries({ queryKey: ["intelligence"] });
  const overview = overviewQuery.data;

  return (
    <PageFrame width="wide">
      <IntelligenceHeader />
      <ScopeToolbar
        windowDays={windowDays}
        onWindowChange={setWindowDays}
        onRefresh={() => void refreshAll()}
        refreshing={fetchingCount > 0}
        overview={overview}
      />

      {overviewQuery.isLoading ? (
        <CockpitLoading />
      ) : overviewQuery.isError || !overview ? (
        <ErrorState
          title="Operational posture unavailable"
          description="The primary cockpit signal could not be loaded. Supporting panels remain independently refreshable."
          onRetry={() => void overviewQuery.refetch()}
          retrying={overviewQuery.isFetching}
        />
      ) : (
        <>
          <div data-intelligence-section="operational-posture">
            <OperationalPosture data={overview} />
          </div>
          {overview.scope.truncated && (
            <Alert variant="warning" title="Operational analysis is sampled">
              Exception counts are based on {overview.scope.analyzed_tickets.toLocaleString()} of {overview.scope.active_open_tickets.toLocaleString()} active tickets. Scope totals remain exact.
            </Alert>
          )}
          <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(22rem,0.85fr)]">
            <div data-intelligence-section="attention-queue">
              <AttentionQueue data={overview} />
            </div>
            <div className="min-w-0 space-y-6">
              <div data-intelligence-section="age-flow"><AgeAndFlowPanel data={overview} /></div>
              <div data-intelligence-section="stale-backlog"><StaleBacklogPanel data={overview} /></div>
            </div>
          </div>
        </>
      )}

      <section data-intelligence-section="team-capacity" className="space-y-4">
        <SectionHeader
          title="Team capacity"
          description={`Current assignments and delivery outcomes within the last ${windowDays} days.`}
        />
        <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]">
          <WorkloadPanel query={workloadQuery} />
          <AccountHealthPanel windowDays={windowDays} />
        </div>
      </section>

      <section data-intelligence-section="demand-patterns" className="space-y-4">
        <SectionHeader
          title="Demand and systemic patterns"
          description={`Only tickets active in the selected ${windowDays}-day window contribute to these signals.`}
        />
        <div className="grid min-w-0 gap-6 lg:grid-cols-2">
          <TrendsPanel query={trendsQuery} />
          <SystemicPanel query={systemicQuery} />
        </div>
      </section>
    </PageFrame>
  );
}

function ScopeToolbar({
  windowDays,
  onWindowChange,
  onRefresh,
  refreshing,
  overview,
}: {
  windowDays: WindowDays;
  onWindowChange: (days: WindowDays) => void;
  onRefresh: () => void;
  refreshing: boolean;
  overview?: IntelligenceOverviewResponse;
}) {
  return (
    <section aria-label="Intelligence scope controls" className="rounded-xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5">
      <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-ink-700">Activity window</span>
            <div role="group" aria-label="Operational activity window" className="inline-flex rounded-lg border border-linen-400 bg-linen-100 p-1">
              {WINDOWS.map((days) => (
                <button
                  key={days}
                  type="button"
                  aria-pressed={windowDays === days}
                  onClick={() => onWindowChange(days)}
                  className={cn(
                    "min-h-8 rounded-md px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
                    windowDays === days ? "bg-ink-700 text-white shadow-sm" : "text-ink-500 hover:bg-linen-300 hover:text-ink-700",
                  )}
                >
                  {days} days
                </button>
              ))}
            </div>
            {windowDays === 30 && <Badge variant="info">Recommended</Badge>}
          </div>
          <p className="mt-2 text-xs leading-5 text-ink-500">
            Uses the provider&apos;s last update time, falling back to provider creation time. Import time never makes a legacy ticket look current.
          </p>
        </div>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
          <div className="min-w-0 text-xs leading-5 text-ink-400 sm:text-right">
            <span className="block">Auto-refreshes every 30 seconds</span>
            <span className="block">{overview ? `Generated ${formatLocalDateTime(overview.generated_at)}` : "Waiting for current posture"}</span>
          </div>
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={<RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />}
            pending={refreshing}
            pendingLabel="Refreshing"
            onClick={onRefresh}
          >
            Refresh all
          </Button>
        </div>
      </div>
    </section>
  );
}

function CockpitLoading() {
  return (
    <div aria-busy="true" aria-label="Loading intelligence cockpit" className="space-y-6">
      <Skeleton className="h-44 w-full" />
      <SummaryStrip label="Loading operational metrics">
        {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28 w-full" />)}
      </SummaryStrip>
      <div className="grid gap-6 xl:grid-cols-2"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>
    </div>
  );
}

function OperationalPosture({ data }: { data: IntelligenceOverviewResponse }) {
  const config = postureConfig[data.posture];
  const PostureIcon = config.icon;
  const immediateActions = data.posture_metrics.sla_breached
    + data.posture_metrics.p1_open
    + data.posture_metrics.escalation_prone;
  return (
    <section data-intelligence-section="operational-posture" aria-labelledby="operational-posture-title" className="relative overflow-hidden rounded-2xl bg-ink-700 p-5 text-white shadow-md sm:p-6">
      <span aria-hidden="true" className="nexora-spectrum absolute inset-x-0 top-0 h-[3px]" />
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-white/10"><PostureIcon className="h-5 w-5" /></span>
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-linen-400">Operational posture</p>
              <h2 id="operational-posture-title" className="mt-1 text-2xl font-medium tracking-[-0.025em]">{config.label}</h2>
            </div>
            <Badge variant={config.badge} dot className="border-white/10">{data.scope.window_days}-day view</Badge>
          </div>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-linen-300">{config.description}</p>
          <p className="mt-2 text-xs leading-5 text-linen-400">
            {data.scope.active_open_tickets.toLocaleString()} active open tickets are in scope; {data.scope.excluded_stale_open_tickets.toLocaleString()} stale open tickets are isolated from live scoring.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:min-w-[34rem]">
          <DarkMetric label="Act now" value={immediateActions} detail="critical signals" tone={immediateActions ? "danger" : "neutral"} />
          <DarkMetric label="SLA breach" value={data.posture_metrics.sla_breached} detail={`${data.posture_metrics.sla_at_risk} approaching`} tone={data.posture_metrics.sla_breached ? "danger" : data.posture_metrics.sla_at_risk ? "warning" : "neutral"} />
          <DarkMetric label="Unassigned" value={data.posture_metrics.unassigned_open} detail="ownership gaps" tone={data.posture_metrics.unassigned_open ? "warning" : "neutral"} />
          <DarkMetric label="Net flow" value={withSign(data.flow.net_change)} detail={`${data.flow.created} in · ${data.flow.resolved} out`} tone={data.flow.net_change > 0 ? "warning" : "neutral"} />
        </div>
      </div>
    </section>
  );
}

function DarkMetric({ label, value, detail, tone }: { label: string; value: number | string; detail: string; tone: "danger" | "warning" | "neutral" }) {
  return (
    <div className={cn("rounded-xl border p-3", tone === "danger" ? "border-rust-400/40 bg-rust-600/15" : tone === "warning" ? "border-amber-400/30 bg-amber-400/10" : "border-white/10 bg-white/[0.06]")}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-linen-400">{label}</p>
      <p className="mt-2 font-mono text-2xl font-medium tabular-nums text-white">{value}</p>
      <p className="mt-1 text-[11px] leading-4 text-linen-400">{detail}</p>
    </div>
  );
}

function AttentionQueue({ data }: { data: IntelligenceOverviewResponse }) {
  return (
    <Panel
      title="Command queue"
      description="The next tickets supervisors should inspect, ordered by SLA, criticality, escalation risk, ownership, and operational score."
      icon={<ListChecks className="h-4 w-4" />}
      data-intelligence-section="attention-queue"
      action={<Link href="/tickets" className="inline-flex items-center gap-1 text-xs font-semibold text-semantic-primary hover:underline">Open All Tickets <ArrowRight className="h-3.5 w-3.5" /></Link>}
    >
      {data.attention_queue.length === 0 ? (
        <EmptyPanel title="No active exceptions" description="No ticket in the current activity window requires elevated attention." />
      ) : (
        <ol className="space-y-2">
          {data.attention_queue.slice(0, 10).map((ticket, index) => (
            <AttentionRow key={ticket.ticket_id} ticket={ticket} index={index} />
          ))}
        </ol>
      )}
    </Panel>
  );
}

function AttentionRow({ ticket, index }: { ticket: IntelligenceAttentionTicket; index: number }) {
  const severe = ticket.sla.status === "breached" || ticket.priority.toLowerCase() === "p1";
  return (
    <li>
      <Link
        href={`/tickets/${ticket.ticket_id}`}
        className={cn(
          "grid min-w-0 grid-cols-[2rem_minmax(0,1fr)] gap-3 rounded-xl border p-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] sm:grid-cols-[2rem_minmax(0,1fr)_auto]",
          severe ? "border-rust-400/35 bg-[var(--color-danger-soft)] hover:border-rust-400/60" : "border-linen-300 hover:border-linen-500 hover:bg-linen-100",
        )}
      >
        <span className={cn("grid h-8 w-8 place-items-center rounded-lg text-xs font-semibold", severe ? "bg-semantic-danger text-white" : "bg-ink-700 text-white")}>{index + 1}</span>
        <span className="min-w-0">
          <span className="flex min-w-0 flex-wrap items-center gap-1.5">
            <Badge variant={severe ? "danger" : ticket.sla.status === "at_risk" ? "warning" : "neutral"}>{ticket.priority}</Badge>
            {ticket.reasons.slice(0, 3).map((reason) => <Badge key={reason} variant={reason === "SLA breached" || reason === "Critical priority" ? "danger" : reason === "SLA at risk" || reason === "Unassigned" ? "warning" : "neutral"}>{reason}</Badge>)}
          </span>
          <ListText text={ticket.subject} lines={2} className="mt-2 text-sm font-semibold leading-5 text-ink-700" />
          <ListText text={`${ticket.category || "Uncategorized"} · ${formatHours(ticket.age_hours)} open · ${formatHours(ticket.dormant_hours)} since activity`} lines={2} className="mt-1 text-xs leading-5 text-ink-500" />
        </span>
        <span className="col-start-2 flex items-end justify-between gap-3 sm:col-start-3 sm:block sm:text-right">
          <span><strong className="block font-mono text-base tabular-nums text-ink-700">{ticket.priority_score}</strong><span className="text-[10px] uppercase tracking-wide text-ink-400">priority</span></span>
          <span className="sm:mt-3 sm:block"><strong className={cn("block text-xs tabular-nums", ticket.sla.status === "breached" ? "text-semantic-danger" : "text-ink-600")}>{ticket.sla.status === "breached" ? `${formatHours(ticket.sla.overdue_hours)} overdue` : `${formatHours(ticket.sla.remaining_hours)} left`}</strong><span className="text-[10px] text-ink-400">{ticket.sla.target_source === "provider_due_at" ? "Provider SLA" : "Policy SLA"}</span></span>
        </span>
      </Link>
    </li>
  );
}

function AgeAndFlowPanel({ data }: { data: IntelligenceOverviewResponse }) {
  const bands = [
    ["Under 24h", data.age_bands.under_24h],
    ["1–3 days", data.age_bands.one_to_three_days],
    ["4–7 days", data.age_bands.four_to_seven_days],
    ["Over 7 days", data.age_bands.over_seven_days],
  ] as const;
  const max = Math.max(1, ...bands.map(([, value]) => value));
  return (
    <Panel title="Backlog age & flow" description="Age distribution of active open work and demand movement in the selected window." icon={<BarChart3 className="h-4 w-4" />} data-intelligence-section="age-flow">
      <div className="grid grid-cols-3 gap-2">
        <CompactMetric label="Created" value={data.flow.created} icon={<TrendingUp className="h-3.5 w-3.5" />} />
        <CompactMetric label="Resolved" value={data.flow.resolved} icon={<TrendingDown className="h-3.5 w-3.5" />} />
        <CompactMetric label="Net" value={withSign(data.flow.net_change)} icon={<Activity className="h-3.5 w-3.5" />} warning={data.flow.net_change > 0} />
      </div>
      <div className="mt-5 space-y-3">
        {bands.map(([label, value], index) => (
          <div key={label} className="grid grid-cols-[5.5rem_minmax(0,1fr)_2.5rem] items-center gap-3 text-xs">
            <span className="text-ink-500">{label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-linen-300"><div className={cn("h-full rounded-full", index === bands.length - 1 ? "bg-semantic-warning" : "bg-semantic-primary")} style={{ width: `${(value / max) * 100}%` }} /></div>
            <span className="text-right font-mono tabular-nums text-ink-600">{value}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function CompactMetric({ label, value, icon, warning = false }: { label: string; value: number | string; icon: ReactNode; warning?: boolean }) {
  return (
    <div className={cn("rounded-xl border p-3", warning ? "border-amber-400/40 bg-[var(--color-warning-soft)]" : "border-linen-300 bg-linen-100")}>
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400">{icon}{label}</div>
      <p className="mt-2 font-mono text-xl tabular-nums text-ink-700">{value}</p>
    </div>
  );
}

function StaleBacklogPanel({ data }: { data: IntelligenceOverviewResponse }) {
  const stale = data.stale_backlog;
  return (
    <Panel
      title="Backlog hygiene"
      description={`Open tickets with no provider activity inside the ${data.scope.window_days}-day operating window. Tracked separately, never mixed into live risk.`}
      icon={<Archive className="h-4 w-4" />}
      data-intelligence-section="stale-backlog"
      action={<Badge variant={stale.count ? "warning" : "success"} dot>{stale.count.toLocaleString()} isolated</Badge>}
    >
      {stale.count === 0 ? (
        <EmptyPanel title="No stale open backlog" description="Every open ticket has activity inside the selected window." />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2">
            <CompactMetric label="Critical stale" value={stale.p1_count} icon={<Siren className="h-3.5 w-3.5" />} warning={stale.p1_count > 0} />
            <CompactMetric label="Unassigned stale" value={stale.unassigned_count} icon={<UserRoundX className="h-3.5 w-3.5" />} warning={stale.unassigned_count > 0} />
          </div>
          <Alert variant="info" title="Protected operational scope" className="text-xs">
            These tickets stay discoverable in All Tickets, but do not inflate current SLA, trend, workload, or systemic signals.
          </Alert>
          <div className="space-y-2">
            {stale.items.slice(0, 5).map((ticket) => (
              <Link key={ticket.ticket_id} href={`/tickets/${ticket.ticket_id}`} className="flex min-w-0 items-start justify-between gap-3 rounded-xl border border-linen-300 p-3 transition-colors hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
                <span className="min-w-0"><ListText text={ticket.subject} lines={2} className="text-xs font-semibold leading-5 text-ink-700" /><span className="mt-1 flex flex-wrap gap-1.5"><Badge>{ticket.priority}</Badge>{ticket.is_unassigned && <Badge variant="warning">Unassigned</Badge>}</span></span>
                <span className="shrink-0 text-right text-[10px] leading-4 text-ink-400"><strong className="block font-mono text-xs tabular-nums text-ink-600">{ticket.dormant_days == null ? "Unknown" : `${Math.round(ticket.dormant_days).toLocaleString()}d`}</strong>dormant</span>
              </Link>
            ))}
          </div>
          <Link href="/tickets" className="inline-flex items-center gap-1 text-xs font-semibold text-semantic-primary hover:underline">Review in All Tickets <ArrowRight className="h-3.5 w-3.5" /></Link>
        </div>
      )}
    </Panel>
  );
}

function WorkloadPanel({ query }: { query: UseQueryResult<IntelWorkloadResponse, Error> }) {
  const agents = query.data?.agents ?? [];
  const maxOpen = Math.max(1, ...agents.map((agent) => agent.open_tickets));
  return (
    <Panel title="Assignment balance" description={query.data?.workforce_source === "provider" ? "Authoritative provider-agent assignments and completion outcomes in the same activity window." : "Active Tickety assignments and completion outcomes in the same activity window."} icon={<Users className="h-4 w-4" />}>
      {query.isLoading ? <PanelLoading /> : query.isError ? <PanelError title="Workload unavailable" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : agents.length === 0 ? <EmptyPanel title="No active agent roster" description="No active agents or supervisors are available for workload analysis." /> : (
        <div className="space-y-3">
          <SamplingNotice analyzed={query.data!.analyzed_users} total={query.data!.total_users} subject="active agents" />
          <div className="flex flex-wrap gap-2"><Badge variant="info">{query.data!.assigned_users} of {query.data!.total_users} agents assigned</Badge><Badge>{query.data!.total_open_assignments} active assignments</Badge></div>
          {query.data!.unmapped_open_assignments > 0 && <Alert variant="warning" title="Provider directory coverage gap" className="text-xs">{query.data!.unmapped_open_assignments} active assignment{query.data!.unmapped_open_assignments === 1 ? "" : "s"} reference provider agents missing from the current directory projection.</Alert>}
          {agents.slice(0, 10).map((agent) => (
            <article key={agent.user_id} className="rounded-xl border border-linen-300 p-3">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0"><ListText text={agent.name} lines={2} className="text-sm font-semibold leading-5 text-ink-700" /><ListText text={`${agent.source === "provider" ? agent.group_names.slice(0, 2).join(" · ") || agent.title || "Provider agent" : `Tier ${agent.tier}`} · ${agent.total_resolved} resolved · ${agent.avg_resolution_hours ? `${agent.avg_resolution_hours}h avg` : "no completion sample"}`} lines={2} className="mt-0.5 text-xs leading-5 text-ink-400" /></div>
                <Badge variant={agent.load_status === "overloaded" ? "danger" : agent.load_status === "high" ? "warning" : "success"} dot>{agent.open_tickets} open</Badge>
              </div>
              <div className="mt-3 flex items-center gap-3"><div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-linen-300"><div className={cn("h-full rounded-full", agent.load_status === "overloaded" ? "bg-semantic-danger" : agent.load_status === "high" ? "bg-semantic-warning" : "bg-semantic-success")} style={{ width: `${(agent.open_tickets / maxOpen) * 100}%` }} /></div>{agent.p1_open_tickets > 0 && <span className="text-[10px] font-semibold text-semantic-danger">{agent.p1_open_tickets} P1</span>}</div>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}

function AccountHealthPanel({ windowDays }: { windowDays: WindowDays }) {
  const [reporter, setReporter] = useState("");
  const [activeReporter, setActiveReporter] = useState("");
  const query = useQuery<AccountHealth>({
    queryKey: ["intelligence", "health", activeReporter, windowDays],
    queryFn: () => api.getIntelHealthForWindow(activeReporter, windowDays),
    enabled: Boolean(activeReporter),
  });
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = reporter.trim();
    if (value) setActiveReporter(value);
  };
  return (
    <Panel title="Requester health" description={`Service experience for one requester inside the ${windowDays}-day activity window.`} icon={<Gauge className="h-4 w-4" />}>
      <form onSubmit={submit} className="flex min-w-0 gap-2">
        <label className="relative min-w-0 flex-1"><span className="sr-only">Reporter or customer</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" /><input className="input-base input-search h-10 w-full" value={reporter} onChange={(event) => setReporter(event.target.value)} placeholder="Reporter or customer" /></label>
        <Button type="submit" size="sm" disabled={!reporter.trim()}>Check</Button>
      </form>
      <div className="mt-4">
        {!activeReporter ? <EmptyPanel title="Choose a requester" description="Search an exact reporter identifier to inspect current experience risk." /> : query.isLoading ? <PanelLoading rows={2} /> : query.isError ? <PanelError title="No current requester history" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : query.data ? <AccountHealthResult data={query.data} /> : null}
      </div>
    </Panel>
  );
}

function AccountHealthResult({ data }: { data: AccountHealth }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4"><div className="grid h-20 w-20 shrink-0 place-items-center rounded-full border-[8px] border-linen-300"><span className="font-mono text-xl font-semibold tabular-nums text-ink-700">{data.health_score}</span></div><div className="min-w-0"><Badge variant={data.churn_risk === "high" ? "danger" : data.churn_risk === "medium" ? "warning" : "success"} dot>{data.churn_risk} experience risk</Badge><p className="mt-2 text-sm text-ink-600">{data.open} open · {data.resolved} resolved · {data.total} active tickets</p><p className="mt-1 text-xs leading-5 text-ink-500">Average escalation risk {data.avg_escalation_risk} · negative sentiment {(data.negative_sentiment_ratio * 100).toFixed(0)}%</p></div></div>
      <SamplingNotice analyzed={data.analyzed_tickets} total={data.total} />
    </div>
  );
}

function TrendsPanel({ query }: { query: UseQueryResult<IntelTrendsResponse, Error> }) {
  const data = query.data;
  const maxCategory = data ? Math.max(1, ...Object.values(data.by_category)) : 1;
  return (
    <Panel title="Demand mix" description="Category, sentiment, and recurring language in the current activity window." icon={<TrendingUp className="h-4 w-4" />}>
      {query.isLoading ? <PanelLoading /> : query.isError ? <PanelError title="Demand trends unavailable" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : !data || data.total_tickets === 0 ? <EmptyPanel title="No current trend signal" description="No eligible ticket activity exists inside this window." /> : (
        <div className="space-y-5">
          <SamplingNotice analyzed={data.analyzed_tickets} total={data.total_tickets} />
          <div className="space-y-3">{Object.entries(data.by_category).slice(0, 8).map(([category, count]) => <div key={category} className="grid min-w-0 grid-cols-[minmax(6rem,8rem)_minmax(3rem,1fr)_2.5rem] items-center gap-3 text-xs"><ListText text={category} lines={2} className="text-ink-600" /><div className="h-2 overflow-hidden rounded-full bg-linen-300"><div className="h-full rounded-full bg-semantic-primary" style={{ width: `${(count / maxCategory) * 100}%` }} /></div><span className="text-right font-mono tabular-nums text-ink-500">{count}</span></div>)}</div>
          <div className="grid gap-4 sm:grid-cols-2"><div><h3 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">Sentiment</h3><div className="mt-2 flex flex-wrap gap-1.5">{Object.entries(data.by_sentiment).slice(0, 8).map(([sentiment, count]) => <Badge key={sentiment}>{sentiment}: {count}</Badge>)}</div></div><div><h3 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">Recurring terms</h3><div className="mt-2 flex flex-wrap gap-1.5">{data.top_terms.slice(0, 10).map(([term, count]) => <Badge key={term} variant="info">{term} · {count}</Badge>)}</div></div></div>
        </div>
      )}
    </Panel>
  );
}

function SystemicPanel({ query }: { query: UseQueryResult<SystemicIssuesResponse, Error> }) {
  const data = query.data;
  return (
    <Panel title="Systemic issue radar" description="Related current tickets that may share a root cause or business impact." icon={<Radar className="h-4 w-4" />}>
      {query.isLoading ? <PanelLoading /> : query.isError ? <PanelError title="Systemic analysis unavailable" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : !data || data.clusters.length === 0 ? <EmptyPanel title="No current systemic clusters" description="No related pattern met the detection threshold inside this activity window." /> : (
        <div className="space-y-3">
          <SamplingNotice analyzed={data.analyzed_tickets} total={data.total_tickets} />
          {data.clusters.slice(0, 6).map((cluster) => (
            <article key={cluster.cluster_id} className="rounded-xl border border-linen-300 p-4">
              <div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap gap-1.5"><Badge variant="info" icon={<Layers3 className="h-3 w-3" />}>{cluster.ticket_count} related</Badge><Badge variant={cluster.business_impact_score >= 70 ? "danger" : "warning"}>Impact {Math.round(cluster.business_impact_score)}</Badge></div><ListText text={cluster.samples[0] || cluster.cluster_id} lines={2} className="mt-2 text-sm font-semibold leading-5 text-ink-700" /></div>{cluster.ticket_ids[0] && <Link href={`/tickets/${cluster.ticket_ids[0]}`} aria-label={`Open evidence for ${cluster.cluster_id}`} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-400 transition-colors hover:bg-linen-200 hover:text-ink-700"><ArrowRight className="h-4 w-4" /></Link>}</div>
              <div className="mt-3 flex flex-wrap gap-1.5">{cluster.shared_keywords.slice(0, 8).map((keyword) => <Badge key={keyword}>{keyword}</Badge>)}</div>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}

function Panel({ title, description, icon, children, action, className, ...props }: { title: string; description?: string; icon: ReactNode; children: ReactNode; action?: ReactNode; className?: string; "data-intelligence-section"?: string }) {
  return (
    <section className={cn("min-w-0 overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm", className)} {...props}>
      <div className="flex min-w-0 flex-col gap-3 border-b border-linen-400 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5"><div className="flex min-w-0 gap-3"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-linen-200 text-ink-500">{icon}</span><div className="min-w-0"><h2 className="text-sm font-semibold text-ink-700">{title}</h2>{description && <p className="mt-1 break-words text-xs leading-5 text-ink-500 [overflow-wrap:anywhere]">{description}</p>}</div></div>{action && <div className="min-w-0 shrink-0">{action}</div>}</div>
      <div className="min-w-0 p-4 sm:p-5">{children}</div>
    </section>
  );
}

function PanelLoading({ rows = 4 }: { rows?: number }) {
  return <div className="space-y-3" aria-label="Loading intelligence"><Skeleton className="h-16 w-full" />{Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="h-12 w-full" />)}</div>;
}

function PanelError({ title, onRetry, retrying }: { title: string; onRetry: () => void; retrying: boolean }) {
  return <ErrorState className="min-h-48" title={title} description="This signal could not be refreshed. Other cockpit panels remain independent." onRetry={onRetry} retrying={retrying} />;
}

function EmptyPanel({ title, description }: { title: string; description: string }) {
  return <EmptyState className="min-h-40 border-0 bg-transparent px-3 py-6" icon={<ShieldCheck className="h-5 w-5" />} title={title} description={description} />;
}

function SamplingNotice({ analyzed, total, subject = "tickets" }: { analyzed: number; total: number; subject?: string }) {
  if (analyzed >= total) return null;
  return <Alert variant="warning" title="Sampled result" className="mb-4 text-xs">Calculated from {analyzed.toLocaleString()} of {total.toLocaleString()} {subject}.</Alert>;
}

function formatHours(hours: number) {
  if (!Number.isFinite(hours)) return "unknown";
  if (hours < 1) return "<1h";
  if (hours < 24) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

function withSign(value: number) {
  return value > 0 ? `+${value}` : String(value);
}
