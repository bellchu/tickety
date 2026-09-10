import type { Metadata } from "next";
import { IntelligenceWorkspace } from "@/components/intelligence/IntelligenceWorkspace";

export const metadata: Metadata = { title: "Automation discovery · OPS Tower" };

export default function AutomationDiscoveryPage() {
  return <IntelligenceWorkspace view="automation-discovery" />;
}
