import type { Metadata } from "next";
import { Suspense } from "react";
import { AgentWorkspace } from "@/components/agent/AgentWorkspace";
import { Skeleton } from "@/components/ui";

export const metadata: Metadata = {
  title: "Agent workspace",
  description: "A focused personal and team ticket workspace for Tickety agents.",
};

export default function AgentPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[70vh] min-h-[640px] w-full rounded-2xl" />}>
      <AgentWorkspace />
    </Suspense>
  );
}
