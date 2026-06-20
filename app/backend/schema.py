from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class Ticket(BaseModel):
    id: str
    subject: str
    description: str = ""
    reporter: str = ""
    status: str = "New"
    priority: str = "Medium"
    sentiment: Optional[str] = None
    category: Optional[str] = None
    mood: Optional[str] = None
    complexity: int = 1
    ai_reasoning: Optional[str] = None
    suggested_response: Optional[str] = None

    # Standalone ticketing
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    due_by: Optional[datetime] = None
    tags: Optional[str] = None

    external_source: Optional[str] = None
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    external_status: Optional[str] = None
    external_assignee_id: Optional[str] = None
    external_updated_at: Optional[datetime] = None

    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    points_awarded: int = 0

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Intelligence fields
    escalation_risk: int = 0
    summary: Optional[str] = None
    recommended_solution: Optional[str] = None


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
    last_synced_at: Optional[datetime] = None
    last_status: str = "idle"
    last_error: Optional[str] = None
    total_synced: int = 0


class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    reporter: str = ""
    priority: str = "P3"


class ExternalTicket(BaseModel):
    external_id: str
    subject: str
    description: str
    reporter: str
    priority: str
    status: str
    assignee_id: Optional[str] = None
    updated_at: Optional[datetime] = None
    url: Optional[str] = None


class WebhookEvent(BaseModel):
    event_type: str
    external_id: str
    raw: dict


class Settings(BaseModel):
    DEEPSEEK_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_API_BASE: Optional[str] = None
    AZURE_API_KEY: Optional[str] = None
    AZURE_API_BASE: Optional[str] = None
    AZURE_API_VERSION: Optional[str] = None
    AZURE_AI_API_KEY: Optional[str] = None
    AZURE_AI_API_BASE: Optional[str] = None
    DEFAULT_MODEL: Optional[str] = None
    DATABASE_URL: Optional[str] = None
    ITSM_PROVIDER: Optional[str] = None
    FRESHSERVICE_DOMAIN: Optional[str] = None
    FRESHSERVICE_API_KEY: Optional[str] = None
    FRESHSERVICE_OAUTH_CLIENT_ID: Optional[str] = None
    FRESHSERVICE_OAUTH_CLIENT_SECRET: Optional[str] = None
    FRESHSERVICE_OAUTH_REDIRECT_URI: Optional[str] = None
    FRESHSERVICE_OAUTH_ACCESS_TOKEN: Optional[str] = None
    FRESHSERVICE_OAUTH_REFRESH_TOKEN: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None
    SYNC_INTERVAL_SECONDS: Optional[str] = None
    NEXT_PUBLIC_API_URL: Optional[str] = None
    NEXT_PUBLIC_WS_URL: Optional[str] = None
    # AI automation toggles ("true" / "false" as stored in env-style settings)
    SLA_P1_HOURS: Optional[str] = None
    SLA_P2_HOURS: Optional[str] = None
    SLA_P3_HOURS: Optional[str] = None

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

    # Allow any provider-specific key from the catalog without re-declaring.
    model_config = {"extra": "allow"}

class ResolutionPlan(BaseModel):
    root_cause_hypothesis: str = ""
    resolution_steps: List[str] = []
    confidence: str = "medium"
    estimated_effort: str = "medium"
    escalation_advice: str = ""
    preventive_note: str = ""


class RecommendedSolution(BaseModel):
    ticket_id: str
    plan: ResolutionPlan
    cached: bool = False

# ── Standalone ticketing schemas ──────────────────────────────

class TicketUpdate(BaseModel):
    subject: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    due_by: Optional[datetime] = None


class TicketComment(BaseModel):
    id: int
    ticket_id: str
    author_id: Optional[str] = None
    author_name: str = "System"
    body: str
    is_private: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class TicketCommentCreate(BaseModel):
    body: str = Field(..., min_length=1)
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
    ticket_ids: List[str] = Field(..., min_length=1)
    action: str = Field(..., description="assign | close | set_priority | set_category")
    value: Optional[str] = None


# ── Authentication ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


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


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3)
    title: Optional[str] = None
    role: str = "agent"  # admin | supervisor | agent
    password: Optional[str] = None  # optional, generated if omitted


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    title: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class AuthResponse(BaseModel):
    token: str
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
    status: str = "draft"
    views: int = 0
    helpful: int = 0
    not_helpful: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KbArticleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    category: Optional[str] = None
    tags: Optional[str] = None
    status: str = "draft"


class KbArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    status: Optional[str] = None


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
    change_id: str
    approver_id: str


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
    description: str = ""
    reporter: str = Field(..., min_length=1)
    priority: str = "P3"

class PortalTicketOut(BaseModel):
    id: str
    subject: str
    status: str
    priority: str
    reporter: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
