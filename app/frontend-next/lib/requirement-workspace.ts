import type { BusinessRequirement, RequirementDecision, RequirementWorkspaceDetail } from "./requirements-types";

export type DecisionFilter = "open" | "blocking" | "exploratory" | "recorded" | "all";

export function filterDecisions(items: RequirementDecision[], filter: DecisionFilter, search: string, editingId = "", requirementId = "") {
  const query = search.trim().toLocaleLowerCase();
  const matching = items.filter(item => {
    if (item.id === editingId) return true;
    if (requirementId && item.requirement_id && item.requirement_id !== requirementId) return false;
    const matchesStatus = filter === "all" || (filter === "recorded" ? item.status === "resolved"
      : item.status === "open" && (filter === "open" || (filter === "blocking" ? item.blocking : !item.blocking)));
    return matchesStatus && (!query || [item.question, item.owner_role, item.resolution || ""].some(value => value.toLocaleLowerCase().includes(query)));
  });
  // Triage open work by its effect on agreement, preserving order within each group.
  return filter === "open" ? matching.sort((left, right) =>
    Number(right.status === "open" && right.blocking) - Number(left.status === "open" && left.blocking),
  ) : matching;
}

export type RequirementFilter = "all" | "questions" | "review" | "agreed" | "delivery" | "deferred";

export function sourceRequirementCounts(items: BusinessRequirement[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.source_id, (counts.get(item.source_id) || 0) + 1);
  return counts;
}

export function blockedRequirementIds(items: BusinessRequirement[], decisions: RequirementDecision[] = []): Set<string> {
  const blocked = new Set<string>();
  for (const decision of decisions) {
    if (decision.status !== "open" || !decision.blocking) continue;
    if (!decision.requirement_id) return new Set(items.map(item => item.id));
    blocked.add(decision.requirement_id);
  }
  return blocked;
}

export function filterRequirements(items: BusinessRequirement[], search: string, filter: RequirementFilter, decisions: RequirementDecision[] = [], sourceId = "") {
  const query = search.trim().replace(/\s+/g, " ").toLocaleLowerCase();
  const blockedIds = blockedRequirementIds(items, decisions);
  return items.filter(item => {
    if (sourceId && item.source_id !== sourceId) return false;
    const matchesText = !query || [item.reference, item.title, item.actor, item.action, item.benefit, item.evidence_quote,
      ...(item.acceptance_criteria || []), item.story?.reference, item.story?.title, item.story?.statement]
      .some(value => value?.replace(/\s+/g, " ").toLocaleLowerCase().includes(query));
    const blocked = blockedIds.has(item.id);
    const matchesFilter = filter === "all"
      || (filter === "deferred" && item.priority === "wont")
      || (filter === "questions" && item.priority !== "wont" && (blocked || item.quality_issues.length > 0))
      || (filter === "review" && item.priority !== "wont" && item.status === "draft" && !blocked && item.quality_issues.length === 0)
      || (filter === "agreed" && item.priority !== "wont" && item.status === "validated" && !item.story && !blocked)
      || (filter === "delivery" && item.priority !== "wont" && item.story !== null);
    return matchesText && matchesFilter;
  });
}

export function workspaceFocus(detail: RequirementWorkspaceDetail) {
  const items = orderRequirements(detail.requirements.filter(item => item.priority !== "wont"), "priority");
  const activeIds = new Set(items.map(item => item.id));
  const blockers = (detail.decisions || []).filter(item => item.status === "open" && item.blocking && (!item.requirement_id || activeIds.has(item.requirement_id)));
  if (blockers.length) return {
    title: "A business answer is needed",
    reason: `${blockers.length} blocking questions need a recorded decision. Start with ${blockers[0].owner_role}: ${blockers[0].question}`,
    label: "Open the decision log", action: "decisions" as const,
  };
  if (!detail.sources.length) return {
    title: "Ground the business need",
    reason: "Add the material behind the request so decisions can be traced to evidence.",
    label: "Add supporting material", action: "source" as const,
  };
  const unclear = items.filter(item => item.quality_issues.length > 0);
  if (unclear.length) return {
    title: "Resolve what is still uncertain",
    reason: `${unclear.length} requirements have unanswered questions. Clarify the expected outcome or acceptance criteria before asking for agreement.`,
    label: "Work through open questions", action: "questions" as const,
  };
  const reviewable = items.find(item => item.status === "draft");
  if (reviewable) return {
    title: "A business decision is ready",
    reason: `${reviewable.reference} has the essential detail and comes next by recorded business priority. Confirm it with the accountable stakeholder and record the decision.`,
    label: "Review the requirement", action: "review" as const, item: reviewable,
  };
  const linkedSources = sourceRequirementCounts(detail.requirements);
  const unstated = detail.sources.find(source => !linkedSources.has(source.id));
  if (unstated) return {
    title: "Explore the context you have collected",
    reason: `“${unstated.title}” has no linked requirements yet. Identify the business needs, or keep it as supporting context.`,
    label: "Explore this source", action: "gather" as const, sourceId: unstated.id,
  };
  if (!items.length) return {
    title: "The captured needs are outside this delivery scope",
    reason: "Keep their evidence for future planning. Bring a requirement back into scope when its business priority changes.",
    label: "Review deferred needs", action: "deferred" as const,
  };
  const agreed = items.find(item => item.status === "validated" && !item.story);
  if (agreed) return {
    title: "Turn agreement into a delivery conversation",
    reason: `${agreed.reference} is signed off and comes next by recorded business priority. Create a story with the agreed scope and acceptance criteria for delivery-team review.`,
    label: "Prepare its user story", action: "story" as const, item: agreed,
  };
  return {
    title: "Ready for a delivery review",
    reason: "The current requirements have signed-off stories. Export the brief for estimation and planning, or add new evidence if the business need changes.",
    label: "Export the business brief", action: "export" as const,
  };
}

export function reviewUnavailableReason(reviewed: BusinessRequirement, current: BusinessRequirement | undefined, blocked: boolean): string | null {
  if (!current) return "This requirement is no longer available. Your review note has been kept.";
  if (current.revision !== reviewed.revision) return `The requirement has changed to revision ${current.revision}. Your note is kept; review the current version before signing off.`;
  if (current.priority === "wont") return "This requirement is outside the current delivery scope.";
  if (current.status !== "draft") return "This requirement has already been signed off.";
  if (blocked) return "Resolve the blocking business questions before signing off.";
  if (current.quality_issues.length) return "Clarify the requirement's open quality issues before signing off.";
  return null;
}

export type RequirementOrder = "recorded" | "priority";
const priorityOrder = { must: 0, should: 1, could: 2, wont: 3 };
export function orderRequirements(items: BusinessRequirement[], order: RequirementOrder) {
  return order === "priority" ? [...items].sort((left, right) => priorityOrder[left.priority] - priorityOrder[right.priority]) : items;
}

/** AI findings remain actionable only for the exact saved snapshots reviewed. */
export function requirementSnapshotsCurrent(
  snapshots: { id: string; revision: number }[],
  items: { id: string; revision: number }[],
): boolean {
  const revisions = new Map(items.map(item => [item.id, item.revision]));
  return snapshots.every(snapshot => revisions.get(snapshot.id) === snapshot.revision);
}

export function decisionWindow(items: RequirementDecision[], limit: number, editingId = "") {
  return items.filter((item, index) => index < limit || item.id === editingId);
}
