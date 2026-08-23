"use client";

import { useState, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createTicketStreamWS } from "@/lib/ws";
import type { TicketAnalysisResult, TriageStep } from "@/lib/types";
import {
  isTicketAnalysisResult,
  isTriageProgressMessage,
  triageWatchdogDelayMs,
} from "@/lib/realtime-validation";
import { ListChecks, Loader2, CheckCircle2, RefreshCw, AlertTriangle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Alert, Button } from "@/components/ui";

interface Props {
  ticketId: string;
  hasExisting?: boolean;
  onComplete?: (result: TicketAnalysisResult) => void;
}

export function AIThinkingStream({ ticketId, hasExisting, onComplete }: Props) {
  const [steps, setSteps] = useState<TriageStep[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TicketAnalysisResult | null>(null);
  const [error, setError] = useState("");
  const wsRef = useRef<ReturnType<typeof createTicketStreamWS> | null>(null);
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();

  const clearWatchdog = () => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  };

  const startWatchdog = (timeoutSeconds?: unknown) => {
    clearWatchdog();
    watchdogRef.current = setTimeout(() => {
      finishWithError("The analysis timed out before it completed. Please try again.");
    }, triageWatchdogDelayMs(timeoutSeconds));
  };

  useEffect(() => {
    return () => {
      clearWatchdog();
      wsRef.current?.disconnect();
    };
  }, []);

  const finishWithError = (message: string) => {
    setError(message);
    setRunning(false);
    clearWatchdog();
    wsRef.current?.disconnect();
    wsRef.current = null;
  };

  const startTriage = async () => {
    setRunning(true);
    setSteps([]);
    setResult(null);
    setError("");
    startWatchdog();
    const ws = createTicketStreamWS(ticketId);
    wsRef.current = ws;
    ws.onMessage((data) => {
      if (!data || typeof data !== "object") {
        finishWithError("The analysis stream returned an unexpected message. Please try again.");
        return;
      }
      if (data.type === "progress") {
        if (!isTriageProgressMessage(data)) {
          finishWithError("The analysis stream returned an unexpected message. Please try again.");
          return;
        }
        startWatchdog(data.timeout_seconds);
        setSteps(data.steps);
      } else if (data.type === "complete") {
        const payload = data.result;
        if (!isTicketAnalysisResult(payload, ticketId)) {
          finishWithError("The analysis returned an unexpected result. Please try again.");
          return;
        }
        const result = payload;
        clearWatchdog();
        setResult(result);
        setSteps((prev) => prev.map((s) => (
          s.status === "error" ? s : { ...s, status: "done" as const }
        )));
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
        finishWithError(typeof data.message === "string" ? data.message : "The analysis stream stopped before it completed.");
      }
    });
    ws.connect();
  };

  return (
    <section className="rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-6" aria-labelledby="ai-analysis-title" aria-busy={running}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <ListChecks className="w-4 h-4 text-ink-600" />
          <h2 id="ai-analysis-title" className="text-sm font-semibold text-ink-700">AI analysis</h2>
        </div>
        <Button variant="secondary" size="sm" onClick={startTriage} pending={running} pendingLabel="Analyzing…" leadingIcon={<RefreshCw className="h-3.5 w-3.5" />}>Run analysis</Button>
      </div>

      {error && <Alert className="mb-4" variant="danger" title="Analysis did not complete">{error}</Alert>}

      {result && result.errors.length > 0 && (
        <Alert className="mb-4" variant="warning" title="Analysis completed with partial results">
          Some AI-generated details were unavailable. The available results are shown below; run the analysis again to retry the missing step.
        </Alert>
      )}

      <AnimatePresence mode="popLayout">
        {steps.length > 0 && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-2 mb-4">
            {steps.map((step, i) => (
              <motion.div key={step.step} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.1 }} className="flex items-center gap-2 text-sm">
                {step.status === "done" ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-ink-400" />
                ) : step.status === "active" ? (
                  <Loader2 className="w-3.5 h-3.5 text-ink-600 animate-spin" />
                ) : step.status === "error" ? (
                  <AlertTriangle className="w-3.5 h-3.5 text-semantic-danger" />
                ) : (
                  <div className="w-3.5 h-3.5 rounded-full border-2 border-linen-400" />
                )}
                <span className={
                  step.status === "done" ? "text-ink-600" :
                  step.status === "active" ? "text-ink-700 font-medium" :
                  step.status === "error" ? "text-semantic-danger font-medium" :
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
    </section>
  );
}
