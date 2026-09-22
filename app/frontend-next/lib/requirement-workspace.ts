import type { BusinessRequirement, RequirementWorkspaceDetail } from "./requirements-types";

export type RequirementFilter = "all" | "questions" | "review" | "delivery";

export function filterRequirements(items: BusinessRequirement[], search: string, filter: RequirementFilter) {
  const query = search.trim().toLocaleLowerCase();
  return items.filter(item => {
    const matchesText = !query || [item.reference, item.title, item.actor, item.action, item.benefit]
      .some(value => value.toLocaleLowerCase().includes(query));
    const matchesFilter = filter === "all"
      || (filter === "questions" && item.quality_issues.length > 0)
      || (filter === "review" && item.status === "draft" && item.quality_issues.length === 0)
      || (filter === "delivery" && item.story !== null);
    return matchesText && matchesFilter;
  });
}

export function workspaceFocus(detail: RequirementWorkspaceDetail) {
  const items = detail.requirements;
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
  const unstated = detail.sources.find(source => !items.some(item => item.source_id === source.id));
  if (unstated) return {
    title: "Explore the context you have collected",
    reason: `“${unstated.title}” has no linked requirements yet. Identify the business needs, or keep it as supporting context.`,
    label: "Explore this source", action: "gather" as const, sourceId: unstated.id,
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
