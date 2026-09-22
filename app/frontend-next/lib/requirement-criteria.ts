import { requirementTextBounds } from "./requirement-text";

/** Match the server's per-criterion bounds while allowing incomplete drafts. */
export function parseRequirementCriteria(entries: string[]): { criteria: string[]; issue: string | null } {
  const numbered = entries.map((value, index) => ({ value: value.trim(), number: index + 1 })).filter(item => item.value);
  const criteria = numbered.map(item => item.value);
  if (criteria.length > 20) return { criteria, issue: `There are ${criteria.length} acceptance criteria. Keep at most 20.` };
  for (const item of numbered) {
    const { length, valid } = requirementTextBounds(item.value, 1000);
    if (item.value.includes("\0")) return { criteria, issue: `Criterion ${item.number} contains an unsupported control character. Remove it before saving.` };
    if (!valid) return { criteria, issue: `Criterion ${item.number} has ${length} characters. Each criterion needs 10–1,000 characters after trimming spaces.` };
  }
  return { criteria, issue: null };
}
