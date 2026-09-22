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
      `Stakeholder: ${row.actor || "To confirm"}`, `Required capability: ${row.action || "To clarify"}`,
      `Business outcome: ${row.benefit || "To agree"}`, `Source: ${row.source_id}`,
      "Evidence:", row.evidence_quote, "", "Acceptance criteria:",
      ...row.acceptance_criteria.map(item => `- ${item}`));
    if (row.quality_issues.length) lines.push("Open clarification items:", ...row.quality_issues.map(item => `- ${item}`));
    if (row.validated_at) lines.push(`Signed off by user ${row.validated_by || "Deleted account"} as ${row.reviewer_role} at ${row.validated_at}.`, `Review note: ${row.validation_note}`);
    if (row.story) lines.push("", `#### ${row.story.reference}: ${row.story.title}`, row.story.statement,
      `Traces to ${row.story.requirement_reference}, validated revision ${row.story.validated_revision}.`);
  }
  lines.push("", "## Development handoff", "User stories are ready for delivery-team review. No external development tickets have been created.", "");
  return lines.join("\n");
}
