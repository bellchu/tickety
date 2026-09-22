/** Preserve the question and provenance; AI context still needs human confirmation. */
export function reviewQuestionDraft(question: string, finding: string, snapshots: { reference: string; revision: number }[]): string {
  const header = `AI review · ${snapshots.map(item => `${item.reference} r${item.revision}`).join(", ")}\nQuestion: ${question}\n\nContext to confirm: `;
  const remaining = 4000 - Array.from(header).length;
  const context = Array.from(finding);
  if (context.length <= remaining) return header + finding;
  const marker = "… [context shortened]";
  return header + context.slice(0, Math.max(0, remaining - Array.from(marker).length)).join("") + marker;
}
