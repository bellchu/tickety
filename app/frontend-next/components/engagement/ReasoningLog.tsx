"use client";

import { ListTree } from "lucide-react";

/** Color-coded semantic categories for AI reasoning log segments. */
const CATEGORIES: { prefix: string; color: string }[] = [
  { prefix: "scope:",    color: "bg-[var(--color-info-soft)] border-clay-200 text-clay-800" },
  { prefix: "urgency:",  color: "bg-[var(--color-danger-soft)] border-rust-400/30 text-rust-600"   },
  { prefix: "impact:",   color: "bg-amber-50 border-amber-200 text-amber-800" },
  { prefix: "category:", color: "bg-[var(--color-success-soft)] border-moss-400/30 text-moss-600" },
  { prefix: "status:",   color: "bg-linen-300 border-linen-400 text-ink-600" },
  { prefix: "action:",   color: "bg-[var(--color-primary-soft)] border-clay-200 text-clay-800" },
  { prefix: "note:",     color: "bg-linen-200 border-linen-400 text-ink-600" },
];

interface Segment {
  label: string;
  value: string;
  color: string;
}

function parseReasoning(text: string): Segment[] {
  const segments: Segment[] = [];
  const parts = text
    .replace(/\.(?=\s*(scope|urgency|impact|category|status|action|note|$))/gi, "|")
    .split("|")
    .filter(Boolean);

  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed) continue;

    let matched = false;
    for (const cat of CATEGORIES) {
      if (trimmed.toLowerCase().startsWith(cat.prefix)) {
        segments.push({
          label: cat.prefix.replace(":", ""),
          value: trimmed.slice(cat.prefix.length).trim(),
          color: cat.color,
        });
        matched = true;
        break;
      }
    }
    if (!matched) {
      segments.push({
        label: "info",
        value: trimmed,
        color: "bg-linen-200 border-linen-400 text-ink-600",
      });
    }
  }
  return segments;
}

function highlightKeywords(text: string): React.ReactNode {
  // Bold numbers and key metrics within value text
  const parts = text.split(/(\d+\s*(?:users|hours|minutes|days|tickets)?)/g);
  return parts.map((p, i) =>
    /\d/.test(p) ? (
      <span key={i} className="font-bold tabular-nums text-ink-700">{p}</span>
    ) : (
      p
    )
  );
}

export function ReasoningLog({ text }: { text: string }) {
  const segments = parseReasoning(text);

  return (
    <div className="card-surface p-6">
      <div className="flex items-center gap-2 mb-4">
        <ListTree className="w-4 h-4 text-ink-600" />
        <h3 className="text-sm font-semibold text-ink-700">AI Reasoning Log</h3>
      </div>

      <div className="space-y-2">
        {segments.map((seg, i) => (
          <div
            key={i}
            className={`flex min-w-0 flex-col gap-1.5 rounded-md border px-3 py-2.5 sm:flex-row sm:gap-3 ${seg.color}`}
          >
            <span className="shrink-0 text-[11px] font-bold uppercase tracking-wider opacity-70 sm:w-16">
              {seg.label}
            </span>
            <span className="min-w-0 break-words text-sm leading-relaxed [overflow-wrap:anywhere]">
              {highlightKeywords(seg.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
