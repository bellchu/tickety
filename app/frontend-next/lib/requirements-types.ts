export type SourceKind = "document" | "email" | "sop" | "transcript";
export type RequirementPriority = "must" | "should" | "could" | "wont";

export interface RequirementWorkspace {
  id: string;
  title: string;
  objective: string;
  request_type: "approved_project" | "enhancement";
  owner_id: string | null;
  created_at: string;
}

export interface RequirementSource {
  id: string;
  title: string;
  kind: SourceKind;
  content_sha256: string;
  content?: string;
  created_at: string;
}

export interface RequirementDraft {
  source_id: string;
  title: string;
  actor: string;
  action: string;
  benefit: string;
  evidence_quote: string;
  acceptance_criteria: string[];
  priority: RequirementPriority;
}

export interface UserStory {
  reference: string;
  requirement_reference: string;
  title: string;
  statement: string;
  acceptance_criteria: string[];
  requirement_id: string;
  source_id: string;
  validated_revision: number;
  priority: RequirementPriority;
}

export interface BusinessRequirement extends RequirementDraft {
  id: string;
  reference: string;
  revision: number;
  status: "draft" | "validated";
  validated_by: string | null;
  validated_at: string | null;
  reviewer_role: string | null;
  validation_note: string | null;
  quality_issues: string[];
  story: UserStory | null;
}

export interface RequirementWorkspaceDetail {
  workspace: RequirementWorkspace;
  sources: RequirementSource[];
  requirements: BusinessRequirement[];
}

export interface RequirementCandidate extends Omit<RequirementDraft, "source_id"> {
  assumptions: string[];
}

export interface GatherSuggestions {
  source_id: string;
  model: string;
  source_truncated: boolean;
  discarded_candidates: number;
  candidates: RequirementCandidate[];
  questions: string[];
}

export interface RequirementAssistance {
  model: string;
  mode: "review" | "story";
  base_revision: number;
  input_truncated: boolean;
  suggestions: {
    findings?: { category: string; finding: string; question: string }[];
    questions?: string[];
    actor?: string;
    action?: string;
    benefit?: string;
    acceptance_criteria?: string[];
    assumptions?: string[];
  };
}
