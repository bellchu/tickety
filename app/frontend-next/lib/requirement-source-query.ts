import type { RequirementSource } from "./requirements-types";

export function requirementSourceQuery(userId: string, workspaceId: string, sourceId: string, load: (workspaceId: string, sourceId: string) => Promise<RequirementSource>, visible = true) {
  return {
    queryKey: ["requirement-source", userId, workspaceId, sourceId],
    queryFn: () => load(workspaceId, sourceId),
    enabled: visible && Boolean(sourceId),
    // Saved evidence is immutable. Keep normal inactive-cache eviction.
    staleTime: Infinity,
  };
}
