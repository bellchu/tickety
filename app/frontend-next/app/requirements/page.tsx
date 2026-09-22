"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ClipboardList, Download, FileText, Plus } from "lucide-react";
import { requirementBrief } from "@/lib/requirement-export";
import { api } from "@/lib/api";
import type { BusinessRequirement, RequirementDraft, RequirementPriority, RequirementWorkspaceDetail, SourceKind } from "@/lib/requirements-types";
import { Button } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";
import { formatLocalDateTime } from "@/lib/date-time";

const inputStyle = "mt-1 w-full rounded-lg border border-linen-500 bg-white px-3 py-2 text-sm text-ink-700 focus:outline-none focus:ring-2 focus:ring-clay-400";
const panelStyle = "rounded-xl border border-linen-400 bg-white p-5 shadow-sm";
const kinds: Record<SourceKind, string> = { document: "Business document", email: "Email", sop: "SOP", transcript: "Meeting transcript" };
const priorities: Record<RequirementPriority, string> = { must: "Must have", should: "Should have", could: "Could have", wont: "Not this time" };
const blankDraft: RequirementDraft = { source_id: "", title: "", actor: "", action: "", benefit: "", evidence_quote: "", acceptance_criteria: [], priority: "should" };
const message = (error: unknown) => error instanceof Error ? error.message : "Something went wrong. Please try again.";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-sm font-medium text-ink-600">{label}{children}</label>;
}

function ErrorMessage({ error }: { error: unknown }) {
  return error ? <p role="alert" className="rounded-lg border border-rust-400/30 bg-rust-400/10 p-3 text-sm text-rust-600">{message(error)}</p> : null;
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
  const [selected, setSelected] = useState<string | null>(null);
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
  const list = useQuery({ queryKey: ["requirement-workspaces", offset], queryFn: () => api.getRequirementWorkspaces(offset), enabled: Boolean(allowed) });

  async function create(event: FormEvent) {
    event.preventDefault();
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
  if (selected) return <Workspace key={selected} id={selected} onBack={() => setSelected(null)} />;

  return <PageFrame>
    <PageHeader eyebrow="Business operations" icon={<ClipboardList size={16} />} title="Turn business context into clear requirements" description="Gather evidence, agree on what matters, and give delivery teams user stories they can act on." actions={<Button leadingIcon={<Plus size={16} />} onClick={() => setCreating(!creating)}>New initiative</Button>} />
    <div className="grid gap-3 md:grid-cols-3">{[
      ["01 · Gather", "Bring documents, emails, SOPs and meeting notes together."],
      ["02 · Validate", "Resolve vague language and confirm outcomes with source evidence."],
      ["03 · Create stories", "Turn agreed requirements into stories with acceptance criteria."],
    ].map(([heading, body]) => <div key={heading} className={panelStyle}><h2 className="font-semibold text-ink-700">{heading}</h2><p className="mt-2 text-sm leading-6 text-ink-500">{body}</p></div>)}</div>
    {creating && <form onSubmit={create} className={`${panelStyle} space-y-4`}>
      <h2 className="text-lg font-semibold">Start an initiative</h2>
      <Field label="Initiative name"><input required maxLength={200} value={title} onChange={event => setTitle(event.target.value)} className={inputStyle} placeholder="For example: simplify supplier onboarding" /></Field>
      <Field label="Request type"><select className={inputStyle} value={requestType} onChange={event => setRequestType(event.target.value as "approved_project" | "enhancement")}><option value="approved_project">Approved project / request</option><option value="enhancement">Enhancement</option></select></Field>
      <Field label="Business objective"><textarea required minLength={10} maxLength={4000} rows={3} value={objective} onChange={event => setObjective(event.target.value)} className={inputStyle} placeholder="What outcome should improve, and for whom?" /></Field>
      <p className="text-xs text-ink-500">Visible to you and workspace administrators.</p>
      <ErrorMessage error={error} /><Button type="submit" pending={pending}>Create initiative</Button>
    </form>}
    <ErrorMessage error={list.error} />
    {list.isError && <Button variant="secondary" onClick={() => list.refetch()}>Retry loading initiatives</Button>}
    {list.isPending && <p role="status">Loading initiatives…</p>}
    {list.data?.items.length === 0 && <div className={`${panelStyle} text-center`}><FileText className="mx-auto mb-3 text-ink-400" /><h2 className="font-semibold">Start with a business question</h2><p className="mt-2 text-sm text-ink-500">Create your first initiative, then add the material that explains the problem.</p></div>}
    <div className="grid gap-4 md:grid-cols-2">{list.data?.items.map(workspace => <button key={workspace.id} onClick={() => setSelected(workspace.id)} className={`${panelStyle} text-left transition hover:border-clay-400 focus-visible:ring-2 focus-visible:ring-clay-400`}><h2 className="text-lg font-semibold text-ink-700">{workspace.title}</h2><p className="mt-2 line-clamp-3 text-sm text-ink-500">{workspace.objective}</p><p className="mt-4 text-xs text-ink-400">Created {formatLocalDateTime(workspace.created_at)}</p></button>)}</div>
    {list.data && <div className="flex items-center justify-between"><Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</Button><span className="text-xs text-ink-500">{list.data.total} initiatives</span><Button variant="secondary" disabled={offset + 25 >= list.data.total} onClick={() => setOffset(offset + 25)}>Next</Button></div>}
  </PageFrame>;
}

function Workspace({ id, onBack }: { id: string; onBack: () => void }) {
  const query = useQuery({ queryKey: ["requirement-workspace", id], queryFn: () => api.getRequirementWorkspace(id) });
  const [tab, setTab] = useState<"sources" | "requirements" | "stories">("sources");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceKind, setSourceKind] = useState<SourceKind>("document");
  const [content, setContent] = useState("");
  const [draft, setDraft] = useState<RequirementDraft>({ ...blankDraft });
  const [criteria, setCriteria] = useState("");
  const [editing, setEditing] = useState<BusinessRequirement | undefined>();
  const [showForm, setShowForm] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [reviewing, setReviewing] = useState<BusinessRequirement | null>(null);
  const [reviewerRole, setReviewerRole] = useState("Product Owner");
  const [reviewNote, setReviewNote] = useState("");
  const source = useQuery({ queryKey: ["requirement-source", id, draft.source_id], queryFn: () => api.getRequirementSource(id, draft.source_id), enabled: Boolean(draft.source_id) });
  const detail = query.data;

  async function run(label: string, operation: () => Promise<unknown>, success?: () => void) {
    if (pending) return;
    setPending(label); setError(null); setNotice("");
    try { await operation(); setNotice("Saved."); success?.(); await query.refetch(); }
    catch (caught) { setError(caught); }
    finally { setPending(""); }
  }

  function edit(row?: BusinessRequirement) {
    setEditing(row);
    setDraft(row ? { source_id: row.source_id, title: row.title, actor: row.actor, action: row.action, benefit: row.benefit, evidence_quote: row.evidence_quote, acceptance_criteria: row.acceptance_criteria, priority: row.priority } : { ...blankDraft, source_id: detail?.sources[0]?.id || "" });
    setCriteria(row?.acceptance_criteria.join("\n") || "");
    setShowForm(true); setTab("requirements"); setError(null);
  }

  async function importText(file?: File) {
    if (!file) return;
    setError(null);
    try {
      if (!/\.(txt|md|eml|vtt|srt)$/i.test(file.name)) throw new Error("Choose a UTF-8 TXT, Markdown, EML, VTT or SRT file, or paste the text below.");
      if (file.size > 400000) throw new Error("Choose a file smaller than 400 KB.");
      const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (text.length > 100000 || text.includes("\0")) throw new Error("Source text must contain at most 100,000 characters and no NUL characters.");
      setContent(text); setSourceTitle(file.name);
      if (/\.eml$/i.test(file.name)) setSourceKind("email");
      else if (/\.(vtt|srt)$/i.test(file.name)) setSourceKind("transcript");
    } catch (caught) { setError(caught); }
  }

  if (!detail) return <PageFrame><Button variant="ghost" onClick={onBack}>Back to initiatives</Button><ErrorMessage error={query.error} />{query.isPending ? <p role="status">Loading initiative…</p> : <Button onClick={() => query.refetch()}>Retry</Button>}</PageFrame>;
  const validated = detail.requirements.filter(row => row.status === "validated").length;
  const stories = detail.requirements.filter(row => row.story);

  return <PageFrame>
    <Button variant="ghost" leadingIcon={<ArrowLeft size={16} />} onClick={onBack}>All initiatives</Button>
    <PageHeader eyebrow="Requirement gathering" title={detail.workspace.title} description={detail.workspace.objective} actions={<Button variant="secondary" leadingIcon={<Download size={16} />} onClick={() => exportBrief(detail)}>Export BRD</Button>} />
    <div className="grid grid-cols-3 gap-3">{[[detail.sources.length, "Sources"], [validated, "Validated requirements"], [stories.length, "User stories"]].map(([count, label]) => <div key={label} className={panelStyle}><strong className="text-2xl text-ink-700">{count}</strong><p className="mt-1 text-xs text-ink-500">{label}</p></div>)}</div>
    <nav aria-label="Requirement workflow" className="flex flex-wrap gap-2">{(["sources", "requirements", "stories"] as const).map((value, index) => <Button key={value} variant={tab === value ? "primary" : "secondary"} aria-pressed={tab === value} onClick={() => setTab(value)}>{index + 1}. {value === "sources" ? "Gather sources" : value === "requirements" ? "Validate requirements" : "User stories"}</Button>)}</nav>
    <ErrorMessage error={error || query.error} /><p role="status" className="text-sm text-moss-700">{notice}</p>
    {query.isError && <Button variant="secondary" onClick={() => query.refetch()}>Refresh initiative</Button>}
    {tab === "sources" && <div className="grid items-start gap-5 lg:grid-cols-2">
      <form className={`${panelStyle} space-y-4`} onSubmit={event => { event.preventDefault(); void run("source", () => api.addRequirementSource(id, { title: sourceTitle, kind: sourceKind, content }), () => { setSourceTitle(""); setContent(""); }); }}>
        <h2 className="text-lg font-semibold">Add context</h2><p className="text-sm text-ink-500">Paste source material or import a text file. Sources are preserved so every requirement can point back to its evidence.</p>
        <Field label="Import text file"><input type="file" accept=".txt,.md,.eml,.vtt,.srt" onChange={event => { void importText(event.target.files?.[0]); event.target.value = ""; }} className="mt-2 block w-full text-sm" /></Field>
        <Field label="Source title"><input required maxLength={200} className={inputStyle} value={sourceTitle} onChange={event => setSourceTitle(event.target.value)} /></Field>
        <Field label="Source type"><select className={inputStyle} value={sourceKind} onChange={event => setSourceKind(event.target.value as SourceKind)}>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        <Field label="Source text"><textarea required minLength={10} maxLength={100000} rows={10} className={inputStyle} value={content} onChange={event => setContent(event.target.value)} /></Field><p className="text-xs text-ink-400">{content.length.toLocaleString()} / 100,000 characters · Text formats only in this release.</p>
        <Button type="submit" pending={pending === "source"} disabled={Boolean(pending) || detail.sources.length >= 50}>Save source</Button>
      </form>
      <section className="space-y-3" aria-label="Saved sources"><h2 className="font-semibold">Evidence library</h2>{detail.sources.length === 0 && <p className="text-sm text-ink-500">No sources yet. Start with an email, SOP or meeting note that explains the need.</p>}{detail.sources.map(item => <div key={item.id} className={panelStyle}><span className="text-xs font-medium text-clay-700">{kinds[item.kind]}</span><h3 className="mt-1 font-semibold">{item.title}</h3><p className="mt-2 text-xs text-ink-400">Added {formatLocalDateTime(item.created_at)}</p><Button className="mt-3" variant="secondary" onClick={() => { edit(); setDraft({ ...blankDraft, source_id: item.id }); }}>Gather a requirement</Button></div>)}</section>
    </div>}
    {tab === "requirements" && <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-ink-500">{detail.requirements.length} requirements · Quality checks support your review; validation is your decision.</p><Button disabled={!detail.sources.length || Boolean(pending)} onClick={() => edit()}>New requirement</Button></div>
      {!detail.sources.length && <p className={panelStyle}>Add source material before gathering requirements.</p>}
      {reviewing && <form className={`${panelStyle} space-y-4`} onSubmit={event => { event.preventDefault(); void run(reviewing.id, () => api.validateBusinessRequirement(id, reviewing, { reviewer_role: reviewerRole, validation_note: reviewNote }), () => setReviewing(null)); }}>
        <h2 className="font-semibold">Sign off {reviewing.reference}: {reviewing.title}</h2>
        <p className="text-sm text-ink-500">Confirm that the requirement reflects the source, the expected outcome is agreed, and the acceptance criteria can be tested. Your signed-in account is recorded.</p>
        <Field label="Review capacity"><select className={inputStyle} value={reviewerRole} onChange={event => setReviewerRole(event.target.value)}>{["Product Owner", "Business Stakeholder", "Technical Business Analyst", "DTL"].map(role => <option key={role}>{role}</option>)}</select></Field>
        <Field label="Sign-off note"><textarea required minLength={10} maxLength={4000} className={inputStyle} value={reviewNote} onChange={event => setReviewNote(event.target.value)} placeholder="What was confirmed, and with whom?" /></Field>
        <div className="flex gap-2"><Button type="submit" pending={pending === reviewing.id} disabled={Boolean(pending)}>Sign off requirement</Button><Button variant="ghost" disabled={Boolean(pending)} onClick={() => setReviewing(null)}>Cancel</Button></div>
      </form>}
      {showForm && <form className={`${panelStyle} space-y-4`} onSubmit={event => { event.preventDefault(); void run("requirement", () => api.saveBusinessRequirement(id, { ...draft, acceptance_criteria: criteria.split("\n").map(line => line.trim()).filter(Boolean) }, editing), () => { setShowForm(false); setEditing(undefined); }); }}>
        <h2 className="text-lg font-semibold">{editing ? "Edit requirement" : "Gather a requirement"}</h2>
        {editing?.status === "validated" && <p className="text-sm text-amber-700">Saving changes resets validation and removes the existing user story. Review the updated requirement again.</p>}
        <Field label="Evidence source"><select required value={draft.source_id} onChange={event => setDraft({ ...draft, source_id: event.target.value, evidence_quote: "" })} className={inputStyle}>{detail.sources.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></Field>
        <ErrorMessage error={source.error} />{source.isPending && <p role="status">Loading source…</p>}
        {source.data?.content && <details className="rounded-lg bg-linen-100 p-3" open><summary className="cursor-pointer text-sm font-medium">Read source and copy an exact excerpt</summary><pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-6 text-ink-500">{source.data.content}</pre></details>}
        <Field label="Exact evidence excerpt"><textarea required minLength={10} maxLength={4000} rows={3} className={inputStyle} value={draft.evidence_quote} onChange={event => setDraft({ ...draft, evidence_quote: event.target.value })} /></Field>
        <Field label="Requirement title"><input required maxLength={200} className={inputStyle} value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} /></Field>
        <div className="grid gap-4 md:grid-cols-2"><Field label="As a… (stakeholder or user role)"><input maxLength={200} className={inputStyle} value={draft.actor} onChange={event => setDraft({ ...draft, actor: event.target.value })} placeholder="finance analyst" /></Field><Field label="Priority"><select className={inputStyle} value={draft.priority} onChange={event => setDraft({ ...draft, priority: event.target.value as RequirementPriority })}>{Object.entries(priorities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field></div>
        <Field label="I want to… (required capability)"><textarea maxLength={4000} className={inputStyle} value={draft.action} onChange={event => setDraft({ ...draft, action: event.target.value })} /></Field>
        <Field label="So that… (business outcome)"><textarea maxLength={4000} className={inputStyle} value={draft.benefit} onChange={event => setDraft({ ...draft, benefit: event.target.value })} /></Field>
        <Field label="Acceptance criteria · one per line"><textarea rows={4} maxLength={20020} className={inputStyle} value={criteria} onChange={event => setCriteria(event.target.value)} placeholder="Given a valid request, when it is submitted, then a receipt appears within 30 seconds." /></Field>
        <div className="flex gap-2"><Button type="submit" pending={pending === "requirement"} disabled={Boolean(pending) || source.isError}>Save draft</Button><Button variant="ghost" disabled={Boolean(pending)} onClick={() => setShowForm(false)}>Cancel</Button></div>
      </form>}
      {detail.requirements.map(row => <article key={row.id} className={`${panelStyle} space-y-3`}>
        <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{row.reference} · {row.title}</h2><span className="text-xs font-semibold text-clay-700">{priorities[row.priority]} · {row.status === "validated" ? "Validated" : "Draft"}</span></div>
        <p className="text-sm text-ink-600">As a {row.actor || "[role to confirm]"}, I want to {row.action || "[capability to clarify]"}, so that {row.benefit || "[outcome to agree]"}.</p>
        <blockquote className="border-l-2 border-clay-300 pl-3 text-sm italic text-ink-500">“{row.evidence_quote}”</blockquote><p className="text-xs text-ink-400">Source: {detail.sources.find(item => item.id === row.source_id)?.title}</p>
        {row.acceptance_criteria.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm text-ink-600">{row.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>}
        {row.quality_issues.length > 0 && <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800"><p className="font-semibold">Clarify before validation</p><ul className="mt-1 list-disc pl-5">{row.quality_issues.map(issue => <li key={issue}>{issue}</li>)}</ul></div>}
        {row.validated_at && <p className="text-xs text-moss-700">Signed off as {row.reviewer_role} · {formatLocalDateTime(row.validated_at)}</p>}
        <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={Boolean(pending)} onClick={() => edit(row)}>Edit</Button>{row.status === "draft" ? <Button leadingIcon={<CheckCircle2 size={16} />} disabled={Boolean(pending) || row.quality_issues.length > 0} pending={pending === row.id} onClick={() => { setReviewing(row); setReviewNote(""); }}>Confirm requirement</Button> : <Button disabled={Boolean(pending) || Boolean(row.story)} pending={pending === row.id} onClick={() => run(row.id, () => api.createRequirementStory(id, row), () => setTab("stories"))}>{row.story ? "Story created" : "Create user story"}</Button>}</div>
      </article>)}
    </div>}
    {tab === "stories" && <section className="space-y-4" aria-label="User stories">{stories.length === 0 && <div className={panelStyle}><h2 className="font-semibold">Stories start with agreement</h2><p className="mt-2 text-sm text-ink-500">Confirm a requirement, then create its user story. The story keeps the agreed acceptance criteria and source reference.</p></div>}{stories.map(row => <article key={row.id} className={`${panelStyle} space-y-3`}><h2 className="text-lg font-semibold">{row.story!.reference} · {row.story!.title}</h2><p className="text-sm leading-6 text-ink-600">{row.story!.statement}</p><h3 className="text-sm font-semibold">Acceptance criteria</h3><ul className="list-disc space-y-2 pl-5 text-sm text-ink-600">{row.story!.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul><p className="text-xs text-ink-400">{priorities[row.priority]} · Source: {detail.sources.find(item => item.id === row.source_id)?.title}</p><Button variant="secondary" disabled={Boolean(pending)} onClick={() => run(`copy-${row.id}`, () => navigator.clipboard.writeText([row.story!.title, row.story!.statement, ...row.story!.acceptance_criteria.map(item => `- ${item}`)].join("\n\n")), () => setNotice("Copied user story."))}>Copy story</Button></article>)}</section>}
  </PageFrame>;
}
