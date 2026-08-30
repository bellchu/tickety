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
    <div className="flex min-w-0 flex-col gap-3 xs:flex-row xs:items-center">
      {momentum > 0 && (
        <div className="flex items-center gap-1 rounded-lg border border-amber-400/30 bg-[var(--color-warning-soft)] px-2 py-1">
          <Flame className="h-3.5 w-3.5 text-semantic-warning" />
          <span className="text-xs font-semibold text-semantic-warning">{momentum}</span>
        </div>
      )}
      <div className="flex min-w-0 w-full items-center gap-2">
        <div className="flex shrink-0 items-center gap-1.5">
          <Star className="w-4 h-4 text-ink-500 fill-ink-500" />
          <span className="text-sm font-semibold text-ink-700">{tierName(tier)}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="h-2 bg-linen-300 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-gradient-to-r from-clay-300 to-clay-500 rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${percent}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
            />
          </div>
          <div className="text-[10px] text-ink-400 mt-0.5 flex justify-between">
            <span>{points} pts</span>
            <span>{current}/{needed}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
