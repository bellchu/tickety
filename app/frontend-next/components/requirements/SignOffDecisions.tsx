import { memo } from "react";
import { filterDecisions, prioritizeBlockingDecisions } from "@/lib/requirement-workspace";
import type { RequirementDecision } from "@/lib/requirements-types";

/** Read-only context; recording an answer never substitutes for human sign-off. */
export const SignOffDecisions = memo(function SignOffDecisions({ requirementId, decisions }: { requirementId: string; decisions: RequirementDecision[] }) {
  const related = prioritizeBlockingDecisions(filterDecisions(decisions, "all", "", "", requirementId));
  const blockers = related.filter(item => item.status === "open" && item.blocking).length;
  const exploratory = related.filter(item => item.status === "open" && !item.blocking).length;
  const recorded = related.length - blockers - exploratory;
  return <section className="space-y-3 rounded-lg border border-linen-400 p-4" aria-label="Business decisions affecting sign-off">
    <h3 className="text-sm font-semibold">Business decisions to consider</h3>
    {related.length ? <>
      <p className="text-xs text-ink-500">{recorded} recorded · {blockers} blocking · {exploratory} exploratory</p>
      <p className="text-sm text-ink-500">Check that the requirement and acceptance criteria reflect these answers. Unanswered blocking questions appear first. Whole-initiative decisions apply here too. Exploratory questions remain open without blocking agreement.</p>
      <div className="max-h-72 space-y-2 overflow-y-auto">
        {related.map(item => <details key={item.id} className="rounded-lg bg-linen-50 p-3 text-sm">
          <summary className="cursor-pointer font-medium text-ink-700">{item.question}<span className="ml-2 text-xs font-normal text-ink-500">{item.status === "resolved" ? "Decision recorded" : item.blocking ? "Blocks sign-off" : "Exploratory"}</span></summary>
          <p className="mt-2 text-xs text-ink-500">{item.requirement_id ? "This requirement" : "Whole initiative"} · Answer owner: {item.owner_role}</p>
          <p className="mt-2 whitespace-pre-wrap break-words text-ink-600">{item.status === "resolved" ? item.resolution : "An answer has not been recorded yet."}</p>
        </details>)}
      </div>
    </> : <p className="text-sm text-ink-500">No business questions or decisions are recorded for this requirement or the whole initiative. Confirm any unresolved assumptions with the stakeholder.</p>}
  </section>;
});
