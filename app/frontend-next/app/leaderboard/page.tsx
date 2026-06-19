"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { motion } from "framer-motion";
import { Crown, Medal, Award } from "lucide-react";
import { cn } from "@/lib/utils";

export default function LeaderboardPage() {
  const { data: leaderboard, isLoading } = useQuery({
    queryKey: ["leaderboard"],
    queryFn: api.getLeaderboard,
  });

  const rankIcon = (rank: number) => {
    if (rank === 1) return <Crown className="h-5 w-5 text-slate-500" />;
    if (rank === 2) return <Medal className="h-5 w-5 text-slate-400" />;
    if (rank === 3) return <Award className="h-5 w-5 text-orange-600" />;
    return (
      <span className="w-5 text-center text-sm font-bold text-slate-300">
        {rank}
      </span>
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-1">
          Team
        </p>
        <h1 className="text-[1.75rem] font-extrabold text-slate-900 tracking-tight">
          Leaderboard
        </h1>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card-surface p-5">
              <div className="skeleton h-6 w-full" />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {(leaderboard || []).map((user, i) => (
            <motion.div
              key={user.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05, duration: 0.25 }}
              className={cn(
                "card-surface p-4 flex items-center gap-4",
                user.rank === 1 &&
                  ""
              )}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-50">
                {rankIcon(user.rank || i + 1)}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-bold text-slate-900 truncate">
                  {user.name}
                </p>
                <p className="text-xs text-slate-400 truncate">{user.title}</p>
              </div>
              <div className="flex shrink-0 items-center gap-6">
                <Stat label="Resolved" value={user.tickets_resolved} />
                <Stat label="Momentum" value={user.momentum} accent />
                <Stat
                  label="Points"
                  value={user.impact_points.toLocaleString()}
                  primary
                />
                <Stat label="Tier" value={`T${user.tier}`} />
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  primary,
}: {
  label: string;
  value: string | number;
  accent?: boolean;
  primary?: boolean;
}) {
  return (
    <div className="text-center">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </p>
      <p
        className={cn(
          "text-sm font-bold mt-0.5",
          primary ? "text-[1.1rem] text-slate-700" : "text-slate-700",
          accent && "text-slate-600"
        )}
      >
        {value}
      </p>
    </div>
  );
}
