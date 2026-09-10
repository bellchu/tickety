import type { Metadata } from "next";
import { IntelligenceWorkspace } from "@/components/intelligence/IntelligenceWorkspace";

export const metadata: Metadata = { title: "Demand patterns · OPS Tower" };

export default function DemandPatternsPage() {
  return <IntelligenceWorkspace view="demand-patterns" />;
}
