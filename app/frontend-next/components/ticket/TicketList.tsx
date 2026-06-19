"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PriorityCard } from "@/components/engagement/PriorityCard";
import { Filter, Search } from "lucide-react";
import { cn } from "@/lib/utils";

const FILTERS = ["All", "Open", "Escalated", "Closed", "Awaiting Review"] as const;
const SORTS = ["Newest", "Priority", "Complexity"] as const;

export function TicketList() {
  const { data: tickets, isLoading } = useQuery({
    queryKey: ["tickets"],
    queryFn: api.getTickets,
  });
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const [sort, setSort] = useState<(typeof SORTS)[number]>("Newest");
  const [search, setSearch] = useState("");

  const priorityRank: Record<string, number> = { P1: 0, P2: 1, P3: 2 };

  const filtered = (tickets || [])
    .filter((t) => filter === "All" || t.status === filter)
    .filter(
      (t) =>
        !search ||
        t.subject.toLowerCase().includes(search.toLowerCase()) ||
        t.description.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) => {
      if (sort === "Priority")
        return (
          (priorityRank[a.priority] || 3) - (priorityRank[b.priority] || 3)
        );
      if (sort === "Complexity")
        return (b.complexity || 1) - (a.complexity || 1);
      return (
        new Date(b.created_at || 0).getTime() -
        new Date(a.created_at || 0).getTime()
      );
    });

  return (
    <div>
      {/* Controls bar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search tickets…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input-base pl-10"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                  filter === f
                    ? "bg-slate-800 text-white"
                    : "bg-white text-slate-500 border border-slate-200 hover:bg-slate-50"
                )}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof SORTS[number])}
          className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-slate-200"
        >
          {SORTS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card-surface p-5 h-40">
              <div className="skeleton h-4 w-20 rounded mb-3" />
              <div className="skeleton h-4 w-full rounded mb-2" />
              <div className="skeleton h-4 w-2/3 rounded" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card-surface p-12 text-center">
          <p className="text-slate-400">No tickets match your filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((ticket, i) => (
            <PriorityCard key={ticket.id} ticket={ticket} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
