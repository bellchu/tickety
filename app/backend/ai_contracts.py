"""Strict contracts for every LLM-backed Tickety OPS Tower task.

Provider JSON mode is only a formatting hint.  These models are the actual
trust boundary before generated data can affect ticket state or be returned to
users.
"""

import math
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
RoutingDomain = Literal[
    "service_desk",
    "endpoint_hardware",
    "end_user_software",
    "network",
    "access",
    "enterprise_business_application",
    "development_engineering",
    "ambiguous",
    "unknown",
]
RoutingAbstentionReason = Literal[
    "catalog_unavailable",
    "catalog_stale",
    "invalid_output",
    "low_confidence",
    "missing_ai_category",
    "model_failure",
    "unsupported_ai_category",
    "untrusted_ai_status",
    "workspace_mismatch",
]
ResolverGroup = Literal[
    "INFRA_HELPDESK",
    "INFRA_NETWORK",
    "INFRA_SYSTEMS",
    "INFRA_ARCH",
    "APP_CRM_ALMO",
    "APP_CRM_JAM",
    "APP_RPA",
    "APP_SQL",
    "APP_JDE",
    "APP_JDE_BA",
    "APP_KORBER",
    "APP_AS400",
    "APP_WEB",
    "APP_EDI_API",
    "APP_PM",
]
AI_RESOLVER_TEAMS = (
    "INFRA_HELPDESK",
    "INFRA_NETWORK",
    "INFRA_SYSTEMS",
    "INFRA_ARCH",
    "APP_CRM_ALMO",
    "APP_CRM_JAM",
    "APP_RPA",
    "APP_SQL",
    "APP_JDE",
    "APP_JDE_BA",
    "APP_KORBER",
    "APP_AS400",
    "APP_WEB",
    "APP_EDI_API",
    "APP_PM",
)
# Backward-compatible type name for modules that have not yet moved to the
# dedicated routing contract. It has the same closed resolver-code surface.
ResolverTeam = ResolverGroup
RoutingServiceText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[^\r\n]+$",
    ),
]
RoutingReasonText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=1_000,
        pattern=r"^[^\r\n]+$",
    ),
]


class StrictAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TriageAnalysis(StrictAIModel):
    sentiment: Literal["Business-Critical", "High-Impact", "Moderate", "Neutral", "Positive"]
    category: Literal["Hardware", "Software", "Network", "Access Request", "Other"]
    priority: Literal["P1", "P2", "P3", "P4"]
    mood: Literal["critical", "urgent", "concerned", "neutral", "satisfied"]
    action: Literal["escalate", "respond", "route"]
    reasoning: ShortText


class ResolverRoutingAnalysis(StrictAIModel):
    """Closed, dedicated resolver-group decision returned by the routing model."""

    primary_group: ResolverGroup
    secondary_group: Optional[ResolverGroup]
    confidence: float = Field(ge=0.0, le=1.0)
    business_context: Literal["ALMO", "JAM", "UNKNOWN"]
    scope: Literal["single_user", "multiple_users", "service_wide", "unknown"]
    affected_service: RoutingServiceText
    failure_domain: RoutingServiceText
    reason: RoutingReasonText

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_numeric_confidence(cls, value):
        # JSON booleans are integers in Python, so reject them explicitly.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("confidence must be a JSON number")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("confidence must be finite")
        # Keep the persisted/content-hashed representation stable across
        # database drivers that normalize IEEE-754 negative zero.
        return 0.0 if numeric == 0 else numeric

    @field_validator("affected_service", "failure_domain", "reason")
    @classmethod
    def validate_single_line_text(cls, value: str) -> str:
        if len(value.splitlines()) != 1:
            raise ValueError("routing text fields must contain exactly one line")
        return value

    @model_validator(mode="after")
    def validate_routing_decision(self):
        if self.secondary_group == self.primary_group:
            raise ValueError("secondary group must differ from primary group")
        if self.secondary_group == "INFRA_HELPDESK":
            raise ValueError("INFRA_HELPDESK cannot be a secondary group")
        groups = {self.primary_group, self.secondary_group}
        if "APP_CRM_ALMO" in groups and self.business_context != "ALMO":
            raise ValueError("APP_CRM_ALMO requires ALMO business context")
        if "APP_CRM_JAM" in groups and self.business_context != "JAM":
            raise ValueError("APP_CRM_JAM requires JAM business context")
        if (
            self.affected_service.casefold() == "unknown"
            or self.failure_domain.casefold() == "unknown"
        ) and self.confidence >= 0.60:
            raise ValueError(
                "unknown service or failure domain requires confidence below 0.60"
            )
        return self


class SuggestedReply(StrictAIModel):
    suggested_response: LongText


class TicketSummary(StrictAIModel):
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]


class ResolutionAnalysis(StrictAIModel):
    root_cause_hypothesis: ShortText
    resolution_steps: list[ShortText] = Field(min_length=1, max_length=12)
    confidence: Literal["high", "medium", "low"]
    estimated_effort: Literal["low", "medium", "high"]
    escalation_advice: ShortText
    preventive_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1_000)] = ""


class RoutingCandidate(StrictAIModel):
    """A closed-set resolver-group candidate supplied by a validated catalog."""

    group_id: Identifier
    workspace_id: Identifier
    rank: int = Field(ge=1, le=10)
    score: float = Field(ge=0.0, le=1.0)


class RoutingRecommendation(StrictAIModel):
    """Strict output contract for the future catalog-bound routing ranker."""

    schema_version: Literal["1"] = "1"
    status: Literal["ai_recommended", "unrouted_review"]
    domain: RoutingDomain
    candidates: list[RoutingCandidate] = Field(default_factory=list, max_length=10)
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence_reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=1_000),
    ] = ""
    abstention_reason: Optional[RoutingAbstentionReason] = None
    workspace_id: Identifier
    source_context_hash: Digest
    catalog_version: Optional[Identifier] = None
    catalog_hash: Optional[Digest] = None
    policy_version: Identifier
    model_version: Optional[Identifier] = None

    @model_validator(mode="after")
    def validate_routing_invariants(self):
        ranks = [candidate.rank for candidate in self.candidates]
        if ranks != list(range(1, len(self.candidates) + 1)):
            raise ValueError("routing candidate ranks must be consecutive and ordered")
        group_ids = [candidate.group_id for candidate in self.candidates]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("routing candidate group IDs must be unique")
        scores = [candidate.score for candidate in self.candidates]
        if scores != sorted(scores, reverse=True):
            raise ValueError("routing candidates must be ordered by descending score")
        if any(candidate.workspace_id != self.workspace_id for candidate in self.candidates):
            raise ValueError("routing candidate workspace must match the recommendation")
        if self.status == "ai_recommended":
            if not self.candidates:
                raise ValueError("an AI recommendation requires at least one candidate")
            if not self.catalog_version or not self.catalog_hash or not self.model_version:
                raise ValueError("an AI recommendation requires catalog and model provenance")
            if self.abstention_reason is not None:
                raise ValueError("an AI recommendation cannot include an abstention reason")
        else:
            if self.candidates:
                raise ValueError("an unrouted result cannot include candidates")
            if self.abstention_reason is None:
                raise ValueError("an unrouted result requires an abstention reason")
        return self


class GroundedItem(StrictAIModel):
    text: ShortText
    citations: list[str] = Field(min_length=1, max_length=10)


class TicketIntelligenceAnswer(StrictAIModel):
    answer: LongText
    answer_citations: list[str] = Field(min_length=1, max_length=10)
    findings: list[GroundedItem] = Field(default_factory=list, max_length=12)
    confidence: Literal["high", "medium", "low"] = "low"
