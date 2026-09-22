"use client";

import { requirementErrorMessage } from "@/lib/requirement-errors";

import { useState } from "react";
import { api } from "@/lib/api";
import type { SourceKind } from "@/lib/requirements-types";
import { Button } from "@/components/ui";
import { Field, inputStyle, panelStyle, kinds } from "./fields";

export function SourceIntakeForm({ workspaceId, open, pending, onSave }: {
  workspaceId: string;
  open: boolean;
  pending: string;
  onSave: (data: Parameters<typeof api.addRequirementSource>[1]) => Promise<boolean>;
}) {
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceKind, setSourceKind] = useState<SourceKind>("document");
  const [importWarnings, setImportWarnings] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);
  const [content, setContent] = useState("");
  const [error, setError] = useState<unknown>(null);
  async function importText(file?: File) {
    if (!file) return;
    setError(null); setImportWarnings([]); setImporting(true);
    try {
      if (!/\.(txt|md|eml|docx|pdf|vtt|srt)$/i.test(file.name)) throw new Error("Choose a TXT, Markdown, EML, DOCX, PDF, VTT or SRT file. Text files must use UTF-8.");
      if (file.size > 400000) throw new Error("Choose a file smaller than 400 KB.");
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (/\.(eml|docx|pdf)$/i.test(file.name)) {
        let binary = "";
        for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
        const isEmail = /\.eml$/i.test(file.name);
        const preview = isEmail ? api.previewRequirementEmail : /\.pdf$/i.test(file.name) ? api.previewRequirementPdf : api.previewRequirementDocx;
        const result = await preview(workspaceId, btoa(binary));
        setContent(result.content); setSourceTitle(result.title || file.name); setSourceKind(isEmail ? "email" : "document"); setImportWarnings(result.warnings);
        return;
      }
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      if (text.length > 100000 || text.includes("\0")) throw new Error("Source text must contain at most 100,000 characters and no NUL characters.");
      setContent(text); setSourceTitle(file.name);
      if (/\.(vtt|srt)$/i.test(file.name)) setSourceKind("transcript");
    } catch (caught) { setError(caught); }
    finally { setImporting(false); }
  }

  if (!open) return null;
  return <>
    {Boolean(error) && <p role="alert" className="rounded-lg bg-rust-400/10 p-3 text-sm text-rust-600">{requirementErrorMessage(error)}</p>}
      <form className={`${panelStyle} space-y-4`} onSubmit={async event => { event.preventDefault(); setError(null); if (await onSave({ title: sourceTitle, kind: sourceKind, content })) { setSourceTitle(""); setContent(""); setImportWarnings([]); } }}>
        <h2 className="text-lg font-semibold">Add supporting material</h2><p className="text-sm text-ink-500">Paste source material or import a document or email. Sources are preserved so every requirement can point back to its evidence.</p>
        <Field label="Import source file"><input type="file" disabled={importing || Boolean(pending)} accept=".txt,.md,.eml,.docx,.pdf,.vtt,.srt" onChange={event => { void importText(event.target.files?.[0]); event.target.value = ""; }} className="mt-2 block w-full text-sm" /></Field>
        {importing && <p role="status" className="text-xs">Preparing source preview…</p>}
        {importWarnings.map(warning => <p key={warning} className="text-xs text-amber-800">{warning}</p>)}
        <Field label="Source title"><input disabled={importing || Boolean(pending)} required maxLength={200} className={inputStyle} value={sourceTitle} onChange={event => setSourceTitle(event.target.value)} /></Field>
        <Field label="Source type"><select disabled={importing || Boolean(pending)} className={inputStyle} value={sourceKind} onChange={event => setSourceKind(event.target.value as SourceKind)}>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        <Field label="Source text"><textarea disabled={importing || Boolean(pending)} required minLength={10} maxLength={100000} rows={7} className={inputStyle} value={content} onChange={event => setContent(event.target.value)} /></Field><p className="text-xs text-ink-400">{content.length.toLocaleString()} / 100,000 characters · Text, EML, DOCX and PDF · 400 KB file limit.</p>
        <Button type="submit" pending={pending === "source"} disabled={importing || Boolean(pending)}>Save source</Button>
      </form>
  </>;
}
