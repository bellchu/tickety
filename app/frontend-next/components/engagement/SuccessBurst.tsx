"use client";

import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, X } from "lucide-react";
import type { PointsNotification } from "@/lib/types";

interface Props {
  notification: PointsNotification;
  onClose: () => void;
}

export function SuccessBurst({ notification, onClose }: Props) {
  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.9 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -20, scale: 0.9 }}
        transition={{ type: "spring", stiffness: 300, damping: 25 }}
        className="fixed bottom-6 right-6 z-50"
      >
        <div className="card-surface p-4 pr-10 min-w-[280px] shadow-lg">
          <button
            onClick={onClose}
            className="absolute top-3 right-3 text-ink-400 hover:text-ink-600"
          >
            <X className="w-4 h-4" />
          </button>
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-linen-300 flex items-center justify-center flex-shrink-0">
              <CheckCircle2 className="w-5 h-5 text-ink-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-ink-700">
                +{notification.points_earned} Impact Points
              </p>
              <p className="text-xs text-ink-500 mt-0.5">
                {notification.user_name} resolved &ldquo;{notification.ticket_subject}&rdquo;
              </p>
              <p className="text-xs text-ink-400 mt-1">
                Total: {notification.new_total} pts · Momentum: {notification.new_momentum}
              </p>
            </div>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}