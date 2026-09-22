import type { ReactNode } from "react";

export const inputStyle = "mt-1 w-full rounded-lg border border-linen-500 bg-white px-3 py-2 text-sm text-ink-700 focus:outline-none focus:ring-2 focus:ring-clay-400";
export const panelStyle = "rounded-xl border border-linen-400 bg-white p-5 shadow-sm";
export { requirementPriorityLabels as priorities } from "@/lib/requirement-workspace";
export { requirementSourceKindLabels as kinds } from "@/lib/requirement-workspace";
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-sm font-medium text-ink-600">{label}{children}</label>;
}
