"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  BarChart3, TicketIcon, Clock, CheckCircle2, AlertTriangle,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { cn } from "@/lib/utils";
import { Alert, EmptyState, ErrorState, Skeleton } from "@/components/ui";

const CHART_COLORS = ["#3D5AFE", "#7C8BFF", "#5C5347", "#9B9084", "#6B8E5A", "#D4A24C", "#C44A3F"];
const PRIORITY_COLORS: Record<string, string> = { P1: "#C44A3F", P2: "#D4A24C", P3: "#3D5AFE", P4: "#9B9084" };

export default function ReportsPage() {
  const summaryQuery = useQuery({ queryKey: ["report-summary"], queryFn: api.getReportSummary });
  const volumeQuery = useQuery({ queryKey: ["report-volume"], queryFn: api.getReportVolume });
  const categoryQuery = useQuery({ queryKey: ["report-by-category"], queryFn: api.getReportByCategory });
  const statusQuery = useQuery({ queryKey: ["report-by-status"], queryFn: api.getReportByStatus });
  const slaQuery = useQuery({ queryKey: ["report-sla"], queryFn: api.getReportSlaCompliance });
  const resolutionQuery = useQuery({ queryKey: ["report-resolution"], queryFn: api.getReportResolutionTime });
  const queries = [summaryQuery, volumeQuery, categoryQuery, statusQuery, slaQuery, resolutionQuery];
  const summary = summaryQuery.data;
  const volume = volumeQuery.data;
  const byCategory = categoryQuery.data;
  const byStatus = statusQuery.data;
  const slaCompliance = slaQuery.data;
  const resolutionTime = resolutionQuery.data;
  const failed = queries.filter((query) => query.isError).length;

  const volumeData = (volume?.days || []).map((d, i) => ({ day: d.slice(5), count: volume?.counts?.[i] ?? 0 }));
  const categoryData = (byCategory?.categories || []).map((c, i) => ({ name: c, value: byCategory?.counts?.[i] ?? 0 }));
  const statusData = (byStatus?.statuses || []).map((s, i) => ({ name: s, value: byStatus?.counts?.[i] ?? 0 }));
  const slaData = slaCompliance ? Object.entries(slaCompliance).map(([p, v]) => ({
    priority: p, compliance: v.compliance, breached: v.breached, total: v.total,
  })) : [];
  const resolutionData = (resolutionTime?.categories || []).map((c, i) => ({ category: c, hours: resolutionTime?.avg_hours?.[i] ?? 0 }));

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="border-b border-linen-400 pb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-400">Operational analytics</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-ink-700">Reports</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-500">Understand service demand, delivery speed, and SLA performance across the operating model.</p>
      </header>

      {failed === queries.length && (
        <ErrorState title="Reports could not be loaded" description="The analytics service did not return any report data." onRetry={() => void Promise.all(queries.map((query) => query.refetch()))} retrying={queries.some((query) => query.isFetching)} />
      )}
      {failed > 0 && failed < queries.length && <Alert variant="warning" title="Partial report data">{failed} report {failed === 1 ? "section is" : "sections are"} unavailable. Available figures remain visible and missing sections can be retried by refreshing the page.</Alert>}

      {/* KPI summary cards */}
      {failed < queries.length && <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile label="Total tickets" value={summary?.total_tickets} icon={TicketIcon} loading={summaryQuery.isLoading} />
        <KpiTile label="Open" value={summary?.open_tickets} icon={Clock} color="text-semantic-info" loading={summaryQuery.isLoading} />
        <KpiTile label="Resolved" value={summary?.resolved_tickets} icon={CheckCircle2} color="text-semantic-success" loading={summaryQuery.isLoading} />
        <KpiTile label="SLA breached" value={summary?.breached_sla} icon={AlertTriangle} color="text-semantic-danger" loading={summaryQuery.isLoading} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MiniStat label="Avg resolution time" value={summary ? `${summary.avg_resolution_hours}h` : "—"} loading={summaryQuery.isLoading} />
        <MiniStat label="Escalation rate" value={summary ? `${summary.escalation_rate}%` : "—"} loading={summaryQuery.isLoading} />
        <MiniStat label="CSAT proxy" value={summary ? `${summary.csat_proxy}%` : "—"} loading={summaryQuery.isLoading} />
      </div>

      {/* Volume chart */}
      <div className="card-surface p-5">
        <h2 className="text-sm font-semibold text-ink-700 mb-4">Ticket Volume (Last 30 Days)</h2>
        {volumeQuery.isLoading ? <ChartSkeleton /> : volumeQuery.isError ? <SectionError onRetry={() => void volumeQuery.refetch()} /> : volumeData.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={volumeData}>
              <defs>
                <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3D5AFE" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3D5AFE" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#E8E1D6" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#9B9084" }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10, fill: "#9B9084" }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E8E1D6" }} />
              <Area type="monotone" dataKey="count" stroke="#3D5AFE" strokeWidth={2} fill="url(#volGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <EmptyChart />
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By category */}
        <div className="card-surface p-5">
          <h2 className="text-sm font-semibold text-ink-700 mb-4">Tickets by Category</h2>
          {categoryQuery.isLoading ? <ChartSkeleton /> : categoryQuery.isError ? <SectionError onRetry={() => void categoryQuery.refetch()} /> : categoryData.length > 0 ? (
            <div className="space-y-4">
              {byCategory?.truncated && <Alert variant="warning" title="Category view is limited" className="text-xs">Showing {categoryData.length.toLocaleString()} of {byCategory.total_categories.toLocaleString()} categories. Counts are exact for the categories shown.</Alert>}
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={categoryData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} innerRadius={40}>
                    {categoryData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyChart />}
        </div>

        {/* By status */}
        <div className="card-surface p-5">
          <h2 className="text-sm font-semibold text-ink-700 mb-4">Tickets by Status</h2>
          {statusQuery.isLoading ? <ChartSkeleton /> : statusQuery.isError ? <SectionError onRetry={() => void statusQuery.refetch()} /> : statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={statusData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#E8E1D6" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: "#9B9084" }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: "#9B9084" }} width={90} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E8E1D6" }} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {statusData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </div>
      </div>

      {/* SLA compliance */}
      <div className="card-surface p-5">
        <h2 className="text-sm font-semibold text-ink-700 mb-4">SLA Compliance by Priority</h2>
        {slaQuery.isLoading ? <ChartSkeleton /> : slaQuery.isError ? <SectionError onRetry={() => void slaQuery.refetch()} /> : slaData.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {slaData.map((s) => (
              <div key={s.priority} className="rounded border border-linen-400 p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-ink-700">{s.priority}</span>
                  <span className={cn("text-lg font-bold", s.compliance >= 90 ? "text-moss-500" : s.compliance >= 70 ? "text-amber-500" : "text-rust-500")}>
                    {s.compliance}%
                  </span>
                </div>
                <div className="w-full bg-linen-300 rounded-full h-2 mb-2">
                  <div className={cn("h-2 rounded-full", s.compliance >= 90 ? "bg-moss-500" : s.compliance >= 70 ? "bg-amber-500" : "bg-rust-500")} style={{ width: `${s.compliance}%` }} />
                </div>
                <p className="text-xs text-ink-400">{s.breached} breached / {s.total} total</p>
              </div>
            ))}
          </div>
        ) : <EmptyChart />}
      </div>

      {/* Resolution time by category */}
      <div className="card-surface p-5">
        <h2 className="text-sm font-semibold text-ink-700 mb-4">Avg Resolution Time by Category (hours)</h2>
        {resolutionQuery.isLoading ? <ChartSkeleton /> : resolutionQuery.isError ? <SectionError onRetry={() => void resolutionQuery.refetch()} /> : resolutionData.length > 0 ? (
          <div className="space-y-4">
            {resolutionTime?.truncated && <Alert variant="warning" title="Resolution averages are sampled" className="text-xs">Calculated from the latest {resolutionTime.analyzed_tickets.toLocaleString()} of {resolutionTime.total_matching_tickets.toLocaleString()} matching resolved tickets.</Alert>}
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={resolutionData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E8E1D6" vertical={false} />
                <XAxis dataKey="category" tick={{ fontSize: 10, fill: "#9B9084" }} />
                <YAxis tick={{ fontSize: 10, fill: "#9B9084" }} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E8E1D6" }} />
                <Bar dataKey="hours" radius={[4, 4, 0, 0]}>
                  {resolutionData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : <EmptyChart />}
      </div>
      </>}
    </div>
  );
}

function KpiTile({ label, value, icon: Icon, color, loading }: { label: string; value?: number; icon: React.ElementType; color?: string; loading: boolean }) {
  return (
    <div className="card-surface p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">{label}</span>
        <Icon className={cn("w-4 h-4", color || "text-ink-400")} strokeWidth={1.5} />
      </div>
      {loading ? <Skeleton className="mt-3 h-8 w-20" /> : <p className="text-3xl font-semibold tracking-[-0.04em] text-ink-700 tabular-nums">{value == null ? "—" : value.toLocaleString()}</p>}
    </div>
  );
}

function MiniStat({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <div className="card-surface p-4 flex items-center justify-between">
      <span className="text-sm text-ink-500">{label}</span>
      {loading ? <Skeleton className="h-6 w-16" /> : <span className="text-lg font-bold text-ink-700 tabular-nums">{value}</span>}
    </div>
  );
}

function EmptyChart() {
  return (
    <EmptyState className="min-h-[200px] border-0 bg-transparent" icon={<BarChart3 className="h-5 w-5" />} title="No data available" description="This report will populate when matching ticket activity exists." />
  );
}

function ChartSkeleton() { return <div className="space-y-4 py-3" aria-label="Loading report"><Skeleton className="h-44 w-full" /><Skeleton className="h-3 w-2/3" /></div>; }
function SectionError({ onRetry }: { onRetry: () => void }) { return <ErrorState className="min-h-[200px]" title="Report unavailable" description="This section could not be loaded." onRetry={onRetry} />; }
