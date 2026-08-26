"""SupportLogic-inspired "ambient agents" for Tickety.

These are deterministic/heuristic agents (plus one LLM-backed summarizer) that
run on demand over the existing ticket + user data. They mirror the spirit of
SupportLogic's ambient AI workforce, scoped to what Tickety already stores:

  - Escalation Risk Agent   predict escalation risk per ticket
  - SLA Agent               watch SLA clocks, flag pre-breach + breaches
  - Prioritization Agent    rank the open backlog by urgency/impact/risk
  - Routing Agent           recommend the best engineer for a ticket
  - Summarization Agent     LLM-generated case summary
  - Account Health Agent    per-reporter health score (churn risk proxy)
  - Text Analytics Agent    trends, category & sentiment distribution, top terms
  - Proactive Alert Agent   unified feed of at-risk / breaching / escalate cases

All scores are bounded 0-100. Heuristics are intentionally transparent so the
reasoning can be shown in the UI alongside the number.
"""

from __future__ import annotations

import math
import json
import re
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from .database import (
    ExternalConversationRecord,
    ExternalGroupRecord,
    IntelligenceStudyRecord,
    TicketRecord,
    UserRecord,
)
from .llm_manager import LLMInvalidOutputError, LLMManager
from .ai_contracts import AI_RESOLVER_TEAMS, ResolutionAnalysis, TicketSummary
from .ai_input import (
    UnsafeAIAdviceError,
    canonical_bounded_json,
    neutralize_generated_uris,
    prompt_char_limit,
    validate_semantic_advice,
)
from .privacy import redact_text
from .prompts import RESOLUTION_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT
from .sla_policy import ticket_is_sla_exempt

# ── Tunables ──────────────────────────────────────────────────────────────

# SLA targets (hours to resolution) by priority, mirroring typical P1/P2/P3 SLOs.
SLA_HOURS = {"P1": 4, "P2": 24, "P3": 72}
DEFAULT_SLA_HOURS = 72

def _load_sla_hours():
    """Reload SLA targets from env (may be overridden by settings UI)."""
    import os as _os
    global SLA_HOURS
    for p in ("P1", "P2", "P3"):
        v = _os.getenv(f"SLA_{p}_HOURS")
        if v and v.isdigit():
            SLA_HOURS[p] = int(v)

# Fraction of SLA window remaining below which a case is "at risk".
SLA_AT_RISK_THRESHOLD = 0.20

# Priority weight for composite scoring.
PRIORITY_WEIGHT = {"P1": 100, "P2": 60, "P3": 25}

# Sentiment contribution to escalation risk.
SENTIMENT_RISK = {
    "Business-Critical": 40,
    "High-Impact": 30,
    "Moderate": 15,
    "Neutral": 5,
    "Positive": 0,
}

# Mood contribution to escalation risk.
MOOD_RISK = {
    "critical": 25,
    "urgent": 20,
    "concerned": 10,
    "neutral": 5,
    "satisfied": 0,
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "is",
    "are", "was", "were", "be", "been", "being", "with", "at", "by", "from",
    "this", "that", "it", "as", "not", "no", "we", "you", "i", "please", "can",
    "could", "would", "should", "my", "our", "your", "have", "has", "had",
    "do", "does", "did", "will", "if", "then", "so", "than", "too", "very",
}

_MAX_ANALYTICS_ROWS = 500


# ── helpers ───────────────────────────────────────────────────────────────

def _ticket_activity_expression():
    """Authoritative last activity for operational analytics.

    Provider timestamps must win over local projection timestamps. Importing a
    ten-year-old ticket updates the local row today; using ``updated_at`` first
    would incorrectly make that legacy record look operationally current.
    """
    return func.coalesce(
        TicketRecord.external_updated_at,
        TicketRecord.external_created_at,
        TicketRecord.updated_at,
        TicketRecord.created_at,
    )


def _ticket_activity_at(ticket: TicketRecord) -> Optional[datetime]:
    return (
        ticket.external_updated_at
        or ticket.external_created_at
        or ticket.updated_at
        or ticket.created_at
    )


def _ticket_created_expression():
    return func.coalesce(TicketRecord.external_created_at, TicketRecord.created_at)


def _scope_query(query, since: Optional[datetime]):
    if since is None:
        return query
    return query.filter(_ticket_activity_expression() >= since)

def _age_hours(t: TicketRecord, now: Optional[datetime] = None) -> float:
    now = now or datetime.utcnow()
    started = t.external_created_at or t.created_at or now
    ended = (t.external_resolved_at or t.resolved_at or now) if not _open(t) else now
    delta = ended - started
    return max(0.0, delta.total_seconds() / 3600.0)


def _open(t: TicketRecord) -> bool:
    status = (t.status or "").lower()
    return status not in {"closed", "resolved", "cancelled"}


def _clamp(v: int) -> int:
    return max(0, min(100, int(round(v))))


# ── 1. Escalation Risk Agent ─────────────────────────────────────────────

def escalation_risk(t: TicketRecord, now: Optional[datetime] = None) -> int:
    """Predict 0-100 risk that this case will be escalated.

    Combines sentiment, mood, priority, complexity, age, and an already-escalated
    status. Transparent and deterministic so the UI can explain the score.
    """
    score = 0
    score += SENTIMENT_RISK.get(t.sentiment or "", 5)
    score += MOOD_RISK.get((t.mood or "neutral").lower(), 5)
    # Priority: map P1/P2/P3 to a risk contribution (capped).
    score += min(20, PRIORITY_WEIGHT.get(t.priority, 25) // 5)
    score += (t.complexity or 1) * 4
    # Age decay: ramp risk as a case sits unresolved past half its SLA window.
    sla_h = SLA_HOURS.get(t.priority, DEFAULT_SLA_HOURS)
    age = _age_hours(t, now)
    if _open(t) and not ticket_is_sla_exempt(t):
        if age > sla_h:
            score += 15  # past SLA
        elif age > sla_h / 2:
            score += 8
    if (t.status or "").lower() == "escalated":
        score += 25
    return _clamp(score)


# ── 2. SLA Agent ──────────────────────────────────────────────────────────

def sla_status(t: TicketRecord, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return SLA clock state for a ticket."""
    now = now or datetime.utcnow()
    sla_exempt = ticket_is_sla_exempt(t)
    configured_sla_h = SLA_HOURS.get(t.priority, DEFAULT_SLA_HOURS)
    start = t.external_created_at or t.created_at or now
    due_at = t.resolution_due_at or t.external_due_by or t.due_by
    if due_at and due_at > start:
        sla_h = max(0.01, (due_at - start).total_seconds() / 3600.0)
        target_source = "provider_due_at"
    else:
        sla_h = float(configured_sla_h)
        due_at = start + timedelta(hours=sla_h)
        target_source = "priority_policy"
    end = t.external_resolved_at or t.resolved_at or (
        now if _open(t) else (t.external_updated_at or t.updated_at or now)
    )
    elapsed = max(0.0, (end - start).total_seconds() / 3600.0)
    remaining_h = (due_at - end).total_seconds() / 3600.0
    breached = remaining_h <= 0 and _open(t) and not sla_exempt
    at_risk = (
        not breached
        and _open(t)
        and not sla_exempt
        and remaining_h <= sla_h * SLA_AT_RISK_THRESHOLD
        and remaining_h > 0
    )
    return {
        "ticket_id": t.id,
        "subject": t.subject,
        "priority": t.priority,
        "sla_target_hours": sla_h,
        "elapsed_hours": round(elapsed, 2),
        "remaining_hours": 0.0 if sla_exempt else round(max(0.0, remaining_h), 2),
        "overdue_hours": 0.0 if sla_exempt else round(max(0.0, -remaining_h), 2),
        "due_at": due_at.isoformat(),
        "target_source": target_source,
        "status": "breached" if breached else ("at_risk" if at_risk else "on_track"),
        "is_open": _open(t),
    }


# ── 3. Prioritization Agent ──────────────────────────────────────────────

def prioritize_score(t: TicketRecord, now: Optional[datetime] = None) -> int:
    """Composite "next best ticket to work on" score (0-100)."""
    now = now or datetime.utcnow()
    score = PRIORITY_WEIGHT.get(t.priority, 25)
    score += escalation_risk(t, now) * 0.4
    # Age pressure: how far through its SLA window the case is.
    sla_h = SLA_HOURS.get(t.priority, DEFAULT_SLA_HOURS)
    age = _age_hours(t, now)
    if not ticket_is_sla_exempt(t):
        score += min(30, (age / max(1, sla_h)) * 30)
    score += (t.complexity or 1) * 2
    return _clamp(score)


# ── 4. Routing Agent ──────────────────────────────────────────────────────

# Tier = engineering SKILL level needed, driven by technical difficulty
# (category) crossed with blast-radius urgency (priority). It is deliberately
# NOT a function of `complexity`, because complexity mixes in customer
# sentiment/urgency and would over-tier routine single-user issues
# (e.g. an Outlook crash is Software + P1 -> tier 2, not tier 3). Only
# infrastructure-grade, customer-facing outages (Network P1) reach tier 3.
CATEGORY_DIFFICULTY = {
    "access request": 1,
    "software": 1,
    "hardware": 1,
    "other": 1,
    "network": 2,  # infra / shared service -> needs higher skill
}
# Priority adds urgency that raises the required skill band.
_PRIORITY_TIER_BUMP = {"P1": 1, "P2": 0, "P3": 0}

# Team routing prefers a trusted AI issue type. Freshservice's authoritative,
# closed-set category can provide a deterministic fallback when an AI result is
# not ready yet. The fallback is deliberately exact-match only: unknown values
# and the AI ``Other`` bucket still fail closed for human review.
AI_CATEGORY_TEAMS = {
    "Network": "Network Operations",
    "Access Request": "Identity and Access",
    "Hardware": "Workplace Technology",
    "Software": "Application Support",
}
SOURCE_CATEGORY_TEAMS = {
    "User Management": "Identity and Access",
    "Password Reset": "Identity and Access",
    "Termination/Resignation": "Identity and Access",
    "Hardware - Accessories": "Workplace Technology",
    "Hardware - Computers": "Workplace Technology",
    "Hardware - Printers": "Workplace Technology",
    "Mobile Phones": "Workplace Technology",
    "Software": "Application Support",
    "E1 App": "Application Support",
    "E1 CNC": "Application Support",
    "E1 Credit Card Processing": "Application Support",
    "Almo - ERP/WMS Team": "Application Support",
    "B2B Web": "Application Support",
    "WMS": "Application Support",
}
_QUALITY_SOURCE_CATEGORY_TEAMS = {
    **SOURCE_CATEGORY_TEAMS,
    # Broader historical classifications are useful for confidence-gated
    # group profiling, but intentionally do not alter the existing fail-closed
    # live routing contract above.
    "Infrastructure": "Network Operations",
    "Power BI - Dashboards": "Application Support",
    "BI": "Application Support",
    "CRM": "Application Support",
    "Web": "Application Support",
    "SQL Admin": "Application Support",
    "E1 Development": "Application Support",
    "E1 Forms": "Application Support",
    "E1 Bulk Update": "Application Support",
    "E1 Avatax": "Application Support",
    "EDI / Integrations": "Application Support",
    "EDI / Integrations - POs": "Application Support",
    "Almo - WebDev Team": "Application Support",
}
UNROUTED_REVIEW_TEAM = "Unrouted / Review"
NO_ACTIVE_ROUTING_TEAM = "No active routing"
_TRUSTED_AI_ROUTING_STATUSES = {"completed", "partial", "triage_completed"}


@dataclass(frozen=True)
class TeamRoutingDecision:
    """AI resolver-team projection until catalog-bound group routing is enabled.

    ``ai_team`` is selected from Tickety's closed set of resolver teams, while
    ``ai_category`` remains a compatibility fallback for older artifacts.
    Neither is represented as a validated Freshservice resolver-group route.
    Every untrusted or unmapped outcome fails closed to an explicit review
    state.
    """

    recommended_team: str
    basis: Literal[
        "source_group",
        "ai_team",
        "ai_category",
        "source_category",
        "not_applicable",
        "unrouted_review",
    ]
    status: Literal[
        "source_group_assignment",
        "ai_team_recommendation",
        "legacy_ai_category",
        "source_category_suggestion",
        "not_applicable",
        "unrouted_review",
    ]
    abstention_reason: Optional[
        Literal[
            "missing_ai_category",
            "unsupported_ai_category",
            "untrusted_ai_status",
        ]
    ]
    catalog_validated: bool = False


def team_routing_decision(
    ai_suggested_category: Optional[str],
    ai_status: Optional[str],
    *,
    ai_suggested_team: Optional[str] = None,
    source_group_id: Optional[str] = None,
    source_category: Optional[str] = None,
    ticket_status: Optional[str] = None,
    ai_evidence_current: bool = False,
) -> TeamRoutingDecision:
    """Return an AI-first, fail-closed routing projection with provenance.

    ``source_group_id`` is accepted for compatibility with existing callers,
    but it represents the provider's current assignment and never influences
    Tickety's recommendation.
    """
    if (ticket_status or "").strip().lower() in {"closed", "resolved", "cancelled"}:
        return TeamRoutingDecision(
            recommended_team=NO_ACTIVE_ROUTING_TEAM,
            basis="not_applicable",
            status="not_applicable",
            abstention_reason=None,
        )
    normalized_status = (ai_status or "").strip().lower().replace("-", "_")
    ai_routing_trusted = (
        normalized_status in _TRUSTED_AI_ROUTING_STATUSES
        or ai_evidence_current
    )
    normalized_ai_team = (ai_suggested_team or "").strip()
    if ai_routing_trusted and normalized_ai_team in AI_RESOLVER_TEAMS:
        return TeamRoutingDecision(
            recommended_team=normalized_ai_team,
            basis="ai_team",
            status="ai_team_recommendation",
            abstention_reason=None,
        )

    # Preserve recommendations generated before the explicit AI team contract
    # while those tickets are refreshed through the bounded worker queues.
    if ai_routing_trusted and ai_suggested_category:
        team = AI_CATEGORY_TEAMS.get(ai_suggested_category)
        if team:
            return TeamRoutingDecision(
                recommended_team=team,
                basis="ai_category",
                status="legacy_ai_category",
                abstention_reason=None,
            )

    source_team = SOURCE_CATEGORY_TEAMS.get((source_category or "").strip())
    if source_team:
        return TeamRoutingDecision(
            recommended_team=source_team,
            basis="source_category",
            status="source_category_suggestion",
            abstention_reason=None,
        )

    if not ai_routing_trusted:
        reason = "untrusted_ai_status"
    elif not ai_suggested_category:
        reason = "missing_ai_category"
    else:
        reason = "unsupported_ai_category"
    return TeamRoutingDecision(
        recommended_team=UNROUTED_REVIEW_TEAM,
        basis="unrouted_review",
        status="unrouted_review",
        abstention_reason=reason,
    )


def recommended_team(
    ai_suggested_category: Optional[str],
    ai_status: Optional[str],
    ai_suggested_team: Optional[str] = None,
) -> tuple[str, str]:
    """Return the legacy tuple shape without restoring an implicit fallback."""
    decision = team_routing_decision(
        ai_suggested_category,
        ai_status,
        ai_suggested_team=ai_suggested_team,
    )
    return decision.recommended_team, decision.basis


def tier_needed_for(ticket: TicketRecord) -> int:
    cat = (ticket.category or "other").lower()
    base = CATEGORY_DIFFICULTY.get(cat, 1)
    bump = _PRIORITY_TIER_BUMP.get(ticket.priority, 0)
    return max(1, min(3, base + bump))


def recommend_assignee(
    db: Session, ticket: TicketRecord
) -> Dict[str, Any]:
    """Recommend the best engineer for a ticket.

    Tier requirement comes from technical difficulty (category x priority),
    NOT from `complexity`/sentiment. Escalation risk only nudges a preference
    toward a higher tier; it never forces one.
    """
    total_users = db.query(UserRecord).count()
    users = db.query(UserRecord).order_by(
        UserRecord.tier.desc(),
        UserRecord.impact_points.desc(),
        UserRecord.momentum.desc(),
        UserRecord.id.asc(),
    ).limit(_MAX_ANALYTICS_ROWS).all()
    if not users:
        return {
            "recommended_user_id": None,
            "candidates": [],
            "total_users": total_users,
            "analyzed_users": 0,
            "candidate_pool_truncated": False,
        }

    risk = escalation_risk(ticket)
    complexity = ticket.complexity or 1
    tier_needed = tier_needed_for(ticket)

    candidates = []
    for u in users:
        tier_ok = (u.tier or 1) >= tier_needed
        score = (u.impact_points or 0) * 0.5
        score += (u.momentum or 0) * 2
        score += (u.tier or 1) * 10
        if not tier_ok:
            score -= 40  # penalize under-skilled assignment
        # Slight preference for a higher tier when risk is high (soft nudge,
        # not a hard gate).
        if risk >= 70:
            score += (u.tier or 1) * 5
        candidates.append({
            "user_id": u.id,
            "name": u.name,
            "tier": u.tier,
            "impact_points": u.impact_points,
            "momentum": u.momentum,
            "score": _clamp(score),
            "tier_ok": tier_ok,
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    cat_label = (ticket.category or "other").title()
    return {
        "recommended_user_id": candidates[0]["user_id"] if candidates else None,
        "recommended_name": candidates[0]["name"] if candidates else None,
        "tier_needed": tier_needed,
        "reasoning": (
            f"{ticket.priority or 'P3'} {cat_label} issue -> tier {tier_needed} "
            f"engineer (risk {risk}, complexity {complexity} only nudges preference, "
            f"does not raise the tier floor)."
        ),
        "candidates": candidates[:5],
        "total_users": total_users,
        "analyzed_users": len(users),
        "candidate_pool_truncated": total_users > len(users),
    }


# ── 4b. Service-quality signal agents ────────────────────────────────────

# These agents are deliberately advisory. They never update provider routing,
# priority, assignment, or SLA state. The UI links every signal back to the
# source ticket so a human can validate and act in the system of record.
_TRUSTED_SIGNAL_STATUSES = {"completed", "partial", "triage_completed"}
_GROUP_PROFILE_MIN_SAMPLE = 10
_GROUP_PROFILE_MIN_CONFIDENCE = 0.60

SUPPORT_LEVELS = {
    0: {"name": "Level 0", "label": "Self-service / bot"},
    1: {"name": "Level 1", "label": "Help desk"},
    2: {"name": "Level 2", "label": "Specialist"},
    3: {"name": "Level 3", "label": "Expert / major incident"},
}

_LEVEL_ZERO_PATTERNS = {
    "Password and account recovery": (
        re.compile(r"\b(password reset|reset (?:my |the )?password|account unlock|unlock (?:my |the )?account|forgot(?:ten)? password)\b", re.I),
        "Password or account recovery workflow",
    ),
    "Restart and reconnect": (
        re.compile(r"\b(reboot(?:ed|ing)?|restart(?:ed|ing)?|power cycl(?:e|ed|ing)|reconnect(?:ed|ing)?|sign out and (?:back )?in)\b", re.I),
        "Restart, power-cycle, or reconnect resolution",
    ),
    "Cache and browser reset": (
        re.compile(r"\b(clear(?:ed|ing)? (?:the )?(?:browser )?cache|clear(?:ed|ing)? cookies|incognito|private browsing|browser reset)\b", re.I),
        "Browser cache or session reset",
    ),
    "Standard software update": (
        re.compile(r"\b(update(?:d|ing)? (?:the )?(?:app|application|client|software)|install(?:ed|ing)? (?:the )?(?:approved )?(?:app|application|client|software))\b", re.I),
        "Standard software install or update",
    ),
    "MFA enrollment and reset": (
        re.compile(r"\b(mfa reset|reset (?:my |the )?(?:mfa|authenticator)|authenticator (?:setup|enrollment|re-enroll)|multi-factor (?:setup|reset))\b", re.I),
        "MFA enrollment or reset workflow",
    ),
    "Printer queue recovery": (
        re.compile(r"\b(clear(?:ed|ing)? (?:the )?print queue|restart(?:ed|ing)? (?:the )?spooler|remove(?:d|ing)? and re-add(?:ed|ing)? (?:the )?printer)\b", re.I),
        "Printer queue or spooler recovery",
    ),
}

_LEVEL_ZERO_EXCLUSION = re.compile(
    r"\b(security incident|data loss|breach|malware|ransomware|server outage|"
    r"multiple users|company.?wide|site.?wide|hardware replacement|replace(?:d|ment)? "
    r"(?:the )?(?:laptop|desktop|server|drive)|firewall change|production outage)\b",
    re.I,
)

_FRUSTRATION_MARKERS = (
    (re.compile(r"\b(frustrat(?:ed|ing)|unacceptable|ridiculous|angry|upset)\b", re.I), "Explicit frustration language"),
    (re.compile(r"\b(still (?:not|isn't|is not|doesn't|does not)|again|third time|multiple times)\b", re.I), "Repeated unresolved issue language"),
    (re.compile(r"\b(no response|no reply|waiting (?:for|since)|any update|please update)\b", re.I), "Requester is chasing an update"),
    (re.compile(r"\b(asap|urgent|immediately|blocking me|cannot work|can't work)\b", re.I), "Time-pressure language"),
)

_VAGUE_FAILURE = re.compile(
    r"^(?:my |the )?(?:computer|laptop|pc|system|application|app|email|printer|"
    r"internet|vpn|software)?\s*(?:is |isn't |is not )?(?:not working|broken|"
    r"doesn't work|does not work|has an issue|issue|problem|help)[.!?\s]*$",
    re.I,
)


def _trusted_signal(ticket: TicketRecord) -> bool:
    return (ticket.ai_status or "").strip().lower().replace("-", "_") in _TRUSTED_SIGNAL_STATUSES


def _source_category(ticket: TicketRecord) -> str:
    return (ticket.external_category or ticket.category or "").strip()


def _recommended_team_for_signal(ticket: TicketRecord) -> tuple[Optional[str], str]:
    team = (ticket.ai_suggested_team or "").strip()
    if _trusted_signal(ticket) and team in AI_RESOLVER_TEAMS:
        return team, "trusted_ai_recommendation"
    source_team = _QUALITY_SOURCE_CATEGORY_TEAMS.get(_source_category(ticket))
    if source_team:
        return source_team, "provider_category_policy"
    ai_category_team = AI_CATEGORY_TEAMS.get(ticket.ai_suggested_category or "")
    if _trusted_signal(ticket) and ai_category_team:
        return ai_category_team, "trusted_ai_category"
    return None, "insufficient_evidence"


def _support_level_from_fields(
    *, priority: Optional[str], category: Optional[str], complexity: Optional[int]
) -> int:
    normalized_priority = (priority or "").strip().lower()
    normalized_category = (category or "").strip().lower()
    measured_complexity = max(1, min(5, int(complexity or 1)))
    infrastructure = any(term in normalized_category for term in (
        "network", "infrastructure", "server", "security", "sql admin",
    ))
    if measured_complexity >= 5 or (
        normalized_priority in {"p1", "urgent"} and infrastructure
    ):
        return 3
    if measured_complexity >= 3 or normalized_priority in {"p1", "urgent"} or infrastructure:
        return 2
    return 1


def _level_zero_theme(text: str) -> Optional[tuple[str, str]]:
    for theme, (pattern, evidence) in _LEVEL_ZERO_PATTERNS.items():
        if pattern.search(text or ""):
            return theme, evidence
    return None


def _dominant(counter: Counter) -> tuple[Optional[Any], int, float]:
    if not counter:
        return None, 0, 0.0
    value, count = counter.most_common(1)[0]
    total = sum(counter.values())
    return value, total, round(count / max(1, total), 3)


def build_group_profiles(
    db: Session, *, since: datetime
) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Learn resolver-group function and service level from completed work.

    Freshservice currently has no Level 0-3 group metadata. These profiles are
    therefore explicitly inferred, sample-gated, and never written back.
    """
    completed_at = func.coalesce(
        TicketRecord.external_resolved_at,
        TicketRecord.resolved_at,
        TicketRecord.external_updated_at,
        TicketRecord.updated_at,
    )
    rows = db.query(
        TicketRecord.binding_id,
        TicketRecord.external_group_id,
        TicketRecord.external_category,
        TicketRecord.category,
        TicketRecord.ai_suggested_team,
        TicketRecord.ai_status,
        TicketRecord.complexity,
        TicketRecord.priority,
        func.count(TicketRecord.id),
    ).filter(
        TicketRecord.external_group_id.isnot(None),
        TicketRecord.external_group_id != "",
        func.lower(func.coalesce(TicketRecord.status, "")).in_(["closed", "resolved"]),
        completed_at >= since,
    ).group_by(
        TicketRecord.binding_id,
        TicketRecord.external_group_id,
        TicketRecord.external_category,
        TicketRecord.category,
        TicketRecord.ai_suggested_team,
        TicketRecord.ai_status,
        TicketRecord.complexity,
        TicketRecord.priority,
    ).all()

    counters: Dict[tuple[str, str], Dict[str, Counter]] = {}
    for (
        binding_id, group_id, external_category, category, ai_team, ai_status,
        complexity, priority, count,
    ) in rows:
        key = (binding_id or "legacy", group_id)
        bucket = counters.setdefault(key, {"teams": Counter(), "levels": Counter()})
        normalized_status = (ai_status or "").strip().lower().replace("-", "_")
        if normalized_status in _TRUSTED_SIGNAL_STATUSES and ai_team in AI_RESOLVER_TEAMS:
            team = ai_team
        else:
            team = _QUALITY_SOURCE_CATEGORY_TEAMS.get((external_category or category or "").strip())
        if team:
            bucket["teams"][team] += int(count)
        level = _support_level_from_fields(
            priority=priority,
            category=external_category or category,
            complexity=complexity,
        )
        bucket["levels"][level] += int(count)

    group_rows = db.query(ExternalGroupRecord).all()
    names = {
        (group.binding_id or "legacy", group.external_id): group.name
        for group in group_rows
    }
    profiles: Dict[tuple[str, str], Dict[str, Any]] = {}
    for key, values in counters.items():
        team, team_samples, team_confidence = _dominant(values["teams"])
        level, level_samples, level_confidence = _dominant(values["levels"])
        profiles[key] = {
            "group_id": key[1],
            "group_name": names.get(key) or f"Provider group {key[1]}",
            "directory_name_available": key in names,
            "functional_team": team,
            "functional_samples": team_samples,
            "functional_confidence": team_confidence,
            "inferred_level": level,
            "level_samples": level_samples,
            "level_confidence": level_confidence,
        }
    return profiles


def routing_alert(
    ticket: TicketRecord,
    profile: Optional[Dict[str, Any]],
    *, now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    expected_team, source = _recommended_team_for_signal(ticket)
    if not profile or not expected_team or not profile.get("functional_team"):
        return None
    if (
        profile["functional_samples"] < _GROUP_PROFILE_MIN_SAMPLE
        or profile["functional_confidence"] < _GROUP_PROFILE_MIN_CONFIDENCE
        or profile["functional_team"] == expected_team
    ):
        return None
    now = now or datetime.utcnow()
    activity_at = _ticket_activity_at(ticket)
    dormant_hours = max(
        0.0,
        (now - activity_at).total_seconds() / 3600.0 if activity_at else 0.0,
    )
    severity = "high" if (
        (ticket.priority or "").strip().lower() in {"p1", "urgent"}
        or dormant_hours >= 48
    ) else "medium"
    return {
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "priority": ticket.priority or "Unspecified",
        "severity": severity,
        "current_group_id": ticket.external_group_id,
        "current_group_name": profile["group_name"],
        "directory_name_available": profile["directory_name_available"],
        "group_profile_team": profile["functional_team"],
        "recommended_team": expected_team,
        "recommendation_source": source,
        "profile_confidence": profile["functional_confidence"],
        "profile_samples": profile["functional_samples"],
        "dormant_hours": round(dormant_hours, 2),
        "evidence": [
            f"Ticket evidence recommends {expected_team}",
            f"{round(profile['functional_confidence'] * 100)}% of {profile['functional_samples']} classified historical tickets in this group align to {profile['functional_team']}",
        ],
        "alert_only": True,
    }


def support_level_assessment(
    ticket: TicketRecord,
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    request_text = " ".join(filter(None, (
        ticket.subject,
        ticket.description,
        ticket.external_category,
        ticket.external_subcategory,
        ticket.external_item_category,
    )))
    l0 = _level_zero_theme(request_text)
    high_risk = (
        (ticket.priority or "").strip().lower() in {"p1", "urgent"}
        or (ticket.sentiment or "") in {"Business-Critical", "High-Impact"}
        or bool(_LEVEL_ZERO_EXCLUSION.search(request_text))
    )
    if l0 and not high_risk and int(ticket.complexity or 1) <= 2:
        recommended = 0
        basis = l0[1]
    else:
        recommended = _support_level_from_fields(
            priority=ticket.priority,
            category=_source_category(ticket) or ticket.ai_suggested_category,
            complexity=ticket.complexity,
        )
        if recommended == 3:
            basis = "Critical infrastructure impact or expert-level complexity"
        elif recommended == 2:
            basis = "Specialist skill, elevated priority, or multi-step complexity"
        else:
            basis = "Routine help-desk diagnosis and fulfillment"

    inferred_level = None
    inferred_confidence = 0.0
    inferred_samples = 0
    if profile and (
        profile.get("level_samples", 0) >= _GROUP_PROFILE_MIN_SAMPLE
        and profile.get("level_confidence", 0) >= 0.50
    ):
        inferred_level = profile.get("inferred_level")
        inferred_confidence = profile.get("level_confidence", 0.0)
        inferred_samples = profile.get("level_samples", 0)
    mismatch = inferred_level is not None and inferred_level != recommended
    mismatch_direction = None
    if mismatch:
        mismatch_direction = "under-tiered" if inferred_level < recommended else "over-tiered"
    return {
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "priority": ticket.priority or "Unspecified",
        "recommended_level": recommended,
        "recommended_name": SUPPORT_LEVELS[recommended]["name"],
        "recommended_label": SUPPORT_LEVELS[recommended]["label"],
        "classification_confidence": "high" if _trusted_signal(ticket) or l0 else "medium",
        "basis": basis,
        "inferred_assigned_level": inferred_level,
        "inferred_assigned_name": SUPPORT_LEVELS[inferred_level]["name"] if inferred_level is not None else None,
        "inferred_from_group_history": inferred_level is not None,
        "inferred_confidence": inferred_confidence,
        "inferred_samples": inferred_samples,
        "mismatch": mismatch,
        "mismatch_direction": mismatch_direction,
    }


def public_conversations_for_tickets(
    db: Session, ticket_ids: List[str]
) -> Dict[str, List[ExternalConversationRecord]]:
    if not ticket_ids:
        return {}
    rows = db.query(ExternalConversationRecord).filter(
        ExternalConversationRecord.ticket_id.in_(ticket_ids),
        ExternalConversationRecord.deleted.is_(False),
        ExternalConversationRecord.is_private.is_(False),
    ).order_by(
        ExternalConversationRecord.ticket_id.asc(),
        func.coalesce(
            ExternalConversationRecord.provider_created_at,
            ExternalConversationRecord.provider_updated_at,
            ExternalConversationRecord.received_at,
        ).asc(),
        ExternalConversationRecord.external_id.asc(),
    ).all()
    grouped: Dict[str, List[ExternalConversationRecord]] = {}
    for row in rows:
        grouped.setdefault(row.ticket_id, []).append(row)
    return grouped


def _conversation_at(row: ExternalConversationRecord) -> datetime:
    return row.provider_created_at or row.provider_updated_at or row.received_at


def customer_friction_signal(
    ticket: TicketRecord,
    conversations: List[ExternalConversationRecord],
    *, now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    incoming = [row for row in conversations if row.incoming]
    outgoing = [row for row in conversations if not row.incoming]
    requester_text = " ".join(
        [ticket.description or "", *(row.body or "" for row in incoming)]
    )
    frustration_evidence = [
        label for pattern, label in _FRUSTRATION_MARKERS
        if pattern.search(requester_text)
    ]
    if (ticket.mood or "").lower() in {"urgent", "critical"}:
        frustration_evidence.append("AI triage detected urgent or critical requester mood")

    requester_events = [
        ticket.external_created_at or ticket.created_at,
        *(_conversation_at(row) for row in incoming),
    ]
    agent_events = sorted(_conversation_at(row) for row in outgoing)
    conversation_coverage = bool(
        conversations
        or ticket.external_conversations_synced_at
        or not ticket.external_source
    )
    ticket_end = (
        now if _open(ticket)
        else ticket.external_resolved_at or ticket.resolved_at
        or ticket.external_updated_at or ticket.updated_at or now
    )
    gaps: List[float] = []
    unanswered_gaps: List[float] = []
    unanswered = 0
    if conversation_coverage:
        for request_at in requester_events:
            response_at = next((event for event in agent_events if event >= request_at), None)
            if response_at is None:
                unanswered += 1
                response_at = ticket_end
                gap_hours = max(0.0, (response_at - request_at).total_seconds() / 3600.0)
                unanswered_gaps.append(gap_hours)
            else:
                gap_hours = max(0.0, (response_at - request_at).total_seconds() / 3600.0)
            gaps.append(gap_hours)
    max_gap = max(gaps, default=0.0)
    current_unanswered_gap = max(unanswered_gaps, default=0.0)
    priority = (ticket.priority or "").strip().lower()
    gap_threshold = 4.0 if priority in {"p1", "urgent"} else (12.0 if priority in {"p2", "high"} else 24.0)
    round_trips = min(len(requester_events), len(agent_events))
    excessive_back_and_forth = len(conversations) >= 8 and round_trips >= 4
    # A completed late reply is accounted for in the reactive first-response
    # SLA view. The live friction alert remains actionable by firing only when
    # a requester turn is still waiting beyond the elapsed-time threshold.
    long_gap = current_unanswered_gap >= gap_threshold and _open(ticket)
    frustrated = bool(frustration_evidence)
    flagged = frustrated or long_gap or excessive_back_and_forth
    evidence = list(dict.fromkeys(frustration_evidence))
    if long_gap:
        evidence.append(f"A requester turn has waited {round(current_unanswered_gap, 1)} hours for a response")
    if excessive_back_and_forth:
        evidence.append(f"{len(conversations)} public messages across at least {round_trips} response cycles")
    severity_score = (2 if frustrated else 0) + (2 if long_gap else 0) + (1 if excessive_back_and_forth else 0)
    return {
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "priority": ticket.priority or "Unspecified",
        "flagged": flagged,
        "severity": "high" if severity_score >= 4 else ("medium" if severity_score >= 2 else "low"),
        "frustration_detected": frustrated,
        "long_response_gap": long_gap,
        "excessive_back_and_forth": excessive_back_and_forth,
        "max_response_gap_hours": round(max_gap, 2),
        "current_unanswered_gap_hours": round(current_unanswered_gap, 2),
        "gap_threshold_hours": gap_threshold,
        "public_message_count": len(conversations),
        "requester_message_count": len(requester_events),
        "agent_message_count": len(agent_events),
        "unanswered_requester_turns": unanswered,
        "conversation_coverage": conversation_coverage,
        "evidence": evidence,
    }


def clarification_assessment(
    ticket: TicketRecord,
    conversations: List[ExternalConversationRecord],
) -> Dict[str, Any]:
    incoming_detail = " ".join(row.body or "" for row in conversations if row.incoming)
    original = " ".join(filter(None, (ticket.subject, ticket.description))).strip()
    combined = f"{original} {incoming_detail}".strip()
    compact = re.sub(r"\s+", " ", combined)
    evidence: List[str] = []
    questions: List[str] = []
    score = 0
    if len(compact) < 60:
        score += 2
        evidence.append("Request contains fewer than 60 characters of usable detail")
    if _VAGUE_FAILURE.match(original.strip()) or _VAGUE_FAILURE.search(original.strip()):
        score += 2
        evidence.append("Generic failure wording does not identify a diagnostic symptom")
    has_error = bool(re.search(r"\b(error|code|message|says|shows|screenshot|\d{3,})\b", compact, re.I))
    has_timing = bool(re.search(r"\b(since|started|begin|today|yesterday|after|before|when|\d{1,2}:\d{2})\b", compact, re.I))
    has_scope = bool(re.search(r"\b(one user|multiple users|everyone|team|department|only me|all users|site)\b", compact, re.I))
    has_steps = bool(re.search(r"\b(tried|attempted|restarted|rebooted|reinstalled|cleared|tested|checked)\b", compact, re.I))
    if not has_error:
        score += 1
        evidence.append("No exact error, message, or observable symptom is provided")
        questions.append("What exact error message or behavior do you see?")
    if not has_timing:
        score += 1
        questions.append("When did this start, and did anything change immediately beforehand?")
    if not has_scope:
        score += 1
        questions.append("Is this affecting only you or multiple people?")
    if not has_steps:
        questions.append("What troubleshooting steps have already been attempted?")
    if not re.search(r"\b(laptop|desktop|computer|phone|printer|vpn|email|outlook|browser|application|app|system|service|website|network|wifi|account)\b", compact, re.I):
        score += 1
        questions.insert(0, "Which device, application, or service is affected?")
    flagged = score >= 3
    return {
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "priority": ticket.priority or "Unspecified",
        "flagged": flagged,
        "detail_score": max(0, 100 - score * 15),
        "evidence": evidence,
        "suggested_questions": list(dict.fromkeys(questions))[:4],
    }


FIRST_RESPONSE_SLA_HOURS = {"P1": 1.0, "P2": 4.0, "P3": 8.0}


def first_response_sla_status(
    ticket: TicketRecord,
    conversations: List[ExternalConversationRecord],
    *, now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    sla_exempt = ticket_is_sla_exempt(ticket)
    started_at = ticket.external_created_at or ticket.created_at or now
    due_at = ticket.external_fr_due_by or ticket.response_due_at
    if due_at and due_at > started_at:
        target_source = "provider_due_at"
        target_hours = (due_at - started_at).total_seconds() / 3600.0
    else:
        target_source = "priority_policy"
        target_hours = FIRST_RESPONSE_SLA_HOURS.get(ticket.priority, 8.0)
        due_at = started_at + timedelta(hours=target_hours)
    response_times = [
        _conversation_at(row) for row in conversations
        if not row.incoming and _conversation_at(row) >= started_at
    ]
    responded_at = min(response_times) if response_times else None
    conversation_coverage = bool(
        conversations
        or ticket.external_conversations_synced_at
        or not ticket.external_source
    )
    terminal_at = (
        ticket.external_resolved_at or ticket.resolved_at
        or ticket.external_updated_at or ticket.updated_at or now
    )
    observed_at = responded_at or (now if _open(ticket) else terminal_at)
    delta_hours = (due_at - observed_at).total_seconds() / 3600.0
    if sla_exempt or (not conversation_coverage and responded_at is None):
        status = "unmeasured"
        breached = False
        approaching = False
    else:
        breached = delta_hours < 0
        approaching = (
            not breached and responded_at is None and _open(ticket)
            and delta_hours <= target_hours * SLA_AT_RISK_THRESHOLD
        )
        status = "breached" if breached else (
            "approaching" if approaching else ("met" if responded_at else "on_track")
        )
    return {
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "priority": ticket.priority or "Unspecified",
        "metric": "first_response",
        "status": status,
        "breach_state": "active" if breached and responded_at is None and _open(ticket) else ("historical" if breached else None),
        "target_source": target_source,
        "target_hours": round(target_hours, 2),
        "started_at": started_at.isoformat(),
        "due_at": due_at.isoformat(),
        "completed_at": responded_at.isoformat() if responded_at else None,
        "remaining_hours": 0.0 if sla_exempt else round(max(0.0, delta_hours), 2),
        "overdue_hours": 0.0 if sla_exempt else round(max(0.0, -delta_hours), 2),
        "is_open": _open(ticket),
    }


def resolution_sla_monitor_status(
    ticket: TicketRecord,
    *, now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    sla_exempt = ticket_is_sla_exempt(ticket)
    started_at = ticket.external_created_at or ticket.created_at or now
    due_at = ticket.resolution_due_at or ticket.external_due_by or ticket.due_by
    configured = float(SLA_HOURS.get(ticket.priority, DEFAULT_SLA_HOURS))
    if due_at and due_at > started_at:
        target_source = "provider_due_at"
        target_hours = (due_at - started_at).total_seconds() / 3600.0
    else:
        target_source = "priority_policy"
        target_hours = configured
        due_at = started_at + timedelta(hours=target_hours)
    completed_at = ticket.external_resolved_at or ticket.resolved_at
    observed_at = completed_at or (now if _open(ticket) else ticket.external_updated_at or ticket.updated_at or now)
    delta_hours = (due_at - observed_at).total_seconds() / 3600.0
    if sla_exempt or (not _open(ticket) and completed_at is None):
        status = "unmeasured"
        breached = False
        approaching = False
    else:
        breached = delta_hours < 0
        approaching = (
            not breached and completed_at is None and _open(ticket)
            and delta_hours <= target_hours * SLA_AT_RISK_THRESHOLD
        )
        status = "breached" if breached else (
            "approaching" if approaching else ("met" if completed_at else "on_track")
        )
    return {
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "priority": ticket.priority or "Unspecified",
        "metric": "resolution",
        "status": status,
        "breach_state": "active" if breached and completed_at is None and _open(ticket) else ("historical" if breached else None),
        "target_source": target_source,
        "target_hours": round(target_hours, 2),
        "started_at": started_at.isoformat(),
        "due_at": due_at.isoformat(),
        "completed_at": completed_at.isoformat() if completed_at else None,
        "remaining_hours": 0.0 if sla_exempt else round(max(0.0, delta_hours), 2),
        "overdue_hours": 0.0 if sla_exempt else round(max(0.0, -delta_hours), 2),
        "is_open": _open(ticket),
    }


def run_level_zero_study(
    db: Session, *, months: int = 12, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Run a complete, unsampled historical Level Zero opportunity study."""
    now = now or datetime.utcnow()
    range_start = now - timedelta(days=months * 30)
    completed_at = func.coalesce(
        TicketRecord.external_resolved_at,
        TicketRecord.resolved_at,
        TicketRecord.external_updated_at,
        TicketRecord.updated_at,
    )
    base = db.query(TicketRecord).filter(
        func.lower(func.coalesce(TicketRecord.status, "")).in_(["closed", "resolved"]),
        completed_at >= range_start,
        completed_at <= now,
        TicketRecord.portal_access_token_hash.is_(None),
    )
    analyzed = base.count()
    source_data_through = base.with_entities(func.max(completed_at)).scalar()

    # Outgoing public replies are resolution evidence. Only the matching theme
    # label is retained; customer or agent message content is never returned.
    outgoing_themes: Dict[str, tuple[str, str]] = {}
    outgoing_rows = db.query(
        ExternalConversationRecord.ticket_id,
        ExternalConversationRecord.body,
    ).join(
        TicketRecord,
        TicketRecord.id == ExternalConversationRecord.ticket_id,
    ).filter(
        func.lower(func.coalesce(TicketRecord.status, "")).in_(["closed", "resolved"]),
        completed_at >= range_start,
        completed_at <= now,
        ExternalConversationRecord.deleted.is_(False),
        ExternalConversationRecord.is_private.is_(False),
        ExternalConversationRecord.incoming.is_(False),
        ExternalConversationRecord.body.isnot(None),
    ).yield_per(1_000)
    for ticket_id, body in outgoing_rows:
        if ticket_id in outgoing_themes:
            continue
        match = _level_zero_theme(body or "")
        if match:
            outgoing_themes[ticket_id] = match

    candidates: List[Dict[str, Any]] = []
    theme_counts: Counter = Counter()
    confidence_counts: Counter = Counter()
    for ticket in base.order_by(completed_at.desc(), TicketRecord.id.asc()).yield_per(500):
        request_text = " ".join(filter(None, (
            ticket.subject,
            ticket.description,
            ticket.external_category,
            ticket.external_subcategory,
            ticket.external_item_category,
        )))
        resolution_text = " ".join(filter(None, (ticket.summary, ticket.recommended_solution)))
        resolution_match = outgoing_themes.get(ticket.id) or _level_zero_theme(resolution_text)
        request_match = _level_zero_theme(request_text)
        match = resolution_match or request_match
        if not match:
            continue
        combined = f"{request_text} {resolution_text}"
        if (
            _LEVEL_ZERO_EXCLUSION.search(combined)
            or (ticket.priority or "").strip().lower() in {"p1", "urgent"}
            or (ticket.sentiment or "") in {"Business-Critical", "High-Impact"}
            or int(ticket.complexity or 1) > 2
        ):
            continue
        confidence = "high" if resolution_match else "medium"
        theme, evidence = match
        resolved_at = (
            ticket.external_resolved_at or ticket.resolved_at
            or ticket.external_updated_at or ticket.updated_at
        )
        theme_counts[theme] += 1
        confidence_counts[confidence] += 1
        candidates.append({
            "ticket_id": ticket.id,
            "subject": ticket.subject,
            "theme": theme,
            "confidence": confidence,
            "evidence": evidence if resolution_match else f"Request matches {theme.lower()} automation pattern",
            "resolved_at": resolved_at.isoformat() if resolved_at else None,
            "priority": ticket.priority or "Unspecified",
        })

    candidates.sort(key=lambda item: (
        0 if item["confidence"] == "high" else 1,
        item["theme"],
        item["ticket_id"],
    ))
    eligible = len(candidates)
    return {
        "study_type": "level_zero_opportunity",
        "period_months": months,
        "range_start_at": range_start.isoformat(),
        "range_end_at": now.isoformat(),
        "source_data_through_at": source_data_through.isoformat() if source_data_through else None,
        "method": "complete_unsampled_rule_assessment",
        "analyzed_tickets": analyzed,
        "eligible_tickets": eligible,
        "high_confidence_tickets": confidence_counts["high"],
        "review_candidates": confidence_counts["medium"],
        "estimated_annualized_opportunities": round(eligible * 12 / max(1, months)),
        "opportunity_rate": round(eligible / max(1, analyzed), 4),
        "by_theme": [
            {"theme": theme, "count": count}
            for theme, count in theme_counts.most_common()
        ],
        "items": candidates[:100],
        "items_truncated": eligible > 100,
        "safeguards": [
            "P1, high-impact, security, outage, data-loss, and hardware-replacement work is excluded",
            "High confidence requires simple-resolution evidence; request-only matches remain review candidates",
            "The assessment is advisory and does not send replies or change tickets",
        ],
    }


def create_level_zero_study_snapshot(
    db: Session,
    *,
    months: int = 12,
    created_by: Optional[str] = None,
    now: Optional[datetime] = None,
) -> tuple[IntelligenceStudyRecord, Dict[str, Any]]:
    """Run and durably retain a deliberate Level Zero study snapshot."""
    now = now or datetime.utcnow()
    result = run_level_zero_study(db, months=months, now=now)
    record = IntelligenceStudyRecord(
        id=secrets.token_hex(18),
        study_type="level_zero_opportunity",
        period_months=months,
        range_start_at=datetime.fromisoformat(result["range_start_at"]),
        range_end_at=datetime.fromisoformat(result["range_end_at"]),
        source_data_through_at=(
            datetime.fromisoformat(result["source_data_through_at"])
            if result["source_data_through_at"] else None
        ),
        analyzed_tickets=result["analyzed_tickets"],
        eligible_tickets=result["eligible_tickets"],
        result_json=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        created_by=created_by,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, result


# ── 5. Summarization Agent (LLM-backed) ───────────────────────────────────


async def summarize_ticket(
    llm: LLMManager, ticket: TicketRecord, *, force: bool = False
) -> str | None:
    """LLM-generated case summary (cached on the ticket).
    Returns None when the LLM fails — the caller should not persist None."""
    # Ignore stale fallback placeholders so existing tickets get regenerated.
    if not force and ticket.summary and "auto summary unavailable" not in ticket.summary:
        return ticket.summary
    prompt = canonical_bounded_json(
        {
            "subject": redact_text(ticket.subject),
            "description": redact_text(ticket.description or ""),
            "public_thread": redact_text(
                getattr(ticket, "external_conversation_text", "") or ""
            ),
            "triage_reasoning": redact_text(ticket.ai_reasoning or ""),
        },
        max_chars=prompt_char_limit(llm),
        field_limits={
            "subject": 1_000,
            "description": 10_000,
            "public_thread": 12_000,
            "triage_reasoning": 4_000,
        },
    )
    result = await llm.analyze(
        prompt,
        response_model=TicketSummary,
        system_prompt=SUMMARY_SYSTEM_PROMPT,
        max_tokens=500,
    )
    summary = neutralize_generated_uris(
        (result.get("summary") or "").strip()
    )
    try:
        validate_semantic_advice(summary)
    except UnsafeAIAdviceError as exc:
        raise LLMInvalidOutputError(
            "AI provider returned unsafe summary output"
        ) from exc
    # Don't persist the fallback placeholder — it's not a real summary.
    # The frontend will show a clean "unavailable" state instead.
    return summary or None


# ── 5b. Resolution Agent (LLM-backed) ─────────────────────────────

# Produces a concrete, actionable resolution plan the assigned engineer can
# follow: root-cause hypothesis, ordered steps, confidence, and when to
# escalate. Cached on the ticket as `recommended_solution` (JSON string).


def _semantic_retry_system_prompt(
    system_prompt: str, violations: tuple[str, ...]
) -> str:
    """Ask once for a clean replacement after deterministic policy rejection."""
    classifications = ", ".join(sorted(violations)) or "unsafe_advice"
    return (
        f"{system_prompt}\n\n"
        "The prior candidate output was rejected by deterministic safety "
        f"validation ({classifications}). Produce a completely new answer. "
        "Do not quote or minimally edit the rejected answer. Do not request "
        "credentials, include links or executable commands, or propose "
        "disabling, bypassing, or weakening any security control. Keep every "
        "step reversible and suitable for human review."
    )


async def recommend_resolution(
    llm: LLMManager, ticket: TicketRecord
) -> Dict[str, Any]:
    """LLM-generated resolution plan for the assigned engineer.

    Cached on the ticket as `recommended_solution` (JSON). Returns the parsed
    plan dict so the endpoint can shape the response.
    """
    prompt = canonical_bounded_json(
        {
            "subject": redact_text(ticket.subject),
            "description": redact_text(ticket.description or ""),
            "public_thread": redact_text(
                getattr(ticket, "external_conversation_text", "") or ""
            ),
            "triage_reasoning": redact_text(ticket.ai_reasoning or ""),
        },
        fixed_fields={
            "category": ticket.category or "Other",
            "priority": ticket.priority or "P3",
            "sentiment": ticket.sentiment or "Neutral",
        },
        max_chars=prompt_char_limit(llm),
        field_limits={
            "subject": 1_000,
            "description": 10_000,
            "public_thread": 12_000,
            "triage_reasoning": 4_000,
        },
    )
    plan = await llm.analyze(
        prompt,
        response_model=ResolutionAnalysis,
        system_prompt=RESOLUTION_SYSTEM_PROMPT,
        max_tokens=1_200,
    )
    plan = neutralize_generated_uris(plan)
    try:
        validate_semantic_advice(plan)
    except UnsafeAIAdviceError as exc:
        plan = await llm.analyze(
            prompt,
            response_model=ResolutionAnalysis,
            system_prompt=_semantic_retry_system_prompt(
                RESOLUTION_SYSTEM_PROMPT, exc.violations
            ),
            max_tokens=1_200,
        )
        plan = neutralize_generated_uris(plan)
        try:
            validate_semantic_advice(plan)
        except UnsafeAIAdviceError as retry_exc:
            raise LLMInvalidOutputError(
                "AI provider returned unsafe resolution advice"
            ) from retry_exc
    return plan


# ── 6. Account Health Agent ────────────────────────────────────────────────

def account_health(
    db: Session,
    reporter: str,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Per-reporter health inside the selected operational activity window."""
    query = _scope_query(
        db.query(TicketRecord).filter(TicketRecord.reporter == reporter),
        since,
    )
    total = query.count()
    if not total:
        return {"reporter": reporter, "health_score": None, "churn_risk": "unknown",
                "open": 0, "total": 0}
    open_n = query.filter(or_(
        TicketRecord.status.is_(None),
        func.lower(TicketRecord.status).notin_(["closed", "resolved", "cancelled"]),
    )).count()
    resolved_n = query.filter(TicketRecord.resolved_at.isnot(None)).count()
    tickets = query.order_by(
        TicketRecord.updated_at.desc().nullslast(), TicketRecord.id.asc()
    ).limit(_MAX_ANALYTICS_ROWS).all()

    analyzed = len(tickets)
    avg_risk = sum(escalation_risk(t) for t in tickets) / analyzed

    # Sentiment pain: count negative sentiments.
    pain = sum(
        1 for t in tickets
        if (t.sentiment or "") in {"Business-Critical", "High-Impact"}
    )
    pain_ratio = pain / analyzed

    # Health = 100 - risk-driven penalties.
    health = 100 - (avg_risk * 0.5) - (pain_ratio * 30) - (min(open_n, 5) * 4)
    health = _clamp(health)

    if health >= 70:
        risk = "low"
    elif health >= 45:
        risk = "medium"
    else:
        risk = "high"

    return {
        "reporter": reporter,
        "health_score": health,
        "churn_risk": risk,
        "open": open_n,
        "resolved": resolved_n,
        "total": total,
        "avg_escalation_risk": round(avg_risk, 1),
        "negative_sentiment_ratio": round(pain_ratio, 2),
        "analyzed_tickets": analyzed,
        "truncated": total > analyzed,
    }


# ── 7. Text Analytics Agent ───────────────────────────────────────────────


def _non_portal_ticket_query(db: Session):
    return db.query(TicketRecord).filter(
        func.lower(func.coalesce(TicketRecord.external_source, "")) != "portal"
    )


def _trusted_text_evidence_query(db: Session):
    """Use only Tickety-owned prose for cross-ticket text aggregation."""
    return db.query(TicketRecord).filter(or_(
        TicketRecord.external_source.is_(None),
        func.lower(TicketRecord.external_source).in_(["manual", "standalone"]),
    ))


def trends(
    db: Session,
    limit_terms: int = 15,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate trends inside an explicit operational activity window."""
    aggregate_query = _scope_query(_non_portal_ticket_query(db), since)
    total_tickets = aggregate_query.count()
    tickets = aggregate_query.order_by(
        TicketRecord.updated_at.desc().nullslast(), TicketRecord.id.asc()
    ).limit(_MAX_ANALYTICS_ROWS).all()
    text_tickets = _scope_query(_trusted_text_evidence_query(db), since).order_by(
        TicketRecord.updated_at.desc().nullslast(), TicketRecord.id.asc()
    ).limit(_MAX_ANALYTICS_ROWS).all()

    categories = Counter()
    sentiments = Counter()
    statuses = Counter()
    word_counter: Counter = Counter()

    token_re = re.compile(r"[A-Za-z][A-Za-z0-9_'-]{2,}")
    for t in tickets:
        if t.category:
            categories[t.category] += 1
        if t.sentiment:
            sentiments[t.sentiment] += 1
        if t.status:
            statuses[t.status] += 1
    for t in text_tickets:
        text = (f"{t.subject or ''} {t.description or ''}").lower()
        for tok in token_re.findall(text):
            if tok in _STOPWORDS:
                continue
            if len(tok) < 4:
                continue
            word_counter[tok] += 1

    return {
        "total_tickets": total_tickets,
        "analyzed_tickets": len(tickets),
        "text_evidence_tickets": len(text_tickets),
        "truncated": total_tickets > len(tickets),
        "by_category": dict(categories.most_common()),
        "by_sentiment": dict(sentiments.most_common()),
        "by_status": dict(statuses.most_common()),
        "top_terms": word_counter.most_common(limit_terms),
    }


# ── 8. Proactive Alert Agent ──────────────────────────────────────────────

# ── 7b. Systemic Issue Detection ──────────────────────────────────────────

def _ticket_keywords(ticket) -> set:
    text = f"{ticket.subject or ''} {ticket.description or ''}".lower()
    token_re = __import__("re").compile(r"[a-z][a-z0-9_'-]{2,}")
    return {t for t in token_re.findall(text) if t not in _STOPWORDS}

def _jaccard(a: set, b: set) -> float:
    if not a or not b: return 0.0
    return len(a & b) / len(a | b)

from collections import Counter
def systemic_issues(
    db,
    cluster_threshold: int = 3,
    similarity_cutoff: float = 0.25,
    since: Optional[datetime] = None,
) -> dict:
    # Pairwise similarity is O(n^2); bound the working set so one request
    # cannot monopolize an API worker on an arbitrarily large installation.
    trusted_query = _scope_query(_trusted_text_evidence_query(db), since)
    total_tickets = trusted_query.count()
    tickets = trusted_query.order_by(
        TicketRecord.updated_at.desc().nullslast(), TicketRecord.id.asc()
    ).limit(500).all()
    if len(tickets) < 2:
        return {
            "clusters": [],
            "total_tickets": total_tickets,
            "analyzed_tickets": len(tickets),
            "truncated": total_tickets > len(tickets),
            "clustered_tickets": 0,
            "parameters": {
                "similarity_cutoff": similarity_cutoff,
                "min_cluster_size": cluster_threshold,
            },
        }

    keywords = {t.id: _ticket_keywords(t) for t in tickets}
    ids = list(keywords.keys())
    adj = {tid: set() for tid in ids}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if _jaccard(keywords[ids[i]], keywords[ids[j]]) >= similarity_cutoff:
                adj[ids[i]].add(ids[j])
                adj[ids[j]].add(ids[i])

    visited = set()
    clusters = []
    for tid in ids:
        if tid in visited: continue
        stack = [tid]; component = []
        while stack:
            n = stack.pop()
            if n in visited: continue
            visited.add(n); component.append(n)
            stack.extend(adj[n] - visited)
        if len(component) >= cluster_threshold:
            clusters.append(component)

    pw = {"P1": 4, "P2": 3, "P3": 2}
    tmap = {t.id: t for t in tickets}
    results = []
    for comp in clusters:
        cts = [tmap[tid] for tid in comp if tid in tmap]
        if len(cts) < cluster_threshold: continue
        kw_sets = [keywords[t.id] for t in cts]
        common = kw_sets[0].copy() if kw_sets else set()
        for ks in kw_sets[1:]: common &= ks
        if not common and len(kw_sets) >= 2: common = kw_sets[0] & kw_sets[-1]
        avg_w = sum(pw.get(t.priority or "P3", 2) for t in cts) / len(cts)
        avg_r = sum(t.escalation_risk or 0 for t in cts) / len(cts)
        impact = len(cts) * avg_w * max(avg_r / 50 + 0.5, 1.0)
        results.append({
            "cluster_id": f"sys-{len(results)+1:03d}",
            "ticket_count": len(cts),
            "ticket_ids": [t.id for t in cts[:10]],
            "avg_priority_weight": round(avg_w, 1),
            "avg_escalation_risk": round(avg_r, 1),
            "business_impact_score": round(impact, 1),
            "shared_keywords": sorted(common)[:12],
            "samples": [t.subject for t in cts[:5]],
            "status_breakdown": dict(Counter(t.status for t in cts).most_common()),
        })
    results.sort(key=lambda c: c["business_impact_score"], reverse=True)
    return {
        "clusters": results,
        "total_tickets": total_tickets,
        "analyzed_tickets": len(tickets),
        "truncated": total_tickets > len(tickets),
        "clustered_tickets": sum(c["ticket_count"] for c in results),
        "parameters": {"similarity_cutoff": similarity_cutoff, "min_cluster_size": cluster_threshold},
    }

def proactive_alerts(
    db: Session,
    now: Optional[datetime] = None,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Unified feed of cases needing human attention right now:
    escalation-prone, SLA at-risk, and SLA-breached tickets."""
    now = now or datetime.utcnow()
    open_query = db.query(TicketRecord).filter(or_(
        TicketRecord.status.is_(None),
        func.lower(TicketRecord.status).notin_(["closed", "resolved", "cancelled"]),
    ))
    open_query = _scope_query(open_query, since)
    total_open = open_query.count()
    open_tickets = open_query.order_by(
        case(
            {"P1": 1, "Urgent": 1, "P2": 2, "High": 2, "P3": 3, "Medium": 3},
            value=TicketRecord.priority,
            else_=4,
        ).asc(),
        _ticket_activity_expression().desc().nullslast(),
        TicketRecord.id.asc(),
    ).limit(_MAX_ANALYTICS_ROWS).all()

    escalate_prone = []
    sla_at_risk = []
    sla_breached = []
    for t in open_tickets:
        risk = escalation_risk(t, now)
        if risk >= 70:
            escalate_prone.append({"ticket_id": t.id, "subject": t.subject,
                                    "risk": risk, "priority": t.priority})
        sla = sla_status(t, now)
        if sla["status"] == "at_risk":
            sla_at_risk.append(sla)
        elif sla["status"] == "breached":
            sla_breached.append(sla)

    # Sort by severity.
    escalate_prone.sort(key=lambda x: x["risk"], reverse=True)
    sla_at_risk.sort(key=lambda x: x["remaining_hours"])
    sla_breached.sort(key=lambda x: x["elapsed_hours"], reverse=True)

    return {
        "generated_at": now.isoformat(),
        "total_open_tickets": total_open,
        "analyzed_tickets": len(open_tickets),
        "truncated": total_open > len(open_tickets),
        "summary": {
            "escalation_prone": len(escalate_prone),
            "sla_at_risk": len(sla_at_risk),
            "sla_breached": len(sla_breached),
        },
        "escalation_prone": escalate_prone,
        "sla_at_risk": sla_at_risk,
        "sla_breached": sla_breached,
    }
