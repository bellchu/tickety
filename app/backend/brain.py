import asyncio
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
            subject=ticket_data["subject"],
            description=ticket_data["description"],
        )
        # Pass json_schema (truthy) so the LLM manager enables DeepSeek JSON Output
        # (response_format=json_object) for reliable structured triage results.
        analysis = await self.llm.analyze(triage_prompt, json_schema={})

        if "mood" not in analysis:
            analysis["mood"] = "neutral"
        if "sentiment" not in analysis:
            analysis["sentiment"] = "Neutral"
        if "priority" not in analysis:
            analysis["priority"] = "P3"
        if "category" not in analysis:
            analysis["category"] = "Other"
        if "action" not in analysis:
            analysis["action"] = "respond"
        if "reasoning" not in analysis:
            analysis["reasoning"] = "Auto-filled."

        analysis["complexity"] = calculate_complexity(
            analysis["priority"], analysis["sentiment"]
        )

        if analysis.get("action") == "respond" and kb_info:
            reply_prompt = REPLY_PROMPT.format(
                subject=ticket_data["subject"],
                description=ticket_data["description"],
                kb_info=kb_info,
            )
            reply_analysis = await self.llm.analyze(reply_prompt, json_schema={})
            analysis["suggested_response"] = reply_analysis.get("suggested_response")

        return analysis