"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  IntelAlertsResponse,
  IntelPrioritizeResponse,
  IntelSlaResponse,
  IntelTrendsResponse,
  AccountHealth,
  RouteRecommendation,
} from "@/lib/types";
import {
  Radar,
  AlertTriangle,
  Timer,
  ListOrdered,
  Users,
  TrendingUp,
  Activity,
  Search,
  Gauge,
  RefreshCw,
} from "lucide-react";
import { cn, priorityColor } from "@/lib/utils";

export default function IntelligencePage() {
  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-linen-300 flex items-center justify-center">
          <Radar className="w-5 h-5 text-ink-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-ink-700">Intelligence</h1>
          <p className="text-sm text-ink-500">
            Ambient AI agents: escalation risk, SLA, prioritization, routing,
            account health &amp; trends.
          </p>
        </div>
      </div>

      <AlertsPanel />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PrioritizePanel />
        <SlaPanel />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TrendsPanel />
        <HealthPanel />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <WorkloadPanel />
        <SystemicPanel />
      </div>
    </div>
  );
}

function SectionCard({
  title,
  icon: Icon,
  children,
  right,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="card-surface p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="w-5 h-5 text-ink-600" />
          <h2 className="text-lg font-semibold text-ink-700">{title}</h2>
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

function StatPill({ value, tone }: { value: number; tone: "red" | "amber" | "emerald" }) {
  const tones = {
    red: "bg-rust-400/10 text-red-700 border-rust-400/30",
    amber: "bg-linen-200 text-ink-600 border-linen-400",
    emerald: "bg-linen-200 text-ink-600 border-linen-400",
  };
  return (
    <span className={cn("inline-flex items-center justify-center min-w-[2.25rem] px-2 py-0.5 rounded-full text-sm font-semibold border", tones[tone])}>
      {value}
    </span>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-ink-400 py-2">{children}</p>;
}

// ── Proactive Alerts ──────────────────────────────────────────

function AlertsPanel() {
  const { data, isLoading } = useQuery<IntelAlertsResponse>({
    queryKey: ["intel-alerts"],
    queryFn: api.getIntelAlerts,
    refetchInterval: 30000,
  });

  return (
    <SectionCard title="Proactive Alerts" icon={AlertTriangle} right={isLoading ? <RefreshCw className="w-4 h-4 animate-spin text-ink-400" /> : null}>
      {!data ? (
        <EmptyHint>Loading alerts…</EmptyHint>
      ) : (
        <>
          <div className="flex flex-wrap gap-3">
            <div className="flex items-center gap-2">
              <StatPill value={data.summary.escalation_prone} tone="red" />
              <span className="text-sm text-ink-600">escalation-prone</span>
            </div>
            <div className="flex items-center gap-2">
              <StatPill value={data.summary.sla_at_risk} tone="amber" />
              <span className="text-sm text-ink-600">SLA at risk</span>
            </div>
            <div className="flex items-center gap-2">
              <StatPill value={data.summary.sla_breached} tone="red" />
              <span className="text-sm text-ink-600">SLA breached</span>
            </div>
          </div>

          {data.escalation_prone.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                Escalation-prone cases
              </h3>
              {data.escalation_prone.slice(0, 6).map((a) => (
                <div key={a.ticket_id} className="flex items-center justify-between gap-3 p-3 rounded-lg bg-rust-400/10/50 border border-red-100">
                  <div className="min-w-0">
                    <a href={`/tickets/${a.ticket_id}`} className="block truncate text-sm font-medium text-ink-700 hover:text-ink-700">
                      {a.subject}
                    </a>
                    <span className="text-xs text-ink-500">{a.priority} · risk {a.risk}/100</span>
                  </div>
                  <RiskBar value={a.risk} />
                </div>
              ))}
            </div>
          )}

          {data.sla_breached.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">SLA breached</h3>
              {data.sla_breached.slice(0, 4).map((s) => (
                <SlaRow key={s.ticket_id} s={s} />
              ))}
            </div>
          )}

          {data.summary.escalation_prone === 0 &&
            data.summary.sla_at_risk === 0 &&
            data.summary.sla_breached === 0 && (
              <EmptyHint>No cases need attention right now. ✅</EmptyHint>
            )}
        </>
      )}
    </SectionCard>
  );
}

function RiskBar({ value }: { value: number }) {
  const tone = value >= 70 ? "bg-rust-400/100" : value >= 40 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2 w-32 shrink-0">
      <div className="h-2 flex-1 rounded-full bg-linen-300 overflow-hidden">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs font-semibold text-ink-600 w-8 text-right">{value}</span>
    </div>
  );
}

// ── Prioritization ────────────────────────────────────────────

function PrioritizePanel() {
  const { data, isLoading } = useQuery<IntelPrioritizeResponse>({
    queryKey: ["intel-prioritize"],
    queryFn: api.getIntelPrioritize,
  });
  return (
    <SectionCard title="Backlog Prioritization" icon={ListOrdered} right={isLoading ? <RefreshCw className="w-4 h-4 animate-spin text-ink-400" /> : null}>
      {!data ? (
        <EmptyHint>Loading…</EmptyHint>
      ) : data.ranked.length === 0 ? (
        <EmptyHint>No open tickets in the backlog.</EmptyHint>
      ) : (
        <ol className="space-y-2">
          {data.ranked.slice(0, 8).map((t, i) => (
            <li key={t.ticket_id} className="flex items-center gap-3 p-3 rounded-lg border border-linen-300">
              <span className="w-6 h-6 rounded-full bg-linen-300 text-ink-600 text-xs font-bold flex items-center justify-center">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <a href={`/tickets/${t.ticket_id}`} className="block truncate text-sm font-medium text-ink-700 hover:text-ink-700">
                  {t.subject}
                </a>
                <span className="text-xs text-ink-500">
                  {t.priority} · {t.category || "—"} · {t.age_hours}h old · risk {t.escalation_risk}
                </span>
              </div>
              <div className="text-right shrink-0">
                <div className="text-sm font-semibold text-ink-600">{t.score}</div>
                <div className="text-[10px] uppercase text-ink-400">score</div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  );
}

// ── SLA ───────────────────────────────────────────────────────

function SlaPanel() {
  const { data, isLoading } = useQuery<IntelSlaResponse>({
    queryKey: ["intel-sla"],
    queryFn: api.getIntelSla,
  });
  return (
    <SectionCard title="SLA Clocks" icon={Timer} right={isLoading ? <RefreshCw className="w-4 h-4 animate-spin text-ink-400" /> : null}>
      {!data ? (
        <EmptyHint>Loading…</EmptyHint>
      ) : data.items.length === 0 ? (
        <EmptyHint>No open tickets to track.</EmptyHint>
      ) : (
        <div className="space-y-2">
          {data.items.slice(0, 10).map((s) => (
            <SlaRow key={s.ticket_id} s={s} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function SlaRow({ s }: { s: import("@/lib/types").SlaStatusItem }) {
  const tone =
    s.status === "breached"
      ? "border-red-100 bg-rust-400/10/50"
      : s.status === "at_risk"
      ? "border-linen-400 bg-linen-200"
      : "border-linen-300";
  const dot =
    s.status === "breached" ? "bg-rust-400/100" : s.status === "at_risk" ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className={cn("flex items-center gap-3 p-3 rounded-lg border", tone)}>
      <span className={cn("w-2 h-2 rounded-full", dot)} />
      <div className="min-w-0 flex-1">
        <a href={`/tickets/${s.ticket_id}`} className="block truncate text-sm font-medium text-ink-700 hover:text-ink-700">
          {s.subject}
        </a>
        <span className={cn("text-xs px-1.5 py-0.5 rounded border", priorityColor(s.priority))}>
          {s.priority}
        </span>
      </div>
      <div className="text-right shrink-0 text-xs text-ink-600">
        {s.status === "breached"
          ? `breached ${s.elapsed_hours}h`
          : `${s.remaining_hours}h left`}
        <div className="text-[10px] uppercase text-ink-400">
          target {s.sla_target_hours}h
        </div>
      </div>
    </div>
  );
}

// ── Trends ─────────────────────────────────────────────────────

function TrendsPanel() {
  const { data, isLoading } = useQuery<IntelTrendsResponse>({
    queryKey: ["intel-trends"],
    queryFn: api.getIntelTrends,
  });
  if (!data) {
    return (
      <SectionCard title="Trends &amp; Text Analytics" icon={TrendingUp}>
        <EmptyHint>Loading…</EmptyHint>
      </SectionCard>
    );
  }
  const maxCat = Math.max(1, ...Object.values(data.by_category));
  return (
    <SectionCard title="Trends & Text Analytics" icon={TrendingUp} right={isLoading ? <RefreshCw className="w-4 h-4 animate-spin text-ink-400" /> : null}>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500 mb-2">By category</h3>
          {Object.entries(data.by_category).length === 0 ? (
            <EmptyHint>No categories yet.</EmptyHint>
          ) : (
            <div className="space-y-1.5">
              {Object.entries(data.by_category).slice(0, 8).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-xs">
                  <span className="w-24 truncate text-ink-600">{k}</span>
                  <div className="flex-1 h-2 rounded-full bg-linen-300 overflow-hidden">
                    <div className="h-full bg-linen-3000 rounded-full" style={{ width: `${(v / maxCat) * 100}%` }} />
                  </div>
                  <span className="w-6 text-right text-ink-500">{v}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500 mb-2">By sentiment</h3>
          {Object.entries(data.by_sentiment).length === 0 ? (
            <EmptyHint>No sentiment data.</EmptyHint>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(data.by_sentiment).map(([k, v]) => (
                <span key={k} className="text-xs px-2 py-1 rounded-lg bg-linen-200 border border-linen-400 text-ink-600">
                  {k} <span className="font-semibold">{v}</span>
                </span>
              ))}
            </div>
          )}
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500 mt-4 mb-2">Top terms</h3>
          <div className="flex flex-wrap gap-1.5">
            {data.top_terms.slice(0, 18).map(([term, n]) => (
              <span key={term} className="text-xs px-2 py-1 rounded-lg bg-linen-300 border border-linen-400 text-ink-600">
                {term} <span className="text-ink-400">{n}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

// ── Account Health + Routing ───────────────────────────────────

function HealthPanel() {
  const [reporter, setReporter] = useState("");
  const [activeReporter, setActiveReporter] = useState("");
  const queryClient = useQueryClient();

  const { data, isFetching } = useQuery<AccountHealth | null>({
    queryKey: ["intel-health", activeReporter],
    queryFn: () => (activeReporter ? api.getIntelHealth(activeReporter) : Promise.resolve(null)),
    enabled: !!activeReporter,
  });

  const run = (e: React.FormEvent) => {
    e.preventDefault();
    const r = reporter.trim();
    if (r) setActiveReporter(r);
  };

  return (
    <SectionCard
      title="Account Health & Routing"
      icon={Gauge}
      right={
        <form onSubmit={run} className="flex gap-2">
          <div className="relative">
            <Search className="w-4 h-4 text-ink-400 absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              value={reporter}
              onChange={(e) => setReporter(e.target.value)}
              placeholder="reporter / customer"
              className="input-base input-search py-1.5 text-sm w-44"
            />
          </div>
          <button type="submit" className="px-3 rounded-lg bg-ink-700 text-white text-sm hover:bg-ink-800">
            Check
          </button>
        </form>
      }
    >
      {!activeReporter ? (
        <EmptyHint>Enter a reporter to score account health and churn risk.</EmptyHint>
      ) : isFetching ? (
        <EmptyHint>Scoring…</EmptyHint>
      ) : data && data.health_score !== null ? (
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <div className="relative w-20 h-20">
              <svg viewBox="0 0 36 36" className="w-20 h-20 -rotate-90">
                <circle cx="18" cy="18" r="15.5" fill="none" stroke="#e2e8f0" strokeWidth="4" />
                <circle
                  cx="18" cy="18" r="15.5" fill="none"
                  stroke={data.churn_risk === "high" ? "#ef4444" : data.churn_risk === "medium" ? "#f59e0b" : "#10b981"}
                  strokeWidth="4" strokeLinecap="round"
                  strokeDasharray={`${(data.health_score ?? 0) * 0.98} 100`}
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-lg font-bold text-ink-700">{data.health_score}</span>
              </div>
            </div>
            <div className="space-y-1 text-sm text-ink-600">
              <div>Churn risk: <span className="font-semibold capitalize">{data.churn_risk}</span></div>
              <div>{data.open} open · {data.resolved} resolved · {data.total} total</div>
              <div>Avg escalation risk: {data.avg_escalation_risk}</div>
              <div>Negative sentiment ratio: {(data.negative_sentiment_ratio * 100).toFixed(0)}%</div>
            </div>
          </div>
          <RoutingWidget reporter={activeReporter} onInvalidate={() => queryClient.invalidateQueries({ queryKey: ["intel-health", activeReporter] })} />
        </div>
      ) : (
        <EmptyHint>No tickets found for “{activeReporter}”.</EmptyHint>
      )}
    </SectionCard>
  );
}

function RoutingWidget({ reporter, onInvalidate }: { reporter: string; onInvalidate: () => void }) {
  return <EmptyHint>Use the Tickets page → open a ticket → the Routing agent recommends an assignee.</EmptyHint>;
}
// ── Systemic Issues Panel ─────────────────────────────────────

function SystemicPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["intel-systemic"],
    queryFn: () => api.getIntelSystemic(2),
  });

  return (
    <SectionCard title="Systemic Issues" icon={Radar}>
      {isLoading ? (
        <p className="text-sm text-ink-400 py-2">Clustering tickets…</p>
      ) : !data || data.clusters.length === 0 ? (
        <p className="text-sm text-ink-400 py-2">
          No systemic clusters detected. {data?.total_tickets ?? 0} tickets
          analysed — each issue appears to be isolated.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-ink-500">
            {data.clusters.length} cluster{data.clusters.length > 1 ? "s" : ""}{" "}
            covering {data.clustered_tickets} of {data.total_tickets} tickets
            (similarity ≥ {data.parameters.similarity_cutoff})
          </p>
          {data.clusters.map((c) => (
            <div
              key={c.cluster_id}
              className="rounded border border-linen-400 bg-linen-50 p-4 space-y-2"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-ink-700">
                  {c.cluster_id}
                </span>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-ink-500">
                    {c.ticket_count} tickets
                  </span>
                  <span className="font-semibold text-ink-600">
                    impact {c.business_impact_score}
                  </span>
                  <span className="text-ink-500">
                    avg risk {c.avg_escalation_risk}/100
                  </span>
                </div>
              </div>

              {/* Keywords */}
              <div className="flex flex-wrap gap-1">
                {c.shared_keywords.slice(0, 8).map((kw) => (
                  <span
                    key={kw}
                    className="px-2 py-0.5 rounded border border-linen-400 bg-linen-200 text-[11px] text-ink-600"
                  >
                    {kw}
                  </span>
                ))}
              </div>

              {/* Sample tickets */}
              <ul className="space-y-0.5">
                {c.samples.map((s, i) => (
                  <li key={i} className="text-xs text-ink-500 truncate">
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

// ── Agent Workload Panel ─────────────────────────────────────

function WorkloadPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["agent-workload"],
    queryFn: () => fetch("/api/intelligence/workload").then(r => r.json()),
  });

  const agents = data?.agents ?? [];

  return (
    <SectionCard title="Agent Workload" icon={Users}>
      {isLoading ? (
        <p className="text-sm text-ink-400 py-2">Loading…</p>
      ) : agents.length === 0 ? (
        <p className="text-sm text-ink-400 py-2">No agents with assigned tickets.</p>
      ) : (
        <div className="space-y-2">
          {agents.slice(0, 8).map((a: any) => (
            <div key={a.user_id} className="flex items-center justify-between rounded border border-linen-300 px-3 py-2">
              <div className="min-w-0 flex-1">
                <span className="text-sm font-medium text-ink-700">{a.name}</span>
                {a.tier > 1 && (
                  <span className="ml-2 text-[10px] font-semibold text-ink-500">T{a.tier}</span>
                )}
              </div>
              <div className="flex items-center gap-4 text-xs">
                <span className="tabular-nums text-ink-600">
                  <span className="font-semibold">{a.open_tickets}</span> open
                </span>
                <span className="tabular-nums text-ink-500">
                  {a.total_resolved} resolved
                </span>
                {a.avg_resolution_hours > 0 && (
                  <span className="tabular-nums text-ink-400">
                    avg {a.avg_resolution_hours}h
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
