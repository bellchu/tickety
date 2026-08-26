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
    <Suspense fallback={(
      <div aria-busy="true" aria-label="Loading agent workspace">
        <span className="sr-only" role="status">Loading agent workspace…</span>
        <Skeleton className="h-[70vh] min-h-[28rem] w-full rounded-2xl sm:min-h-[40rem]" />
      </div>
    )}>
      <AgentWorkspace />
    </Suspense>
  );
}
