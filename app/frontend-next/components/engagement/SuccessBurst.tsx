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
        className="fixed inset-x-4 bottom-4 z-50 sm:inset-x-auto sm:bottom-6 sm:right-6"
      >
        <div className="card-surface relative w-full max-w-sm p-4 pr-10 shadow-lg sm:min-w-[280px]">
          <button
            type="button"
            aria-label="Dismiss points notification"
            onClick={onClose}
            className="absolute right-3 top-3 rounded-md p-1 text-ink-400 hover:bg-linen-200 hover:text-ink-600"
          >
            <X className="w-4 h-4" />
          </button>
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-linen-300 flex items-center justify-center flex-shrink-0">
              <CheckCircle2 className="w-5 h-5 text-ink-600" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink-700">
                +{notification.points_earned} Impact Points
              </p>
              <p className="mt-0.5 break-words text-xs text-ink-500 [overflow-wrap:anywhere]">
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
