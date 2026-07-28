"""Strict contracts for every LLM-backed Tickety task.

Provider JSON mode is only a formatting hint.  These models are the actual
trust boundary before generated data can affect ticket state or be returned to
users.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]


class StrictAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TriageAnalysis(StrictAIModel):
    sentiment: Literal["Business-Critical", "High-Impact", "Moderate", "Neutral", "Positive"]
    category: Literal["Hardware", "Software", "Network", "Access Request", "Other"]
    priority: Literal["P1", "P2", "P3"]
    mood: Literal["critical", "urgent", "concerned", "neutral", "satisfied"]
    action: Literal["escalate", "respond", "route"]
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


class GroundedItem(StrictAIModel):
    text: ShortText
    citations: list[str] = Field(min_length=1, max_length=10)


class TicketIntelligenceAnswer(StrictAIModel):
    answer: LongText
    answer_citations: list[str] = Field(min_length=1, max_length=10)
    findings: list[GroundedItem] = Field(default_factory=list, max_length=12)
    confidence: Literal["high", "medium", "low"] = "low"
