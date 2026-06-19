"use client";

import { motion } from "framer-motion";
import { tierProgress, tierName } from "@/lib/utils";
import { Flame, Star } from "lucide-react";

interface Props {
  points: number;
  tier: number;
  momentum: number;
}

export function ImpactBar({ points, tier, momentum }: Props) {
  const { current, needed, percent } = tierProgress(points);

  return (
    <div className="flex items-center gap-3">
      {momentum > 0 && (
        <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-orange-50 border border-orange-200">
          <Flame className="w-3.5 h-3.5 text-orange-500" />
          <span className="text-xs font-semibold text-orange-600">{momentum}</span>
        </div>
      )}
      <div className="flex items-center gap-2 min-w-[180px]">
        <div className="flex items-center gap-1.5">
          <Star className="w-4 h-4 text-slate-500 fill-slate-500" />
          <span className="text-sm font-semibold text-slate-900">{tierName(tier)}</span>
        </div>
        <div className="flex-1">
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-gradient-to-r from-slate-400 to-slate-600 rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${percent}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
            />
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5 flex justify-between">
            <span>{points} pts</span>
            <span>{current}/{needed}</span>
          </div>
        </div>
      </div>
    </div>
  );
}