export interface Ticket {
  id: string;
  subject: string;
  description: string;
  reporter: string;
  status: string;
  priority: string;
  sentiment: string | null;
  category: string | null;
  mood: string | null;
  complexity: number;
  ai_reasoning: string | null;
  suggested_response: string | null;
  assignee_id: string | null;
  assignee_name: string | null;
  due_by: string | null;
  tags: string | null;
  external_source: string | null;
  external_id: string | null;
  external_url: string | null;
  external_status: string | null;
  external_assignee_id: string | null;
  external_updated_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  points_awarded: number;
  created_at: string | null;
  updated_at: string | null;
  escalation_risk: number;
  summary: string | null;
  recommended_solution: string | null;
}

export interface TicketCreateInput {
  subject: string;
  description: string;
  reporter: string;
  priority: string;
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
  last_synced_at: string | null;
  last_status: string;
  last_error: string | null;
  total_synced: number;
}

export interface TriageResult {
  ticket_id: string;
  sentiment: string;
  category: string;
  priority: string;
  mood: string;
  complexity: number;
  action: string;
  reasoning: string;
  suggested_response: string | null;
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
  status: "pending" | "active" | "done";
}

export interface Settings {
  DEEPSEEK_API_KEY: string;
  OPENAI_API_KEY: string;
  OPENAI_API_BASE: string;
  OPENROUTER_API_KEY: string;
  OPENROUTER_API_BASE: string;
  AZURE_API_KEY: string;
  AZURE_API_BASE: string;
  AZURE_API_VERSION: string;
  AZURE_AI_API_KEY: string;
  AZURE_AI_API_BASE: string;
  DEFAULT_MODEL: string;
  DATABASE_URL: string;
  ITSM_PROVIDER: string;
  FRESHSERVICE_DOMAIN: string;
  FRESHSERVICE_API_KEY: string;
  FRESHSERVICE_OAUTH_CLIENT_ID: string;
  FRESHSERVICE_OAUTH_CLIENT_SECRET: string;
  FRESHSERVICE_OAUTH_REDIRECT_URI: string;
  WEBHOOK_SECRET: string;
  SYNC_INTERVAL_SECONDS: string;
  NEXT_PUBLIC_API_URL: string;
  NEXT_PUBLIC_WS_URL: string;
  SLA_P1_HOURS: string;
  SLA_P2_HOURS: string;
  SLA_P3_HOURS: string;
  ORG_NAME: string;
  ORG_LOGO_URL: string;
  ORG_PRIMARY_COLOR: string;
  AUTO_TRIAGE_ENABLED: string;
  AUTO_SUMMARIZE_ENABLED: string;
  AUTO_ROUTE_ENABLED: string;
  AUTO_RESOLVE_ENABLED: string;
  AUTO_SYSTEMIC_ENABLED: string;
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
  status: "on_track" | "at_risk" | "breached";
  is_open: boolean;
}

export interface IntelSlaResponse {
  generated_at: string;
  count: number;
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
  backlog_size: number;
  ranked: PrioritizedTicket[];
}

export interface IntelAlertsResponse {
  generated_at: string;
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
  total_tickets: number;
  by_category: Record<string, number>;
  by_sentiment: Record<string, number>;
  by_status: Record<string, number>;
  top_terms: Array<[string, number]>;
}

export interface AccountHealth {
  reporter: string;
  health_score: number | null;
  churn_risk: "low" | "medium" | "high" | "unknown";
  open: number;
  resolved: number;
  total: number;
  avg_escalation_risk: number;
  negative_sentiment_ratio: number;
}

export interface RouteCandidate {
  user_id: string;
  name: string;
  tier: number;
  impact_points: number;
  momentum: number;
  score: number;
  tier_ok: boolean;
}

export interface RouteRecommendation {
  recommended_user_id: string | null;
  recommended_name: string | null;
  reasoning: string;
  tier_needed: number;
  candidates: RouteCandidate[];
}

export interface TicketSummary {
  ticket_id: string;
  summary: string;
}

// ── Resolution Agent (Recommended Solution) ─────────────────

export interface ResolutionPlan {
  root_cause_hypothesis: string;
  resolution_steps: string[];
  confidence: "high" | "medium" | "low" | string;
  estimated_effort: "high" | "medium" | "low" | string;
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

export interface FetchTicketsResult {
  new: number;
  updated: number;
  skipped: number;
  errors: number;
  fetched: number;
  days: number;
  overwrite: boolean;
}

// ── Agent sync ────────────────────────────────────────────────

export interface AgentRecord {
  id: string;
  name: string;
  email: string | null;
  title: string | null;
  tier: number;
  impact_points: number;
  external_source: string | null;
  external_assignee_id: string | null;
}

export interface AgentListResponse {
  agents: AgentRecord[];
}

export interface SyncAgentsResult {
  created: number;
  updated: number;
  errors: number;
  total: number;
  skipped_inactive: number;
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
  clusters: SystemicCluster[];
  total_tickets: number;
  clustered_tickets: number;
  parameters: {
    similarity_cutoff: number;
    min_cluster_size: number;
  };
}

// ── Standalone ticketing types ────────────────────────────────

export interface TicketComment {
  id: number;
  ticket_id: string;
  author_id: string | null;
  author_name: string;
  body: string;
  is_private: boolean;
  created_at: string;
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

export interface AuthResponse {
  token: string;
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
  status: string;
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

export interface ReportSummary {
  total_tickets: number;
  open_tickets: number;
  resolved_tickets: number;
  breached_sla: number;
  avg_resolution_hours: number;
  escalation_rate: number;
  csat_proxy: number;
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

export interface ServiceRequest {
  id: string;
  ticket_id: string;
  service_item_id: string | null;
  service_name: string | null;
  quantity: number;
  justification: string;
  delivery_notes: string | null;
  fulfilled_by: string | null;
  fulfilled_at: string | null;
  created_at: string | null;
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

export interface ChangeApproval {
  id: number;
  change_id: string;
  approver_id: string;
  approver_name: string | null;
  decision: string | null;
  comment: string | null;
  decided_at: string | null;
  created_at: string | null;
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
  sent_at: string | null;
  responded_at: string | null;
  created_at: string | null;
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

// ── Self-Service Portal ─────────────────────────────────────────

export interface PortalTicket {
  id: string;
  subject: string;
  status: string;
  priority: string;
  reporter: string;
  created_at: string | null;
  updated_at: string | null;
}
