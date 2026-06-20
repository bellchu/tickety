"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { motion } from "framer-motion";
import { RECOGNITION_META, ALL_RECOGNITION_KEYS } from "@/lib/recognitions";
import { ImpactBar } from "@/components/engagement/ImpactBar";
import { MomentumCounter } from "@/components/engagement/MomentumCounter";
import {
  Medal, Flame, AlertOctagon, Zap, Heart, CalendarCheck, Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<string, React.ReactNode> = {
  medal: <Medal className="w-6 h-6" />,
  flame: <Flame className="w-6 h-6" />,
  "alert-octagon": <AlertOctagon className="w-6 h-6" />,
  zap: <Zap className="w-6 h-6" />,
  heart: <Heart className="w-6 h-6" />,
  "calendar-check": <CalendarCheck className="w-6 h-6" />,
};

export default function ProfilePage() {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.getMe });
  const { data: recognitions } = useQuery({
    queryKey: ["recognitions", me?.id],
    queryFn: () => api.getRecognitions(me!.id),
    enabled: !!me,
  });

  const unlockedKeys = new Set((recognitions || []).map((r) => r.recognition_key));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-700">Profile</h1>
        <p className="text-sm text-ink-500 mt-1">Your achievements and performance</p>
      </div>

      {me && (
        <div className="card-surface p-6">
          <div className="flex items-center gap-4 mb-6">
            <div className="w-16 h-16 rounded-2xl bg-ink-700 flex items-center justify-center">
              <span className="text-2xl font-bold text-white">
                {me.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
              </span>
            </div>
            <div className="flex-1">
              <h2 className="text-xl font-bold text-ink-700">{me.name}</h2>
              <p className="text-sm text-ink-500">{me.title}</p>
              <p className="text-xs text-ink-400 mt-0.5">Tier {me.tier}</p>
            </div>
            <MomentumCounter momentum={me.momentum} />
          </div>

          <div className="pt-6 border-t border-linen-300">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-semibold text-ink-600">Impact Points Progress</p>
              <p className="text-2xl font-bold text-ink-600">{me.impact_points}</p>
            </div>
            <ImpactBar points={me.impact_points} tier={me.tier} momentum={me.momentum} />
          </div>
        </div>
      )}

      <div>
        <h2 className="text-lg font-semibold text-ink-700 mb-4">Recognition Wall</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {ALL_RECOGNITION_KEYS.map((key, i) => {
            const meta = RECOGNITION_META[key];
            const unlocked = unlockedKeys.has(key);
            return (
              <motion.div
                key={key}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.06 }}
                className={cn(
                  "card-surface p-5 flex items-center gap-4",
                  unlocked ? "ring-1 ring-linen-400" : "opacity-60"
                )}
              >
                <div className={cn(
                  "w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0",
                  unlocked ? "bg-linen-300 text-ink-600" : "bg-linen-200 text-linen-400"
                )}>
                  {unlocked ? ICON_MAP[meta.icon] : <Lock className="w-5 h-5" />}
                </div>
                <div>
                  <p className="text-sm font-semibold text-ink-700">{meta.display_name}</p>
                  <p className="text-xs text-ink-500">{meta.description}</p>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}