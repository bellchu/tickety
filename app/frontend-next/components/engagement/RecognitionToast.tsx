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
    <div className="fixed bottom-6 right-6 z-50 mt-20">
      <AnimatePresence>
        {recognitions.map((rec, i) => (
          <motion.div
            key={`${rec.recognition_key}-${i}`}
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 40 }}
            transition={{ delay: i * 0.15, type: "spring", stiffness: 250, damping: 20 }}
            className="card-surface p-4 pr-10 min-w-[280px] shadow-lg mb-3 relative"
          >
            <button
              onClick={onClose}
              className="absolute top-3 right-3 text-slate-400 hover:text-slate-600"
            >
              <X className="w-4 h-4" />
            </button>
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center flex-shrink-0">
                <Award className="w-5 h-5 text-slate-600" />
              </div>
              <div>
                <p className="text-xs font-medium text-slate-600 uppercase tracking-wider">
                  Recognition Unlocked
                </p>
                <p className="text-sm font-semibold text-slate-900 mt-0.5">
                  {rec.display_name}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">{rec.description}</p>
              </div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}