"use client";

import { requirementSnapshotsCurrent } from "@/lib/requirement-workspace";
import { requirementErrorMessage } from "@/lib/requirement-errors";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui";
import type { BusinessRequirement, RequirementCrossReview } from "@/lib/requirements-types";

export function CrossReviewPanel({ workspaceId, items, onQuestion }: { workspaceId: string; items: BusinessRequirement[]; onQuestion: (question: string, requirementId: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<RequirementCrossReview | null>(null);
  const [error, setError] = useState("");
  const stale = Boolean(result && !requirementSnapshotsCurrent(result.requirements, items));
  async function review() {
    if (pending) return;
    setPending(true); setError(""); setResult(null);
    try { setResult(await api.crossReviewRequirements(workspaceId, selected)); }
    catch (caught) { setError(requirementErrorMessage(caught)); }
    finally { setPending(false); }
  }
  return <section className="space-y-3 rounded-xl border border-linen-400 bg-white p-4" aria-label="Cross-requirement review">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-semibold">Check how the requirements fit together</h3><p className="mt-1 text-xs text-ink-500">Explore possible conflicts, overlaps and dependencies.</p></div><Button size="sm" variant="secondary" onClick={() => setOpen(!open)}>{open ? "Close cross-check" : "Cross-check scope"}</Button></div>
    {open && <div className="space-y-3">
      <p className="text-xs text-ink-500">Choose 2–8 requirements. AI suggestions do not change scope or sign-off.</p>
      <div className="max-h-48 space-y-2 overflow-y-auto">{items.map(item => <label key={item.id} className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={selected.includes(item.id)} disabled={pending || (!selected.includes(item.id) && selected.length >= 8)} onChange={event => setSelected(event.target.checked ? [...selected, item.id] : selected.filter(id => id !== item.id))} /><span>{item.reference} · {item.title}{item.priority === "wont" ? " · Not this time" : ""}</span></label>)}</div>
      <Button size="sm" pending={pending} disabled={pending || selected.length < 2} onClick={review}>Review selected requirements</Button>
      {error && <p role="alert" className="text-sm text-rust-600">{error}</p>}
      {result && <div className="space-y-3">
        <p className="text-xs text-ink-500">{result.model} · {result.requirements.map(item => `${item.reference} r${item.revision}`).join(", ")}</p>
        {result.input_truncated && <p className="text-xs text-amber-800">Some requirement details did not fit in the analysis. Check the complete requirements before deciding.</p>}
        {stale && <p role="status" className="text-sm text-amber-800">A reviewed requirement has changed. Run a new cross-check before tracking these findings.</p>}
        {result.findings.length === 0 && <p className="text-sm text-ink-500">No findings were suggested. This does not establish that the requirements are complete or consistent.</p>}
        {result.findings.map((finding, index) => <article key={index} className="space-y-2 rounded-lg bg-linen-100 p-3 text-sm"><p className="text-xs font-semibold uppercase text-clay-700">{finding.category.replaceAll("_", " ")} · {finding.references.join(", ")}</p><p>{finding.finding}</p><p className="text-ink-500">{finding.question}</p><Button size="sm" variant="secondary" disabled={Boolean(stale)} onClick={() => onQuestion(`${finding.references.join(", ")}: ${finding.question}`, finding.references.length === 1 ? result.requirements.find(item => item.reference === finding.references[0])?.id || null : null)}>Track review question</Button></article>)}
      </div>}
    </div>}
  </section>;
}
