import asyncio
import json
from .ai_contracts import SuggestedReply, TriageAnalysis
from .llm_manager import LLMManager
from .prompts import Triage_PROMPT, REPLY_PROMPT

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
        triage_prompt = Triage_PROMPT.format(
            ticket_json=json.dumps(
                {
                    "subject": ticket_data.get("subject") or "",
                    "description": ticket_data.get("description") or "",
                },
                ensure_ascii=False,
            ),
        )
        # Pass json_schema (truthy) so the LLM manager enables DeepSeek JSON Output
        # (response_format=json_object) for reliable structured triage results.
        analysis = await self.llm.analyze(
            triage_prompt,
            response_model=TriageAnalysis,
            max_tokens=600,
        )

        analysis["complexity"] = calculate_complexity(
            analysis["priority"], analysis["sentiment"]
        )

        if analysis.get("action") == "respond" and kb_info:
            reply_prompt = REPLY_PROMPT.format(
                ticket_json=json.dumps(
                    {
                        "subject": ticket_data.get("subject") or "",
                        "description": ticket_data.get("description") or "",
                    },
                    ensure_ascii=False,
                ),
                kb_json=json.dumps({"evidence": kb_info}, ensure_ascii=False),
            )
            reply_analysis = await self.llm.analyze(
                reply_prompt,
                response_model=SuggestedReply,
                max_tokens=800,
            )
            analysis["suggested_response"] = reply_analysis.get("suggested_response")

        return analysis
