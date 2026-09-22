/** Match the server's per-criterion bounds while allowing incomplete drafts. */
export function parseRequirementCriteria(text: string): { criteria: string[]; issue: string | null } {
  const lines = text.split("\n").map((value, index) => ({ value: value.trim(), line: index + 1 })).filter(item => item.value);
  const criteria = lines.map(item => item.value);
  if (criteria.length > 20) return { criteria, issue: `There are ${criteria.length} acceptance criteria. Keep at most 20, one per line.` };
  for (const item of lines) {
    const length = [...item.value].length;
    if (length < 10 || length > 1000) return { criteria, issue: `Line ${item.line} has ${length} characters. Each criterion needs 10–1,000 characters after trimming spaces.` };
  }
  return { criteria, issue: null };
}
