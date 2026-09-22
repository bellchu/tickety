import type { BusinessRequirement, RequirementDecision, RequirementWorkspaceDetail } from "./requirements-types";

export type RequirementFilter = "all" | "questions" | "review" | "delivery" | "deferred";

export function blockedRequirementIds(items: BusinessRequirement[], decisions: RequirementDecision[] = []): Set<string> {
  const blocked = new Set<string>();
  for (const decision of decisions) {
    if (decision.status !== "open" || !decision.blocking) continue;
    if (!decision.requirement_id) return new Set(items.map(item => item.id));
    blocked.add(decision.requirement_id);
  }
  return blocked;
}

export function filterRequirements(items: BusinessRequirement[], search: string, filter: RequirementFilter, decisions: RequirementDecision[] = []) {
  const query = search.trim().toLocaleLowerCase();
  const blockedIds = blockedRequirementIds(items, decisions);
  return items.filter(item => {
    const matchesText = !query || [item.reference, item.title, item.actor, item.action, item.benefit]
      .some(value => value.toLocaleLowerCase().includes(query));
    const blocked = blockedIds.has(item.id);
    const matchesFilter = filter === "all"
      || (filter === "deferred" && item.priority === "wont")
      || (filter === "questions" && item.priority !== "wont" && (blocked || item.quality_issues.length > 0))
      || (filter === "review" && item.priority !== "wont" && item.status === "draft" && !blocked && item.quality_issues.length === 0)
      || (filter === "delivery" && item.priority !== "wont" && item.story !== null);
    return matchesText && matchesFilter;
  });
}

export function workspaceFocus(detail: RequirementWorkspaceDetail) {
  const items = detail.requirements.filter(item => item.priority !== "wont");
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
    reason: `${reviewable.reference} has the essential detail. Confirm it with the accountable stakeholder and record the decision.`,
    label: "Review the requirement", action: "review" as const, item: reviewable,
  };
  const unstated = detail.sources.find(source => !detail.requirements.some(item => item.source_id === source.id));
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
    reason: `${agreed.reference} is signed off. Create a story with the agreed scope and acceptance criteria for delivery-team review.`,
    label: "Prepare its user story", action: "story" as const, item: agreed,
  };
  return {
    title: "Ready for a delivery review",
    reason: "The current requirements have signed-off stories. Export the brief for estimation and planning, or add new evidence if the business need changes.",
    label: "Export the business brief", action: "export" as const,
  };
}
