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
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import TicketRecord, UserRecord
from .llm_manager import LLMManager

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


# ── helpers ───────────────────────────────────────────────────────────────

def _age_hours(t: TicketRecord, now: Optional[datetime] = None) -> float:
    now = now or datetime.utcnow()
    delta = now - (t.resolved_at or t.updated_at or t.created_at or now)
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
    if _open(t):
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
    sla_h = SLA_HOURS.get(t.priority, DEFAULT_SLA_HOURS)
    target = timedelta(hours=sla_h)
    start = t.created_at or now
    end = t.resolved_at or (now if _open(t) else (t.updated_at or now))
    elapsed = max(0.0, (end - start).total_seconds() / 3600.0)
    remaining_h = sla_h - elapsed
    breached = remaining_h <= 0 and _open(t)
    at_risk = (
        not breached
        and _open(t)
        and remaining_h <= sla_h * SLA_AT_RISK_THRESHOLD
        and remaining_h > 0
    )
    return {
        "ticket_id": t.id,
        "subject": t.subject,
        "priority": t.priority,
        "sla_target_hours": sla_h,
        "elapsed_hours": round(elapsed, 2),
        "remaining_hours": round(max(0.0, remaining_h), 2),
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
    users = db.query(UserRecord).all()
    if not users:
        return {"recommended_user_id": None, "candidates": []}

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
    }


# ── 5. Summarization Agent (LLM-backed) ───────────────────────────────────

_SUMMARY_PROMPT = (
    "Summarize the following IT support ticket in 2-3 concise sentences for a "
    "support manager. Capture the issue, urgency, and any action already taken. "
    "Return JSON: {{\"summary\": \"...\"}}.\n\n"
    "Subject: {subject}\nDescription: {description}\n"
    "AI triage reasoning so far: {reasoning}"
)


async def summarize_ticket(
    llm: LLMManager, ticket: TicketRecord
) -> str | None:
    """LLM-generated case summary (cached on the ticket).
    Returns None when the LLM fails — the caller should not persist None."""
    # Ignore stale fallback placeholders so existing tickets get regenerated.
    if ticket.summary and "auto summary unavailable" not in ticket.summary:
        return ticket.summary
    prompt = _SUMMARY_PROMPT.format(
        subject=ticket.subject,
        description=ticket.description or "",
        reasoning=ticket.ai_reasoning or "",
    )
    result = await llm.analyze(prompt, json_schema={})
    summary = (result.get("summary") or "").strip()
    # Don't persist the fallback placeholder — it's not a real summary.
    # The frontend will show a clean "unavailable" state instead.
    return summary or None


# ── 5b. Resolution Agent (LLM-backed) ─────────────────────────────

# Produces a concrete, actionable resolution plan the assigned engineer can
# follow: root-cause hypothesis, ordered steps, confidence, and when to
# escalate. Cached on the ticket as `recommended_solution` (JSON string).
_RESOLUTION_PROMPT = (
    "You are a senior IT support engineer. Given the ticket below, produce a "
    "concrete resolution plan that the assigned engineer can follow directly "
    "to resolve the issue. Be specific and actionable; prefer standard, safe "
    "troubleshooting steps. Do not invent credentials, IPs, or private data.\n\n"
    "Subject: {subject}\n"
    "Description: {description}\n"
    "Category: {category}\nPriority: {priority}\nSentiment: {sentiment}\n"
    "AI triage reasoning so far: {reasoning}\n\n"
    "Return exactly this JSON:\n"
    "{{\n"
    "  \"root_cause_hypothesis\": \"most likely root cause in one sentence\",\n"
    "  \"resolution_steps\": [\"ordered, concrete step 1\", \"step 2\", ...],\n"
    "  \"confidence\": \"high | medium | low\",\n"
    "  \"estimated_effort\": \"low | medium | high\",\n"
    "  \"escalation_advice\": \"when/how to escalate if the steps don't fix it\",\n"
    "  \"preventive_note\": \"one-line fix to prevent recurrence, or empty\"\n"
    "}}"
)


async def recommend_resolution(
    llm: LLMManager, ticket: TicketRecord
) -> Dict[str, Any]:
    """LLM-generated resolution plan for the assigned engineer.

    Cached on the ticket as `recommended_solution` (JSON). Returns the parsed
    plan dict so the endpoint can shape the response.
    """
    prompt = _RESOLUTION_PROMPT.format(
        subject=ticket.subject,
        description=ticket.description or "",
        category=ticket.category or "Other",
        priority=ticket.priority or "P3",
        sentiment=ticket.sentiment or "Neutral",
        reasoning=ticket.ai_reasoning or "",
    )
    result = await llm.analyze(prompt, json_schema={})
    # Normalize / fill defaults so the UI always has the expected shape.
    steps = result.get("resolution_steps") or []
    if isinstance(steps, str):
        steps = [steps]
    plan = {
        "root_cause_hypothesis": result.get("root_cause_hypothesis") or "",
        "resolution_steps": [str(s).strip() for s in steps if str(s).strip()],
        "confidence": (result.get("confidence") or "medium").lower(),
        "estimated_effort": (result.get("estimated_effort") or "medium").lower(),
        "escalation_advice": result.get("escalation_advice") or "",
        "preventive_note": result.get("preventive_note") or "",
    }
    return plan


# ── 6. Account Health Agent ────────────────────────────────────────────────

def account_health(db: Session, reporter: str) -> Dict[str, Any]:
    """Per-reporter health score (churn-risk proxy) from their ticket history."""
    tickets = db.query(TicketRecord).filter(TicketRecord.reporter == reporter).all()
    if not tickets:
        return {"reporter": reporter, "health_score": None, "churn_risk": "unknown",
                "open": 0, "total": 0}

    total = len(tickets)
    open_tickets = [t for t in tickets if _open(t)]
    open_n = len(open_tickets)
    resolved = [t for t in tickets if t.resolved_at]
    resolved_n = len(resolved)
    avg_risk = sum(escalation_risk(t) for t in tickets) / total

    # Sentiment pain: count negative sentiments.
    pain = sum(
        1 for t in tickets
        if (t.sentiment or "") in {"Business-Critical", "High-Impact"}
    )
    pain_ratio = pain / total

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
    }


# ── 7. Text Analytics Agent ───────────────────────────────────────────────

def trends(db: Session, limit_terms: int = 15) -> Dict[str, Any]:
    """Aggregate trends across all tickets: category & sentiment distribution,
    status counts, and top keywords (lightweight VOC)."""
    tickets = db.query(TicketRecord).all()

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
        text = (f"{t.subject or ''} {t.description or ''}").lower()
        for tok in token_re.findall(text):
            if tok in _STOPWORDS:
                continue
            if len(tok) < 4:
                continue
            word_counter[tok] += 1

    return {
        "total_tickets": len(tickets),
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
def systemic_issues(db, cluster_threshold: int = 3, similarity_cutoff: float = 0.25) -> dict:
    tickets = db.query(TicketRecord).all()
    if len(tickets) < 2:
        return {"clusters": [], "total_tickets": len(tickets)}

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
        "total_tickets": len(tickets),
        "clustered_tickets": sum(c["ticket_count"] for c in results),
        "parameters": {"similarity_cutoff": similarity_cutoff, "min_cluster_size": cluster_threshold},
    }

def proactive_alerts(db: Session, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Unified feed of cases needing human attention right now:
    escalation-prone, SLA at-risk, and SLA-breached tickets."""
    now = now or datetime.utcnow()
    open_tickets = [t for t in db.query(TicketRecord).all() if _open(t)]

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
        "summary": {
            "escalation_prone": len(escalate_prone),
            "sla_at_risk": len(sla_at_risk),
            "sla_breached": len(sla_breached),
        },
        "escalation_prone": escalate_prone,
        "sla_at_risk": sla_at_risk,
        "sla_breached": sla_breached,
    }