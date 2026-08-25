"""Strict contracts for every LLM-backed Tickety task.

Provider JSON mode is only a formatting hint.  These models are the actual
trust boundary before generated data can affect ticket state or be returned to
users.
"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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
AI_RESOLVER_TEAMS = (
    "Application Support",
    "Identity and Access",
    "Network Operations",
    "Workplace Technology",
)
ResolverTeam = Literal[
    "Application Support",
    "Identity and Access",
    "Network Operations",
    "Workplace Technology",
]


class StrictAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TriageAnalysis(StrictAIModel):
    sentiment: Literal["Business-Critical", "High-Impact", "Moderate", "Neutral", "Positive"]
    category: Literal["Hardware", "Software", "Network", "Access Request", "Other"]
    priority: Literal["P1", "P2", "P3"]
    mood: Literal["critical", "urgent", "concerned", "neutral", "satisfied"]
    action: Literal["escalate", "respond", "route"]
    recommended_team: ResolverTeam
    reasoning: ShortText


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
