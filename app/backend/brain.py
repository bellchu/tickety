import json

from .ai_contracts import ResolverRoutingAnalysis, SuggestedReply, TriageAnalysis
from .ai_input import (
    UnsafeAIAdviceError,
    canonical_bounded_json,
    prompt_char_limit,
    validate_semantic_advice,
)
from .llm_manager import LLMInvalidOutputError, LLMManager
from .prompts import REPLY_SYSTEM_PROMPT, ROUTING_SYSTEM_PROMPT, TRIAGE_SYSTEM_PROMPT
from .privacy import redact_text
from .routing_policy import routing_business_context

MOOD_TO_EMOJI = {
    "critical": "😡",
    "urgent": "😤",
    "concerned": "😟",
    "neutral": "😐",
    "satisfied": "🙂",
}

SENTIMENT_COMPLEXITY = {
    "Business-Critical": 2,
    "High-Impact": 2,
    "Moderate": 1,
    "Neutral": 0,
    "Positive": 0,
}

PRIORITY_COMPLEXITY = {
    "P1": 3,
    "P2": 2,
    "P3": 1,
    "P4": 1,
}

_ROUTING_CONVERSATION_IDENTITY_KEYS = frozenset({
    "author",
    "authorid",
    "authoremail",
    "authorexternalid",
    "authorname",
    "authorusername",
    "externalauthorid",
    "employeeemail",
    "employeeid",
    "employeename",
    "employeeusername",
    "requesteremail",
    "requesterid",
    "requestername",
    "requesterusername",
    # The synced revision digest includes author_external_id. Excluding the
    # digest prevents that identity from influencing model input or route-cache
    # identity indirectly.
    "revisionhash",
    "useremail",
    "username",
})


def routing_public_thread(value: object) -> str:
    """Remove structured actor identity while retaining conversation evidence."""
    if isinstance(value, (dict, list)):
        parsed = value
    else:
        raw = "" if value is None else str(value)
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            # Legacy unstructured transcripts still receive the normal PII
            # redaction below; there are no structured actor fields to project.
            return raw

    def without_identity(candidate, depth: int = 0):
        if depth > 20:
            return "[nested content omitted]"
        if isinstance(candidate, list):
            return [without_identity(item, depth + 1) for item in candidate]
        if not isinstance(candidate, dict):
            return candidate
        sanitized = {}
        for key, item in candidate.items():
            normalized_key = "".join(
                character for character in str(key).casefold()
                if character.isalnum()
            )
            if normalized_key in _ROUTING_CONVERSATION_IDENTITY_KEYS:
                continue
            sanitized[key] = without_identity(item, depth + 1)
        return sanitized

    try:
        return json.dumps(
            without_identity(parsed),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        # A non-JSON-compatible decoded value cannot be trusted as a structured
        # transcript. Omit it instead of risking actor metadata disclosure.
        return ""


def calculate_complexity(priority: str, sentiment: str) -> int:
    base = PRIORITY_COMPLEXITY.get(priority, 1)
    sentiment_add = SENTIMENT_COMPLEXITY.get(sentiment, 0)
    return min(5, max(1, base + sentiment_add))


class IntelligenceEngine:
    def __init__(self, llm_manager: LLMManager):
        self.llm = llm_manager

    async def route_ticket(
        self,
        ticket_data: dict,
        *,
        requester_email: str | None = None,
    ) -> dict:
        """Return a dedicated resolver decision without exposing identity data."""
        context_hint = routing_business_context(
            requester_email
            if requester_email is not None
            else ticket_data.get("requester_email")
        )
        routing_prompt = canonical_bounded_json(
            {
                "subject": redact_text(ticket_data.get("subject") or ""),
                "description": redact_text(ticket_data.get("description") or ""),
                "public_thread": redact_text(
                    routing_public_thread(ticket_data.get("public_thread") or "")
                ),
                "freshservice_category": redact_text(
                    ticket_data.get("freshservice_category") or ""
                ),
                "freshservice_subcategory": redact_text(
                    ticket_data.get("freshservice_subcategory") or ""
                ),
                "freshservice_item_category": redact_text(
                    ticket_data.get("freshservice_item_category") or ""
                ),
            },
            max_chars=prompt_char_limit(self.llm),
            field_limits={
                "subject": 1_000,
                "description": 10_000,
                "public_thread": 12_000,
                "freshservice_category": 255,
                "freshservice_subcategory": 255,
                "freshservice_item_category": 255,
            },
            fixed_fields={"business_context_hint": context_hint},
        )
        analysis = await self.llm.analyze(
            routing_prompt,
            response_model=ResolverRoutingAnalysis,
            system_prompt=ROUTING_SYSTEM_PROMPT,
            max_tokens=800,
        )
        try:
            validated = ResolverRoutingAnalysis.model_validate(analysis)
            if (
                context_hint != "UNKNOWN"
                and validated.business_context not in {context_hint, "UNKNOWN"}
            ):
                raise ValueError(
                    "routing business context conflicts with the trusted domain hint"
                )
            return validated.model_dump()
        except (TypeError, ValueError) as exc:
            raise LLMInvalidOutputError(
                "AI provider returned invalid resolver routing output"
            ) from exc

    async def process_ticket(self, ticket_data: dict, kb_info: str = "") -> dict:
        triage_prompt = canonical_bounded_json(
            {
                "subject": redact_text(ticket_data.get("subject") or ""),
                "description": redact_text(ticket_data.get("description") or ""),
                "public_thread": redact_text(ticket_data.get("public_thread") or ""),
                "freshservice_category": redact_text(
                    ticket_data.get("freshservice_category") or ""
                ),
                "freshservice_subcategory": redact_text(
                    ticket_data.get("freshservice_subcategory") or ""
                ),
                "freshservice_item_category": redact_text(
                    ticket_data.get("freshservice_item_category") or ""
                ),
            },
            max_chars=prompt_char_limit(self.llm),
            field_limits={
                "subject": 1_000,
                "description": 10_000,
                "public_thread": 12_000,
                "freshservice_category": 255,
                "freshservice_subcategory": 255,
                "freshservice_item_category": 255,
            },
        )
        analysis = await self.llm.analyze(
            triage_prompt,
            response_model=TriageAnalysis,
            system_prompt=TRIAGE_SYSTEM_PROMPT,
            max_tokens=600,
        )
        try:
            validate_semantic_advice(analysis)
        except UnsafeAIAdviceError as exc:
            raise LLMInvalidOutputError(
                "AI provider returned unsafe triage output"
            ) from exc

        analysis["complexity"] = calculate_complexity(
            analysis["priority"], analysis["sentiment"]
        )

        if analysis.get("action") == "respond" and kb_info:
            reply_prompt = canonical_bounded_json(
                {
                    "ticket_subject": redact_text(ticket_data.get("subject") or ""),
                    "ticket_description": redact_text(
                        ticket_data.get("description") or ""
                    ),
                    "public_thread": redact_text(
                        ticket_data.get("public_thread") or ""
                    ),
                    "knowledge_base_evidence": redact_text(kb_info),
                },
                max_chars=prompt_char_limit(self.llm),
                field_limits={
                    "ticket_subject": 1_000,
                    "ticket_description": 10_000,
                    "public_thread": 12_000,
                    "knowledge_base_evidence": 8_000,
                },
            )
            reply_analysis = await self.llm.analyze(
                reply_prompt,
                response_model=SuggestedReply,
                system_prompt=REPLY_SYSTEM_PROMPT,
                max_tokens=800,
            )
            try:
                validate_semantic_advice(reply_analysis)
            except UnsafeAIAdviceError as exc:
                raise LLMInvalidOutputError(
                    "AI provider returned unsafe suggested advice"
                ) from exc
            analysis["suggested_response"] = reply_analysis.get("suggested_response")

        return analysis
