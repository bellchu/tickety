"use client";

import { readRequirementEditor, rememberRequirementEditor, readRequirementSourceDraft, readRequirementDecisionDraft } from "@/lib/requirement-editor-cache";
import { parseRequirementCriteria } from "@/lib/requirement-criteria";
import { requirementErrorMessage } from "@/lib/requirement-errors";

import { Suspense, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ClipboardList, Download, FileText, Plus, Sparkles, ArrowUpRight } from "lucide-react";
import { requirementBrief, requirementStoryText } from "@/lib/requirement-export";
import { RequirementHistoryPanel } from "@/components/requirements/RequirementHistoryPanel";
import { CrossReviewPanel } from "@/components/requirements/CrossReviewPanel";
import { SourceExplorer } from "@/components/requirements/SourceExplorer";
import { SourceIntakeForm } from "@/components/requirements/SourceIntakeForm";
import { Field, inputStyle, panelStyle, kinds } from "@/components/requirements/fields";
import { DecisionLog } from "@/components/requirements/DecisionLog";
import { RequirementCard } from "@/components/requirements/RequirementCard";
import { blockedRequirementIds, filterRequirements, workspaceFocus, type RequirementFilter } from "@/lib/requirement-workspace";
import { api } from "@/lib/api";
import type { BusinessRequirement, GatherSuggestions, RequirementAssistance, RequirementDraft, RequirementPriority, RequirementWorkspaceDetail } from "@/lib/requirements-types";
import { Button, ConfirmDialog } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";
import { formatLocalDateTime } from "@/lib/date-time";

const priorities: Record<RequirementPriority, string> = { must: "Must have", should: "Should have", could: "Could have", wont: "Not this time" };
const blankDraft: RequirementDraft = { source_id: "", title: "", actor: "", action: "", benefit: "", evidence_quote: "", acceptance_criteria: [], priority: "should" };
function ErrorMessage({ error }: { error: unknown }) {
  return error ? <p role="alert" className="rounded-lg border border-rust-400/30 bg-rust-400/10 p-3 text-sm text-rust-600">{requirementErrorMessage(error)}</p> : null;
}

function exportBrief(detail: RequirementWorkspaceDetail) {
  const blob = new Blob([requirementBrief(detail)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "business-requirements.md";
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function RequirementsPage() {
  return <Suspense fallback={<p role="status">Loading requirements…</p>}><RequirementsContent /></Suspense>;
}

function RequirementsContent() {
  const router = useRouter();
  const params = useSearchParams();
  const selected = params.get("initiative") || null;
  function initiativeURL(id: string | null) {
    const query = new URLSearchParams(params.toString());
    if (id) query.set("initiative", id);
    else query.delete("initiative");
    return `/requirements${query.size ? `?${query.toString()}` : ""}`;
  }
  function setSelected(id: string | null) { router.push(initiativeURL(id)); }
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [requestType, setRequestType] = useState<"approved_project" | "enhancement">("approved_project");
  const queryClient = useQueryClient();
  const auth = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const allowed = !auth.isError && auth.data?.auth_kind === "session" && auth.data?.is_active && ["agent", "supervisor", "admin"].includes(auth.data.role.toLowerCase());
  const list = useQuery({ queryKey: ["requirement-workspaces", offset], queryFn: () => api.getRequirementWorkspaces(offset), enabled: Boolean(allowed) && !selected });

  async function create(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true); setError(null);
    try {
      const workspace = await api.createRequirementWorkspace({ title, objective, request_type: requestType });
      await queryClient.invalidateQueries({ queryKey: ["requirement-workspaces"] });
      setSelected(workspace.id); setCreating(false); setTitle(""); setObjective("");
    } catch (caught) { setError(caught); }
    finally { setPending(false); }
  }

  if (auth.isPending) return <p role="status">Checking access…</p>;
  if (!allowed) return <PageFrame><PageHeader title="Requirements" description="Sign in with an active operations account to work with business requirements." /><ErrorMessage error={auth.error} /></PageFrame>;
  if (selected) return <Workspace key={`${auth.data.id}:${selected}`} userId={auth.data.id} id={selected} canAI={auth.data?.app_mode === "production" || auth.data?.role.toLowerCase() === "admin"} onBack={() => setSelected(null)} />;

  return <PageFrame>
    <PageHeader eyebrow="Business operations" icon={<ClipboardList size={16} />} title="Business requirements, in context" description="A shared place to understand the need, resolve uncertainty, and shape work worth delivering." actions={<Button leadingIcon={<Plus size={16} />} onClick={() => setCreating(!creating)}>New initiative</Button>} />
    {creating && <form onSubmit={create} aria-busy={pending} className={panelStyle}>
      <fieldset disabled={pending} className="space-y-4">
      <h2 className="text-lg font-semibold">Start an initiative</h2>
      <Field label="Initiative name"><input required maxLength={200} value={title} onChange={event => setTitle(event.target.value)} className={inputStyle} placeholder="For example: simplify supplier onboarding" /></Field>
      <Field label="Request type"><select className={inputStyle} value={requestType} onChange={event => setRequestType(event.target.value as "approved_project" | "enhancement")}><option value="approved_project">Approved project / request</option><option value="enhancement">Enhancement</option></select></Field>
      <Field label="Business objective"><textarea required minLength={10} maxLength={4000} rows={3} value={objective} onChange={event => setObjective(event.target.value)} className={inputStyle} placeholder="What outcome should improve, and for whom?" /></Field>
      <p className="text-xs text-ink-500">Visible to you and workspace administrators.</p>
      <ErrorMessage error={error} /><Button type="submit" pending={pending}>Create initiative</Button>
      </fieldset>
    </form>}
    <ErrorMessage error={list.error} />
    {list.isError && <Button variant="secondary" onClick={() => list.refetch()}>Retry loading initiatives</Button>}
    {list.isPending && <p role="status">Loading initiatives…</p>}
    {list.data?.items.length === 0 && <div className={`${panelStyle} text-center`}><FileText className="mx-auto mb-3 text-ink-400" /><h2 className="font-semibold">Start with a business question</h2><p className="mt-2 text-sm text-ink-500">Create your first initiative, then add the material that explains the problem.</p></div>}
    <div className="grid gap-4 md:grid-cols-2">{list.data?.items.map(workspace => <Link key={workspace.id} href={initiativeURL(workspace.id)} prefetch={false} className={`${panelStyle} text-left transition hover:border-clay-400 focus-visible:ring-2 focus-visible:ring-clay-400`}><h2 className="text-lg font-semibold text-ink-700">{workspace.title}</h2><p className="mt-2 line-clamp-3 text-sm text-ink-500">{workspace.objective}</p><p className="mt-4 text-xs text-ink-400">Created {formatLocalDateTime(workspace.created_at)}</p></Link>)}</div>
    {list.data && <div className="flex items-center justify-between"><Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</Button><span className="text-xs text-ink-500">{list.data.total} initiatives</span><Button variant="secondary" disabled={offset + 25 >= list.data.total} onClick={() => setOffset(offset + 25)}>Next</Button></div>}
  </PageFrame>;
}

function Workspace({ id, userId, canAI, onBack }: { id: string; userId: string; canAI: boolean; onBack: () => void }) {
  const editorClient = useQueryClient();
  const [restored] = useState(() => readRequirementEditor(editorClient, userId, id));
  const query = useQuery({ queryKey: ["requirement-workspace", id], queryFn: () => api.getRequirementWorkspace(id) });
  const [historyItem, setHistoryItem] = useState<string | null>(null);
  const [decisionsOpen, setDecisionsOpen] = useState(() => Boolean(readRequirementDecisionDraft(editorClient, userId, id)));
  const [questionSeed, setQuestionSeed] = useState<{ question: string; requirementId: string | null } | null>(null);
  const [sourceFormOpen, setSourceFormOpen] = useState(() => Boolean(readRequirementSourceDraft(editorClient, userId, id)));
  const [sourceViewing, setSourceViewing] = useState("");
  const [filter, setFilter] = useState<RequirementFilter>("all");
  const [search, setSearch] = useState("");
  const [draftAssumptions, setDraftAssumptions] = useState<string[]>(restored?.assumptions || []);
  const [draft, setDraft] = useState<RequirementDraft>(restored?.draft || { ...blankDraft });
  const [criteria, setCriteria] = useState(restored?.criteria || "");
  const parsedCriteria = useMemo(() => parseRequirementCriteria(criteria), [criteria]);
  const [draftBaseline, setDraftBaseline] = useState(restored?.baseline || "");
  const [transition, setTransition] = useState<(() => void) | null>(null);
  const [editing, setEditing] = useState<BusinessRequirement | undefined>(restored?.editing);
  const [showForm, setShowForm] = useState(restored?.showForm || false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState(restored ? "Unsaved work restored in this tab. Review it before saving." : "");
  const [reviewing, setReviewing] = useState<BusinessRequirement | null>(restored?.reviewing || null);
  const [reviewerRole, setReviewerRole] = useState(restored?.reviewerRole || "Product Owner");
  const [reviewNote, setReviewNote] = useState(restored?.reviewNote || "");
  const [gathered, setGathered] = useState<GatherSuggestions | null>(null);
  const [assistance, setAssistance] = useState<{ item: BusinessRequirement; result: RequirementAssistance } | null>(null);
  const source = useQuery({ queryKey: ["requirement-source", id, draft.source_id], queryFn: () => api.getRequirementSource(id, draft.source_id), enabled: Boolean(draft.source_id) });
  const evidence = useQuery({ queryKey: ["requirement-source", id, sourceViewing], queryFn: () => api.getRequirementSource(id, sourceViewing), enabled: Boolean(sourceViewing) });
  const detail = query.data;
  const dirty = showForm && JSON.stringify([draft, criteria]) !== draftBaseline;
  const unsaved = dirty || Boolean(reviewing && reviewNote.trim());
  useEffect(() => {
    rememberRequirementEditor(editorClient, userId, id, unsaved ? {
      draft, criteria, baseline: draftBaseline, assumptions: draftAssumptions,
      editing, showForm, reviewing, reviewerRole, reviewNote,
    } : null);
  }, [editorClient, userId, id, unsaved, draft, criteria, draftBaseline, draftAssumptions, editing, showForm, reviewing, reviewerRole, reviewNote]);

  function switchEditor(action: () => void) {
    if (pending) return;
    if (unsaved) setTransition(() => action);
    else action();
  }
  function signOff(row: BusinessRequirement) {
    switchEditor(() => { setReviewing(row); setShowForm(false); setReviewNote(""); });
  }

  async function run(label: string, operation: () => Promise<unknown>, success?: () => void, refresh = true) {
    if (pending) return;
    setPending(label); setError(null); setNotice("");
    try { await operation(); setNotice(refresh ? "Saved." : "Ready for review."); success?.(); if (refresh) await query.refetch(); }
    catch (caught) { setError(caught); }
    finally { setPending(""); }
  }

  function edit(row?: BusinessRequirement) {
    setEditing(row);
    const nextDraft = row ? { source_id: row.source_id, title: row.title, actor: row.actor, action: row.action, benefit: row.benefit, evidence_quote: row.evidence_quote, acceptance_criteria: row.acceptance_criteria, priority: row.priority } : { ...blankDraft, source_id: detail?.sources[0]?.id || "" };
    const nextCriteria = row?.acceptance_criteria.join("\n") || "";
    setDraft(nextDraft); setCriteria(nextCriteria);
    setDraftBaseline(JSON.stringify([nextDraft, nextCriteria]));
    setShowForm(true); setReviewing(null); setDraftAssumptions([]); setError(null);
  }

  async function saveDraft() {
    if (parsedCriteria.issue) { setError(new Error(parsedCriteria.issue)); return; }
    let saved: Awaited<ReturnType<typeof api.saveBusinessRequirement>> | undefined;
    await run("requirement", async () => {
      saved = await api.saveBusinessRequirement(id, { ...draft, acceptance_criteria: parsedCriteria.criteria }, editing);
    }, () => {
      rememberRequirementEditor(editorClient, userId, id, null);
      setShowForm(false); setEditing(undefined);
      if (saved?.unchanged) setNotice("No business content changed. The existing agreement, story and revision were preserved.");
      else if (saved?.reused) {
        setFilter("all"); setSearch("");
        setNotice(`This requirement already exists as ${saved.reference}. Its saved agreement and history were preserved.`);
      }
    });
  }

  async function saveSource(data: Parameters<typeof api.addRequirementSource>[1]) {
    let saved: Awaited<ReturnType<typeof api.addRequirementSource>> | undefined;
    await run("source", async () => { saved = await api.addRequirementSource(id, data); }, () => {
      setSourceFormOpen(false);
      if (saved) {
        setSourceViewing(saved.id);
        setNotice(saved.reused ? `This content is already saved as “${saved.title}”. The existing evidence was reused.` : "Source saved.");
      }
    });
    return Boolean(saved);
  }


  if (!detail) return <PageFrame><Button variant="ghost" onClick={onBack}>Back to initiatives</Button><ErrorMessage error={query.error} />{query.isPending ? <p role="status">Loading initiative…</p> : <Button onClick={() => query.refetch()}>Retry</Button>}</PageFrame>;
  const focus = workspaceFocus(detail);
  const visibleItems = filterRequirements(detail.requirements, search, filter, detail.decisions);
  const blockedIds = blockedRequirementIds(detail.requirements, detail.decisions);
  const questions = filterRequirements(detail.requirements, "", "questions", detail.decisions).length;
  const deliveryReady = detail.requirements.filter(item => item.priority !== "wont" && item.story).length;
  const sourceNames = new Map(detail.sources.map(item => [item.id, item.title]));

  function followFocus() {
    if (focus.action === "decisions") setDecisionsOpen(true);
    else if (focus.action === "source") setSourceFormOpen(true);
    else if (focus.action === "deferred") { setFilter("deferred"); setSearch(""); }
    else if (focus.action === "questions") { setFilter("questions"); setSearch(""); }
    else if (focus.action === "review") signOff(focus.item);
    else if (focus.action === "gather") setSourceViewing(focus.sourceId);
    else if (focus.action === "story") void run(focus.item.id, () => api.createRequirementStory(id, focus.item));
    else exportBrief(detail!);
  }

  return <PageFrame width="wide">
    <ConfirmDialog open={Boolean(transition)} onOpenChange={open => { if (!open) setTransition(null); }} title="Discard unsaved changes?" description="Your current requirement edits or sign-off note have not been saved. Keep editing, or discard them to continue." cancelLabel="Keep editing" confirmLabel="Discard and continue" destructive onConfirm={() => { const action = transition; setTransition(null); action?.(); }} />
    <Button variant="ghost" leadingIcon={<ArrowLeft size={16} />} onClick={onBack}>All initiatives</Button>
    <PageHeader eyebrow="Business workspace" title={detail.workspace.title} description={detail.workspace.objective}
      meta={`${detail.workspace.request_type === "enhancement" ? "Enhancement" : "Approved project / request"} · ${detail.requirements.length} requirements · ${deliveryReady} delivery ready`}
      actions={<><Button variant="ghost" disabled={Boolean(pending)} onClick={() => query.refetch()}>Refresh</Button><Button variant="secondary" leadingIcon={<Download size={16} />} onClick={() => exportBrief(detail)}>Export BRD</Button></>} />
    <section className="flex flex-col gap-5 rounded-xl border border-clay-300/40 bg-gradient-to-r from-[#06243A] to-[#103E50] p-5 text-white sm:flex-row sm:items-center sm:justify-between" aria-label="Suggested focus">
      <div className="max-w-2xl"><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200">Worth your attention</p><h2 className="mt-2 text-lg font-medium">{focus.title}</h2><p className="mt-2 text-sm leading-6 text-slate-200">{focus.reason}</p></div>
      <Button className="shrink-0" variant="secondary" trailingIcon={<ArrowUpRight size={15} />} disabled={Boolean(pending)} onClick={followFocus}>{focus.label}</Button>
    </section>
    <DecisionLog workspaceId={id} userId={userId} requirements={detail.requirements} decisions={detail.decisions || []} open={decisionsOpen} onToggle={() => setDecisionsOpen(!decisionsOpen)} seed={questionSeed} onSeedUsed={() => setQuestionSeed(null)} onSaved={() => query.refetch()} />
    <ErrorMessage error={error || query.error} />{notice && <p role="status" className="text-sm text-moss-700">{notice}</p>}
    <div className="grid items-start gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="min-w-0 space-y-4" aria-label="Business context">
        <div className="flex items-center justify-between"><div><h2 className="font-semibold text-ink-700">Context & evidence</h2><p className="mt-1 text-xs text-ink-400">{detail.sources.length} sources · Add context whenever it changes</p></div><Button className="shrink-0 whitespace-nowrap" variant="ghost" size="sm" leadingIcon={<Plus size={14} />} onClick={() => setSourceFormOpen(!sourceFormOpen)}>Add</Button></div>
        <SourceIntakeForm workspaceId={id} userId={userId} open={sourceFormOpen || detail.sources.length === 0} pending={pending} onSave={saveSource} />
        {detail.sources.map(item => <div key={item.id} className="space-y-3 rounded-xl border border-linen-400 bg-white p-4">
          <button className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-clay-400" onClick={() => setSourceViewing(sourceViewing === item.id ? "" : item.id)}>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-clay-700">{kinds[item.kind]}</span><h3 className="mt-1 text-sm font-semibold text-ink-700">{item.title}</h3>
            <p className="mt-1 text-xs text-ink-400">{detail.requirements.filter(row => row.source_id === item.id).length} linked requirements</p>
          </button>
          {sourceViewing === item.id && <div><ErrorMessage error={evidence.error} />{evidence.isPending ? <p role="status" className="text-xs">Loading source…</p> : evidence.data?.content && <SourceExplorer key={item.id} content={evidence.data.content} canAI={canAI} busy={Boolean(pending)} onExplore={excerpt => run(`gather-${item.id}`, async () => { setGathered(null); setGathered(await api.gatherRequirements(id, item.id, excerpt)); }, undefined, false)} />}</div>}
          <div className="flex flex-wrap gap-1"><Button size="sm" variant="ghost" disabled={Boolean(pending)} onClick={() => switchEditor(() => { edit(); const nextDraft = { ...blankDraft, source_id: item.id }; setDraft(nextDraft); setDraftBaseline(JSON.stringify([nextDraft, ""])); })}>Link a requirement</Button>
            {canAI && <Button size="sm" variant="secondary" leadingIcon={<Sparkles size={13} />} pending={pending === `gather-${item.id}`} disabled={Boolean(pending)} onClick={() => run(`gather-${item.id}`, async () => { setGathered(null); setGathered(await api.gatherRequirements(id, item.id)); }, undefined, false)}>Explore with AI</Button>}
          </div>
        </div>)}
        {canAI && <p className="text-xs leading-5 text-ink-400">AI uses your configured provider and the material you select. Suggestions need your review; they never sign off requirements.</p>}
      </aside>
      <section className="min-w-0 space-y-5" aria-label="Requirements and decisions">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold text-ink-700">Requirements & decisions</h2><p className="mt-1 text-xs text-ink-400">{questions ? `${questions} items need clarification` : "Keep the evidence, decision and delivery story together"}</p></div><Button leadingIcon={<Plus size={15} />} disabled={!detail.sources.length || Boolean(pending)} onClick={() => switchEditor(() => edit())}>New requirement</Button></div>
        <div className="flex flex-col gap-3 sm:flex-row"><label className="flex-1"><span className="sr-only">Search requirements</span><input className={inputStyle} placeholder="Find a requirement, outcome or stakeholder…" value={search} onChange={event => setSearch(event.target.value)} /></label><label><span className="sr-only">Show requirements</span><select className={inputStyle} value={filter} onChange={event => setFilter(event.target.value as RequirementFilter)}><option value="all">All work</option><option value="questions">Open questions</option><option value="review">Ready for review</option><option value="delivery">Delivery ready</option><option value="deferred">Not this time</option></select></label></div>
    {canAI && detail.requirements.length >= 2 && <CrossReviewPanel workspaceId={id} items={detail.requirements} onQuestion={(question, requirementId) => { setQuestionSeed({ question, requirementId }); setDecisionsOpen(true); }} />}
    {historyItem && <RequirementHistoryPanel key={historyItem} workspaceId={id} itemId={historyItem} revision={detail.requirements.find(item => item.id === historyItem)?.revision || 0} onClose={() => setHistoryItem(null)} />}
    {gathered && <section className={`${panelStyle} space-y-4`} aria-label="AI gathering suggestions">
      <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">AI gathering suggestions</h2><Button variant="ghost" onClick={() => setGathered(null)}>Dismiss suggestions</Button></div>
      <p className="text-xs text-ink-400">{gathered.model} · {detail.sources.find(item => item.id === gathered.source_id)?.title}</p>
      {gathered.scope === "excerpt" && <p className="text-sm text-ink-500">These suggestions cover only your selected passage. Explore other passages to review the rest of the source.</p>}
      {gathered.source_truncated && <p className="text-sm text-amber-800">Only part of this source fit in the analysis. Review the full source for missing requirements.</p>}
      {gathered.discarded_candidates > 0 && <p className="text-sm text-amber-800">{gathered.discarded_candidates} suggestions were excluded because their evidence could not be matched to the source.</p>}
      {gathered.candidates.length === 0 && <p className="text-sm">No verifiable requirements were found. You can gather a requirement manually.</p>}
      {gathered.questions.length > 0 && <div><h3 className="text-sm font-semibold">Questions for stakeholders</h3><ul className="list-disc pl-5 text-sm">{gathered.questions.map((question, index) => <li key={index}>{question}<Button size="sm" variant="ghost" onClick={() => { setQuestionSeed({ question, requirementId: null }); setDecisionsOpen(true); }}>Track question</Button></li>)}</ul></div>}
      {gathered.candidates.map((candidate, index) => <article key={index} className="space-y-3 rounded-lg border border-linen-400 p-4"><h3 className="font-semibold">{candidate.title}</h3><p className="text-sm text-ink-500">{candidate.action}</p><blockquote className="border-l-2 border-clay-300 pl-3 text-sm">{candidate.evidence_quote}</blockquote>{candidate.assumptions.length > 0 && <div className="text-sm text-amber-800"><strong>Assumptions to confirm</strong><ul className="list-disc pl-5">{candidate.assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul></div>}<Button variant="secondary" disabled={Boolean(pending)} onClick={() => switchEditor(() => { edit(); const { assumptions: _assumptions, ...fields } = candidate; setDraft({ ...fields, source_id: gathered.source_id }); setCriteria(candidate.acceptance_criteria.join("\n")); setDraftAssumptions(candidate.assumptions); setGathered(null); })}>Review draft</Button></article>)}
    </section>}
    {assistance && <section className={`${panelStyle} space-y-4`} aria-label="AI requirement review">
      <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">AI {assistance.result.mode === "review" ? "review" : "story refinement"} · {assistance.item.reference}</h2><Button variant="ghost" onClick={() => setAssistance(null)}>Dismiss review</Button></div>
      <p className="text-xs text-ink-400">{assistance.result.model} · Based on revision {assistance.result.base_revision}</p>
      {assistance.result.input_truncated && <p className="text-sm text-amber-800">This review covers only part of the requirement. Check the complete requirement before making a decision.</p>}
      {assistance.result.suggestions.findings?.map((finding, index) => <div key={index} className="rounded-lg bg-linen-100 p-3 text-sm"><strong>{finding.category.replaceAll("_", " ")}</strong><p>{finding.finding}</p><p className="mt-2 text-ink-500">{finding.question}</p><Button size="sm" variant="ghost" onClick={() => { setQuestionSeed({ question: finding.question, requirementId: assistance.item.id }); setDecisionsOpen(true); }}>Track question</Button></div>)}
      {assistance.result.mode === "review" && assistance.result.suggestions.findings?.length === 0 && <p className="text-sm">No findings were suggested. Human review and sign-off are still required.</p>}
      {assistance.result.suggestions.questions?.map((question, index) => <p key={index} className="text-sm">{question}</p>)}
      {assistance.result.mode === "story" && <><p className="text-sm">As a {assistance.result.suggestions.actor}, I want to {assistance.result.suggestions.action}, so that {assistance.result.suggestions.benefit}.</p><ul className="list-disc pl-5 text-sm">{assistance.result.suggestions.acceptance_criteria?.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>{Boolean(assistance.result.suggestions.assumptions?.length) && <div className="text-sm text-amber-800"><strong>Assumptions to confirm</strong><ul className="list-disc pl-5">{assistance.result.suggestions.assumptions?.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul></div>}<p className="text-xs text-ink-500">Saving this refinement creates a revised draft and requires a new sign-off.</p><Button variant="secondary" disabled={Boolean(pending)} onClick={() => switchEditor(() => { const { item, result } = assistance; edit(item); setDraft({ source_id: item.source_id, title: item.title, evidence_quote: item.evidence_quote, priority: item.priority, actor: result.suggestions.actor || item.actor, action: result.suggestions.action || item.action, benefit: result.suggestions.benefit || item.benefit, acceptance_criteria: result.suggestions.acceptance_criteria || item.acceptance_criteria }); setCriteria((result.suggestions.acceptance_criteria || item.acceptance_criteria).join("\n")); setDraftAssumptions(result.suggestions.assumptions || []); setAssistance(null); })}>Review as a new revision</Button></>}
    </section>}
      {reviewing && <form className={panelStyle} aria-busy={pending === reviewing.id} onSubmit={event => { event.preventDefault(); void run(reviewing.id, () => api.validateBusinessRequirement(id, reviewing, { reviewer_role: reviewerRole, validation_note: reviewNote }), () => { rememberRequirementEditor(editorClient, userId, id, null); setReviewing(null); }); }}>
        <fieldset disabled={pending === reviewing.id} className="space-y-4">
        <h2 className="font-semibold">Sign off {reviewing.reference}: {reviewing.title}</h2>
        <p className="text-sm text-ink-500">Confirm that the requirement reflects the source, the expected outcome is agreed, and the acceptance criteria can be tested. Your signed-in account is recorded.</p>
        <Field label="Review capacity"><select className={inputStyle} value={reviewerRole} onChange={event => setReviewerRole(event.target.value)}>{["Product Owner", "Business Stakeholder", "Technical Business Analyst", "DTL"].map(role => <option key={role}>{role}</option>)}</select></Field>
        <Field label="Sign-off note"><textarea required minLength={10} maxLength={4000} className={inputStyle} value={reviewNote} onChange={event => setReviewNote(event.target.value)} placeholder="What was confirmed, and with whom?" /></Field>
        <div className="flex gap-2"><Button type="submit" pending={pending === reviewing.id} disabled={Boolean(pending)}>Sign off requirement</Button><Button variant="ghost" disabled={Boolean(pending)} onClick={() => switchEditor(() => setReviewing(null))}>Cancel</Button></div>
        </fieldset>
      </form>}
      {showForm && <form className={panelStyle} aria-busy={pending === "requirement"} onSubmit={event => { event.preventDefault(); void saveDraft(); }}>
        <fieldset disabled={pending === "requirement"} className="space-y-4">
        <h2 className="text-lg font-semibold">{editing ? "Edit requirement" : "Gather a requirement"}</h2>
        {dirty && <p role="status" className="text-xs text-amber-800">Unsaved changes · Kept in this tab while you browse. Save before refreshing or closing.</p>}
        {draftAssumptions.length > 0 && <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800"><strong>Resolve these assumptions while reviewing</strong><ul className="list-disc pl-5">{draftAssumptions.map((item, index) => <li key={index}>{item}<Button size="sm" variant="ghost" onClick={() => { setQuestionSeed({ question: item, requirementId: editing?.id || null }); setDecisionsOpen(true); }}>Track assumption</Button></li>)}</ul></div>}
        {editing?.status === "validated" && <p className="text-sm text-amber-700">Saving changes resets validation and removes the existing user story. Review the updated requirement again.</p>}
        <Field label="Evidence source"><select required value={draft.source_id} onChange={event => setDraft({ ...draft, source_id: event.target.value, evidence_quote: "" })} className={inputStyle}>{detail.sources.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></Field>
        <ErrorMessage error={source.error} />{source.isPending && <p role="status">Loading source…</p>}
        {source.data?.content && <details className="rounded-lg bg-linen-100 p-3" open><summary className="cursor-pointer text-sm font-medium">Read source and copy an exact excerpt</summary><pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-6 text-ink-500">{source.data.content}</pre></details>}
        <Field label="Exact evidence excerpt"><textarea required minLength={10} maxLength={4000} rows={3} className={inputStyle} value={draft.evidence_quote} onChange={event => setDraft({ ...draft, evidence_quote: event.target.value })} /></Field>
        <Field label="Requirement title"><input required maxLength={200} className={inputStyle} value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} /></Field>
        <div className="grid gap-4 md:grid-cols-2"><Field label="As a… (stakeholder or user role)"><input maxLength={200} className={inputStyle} value={draft.actor} onChange={event => setDraft({ ...draft, actor: event.target.value })} placeholder="finance analyst" /></Field><Field label="Priority"><select className={inputStyle} value={draft.priority} onChange={event => setDraft({ ...draft, priority: event.target.value as RequirementPriority })}>{Object.entries(priorities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field></div>
        <Field label="I want to… (required capability)"><textarea maxLength={4000} className={inputStyle} value={draft.action} onChange={event => setDraft({ ...draft, action: event.target.value })} /></Field>
        <Field label="So that… (business outcome)"><textarea maxLength={4000} className={inputStyle} value={draft.benefit} onChange={event => setDraft({ ...draft, benefit: event.target.value })} /></Field>
        <Field label="Acceptance criteria · one per line"><textarea rows={4} maxLength={20020} aria-invalid={Boolean(parsedCriteria.issue)} aria-describedby="requirement-criteria-help" className={inputStyle} value={criteria} onChange={event => setCriteria(event.target.value)} placeholder="Given a valid request, when it is submitted, then a receipt appears within 30 seconds." /></Field>
        <p id="requirement-criteria-help" className={`text-xs ${parsedCriteria.issue ? "text-rust-600" : "text-ink-500"}`}>{parsedCriteria.issue || `${parsedCriteria.criteria.length} / 20 criteria · 10–1,000 characters each. You can leave this empty while drafting.`}</p>
        <div className="flex gap-2"><Button type="submit" pending={pending === "requirement"} disabled={Boolean(pending) || source.isError || Boolean(parsedCriteria.issue)}>Save draft</Button><Button variant="ghost" disabled={Boolean(pending)} onClick={() => switchEditor(() => setShowForm(false))}>Cancel</Button></div>
        </fieldset>
      </form>}

        {visibleItems.length === 0 && <div className={`${panelStyle} py-10 text-center`}><FileText className="mx-auto text-ink-300" /><h3 className="mt-3 font-semibold">{detail.requirements.length ? "No requirements match this view" : "Give the business need a clear shape"}</h3><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-500">{detail.requirements.length ? "Try a different search or show all work." : "Explore your material, capture an outcome, or start with a question. Your evidence and decisions will stay connected here."}</p></div>}
        {visibleItems.map(row => <RequirementCard key={row.id} item={row} blocked={blockedIds.has(row.id)} sourceTitle={sourceNames.get(row.source_id) || "Source unavailable"} canAI={canAI} busy={Boolean(pending)} pending={pending}
          onEdit={() => switchEditor(() => edit(row))}
          onHistory={() => setHistoryItem(row.id)}
          onReview={() => run(`review-${row.id}`, async () => { setAssistance(null); setAssistance({ item: row, result: await api.assistRequirement(id, row, "review") }); }, undefined, false)}
          onSignOff={() => signOff(row)}
          onCreateStory={() => run(row.id, () => api.createRequirementStory(id, row))}
          onCopyStory={() => run(`copy-${row.id}`, () => navigator.clipboard.writeText(requirementStoryText(detail, row)), () => setNotice("Copied user story."), false)}
          onRefine={() => run(`refine-${row.id}`, async () => { setAssistance(null); setAssistance({ item: row, result: await api.assistRequirement(id, row, "story") }); }, undefined, false)}
        />)}
      </section>
    </div>
  </PageFrame>;
}
