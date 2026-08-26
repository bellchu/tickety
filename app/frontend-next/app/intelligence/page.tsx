"use client";

import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";
import { useIsFetching, useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Archive,
  ArrowRight,
  BarChart3,
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Gauge,
  Layers3,
  ListChecks,
  MessageSquare,
  Play,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Siren,
  Sparkles,
  Timer,
  TrendingDown,
  TrendingUp,
  UserRoundX,
  Users,
  Waypoints,
} from "lucide-react";
import { Alert, Badge, Button, Dialog, EmptyState, ErrorState, ListText, Skeleton, type BadgeVariant } from "@/components/ui";
import { PageFrame, PageHeader, SummaryStrip } from "@/components/layout/PageLayout";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence, isDemoContext } from "@/lib/auth";
import { formatLocalDateTime } from "@/lib/date-time";
import type {
  AccountHealth,
  IntelligenceAttentionTicket,
  IntelligenceOverviewResponse,
  IntelTrendsResponse,
  IntelWorkloadResponse,
  LevelZeroStudy,
  ServiceQualityResponse,
  SlaMonitoringItem,
  SlaMonitoringResponse,
  SystemicIssuesResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const WINDOWS = [7, 30, 90] as const;
type WindowDays = (typeof WINDOWS)[number];

interface TicketEvidenceItem {
  key: string;
  ticketId: string;
  subject: string;
  badges?: Array<{ label: string; variant?: BadgeVariant }>;
  detail?: string;
}

interface TicketEvidenceSelection {
  title: string;
  description: string;
  items: TicketEvidenceItem[];
  expectedCount?: number;
  truncated?: boolean;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  scopeTruncated?: boolean;
  scopeAnalyzed?: number;
  scopeTotal?: number;
}

interface AssigneeEvidenceRequest {
  name: string;
  id: string | null;
  source: SlaMonitoringItem["assignee_source"];
  ticketCount: number;
  clockCount: number;
}

interface SlaAssigneeGroup {
  key: string;
  id: string | null;
  name: string;
  source: SlaMonitoringItem["assignee_source"];
  ticketCount: number;
  clockCount: number;
}

function slaAssigneeKey(source: SlaMonitoringItem["assignee_source"], id: string | null) {
  return JSON.stringify([source, id]);
}

function groupSlaBreachesByAssignee(
  summaries: SlaMonitoringResponse["by_assignee"],
): SlaAssigneeGroup[] {
  return summaries.map((summary) => {
    const key = slaAssigneeKey(summary.assignee_source, summary.assignee_id);
    return {
      key,
      id: summary.assignee_id,
      name: summary.assignee_name || "Unassigned or unmapped",
      source: summary.assignee_source,
      ticketCount: summary.breached_ticket_count,
      clockCount: summary.breached_clock_count,
    };
  }).sort((left, right) => (
    right.ticketCount - left.ticketCount || left.name.localeCompare(right.name)
  ));
}

function slaEvidenceItems(items: SlaMonitoringItem[]): TicketEvidenceItem[] {
  return items.map((item) => ({
    key: `${item.ticket_id}-${item.metric}-${item.status}-${item.breach_state || "current"}`,
    ticketId: item.ticket_id,
    subject: item.subject,
    badges: [
      { label: item.priority, variant: item.status === "breached" ? "danger" : "warning" },
      { label: item.metric === "first_response" ? "First response" : "Resolution" },
      ...(item.breach_state ? [{ label: item.breach_state, variant: item.breach_state === "active" ? "danger" as const : "neutral" as const }] : []),
    ],
    detail: `${item.assignee_name || "Unassigned"} · due ${formatLocalDateTime(item.due_at)} · ${item.status === "approaching" ? `${formatHours(item.remaining_hours)} left` : `${formatHours(item.overdue_hours)} overdue`}`,
  }));
}

function attentionEvidenceItems(items: IntelligenceAttentionTicket[]): TicketEvidenceItem[] {
  return items.map((item) => ({
    key: item.ticket_id,
    ticketId: item.ticket_id,
    subject: item.subject,
    badges: [
      { label: item.priority, variant: item.priority.toLowerCase() === "p1" || item.priority.toLowerCase() === "urgent" ? "danger" : "neutral" },
      ...(item.status ? [{ label: item.status }] : []),
    ],
    detail: item.reasons.join(" · "),
  }));
}

function useAssigneeBreachEvidence(windowDays: number) {
  const [evidence, setEvidence] = useState<TicketEvidenceSelection | null>(null);
  const requestVersion = useRef(0);

  const showEvidence = (selection: TicketEvidenceSelection) => {
    requestVersion.current += 1;
    setEvidence(selection);
  };
  const closeEvidence = () => {
    requestVersion.current += 1;
    setEvidence(null);
  };
  const loadAssigneeEvidence = async (request: AssigneeEvidenceRequest) => {
    const version = ++requestVersion.current;
    const title = `${request.name} · breached tickets`;
    const description = `${request.ticketCount.toLocaleString()} unique ticket${request.ticketCount === 1 ? "" : "s"} across ${request.clockCount.toLocaleString()} breached SLA clock${request.clockCount === 1 ? "" : "s"}.`;
    setEvidence({ title, description, items: [], expectedCount: request.clockCount, loading: true });
    try {
      const result = await api.getIntelSlaAssigneeEvidence(
        windowDays,
        request.source ?? "unmapped",
        request.id,
      );
      if (requestVersion.current !== version) return;
      const sampledDescription = `In the analyzed sample, ${result.breached_ticket_count.toLocaleString()} unique ticket${result.breached_ticket_count === 1 ? "" : "s"} carried ${result.breached_clock_count.toLocaleString()} breached SLA clock${result.breached_clock_count === 1 ? "" : "s"}.`;
      setEvidence({
        title,
        description: result.scope.truncated ? sampledDescription : `${result.breached_ticket_count.toLocaleString()} unique ticket${result.breached_ticket_count === 1 ? "" : "s"} across ${result.breached_clock_count.toLocaleString()} breached SLA clock${result.breached_clock_count === 1 ? "" : "s"}.`,
        items: slaEvidenceItems(result.items),
        expectedCount: result.breached_clock_count,
        truncated: result.items_truncated || result.items.length < result.breached_clock_count,
        scopeTruncated: result.scope.truncated,
        scopeAnalyzed: result.scope.analyzed_tickets,
        scopeTotal: result.scope.total_tickets,
      });
    } catch {
      if (requestVersion.current !== version) return;
      setEvidence({
        title,
        description,
        items: [],
        error: true,
        onRetry: () => { void loadAssigneeEvidence(request); },
      });
    }
  };

  return {
    evidence,
    showEvidence,
    closeEvidence,
    openAssigneeEvidence: (request: AssigneeEvidenceRequest) => { void loadAssigneeEvidence(request); },
  };
}

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
      eyebrow="Tickety OPS Tower"
      icon={<Sparkles className="h-4 w-4" />}
      title="OPS Tower"
      description={<><span className="font-medium text-ink-600">Command the Queue. The intelligence behind every ticket.</span>{" "}A decision-first view of current service risk, queue health, team capacity, and emerging demand. Legacy records are isolated from live operational signals.</>}
      meta="Powered by CommandIQ. Recommendations are advisory and always link back to source tickets for human review."
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
  const qualityQuery = useQuery({
    queryKey: ["intelligence", "service-quality", windowDays],
    queryFn: () => api.getIntelServiceQuality(windowDays),
  });
  const slaMonitoringQuery = useQuery({
    queryKey: ["intelligence", "sla-monitoring", windowDays],
    queryFn: () => api.getIntelSlaMonitoring(windowDays),
  });

  const refreshAll = () => queryClient.invalidateQueries({ queryKey: ["intelligence"] });
  const overview = overviewQuery.data;
  const revealSection = (targetSelector: string, detailsSelector?: string) => {
    if (detailsSelector) {
      const details = document.querySelector<HTMLDetailsElement>(detailsSelector);
      if (details) details.open = true;
    }
    window.requestAnimationFrame(() => {
      document.querySelector(targetSelector)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

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
          density="compact"
          title="Operational posture unavailable"
          description="The primary cockpit signal could not be loaded. Supporting panels remain independently refreshable."
          onRetry={() => void overviewQuery.refetch()}
          retrying={overviewQuery.isFetching}
        />
      ) : (
        <>
          <div data-intelligence-section="operational-posture">
            <OperationalPosture
              data={overview}
              onShowAttention={() => revealSection('[data-intelligence-section="attention-queue"]')}
              onShowSla={() => revealSection('[data-intelligence-section="sla-monitoring"]', "#service-assurance")}
            />
          </div>
          {overview.scope.truncated && (
            <Alert variant="warning" title="Operational analysis is sampled">
              Exception counts are based on {overview.scope.analyzed_tickets.toLocaleString()} of {overview.scope.active_open_tickets.toLocaleString()} active tickets. Scope totals remain exact.
            </Alert>
          )}
          <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(22rem,0.85fr)]">
            <div id="attention-queue" data-intelligence-section="attention-queue" className="scroll-mt-24">
              <AttentionQueue data={overview} />
            </div>
            <details className="group min-w-0 rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
              <CockpitDisclosureSummary
                title="Backlog context"
                description="Age, flow, and stale records that support queue decisions."
                status="View details"
              />
              <div className="min-w-0 space-y-6 border-t border-linen-400 p-4">
                <div data-intelligence-section="age-flow"><AgeAndFlowPanel data={overview} /></div>
                <div data-intelligence-section="stale-backlog"><StaleBacklogPanel data={overview} /></div>
              </div>
            </details>
          </div>
        </>
      )}

      <div role="group" aria-label="Supporting intelligence views" className="space-y-4">
        <details data-intelligence-section="service-assurance" id="service-assurance" className="group rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
          <CockpitDisclosureSummary
            title="Service assurance"
            description={`Human-review guardrails for routing, support level, customer friction, request quality, and SLA exposure in the last ${windowDays} days.`}
            status={qualityQuery.isError || slaMonitoringQuery.isError ? "Needs retry" : qualityQuery.isLoading || slaMonitoringQuery.isLoading ? "Loading" : "Ready"}
            warning={qualityQuery.isError || slaMonitoringQuery.isError}
          />
          <div className="space-y-4 border-t border-linen-400 p-4 sm:p-5">
            <ServiceQualityPanels key={`quality-${windowDays}`} query={qualityQuery} />
            <SlaMonitoringPanel key={`sla-${windowDays}`} query={slaMonitoringQuery} />
          </div>
        </details>

        <details data-intelligence-section="team-capacity" className="group rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
          <CockpitDisclosureSummary
            title="Team capacity"
            description={`Current assignments and delivery outcomes within the last ${windowDays} days.`}
            status={workloadQuery.isError || slaMonitoringQuery.isError ? "Needs retry" : workloadQuery.isLoading || slaMonitoringQuery.isLoading ? "Loading" : "Ready"}
            warning={workloadQuery.isError || slaMonitoringQuery.isError}
          />
          <div className="grid min-w-0 gap-6 border-t border-linen-400 p-4 sm:p-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]">
            <WorkloadPanel key={`workload-${windowDays}`} query={workloadQuery} slaQuery={slaMonitoringQuery} windowDays={windowDays} />
            <AccountHealthPanel windowDays={windowDays} />
          </div>
        </details>

        <details data-intelligence-section="demand-patterns" className="group rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
          <CockpitDisclosureSummary
            title="Demand and systemic patterns"
            description={`Only tickets active in the selected ${windowDays}-day window contribute to these signals.`}
            status={trendsQuery.isError || systemicQuery.isError ? "Needs retry" : trendsQuery.isLoading || systemicQuery.isLoading ? "Loading" : "Ready"}
            warning={trendsQuery.isError || systemicQuery.isError}
          />
          <div className="grid min-w-0 gap-6 border-t border-linen-400 p-4 sm:p-5 lg:grid-cols-2">
            <TrendsPanel query={trendsQuery} />
            <SystemicPanel key={`systemic-${windowDays}`} query={systemicQuery} />
          </div>
        </details>

        <details data-intelligence-section="automation-discovery" className="group rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
          <CockpitDisclosureSummary
            title="Automation discovery"
            description="A deliberate historical study, kept separate from the live operating window and never rerun automatically."
            status="On demand"
          />
          <div className="border-t border-linen-400 p-4 sm:p-5">
            <LevelZeroStudyPanel />
          </div>
        </details>
      </div>
    </PageFrame>
  );
}

function CockpitDisclosureSummary({
  title,
  description,
  status,
  warning = false,
}: {
  title: string;
  description: string;
  status: string;
  warning?: boolean;
}) {
  return (
    <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 rounded-2xl px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] sm:px-5 [&::-webkit-details-marker]:hidden">
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-ink-700">{title}</span>
        <span className="mt-1 block break-words text-xs leading-5 text-ink-500 [overflow-wrap:anywhere]">{description}</span>
      </span>
      <span className="flex shrink-0 items-center gap-2">
        <Badge variant={warning ? "warning" : "neutral"} dot={warning}>{status}</Badge>
        <ChevronDown className="h-4 w-4 text-ink-400 transition-transform group-open:rotate-180" aria-hidden="true" />
      </span>
    </summary>
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

function OperationalPosture({ data, onShowAttention, onShowSla }: { data: IntelligenceOverviewResponse; onShowAttention: () => void; onShowSla: () => void }) {
  const [evidence, setEvidence] = useState<TicketEvidenceSelection | null>(null);
  const config = postureConfig[data.posture];
  const PostureIcon = config.icon;
  const immediateActions = data.posture_metrics.sla_breached
    + data.posture_metrics.p1_open
    + data.posture_metrics.escalation_prone;
  const showUnassigned = () => setEvidence({
    title: "Unassigned active tickets",
    description: "Active tickets in the selected activity window that do not have a Tickety OPS Tower or provider owner.",
    items: attentionEvidenceItems(data.unassigned_evidence.items),
    expectedCount: data.posture_metrics.unassigned_open,
    truncated: data.unassigned_evidence.items_truncated,
  });
  return (
    <>
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
          <DarkMetric label="Act now" value={immediateActions} detail="critical signals" tone={immediateActions ? "danger" : "neutral"} onClick={onShowAttention} />
          <DarkMetric label="SLA breach" value={data.posture_metrics.sla_breached} detail={`${data.posture_metrics.sla_at_risk} approaching`} tone={data.posture_metrics.sla_breached ? "danger" : data.posture_metrics.sla_at_risk ? "warning" : "neutral"} onClick={onShowSla} />
          <DarkMetric label="Unassigned" value={data.posture_metrics.unassigned_open} detail="ownership gaps" tone={data.posture_metrics.unassigned_open ? "warning" : "neutral"} onClick={showUnassigned} />
          <DarkMetric label="Net flow" value={withSign(data.flow.net_change)} detail={`${data.flow.created} in · ${data.flow.resolved} out`} tone={data.flow.net_change > 0 ? "warning" : "neutral"} />
        </div>
      </div>
      </section>
      <TicketEvidenceDialog selection={evidence} onClose={() => setEvidence(null)} />
    </>
  );
}

function DarkMetric({ label, value, detail, tone, onClick }: { label: string; value: number | string; detail: string; tone: "danger" | "warning" | "neutral"; onClick?: () => void }) {
  const interactive = Boolean(onClick && Number(value) > 0);
  const className = cn("rounded-xl border p-3 text-left", tone === "danger" ? "border-rust-400/40 bg-rust-600/15" : tone === "warning" ? "border-amber-400/30 bg-amber-400/10" : "border-white/10 bg-white/[0.06]", interactive && "group transition-colors hover:border-white/40 hover:bg-white/[0.1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70");
  const content = <>
      <span className="block text-[10px] font-semibold uppercase tracking-[0.1em] text-linen-400">{label}</span>
      <span className="mt-2 block font-mono text-2xl font-medium tabular-nums text-white">{value}</span>
      <span className="mt-1 block text-[11px] leading-4 text-linen-400">{detail}</span>
      {interactive && <span className="mt-2 inline-flex items-center gap-1 text-[10px] font-semibold text-white">View details <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></span>}
    </>;
  return interactive ? <button type="button" className={className} onClick={onClick} aria-label={`${label}: ${value}. View details`}>{content}</button> : <div className={className}>{content}</div>;
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

function ServiceQualityPanels({ query }: { query: UseQueryResult<ServiceQualityResponse, Error> }) {
  const [evidence, setEvidence] = useState<TicketEvidenceSelection | null>(null);
  if (query.isLoading) {
    return <div className="grid gap-6 lg:grid-cols-2" aria-label="Loading service assurance"><Skeleton className="h-96" /><Skeleton className="h-96" /><Skeleton className="h-96" /><Skeleton className="h-96" /></div>;
  }
  if (query.isError || !query.data) {
    return <ErrorState density="compact" title="Service-quality guardrails unavailable" description="Routing, level, friction, and clarification signals could not be refreshed." onRetry={() => void query.refetch()} retrying={query.isFetching} />;
  }
  const data = query.data;
  const mismatches = data.level_assessments.filter((item) => item.mismatch);
  const openQualityEvidence = (kind: "routing" | "level" | "friction" | "clarification") => {
    if (kind === "routing") {
      const items = data.routing_alerts.map((alert) => ({
        key: alert.ticket_id,
        ticketId: alert.ticket_id,
        subject: alert.subject,
        badges: [
          { label: alert.priority, variant: alert.severity === "high" ? "danger" as const : "warning" as const },
          { label: `${Math.round(alert.profile_confidence * 100)}% group profile` },
        ],
        detail: `${alert.current_group_name} (${alert.group_profile_team}) → review for ${alert.recommended_team}`,
      }));
      setEvidence({
        title: "Possible routing mismatches",
        description: `${data.summary.routing_mismatches.toLocaleString()} ticket${data.summary.routing_mismatches === 1 ? "" : "s"} need human routing review.`,
        items,
        expectedCount: data.summary.routing_mismatches,
        truncated: items.length < data.summary.routing_mismatches,
      });
      return;
    }
    if (kind === "level") {
      const items = mismatches.map((item) => ({
        key: item.ticket_id,
        ticketId: item.ticket_id,
        subject: item.subject,
        badges: [
          { label: item.priority },
          { label: item.mismatch_direction || "Mismatch", variant: item.mismatch_direction === "under-tiered" ? "danger" as const : "warning" as const },
        ],
        detail: `${item.inferred_assigned_name || "Unknown current level"} → ${item.recommended_name}. ${item.basis}`,
      }));
      setEvidence({
        title: "Support-level mismatches",
        description: `${data.summary.level_mismatches.toLocaleString()} ticket${data.summary.level_mismatches === 1 ? "" : "s"} may need a different support level.`,
        items,
        expectedCount: data.summary.level_mismatches,
        truncated: items.length < data.summary.level_mismatches,
      });
      return;
    }
    if (kind === "friction") {
      const items = data.friction_alerts.map((alert) => ({
        key: alert.ticket_id,
        ticketId: alert.ticket_id,
        subject: alert.subject,
        badges: [
          { label: alert.priority },
          { label: `${alert.severity} friction`, variant: alert.severity === "high" ? "danger" as const : "warning" as const },
        ],
        detail: alert.evidence.join(" · "),
      }));
      setEvidence({
        title: "Tickets with customer friction",
        description: `${data.summary.customer_friction.toLocaleString()} ticket${data.summary.customer_friction === 1 ? "" : "s"} show frustration, delay, or excess conversation turns.`,
        items,
        expectedCount: data.summary.customer_friction,
        truncated: items.length < data.summary.customer_friction,
      });
      return;
    }
    const items = data.clarification_alerts.map((alert) => ({
      key: alert.ticket_id,
      ticketId: alert.ticket_id,
      subject: alert.subject,
      badges: [
        { label: alert.priority },
        { label: `Detail ${alert.detail_score}/100`, variant: "warning" as const },
      ],
      detail: alert.suggested_questions[0] ? `Ask next: ${alert.suggested_questions[0]}` : alert.evidence.join(" · "),
    }));
    setEvidence({
      title: "Tickets that need clarification",
      description: `${data.summary.clarification_needed.toLocaleString()} ticket${data.summary.clarification_needed === 1 ? "" : "s"} need more diagnostic detail.`,
      items,
      expectedCount: data.summary.clarification_needed,
      truncated: items.length < data.summary.clarification_needed,
    });
  };
  return (
    <div className="space-y-4">
      {data.scope.truncated && <SamplingNotice analyzed={data.scope.analyzed_tickets} total={data.scope.total_active_tickets} />}
      <Alert variant="info" title="Advisory guardrail — no automatic routing" className="text-xs">
        These signals never reassign, reprioritize, or reply to a ticket. Resolver-team and assigned-level comparisons are confidence-gated against 12 months of completed group history.
      </Alert>
      <SummaryStrip label="Service-quality exceptions">
        <AssuranceMetric label="Possible misroutes" value={data.summary.routing_mismatches} detail={`${data.summary.routing_profiled_tickets} tickets calibrated`} warning={data.summary.routing_mismatches > 0} onClick={() => openQualityEvidence("routing")} />
        <AssuranceMetric label="Level mismatch" value={data.summary.level_mismatches} detail={`${data.summary.assigned_level_profiled_tickets} assigned levels inferred`} warning={data.summary.level_mismatches > 0} onClick={() => openQualityEvidence("level")} />
        <AssuranceMetric label="Customer friction" value={data.summary.customer_friction} detail="frustration, delay, or excess turns" warning={data.summary.customer_friction > 0} onClick={() => openQualityEvidence("friction")} />
        <AssuranceMetric label="Needs clarification" value={data.summary.clarification_needed} detail="insufficient diagnostic detail" warning={data.summary.clarification_needed > 0} onClick={() => openQualityEvidence("clarification")} />
      </SummaryStrip>
      <div className="grid min-w-0 gap-6 xl:grid-cols-2">
        <Panel title="Routing guardrail" description="Flags a likely functional-team mismatch only when the current group has enough consistent historical evidence." icon={<Waypoints className="h-4 w-4" />} action={<Badge variant={data.routing_alerts.length ? "warning" : "success"} dot>{data.routing_alerts.length} alerts</Badge>}>
          {data.routing_alerts.length === 0 ? (
            <EmptyPanel
              title={data.summary.routing_profiled_tickets ? "No calibrated routing mismatch" : "Group calibration not ready"}
              description={data.summary.routing_profiled_tickets ? "Evaluated tickets align with the functional profile of their current group." : "No active ticket has both a supported recommendation and a sufficiently consistent historical group profile yet."}
            />
          ) : (
            <div className="space-y-2">
              {data.routing_alerts.slice(0, 6).map((alert) => (
                <Link key={alert.ticket_id} href={`/tickets/${alert.ticket_id}`} className="block min-w-0 rounded-xl border border-amber-400/35 bg-[var(--color-warning-soft)] p-3 transition-colors hover:border-amber-400/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
                  <div className="flex flex-wrap items-center gap-1.5"><Badge variant={alert.severity === "high" ? "danger" : "warning"}>{alert.priority}</Badge><Badge>{Math.round(alert.profile_confidence * 100)}% group profile</Badge>{!alert.directory_name_available && <Badge variant="warning">Directory name missing</Badge>}</div>
                  <ListText text={alert.subject} lines={2} className="mt-2 text-sm font-semibold leading-5 text-ink-700" />
                  <p className="mt-1 text-xs leading-5 text-ink-500"><strong className="text-ink-600">Current:</strong> {alert.current_group_name} ({alert.group_profile_team}) <ArrowRight className="mx-1 inline h-3 w-3" /> <strong className="text-ink-600">Review for:</strong> {alert.recommended_team}</p>
                  <p className="mt-1 text-[11px] leading-4 text-ink-400">{alert.profile_samples} historical classifications · {formatHours(alert.dormant_hours)} since provider activity</p>
                </Link>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Level 0–3 alignment" description="AI-informed support-level need compared with the current group’s inferred delivery level. Freshservice does not currently define assigned tiers." icon={<Layers3 className="h-4 w-4" />} action={<Badge variant={mismatches.length ? "warning" : "info"}>{mismatches.length} mismatches</Badge>}>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {([0, 1, 2, 3] as const).map((level) => <CompactMetric key={level} label={`Level ${level}`} value={data.level_distribution[String(level) as "0" | "1" | "2" | "3"] ?? 0} icon={level === 0 ? <Bot className="h-3.5 w-3.5" /> : <Layers3 className="h-3.5 w-3.5" />} />)}
          </div>
          <Alert variant="info" title="Assigned level is inferred" className="mt-4 text-xs">Until provider tiers exist, Tickety OPS Tower learns a group’s typical level from completed work and only calls a mismatch when the sample is large and consistent enough.</Alert>
          {mismatches.length === 0 ? <EmptyPanel title="No confident level mismatch" description="No calibrated active ticket is clearly above or below its current group’s inferred level." /> : (
            <div className="mt-4 space-y-2">
              {mismatches.slice(0, 6).map((item) => (
                <Link key={item.ticket_id} href={`/tickets/${item.ticket_id}`} className="flex min-w-0 items-start justify-between gap-3 rounded-xl border border-linen-300 p-3 transition-colors hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
                  <span className="min-w-0"><span className="flex flex-wrap gap-1.5"><Badge variant={item.mismatch_direction === "under-tiered" ? "danger" : "warning"}>{item.mismatch_direction}</Badge><Badge>{item.priority}</Badge></span><ListText text={item.subject} lines={2} className="mt-2 text-xs font-semibold leading-5 text-ink-700" /><ListText text={item.basis} lines={2} className="mt-1 text-[11px] leading-4 text-ink-400" /></span>
                  <span className="shrink-0 text-right text-xs text-ink-500"><strong className="block text-ink-700">{item.inferred_assigned_name}</strong><ArrowRight className="my-1 ml-auto h-3.5 w-3.5" /><strong className="block text-semantic-primary">{item.recommended_name}</strong></span>
                </Link>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Customer friction" description="Requester frustration, long requester-to-agent response gaps, and excessive correspondence cycles." icon={<MessageSquare className="h-4 w-4" />} action={<Badge variant={data.friction_alerts.length ? "warning" : "success"} dot>{data.friction_alerts.length} flagged</Badge>}>
          {data.friction_alerts.length === 0 ? <EmptyPanel title="No friction threshold crossed" description="No analyzed conversation shows a material frustration, delay, or back-and-forth signal." /> : (
            <div className="space-y-2">
              {data.friction_alerts.slice(0, 6).map((alert) => (
                <Link key={alert.ticket_id} href={`/tickets/${alert.ticket_id}`} className="block min-w-0 rounded-xl border border-linen-300 p-3 transition-colors hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
                  <div className="flex flex-wrap gap-1.5"><Badge variant={alert.severity === "high" ? "danger" : "warning"}>{alert.priority}</Badge>{alert.frustration_detected && <Badge variant="warning">Frustration</Badge>}{alert.long_response_gap && <Badge variant="danger">{formatHours(alert.current_unanswered_gap_hours)} waiting</Badge>}{alert.excessive_back_and_forth && <Badge>{alert.public_message_count} messages</Badge>}</div>
                  <ListText text={alert.subject} lines={2} className="mt-2 text-sm font-semibold leading-5 text-ink-700" />
                  <ListText text={alert.evidence.join(" · ")} lines={2} className="mt-1 text-xs leading-5 text-ink-500" />
                </Link>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Clarification needed" description="Finds vague requests before agents lose time guessing, and proposes the missing diagnostic questions." icon={<CircleHelp className="h-4 w-4" />} action={<Badge variant={data.clarification_alerts.length ? "warning" : "success"} dot>{data.clarification_alerts.length} flagged</Badge>}>
          {data.clarification_alerts.length === 0 ? <EmptyPanel title="Requests are actionable" description="No analyzed request is currently below the diagnostic-detail threshold." /> : (
            <div className="space-y-2">
              {data.clarification_alerts.slice(0, 6).map((alert) => (
                <Link key={alert.ticket_id} href={`/tickets/${alert.ticket_id}`} className="block min-w-0 rounded-xl border border-linen-300 p-3 transition-colors hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
                  <div className="flex items-center justify-between gap-2"><Badge variant="warning">{alert.priority}</Badge><span className="font-mono text-[11px] tabular-nums text-ink-400">Detail {alert.detail_score}/100</span></div>
                  <ListText text={alert.subject} lines={2} className="mt-2 text-sm font-semibold leading-5 text-ink-700" />
                  {alert.suggested_questions[0] && <p className="mt-2 rounded-lg bg-linen-200 px-3 py-2 text-xs leading-5 text-ink-600"><strong>Ask next:</strong> {alert.suggested_questions[0]}</p>}
                </Link>
              ))}
            </div>
          )}
        </Panel>
      </div>
      <TicketEvidenceDialog selection={evidence} onClose={() => setEvidence(null)} />
    </div>
  );
}

function AssuranceMetric({ label, value, detail, warning, onClick }: { label: string; value: number; detail: string; warning: boolean; onClick?: () => void }) {
  const className = cn(
    "rounded-xl border p-4 text-left",
    warning ? "border-amber-400/40 bg-[var(--color-warning-soft)]" : "border-linen-300 bg-linen-100",
    onClick && value > 0 && "group cursor-pointer transition-colors hover:border-ink-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2",
  );
  const content = <><span className="block text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</span><span className="mt-2 block font-mono text-2xl tabular-nums text-ink-700">{value}</span><span className="mt-1 block text-[11px] leading-4 text-ink-500">{detail}</span>{onClick && value > 0 && <span className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-semantic-primary">View tickets <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></span>}</>;
  return onClick && value > 0 ? <button type="button" className={className} onClick={onClick} aria-label={`${label}: ${value}. View tickets`}>{content}</button> : <div className={className}>{content}</div>;
}

function SlaCountButton({ value, label, onClick }: { value: number; label: string; onClick: () => void }) {
  if (value === 0) return <span className="font-mono tabular-nums text-ink-400">0</span>;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label}: ${value}. View tickets`}
      className="inline-flex min-h-8 min-w-8 items-center justify-center rounded-md px-2 font-mono font-semibold tabular-nums text-semantic-primary underline decoration-semantic-primary/30 underline-offset-4 transition-colors hover:bg-linen-200 hover:decoration-semantic-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
    >
      {value}
    </button>
  );
}

function SlaMonitoringPanel({ query }: { query: UseQueryResult<SlaMonitoringResponse, Error> }) {
  const [view, setView] = useState<"reactive" | "proactive">("proactive");
  const data = query.data;
  const { evidence, showEvidence, closeEvidence, openAssigneeEvidence } = useAssigneeBreachEvidence(data?.window_days ?? 30);
  const rows = data ? (view === "reactive" ? data.reactive : data.proactive) : [];
  const assigneeGroups = data ? groupSlaBreachesByAssignee(data.by_assignee) : [];
  const openSlaEvidence = (title: string, description: string, items: SlaMonitoringItem[], expectedCount = items.length) => {
    showEvidence({
      title,
      description,
      items: slaEvidenceItems(items),
      expectedCount,
      truncated: items.length < expectedCount,
    });
  };
  const priorityRows = (priority: string, metric: SlaMonitoringItem["metric"], status: "breached" | "approaching") => (
    (status === "breached" ? data?.reactive : data?.proactive)?.filter((item) => item.priority === priority && item.metric === metric) ?? []
  );
  return (
    <Panel title="SLA breach monitoring" description="First-response and resolution clocks by priority, with proactive and reactive drill-down kept separate." icon={<Timer className="h-4 w-4" />} className="scroll-mt-24" data-intelligence-section="sla-monitoring">
      {query.isLoading ? <PanelLoading /> : query.isError || !data ? <PanelError title="SLA monitoring unavailable" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : (
        <div className="space-y-5">
          <SamplingNotice analyzed={data.scope.analyzed_tickets} total={data.scope.total_tickets} />
          <div className="grid gap-2 sm:grid-cols-4">
            <AssuranceMetric label="Approaching" value={data.summary.approaching_breaches} detail="act before due" warning={data.summary.approaching_breaches > 0} onClick={() => openSlaEvidence("Approaching SLA clocks", "Tickets that are close to a measured first-response or resolution deadline.", data.proactive, data.summary.approaching_breaches)} />
            <AssuranceMetric label="Active breach" value={data.summary.active_breaches} detail="currently overdue" warning={data.summary.active_breaches > 0} onClick={() => openSlaEvidence("Active SLA breaches", "Open tickets with a measured first-response or resolution clock currently overdue.", data.reactive.filter((item) => item.breach_state === "active"), data.summary.active_breaches)} />
            <AssuranceMetric label="Historical breach" value={data.summary.historical_breaches} detail="completed after due" warning={data.summary.historical_breaches > 0} onClick={() => openSlaEvidence("Historical SLA breaches", "Completed response or resolution clocks that finished after their deadline.", data.reactive.filter((item) => item.breach_state === "historical"), data.summary.historical_breaches)} />
            <AssuranceMetric label="Unmeasured" value={data.scope.unmeasured_clocks} detail="source evidence unavailable" warning={false} />
          </div>
          <div className="overflow-x-auto rounded-xl border border-linen-300">
            <table className="min-w-[650px] w-full text-xs">
              <thead><tr className="border-b border-linen-300 bg-linen-100 text-left text-[10px] uppercase tracking-[0.1em] text-ink-400"><th className="px-3 py-2">Priority</th><th className="px-3 py-2">First response breached</th><th className="px-3 py-2">First response approaching</th><th className="px-3 py-2">Resolution breached</th><th className="px-3 py-2">Resolution approaching</th></tr></thead>
              <tbody>
                {Object.entries(data.by_priority).sort(([a], [b]) => a.localeCompare(b)).map(([priority, metrics]) => (
                  <tr key={priority} className="border-b border-linen-200 last:border-0">
                    <td className="px-3 py-2 font-semibold text-ink-700">{priority}</td>
                    <td className="px-3 py-1"><SlaCountButton value={metrics.first_response.breached} label={`${priority} first-response breaches`} onClick={() => openSlaEvidence(`${priority} first-response breaches`, `Breached first-response clocks for ${priority} tickets.`, priorityRows(priority, "first_response", "breached"), metrics.first_response.breached)} /></td>
                    <td className="px-3 py-1"><SlaCountButton value={metrics.first_response.approaching} label={`${priority} first-response clocks approaching`} onClick={() => openSlaEvidence(`${priority} first-response clocks approaching`, `First-response clocks approaching their deadline for ${priority} tickets.`, priorityRows(priority, "first_response", "approaching"), metrics.first_response.approaching)} /></td>
                    <td className="px-3 py-1"><SlaCountButton value={metrics.resolution.breached} label={`${priority} resolution breaches`} onClick={() => openSlaEvidence(`${priority} resolution breaches`, `Breached resolution clocks for ${priority} tickets.`, priorityRows(priority, "resolution", "breached"), metrics.resolution.breached)} /></td>
                    <td className="px-3 py-1"><SlaCountButton value={metrics.resolution.approaching} label={`${priority} resolution clocks approaching`} onClick={() => openSlaEvidence(`${priority} resolution clocks approaching`, `Resolution clocks approaching their deadline for ${priority} tickets.`, priorityRows(priority, "resolution", "approaching"), metrics.resolution.approaching)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {assigneeGroups.length > 0 && (
            <section aria-labelledby="sla-by-assignee-title" className="rounded-xl border border-linen-300 bg-linen-100 p-4">
              <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h3 id="sla-by-assignee-title" className="text-sm font-semibold text-ink-700">Breached tickets by assignee</h3>
                  <p className="mt-1 text-xs leading-5 text-ink-500">Counts are unique tickets; a ticket can carry both first-response and resolution breaches.</p>
                </div>
                {data.items_truncated && <Badge variant="warning">Returned evidence capped</Badge>}
              </div>
              <div className="mt-3 grid max-h-80 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
                {assigneeGroups.map((group) => (
                  <button
                    key={group.key}
                    type="button"
                    onClick={() => openAssigneeEvidence({ name: group.name, id: group.id, source: group.source, ticketCount: group.ticketCount, clockCount: group.clockCount })}
                    className="group flex min-w-0 items-center justify-between gap-3 rounded-lg border border-linen-300 bg-linen-50 px-3 py-2.5 text-left transition-colors hover:border-ink-400 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                  >
                    <span className="min-w-0"><span className="block truncate text-xs font-semibold text-ink-700">{group.name}</span><span className="mt-0.5 block text-[10px] text-ink-400">{group.source === "provider" ? "Provider agent" : group.source === "tickety" ? "Tickety OPS Tower agent" : "No mapped owner"} · {group.clockCount} clock{group.clockCount === 1 ? "" : "s"}</span></span>
                    <span className="flex shrink-0 items-center gap-1.5 font-mono text-xs font-semibold tabular-nums text-semantic-danger">{group.ticketCount} ticket{group.ticketCount === 1 ? "" : "s"}<ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></span>
                  </button>
                ))}
              </div>
            </section>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div role="group" aria-label="SLA monitoring view" className="inline-flex rounded-lg border border-linen-400 bg-linen-100 p-1">
              <button type="button" aria-pressed={view === "proactive"} onClick={() => setView("proactive")} className={cn("min-h-8 rounded-md px-3 text-xs font-semibold", view === "proactive" ? "bg-ink-700 text-white" : "text-ink-500 hover:bg-linen-300")}>Approaching ({data.summary.approaching_breaches})</button>
              <button type="button" aria-pressed={view === "reactive"} onClick={() => setView("reactive")} className={cn("min-h-8 rounded-md px-3 text-xs font-semibold", view === "reactive" ? "bg-ink-700 text-white" : "text-ink-500 hover:bg-linen-300")}>Breached ({data.summary.reactive_breaches})</button>
            </div>
            <span className="text-[11px] text-ink-400">Provider deadlines are used when available; policy clocks are labeled explicitly.</span>
          </div>
          {rows.length === 0 ? <EmptyPanel title={view === "proactive" ? "No approaching breach" : "No recorded breach"} description={view === "proactive" ? "No measured first-response or resolution clock is currently inside the proactive risk threshold." : "No measured clock in this window finished or remains past due."} /> : (
            <div className="space-y-3">
              <div className="grid gap-2 lg:grid-cols-2">
                {rows.slice(0, 12).map((item) => <Link key={`${item.ticket_id}-${item.metric}`} href={`/tickets/${item.ticket_id}`} className="flex min-w-0 items-start justify-between gap-3 rounded-xl border border-linen-300 p-3 transition-colors hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"><span className="min-w-0"><span className="flex flex-wrap gap-1.5"><Badge variant={view === "reactive" ? "danger" : "warning"}>{item.priority}</Badge><Badge>{item.metric === "first_response" ? "First response" : "Resolution"}</Badge>{item.breach_state && <Badge>{item.breach_state}</Badge>}</span><ListText text={item.subject} lines={2} className="mt-2 text-xs font-semibold leading-5 text-ink-700" /><span className="mt-1 block text-[10px] text-ink-400">{item.assignee_name || "Unassigned"} · {item.target_source === "provider_due_at" ? "Provider SLA" : "Policy SLA"} · due {formatLocalDateTime(item.due_at)}</span></span><span className={cn("shrink-0 text-right font-mono text-xs tabular-nums", view === "reactive" ? "text-semantic-danger" : "text-semantic-warning")}>{view === "reactive" ? `${formatHours(item.overdue_hours)} overdue` : `${formatHours(item.remaining_hours)} left`}</span></Link>)}
              </div>
              {(rows.length > 12 || data.items_truncated) && <Button variant="ghost" size="sm" onClick={() => openSlaEvidence(view === "reactive" ? "All returned SLA breaches" : "All returned approaching SLA clocks", view === "reactive" ? "Every breached clock returned for the selected activity window." : "Every approaching clock returned for the selected activity window.", rows, view === "reactive" ? data.summary.reactive_breaches : data.summary.approaching_breaches)}>View all {view === "reactive" ? data.summary.reactive_breaches : data.summary.approaching_breaches}</Button>}
            </div>
          )}
        </div>
      )}
      <TicketEvidenceDialog selection={evidence} onClose={closeEvidence} />
    </Panel>
  );
}

function LevelZeroStudyPanel() {
  const [months, setMonths] = useState<6 | 12>(12);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["intelligence", "level-zero-study", months],
    queryFn: () => api.getLevelZeroStudy(months),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const run = useMutation({
    mutationFn: () => api.runLevelZeroStudy(months),
    onSuccess: (study: LevelZeroStudy) => {
      queryClient.setQueryData(["intelligence", "level-zero-study", months], { study });
    },
  });
  const study = query.data?.study;
  return (
    <Panel
      title="Level Zero opportunity study"
      description="One persisted snapshot of resolved work that may have been safely handled through self-service or a future support bot. It never runs on the live refresh cycle."
      icon={<Bot className="h-4 w-4" />}
      action={<div className="flex flex-wrap items-center gap-2"><div role="group" aria-label="Level Zero study period" className="inline-flex rounded-lg border border-linen-400 bg-linen-100 p-1">{([6, 12] as const).map((value) => <button key={value} type="button" aria-pressed={months === value} onClick={() => setMonths(value)} className={cn("min-h-8 rounded-md px-3 text-xs font-semibold", months === value ? "bg-ink-700 text-white" : "text-ink-500 hover:bg-linen-300")}>{value} months</button>)}</div><Button size="sm" leadingIcon={<Play className="h-3.5 w-3.5" />} pending={run.isPending} pendingLabel="Analyzing" onClick={() => run.mutate()}>{study ? "Run new snapshot" : "Run study"}</Button></div>}
    >
      {query.isLoading ? <PanelLoading rows={3} /> : query.isError ? <PanelError title="Level Zero snapshot unavailable" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : run.isError ? <Alert variant="danger" title="Study could not be completed">The existing snapshot is unchanged. Retry when historical ticket data is available.</Alert> : !study ? <EmptyPanel title={`No ${months}-month study has been run`} description="Run the one-time assessment to review every resolved, non-portal ticket in this period. The resulting snapshot is retained until an authorized user deliberately creates another." /> : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2"><Badge variant="info">Complete, unsampled review</Badge><Badge>{study.period_months} months</Badge><span className="text-[11px] text-ink-400">Created {formatLocalDateTime(study.created_at)} · source through {study.source_data_through_at ? formatLocalDateTime(study.source_data_through_at) : "no completed data"}</span></div>
          <div className="grid gap-2 sm:grid-cols-4">
            <AssuranceMetric label="Reviewed" value={study.analyzed_tickets} detail="resolved tickets" warning={false} />
            <AssuranceMetric label="L0 candidates" value={study.eligible_tickets} detail={`${(study.opportunity_rate * 100).toFixed(1)}% opportunity rate`} warning={study.eligible_tickets > 0} />
            <AssuranceMetric label="High confidence" value={study.high_confidence_tickets} detail="resolution evidence found" warning={false} />
            <AssuranceMetric label="Annualized" value={study.estimated_annualized_opportunities} detail="potential cases / year" warning={false} />
          </div>
          <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div><h3 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">Opportunity themes</h3><div className="mt-3 space-y-2">{study.by_theme.length ? study.by_theme.map((theme) => <div key={theme.theme} className="flex items-center justify-between gap-3 rounded-lg bg-linen-100 px-3 py-2 text-xs"><span className="text-ink-600">{theme.theme}</span><strong className="font-mono tabular-nums text-ink-700">{theme.count}</strong></div>) : <p className="text-xs text-ink-400">No safe automation theme met the study criteria.</p>}</div></div>
            <div><h3 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">Evidence drill-down</h3>{study.items.length ? <div className="mt-3 space-y-2">{study.items.slice(0, 6).map((item) => <Link key={item.ticket_id} href={`/tickets/${item.ticket_id}`} className="flex min-w-0 items-start justify-between gap-3 rounded-xl border border-linen-300 p-3 transition-colors hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"><span className="min-w-0"><span className="flex flex-wrap gap-1.5"><Badge variant={item.confidence === "high" ? "success" : "info"}>{item.confidence} confidence</Badge><Badge>{item.theme}</Badge></span><ListText text={item.subject} lines={2} className="mt-2 text-xs font-semibold leading-5 text-ink-700" /><ListText text={item.evidence} lines={2} className="mt-1 text-[11px] leading-4 text-ink-400" /></span><ArrowRight className="mt-1 h-4 w-4 shrink-0 text-ink-400" /></Link>)}</div> : <EmptyPanel title="No candidate evidence" description="The study completed but did not find a safely bounded Level Zero pattern." />}</div>
          </div>
          <Alert variant="info" title="Safety boundary" className="text-xs">{study.safeguards.join(" ")}</Alert>
        </div>
      )}
    </Panel>
  );
}

function WorkloadPanel({ query, slaQuery, windowDays }: { query: UseQueryResult<IntelWorkloadResponse, Error>; slaQuery: UseQueryResult<SlaMonitoringResponse, Error>; windowDays: WindowDays }) {
  const { evidence, closeEvidence, openAssigneeEvidence } = useAssigneeBreachEvidence(windowDays);
  const slaData = slaQuery.isError ? undefined : slaQuery.data;
  const agents = query.data?.agents ?? [];
  const maxOpen = Math.max(1, ...agents.map((agent) => agent.open_tickets));
  return (
    <Panel title="Assignment balance" description={query.data?.workforce_source === "provider" ? "Authoritative provider-agent assignments and completion outcomes in the same activity window. Breach counts open their ticket evidence." : "Active Tickety OPS Tower assignments and completion outcomes in the same activity window. Breach counts open their ticket evidence."} icon={<Users className="h-4 w-4" />}>
      {query.isLoading ? <PanelLoading /> : query.isError ? <PanelError title="Workload unavailable" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : agents.length === 0 ? <EmptyPanel title="No active agent roster" description="No active agents or supervisors are available for workload analysis." /> : (
        <div className="space-y-3">
          {slaQuery.isError && <Alert variant="warning" title="SLA breach indicators unavailable" action={<Button variant="secondary" size="sm" onClick={() => void slaQuery.refetch()} pending={slaQuery.isFetching} pendingLabel="Retrying…">Retry</Button>}>Missing breach links do not mean an agent has zero breaches. Reload the SLA evidence before using this panel for assignment decisions.</Alert>}
          {!slaQuery.isError && slaQuery.isLoading && <Alert variant="info" title="Loading SLA breach indicators">Assignment data is available; per-agent breach links will appear after SLA evidence finishes loading.</Alert>}
          <SamplingNotice analyzed={query.data!.analyzed_users} total={query.data!.total_users} subject="active agents" />
          <div className="flex flex-wrap gap-2"><Badge variant="info">{query.data!.assigned_users} of {query.data!.total_users} agents assigned</Badge><Badge>{query.data!.total_open_assignments} active assignments</Badge></div>
          {query.data!.unmapped_open_assignments > 0 && <Alert variant="warning" title="Provider directory coverage gap" className="text-xs">{query.data!.unmapped_open_assignments} active assignment{query.data!.unmapped_open_assignments === 1 ? "" : "s"} reference provider agents missing from the current directory projection.</Alert>}
          {agents.slice(0, 10).map((agent) => {
            const breachSummary = slaData?.by_assignee.find((item) => item.assignee_source === agent.source && item.assignee_id === agent.user_id);
            const breachedTickets = breachSummary?.breached_ticket_count ?? 0;
            const breachedClocks = breachSummary?.breached_clock_count ?? 0;
            return (
              <article key={agent.user_id} className="rounded-xl border border-linen-300 p-3">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0"><ListText text={agent.name} lines={2} className="text-sm font-semibold leading-5 text-ink-700" /><ListText text={`${agent.source === "provider" ? agent.group_names.slice(0, 2).join(" · ") || agent.title || "Provider agent" : `Tier ${agent.tier}`} · ${agent.total_resolved} resolved · ${agent.avg_resolution_hours ? `${agent.avg_resolution_hours}h avg` : "no completion sample"}`} lines={2} className="mt-0.5 text-xs leading-5 text-ink-400" /></div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <Badge variant={agent.load_status === "overloaded" ? "danger" : agent.load_status === "high" ? "warning" : "success"} dot>{agent.open_tickets} open</Badge>
                    {breachedTickets > 0 && (
                      <button type="button" onClick={() => openAssigneeEvidence({ name: agent.name, id: agent.user_id, source: agent.source, ticketCount: breachedTickets, clockCount: breachedClocks })} className="inline-flex min-h-8 items-center gap-1 rounded-md px-2 text-[10px] font-semibold text-semantic-danger underline decoration-semantic-danger/30 underline-offset-4 transition-colors hover:bg-[var(--color-danger-soft)] hover:decoration-semantic-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]" aria-label={`${agent.name}: view ${breachedTickets} breached ticket${breachedTickets === 1 ? "" : "s"}`}>
                        {breachedTickets} breached <ArrowRight className="h-3 w-3" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-3"><div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-linen-300"><div className={cn("h-full rounded-full", agent.load_status === "overloaded" ? "bg-semantic-danger" : agent.load_status === "high" ? "bg-semantic-warning" : "bg-semantic-success")} style={{ width: `${(agent.open_tickets / maxOpen) * 100}%` }} /></div>{agent.p1_open_tickets > 0 && <span className="text-[10px] font-semibold text-semantic-danger">{agent.p1_open_tickets} P1</span>}</div>
              </article>
            );
          })}
        </div>
      )}
      <TicketEvidenceDialog selection={evidence} onClose={closeEvidence} />
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
  const [evidence, setEvidence] = useState<TicketEvidenceSelection | null>(null);
  const data = query.data;
  const openCluster = (cluster: SystemicIssuesResponse["clusters"][number]) => {
    const statusDetail = Object.entries(cluster.status_breakdown).map(([status, count]) => `${status}: ${count}`).join(" · ");
    setEvidence({
      title: `${cluster.cluster_id} · related tickets`,
      description: `${cluster.ticket_count.toLocaleString()} tickets share this detected pattern. Open any returned evidence ticket for its complete record.`,
      items: cluster.ticket_ids.map((ticketId, index) => ({
        key: ticketId,
        ticketId,
        subject: cluster.samples[index] || `Ticket ${ticketId}`,
        badges: [{ label: `Evidence ${index + 1}`, variant: "info" }],
        detail: statusDetail || cluster.shared_keywords.join(" · "),
      })),
      expectedCount: cluster.ticket_count,
      truncated: cluster.ticket_ids.length < cluster.ticket_count,
    });
  };
  return (
    <Panel title="Systemic issue radar" description="Related current tickets that may share a root cause or business impact." icon={<Radar className="h-4 w-4" />}>
      {query.isLoading ? <PanelLoading /> : query.isError ? <PanelError title="Systemic analysis unavailable" onRetry={() => void query.refetch()} retrying={query.isFetching} /> : !data || data.clusters.length === 0 ? <EmptyPanel title="No current systemic clusters" description="No related pattern met the detection threshold inside this activity window." /> : (
        <div className="space-y-3">
          <SamplingNotice analyzed={data.analyzed_tickets} total={data.total_tickets} />
          {data.clusters.slice(0, 6).map((cluster) => (
            <button key={cluster.cluster_id} type="button" onClick={() => openCluster(cluster)} aria-label={`View ${cluster.ticket_ids.length} evidence tickets for ${cluster.cluster_id}`} className="group block w-full rounded-xl border border-linen-300 p-4 text-left transition-colors hover:border-ink-400 hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]">
              <span className="flex min-w-0 items-start justify-between gap-3"><span className="min-w-0"><span className="flex flex-wrap gap-1.5"><Badge variant="info" icon={<Layers3 className="h-3 w-3" />}>{cluster.ticket_count} related</Badge><Badge variant={cluster.business_impact_score >= 70 ? "danger" : "warning"}>Impact {Math.round(cluster.business_impact_score)}</Badge></span><ListText text={cluster.samples[0] || cluster.cluster_id} lines={2} className="mt-2 text-sm font-semibold leading-5 text-ink-700" /></span><span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-400 transition-colors group-hover:bg-white group-hover:text-ink-700"><ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></span></span>
              <span className="mt-3 flex flex-wrap gap-1.5">{cluster.shared_keywords.slice(0, 8).map((keyword) => <Badge key={keyword}>{keyword}</Badge>)}</span>
              <span className="mt-3 block text-[11px] font-semibold text-semantic-primary">View {cluster.ticket_ids.length} evidence ticket{cluster.ticket_ids.length === 1 ? "" : "s"}</span>
            </button>
          ))}
        </div>
      )}
      <TicketEvidenceDialog selection={evidence} onClose={() => setEvidence(null)} />
    </Panel>
  );
}

function TicketEvidenceDialog({ selection, onClose }: { selection: TicketEvidenceSelection | null; onClose: () => void }) {
  const expectedCount = selection?.expectedCount ?? selection?.items.length ?? 0;
  const returnedCount = selection?.items.length ?? 0;
  const incomplete = Boolean(selection && !selection.loading && !selection.error && (selection.truncated || returnedCount < expectedCount));
  return (
    <Dialog
      open={Boolean(selection)}
      onOpenChange={(open) => { if (!open) onClose(); }}
      title={selection?.title || "Ticket evidence"}
      description={selection?.description}
      className="max-w-2xl"
    >
      {selection?.loading ? (
        <div aria-busy="true" aria-label="Loading ticket evidence" className="space-y-3"><Skeleton className="h-20 w-full" /><Skeleton className="h-20 w-full" /><span className="sr-only">Loading ticket evidence</span></div>
      ) : selection?.error ? (
        <ErrorState density="compact" title="Ticket evidence unavailable" description="The aggregate count is still visible, but the source tickets could not be loaded." onRetry={selection.onRetry} />
      ) : selection && (
        <div className="space-y-4">
          {selection.scopeTruncated && (
            <Alert variant="warning" title="Assignee scope is sampled" className="text-xs">
              Counts were calculated from {selection.scopeAnalyzed?.toLocaleString()} of {selection.scopeTotal?.toLocaleString()} matching tickets in the selected window. They are sample counts, not complete assignee totals.
            </Alert>
          )}
          {incomplete && (
            <Alert variant="warning" title="Returned evidence is bounded" className="text-xs">
              This view contains {returnedCount.toLocaleString()} returned evidence row{returnedCount === 1 ? "" : "s"} for a total of {expectedCount.toLocaleString()}. Counts remain visible, but omitted records are not guessed.
            </Alert>
          )}
          {selection.items.length === 0 ? (
            <EmptyPanel title="No ticket evidence returned" description="The aggregate count is available, but this bounded response did not include a matching ticket row." />
          ) : (
            <div className="space-y-2">
              {selection.items.map((item) => (
                <Link
                  key={item.key}
                  href={`/tickets/${encodeURIComponent(item.ticketId)}`}
                  onClick={onClose}
                  className="group flex min-w-0 items-start justify-between gap-3 rounded-xl border border-linen-300 p-3 transition-colors hover:border-ink-400 hover:bg-linen-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                >
                  <span className="min-w-0">
                    {item.badges && item.badges.length > 0 && <span className="flex flex-wrap gap-1.5">{item.badges.map((badge, index) => <Badge key={`${badge.label}-${index}`} variant={badge.variant}>{badge.label}</Badge>)}</span>}
                    <ListText text={item.subject} lines={2} className={cn("text-sm font-semibold leading-5 text-ink-700", item.badges?.length && "mt-2")} />
                    {item.detail && <ListText text={item.detail} lines={3} className="mt-1 text-xs leading-5 text-ink-500" />}
                  </span>
                  <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-ink-400 transition-transform group-hover:translate-x-0.5 group-hover:text-ink-700" aria-hidden="true" />
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </Dialog>
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
  return <ErrorState density="compact" title={title} description="This signal could not be refreshed. Other cockpit panels remain independent." onRetry={onRetry} retrying={retrying} />;
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
