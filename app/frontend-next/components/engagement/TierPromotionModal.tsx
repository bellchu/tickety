"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Star, X } from "lucide-react";
import type { PointsNotification } from "@/lib/types";
import { useEffect } from "react";

interface Props {
  notification: PointsNotification;
  onClose: () => void;
}

export function TierPromotionModal({ notification, onClose }: Props) {
  useEffect(() => {
    const timer = setTimeout(onClose, 5000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/30 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.8, opacity: 0 }}
          transition={{ type: "spring", stiffness: 200, damping: 20 }}
          className="relative bg-white rounded-3xl p-8 max-w-md mx-4 text-center shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-slate-400 hover:text-slate-600"
          >
            <X className="w-5 h-5" />
          </button>
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
            className="w-20 h-20 mx-auto rounded-full bg-slate-700 flex items-center justify-center mb-4"
          >
            <Star className="w-10 h-10 text-white fill-white" />
          </motion.div>
          <p className="text-sm font-medium text-slate-600 uppercase tracking-wider">
            Tier Promotion
          </p>
          <h2 className="text-2xl font-bold text-slate-900 mt-2">
            Congratulations, {notification.user_name}!
          </h2>
          <p className="text-slate-600 mt-2">
            You&rsquo;ve been promoted to <span className="font-semibold text-slate-600">Tier {notification.new_tier}</span>
          </p>
          <div className="mt-6 pt-4 border-t border-slate-100">
            <p className="text-xs text-slate-400">
              Total Impact Points: {notification.new_total}
            </p>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}