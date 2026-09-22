import { currentScopeBlockers, filterDecisions, requirementPriorityLabels } from "./requirement-workspace";
import type { BusinessRequirement, RequirementWorkspaceDetail } from "./requirements-types";

export function requirementBriefFilename(workspace: { title: string; id: string }): string {
  const title = Array.from(workspace.title.normalize("NFKC").replace(/[^\p{L}\p{N}]+/gu, "-")).slice(0, 40).join("").replace(/^-+|-+$/g, "") || "untitled";
  const id = workspace.id.replace(/[^a-zA-Z0-9-]/g, "").slice(0, 36);
  return `requirements-${title}${id ? `-${id}` : ""}.md`;
}

function prose(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/[\\`*_[\]<>#|~]/g, "\\$&")
    .replace(/^( {0,3})([-=])([- =]*)$/gm, "$1\\$2$3")
    .replace(/^(\s*)([-+])(?=\s)/gm, "$1\\$2")
    .replace(/^(\s*\d+)([.)])(?=\s)/gm, "$1\\$2");
}
function inline(value: string): string { return prose(value.replace(/[\r\n]+/g, " ")); }
function bullet(value: string): string { return `- ${prose(value).replace(/\r?\n/g, "\n  ")}`; }
function evidenceBlock(value: string): string {
  const longest = Math.max(0, ...(value.match(/`+/g) || []).map(run => run.length));
  const fence = "`".repeat(Math.max(3, longest + 1));
  return `${fence}text\n${value}\n${fence}`;
}

export function requirementBrief(detail: RequirementWorkspaceDetail): string {
  const { workspace, requirements, sources } = detail;
  const requirementsById = new Map(requirements.map(item => [item.id, item]));
  const included = requirements.filter(item => item.priority !== "wont");
  const drafts = included.filter(item => item.status === "draft").length;
  const agreed = included.filter(item => item.status === "validated" && !item.story).length;
  const stories = included.filter(item => item.story).length;
  const openBlockers = (detail.decisions || []).filter(item => item.status === "open" && item.blocking);
  const blockers = openBlockers.length;
  const currentBlocking = new Set(currentScopeBlockers(requirements, detail.decisions));
  const currentBlockers = currentBlocking.size;
  const deferredBlockers = blockers - currentBlockers;
  const sourceLinks = new Map<string, string[]>();
  for (const row of requirements) {
    const references = sourceLinks.get(row.source_id) || [];
    references.push(`${row.reference}${row.priority === "wont" ? " (deferred)" : ""}`);
    sourceLinks.set(row.source_id, references);
  }
  const lines = [
    `# Business requirements: ${inline(workspace.title)}`, "",
    `Initiative ID: ${workspace.id}`,
    `Request type: ${workspace.request_type === "enhancement" ? "Enhancement" : "Approved project / request"}`, "",
    "## Business objective", prose(workspace.objective), "",
    "## Scope and readiness",
    `- Included in this initiative: ${included.length} requirements`,
    `- Drafts awaiting agreement: ${drafts}`,
    `- Signed off, awaiting story preparation: ${agreed}`,
    `- User stories prepared for delivery-team review: ${stories}`,
    `- Deferred — not this time: ${requirements.length - included.length}`,
    `- Open blocking business questions: ${blockers}`,
    `- Affecting current scope or requiring scope confirmation: ${currentBlockers}`,
    `- Linked only to deferred requirements: ${deferredBlockers}`,
    "", "This brief is a snapshot of recorded work. Inclusion is not sign-off; prepared stories still need delivery-team review and planning.", "",
    "## Evidence register",
    ...sources.flatMap(source => [
      `- ${inline(source.title)} (${source.kind}) — ${source.id}; SHA-256: ${source.content_sha256}`,
      ...(source.context_reviewed_at ? [`  Kept as background by ${inline(source.context_reviewed_by || "Former member")} at ${inline(source.context_reviewed_at)}; still available for exploration.`] : []),
      `  ${sourceLinks.has(source.id) ? `Supports: ${sourceLinks.get(source.id)!.join(", ")}` : "Supporting context — no linked requirements recorded."}`,
    ]), "",
    "## Documented requirements and functional specification",
  ];
  for (const row of requirements) {
    lines.push("", `### ${row.reference}: ${inline(row.title)}`, `Status: ${row.status === "validated" ? "Signed off" : "Draft — awaiting agreement"} | Priority: ${requirementPriorityLabels[row.priority]} | Revision: ${row.revision}`,
      `Delivery scope: ${row.priority === "wont" ? "Deferred — not this time" : "Included"}`,
      `Stakeholder: ${inline(row.actor || "To confirm")}`, `Required capability: ${prose(row.action || "To clarify")}`,
      `Business outcome: ${prose(row.benefit || "To agree")}`, `Source: ${row.source_id}`,
      "Evidence:", evidenceBlock(row.evidence_quote), "", "Acceptance criteria:",
      ...row.acceptance_criteria.map(bullet));
    if (row.quality_issues.length) lines.push("Open clarification items:", ...row.quality_issues.map(bullet));
    if (row.validated_at) lines.push(`Signed off by user ${inline(row.validated_by || "Deleted account")} as ${inline(row.reviewer_role || "Unrecorded capacity")} at ${inline(row.validated_at)}.`, `Review note: ${prose(row.validation_note || "")}`);
    if (row.story && row.priority !== "wont") lines.push("", `#### ${row.story.reference}: ${inline(row.story.title)}`, prose(row.story.statement),
      `Traces to ${row.story.requirement_reference}, validated revision ${row.story.validated_revision}.`);
  }
  lines.push("", "## Questions and business decisions",
    "Open blockers affecting current scope or needing scope confirmation appear first. Other records retain their recorded order.");
  const orderedDecisions = [...(detail.decisions || [])].sort((left, right) => Number(currentBlocking.has(right)) - Number(currentBlocking.has(left)));
  for (const item of orderedDecisions) {
    const scope = item.requirement_id ? requirementsById.get(item.requirement_id)?.reference || item.requirement_id : "Whole initiative";
    const deferred = item.requirement_id && requirementsById.get(item.requirement_id)?.priority === "wont";
    const effect = item.status === "resolved" ? "Answer recorded; this does not sign off or update requirements."
      : !item.blocking ? "Exploratory; does not block sign-off."
      : deferred ? "Blocks future sign-off if the requirement returns to delivery scope."
      : "Blocks sign-off for the affected scope.";
    lines.push("", `### ${inline(item.question)}`, `Scope: ${scope} | Answer owner: ${inline(item.owner_role || "Unassigned")}`,
      `Status: ${item.status === "resolved" ? "Decision recorded" : "Open question"} | Decision type: ${item.blocking ? "Required before sign-off" : "Exploratory"}`,
      `Current effect: ${effect}`);
    if (item.resolution) lines.push(`Decision: ${prose(item.resolution)}`, `Recorded by ${inline(item.resolved_by || "Former member")} at ${inline(item.resolved_at || "Unrecorded")}`);
  }
  lines.push("", "## Development handoff", `${stories} user stories prepared for delivery-team review; ${blockers} blocking business questions remain. ${currentBlockers} affect current scope or need scope confirmation; ${deferredBlockers} relate only to deferred requirements. No external development tickets have been created.`, "");
  return lines.join("\n");
}


export function requirementStoryText(detail: RequirementWorkspaceDetail, row: BusinessRequirement): string {
  const story = row.story;
  if (!story || row.status !== "validated" || row.priority === "wont") {
    throw new Error("Prepare an in-scope, signed-off user story before copying it.");
  }
  const source = detail.sources.find(item => item.id === row.source_id);
  const relevantDecisions = filterDecisions(detail.decisions || [], "all", "", "", row.id);
  const questions = relevantDecisions.filter(item => item.status === "open");
  const decisions = relevantDecisions.filter(item => item.status === "resolved");
  const lines = [
    `# ${story.reference}: ${inline(story.title)}`, "", prose(story.statement), "",
    "## Acceptance criteria", ...story.acceptance_criteria.map(bullet), "",
    "## Business context", prose(detail.workspace.objective),
    `Business priority: ${requirementPriorityLabels[row.priority]}`,
    "Delivery scope: Included in the current initiative", "",
    "## Traceability",
    `Initiative: ${inline(detail.workspace.title)} (${detail.workspace.id})`,
    `Requirement: ${story.requirement_reference}; signed-off revision ${story.validated_revision}`,
    `Source: ${inline(source?.title || "Source unavailable")} (${row.source_id})`,
    ...(source ? [`Evidence text SHA-256: ${source.content_sha256}`] : []),
    "Evidence excerpt:", evidenceBlock(row.evidence_quote),
    `Signed off by: ${inline(row.validated_by || "Former member")} as ${inline(row.reviewer_role || "Unrecorded capacity")}`,
    `Sign-off time: ${inline(row.validated_at || "Unrecorded")}`,
    `Review note: ${prose(row.validation_note || "Unrecorded")}`, "",
    "## Recorded business decisions",
    ...decisions.flatMap(item => [
      `### ${inline(item.question)}`,
      `Scope: ${item.requirement_id ? "This requirement" : "Whole initiative"}`,
      `Answer owner: ${inline(item.owner_role || "Unassigned")}`,
      `Decision: ${prose(item.resolution || "No resolution text recorded")}`,
      `Recorded by: ${inline(item.resolved_by || "Former member")} at ${inline(item.resolved_at || "Unrecorded")}`, "",
    ]),
    ...(decisions.length ? [] : ["No business decisions are recorded for this requirement or its initiative.", ""]),
    "## Open business questions",
    ...questions.map(item => bullet(`${item.blocking ? "Blocks sign-off" : "Exploratory"}: ${item.question} (Answer owner: ${item.owner_role || "Unassigned"})`)),
    ...(questions.length ? [] : ["No open questions are recorded for this requirement or its initiative."]), "",
    "Prepared for delivery-team review. No external development ticket has been created.",
  ];
  return lines.join("\n");
}
