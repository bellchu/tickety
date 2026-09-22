import type { QueryClient } from "@tanstack/react-query";

/** Saved work can change counts on every cached search/page of the overview. */
export function invalidateRequirementOverviews(client: QueryClient) {
  return client.invalidateQueries({ queryKey: ["requirement-workspaces"], refetchType: "none" });
}
