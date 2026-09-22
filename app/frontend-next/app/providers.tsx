"use client";

import { useEffect } from "react";
import { hasRequirementEditorDrafts } from "@/lib/requirement-editor-cache";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (hasRequirementEditorDrafts(queryClient)) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);
  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}
