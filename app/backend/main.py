import os
import json
import asyncio
import secrets
import hashlib
import hmac
import unicodedata
import urllib.parse
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Request, Response, Cookie, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, case, desc, func, or_, text
from sqlalchemy.exc import IntegrityError

from .database import (
    init_db, get_db, SessionLocal,
    TicketRecord, UserRecord, RecognitionRecord,
    ExternalUserRecord, SyncStateRecord,
    TicketCommentRecord, TicketCategoryRecord, TicketAuditLogRecord,
    SessionRecord, KbArticleRecord, TicketLinkRecord,
    TicketStatusConfigRecord, TicketPriorityConfigRecord, NotificationConfigRecord,
    SsoIdentityRecord, SsoTransactionRecord,
    ProjectRecord, ServiceItemRecord, ServiceRequestRecord,
    ProblemRecord, ProblemTicketLinkRecord,
    ChangeRecord, ChangeApprovalRecord, ChangeTicketLinkRecord,
    AssetRecord,
    SurveyTemplateRecord, SurveyRecord, SurveyResponseRecord,
    TimeEntryRecord,
    AIUsageEventRecord,
    AIRequestBucketRecord,
    LLMCallRecord,
    AIArtifactRecord,
    SettingsRecord,
    IntegrationBindingRecord,
    IntegrationCapabilityRecord,
    IntegrationAuditRecord,
)
from .schema import (
    Ticket, User, UserSummary, Recognition, SyncStatus,
    AutomaticAIEnableRequest, AutomaticAIPauseRequest,
    ExternalUser, ExternalUserSyncResult,
    TriageResult, PointsAwardedNotification, TicketCreate,
    ResolutionPlan, RecommendedSolution,
    TicketUpdate, TicketComment, TicketCommentCreate,
    TicketCategory, TicketCategoryCreate, TicketAuditEntry, BulkAction,
    TicketIntelligenceAnalysisRequest, TicketIntelligenceAnalysisResponse,
    TicketIntelligenceBackfillRequest, TicketIntelligenceSearchResponse,
    RelatedTicketsResponse,
    LoginRequest, UserCreate, UserUpdate, AuthResponse, AuthContext, UserOut,
    KbArticle, KbArticleCreate, KbArticleUpdate, KbFeedbackCreate,
    TicketStatusConfig, TicketStatusConfigCreate,
    TicketPriorityConfig, TicketPriorityConfigCreate,
    NotificationConfig, NotificationConfigUpdate,
    ReportSummary,
    Project, ProjectCreate, ProjectUpdate,
    ServiceItem, ServiceItemCreate, ServiceRequest, ServiceRequestCreate,
    ServiceRequestApprovalDecision, ServiceRequestFulfillmentUpdate,
    Problem, ProblemCreate, ProblemUpdate,
    ChangeRecordOut, ChangeCreate, ChangeUpdate, ChangeApprovalOut, ChangeApprovalCreate, ChangeApprovalDecision,
    Asset, AssetCreate, AssetUpdate,
    SurveyTemplate, SurveyOut, SurveySend, SurveyResponseCreate,
    TimeEntry, TimeEntryCreate,
    PortalTicketCreate, PortalTicketOut, PortalTicketCreated,
    IntegrationBindingCreate, IntegrationBindingSuspend,
    FreshworksBootstrapRequest, FreshworksBootstrapRedeem,
)
from .llm_manager import (
    LLMAnalysisError,
    LLMCapacityError,
    LLMInvalidInputError,
    LLMInvalidOutputError,
    LLMUnavailableError,
    LLMManager,
    get_llm_metrics,
    get_llm_catalog,
    refresh_live_models_if_stale,
)
from .ai_contracts import (
    ResolutionAnalysis,
    SuggestedReply,
    TicketIntelligenceAnswer,
    TicketSummary,
    TriageAnalysis,
)
from .ai_input import (
    UnsafeAIAdviceError,
    prompt_char_limit,
    validate_semantic_advice,
)
from .ai_state import invalidate_ticket_ai, invalidate_ticket_resolution
from .brain import IntelligenceEngine
from . import intelligence as intel
from . import ticket_vectors
from .prompts import (
    RAG_SYSTEM_PROMPT, REPLY_SYSTEM_PROMPT, RESOLUTION_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT, TRIAGE_SYSTEM_PROMPT,
    RECOGNITIONS, TIER_THRESHOLDS, PRIORITY_POINTS,
    MOMENTUM_BONUS_CAP, MOMENTUM_RESET_HOURS,
)
from .integrations.registry import get_adapter
from .integrations.sync import (
    AUTOMATIC_AI_LOOKBACK_DAYS,
    async_sync_external_users,
    enable_automatic_ai,
    pause_automatic_ai,
    fetch_tickets_by_days,
    handle_webhook_event,
    sync_tickets_from_external,
)
from .integrations.freshservice import FreshserviceAdapter
from .integrations.bindings import (
    BindingValidationError,
    activate_binding,
    create_binding,
    get_active_binding,
    get_binding,
    list_capabilities,
    serialize_binding,
    suspend_binding,
    validate_automatic_ai_rollout_evidence,
    validate_binding,
)
from .integrations.embedded import (
    EmbeddedAuthError,
    authenticate_session,
    issue_bootstrap_code,
    redeem_bootstrap_code,
    require_ticket_scope,
    verify_installation_secret,
)
from .sync_worker import start_sync_worker, stop_sync_worker, get_sync_status
from . import settings as settings_module
from . import sso as sso_service
from .security import RequestBodyLimitMiddleware
from .privacy import redact_data
from .production_security import (
    disable_seeded_demo_identities as _disable_seeded_demo_identities,
)

# Single source of truth for the backend version. Bump when shipping user-visible
# changes. Build SHA/time are injected at image build time (see Dockerfile).
VERSION = "1.2.0"
BUILD_SHA = os.getenv("TICKETY_BUILD_SHA", "local")
BUILD_TIME = os.getenv("TICKETY_BUILD_TIME", "")


def _ai_pipeline_contract_version() -> str:
    """Bind cached AI artifacts to every trusted prompt/output contract."""
    contract = {
        "input_policy": "canonical-json-v1;semantic-advice-v1;rag-authority-v1",
        "prompts": {
            "triage": TRIAGE_SYSTEM_PROMPT,
            "reply": REPLY_SYSTEM_PROMPT,
            "summary": SUMMARY_SYSTEM_PROMPT,
            "resolution": RESOLUTION_SYSTEM_PROMPT,
            "rag": RAG_SYSTEM_PROMPT,
        },
        "schemas": {
            model.__name__: model.model_json_schema()
            for model in (
                TriageAnalysis,
                SuggestedReply,
                TicketSummary,
                ResolutionAnalysis,
                TicketIntelligenceAnswer,
            )
        },
    }
    encoded = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return f"2026-07-13.{hashlib.sha256(encoded).hexdigest()[:12]}"


AI_PIPELINE_VERSION = _ai_pipeline_contract_version()

app = FastAPI(title="Tickety", version=VERSION)


@app.exception_handler(LLMAnalysisError)
async def _llm_error_handler(_request: Request, exc: LLMAnalysisError):
    status = 502 if isinstance(exc, LLMInvalidOutputError) else 503
    code = "invalid_ai_output" if status == 502 else "ai_unavailable"
    return JSONResponse(status_code=status, content={"detail": code})

# Best-effort early load so import-time middleware settings such as CORS can
# pick up DB overrides after a restart. Startup reloads after init_db as well.
settings_module.load_settings_into_env()


def _cors_allow_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if configured:
        origins = [
            origin.strip().rstrip("/")
            for origin in configured.split(",")
            if origin.strip()
        ]
        if settings_module.is_production_mode():
            return [origin for origin in origins if origin != "*"]
        return origins
    if settings_module.is_production_mode():
        return []
    return ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestBodyLimitMiddleware)

# Optional Host-header allowlist (defense in depth against host injection in
# the origin checks and portal tracking URLs). Opt-in: deployments behind a
# proxy should list their public hostnames in TRUSTED_HOSTS.
_trusted_hosts = [
    host.strip()
    for host in os.getenv("TRUSTED_HOSTS", "").split(",")
    if host.strip()
]
if _trusted_hosts:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts)

llm_mgr = LLMManager()
engine = IntelligenceEngine(llm_mgr)

SESSION_COOKIE = "tickety_session"
SESSION_TTL_DAYS = 14
SSO_STATE_COOKIE = "tickety_sso_state"
FRESHSERVICE_OAUTH_STATE_COOKIE = "tickety_freshservice_oauth_state"
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 390_000
_LOGIN_FAILURES: dict[str, list[datetime]] = {}
_LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
_LOGIN_FAILURE_LIMIT = 5
PORTAL_ACCESS_TOKEN_BYTES = 32
PORTAL_ACCESS_TOKEN_TTL_DAYS = 90
_PUBLIC_HTTP_PATHS = {
    "/health",
    "/health/live",
    "/health/ready",
    "/version",
    "/auth/login",
    "/auth/logout",
    "/auth/sso/config",
    "/auth/sso/login",
    "/auth/sso/callback",
    "/webhooks/external",
    "/openapi.json",
}
_PUBLIC_HTTP_PREFIXES = (
    "/portal/",
    "/webhooks/external/",
    "/integrations/freshworks/",
    "/docs",
    "/redoc",
)


def _is_public_http_path(path: str) -> bool:
    return path in _PUBLIC_HTTP_PATHS or any(path.startswith(prefix) for prefix in _PUBLIC_HTTP_PREFIXES)


def _auth_required_for_request() -> bool:
    return settings_module.is_production_mode() or settings_module.get_bool("LOGIN_REQUIRED")


def _request_origin_allowed(request: Request, *, require_explicit: bool = False) -> bool:
    fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site == "cross-site":
        return False
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer", "")
        origin = referer if referer else ""
    if not origin:
        return fetch_site == "same-origin" or (not require_explicit and not fetch_site)
    parsed = urllib.parse.urlparse(origin)
    if not parsed.scheme or not parsed.netloc:
        return False
    supplied_origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = _cors_allow_origins()
    # In production the browser origin is a configured deployment boundary.
    # Do not turn the request Host header into an origin allowlist: a direct
    # client can supply both Host and Origin values.
    if settings_module.is_production_mode():
        return supplied_origin in allowed
    if settings_module.get_bool("TRUST_FORWARDED_HEADERS"):
        forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    else:
        # Never trust attacker-controllable forwarding headers unless the
        # deployment explicitly confirms its proxy overwrites them.
        forwarded_host = forwarded_proto = ""
    request_host = forwarded_host or request.url.netloc
    request_scheme = forwarded_proto or request.url.scheme
    request_origin = f"{request_scheme}://{request_host}"
    if supplied_origin == request_origin:
        return True
    return "*" in allowed or supplied_origin in allowed


def _roles_required_for_request(path: str, method: str) -> Optional[set[str]]:
    unsafe = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    if path == "/admin/llm/metrics" and method.upper() == "GET":
        return {"admin", "supervisor"}
    if path.startswith("/admin/settings") or path.startswith("/admin/llm") or path.startswith("/oauth/"):
        return {"admin"}
    if path.startswith("/admin/"):
        return {"admin", "supervisor"}
    if path.startswith("/config/"):
        return {"admin", "supervisor"}
    if unsafe and path == "/tickets/bulk":
        return {"admin", "supervisor"}
    if method.upper() == "DELETE" and path.startswith("/tickets/"):
        return {"admin", "supervisor"}
    if path == "/users" or (unsafe and path.startswith("/users/")):
        return {"admin", "supervisor"}
    if unsafe and path.startswith("/kb/") and path.endswith("/feedback"):
        return None
    if unsafe and path.startswith((
        "/categories",
        "/projects",
        "/services",
        "/service-requests",
        "/problems",
        "/changes",
        "/assets",
        "/kb",
        "/surveys/send",
    )):
        return {"admin", "supervisor"}
    return None


def _resolve_request_user(request: Request, db: Session, allow_demo: bool) -> Optional[UserRecord]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.query(SessionRecord).filter(SessionRecord.token == token).first()
        if session and (not session.expires_at or session.expires_at > datetime.utcnow()):
            user = db.query(UserRecord).filter(UserRecord.id == session.user_id).first()
            if user and user.is_active:
                return user
    if allow_demo and settings_module.is_demo_mode() and not settings_module.get_bool("LOGIN_REQUIRED"):
        admin = db.query(UserRecord).filter(
            UserRecord.is_active.is_(True),
            UserRecord.role == "admin",
        ).first()
        if admin:
            return admin
        return db.query(UserRecord).filter(UserRecord.is_active.is_(True)).first()
    return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserRecord:
    """Dependency: resolve the logged-in user from the session cookie.

    Falls back to the first user only in demo mode when LOGIN_REQUIRED is not
    enabled. Production mode always requires an explicit session."""
    state_user = getattr(request.state, "current_user", None)
    if state_user and getattr(state_user, "is_active", False):
        request.state.demo_fallback = False
        return state_user
    user = _resolve_request_user(request, db, allow_demo=False)
    if user:
        request.state.demo_fallback = False
        return user
    user = _resolve_request_user(
        request,
        db,
        allow_demo=settings_module.is_demo_mode() and not settings_module.get_bool("LOGIN_REQUIRED"),
    )
    if user:
        request.state.demo_fallback = True
        return user
    raise HTTPException(status_code=401, detail="Not authenticated")


def get_authenticated_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserRecord:
    """Resolve only a real session; never grant the demo fallback identity.

    Billable or sensitive AI surfaces use this dependency even when the rest
    of a local demo is configured for no-login browsing.  Unsafe requests also
    enforce the origin check here because demo mode intentionally bypasses the
    global authentication middleware.
    """
    if (
        request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        and not _request_origin_allowed(request)
    ):
        raise HTTPException(status_code=403, detail="Invalid request origin")
    state_user = getattr(request.state, "current_user", None)
    if state_user and getattr(state_user, "is_active", False):
        return state_user
    user = _resolve_request_user(request, db, allow_demo=False)
    if user:
        return user
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_protected_ai_origin(request: Request) -> None:
    """Block cross-site browser requests even for billable AI GET endpoints."""
    if not _request_origin_allowed(request, require_explicit=True):
        raise HTTPException(status_code=403, detail="Invalid request origin")


def get_protected_ai_user(
    user: UserRecord = Depends(get_authenticated_user),
    _origin: None = Depends(require_protected_ai_origin),
) -> UserRecord:
    """Require a real session for protected AI; demos additionally require admin."""
    if settings_module.is_demo_mode() and (user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Demo AI access requires an admin session")
    return user


def require_role(*roles: str):
    """Dependency factory: require the current user to have one of the roles."""
    def checker(user: UserRecord = Depends(get_current_user)) -> UserRecord:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


def require_protected_ai_role(*roles: str):
    def checker(user: UserRecord = Depends(get_protected_ai_user)) -> UserRecord:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


def require_admin_callback_user(
    user: UserRecord = Depends(get_authenticated_user),
) -> UserRecord:
    """Authenticate admin OAuth callbacks without rejecting provider redirects."""
    if (user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def _can_access_private_ai_context(user: UserRecord) -> bool:
    """Private notes never participate in cross-ticket RAG.

    The optional indexing flag may support a future same-ticket retrieval
    feature, but it must not let an agent plant text that later appears in a
    supervisor's global analysis context.
    """
    return False


def _authorize_ticket_analysis(user: UserRecord, ticket: TicketRecord) -> None:
    if (user.role or "").lower() in {"admin", "supervisor"}:
        return
    if (user.role or "").lower() == "agent" and ticket.assignee_id in {None, user.id}:
        return
    raise HTTPException(status_code=403, detail="Insufficient ticket analysis permission")


def _authorize_ticket_mutation(
    user: UserRecord,
    ticket: TicketRecord,
    *,
    changed_fields: Optional[set[str]] = None,
    requested_assignee_id: Optional[str] = None,
) -> None:
    """Prevent one agent from planting evidence in another/shared queue.

    An agent may atomically claim an unassigned ticket, but that claim request
    cannot smuggle any content mutation in the same PATCH.
    """
    role = (user.role or "").lower()
    if role in {"admin", "supervisor"}:
        return
    if role != "agent":
        raise HTTPException(status_code=403, detail="Insufficient ticket permissions")
    if ticket.assignee_id == user.id:
        if (
            changed_fields
            and "assignee_id" in changed_fields
            and requested_assignee_id != user.id
        ):
            raise HTTPException(
                status_code=403,
                detail="Agents cannot reassign tickets to another queue",
            )
        return
    if (
        ticket.assignee_id is None
        and changed_fields == {"assignee_id"}
        and requested_assignee_id == user.id
    ):
        return
    raise HTTPException(
        status_code=403,
        detail="Claim the ticket before adding or changing evidence",
    )


def _ticket_scope_assignee_id(user: UserRecord) -> Optional[str]:
    """Return the agent scope; fail closed for every unknown active role."""
    role = (user.role or "").lower()
    if role in {"admin", "supervisor"}:
        return None
    if role == "agent":
        return user.id
    raise HTTPException(status_code=403, detail="Insufficient ticket permissions")


def _login_key(payload: LoginRequest, request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{payload.email.strip().lower()}:{ip}"


def _login_blocked(payload: LoginRequest, request: Request) -> bool:
    key = _login_key(payload, request)
    cutoff = datetime.utcnow() - _LOGIN_FAILURE_WINDOW
    attempts = [ts for ts in _LOGIN_FAILURES.get(key, []) if ts > cutoff]
    _LOGIN_FAILURES[key] = attempts
    return len(attempts) >= _LOGIN_FAILURE_LIMIT


def _record_login_failure(payload: LoginRequest, request: Request):
    key = _login_key(payload, request)
    _LOGIN_FAILURES.setdefault(key, []).append(datetime.utcnow())


def _clear_login_failures(payload: LoginRequest, request: Request):
    _LOGIN_FAILURES.pop(_login_key(payload, request), None)


@app.middleware("http")
async def require_auth_by_default(request: Request, call_next):
    # Unsafe methods must always pass the origin gate, even in no-login demo
    # mode: anonymous POSTs would otherwise execute as the demo fallback
    # identity with no cross-site protection at all.
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and not _request_origin_allowed(request):
        return JSONResponse({"detail": "Invalid request origin"}, status_code=403)

    if request.method == "OPTIONS" or _is_public_http_path(request.url.path):
        return await call_next(request)

    roles = _roles_required_for_request(request.url.path, request.method)

    # Local demos may allow anonymous browsing, but privileged routes must
    # always be backed by a real session.  Do not let the demo fallback
    # identity reach administration, configuration, or OAuth flows.
    if not _auth_required_for_request() and not roles:
        return await call_next(request)

    db = SessionLocal()
    try:
        user = _resolve_request_user(request, db, allow_demo=False)
        if not user:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        if roles and user.role not in roles:
            return JSONResponse({"detail": "Insufficient permissions"}, status_code=403)
        if (
            roles
            and settings_module.is_demo_mode()
            and (user.role or "").lower() != "admin"
        ):
            return JSONResponse({"detail": "Insufficient permissions"}, status_code=403)
        request.state.current_user = user
    finally:
        db.close()
    return await call_next(request)

# WebSocket connection manager for real-time notifications. Each entry is a
# (user_id, websocket) pair so recipients only receive their own events and
# dead connections are bounded by the heartbeat-free cleanup on failure.
_notification_subscribers: list[tuple[str, WebSocket]] = []


async def _broadcast_notification(notification: dict):
    recipient_id = notification.get("user_id")
    if not isinstance(recipient_id, str) or not recipient_id:
        return
    dead = []
    for user_id, ws in list(_notification_subscribers):
        if user_id != recipient_id:
            continue
        try:
            await asyncio.wait_for(ws.send_json(notification), timeout=2)
        except Exception:
            dead.append((user_id, ws))
    for entry in dead:
        if entry in _notification_subscribers:
            _notification_subscribers.remove(entry)


def _prune_ai_operational_data(db: Session) -> dict[str, int]:
    """Apply bounded retention to high-volume AI audit/control tables."""
    now = datetime.utcnow()
    metrics_days = _bounded_env_int("AI_METRICS_RETENTION_DAYS", 30, 1, 3650)
    artifact_days = _bounded_env_int("AI_ARTIFACT_RETENTION_DAYS", 90, 1, 3650)
    counts = {
        "usage_events": db.query(AIUsageEventRecord).filter(
            AIUsageEventRecord.created_at < now - timedelta(days=metrics_days)
        ).delete(synchronize_session=False),
        "request_buckets": db.query(AIRequestBucketRecord).filter(
            AIRequestBucketRecord.window_start < now - timedelta(days=2)
        ).delete(synchronize_session=False),
        "llm_calls": db.query(LLMCallRecord).filter(
            LLMCallRecord.created_at < now - timedelta(days=metrics_days)
        ).delete(synchronize_session=False),
        "inactive_artifacts": db.query(AIArtifactRecord).filter(
            AIArtifactRecord.active.is_(False),
            AIArtifactRecord.created_at < now - timedelta(days=artifact_days),
        ).delete(synchronize_session=False),
    }
    db.commit()
    return {key: int(value or 0) for key, value in counts.items()}


@app.on_event("startup")
async def startup():
    init_db()
    # Hydrate env from DB overrides BEFORE building the LLM manager so that
    # keys saved via the settings UI are picked up on restart too.
    settings_module.load_settings_into_env()
    cleanup_db = SessionLocal()
    try:
        if settings_module.is_production_mode():
            disabled_demo_users = _disable_seeded_demo_identities(cleanup_db)
            if disabled_demo_users:
                print(f"[security] disabled_seeded_demo_users={disabled_demo_users}")
        pruned_ai_rows = _prune_ai_operational_data(cleanup_db)
        if sum(pruned_ai_rows.values()):
            print(f"[security] pruned_ai_operational_rows={sum(pruned_ai_rows.values())}")
        removed_private_documents = ticket_vectors.purge_private_comment_documents(cleanup_db)
        if removed_private_documents:
            print(f"[vectors] removed_private_documents={removed_private_documents}")
        removed_portal_documents = ticket_vectors.purge_portal_ticket_documents(cleanup_db)
        if removed_portal_documents:
            print(f"[vectors] removed_portal_documents={removed_portal_documents}")
        removed_unapproved_kb = ticket_vectors.purge_unapproved_kb_documents(cleanup_db)
        if removed_unapproved_kb:
            print(f"[vectors] removed_unapproved_kb_documents={removed_unapproved_kb}")
    finally:
        cleanup_db.close()
    global llm_mgr
    llm_mgr = LLMManager()
    engine.llm = llm_mgr
    # Fixed demo accounts and sample data are never created in production,
    # even if a stale database override still contains SEED_DEMO_DATA=true.
    if settings_module.is_demo_mode():
        from .seed import run_seed
        run_seed()
    start_sync_worker()


@app.on_event("shutdown")
async def shutdown():
    stop_sync_worker(wait=True)


# ── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": settings_module.app_mode(),
        "version": VERSION,
        "build_sha": BUILD_SHA,
        "build_time": BUILD_TIME,
    }


@app.get("/health/live")
async def health_live():
    """Process liveness only; dependencies intentionally are not consulted."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready(response: Response, db: Session = Depends(get_db)):
    """Readiness gate for dependencies required to serve application traffic."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        # Public health responses must not expose drivers, hosts, credentials,
        # SQL, or other internal exception details.
        response.status_code = 503
        return {"status": "not_ready", "checks": {"database": "unavailable"}}
    return {"status": "ready", "checks": {"database": "ok"}}


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

_PUBLIC_DEMO_AI_FIELDS = {
    "sentiment": None,
    "category": None,
    "mood": None,
    "complexity": 1,
    "ai_reasoning": None,
    "suggested_response": None,
    "ai_review_state": None,
    "escalation_risk": 0,
    "summary": None,
    "recommended_solution": None,
    "ai_source_hash": None,
    "ai_pipeline_version": None,
    "ai_model": None,
    "ai_status": None,
    "ai_claim_id": None,
    "ai_lease_expires_at": None,
    "ai_attempts": 0,
    "ai_next_attempt_at": None,
    "ai_requested_artifacts": None,
    "ai_started_at": None,
    "ai_generated_at": None,
    "ai_error": None,
    "ai_synthetic": False,
    "ai_suggested_priority": None,
    "ai_suggested_category": None,
    "recommended_team": "Unrouted / Review",
    "recommended_team_basis": "unrouted_review",
    "routing_status": "unrouted_review",
    "routing_abstention_reason": "untrusted_ai_status",
    "routing_catalog_validated": False,
}


def _enrich_ticket_team(ticket: TicketRecord) -> None:
    decision = intel.team_routing_decision(
        ticket.ai_suggested_category,
        ticket.ai_status,
    )
    ticket.__dict__["recommended_team"] = decision.recommended_team
    ticket.__dict__["recommended_team_basis"] = decision.basis
    ticket.__dict__["routing_status"] = decision.status
    ticket.__dict__["routing_abstention_reason"] = decision.abstention_reason
    ticket.__dict__["routing_catalog_validated"] = decision.catalog_validated


def _ticket_for_request(request: Request, ticket: TicketRecord) -> Ticket | TicketRecord:
    """Remove generated AI artifacts from anonymous demo browsing responses."""
    if not getattr(request.state, "demo_fallback", False):
        return ticket
    return Ticket.model_validate(ticket, from_attributes=True).model_copy(
        update=_PUBLIC_DEMO_AI_FIELDS
    )

@app.get("/tickets", response_model=List[Ticket])
async def list_tickets(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
    status: Optional[str] = Query(default=None, max_length=100),
    priority: Optional[str] = Query(default=None, max_length=100),
    assignee_id: Optional[str] = Query(default=None, max_length=255),
    category: Optional[str] = Query(default=None, max_length=100),
    search: Optional[str] = Query(default=None, max_length=200),
    sort: str = Query(default="newest", pattern="^(newest|oldest|priority|updated|complexity)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
):
    if getattr(request.state, "demo_fallback", False):
        # Anonymous demo responses redact these model-generated values. Do not
        # retain them as query or ordering oracles after redaction.
        if category or sort == "complexity":
            raise HTTPException(
                status_code=403,
                detail="AI-derived ticket filters require authentication",
            )
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    q = db.query(TicketRecord)
    if allowed_assignee_id is not None:
        q = q.filter(or_(
            TicketRecord.assignee_id.is_(None),
            TicketRecord.assignee_id == allowed_assignee_id,
        ))
    if status:
        q = q.filter(TicketRecord.status == status)
    if priority:
        q = q.filter(TicketRecord.priority == priority)
    if assignee_id:
        q = q.filter(TicketRecord.assignee_id == assignee_id)
    if category:
        q = q.filter(TicketRecord.category == category)
    if search:
        # Treat SQL wildcard characters as user text so searches remain
        # predictable and cannot accidentally expand into an unbounded match.
        escaped_search = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if escaped_search:
            pattern = f"%{escaped_search}%"
            q = q.filter(or_(
                TicketRecord.subject.ilike(pattern, escape="\\"),
                TicketRecord.description.ilike(pattern, escape="\\"),
                TicketRecord.reporter.ilike(pattern, escape="\\"),
                TicketRecord.external_id.ilike(pattern, escape="\\"),
            ))
    if sort == "oldest":
        q = q.order_by(TicketRecord.created_at.asc(), TicketRecord.id.asc())
    elif sort == "priority":
        priority_rank = {
            "P1": 1, "Urgent": 1,
            "P2": 2, "High": 2,
            "P3": 3, "Medium": 3,
            "P4": 4, "Low": 4,
        }
        # SQLAlchemy's portable CASE expression keeps semantic priority order
        # across SQLite (tests) and PostgreSQL (production).
        q = q.order_by(
            case(priority_rank, value=TicketRecord.priority, else_=5),
            TicketRecord.created_at.desc(),
            TicketRecord.id.asc(),
        )
    elif sort == "updated":
        q = q.order_by(TicketRecord.updated_at.desc(), TicketRecord.id.asc())
    elif sort == "complexity":
        q = q.order_by(TicketRecord.complexity.desc(), TicketRecord.created_at.desc(), TicketRecord.id.asc())
    else:
        q = q.order_by(TicketRecord.created_at.desc(), TicketRecord.id.asc())

    # Fetch one extra row to signal whether another page exists without a
    # potentially expensive COUNT(*) over the filtered result set.
    page = q.offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    tickets = page[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()

    # Resolve every assignee in one query instead of issuing one query per
    # ticket. Missing users intentionally remain null in the API response.
    assignee_ids = {ticket.assignee_id for ticket in tickets if ticket.assignee_id}
    assignee_names = {}
    if assignee_ids:
        assignee_names = dict(
            db.query(UserRecord.id, UserRecord.name)
            .filter(UserRecord.id.in_(assignee_ids))
            .all()
        )
    for ticket in tickets:
        ticket.__dict__["assignee_name"] = assignee_names.get(ticket.assignee_id)
    external_keys = {
        (ticket.binding_id, ticket.external_source, ticket.external_assignee_id)
        for ticket in tickets
        if ticket.external_source and ticket.external_assignee_id
    }
    external_names = {}
    if external_keys:
        rows = db.query(ExternalUserRecord).filter(
            ExternalUserRecord.binding_id.in_({key[0] for key in external_keys}),
            ExternalUserRecord.provider.in_({key[1] for key in external_keys}),
            ExternalUserRecord.external_id.in_({key[2] for key in external_keys}),
            ExternalUserRecord.user_type == "agent",
        ).all()
        external_names = {
            (row.binding_id, row.provider, row.external_id): row.name for row in rows
        }
    for ticket in tickets:
        ticket.__dict__["external_assignee_name"] = external_names.get(
            (ticket.binding_id, ticket.external_source, ticket.external_assignee_id)
        )
        _enrich_ticket_team(ticket)
    return [_ticket_for_request(request, ticket) for ticket in tickets]


@app.get("/tickets/{ticket_id}", response_model=Ticket)
async def get_ticket(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(user, ticket)
    # Enrich with assignee name
    if ticket.assignee_id:
        user = db.query(UserRecord).filter(UserRecord.id == ticket.assignee_id).first()
        ticket.__dict__["assignee_name"] = user.name if user else None
    if ticket.external_source and ticket.external_assignee_id:
        external_user = db.query(ExternalUserRecord).filter(
            ExternalUserRecord.binding_id == ticket.binding_id,
            ExternalUserRecord.provider == ticket.external_source,
            ExternalUserRecord.external_id == ticket.external_assignee_id,
            ExternalUserRecord.user_type == "agent",
        ).first()
        ticket.__dict__["external_assignee_name"] = (
            external_user.name if external_user else None
        )
    _enrich_ticket_team(ticket)
    return _ticket_for_request(request, ticket)


@app.get("/tickets/{ticket_id}/related", response_model=RelatedTicketsResponse)
async def get_related_tickets(
    ticket_id: str,
    limit: int = Query(5, ge=1, le=5),
    user: UserRecord = Depends(get_protected_ai_user),
    db: Session = Depends(get_db),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(user, ticket)
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    _reserve_ai_request(db, user.id, "related_tickets")
    query = " ".join(
        value.strip() for value in (ticket.subject or "", ticket.description or "")
        if value and value.strip()
    )[:1000]
    if not query:
        query = ticket.id[:1000]
    try:
        retrieval = await ticket_vectors.retrieve_ticket_context(
            db,
            query,
            limit=min(15, limit * 3),
            source_types=["ticket"],
            include_private_comments=False,
            allowed_assignee_id=allowed_assignee_id,
        )
    except Exception as exc:
        db.rollback()
        print(f"[related-tickets] retrieval failed kind={type(exc).__name__}")
        raise HTTPException(
            status_code=503,
            detail="related_tickets_unavailable",
        ) from exc

    ranked: list[dict[str, Any]] = []
    seen_ids = {ticket_id}
    for result in retrieval.get("results", []):
        related_id = str(result.get("ticket_id") or "")
        if (
            result.get("source_type") != "ticket"
            or not related_id
            or related_id in seen_ids
        ):
            continue
        seen_ids.add(related_id)
        ranked.append({"ticket_id": related_id, "result": result})

    records_by_id: dict[str, TicketRecord] = {}
    if ranked:
        related_ids = [item["ticket_id"] for item in ranked]
        related_query = db.query(TicketRecord).filter(
            TicketRecord.id.in_(related_ids),
            func.lower(func.coalesce(TicketRecord.external_source, "")) != "portal",
        )
        if allowed_assignee_id is not None:
            related_query = related_query.filter(
                TicketRecord.assignee_id == allowed_assignee_id
            )
        records_by_id = {record.id: record for record in related_query.all()}

    items = []
    for ranked_item in ranked:
        if len(items) >= limit:
            break
        record = records_by_id.get(ranked_item["ticket_id"])
        if not record:
            continue
        result = ranked_item["result"]
        items.append({
            "ticket_id": record.id,
            "subject": record.subject,
            "status": record.status,
            "priority": record.priority,
            "category": record.category,
            "score": float(result.get("score") or 0.0),
            "match_method": str(result.get("match_method") or "keyword"),
        })
    return {
        "ticket_id": ticket.id,
        "available": True,
        "match_method": str(retrieval.get("match_method") or "keyword"),
        "items": items,
    }


def _normalize_portal_reporter(reporter: str) -> str:
    value = (reporter or "").strip().lower()
    if not re.fullmatch(r"[^@\s%_*]+@[^@\s%_*]+\.[^@\s%_*]+", value):
        raise HTTPException(status_code=400, detail="A valid email address is required")
    return value


def _normalize_portal_priority(priority: str) -> str:
    value = (priority or "P3").strip()
    mapping = {
        "urgent": "P1",
        "high": "P2",
        "medium": "P3",
        "normal": "P3",
        "low": "P4",
        "p1": "P1",
        "p2": "P2",
        "p3": "P3",
        "p4": "P4",
    }
    return mapping.get(value.lower(), value.upper() if value.upper() in {"P1", "P2", "P3", "P4"} else "P3")


def _portal_token_ttl() -> timedelta:
    """Return a bounded portal capability lifetime.

    The environment override supports deployments with stricter retention
    requirements while preventing accidental non-expiring or extreme values.
    """
    try:
        days = int(os.getenv("PORTAL_ACCESS_TOKEN_TTL_DAYS", PORTAL_ACCESS_TOKEN_TTL_DAYS))
    except (TypeError, ValueError):
        days = PORTAL_ACCESS_TOKEN_TTL_DAYS
    return timedelta(days=max(1, min(days, 3650)))


def _portal_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _portal_tracking_url(request: Request, token: str) -> str:
    frontend_origin = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    origin = frontend_origin or str(request.base_url).rstrip("/")
    # Keep bearer capability material in the fragment: fragments are handled
    # client-side and are not sent in HTTP requests or ordinary access logs.
    return f"{origin}/portal#token={urllib.parse.quote(token, safe='')}"


def _portal_bearer_token(request: Request) -> Optional[str]:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token or token != token.strip():
        return None
    return token


def _portal_ticket_for_token(db: Session, token: Optional[str]) -> Optional[TicketRecord]:
    # urlsafe_b64encode output for a 32-byte token is 43 characters. Keep the
    # accepted range narrow and do a dummy comparison for malformed tokens so
    # obvious invalid inputs do not take a completely separate fast path.
    if not token or not 40 <= len(token) <= 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        hmac.compare_digest("0" * 64, _portal_token_digest("invalid"))
        return None
    digest = _portal_token_digest(token)
    ticket = db.query(TicketRecord).filter(
        TicketRecord.portal_access_token_hash == digest,
        TicketRecord.external_source == "portal",
    ).first()
    if not ticket or not ticket.portal_access_token_hash:
        hmac.compare_digest("0" * 64, digest)
        return None
    if not hmac.compare_digest(ticket.portal_access_token_hash, digest):
        return None
    if not ticket.portal_access_expires_at or ticket.portal_access_expires_at <= datetime.utcnow():
        return None
    return ticket


def _priority_sla_hours(db: Session, priority: str) -> int:
    configured = db.query(TicketPriorityConfigRecord).filter(
        TicketPriorityConfigRecord.name == priority
    ).first()
    if configured and configured.sla_hours:
        return int(configured.sla_hours)
    env_key = f"SLA_{priority}_HOURS"
    raw = os.getenv(env_key)
    if raw and raw.isdigit():
        return int(raw)
    defaults = {"P1": 4, "P2": 24, "P3": 72, "P4": 168}
    return defaults.get(priority, 72)


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _increment_request_bucket(
    db: Session,
    actor_id: str,
    window_kind: str,
    window_start: datetime,
) -> int:
    values = {
        "actor_id": actor_id,
        "window_kind": window_kind,
        "window_start": window_start,
        "request_count": 1,
    }
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        row = db.query(AIRequestBucketRecord).filter_by(
            actor_id=actor_id,
            window_kind=window_kind,
            window_start=window_start,
        ).with_for_update().first()
        if row:
            row.request_count += 1
        else:
            row = AIRequestBucketRecord(**values)
            db.add(row)
        db.flush()
        return row.request_count
    statement = insert(AIRequestBucketRecord).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=["actor_id", "window_kind", "window_start"],
        set_={"request_count": AIRequestBucketRecord.request_count + 1},
    ).returning(AIRequestBucketRecord.request_count)
    return int(db.execute(statement).scalar_one())


def _reserve_ai_request(db: Session, actor_id: str, task: str) -> None:
    """Durable per-user provider-work budget shared by every API replica."""
    now = datetime.utcnow()
    per_minute = _bounded_env_int("AI_USER_REQUESTS_PER_MINUTE", 10, 1, 120)
    per_day = _bounded_env_int("AI_USER_REQUESTS_PER_DAY", 200, 1, 10_000)
    minute_start = now.replace(second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    minute_count = _increment_request_bucket(db, actor_id, "minute", minute_start)
    day_count = _increment_request_bucket(db, actor_id, "day", day_start)
    if minute_count > per_minute:
        db.rollback()
        raise HTTPException(status_code=429, detail="ai_rate_limit_exceeded", headers={"Retry-After": "60"})
    if day_count > per_day:
        db.rollback()
        raise HTTPException(status_code=429, detail="ai_daily_budget_exceeded", headers={"Retry-After": "3600"})
    db.add(AIUsageEventRecord(actor_id=actor_id, task=task, created_at=now))
    db.commit()


def _reserve_analytics_request(db: Session, actor_id: str) -> None:
    """Rate-limit local analytics without spending the provider-work budget."""
    now = datetime.utcnow()
    per_minute = _bounded_env_int(
        "ANALYTICS_USER_REQUESTS_PER_MINUTE", 60, 1, 600
    )
    per_day = _bounded_env_int(
        "ANALYTICS_USER_REQUESTS_PER_DAY", 5_000, 1, 100_000
    )
    minute_count = _increment_request_bucket(
        db,
        actor_id,
        "analytics_minute",
        now.replace(second=0, microsecond=0),
    )
    day_count = _increment_request_bucket(
        db,
        actor_id,
        "analytics_day",
        now.replace(hour=0, minute=0, second=0, microsecond=0),
    )
    if minute_count > per_minute:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="analytics_rate_limit_exceeded",
            headers={"Retry-After": "60"},
        )
    if day_count > per_day:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="analytics_daily_limit_exceeded",
            headers={"Retry-After": "3600"},
        )
    db.commit()


def _reserve_index_write_request(db: Session, actor_id: str) -> None:
    """Bound corpus mutations even when no external embedding call occurs."""
    now = datetime.utcnow()
    per_minute = _bounded_env_int("AI_INDEX_WRITES_PER_MINUTE", 30, 1, 600)
    per_day = _bounded_env_int("AI_INDEX_WRITES_PER_DAY", 500, 1, 100_000)
    minute_count = _increment_request_bucket(
        db,
        actor_id,
        "index_write_minute",
        now.replace(second=0, microsecond=0),
    )
    day_count = _increment_request_bucket(
        db,
        actor_id,
        "index_write_day",
        now.replace(hour=0, minute=0, second=0, microsecond=0),
    )
    if minute_count > per_minute:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="ai_index_write_rate_limit_exceeded",
            headers={"Retry-After": "60"},
        )
    if day_count > per_day:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="ai_index_write_daily_limit_exceeded",
            headers={"Retry-After": "3600"},
        )
    db.commit()


def _normalized_corpus_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _reject_duplicate_recent_comment(
    db: Session,
    *,
    ticket_id: str,
    author_id: str,
    body: str,
    is_private: bool,
) -> None:
    """Prevent cheap repeated documents from dominating keyword retrieval."""
    normalized = _normalized_corpus_text(body)
    if not normalized:
        raise HTTPException(status_code=422, detail="Comment body cannot be blank")
    recent = db.query(TicketCommentRecord.body).filter(
        TicketCommentRecord.ticket_id == ticket_id,
        TicketCommentRecord.author_id == author_id,
        TicketCommentRecord.is_private.is_(is_private),
        TicketCommentRecord.created_at >= datetime.utcnow() - timedelta(days=1),
    ).order_by(
        TicketCommentRecord.created_at.desc(), TicketCommentRecord.id.desc()
    ).limit(100).all()
    if any(_normalized_corpus_text(row.body) == normalized for row in recent):
        raise HTTPException(status_code=409, detail="duplicate_comment")


def _reserve_portal_ticket_request(
    db: Session,
    reporter: str,
) -> None:
    """Durably bound public creation globally and per normalized reporter."""
    now = datetime.utcnow()
    per_minute = _bounded_env_int("PORTAL_TICKETS_PER_MINUTE", 5, 1, 60)
    per_day = _bounded_env_int("PORTAL_TICKETS_PER_DAY", 50, 1, 1_000)
    global_per_minute = _bounded_env_int(
        "PORTAL_TICKETS_GLOBAL_PER_MINUTE", 20, 1, 600
    )
    global_per_day = _bounded_env_int(
        "PORTAL_TICKETS_GLOBAL_PER_DAY", 200, 1, 10_000
    )
    limits = (
        (
            "portal-global",
            "portal_global_create_minute",
            "portal_global_create_day",
            global_per_minute,
            global_per_day,
        ),
        (
            "portal-reporter:"
            + hashlib.sha256(reporter.strip().lower().encode()).hexdigest()[:32],
            "portal_create_minute",
            "portal_create_day",
            per_minute,
            per_day,
        ),
    )
    for actor_id, minute_kind, day_kind, minute_limit, day_limit in limits:
        minute_count = _increment_request_bucket(
            db,
            actor_id,
            minute_kind,
            now.replace(second=0, microsecond=0),
        )
        day_count = _increment_request_bucket(
            db,
            actor_id,
            day_kind,
            now.replace(hour=0, minute=0, second=0, microsecond=0),
        )
        if minute_count > minute_limit or day_count > day_limit:
            db.rollback()
            raise HTTPException(
                status_code=429,
                detail="portal_ticket_rate_limit_exceeded",
                headers={
                    "Retry-After": "60" if minute_count > minute_limit else "3600"
                },
            )
    db.commit()


def _reserve_survey_response_request(db: Session, survey_id: str) -> None:
    """Durably bound survey submissions without storing attacker-controlled IDs."""
    now = datetime.utcnow()
    per_survey_id = "survey:" + hashlib.sha256(
        survey_id.encode("utf-8")
    ).hexdigest()[:32]
    limits = (
        (
            per_survey_id,
            "survey_response_minute",
            "survey_response_day",
            5,
            100,
        ),
        (
            "survey-global",
            "survey_response_global_minute",
            "survey_response_global_day",
            _bounded_env_int("SURVEY_RESPONSES_GLOBAL_PER_MINUTE", 100, 1, 10_000),
            _bounded_env_int("SURVEY_RESPONSES_GLOBAL_PER_DAY", 5_000, 1, 1_000_000),
        ),
    )
    for actor_id, minute_kind, day_kind, minute_limit, day_limit in limits:
        minute_count = _increment_request_bucket(
            db, actor_id, minute_kind, now.replace(second=0, microsecond=0)
        )
        day_count = _increment_request_bucket(
            db, actor_id, day_kind, now.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        if minute_count > minute_limit or day_count > day_limit:
            db.rollback()
            raise HTTPException(
                status_code=429,
                detail="survey_rate_limit_exceeded",
                headers={"Retry-After": "60" if minute_count > minute_limit else "3600"},
            )
    # Persist before checking the survey state so failed submissions cannot
    # evade the rate limit through a later 404/409 response.
    db.commit()


def _reserve_embedding_request(
    db: Session,
    user: UserRecord,
    task: str,
    *,
    eligible: bool = True,
) -> None:
    if (
        eligible
        and ticket_vectors.embedding_enabled()
        and ticket_vectors.ticket_vector_store_ready(db)
    ):
        _reserve_ai_request(db, user.id, task)


def _apply_sla_targets(ticket: TicketRecord, db: Session):
    started_at = ticket.external_created_at or ticket.created_at or datetime.utcnow()
    resolution_due = ticket.external_due_by or ticket.due_by
    if not resolution_due:
        resolution_due = started_at + timedelta(hours=_priority_sla_hours(db, ticket.priority or "P3"))
    response_due = ticket.external_fr_due_by
    if not response_due:
        response_due = started_at + timedelta(hours=max(1, min(4, _priority_sla_hours(db, ticket.priority or "P3") // 4)))
    ticket.response_due_at = ticket.response_due_at or response_due
    ticket.resolution_due_at = ticket.resolution_due_at or resolution_due
    ticket.due_by = ticket.due_by or resolution_due


def _terminal_status_names(db: Session) -> set[str]:
    configured = db.query(TicketStatusConfigRecord).filter(
        TicketStatusConfigRecord.is_terminal.is_(True)
    ).all()
    names = {c.name.lower() for c in configured}
    return names or {"closed", "resolved", "cancelled"}


def _is_terminal_status(db: Session, status: Optional[str]) -> bool:
    return bool(status and status.lower() in _terminal_status_names(db))


def _require_demo_ticketing() -> None:
    """Keep production Tickety on the read-only sidecar boundary.

    Demo mode retains local ticket CRUD for the bundled showcase data. In a
    real deployment, Freshservice owns ticket lifecycle and Tickety stores
    only synchronized projections plus local intelligence.
    """
    if settings_module.is_production_mode():
        raise HTTPException(
            status_code=409,
            detail=(
                "Freshservice is the authoritative ticket system; "
                "Tickety production ticket lifecycle is read-only"
            ),
        )


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
async def update_ticket(
    ticket_id: str,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_protected_ai_user),
):
    """Update a ticket — status, priority, assignee, category, tags, etc.
    Records every change in the audit log."""
    _require_demo_ticketing()
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    supplied_changes = {
        field
        for field, value in payload.model_dump(exclude_unset=True).items()
        if value is not None and getattr(ticket, field, None) != value
    }
    _authorize_ticket_mutation(
        user,
        ticket,
        changed_fields=supplied_changes,
        requested_assignee_id=payload.assignee_id,
    )
    document_fields = {
        "subject", "description", "status", "workflow_status", "priority",
        "category", "tags", "assignee_id", "ticket_type",
    }
    document_input_changed = any(
        getattr(payload, field, None) is not None
        and getattr(ticket, field, None) != getattr(payload, field)
        for field in document_fields
    )
    analysis_input_changed = any(
        getattr(payload, field, None) is not None
        and getattr(ticket, field, None) != getattr(payload, field)
        for field in {"subject", "description"}
    )
    resolution_input_changed = any(
        getattr(payload, field, None) is not None
        and getattr(ticket, field, None) != getattr(payload, field)
        for field in {"priority", "category"}
    )
    if document_input_changed:
        _reserve_index_write_request(db, user.id)
    if (
        (
            analysis_input_changed
            and _automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE")
        )
        or (
            resolution_input_changed
            and _automation_enabled("AUTO_RESOLVE_ENABLED")
        )
    ):
        _reserve_ai_request(db, user.id, "ticket_update_auto_processing")
    _reserve_embedding_request(
        db,
        user,
        "ticket_update_embedding",
        eligible=document_input_changed,
    )
    actor_name = user.name
    # Track changes for audit log
    for field in [
        "subject", "description", "status", "workflow_status", "ai_review_state",
        "priority", "ticket_type", "impact", "urgency", "assignee_id", "service_id",
        "asset_id", "category", "tags", "response_due_at", "resolution_due_at", "due_by",
    ]:
        val = getattr(payload, field, None)
        if val is not None:
            old = getattr(ticket, field, None)
            if old != val:
                db.add(TicketAuditLogRecord(
                    ticket_id=ticket.id, field=field,
                    old_value=str(old) if old else None,
                    new_value=str(val),
                    changed_by=actor_name,
                ))
                setattr(ticket, field, val)
    if analysis_input_changed:
        invalidate_ticket_ai(ticket)
    elif resolution_input_changed:
        invalidate_ticket_resolution(ticket)
    if payload.priority:
        # Recompute missing SLA clocks after priority changes; explicit due dates win.
        _apply_sla_targets(ticket, db)
    # Auto-set resolved_at when status changes to Resolved/Closed
    if payload.status and _is_terminal_status(db, payload.status):
        if not ticket.resolved_at:
            ticket.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    if document_input_changed:
        await ticket_vectors.refresh_ticket_documents(db, ticket)
    return ticket


@app.delete("/tickets/{ticket_id}")
async def delete_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    _require_demo_ticketing()
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket_vectors.delete_ticket_documents(db, ticket_id)
    db.delete(ticket)
    db.commit()
    return {"status": "deleted", "ticket_id": ticket_id}


# ── Ticket comments / notes ──────────────────────────────────

@app.get("/tickets/{ticket_id}/comments", response_model=List[TicketComment])
async def list_comments(
    ticket_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(user, ticket)
    query = db.query(TicketCommentRecord).filter(
        TicketCommentRecord.ticket_id == ticket_id
    )
    if (user.role or "").lower() not in {"admin", "supervisor"}:
        # Private notes are supervisor material; agents never see them.
        query = query.filter(TicketCommentRecord.is_private.is_(False))
    comments = query.order_by(
        TicketCommentRecord.created_at.desc(), TicketCommentRecord.id.desc()
    ).offset(offset).limit(limit).all()
    return list(reversed(comments))


@app.post("/tickets/{ticket_id}/comments", response_model=TicketComment, status_code=201)
async def add_comment(
    ticket_id: str,
    payload: TicketCommentCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_protected_ai_user),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_mutation(user, ticket)
    _reserve_index_write_request(db, user.id)
    _reject_duplicate_recent_comment(
        db,
        ticket_id=ticket_id,
        author_id=user.id,
        body=payload.body,
        is_private=payload.is_private,
    )
    _reserve_embedding_request(
        db,
        user,
        "ticket_comment_embedding",
        eligible=(
            not payload.is_private
            or ticket_vectors.private_comment_indexing_enabled()
        ),
    )
    comment = TicketCommentRecord(
        ticket_id=ticket_id,
        body=payload.body,
        is_private=payload.is_private,
        author_id=user.id,
        author_name=user.name,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    await ticket_vectors.upsert_comment_document(db, comment)
    return comment


# ── Ticket audit log ──────────────────────────────────────────

@app.get("/tickets/{ticket_id}/audit", response_model=List[TicketAuditEntry])
async def get_audit_log(
    ticket_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(user, ticket)
    return db.query(TicketAuditLogRecord).filter(
        TicketAuditLogRecord.ticket_id == ticket_id
    ).order_by(
        TicketAuditLogRecord.changed_at.desc(), TicketAuditLogRecord.id.desc()
    ).offset(offset).limit(limit).all()


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
async def bulk_action(
    payload: BulkAction,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Apply an action to multiple tickets at once.
    Actions: assign, close, set_priority, set_category."""
    _require_demo_ticketing()
    ticket_ids = list(dict.fromkeys(payload.ticket_ids))
    tickets = db.query(TicketRecord).filter(TicketRecord.id.in_(ticket_ids)).all()
    if len(tickets) != len(ticket_ids):
        raise HTTPException(status_code=404, detail="One or more tickets were not found")

    if payload.action != "close" and not payload.value:
        raise HTTPException(status_code=422, detail="A value is required for this bulk action")
    if payload.action == "assign":
        assignee = db.query(UserRecord).filter(
            UserRecord.id == payload.value,
            UserRecord.is_active.is_(True),
        ).first()
        if not assignee:
            raise HTTPException(status_code=422, detail="Assignee is not an active user")
    elif payload.action == "set_category":
        category = db.query(TicketCategoryRecord).filter(
            TicketCategoryRecord.name == payload.value,
        ).first()
        if not category:
            raise HTTPException(status_code=422, detail="Category does not exist")
    elif payload.action == "set_priority":
        configured_priorities = {
            row[0] for row in db.query(TicketPriorityConfigRecord.name).all()
        }
        allowed_priorities = configured_priorities or {"P1", "P2", "P3", "P4"}
        if payload.value not in allowed_priorities:
            raise HTTPException(status_code=422, detail="Priority does not exist")

    target_field = {
        "assign": "assignee_id",
        "close": "status",
        "set_priority": "priority",
        "set_category": "category",
    }[payload.action]
    target_value = "Closed" if payload.action == "close" else payload.value
    if any(getattr(ticket, target_field, None) != target_value for ticket in tickets):
        _reserve_index_write_request(db, user.id)

    if (
        payload.action in {"set_priority", "set_category"}
        and any(
            getattr(ticket, "priority" if payload.action == "set_priority" else "category")
            != payload.value
            for ticket in tickets
        )
        and _automation_enabled("AUTO_RESOLVE_ENABLED")
    ):
        _reserve_ai_request(db, user.id, "ticket_bulk_auto_processing")

    count = 0
    changed_ticket_ids: set[str] = set()
    actor_name = user.name

    def record_change(ticket: TicketRecord, field: str, new_value):
        old = getattr(ticket, field, None)
        if old == new_value:
            return False
        db.add(TicketAuditLogRecord(
            ticket_id=ticket.id,
            field=field,
            old_value=str(old) if old else None,
            new_value=str(new_value),
            changed_by=actor_name,
        ))
        setattr(ticket, field, new_value)
        changed_ticket_ids.add(ticket.id)
        return True

    for t in tickets:
        if payload.action == "assign" and payload.value:
            record_change(t, "assignee_id", payload.value)
        elif payload.action == "close":
            record_change(t, "status", "Closed")
            record_change(t, "workflow_status", "Closed")
            if not t.resolved_at:
                t.resolved_at = datetime.utcnow()
                changed_ticket_ids.add(t.id)
        elif payload.action == "set_priority" and payload.value:
            if record_change(t, "priority", payload.value):
                invalidate_ticket_resolution(t)
            _apply_sla_targets(t, db)
        elif payload.action == "set_category" and payload.value:
            if record_change(t, "category", payload.value):
                invalidate_ticket_resolution(t)
        count += 1
    ticket_vectors.delete_ticket_source_documents(db, list(changed_ticket_ids))
    db.commit()
    return {"status": "completed", "updated": count}


# ── Manual ticket creation ───────────────────────────────────

@app.post("/tickets", response_model=Ticket, status_code=201)
async def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_protected_ai_user),
):
    """Create a ticket by hand (no ITSM sync). Auto-triaged if enabled."""
    _require_demo_ticketing()
    import uuid as _uuid
    _reserve_index_write_request(db, user.id)
    if _automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE"):
        # Manual creation can immediately invoke the LLM pipeline. Charge the
        # authenticated caller before persisting the ticket so this indirect
        # path cannot bypass the per-user AI request budget.
        _reserve_ai_request(db, user.id, "ticket_create_auto_processing")
    _reserve_embedding_request(db, user, "ticket_create_embedding")
    ticket = TicketRecord(
        id=str(_uuid.uuid4()),
        subject=payload.subject.strip(),
        description=payload.description,
        reporter=payload.reporter.strip() or "manual",
        status="New",
        workflow_status="New",
        priority=payload.priority,
        ticket_type=payload.ticket_type,
        assignee_id=user.id if (user.role or "").lower() == "agent" else None,
        impact=payload.impact,
        urgency=payload.urgency,
        service_id=payload.service_id,
        asset_id=payload.asset_id,
        external_source="manual",
    )
    _apply_sla_targets(ticket, db)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    await ticket_vectors.refresh_ticket_documents(db, ticket)
    await _auto_process(ticket, db)
    return ticket


def _automation_enabled(key: str, legacy_alias: Optional[str] = None) -> bool:
    return settings_module.automation_enabled(key, legacy_alias)


def _schedule_ai_retry(
    db: Session,
    ticket_id: str,
    artifacts: set[str],
    error_code: str,
    *,
    expected_claim_id: Optional[str] = None,
) -> bool:
    query = db.query(TicketRecord).filter(TicketRecord.id == ticket_id)
    if expected_claim_id:
        query = query.filter(TicketRecord.ai_claim_id == expected_claim_id)
    else:
        query = query.filter(or_(
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_status != "running",
        ))
    ticket = query.with_for_update().first()
    if not ticket:
        return False
    attempts = int(ticket.ai_attempts or 0) + 1
    max_attempts = _bounded_env_int("AI_ANALYSIS_MAX_ATTEMPTS", 3, 1, 10)
    ticket.ai_attempts = attempts
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_error = error_code
    ticket.ai_requested_artifacts = ",".join(sorted(artifacts))
    if attempts >= max_attempts:
        ticket.ai_status = "dead_letter"
        ticket.ai_next_attempt_at = None
    else:
        ticket.ai_status = "queued"
        ticket.ai_next_attempt_at = datetime.utcnow() + timedelta(
            seconds=min(3600, 30 * (2 ** (attempts - 1)))
        )
    db.commit()
    return True


def _defer_ai_capacity(
    db: Session,
    ticket_id: str,
    artifacts: set[str],
    retry_after_seconds: float,
    *,
    expected_claim_id: Optional[str] = None,
) -> bool:
    """Release a claim for quota recovery without consuming a failure attempt."""
    query = db.query(TicketRecord).filter(TicketRecord.id == ticket_id)
    if expected_claim_id:
        query = query.filter(TicketRecord.ai_claim_id == expected_claim_id)
    else:
        query = query.filter(or_(
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_status != "running",
        ))
    ticket = query.with_for_update().first()
    if not ticket:
        return False
    requested = set(artifacts)
    if ticket.ai_status == "queued":
        requested.update(
            item
            for item in (ticket.ai_requested_artifacts or "").split(",")
            if item
        )
    ticket.ai_status = "queued"
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_error = "provider_capacity"
    ticket.ai_requested_artifacts = ",".join(sorted(requested))
    ticket.ai_next_attempt_at = datetime.utcnow() + timedelta(
        seconds=max(1, min(int(retry_after_seconds), 172_800))
    )
    db.commit()
    return True


def _analysis_step_error_code(exc: BaseException) -> str:
    """Reduce an internal exception to a stable, non-sensitive failure class."""
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, LLMInvalidInputError):
        return "invalid_input"
    if isinstance(exc, LLMInvalidOutputError):
        return "invalid_output"
    if isinstance(exc, LLMCapacityError):
        return "provider_capacity"
    if isinstance(exc, LLMUnavailableError):
        return "provider_unavailable"
    if isinstance(exc, LLMAnalysisError):
        return "analysis_rejected"
    return "internal_error"


def _analysis_error_signature(errors: List[Dict[str, str]]) -> str:
    return ",".join(
        f"{error['step']}:{error['error']}" for error in errors
    )


async def _auto_process(ticket: TicketRecord, db, force: bool = False):
    """Worker/webhook adapter for the shared claimed artifact orchestrator."""
    if not force and not _automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE"):
        return
    requested = {
        item for item in (ticket.ai_requested_artifacts or "").split(",") if item
    }
    artifacts = requested
    if not artifacts:
        artifacts = set()
        if not ticket.ai_reasoning and _automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE"):
            artifacts.add("triage")
        if not ticket.summary and _automation_enabled("AUTO_SUMMARIZE_ENABLED"):
            artifacts.add("summary")
        if not ticket.recommended_solution and _automation_enabled("AUTO_RESOLVE_ENABLED"):
            artifacts.add("resolution")
        if _automation_enabled("AUTO_ROUTE_ENABLED"):
            artifacts.add("route")
    if not artifacts:
        return
    ticket_id = ticket.id
    try:
        _reserve_ai_request(db, "system-worker", f"worker:{'+'.join(sorted(artifacts))}")
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        db.rollback()
        deferred = db.query(TicketRecord).filter(
            TicketRecord.id == ticket.id,
            or_(TicketRecord.ai_claim_id.is_(None), TicketRecord.ai_claim_id == ""),
            or_(TicketRecord.ai_status.is_(None), TicketRecord.ai_status != "running"),
        ).with_for_update().first()
        if deferred:
            deferred.ai_status = "queued"
            deferred.ai_requested_artifacts = ",".join(sorted(artifacts))
            deferred.ai_next_attempt_at = datetime.utcnow() + timedelta(seconds=60)
            db.commit()
        return
    try:
        await _run_ticket_analysis(
            ticket,
            db,
            force=force or bool(requested),
            artifacts=artifacts,
        )
    except Exception as exc:
        db.rollback()
        if isinstance(exc, HTTPException) and exc.detail == "analysis_claim_lost":
            raise
        _schedule_ai_retry(
            db,
            ticket_id,
            artifacts,
            "analysis_failed",
            expected_claim_id=getattr(exc, "analysis_claim_id", None),
        )
        raise


def _ticket_kb_context(ticket: TicketRecord) -> str:
    text = (ticket.subject + " " + ticket.description).lower()
    if "vpn" in text:
        return "To reset VPN, restart the client and click Reconnect. Ensure corporate Wi-Fi is connected."
    return ""


def _apply_ticket_analysis(ticket: TicketRecord, analysis_data: Dict[str, Any], db: Session) -> None:
    ticket.sentiment = analysis_data.get("sentiment")
    # Generated classification remains advisory. Only an audited human ticket
    # update may change the canonical category used by routing and retrieval.
    ticket.ai_suggested_category = analysis_data.get("category")
    ticket.ai_suggested_priority = analysis_data.get("priority")
    ticket.mood = analysis_data.get("mood")
    ticket.complexity = analysis_data.get("complexity", 1)
    ticket.ai_reasoning = analysis_data.get("reasoning")
    ticket.escalation_risk = intel.escalation_risk(ticket)

    if analysis_data.get("suggested_response"):
        ticket.suggested_response = analysis_data.get("suggested_response")
        ticket.ai_review_state = "Awaiting Review"
    elif analysis_data.get("action") == "escalate":
        # Generated analysis is decision support. A human must apply the
        # operational escalation through the normal audited workflow action.
        ticket.ai_review_state = "Escalation Suggested"
        ticket.workflow_status = ticket.workflow_status or ticket.status or "Open"
    else:
        ticket.ai_review_state = "Processed"
        ticket.workflow_status = ticket.workflow_status or ticket.status or "Open"
    ticket.status = ticket.workflow_status or ticket.status


def _triage_result_payload(ticket: TicketRecord, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ticket_id": ticket.id,
        "sentiment": analysis_data.get("sentiment", "Neutral"),
        "category": analysis_data.get("category", "Other"),
        "priority": analysis_data.get("priority", "P3"),
        "mood": analysis_data.get("mood", "neutral"),
        "complexity": analysis_data.get("complexity", 1),
        "action": analysis_data.get("action", "respond"),
        "reasoning": analysis_data.get("reasoning", ""),
        "suggested_response": analysis_data.get("suggested_response"),
        "escalation_risk": ticket.escalation_risk or 0,
    }


def _llm_cache_identity() -> str:
    identity = getattr(engine.llm, "cache_identity", None)
    if isinstance(identity, str) and identity:
        return identity
    return str(engine.llm.model_name)


def _ticket_analysis_hash(ticket: TicketRecord) -> str:
    payload = {
        "subject": ticket.subject or "",
        "description": ticket.description or "",
        "public_thread": ticket.external_conversation_text or "",
        "model": _llm_cache_identity(),
        "pipeline": AI_PIPELINE_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _analysis_lease_seconds() -> int:
    configured = _bounded_env_int("AI_ANALYSIS_LEASE_SECONDS", 1800, 300, 7200)
    provider_floor = int(3 * getattr(engine.llm, "overall_timeout", 90) + 180)
    pipeline_floor = _analysis_pipeline_timeout_seconds() + 60
    return max(configured, provider_floor, pipeline_floor)


def _analysis_pipeline_timeout_seconds() -> int:
    return _bounded_env_int("AI_PIPELINE_TIMEOUT_SECONDS", 900, 120, 3600)


def _artifact_input_hash(ticket: TicketRecord, artifact: str) -> str:
    payload: Dict[str, Any] = {
        "artifact": artifact,
        "subject": ticket.subject or "",
        "description": ticket.description or "",
        "public_thread": ticket.external_conversation_text or "",
        "model": _llm_cache_identity(),
        "pipeline": AI_PIPELINE_VERSION,
    }
    if artifact in {"summary", "resolution"}:
        payload["triage_reasoning"] = ticket.ai_reasoning or ""
    if artifact == "resolution":
        payload.update({
            "provider_source_context_hash": ticket.external_source_context_hash,
            "category": ticket.category or "Other",
            "priority": ticket.priority or "P3",
            "sentiment": ticket.sentiment or "Neutral",
            "provider_category": ticket.external_category,
            "provider_subcategory": ticket.external_subcategory,
            "provider_item_category": ticket.external_item_category,
        })
    if artifact == "route":
        payload.update({
            "provider_source_context_hash": ticket.external_source_context_hash,
            "priority": ticket.priority or "P3",
            "provider_category": ticket.external_category,
            "provider_subcategory": ticket.external_subcategory,
            "provider_item_category": ticket.external_item_category,
            "provider_group_id": ticket.external_group_id,
            "provider_responder_id": ticket.external_assignee_id,
        })
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _artifact_is_current(db: Session, ticket: TicketRecord, artifact: str) -> bool:
    field_present = {
        "triage": bool(ticket.ai_reasoning),
        "summary": bool(ticket.summary),
        "resolution": bool(ticket.recommended_solution),
    }.get(artifact, False)
    if not field_present or ticket.ai_status in {"legacy_stale", "provenance_unknown", "stale"}:
        return False
    query = db.query(AIArtifactRecord).filter(
        AIArtifactRecord.ticket_id == ticket.id,
        AIArtifactRecord.artifact == artifact,
        AIArtifactRecord.input_hash == _artifact_input_hash(ticket, artifact),
        AIArtifactRecord.pipeline_version == AI_PIPELINE_VERSION,
        AIArtifactRecord.model == _llm_cache_identity(),
        AIArtifactRecord.active.is_(True),
    )
    if settings_module.is_production_mode() or not bool(
        getattr(engine.llm, "allow_synthetic", False)
    ):
        query = query.filter(AIArtifactRecord.synthetic.is_(False))
    return query.first() is not None


def _claim_ticket_analysis(
    ticket: TicketRecord, db: Session, *, force: bool = False
) -> tuple[bool, str, str]:
    """Atomically claim a ticket across API and worker processes."""
    source_hash = _ticket_analysis_hash(ticket)
    now = datetime.utcnow()
    claim_id = secrets.token_hex(16)
    lease_seconds = _analysis_lease_seconds()
    available = or_(
        TicketRecord.ai_status.is_(None),
        TicketRecord.ai_status != "running",
        TicketRecord.ai_lease_expires_at.is_(None),
        TicketRecord.ai_lease_expires_at < now,
    )
    query = db.query(TicketRecord).filter(TicketRecord.id == ticket.id, available)
    if not force:
        query = query.filter(or_(
            TicketRecord.ai_status != "completed",
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_source_hash != source_hash,
            TicketRecord.ai_source_hash.is_(None),
            TicketRecord.ai_pipeline_version != AI_PIPELINE_VERSION,
            TicketRecord.ai_pipeline_version.is_(None),
            TicketRecord.ai_model != _llm_cache_identity(),
            TicketRecord.ai_model.is_(None),
        ))
    changed = query.update(
        {
            TicketRecord.ai_status: "running",
            TicketRecord.ai_claim_id: claim_id,
            TicketRecord.ai_lease_expires_at: now + timedelta(seconds=lease_seconds),
            TicketRecord.ai_started_at: now,
            TicketRecord.ai_error: None,
            TicketRecord.ai_source_hash: source_hash,
            TicketRecord.ai_pipeline_version: AI_PIPELINE_VERSION,
            TicketRecord.ai_model: _llm_cache_identity(),
        },
        synchronize_session=False,
    )
    db.commit()
    db.refresh(ticket)
    return bool(changed), source_hash, claim_id


def _cached_analysis_payload(ticket: TicketRecord, db: Session) -> Dict[str, Any]:
    try:
        plan = json.loads(ticket.recommended_solution) if ticket.recommended_solution else None
    except (TypeError, ValueError):
        plan = None
    triage_data = {
        "sentiment": ticket.sentiment or "Neutral",
        "category": ticket.ai_suggested_category or "Other",
        "priority": ticket.priority or "P3",
        "mood": ticket.mood or "neutral",
        "complexity": ticket.complexity or 1,
        "action": "escalate" if ticket.ai_review_state in {"Escalated", "Escalation Suggested"} else "respond",
        "reasoning": ticket.ai_reasoning or "",
        "suggested_response": ticket.suggested_response,
    }
    return {
        "ticket_id": ticket.id,
        "triage": _triage_result_payload(ticket, triage_data),
        "summary": ticket.summary,
        "route": intel.recommend_assignee(db, ticket),
        "recommended_solution": {
            "ticket_id": ticket.id,
            "plan": plan,
            "cached": True,
        } if plan else None,
        "documents_changed": 0,
        "errors": [],
        "cached": True,
    }


def _record_ai_artifact(
    db: Session,
    ticket: TicketRecord,
    artifact: str,
    content: Any,
    source_hash: str,
) -> None:
    db.query(AIArtifactRecord).filter(
        AIArtifactRecord.ticket_id == ticket.id,
        AIArtifactRecord.artifact == artifact,
        AIArtifactRecord.active.is_(True),
    ).update({AIArtifactRecord.active: False}, synchronize_session=False)
    serialized = json.dumps(content, sort_keys=True, default=str, ensure_ascii=False)
    db.add(AIArtifactRecord(
        ticket_id=ticket.id,
        artifact=artifact,
        input_hash=_artifact_input_hash(ticket, artifact),
        pipeline_version=AI_PIPELINE_VERSION,
        provider=getattr(engine.llm, "provider", "unknown"),
        model=_llm_cache_identity(),
        synthetic=bool(
            getattr(engine.llm, "is_mock", False)
            and getattr(engine.llm, "allow_synthetic", False)
        ),
        content_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        active=True,
        created_at=datetime.utcnow(),
    ))


def _ensure_analysis_input_current(
    ticket: TicketRecord, db: Session, source_hash: str, claim_id: str
) -> TicketRecord:
    ticket = db.query(TicketRecord).filter(
        TicketRecord.id == ticket.id,
        TicketRecord.ai_claim_id == claim_id,
        TicketRecord.ai_status == "running",
    ).with_for_update().populate_existing().first()
    if not ticket:
        raise HTTPException(status_code=409, detail="analysis_claim_lost")
    if ticket.ai_claim_id != claim_id or ticket.ai_status != "running":
        raise HTTPException(status_code=409, detail="analysis_claim_lost")
    if _ticket_analysis_hash(ticket) == source_hash:
        return ticket
    invalidate_ticket_ai(ticket)
    ticket.ai_error = "input_changed_during_analysis"
    db.commit()
    raise HTTPException(status_code=409, detail="analysis_input_changed")


def _renew_analysis_lease(db: Session, ticket_id: str, claim_id: str) -> None:
    lease_seconds = _analysis_lease_seconds()
    changed = db.query(TicketRecord).filter(
        TicketRecord.id == ticket_id,
        TicketRecord.ai_claim_id == claim_id,
        TicketRecord.ai_status == "running",
    ).update({
        TicketRecord.ai_lease_expires_at: datetime.utcnow() + timedelta(seconds=lease_seconds)
    }, synchronize_session=False)
    if not changed:
        db.rollback()
        raise HTTPException(status_code=409, detail="analysis_claim_lost")
    db.commit()


def _pipeline_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise asyncio.TimeoutError("AI pipeline deadline exceeded")
    return remaining


async def _run_ticket_analysis(
    ticket: TicketRecord,
    db: Session,
    *,
    force: bool = False,
    artifacts: Optional[set[str]] = None,
    progress=None,
) -> Dict[str, Any]:
    """Run claimed AI artifacts through one ownership-safe orchestrator."""
    requested_artifacts = set(
        artifacts
        if artifacts is not None
        else {"triage", "summary", "route", "resolution", "refresh"}
    )
    if not requested_artifacts.issubset(
        {"triage", "summary", "route", "resolution", "refresh"}
    ):
        raise ValueError("unsupported AI artifact")
    artifacts = set(requested_artifacts)
    if artifacts - {"refresh"}:
        # Every generated artifact can change the indexed ticket document.
        # Treat refresh as a deterministic downstream dependency while keeping
        # the durable retry request scoped to the failed generated artifact.
        artifacts.add("refresh")
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket.id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not force:
        persisted_artifacts = artifacts - {"route", "refresh"}
        artifact_cached = bool(persisted_artifacts) and all(
            _artifact_is_current(db, ticket, artifact)
            for artifact in persisted_artifacts
        )
        if artifact_cached:
            return _cached_analysis_payload(ticket, db)
    claimed, source_hash, claim_id = _claim_ticket_analysis(
        ticket,
        db,
        force=force or (not artifact_cached if not force else False),
    )
    if not claimed:
        if ticket.ai_status == "running":
            raise HTTPException(status_code=409, detail="analysis_in_progress")
        return _cached_analysis_payload(ticket, db)
    pipeline_deadline = time.monotonic() + _analysis_pipeline_timeout_seconds()

    async def emit(step: str, status: str):
        if progress:
            await progress(step, status)

    errors: List[Dict[str, str]] = []
    capacity_deferrals: Dict[str, float] = {}
    analysis_data = {
        "sentiment": ticket.sentiment or "Neutral",
        "category": ticket.category or "Other",
        "priority": ticket.ai_suggested_priority or ticket.priority or "P3",
        "mood": ticket.mood or "neutral",
        "complexity": ticket.complexity or 1,
        "action": "escalate" if ticket.ai_review_state == "Escalation Suggested" else "respond",
        "reasoning": ticket.ai_reasoning or "",
        "suggested_response": ticket.suggested_response,
    }
    if "triage" in artifacts:
        try:
            await emit("triage", "active")
            ticket_id = ticket.id
            db.expunge(ticket)
            db.close()
            analysis_data = await asyncio.wait_for(
                engine.process_ticket(
                    {
                        "subject": ticket.subject,
                        "description": ticket.description,
                        "public_thread": ticket.external_conversation_text or "",
                    },
                    kb_info=_ticket_kb_context(ticket),
                ),
                timeout=_pipeline_remaining(pipeline_deadline),
            )
            ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            ticket = _ensure_analysis_input_current(ticket, db, source_hash, claim_id)
            serialized_triage = json.dumps(
                analysis_data, sort_keys=True, default=str, ensure_ascii=False
            )
            new_triage_hash = hashlib.sha256(serialized_triage.encode("utf-8")).hexdigest()
            prior_triage = db.query(AIArtifactRecord).filter(
                AIArtifactRecord.ticket_id == ticket.id,
                AIArtifactRecord.artifact == "triage",
                AIArtifactRecord.active.is_(True),
            ).first()
            if prior_triage is None or prior_triage.content_hash != new_triage_hash:
                ticket.summary = None
                ticket.recommended_solution = None
                db.query(AIArtifactRecord).filter(
                    AIArtifactRecord.ticket_id == ticket.id,
                    AIArtifactRecord.artifact.in_(["summary", "resolution"]),
                    AIArtifactRecord.active.is_(True),
                ).update({AIArtifactRecord.active: False}, synchronize_session=False)
            _apply_ticket_analysis(ticket, analysis_data, db)
            _record_ai_artifact(db, ticket, "triage", analysis_data, source_hash)
            db.commit()
            db.refresh(ticket)
            await emit("triage", "done")
        except Exception as exc:
            db.rollback()
            try:
                setattr(exc, "analysis_claim_id", claim_id)
            except Exception:
                pass
            claim_terminal = (
                isinstance(exc, HTTPException)
                and exc.detail in {"analysis_input_changed", "analysis_claim_lost"}
            )
            if not claim_terminal:
                error_code = _analysis_step_error_code(exc)
                error_signature = f"triage:{error_code}"
                print(
                    f"[analysis] artifact failed ticket={ticket.id[:8]} "
                    f"step=triage code={error_code}"
                )
                if isinstance(exc, LLMCapacityError):
                    _defer_ai_capacity(
                        db,
                        ticket.id,
                        requested_artifacts,
                        exc.retry_after_seconds,
                        expected_claim_id=claim_id,
                    )
                else:
                    _schedule_ai_retry(
                        db,
                        ticket.id,
                        requested_artifacts,
                        error_signature,
                        expected_claim_id=claim_id,
                    )
            await emit("triage", "error")
            raise

    summary = ticket.summary
    try:
        plan_dict = json.loads(ticket.recommended_solution) if ticket.recommended_solution else None
    except (TypeError, ValueError):
        plan_dict = None

    tasks = {}
    if "summary" in artifacts:
        await emit("summary", "active")
        tasks["summary"] = asyncio.create_task(
            intel.summarize_ticket(engine.llm, ticket, force=True)
        )
    if "resolution" in artifacts:
        await emit("resolution", "active")
        tasks["resolution"] = asyncio.create_task(
            intel.recommend_resolution(engine.llm, ticket)
        )
    if tasks:
        ticket_id = ticket.id
        db.expunge(ticket)
        db.close()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks.values(), return_exceptions=True),
                timeout=_pipeline_remaining(pipeline_deadline),
            )
        except Exception as exc:
            for task in tasks.values():
                task.cancel()
            db.rollback()
            try:
                setattr(exc, "analysis_claim_id", claim_id)
            except Exception:
                pass
            error_code = _analysis_step_error_code(exc)
            failed_steps = sorted(tasks)
            error_signature = ",".join(
                f"{step}:{error_code}" for step in failed_steps
            )
            print(
                f"[analysis] artifact group failed ticket={ticket_id[:8]} "
                f"steps={'+'.join(failed_steps)} code={error_code}"
            )
            _schedule_ai_retry(
                db,
                ticket_id,
                set(tasks),
                error_signature,
                expected_claim_id=claim_id,
            )
            raise
        task_results = dict(zip(tasks, results))
        ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket = _ensure_analysis_input_current(ticket, db, source_hash, claim_id)
        if "summary" in task_results:
            result = task_results["summary"]
            if isinstance(result, Exception):
                error_code = _analysis_step_error_code(result)
                errors.append({"step": "summary", "error": error_code})
                if isinstance(result, LLMCapacityError):
                    capacity_deferrals["summary"] = result.retry_after_seconds
                print(
                    f"[analysis] artifact failed ticket={ticket.id[:8]} "
                    f"step=summary code={error_code}"
                )
                await emit("summary", "error")
            else:
                summary = result
                if summary:
                    ticket.summary = summary
                    _record_ai_artifact(db, ticket, "summary", summary, source_hash)
                await emit("summary", "done")
        if "resolution" in task_results:
            result = task_results["resolution"]
            if isinstance(result, Exception):
                error_code = _analysis_step_error_code(result)
                errors.append({"step": "resolution", "error": error_code})
                if isinstance(result, LLMCapacityError):
                    capacity_deferrals["resolution"] = result.retry_after_seconds
                print(
                    f"[analysis] artifact failed ticket={ticket.id[:8]} "
                    f"step=resolution code={error_code}"
                )
                await emit("resolution", "error")
            else:
                plan_dict = result
                ticket.recommended_solution = json.dumps(plan_dict)
                _record_ai_artifact(db, ticket, "resolution", plan_dict, source_hash)
                await emit("resolution", "done")
        db.commit()
        db.refresh(ticket)

    route = None
    if "route" in artifacts:
        try:
            await emit("route", "active")
            route = intel.recommend_assignee(db, ticket)
            await emit("route", "done")
        except Exception as exc:
            error_code = _analysis_step_error_code(exc)
            errors.append({"step": "route", "error": error_code})
            print(
                f"[analysis] artifact failed ticket={ticket.id[:8]} "
                f"step=route code={error_code}"
            )
            await emit("route", "error")

    documents_changed = 0
    if "refresh" in artifacts:
        await emit("refresh", "active")
        try:
            async def refresh_heartbeat() -> None:
                _renew_analysis_lease(db, ticket.id, claim_id)

            documents_changed = await ticket_vectors.refresh_ticket_documents(
                db,
                ticket,
                heartbeat=refresh_heartbeat,
                deadline_monotonic=pipeline_deadline,
            )
            await emit("refresh", "done")
        except asyncio.TimeoutError as exc:
            db.rollback()
            try:
                setattr(exc, "analysis_claim_id", claim_id)
            except Exception:
                pass
            _schedule_ai_retry(
                db,
                ticket.id,
                {"refresh"},
                "refresh:timeout",
                expected_claim_id=claim_id,
            )
            await emit("refresh", "error")
            raise
        except Exception as exc:
            error_code = _analysis_step_error_code(exc)
            errors.append({"step": "refresh", "error": error_code})
            print(
                f"[analysis] artifact failed ticket={ticket.id[:8]} "
                f"step=refresh code={error_code}"
            )
            await emit("refresh", "error")

    try:
        _pipeline_remaining(pipeline_deadline)
    except asyncio.TimeoutError as exc:
        try:
            setattr(exc, "analysis_claim_id", claim_id)
        except Exception:
            pass
        _schedule_ai_retry(
            db,
            ticket.id,
            requested_artifacts,
            "pipeline:timeout",
            expected_claim_id=claim_id,
        )
        raise
    db.refresh(ticket)
    ticket = _ensure_analysis_input_current(ticket, db, source_hash, claim_id)
    ticket.ai_source_hash = source_hash
    ticket.ai_pipeline_version = AI_PIPELINE_VERSION
    ticket.ai_model = _llm_cache_identity()
    complete = bool(ticket.ai_reasoning and ticket.summary and ticket.recommended_solution)
    ticket.ai_status = (
        "partial" if errors else "completed" if complete else "triage_completed"
    )
    error_signature = _analysis_error_signature(errors)
    ticket.ai_error = error_signature or None
    ticket.ai_generated_at = datetime.utcnow()
    ticket.ai_synthetic = db.query(AIArtifactRecord).filter(
        AIArtifactRecord.ticket_id == ticket.id,
        AIArtifactRecord.active.is_(True),
        AIArtifactRecord.synthetic.is_(True),
    ).count() > 0
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    if not errors:
        ticket.ai_attempts = 0
        ticket.ai_next_attempt_at = None
        ticket.ai_requested_artifacts = None
    db.commit()
    await emit("done", "done")

    failed_artifacts = {
        error["step"] for error in errors if error["step"] in artifacts
    }
    if failed_artifacts:
        if failed_artifacts.issubset(capacity_deferrals):
            _defer_ai_capacity(
                db,
                ticket.id,
                failed_artifacts,
                max(capacity_deferrals.values()),
            )
        else:
            _schedule_ai_retry(
                db,
                ticket.id,
                failed_artifacts,
                error_signature,
            )

    if errors and len(requested_artifacts) == 1:
        exc = LLMUnavailableError("AI artifact generation failed")
        setattr(exc, "analysis_claim_id", claim_id)
        raise exc

    return {
        "ticket_id": ticket.id,
        "triage": _triage_result_payload(ticket, analysis_data),
        "summary": summary or ticket.summary,
        "route": route,
        "recommended_solution": {
            "ticket_id": ticket.id,
            "plan": plan_dict,
            "cached": False,
        } if plan_dict else None,
        "documents_changed": documents_changed,
        "errors": errors,
        "cached": False,
    }


@app.post("/tickets/{ticket_id}/triage", response_model=TriageResult)
async def trigger_triage(
    ticket_id: str,
    force: bool = Query(False, description="Regenerate even if current triage is fresh"),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_protected_ai_user),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(_user, ticket)
    _reserve_ai_request(db, _user.id, "triage")

    result = await _run_ticket_analysis(
        ticket, db, force=force, artifacts={"triage"}
    )
    return TriageResult(**result["triage"])


@app.post("/tickets/{ticket_id}/analysis")
async def run_ticket_analysis(
    ticket_id: str,
    force: bool = Query(False, description="Regenerate even when the current analysis is fresh"),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_protected_ai_user),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(_user, ticket)
    _reserve_ai_request(db, _user.id, "full_analysis")
    return await _run_ticket_analysis(ticket, db, force=force)


# ── Authentication ─────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"{PASSWORD_HASH_SCHEME}${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def _is_legacy_sha256_hash(password_hash: str) -> bool:
    return (
        len(password_hash) == 64
        and all(ch in "0123456789abcdef" for ch in password_hash.lower())
    )


def _password_uses_current_hash(password_hash: Optional[str]) -> bool:
    return bool(password_hash and password_hash.startswith(f"{PASSWORD_HASH_SCHEME}$"))


def _verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        # Burn the PBKDF2 cost so unknown-account lookups match known-account
        # failures in response time.
        _dummy_pbkdf2(password)
        return False
    if _is_legacy_sha256_hash(password_hash):
        # Preserve one successful login as a migration path; the caller
        # immediately replaces this legacy hash with PBKDF2. Failed checks do
        # PBKDF2 dummy work so they do not become a cheap timing oracle.
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        verified = hmac.compare_digest(legacy, password_hash)
        if not verified:
            _dummy_pbkdf2(password)
        return verified
    try:
        scheme, iterations_raw, salt, expected = password_hash.split("$", 3)
        if scheme != PASSWORD_HASH_SCHEME:
            _dummy_pbkdf2(password)
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations_raw),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        _dummy_pbkdf2(password)
        return False


def _dummy_pbkdf2(password: str) -> None:
    """Constant-work dummy verification for accounts without a usable hash."""
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        b"tickety-dummy-salt",
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    hmac.compare_digest(digest, digest)


def _cookie_secure() -> bool:
    return settings_module.is_production_mode() or settings_module.get_bool("COOKIE_SECURE")


def _cookie_samesite() -> str:
    value = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def _set_session_cookie(resp: Response, name: str, value: str, max_age: int):
    same_site = _cookie_samesite()
    resp.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure() or same_site == "none",
        samesite=same_site,
    )


def _delete_session_cookie(resp: Response, name: str):
    same_site = _cookie_samesite()
    resp.delete_cookie(
        name,
        secure=_cookie_secure() or same_site == "none",
        samesite=same_site,
    )


def _set_sso_state_cookie(resp: Response, value: str):
    resp.set_cookie(
        SSO_STATE_COOKIE,
        value,
        max_age=sso_service.SSO_TRANSACTION_TTL_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        # The IdP returns through a cross-site top-level GET. Strict would drop
        # the state cookie; None is unnecessary for this redirect flow.
        samesite="lax",
        path="/api/auth/sso",
    )


def _delete_sso_state_cookie(resp: Response):
    resp.delete_cookie(
        SSO_STATE_COOKIE,
        secure=_cookie_secure(),
        samesite="lax",
        path="/api/auth/sso",
    )


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


@app.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    if _login_blocked(payload, request):
        raise HTTPException(status_code=429, detail="Too many failed login attempts")
    email = payload.email.strip().lower()
    user = db.query(UserRecord).filter(func.lower(UserRecord.email) == email).first()
    if not user or not user.is_active:
        # Burn the same PBKDF2 cost as a real verification so response
        # timing cannot be used to enumerate registered email addresses.
        _verify_password(payload.password, None)
        _record_login_failure(payload, request)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _verify_password(payload.password, user.password_hash):
        _record_login_failure(payload, request)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_login_failures(payload, request)
    if not _password_uses_current_hash(user.password_hash):
        user.password_hash = _hash_password(payload.password)
    token = _create_session(db, user.id, request)
    user.last_login_at = datetime.utcnow()
    db.commit()
    resp = JSONResponse({"user": UserOut.model_validate(user).model_dump(mode="json")})
    _set_session_cookie(resp, SESSION_COOKIE, token, SESSION_TTL_DAYS * 86400)
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
    _delete_session_cookie(resp, SESSION_COOKIE)
    return resp


@app.get("/auth/me", response_model=AuthContext)
async def auth_me(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    return {
        **UserOut.model_validate(user).model_dump(mode="json"),
        "auth_kind": (
            "demo_fallback"
            if getattr(request.state, "demo_fallback", False)
            else "session"
        ),
        "app_mode": settings_module.app_mode(),
    }


# ── SSO (OIDC) ──────────────────────────────────────────────────

@app.get("/auth/sso/config")
async def sso_config():
    return JSONResponse(
        sso_service.public_sso_config(),
        headers={"Cache-Control": "no-store"},
    )


def _sso_frontend_redirect(path: str, **params: str) -> str:
    safe_path = "/login" if path == "/login" else sso_service.safe_next_path(path)
    frontend_origin = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    target = f"{frontend_origin}{safe_path}" if frontend_origin else safe_path
    if params:
        separator = "&" if "?" in target else "?"
        target = f"{target}{separator}{urllib.parse.urlencode(params)}"
    return target


def _sso_failure_response(error_code: str, next_path: str = "/") -> RedirectResponse:
    login_params = {"sso_error": error_code}
    safe_next = sso_service.safe_next_path(next_path)
    if safe_next != "/":
        login_params["next"] = safe_next
    response = RedirectResponse(
        url=_sso_frontend_redirect("/login", **login_params),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
    _delete_sso_state_cookie(response)
    return response


def _sso_allowed_email(email: str) -> bool:
    allowed_domains = {
        domain.strip().lower()
        for domain in (os.getenv("SSO_ALLOWED_DOMAINS") or "").split(",")
        if domain.strip()
    }
    if not allowed_domains:
        return True
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    return domain in allowed_domains


def _resolve_sso_user(
    db: Session,
    identity: sso_service.OidcIdentity,
    provider_type: str,
) -> tuple[UserRecord, SsoIdentityRecord]:
    linked = db.query(SsoIdentityRecord).filter(
        SsoIdentityRecord.issuer == identity.issuer,
        SsoIdentityRecord.subject == identity.subject,
    ).first()
    if linked:
        user = db.query(UserRecord).filter(UserRecord.id == linked.user_id).first()
        if not user or not user.is_active:
            raise PermissionError("account_deactivated")
        linked.email_at_link = identity.email
        linked.last_login_at = datetime.utcnow()
        return user, linked

    matching_users = db.query(UserRecord).filter(
        func.lower(UserRecord.email) == identity.email
    ).limit(2).all()
    if len(matching_users) > 1:
        raise PermissionError("identity_conflict")
    user = matching_users[0] if matching_users else None
    if user and not user.is_active:
        raise PermissionError("account_deactivated")
    if not user:
        if not settings_module.get_bool("SSO_AUTO_PROVISION", default=False):
            raise PermissionError("account_not_provisioned")
        import uuid as _uuid

        user = UserRecord(
            id=f"u-{_uuid.uuid4().hex[:8]}",
            email=identity.email,
            name=identity.name or identity.email,
            role="agent",
            is_active=True,
            password_hash="",
        )
        db.add(user)
        db.flush()

    conflicting_link = db.query(SsoIdentityRecord).filter(
        SsoIdentityRecord.user_id == user.id,
        SsoIdentityRecord.issuer == identity.issuer,
    ).first()
    if conflicting_link:
        raise PermissionError("identity_conflict")

    linked = SsoIdentityRecord(
        user_id=user.id,
        provider=provider_type,
        issuer=identity.issuer,
        subject=identity.subject,
        email_at_link=identity.email,
        created_at=datetime.utcnow(),
        last_login_at=datetime.utcnow(),
    )
    db.add(linked)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raced_link = db.query(SsoIdentityRecord).filter(
            SsoIdentityRecord.issuer == identity.issuer,
            SsoIdentityRecord.subject == identity.subject,
        ).first()
        if not raced_link:
            raise PermissionError("identity_conflict")
        raced_user = db.query(UserRecord).filter(
            UserRecord.id == raced_link.user_id,
            UserRecord.is_active.is_(True),
        ).first()
        if not raced_user:
            raise PermissionError("account_deactivated")
        return raced_user, raced_link
    return user, linked


@app.get("/auth/sso/login")
async def sso_login(
    next: str = Query("/", max_length=2048),
    db: Session = Depends(get_db),
):
    next_path = sso_service.safe_next_path(next)
    try:
        config = sso_service.resolve_sso_config()
        metadata = await sso_service.fetch_oidc_metadata(config)
    except sso_service.SsoConfigurationError:
        return _sso_failure_response("configuration_error", next_path)
    except sso_service.SsoProtocolError:
        return _sso_failure_response("provider_unavailable", next_path)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
    now = datetime.utcnow()
    db.query(SsoTransactionRecord).filter(
        SsoTransactionRecord.expires_at <= now
    ).delete(synchronize_session=False)
    db.add(SsoTransactionRecord(
        state_hash=state_hash,
        nonce=nonce,
        code_verifier=code_verifier,
        next_path=next_path,
        provider=config.provider_type,
        discovery_url=config.discovery_url,
        redirect_uri=config.redirect_uri,
        client_id=config.client_id,
        created_at=now,
        expires_at=now + timedelta(seconds=sso_service.SSO_TRANSACTION_TTL_SECONDS),
    ))
    db.commit()
    url = sso_service.build_authorization_url(
        metadata,
        config,
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
    )
    resp = RedirectResponse(
        url=url,
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
    _set_sso_state_cookie(resp, state)
    return resp


@app.get("/auth/sso/callback")
async def sso_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: Optional[str] = Query(None, max_length=4096),
    state: Optional[str] = Query(None, max_length=1024),
    error: Optional[str] = Query(None, max_length=256),
):
    saved_state = request.cookies.get(SSO_STATE_COOKIE)
    if not state or not saved_state or not hmac.compare_digest(saved_state, state):
        return _sso_failure_response("invalid_state")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    transaction = db.query(SsoTransactionRecord).filter(
        SsoTransactionRecord.state_hash == state_hash
    ).with_for_update().first()
    if not transaction or transaction.expires_at <= datetime.utcnow():
        if transaction:
            db.delete(transaction)
            db.commit()
        return _sso_failure_response("expired_request")
    next_path = sso_service.safe_next_path(transaction.next_path)
    transaction_provider = transaction.provider
    transaction_discovery_url = transaction.discovery_url
    transaction_redirect_uri = transaction.redirect_uri
    transaction_client_id = transaction.client_id
    transaction_code_verifier = transaction.code_verifier
    transaction_nonce = transaction.nonce
    db.delete(transaction)
    db.commit()

    if error:
        return _sso_failure_response(
            "access_denied" if error == "access_denied" else "provider_error",
            next_path,
        )
    if not code:
        return _sso_failure_response("provider_error", next_path)

    try:
        config = sso_service.resolve_sso_config()
        if not all((
            transaction_provider == config.provider_type,
            transaction_discovery_url == config.discovery_url,
            transaction_redirect_uri == config.redirect_uri,
            transaction_client_id == config.client_id,
        )):
            return _sso_failure_response("configuration_changed", next_path)
        metadata = await sso_service.fetch_oidc_metadata(config)
        token_payload = await sso_service.exchange_authorization_code(
            metadata,
            config,
            code=code,
            code_verifier=transaction_code_verifier,
        )
        identity = await sso_service.resolve_oidc_identity(
            token_payload,
            metadata,
            config,
            nonce=transaction_nonce,
        )
    except sso_service.SsoConfigurationError:
        return _sso_failure_response("configuration_error", next_path)
    except sso_service.SsoProtocolError:
        return _sso_failure_response("invalid_identity", next_path)

    if not _sso_allowed_email(identity.email):
        return _sso_failure_response("domain_not_allowed", next_path)
    try:
        user, linked_identity = _resolve_sso_user(
            db,
            identity,
            config.provider_type,
        )
    except PermissionError as exc:
        db.rollback()
        code_value = str(exc) if str(exc) in {
            "account_deactivated",
            "account_not_provisioned",
            "identity_conflict",
        } else "access_denied"
        return _sso_failure_response(code_value, next_path)

    token = _create_session(db, user.id, request)
    user.last_login_at = datetime.utcnow()
    linked_identity.last_login_at = datetime.utcnow()
    linked_identity.email_at_link = identity.email
    db.commit()

    resp = RedirectResponse(
        url=_sso_frontend_redirect(next_path),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
    _set_session_cookie(resp, SESSION_COOKIE, token, SESSION_TTL_DAYS * 86400)
    _delete_sso_state_cookie(resp)
    return resp


# ── Ticket intelligence retrieval ─────────────────────────────

_RAG_PROMPT_CHAR_LIMIT = 24_000
_RAG_METADATA_KEYS = (
    "status", "workflow_status", "priority", "category", "ticket_type",
    "created_at", "updated_at", "resolved_at", "tags",
)
_RAG_AUTHORITIES = {
    "published_kb", "internal_comment", "external_report",
    "authenticated_report",
}


def _bounded_rag_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [str(item)[:60] for item in list(value)[:5]]
    return str(value)[:120]


def _rag_json(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def _pack_rag_evidence(
    question: str,
    results: list[dict],
    *,
    max_chars: int,
) -> tuple[str, list[dict], dict[str, dict]]:
    """Pack complete, bounded evidence records without slicing rendered JSON."""
    prompt_payload = redact_data({"question": str(question)[:1_000], "evidence": []})
    packed_context: list[dict] = []
    citations: dict[str, dict] = {}

    for idx, source in enumerate(results, start=1):
        citation_id = f"S{idx}"
        raw_metadata = source.get("metadata") or {}
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        metadata = {
            key: _bounded_rag_value(raw_metadata.get(key))
            for key in _RAG_METADATA_KEYS
            if raw_metadata.get(key) is not None
        }
        authority = source.get("authority")
        if authority not in _RAG_AUTHORITIES:
            authority = "authenticated_report"
        evidence_item = redact_data({
            "citation_id": citation_id,
            "authority": authority,
            "source_type": str(source.get("source_type") or "")[:40],
            "source_id": str(source.get("source_id") or "")[:255],
            "ticket_id": (
                str(source.get("ticket_id"))[:255]
                if source.get("ticket_id") is not None else None
            ),
            "title": str(source.get("title") or "")[:300],
            "metadata": metadata,
            "text": str(source.get("snippet") or "")[:700],
        })
        candidate = {
            **prompt_payload,
            "evidence": [*prompt_payload["evidence"], evidence_item],
        }
        serialized = _rag_json(candidate)
        if len(serialized) > max_chars:
            # Preserve ranking and structural containment. A minimal first
            # record still gives the model evidence when the configured
            # provider prompt limit is unusually small.
            if packed_context:
                break
            evidence_item = {
                **evidence_item,
                "title": evidence_item["title"][:120],
                "text": evidence_item["text"][:240],
                "metadata": {
                    key: value
                    for key, value in evidence_item["metadata"].items()
                    if key in {"status", "priority", "category"}
                },
            }
            candidate = {**prompt_payload, "evidence": [evidence_item]}
            serialized = _rag_json(candidate)
            if len(serialized) > max_chars:
                raise LLMInvalidOutputError("AI evidence cannot fit provider input limit")

        prompt_payload = candidate
        packed_item = {
            "source_type": evidence_item["source_type"],
            "source_id": evidence_item["source_id"],
            "ticket_id": evidence_item["ticket_id"],
            "title": evidence_item["title"],
            "snippet": evidence_item["text"],
            "score": float(source.get("score") or 0.0),
            "match_method": str(source.get("match_method") or "keyword")[:40],
            "citation_id": citation_id,
            "authority": authority,
            "metadata": evidence_item["metadata"],
        }
        # Internal immutable-source identifiers are excluded by the response
        # schema but retained for the digest-bound v2 context snapshot.
        for internal_key in (
            "chunk_id", "content_hash", "parent_hash", "source_revision"
        ):
            if source.get(internal_key) is not None:
                packed_item[internal_key] = str(source[internal_key])
        packed_context.append(packed_item)
        citations[citation_id] = packed_item

    return _rag_json(prompt_payload), packed_context, citations

@app.get("/ticket-intelligence/status")
async def ticket_intelligence_status(
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    return ticket_vectors.ticket_vector_status(db)


@app.post("/ticket-intelligence/backfill")
async def ticket_intelligence_backfill(
    payload: TicketIntelligenceBackfillRequest,
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    _reserve_ai_request(db, _user.id, "ticket_intelligence_backfill")
    return await ticket_vectors.backfill_ticket_documents(
        db,
        limit=payload.limit,
        include_comments=payload.include_comments,
        include_kb=payload.include_kb,
        force=payload.force,
    )


@app.post("/tickets/{ticket_id}/intelligence/refresh")
async def refresh_ticket_intelligence(
    ticket_id: str,
    force: bool = False,
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _reserve_ai_request(db, _user.id, "ticket_intelligence_refresh")
    changed = await ticket_vectors.refresh_ticket_documents(db, ticket, force=force)
    return {"ticket_id": ticket_id, "documents_changed": changed}


@app.get("/ticket-intelligence/search", response_model=TicketIntelligenceSearchResponse)
async def search_ticket_intelligence(
    request: Request,
    q: str = Query(..., min_length=1, max_length=1000),
    limit: int = Query(8, ge=1, le=30),
    _user: UserRecord = Depends(get_protected_ai_user),
    db: Session = Depends(get_db),
):
    allowed_assignee_id = _ticket_scope_assignee_id(_user)
    _reserve_ai_request(db, _user.id, "ticket_intelligence_search")
    return await ticket_vectors.retrieve_ticket_context(
        db,
        q,
        limit=limit,
        include_private_comments=_can_access_private_ai_context(_user),
        allowed_assignee_id=allowed_assignee_id,
    )


@app.post("/ticket-intelligence/analyze", response_model=TicketIntelligenceAnalysisResponse)
async def analyze_ticket_intelligence(
    payload: TicketIntelligenceAnalysisRequest,
    request: Request,
    _user: UserRecord = Depends(get_protected_ai_user),
    db: Session = Depends(get_db),
):
    allowed_assignee_id = _ticket_scope_assignee_id(_user)
    _reserve_ai_request(db, _user.id, "ticket_intelligence")
    retrieval = await ticket_vectors.retrieve_ticket_context(
        db,
        payload.question,
        limit=payload.limit,
        source_types=payload.source_types,
        include_private_comments=_can_access_private_ai_context(_user),
        allowed_assignee_id=allowed_assignee_id,
    )
    # Retrieval is complete; release its read transaction before the LLM call.
    db.rollback()
    retrieved_context = retrieval.get("results", [])
    if not retrieved_context:
        return {
            "question": payload.question,
            "match_method": retrieval.get("match_method", "keyword"),
            "answer": "No matching ticket evidence was found.",
            "findings": [],
            "recommended_actions": [],
            "citations": [],
            "confidence": "low",
            "context": [],
            "grounded_findings": [],
            "grounded_recommended_actions": [],
        }

    prompt, context, allowed_citations = _pack_rag_evidence(
        payload.question,
        retrieved_context,
        max_chars=min(_RAG_PROMPT_CHAR_LIMIT, prompt_char_limit(llm_mgr)),
    )
    snapshot = None
    from .rag.config import read_enabled as rag_v2_read_enabled

    if rag_v2_read_enabled():
        from .rag.snapshots import create_snapshot

        snapshot = create_snapshot(
            db,
            actor_id=str(_user.id),
            actor_role=str(_user.role),
            include_private_comments=_can_access_private_ai_context(_user),
            allowed_assignee_id=allowed_assignee_id,
            query=payload.question,
            embedding_identity=ticket_vectors._embedding_identity(),
            # Persist the exact already-redacted evidence array supplied to
            # the first agent. The second agent reuses these bytes' canonical
            # JSON representation; generated output is never appended.
            packed_evidence=json.loads(prompt)["evidence"],
            citation_allowlist=allowed_citations,
            retrieval_results=retrieved_context,
        )
        if snapshot is None:
            raise RuntimeError(
                "RAG v2 evidence could not be bound to an authorized snapshot"
            )
    result = await llm_mgr.analyze(
        prompt,
        response_model=TicketIntelligenceAnswer,
        system_prompt=RAG_SYSTEM_PROMPT,
        max_tokens=1_200,
    )

    findings = result.get("findings") or []
    try:
        validate_semantic_advice({
            "answer": result.get("answer") or "",
            "findings": findings,
        })
    except UnsafeAIAdviceError as exc:
        raise LLMInvalidOutputError("AI provider returned unsafe ticket advice") from exc

    all_model_citations = [
        *(result.get("answer_citations") or []),
        *[citation for item in findings for citation in item.get("citations", [])],
    ]
    if any(citation not in allowed_citations for citation in all_model_citations):
        raise LLMInvalidOutputError("AI response cited evidence outside the retrieval set")

    def is_published_kb(citation: str) -> bool:
        return allowed_citations[citation]["authority"] == "published_kb"

    # The model does not select or author actions. Approved KB candidates are
    # ranked by retrieval, and Tickety emits only a deterministic review step.
    trusted_action_citations = [
        item["citation_id"]
        for item in context
        if item["authority"] == "published_kb"
    ][:2]
    trusted_actions = [
        {
            "text": (
                "Review and follow the approved knowledge-base guidance in "
                f"citation {citation} before taking action."
            ),
            "citations": [citation],
        }
        for citation in trusted_action_citations
    ]
    grounded_findings = []
    for item in findings:
        grounded_item = dict(item)
        if not all(is_published_kb(citation) for citation in item["citations"]):
            grounded_item["text"] = f"Unverified report — {item['text']}"[:1_000]
        grounded_findings.append(grounded_item)
    citations = list(dict.fromkeys([
        *(result.get("answer_citations") or []),
        *[
            citation
            for item in [*grounded_findings, *trusted_actions]
            for citation in item.get("citations", [])
        ],
    ]))
    answer_citations = result.get("answer_citations") or []
    answer_is_fully_reviewed = bool(answer_citations) and all(
        is_published_kb(citation) for citation in answer_citations
    )
    trusted_answer_sources = {
        (
            allowed_citations[citation]["source_type"],
            allowed_citations[citation]["source_id"],
        )
        for citation in answer_citations
        if answer_is_fully_reviewed
    }
    confidence = result.get("confidence", "low")
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    confidence_cap = 2
    if not trusted_answer_sources:
        confidence_cap = 0
    elif len(trusted_answer_sources) < 2:
        confidence_cap = 1
    confidence = min(
        confidence_rank.get(confidence, 0), confidence_cap
    )
    confidence = ("low", "medium", "high")[confidence]

    answer = result.get("answer") or ""
    if not answer_is_fully_reviewed:
        answer = f"Unverified reports only — {answer}"
    return {
        "question": payload.question,
        "match_method": retrieval.get("match_method", "keyword"),
        "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
        "snapshot_digest": snapshot["snapshot_digest"] if snapshot else None,
        "answer": answer,
        "findings": [item["text"] for item in grounded_findings],
        "recommended_actions": [item["text"] for item in trusted_actions],
        "citations": citations,
        "confidence": confidence,
        "context": context,
        "grounded_findings": grounded_findings,
        "grounded_recommended_actions": trusted_actions,
    }


# ── Users / Agents CRUD (standalone) ───────────────────────────

@app.get("/users", response_model=List[UserOut])
async def list_users(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    return db.query(UserRecord).order_by(UserRecord.name).all()


@app.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    if payload.role == "admin" and _user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create admin users")
    email = payload.email.strip().lower()
    existing = db.query(UserRecord).filter(func.lower(UserRecord.email) == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already in use")
    import uuid as _uuid
    password = payload.password or secrets.token_urlsafe(12)
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = UserRecord(
        id=f"u-{_uuid.uuid4().hex[:8]}",
        name=payload.name,
        email=email,
        title=payload.title,
        role=payload.role,
        password_hash=_hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.password and settings_module.is_demo_mode():
        raise HTTPException(
            status_code=403,
            detail="Password changes are disabled in demo mode",
        )
    if payload.role is not None:
        if _user.role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can change roles")
        if user.id == _user.id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="Admins cannot remove their own admin role")
    if user.role == "admin" and _user.role != "admin":
        if any(
            field is not None
            for field in (payload.password, payload.email, payload.is_active)
        ):
            raise HTTPException(
                status_code=403,
                detail="Only admins can modify admin accounts",
            )
    if payload.is_active is False and user.role == "admin":
        active_admins = db.query(UserRecord).filter(
            UserRecord.role == "admin",
            UserRecord.is_active.is_(True),
            UserRecord.id != user.id,
        ).count()
        if active_admins == 0:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
    if payload.email is not None:
        email = payload.email.strip().lower()
        existing = db.query(UserRecord).filter(
            func.lower(UserRecord.email) == email,
            UserRecord.id != user.id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already in use")
    for field in ["name", "email", "title", "role", "is_active"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(user, field, val.strip().lower() if field == "email" else val)
    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        user.password_hash = _hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@app.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin":
        if _user.role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can deactivate admin users")
        active_admins = db.query(UserRecord).filter(
            UserRecord.role == "admin",
            UserRecord.is_active.is_(True),
            UserRecord.id != user.id,
        ).count()
        if active_admins == 0:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
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
    response: Response,
    db: Session = Depends(get_db),
    search: Optional[str] = Query(default=None, max_length=200),
    category: Optional[str] = Query(default=None, max_length=100),
    status: Optional[str] = Query(default=None, max_length=50),
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: UserRecord = Depends(get_authenticated_user),
):
    if status and status != "published" and user.role not in {"admin", "supervisor"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    q = db.query(KbArticleRecord)
    if status:
        q = q.filter(KbArticleRecord.status == status)
    else:
        q = q.filter(KbArticleRecord.status == "published")
    if category:
        q = q.filter(KbArticleRecord.category == category)
    if search:
        escaped_search = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if escaped_search:
            q = q.filter(KbArticleRecord.title.ilike(f"%{escaped_search}%", escape="\\"))
    page = q.order_by(
        desc(KbArticleRecord.updated_at), KbArticleRecord.id.asc()
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    articles = page[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    author_ids = {article.author_id for article in articles if article.author_id}
    author_names = dict(
        db.query(UserRecord.id, UserRecord.name)
        .filter(UserRecord.id.in_(author_ids))
        .all()
    ) if author_ids else {}
    for a in articles:
        a.__dict__["author_name"] = author_names.get(a.author_id)
    return articles


@app.get("/kb/categories")
async def list_kb_categories(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_authenticated_user),
):
    rows = db.query(KbArticleRecord.category).filter(
        KbArticleRecord.category.isnot(None), KbArticleRecord.status == "published"
    ).distinct().order_by(KbArticleRecord.category.asc()).limit(200).all()
    return {"categories": [r[0] for r in rows if r[0]]}


@app.get("/kb/{article_id}", response_model=KbArticle)
async def get_kb_article(
    article_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
):
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if article.status != "published" and user.role not in {"admin", "supervisor"}:
        raise HTTPException(status_code=404, detail="Article not found")
    article.views += 1
    db.commit()
    db.refresh(article)
    if article.author_id:
        u = db.query(UserRecord).filter(UserRecord.id == article.author_id).first()
        article.__dict__["author_name"] = u.name if u else None
    return article


@app.post("/kb", response_model=KbArticle, status_code=201)
async def create_kb_article(
    payload: KbArticleCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    import uuid as _uuid
    if payload.status == "published":
        raise HTTPException(
            status_code=409,
            detail="Create a draft before independent publication review",
        )
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
        author_id=user.id,
        reviewer_id=None,
        published_at=None,
        review_due_at=payload.review_due_at,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    await ticket_vectors.upsert_kb_document(db, article)
    return article


@app.patch("/kb/{article_id}", response_model=KbArticle)
async def update_kb_article(
    article_id: str,
    payload: KbArticleUpdate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    revision_fingerprint = hashlib.sha256(json.dumps(
        {
            "title": article.title,
            "content": article.content,
            "category": article.category,
            "tags": article.tags,
            "status": article.status,
            "author_id": article.author_id,
            "reviewer_id": article.reviewer_id,
            "version": article.version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    authoring_fields = {"title", "content", "category", "tags"}
    supplied = payload.model_dump(exclude_unset=True)
    authoring_changed = {
        field
        for field in authoring_fields
        if field in supplied
        and supplied[field] is not None
        and getattr(article, field, None) != supplied[field]
    }
    requested_status = payload.status
    publishing = requested_status == "published" and article.status != "published"
    if requested_status == "published" and authoring_changed:
        raise HTTPException(
            status_code=409,
            detail="Save content as draft before independent publication review",
        )
    if publishing and article.author_id and article.author_id == _user.id:
        raise HTTPException(
            status_code=403,
            detail="Knowledge articles require an independent reviewer",
        )
    if publishing and not article.author_id:
        raise HTTPException(
            status_code=409,
            detail="Claim legacy article authorship as draft before review",
        )
    if article.status == "published" and authoring_changed and requested_status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Published content changes must return the article to draft",
        )

    target_status = requested_status if requested_status is not None else article.status
    if authoring_changed and target_status == "published":
        target_status = "draft"
    index_input_changed = bool(
        authoring_changed or target_status != article.status
    )
    if index_input_changed and target_status == "published":
        _reserve_index_write_request(db, _user.id)
    _reserve_embedding_request(
        db,
        _user,
        "kb_update_embedding",
        eligible=index_input_changed and target_status == "published",
    )
    # Quota reservations commit independently. Re-lock and verify the exact
    # revision afterwards so concurrent edits cannot be published under a
    # review that observed different content.
    article = db.query(KbArticleRecord).filter(
        KbArticleRecord.id == article_id
    ).populate_existing().with_for_update().first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    locked_fingerprint = hashlib.sha256(json.dumps(
        {
            "title": article.title,
            "content": article.content,
            "category": article.category,
            "tags": article.tags,
            "status": article.status,
            "author_id": article.author_id,
            "reviewer_id": article.reviewer_id,
            "version": article.version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    if locked_fingerprint != revision_fingerprint:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Knowledge article changed during review; retry from current draft",
        )
    previous_status = article.status
    for field in ["title", "content", "category", "tags", "review_due_at"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(article, field, val)
    article.status = target_status
    if authoring_changed or (article.author_id is None and target_status != "published"):
        article.author_id = _user.id
    if payload.title:
        article.slug = _slugify(payload.title)
    if authoring_changed:
        article.version = (article.version or 1) + 1
    if target_status == "published" and previous_status != "published":
        article.reviewer_id = _user.id
        article.published_at = datetime.utcnow()
    elif target_status != "published":
        article.reviewer_id = None
        article.published_at = None
    db.commit()
    db.refresh(article)
    if index_input_changed:
        await ticket_vectors.upsert_kb_document(db, article)
    return article


@app.delete("/kb/{article_id}")
async def delete_kb_article(
    article_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if ticket_vectors.ticket_vector_store_ready(db):
        db.execute(
            text(
                "DELETE FROM ticket_search_documents "
                "WHERE source_type = 'kb_article' AND source_id = :source_id"
            ),
            {"source_id": article_id},
        )
    db.delete(article)
    db.commit()
    return {"status": "deleted"}


@app.post("/kb/{article_id}/feedback")
async def kb_feedback(
    article_id: str,
    payload: KbFeedbackCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
):
    if (user.role or "").lower() not in {"admin", "supervisor", "agent"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    _reserve_analytics_request(db, user.id)
    article = db.query(KbArticleRecord).filter(KbArticleRecord.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if payload.helpful:
        article.helpful += 1
    else:
        article.not_helpful += 1
    db.commit()
    return {"status": "ok", "helpful": article.helpful, "not_helpful": article.not_helpful}


@app.post("/tickets/{ticket_id}/kb/{article_id}", status_code=201)
async def link_kb_to_ticket(
    ticket_id: str,
    article_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
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
async def get_ticket_kb_links(
    ticket_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(user, ticket)
    links = db.query(TicketLinkRecord).filter(
        TicketLinkRecord.ticket_id == ticket_id
    ).order_by(TicketLinkRecord.id.asc()).offset(offset).limit(limit).all()
    article_ids = [l.kb_article_id for l in links]
    if not article_ids:
        return []
    query = db.query(KbArticleRecord).filter(KbArticleRecord.id.in_(article_ids))
    if (user.role or "").lower() not in {"admin", "supervisor"}:
        query = query.filter(KbArticleRecord.status == "published")
    return query.order_by(KbArticleRecord.id.asc()).limit(limit).all()


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
    terminal = _terminal_status_names(db)
    total = db.query(TicketRecord).count()
    open_t = db.query(TicketRecord).filter(func.lower(TicketRecord.status).notin_(terminal)).count()
    resolved = db.query(TicketRecord).filter(func.lower(TicketRecord.status).in_(terminal)).count()
    breached = db.query(TicketRecord).filter(
        or_(TicketRecord.resolution_due_at < now, TicketRecord.due_by < now),
        func.lower(TicketRecord.status).notin_(terminal),
    ).count()

    resolved_tickets = db.query(TicketRecord).filter(TicketRecord.resolved_at.isnot(None)).all()
    avg_hours = 0.0
    if resolved_tickets:
        durations = []
        for t in resolved_tickets:
            start = t.external_created_at or t.created_at
            end = t.external_resolved_at or t.resolved_at
            if start and end:
                durations.append((end - start).total_seconds())
        if durations:
            avg_hours = round(sum(durations) / len(durations) / 3600, 1)

    escalation_rate = round((db.query(TicketRecord).filter(TicketRecord.status == "Escalated").count() / total * 100), 1) if total else 0.0
    avg_rating = db.query(func.avg(SurveyResponseRecord.rating)).scalar()
    csat = round(float(avg_rating) / 5 * 100, 1) if avg_rating else 0.0

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
    created_col = func.coalesce(TicketRecord.external_created_at, TicketRecord.created_at)
    rows = db.query(
        func.date_trunc("day", created_col).label("day"),
        func.count().label("count"),
    ).filter(created_col >= since).group_by("day").order_by("day").all()
    return {"days": [r.day.isoformat() for r in rows], "counts": [r.count for r in rows]}


@app.get("/reports/by-category")
async def reports_by_category(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    _reserve_analytics_request(db, user.id)
    total_categories = int(db.query(
        func.count(func.distinct(TicketRecord.category))
    ).filter(TicketRecord.category.isnot(None)).scalar() or 0)
    rows = db.query(
        TicketRecord.category, func.count().label("count")
    ).filter(TicketRecord.category.isnot(None)).group_by(
        TicketRecord.category
    ).order_by(func.count().desc()).limit(100).all()
    return {
        "categories": [r.category for r in rows],
        "counts": [r.count for r in rows],
        "total_categories": total_categories,
        "truncated": total_categories > len(rows),
    }


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
            or_(TicketRecord.resolution_due_at < now, TicketRecord.due_by < now),
        ).count()
        compliance = round(((total - breached) / total * 100), 1) if total else 100.0
        result[p] = {"total": total, "breached": breached, "compliance": compliance}
    return result


@app.get("/reports/resolution-time")
async def reports_resolution_time(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Avg resolution time by category."""
    _reserve_analytics_request(db, user.id)
    query = db.query(TicketRecord).filter(
        TicketRecord.resolved_at.isnot(None),
        TicketRecord.category.isnot(None),
    )
    total_matching = query.count()
    rows = query.order_by(TicketRecord.resolved_at.desc()).limit(500).all()
    by_cat = {}
    for t in rows:
        start = t.external_created_at or t.created_at
        end = t.external_resolved_at or t.resolved_at
        if not start or not end:
            continue
        hours = (end - start).total_seconds() / 3600
        cat = t.category
        by_cat.setdefault(cat, []).append(hours)
    return {
        "categories": list(by_cat.keys()),
        "avg_hours": [round(sum(v) / len(v), 1) for v in by_cat.values()],
        "total_matching_tickets": total_matching,
        "analyzed_tickets": len(rows),
        "truncated": total_matching > len(rows),
    }


# ── User / Engagement ────────────────────────────────────────

@app.get("/me", response_model=User)
async def get_current_user_endpoint(user: UserRecord = Depends(get_current_user)):
    return user


@app.get("/users/{user_id}", response_model=User)
async def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_authenticated_user),
):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (_user.role or "").lower() not in {"admin", "supervisor"} and user.id != _user.id:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
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


# ── Freshworks embedded app ──────────────────────────────────

def _embedded_auth_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=401, detail="Freshworks embedded authentication failed")


@app.post("/integrations/freshworks/bootstrap")
def freshworks_bootstrap(
    payload: FreshworksBootstrapRequest,
    response: Response,
    x_tickety_app_secret: Optional[str] = Header(None, alias="X-Tickety-App-Secret"),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        verify_installation_secret(x_tickety_app_secret)
        code, expires_at = issue_bootstrap_code(
            db,
            binding_id=payload.binding_id,
            account_host=payload.account_host,
            external_user_id=payload.external_user_id,
            workspace_id=payload.workspace_id,
            external_ticket_id=payload.external_ticket_id,
            ticket_updated_at=payload.ticket_updated_at,
            audience=payload.audience,
        )
    except (EmbeddedAuthError, BindingValidationError) as exc:
        db.rollback()
        raise _embedded_auth_error(exc) from exc
    return {"code": code, "expires_at": expires_at}


@app.post("/integrations/freshworks/session")
def freshworks_session(
    payload: FreshworksBootstrapRedeem,
    response: Response,
    x_tickety_app_secret: Optional[str] = Header(None, alias="X-Tickety-App-Secret"),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        verify_installation_secret(x_tickety_app_secret)
        token, session = redeem_bootstrap_code(
            db, binding_id=payload.binding_id, code=payload.code
        )
    except EmbeddedAuthError as exc:
        db.rollback()
        raise _embedded_auth_error(exc) from exc
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": session.expires_at,
        "binding_id": session.binding_id,
        "external_ticket_id": session.external_ticket_id,
    }


def _embedded_ticket_context(
    db: Session, authorization: Optional[str], external_ticket_id: str
):
    try:
        principal = authenticate_session(db, authorization)
        require_ticket_scope(principal, external_ticket_id)
    except EmbeddedAuthError as exc:
        db.rollback()
        raise _embedded_auth_error(exc) from exc
    ticket = db.query(TicketRecord).filter(
        TicketRecord.binding_id == principal.binding.id,
        TicketRecord.external_source == "freshservice",
        TicketRecord.external_id == external_ticket_id,
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket has not been synchronized to Tickety")
    return principal, ticket


def _stored_json(value: Optional[str]):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


@app.get("/integrations/freshworks/tickets/{external_ticket_id}")
def freshworks_ticket_context(
    external_ticket_id: str,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    if not external_ticket_id.isdigit():
        raise HTTPException(status_code=404, detail="Ticket not found")
    principal, ticket = _embedded_ticket_context(
        db, authorization, external_ticket_id
    )
    capabilities = {
        row.capability: row.status
        for row in db.query(IntegrationCapabilityRecord).filter(
            IntegrationCapabilityRecord.binding_id == principal.binding.id
        ).all()
    }
    return {
        "binding": {
            "id": principal.binding.id,
            "environment": principal.binding.environment,
            "expires_at": principal.binding.expires_at,
        },
        "actor": {
            "id": principal.external_user.external_id,
            "name": principal.external_user.name,
            "user_type": principal.external_user.user_type,
            "identity_domain": "external_itsm",
        },
        "ticket": {
            "id": ticket.id,
            "external_id": ticket.external_id,
            "subject": ticket.subject,
            "summary": ticket.summary,
            "status": ticket.status,
            "priority": ticket.priority,
            "assignee_id": ticket.assignee_id,
            "external_assignee_id": ticket.external_assignee_id,
            "updated_at": ticket.external_updated_at or ticket.updated_at,
            "recommended_solution": _stored_json(ticket.recommended_solution),
        },
        "capabilities": capabilities,
    }


# ── Sync / Admin ─────────────────────────────────────────────

def _binding_or_404(db: Session, binding_id: str) -> IntegrationBindingRecord:
    binding = get_binding(db, binding_id)
    if not binding:
        raise HTTPException(status_code=404, detail="Integration binding not found")
    return binding


def _sync_adapter_for_binding(
    db: Session, binding_id: Optional[str]
) -> tuple[Any, str]:
    binding = _binding_or_404(db, binding_id) if binding_id else get_active_binding(db)
    if binding:
        if binding.state != "active":
            raise HTTPException(status_code=409, detail="Integration binding is not active")
        if binding.expires_at and binding.expires_at <= datetime.utcnow():
            raise HTTPException(status_code=409, detail="Integration binding has expired")
        return get_adapter(binding=binding), binding.id
    try:
        return get_adapter(), "legacy"
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/admin/integrations/bindings", status_code=201)
def create_integration_binding(
    payload: IntegrationBindingCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    try:
        binding = create_binding(
            db,
            provider=payload.provider,
            environment=payload.environment,
            canonical_account_host=payload.canonical_account_host,
            workspace_ids=payload.workspace_ids,
            installation_id=payload.installation_id,
            product_variant=payload.product_variant,
            credential_reference=payload.credential_reference,
            expires_at=payload.expires_at,
            actor_id=user.id,
        )
    except BindingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Integration binding already exists") from exc
    return serialize_binding(binding)


@app.get("/admin/integrations/bindings")
def list_integration_bindings(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    rows = db.query(IntegrationBindingRecord).order_by(
        IntegrationBindingRecord.created_at.desc()
    ).all()
    return {"bindings": [serialize_binding(row) for row in rows]}


@app.get("/admin/integrations/bindings/{binding_id}/capabilities")
def get_integration_capabilities(
    binding_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    _binding_or_404(db, binding_id)
    return {
        "binding_id": binding_id,
        "capabilities": [
            {
                "capability": row.capability,
                "status": row.status,
                "details": json.loads(row.details or "{}"),
                "checked_at": row.checked_at,
            }
            for row in list_capabilities(db, binding_id)
        ],
    }


@app.post("/admin/integrations/bindings/{binding_id}/validate")
async def validate_integration_binding(
    binding_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    binding = _binding_or_404(db, binding_id)
    try:
        result = await validate_binding(db, binding, actor_id=user.id)
    except BindingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"binding": serialize_binding(binding), **result}


@app.post("/admin/integrations/bindings/{binding_id}/activate")
def activate_integration_binding(
    binding_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    binding = _binding_or_404(db, binding_id)
    try:
        binding = activate_binding(db, binding, actor_id=user.id)
    except BindingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_binding(binding)


@app.post("/admin/integrations/bindings/{binding_id}/suspend")
def suspend_integration_binding(
    binding_id: str,
    payload: IntegrationBindingSuspend,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    binding = _binding_or_404(db, binding_id)
    try:
        binding = suspend_binding(
            db, binding, actor_id=user.id, reason=payload.reason
        )
    except BindingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_binding(binding)

@app.post("/admin/sync/trigger")
def trigger_sync(
    binding_id: Optional[str] = Query(None, max_length=36),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    _reserve_ai_request(db, user.id, "itsm_sync")
    adapter, effective_binding_id = _sync_adapter_for_binding(db, binding_id)
    result = sync_tickets_from_external(adapter, binding_id=effective_binding_id)
    return {"status": "completed", "result": result}


@app.post("/admin/integrations/bindings/{binding_id}/automatic-ai/enable")
def enable_integration_automatic_ai(
    binding_id: str,
    payload: AutomaticAIEnableRequest,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    """Create the binding's first explicit realtime-only automatic-AI boundary."""
    binding = _binding_or_404(db, binding_id)
    if binding.state != "active":
        raise HTTPException(status_code=409, detail="Integration binding is not active")
    capabilities = {
        row.capability: row.status
        for row in db.query(IntegrationCapabilityRecord).filter(
            IntegrationCapabilityRecord.binding_id == binding_id
        ).all()
    }
    missing = [
        capability for capability in ("ticket.read", "conversation.read")
        if capabilities.get(capability) != "supported"
    ]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Automatic AI requires supported capabilities: {', '.join(missing)}",
        )
    try:
        validate_automatic_ai_rollout_evidence(db, binding)
    except BindingValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        state = enable_automatic_ai(
            db,
            binding_id=binding_id,
            provider=binding.provider,
            actor_id=user.id,
            reason=payload.reason,
            expected_generation=payload.expected_generation,
        )
        db.add(IntegrationAuditRecord(
            binding_id=binding_id,
            action="automatic_ai_enabled",
            actor_id=user.id,
            details=json.dumps(
                {
                    "generation": state.automatic_ai_generation,
                    "cutover_at": state.automatic_ai_cutover_at.isoformat(),
                    "lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
                    "reason": payload.reason,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        ))
        db.commit()
        db.refresh(state)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        detail = (
            str(exc)
            if isinstance(exc, ValueError)
            else "automatic_ai_generation_conflict"
        )
        raise HTTPException(status_code=409, detail=detail) from exc
    return {
        "binding_id": binding_id,
        "automatic_ai_enabled": state.automatic_ai_enabled,
        "automatic_ai_generation": state.automatic_ai_generation,
        "automatic_ai_cutover_at": state.automatic_ai_cutover_at,
        "automatic_ai_enabled_at": state.automatic_ai_enabled_at,
        "automatic_ai_lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
    }


@app.post("/admin/integrations/bindings/{binding_id}/automatic-ai/pause")
def pause_integration_automatic_ai(
    binding_id: str,
    payload: AutomaticAIPauseRequest,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    """Emergency stop: revoke in-flight claims without moving the cutover."""
    binding = _binding_or_404(db, binding_id)
    try:
        state, revoked = pause_automatic_ai(
            db,
            binding_id=binding_id,
            provider=binding.provider,
            actor_id=user.id,
            expected_generation=payload.expected_generation,
        )
        db.add(IntegrationAuditRecord(
            binding_id=binding_id,
            action="automatic_ai_paused",
            actor_id=user.id,
            details=json.dumps(
                {
                    "generation": state.automatic_ai_generation,
                    "cutover_at": state.automatic_ai_cutover_at.isoformat(),
                    "reason": payload.reason,
                    "revoked_requests": revoked,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        ))
        db.commit()
        db.refresh(state)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "automatic_ai_pause_conflict"
        raise HTTPException(status_code=409, detail=detail) from exc
    return {
        "binding_id": binding_id,
        "automatic_ai_enabled": state.automatic_ai_enabled,
        "automatic_ai_generation": state.automatic_ai_generation,
        "automatic_ai_cutover_at": state.automatic_ai_cutover_at,
        "automatic_ai_paused_at": state.automatic_ai_paused_at,
        "revoked_requests": revoked,
    }


@app.post("/admin/sync/fetch")
def fetch_sync(
    days: int = Query(7, ge=1, le=365, description="Fetch tickets updated in the last N days"),
    overwrite: bool = Query(False, description="Refresh all provider fields on already-imported tickets"),
    binding_id: Optional[str] = Query(None, max_length=36),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Manual "fetch by days" pull from the ITSM provider.

    Walks every page of tickets updated in the last `days` days while
    respecting the provider's rate limits. Source status is always reconciled
    for already-imported tickets. Other local fields remain unchanged unless
    overwrite=true requests a full provider refresh.
    """
    _reserve_ai_request(db, user.id, "itsm_fetch")
    adapter, effective_binding_id = _sync_adapter_for_binding(db, binding_id)
    result = fetch_tickets_by_days(
        adapter,
        days=days,
        overwrite=overwrite,
        binding_id=effective_binding_id,
    )
    return {"status": "completed", "result": result}


@app.get("/admin/sync/status", response_model=SyncStatus)
async def sync_status(
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    s = get_sync_status()
    return SyncStatus(
        provider=s.get("provider", "none"),
        binding_id=s.get("binding_id"),
        last_synced_at=datetime.fromisoformat(s["last_synced_at"]) if s.get("last_synced_at") else None,
        automatic_ai_enabled=s.get("automatic_ai_enabled", False),
        automatic_ai_generation=s.get("automatic_ai_generation"),
        automatic_ai_cutover_at=(
            datetime.fromisoformat(s["automatic_ai_cutover_at"])
            if s.get("automatic_ai_cutover_at") else None
        ),
        automatic_ai_enabled_at=(
            datetime.fromisoformat(s["automatic_ai_enabled_at"])
            if s.get("automatic_ai_enabled_at") else None
        ),
        automatic_ai_paused_at=(
            datetime.fromisoformat(s["automatic_ai_paused_at"])
            if s.get("automatic_ai_paused_at") else None
        ),
        automatic_ai_lookback_days=s.get(
            "automatic_ai_lookback_days", AUTOMATIC_AI_LOOKBACK_DAYS
        ),
        last_status=s.get("last_status", "idle"),
        last_error="sync_failed" if s.get("last_error") else None,
        total_synced=s.get("total_synced", 0),
    )


# ── Settings ─────────────────────────────────────────────────

@app.post("/admin/sync/agents", deprecated=True)
@app.post("/admin/sync/external-users")
async def sync_external_user_directory(
    binding_id: Optional[str] = Query(None, max_length=36),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Refresh provider-owned profiles without changing Tickety accounts."""
    adapter, effective_binding_id = _sync_adapter_for_binding(db, binding_id)
    result = await async_sync_external_users(
        adapter, binding_id=effective_binding_id
    )
    changed = result.get("created", 0) + result.get("updated", 0) + result.get("deactivated", 0)
    if result.get("errors", 0) and result.get("total", 0) == 0 and not changed:
        status = "failed"
    elif result.get("errors", 0):
        status = "completed_with_errors"
    else:
        status = "completed"
    return {
        "status": status,
        "result": ExternalUserSyncResult(**result).model_dump(mode="json"),
    }


def _external_user_payload(record: ExternalUserRecord) -> dict:
    try:
        profile = json.loads(record.profile_json or "{}")
    except (TypeError, ValueError):
        profile = {}
    if not isinstance(profile, dict):
        profile = {}
    return ExternalUser(
        id=record.id,
        binding_id=record.binding_id,
        provider=record.provider,
        external_id=record.external_id,
        user_type=record.user_type,
        name=record.name,
        email=record.email,
        title=record.title,
        active=record.active,
        profile=profile,
        source_updated_at=record.source_updated_at,
        fetched_at=record.fetched_at,
    ).model_dump(mode="json")


@app.get("/admin/external-users")
async def list_external_users(
    binding_id: Optional[str] = Query(None, max_length=36),
    provider: Optional[str] = Query(None, max_length=64),
    user_type: Optional[str] = Query(None, pattern="^(agent|requester)$"),
    active: Optional[bool] = Query(True),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    query = db.query(ExternalUserRecord)
    if binding_id:
        query = query.filter(ExternalUserRecord.binding_id == binding_id)
    if provider:
        query = query.filter(ExternalUserRecord.provider == provider)
    if user_type:
        query = query.filter(ExternalUserRecord.user_type == user_type)
    if active is not None:
        query = query.filter(ExternalUserRecord.active.is_(active))
    records = query.order_by(
        ExternalUserRecord.user_type, ExternalUserRecord.name, ExternalUserRecord.external_id
    ).all()
    return {"users": [_external_user_payload(record) for record in records]}


@app.get("/admin/agents", deprecated=True)
async def list_external_agents(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    records = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
    ).order_by(ExternalUserRecord.name).all()
    return {"agents": [_external_user_payload(record) for record in records]}


# ── OAuth 2.0 ──────────────────────────────────────────────────

@app.get("/oauth/status")
async def oauth_status(
    _user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    """Return whether OAuth is configured and a token is present."""
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    return {
        "configured": ad.oauth_configured,
        "connected": bool(ad.oauth_access_token),
        "domain": ad.domain,
    }


@app.get("/oauth/authorize")
async def oauth_authorize(
    _user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    """Return the OAuth 2.0 authorization URL for the configured external ITSM provider."""
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    if not ad.oauth_configured:
        raise HTTPException(400, "OAuth client ID and secret not configured")
    state = secrets.token_urlsafe(32)
    resp = JSONResponse({"url": ad.oauth_authorization_url(state)})
    _set_session_cookie(resp, FRESHSERVICE_OAUTH_STATE_COOKIE, state, 600)
    return resp


@app.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[\x21-\x7e]+$",
        description="The authorisation code from the ITSM provider",
    ),
    state: str = Query(
        ...,
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="OAuth state returned by the provider",
    ),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_admin_callback_user),
):
    """Exchange the OAuth code for tokens and persist them."""
    saved_state = request.cookies.get(FRESHSERVICE_OAUTH_STATE_COOKIE)
    if not saved_state or not hmac.compare_digest(saved_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    state_key = f"OAUTH_STATE_USED_{hashlib.sha256(state.encode('ascii')).hexdigest()}"
    try:
        db.add(SettingsRecord(key=state_key, value=str(int(time.time()))))
        db.flush()
        db.query(SettingsRecord).filter(
            SettingsRecord.key.like("OAUTH_STATE_USED_%"),
            SettingsRecord.updated_at < datetime.utcnow() - timedelta(hours=1),
        ).delete(synchronize_session=False)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="OAuth state protection unavailable",
        ) from exc
    _reserve_ai_request(db, user.id, "itsm_oauth_callback")
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    try:
        tokens = await ad.oauth_exchange_code(code)
    except Exception as e:
        print(f"[oauth] token exchange failed kind={type(e).__name__}")
        raise HTTPException(400, "OAuth token exchange failed") from e

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    if not access_token:
        raise HTTPException(400, "No access_token in response")

    # Persist tokens in the database so the adapter picks them up on restart.
    try:
        settings_module.update_settings(
            {
                "FRESHSERVICE_OAUTH_ACCESS_TOKEN": access_token,
                "FRESHSERVICE_OAUTH_REFRESH_TOKEN": refresh_token,
            },
            actor_id=user.id,
        )
    except Exception as exc:
        print(f"[oauth] token persistence failed kind={type(exc).__name__}")
        raise HTTPException(503, "OAuth token persistence failed") from None
    # Also patch env so the current process sees them immediately.
    os.environ["FRESHSERVICE_OAUTH_ACCESS_TOKEN"] = access_token
    os.environ["FRESHSERVICE_OAUTH_REFRESH_TOKEN"] = refresh_token

    resp = JSONResponse({
        "status": "connected",
        "expires_in": tokens.get("expires_in"),
    })
    _delete_session_cookie(resp, FRESHSERVICE_OAUTH_STATE_COOKIE)
    return resp


@app.post("/oauth/refresh")
async def oauth_refresh(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    """Manually refresh the OAuth access token."""
    _reserve_ai_request(db, user.id, "itsm_oauth_refresh")
    from .integrations.registry import get_adapter as _ga
    ad = _ga()
    try:
        tokens = await ad.oauth_refresh()
    except Exception as e:
        print(f"[oauth] token refresh failed kind={type(e).__name__}")
        raise HTTPException(400, "OAuth token refresh failed") from e

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    try:
        settings_module.update_settings(
            {
                "FRESHSERVICE_OAUTH_ACCESS_TOKEN": access_token,
                "FRESHSERVICE_OAUTH_REFRESH_TOKEN": refresh_token,
            },
            actor_id=user.id,
        )
    except Exception as exc:
        print(f"[oauth] token persistence failed kind={type(exc).__name__}")
        raise HTTPException(503, "OAuth token persistence failed") from None
    return {"status": "refreshed", "expires_in": tokens.get("expires_in")}


@app.post("/admin/sync/triage-all")
async def triage_all_untriaged(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Retroactively run AI triage on every ticket that hasn't been analysed yet.
    Useful after enabling auto‑triage or when tickets were imported before
    AI automation was turned on."""
    _reserve_ai_request(db, user.id, "triage_all")
    untriaged = db.query(TicketRecord).filter(
        TicketRecord.ai_reasoning.is_(None),
        or_(
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_status.notin_(["dead_letter", "failed", "running", "queued"]),
        ),
    ).order_by(
        TicketRecord.created_at.asc(), TicketRecord.id.asc()
    ).limit(limit).all()
    for ticket in untriaged:
        ticket.ai_status = "queued"
        ticket.ai_started_at = None
        ticket.ai_error = None
        ticket.ai_next_attempt_at = None
        ticket.ai_requested_artifacts = "triage"
    db.commit()
    return {"status": "queued", "found": len(untriaged), "queued": len(untriaged)}


@app.post("/admin/sync/repair")
async def repair_ai_gaps(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    limit: int = Query(default=100, ge=1, le=500),
):
    """One‑time repair sweep: fill summary and resolution plan gaps for
    tickets that have triage data but are missing the later pipeline steps."""
    _reserve_ai_request(db, user.id, "repair_ai_gaps")
    candidates = db.query(TicketRecord).filter(
        or_(
            and_(TicketRecord.ai_reasoning.isnot(None), TicketRecord.summary.is_(None)),
            and_(
                TicketRecord.ai_reasoning.isnot(None),
                TicketRecord.recommended_solution.is_(None),
            ),
            TicketRecord.ai_status == "legacy_stale",
        ),
        or_(
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_status.notin_(["dead_letter", "failed", "running", "queued"]),
        ),
    ).order_by(
        TicketRecord.updated_at.asc(), TicketRecord.id.asc()
    ).limit(limit).all()
    no_summary = [
        ticket for ticket in candidates
        if ticket.ai_reasoning is not None and ticket.summary is None
    ]
    no_resolution = [
        ticket for ticket in candidates
        if ticket.ai_reasoning is not None and ticket.recommended_solution is None
    ]
    legacy_stale = [ticket for ticket in candidates if ticket.ai_status == "legacy_stale"]
    queued = {ticket.id: ticket for ticket in candidates}
    summary_ids = {ticket.id for ticket in no_summary}
    resolution_ids = {ticket.id for ticket in no_resolution}
    legacy_ids = {ticket.id for ticket in legacy_stale}
    for ticket in queued.values():
        artifacts = []
        if ticket.id in legacy_ids:
            artifacts.extend(["triage", "summary", "resolution"])
        elif ticket.id in summary_ids:
            artifacts.append("summary")
        if ticket.id in resolution_ids and "resolution" not in artifacts:
            artifacts.append("resolution")
        ticket.ai_status = "queued"
        ticket.ai_started_at = None
        ticket.ai_error = None
        ticket.ai_next_attempt_at = None
        ticket.ai_requested_artifacts = ",".join(artifacts)
    db.commit()

    return {
        "status": "queued",
        "found_no_summary": len(no_summary),
        "found_no_resolution": len(no_resolution),
        "found_legacy_stale": len(legacy_stale),
        "queued": len(queued),
    }


@app.get("/admin/settings")
async def get_settings(_user: UserRecord = Depends(require_protected_ai_role("admin"))):
    return settings_module.get_settings()


@app.put("/admin/settings")
async def update_settings(
    payload: dict,
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    try:
        return settings_module.update_settings(payload, actor_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        print(f"[settings] persistence failed kind={type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Settings persistence failed") from None


@app.get("/admin/llm/catalog")
async def llm_catalog(_user: UserRecord = Depends(require_protected_ai_role("admin"))):
    """Return the Foundry catalog, refreshing deployments when stale."""
    await refresh_live_models_if_stale()
    return get_llm_catalog()


@app.get("/admin/llm/metrics")
async def llm_metrics(
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """Prompt-free process and durable 24-hour LLM operational counters."""
    since = datetime.utcnow() - timedelta(days=1)
    rows = db.query(
        LLMCallRecord.status,
        func.count(LLMCallRecord.id),
        func.coalesce(func.sum(LLMCallRecord.total_tokens), 0),
        func.coalesce(func.sum(LLMCallRecord.latency_ms), 0),
    ).filter(LLMCallRecord.created_at >= since).group_by(LLMCallRecord.status).all()
    return {
        "process": get_llm_metrics(),
        "durable_24h": {
            status: {
                "calls": int(calls),
                "total_tokens": int(tokens),
                "latency_ms": int(latency),
            }
            for status, calls, tokens, latency in rows
        },
    }


@app.post("/admin/llm/refresh-models")
async def refresh_models(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    """Immediately refresh Foundry and Custom AI API model catalogs."""
    _reserve_ai_request(db, user.id, "refresh_model_catalog")
    from .llm_manager import fetch_live_models
    results = await fetch_live_models()
    return {
        "status": "completed",
        "providers_queried": list(results.keys()),
        "total_models": sum(len(v) for v in results.values()),
        "results": {k: len(v) for k, v in results.items()},
    }


# ── Intelligence (SupportLogic-style ambient agents) ──────────

_INTELLIGENCE_ROW_LIMIT = 500


def _open_ticket_query(db: Session):
    return db.query(TicketRecord).filter(or_(
        TicketRecord.status.is_(None),
        func.lower(TicketRecord.status).notin_(["closed", "resolved", "cancelled"]),
    ))


def _intelligence_candidate_order():
    return (
        case(
            {"P1": 1, "Urgent": 1, "P2": 2, "High": 2, "P3": 3, "Medium": 3},
            value=TicketRecord.priority,
            else_=4,
        ).asc(),
        TicketRecord.created_at.asc().nullsfirst(),
        TicketRecord.id.asc(),
    )

@app.get("/intelligence/alerts")
async def intel_alerts(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Proactive Alert Agent: unified feed of cases needing attention now."""
    _reserve_analytics_request(db, _user.id)
    return intel.proactive_alerts(db)


@app.get("/intelligence/prioritize")
async def intel_prioritize(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Prioritization Agent: open backlog ranked by composite urgency/impact/risk."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    open_query = _open_ticket_query(db)
    total_open = open_query.count()
    open_tickets = open_query.order_by(
        *_intelligence_candidate_order()
    ).limit(_INTELLIGENCE_ROW_LIMIT).all()
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
    return {
        "generated_at": now.isoformat(),
        "backlog_size": total_open,
        "analyzed_tickets": len(open_tickets),
        "truncated": total_open > len(open_tickets),
        "ranked": ranked,
    }


@app.get("/intelligence/sla")
async def intel_sla(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """SLA Agent: SLA clock state for every open ticket."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    open_query = _open_ticket_query(db)
    total_open = open_query.count()
    candidates = open_query.order_by(
        *_intelligence_candidate_order()
    ).limit(_INTELLIGENCE_ROW_LIMIT).all()
    rows = [intel.sla_status(ticket, now) for ticket in candidates]
    rows.sort(key=lambda r: r["remaining_hours"])
    return {
        "generated_at": now.isoformat(),
        "count": total_open,
        "analyzed_tickets": len(candidates),
        "truncated": total_open > len(candidates),
        "items": rows,
    }


@app.get("/intelligence/trends")
async def intel_trends(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Text Analytics Agent: category/sentiment distribution + top terms."""
    _reserve_analytics_request(db, _user.id)
    return intel.trends(db)


@app.get("/intelligence/systemic")
async def intel_systemic(
    db: Session = Depends(get_db),
    min_cluster: int = Query(2, ge=2, le=20, description="Minimum tickets to flag as a systemic issue"),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Systemic Issue Detection: cluster similar tickets and surface broad
    business‑impact patterns. Returns clusters ranked by impact score, each
    with shared keywords, sample tickets, and priority/risk stats."""
    _reserve_analytics_request(db, _user.id)
    return intel.systemic_issues(db, cluster_threshold=min_cluster)


@app.get("/intelligence/workload")
async def agent_workload(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Agent workload: open tickets per agent + resolution metrics."""
    _reserve_analytics_request(db, _user.id)
    total_users = db.query(UserRecord).count()
    users = db.query(UserRecord).order_by(
        UserRecord.tier.desc(),
        UserRecord.impact_points.desc(),
        UserRecord.id.asc(),
    ).limit(
        _INTELLIGENCE_ROW_LIMIT
    ).all()
    user_ids = [user.id for user in users]
    open_counts = dict(db.query(
        TicketRecord.resolved_by,
        func.count(TicketRecord.id),
    ).filter(
        TicketRecord.resolved_by.in_(user_ids),
        TicketRecord.status.notin_(["Closed", "Resolved"]),
    ).group_by(TicketRecord.resolved_by).all()) if user_ids else {}
    resolved_counts = dict(db.query(
        TicketRecord.resolved_by,
        func.count(TicketRecord.id),
    ).filter(
        TicketRecord.resolved_by.in_(user_ids),
    ).group_by(TicketRecord.resolved_by).all()) if user_ids else {}
    duration_query = db.query(
        TicketRecord.resolved_by,
        TicketRecord.resolved_at,
        TicketRecord.created_at,
    ).filter(
        TicketRecord.resolved_by.in_(user_ids),
        TicketRecord.resolved_at.isnot(None),
        TicketRecord.created_at.isnot(None),
    )
    total_duration_rows = duration_query.count() if user_ids else 0
    resolved_rows = duration_query.order_by(
        TicketRecord.resolved_at.desc()
    ).limit(5_000).all() if user_ids else []
    duration_totals: dict[str, tuple[float, int]] = {}
    for resolved_by, resolved_at, created_at in resolved_rows:
        total_seconds, count = duration_totals.get(resolved_by, (0.0, 0))
        duration_totals[resolved_by] = (
            total_seconds + (resolved_at - created_at).total_seconds(),
            count + 1,
        )
    result = []
    for u in users:
        avg_hours = 0.0
        if u.id in duration_totals:
            total_seconds, duration_count = duration_totals[u.id]
            avg_hours = round(total_seconds / duration_count / 3600, 1)
        result.append({
            "user_id": u.id,
            "name": u.name,
            "open_tickets": int(open_counts.get(u.id, 0)),
            "total_resolved": int(resolved_counts.get(u.id, 0)),
            "avg_resolution_hours": avg_hours,
            "impact_points": u.impact_points,
            "tier": u.tier,
        })
    result.sort(key=lambda r: r["open_tickets"], reverse=True)
    return {
        "agents": result,
        "total_users": total_users,
        "analyzed_users": len(users),
        "users_truncated": total_users > len(users),
        "duration_rows_analyzed": len(resolved_rows),
        "duration_rows_truncated": total_duration_rows > len(resolved_rows),
    }

@app.get("/intelligence/health/{reporter}")
async def intel_health(
    reporter: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Account Health Agent: per-reporter health score + churn-risk band."""
    if len(reporter) > 320:
        raise HTTPException(status_code=422, detail="Reporter identifier is too long")
    _reserve_analytics_request(db, _user.id)
    result = intel.account_health(db, reporter)
    if result["health_score"] is None:
        raise HTTPException(status_code=404, detail="No tickets for that reporter")
    return result


@app.get("/intelligence/route/{ticket_id}")
async def intel_route(
    ticket_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_protected_ai_user),
):
    """Routing Agent: recommend the best engineer for a ticket."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(_user, ticket)
    _reserve_analytics_request(db, _user.id)
    return intel.recommend_assignee(db, ticket)


@app.post("/tickets/{ticket_id}/summary")
async def ticket_summary(
    ticket_id: str,
    force: bool = Query(False, description="Regenerate even if a cached summary exists"),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_protected_ai_user),
):
    """Summarization Agent: LLM-generated case summary (cached on the ticket)."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(_user, ticket)
    _reserve_ai_request(db, _user.id, "summary")
    result = await _run_ticket_analysis(
        ticket, db, force=force, artifacts={"summary"}
    )
    return {"ticket_id": ticket.id, "summary": result["summary"]}


@app.post("/intelligence/resolve/{ticket_id}", response_model=RecommendedSolution)
async def ticket_resolve(
    ticket_id: str,
    force: bool = Query(False, description="Regenerate even if a cached plan exists"),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_protected_ai_user),
):
    """Resolution Agent: LLM-generated resolution plan the assigned engineer can
    follow. Cached on the ticket as `recommended_solution` (JSON string). Pass
    force=true to regenerate."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(_user, ticket)
    _reserve_ai_request(db, _user.id, "resolution")
    result = await _run_ticket_analysis(
        ticket, db, force=force, artifacts={"resolution"}
    )
    recommended = result.get("recommended_solution")
    if not recommended or not recommended.get("plan"):
        raise LLMInvalidOutputError("Resolution artifact was not generated")
    plan_dict = ResolutionAnalysis.model_validate(recommended["plan"]).model_dump()
    return RecommendedSolution(
        ticket_id=ticket.id,
        plan=ResolutionPlan(**plan_dict),
        cached=bool(result.get("cached") or recommended.get("cached")),
    )


# ── Webhooks ─────────────────────────────────────────────────

_WEBHOOK_DELIVERY_PREFIX = "WEBHOOK_DELIVERY_"


def _claim_webhook_delivery(
    request: Request, raw_body: bytes, binding_id: str = "legacy"
) -> str:
    """Atomically reject duplicate signed deliveries without retaining payloads."""
    timestamp = (request.headers.get("x-freshservice-webhook-timestamp") or "").strip()
    signature = (request.headers.get("x-freshservice-webhook-signature") or "").strip()
    digest = hashlib.sha256(
        binding_id.encode("ascii") + b"\0" + timestamp.encode("ascii")
        + b"\0" + signature.encode("ascii") + b"\0" + raw_body
    ).hexdigest()
    key = f"{_WEBHOOK_DELIVERY_PREFIX}{digest}"
    db = SessionLocal()
    try:
        db.add(SettingsRecord(
            key=key, value=f"claimed:{int(time.time())}"
        ))
        db.flush()
        max_age = _bounded_env_int("WEBHOOK_MAX_AGE_SECONDS", 300, 30, 3600)
        db.query(SettingsRecord).filter(
            SettingsRecord.key.like(f"{_WEBHOOK_DELIVERY_PREFIX}%"),
            SettingsRecord.updated_at
            < datetime.utcnow() - timedelta(seconds=max_age * 2),
        ).delete(synchronize_session=False)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate webhook delivery") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Webhook replay protection unavailable"
        ) from exc
    finally:
        db.close()
    return key


def _complete_webhook_delivery(key: str) -> None:
    db = SessionLocal()
    try:
        changed = db.query(SettingsRecord).filter(
            SettingsRecord.key == key,
            SettingsRecord.value.like("claimed:%"),
        ).update(
            {
                SettingsRecord.value: f"completed:{int(time.time())}",
                SettingsRecord.updated_at: datetime.utcnow(),
            },
            synchronize_session=False,
        )
        if changed != 1:
            raise RuntimeError("webhook delivery claim is unavailable")
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Webhook replay protection unavailable"
        ) from exc
    finally:
        db.close()


def _release_webhook_delivery(key: str) -> None:
    db = SessionLocal()
    try:
        db.query(SettingsRecord).filter(
            SettingsRecord.key == key,
            SettingsRecord.value.like("claimed:%"),
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Webhook replay protection unavailable"
        ) from exc
    finally:
        db.close()

async def _process_freshservice_webhook(
    request: Request, binding: Optional[IntegrationBindingRecord] = None
):
    raw_body = await request.body()
    binding_id = binding.id if binding else "legacy"
    adapter = get_adapter(binding=binding) if binding else get_adapter("freshservice")
    request_headers = dict(request.headers)
    if not adapter.verify_webhook_signature(request_headers, raw_body):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    event = adapter.parse_verified_webhook(payload)
    if not event:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    delivery_key = _claim_webhook_delivery(request, raw_body, binding_id)
    try:
        ticket = await asyncio.to_thread(
            handle_webhook_event,
            event,
            adapter,
            binding_id=binding_id,
        )
        if not ticket:
            raise RuntimeError("webhook event was not applied")
        db = SessionLocal()
        try:
            current_ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket.id).first()
            if current_ticket:
                # The webhook is only a hint. Automatic AI eligibility was
                # decided from the authoritative refetch and immutable
                # cutover evidence inside handle_webhook_event.
                await _check_resolution_and_award(current_ticket, db=db)
        finally:
            db.close()
    except Exception as exc:
        _release_webhook_delivery(delivery_key)
        print(f"[webhook] processing failed kind={type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Webhook processing failed") from exc
    _complete_webhook_delivery(delivery_key)
    return {"status": "received", "ticket_id": ticket.id if ticket else None}


@app.post("/webhooks/external")
async def freshservice_webhook(request: Request):
    return await _process_freshservice_webhook(request)


@app.post("/webhooks/external/{binding_id}")
async def freshservice_binding_webhook(
    binding_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    binding = _binding_or_404(db, binding_id)
    if binding.provider != "freshservice" or binding.state != "active":
        raise HTTPException(status_code=404, detail="Integration binding not found")
    if binding.expires_at and binding.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=410, detail="Integration binding expired")
    return await _process_freshservice_webhook(request, binding)


# ── Resolution & Points Awarding ─────────────────────────────

async def _check_resolution_and_award(ticket: TicketRecord, db: Optional[Session] = None):
    """Check if a ticket transitioned to Closed and award points to the assignee."""
    owns_db = db is None
    db = db or SessionLocal()
    ticket = db.query(TicketRecord).filter(
        TicketRecord.id == ticket.id
    ).populate_existing().with_for_update().first()
    if not ticket:
        if owns_db:
            db.close()
        return
    if ticket.external_status and ticket.external_status.lower() not in ("closed", "resolved"):
        if owns_db:
            db.close()
        return
    if ticket.points_awarded_sent:
        if owns_db:
            db.close()
        return
    try:
        # Only an explicitly assigned Tickety account can receive local points.
        # Provider identities are deliberately not mapped into this user domain.
        if not ticket.assignee_id:
            return
        user = db.query(UserRecord).filter(UserRecord.id == ticket.assignee_id).first()
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
        ticket.resolved_at = ticket.external_resolved_at or ticket.resolved_at or datetime.utcnow()
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
        print(f"[award] error kind={type(e).__name__}")
        db.rollback()
    finally:
        if owns_db:
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
    service_ids = {request.service_item_id for request in reqs if request.service_item_id}
    service_names = {
        service.id: service.name
        for service in db.query(ServiceItemRecord).filter(ServiceItemRecord.id.in_(service_ids)).all()
    } if service_ids else {}
    for request in reqs:
        request.__dict__["service_name"] = service_names.get(request.service_item_id)
    return reqs


@app.post("/service-requests", response_model=ServiceRequest, status_code=201)
async def create_service_request(payload: ServiceRequestCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    ticket = db.query(TicketRecord).filter(TicketRecord.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    service = db.query(ServiceItemRecord).filter(
        ServiceItemRecord.id == payload.service_item_id,
        ServiceItemRecord.is_active.is_(True),
    ).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service item not found")
    existing = db.query(ServiceRequestRecord).filter(ServiceRequestRecord.ticket_id == payload.ticket_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ticket already has a service request")
    approval_status = "pending" if service.approval_required else "not_required"
    sr = ServiceRequestRecord(
        id=f"sr-{_uuid.uuid4().hex[:8]}",
        approval_status=approval_status,
        fulfillment_status="pending",
        **payload.model_dump(),
    )
    ticket.ticket_type = "request"
    ticket.service_id = service.id
    ticket.workflow_status = "Pending Approval" if service.approval_required else "Pending Fulfillment"
    ticket.status = ticket.workflow_status
    if service.sla_hours:
        started_at = ticket.created_at or datetime.utcnow()
        ticket.resolution_due_at = started_at + timedelta(hours=service.sla_hours)
        ticket.due_by = ticket.resolution_due_at
    db.add(sr)
    db.commit()
    db.refresh(sr)
    return sr


@app.patch("/service-requests/{request_id}/approval", response_model=ServiceRequest)
async def decide_service_request_approval(
    request_id: str,
    payload: ServiceRequestApprovalDecision,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    sr = db.query(ServiceRequestRecord).filter(ServiceRequestRecord.id == request_id).first()
    if not sr:
        raise HTTPException(status_code=404, detail="Service request not found")
    ticket = db.query(TicketRecord).filter(TicketRecord.id == sr.ticket_id).first()
    if sr.approval_status == "not_required":
        raise HTTPException(status_code=400, detail="Approval is not required for this request")
    if sr.approval_status in {"approved", "rejected"}:
        raise HTTPException(status_code=409, detail="Service request approval already decided")
    sr.approval_status = payload.decision
    sr.approved_by = user.id
    sr.approved_at = datetime.utcnow()
    if payload.comment:
        sr.delivery_notes = payload.comment
    if payload.decision == "approved":
        sr.fulfillment_status = "pending"
        if ticket:
            ticket.workflow_status = "Pending Fulfillment"
            ticket.status = ticket.workflow_status
    else:
        sr.fulfillment_status = "cancelled"
        if ticket:
            ticket.workflow_status = "Request Rejected"
            ticket.status = ticket.workflow_status
    db.commit()
    db.refresh(sr)
    return sr


@app.patch("/service-requests/{request_id}/fulfillment", response_model=ServiceRequest)
async def update_service_request_fulfillment(
    request_id: str,
    payload: ServiceRequestFulfillmentUpdate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    sr = db.query(ServiceRequestRecord).filter(ServiceRequestRecord.id == request_id).first()
    if not sr:
        raise HTTPException(status_code=404, detail="Service request not found")
    if sr.approval_status == "pending":
        raise HTTPException(status_code=400, detail="Service request must be approved before fulfillment")
    if sr.approval_status == "rejected":
        raise HTTPException(status_code=400, detail="Rejected service requests cannot be fulfilled")
    ticket = db.query(TicketRecord).filter(TicketRecord.id == sr.ticket_id).first()
    sr.fulfillment_status = payload.status
    sr.delivery_notes = payload.delivery_notes or sr.delivery_notes
    if payload.status == "fulfilled":
        sr.fulfilled_by = user.id
        sr.fulfilled_at = datetime.utcnow()
        if ticket:
            ticket.workflow_status = "Resolved"
            ticket.status = "Resolved"
            ticket.resolved_at = ticket.resolved_at or datetime.utcnow()
    else:
        if ticket:
            ticket.workflow_status = "Request Cancelled"
            ticket.status = ticket.workflow_status
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
    if payload.status and payload.status in ("Resolved", "Closed"):
        if not problem.root_cause:
            raise HTTPException(status_code=400, detail="Root cause is required before closing a problem")
        if not (problem.resolution or problem.workaround):
            raise HTTPException(status_code=400, detail="Resolution or workaround is required before closing a problem")
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
async def get_problem_tickets(
    problem_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    links = db.query(ProblemTicketLinkRecord).filter(ProblemTicketLinkRecord.problem_id == problem_id).all()
    ticket_ids = [l.ticket_id for l in links]
    if not ticket_ids:
        return []
    query = db.query(TicketRecord).filter(TicketRecord.id.in_(ticket_ids))
    if allowed_assignee_id is not None:
        query = query.filter(or_(
            TicketRecord.assignee_id.is_(None),
            TicketRecord.assignee_id == allowed_assignee_id,
        ))
    return [_ticket_for_request(request, ticket) for ticket in query.all()]


# ── Change Management ──────────────────────────────────────────

_CHANGE_STATUSES = {
    "Draft", "Submitted", "CAB Review", "Approved", "In Progress",
    "Completed", "Rejected", "Cancelled",
}
_CHANGE_APPROVAL_REQUIRED_STATUSES = {"Approved", "In Progress", "Completed"}


def _change_approval_summary(db: Session, change_id: str) -> tuple[int, int, int]:
    approvals = db.query(ChangeApprovalRecord).filter(ChangeApprovalRecord.change_id == change_id).all()
    approved = sum(1 for a in approvals if a.decision == "approved")
    rejected = sum(1 for a in approvals if a.decision == "rejected")
    pending = sum(1 for a in approvals if not a.decision or a.decision == "pending")
    return approved, rejected, pending


def _validate_change_window(start: Optional[datetime], end: Optional[datetime]):
    if start and end and end <= start:
        raise HTTPException(status_code=400, detail="Scheduled end must be after scheduled start")


def _validate_change_status(status: Optional[str]):
    if status and status not in _CHANGE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid change status")


def _ensure_change_ready_for_execution(change: ChangeRecord):
    if not change.scheduled_start or not change.scheduled_end:
        raise HTTPException(status_code=400, detail="Scheduled start and end are required")
    _validate_change_window(change.scheduled_start, change.scheduled_end)
    if not change.rollback_plan:
        raise HTTPException(status_code=400, detail="Rollback plan is required")
    if not change.test_plan:
        raise HTTPException(status_code=400, detail="Test plan is required")


def _ensure_change_transition_allowed(db: Session, change: ChangeRecord, target_status: Optional[str]):
    if not target_status or target_status == change.status:
        return
    _validate_change_status(target_status)
    approved, rejected, _pending = _change_approval_summary(db, change.id)
    if rejected and target_status in _CHANGE_APPROVAL_REQUIRED_STATUSES:
        raise HTTPException(status_code=400, detail="Rejected changes cannot move forward")
    if target_status in _CHANGE_APPROVAL_REQUIRED_STATUSES and approved == 0:
        raise HTTPException(status_code=400, detail="At least one CAB approval is required")
    if target_status in _CHANGE_APPROVAL_REQUIRED_STATUSES:
        _ensure_change_ready_for_execution(change)


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
async def create_change(
    payload: ChangeCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    import uuid as _uuid
    _validate_change_status(payload.status)
    _validate_change_window(payload.scheduled_start, payload.scheduled_end)
    if payload.status in _CHANGE_APPROVAL_REQUIRED_STATUSES:
        raise HTTPException(status_code=400, detail="CAB approval is required before this status")
    change = ChangeRecord(
        id=f"chg-{_uuid.uuid4().hex[:8]}",
        requested_by=user.id,
        **payload.model_dump(),
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    return change


@app.patch("/changes/{change_id}", response_model=ChangeRecordOut)
async def update_change(
    change_id: str,
    payload: ChangeUpdate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    change = db.query(ChangeRecord).filter(ChangeRecord.id == change_id).first()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    for field in ["title", "description", "status", "change_type", "priority", "risk_level",
                   "impact", "rollback_plan", "test_plan", "scheduled_start", "scheduled_end",
                   "assigned_to"]:
        val = getattr(payload, field, None)
        if val is not None and field != "status":
            setattr(change, field, val)
    _validate_change_window(change.scheduled_start, change.scheduled_end)
    _ensure_change_transition_allowed(db, change, payload.status)
    if payload.status is not None:
        change.status = payload.status
    if payload.status and payload.status == "Completed" and not change.completed_at:
        change.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(change)
    return change


@app.delete("/changes/{change_id}")
async def delete_change(
    change_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
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
async def add_change_approval(
    change_id: str,
    payload: ChangeApprovalCreate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    change = db.query(ChangeRecord).filter(ChangeRecord.id == change_id).first()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    approver = db.query(UserRecord).filter(UserRecord.id == payload.approver_id, UserRecord.is_active.is_(True)).first()
    if not approver:
        raise HTTPException(status_code=404, detail="Approver not found")
    if change.requested_by and change.requested_by == payload.approver_id:
        raise HTTPException(status_code=400, detail="Requester cannot approve their own change")
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
async def decide_approval(
    change_id: str,
    approver_id: str,
    payload: Optional[ChangeApprovalDecision] = None,
    decision: Optional[str] = None,
    comment: Optional[str] = None,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    change = db.query(ChangeRecord).filter(ChangeRecord.id == change_id).first()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    approval = None
    if approver_id.isdigit():
        approval = db.query(ChangeApprovalRecord).filter(
            ChangeApprovalRecord.change_id == change_id,
            ChangeApprovalRecord.id == int(approver_id),
        ).first()
    if not approval:
        approval = db.query(ChangeApprovalRecord).filter(
            ChangeApprovalRecord.change_id == change_id, ChangeApprovalRecord.approver_id == approver_id
        ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if user.role != "admin" and approval.approver_id != user.id:
        raise HTTPException(status_code=403, detail="Only the assigned approver or an admin can decide")
    if change.requested_by == user.id and approval.approver_id == user.id:
        raise HTTPException(status_code=400, detail="Requester cannot approve their own change")
    selected_decision = payload.decision if payload else decision
    selected_comment = payload.comment if payload else (comment or "")
    if selected_decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Decision must be approved or rejected")
    approval.decision = selected_decision
    approval.comment = selected_comment
    approval.decided_at = datetime.utcnow()
    db.flush()
    approved, rejected, pending = _change_approval_summary(db, change_id)
    if rejected:
        change.status = "Rejected"
    elif approved and pending == 0 and change.status in {"Draft", "Submitted", "CAB Review"}:
        try:
            _ensure_change_ready_for_execution(change)
            change.status = "Approved"
        except HTTPException:
            change.status = "CAB Review"
    db.commit()
    return {"status": "ok", "decision": selected_decision, "change_status": change.status}


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


@app.get("/assets/stats")
async def asset_stats(db: Session = Depends(get_db)):
    total = db.query(AssetRecord).count()
    by_type = {}
    for row in db.query(AssetRecord.asset_type, func.count()).group_by(AssetRecord.asset_type).all():
        by_type[row[0]] = row[1]
    return {"total": total, "by_type": by_type}


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
    _reserve_survey_response_request(db, survey_id)
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
async def create_time_entry(
    payload: TimeEntryCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    entry = TimeEntryRecord(
        ticket_id=payload.ticket_id,
        user_id=user.id,
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

@app.post("/portal/tickets", response_model=PortalTicketCreated, status_code=201)
async def portal_create_ticket(
    payload: PortalTicketCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _require_demo_ticketing()
    import uuid as _uuid
    reporter = _normalize_portal_reporter(payload.reporter)
    _reserve_portal_ticket_request(db, reporter)
    access_token = secrets.token_urlsafe(PORTAL_ACCESS_TOKEN_BYTES)
    access_expires_at = datetime.utcnow() + _portal_token_ttl()
    ticket = TicketRecord(
        id=f"portal-{_uuid.uuid4().hex}",
        subject=payload.subject.strip(),
        description=payload.description,
        reporter=reporter,
        status="New",
        workflow_status="New",
        priority=_normalize_portal_priority(payload.priority),
        ticket_type="incident",
        external_source="portal",
        portal_access_token_hash=_portal_token_digest(access_token),
        portal_access_expires_at=access_expires_at,
    )
    _apply_sla_targets(ticket, db)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    response.headers["Cache-Control"] = "no-store"
    return PortalTicketCreated(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        access_token=access_token,
        tracking_url=_portal_tracking_url(request, access_token),
        access_expires_at=access_expires_at,
    )


@app.get("/portal/tickets", response_model=PortalTicketOut)
async def portal_list_tickets(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    ticket = _portal_ticket_for_token(db, _portal_bearer_token(request))
    if not ticket:
        # Missing, malformed, unknown, expired, and legacy tickets share one
        # response so this public endpoint cannot be used for enumeration.
        raise HTTPException(status_code=404, detail="Tracking link is invalid or expired")
    return ticket


def _websocket_user(ws: WebSocket) -> Optional[UserRecord]:
    db = SessionLocal()
    try:
        token = ws.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        session = db.query(SessionRecord).filter(SessionRecord.token == token).first()
        if not session or (session.expires_at and session.expires_at <= datetime.utcnow()):
            return None
        user = db.query(UserRecord).filter(UserRecord.id == session.user_id).first()
        return user if user and user.is_active else None
    finally:
        db.close()


def _websocket_origin_allowed(ws: WebSocket) -> bool:
    origin = (ws.headers.get("origin") or "").strip().rstrip("/")
    if not origin:
        return False
    parsed = urllib.parse.urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    allowed = {
        value.rstrip("/") for value in _cors_allow_origins() if value != "*"
    }
    if origin in allowed:
        return True
    # Production WebSockets never trust Host-header or forwarded-header
    # origins; the reviewed deployment must declare every browser origin.
    if settings_module.is_production_mode():
        return False
    # Demo mode: the browser's Origin must match the Host it connected to.
    # Forwarding headers are only honored when the deployment explicitly
    # confirms its proxy overwrites them.
    if settings_module.get_bool("TRUST_FORWARDED_HEADERS"):
        forwarded_host = (ws.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        forwarded_proto = (ws.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    else:
        forwarded_host = forwarded_proto = ""
    host = forwarded_host or (ws.headers.get("host") or "").strip()
    if host and origin == f"{forwarded_proto or 'https'}://{host}".rstrip("/"):
        return True
    return False


@app.websocket("/ws/tickets/{ticket_id}/stream")
async def ws_ticket_stream(ws: WebSocket, ticket_id: str):
    if not _websocket_origin_allowed(ws):
        await ws.close(code=1008)
        return
    ws_user = _websocket_user(ws)
    if not ws_user:
        await ws.close(code=1008)
        return
    if settings_module.is_demo_mode() and (ws_user.role or "").lower() != "admin":
        await ws.close(code=1008)
        return
    await ws.accept()
    db = SessionLocal()
    try:
        ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
        if not ticket:
            await ws.send_json({"error": "Ticket not found"})
            await ws.close()
            return
        if ws_user:
            try:
                _authorize_ticket_analysis(ws_user, ticket)
            except HTTPException:
                await ws.send_json({"type": "error", "message": "Insufficient ticket analysis permission"})
                await ws.close(code=1008)
                return
        _reserve_ai_request(db, ws_user.id if ws_user else "demo-websocket", "full_analysis")

        steps = [
            {"step": "reading", "label": "Reading ticket details...", "status": "done"},
            {"step": "triage", "label": "Triaging sentiment, category, priority...", "status": "pending"},
            {"step": "summary", "label": "Generating case summary...", "status": "pending"},
            {"step": "route", "label": "Recommending engineer route...", "status": "pending"},
            {"step": "resolution", "label": "Drafting resolution plan...", "status": "pending"},
            {"step": "refresh", "label": "Refreshing ticket intelligence...", "status": "pending"},
            {"step": "done", "label": "Analysis complete", "status": "pending"},
        ]

        def progress_payload() -> dict:
            return {
                "type": "progress",
                "steps": steps,
                "timeout_seconds": _analysis_pipeline_timeout_seconds(),
            }

        await ws.send_json(progress_payload())

        async def report_progress(step_name: str, status: str):
            for item in steps:
                if item["step"] == step_name:
                    item["status"] = status
                    break
            await ws.send_json(progress_payload())

        result = await _run_ticket_analysis(ticket, db, progress=report_progress)

        await ws.send_json({"type": "complete", "result": result})
        await ws.close()
    except WebSocketDisconnect:
        pass
    except Exception:
        await ws.send_json({"type": "error", "message": "Analysis could not be completed"})
        await ws.close()
    finally:
        db.close()


@app.websocket("/ws/notifications")
async def ws_notifications(ws: WebSocket):
    ws_user = _websocket_user(ws)
    if (
        not _websocket_origin_allowed(ws)
        or not ws_user
        or (
            settings_module.is_demo_mode()
            and (ws_user.role or "").lower() != "admin"
        )
    ):
        await ws.close(code=1008)
        return
    await ws.accept()
    _notification_subscribers.append((ws_user.id, ws))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if (ws_user.id, ws) in _notification_subscribers:
            _notification_subscribers.remove((ws_user.id, ws))
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
        if (ws_user.id, ws) in _notification_subscribers:
            _notification_subscribers.remove((ws_user.id, ws))
