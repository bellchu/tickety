"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  BarChart3, TicketIcon, Clock, CheckCircle2, AlertTriangle, TrendingUp,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { cn } from "@/lib/utils";

const CHART_COLORS = ["#6B8E5A", "#C77B4F", "#D4A24C", "#5C554B", "#8AA874", "#C44A3F", "#3D372F"];
const PRIORITY_COLORS: Record<string, string> = { P1: "#C44A3F", P2: "#D4A24C", P3: "#6B8E5A", P4: "#8A8276" };

export default function ReportsPage() {
  const { data: summary } = useQuery({ queryKey: ["report-summary"], queryFn: api.getReportSummary });
  const { data: volume } = useQuery({ queryKey: ["report-volume"], queryFn: api.getReportVolume });
  const { data: byCategory } = useQuery({ queryKey: ["report-by-category"], queryFn: api.getReportByCategory });
  const { data: byStatus } = useQuery({ queryKey: ["report-by-status"], queryFn: api.getReportByStatus });
  const { data: slaCompliance } = useQuery({ queryKey: ["report-sla"], queryFn: api.getReportSlaCompliance });
  const { data: resolutionTime } = useQuery({ queryKey: ["report-resolution"], queryFn: api.getReportResolutionTime });

  const volumeData = (volume?.days || []).map((d, i) => ({ day: d.slice(5), count: volume?.counts?.[i] ?? 0 }));
  const categoryData = (byCategory?.categories || []).map((c, i) => ({ name: c, value: byCategory?.counts?.[i] ?? 0 }));
  const statusData = (byStatus?.statuses || []).map((s, i) => ({ name: s, value: byStatus?.counts?.[i] ?? 0 }));
  const slaData = slaCompliance ? Object.entries(slaCompliance).map(([p, v]) => ({
    priority: p, compliance: v.compliance, breached: v.breached, total: v.total,
  })) : [];
  const resolutionData = (resolutionTime?.categories || []).map((c, i) => ({ category: c, hours: resolutionTime?.avg_hours?.[i] ?? 0 }));

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Reports &amp; Analytics</h1>
          <p className="text-[13px] text-ink-500">
            Ticket volume, SLA compliance, resolution times, and category breakdown
          </p>
        </div>
      </div>

      {/* KPI summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiTile label="Total Tickets" value={summary?.total_tickets ?? 0} icon={TicketIcon} />
        <KpiTile label="Open" value={summary?.open_tickets ?? 0} icon={Clock} color="text-blue-400" />
        <KpiTile label="Resolved" value={summary?.resolved_tickets ?? 0} icon={CheckCircle2} color="text-moss-500" />
        <KpiTile label="SLA Breached" value={summary?.breached_sla ?? 0} icon={AlertTriangle} color="text-rust-500" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MiniStat label="Avg Resolution Time" value={`${summary?.avg_resolution_hours ?? 0}h`} />
        <MiniStat label="Escalation Rate" value={`${summary?.escalation_rate ?? 0}%`} />
        <MiniStat label="CSAT Proxy" value={`${summary?.csat_proxy ?? 0}%`} />
      </div>

      {/* Volume chart */}
      <div className="card-surface p-5">
        <h2 className="text-sm font-semibold text-ink-700 mb-4">Ticket Volume (Last 30 Days)</h2>
        {volumeData.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={volumeData}>
              <defs>
                <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6B8E5A" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6B8E5A" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#EAE3D9" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#8A8276" }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10, fill: "#8A8276" }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #EAE3D9" }} />
              <Area type="monotone" dataKey="count" stroke="#6B8E5A" strokeWidth={2} fill="url(#volGrad)" />
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
          {categoryData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={categoryData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} innerRadius={40}>
                  {categoryData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </div>

        {/* By status */}
        <div className="card-surface p-5">
          <h2 className="text-sm font-semibold text-ink-700 mb-4">Tickets by Status</h2>
          {statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={statusData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#EAE3D9" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: "#8A8276" }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: "#8A8276" }} width={90} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #EAE3D9" }} />
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
        {slaData.length > 0 ? (
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
        {resolutionData.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={resolutionData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#EAE3D9" vertical={false} />
              <XAxis dataKey="category" tick={{ fontSize: 10, fill: "#8A8276" }} />
              <YAxis tick={{ fontSize: 10, fill: "#8A8276" }} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #EAE3D9" }} />
              <Bar dataKey="hours" radius={[4, 4, 0, 0]}>
                {resolutionData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : <EmptyChart />}
      </div>
    </div>
  );
}

function KpiTile({ label, value, icon: Icon, color }: { label: string; value: number; icon: React.ElementType; color?: string }) {
  return (
    <div className="card-surface p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">{label}</span>
        <Icon className={cn("w-4 h-4", color || "text-ink-400")} strokeWidth={1.5} />
      </div>
      <p className="text-2xl font-bold text-ink-700 tabular-nums">{value.toLocaleString()}</p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card-surface p-4 flex items-center justify-between">
      <span className="text-sm text-ink-500">{label}</span>
      <span className="text-lg font-bold text-ink-700 tabular-nums">{value}</span>
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="h-[200px] flex items-center justify-center text-ink-300 text-sm">
      No data available
    </div>
  );
}