"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { TicketCreateInput } from "@/lib/types";
import { X, Plus, Loader2 } from "lucide-react";

const PRIORITIES = [
  { value: "P3", label: "P3 — Low" },
  { value: "P2", label: "P2 — Medium" },
  { value: "P1", label: "P1 — High" },
];

interface Props {
  open: boolean;
  onClose: () => void;
}

export function NewTicketModal({ open, onClose }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<TicketCreateInput>({
    subject: "",
    description: "",
    reporter: "",
    priority: "P3",
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.createTicket(form),
    onSuccess: (ticket) => {
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      reset();
      onClose();
      router.push(`/tickets/${ticket.id}`);
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });

  const reset = () => {
    setForm({ subject: "", description: "", reporter: "", priority: "P3" });
    setError(null);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink-700/40 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-lg bg-linen-50 shadow-xl border border-linen-400">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-linen-300">
          <div className="flex items-center gap-2">
            <Plus className="w-5 h-5 text-ink-600" />
            <h2 className="text-base font-semibold text-ink-700">
              New Ticket
            </h2>
          </div>
          <button
            onClick={() => {
              reset();
              onClose();
            }}
            className="text-ink-400 hover:text-ink-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-ink-600">Subject</span>
            <input
              type="text"
              value={form.subject}
              onChange={(e) =>
                setForm((f) => ({ ...f, subject: e.target.value }))
              }
              placeholder="Brief summary of the ticket"
              className="input-base w-full"
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-ink-600">
              Description
            </span>
            <textarea
              rows={4}
              value={form.description}
              onChange={(e) =>
                setForm((f) => ({ ...f, description: e.target.value }))
              }
              placeholder="Full details the AI will read for sentiment, category, and priority analysis…"
              className="input-base w-full resize-y"
            />
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-ink-600">
                Reporter
              </span>
              <input
                type="text"
                value={form.reporter}
                onChange={(e) =>
                  setForm((f) => ({ ...f, reporter: e.target.value }))
                }
                placeholder="Name or email"
                className="input-base w-full"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-ink-600">
                Priority
              </span>
              <select
                value={form.priority}
                onChange={(e) =>
                  setForm((f) => ({ ...f, priority: e.target.value }))
                }
                className="input-base w-full"
              >
                {PRIORITIES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {error && (
            <p className="text-sm text-rust-500 bg-red-50 rounded-lg p-3 border border-red-100">
              {error}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-5 py-4 border-t border-linen-300">
          <button
            type="button"
            onClick={() => {
              reset();
              onClose();
            }}
            disabled={mutation.isPending}
            className="btn-secondary text-xs"
          >
            Cancel
          </button>
          <button
            type="submit"
            onClick={() => mutation.mutate()}
            disabled={
              mutation.isPending || form.subject.trim().length === 0
            }
            className="btn-primary text-xs"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Creating…
              </>
            ) : (
              <>
                <Plus className="w-3.5 h-3.5" /> Create Ticket
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
