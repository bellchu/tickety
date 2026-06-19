"use client";

import { ListTree } from "lucide-react";

/** Color-coded semantic categories for AI reasoning log segments. */
const CATEGORIES: { prefix: string; color: string }[] = [
  { prefix: "scope:",    color: "bg-blue-50 border-blue-200 text-blue-800" },
  { prefix: "urgency:",  color: "bg-red-50 border-red-200 text-red-800"   },
  { prefix: "impact:",   color: "bg-amber-50 border-amber-200 text-amber-800" },
  { prefix: "category:", color: "bg-emerald-50 border-emerald-200 text-emerald-800" },
  { prefix: "status:",   color: "bg-slate-100 border-slate-200 text-slate-700" },
  { prefix: "action:",   color: "bg-violet-50 border-violet-200 text-violet-800" },
  { prefix: "note:",     color: "bg-slate-50 border-slate-200 text-slate-600" },
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
        color: "bg-slate-50 border-slate-200 text-slate-700",
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
      <span key={i} className="font-bold tabular-nums text-slate-900">{p}</span>
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
        <ListTree className="w-4 h-4 text-slate-600" />
        <h3 className="text-sm font-semibold text-slate-900">AI Reasoning Log</h3>
      </div>

      <div className="space-y-2">
        {segments.map((seg, i) => (
          <div
            key={i}
            className={`flex gap-3 rounded-md border px-3 py-2.5 ${seg.color}`}
          >
            <span className="shrink-0 text-[11px] font-bold uppercase tracking-wider opacity-70 w-16">
              {seg.label}
            </span>
            <span className="text-sm leading-relaxed">
              {highlightKeywords(seg.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
