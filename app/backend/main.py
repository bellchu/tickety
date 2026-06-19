import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .database import (
    init_db, get_db, SessionLocal,
    TicketRecord, UserRecord, RecognitionRecord,
    UserMappingRecord, SyncStateRecord,
)
from .schema import (
    Ticket, User, UserSummary, Recognition, SyncStatus,
    TriageResult, PointsAwardedNotification, TicketCreate,
    ResolutionPlan, RecommendedSolution,
)
from .llm_manager import LLMManager, get_llm_catalog
from .brain import IntelligenceEngine
from . import intelligence as intel
from .prompts import (
    RECOGNITIONS, TIER_THRESHOLDS, PRIORITY_POINTS,
    MOMENTUM_BONUS_CAP, MOMENTUM_RESET_HOURS,
)
from .integrations.registry import get_adapter
from .integrations.sync import sync_tickets_from_external, handle_webhook_event, fetch_tickets_by_days, sync_agents_from_external
from .integrations.freshservice import FreshserviceAdapter
from .sync_worker import start_sync_worker, get_sync_status
from . import settings as settings_module

# Single source of truth for the backend version. Bump when shipping user-visible
# changes. Build SHA/time are injected at image build time (see Dockerfile).
VERSION = "2.2.0"
BUILD_SHA = os.getenv("TICKETY_BUILD_SHA", "local")
BUILD_TIME = os.getenv("TICKETY_BUILD_TIME", "")

app = FastAPI(title="Tickety", version=VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm_mgr = LLMManager()
engine = IntelligenceEngine(llm_mgr)

# WebSocket connection manager for real-time notifications
_notification_subscribers: list = []


async def _broadcast_notification(notification: dict):
    dead = []
    for ws in _notification_subscribers:
        try:
            await ws.send_json(notification)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _notification_subscribers:
            _notification_subscribers.remove(ws)


@app.on_event("startup")
async def startup():
    init_db()
    # Hydrate env from DB overrides BEFORE building the LLM manager so that
    # keys saved via the settings UI are picked up on restart too.
    settings_module.load_settings_into_env()
    global llm_mgr
    llm_mgr = LLMManager()
    engine.llm = llm_mgr
    from .seed import run_seed
    run_seed()
    start_sync_worker()


# ── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": VERSION,
        "build_sha": BUILD_SHA,
        "build_time": BUILD_TIME,
    }


@app.get("/version")
async def version():
    """Build/version info for the footer. Lets you identify exactly which
    image a running pod is running (version + git SHA + build timestamp)."""
    return {
        "app": "Tickety",
        "component": "backend",
        "version": VERSION,
        "build_sha": BUILD_SHA,
        "build_time": BUILD_TIME,
    }


# ── Tickets ──────────────────────────────────────────────────

@app.get("/tickets", response_model=List[Ticket])
async def list_tickets(db: Session = Depends(get_db)):
    return db.query(TicketRecord).order_by(desc(TicketRecord.created_at)).all()


@app.get("/tickets/{ticket_id}", response_model=Ticket)
async def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# ── Manual ticket creation ───────────────────────────────────

@app.post("/tickets", response_model=Ticket, status_code=201)
async def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    """Create a ticket by hand (no ITSM sync). Auto-triaged if enabled."""
    import uuid as _uuid
    ticket = TicketRecord(
        id=str(_uuid.uuid4()),
        subject=payload.subject.strip(),
        description=payload.description,
        reporter=payload.reporter.strip() or "manual",
        status="New",
        priority=payload.priority,
        external_source="manual",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    await _auto_process(ticket, db)
    return ticket


async def _auto_process(ticket: TicketRecord, db):
    """Run the full AI pipeline on a ticket — triage, summarization,
    routing, and resolution — all automatic, no user interaction needed.
    When the user opens the ticket every insight is already there."""
    if ticket.ai_reasoning:
        return  # already processed

    print(f"[auto] triaging {ticket.id[:8]}")
    analysis = await engine.process_ticket({
        "subject": ticket.subject,
        "description": ticket.description,
    })
    ticket.sentiment = analysis.get("sentiment")
    ticket.category = analysis.get("category")
    ticket.priority = analysis.get("priority")
    ticket.mood = analysis.get("mood")
    ticket.complexity = analysis.get("complexity", 1)
    ticket.ai_reasoning = analysis.get("reasoning")
    ticket.escalation_risk = intel.escalation_risk(ticket)
    if analysis.get("suggested_response"):
        ticket.suggested_response = analysis.get("suggested_response")
        ticket.status = "Awaiting Review"
    elif analysis.get("action") == "escalate":
        ticket.status = "Escalated"
    else:
        ticket.status = "Processed"
    db.commit()
    db.refresh(ticket)

    # Summarization
    try:
        summary = await intel.summarize_ticket(engine.llm, ticket)
        if summary:
            ticket.summary = summary
            db.commit()
    except Exception as e:
        print(f"[auto] summarization failed: {e}")

    # Routing
    try:
        route = intel.recommend_assignee(db, ticket)
        print(f"[auto] routing: {route.get('recommended_name','-')}")
    except Exception as e:
        print(f"[auto] routing failed: {e}")

    # Resolution plan
    try:
        plan = await intel.recommend_resolution(engine.llm, ticket)
        ticket.recommended_solution = json.dumps(plan)
        db.commit()
    except Exception as e:
        print(f"[auto] resolution failed: {e}")


@app.post("/tickets/{ticket_id}/triage", response_model=TriageResult)
async def trigger_triage(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    kb_context = ""
    text = (ticket.subject + " " + ticket.description).lower()
    if "vpn" in text:
        kb_context = "To reset VPN, restart the client and click Reconnect. Ensure corporate Wi-Fi is connected."

    analysis_data = await engine.process_ticket({
        "subject": ticket.subject,
        "description": ticket.description,
    }, kb_info=kb_context)

    ticket.sentiment = analysis_data.get("sentiment")
    ticket.category = analysis_data.get("category")
    ticket.priority = analysis_data.get("priority")
    ticket.mood = analysis_data.get("mood")
    ticket.complexity = analysis_data.get("complexity", 1)
    ticket.ai_reasoning = analysis_data.get("reasoning")
    # Escalation Risk Agent: score 0-100, persisted for prioritization/alerts.
    ticket.escalation_risk = intel.escalation_risk(ticket)
    if analysis_data.get("suggested_response"):
        ticket.suggested_response = analysis_data.get("suggested_response")
        ticket.status = "Awaiting Review"
        ticket.ai_reasoning += f" | Suggested Response: {analysis_data['suggested_response']}"
    elif analysis_data.get("action") == "escalate":
        ticket.status = "Escalated"
    else:
        ticket.status = "Processed"

    db.commit()
    db.refresh(ticket)

    return TriageResult(
        ticket_id=ticket.id,
        sentiment=analysis_data.get("sentiment", "Neutral"),
        category=analysis_data.get("category", "Other"),
        priority=analysis_data.get("priority", "P3"),
        mood=analysis_data.get("mood", "neutral"),
        complexity=analysis_data.get("complexity", 1),
        action=analysis_data.get("action", "respond"),
        reasoning=analysis_data.get("reasoning", ""),
        suggested_response=analysis_data.get("suggested_response"),
        escalation_risk=ticket.escalation_risk or 0,
    )


# ── User / Engagement ────────────────────────────────────────

@app.get("/me", response_model=User)
async def get_current_user(db: Session = Depends(get_db)):
    user = db.query(UserRecord).first()
    if not user:
        raise HTTPException(status_code=404, detail="No users found")
    return user


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/leaderboard", response_model=List[UserSummary])
async def get_leaderboard(db: Session = Depends(get_db)):
    users = db.query(UserRecord).order_by(desc(UserRecord.impact_points)).all()
    result = []
    for i, u in enumerate(users):
        resolved_count = db.query(TicketRecord).filter(
            TicketRecord.resolved_by == u.id,
            TicketRecord.points_awarded > 0,
        ).count()
        result.append(UserSummary(
            id=u.id,
            name=u.name,
            avatar=u.avatar,
            title=u.title,
            impact_points=u.impact_points,
            tier=u.tier,
            momentum=u.momentum,
            tickets_resolved=resolved_count,
            rank=i + 1,
        ))
    return result


@app.get("/recognitions/{user_id}", response_model=List[Recognition])
async def get_user_recognitions(user_id: str, db: Session = Depends(get_db)):
    recs = db.query(RecognitionRecord).filter(
        RecognitionRecord.user_id == user_id
    ).order_by(desc(RecognitionRecord.unlocked_at)).all()
    result = []
    for r in recs:
        meta = RECOGNITIONS.get(r.recognition_key, {})
        result.append(Recognition(
            id=r.id,
            user_id=r.user_id,
            recognition_key=r.recognition_key,
            unlocked_at=r.unlocked_at,
            ticket_id=r.ticket_id,
            display_name=meta.get("display_name", r.recognition_key),
            description=meta.get("description", ""),
            icon=meta.get("icon", "award"),
        ))
    return result


# ── Sync / Admin ─────────────────────────────────────────────

@app.post("/admin/sync/trigger")
async def trigger_sync():
    adapter = get_adapter()
    result = sync_tickets_from_external(adapter)
    return {"status": "completed", "result": result}


@app.post("/admin/sync/fetch")
async def fetch_sync(
    days: int = Query(7, ge=1, le=365, description="Fetch tickets updated in the last N days"),
    overwrite: bool = Query(False, description="Overwrite already-imported tickets from the source"),
):
    """Manual "fetch by days" pull from the ITSM provider.

    Walks every page of tickets updated in the last `days` days while
    respecting the provider's rate limits. By default tickets that are
    already imported (matched by external_source + external_id) are skipped
    so re-running an overlapping window won't clobber local AI triage / status
    changes; pass overwrite=true to force-refresh them from the source.
    """
    adapter = get_adapter()
    result = fetch_tickets_by_days(adapter, days=days, overwrite=overwrite)
    return {"status": "completed", "result": result}


@app.get("/admin/sync/status", response_model=SyncStatus)
async def sync_status():
    s = get_sync_status()
    return SyncStatus(
        provider=s.get("provider", "none"),
        last_synced_at=datetime.fromisoformat(s["last_synced_at"]) if s.get("last_synced_at") else None,
        last_status=s.get("last_status", "idle"),
        last_error=s.get("last_error"),
        total_synced=s.get("total_synced", 0),
    )


# ── Settings ─────────────────────────────────────────────────

@app.post("/admin/sync/agents")
async def sync_agents():
    """Fetch agents from the ITSM provider and create Tickety user accounts.

    Pulls every agent from GET /api/v2/agents (with rate‑limit pacing),
    then creates or updates a matching Tickety UserRecord + UserMappingRecord.
    Returns {created, updated, errors, total}."""
    adapter = get_adapter()
    result = sync_agents_from_external(adapter)
    return {"status": "completed", "result": result}


@app.get("/admin/agents")
async def list_agents(db: Session = Depends(get_db)):
    """Return every user that has an external mapping (i.e. is an agent account)."""
    mappings = db.query(UserMappingRecord).all()
    mapped_ids = {m.tickety_user_id for m in mappings}
    users = db.query(UserRecord).filter(UserRecord.id.in_(mapped_ids)).all()
    out = []
    for u in users:
        m = next((x for x in mappings if x.tickety_user_id == u.id), None)
        out.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "title": u.title,
            "tier": u.tier,
            "impact_points": u.impact_points,
            "external_source": m.external_source if m else None,
            "external_assignee_id": m.external_assignee_id if m else None,
        })
    return {"agents": out}


# ── OAuth 2.0 (Freshworks App SDK / marketplace integration) ─────

@app.get("/oauth/status")
async def oauth_status():
    """Return whether OAuth is configured and a token is present."""
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    return {
        "configured": ad.oauth_configured,
        "connected": bool(ad.oauth_access_token),
        "domain": ad.domain,
    }


@app.get("/oauth/authorize")
async def oauth_authorize():
    """Return the Freshservice OAuth 2.0 authorization URL the user should visit."""
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    if not ad.oauth_configured:
        raise HTTPException(400, "OAuth client ID and secret not configured")
    return {"url": ad.oauth_authorization_url()}


@app.get("/oauth/callback")
async def oauth_callback(code: str = Query(..., description="The authorisation code from Freshservice")):
    """Exchange the OAuth code for tokens and persist them."""
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    try:
        tokens = await ad.oauth_exchange_code(code)
    except Exception as e:
        raise HTTPException(400, f"Token exchange failed: {e}")

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    if not access_token:
        raise HTTPException(400, "No access_token in response")

    # Persist tokens in the database so the adapter picks them up on restart.
    settings_module.update_settings({
        "FRESHSERVICE_OAUTH_ACCESS_TOKEN": access_token,
        "FRESHSERVICE_OAUTH_REFRESH_TOKEN": refresh_token,
    })
    # Also patch env so the current process sees them immediately.
    os.environ["FRESHSERVICE_OAUTH_ACCESS_TOKEN"] = access_token
    os.environ["FRESHSERVICE_OAUTH_REFRESH_TOKEN"] = refresh_token

    return {
        "status": "connected",
        "access_token": access_token[:12] + "…",
        "expires_in": tokens.get("expires_in"),
    }


@app.post("/oauth/refresh")
async def oauth_refresh():
    """Manually refresh the OAuth access token."""
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    try:
        tokens = await ad.oauth_refresh()
    except Exception as e:
        raise HTTPException(400, f"Token refresh failed: {e}")

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    settings_module.update_settings({
        "FRESHSERVICE_OAUTH_ACCESS_TOKEN": access_token,
        "FRESHSERVICE_OAUTH_REFRESH_TOKEN": refresh_token,
    })
    return {"status": "refreshed", "expires_in": tokens.get("expires_in")}


@app.post("/admin/sync/triage-all")
async def triage_all_untriaged(db: Session = Depends(get_db)):
    """Retroactively run AI triage on every ticket that hasn't been analysed yet.
    Useful after enabling auto‑triage or when tickets were imported before
    AI automation was turned on."""
    untriaged = db.query(TicketRecord).filter(
        TicketRecord.ai_reasoning.is_(None)
    ).all()
    count = 0
    for ticket in untriaged:
        try:
            await _auto_process(ticket, db)
            count += 1
        except Exception as e:
            print(f"[triage-all] error on {ticket.id}: {e}")
    return {"status": "completed", "found": len(untriaged), "processed": count}


@app.post("/admin/sync/repair")
async def repair_ai_gaps(db: Session = Depends(get_db)):
    """One‑time repair sweep: fill summary and resolution plan gaps for
    tickets that have triage data but are missing the later pipeline steps."""
    no_summary = db.query(TicketRecord).filter(
        TicketRecord.ai_reasoning.isnot(None),
        TicketRecord.summary.is_(None)
    ).all()
    no_resolution = db.query(TicketRecord).filter(
        TicketRecord.ai_reasoning.isnot(None),
        TicketRecord.recommended_solution.is_(None)
    ).all()

    results = {"summaries_filled": 0, "resolutions_filled": 0, "errors": 0}

    for ticket in no_summary:
        try:
            s = await intel.summarize_ticket(engine.llm, ticket)
            if s:
                ticket.summary = s
                db.commit()
                results["summaries_filled"] += 1
        except Exception as e:
            results["errors"] += 1
            print(f"[repair] summary error on {ticket.id[:8]}: {e}")

    for ticket in no_resolution:
        try:
            plan = await intel.recommend_resolution(engine.llm, ticket)
            ticket.recommended_solution = json.dumps(plan)
            db.commit()
            results["resolutions_filled"] += 1
        except Exception as e:
            results["errors"] += 1
            print(f"[repair] resolution error on {ticket.id[:8]}: {e}")

    return {
        "status": "completed",
        "found_no_summary": len(no_summary),
        "found_no_resolution": len(no_resolution),
        **results,
    }


@app.get("/admin/settings")
async def get_settings():
    return settings_module.get_settings()


@app.put("/admin/settings")
async def update_settings(payload: dict):
    return settings_module.update_settings(payload)


@app.get("/admin/llm/catalog")
async def llm_catalog():
    """Provider catalog for the settings UI: list of supported providers,
    their preset models, which env vars they need, and which of those are
    already configured. Never returns secret values."""
    return get_llm_catalog()


@app.post("/admin/llm/refresh-models")
async def refresh_models():
    """Fetch the latest available models from each configured LLM provider.

    Queries DeepSeek, OpenAI, and OpenRouter for their current model lists.
    Only providers with a valid API key configured are queried; others are
    left with their preset defaults. Results are persisted so the catalog
    picks them up on restart."""
    from .llm_manager import fetch_live_models
    results = await fetch_live_models()
    return {
        "status": "completed",
        "providers_queried": list(results.keys()),
        "total_models": sum(len(v) for v in results.values()),
        "results": {k: len(v) for k, v in results.items()},
    }


# ── Intelligence (SupportLogic-style ambient agents) ──────────

@app.get("/intelligence/alerts")
async def intel_alerts(db: Session = Depends(get_db)):
    """Proactive Alert Agent: unified feed of cases needing attention now."""
    return intel.proactive_alerts(db)


@app.get("/intelligence/prioritize")
async def intel_prioritize(db: Session = Depends(get_db)):
    """Prioritization Agent: open backlog ranked by composite urgency/impact/risk."""
    now = datetime.utcnow()
    open_tickets = [t for t in db.query(TicketRecord).all() if intel._open(t)]
    ranked = []
    for t in open_tickets:
        ranked.append({
            "ticket_id": t.id,
            "subject": t.subject,
            "priority": t.priority,
            "sentiment": t.sentiment,
            "category": t.category,
            "complexity": t.complexity,
            "escalation_risk": t.escalation_risk or 0,
            "age_hours": round(intel._age_hours(t, now), 2),
            "score": intel.prioritize_score(t, now),
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return {"generated_at": now.isoformat(), "backlog_size": len(ranked), "ranked": ranked}


@app.get("/intelligence/sla")
async def intel_sla(db: Session = Depends(get_db)):
    """SLA Agent: SLA clock state for every open ticket."""
    now = datetime.utcnow()
    rows = [intel.sla_status(t, now) for t in db.query(TicketRecord).all() if intel._open(t)]
    rows.sort(key=lambda r: r["remaining_hours"])
    return {"generated_at": now.isoformat(), "count": len(rows), "items": rows}


@app.get("/intelligence/trends")
async def intel_trends(db: Session = Depends(get_db)):
    """Text Analytics Agent: category/sentiment distribution + top terms."""
    return intel.trends(db)


@app.get("/intelligence/systemic")
async def intel_systemic(
    db: Session = Depends(get_db),
    min_cluster: int = Query(2, ge=2, le=20, description="Minimum tickets to flag as a systemic issue"),
):
    """Systemic Issue Detection: cluster similar tickets and surface broad
    business‑impact patterns. Returns clusters ranked by impact score, each
    with shared keywords, sample tickets, and priority/risk stats."""
    return intel.systemic_issues(db, cluster_threshold=min_cluster)


@app.get("/intelligence/workload")
async def agent_workload(db: Session = Depends(get_db)):
    """Agent workload: open tickets per agent + resolution metrics."""
    users = db.query(UserRecord).all()
    result = []
    for u in users:
        open_count = db.query(TicketRecord).filter(
            TicketRecord.resolved_by == u.id,
            TicketRecord.status.notin_(["Closed", "Resolved"]),
        ).count()
        total_resolved = db.query(TicketRecord).filter(
            TicketRecord.resolved_by == u.id,
        ).count()
        resolved_tickets = db.query(TicketRecord).filter(
            TicketRecord.resolved_by == u.id,
            TicketRecord.resolved_at.isnot(None),
            TicketRecord.created_at.isnot(None),
        ).all()
        avg_hours = 0.0
        if resolved_tickets:
            total_s = sum(
                (t.resolved_at - t.created_at).total_seconds()
                for t in resolved_tickets
            )
            avg_hours = round(total_s / len(resolved_tickets) / 3600, 1)
        result.append({
            "user_id": u.id,
            "name": u.name,
            "open_tickets": open_count,
            "total_resolved": total_resolved,
            "avg_resolution_hours": avg_hours,
            "impact_points": u.impact_points,
            "tier": u.tier,
        })
    result.sort(key=lambda r: r["open_tickets"], reverse=True)
    return {"agents": result}


@app.get("/intelligence/health/{reporter}")


@app.get("/intelligence/health/{reporter}")
async def intel_health(reporter: str, db: Session = Depends(get_db)):
    """Account Health Agent: per-reporter health score + churn-risk band."""
    result = intel.account_health(db, reporter)
    if result["health_score"] is None:
        raise HTTPException(status_code=404, detail="No tickets for that reporter")
    return result


@app.get("/intelligence/route/{ticket_id}")
async def intel_route(ticket_id: str, db: Session = Depends(get_db)):
    """Routing Agent: recommend the best engineer for a ticket."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return intel.recommend_assignee(db, ticket)


@app.post("/tickets/{ticket_id}/summary")
async def ticket_summary(ticket_id: str, db: Session = Depends(get_db)):
    """Summarization Agent: LLM-generated case summary (cached on the ticket)."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    summary = await intel.summarize_ticket(engine.llm, ticket)
    if summary:
        ticket.summary = summary
        db.commit()
        db.refresh(ticket)
    return {"ticket_id": ticket.id, "summary": summary}


@app.post("/intelligence/resolve/{ticket_id}", response_model=RecommendedSolution)
async def ticket_resolve(
    ticket_id: str,
    force: bool = Query(False, description="Regenerate even if a cached plan exists"),
    db: Session = Depends(get_db),
):
    """Resolution Agent: LLM-generated resolution plan the assigned engineer can
    follow. Cached on the ticket as `recommended_solution` (JSON string). Pass
    force=true to regenerate."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    cached = False
    if ticket.recommended_solution and not force:
        try:
            plan_dict = json.loads(ticket.recommended_solution)
            cached = True
        except Exception:
            plan_dict = await intel.recommend_resolution(engine.llm, ticket)
            ticket.recommended_solution = json.dumps(plan_dict)
            db.commit()
    else:
        plan_dict = await intel.recommend_resolution(engine.llm, ticket)
        ticket.recommended_solution = json.dumps(plan_dict)
        db.commit()
    db.refresh(ticket)
    return RecommendedSolution(
        ticket_id=ticket.id,
        plan=ResolutionPlan(**plan_dict),
        cached=cached,
    )


# ── Webhooks ─────────────────────────────────────────────────

@app.post("/webhooks/freshservice")
async def freshservice_webhook(payload: dict):
    adapter = get_adapter("freshservice")
    event = adapter.parse_webhook(payload, {})
    if not event:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    ticket = handle_webhook_event(event, adapter)
    if ticket:
        await _auto_process(ticket, SessionLocal())
        await _check_resolution_and_award(ticket)
    return {"status": "received", "ticket_id": ticket.id if ticket else None}


# ── Resolution & Points Awarding ─────────────────────────────

async def _check_resolution_and_award(ticket: TicketRecord):
    """Check if a ticket transitioned to Closed and award points to the assignee."""
    if ticket.external_status and ticket.external_status.lower() not in ("closed", "resolved"):
        return
    if ticket.points_awarded_sent:
        return

    db = SessionLocal()
    try:
        # Find assignee mapping
        if not ticket.external_assignee_id:
            return
        mapping = db.query(UserMappingRecord).filter(
            UserMappingRecord.external_source == ticket.external_source,
            UserMappingRecord.external_assignee_id == ticket.external_assignee_id,
        ).first()
        if not mapping:
            return

        user = db.query(UserRecord).filter(UserRecord.id == mapping.tickety_user_id).first()
        if not user:
            return

        # Calculate points
        base_points = PRIORITY_POINTS.get(ticket.priority, 15)
        momentum_multiplier = min(
            1 + (user.momentum * 0.1), MOMENTUM_BONUS_CAP
        )
        earned = int(base_points * momentum_multiplier)

        # Update user
        old_tier = user.tier
        user.impact_points += earned
        user.last_action_at = datetime.utcnow()
        user.momentum += 1

        # Determine new tier
        new_tier = 1
        for i in range(len(TIER_THRESHOLDS) - 1, -1, -1):
            if user.impact_points >= TIER_THRESHOLDS[i]:
                new_tier = i + 1 if i > 0 else 1
                break
        user.tier = new_tier
        tier_promoted = new_tier > old_tier

        # Update ticket
        ticket.resolved_by = user.id
        ticket.resolved_at = datetime.utcnow()
        ticket.points_awarded = earned
        ticket.points_awarded_sent = True

        # Check recognitions
        new_recognitions = _check_recognitions(db, user, ticket)

        db.commit()
        db.refresh(user)
        db.refresh(ticket)

        # Build notification
        notification = PointsAwardedNotification(
            ticket_id=ticket.id,
            ticket_subject=ticket.subject,
            user_id=user.id,
            user_name=user.name,
            points_earned=earned,
            new_total=user.impact_points,
            new_tier=user.tier,
            tier_promoted=tier_promoted,
            new_momentum=user.momentum,
            recognitions_unlocked=[
                Recognition(
                    id=0,
                    user_id=user.id,
                    recognition_key=r,
                    unlocked_at=datetime.utcnow(),
                    display_name=RECOGNITIONS[r]["display_name"],
                    description=RECOGNITIONS[r]["description"],
                    icon=RECOGNITIONS[r]["icon"],
                )
                for r in new_recognitions
            ],
        )
        await _broadcast_notification(notification.model_dump(mode="json"))

    except Exception as e:
        print(f"[award] error: {e}")
        db.rollback()
    finally:
        db.close()


def _check_recognitions(db: Session, user: UserRecord, ticket: TicketRecord) -> list:
    unlocked = []
    existing_keys = {
        r.recognition_key for r in
        db.query(RecognitionRecord).filter(RecognitionRecord.user_id == user.id).all()
    }

    resolved_count = db.query(TicketRecord).filter(
        TicketRecord.resolved_by == user.id,
        TicketRecord.points_awarded > 0,
    ).count()

    checks = {
        "first_resolution": resolved_count >= 1,
        "consistent_performer": user.momentum >= 10,
        "critical_specialist": db.query(TicketRecord).filter(
            TicketRecord.resolved_by == user.id,
            TicketRecord.priority == "P1",
            TicketRecord.points_awarded > 0,
        ).count() >= 5,
        "rapid_responder": (
            ticket.resolved_at and ticket.created_at
            and (ticket.resolved_at - ticket.created_at) < timedelta(minutes=5)
        ),
        "sentiment_expert": resolved_count >= 10,
        "reliability_streak": _check_reliability_streak(db, user),
    }

    for key, passes in checks.items():
        if passes and key not in existing_keys:
            db.add(RecognitionRecord(
                user_id=user.id,
                recognition_key=key,
                ticket_id=ticket.id,
            ))
            unlocked.append(key)

    return unlocked


def _check_reliability_streak(db: Session, user: UserRecord) -> bool:
    resolved = db.query(TicketRecord).filter(
        TicketRecord.resolved_by == user.id,
        TicketRecord.resolved_at.isnot(None),
    ).order_by(desc(TicketRecord.resolved_at)).limit(7).all()

    if len(resolved) < 7:
        return False

    days = set()
    for t in resolved:
        days.add(t.resolved_at.date())
    return len(days) >= 7


# ── WebSockets ───────────────────────────────────────────────

@app.websocket("/ws/tickets/{ticket_id}/stream")
async def ws_ticket_stream(ws: WebSocket, ticket_id: str):
    await ws.accept()
    db = SessionLocal()
    try:
        ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
        if not ticket:
            await ws.send_json({"error": "Ticket not found"})
            await ws.close()
            return

        steps = [
            {"step": "reading", "label": "Reading ticket details...", "status": "active"},
            {"step": "sentiment", "label": "Analyzing customer sentiment...", "status": "pending"},
            {"step": "categorize", "label": "Categorizing issue type...", "status": "pending"},
            {"step": "priority", "label": "Assessing priority level...", "status": "pending"},
            {"step": "mood", "label": "Inferring customer mood...", "status": "pending"},
            {"step": "complexity", "label": "Calculating complexity rating...", "status": "pending"},
            {"step": "done", "label": "Analysis complete", "status": "pending"},
        ]

        for i, step in enumerate(steps):
            step["status"] = "active"
            await ws.send_json({"type": "progress", "steps": steps})
            await asyncio.sleep(0.8)
            step["status"] = "done"
        # Flush the final state so every step (including "Analysis complete")
        # is reported as done — otherwise the last step keeps its "active"
        # status on the client and the spinner never stops.
        await ws.send_json({"type": "progress", "steps": steps})

        # Trigger actual triage
        analysis = await engine.process_ticket({
            "subject": ticket.subject,
            "description": ticket.description,
        })

        ticket.sentiment = analysis.get("sentiment")
        ticket.category = analysis.get("category")
        ticket.priority = analysis.get("priority")
        ticket.mood = analysis.get("mood")
        ticket.complexity = analysis.get("complexity", 1)
        ticket.ai_reasoning = analysis.get("reasoning")
        ticket.escalation_risk = intel.escalation_risk(ticket)
        if analysis.get("suggested_response"):
            ticket.suggested_response = analysis.get("suggested_response")
        db.commit()

        await ws.send_json({"type": "complete", "result": analysis})
        await ws.close()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close()
    finally:
        db.close()


@app.websocket("/ws/notifications")
async def ws_notifications(ws: WebSocket):
    await ws.accept()
    _notification_subscribers.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in _notification_subscribers:
            _notification_subscribers.remove(ws)