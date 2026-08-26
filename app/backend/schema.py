import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List, Literal
from datetime import datetime, timezone

from .ai_contracts import AI_RESOLVER_TEAMS, ResolverGroup


def _reject_nul(value: Optional[str]) -> Optional[str]:
    if value is not None and "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


def _utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize API datetimes to the database's UTC-naive convention."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class StrictWriteModel(BaseModel):
    """Reject misspelled or read-only fields instead of reporting false success."""

    model_config = ConfigDict(extra="forbid")


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
    ai_suggested_team: Optional[str] = None
    ai_secondary_team: Optional[str] = None
    ai_routing_confidence: Optional[float] = None
    ai_business_context: Optional[str] = None
    ai_routing_scope: Optional[str] = None
    ai_affected_service: Optional[str] = None
    ai_failure_domain: Optional[str] = None
    ai_routing_reason: Optional[str] = None
    recommended_team: str = "Unrouted / Review"
    recommended_team_basis: Literal[
        "source_group",
        "ai_team",
        "ai_category",
        "source_category",
        "not_applicable",
        "unrouted_review",
    ] = "unrouted_review"
    routing_status: Literal[
        "source_group_assignment",
        "ai_team_recommendation",
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

    @model_validator(mode="after")
    def hide_untrusted_route_bundle(self):
        """Never serialize raw routing columns without exact route provenance."""
        if self.recommended_team_basis != "ai_team":
            self.ai_suggested_team = None
            self.ai_secondary_team = None
            self.ai_routing_confidence = None
            self.ai_business_context = None
            self.ai_routing_scope = None
            self.ai_affected_service = None
            self.ai_failure_domain = None
            self.ai_routing_reason = None
        return self


class AIAnalysis(BaseModel):
    sentiment: str
    category: str
    priority: str
    mood: str
    action: str
    reasoning: str
    suggested_response: Optional[str] = None


class ResolverCatalogScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(..., min_length=1, max_length=64)
    workspace_id: Optional[str] = Field(None, max_length=255)


class ResolverCatalogThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_group_tickets: int = Field(..., ge=1, le=10_000)
    minimum_distinct_agents: int = Field(..., ge=1, le=10_000)
    minimum_top_share: float = Field(..., ge=0.0, le=1.0)
    minimum_runner_up_lead: float = Field(..., ge=0.0, le=1.0)
    minimum_evidence_coverage: float = Field(..., ge=0.0, le=1.0)
    minimum_confidence: float = Field(..., ge=0.0, le=1.0)
    history_ticket_limit: int = Field(..., ge=1, le=100_000)


class ResolverCatalogCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ticket_count: int = Field(..., ge=0)
    analyzed_ticket_count: int = Field(..., ge=0)
    trusted_route_ticket_count: int = Field(..., ge=0)
    membership_eligible_ticket_count: int = Field(..., ge=0)
    unambiguous_ticket_count: int = Field(..., ge=0)
    ambiguous_membership_ticket_count: int = Field(..., ge=0)
    without_membership_evidence_ticket_count: int = Field(..., ge=0)
    excluded_ambiguous_or_unmatched_ticket_count: int = Field(..., ge=0)
    history_truncated: bool
    catalog_scopes_truncated: bool

    @model_validator(mode="after")
    def validate_coverage_counts(self):
        if self.analyzed_ticket_count != self.candidate_ticket_count:
            raise ValueError("analyzed count must match the bounded candidate set")
        if self.trusted_route_ticket_count > self.analyzed_ticket_count:
            raise ValueError("trusted routes cannot exceed analyzed candidates")
        if self.membership_eligible_ticket_count > self.trusted_route_ticket_count:
            raise ValueError("membership evidence cannot exceed trusted routes")
        if (
            self.unambiguous_ticket_count
            + self.ambiguous_membership_ticket_count
            > self.membership_eligible_ticket_count
        ):
            raise ValueError("membership evidence counts exceed eligible tickets")
        if self.without_membership_evidence_ticket_count != (
            self.trusted_route_ticket_count - self.membership_eligible_ticket_count
        ):
            raise ValueError("unmatched membership count is inconsistent")
        if self.excluded_ambiguous_or_unmatched_ticket_count != (
            self.trusted_route_ticket_count - self.unambiguous_ticket_count
        ):
            raise ValueError("excluded evidence count is inconsistent")
        return self


class ResolverCatalogRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolver_code: ResolverGroup
    scope: ResolverCatalogScope
    provider_group_id: str = Field(..., min_length=1, max_length=255)
    provider_group_name: str = Field(..., min_length=1, max_length=255)
    trusted_ticket_count: int = Field(..., ge=0)
    membership_eligible_ticket_count: int = Field(..., ge=0)
    unambiguous_ticket_count: int = Field(..., ge=0)
    ambiguous_membership_ticket_count: int = Field(..., ge=0)
    evidence_ticket_count: int = Field(..., ge=0)
    direct_assignment_ticket_count: int = Field(..., ge=0)
    sole_membership_ticket_count: int = Field(..., ge=0)
    distinct_agent_count: int = Field(..., ge=0)
    candidate_group_count: int = Field(..., ge=1)
    runner_up_ticket_count: int = Field(..., ge=0)
    group_share: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    runner_up_lead: float = Field(..., ge=0.0, le=1.0)
    evidence_coverage: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., min_length=1, max_length=500)
    advisory_only: Literal[True]

    @model_validator(mode="after")
    def validate_aggregate_evidence(self):
        if self.direct_assignment_ticket_count + self.sole_membership_ticket_count != (
            self.evidence_ticket_count
        ):
            raise ValueError("recommendation evidence split is inconsistent")
        if self.evidence_ticket_count > self.unambiguous_ticket_count:
            raise ValueError("group evidence cannot exceed unambiguous evidence")
        if self.unambiguous_ticket_count > self.membership_eligible_ticket_count:
            raise ValueError("unambiguous evidence cannot exceed eligible evidence")
        if self.membership_eligible_ticket_count > self.trusted_ticket_count:
            raise ValueError("eligible evidence cannot exceed trusted evidence")
        if self.distinct_agent_count > self.evidence_ticket_count:
            raise ValueError("agent aggregate cannot exceed group evidence")
        if self.runner_up_ticket_count > self.unambiguous_ticket_count:
            raise ValueError("runner-up evidence cannot exceed the evidence set")
        if self.confidence > self.group_share:
            raise ValueError("sample-adjusted confidence cannot exceed group share")
        return self


ResolverCatalogGapReason = Literal[
    "no_trusted_history",
    "no_unambiguous_membership_evidence",
    "insufficient_evidence_coverage",
    "insufficient_ticket_sample",
    "insufficient_agent_diversity",
    "low_dominance",
    "ambiguous_lead",
    "catalog_group_unavailable",
    "evidence_truncated",
    "low_sample_adjusted_confidence",
]


class ResolverCatalogGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolver_code: ResolverGroup
    scope: ResolverCatalogScope
    reason: ResolverCatalogGapReason
    trusted_ticket_count: int = Field(..., ge=0)
    membership_eligible_ticket_count: int = Field(..., ge=0)
    unambiguous_ticket_count: int = Field(..., ge=0)
    ambiguous_membership_ticket_count: int = Field(..., ge=0)
    leading_ticket_count: int = Field(..., ge=0)
    leading_distinct_agent_count: int = Field(..., ge=0)
    candidate_group_count: int = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_gap_aggregates(self):
        if self.membership_eligible_ticket_count > self.trusted_ticket_count:
            raise ValueError("eligible gap evidence cannot exceed trusted evidence")
        if (
            self.unambiguous_ticket_count
            + self.ambiguous_membership_ticket_count
            > self.membership_eligible_ticket_count
        ):
            raise ValueError("gap membership counts exceed eligible evidence")
        if self.leading_ticket_count > self.unambiguous_ticket_count:
            raise ValueError("leading gap evidence exceeds unambiguous evidence")
        if self.leading_distinct_agent_count > self.leading_ticket_count:
            raise ValueError("leading agent aggregate exceeds leading evidence")
        return self


class ResolverCatalogRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    generated_at: datetime
    window_start_at: datetime
    window_days: Literal[365]
    advisory_only: Literal[True]
    mapping_applied: Literal[False]
    no_mapping_applied: Literal[True]
    thresholds: ResolverCatalogThresholds
    coverage: ResolverCatalogCoverage
    ready: bool
    scopes: List[ResolverCatalogScope] = Field(default_factory=list, max_length=50)
    recommendations: List[ResolverCatalogRecommendationItem] = Field(
        default_factory=list,
        max_length=750,
    )
    scoped_gaps: List[ResolverCatalogGap] = Field(
        default_factory=list,
        max_length=750,
    )
    unmapped_codes: List[ResolverGroup] = Field(default_factory=list, max_length=15)
    unmapped_codes_scope: Optional[ResolverCatalogScope] = None

    @model_validator(mode="after")
    def validate_recommendation_partition(self):
        scope_keys = {
            (scope.binding_id, scope.provider, scope.workspace_id)
            for scope in self.scopes
        }
        if len(scope_keys) != len(self.scopes):
            raise ValueError("catalog scopes must be unique")
        recommendation_keys = {
            (
                item.scope.binding_id,
                item.scope.provider,
                item.scope.workspace_id,
                item.resolver_code,
            )
            for item in self.recommendations
        }
        if len(recommendation_keys) != len(self.recommendations):
            raise ValueError("resolver recommendations must be unique per scope")
        gap_keys = {
            (
                item.scope.binding_id,
                item.scope.provider,
                item.scope.workspace_id,
                item.resolver_code,
            )
            for item in self.scoped_gaps
        }
        if len(gap_keys) != len(self.scoped_gaps):
            raise ValueError("resolver gaps must be unique per scope")
        if recommendation_keys.intersection(gap_keys):
            raise ValueError("a scoped resolver code cannot be mapped and a gap")
        item_scope_keys = {key[:3] for key in recommendation_keys.union(gap_keys)}
        if not item_scope_keys.issubset(scope_keys):
            raise ValueError("recommendation evidence references an unknown scope")
        for scope_key in scope_keys:
            scoped_codes = {
                key[3] for key in recommendation_keys.union(gap_keys)
                if key[:3] == scope_key
            }
            if scoped_codes != set(AI_RESOLVER_TEAMS):
                raise ValueError("each catalog scope must classify every resolver code")
        if self.ready != bool(self.recommendations):
            raise ValueError("readiness must reflect emitted recommendations")
        if len(self.unmapped_codes) != len(set(self.unmapped_codes)):
            raise ValueError("unmapped resolver codes must be unique")
        if not self.scopes:
            if set(self.unmapped_codes) != set(AI_RESOLVER_TEAMS):
                raise ValueError("an empty catalog must mark every resolver code unmapped")
            if self.unmapped_codes_scope is not None:
                raise ValueError("an empty catalog cannot name an unmapped scope")
        elif len(self.scopes) == 1:
            if self.unmapped_codes_scope != self.scopes[0]:
                raise ValueError("single-scope unmapped codes require that exact scope")
        elif self.unmapped_codes or self.unmapped_codes_scope is not None:
            raise ValueError("multi-scope gaps must remain scoped")
        return self


class RoutingAutomationFeatureState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    effective: bool


class RoutingTriageManagementStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    generated_at: datetime
    advisory_only: Literal[True]
    catalog_mapping_status: Literal["pending"]
    catalog_mapping_write_available: Literal[False]
    automation_controls_editable: bool
    rule_controls_editable: bool
    triage_queue_action_available: Literal[True]
    auto_triage: RoutingAutomationFeatureState
    auto_routing: RoutingAutomationFeatureState
    resolver_groups: List[ResolverGroup] = Field(..., min_length=15, max_length=15)

    @field_validator("resolver_groups")
    @classmethod
    def validate_resolver_groups(cls, value):
        if len(set(value)) != 15 or set(value) != set(AI_RESOLVER_TEAMS):
            raise ValueError("resolver_groups must contain the closed resolver taxonomy")
        return value


class RoutingTriageAutomationUpdate(StrictWriteModel):
    auto_triage_enabled: bool
    auto_routing_enabled: bool


class AgentResolverTeamMappingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    user_name: str
    title: Optional[str] = None
    role: Literal["admin", "supervisor", "agent"]
    is_active: bool
    resolver_groups: List[ResolverGroup] = Field(default_factory=list, max_length=15)
    updated_at: Optional[datetime] = None

    @field_validator("resolver_groups")
    @classmethod
    def unique_groups(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("resolver groups must be unique")
        return value


class AgentResolverTeamMappingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    editable: bool
    items: List[AgentResolverTeamMappingItem]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=200)
    offset: int = Field(..., ge=0)
    has_more: bool


class AgentResolverTeamMappingUpdate(StrictWriteModel):
    resolver_groups: List[ResolverGroup] = Field(default_factory=list, max_length=15)
    expected_resolver_groups: List[ResolverGroup] = Field(default_factory=list, max_length=15)

    @field_validator("resolver_groups", "expected_resolver_groups")
    @classmethod
    def unique_mapping_groups(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("resolver groups must be unique")
        return value


class RoutingRuleBase(StrictWriteModel):
    name: str = Field(..., min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _./&()-]*$")
    description: Optional[str] = Field(None, max_length=240)
    enabled: bool = True
    priority: int = Field(100, ge=1, le=1000)
    business_context: Optional[Literal["ALMO", "JAM", "UNKNOWN"]] = None
    scope: Optional[Literal["single_user", "multiple_users", "service_wide", "unknown"]] = None
    service_contains: Optional[str] = Field(None, min_length=2, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _./&()-]*$")
    failure_domain_contains: Optional[str] = Field(None, min_length=2, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _./&()-]*$")
    primary_group: ResolverGroup
    secondary_group: Optional[ResolverGroup] = None

    @field_validator("name", "description", "service_contains", "failure_domain_contains")
    @classmethod
    def normalize_rule_text(cls, value):
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_rule(self):
        if not any((
            self.business_context,
            self.scope,
            self.service_contains,
            self.failure_domain_contains,
        )):
            raise ValueError("at least one structured match condition is required")
        if self.secondary_group == self.primary_group:
            raise ValueError("secondary group must differ from primary group")
        if self.secondary_group == "INFRA_HELPDESK":
            raise ValueError("Helpdesk cannot be configured as a secondary group")
        return self


class RoutingRuleCreate(RoutingRuleBase):
    pass


class RoutingRuleUpdate(RoutingRuleBase):
    expected_version: int = Field(..., ge=1)


class RoutingRuleOut(RoutingRuleBase):
    id: int
    version: int = Field(..., ge=1)
    created_at: datetime
    updated_at: datetime


class RoutingRuleListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    editable: bool
    core_policy_protected: Literal[True]
    items: List[RoutingRuleOut] = Field(default_factory=list, max_length=200)


class TriageResult(BaseModel):
    ticket_id: str
    sentiment: str
    category: str
    priority: str
    mood: str
    complexity: int
    action: str
    recommended_team: str
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
    not_applicable: int = 0
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
        "not_applicable",
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
    http_status: Optional[int] = None
    failure_kind: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    dispatched: bool = False
    estimated_tokens: int = 0
    created_at: datetime


class AILLMCallSummary(BaseModel):
    calls: int = 0
    successful: int = 0
    failed_attempts: int = 0
    deferred: int = 0
    total_tokens: int = 0
    average_latency_ms: int = 0
    last_call_at: Optional[datetime] = None


class AIProviderCooldownStatus(BaseModel):
    provider: str
    reason: str
    retry_at: datetime


class AIStatusResponse(BaseModel):
    generated_at: datetime
    automation: List[AIAutomationFeatureStatus]
    active_integration_bindings: int = 0
    automatic_ai_bindings: int = 0
    active_routing_backlog_enabled: bool = False
    queue: AIQueueStatusSummary
    view: Literal[
        "all", "active", "retry_scheduled", "attention", "completed",
        "not_analyzed", "not_applicable",
    ]
    search: str = ""
    tasks: List[AITaskStatusItem]
    total_tasks: int
    limit: int
    offset: int
    provider_cooldown: Optional[AIProviderCooldownStatus] = None
    recent_calls: List[AILLMCallStatusItem]
    calls_24h: AILLMCallSummary


class AIRetryScheduleRequest(BaseModel):
    scheduled_at: datetime


class AIRetryQueueActionResponse(BaseModel):
    action: Literal["clear", "retry_all_now", "retry_now", "reschedule"]
    affected: int
    ticket_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    dispatch_blocked_until: Optional[datetime] = None


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
    groups_created: int = 0
    groups_updated: int = 0
    groups_unchanged: int = 0
    groups_deactivated: int = 0
    memberships: int = 0
    group_errors: int = 0


class ExternalGroup(BaseModel):
    id: str
    binding_id: str
    provider: str
    external_id: str
    workspace_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    active: bool = True
    source_updated_at: Optional[datetime] = None
    fetched_at: datetime


class UserExternalIdentityLinkOut(BaseModel):
    id: int
    user_id: str
    external_user_id: str
    binding_id: str
    provider: str
    external_id: str
    external_name: str
    external_email: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class UserExternalIdentityLinkUpdate(BaseModel):
    external_user_id: str = Field(..., min_length=1, max_length=36)


class AgentWorkspaceTeam(BaseModel):
    id: str
    external_id: str
    name: str
    workspace_id: Optional[str] = None
    membership_kind: Literal["member", "observer"] = "member"
    ticket_count: int = 0
    unassigned_count: int = 0


class AgentWorkspaceIdentity(BaseModel):
    link_id: int
    external_user_id: str
    external_id: str
    name: str
    email: Optional[str] = None
    binding_id: str
    provider: str


class AgentWorkspaceBootstrap(BaseModel):
    identity: Optional[AgentWorkspaceIdentity] = None
    teams: List[AgentWorkspaceTeam] = Field(default_factory=list)
    teams_truncated: bool = False
    counts: dict[str, int] = Field(default_factory=dict)


class AgentWorkspaceTicket(Ticket):
    assignment_scope: Literal["mine", "team"]
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    is_unread: bool = True
    is_starred: bool = False
    follow_up_at: Optional[datetime] = None
    needs_reply: bool = False
    sla_at_risk: bool = False
    next_best_score: int = 0
    next_best_reasons: List[str] = Field(default_factory=list)


class AgentTicketStateUpdate(BaseModel):
    mark_seen: bool = False
    starred: Optional[bool] = None
    follow_up_at: Optional[datetime] = None
    clear_follow_up: bool = False


class EmailRecipient(BaseModel):
    id: str
    name: str
    email: str
    audience: Literal["agents", "users"]
    source: str
    title: Optional[str] = None


class EmailRecipientList(BaseModel):
    audience: Literal["agents", "users"]
    recipients: List[EmailRecipient]
    total: int
    truncated: bool = False


class EmailProviderStatus(BaseModel):
    provider: Literal["sendgrid"] = "sendgrid"
    configured: bool
    api_key_set: bool
    from_email_set: bool
    from_name: str


class EmailSendRequest(BaseModel):
    audience: Literal["agents", "users"]
    recipient_ids: List[str] = Field(..., min_length=1, max_length=50)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=50_000)

    @field_validator("recipient_ids")
    @classmethod
    def validate_recipient_ids(cls, value: List[str]) -> List[str]:
        normalized = [recipient_id.strip() for recipient_id in value]
        if any(not recipient_id or len(recipient_id) > 300 for recipient_id in normalized):
            raise ValueError("Recipient IDs are invalid")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Recipient IDs must be unique")
        return normalized

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        subject = value.strip()
        if not subject or any(ord(character) < 32 or ord(character) == 127 for character in subject):
            raise ValueError("Subject contains invalid control characters")
        return subject

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        body = value.strip()
        if not body or "\x00" in body:
            raise ValueError("Email body is invalid")
        return body


class EmailSendResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    recipient_count: int
    message_id: Optional[str] = None


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
    SENDGRID_API_KEY: Optional[str] = None
    SENDGRID_FROM_EMAIL: Optional[str] = None
    SENDGRID_FROM_NAME: Optional[str] = None
    SENDGRID_REPLY_TO_EMAIL: Optional[str] = None
    EMAIL_SENDS_PER_MINUTE: Optional[str] = None
    EMAIL_RECIPIENTS_PER_DAY: Optional[str] = None
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

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


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
    email: str = Field(..., min_length=3, max_length=320)
    title: Optional[str] = None
    role: Literal["admin", "supervisor", "agent"] = "agent"
    password: Optional[str] = None  # optional, generated if omitted

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip().lower()
        if len(normalized) < 3:
            raise ValueError("must be at least 3 characters")
        return normalized


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = Field(None, min_length=3, max_length=320)
    title: Optional[str] = None
    role: Optional[Literal["admin", "supervisor", "agent"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_nul(value)
        normalized = value.strip().lower()
        if len(normalized) < 3:
            raise ValueError("must be at least 3 characters")
        return normalized


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
    name: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=100)
    color: Literal["slate", "blue", "amber", "red", "emerald", "moss", "clay"] = "slate"
    is_open: bool = Field(default=True, strict=True)
    is_terminal: bool = Field(default=False, strict=True)
    sort_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]*", normalized):
            raise ValueError("name must use letters, numbers, spaces, hyphens, or underscores")
        return normalized

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_lifecycle(self):
        if self.is_open and self.is_terminal:
            raise ValueError("a terminal status cannot count as open")
        return self


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
    name: str = Field(..., min_length=1, max_length=32)
    label: str = Field(..., min_length=1, max_length=100)
    color: Literal["slate", "blue", "amber", "red", "emerald", "moss", "clay"] = "slate"
    sla_hours: Optional[int] = Field(default=None, ge=1, le=8_760)
    weight: int = Field(default=10, ge=1, le=1_000)
    sort_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]*", normalized):
            raise ValueError("name must use letters, numbers, spaces, hyphens, or underscores")
        return normalized

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


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


class ProjectCreate(StrictWriteModel):
    name: str = Field(..., min_length=1, max_length=120)
    key: str = Field(..., min_length=2, max_length=20)
    description: str = Field("", max_length=20_000)
    lead_id: Optional[str] = Field(None, max_length=255)

    @field_validator("name", "key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()

    @field_validator("lead_id")
    @classmethod
    def normalize_optional_id(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None


class ProjectUpdate(StrictWriteModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=20_000)
    lead_id: Optional[str] = Field(None, max_length=255)
    status: Optional[Literal["active", "archived"]] = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        return value.strip() if value is not None else None

    @field_validator("lead_id")
    @classmethod
    def normalize_optional_id(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("name", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


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


class ServiceItemCreate(StrictWriteModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=20_000)
    category: Optional[str] = Field(None, max_length=200)
    pricing: Optional[str] = Field(None, max_length=500)
    sla_hours: Optional[int] = Field(None, ge=1, le=8_760)
    approval_required: bool = Field(False, strict=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()

    @field_validator("category", "pricing")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None


class ServiceItemUpdate(StrictWriteModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=20_000)
    category: Optional[str] = Field(None, max_length=200)
    pricing: Optional[str] = Field(None, max_length=500)
    sla_hours: Optional[int] = Field(None, ge=1, le=8_760)
    approval_required: Optional[bool] = Field(None, strict=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        return value.strip() if value is not None else None

    @field_validator("category", "pricing")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("name", "approval_required"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


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


class ServiceRequestCreate(StrictWriteModel):
    ticket_id: str = Field(..., min_length=1, max_length=255)
    service_item_id: str = Field(..., min_length=1, max_length=255)
    quantity: int = Field(1, ge=1, le=1_000)
    justification: str = Field("", max_length=20_000)

    @field_validator("ticket_id", "service_item_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("justification")
    @classmethod
    def normalize_justification(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()


class ServiceRequestApprovalDecision(StrictWriteModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field("", max_length=5_000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()


class ServiceRequestFulfillmentUpdate(StrictWriteModel):
    status: Literal["fulfilled", "cancelled"]
    delivery_notes: str = Field("", max_length=20_000)

    @field_validator("delivery_notes")
    @classmethod
    def normalize_delivery_notes(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()


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


class ProblemCreate(StrictWriteModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=20_000)
    priority: Literal["P1", "P2", "P3", "P4"] = "P2"
    category: Optional[str] = Field(None, max_length=200)
    assigned_to: Optional[str] = Field(None, max_length=255)
    impact_scope: Optional[str] = Field(None, max_length=2_000)

    @field_validator("title", "priority")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()

    @field_validator("category", "assigned_to", "impact_scope")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None


class ProblemUpdate(StrictWriteModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=20_000)
    status: Optional[Literal[
        "New", "Under Investigation", "Known Error", "Resolved", "Closed"
    ]] = None
    priority: Optional[Literal["P1", "P2", "P3", "P4"]] = None
    category: Optional[str] = Field(None, max_length=200)
    assigned_to: Optional[str] = Field(None, max_length=255)
    root_cause: Optional[str] = Field(None, max_length=20_000)
    workaround: Optional[str] = Field(None, max_length=20_000)
    resolution: Optional[str] = Field(None, max_length=20_000)
    impact_scope: Optional[str] = Field(None, max_length=2_000)

    @field_validator("title", "status", "priority")
    @classmethod
    def normalize_required_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        return value.strip() if value is not None else None

    @field_validator(
        "category", "assigned_to", "root_cause", "workaround", "resolution",
        "impact_scope",
    )
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("title", "status", "priority"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


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


class ChangeCreate(StrictWriteModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=20_000)
    change_type: Literal["Normal", "Standard", "Emergency"] = "Normal"
    status: Literal["Draft", "Submitted"] = "Draft"
    priority: Literal["P1", "P2", "P3", "P4"] = "P2"
    risk_level: Literal["Low", "Medium", "High"] = "Medium"
    impact: Optional[str] = Field(None, max_length=2_000)
    rollback_plan: Optional[str] = Field(None, max_length=20_000)
    test_plan: Optional[str] = Field(None, max_length=20_000)
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("change_type", "status", "priority", "risk_level")
    @classmethod
    def normalize_choice(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()

    @field_validator("impact", "rollback_plan", "test_plan", "assigned_to")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None

    @field_validator("scheduled_start", "scheduled_end")
    @classmethod
    def normalize_schedule(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _utc_naive(value)


class ChangeUpdate(StrictWriteModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=20_000)
    status: Optional[Literal[
        "Draft", "Submitted", "CAB Review", "Approved", "In Progress",
        "Completed", "Rejected", "Cancelled",
    ]] = None
    change_type: Optional[Literal["Normal", "Standard", "Emergency"]] = None
    priority: Optional[Literal["P1", "P2", "P3", "P4"]] = None
    risk_level: Optional[Literal["Low", "Medium", "High"]] = None
    impact: Optional[str] = Field(None, max_length=2_000)
    rollback_plan: Optional[str] = Field(None, max_length=20_000)
    test_plan: Optional[str] = Field(None, max_length=20_000)
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("status", "change_type", "priority", "risk_level")
    @classmethod
    def normalize_choice(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        return value.strip() if value is not None else None

    @field_validator("impact", "rollback_plan", "test_plan", "assigned_to")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None

    @field_validator("scheduled_start", "scheduled_end")
    @classmethod
    def normalize_schedule(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _utc_naive(value)

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("title", "status", "change_type", "priority", "risk_level"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


class ChangeApprovalOut(BaseModel):
    id: int
    change_id: str
    approver_id: Optional[str] = None
    approver_name: Optional[str] = None
    decision: Optional[str] = None
    comment: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChangeApprovalCreate(StrictWriteModel):
    approver_id: str = Field(..., min_length=1, max_length=255)

    @field_validator("approver_id")
    @classmethod
    def normalize_approver_id(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ChangeApprovalDecision(StrictWriteModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field("", max_length=5_000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        _reject_nul(value)
        return value.strip()


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


class AssetCreate(StrictWriteModel):
    name: str = Field(..., min_length=1, max_length=200)
    asset_type: Literal[
        "Hardware", "Software", "License", "Network", "Facility"
    ]
    asset_tag: Optional[str] = Field(None, max_length=255)
    status: Literal["In Use", "Available", "Retired", "Broken", "Lost"] = "In Use"
    owner_id: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    vendor: Optional[str] = Field(None, max_length=255)
    model: Optional[str] = Field(None, max_length=255)
    purchase_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    cost: Optional[float] = Field(None, ge=0, le=1_000_000_000_000)
    notes: Optional[str] = Field(None, max_length=20_000)

    @field_validator("name", "asset_type", "status")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("asset_tag", "owner_id", "location", "vendor", "model", "notes")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None

    @field_validator("purchase_date", "warranty_expiry")
    @classmethod
    def normalize_datetime(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _utc_naive(value)


class AssetUpdate(StrictWriteModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    asset_type: Optional[Literal[
        "Hardware", "Software", "License", "Network", "Facility"
    ]] = None
    asset_tag: Optional[str] = Field(None, max_length=255)
    status: Optional[Literal[
        "In Use", "Available", "Retired", "Broken", "Lost"
    ]] = None
    owner_id: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    vendor: Optional[str] = Field(None, max_length=255)
    model: Optional[str] = Field(None, max_length=255)
    purchase_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    cost: Optional[float] = Field(None, ge=0, le=1_000_000_000_000)
    notes: Optional[str] = Field(None, max_length=20_000)

    @field_validator("name", "asset_type", "status")
    @classmethod
    def normalize_required_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("asset_tag", "owner_id", "location", "vendor", "model", "notes")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        _reject_nul(value)
        normalized = value.strip() if value is not None else ""
        return normalized or None

    @field_validator("purchase_date", "warranty_expiry")
    @classmethod
    def normalize_datetime(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _utc_naive(value)

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("name", "asset_type", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


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
    recipient_email: Optional[str] = None
    recipient_name: Optional[str] = None
    response_expires_at: Optional[datetime] = None
    delivery_status: Literal["pending", "uncertain", "accepted", "failed", "legacy"] = "legacy"
    delivery_message_id: Optional[str] = None
    delivery_error: Optional[str] = None
    delivery_attempted_at: Optional[datetime] = None
    sent_by: Optional[str] = None
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SurveySend(BaseModel):
    ticket_id: str = Field(..., min_length=1, max_length=255)
    template_id: int = Field(1, ge=1)

    @field_validator("ticket_id")
    @classmethod
    def normalize_ticket_id(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class SurveyResponseCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field("", max_length=2_000)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Survey comment is invalid")
        return value.strip()


class SurveyPortalLookupRequest(BaseModel):
    # Shape validation is intentionally completed in the handler so malformed
    # and unknown capabilities receive the same public response.
    token: str = Field("", max_length=512)


class SurveyPortalQuestion(BaseModel):
    question: str
    expires_at: datetime


class SurveyPortalResponseRequest(SurveyResponseCreate):
    token: str = Field("", max_length=512)


class SurveyPortalSubmitted(BaseModel):
    status: Literal["submitted"] = "submitted"


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
    ticket_id: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=10_000)
    minutes: int = Field(..., ge=1, le=1_440)

    @field_validator("ticket_id", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        _reject_nul(value)
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


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
