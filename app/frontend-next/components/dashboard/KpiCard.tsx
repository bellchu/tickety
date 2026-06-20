"use client";

import { motion } from "framer-motion";

interface Props {
  label: string;
  value: number;
  icon?: React.ReactNode;
}

export function KpiCard({ label, value, icon }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="card-surface p-5"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="kpi-label">{label}</span>
        {icon && <span className="text-ink-400">{icon}</span>}
      </div>
      <span className="kpi-value">{value.toLocaleString()}</span>
    </motion.div>
  );
}