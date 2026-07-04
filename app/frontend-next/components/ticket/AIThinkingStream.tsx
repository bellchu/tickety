"use client";

import { useState, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createTicketStreamWS } from "@/lib/ws";
import type { TicketAnalysisResult, TriageStep } from "@/lib/types";
import { ListChecks, Loader2, CheckCircle2, RefreshCw } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Props {
  ticketId: string;
  hasExisting?: boolean;
  onComplete?: (result: TicketAnalysisResult) => void;
}

export function AIThinkingStream({ ticketId, hasExisting, onComplete }: Props) {
  const [steps, setSteps] = useState<TriageStep[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TicketAnalysisResult | null>(null);
  const wsRef = useRef<ReturnType<typeof createTicketStreamWS> | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    return () => { wsRef.current?.disconnect(); };
  }, []);

  const startTriage = async () => {
    setRunning(true);
    setSteps([]);
    setResult(null);
    const ws = createTicketStreamWS(ticketId);
    wsRef.current = ws;
    ws.onMessage((data) => {
      if (data.type === "progress") {
        setSteps(data.steps);
      } else if (data.type === "complete") {
        const result = data.result as TicketAnalysisResult;
        setResult(result);
        setSteps((prev) => prev.map((s) => ({ ...s, status: "done" as const })));
        setRunning(false);
        wsRef.current?.disconnect();
        wsRef.current = null;
        onComplete?.(result);
        queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
        queryClient.invalidateQueries({ queryKey: ["tickets"] });
        queryClient.invalidateQueries({ queryKey: ["intel-alerts"] });
        queryClient.invalidateQueries({ queryKey: ["intel-prioritize"] });
        queryClient.invalidateQueries({ queryKey: ["intel-sla"] });
        queryClient.invalidateQueries({ queryKey: ["intel-trends"] });
        queryClient.invalidateQueries({ queryKey: ["intel-systemic"] });
        queryClient.invalidateQueries({ queryKey: ["intel-workload"] });
        queryClient.invalidateQueries({ queryKey: ["intel-route", ticketId] });
      } else if (data.type === "error") {
        setRunning(false);
        wsRef.current?.disconnect();
        wsRef.current = null;
      }
    });
    ws.connect();
  };

  return (
    <div className="card-surface p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <ListChecks className="w-4 h-4 text-ink-600" />
          <h3 className="text-sm font-semibold text-ink-700">AI Analysis</h3>
        </div>
        <button onClick={startTriage} disabled={running} className="btn-secondary text-xs">
          {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          {running ? "Analyzing…" : "Run Analysis"}
        </button>
      </div>

      <AnimatePresence mode="popLayout">
        {steps.length > 0 && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-2 mb-4">
            {steps.map((step, i) => (
              <motion.div key={step.step} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.1 }} className="flex items-center gap-2 text-sm">
                {step.status === "done" ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-ink-400" />
                ) : step.status === "active" ? (
                  <Loader2 className="w-3.5 h-3.5 text-ink-600 animate-spin" />
                ) : (
                  <div className="w-3.5 h-3.5 rounded-full border-2 border-linen-400" />
                )}
                <span className={
                  step.status === "done" ? "text-ink-600" :
                  step.status === "active" ? "text-ink-700 font-medium" :
                  "text-ink-400"
                }>
                  {step.label}
                </span>
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {result && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-4 pt-4 border-t border-linen-300">
          <div className="grid grid-cols-2 gap-3 text-sm">
            {Object.entries(result).slice(0, 6).map(([key, val]) => (
              <div key={key}>
                <span className="text-xs text-ink-400 capitalize">{key}</span>
                <p className="font-medium text-ink-600">{String(val).slice(0, 80)}</p>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {!running && steps.length === 0 && !result && (
        <p className="text-sm text-ink-400">
          {hasExisting
            ? "AI analysis complete — see details below."
            : "Click &ldquo;Run Analysis&rdquo; to trigger AI triage on this ticket."}
        </p>
      )}
    </div>
  );
}
