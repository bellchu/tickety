import type { Metadata } from "next";
import { IntelligenceWorkspace } from "@/components/intelligence/IntelligenceWorkspace";

export const metadata: Metadata = { title: "Service assurance · OPS Tower" };

export default function ServiceAssurancePage() {
  return <IntelligenceWorkspace view="service-assurance" />;
}
