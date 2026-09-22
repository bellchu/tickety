import type { QueryClient } from "@tanstack/react-query";
import type { BusinessRequirement, RequirementDraft, SourceKind } from "./requirements-types";

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
  rememberDraft(client, [...prefix, userId, workspaceId], draft);
}

function rememberDraft(client: QueryClient, queryKey: string[], draft: RequirementEditorDraft | RequirementSourceDraft | RequirementDecisionDraft | null) {
  if (!draft) { client.removeQueries({ queryKey, exact: true }); return; }
  // These are tab-memory drafts, never fetched or persisted to browser storage.
  // Keep them until saved/discarded or the authenticated query cache is cleared.
  client.setQueryDefaults(prefix, { gcTime: Infinity, staleTime: Infinity });
  client.setQueryData(queryKey, draft);
}

export function hasRequirementEditorDrafts(client: QueryClient): boolean {
  return client.getQueryCache().findAll({ queryKey: prefix }).some(query => Boolean(query.state.data));
}

export interface RequirementSourceDraft {
  title: string;
  kind: SourceKind;
  content: string;
  warnings: string[];
}

export function readRequirementSourceDraft(client: QueryClient, userId: string, workspaceId: string) {
  return client.getQueryData<RequirementSourceDraft>([...prefix, userId, workspaceId, "source"]);
}

export function rememberRequirementSourceDraft(client: QueryClient, userId: string, workspaceId: string, draft: RequirementSourceDraft | null) {
  rememberDraft(client, [...prefix, userId, workspaceId, "source"], draft);
}

export interface RequirementDecisionDraft {
  question: string;
  owner: string;
  requirementId: string;
  blocking: boolean;
  resolving: string;
  resolution: string;
}
export function readRequirementDecisionDraft(client: QueryClient, userId: string, workspaceId: string) {
  return client.getQueryData<RequirementDecisionDraft>([...prefix, userId, workspaceId, "decision"]);
}
export function rememberRequirementDecisionDraft(client: QueryClient, userId: string, workspaceId: string, draft: RequirementDecisionDraft | null) {
  rememberDraft(client, [...prefix, userId, workspaceId, "decision"], draft);
}
