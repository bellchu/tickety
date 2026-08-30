"use client";

import { motion, AnimatePresence } from "framer-motion";
import { X, Award } from "lucide-react";
import type { Recognition } from "@/lib/types";

interface Props {
  recognitions: Recognition[];
  onClose: () => void;
}

export function RecognitionToast({ recognitions, onClose }: Props) {
  return (
    <div className="fixed inset-x-4 bottom-4 z-50 mt-20 sm:inset-x-auto sm:bottom-6 sm:right-6">
      <AnimatePresence>
        {recognitions.map((rec, i) => (
          <motion.div
            key={`${rec.recognition_key}-${i}`}
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 40 }}
            transition={{ delay: i * 0.15, type: "spring", stiffness: 250, damping: 20 }}
            className="card-surface relative mb-3 w-full max-w-sm p-4 pr-10 shadow-lg sm:min-w-[280px]"
          >
            <button
              type="button"
              aria-label="Dismiss recognition"
              onClick={onClose}
              className="absolute right-3 top-3 rounded-md p-1 text-ink-400 hover:bg-linen-200 hover:text-ink-600"
            >
              <X className="w-4 h-4" />
            </button>
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-linen-300 flex items-center justify-center flex-shrink-0">
                <Award className="w-5 h-5 text-ink-600" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-medium text-ink-600 uppercase tracking-wider">
                  Recognition Unlocked
                </p>
                <p className="mt-0.5 break-words text-sm font-semibold text-ink-700 [overflow-wrap:anywhere]">
                  {rec.display_name}
                </p>
                <p className="mt-0.5 break-words text-xs text-ink-500 [overflow-wrap:anywhere]">{rec.description}</p>
              </div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
