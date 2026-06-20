"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { PriorityCard } from "@/components/engagement/PriorityCard";
import { MomentumCounter } from "@/components/engagement/MomentumCounter";
import { TicketIcon, AlertTriangle, Clock, CheckCircle2 } from "lucide-react";

export default function DashboardPage() {
  const { data: tickets } = useQuery({
    queryKey: ["tickets"],
    queryFn: api.getTickets,
  });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.getMe });

  const all = tickets || [];
  const open = all.filter(
    (t) => t.status === "Open" || t.status === "New"
  ).length;
  const escalated = all.filter((t) => t.status === "Escalated").length;
  const closed = all.filter((t) => t.status === "Closed").length;
  const priorityTickets = all
    .filter((t) => t.status !== "Closed")
    .sort((a, b) => {
      const rank: Record<string, number> = { P1: 0, P2: 1, P3: 2 };
      return (rank[a.priority] || 3) - (rank[b.priority] || 3);
    })
    .slice(0, 6);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">
            {me ? `Hello, ${me.name.split(" ")[0]}` : "Tickets overview"}
          </h1>
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-moss-500" />
            <p className="text-[13px] text-ink-500">
              {all.length} total tickets · {open} open · Updated just now
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button className="btn-secondary text-xs">
            Export
          </button>
          <button className="btn-primary text-xs">
            New Ticket
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Total Tickets"
          value={all.length}
          icon={<TicketIcon className="w-4 h-4" strokeWidth={1.5} />}
        />
        <KpiCard
          label="Open"
          value={open}
          icon={<Clock className="w-4 h-4" strokeWidth={1.5} />}
        />
        <KpiCard
          label="Escalated"
          value={escalated}
          icon={<AlertTriangle className="w-4 h-4" strokeWidth={1.5} />}
        />
        <KpiCard
          label="Resolved"
          value={closed}
          icon={<CheckCircle2 className="w-4 h-4" strokeWidth={1.5} />}
        />
      </div>

      {me && (
        <div className="card-surface p-5 flex items-center justify-between">
          <div>
            <p className="kpi-label">Your Performance</p>
            <div className="flex items-baseline gap-2 mt-1.5">
              <span className="kpi-value">
                {me.impact_points.toLocaleString()}
              </span>
              <span className="text-sm text-ink-500">Impact Points</span>
            </div>
            <div className="flex items-center gap-3 mt-2.5">
              <span className="rounded-full border border-linen-400 px-2 py-0.5 text-[11px] font-medium text-ink-500">
                Tier {me.tier}
              </span>
              <span className="text-xs text-ink-500">{me.title}</span>
            </div>
          </div>
          <MomentumCounter momentum={me.momentum} />
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[15px] font-semibold text-ink-700">
            Priority Queue
          </h2>
          <span className="text-xs text-ink-400">
            {priorityTickets.length} active
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {priorityTickets.map((t, i) => (
            <PriorityCard key={t.id} ticket={t} index={i} />
          ))}
        </div>
      </div>
    </div>
  );
}