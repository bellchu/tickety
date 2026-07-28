from .ai_contracts import SuggestedReply, TriageAnalysis
from .ai_input import (
    UnsafeAIAdviceError,
    canonical_bounded_json,
    prompt_char_limit,
    validate_semantic_advice,
)
from .llm_manager import LLMInvalidOutputError, LLMManager
from .prompts import REPLY_SYSTEM_PROMPT, TRIAGE_SYSTEM_PROMPT
from .privacy import redact_text

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
}


def calculate_complexity(priority: str, sentiment: str) -> int:
    base = PRIORITY_COMPLEXITY.get(priority, 1)
    sentiment_add = SENTIMENT_COMPLEXITY.get(sentiment, 0)
    return min(5, max(1, base + sentiment_add))


class IntelligenceEngine:
    def __init__(self, llm_manager: LLMManager):
        self.llm = llm_manager

    async def process_ticket(self, ticket_data: dict, kb_info: str = "") -> dict:
        triage_prompt = canonical_bounded_json(
            {
                "subject": redact_text(ticket_data.get("subject") or ""),
                "description": redact_text(ticket_data.get("description") or ""),
            },
            max_chars=prompt_char_limit(self.llm),
            field_limits={"subject": 1_000, "description": 20_000},
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
                    "knowledge_base_evidence": redact_text(kb_info),
                },
                max_chars=prompt_char_limit(self.llm),
                field_limits={
                    "ticket_subject": 1_000,
                    "ticket_description": 18_000,
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
