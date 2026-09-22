"use client";

import { filterRequirements, requirementSnapshotsCurrent } from "@/lib/requirement-workspace";
import { reviewQuestionDraft } from "@/lib/requirement-review-question";
import { requirementErrorMessage } from "@/lib/requirement-errors";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui";
import { Field, inputStyle } from "./fields";
import type { BusinessRequirement, RequirementCrossReview } from "@/lib/requirements-types";

export function CrossReviewPanel({ workspaceId, items, onQuestion }: { workspaceId: string; items: BusinessRequirement[]; onQuestion: (question: string, requirementId: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<RequirementCrossReview | null>(null);
  const [error, setError] = useState("");
  const matching = useMemo(() => open ? filterRequirements(items, search, "all") : [], [open, items, search]);
  const chosen = useMemo(() => open ? items.filter(item => selected.includes(item.id)) : [], [open, items, selected]);
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
      <Field label="Find requirements for cross-check"><input type="search" className={inputStyle} value={search} onChange={event => setSearch(event.target.value)} placeholder="Search a reference, outcome or acceptance criterion…" /></Field>
      <p role="status" className="text-xs text-ink-500">{selected.length} / 8 selected · {matching.length} matching requirements</p>
      {chosen.length > 0 && <div className="space-y-1" aria-label="Selected requirements for cross-check">{chosen.map(item => <div key={item.id} className="flex items-center justify-between gap-2 rounded-lg bg-linen-100 px-2 py-1 text-xs"><span>{item.reference} · {item.title}{item.priority === "wont" ? " · Not this time" : ""}</span><Button size="sm" variant="ghost" disabled={pending} aria-label={`Remove ${item.reference} from cross-check`} onClick={() => setSelected(selected.filter(id => id !== item.id))}>Remove</Button></div>)}</div>}
      {matching.length === 0 && <p className="text-xs text-ink-500">No matching requirements. Your selection is kept; change the search to find more.</p>}
      <div className="max-h-48 space-y-2 overflow-y-auto">{matching.map(item => <label key={item.id} className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={selected.includes(item.id)} disabled={pending || (!selected.includes(item.id) && selected.length >= 8)} onChange={event => setSelected(event.target.checked ? [...selected, item.id] : selected.filter(id => id !== item.id))} /><span>{item.reference} · {item.title}{item.priority === "wont" ? " · Not this time" : ""}</span></label>)}</div>
      <Button size="sm" pending={pending} disabled={pending || selected.length < 2} onClick={review}>Review selected requirements</Button>
      {error && <p role="alert" className="text-sm text-rust-600">{error}</p>}
      {result && <div className="space-y-3">
        <p className="text-xs text-ink-500">{result.model} · {result.requirements.map(item => `${item.reference} r${item.revision}`).join(", ")}</p>
        {result.input_truncated && <p className="text-xs text-amber-800">Some requirement details did not fit in the analysis. Check the complete requirements before deciding.</p>}
        {stale && <p role="status" className="text-sm text-amber-800">A reviewed requirement has changed. Run a new cross-check before tracking these findings.</p>}
        {result.findings.length === 0 && <p className="text-sm text-ink-500">No findings were suggested. This does not establish that the requirements are complete or consistent.</p>}
        {result.findings.map((finding, index) => <article key={index} className="space-y-2 rounded-lg bg-linen-100 p-3 text-sm"><p className="text-xs font-semibold uppercase text-clay-700">{finding.category.replaceAll("_", " ")} · {finding.references.join(", ")}</p><p>{finding.finding}</p><p className="text-ink-500">{finding.question}</p><Button size="sm" variant="secondary" disabled={Boolean(stale)} onClick={() => onQuestion(reviewQuestionDraft(finding.question, finding.finding, finding.references.flatMap(reference => result.requirements.filter(item => item.reference === reference))), finding.references.length === 1 ? result.requirements.find(item => item.reference === finding.references[0])?.id || null : null)}>Track review question</Button></article>)}
      </div>}
    </div>}
  </section>;
}
