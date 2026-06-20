import os
import json
import asyncio
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from .database import (
    init_db, get_db, SessionLocal,
    TicketRecord, UserRecord, RecognitionRecord,
    UserMappingRecord, SyncStateRecord,
    TicketCommentRecord, TicketCategoryRecord, TicketAuditLogRecord,
    SessionRecord, KbArticleRecord, TicketLinkRecord,
    TicketStatusConfigRecord, TicketPriorityConfigRecord, NotificationConfigRecord,
    ProjectRecord, ServiceItemRecord, ServiceRequestRecord,
    ProblemRecord, ProblemTicketLinkRecord,
    ChangeRecord, ChangeApprovalRecord, ChangeTicketLinkRecord,
    AssetRecord,
    SurveyTemplateRecord, SurveyRecord, SurveyResponseRecord,
    TimeEntryRecord,
)
from .schema import (
    Ticket, User, UserSummary, Recognition, SyncStatus,
    TriageResult, PointsAwardedNotification, TicketCreate,
    ResolutionPlan, RecommendedSolution,
    TicketUpdate, TicketComment, TicketCommentCreate,
    TicketCategory, TicketCategoryCreate, TicketAuditEntry, BulkAction,
    LoginRequest, UserCreate, UserUpdate, AuthResponse, UserOut,
    KbArticle, KbArticleCreate, KbArticleUpdate,
    TicketStatusConfig, TicketStatusConfigCreate,
    TicketPriorityConfig, TicketPriorityConfigCreate,
    NotificationConfig, NotificationConfigUpdate,
    ReportSummary,
    Project, ProjectCreate, ProjectUpdate,
    ServiceItem, ServiceItemCreate, ServiceRequest, ServiceRequestCreate,
    Problem, ProblemCreate, ProblemUpdate,
    ChangeRecordOut, ChangeCreate, ChangeUpdate, ChangeApprovalOut, ChangeApprovalCreate,
    Asset, AssetCreate, AssetUpdate,
    SurveyTemplate, SurveyOut, SurveySend, SurveyResponseCreate,
    TimeEntry, TimeEntryCreate,
    PortalTicketCreate, PortalTicketOut,
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
VERSION = "1.0.1"
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
async def list_tickets(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "newest",
):
    q = db.query(TicketRecord)
    if status:
        q = q.filter(TicketRecord.status == status)
    if priority:
        q = q.filter(TicketRecord.priority == priority)
    if assignee_id:
        q = q.filter(TicketRecord.assignee_id == assignee_id)
    if category:
        q = q.filter(TicketRecord.category == category)
    if search:
        q = q.filter(TicketRecord.subject.ilike(f"%{search}%"))
    if sort == "oldest":
        q = q.order_by(TicketRecord.created_at.asc())
    elif sort == "priority":
        q = q.order_by(desc(TicketRecord.priority))
    else:
        q = q.order_by(desc(TicketRecord.created_at))
    tickets = q.all()
    # Enrich with assignee names
    for t in tickets:
        if t.assignee_id:
            user = db.query(UserRecord).filter(UserRecord.id == t.assignee_id).first()
            t.__dict__["assignee_name"] = user.name if user else None
    return tickets


@app.get("/tickets/{ticket_id}", response_model=Ticket)
async def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # Enrich with assignee name
    if ticket.assignee_id:
        user = db.query(UserRecord).filter(UserRecord.id == ticket.assignee_id).first()
        ticket.__dict__["assignee_name"] = user.name if user else None
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
async def update_ticket(ticket_id: str, payload: TicketUpdate, db: Session = Depends(get_db)):
    """Update a ticket — status, priority, assignee, category, tags, etc.
    Records every change in the audit log."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # Track changes for audit log
    for field in ["subject", "description", "status", "priority", "assignee_id", "category", "tags"]:
        val = getattr(payload, field, None)
        if val is not None:
            old = getattr(ticket, field, None)
            if old != val:
                db.add(TicketAuditLogRecord(
                    ticket_id=ticket.id, field=field,
                    old_value=str(old) if old else None,
                    new_value=str(val),
                ))
                setattr(ticket, field, val)
    if payload.due_by is not None:
        ticket.due_by = payload.due_by
    # Auto-set resolved_at when status changes to Resolved/Closed
    if payload.status and payload.status.lower() in ("resolved", "closed"):
        if not ticket.resolved_at:
            ticket.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    return ticket


@app.delete("/tickets/{ticket_id}")
async def delete_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    db.delete(ticket)
    db.commit()
    return {"status": "deleted", "ticket_id": ticket_id}


# ── Ticket comments / notes ──────────────────────────────────

@app.get("/tickets/{ticket_id}/comments", response_model=List[TicketComment])
async def list_comments(ticket_id: str, db: Session = Depends(get_db)):
    return db.query(TicketCommentRecord).filter(
        TicketCommentRecord.ticket_id == ticket_id
    ).order_by(TicketCommentRecord.created_at.asc()).all()


@app.post("/tickets/{ticket_id}/comments", response_model=TicketComment, status_code=201)
async def add_comment(ticket_id: str, payload: TicketCommentCreate, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    comment = TicketCommentRecord(
        ticket_id=ticket_id,
        body=payload.body,
        is_private=payload.is_private,
        author_name="Agent",
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


# ── Ticket audit log ──────────────────────────────────────────

@app.get("/tickets/{ticket_id}/audit", response_model=List[TicketAuditEntry])
async def get_audit_log(ticket_id: str, db: Session = Depends(get_db)):
    return db.query(TicketAuditLogRecord).filter(
        TicketAuditLogRecord.ticket_id == ticket_id
    ).order_by(TicketAuditLogRecord.changed_at.desc()).all()


# ── Ticket categories ────────────────────────────────────────

@app.get("/categories", response_model=List[TicketCategory])
async def list_categories(db: Session = Depends(get_db)):
    return db.query(TicketCategoryRecord).order_by(TicketCategoryRecord.name).all()


@app.post("/categories", response_model=TicketCategory, status_code=201)
async def create_category(payload: TicketCategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(TicketCategoryRecord).filter(TicketCategoryRecord.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Category already exists")
    cat = TicketCategoryRecord(name=payload.name, description=payload.description, color=payload.color)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@app.delete("/categories/{cat_id}")
async def delete_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(TicketCategoryRecord).filter(TicketCategoryRecord.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(cat)
    db.commit()
    return {"status": "deleted"}


# ── Bulk operations ───────────────────────────────────────────

@app.post("/tickets/bulk")
async def bulk_action(payload: BulkAction, db: Session = Depends(get_db)):
    """Apply an action to multiple tickets at once.
    Actions: assign, close, set_priority, set_category."""
    tickets = db.query(TicketRecord).filter(TicketRecord.id.in_(payload.ticket_ids)).all()
    count = 0
    for t in tickets:
        if payload.action == "assign" and payload.value:
            t.assignee_id = payload.value
        elif payload.action == "close":
            t.status = "Closed"
            if not t.resolved_at:
                t.resolved_at = datetime.utcnow()
        elif payload.action == "set_priority" and payload.value:
            t.priority = payload.value
        elif payload.action == "set_category" and payload.value:
            t.category = payload.value
        count += 1
    db.commit()
    return {"status": "completed", "updated": count}


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


# ── Authentication ─────────────────────────────────────────────

SESSION_COOKIE = "tickety_session"
SESSION_TTL_DAYS = 14


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        return False
    return _hash_password(password) == password_hash


def _create_session(db: Session, user_id: str, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    session = SessionRecord(
        token=token,
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(session)
    db.commit()
    return token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserRecord:
    """Dependency: resolve the logged-in user from the session cookie.

    Falls back to the first user (demo/single-user mode) when no session exists,
    so existing deployments keep working without a login step."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.query(SessionRecord).filter(SessionRecord.token == token).first()
        if session and (not session.expires_at or session.expires_at > datetime.utcnow()):
            user = db.query(UserRecord).filter(UserRecord.id == session.user_id).first()
            if user and user.is_active:
                return user
    # Fallback: first active user (single-user/demo mode)
    user = db.query(UserRecord).filter(UserRecord.is_active.is_(True)).first()
    if user:
        return user
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_role(*roles: str):
    """Dependency factory: require the current user to have one of the roles."""
    def checker(user: UserRecord = Depends(get_current_user)) -> UserRecord:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


@app.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(UserRecord).filter(UserRecord.email == payload.email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _create_session(db, user.id, request)
    user.last_login_at = datetime.utcnow()
    db.commit()
    resp = JSONResponse({"token": token, "user": UserOut.model_validate(user).model_dump(mode="json")})
    resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_DAYS * 86400, httponly=True, samesite="lax")
    return resp


@app.post("/auth/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.query(SessionRecord).filter(SessionRecord.token == token).first()
        if session:
            db.delete(session)
            db.commit()
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.get("/auth/me", response_model=UserOut)
async def auth_me(user: UserRecord = Depends(get_current_user)):
    return user


# ── Users / Agents CRUD (standalone) ───────────────────────────

@app.get("/users", response_model=List[UserOut])
async def list_users(db: Session = Depends(get_db)):
    return db.query(UserRecord).order_by(UserRecord.name).all()


@app.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(UserRecord).filter(UserRecord.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already in use")
    import uuid as _uuid
    password = payload.password or secrets.token_urlsafe(12)
    user = UserRecord(
        id=f"u-{_uuid.uuid4().hex[:8]}",
        name=payload.name,
        email=payload.email,
        title=payload.title,
        role=payload.role,
        password_hash=_hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: str, payload: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for field in ["name", "email", "title", "role", "is_active"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(user, field, val)
    if payload.password:
        user.password_hash = _hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@app.delete("/users/{user_id}")
async def delete_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Soft-delete: deactivate instead of removing (preserves ticket history)
    user.is_active = False
    db.commit()
    return {"status": "deactivated", "user_id": user_id}


# ── Knowledge Base ─────────────────────────────────────────────

def _slugify(title: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "article"


@app.get("/kb", response_model=List[KbArticle])
async def list_kb_articles(
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
):
    q = db.query(KbArticleRecord)
    if status:
        q = q.filter(KbArticleRecord.status == status)
    else:
        q = q.filter(KbArticleRecord.status == "published")
    if category:
        q = q.filter(KbArticleRecord.category == category)
    if search:
        q = q.filter(KbArticleRecord.title.ilike(f"%{search}%"))
    articles = q.order_by(desc(KbArticleRecord.updated_at)).all()
    # Enrich with author names
    for a in articles:
        if a.author_id:
            u = db.query(UserRecord).filter(UserRecord.id == a.author_id).first()
            a.__dict__["author_name"] = u.name if u else None
        else:
            a.__dict__["author_name"] = None
    return articles


@app.get("/kb/categories")
async def list_kb_categories(db: Session = Depends(get_db)):
    rows = db.query(KbArticleRecord.category).filter(
        KbArticleRecord.category.isnot(None), KbArticleRecord.status == "published"
    ).distinct().all()
    return {"categories": [r[0] for r in rows if r[0]]}


@app.get("/kb/{article_id}", response_model=KbArticle)
async def get_kb_article(article_id: str, db: Session = Depends(get_db)):
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    article.views += 1
    db.commit()
    db.refresh(article)
    if article.author_id:
        u = db.query(UserRecord).filter(UserRecord.id == article.author_id).first()
        article.__dict__["author_name"] = u.name if u else None
    return article


@app.post("/kb", response_model=KbArticle, status_code=201)
async def create_kb_article(payload: KbArticleCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    base_slug = _slugify(payload.title)
    slug = base_slug
    i = 1
    while db.query(KbArticleRecord).filter(KbArticleRecord.slug == slug).first():
        slug = f"{base_slug}-{i}"
        i += 1
    article = KbArticleRecord(
        id=f"kb-{_uuid.uuid4().hex[:8]}",
        title=payload.title,
        slug=slug,
        content=payload.content,
        category=payload.category,
        tags=payload.tags,
        status=payload.status,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


@app.patch("/kb/{article_id}", response_model=KbArticle)
async def update_kb_article(article_id: str, payload: KbArticleUpdate, db: Session = Depends(get_db)):
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    for field in ["title", "content", "category", "tags", "status"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(article, field, val)
    if payload.title:
        article.slug = _slugify(payload.title)
    db.commit()
    db.refresh(article)
    return article


@app.delete("/kb/{article_id}")
async def delete_kb_article(article_id: str, db: Session = Depends(get_db)):
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    db.delete(article)
    db.commit()
    return {"status": "deleted"}


@app.post("/kb/{article_id}/feedback")
async def kb_feedback(article_id: str, payload: dict, db: Session = Depends(get_db)):
    helpful = payload.get("helpful", True)
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if helpful:
        article.helpful += 1
    else:
        article.not_helpful += 1
    db.commit()
    return {"status": "ok", "helpful": article.helpful, "not_helpful": article.not_helpful}


@app.post("/tickets/{ticket_id}/kb/{article_id}", status_code=201)
async def link_kb_to_ticket(ticket_id: str, article_id: str, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    existing = db.query(TicketLinkRecord).filter(
        TicketLinkRecord.ticket_id == ticket_id, TicketLinkRecord.kb_article_id == article_id
    ).first()
    if existing:
        return {"status": "exists"}
    db.add(TicketLinkRecord(ticket_id=ticket_id, kb_article_id=article_id))
    db.commit()
    return {"status": "linked"}


@app.get("/tickets/{ticket_id}/kb", response_model=List[KbArticle])
async def get_ticket_kb_links(ticket_id: str, db: Session = Depends(get_db)):
    links = db.query(TicketLinkRecord).filter(TicketLinkRecord.ticket_id == ticket_id).all()
    article_ids = [l.kb_article_id for l in links]
    if not article_ids:
        return []
    return db.query(KbArticleRecord).filter(KbArticleRecord.id.in_(article_ids)).all()


# ── Custom ticket status / priority config ─────────────────────

@app.get("/config/statuses", response_model=List[TicketStatusConfig])
async def list_status_config(db: Session = Depends(get_db)):
    return db.query(TicketStatusConfigRecord).order_by(TicketStatusConfigRecord.sort_order).all()


@app.post("/config/statuses", response_model=TicketStatusConfig, status_code=201)
async def create_status_config(payload: TicketStatusConfigCreate, db: Session = Depends(get_db)):
    existing = db.query(TicketStatusConfigRecord).filter(TicketStatusConfigRecord.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Status already exists")
    rec = TicketStatusConfigRecord(**payload.model_dump())
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@app.delete("/config/statuses/{status_id}")
async def delete_status_config(status_id: int, db: Session = Depends(get_db)):
    rec = db.query(TicketStatusConfigRecord).filter(TicketStatusConfigRecord.id == status_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Status not found")
    db.delete(rec)
    db.commit()
    return {"status": "deleted"}


@app.get("/config/priorities", response_model=List[TicketPriorityConfig])
async def list_priority_config(db: Session = Depends(get_db)):
    return db.query(TicketPriorityConfigRecord).order_by(TicketPriorityConfigRecord.sort_order).all()


@app.post("/config/priorities", response_model=TicketPriorityConfig, status_code=201)
async def create_priority_config(payload: TicketPriorityConfigCreate, db: Session = Depends(get_db)):
    existing = db.query(TicketPriorityConfigRecord).filter(TicketPriorityConfigRecord.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Priority already exists")
    rec = TicketPriorityConfigRecord(**payload.model_dump())
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@app.delete("/config/priorities/{priority_id}")
async def delete_priority_config(priority_id: int, db: Session = Depends(get_db)):
    rec = db.query(TicketPriorityConfigRecord).filter(TicketPriorityConfigRecord.id == priority_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Priority not found")
    db.delete(rec)
    db.commit()
    return {"status": "deleted"}


# ── Notification config ────────────────────────────────────────

@app.get("/config/notifications", response_model=List[NotificationConfig])
async def list_notification_config(db: Session = Depends(get_db)):
    return db.query(NotificationConfigRecord).all()


@app.patch("/config/notifications/{event}", response_model=NotificationConfig)
async def update_notification_config(event: str, payload: NotificationConfigUpdate, db: Session = Depends(get_db)):
    rec = db.query(NotificationConfigRecord).filter(NotificationConfigRecord.event == event).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Notification event not found")
    if payload.enabled is not None:
        rec.enabled = payload.enabled
    if payload.channels is not None:
        rec.channels = payload.channels
    db.commit()
    db.refresh(rec)
    return rec


# ── Reports / Analytics ─────────────────────────────────────────

@app.get("/reports/summary", response_model=ReportSummary)
async def reports_summary(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    total = db.query(TicketRecord).count()
    open_t = db.query(TicketRecord).filter(TicketRecord.status.notin_(["Closed", "Resolved"])).count()
    resolved = db.query(TicketRecord).filter(TicketRecord.status.in_(["Closed", "Resolved"])).count()
    breached = db.query(TicketRecord).filter(
        TicketRecord.due_by.isnot(None), TicketRecord.due_by < now,
        TicketRecord.status.notin_(["Closed", "Resolved"]),
    ).count()

    resolved_tickets = db.query(TicketRecord).filter(
        TicketRecord.resolved_at.isnot(None), TicketRecord.created_at.isnot(None)
    ).all()
    avg_hours = 0.0
    if resolved_tickets:
        total_s = sum((t.resolved_at - t.created_at).total_seconds() for t in resolved_tickets)
        avg_hours = round(total_s / len(resolved_tickets) / 3600, 1)

    escalation_rate = round((db.query(TicketRecord).filter(TicketRecord.status == "Escalated").count() / total * 100), 1) if total else 0.0
    csat = round((db.query(TicketRecord).filter(TicketRecord.sentiment == "Positive").count() / total * 100), 1) if total else 0.0

    return ReportSummary(
        total_tickets=total, open_tickets=open_t, resolved_tickets=resolved,
        breached_sla=breached, avg_resolution_hours=avg_hours,
        escalation_rate=escalation_rate, csat_proxy=csat,
    )


@app.get("/reports/volume")
async def reports_volume(db: Session = Depends(get_db)):
    """Ticket volume grouped by day for the last 30 days."""
    now = datetime.utcnow()
    since = now - timedelta(days=30)
    rows = db.query(
        func.date_trunc("day", TicketRecord.created_at).label("day"),
        func.count().label("count"),
    ).filter(TicketRecord.created_at >= since).group_by("day").order_by("day").all()
    return {"days": [r.day.isoformat() for r in rows], "counts": [r.count for r in rows]}


@app.get("/reports/by-category")
async def reports_by_category(db: Session = Depends(get_db)):
    rows = db.query(
        TicketRecord.category, func.count().label("count")
    ).filter(TicketRecord.category.isnot(None)).group_by(TicketRecord.category).all()
    return {"categories": [r.category for r in rows], "counts": [r.count for r in rows]}


@app.get("/reports/by-status")
async def reports_by_status(db: Session = Depends(get_db)):
    rows = db.query(
        TicketRecord.status, func.count().label("count")
    ).group_by(TicketRecord.status).all()
    return {"statuses": [r.status for r in rows], "counts": [r.count for r in rows]}


@app.get("/reports/sla-compliance")
async def reports_sla_compliance(db: Session = Depends(get_db)):
    """SLA compliance rate by priority."""
    now = datetime.utcnow()
    result = {}
    for p in ["P1", "P2", "P3"]:
        total = db.query(TicketRecord).filter(TicketRecord.priority == p).count()
        breached = db.query(TicketRecord).filter(
            TicketRecord.priority == p,
            TicketRecord.due_by.isnot(None), TicketRecord.due_by < now,
        ).count()
        compliance = round(((total - breached) / total * 100), 1) if total else 100.0
        result[p] = {"total": total, "breached": breached, "compliance": compliance}
    return result


@app.get("/reports/resolution-time")
async def reports_resolution_time(db: Session = Depends(get_db)):
    """Avg resolution time by category."""
    rows = db.query(TicketRecord).filter(
        TicketRecord.resolved_at.isnot(None), TicketRecord.created_at.isnot(None),
        TicketRecord.category.isnot(None),
    ).all()
    by_cat = {}
    for t in rows:
        hours = (t.resolved_at - t.created_at).total_seconds() / 3600
        cat = t.category
        by_cat.setdefault(cat, []).append(hours)
    return {"categories": list(by_cat.keys()), "avg_hours": [round(sum(v) / len(v), 1) for v in by_cat.values()]}


# ── User / Engagement ────────────────────────────────────────

@app.get("/me", response_model=User)
async def get_current_user_endpoint(user: UserRecord = Depends(get_current_user)):
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


# ── OAuth 2.0 ──────────────────────────────────────────────────

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
    """Return the OAuth 2.0 authorization URL for the configured external ITSM provider."""
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    if not ad.oauth_configured:
        raise HTTPException(400, "OAuth client ID and secret not configured")
    return {"url": ad.oauth_authorization_url()}


@app.get("/oauth/callback")
async def oauth_callback(code: str = Query(..., description="The authorisation code from the ITSM provider")):
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

@app.post("/webhooks/external")
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


# ── Projects ──────────────────────────────────────────────────

@app.get("/projects", response_model=List[Project])
async def list_projects(db: Session = Depends(get_db)):
    projects = db.query(ProjectRecord).order_by(ProjectRecord.name).all()
    for p in projects:
        if p.lead_id:
            u = db.query(UserRecord).filter(UserRecord.id == p.lead_id).first()
            p.__dict__["lead_name"] = u.name if u else None
    return projects


@app.post("/projects", response_model=Project, status_code=201)
async def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    existing = db.query(ProjectRecord).filter(ProjectRecord.key == payload.key.upper()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project key already exists")
    project = ProjectRecord(
        id=f"proj-{_uuid.uuid4().hex[:8]}",
        name=payload.name,
        key=payload.key.upper(),
        description=payload.description,
        lead_id=payload.lead_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(ProjectRecord).filter(ProjectRecord.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for field in ["name", "description", "lead_id", "status"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(project, field, val)
    db.commit()
    db.refresh(project)
    return project


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(ProjectRecord).filter(ProjectRecord.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return {"status": "deleted"}


# ── Service Catalog ────────────────────────────────────────────

@app.get("/services", response_model=List[ServiceItem])
async def list_services(
    db: Session = Depends(get_db),
    category: Optional[str] = None,
):
    q = db.query(ServiceItemRecord)
    if category:
        q = q.filter(ServiceItemRecord.category == category)
    return q.order_by(ServiceItemRecord.category, ServiceItemRecord.name).all()


@app.post("/services", response_model=ServiceItem, status_code=201)
async def create_service(payload: ServiceItemCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    item = ServiceItemRecord(id=f"svc-{_uuid.uuid4().hex[:8]}", **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.patch("/services/{service_id}", response_model=ServiceItem)
async def update_service(service_id: str, payload: ServiceItemCreate, db: Session = Depends(get_db)):
    item = db.query(ServiceItemRecord).filter(ServiceItemRecord.id == service_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Service item not found")
    for field in ["name", "description", "category", "pricing", "sla_hours", "approval_required"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(item, field, val)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/services/{service_id}")
async def delete_service(service_id: str, db: Session = Depends(get_db)):
    item = db.query(ServiceItemRecord).filter(ServiceItemRecord.id == service_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Service item not found")
    item.is_active = False
    db.commit()
    return {"status": "deactivated"}


@app.get("/service-requests", response_model=List[ServiceRequest])
async def list_service_requests(db: Session = Depends(get_db)):
    reqs = db.query(ServiceRequestRecord).order_by(desc(ServiceRequestRecord.created_at)).all()
    for r in reqs:
        if r.service_item_id:
            svc = db.query(ServiceItemRecord).filter(ServiceItemRecord.id == r.service_item_id).first()
            r.__dict__["service_name"] = svc.name if svc else None
    return reqs


@app.post("/service-requests", response_model=ServiceRequest, status_code=201)
async def create_service_request(payload: ServiceRequestCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    ticket = db.query(TicketRecord).filter(TicketRecord.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    existing = db.query(ServiceRequestRecord).filter(ServiceRequestRecord.ticket_id == payload.ticket_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ticket already has a service request")
    sr = ServiceRequestRecord(id=f"sr-{_uuid.uuid4().hex[:8]}", **payload.model_dump())
    db.add(sr)
    db.commit()
    db.refresh(sr)
    return sr


# ── Problem Management ─────────────────────────────────────────

@app.get("/problems", response_model=List[Problem])
async def list_problems(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
):
    q = db.query(ProblemRecord)
    if status:
        q = q.filter(ProblemRecord.status == status)
    problems = q.order_by(desc(ProblemRecord.created_at)).all()
    for p in problems:
        if p.assigned_to:
            u = db.query(UserRecord).filter(UserRecord.id == p.assigned_to).first()
            p.__dict__["assigned_name"] = u.name if u else None
        count = db.query(ProblemTicketLinkRecord).filter(ProblemTicketLinkRecord.problem_id == p.id).count()
        p.__dict__["linked_tickets_count"] = count
    return problems


@app.get("/problems/{problem_id}", response_model=Problem)
async def get_problem(problem_id: str, db: Session = Depends(get_db)):
    problem = db.query(ProblemRecord).filter(ProblemRecord.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    if problem.assigned_to:
        u = db.query(UserRecord).filter(UserRecord.id == problem.assigned_to).first()
        problem.__dict__["assigned_name"] = u.name if u else None
    count = db.query(ProblemTicketLinkRecord).filter(ProblemTicketLinkRecord.problem_id == problem_id).count()
    problem.__dict__["linked_tickets_count"] = count
    return problem


@app.post("/problems", response_model=Problem, status_code=201)
async def create_problem(payload: ProblemCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    problem = ProblemRecord(id=f"prob-{_uuid.uuid4().hex[:8]}", **payload.model_dump())
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem


@app.patch("/problems/{problem_id}", response_model=Problem)
async def update_problem(problem_id: str, payload: ProblemUpdate, db: Session = Depends(get_db)):
    problem = db.query(ProblemRecord).filter(ProblemRecord.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    for field in ["title", "description", "status", "priority", "category", "assigned_to",
                   "root_cause", "workaround", "resolution", "impact_scope"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(problem, field, val)
    if payload.status and payload.status in ("Resolved", "Closed") and not problem.closed_at:
        problem.closed_at = datetime.utcnow()
    db.commit()
    db.refresh(problem)
    return problem


@app.delete("/problems/{problem_id}")
async def delete_problem(problem_id: str, db: Session = Depends(get_db)):
    problem = db.query(ProblemRecord).filter(ProblemRecord.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    db.query(ProblemTicketLinkRecord).filter(ProblemTicketLinkRecord.problem_id == problem_id).delete()
    db.delete(problem)
    db.commit()
    return {"status": "deleted"}


@app.post("/problems/{problem_id}/link/{ticket_id}", status_code=201)
async def link_ticket_to_problem(problem_id: str, ticket_id: str, db: Session = Depends(get_db)):
    problem = db.query(ProblemRecord).filter(ProblemRecord.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    existing = db.query(ProblemTicketLinkRecord).filter(
        ProblemTicketLinkRecord.problem_id == problem_id, ProblemTicketLinkRecord.ticket_id == ticket_id
    ).first()
    if existing:
        return {"status": "exists"}
    db.add(ProblemTicketLinkRecord(problem_id=problem_id, ticket_id=ticket_id))
    db.commit()
    return {"status": "linked"}


@app.delete("/problems/{problem_id}/link/{ticket_id}")
async def unlink_ticket_from_problem(problem_id: str, ticket_id: str, db: Session = Depends(get_db)):
    db.query(ProblemTicketLinkRecord).filter(
        ProblemTicketLinkRecord.problem_id == problem_id, ProblemTicketLinkRecord.ticket_id == ticket_id
    ).delete()
    db.commit()
    return {"status": "unlinked"}


@app.get("/problems/{problem_id}/tickets", response_model=List[Ticket])
async def get_problem_tickets(problem_id: str, db: Session = Depends(get_db)):
    links = db.query(ProblemTicketLinkRecord).filter(ProblemTicketLinkRecord.problem_id == problem_id).all()
    ticket_ids = [l.ticket_id for l in links]
    if not ticket_ids:
        return []
    return db.query(TicketRecord).filter(TicketRecord.id.in_(ticket_ids)).all()


# ── Change Management ──────────────────────────────────────────

@app.get("/changes", response_model=List[ChangeRecordOut])
async def list_changes(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
):
    q = db.query(ChangeRecord)
    if status:
        q = q.filter(ChangeRecord.status == status)
    changes = q.order_by(desc(ChangeRecord.created_at)).all()
    for c in changes:
        if c.requested_by:
            u = db.query(UserRecord).filter(UserRecord.id == c.requested_by).first()
            c.__dict__["requested_name"] = u.name if u else None
        if c.assigned_to:
            u = db.query(UserRecord).filter(UserRecord.id == c.assigned_to).first()
            c.__dict__["assigned_name"] = u.name if u else None
    return changes


@app.get("/changes/{change_id}", response_model=ChangeRecordOut)
async def get_change(change_id: str, db: Session = Depends(get_db)):
    change = db.query(ChangeRecord).filter(ChangeRecord.id == change_id).first()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if change.requested_by:
        u = db.query(UserRecord).filter(UserRecord.id == change.requested_by).first()
        change.__dict__["requested_name"] = u.name if u else None
    if change.assigned_to:
        u = db.query(UserRecord).filter(UserRecord.id == change.assigned_to).first()
        change.__dict__["assigned_name"] = u.name if u else None
    return change


@app.post("/changes", response_model=ChangeRecordOut, status_code=201)
async def create_change(payload: ChangeCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    change = ChangeRecord(id=f"chg-{_uuid.uuid4().hex[:8]}", **payload.model_dump())
    db.add(change)
    db.commit()
    db.refresh(change)
    return change


@app.patch("/changes/{change_id}", response_model=ChangeRecordOut)
async def update_change(change_id: str, payload: ChangeUpdate, db: Session = Depends(get_db)):
    change = db.query(ChangeRecord).filter(ChangeRecord.id == change_id).first()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    for field in ["title", "description", "status", "change_type", "priority", "risk_level",
                   "impact", "rollback_plan", "test_plan", "scheduled_start", "scheduled_end",
                   "assigned_to"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(change, field, val)
    if payload.status and payload.status == "Completed" and not change.completed_at:
        change.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(change)
    return change


@app.delete("/changes/{change_id}")
async def delete_change(change_id: str, db: Session = Depends(get_db)):
    change = db.query(ChangeRecord).filter(ChangeRecord.id == change_id).first()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    db.query(ChangeApprovalRecord).filter(ChangeApprovalRecord.change_id == change_id).delete()
    db.delete(change)
    db.commit()
    return {"status": "deleted"}


@app.get("/changes/{change_id}/approvals", response_model=List[ChangeApprovalOut])
async def get_change_approvals(change_id: str, db: Session = Depends(get_db)):
    approvals = db.query(ChangeApprovalRecord).filter(ChangeApprovalRecord.change_id == change_id).all()
    for a in approvals:
        u = db.query(UserRecord).filter(UserRecord.id == a.approver_id).first()
        a.__dict__["approver_name"] = u.name if u else None
    return approvals


@app.post("/changes/{change_id}/approvals", response_model=ChangeApprovalOut, status_code=201)
async def add_change_approval(change_id: str, payload: ChangeApprovalCreate, db: Session = Depends(get_db)):
    existing = db.query(ChangeApprovalRecord).filter(
        ChangeApprovalRecord.change_id == change_id, ChangeApprovalRecord.approver_id == payload.approver_id
    ).first()
    if existing:
        return existing
    approval = ChangeApprovalRecord(change_id=change_id, approver_id=payload.approver_id)
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


@app.patch("/changes/{change_id}/approvals/{approver_id}")
async def decide_approval(change_id: str, approver_id: str, decision: str, comment: Optional[str] = None, db: Session = Depends(get_db)):
    approval = db.query(ChangeApprovalRecord).filter(
        ChangeApprovalRecord.change_id == change_id, ChangeApprovalRecord.approver_id == approver_id
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    approval.decision = decision
    approval.comment = comment
    approval.decided_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "decision": decision}


# ── Asset / CMDB ───────────────────────────────────────────────

@app.get("/assets", response_model=List[Asset])
async def list_assets(
    db: Session = Depends(get_db),
    asset_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    q = db.query(AssetRecord)
    if asset_type:
        q = q.filter(AssetRecord.asset_type == asset_type)
    if status:
        q = q.filter(AssetRecord.status == status)
    if search:
        q = q.filter(AssetRecord.name.ilike(f"%{search}%"))
    assets = q.order_by(AssetRecord.asset_type, AssetRecord.name).all()
    for a in assets:
        if a.owner_id:
            u = db.query(UserRecord).filter(UserRecord.id == a.owner_id).first()
            a.__dict__["owner_name"] = u.name if u else None
    return assets


@app.get("/assets/{asset_id}", response_model=Asset)
async def get_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.query(AssetRecord).filter(AssetRecord.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.owner_id:
        u = db.query(UserRecord).filter(UserRecord.id == asset.owner_id).first()
        asset.__dict__["owner_name"] = u.name if u else None
    return asset


@app.post("/assets", response_model=Asset, status_code=201)
async def create_asset(payload: AssetCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    asset = AssetRecord(id=f"ast-{_uuid.uuid4().hex[:8]}", **payload.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@app.patch("/assets/{asset_id}", response_model=Asset)
async def update_asset(asset_id: str, payload: AssetUpdate, db: Session = Depends(get_db)):
    asset = db.query(AssetRecord).filter(AssetRecord.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    for field in ["name", "asset_type", "asset_tag", "status", "owner_id", "location",
                   "vendor", "model", "purchase_date", "warranty_expiry", "cost", "notes"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(asset, field, val)
    db.commit()
    db.refresh(asset)
    return asset


@app.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.query(AssetRecord).filter(AssetRecord.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    db.delete(asset)
    db.commit()
    return {"status": "deleted"}


@app.get("/assets/stats")
async def asset_stats(db: Session = Depends(get_db)):
    total = db.query(AssetRecord).count()
    by_type = {}
    for row in db.query(AssetRecord.asset_type, func.count()).group_by(AssetRecord.asset_type).all():
        by_type[row[0]] = row[1]
    return {"total": total, "by_type": by_type}


# ── Surveys / CSAT ─────────────────────────────────────────────

@app.get("/surveys/templates", response_model=List[SurveyTemplate])
async def list_survey_templates(db: Session = Depends(get_db)):
    return db.query(SurveyTemplateRecord).order_by(SurveyTemplateRecord.name).all()


@app.get("/surveys", response_model=List[SurveyOut])
async def list_surveys(db: Session = Depends(get_db)):
    surveys = db.query(SurveyRecord).order_by(desc(SurveyRecord.created_at)).all()
    for s in surveys:
        ticket = db.query(TicketRecord).filter(TicketRecord.id == s.ticket_id).first()
        s.__dict__["ticket_subject"] = ticket.subject if ticket else None
    return surveys


@app.post("/surveys/send", response_model=SurveyOut, status_code=201)
async def send_survey(payload: SurveySend, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    import uuid as _uuid
    survey = SurveyRecord(
        id=f"srv-{_uuid.uuid4().hex[:8]}",
        ticket_id=payload.ticket_id,
        template_id=payload.template_id,
        sent_at=datetime.utcnow(),
    )
    db.add(survey)
    db.commit()
    db.refresh(survey)
    return survey


@app.post("/surveys/{survey_id}/respond", status_code=201)
async def respond_survey(survey_id: str, payload: SurveyResponseCreate, db: Session = Depends(get_db)):
    survey = db.query(SurveyRecord).filter(SurveyRecord.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    if survey.responded_at:
        raise HTTPException(status_code=409, detail="Survey already responded")
    response = SurveyResponseRecord(
        survey_id=survey_id, rating=payload.rating, comment=payload.comment
    )
    survey.responded_at = datetime.utcnow()
    db.add(response)
    db.commit()
    return {"status": "submitted", "rating": payload.rating}


@app.get("/surveys/stats")
async def survey_stats(db: Session = Depends(get_db)):
    total = db.query(SurveyRecord).count()
    responded = db.query(SurveyRecord).filter(SurveyRecord.responded_at.isnot(None)).count()
    responses = db.query(SurveyResponseRecord.rating, func.count()).group_by(SurveyResponseRecord.rating).all()
    avg_rating = db.query(func.avg(SurveyResponseRecord.rating)).scalar() or 0
    return {
        "total_sent": total, "responded": responded, "response_rate": round(responded / total * 100, 1) if total else 0,
        "avg_rating": round(avg_rating, 1),
        "distribution": {str(r): c for r, c in responses},
    }


# ── Time Tracking ──────────────────────────────────────────────

@app.get("/time-entries", response_model=List[TimeEntry])
async def list_time_entries(
    db: Session = Depends(get_db),
    ticket_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    q = db.query(TimeEntryRecord)
    if ticket_id:
        q = q.filter(TimeEntryRecord.ticket_id == ticket_id)
    if user_id:
        q = q.filter(TimeEntryRecord.user_id == user_id)
    entries = q.order_by(desc(TimeEntryRecord.entry_date)).limit(200).all()
    for e in entries:
        u = db.query(UserRecord).filter(UserRecord.id == e.user_id).first()
        e.__dict__["user_name"] = u.name if u else None
    return entries


@app.post("/time-entries", response_model=TimeEntry, status_code=201)
async def create_time_entry(payload: TimeEntryCreate, db: Session = Depends(get_db)):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    entry = TimeEntryRecord(
        ticket_id=payload.ticket_id,
        user_id="u-alice",  # TODO: from auth
        description=payload.description,
        minutes=payload.minutes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.get("/time-entries/ticket/{ticket_id}", response_model=List[TimeEntry])
async def ticket_time_entries(ticket_id: str, db: Session = Depends(get_db)):
    entries = db.query(TimeEntryRecord).filter(TimeEntryRecord.ticket_id == ticket_id).order_by(
        desc(TimeEntryRecord.entry_date)
    ).all()
    for e in entries:
        u = db.query(UserRecord).filter(UserRecord.id == e.user_id).first()
        e.__dict__["user_name"] = u.name if u else None
    return entries


@app.get("/time-entries/summary")
async def time_summary(db: Session = Depends(get_db)):
    total_minutes = db.query(func.sum(TimeEntryRecord.minutes)).scalar() or 0
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_minutes = db.query(func.sum(TimeEntryRecord.minutes)).filter(
        TimeEntryRecord.entry_date >= today
    ).scalar() or 0
    return {"total_hours": round(total_minutes / 60, 1), "today_hours": round(today_minutes / 60, 1)}


# ── Self-Service Portal ────────────────────────────────────────

@app.post("/portal/tickets", response_model=PortalTicketOut, status_code=201)
async def portal_create_ticket(payload: PortalTicketCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    ticket = TicketRecord(
        id=f"portal-{_uuid.uuid4().hex[:8]}",
        subject=payload.subject.strip(),
        description=payload.description,
        reporter=payload.reporter.strip(),
        status="New",
        priority=payload.priority,
        external_source="portal",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@app.get("/portal/tickets", response_model=List[PortalTicketOut])
async def portal_list_tickets(reporter: str, db: Session = Depends(get_db)):
    tickets = db.query(TicketRecord).filter(
        TicketRecord.reporter.ilike(f"%{reporter}%")
    ).order_by(desc(TicketRecord.created_at)).limit(50).all()
    return tickets

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