"use client";

import { CheckCircle2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui";
import { formatLocalDateTime } from "@/lib/date-time";
import type { BusinessRequirement } from "@/lib/requirements-types";

export function RequirementCard({
  item, sourceTitle, canAI, busy, pending,
  onEdit, onReview, onSignOff, onCreateStory, onCopyStory, onRefine,
}: {
  item: BusinessRequirement;
  sourceTitle: string;
  canAI: boolean;
  busy: boolean;
  pending: string;
  onEdit: () => void;
  onReview: () => void;
  onSignOff: () => void;
  onCreateStory: () => void;
  onCopyStory: () => void;
  onRefine: () => void;
}) {
  const needsClarity = item.quality_issues.length > 0;
  const status = item.story ? "Delivery ready" : item.status === "validated" ? "Agreed" : needsClarity ? "Needs clarity" : "Ready for review";
  return (
    <article className="overflow-hidden rounded-xl border border-linen-400 bg-white shadow-sm">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="font-mono text-ink-400">{item.reference}</span>
          <span className={`rounded-full px-2.5 py-1 font-medium ${item.status === "validated" ? "bg-moss-500/10 text-moss-700" : needsClarity ? "bg-amber-50 text-amber-800" : "bg-linen-200 text-ink-500"}`}>{status}</span>
        </div>
        <h3 className="text-lg font-semibold leading-6 text-ink-700">{item.title}</h3>
        <p className="text-sm leading-6 text-ink-500">{item.action || "The required capability still needs to be clarified."}</p>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-400">
          <span>{item.actor || "Stakeholder to confirm"}</span>
          <span>{({ must: "Must have", should: "Should have", could: "Could have", wont: "Not this time" })[item.priority]}</span>
          <span>{sourceTitle}</span>
        </div>
        {needsClarity && <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          <p className="font-medium">Questions to resolve</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">{item.quality_issues.map(issue => <li key={issue}>{issue}</li>)}</ul>
        </div>}
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-ink-600">Evidence & acceptance criteria</summary>
          <div className="mt-3 space-y-3 text-ink-500">
            <blockquote className="border-l-2 border-clay-300 pl-3 italic">“{item.evidence_quote}”</blockquote>
            <p><strong className="font-medium">Business outcome:</strong> {item.benefit || "To agree"}</p>
            <ul className="list-disc space-y-1 pl-5">{item.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>
            {item.validated_at && <p className="text-xs text-moss-700">Signed off as {item.reviewer_role} · {formatLocalDateTime(item.validated_at)}<br />{item.validation_note}</p>}
          </div>
        </details>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={busy} onClick={onEdit}>Edit</Button>
          {canAI && <Button size="sm" variant="ghost" leadingIcon={<Sparkles size={14} />} pending={pending === `review-${item.id}`} disabled={busy} onClick={onReview}>Get AI perspective</Button>}
          {item.status === "draft" ? (
            <Button size="sm" leadingIcon={<CheckCircle2 size={14} />} disabled={busy || needsClarity} onClick={onSignOff}>Sign off</Button>
          ) : !item.story && (
            <Button size="sm" pending={pending === item.id} disabled={busy} onClick={onCreateStory}>Create user story</Button>
          )}
        </div>
      </div>
      {item.story && <details className="border-t border-linen-400 bg-linen-50 px-5 py-4" open>
        <summary className="cursor-pointer text-sm font-semibold text-ink-700">{item.story.reference} · User story</summary>
        <p className="mt-3 text-sm leading-6 text-ink-600">{item.story.statement}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={busy} onClick={onCopyStory}>Copy story</Button>
          {canAI && <Button size="sm" variant="ghost" leadingIcon={<Sparkles size={14} />} pending={pending === `refine-${item.id}`} disabled={busy} onClick={onRefine}>Explore another wording</Button>}
        </div>
      </details>}
    </article>
  );
}
