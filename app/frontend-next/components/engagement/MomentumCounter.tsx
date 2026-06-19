"use client";

import { Flame } from "lucide-react";

interface Props {
  momentum: number;
}

export function MomentumCounter({ momentum }: Props) {
  return (
    <div className="flex items-center gap-3 rounded border border-slate-200 bg-white px-4 py-3">
      <Flame className="h-4 w-4 text-slate-400" />
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
          Momentum
        </p>
        <p className="text-lg font-bold text-slate-900 tabular-nums">
          {momentum}
        </p>
      </div>
    </div>
  );
}
