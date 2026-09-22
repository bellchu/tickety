"use client";

import { RequirementInput } from "./BoundedText";

import { requirementTextBounds } from "@/lib/requirement-text";

import { prepareRequirementSource } from "@/lib/requirement-source-import";
import { requirementErrorMessage } from "@/lib/requirement-errors";

import { useQueryClient } from "@tanstack/react-query";
import { captureRequirementDraftSave, readRequirementSourceDraft, rememberRequirementSourceDraft } from "@/lib/requirement-editor-cache";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { SourceKind } from "@/lib/requirements-types";
import { Button, ConfirmDialog } from "@/components/ui";
import { Field, inputStyle, panelStyle, kinds } from "./fields";

export function SourceIntakeForm({ workspaceId, userId, open, pending, onSave }: {
  workspaceId: string;
  userId: string;
  open: boolean;
  pending: string;
  onSave: (data: Parameters<typeof api.addRequirementSource>[1]) => Promise<boolean>;
}) {
  const client = useQueryClient();
  const [restored] = useState(() => readRequirementSourceDraft(client, userId, workspaceId));
  const [discarding, setDiscarding] = useState(false);
  const [sourceTitle, setSourceTitle] = useState(restored?.title || "");
  const [sourceKind, setSourceKind] = useState<SourceKind>(restored?.kind || "document");
  const [importWarnings, setImportWarnings] = useState<string[]>(restored?.warnings || []);
  const [importing, setImporting] = useState(false);
  const [content, setContent] = useState(restored?.content || "");
  const [error, setError] = useState<unknown>(null);
  const bounds = useMemo(() => requirementTextBounds(content, 100000), [content]);
  const hasDraft = Boolean(sourceTitle || content);
  useEffect(() => {
    rememberRequirementSourceDraft(client, userId, workspaceId, hasDraft ? { title: sourceTitle, kind: sourceKind, content, warnings: importWarnings } : null);
  }, [client, userId, workspaceId, hasDraft, sourceTitle, sourceKind, content, importWarnings]);
  function clearDraft() {
    rememberRequirementSourceDraft(client, userId, workspaceId, null);
    setSourceTitle(""); setContent(""); setSourceKind("document"); setImportWarnings([]); setError(null); setDiscarding(false);
  }
  async function importText(file?: File) {
    if (!file || importing || pending) return;
    const previous = readRequirementSourceDraft(client, userId, workspaceId);
    // Keep a pending draft identity so navigation, replacement and logout are distinguishable.
    rememberRequirementSourceDraft(client, userId, workspaceId, { title: sourceTitle, kind: sourceKind, content, warnings: importWarnings });
    const isCurrent = captureRequirementDraftSave(client, userId, workspaceId, "source");
    setError(null); setImporting(true);
    try {
      const result = await prepareRequirementSource(file, workspaceId, api);
      if (!isCurrent()) return;
      rememberRequirementSourceDraft(client, userId, workspaceId, result);
      setContent(result.content); setSourceTitle(result.title); setSourceKind(result.kind); setImportWarnings(result.warnings);
    } catch (caught) {
      if (isCurrent()) rememberRequirementSourceDraft(client, userId, workspaceId, previous || null);
      setError(caught);
    }
    finally { setImporting(false); }
  }

  if (!open) return null;
  return <>
    <ConfirmDialog open={discarding} onOpenChange={setDiscarding} title="Discard source draft?" description="This removes the unsaved title, text and import preview. Saved sources are unchanged." confirmLabel="Discard draft" cancelLabel="Keep editing" destructive onConfirm={clearDraft} />
    {Boolean(error) && <p role="alert" className="rounded-lg bg-rust-400/10 p-3 text-sm text-rust-600">{requirementErrorMessage(error)}</p>}
      <form className={`${panelStyle} space-y-4`} onSubmit={async event => { event.preventDefault(); if (importing || pending || !bounds.valid) return; setError(null); const isCurrent = captureRequirementDraftSave(client, userId, workspaceId, "source"); if (await onSave({ title: sourceTitle, kind: sourceKind, content }) && isCurrent()) { clearDraft(); } }}>
        <h2 className="text-lg font-semibold">Add supporting material</h2><p className="text-sm text-ink-500">Paste business material or import a document, email or meeting transcript. Sources are preserved so every requirement can point back to its evidence.</p>
        {hasDraft && <p role="status" className="text-xs text-amber-800">Unsaved material · Kept in this tab while you browse. Save before refreshing or closing.</p>}
        <Field label="Import source file"><input type="file" disabled={importing || Boolean(pending)} accept=".txt,.md,.eml,.docx,.pdf,.vtt,.srt" onChange={event => { void importText(event.target.files?.[0]); event.target.value = ""; }} className="mt-2 block w-full text-sm" /></Field>
        {importing && <p role="status" className="text-xs">Preparing source preview…</p>}
        {importWarnings.map(warning => <p key={warning} className="text-xs text-amber-800">{warning}</p>)}
        <Field label="Source title"><RequirementInput disabled={importing || Boolean(pending)} required maxLength={200} className={inputStyle} value={sourceTitle} onChange={event => setSourceTitle(event.target.value)} /></Field>
        <Field label="Source type"><select disabled={importing || Boolean(pending)} className={inputStyle} value={sourceKind} onChange={event => setSourceKind(event.target.value as SourceKind)}>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        <Field label="Source text"><textarea disabled={importing || Boolean(pending)} required aria-invalid={Boolean(content) && !bounds.valid} rows={7} className={inputStyle} value={content} onChange={event => setContent(event.target.value)} /></Field><p className="text-xs text-ink-400">{bounds.length.toLocaleString()} / 100,000 characters · TXT, Markdown, EML, DOCX, PDF, VTT and SRT · 400 KB file limit.</p>
        <p className="text-xs text-ink-500">Use 10–100,000 characters after trimming spaces, without NUL characters.</p>
        <p className="text-xs text-ink-500">Review the text before saving. Keep speaker names and timestamps when they explain who said what. Select SOP or Meeting transcript when appropriate; file format alone does not establish the business context.</p>
        <Button type="submit" pending={pending === "source"} disabled={importing || Boolean(pending) || !bounds.valid}>Save source</Button>
        {hasDraft && <Button variant="ghost" disabled={importing || Boolean(pending)} onClick={() => setDiscarding(true)}>Discard source draft</Button>}
      </form>
  </>;
}
