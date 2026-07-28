"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { TicketCreateInput } from "@/lib/types";
import { Plus } from "lucide-react";
import { Alert, Button, Dialog } from "@/components/ui";

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

  const close = () => {
    if (mutation.isPending) return;
    reset();
    onClose();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => { if (!next) close(); }}
      title="Create a ticket"
      description="Capture enough context for an agent to prioritize and begin work. AI analysis runs separately after creation."
      dismissible={!mutation.isPending}
      footer={<><Button variant="secondary" onClick={close} disabled={mutation.isPending}>Cancel</Button><Button onClick={() => mutation.mutate()} disabled={!form.subject.trim()} pending={mutation.isPending} pendingLabel="Creating…" leadingIcon={<Plus className="h-4 w-4" />}>Create ticket</Button></>}
    >
        <div className="space-y-4">
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
          <div className="grid gap-4 sm:grid-cols-2">
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
            <Alert variant="danger" title="Ticket could not be created">{error}</Alert>
          )}
        </div>
    </Dialog>
  );
}
