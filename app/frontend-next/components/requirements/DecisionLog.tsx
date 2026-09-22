"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";
import { formatLocalDateTime } from "@/lib/date-time";
import type { BusinessRequirement, RequirementDecision } from "@/lib/requirements-types";

const input = "w-full rounded-lg border border-linen-500 bg-white px-3 py-2 text-sm text-ink-700";
export function DecisionLog({ workspaceId, requirements, decisions, open, onToggle, seed, onSeedUsed, onSaved }: {
  workspaceId: string; requirements: BusinessRequirement[]; decisions: RequirementDecision[];
  open: boolean; onToggle: () => void;
  seed: { question: string; requirementId: string | null } | null;
  onSeedUsed: () => void; onSaved: () => Promise<unknown>;
}) {
  const [question, setQuestion] = useState("");
  const [owner, setOwner] = useState("");
  const [requirementId, setRequirementId] = useState("");
  const [blocking, setBlocking] = useState(true);
  const [resolving, setResolving] = useState("");
  const [resolution, setResolution] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  useEffect(() => {
    if (seed) { setQuestion(seed.question); setRequirementId(seed.requirementId || ""); onSeedUsed(); }
  }, [seed, onSeedUsed]);
  async function save(operation: () => Promise<unknown>, done: () => void) {
    if (pending) return;
    setPending(true); setError("");
    try { await operation(); done(); await onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not save the decision."); }
    finally { setPending(false); }
  }
  const outstanding = decisions.filter(item => item.status === "open");
  const blockers = outstanding.filter(item => item.blocking).length;
  return <section className="rounded-xl border border-linen-400 bg-white p-5" aria-label="Business decision log">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-ink-700">Questions & decisions</h2><p className="mt-1 text-xs text-ink-500">{outstanding.length} open · {blockers} blocking · {decisions.length - outstanding.length} decisions recorded</p></div><Button variant="secondary" onClick={onToggle}>{open ? "Close decision log" : "Open decision log"}</Button></div>
    {open && <div className="mt-5 space-y-5">
      <form className="grid gap-3 rounded-lg bg-linen-100 p-4" onSubmit={event => { event.preventDefault(); void save(() => api.addRequirementDecision(workspaceId, { question, owner_role: owner, requirement_id: requirementId || null, blocking }), () => { setQuestion(""); }); }}>
        <h3 className="text-sm font-semibold">Raise a business question</h3>
        <label className="space-y-1 text-sm">Question or assumption to resolve<textarea className={input} required minLength={10} maxLength={4000} value={question} onChange={event => setQuestion(event.target.value)} /></label>
        <div className="grid gap-3 md:grid-cols-2"><label className="space-y-1 text-sm">Who needs to provide the answer?<input className={input} required maxLength={200} placeholder="For example: Procurement lead" value={owner} onChange={event => setOwner(event.target.value)} /></label>
        <label className="space-y-1 text-sm">Affected scope<select className={input} value={requirementId} onChange={event => setRequirementId(event.target.value)}><option value="">Whole initiative</option>{requirements.map(item => <option key={item.id} value={item.id}>{item.reference} · {item.title}</option>)}</select></label></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={blocking} onChange={event => setBlocking(event.target.checked)} />Must be answered before sign-off</label>
        {blocking && <p className="text-xs text-amber-800">This reopens affected requirements and withdraws their current stories. Recording an answer will still require a new sign-off.</p>}
        <p className="text-xs text-ink-500">The answer owner is recorded for follow-up; this does not send a notification or grant access.</p>
        <Button type="submit" className="justify-self-start" pending={pending} disabled={pending}>Track question</Button>
      </form>
      {error && <p role="alert" className="text-sm text-rust-600">{error}</p>}
      <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">Decision register</h3><label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={showHistory} onChange={event => setShowHistory(event.target.checked)} />Include recorded decisions</label></div>
      {decisions.filter(item => showHistory || item.status === "open").map(item => <article key={item.id} className="space-y-3 rounded-lg border border-linen-400 p-4">
        <div className="flex flex-wrap justify-between gap-2 text-xs text-ink-500"><span>{item.requirement_id ? requirements.find(row => row.id === item.requirement_id)?.reference : "Whole initiative"} · {item.owner_role}</span><span>{item.status === "resolved" ? "Decision recorded" : item.blocking ? "Blocks sign-off" : "Exploratory"}</span></div>
        <h4 className="text-sm font-semibold">{item.question}</h4>
        {item.status === "resolved" ? <><p className="whitespace-pre-wrap text-sm text-ink-600">{item.resolution}</p><p className="text-xs text-ink-400">Recorded by {item.resolved_by || "Former member"} · {formatLocalDateTime(item.resolved_at!)}</p></> : resolving === item.id ? <form className="space-y-3" onSubmit={event => { event.preventDefault(); void save(() => api.resolveRequirementDecision(workspaceId, item.id, resolution), () => { setResolving(""); setResolution(""); }); }}>
          <label className="block space-y-1 text-sm">Decision and rationale<textarea required minLength={10} maxLength={4000} className={input} value={resolution} onChange={event => setResolution(event.target.value)} placeholder="What was decided, with whom, and why? Update the requirement separately if its scope changes." /></label>
          <div className="flex gap-2"><Button type="submit" pending={pending} disabled={pending}>Record decision</Button><Button variant="ghost" disabled={pending} onClick={() => setResolving("")}>Cancel</Button></div>
        </form> : <Button variant="secondary" size="sm" disabled={pending} onClick={() => { setResolving(item.id); setResolution(""); }}>Record an answer</Button>}
      </article>)}
      {!outstanding.length && !showHistory && <p className="text-sm text-ink-500">No open business questions are tracked.</p>}
    </div>}
  </section>;
}
