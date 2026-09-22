"use client";

import { reviewQuestionDraft } from "@/lib/requirement-review-question";
import { Button } from "@/components/ui";
import { panelStyle } from "./fields";
import { requirementSnapshotsCurrent } from "@/lib/requirement-workspace";
import type { BusinessRequirement, RequirementAssistance } from "@/lib/requirements-types";

export function AIRequirementReview({ assistance, current: assistanceItem, busy, onDismiss, onReanalyze, onRefine, onQuestion }: {
  assistance: { item: BusinessRequirement; result: RequirementAssistance };
  current?: BusinessRequirement;
  busy: boolean;
  onDismiss: () => void;
  onReanalyze: () => void;
  onRefine: () => void;
  onQuestion: (question: string, requirementId: string) => void;
}) {
  const assistanceStale = !requirementSnapshotsCurrent(
    [{ id: assistance.item.id, revision: assistance.result.base_revision }],
    assistanceItem ? [assistanceItem] : [],
  );
  return (
    <section className={`${panelStyle} space-y-4`} aria-label="AI requirement review">
      <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">AI {assistance.result.mode === "review" ? "review" : "story refinement"} · {assistance.item.reference}</h2><Button variant="ghost" onClick={onDismiss}>Dismiss review</Button></div>
      <p className="text-xs text-ink-400">{assistance.result.model} · Based on revision {assistance.result.base_revision}</p>
      {assistanceStale && <div role="status" className="space-y-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800"><p>This requirement has changed since this analysis. These suggestions are kept for reference; analyze the current version before using them.</p>{assistanceItem && <Button size="sm" variant="secondary" disabled={busy || (assistance.result.mode === "story" && (assistanceItem.status !== "validated" || assistanceItem.priority === "wont"))} onClick={onReanalyze}>Analyze current version</Button>}{assistance.result.mode === "story" && assistanceItem && (assistanceItem.status !== "validated" || assistanceItem.priority === "wont") && <p>Story refinement becomes available after the current requirement is in scope and signed off.</p>}</div>}
      {assistance.result.input_truncated && <p className="text-sm text-amber-800">This review covers only part of the requirement. Check the complete requirement before making a decision.</p>}
      {assistance.result.suggestions.findings?.map((finding, index) => <div key={index} className="rounded-lg bg-linen-100 p-3 text-sm"><strong>{finding.category.replaceAll("_", " ")}</strong><p>{finding.finding}</p><p className="mt-2 text-ink-500">{finding.question}</p><Button size="sm" variant="ghost" disabled={assistanceStale} onClick={() => onQuestion(reviewQuestionDraft(finding.question, finding.finding, [{ reference: assistance.item.reference, revision: assistance.result.base_revision }]), assistance.item.id)}>Track question</Button></div>)}
      {assistance.result.mode === "review" && assistance.result.suggestions.findings?.length === 0 && <p className="text-sm">No findings were suggested. Human review and sign-off are still required.</p>}
      {assistance.result.suggestions.questions?.map((question, index) => <div key={index} className="text-sm"><p>{question}</p><Button size="sm" variant="ghost" disabled={assistanceStale} onClick={() => onQuestion(question, assistance.item.id)}>Track question</Button></div>)}
      {assistance.result.mode === "story" && <><p className="text-sm">As a {assistance.result.suggestions.actor}, I want to {assistance.result.suggestions.action}, so that {assistance.result.suggestions.benefit}.</p><ul className="list-disc pl-5 text-sm">{assistance.result.suggestions.acceptance_criteria?.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>{Boolean(assistance.result.suggestions.assumptions?.length) && <div className="text-sm text-amber-800"><strong>Assumptions to confirm</strong><ul className="list-disc pl-5">{assistance.result.suggestions.assumptions?.map((assumption, index) => <li key={index}>{assumption}<Button size="sm" variant="ghost" disabled={assistanceStale} onClick={() => onQuestion(assumption, assistance.item.id)}>Track assumption</Button></li>)}</ul></div>}<p className="text-xs text-ink-500">Saving this refinement creates a revised draft and requires a new sign-off.</p><Button variant="secondary" disabled={busy || assistanceStale} onClick={onRefine}>Review as a new revision</Button></>}
    </section>
  );
}
