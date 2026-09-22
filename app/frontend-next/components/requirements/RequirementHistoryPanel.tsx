"use client";

import { requirementErrorMessage } from "@/lib/requirement-errors";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatLocalDateTime } from "@/lib/date-time";
import { Button } from "@/components/ui";
import type { BusinessRequirement } from "@/lib/requirements-types";

const labels: Record<string, string> = { created: "Requirement captured", edited: "Requirement revised", signed_off: "Business sign-off", story_created: "Story prepared", blocked: "Reopened by a blocking question" };
const fields: [keyof BusinessRequirement, string][] = [["title", "Title"], ["actor", "Stakeholder"], ["action", "Capability"], ["benefit", "Outcome"], ["priority", "Priority"], ["source_id", "Source"], ["evidence_quote", "Evidence"], ["acceptance_criteria", "Acceptance criteria"], ["status", "Agreement status"], ["validated_by", "Signed off by"], ["validated_at", "Signed off at"], ["reviewer_role", "Review capacity"], ["validation_note", "Review note"], ["story", "User story"]];
function value(item: unknown, field: keyof BusinessRequirement): string {
  if (item === null || item === undefined || item === "") return "—";
  if (field === "priority") return ({ must: "Must have", should: "Should have", could: "Could have", wont: "Not this time" } as Record<string, string>)[String(item)] || String(item);
  if (field === "status") return item === "validated" ? "Signed off" : "Draft";
  if (field === "validated_at") return formatLocalDateTime(String(item));
  if (Array.isArray(item)) return item.join("\n");
  if (typeof item === "object" && "statement" in item) {
    const story = item as { statement: string; acceptance_criteria?: string[] };
    return [story.statement, ...(story.acceptance_criteria || []).map(criterion => `• ${criterion}`)].join("\n");
  }
  return String(item);
}

export function RequirementHistoryPanel({ workspaceId, itemId, revision, onClose }: { workspaceId: string; itemId: string; revision: number; onClose: () => void }) {
  const [offset, setOffset] = useState(0);
  const query = useQuery({ queryKey: ["requirement-history", workspaceId, itemId, revision, offset], queryFn: () => api.getRequirementHistory(workspaceId, itemId, offset) });
  return <section className="space-y-4 rounded-xl border border-linen-400 bg-white p-5" aria-label="Requirement history">
    <div className="flex items-center justify-between"><h2 className="font-semibold">Requirement history</h2><Button variant="ghost" onClick={onClose}>Close history</Button></div>
    <p className="text-xs text-ink-500">Historical evidence is read-only. To restore earlier wording, edit the current requirement and obtain a new sign-off.</p>
    {query.isPending && <p role="status">Loading history…</p>}
    {query.isError && <div role="alert"><p className="text-sm text-rust-600">{requirementErrorMessage(query.error)}</p><Button variant="secondary" onClick={() => query.refetch()}>Retry history</Button></div>}
    {query.data?.total === 0 && <p className="text-sm text-ink-500">No history has been recorded yet. Changes made before history tracking was introduced are not reconstructed.</p>}
    {query.data?.items.map(event => <details key={event.id} className="rounded-lg border border-linen-400 p-4">
      <summary className="cursor-pointer text-sm font-semibold">{event.after.reference} · Revision {event.revision} · {labels[event.action] || event.action}</summary>
      <p className="my-3 text-xs text-ink-500">{formatLocalDateTime(event.created_at)} · {event.actor_id || "Former member"}</p>
      <div className="space-y-4">{fields.filter(([key]) => !event.before || JSON.stringify(event.before[key]) !== JSON.stringify(event.after[key])).map(([key, label]) => <div key={key}>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">{label}</h3>
        <div className="mt-1 grid gap-2 sm:grid-cols-2">{event.before && <div className="min-w-0 rounded bg-linen-100 p-3"><p className="text-[10px] text-ink-400">Before</p><pre className="whitespace-pre-wrap break-words font-sans text-xs leading-5">{value(event.before[key], key)}</pre></div>}<div className="min-w-0 rounded bg-moss-500/5 p-3"><p className="text-[10px] text-ink-400">After</p><pre className="whitespace-pre-wrap break-words font-sans text-xs leading-5">{value(event.after[key], key)}</pre></div></div>
      </div>)}</div>
    </details>)}
    {query.data && query.data.total > 10 && <div className="flex items-center justify-between"><Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>Newer changes</Button><span className="text-xs">{query.data.total} changes</span><Button variant="secondary" disabled={offset + 10 >= query.data.total} onClick={() => setOffset(offset + 10)}>Older changes</Button></div>}
  </section>;
}
