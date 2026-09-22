"use client";

import { useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui";
import { Field, inputStyle } from "./fields";

export function SourceExplorer({ content, canAI, busy, onExplore }: { content: string; canAI: boolean; busy: boolean; onExplore: (excerpt: string) => Promise<void> }) {
  const source = useRef<HTMLPreElement>(null);
  const [excerpt, setExcerpt] = useState("");
  const passage = excerpt.trim();
  const matches = passage.length >= 10 && passage.length <= 12000 && content.includes(passage);
  function captureSelection() {
    if (!canAI || busy) return;
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (source.current?.contains(range.startContainer) && source.current.contains(range.endContainer)) setExcerpt(selection.toString());
  }
  return <div className="space-y-3">
    <pre ref={source} tabIndex={0} aria-label="Saved source text" onMouseUp={captureSelection} onKeyUp={captureSelection} className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-linen-100 p-3 font-sans text-xs leading-5 text-ink-500">{content}</pre>
    {canAI && <div className="space-y-2 border-t border-linen-300 pt-3">
      <Field label="Focus on a passage"><textarea disabled={busy} rows={4} maxLength={12000} className={inputStyle} placeholder="Select text above or paste an exact passage to explore a specific section." value={excerpt} onChange={event => setExcerpt(event.target.value)} /></Field>
      <p className="text-xs text-ink-400">{passage.length.toLocaleString()} / 12,000 characters · The original source remains unchanged.</p>
      {passage && !matches && <p className="text-xs text-amber-800">Choose 10–12,000 characters matching an exact passage in this source.</p>}
      <Button size="sm" variant="secondary" leadingIcon={<Sparkles size={13} />} disabled={busy || !matches} onClick={() => onExplore(passage)}>Explore this passage</Button>
    </div>}
  </div>;
}
