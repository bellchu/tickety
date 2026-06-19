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
