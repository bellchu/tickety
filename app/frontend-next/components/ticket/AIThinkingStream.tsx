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
import { analysisErrorDetails } from "@/lib/analysis-errors";
import { ListChecks, Loader2, CheckCircle2, RefreshCw, AlertTriangle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Alert, Button } from "@/components/ui";

interface Props {
  ticketId: string;
  hasExisting?: boolean;
  recoveryState?: string | null;
  onComplete?: (result: TicketAnalysisResult) => void;
  compact?: boolean;
}

export function AIThinkingStream({ ticketId, hasExisting, recoveryState, onComplete, compact = false }: Props) {
  const [steps, setSteps] = useState<TriageStep[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TicketAnalysisResult | null>(null);
  const [error, setError] = useState("");
  const wsRef = useRef<ReturnType<typeof createTicketStreamWS> | null>(null);
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();
  const recoveryQueued = recoveryState === "queued";

  const clearWatchdog = () => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  };

  const startWatchdog = (timeoutSeconds: unknown, onTimeout: () => void) => {
    clearWatchdog();
    watchdogRef.current = setTimeout(onTimeout, triageWatchdogDelayMs(timeoutSeconds));
  };

  const startHandshakeWatchdog = (onTimeout: () => void) => {
    clearWatchdog();
    watchdogRef.current = setTimeout(onTimeout, 30_000);
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
    const ws = createTicketStreamWS(ticketId);
    wsRef.current = ws;
    let settled = false;
    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      finishWithError(message);
    };
    startHandshakeWatchdog(() => fail("The analysis stream could not start. Check your connection and try again."));
    ws.onMessage((data) => {
      if (!data || typeof data !== "object") {
        fail("The analysis stream returned an unexpected message. Please try again.");
        return;
      }
      if (data.type === "progress") {
        if (!isTriageProgressMessage(data)) {
          fail("The analysis stream returned an unexpected message. Please try again.");
          return;
        }
        startWatchdog(data.timeout_seconds, () => fail("The analysis timed out before it completed. Please try again."));
        setSteps(data.steps);
      } else if (data.type === "complete") {
        const payload = data.result;
        if (!isTicketAnalysisResult(payload, ticketId)) {
          fail("The analysis returned an unexpected result. Please try again.");
          return;
        }
        const result = payload;
        settled = true;
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
        fail(typeof data.message === "string" ? data.message : "The analysis stream stopped before it completed.");
      }
    });
    ws.onClose((event) => {
      fail(
        event.code === 1008
          ? "Your session is not permitted to run this analysis. Refresh your access and try again."
          : "The analysis connection closed before processing began. Please try again."
      );
    });
    ws.onError(() => {
      fail("The analysis connection could not be established. Please try again.");
    });
    ws.connect();
  };

  return (
    <section className={compact ? "border-t border-linen-300 pt-4" : "rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:px-5"} aria-labelledby="ai-analysis-title" aria-busy={running}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-linen-200 text-ink-600">
            <ListChecks className="h-4 w-4" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 id="ai-analysis-title" className="text-sm font-semibold text-ink-700">AI analysis</h3>
            <p className="mt-0.5 text-xs text-ink-500">
              {running
                ? "Analyzing the ticket and refreshing decision support…"
                : recoveryQueued
                  ? "Missing steps are queued for automatic retry."
                : result
                  ? "Analysis finished; the guidance below has been refreshed."
                  : hasExisting
                    ? "Latest guidance is available below."
                    : "No analysis has been run for this ticket yet."}
            </p>
          </div>
        </div>
        <Button variant="secondary" size="sm" onClick={startTriage} pending={running} pendingLabel="Analyzing…" disabled={recoveryQueued} leadingIcon={<RefreshCw className="h-3.5 w-3.5" />}>
          {recoveryQueued ? "Retry scheduled" : hasExisting || result ? "Re-run analysis" : "Run analysis"}
        </Button>
      </div>

      {error && <Alert className="mt-4" variant="danger" title="Analysis did not complete">{error}</Alert>}

      {result && result.errors.length > 0 && (
        <Alert className="mt-4" variant="warning" title="Analysis completed with partial results">
          {analysisErrorDetails(result.errors)}. Available results remain visible. Tickety will automatically retry only the missing steps while retry capacity remains.
        </Alert>
      )}

      <AnimatePresence mode="popLayout">
        {running && steps.length > 0 && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-4 grid gap-2 border-t border-linen-300 pt-4 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((step, i) => (
              <motion.div key={step.step} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }} className="flex min-w-0 items-center gap-2 rounded-lg bg-linen-100 px-2.5 py-2 text-xs">
                {step.status === "done" ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-semantic-success" />
                ) : step.status === "active" ? (
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-ink-600" />
                ) : step.status === "error" ? (
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-semantic-danger" />
                ) : (
                  <div className="h-3.5 w-3.5 shrink-0 rounded-full border-2 border-linen-400" />
                )}
                <span title={step.label} className={`min-w-0 whitespace-normal break-words [overflow-wrap:anywhere] ${
                  step.status === "done" ? "text-ink-600" :
                  step.status === "active" ? "text-ink-700 font-medium" :
                  step.status === "error" ? "text-semantic-danger font-medium" :
                  "text-ink-400"
                }`}>
                  {step.label}
                </span>
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
