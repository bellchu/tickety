"use client";

import { locateEvidenceQuote } from "@/lib/requirement-evidence";
import { requirementTextBounds } from "@/lib/requirement-text";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { readRequirementPassage, rememberRequirementPassage } from "@/lib/requirement-editor-cache";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui";
import { Field, inputStyle } from "./fields";

export function SourceExplorer({ userId, workspaceId, sourceId, content, canAI, busy, focus, onCapture, onExplore }: { userId: string; workspaceId: string; sourceId: string; onCapture: (excerpt: string) => void; focus?: { quote: string; reference: string }; content: string; canAI: boolean; busy: boolean; onExplore: (excerpt: string) => Promise<void> }) {
  const source = useRef<HTMLPreElement>(null);
  const highlight = useRef<HTMLElement>(null);
  const [occurrence, setOccurrence] = useState<{ focus?: typeof focus; position?: number }>({});
  const { position, previous, next } = useMemo(() => locateEvidenceQuote(content, focus?.quote || "", occurrence.focus === focus ? occurrence.position : undefined), [content, focus, occurrence]);
  useEffect(() => {
    if (!focus) return;
    const target = highlight.current || source.current;
    target?.scrollIntoView({ block: "center" });
    target?.focus({ preventScroll: true });
  }, [focus, content, position]);
  const client = useQueryClient();
  const [excerpt, updateExcerpt] = useState(() => readRequirementPassage(client, userId, workspaceId, sourceId));
  function setExcerpt(value: string) {
    rememberRequirementPassage(client, userId, workspaceId, sourceId, value);
    updateExcerpt(value);
  }
  const passage = excerpt.trim();
  const bounds = useMemo(() => requirementTextBounds(excerpt, 12000), [excerpt]);
  const matches = bounds.valid && content.includes(passage);
  function captureSelection() {
    if (busy) return;
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (source.current?.contains(range.startContainer) && source.current.contains(range.endContainer)) setExcerpt(selection.toString());
  }
  return <div className="space-y-3">
    {focus && <p role="status" className="text-xs text-ink-500">{position >= 0 ? `${focus.reference} · Evidence highlighted in the source.` : `${focus.reference} · The excerpt could not be located in this source.`}</p>}
    {focus && (previous >= 0 || next >= 0) && <div className="space-y-2"><p className="text-xs text-amber-800">This excerpt appears more than once. Compare the surrounding text before interpreting it.</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="secondary" disabled={previous < 0} onClick={() => setOccurrence({ focus, position: previous })}>Previous occurrence</Button><Button size="sm" variant="secondary" disabled={next < 0} onClick={() => setOccurrence({ focus, position: next })}>Next occurrence</Button></div></div>}
    <pre ref={source} tabIndex={0} aria-label="Saved source text" onMouseUp={captureSelection} onKeyUp={captureSelection} className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-linen-100 p-3 font-sans text-xs leading-5 text-ink-500">{position >= 0 && focus ? <>{content.slice(0, position)}<mark ref={highlight} tabIndex={-1} aria-label={`Evidence for ${focus.reference}`} className="rounded bg-amber-100 text-ink-700 outline-clay-400">{focus.quote}</mark>{content.slice(position + focus.quote.length)}</> : content}</pre>
    <div className="space-y-2 border-t border-linen-300 pt-3">
      <Field label="Focus on a passage"><textarea disabled={busy} rows={4} aria-invalid={Boolean(passage) && !matches} className={inputStyle} placeholder="Select text above or paste an exact passage to explore a specific section." value={excerpt} onChange={event => setExcerpt(event.target.value)} /></Field>
      <p className="text-xs text-ink-400">{bounds.length.toLocaleString()} / 12,000 characters · The original source remains unchanged.</p>
      {excerpt && <div className="flex flex-wrap items-center gap-2"><p className="text-xs text-ink-500">Passage kept in this tab while you browse. Refreshing or signing out clears it.</p><Button size="sm" variant="ghost" disabled={busy} onClick={() => setExcerpt("")}>Clear passage</Button></div>}
      {passage && !matches && <p className="text-xs text-amber-800">Choose 10–12,000 characters matching an exact passage in this source.</p>}
      <p className="text-xs text-ink-500">Use 10–4,000 characters as evidence for a requirement. {canAI ? "Longer passages can be explored with AI." : "Add the business outcome and acceptance criteria in the draft."}</p>
      <Button size="sm" variant="secondary" disabled={busy || !matches || bounds.length > 4000} onClick={() => onCapture(passage)}>Draft a requirement from this passage</Button>
      {canAI && <Button size="sm" variant="secondary" leadingIcon={<Sparkles size={13} />} disabled={busy || !matches} onClick={() => onExplore(passage)}>Explore this passage</Button>}
    </div>
  </div>;
}
