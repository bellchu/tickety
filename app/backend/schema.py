from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from datetime import datetime


class Ticket(BaseModel):
    id: str
    subject: str
    description: str = ""
    reporter: str = ""
    requester_id: Optional[str] = None
    requester_name: Optional[str] = None
    requester_email: Optional[str] = None
    requester_title: Optional[str] = None
    status: str = "New"
    priority: str = "Medium"
    sentiment: Optional[str] = None
    category: Optional[str] = None
    mood: Optional[str] = None
    complexity: int = 1
    ai_reasoning: Optional[str] = None
    suggested_response: Optional[str] = None

    # Standalone ticketing
    ticket_type: str = "incident"
    impact: Optional[str] = None
    urgency: Optional[str] = None
    workflow_status: Optional[str] = None
    ai_review_state: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    service_id: Optional[str] = None
    asset_id: Optional[str] = None
    response_due_at: Optional[datetime] = None
    resolution_due_at: Optional[datetime] = None
    due_by: Optional[datetime] = None
    sla_paused_at: Optional[datetime] = None
    sla_paused_seconds: int = 0
    tags: Optional[str] = None

    external_source: Optional[str] = None
    binding_id: str = "legacy"
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    external_status: Optional[str] = None
    external_status_code: Optional[str] = None
    external_priority_code: Optional[str] = None
    external_ticket_type_raw: Optional[str] = None
    external_assignee_id: Optional[str] = None
    external_assignee_name: Optional[str] = None
    external_group_id: Optional[str] = None
    external_category: Optional[str] = None
    external_subcategory: Optional[str] = None
    external_item_category: Optional[str] = None
    external_workspace_id: Optional[str] = None
    external_updated_at: Optional[datetime] = None
    external_description_html: Optional[str] = None
    external_conversation_updated_at: Optional[datetime] = None
    external_created_at: Optional[datetime] = None
    external_resolved_at: Optional[datetime] = None
    external_due_by: Optional[datetime] = None
    external_fr_due_by: Optional[datetime] = None

    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    points_awarded: int = 0

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_communication_at: Optional[datetime] = None

    # Intelligence fields
    escalation_risk: int = 0
    summary: Optional[str] = None
    recommended_solution: Optional[str] = None
    ai_source_hash: Optional[str] = None
    ai_pipeline_version: Optional[str] = None
    ai_model: Optional[str] = None
    ai_status: Optional[str] = None
    ai_claim_id: Optional[str] = None
    ai_lease_expires_at: Optional[datetime] = None
    ai_attempts: int = 0
    ai_next_attempt_at: Optional[datetime] = None
    ai_requested_artifacts: Optional[str] = None
    ai_started_at: Optional[datetime] = None
    ai_generated_at: Optional[datetime] = None
    ai_error: Optional[str] = None
    ai_synthetic: bool = False
    ai_suggested_priority: Optional[str] = None
    ai_suggested_category: Optional[str] = None
    recommended_team: str = "Unrouted / Review"
    recommended_team_basis: Literal[
        "ai_category", "source_category", "not_applicable", "unrouted_review"
    ] = "unrouted_review"
    routing_status: Literal[
        "legacy_ai_category",
        "source_category_suggestion",
        "not_applicable",
        "unrouted_review",
    ] = "unrouted_review"
    routing_abstention_reason: Optional[
        Literal[
            "missing_ai_category",
            "unsupported_ai_category",
            "untrusted_ai_status",
        ]
    ] = "untrusted_ai_status"
    routing_catalog_validated: bool = False


class AIAnalysis(BaseModel):
    sentiment: str
    category: str
    priority: str
    mood: str
    action: str
    reasoning: str
    suggested_response: Optional[str] = None


class TriageResult(BaseModel):
    ticket_id: str
    sentiment: str
    category: str
    priority: str
    mood: str
    complexity: int
    action: str
    reasoning: str
    suggested_response: Optional[str] = None
    escalation_risk: int = 0


class User(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    avatar: Optional[str] = None
    title: Optional[str] = None
    impact_points: int = 0
    tier: int = 1
    momentum: int = 0
    last_action_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserSummary(BaseModel):
    id: str
    name: str
    avatar: Optional[str] = None
    title: Optional[str] = None
    impact_points: int = 0
    tier: int = 1
    momentum: int = 0
    tickets_resolved: int = 0
    rank: Optional[int] = None


class Recognition(BaseModel):
    id: int
    user_id: str
    recognition_key: str
    unlocked_at: datetime
    ticket_id: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None


class PointsAwardedNotification(BaseModel):
    ticket_id: str
    ticket_subject: str
    user_id: str
    user_name: str
    points_earned: int
    new_total: int
    new_tier: int
    tier_promoted: bool
    new_momentum: int
    recognitions_unlocked: List[Recognition] = Field(default_factory=list)


class SyncStatus(BaseModel):
    provider: str
    binding_id: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    automatic_ai_enabled: bool = False
    automatic_ai_generation: Optional[int] = None
    automatic_ai_cutover_at: Optional[datetime] = None
    automatic_ai_enabled_at: Optional[datetime] = None
    automatic_ai_paused_at: Optional[datetime] = None
    automatic_ai_lookback_days: int = 7
    automatic_fetch_days: int = 30
    last_status: str = "idle"
    last_error: Optional[str] = None
    total_synced: int = 0
    recent_since_at: Optional[datetime] = None
    recent_cycle_started_at: Optional[datetime] = None
    recent_page: int = 1
    recent_workspace_index: int = 0
    recent_completed_at: Optional[datetime] = None
    history_page: int = 1
    history_workspace_index: int = 0
    history_complete: bool = False
    history_processed: int = 0
    history_since_at: Optional[datetime] = None
    history_until_at: Optional[datetime] = None
    history_requested_at: Optional[datetime] = None
    conversations_processed: int = 0
    run_started_at: Optional[datetime] = None
    run_finished_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    rate_limit_total: Optional[int] = None
    rate_limit_remaining: Optional[int] = None
    rate_limit_used: Optional[int] = None
    last_batch_new: int = 0
    last_batch_updated: int = 0
    last_batch_errors: int = 0
    local_ticket_count: int = 0
    sync_interval_seconds: int = 60
    recent_pages_per_sync: int = 2
    history_pages_per_sync: int = 1
    conversations_per_sync: int = 1
    attachments_per_sync: int = 2
    attachment_storage_configured: bool = False
    attachment_pending: int = 0
    attachment_stored: int = 0
    attachment_errors: int = 0


class AIAutomationFeatureStatus(BaseModel):
    key: str
    label: str
    enabled: bool


class AIQueueStatusSummary(BaseModel):
    total_tickets: int = 0
    not_analyzed: int = 0
    queued: int = 0
    queued_ready: int = 0
    retry_scheduled: int = 0
    running: int = 0
    running_active: int = 0
    lease_expired: int = 0
    completed: int = 0
    partial: int = 0
    stale: int = 0
    failed: int = 0
    dead_letter: int = 0
    paused: int = 0
    attention: int = 0
    oldest_queued_at: Optional[datetime] = None


class AITaskStatusItem(BaseModel):
    ticket_id: str
    subject: str
    ticket_status: str
    priority: str
    source: str
    external_id: Optional[str] = None
    ai_status: Optional[str] = None
    lifecycle: Literal[
        "not_analyzed",
        "queued",
        "retry_scheduled",
        "running",
        "lease_expired",
        "completed",
        "partial",
        "stale",
        "failed",
        "dead_letter",
        "paused",
        "unknown",
    ]
    requested_artifacts: List[str] = Field(default_factory=list)
    attempts: int = 0
    model: Optional[str] = None
    synthetic: bool = False
    started_at: Optional[datetime] = None
    generated_at: Optional[datetime] = None
    next_attempt_at: Optional[datetime] = None
    lease_expires_at: Optional[datetime] = None
    error_code: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AILLMCallStatusItem(BaseModel):
    id: int
    provider: str
    model: str
    task: str
    status: str
    attempts: int
    latency_ms: int
    total_tokens: int
    synthetic: bool
    error_code: Optional[str] = None
    created_at: datetime


class AILLMCallSummary(BaseModel):
    calls: int = 0
    successful: int = 0
    failed_attempts: int = 0
    total_tokens: int = 0
    average_latency_ms: int = 0
    last_call_at: Optional[datetime] = None


class AIStatusResponse(BaseModel):
    generated_at: datetime
    automation: List[AIAutomationFeatureStatus]
    active_integration_bindings: int = 0
    automatic_ai_bindings: int = 0
    active_routing_backlog_enabled: bool = False
    queue: AIQueueStatusSummary
    view: Literal["all", "active", "attention", "completed", "not_analyzed"]
    search: str = ""
    tasks: List[AITaskStatusItem]
    total_tasks: int
    limit: int
    offset: int
    recent_calls: List[AILLMCallStatusItem]
    calls_24h: AILLMCallSummary


class OperationalDiagnosticEntry(BaseModel):
    severity: Literal["info", "warning", "error"]
    source: str
    message: str
    timestamp: Optional[datetime] = None


class OperationalDiagnosticsResponse(BaseModel):
    area: Literal["application", "ai", "sync", "retrieval", "oauth"]
    generated_at: datetime
    entries: List[OperationalDiagnosticEntry]
    truncated: bool = False


class ExternalUser(BaseModel):
    id: str
    binding_id: str
    provider: str
    external_id: str
    user_type: Literal["agent", "requester"]
    name: str
    email: Optional[str] = None
    title: Optional[str] = None
    active: bool = True
    profile: dict = Field(default_factory=dict)
    source_updated_at: Optional[datetime] = None
    fetched_at: datetime


class ExternalUserSyncResult(BaseModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    errors: int = 0
    total: int = 0
    error_details: List[str] = Field(default_factory=list)


class IntegrationBindingCreate(BaseModel):
    provider: Literal["freshservice"] = "freshservice"
    environment: Literal["trial", "sandbox", "production"]
    canonical_account_host: str = Field(..., min_length=1, max_length=255)
    workspace_ids: List[str] = Field(default_factory=list, max_length=50)
    installation_id: Optional[str] = Field(None, max_length=255)
    product_variant: Optional[Literal["ITSM", "MSP"]] = None
    credential_reference: Literal["env://freshservice"] = "env://freshservice"
    expires_at: Optional[datetime] = None


class IntegrationBindingSuspend(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)


class FreshworksBootstrapRequest(BaseModel):
    binding_id: str = Field(..., min_length=36, max_length=36)
    account_host: str = Field(..., min_length=1, max_length=255)
    external_user_id: str = Field(..., min_length=1, max_length=255)
    workspace_id: Optional[str] = Field(None, max_length=255)
    external_ticket_id: Optional[str] = Field(None, pattern=r"^[0-9]+$", max_length=255)
    ticket_updated_at: Optional[datetime] = None
    audience: Literal["ticket_sidebar", "full_page_app"]


class FreshworksBootstrapRedeem(BaseModel):
    binding_id: str = Field(..., min_length=36, max_length=36)
    code: str = Field(..., min_length=32, max_length=255)


class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=20_000)
    reporter: str = Field("", max_length=320)
    priority: str = Field("P3", min_length=1, max_length=32)
    ticket_type: Literal["incident", "request"] = "incident"
    impact: Optional[str] = Field(None, max_length=120)
    urgency: Optional[str] = Field(None, max_length=120)
    service_id: Optional[str] = Field(None, max_length=255)
    asset_id: Optional[str] = Field(None, max_length=255)


class ExternalAttachment(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=1_024)
    content_type: Optional[str] = Field(None, max_length=255)
    size: Optional[int] = Field(None, ge=0)
    download_url: str = Field(..., min_length=1, max_length=8_192)


class ExternalConversation(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=255)
    # Provider content is retained losslessly. AI/search projections apply
    # their own explicit bounds downstream and must never be the archive.
    body: str
    body_html: Optional[str] = None
    author_id: Optional[str] = Field(None, max_length=255)
    author_name: Optional[str] = Field(None, max_length=255)
    author_email: Optional[str] = Field(None, max_length=320)
    is_private: bool = False
    incoming: bool = False
    source: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    attachments: List[ExternalAttachment] = Field(default_factory=list, max_length=1_000)


class AutomaticAIEnableRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    expected_generation: int = Field(..., ge=0)


class AutomaticAIPauseRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    expected_generation: int = Field(..., ge=1)


class ExternalTicket(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=255)
    subject: str = Field(..., min_length=1, max_length=500)
    # Freshservice descriptions can exceed the old 100k validation ceiling.
    # Text columns are the lossless source copy; prompt bounds live elsewhere.
    description: str
    description_html: Optional[str] = None
    reporter: str = Field(..., max_length=320)
    priority: str = Field(..., min_length=1, max_length=32)
    external_priority_code: Optional[str] = Field(None, max_length=64)
    status: str = Field(..., min_length=1, max_length=120)
    external_status_code: Optional[str] = Field(None, max_length=64)
    assignee_id: Optional[str] = Field(None, max_length=255)
    external_group_id: Optional[str] = Field(None, max_length=255)
    external_category: Optional[str] = Field(None, max_length=255)
    external_subcategory: Optional[str] = Field(None, max_length=255)
    external_item_category: Optional[str] = Field(None, max_length=255)
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    due_by: Optional[datetime] = None
    fr_due_by: Optional[datetime] = None
    ticket_type: Optional[str] = Field(None, max_length=120)
    requester_id: Optional[str] = Field(None, max_length=255)
    requester_name: Optional[str] = Field(None, max_length=255)
    requester_email: Optional[str] = Field(None, max_length=320)
    requester_title: Optional[str] = Field(None, max_length=255)
    external_workspace_id: Optional[str] = Field(None, max_length=255)
    url: Optional[str] = Field(None, max_length=2_048)
    conversations_loaded: bool = False
    conversations: List[ExternalConversation] = Field(default_factory=list, max_length=1_000)
    attachments: List[ExternalAttachment] = Field(default_factory=list, max_length=1_000)


class TicketAttachment(BaseModel):
    id: str
    ticket_id: str
    owner_type: Literal["ticket", "conversation"]
    owner_external_id: str
    external_id: str
    name: str
    content_type: Optional[str] = None
    size: Optional[int] = None
    stored_size: Optional[int] = None
    status: str
    created_at: datetime
    stored_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WebhookEvent(BaseModel):
    event_type: str
    external_id: str
    raw: dict


class Settings(BaseModel):
    APP_MODE: Optional[str] = None
    SEED_DEMO_DATA: Optional[str] = None
    CORS_ALLOW_ORIGINS: Optional[str] = None
    COOKIE_SECURE: Optional[str] = None
    COOKIE_SAMESITE: Optional[str] = None
    FOUNDRY_API_KEY: Optional[str] = None
    FOUNDRY_API_BASE: Optional[str] = None
    FOUNDRY_AUTH_METHOD: Optional[str] = None
    CUSTOM_API_KEY: Optional[str] = None
    CUSTOM_API_BASE: Optional[str] = None
    DEFAULT_MODEL: Optional[str] = None
    LLM_ALLOW_SYNTHETIC: Optional[str] = None
    LLM_REQUEST_TIMEOUT_SECONDS: Optional[str] = None
    LLM_OVERALL_TIMEOUT_SECONDS: Optional[str] = None
    LLM_MAX_PROMPT_CHARS: Optional[str] = None
    LLM_MAX_CONCURRENCY: Optional[str] = None
    LLM_PERSIST_METRICS: Optional[str] = None
    LLM_DAILY_TOKEN_BUDGET: Optional[str] = None
    AI_USER_REQUESTS_PER_MINUTE: Optional[str] = None
    AI_USER_REQUESTS_PER_DAY: Optional[str] = None
    AI_SYSTEM_REQUESTS_PER_MINUTE: Optional[str] = None
    AI_SYSTEM_REQUESTS_PER_DAY: Optional[str] = None
    AI_ANALYSIS_LEASE_SECONDS: Optional[str] = None
    AI_ANALYSIS_MAX_ATTEMPTS: Optional[str] = None
    AI_BACKGROUND_TICKETS_PER_SWEEP: Optional[str] = None
    TICKET_EMBEDDING_ENABLED: Optional[str] = None
    TICKET_EMBEDDING_MODEL: Optional[str] = None
    TICKET_EMBEDDING_DIMENSIONS: Optional[str] = None
    TICKET_EMBEDDING_TIMEOUT_SECONDS: Optional[str] = None
    TICKET_EMBEDDING_MAX_CHARS: Optional[str] = None
    TICKET_VECTOR_MIN_SCORE: Optional[str] = None
    TICKET_RAG_SCOPE_KEY: Optional[str] = None
    TICKET_RAG_V2_SCOPE_ALLOWLIST: Optional[str] = None
    TICKET_RAG_V2_WRITE_ENABLED: Optional[str] = None
    TICKET_RAG_V2_WORKER_ENABLED: Optional[str] = None
    TICKET_RAG_V2_READ_ENABLED: Optional[str] = None
    TICKET_RAG_CHUNK_TARGET_TOKENS: Optional[str] = None
    TICKET_RAG_CHUNK_MAX_TOKENS: Optional[str] = None
    TICKET_RAG_CHUNK_OVERLAP_TOKENS: Optional[str] = None
    TICKET_RAG_EMBED_BATCH_SIZE: Optional[str] = None
    TICKET_RAG_EMBED_LEASE_SECONDS: Optional[str] = None
    TICKET_RAG_WORKER_POLL_SECONDS: Optional[str] = None
    TICKET_RAG_QUERY_CACHE_TTL_SECONDS: Optional[str] = None
    TICKET_RAG_QUERY_CACHE_MAX_ROWS: Optional[str] = None
    TICKET_RAG_SNAPSHOT_TTL_SECONDS: Optional[str] = None
    DATABASE_URL: Optional[str] = None
    ITSM_PROVIDER: Optional[str] = None
    FRESHSERVICE_DOMAIN: Optional[str] = None
    FRESHWORKS_ORG_DOMAIN: Optional[str] = None
    FRESHSERVICE_API_KEY: Optional[str] = None
    FRESHSERVICE_WORKSPACE_ID: Optional[str] = None
    FRESHSERVICE_TICKET_INCLUDES: Optional[str] = None
    FRESHSERVICE_AGENT_STATE: Optional[str] = None
    FRESHSERVICE_MIN_INTERVAL_SECONDS: Optional[str] = None
    FRESHSERVICE_RATE_LIMIT_RESERVE: Optional[str] = None
    FRESHSERVICE_RECENT_PAGES_PER_SYNC: Optional[str] = None
    FRESHSERVICE_HISTORY_PAGES_PER_SYNC: Optional[str] = None
    FRESHSERVICE_CONVERSATIONS_PER_SYNC: Optional[str] = None
    FRESHSERVICE_ATTACHMENTS_PER_SYNC: Optional[str] = None
    ATTACHMENT_STORAGE_PROVIDER: Optional[str] = None
    ATTACHMENT_MAX_BYTES: Optional[str] = None
    AZURE_STORAGE_ACCOUNT_URL: Optional[str] = None
    AZURE_STORAGE_CONTAINER: Optional[str] = None
    FRESHSERVICE_OAUTH_CLIENT_ID: Optional[str] = None
    FRESHSERVICE_OAUTH_CLIENT_SECRET: Optional[str] = None
    FRESHSERVICE_OAUTH_REDIRECT_URI: Optional[str] = None
    FRESHSERVICE_OAUTH_SCOPES: Optional[str] = None
    FRESHSERVICE_OAUTH_ACCESS_TOKEN: Optional[str] = None
    FRESHSERVICE_OAUTH_REFRESH_TOKEN: Optional[str] = None
    JIRA_BASE_URL: Optional[str] = None
    JIRA_EMAIL: Optional[str] = None
    JIRA_API_TOKEN: Optional[str] = None
    JIRA_PROJECT_KEY: Optional[str] = None
    JIRA_ISSUE_TYPE: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None
    SYNC_INTERVAL_SECONDS: Optional[str] = None
    NEXT_PUBLIC_API_URL: Optional[str] = None
    NEXT_PUBLIC_WS_URL: Optional[str] = None
    FRONTEND_URL: Optional[str] = None
    # AI automation toggles ("true" / "false" as stored in env-style settings)
    SLA_P1_HOURS: Optional[str] = None
    SLA_P2_HOURS: Optional[str] = None
    SLA_P3_HOURS: Optional[str] = None
    SLA_P4_HOURS: Optional[str] = None

    # Organization / branding
    ORG_NAME: Optional[str] = None
    ORG_LOGO_URL: Optional[str] = None
    ORG_PRIMARY_COLOR: Optional[str] = None

    # AI automation toggles ("true" / "false")
    AUTO_TRIAGE_ENABLED: Optional[str] = None
    AUTO_SUMMARIZE_ENABLED: Optional[str] = None
    AUTO_ROUTE_ENABLED: Optional[str] = None
    AUTO_RESOLVE_ENABLED: Optional[str] = None
    AUTO_SYSTEMIC_ENABLED: Optional[str] = None

    # Auth / Security
    LOGIN_REQUIRED: Optional[str] = None
    SSO_ENABLED: Optional[str] = None
    SSO_PROVIDER: Optional[str] = None
    SSO_ENTRA_TENANT_ID: Optional[str] = None
    SSO_OKTA_DOMAIN: Optional[str] = None
    SSO_OKTA_AUTH_SERVER_ID: Optional[str] = None
    SSO_CLIENT_ID: Optional[str] = None
    SSO_CLIENT_SECRET: Optional[str] = None
    SSO_DISCOVERY_URL: Optional[str] = None
    SSO_REDIRECT_URI: Optional[str] = None
    SSO_ALLOWED_DOMAINS: Optional[str] = None
    SSO_AUTO_PROVISION: Optional[str] = None

    # Allow any provider-specific key from the catalog without re-declaring.
    model_config = {"extra": "allow"}

class ResolutionPlan(BaseModel):
    root_cause_hypothesis: str = ""
    resolution_steps: List[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    estimated_effort: Literal["high", "medium", "low"] = "medium"
    escalation_advice: str = ""
    preventive_note: str = ""


class RecommendedSolution(BaseModel):
    ticket_id: str
    plan: ResolutionPlan
    cached: bool = False

# ── Standalone ticketing schemas ──────────────────────────────

class TicketUpdate(BaseModel):
    subject: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=20_000)
    status: Optional[str] = Field(None, max_length=120)
    workflow_status: Optional[str] = Field(None, max_length=120)
    ai_review_state: Optional[str] = Field(None, max_length=120)
    priority: Optional[str] = Field(None, max_length=32)
    ticket_type: Optional[Literal["incident", "request"]] = None
    impact: Optional[str] = Field(None, max_length=120)
    urgency: Optional[str] = Field(None, max_length=120)
    assignee_id: Optional[str] = Field(None, max_length=255)
    service_id: Optional[str] = Field(None, max_length=255)
    asset_id: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, max_length=120)
    tags: Optional[str] = Field(None, max_length=1_000)
    response_due_at: Optional[datetime] = None
    resolution_due_at: Optional[datetime] = None
    due_by: Optional[datetime] = None


class TicketComment(BaseModel):
    id: int
    ticket_id: str
    author_id: Optional[str] = None
    author_name: str = "System"
    author_email: Optional[str] = None
    author_title: Optional[str] = None
    author_type: Optional[Literal["agent", "requester"]] = None
    body: str
    is_private: bool = False
    created_at: datetime
    external_source: Optional[str] = None
    external_id: Optional[str] = None
    external_author_id: Optional[str] = None
    external_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TicketCommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=20_000)
    is_private: bool = False


class TicketCategory(BaseModel):
    id: int
    name: str
    description: str = ""
    color: str = "slate"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TicketCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    color: str = "slate"


class TicketAuditEntry(BaseModel):
    id: int
    ticket_id: str
    field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: str = "System"
    changed_at: datetime

    class Config:
        from_attributes = True


class BulkAction(BaseModel):
    ticket_ids: List[str] = Field(..., min_length=1, max_length=100)
    action: Literal["assign", "close", "set_priority", "set_category"]
    value: Optional[str] = Field(None, max_length=255)


class TicketIntelligenceBackfillRequest(BaseModel):
    limit: int = Field(200, ge=1, le=500)
    include_comments: bool = True
    include_kb: bool = True
    force: bool = False


class TicketIntelligenceSearchResult(BaseModel):
    source_type: str
    source_id: str
    ticket_id: Optional[str] = None
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    match_method: str = "keyword"
    citation_id: Optional[str] = None
    authority: Literal[
        "published_kb",
        "internal_comment",
        "external_report",
        "authenticated_report",
    ] = "authenticated_report"
    metadata: dict = Field(default_factory=dict)


class TicketIntelligenceSearchResponse(BaseModel):
    query: str
    match_method: str = "keyword"
    results: List[TicketIntelligenceSearchResult] = Field(default_factory=list)


class RelatedTicketItem(BaseModel):
    ticket_id: str
    subject: str
    status: str
    priority: str
    category: Optional[str] = None
    score: float = 0.0
    match_method: str = "keyword"


class RelatedTicketsResponse(BaseModel):
    ticket_id: str
    available: bool = True
    match_method: str = "keyword"
    items: List[RelatedTicketItem] = Field(default_factory=list)


class TicketIntelligenceAnalysisRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(8, ge=1, le=30)
    source_types: List[Literal["ticket", "comment", "kb_article"]] = Field(
        default_factory=lambda: ["ticket", "comment", "kb_article"],
        min_length=1,
        max_length=3,
    )

    @field_validator("source_types")
    @classmethod
    def source_types_must_be_unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("source_types must not contain duplicates")
        return value


class GroundedAnalysisResult(BaseModel):
    text: str = Field(..., min_length=1, max_length=1_000)
    citations: List[str] = Field(..., min_length=1, max_length=10)


class TicketIntelligenceAnalysisResponse(BaseModel):
    question: str
    match_method: str = "keyword"
    snapshot_id: Optional[str] = None
    snapshot_digest: Optional[str] = None
    answer: str = ""
    findings: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    context: List[TicketIntelligenceSearchResult] = Field(default_factory=list)
    grounded_findings: List[GroundedAnalysisResult] = Field(default_factory=list)
    grounded_recommended_actions: List[GroundedAnalysisResult] = Field(default_factory=list)


# ── Authentication ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)


class UserOut(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    avatar: Optional[str] = None
    title: Optional[str] = None
    role: str = "agent"
    is_active: bool = True
    impact_points: int = 0
    tier: int = 1
    momentum: int = 0
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AuthContext(UserOut):
    auth_kind: Literal["session", "demo_fallback"]
    app_mode: Literal["demo", "production"]


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3)
    title: Optional[str] = None
    role: Literal["admin", "supervisor", "agent"] = "agent"
    password: Optional[str] = None  # optional, generated if omitted


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    title: Optional[str] = None
    role: Optional[Literal["admin", "supervisor", "agent"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class AuthResponse(BaseModel):
    token: Optional[str] = None
    user: UserOut


# ── Knowledge Base ──────────────────────────────────────────────

class KbArticle(BaseModel):
    id: str
    title: str
    slug: str
    content: str = ""
    category: Optional[str] = None
    tags: Optional[str] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    reviewer_id: Optional[str] = None
    status: str = "draft"
    version: int = 1
    published_at: Optional[datetime] = None
    review_due_at: Optional[datetime] = None
    views: int = 0
    helpful: int = 0
    not_helpful: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KbArticleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field("", max_length=100_000)
    category: Optional[str] = Field(None, max_length=120)
    tags: Optional[str] = Field(None, max_length=1_000)
    status: Literal["draft", "published", "archived"] = "draft"
    review_due_at: Optional[datetime] = None


class KbArticleUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, max_length=100_000)
    category: Optional[str] = Field(None, max_length=120)
    tags: Optional[str] = Field(None, max_length=1_000)
    status: Optional[Literal["draft", "published", "archived"]] = None
    review_due_at: Optional[datetime] = None


class KbFeedbackCreate(BaseModel):
    helpful: bool = Field(..., strict=True)


# ── Custom status / priority config ─────────────────────────────

class TicketStatusConfig(BaseModel):
    id: int
    name: str
    label: str
    color: str = "slate"
    is_open: bool = True
    is_terminal: bool = False
    sort_order: int = 0

    class Config:
        from_attributes = True


class TicketStatusConfigCreate(BaseModel):
    name: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    color: str = "slate"
    is_open: bool = True
    is_terminal: bool = False
    sort_order: int = 0


class TicketPriorityConfig(BaseModel):
    id: int
    name: str
    label: str
    color: str = "slate"
    sla_hours: Optional[int] = None
    weight: int = 10
    sort_order: int = 0

    class Config:
        from_attributes = True


class TicketPriorityConfigCreate(BaseModel):
    name: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    color: str = "slate"
    sla_hours: Optional[int] = None
    weight: int = 10
    sort_order: int = 0


class NotificationConfig(BaseModel):
    id: int
    event: str
    label: str
    enabled: bool = True
    channels: str = "in_app"

    class Config:
        from_attributes = True


class NotificationConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    channels: Optional[str] = None


# ── Reports ─────────────────────────────────────────────────────

class ReportSummary(BaseModel):
    total_tickets: int
    open_tickets: int
    resolved_tickets: int
    breached_sla: int
    avg_resolution_hours: float
    escalation_rate: float
    csat_proxy: float


# ── Projects ───────────────────────────────────────────────────

class Project(BaseModel):
    id: str
    name: str
    key: str
    description: str = ""
    lead_id: Optional[str] = None
    lead_name: Optional[str] = None
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    key: str = Field(..., min_length=2, max_length=20)
    description: str = ""
    lead_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    lead_id: Optional[str] = None
    status: Optional[str] = None


# ── Service Catalog ────────────────────────────────────────────

class ServiceItem(BaseModel):
    id: str
    name: str
    description: str = ""
    category: Optional[str] = None
    pricing: Optional[str] = None
    sla_hours: Optional[int] = None
    approval_required: bool = False
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    category: Optional[str] = None
    pricing: Optional[str] = None
    sla_hours: Optional[int] = None
    approval_required: bool = False


class ServiceRequest(BaseModel):
    id: str
    ticket_id: str
    service_item_id: Optional[str] = None
    service_name: Optional[str] = None
    quantity: int = 1
    justification: str = ""
    approval_status: str = "not_required"
    fulfillment_status: str = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    delivery_notes: Optional[str] = None
    fulfilled_by: Optional[str] = None
    fulfilled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceRequestCreate(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    service_item_id: str = Field(..., min_length=1)
    quantity: int = 1
    justification: str = ""


class ServiceRequestApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = ""


class ServiceRequestFulfillmentUpdate(BaseModel):
    status: Literal["fulfilled", "cancelled"]
    delivery_notes: str = ""


# ── Problem Management ─────────────────────────────────────────

class Problem(BaseModel):
    id: str
    title: str
    description: str = ""
    status: str = "New"
    priority: str = "P2"
    category: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_name: Optional[str] = None
    root_cause: Optional[str] = None
    workaround: Optional[str] = None
    resolution: Optional[str] = None
    impact_scope: Optional[str] = None
    closed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    linked_tickets_count: int = 0

    class Config:
        from_attributes = True


class ProblemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    priority: str = "P2"
    category: Optional[str] = None
    assigned_to: Optional[str] = None
    impact_scope: Optional[str] = None


class ProblemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assigned_to: Optional[str] = None
    root_cause: Optional[str] = None
    workaround: Optional[str] = None
    resolution: Optional[str] = None
    impact_scope: Optional[str] = None


# ── Change Management ──────────────────────────────────────────

class ChangeRecordOut(BaseModel):
    id: str
    title: str
    description: str = ""
    change_type: str = "Normal"
    status: str = "Draft"
    priority: str = "P2"
    risk_level: str = "Medium"
    impact: Optional[str] = None
    rollback_plan: Optional[str] = None
    test_plan: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    requested_by: Optional[str] = None
    requested_name: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChangeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    change_type: str = "Normal"
    status: str = "Draft"
    priority: str = "P2"
    risk_level: str = "Medium"
    impact: Optional[str] = None
    rollback_plan: Optional[str] = None
    test_plan: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    assigned_to: Optional[str] = None


class ChangeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    change_type: Optional[str] = None
    priority: Optional[str] = None
    risk_level: Optional[str] = None
    impact: Optional[str] = None
    rollback_plan: Optional[str] = None
    test_plan: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    assigned_to: Optional[str] = None


class ChangeApprovalOut(BaseModel):
    id: int
    change_id: str
    approver_id: str
    approver_name: Optional[str] = None
    decision: Optional[str] = None
    comment: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChangeApprovalCreate(BaseModel):
    change_id: Optional[str] = None
    approver_id: str


class ChangeApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = ""


# ── Asset / CMDB ───────────────────────────────────────────────

class Asset(BaseModel):
    id: str
    name: str
    asset_type: str
    asset_tag: Optional[str] = None
    status: str = "In Use"
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    location: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    purchase_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    cost: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AssetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    asset_type: str = Field(..., min_length=1)
    asset_tag: Optional[str] = None
    status: str = "In Use"
    owner_id: Optional[str] = None
    location: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    purchase_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    cost: Optional[float] = None
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    asset_type: Optional[str] = None
    asset_tag: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[str] = None
    location: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    purchase_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    cost: Optional[float] = None
    notes: Optional[str] = None


# ── Surveys / CSAT ─────────────────────────────────────────────

class SurveyTemplate(BaseModel):
    id: int
    name: str
    question: str
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SurveyOut(BaseModel):
    id: str
    ticket_id: str
    template_id: Optional[int] = None
    ticket_subject: Optional[str] = None
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SurveySend(BaseModel):
    ticket_id: str
    template_id: int = 1


class SurveyResponseCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""


# ── Time Tracking ──────────────────────────────────────────────

class TimeEntry(BaseModel):
    id: int
    ticket_id: str
    user_id: str
    user_name: Optional[str] = None
    description: str = ""
    minutes: int
    entry_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TimeEntryCreate(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    description: str = ""
    minutes: int = Field(..., ge=1)


# ── Self-Service Portal ────────────────────────────────────────

class PortalTicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=20_000)
    reporter: str = Field(..., min_length=1, max_length=320)
    priority: str = Field("P3", min_length=1, max_length=32)

class PortalTicketOut(BaseModel):
    id: str
    subject: str
    status: str
    priority: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PortalTicketCreated(PortalTicketOut):
    # Capability material is deliberately present only in the creation
    # response; the database stores its digest, not this bearer token.
    access_token: str
    tracking_url: str
    access_expires_at: datetime
