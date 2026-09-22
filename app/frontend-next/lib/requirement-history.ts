import type { BusinessRequirement } from "./requirements-types";

export const requirementHistoryFields: [keyof BusinessRequirement, string][] = [["title", "Title"], ["actor", "Stakeholder"], ["action", "Capability"], ["benefit", "Outcome"], ["priority", "Priority"], ["source_id", "Source"], ["evidence_quote", "Evidence"], ["acceptance_criteria", "Acceptance criteria"], ["status", "Agreement status"], ["validated_by", "Signed off by"], ["validated_at", "Signed off at"], ["reviewer_role", "Review capacity"], ["validation_note", "Review note"], ["story", "User story"]];

export function requirementChanges(before: BusinessRequirement | null, after: BusinessRequirement) {
  return requirementHistoryFields.filter(([key]) => !before || JSON.stringify(before[key]) !== JSON.stringify(after[key]));
}

export function requirementChangeSummary(before: BusinessRequirement | null, after: BusinessRequirement): string {
  if (!before) return "Initial evidence and business need recorded.";
  const changed = requirementChanges(before, after);
  const business = changed.filter(([key]) => ["title", "actor", "action", "benefit", "priority", "source_id", "evidence_quote", "acceptance_criteria"].includes(key)).map(([, label]) => label);
  const notes: string[] = [];
  if (business.length) notes.push(`Changed: ${business.join(", ")}.`);
  if (before.priority !== "wont" && after.priority === "wont") notes.push("Removed from current delivery scope.");
  if (before.priority === "wont" && after.priority !== "wont") notes.push("Returned to current delivery scope.");
  if (before.status === "validated" && after.status !== "validated") notes.push("Previous agreement withdrawn; a new sign-off is required.");
  if (before.status !== "validated" && after.status === "validated") notes.push("Business agreement recorded.");
  if (before.story && !after.story) notes.push("Previous user story withdrawn.");
  if (!before.story && after.story) notes.push("User story prepared from the agreed requirement.");
  return notes.join(" ") || (changed.length ? `Changed: ${changed.map(([, label]) => label).join(", ")}.` : "No tracked field changes.");
}
