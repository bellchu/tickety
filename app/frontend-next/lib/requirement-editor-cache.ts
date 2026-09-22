import type { QueryClient } from "@tanstack/react-query";
import type { BusinessRequirement, RequirementDraft } from "./requirements-types";

export interface RequirementEditorDraft {
  draft: RequirementDraft;
  criteria: string;
  baseline: string;
  assumptions: string[];
  editing?: BusinessRequirement;
  showForm: boolean;
  reviewing: BusinessRequirement | null;
  reviewerRole: string;
  reviewNote: string;
}

const prefix = ["requirement-editor-draft"];
export function readRequirementEditor(client: QueryClient, userId: string, workspaceId: string) {
  return client.getQueryData<RequirementEditorDraft>([...prefix, userId, workspaceId]);
}

export function rememberRequirementEditor(client: QueryClient, userId: string, workspaceId: string, draft: RequirementEditorDraft | null) {
  const queryKey = [...prefix, userId, workspaceId];
  if (!draft) { client.removeQueries({ queryKey, exact: true }); return; }
  // These are tab-memory drafts, never fetched or persisted to browser storage.
  // Keep them until saved/discarded or the authenticated query cache is cleared.
  client.setQueryDefaults(prefix, { gcTime: Infinity, staleTime: Infinity });
  client.setQueryData(queryKey, draft);
}

export function hasRequirementEditorDrafts(client: QueryClient): boolean {
  return client.getQueryCache().findAll({ queryKey: prefix }).some(query => Boolean(query.state.data));
}
