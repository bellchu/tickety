"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Clock } from "lucide-react";
import type { Ticket } from "@/lib/types";
import {
  priorityColor,
  statusColor,
  complexityDots,
  formatTimeAgo,
  cn,
} from "@/lib/utils";

interface Props {
  ticket: Ticket;
  index?: number;
}

export function PriorityCard({ ticket, index = 0 }: Props) {
  const dots = complexityDots(ticket.complexity);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03, duration: 0.2 }}
    >
      <Link href={`/tickets/${ticket.id}`}>
        <div className="card-surface p-4 cursor-pointer hover:border-linen-400 transition-colors">
          {/* Badge + complexity row */}
          <div className="flex items-center gap-2 mb-2.5">
            <span className={cn("badge", priorityColor(ticket.priority))}>
              {ticket.priority}
            </span>
            <span className={cn("badge", statusColor(ticket.status))}>
              {ticket.status}
            </span>
            <span className="flex items-center gap-1 ml-auto">
              {Array.from({ length: dots.filled }).map((_, i) => (
                <span
                  key={i}
                  className="w-1 h-1 rounded-full bg-linen-500"
                />
              ))}
              {Array.from({ length: dots.empty }).map((_, i) => (
                <span
                  key={`e-${i}`}
                  className="w-1 h-1 rounded-full bg-linen-400"
                />
              ))}
            </span>
          </div>

          <h3 className="text-sm font-semibold text-ink-700 line-clamp-2">
            {ticket.subject}
          </h3>
          <p className="text-xs text-ink-500 mt-1 line-clamp-2 leading-relaxed">
            {ticket.description || "(no description)"}
          </p>

          <div className="flex items-center justify-between mt-3 pt-3 border-t border-linen-300">
            <span className="flex items-center gap-1.5 text-[11px] text-ink-400">
              <Clock className="w-3 h-3" />
              {formatTimeAgo(ticket.created_at)}
            </span>
            {ticket.sentiment && (
              <span
                className={cn(
                  "text-[10px] font-semibold",
                  ticket.sentiment === "Negative"
                    ? "text-rust-500"
                    : ticket.sentiment === "Positive"
                    ? "text-ink-600"
                    : "text-ink-500"
                )}
              >
                {ticket.sentiment}
              </span>
            )}
          </div>
        </div>
      </Link>
    </motion.div>
  );
}
