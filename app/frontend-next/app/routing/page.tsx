import { Route } from "lucide-react";
import { AIRoutingSettings } from "@/components/settings/AIRoutingSettings";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";

export default function RoutingPage() {
  return (
    <PageFrame width="wide" className="pb-10">
      <PageHeader
        eyebrow="Operations intelligence"
        icon={<Route className="h-4 w-4" />}
        title="Routing & triage"
        description="Control the automatic newest-first AI lane, run bounded historical batches, and manage resolver rules and mappings in one focused workspace."
        meta="AI recommendations remain advisory; provider assignments are never changed from this page."
      />
      <AIRoutingSettings />
    </PageFrame>
  );
}
