"use client";

import { RequirementTextarea, RequirementInput } from "./BoundedText";

import { inputStyle } from "./fields";
import { currentScopeBlockers, decisionWindow, filterDecisions, type DecisionFilter } from "@/lib/requirement-workspace";
import { requirementErrorMessage } from "@/lib/requirement-errors";

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { captureRequirementDraftSave, readRequirementDecisionDraft, rememberRequirementDecisionDraft } from "@/lib/requirement-editor-cache";
import { Button, ConfirmDialog } from "@/components/ui";
import { api, APIError } from "@/lib/api";
import { formatLocalDateTime } from "@/lib/date-time";
import type { BusinessRequirement, RequirementDecision } from "@/lib/requirements-types";

export function DecisionLog({ workspaceId, userId, requirements, decisions, open, onToggle, scope, onScopeChange, seed, onSeedUsed, onSaved, pending, onPendingChange, onFindRequirements, decisionRequest }: {
  workspaceId: string; userId: string; requirements: BusinessRequirement[]; decisions: RequirementDecision[];
  open: boolean; onToggle: () => void;
  pending: boolean; onPendingChange: (pending: boolean) => void;
  onFindRequirements: (requirementId: string | null) => void;
  scope: string; onScopeChange: (value: string) => void;
  decisionRequest?: { id: string; includeRecorded?: boolean } | null;
  seed: { question: string; requirementId: string | null } | null;
  onSeedUsed: () => void; onSaved: () => Promise<unknown>;
}) {
  const client = useQueryClient();
  const [restored] = useState(() => readRequirementDecisionDraft(client, userId, workspaceId));
  const [transition, setTransition] = useState<(() => void) | null>(null);
  const [question, setQuestion] = useState(restored?.question || "");
  const [owner, setOwner] = useState(restored?.owner || "");
  const [requirementId, setRequirementId] = useState(restored?.requirementId || "");
  const [blocking, setBlocking] = useState(restored?.blocking ?? true);
  const [resolving, setResolving] = useState(restored?.resolving || "");
  const [resolution, setResolution] = useState(restored?.resolution || "");
  const [error, setError] = useState("");
  const [recordedScope, setRecordedScope] = useState<string | null | undefined>(undefined);
  const [view, setView] = useState<DecisionFilter>("open");
  const [search, setSearch] = useState("");
  const [registerWindow, setRegisterWindow] = useState({ key: "", limit: 20 });
  useEffect(() => {
    if (decisionRequest) { setView(decisionRequest.includeRecorded ? "all" : "open"); setSearch(""); }
  }, [decisionRequest]);
  const hasQuestion = Boolean(question || owner || requirementId || !blocking);
  const hasAnswer = Boolean(resolving && resolution);
  useEffect(() => {
    rememberRequirementDecisionDraft(client, userId, workspaceId, hasQuestion || hasAnswer ? { question, owner, requirementId, blocking, resolving, resolution } : null);
  }, [client, userId, workspaceId, hasQuestion, hasAnswer, question, owner, requirementId, blocking, resolving, resolution]);
  useEffect(() => {
    if (!seed || pending) return;
    const apply = () => { setQuestion(seed.question); setRequirementId(seed.requirementId || ""); setOwner(""); setBlocking(true); };
    if (hasQuestion) setTransition(() => apply);
    else apply();
    onSeedUsed();
  }, [seed, onSeedUsed, pending, hasQuestion]);
  function clearQuestion() {
    rememberRequirementDecisionDraft(client, userId, workspaceId, hasAnswer ? { question: "", owner: "", requirementId: "", blocking: true, resolving, resolution } : null);
    setQuestion(""); setOwner(""); setRequirementId(""); setBlocking(true);
  }
  function clearAnswer() {
    rememberRequirementDecisionDraft(client, userId, workspaceId, hasQuestion ? { question, owner, requirementId, blocking, resolving: "", resolution: "" } : null);
    setResolving(""); setResolution("");
  }
  function changeAnswer(id: string) {
    const apply = () => { setResolving(id); setResolution(""); };
    if (hasAnswer) setTransition(() => apply);
    else apply();
  }
  async function save(operation: () => Promise<unknown>, done: () => void) {
    if (pending) return;
    const isCurrent = captureRequirementDraftSave(client, userId, workspaceId, "decision");
    onPendingChange(true); setError(""); setRecordedScope(undefined);
    try { await operation(); if (isCurrent()) done(); await onSaved(); }
    catch (caught) {
      setError(requirementErrorMessage(caught));
      if (caught instanceof APIError && caught.status === 409) {
        try { await onSaved(); } catch { /* Keep the original conflict and the draft available. */ }
      }
    }
    finally { onPendingChange(false); }
  }
  const outstanding = useMemo(() => decisions.filter(item => item.status === "open"), [decisions]);
  const visibleDecisions = useMemo(() => {
    const matching = filterDecisions(decisions, view, search, resolving, scope, requirements);
    return decisionRequest?.id ? matching.sort((left, right) => Number(right.id === decisionRequest.id) - Number(left.id === decisionRequest.id)) : matching;
  }, [decisions, view, search, resolving, scope, decisionRequest, requirements]);
  const requirementNames = useMemo(() => new Map(requirements.map(item => [item.id, `${item.reference}${item.priority === "wont" ? " · Not this time" : ""}`])), [requirements]);
  const blockers = useMemo(() => outstanding.filter(item => item.blocking).length, [outstanding]);
  const currentBlockers = useMemo(() => currentScopeBlockers(requirements, decisions).length, [requirements, decisions]);
  const windowKey = JSON.stringify([view, search, scope]);
  const limit = registerWindow.key === windowKey ? registerWindow.limit : 20;
  const displayedDecisions = useMemo(() => decisionWindow(visibleDecisions, limit, resolving), [visibleDecisions, limit, resolving]);
  function affectedRequirementsLink(requirementId: string | null) {
    if (requirementId && !requirementNames.has(requirementId)) return null;
    return <a href="#requirement-list" onClick={() => onFindRequirements(requirementId)} className="inline-flex text-sm font-medium text-clay-700 underline underline-offset-2">{requirementId ? `Find ${requirementNames.get(requirementId)}` : "View initiative requirements"}</a>;
  }
  return <section id="business-decisions" tabIndex={-1} className="rounded-xl border border-linen-400 bg-white p-5" aria-label="Business decision log">
    <ConfirmDialog open={Boolean(transition)} onOpenChange={open => { if (!open) setTransition(null); }} title="Replace unsaved decision work?" description="The current question or answer will be discarded. Saved decisions are unchanged." cancelLabel="Keep editing" confirmLabel="Discard and continue" destructive onConfirm={() => { const action = transition; setTransition(null); action?.(); }} />
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-ink-700">Questions & decisions</h2><p className="mt-1 text-xs text-ink-500">{outstanding.length} open · {blockers} blocking · {decisions.length - outstanding.length} decisions recorded</p></div><Button variant="secondary" onClick={onToggle}>{open ? "Close decision log" : "Open decision log"}</Button></div>
    {blockers > 0 && <p className="mt-2 text-xs text-amber-800">{currentBlockers} affect current scope or need scope confirmation · {blockers - currentBlockers} relate only to deferred requirements</p>}
    {open && <div className="mt-5 space-y-5">
      <form className="grid gap-3 rounded-lg bg-linen-100 p-4" onSubmit={event => { event.preventDefault(); void save(() => api.addRequirementDecision(workspaceId, { question, owner_role: owner, requirement_id: requirementId || null, blocking }), clearQuestion); }}>
        <h3 className="text-sm font-semibold">Raise a business question</h3>
        {hasQuestion && <p role="status" className="text-xs text-amber-800">Unsaved question · Kept in this tab while you browse.</p>}
        <fieldset disabled={pending} className="contents">
        <label className="space-y-1 text-sm">Question or assumption to resolve<RequirementTextarea className={inputStyle} required minLength={10} maxLength={4000} value={question} onChange={event => setQuestion(event.target.value)} /></label>
        <div className="grid gap-3 md:grid-cols-2"><label className="space-y-1 text-sm">Who needs to provide the answer?<RequirementInput className={inputStyle} required maxLength={200} placeholder="For example: Procurement lead" value={owner} onChange={event => setOwner(event.target.value)} /></label>
        <label className="space-y-1 text-sm">Affected scope<select className={inputStyle} value={requirementId} onChange={event => setRequirementId(event.target.value)}><option value="">Whole initiative</option>{requirements.map(item => <option key={item.id} value={item.id}>{item.reference} · {item.title}</option>)}</select></label></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={blocking} onChange={event => setBlocking(event.target.checked)} />Must be answered before sign-off</label>
        {blocking && <p className="text-xs text-amber-800">This reopens affected requirements and withdraws their current stories. Recording an answer will still require a new sign-off.</p>}
        <p className="text-xs text-ink-500">The answer owner is recorded for follow-up; this does not send a notification or grant access.</p>
        <Button type="submit" className="justify-self-start" pending={pending} disabled={pending}>Track question</Button>
        {hasQuestion && <Button variant="ghost" disabled={pending} onClick={() => setTransition(() => clearQuestion)}>Discard question draft</Button>}
        </fieldset>
      </form>
      {hasAnswer && !outstanding.some(item => item.id === resolving) && <div className="space-y-2 rounded-lg bg-amber-50 p-3 text-sm">
        <p>The question for your unsaved answer is no longer open. Copy any useful notes before discarding this draft.</p>
        <textarea aria-label="Unsubmitted decision notes" readOnly className={inputStyle} value={resolution} />
        <Button variant="ghost" disabled={pending} onClick={() => setTransition(() => clearAnswer)}>Discard answer draft</Button>
      </div>}
      {recordedScope !== undefined && <div role="status" className="space-y-2 rounded-lg bg-moss-500/10 p-3 text-sm text-moss-700">
        <p>Decision recorded. Check the affected requirements and acceptance criteria against this answer before signing off. Recording an answer does not update their wording or restore a previous sign-off.</p>
        {affectedRequirementsLink(recordedScope)}
      </div>}
      {error && <p role="alert" className="text-sm text-rust-600">{error}</p>}
      <h3 className="text-sm font-semibold">Decision register</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1 text-sm">Find questions, owners or decisions<input type="search" className={inputStyle} value={search} onChange={event => setSearch(event.target.value)} /></label>
        <label className="space-y-1 text-sm">Show decisions<select className={inputStyle} value={view} onChange={event => setView(event.target.value as DecisionFilter)}>
          <option value="open">Open questions</option><option value="current">Current delivery blockers</option><option value="blocking">All sign-off blockers</option><option value="exploratory">Exploratory questions</option><option value="recorded">Recorded decisions</option><option value="all">All questions & decisions</option>
        </select></label>
      </div>
      <label className="block space-y-1 text-sm">Decisions affecting<select className={inputStyle} value={scope} onChange={event => onScopeChange(event.target.value)}><option value="">All requirements</option>{requirements.map(item => <option key={item.id} value={item.id}>{item.reference} · {item.title}</option>)}</select></label>
      {view === "open" && <p className="text-xs text-ink-500">{decisionRequest?.id ? "The suggested question appears first when it matches this view. Other blocking questions follow in recorded order." : "Questions blocking sign-off appear first; each group keeps its recorded order."}</p>}
      {scope && <p className="text-xs text-ink-500">Includes whole-initiative questions and decisions, which also affect this requirement.</p>}
      {view === "current" && <p className="text-xs text-ink-500">Includes current delivery and scope needing confirmation. Questions linked only to deferred requirements are excluded.</p>}
      {resolving && <p className="text-xs text-ink-500">The question you are answering stays visible while you filter.</p>}
      {displayedDecisions.map(item => <article key={item.id} className="space-y-3 rounded-lg border border-linen-400 p-4">
        {item.id === decisionRequest?.id && <p className="text-xs font-semibold text-clay-700">Suggested business question</p>}
        <div className="flex flex-wrap justify-between gap-2 text-xs text-ink-500"><span>{item.requirement_id ? requirementNames.get(item.requirement_id) || "Requirement unavailable" : "Whole initiative"} · {item.owner_role}</span><span>{item.status === "resolved" ? "Decision recorded" : item.blocking ? "Blocks sign-off" : "Exploratory"}</span></div>
        <h4 className="text-sm font-semibold">{item.question}</h4>
        {affectedRequirementsLink(item.requirement_id)}
        {item.status === "resolved" ? <><p className="whitespace-pre-wrap text-sm text-ink-600">{item.resolution}</p><p className="text-xs text-ink-400">Recorded by {item.resolved_by || "Former member"} · {formatLocalDateTime(item.resolved_at!)}</p></> : resolving === item.id ? <form className="space-y-3" onSubmit={event => { event.preventDefault(); void save(() => api.resolveRequirementDecision(workspaceId, item.id, resolution), () => { clearAnswer(); setRecordedScope(item.requirement_id); }); }}>
          {hasAnswer && <p role="status" className="text-xs text-amber-800">Unsaved answer · Kept in this tab while you browse.</p>}
          <label className="block space-y-1 text-sm">Decision and rationale<RequirementTextarea disabled={pending} required minLength={10} maxLength={4000} className={inputStyle} value={resolution} onChange={event => setResolution(event.target.value)} placeholder="What was decided, with whom, and why? Update the requirement separately if its scope changes." /></label>
          <div className="flex gap-2"><Button type="submit" pending={pending} disabled={pending}>Record decision</Button><Button variant="ghost" disabled={pending} onClick={() => changeAnswer("")}>Cancel</Button></div>
        </form> : <Button variant="secondary" size="sm" disabled={pending} onClick={() => changeAnswer(item.id)}>Record an answer</Button>}
      </article>)}
      {visibleDecisions.length > 20 && <div className="flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-xs text-ink-500">Showing {displayedDecisions.length} of {visibleDecisions.length} matching records. Search covers the complete decision register.</p>{displayedDecisions.length < visibleDecisions.length && <Button variant="secondary" onClick={() => setRegisterWindow({ key: windowKey, limit: limit + 20 })}>Show more records</Button>}</div>}
      {!visibleDecisions.length && <p role="status" className="text-sm text-ink-500">{decisions.length ? "No questions or decisions match this view. Change the filter or search to see more." : "No business questions are tracked yet."}</p>}
    </div>}
  </section>;
}
