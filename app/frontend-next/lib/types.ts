export interface Ticket {
  id: string;
  subject: string;
  description: string;
  reporter: string;
  requester_id: string | null;
  requester_name: string | null;
  requester_email: string | null;
  requester_title: string | null;
  status: string;
  priority: string;
  sentiment: string | null;
  category: string | null;
  mood: string | null;
  complexity: number;
  ai_reasoning: string | null;
  suggested_response: string | null;
  ai_source_hash: string | null;
  ai_pipeline_version: string | null;
  ai_model: string | null;
  ai_status: string | null;
  ai_claim_id: string | null;
  ai_lease_expires_at: string | null;
  ai_attempts: number;
  ai_next_attempt_at: string | null;
  ai_requested_artifacts: string | null;
  ai_started_at: string | null;
  ai_generated_at: string | null;
  ai_error: string | null;
  ai_synthetic: boolean;
  ai_suggested_priority: string | null;
  ai_suggested_category: string | null;
  ai_suggested_team: string | null;
  ai_secondary_team: ResolverGroup | null;
  ai_routing_confidence: number | null;
  ai_routing_scope: "single_user" | "multiple_users" | "service_wide" | "unknown" | null;
  ai_affected_service: string | null;
  ai_failure_domain: string | null;
  ai_routing_reason: string | null;
  recommended_team: string;
  recommended_team_basis: "source_group" | "ai_team" | "ai_category" | "source_category" | "not_applicable" | "unrouted_review";
  routing_status: "source_group_assignment" | "ai_team_recommendation" | "legacy_ai_category" | "source_category_suggestion" | "not_applicable" | "unrouted_review";
  routing_abstention_reason: "missing_ai_category" | "unsupported_ai_category" | "untrusted_ai_status" | null;
  routing_catalog_validated: boolean;
  ticket_type: string;
  impact: string | null;
  urgency: string | null;
  workflow_status: string | null;
  ai_review_state: string | null;
  assignee_id: string | null;
  assignee_name: string | null;
  service_id: string | null;
  asset_id: string | null;
  response_due_at: string | null;
  resolution_due_at: string | null;
  due_by: string | null;
  sla_paused_at: string | null;
  sla_paused_seconds: number;
  tags: string | null;
  external_source: string | null;
  binding_id: string;
  external_id: string | null;
  external_url: string | null;
  external_status: string | null;
  external_assignee_id: string | null;
  external_assignee_name: string | null;
  external_workspace_id: string | null;
  external_updated_at: string | null;
  external_description_html: string | null;
  external_conversation_updated_at: string | null;
  external_created_at: string | null;
  external_resolved_at: string | null;
  external_due_by: string | null;
  external_fr_due_by: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  points_awarded: number;
  created_at: string | null;
  updated_at: string | null;
  last_communication_at: string | null;
  escalation_risk: number;
  summary: string | null;
  recommended_solution: string | null;
}

export interface TicketCreateInput {
  subject: string;
  description: string;
  reporter: string;
  priority: string;
  ticket_type?: "incident" | "request";
  impact?: string | null;
  urgency?: string | null;
  service_id?: string | null;
  asset_id?: string | null;
}

export type TicketListSort = "newest" | "oldest" | "priority" | "queue" | "updated" | "complexity";

export interface TicketListParams {
  status?: string;
  priority?: string;
  assigneeId?: string;
  category?: string;
  search?: string;
  sort?: TicketListSort;
  limit?: number;
  offset?: number;
}

export interface TicketPage {
  tickets: Ticket[];
  limit: number;
  offset: number;
  hasMore: boolean;
}

export interface DashboardSummary {
  total_tickets: number;
  active_tickets: number;
  inactive_tickets: number;
  p1_active: number;
  escalated_active: number;
  unassigned_active: number;
}

export type AgentWorkspaceScope = "mine" | "team";
export type AgentWorkspaceFolder =
  | "inbox"
  | "needs_reply"
  | "sla_at_risk"
  | "starred"
  | "follow_up"
  | "closed"
  | "unassigned";

export interface AgentWorkspaceIdentity {
  link_id: number;
  external_user_id: string;
  external_id: string;
  name: string;
  email: string | null;
  binding_id: string;
  provider: string;
}

export interface AgentWorkspaceTeam {
  id: string;
  external_id: string;
  name: string;
  workspace_id: string | null;
  membership_kind: "member" | "observer";
  ticket_count: number;
  unassigned_count: number;
}

export interface AgentWorkspaceBootstrap {
  identity: AgentWorkspaceIdentity | null;
  teams: AgentWorkspaceTeam[];
  counts: Record<string, number>;
}

export interface AgentWorkspaceTicket extends Ticket {
  assignment_scope: AgentWorkspaceScope;
  team_id: string | null;
  team_name: string | null;
  is_unread: boolean;
  is_starred: boolean;
  follow_up_at: string | null;
  needs_reply: boolean;
  sla_at_risk: boolean;
  next_best_score: number;
  next_best_reasons: string[];
}

export interface AgentWorkspaceTicketParams {
  scope?: AgentWorkspaceScope;
  teamId?: string;
  ticketId?: string;
  folder?: AgentWorkspaceFolder;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface AgentTicketStateUpdate {
  mark_seen?: boolean;
  starred?: boolean;
  follow_up_at?: string;
  clear_follow_up?: boolean;
}

export interface RelatedTicketItem {
  ticket_id: string;
  subject: string;
  status: string;
  priority: string;
  category: string | null;
  score: number;
  match_method: string;
}

export interface RelatedTicketsResponse {
  ticket_id: string;
  available: boolean;
  match_method: string;
  items: RelatedTicketItem[];
}

export interface User {
  id: string;
  name: string;
  email: string | null;
  avatar: string | null;
  title: string | null;
  impact_points: number;
  tier: number;
  momentum: number;
  last_action_at: string | null;
}

export interface UserSummary {
  id: string;
  name: string;
  avatar: string | null;
  title: string | null;
  impact_points: number;
  tier: number;
  momentum: number;
  tickets_resolved: number;
  rank: number | null;
}

export interface Recognition {
  id: number;
  user_id: string;
  recognition_key: string;
  unlocked_at: string;
  ticket_id: string | null;
  display_name: string | null;
  description: string | null;
  icon: string | null;
}

export interface SyncStatus {
  provider: string;
  binding_id: string | null;
  last_synced_at: string | null;
  automatic_ai_enabled: boolean;
  automatic_ai_generation: number | null;
  automatic_ai_cutover_at: string | null;
  automatic_ai_enabled_at: string | null;
  automatic_ai_paused_at: string | null;
  automatic_ai_lookback_days: number;
  last_status: string;
  last_error: string | null;
  total_synced: number;
  automatic_fetch_days: number;
  recent_since_at: string | null;
  recent_cycle_started_at: string | null;
  recent_page: number;
  recent_workspace_index: number;
  recent_completed_at: string | null;
  provider_timestamp_repair_pending: boolean;
  provider_timestamp_repair_days: number;
  provider_timestamp_repair_processed: number;
  background_history_page: number;
  background_history_workspace_index: number;
  background_history_complete: boolean;
  background_history_processed: number;
  background_history_started_at: string | null;
  background_history_through_at: string | null;
  history_page: number;
  history_workspace_index: number;
  history_complete: boolean;
  history_processed: number;
  history_since_at: string | null;
  history_until_at: string | null;
  history_requested_at: string | null;
  conversations_processed: number;
  run_started_at: string | null;
  run_finished_at: string | null;
  next_retry_at: string | null;
  rate_limit_total: number | null;
  rate_limit_remaining: number | null;
  rate_limit_used: number | null;
  last_batch_new: number;
  last_batch_updated: number;
  last_batch_errors: number;
  local_ticket_count: number;
  sync_interval_seconds: number;
  recent_pages_per_sync: number;
  history_pages_per_sync: number;
  conversations_per_sync: number;
  attachments_per_sync: number;
  attachment_storage_configured: boolean;
  attachment_pending: number;
  attachment_stored: number;
  attachment_errors: number;
}

export interface AutomaticAIAdmissionResponse {
  binding_id: string;
  provider: string;
  automatic_ai_enabled: boolean;
  automatic_ai_generation: number;
  automatic_ai_cutover_at: string;
  automatic_ai_enabled_at?: string | null;
  automatic_ai_paused_at: string | null;
  automatic_ai_lookback_days: number;
  revoked_requests?: number;
}

export type AITaskView = "all" | "active" | "retry_scheduled" | "attention" | "completed" | "not_analyzed" | "not_applicable";

export type AITaskLifecycle =
  | "not_analyzed"
  | "not_applicable"
  | "queued"
  | "retry_scheduled"
  | "running"
  | "lease_expired"
  | "completed"
  | "partial"
  | "stale"
  | "failed"
  | "dead_letter"
  | "paused"
  | "unknown";

export interface AIAutomationFeatureStatus {
  key: string;
  label: string;
  enabled: boolean;
}

export interface AIQueueStatusSummary {
  total_tickets: number;
  not_analyzed: number;
  not_applicable: number;
  queued: number;
  queued_ready: number;
  retry_scheduled: number;
  running: number;
  running_active: number;
  lease_expired: number;
  completed: number;
  partial: number;
  stale: number;
  failed: number;
  dead_letter: number;
  paused: number;
  attention: number;
  oldest_queued_at: string | null;
}

export interface AITaskStatusItem {
  ticket_id: string;
  subject: string;
  ticket_status: string;
  priority: string;
  source: string;
  external_id: string | null;
  ai_status: string | null;
  lifecycle: AITaskLifecycle;
  requested_artifacts: string[];
  attempts: number;
  model: string | null;
  synthetic: boolean;
  started_at: string | null;
  generated_at: string | null;
  next_attempt_at: string | null;
  lease_expires_at: string | null;
  error_code: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AILLMCallStatusItem {
  id: number;
  provider: string;
  model: string;
  task: string;
  status: string;
  attempts: number;
  latency_ms: number;
  total_tokens: number;
  synthetic: boolean;
  error_code: string | null;
  http_status: number | null;
  failure_kind: string | null;
  retry_after_seconds: number | null;
  dispatched: boolean;
  estimated_tokens: number;
  created_at: string;
}

export interface AIStatusResponse {
  generated_at: string;
  automation: AIAutomationFeatureStatus[];
  active_integration_bindings: number;
  automatic_ai_bindings: number;
  active_routing_backlog_enabled: boolean;
  queue: AIQueueStatusSummary;
  view: AITaskView;
  search: string;
  tasks: AITaskStatusItem[];
  total_tasks: number;
  limit: number;
  offset: number;
  provider_cooldown: {
    provider: string;
    reason: string;
    retry_at: string;
  } | null;
  recent_calls: AILLMCallStatusItem[];
  calls_24h: {
    calls: number;
    successful: number;
    failed_attempts: number;
    deferred: number;
    total_tokens: number;
    average_latency_ms: number;
    last_call_at: string | null;
  };
}

export interface AIRetryQueueActionResponse {
  action: "clear" | "retry_all_now" | "retry_now" | "reschedule";
  affected: number;
  ticket_id: string | null;
  scheduled_at: string | null;
  dispatch_blocked_until: string | null;
}

export interface ReadinessStatus {
  status: "ready" | "not_ready";
  checks: Record<string, "ok" | "unavailable">;
}

export interface TicketIntelligenceStatus {
  vector_store_ready: boolean;
  embedding_enabled: boolean;
  embedding_model: string;
  embedding_dimensions: number;
  documents: number;
  embedded_documents: number;
  stale_documents: number;
  legacy_ticket_documents: number;
  missing_ticket_documents: number;
  missing_comment_documents: number;
  missing_kb_documents: number;
  rag_v2: {
    ready: boolean;
    read_enabled: boolean;
    write_enabled: boolean;
    chunks: number;
    queued: number;
    running: number;
    ready_chunks: number;
    dead_letter: number;
    indexing_errors: number;
    stale_identity_chunks: number;
    oldest_queue_age_seconds: number;
  };
}

export type OperationalDiagnosticArea = "application" | "ai" | "sync" | "retrieval" | "oauth";

export interface OperationalDiagnosticsResponse {
  area: OperationalDiagnosticArea;
  generated_at: string;
  entries: Array<{
    severity: "info" | "warning" | "error";
    source: string;
    message: string;
    timestamp: string | null;
  }>;
  truncated: boolean;
}

export interface TriageResult {
  ticket_id: string;
  sentiment: string;
  category: string;
  priority: string;
  mood: string;
  complexity: number;
  action: string;
  recommended_team: string;
  reasoning: string;
  suggested_response: string | null;
  escalation_risk: number;
}

export interface PointsNotification {
  ticket_id: string;
  ticket_subject: string;
  user_id: string;
  user_name: string;
  points_earned: number;
  new_total: number;
  new_tier: number;
  tier_promoted: boolean;
  new_momentum: number;
  recognitions_unlocked: Recognition[];
}

export interface TriageStep {
  step: string;
  label: string;
  status: "pending" | "active" | "done" | "error";
}

export interface Settings {
  APP_MODE: string;
  TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED: string;
  CORS_ALLOW_ORIGINS: string;
  COOKIE_SECURE: string;
  COOKIE_SAMESITE: string;
  FOUNDRY_API_KEY: string;
  FOUNDRY_API_BASE: string;
  FOUNDRY_AUTH_METHOD: string;
  CUSTOM_API_KEY: string;
  CUSTOM_API_BASE: string;
  DEFAULT_MODEL: string;
  TICKET_RAG_SCOPE_KEY: string;
  TICKET_RAG_V2_SCOPE_ALLOWLIST: string;
  TICKET_RAG_V2_WRITE_ENABLED: string;
  TICKET_RAG_V2_WORKER_ENABLED: string;
  TICKET_RAG_V2_READ_ENABLED: string;
  TICKET_RAG_CHUNK_TARGET_TOKENS: string;
  TICKET_RAG_CHUNK_MAX_TOKENS: string;
  TICKET_RAG_CHUNK_OVERLAP_TOKENS: string;
  TICKET_RAG_EMBED_BATCH_SIZE: string;
  TICKET_RAG_EMBED_LEASE_SECONDS: string;
  TICKET_RAG_WORKER_POLL_SECONDS: string;
  TICKET_RAG_QUERY_CACHE_TTL_SECONDS: string;
  TICKET_RAG_QUERY_CACHE_MAX_ROWS: string;
  TICKET_RAG_SNAPSHOT_TTL_SECONDS: string;
  DATABASE_URL: string;
  ITSM_PROVIDER: string;
  FRESHSERVICE_DOMAIN: string;
  FRESHWORKS_ORG_DOMAIN: string;
  FRESHSERVICE_API_KEY: string;
  FRESHSERVICE_WORKSPACE_ID: string;
  FRESHSERVICE_TICKET_INCLUDES: string;
  FRESHSERVICE_AGENT_STATE: string;
  FRESHSERVICE_MIN_INTERVAL_SECONDS: string;
  FRESHSERVICE_RATE_LIMIT_RESERVE: string;
  FRESHSERVICE_RECENT_PAGES_PER_SYNC: string;
  FRESHSERVICE_HISTORY_PAGES_PER_SYNC: string;
  FRESHSERVICE_CONVERSATIONS_PER_SYNC: string;
  FRESHSERVICE_ATTACHMENTS_PER_SYNC: string;
  ATTACHMENT_STORAGE_PROVIDER: string;
  ATTACHMENT_MAX_BYTES: string;
  AZURE_STORAGE_ACCOUNT_URL: string;
  AZURE_STORAGE_CONTAINER: string;
  FRESHSERVICE_OAUTH_CLIENT_ID: string;
  FRESHSERVICE_OAUTH_CLIENT_SECRET: string;
  FRESHSERVICE_OAUTH_REDIRECT_URI: string;
  FRESHSERVICE_OAUTH_SCOPES: string;
  JIRA_BASE_URL: string;
  JIRA_EMAIL: string;
  JIRA_API_TOKEN: string;
  JIRA_PROJECT_KEY: string;
  JIRA_ISSUE_TYPE: string;
  WEBHOOK_SECRET: string;
  SYNC_INTERVAL_SECONDS: string;
  NEXT_PUBLIC_API_URL: string;
  NEXT_PUBLIC_WS_URL: string;
  FRONTEND_URL: string;
  SENDGRID_API_KEY: string;
  SENDGRID_FROM_EMAIL: string;
  SENDGRID_FROM_NAME: string;
  SENDGRID_REPLY_TO_EMAIL: string;
  EMAIL_SENDS_PER_MINUTE: string;
  EMAIL_RECIPIENTS_PER_DAY: string;
  SLA_P1_HOURS: string;
  SLA_P2_HOURS: string;
  SLA_P3_HOURS: string;
  SLA_P4_HOURS: string;
  ORG_NAME: string;
  ORG_LOGO_URL: string;
  ORG_PRIMARY_COLOR: string;
  AUTO_TRIAGE_ENABLED: string;
  AUTO_SUMMARIZE_ENABLED: string;
  AUTO_ROUTE_ENABLED: string;
  AUTO_RESOLVE_ENABLED: string;
  AUTO_SYSTEMIC_ENABLED: string;
  LOGIN_REQUIRED: string;
  SSO_ENABLED: string;
  SSO_PROVIDER: string;
  SSO_ENTRA_TENANT_ID: string;
  SSO_OKTA_DOMAIN: string;
  SSO_OKTA_AUTH_SERVER_ID: string;
  SSO_CLIENT_ID: string;
  SSO_CLIENT_SECRET: string;
  SSO_DISCOVERY_URL: string;
  SSO_REDIRECT_URI: string;
  SSO_ALLOWED_DOMAINS: string;
  SSO_ALLOWED_GROUP_IDS: string;
  SSO_AUTO_PROVISION: string;
  [key: string]: string | boolean;
}

export interface LlmModelOption {
  id: string;
  label: string;
}

export interface LlmEnvKey {
  key: string;
  label: string;
  secret: boolean;
  placeholder: string;
  is_set: boolean;
}

export interface LlmProvider {
  label: string;
  models: LlmModelOption[];
  free_text_model: boolean;
  model_hint?: string | null;
  env_keys: LlmEnvKey[];
}

export interface LlmCatalog {
  current_provider: string;
  [providerId: string]: string | LlmProvider | undefined;
}

// ── Intelligence (SupportLogic-style ambient agents) ─────────────

export interface SlaStatusItem {
  ticket_id: string;
  subject: string;
  priority: string;
  sla_target_hours: number;
  elapsed_hours: number;
  remaining_hours: number;
  overdue_hours: number;
  due_at: string;
  target_source: "provider_due_at" | "priority_policy";
  status: "on_track" | "at_risk" | "breached";
  is_open: boolean;
}

export interface IntelSlaResponse {
  generated_at: string;
  window_days: number;
  count: number;
  analyzed_tickets: number;
  truncated: boolean;
  items: SlaStatusItem[];
}

export interface PrioritizedTicket {
  ticket_id: string;
  subject: string;
  priority: string;
  sentiment: string | null;
  category: string | null;
  complexity: number;
  escalation_risk: number;
  age_hours: number;
  score: number;
}

export interface IntelPrioritizeResponse {
  generated_at: string;
  window_days: number;
  backlog_size: number;
  analyzed_tickets: number;
  truncated: boolean;
  ranked: PrioritizedTicket[];
}

export interface IntelAlertsResponse {
  generated_at: string;
  window_days: number;
  total_open_tickets: number;
  analyzed_tickets: number;
  truncated: boolean;
  summary: {
    escalation_prone: number;
    sla_at_risk: number;
    sla_breached: number;
  };
  escalation_prone: Array<{ ticket_id: string; subject: string; risk: number; priority: string }>;
  sla_at_risk: SlaStatusItem[];
  sla_breached: SlaStatusItem[];
}

export interface IntelTrendsResponse {
  generated_at: string;
  window_days: number;
  total_tickets: number;
  analyzed_tickets: number;
  pattern_evidence_tickets: number;
  truncated: boolean;
  by_category: Record<string, number>;
  by_sentiment: Record<string, number>;
  by_status: Record<string, number>;
  top_terms: Array<[string, number]>;
}

export interface AccountHealth {
  generated_at: string;
  window_days: number;
  reporter: string;
  health_score: number | null;
  churn_risk: "low" | "medium" | "high" | "unknown";
  open: number;
  resolved: number;
  total: number;
  avg_escalation_risk: number;
  negative_sentiment_ratio: number;
  analyzed_tickets: number;
  truncated: boolean;
}

export type ResolverGroup =
  | "SERVICE_DESK"
  | "ENDPOINT_SUPPORT"
  | "IDENTITY_ACCESS"
  | "NETWORK_OPERATIONS"
  | "INFRASTRUCTURE_OPERATIONS"
  | "CLOUD_PLATFORM"
  | "SECURITY_OPERATIONS"
  | "BUSINESS_APPLICATIONS"
  | "APPLICATION_OPERATIONS"
  | "DATA_SERVICES"
  | "INTEGRATION_SERVICES"
  | "AUTOMATION_SERVICES"
  | "SOFTWARE_ENGINEERING"
  | "SERVICE_DELIVERY";

export interface RouteRecommendation {
  primary_group: ResolverGroup;
  secondary_group: ResolverGroup | null;
  confidence: number;
  scope: "single_user" | "multiple_users" | "service_wide" | "unknown";
  affected_service: string;
  failure_domain: string;
  reason: string;
}

export interface RoutingCatalogScope {
  binding_id: string;
  provider: string;
  workspace_id: string | null;
}

export interface RoutingCatalogRecommendation {
  resolver_code: ResolverGroup;
  scope: RoutingCatalogScope;
  trusted_ticket_count: number;
  membership_eligible_ticket_count: number;
  unambiguous_ticket_count: number;
  ambiguous_membership_ticket_count: number;
  provider_group_id: string;
  provider_group_name: string;
  evidence_ticket_count: number;
  direct_assignment_ticket_count: number;
  sole_membership_ticket_count: number;
  distinct_agent_count: number;
  candidate_group_count: number;
  runner_up_ticket_count: number;
  group_share: number;
  confidence: number;
  runner_up_lead: number;
  evidence_coverage: number;
  advisory_only: true;
  reason: string;
}

export interface RoutingCatalogScopedGap {
  resolver_code: ResolverGroup;
  scope: RoutingCatalogScope;
  trusted_ticket_count: number;
  membership_eligible_ticket_count: number;
  unambiguous_ticket_count: number;
  ambiguous_membership_ticket_count: number;
  reason:
    | "no_trusted_history"
    | "no_unambiguous_membership_evidence"
    | "insufficient_evidence_coverage"
    | "insufficient_ticket_sample"
    | "insufficient_agent_diversity"
    | "low_dominance"
    | "ambiguous_lead"
    | "low_sample_adjusted_confidence"
    | "catalog_group_unavailable"
    | "evidence_truncated";
  leading_ticket_count: number;
  leading_distinct_agent_count: number;
  candidate_group_count: number;
}

export interface RoutingCatalogRecommendationsResponse {
  schema_version: "1";
  window_days: number;
  generated_at: string;
  window_start_at: string;
  advisory_only: true;
  mapping_applied: false;
  no_mapping_applied: true;
  thresholds: {
    minimum_group_tickets: number;
    minimum_distinct_agents: number;
    minimum_top_share: number;
    minimum_runner_up_lead: number;
    minimum_evidence_coverage: number;
    minimum_confidence: number;
    history_ticket_limit: number;
  };
  coverage: {
    candidate_ticket_count: number;
    analyzed_ticket_count: number;
    trusted_route_ticket_count: number;
    membership_eligible_ticket_count: number;
    unambiguous_ticket_count: number;
    ambiguous_membership_ticket_count: number;
    without_membership_evidence_ticket_count: number;
    excluded_ambiguous_or_unmatched_ticket_count: number;
    history_truncated: boolean;
    catalog_scopes_truncated: boolean;
  };
  ready: boolean;
  scopes: RoutingCatalogScope[];
  recommendations: RoutingCatalogRecommendation[];
  scoped_gaps: RoutingCatalogScopedGap[];
  unmapped_codes: ResolverGroup[];
  unmapped_codes_scope: RoutingCatalogScope | null;
}

export interface RoutingTriageStatus {
  schema_version: "1";
  generated_at: string;
  advisory_only: true;
  catalog_mapping_status: "pending";
  catalog_mapping_write_available: false;
  automation_controls_editable: boolean;
  rule_controls_editable: boolean;
  triage_queue_action_available: true;
  directory_people_read_enabled: boolean;
  directory_people_write_enabled: boolean;
  remote_agent_team_eligible: boolean;
  remote_requester_team_eligible: boolean;
  auto_triage: { configured: boolean; effective: boolean };
  auto_routing: { configured: boolean; effective: boolean };
  resolver_groups: ResolverGroup[];
}

export type AIBatchScope =
  | "four_weeks"
  | "three_months"
  | "six_months"
  | "one_year"
  | "all_time";

export type AIBatchMode = "routing_triage" | "full_analysis";

export interface AIBatchPreview {
  scope: AIBatchScope;
  mode: AIBatchMode;
  cutoff_at: string | null;
  eligible_tickets: number;
  estimated_provider_calls: number;
  estimated_tokens: number;
  estimated_tokens_per_artifact: Record<string, number>;
  missing_by_artifact: Record<string, number>;
  warning: string | null;
  requires_cost_acknowledgement: boolean;
}

export interface AIBatchQueueResult extends AIBatchPreview {
  status: "queued";
  queued: number;
  remaining: number;
}

export interface AgentTeamMapping {
  user_id: string;
  user_name: string;
  title: string | null;
  role: "admin" | "supervisor" | "agent";
  is_active: boolean;
  resolver_groups: ResolverGroup[];
  updated_at: string | null;
}

export interface AgentTeamMappingList {
  generated_at: string;
  editable: boolean;
  items: AgentTeamMapping[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface AgentTeamMappingRecommendation {
  subject_key: string;
  person_id: string | null;
  user_id: string | null;
  resolver_group: ResolverGroup;
  confidence: number;
  group_share: number;
  evidence_ticket_count: number;
  total_trusted_ticket_count: number;
  runner_up_ticket_count: number;
  latest_ticket_at: string | null;
  reason: string;
  advisory_only: true;
}

export interface AgentTeamMappingRecommendations {
  schema_version: "1";
  generated_at: string;
  window_start_at: string;
  window_days: number;
  advisory_only: true;
  mapping_applied: false;
  thresholds: {
    minimum_history_tickets: number;
    minimum_top_share: number;
    minimum_runner_up_lead: number;
    minimum_confidence: number;
    history_ticket_limit: number;
  };
  coverage: {
    candidate_ticket_count: number;
    trusted_route_ticket_count: number;
    attributed_ticket_count: number;
    ambiguous_identity_ticket_count: number;
    unmatched_ticket_count: number;
    analyzed_subject_count: number;
    recommended_subject_count: number;
    history_truncated: boolean;
  };
  ready: boolean;
  recommendations: AgentTeamMappingRecommendation[];
}

export type DirectorySourceType =
  | "local"
  | "freshservice_agent"
  | "freshservice_requester";

export interface DirectoryIdentity {
  attachment_id: number;
  external_user_id: string;
  binding_id: string;
  provider: string;
  external_id: string;
  user_type: "agent" | "requester";
  name: string;
  email: string | null;
  title: string | null;
  active: boolean;
  link_method: "source" | "backfill_manual" | "manual" | "auto_exact_email";
  link_state: "active" | "review_required";
  review_reason: string | null;
  fetched_at: string;
}

export interface DirectoryPerson {
  id: string;
  version: number;
  name: string;
  email: string | null;
  title: string | null;
  user_id: string | null;
  role: "admin" | "supervisor" | "agent" | null;
  local_active: boolean;
  remote_active: boolean;
  effective_active: boolean;
  linked: boolean;
  source_types: DirectorySourceType[];
  resolver_groups: ResolverGroup[];
  identities: DirectoryIdentity[];
  updated_at: string;
  last_fetched_at: string | null;
}

export interface DirectoryPersonList {
  generated_at: string;
  editable: boolean;
  items: DirectoryPerson[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface DirectorySyncStatus {
  binding_id: string;
  provider: string;
  status: "idle" | "running" | "success" | "failed" | "partial" | "skipped";
  last_started_at: string | null;
  last_completed_at: string | null;
  last_success_at: string | null;
  stale: boolean;
  stale_after_seconds: number;
  error_kind: string | null;
  counts: Record<string, unknown>;
}

export interface RoutingRule {
  id: number;
  name: string;
  description: string | null;
  enabled: boolean;
  priority: number;
  scope: "single_user" | "multiple_users" | "service_wide" | "unknown" | null;
  service_contains: string | null;
  failure_domain_contains: string | null;
  primary_group: ResolverGroup;
  secondary_group: ResolverGroup | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export type RoutingRuleDraft = Omit<RoutingRule, "id" | "version" | "created_at" | "updated_at">;

export interface RoutingRuleList {
  generated_at: string;
  editable: boolean;
  core_policy_protected: true;
  items: RoutingRule[];
}

export interface WorkloadAgent {
  user_id: string;
  name: string;
  title: string | null;
  source: "provider" | "tickety";
  provider: string | null;
  external_id: string | null;
  group_names: string[];
  tier: number;
  open_tickets: number;
  p1_open_tickets: number;
  total_resolved: number;
  avg_resolution_hours: number;
  impact_points: number;
  load_status: "balanced" | "high" | "overloaded";
}

export interface IntelWorkloadResponse {
  generated_at: string;
  window_days: number;
  workforce_source: "provider" | "tickety";
  assigned_users: number;
  total_open_assignments: number;
  unmapped_open_assignments: number;
  agents: WorkloadAgent[];
  total_users: number;
  analyzed_users: number;
  users_truncated: boolean;
  duration_rows_analyzed: number;
  duration_rows_truncated: boolean;
}

export interface IntelligenceAttentionTicket {
  ticket_id: string;
  subject: string;
  priority: string;
  status: string | null;
  category: string | null;
  assignee_id: string | null;
  is_unassigned: boolean;
  escalation_risk: number;
  priority_score: number;
  age_hours: number;
  dormant_hours: number;
  last_activity_at: string | null;
  sla: SlaStatusItem;
  reasons: string[];
}

export interface IntelligenceStaleTicket {
  ticket_id: string;
  subject: string;
  priority: string;
  status: string | null;
  is_unassigned: boolean;
  last_activity_at: string | null;
  dormant_days: number | null;
}

export interface IntelligenceOverviewResponse {
  generated_at: string;
  posture: "healthy" | "watch" | "critical";
  scope: {
    window_days: number;
    cutoff_at: string;
    activity_basis: "provider_updated_at_or_created_at";
    total_open_tickets: number;
    active_open_tickets: number;
    excluded_stale_open_tickets: number;
    analyzed_tickets: number;
    truncated: boolean;
  };
  posture_metrics: {
    p1_open: number;
    sla_breached: number;
    sla_at_risk: number;
    escalation_prone: number;
    unassigned_open: number;
  };
  flow: {
    created: number;
    resolved: number;
    net_change: number | null;
    measurement_complete: boolean;
    missing_created_timestamps: number;
    missing_resolved_timestamps: number;
  };
  age_bands: {
    under_24h: number;
    one_to_three_days: number;
    four_to_seven_days: number;
    over_seven_days: number;
  };
  attention_queue: IntelligenceAttentionTicket[];
  unassigned_evidence: {
    items: IntelligenceAttentionTicket[];
    items_truncated: boolean;
  };
  stale_backlog: {
    count: number;
    p1_count: number;
    unassigned_count: number;
    oldest_activity_at: string | null;
    items: IntelligenceStaleTicket[];
  };
  freshness: {
    latest_ticket_activity_at: string | null;
  };
}

export interface RoutingQualityAlert {
  ticket_id: string;
  subject: string;
  priority: string;
  severity: "high" | "medium";
  current_group_id: string;
  current_group_name: string;
  directory_name_available: boolean;
  group_profile_team: string;
  recommended_team: string;
  recommendation_source: "trusted_ai_recommendation" | "provider_category_policy" | "trusted_ai_category";
  profile_confidence: number;
  profile_samples: number;
  dormant_hours: number;
  evidence: string[];
  alert_only: true;
}

export interface SupportLevelAssessment {
  ticket_id: string;
  subject: string;
  priority: string;
  recommended_level: 0 | 1 | 2 | 3;
  recommended_name: string;
  recommended_label: string;
  classification_confidence: "high" | "medium";
  basis: string;
  inferred_assigned_level: 0 | 1 | 2 | 3 | null;
  inferred_assigned_name: string | null;
  inferred_from_group_history: boolean;
  inferred_confidence: number;
  inferred_samples: number;
  mismatch: boolean;
  mismatch_direction: "under-tiered" | "over-tiered" | null;
}

export interface CustomerFrictionAlert {
  ticket_id: string;
  subject: string;
  priority: string;
  flagged: true;
  severity: "high" | "medium" | "low";
  frustration_detected: boolean;
  long_response_gap: boolean;
  excessive_back_and_forth: boolean;
  max_response_gap_hours: number;
  current_unanswered_gap_hours: number;
  gap_threshold_hours: number;
  public_message_count: number;
  requester_message_count: number;
  agent_message_count: number;
  unanswered_requester_turns: number;
  conversation_coverage: boolean;
  evidence: string[];
}

export interface ClarificationAlert {
  ticket_id: string;
  subject: string;
  priority: string;
  flagged: true;
  detail_score: number;
  evidence: string[];
  suggested_questions: string[];
}

export interface ServiceQualityResponse {
  generated_at: string;
  window_days: number;
  alert_only: true;
  scope: {
    total_active_tickets: number;
    analyzed_tickets: number;
    truncated: boolean;
    group_profile_period_days: number;
  };
  summary: {
    routing_mismatches: number;
    routing_profiled_tickets: number;
    level_mismatches: number;
    assigned_level_profiled_tickets: number;
    customer_friction: number;
    clarification_needed: number;
  };
  routing_alerts: RoutingQualityAlert[];
  level_distribution: Record<"0" | "1" | "2" | "3", number>;
  level_assessments: SupportLevelAssessment[];
  friction_alerts: CustomerFrictionAlert[];
  clarification_alerts: ClarificationAlert[];
  items_truncated: boolean;
}

export interface SlaMonitoringItem {
  ticket_id: string;
  subject: string;
  priority: string;
  assignee_id: string | null;
  assignee_name: string | null;
  assignee_source: "provider" | "tickety" | null;
  metric: "first_response" | "resolution";
  status: "breached" | "approaching" | "met" | "on_track" | "unmeasured";
  breach_state: "active" | "historical" | null;
  target_source: "provider_due_at" | "priority_policy";
  target_hours: number;
  started_at: string;
  due_at: string;
  completed_at: string | null;
  remaining_hours: number;
  overdue_hours: number;
  is_open: boolean;
}

export interface SlaAssigneeBreachSummary {
  assignee_id: string | null;
  assignee_name: string | null;
  assignee_source: "provider" | "tickety" | null;
  breached_ticket_count: number;
  breached_clock_count: number;
}

export interface SlaMonitoringResponse {
  generated_at: string;
  window_days: number;
  scope: {
    total_tickets: number;
    analyzed_tickets: number;
    truncated: boolean;
    measured_clocks: number;
    unmeasured_clocks: number;
  };
  summary: {
    reactive_breaches: number;
    active_breaches: number;
    historical_breaches: number;
    approaching_breaches: number;
    first_response_breaches: number;
    resolution_breaches: number;
  };
  by_priority: Record<string, {
    first_response: { breached: number; approaching: number };
    resolution: { breached: number; approaching: number };
  }>;
  by_assignee: SlaAssigneeBreachSummary[];
  reactive: SlaMonitoringItem[];
  proactive: SlaMonitoringItem[];
  items_truncated: boolean;
}

export interface SlaAssigneeEvidenceResponse {
  generated_at: string;
  window_days: number;
  assignee_id: string | null;
  assignee_name: string | null;
  assignee_source: "provider" | "tickety" | null;
  breached_ticket_count: number;
  breached_clock_count: number;
  items: SlaMonitoringItem[];
  items_truncated: boolean;
  scope: {
    total_tickets: number;
    analyzed_tickets: number;
    truncated: boolean;
  };
}

export interface LevelZeroStudyItem {
  ticket_id: string;
  subject: string;
  theme: string;
  confidence: "high" | "medium";
  evidence: string;
  resolved_at: string | null;
  priority: string;
}

export interface LevelZeroStudy {
  run_id: string;
  study_type: "level_zero_opportunity";
  period_months: number;
  range_start_at: string;
  range_end_at: string;
  source_data_through_at: string | null;
  created_at: string;
  created_by: string | null;
  method: "complete_unsampled_rule_assessment";
  analyzed_tickets: number;
  eligible_tickets: number;
  high_confidence_tickets: number;
  review_candidates: number;
  estimated_annualized_opportunities: number;
  opportunity_rate: number;
  by_theme: Array<{ theme: string; count: number }>;
  items: LevelZeroStudyItem[];
  items_truncated: boolean;
  safeguards: string[];
}

export interface LevelZeroStudyResponse {
  study: LevelZeroStudy | null;
}

export interface TicketSummary {
  ticket_id: string;
  summary: string;
}

export interface TicketAnalysisResult {
  ticket_id: string;
  triage: TriageResult;
  summary: string | null;
  route: RouteRecommendation | null;
  recommended_solution: RecommendedSolution | null;
  documents_changed: number;
  errors: { step: string; error: string }[];
  cached: boolean;
}

// ── Resolution Agent (Recommended Solution) ─────────────────

export interface ResolutionPlan {
  root_cause_hypothesis: string;
  resolution_steps: string[];
  confidence: "high" | "medium" | "low";
  estimated_effort: "high" | "medium" | "low";
  escalation_advice: string;
  preventive_note: string;
}

export interface RecommendedSolution {
  ticket_id: string;
  plan: ResolutionPlan;
  cached: boolean;
}

// ── Build/version info (footer) ──────────────────────────────

export interface BuildInfo {
  app: string;
  component: string;
  version: string;
  build_sha: string;
  build_time: string;
}
// ── Manual ticket fetch (by days) ─────────────────────────────

export interface FetchOldTicketsResult {
  queued: boolean;
  preset: "2_months" | "3_months" | "custom";
  start_at: string;
  end_at: string;
  requested_at: string;
  start_date: string;
  end_date: string;
}

// ── External ITSM user directory ─────────────────────────────

export interface ExternalUserRecord {
  id: string;
  binding_id: string;
  provider: string;
  external_id: string;
  user_type: "agent" | "requester";
  name: string;
  email: string | null;
  title: string | null;
  active: boolean;
  profile: Record<string, unknown>;
  source_updated_at: string | null;
  fetched_at: string;
}

export interface ExternalUserListResponse {
  users: ExternalUserRecord[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ExternalUserListParams {
  search?: string;
  userType?: ExternalUserRecord["user_type"] | "";
  limit?: number;
  offset?: number;
}

export interface ExternalUserSyncResult {
  created: number;
  updated: number;
  unchanged: number;
  deactivated: number;
  errors: number;
  error_details: string[];
  total: number;
  groups_created: number;
  groups_updated: number;
  groups_unchanged: number;
  groups_deactivated: number;
  memberships: number;
  group_errors: number;
}

export interface UserExternalIdentityLink {
  id: number;
  user_id: string;
  external_user_id: string;
  binding_id: string;
  provider: string;
  external_id: string;
  external_name: string;
  external_email: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export type EmailAudience = "agents" | "users";

export interface EmailRecipient {
  id: string;
  name: string;
  email: string;
  audience: EmailAudience;
  source: string;
  title: string | null;
}

export interface EmailRecipientList {
  audience: EmailAudience;
  recipients: EmailRecipient[];
  total: number;
  truncated: boolean;
}

export interface EmailProviderStatus {
  provider: "sendgrid";
  configured: boolean;
  api_key_set: boolean;
  from_email_set: boolean;
  from_name: string;
}

export interface EmailSendInput {
  audience: EmailAudience;
  recipient_ids: string[];
  subject: string;
  body: string;
}

export interface EmailSendResponse {
  status: "accepted";
  recipient_count: number;
  message_id: string | null;
}

// ── Systemic Issues ───────────────────────────────────────────

export interface SystemicCluster {
  cluster_id: string;
  ticket_count: number;
  ticket_ids: string[];
  avg_priority_weight: number;
  avg_escalation_risk: number;
  business_impact_score: number;
  shared_keywords: string[];
  samples: string[];
  status_breakdown: Record<string, number>;
}

export interface SystemicIssuesResponse {
  generated_at: string;
  window_days: number;
  clusters: SystemicCluster[];
  total_tickets: number;
  analyzed_tickets: number;
  truncated: boolean;
  clustered_tickets: number;
  parameters: {
    similarity_cutoff: number;
    min_cluster_size: number;
  };
}

export interface ReportByCategoryResponse {
  categories: string[];
  counts: number[];
  total_categories: number;
  truncated: boolean;
}

export interface ReportResolutionTimeResponse {
  categories: string[];
  avg_hours: number[];
  total_matching_tickets: number;
  analyzed_tickets: number;
  truncated: boolean;
}

// ── Standalone ticketing types ────────────────────────────────

export interface TicketComment {
  id: number;
  ticket_id: string;
  author_id: string | null;
  author_name: string;
  author_email: string | null;
  author_title: string | null;
  author_type: "agent" | "requester" | null;
  body: string;
  is_private: boolean;
  created_at: string;
  external_source: string | null;
  external_id: string | null;
  external_author_id: string | null;
  external_updated_at: string | null;
}

export interface TicketAttachment {
  id: string;
  ticket_id: string;
  owner_type: "ticket" | "conversation";
  owner_external_id: string;
  external_id: string;
  name: string;
  content_type: string | null;
  size: number | null;
  stored_size: number | null;
  status: string;
  created_at: string;
  stored_at: string | null;
}

export interface TicketAttachmentPage {
  attachments: TicketAttachment[];
  limit: number;
  offset: number;
  hasMore: boolean;
}

export interface TicketCategory {
  id: number;
  name: string;
  description: string;
  color: string;
  created_at: string | null;
}

export interface TicketAuditEntry {
  id: number;
  ticket_id: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
  changed_by: string;
  changed_at: string;
}

// ── Authentication ──────────────────────────────────────────────

export interface UserOut {
  id: string;
  name: string;
  email: string | null;
  avatar: string | null;
  title: string | null;
  role: string;
  is_active: boolean;
  impact_points: number;
  tier: number;
  momentum: number;
  last_login_at: string | null;
}

export interface UserListParams {
  search?: string;
  isActive?: boolean;
  limit?: number;
  offset?: number;
  includeSummary?: boolean;
}

export interface UserPage {
  users: UserOut[];
  limit: number;
  offset: number;
  hasMore: boolean;
  activeRoleCounts: {
    admin: number;
    supervisor: number;
    agent: number;
    other: number;
  };
}

export interface AuthContext extends UserOut {
  auth_kind: "session" | "demo_fallback";
  app_mode: "demo" | "production";
}

export interface AuthResponse {
  token?: string | null;
  user: UserOut;
}

export interface UserCreateInput {
  name: string;
  email: string;
  title?: string;
  role: string;
  password?: string;
}

export interface UserUpdateInput {
  name?: string;
  email?: string;
  title?: string;
  role?: string;
  is_active?: boolean;
  password?: string;
}

// ── Knowledge Base ──────────────────────────────────────────────

export interface KbArticle {
  id: string;
  title: string;
  slug: string;
  content: string;
  category: string | null;
  tags: string | null;
  author_id: string | null;
  author_name: string | null;
  reviewer_id: string | null;
  status: string;
  version: number;
  published_at: string | null;
  review_due_at: string | null;
  views: number;
  helpful: number;
  not_helpful: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface KbArticleCreateInput {
  title: string;
  content: string;
  category?: string;
  tags?: string;
  status: string;
  review_due_at?: string | null;
}

// ── Config (statuses, priorities, notifications) ───────────────

export interface TicketStatusConfig {
  id: number;
  name: string;
  label: string;
  color: string;
  is_open: boolean;
  is_terminal: boolean;
  sort_order: number;
}

export interface TicketPriorityConfig {
  id: number;
  name: string;
  label: string;
  color: string;
  sla_hours: number | null;
  weight: number;
  sort_order: number;
}

export interface NotificationConfig {
  id: number;
  event: string;
  label: string;
  enabled: boolean;
  channels: string;
}

// ── Reports ─────────────────────────────────────────────────────

export type ReportDateField = "created" | "resolved";

export type ReportType = "overview" | "volume" | "breakdown" | "resolution" | "sla";
export type ReportGroupBy = "status" | "priority" | "category" | "assignee" | "source" | "ticket_type";
export type ReportMetric = "ticket_count" | "avg_resolution_hours" | "sla_compliance";
export type ReportResolutionState = "open" | "resolved";
export type ReportSlaState = "breached" | "within_sla" | "not_tracked";

export interface ReportFilters {
  startAt: string;
  endAt: string;
  dateField: ReportDateField;
  status?: string;
  priority?: string;
  category?: string;
  assigneeId?: string;
  source?: string;
  ticketType?: string;
  resolutionState?: ReportResolutionState;
  slaState?: ReportSlaState;
}

export interface ReportSeriesResponse {
  metric: ReportMetric;
  group_by: ReportGroupBy;
  labels: string[];
  values: number[];
  counts: number[];
  unit: "tickets" | "hours" | "percent";
  total_groups: number;
  truncated: boolean;
}

export interface ReportOptions {
  statuses: string[];
  priorities: string[];
  categories: string[];
  sources: string[];
  ticket_types: string[];
  assignees: Array<{ id: string; name: string }>;
  has_unassigned: boolean;
  truncated: {
    statuses: boolean;
    priorities: boolean;
    categories: boolean;
    sources: boolean;
    ticket_types: boolean;
    assignees: boolean;
  };
}

export interface ReportSummary {
  total_tickets: number;
  open_tickets: number;
  resolved_tickets: number;
  breached_sla: number;
  avg_resolution_hours: number;
  escalation_rate: number;
  csat_proxy: number | null;
}

// ── Projects ────────────────────────────────────────────────────

export interface Project {
  id: string;
  name: string;
  key: string;
  description: string;
  lead_id: string | null;
  lead_name: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

// ── Service Catalog ─────────────────────────────────────────────

export interface ServiceItem {
  id: string;
  name: string;
  description: string;
  category: string | null;
  pricing: string | null;
  sla_hours: number | null;
  approval_required: boolean;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ServicePage {
  services: ServiceItem[];
  limit: number;
  offset: number;
  hasMore: boolean;
  summary: {
    total: number;
    active: number;
    categoryCount: number;
    categoryOptions: string[];
    categoryOptionsTruncated: boolean;
  };
}

export interface ServiceRequest {
  id: string;
  ticket_id: string;
  service_item_id: string | null;
  service_name: string | null;
  quantity: number;
  justification: string;
  approval_status: string;
  fulfillment_status: string;
  approved_by: string | null;
  approved_at: string | null;
  delivery_notes: string | null;
  fulfilled_by: string | null;
  fulfilled_at: string | null;
  created_at: string | null;
}

export interface ServiceRequestPage {
  requests: ServiceRequest[];
  limit: number;
  offset: number;
  hasMore: boolean;
  summary: {
    total: number;
    open: number;
    pending: number;
    pendingApproval: number;
    awaitingFulfillment: number;
  };
}

// ── Problem Management ──────────────────────────────────────────

export interface Problem {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  category: string | null;
  assigned_to: string | null;
  assigned_name: string | null;
  root_cause: string | null;
  workaround: string | null;
  resolution: string | null;
  impact_scope: string | null;
  closed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  linked_tickets_count: number;
}

// ── Change Management ───────────────────────────────────────────

export interface ChangeRecord {
  id: string;
  title: string;
  description: string;
  change_type: string;
  status: string;
  priority: string;
  risk_level: string;
  impact: string | null;
  rollback_plan: string | null;
  test_plan: string | null;
  scheduled_start: string | null;
  scheduled_end: string | null;
  requested_by: string | null;
  requested_name: string | null;
  assigned_to: string | null;
  assigned_name: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChangePage {
  changes: ChangeRecord[];
  limit: number;
  offset: number;
  hasMore: boolean;
  summary: {
    awaitingReview: number;
    inProgress: number;
    highRisk: number;
  };
}

export interface ChangeApproval {
  id: number;
  change_id: string;
  approver_id: string | null;
  approver_name: string | null;
  decision: string | null;
  comment: string | null;
  decided_at: string | null;
  created_at: string | null;
}

export interface ChangeApprovalPage {
  approvals: ChangeApproval[];
  limit: number;
  offset: number;
  hasMore: boolean;
}

// ── Asset / CMDB ────────────────────────────────────────────────

export interface Asset {
  id: string;
  name: string;
  asset_type: string;
  asset_tag: string | null;
  status: string;
  owner_id: string | null;
  owner_name: string | null;
  location: string | null;
  vendor: string | null;
  model: string | null;
  purchase_date: string | null;
  warranty_expiry: string | null;
  cost: number | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AssetPage {
  assets: Asset[];
  limit: number;
  offset: number;
  hasMore: boolean;
}

// ── Surveys / CSAT ──────────────────────────────────────────────

export interface SurveyTemplate {
  id: number;
  name: string;
  question: string;
  is_active: boolean;
}

export interface SurveyOut {
  id: string;
  ticket_id: string;
  template_id: number | null;
  ticket_subject: string | null;
  recipient_email: string | null;
  recipient_name: string | null;
  response_expires_at: string | null;
  delivery_status: "pending" | "uncertain" | "accepted" | "failed" | "legacy";
  delivery_message_id: string | null;
  delivery_error: string | null;
  delivery_attempted_at: string | null;
  sent_by: string | null;
  sent_at: string | null;
  responded_at: string | null;
  created_at: string | null;
}

export interface PortalSurveyQuestion {
  question: string;
  expires_at: string;
}

export interface PortalSurveySubmitted {
  status: "submitted";
}

// ── Time Tracking ───────────────────────────────────────────────

export interface TimeEntry {
  id: number;
  ticket_id: string;
  user_id: string;
  user_name: string | null;
  description: string;
  minutes: number;
  entry_date: string | null;
  created_at: string | null;
}

export interface TimeEntryPage {
  entries: TimeEntry[];
  limit: number;
  offset: number;
  hasMore: boolean;
}

// ── Self-Service Portal ─────────────────────────────────────────

export interface PortalTicket {
  id: string;
  subject: string;
  status: string;
  priority: string;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * Returned only by the public ticket creation endpoint. Capability material is
 * intentionally absent from every subsequent ticket response.
 */
export interface PortalTicketCreated extends PortalTicket {
  access_token: string;
  tracking_url: string;
  access_expires_at: string;
}
