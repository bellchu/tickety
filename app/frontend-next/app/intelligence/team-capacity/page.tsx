import type { Metadata } from "next";
import { IntelligenceWorkspace } from "@/components/intelligence/IntelligenceWorkspace";

export const metadata: Metadata = { title: "Team capacity · OPS Tower" };

export default function TeamCapacityPage() {
  return <IntelligenceWorkspace view="team-capacity" />;
}
