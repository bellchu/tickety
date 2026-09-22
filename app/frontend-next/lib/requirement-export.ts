import type { RequirementWorkspaceDetail } from "./requirements-types";

export function requirementBrief(detail: RequirementWorkspaceDetail): string {
  const { workspace, requirements, sources } = detail;
  const lines = [
    `# Business requirements: ${workspace.title}`, "",
    `Initiative ID: ${workspace.id}`,
    `Request type: ${workspace.request_type === "enhancement" ? "Enhancement" : "Approved project / request"}`, "",
    "## Business objective", workspace.objective, "",
    "## Evidence register",
    ...sources.map(source => `- ${source.title} (${source.kind}) — ${source.id}; SHA-256: ${source.content_sha256}`), "",
    "## Documented requirements and functional specification",
  ];
  for (const row of requirements) {
    lines.push("", `### ${row.reference}: ${row.title}`, `Status: ${row.status} | Priority: ${row.priority} | Revision: ${row.revision}`,
      `Delivery scope: ${row.priority === "wont" ? "Deferred — not this time" : "Included"}`,
      `Stakeholder: ${row.actor || "To confirm"}`, `Required capability: ${row.action || "To clarify"}`,
      `Business outcome: ${row.benefit || "To agree"}`, `Source: ${row.source_id}`,
      "Evidence:", row.evidence_quote, "", "Acceptance criteria:",
      ...row.acceptance_criteria.map(item => `- ${item}`));
    if (row.quality_issues.length) lines.push("Open clarification items:", ...row.quality_issues.map(item => `- ${item}`));
    if (row.validated_at) lines.push(`Signed off by user ${row.validated_by || "Deleted account"} as ${row.reviewer_role} at ${row.validated_at}.`, `Review note: ${row.validation_note}`);
    if (row.story && row.priority !== "wont") lines.push("", `#### ${row.story.reference}: ${row.story.title}`, row.story.statement,
      `Traces to ${row.story.requirement_reference}, validated revision ${row.story.validated_revision}.`);
  }
  lines.push("", "## Questions and business decisions");
  for (const item of detail.decisions || []) {
    const scope = item.requirement_id ? requirements.find(row => row.id === item.requirement_id)?.reference || item.requirement_id : "Whole initiative";
    lines.push("", `### ${item.question}`, `Scope: ${scope} | Answer owner: ${item.owner_role}`,
      `Status: ${item.status} | Blocks sign-off: ${item.blocking ? "Yes" : "No"}`);
    if (item.resolution) lines.push(`Decision: ${item.resolution}`, `Recorded by ${item.resolved_by || "Former member"} at ${item.resolved_at}`);
  }
  const blockers = (detail.decisions || []).filter(item => item.status === "open" && item.blocking).length;
  const stories = requirements.filter(item => item.priority !== "wont" && item.story).length;
  lines.push("", "## Development handoff", `${stories} user stories prepared for delivery-team review; ${blockers} blocking business questions remain. No external development tickets have been created.`, "");
  return lines.join("\n");
}
