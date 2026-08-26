import os
import json
import asyncio
import csv
import io
import secrets
import hashlib
import hmac
import unicodedata
import urllib.parse
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Collection, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Path, Request, Response, Cookie, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, aliased
from sqlalchemy import and_, case, desc, extract, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .database import (
    Base, init_db, get_db, SessionLocal, normalize_user_email,
    TicketRecord, UserRecord, RecognitionRecord,
    ExternalUserRecord, ExternalGroupRecord, ExternalGroupMembershipRecord,
    IntelligenceStudyRecord,
    UserExternalIdentityLinkRecord, UserExternalIdentityAuditRecord,
    AgentTicketStateRecord, SyncStateRecord,
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
    LLMProviderCooldownRecord,
    AIArtifactRecord,
    SettingsRecord,
    IntegrationBindingRecord,
    IntegrationCapabilityRecord,
    IntegrationAuditRecord,
    ExternalAttachmentRecord,
    ExternalConversationRecord,
)
from .ai_eligibility import (
    active_ticket_filter,
    is_terminal_status as shared_is_terminal_status,
    mark_terminal_ai_not_applicable,
    terminal_ticket_filter,
    terminal_status_names as shared_terminal_status_names,
)
from .sla_policy import sla_eligible_filter, ticket_is_sla_exempt
from .portable_keys import portable_ascii_lower, portable_ascii_lower_expression
from .schema import (
    Ticket, User, UserSummary, Recognition, SyncStatus,
    AIStatusResponse, AIRetryQueueActionResponse, AIRetryScheduleRequest,
    OperationalDiagnosticsResponse,
    AutomaticAIEnableRequest, AutomaticAIPauseRequest,
    ExternalUser, ExternalUserSyncResult,
    AgentWorkspaceBootstrap, AgentWorkspaceIdentity, AgentWorkspaceTeam,
    AgentWorkspaceTicket, AgentTicketStateUpdate,
    UserExternalIdentityLinkOut, UserExternalIdentityLinkUpdate,
    EmailRecipient, EmailRecipientList, EmailProviderStatus,
    EmailSendRequest, EmailSendResponse,
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
    ServiceItem, ServiceItemCreate, ServiceItemUpdate, ServiceRequest, ServiceRequestCreate,
    ServiceRequestApprovalDecision, ServiceRequestFulfillmentUpdate,
    Problem, ProblemCreate, ProblemUpdate,
    ChangeRecordOut, ChangeCreate, ChangeUpdate, ChangeApprovalOut, ChangeApprovalCreate, ChangeApprovalDecision,
    Asset, AssetCreate, AssetUpdate,
    SurveyTemplate, SurveyOut, SurveySend, SurveyResponseCreate,
    SurveyPortalLookupRequest, SurveyPortalQuestion,
    SurveyPortalResponseRequest, SurveyPortalSubmitted,
    TimeEntry, TimeEntryCreate,
    PortalTicketCreate, PortalTicketOut, PortalTicketCreated,
    IntegrationBindingCreate, IntegrationBindingSuspend,
    FreshworksBootstrapRequest, FreshworksBootstrapRedeem,
    ResolverCatalogRecommendationResponse,
    TicketAttachment,
)
from .attachment_storage import AzureBlobAttachmentStore, AttachmentStorageError
from .branding import PRODUCT_NAME
from .email_service import (
    EmailAddress,
    EmailConfigurationError,
    EmailDeliveryError,
    normalize_email_address,
    normalize_sender_name,
    send_email as send_sendgrid_email,
    sendgrid_status,
)
from .llm_manager import (
    LLMAnalysisError,
    LLMCapacityError,
    LLMContentFilteredError,
    LLMInvalidInputError,
    LLMInvalidOutputError,
    LLMProviderRejectedError,
    LLMUnavailableError,
    LLMManager,
    get_llm_metrics,
    get_llm_catalog,
    refresh_live_models_if_stale,
)
from .ai_contracts import (
    ResolverRoutingAnalysis,
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
from .ai_state import (
    invalidate_ticket_ai,
    invalidate_ticket_resolution,
    merge_terminal_ai_policy_errors,
)
from .brain import IntelligenceEngine, routing_public_thread
from . import intelligence as intel
from . import resolver_catalog
from . import ticket_vectors
from . import agent_workspace
from .prompts import (
    RAG_SYSTEM_PROMPT, REPLY_SYSTEM_PROMPT, RESOLUTION_SYSTEM_PROMPT,
    ROUTING_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT, TRIAGE_SYSTEM_PROMPT,
    RECOGNITIONS, TIER_THRESHOLDS, PRIORITY_POINTS,
    MOMENTUM_BONUS_CAP, MOMENTUM_RESET_HOURS,
)
from .routing_policy import routing_business_context, routing_policy_fingerprint
from .integrations.registry import get_adapter
from .integrations.sync import (
    AUTOMATIC_FETCH_DAYS,
    AUTOMATIC_AI_LOOKBACK_DAYS,
    active_routing_backlog_enabled,
    async_sync_external_users,
    enable_automatic_ai,
    pause_automatic_ai,
    handle_webhook_event,
    queue_old_ticket_fetch,
    sync_tickets_from_external,
    ticket_created_within_filter,
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
from .privacy import configured_secret_values, redact_data, redact_text
from .production_security import (
    disable_seeded_demo_identities as _disable_seeded_demo_identities,
)

# Single source of truth for the backend version. Bump when shipping user-visible
# changes. Build SHA/time are injected at image build time (see Dockerfile).
VERSION = "1.5.0"
BUILD_SHA = os.getenv("TICKETY_BUILD_SHA", "local")
BUILD_TIME = os.getenv("TICKETY_BUILD_TIME", "")


def _ai_pipeline_contract_version() -> str:
    """Bind non-routing AI artifacts to their trusted prompt/output contracts."""
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


def _ai_routing_contract_version() -> str:
    """Version resolver routing independently from unrelated AI artifacts."""
    contract = {
        "input_policy": (
            "canonical-json-v1;ticket-text-untrusted-v1;"
            "actor-identity-excluded-v1;public-thread-identity-excluded-v1"
        ),
        "routing_context_policy": routing_policy_fingerprint(),
        "prompt": ROUTING_SYSTEM_PROMPT,
        "schema": ResolverRoutingAnalysis.model_json_schema(),
    }
    encoded = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return f"2026-08-26.route.{hashlib.sha256(encoded).hexdigest()[:12]}"


AI_PIPELINE_VERSION = _ai_pipeline_contract_version()
AI_ROUTING_PIPELINE_VERSION = _ai_routing_contract_version()


def _artifact_pipeline_version(artifact: str) -> str:
    return (
        AI_ROUTING_PIPELINE_VERSION
        if artifact == "route"
        else AI_PIPELINE_VERSION
    )

app = FastAPI(title=PRODUCT_NAME, version=VERSION)


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
SURVEY_RESPONSE_TOKEN_BYTES = 32
SURVEY_RESPONSE_TOKEN_TTL_DAYS = 30
SURVEY_PRODUCTION_ORIGIN = "https://tickety.nexora.com"
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
    if path.startswith("/config/") and (
        unsafe or path.startswith("/config/notifications")
    ):
        return {"admin", "supervisor"}
    if path == "/surveys" or path.startswith("/surveys/"):
        return {"admin", "supervisor"}
    if path == "/email" or path.startswith("/email/"):
        return {"admin", "supervisor", "agent"}
    if unsafe and path == "/tickets/bulk":
        return {"admin", "supervisor"}
    if method.upper() == "DELETE" and path.startswith("/tickets/"):
        return {"admin", "supervisor"}
    if path == "/users" or (unsafe and path.startswith("/users/")):
        return {"admin", "supervisor"}
    if unsafe and path.startswith("/kb/") and path.endswith("/feedback"):
        return None
    # A change approver may be an agent. Let the exact decision endpoint reach
    # its handler, which requires a real session and verifies that the caller is
    # the assigned approver (or an admin). Keep every other change mutation on
    # the admin/supervisor middleware boundary below.
    if method.upper() == "PATCH" and re.fullmatch(
        r"/changes/[^/]+/approvals/[^/]+", path
    ):
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


_OPERATIONAL_USER_ROLES = frozenset({"admin", "supervisor", "agent"})


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


def require_authenticated_role(*roles: str):
    """Require a real session and one of the supplied operational roles."""
    def checker(user: UserRecord = Depends(get_authenticated_user)) -> UserRecord:
        if (user.role or "").lower() not in roles:
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


def get_email_user(
    user: UserRecord = Depends(get_authenticated_user),
) -> UserRecord:
    """Require a real operational user for billable outbound delivery."""
    role = (user.role or "").lower()
    if role not in {"admin", "supervisor", "agent"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if settings_module.is_demo_mode() and role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Demo email access requires an admin session",
        )
    return user


def _can_access_private_ai_context(user: UserRecord) -> bool:
    """Private notes never participate in cross-ticket RAG.

    The optional indexing flag may support a future same-ticket retrieval
    feature, but it must not let an agent plant text that later appears in a
    supervisor's global analysis context.
    """
    return False


def _authorize_ticket_analysis(
    user: UserRecord,
    ticket: TicketRecord,
    db: Optional[Session] = None,
) -> None:
    if (user.role or "").lower() in {"admin", "supervisor"}:
        return
    if (user.role or "").lower() == "agent" and (
        ticket.assignee_id == user.id
        or (db is not None and agent_workspace.can_work_ticket(db, user, ticket))
    ):
        return
    raise HTTPException(status_code=403, detail="Insufficient ticket analysis permission")


def _authorize_ticket_view(user: UserRecord, _ticket: Optional[TicketRecord] = None) -> None:
    """All operational users may browse the complete All Tickets directory."""
    if (user.role or "").lower() in {"admin", "supervisor", "agent"}:
        return
    raise HTTPException(status_code=403, detail="Insufficient ticket view permission")


def _authorize_ticket_mutation(
    user: UserRecord,
    ticket: TicketRecord,
    *,
    db: Optional[Session] = None,
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
    if ticket.assignee_id == user.id or (
        db is not None and agent_workspace.can_work_ticket(db, user, ticket)
    ):
        if (
            changed_fields
            and "assignee_id" in changed_fields
            and requested_assignee_id not in {None, user.id, ticket.assignee_id}
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


def _request_target_contains_nul(request: Request) -> bool:
    if "\x00" in str(request.scope.get("path", "")):
        return True
    return any(
        "\x00" in part
        for key, value in request.query_params.multi_items()
        for part in (key, value)
    )


@app.middleware("http")
async def require_auth_by_default(request: Request, call_next):
    # PostgreSQL rejects NUL-containing string bind parameters.  Reject them
    # once at the decoded request-target boundary so every current and future
    # path/query SQL filter returns a stable client error instead of a 500.
    if _request_target_contains_nul(request):
        return JSONResponse(
            {"detail": "Request path and query parameters must not contain NUL characters"},
            status_code=422,
        )

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
        normalized_role = (user.role or "").lower()
        # Authentication alone is not authorization. Unknown or legacy role
        # strings must fail closed on every non-public route, including routes
        # whose handlers only declare authentication rather than a role.
        if normalized_role not in _OPERATIONAL_USER_ROLES:
            return JSONResponse({"detail": "Insufficient permissions"}, status_code=403)
        if roles and normalized_role not in roles:
            return JSONResponse({"detail": "Insufficient permissions"}, status_code=403)
        if (
            roles
            and settings_module.is_demo_mode()
            and normalized_role != "admin"
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
    image a running container uses (version + git SHA + build timestamp)."""
    return {
        "app": PRODUCT_NAME,
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
    "ai_suggested_team": None,
    "ai_secondary_team": None,
    "ai_routing_confidence": None,
    "ai_business_context": None,
    "ai_routing_scope": None,
    "ai_affected_service": None,
    "ai_failure_domain": None,
    "ai_routing_reason": None,
    "ai_routing_input_hash": None,
    "recommended_team": "Unrouted / Review",
    "recommended_team_basis": "unrouted_review",
    "routing_status": "unrouted_review",
    "routing_abstention_reason": "untrusted_ai_status",
    "routing_catalog_validated": False,
}


def _enrich_ticket_team(
    ticket: TicketRecord,
    *,
    ai_evidence_current: bool = False,
    terminal_statuses: Optional[set[str]] = None,
) -> None:
    decision = intel.team_routing_decision(
        ticket.ai_suggested_category,
        ticket.ai_status,
        ai_suggested_team=ticket.ai_suggested_team,
        source_category=ticket.external_category,
        ticket_status=ticket.status or ticket.workflow_status,
        ai_evidence_current=ai_evidence_current,
        terminal_statuses=terminal_statuses,
    )
    ticket.__dict__["recommended_team"] = decision.recommended_team
    ticket.__dict__["recommended_team_basis"] = decision.basis
    ticket.__dict__["routing_status"] = decision.status
    ticket.__dict__["routing_abstention_reason"] = decision.abstention_reason
    ticket.__dict__["routing_catalog_validated"] = decision.catalog_validated


def _reporter_fallback_identity(reporter: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    value = (reporter or "").strip()
    if not value or value.isdigit():
        return None, None
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return None, value.lower()
    return value, None


def _current_route_artifact_ticket_ids(
    db: Session,
    tickets: Collection[TicketRecord],
) -> set[str]:
    """Return tickets whose exact resolver-route provenance is currently trusted."""
    return resolver_catalog.current_route_artifact_ticket_ids(
        db,
        tickets,
        pipeline_version=AI_ROUTING_PIPELINE_VERSION,
        model=_llm_cache_identity(),
        allow_synthetic=(
            not settings_module.is_production_mode()
            and bool(getattr(engine.llm, "allow_synthetic", False))
        ),
    )


def _enrich_tickets(db: Session, tickets: list[TicketRecord]) -> None:
    """Attach local owners, provider identities, and communication timing in batches."""
    if not tickets:
        return
    ticket_ids = [ticket.id for ticket in tickets]
    terminal_statuses = _terminal_status_names(db)

    assignee_ids = {ticket.assignee_id for ticket in tickets if ticket.assignee_id}
    assignee_names = {}
    if assignee_ids:
        assignee_names = dict(
            db.query(UserRecord.id, UserRecord.name)
            .filter(UserRecord.id.in_(assignee_ids))
            .all()
        )

    external_ids = {
        external_id
        for ticket in tickets
        for external_id in (
            ticket.external_assignee_id,
            ticket.external_requester_id,
        )
        if ticket.external_source and external_id
    }
    external_profiles: dict[tuple[str, str, str, str], ExternalUserRecord] = {}
    if external_ids:
        rows = db.query(ExternalUserRecord).filter(
            ExternalUserRecord.binding_id.in_({ticket.binding_id for ticket in tickets}),
            ExternalUserRecord.provider.in_({
                ticket.external_source for ticket in tickets if ticket.external_source
            }),
            ExternalUserRecord.external_id.in_(external_ids),
        ).all()
        external_profiles = {
            (row.binding_id, row.provider, row.user_type, row.external_id): row
            for row in rows
        }

    public_comment_times = dict(
        db.query(
            TicketCommentRecord.ticket_id,
            func.max(TicketCommentRecord.created_at),
        ).filter(
            TicketCommentRecord.ticket_id.in_(ticket_ids),
            TicketCommentRecord.is_private.is_(False),
        ).group_by(TicketCommentRecord.ticket_id).all()
    )

    # Aggregate AI lifecycle can be ``queued`` while another artifact is
    # pending. Preserve only a current, non-synthetic resolver-route artifact;
    # aggregate status, legacy triage categories, and provider assignments are
    # not routing evidence. Exact input/model/pipeline checks keep stale routes
    # fail closed.
    current_route_ids = _current_route_artifact_ticket_ids(db, tickets)

    for ticket in tickets:
        ticket.__dict__["assignee_name"] = assignee_names.get(ticket.assignee_id)
        assignee_profile = external_profiles.get((
            ticket.binding_id,
            ticket.external_source or "",
            "agent",
            ticket.external_assignee_id or "",
        ))
        ticket.__dict__["external_assignee_name"] = (
            assignee_profile.name if assignee_profile else None
        )

        requester_profile = external_profiles.get((
            ticket.binding_id,
            ticket.external_source or "",
            "requester",
            ticket.external_requester_id or "",
        ))
        fallback_name, fallback_email = _reporter_fallback_identity(ticket.reporter)
        ticket.__dict__["requester_id"] = ticket.external_requester_id
        ticket.__dict__["requester_name"] = (
            requester_profile.name
            if requester_profile and requester_profile.name
            else ticket.external_requester_name or fallback_name
        )
        ticket.__dict__["requester_email"] = (
            requester_profile.email
            if requester_profile and requester_profile.email
            else ticket.external_requester_email or fallback_email
        )
        ticket.__dict__["requester_title"] = (
            requester_profile.title
            if requester_profile and requester_profile.title
            else ticket.external_requester_title
        )
        communication_times = [
            value for value in (
                ticket.external_created_at or ticket.created_at,
                ticket.external_conversation_updated_at,
                public_comment_times.get(ticket.id),
            )
            if value is not None
        ]
        ticket.__dict__["last_communication_at"] = (
            max(communication_times) if communication_times else None
        )
        _enrich_ticket_team(
            ticket,
            ai_evidence_current=ticket.id in current_route_ids,
            terminal_statuses=terminal_statuses,
        )


def _useful_external_name(value: Optional[str], external_id: Optional[str]) -> Optional[str]:
    name = (value or "").strip()
    if not name or name.isdigit() or name == (external_id or "").strip():
        return None
    if re.fullmatch(r"(?:external|freshservice) user \d+", name, re.IGNORECASE):
        return None
    return name


def _enrich_comments(
    db: Session,
    ticket: TicketRecord,
    comments: list[TicketCommentRecord],
) -> None:
    if not comments:
        return
    local_ids = {comment.author_id for comment in comments if comment.author_id}
    local_profiles = {}
    if local_ids:
        local_profiles = {
            row.id: row
            for row in db.query(UserRecord).filter(UserRecord.id.in_(local_ids)).all()
        }

    external_author_ids = {
        comment.external_author_id
        for comment in comments
        if comment.external_author_id
    }
    external_profiles: dict[tuple[str, str], ExternalUserRecord] = {}
    if ticket.external_source and external_author_ids:
        external_profiles = {
            (row.user_type, row.external_id): row
            for row in db.query(ExternalUserRecord).filter(
                ExternalUserRecord.binding_id == ticket.binding_id,
                ExternalUserRecord.provider == ticket.external_source,
                ExternalUserRecord.external_id.in_(external_author_ids),
            ).all()
        }
    external_comment_ids = {
        comment.external_id for comment in comments if comment.external_id
    }
    incoming_by_id = {}
    if external_comment_ids:
        incoming_by_id = dict(db.query(
            ExternalConversationRecord.external_id,
            ExternalConversationRecord.incoming,
        ).filter(
            ExternalConversationRecord.ticket_id == ticket.id,
            ExternalConversationRecord.external_id.in_(external_comment_ids),
        ).all())

    for comment in comments:
        local_profile = local_profiles.get(comment.author_id)
        if local_profile is not None:
            comment.__dict__["author_name"] = local_profile.name
            comment.__dict__["author_email"] = local_profile.email
            comment.__dict__["author_title"] = local_profile.title
            comment.__dict__["author_type"] = "agent"
            continue
        if not comment.external_source:
            comment.__dict__["author_title"] = None
            comment.__dict__["author_type"] = None
            continue
        author_type = (
            "requester"
            if incoming_by_id.get(comment.external_id or "", False)
            else "agent"
        )
        profile = external_profiles.get((author_type, comment.external_author_id or ""))
        stored_name = _useful_external_name(
            comment.author_name,
            comment.external_author_id,
        )
        profile_name = _useful_external_name(
            profile.name if profile else None,
            comment.external_author_id,
        )
        comment.__dict__["author_name"] = (
            profile_name
            or stored_name
            or f"{comment.external_source.title()} {author_type}"
        )
        comment.__dict__["author_email"] = (
            profile.email if profile and profile.email else comment.author_email
        )
        comment.__dict__["author_title"] = profile.title if profile else None
        comment.__dict__["author_type"] = author_type


def _ticket_for_request(
    request: Request,
    ticket: TicketRecord,
    *,
    redact_ai: bool = False,
) -> Ticket | TicketRecord:
    """Remove generated AI artifacts outside an authorized work context."""
    if not getattr(request.state, "demo_fallback", False) and not redact_ai:
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
    sort: str = Query(default="newest", pattern="^(newest|oldest|priority|queue|updated|complexity)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
):
    _authorize_ticket_view(user)
    if getattr(request.state, "demo_fallback", False):
        # Anonymous demo responses redact these model-generated values. Do not
        # retain them as query or ordering oracles after redaction.
        if category or sort == "complexity":
            raise HTTPException(
                status_code=403,
                detail="AI-derived ticket filters require authentication",
            )
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
        # Treat SQL wildcard characters as user text so searches remain
        # predictable and cannot accidentally expand into an unbounded match.
        escaped_search = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if escaped_search:
            pattern = f"%{escaped_search}%"
            q = q.filter(or_(
                TicketRecord.subject.ilike(pattern, escape="\\"),
                TicketRecord.description.ilike(pattern, escape="\\"),
                TicketRecord.reporter.ilike(pattern, escape="\\"),
                TicketRecord.external_requester_name.ilike(pattern, escape="\\"),
                TicketRecord.external_requester_email.ilike(pattern, escape="\\"),
                TicketRecord.external_requester_title.ilike(pattern, escape="\\"),
                TicketRecord.external_id.ilike(pattern, escape="\\"),
                db.query(ExternalUserRecord.id).filter(
                    ExternalUserRecord.binding_id == TicketRecord.binding_id,
                    ExternalUserRecord.provider == TicketRecord.external_source,
                    ExternalUserRecord.external_id == TicketRecord.external_requester_id,
                    ExternalUserRecord.user_type == "requester",
                    or_(
                        ExternalUserRecord.name.ilike(pattern, escape="\\"),
                        ExternalUserRecord.email.ilike(pattern, escape="\\"),
                        ExternalUserRecord.title.ilike(pattern, escape="\\"),
                    ),
                ).exists(),
            ))
    source_created_at = func.coalesce(
        TicketRecord.external_created_at,
        TicketRecord.created_at,
    )
    latest_public_comment = db.query(
        func.max(TicketCommentRecord.created_at)
    ).filter(
        TicketCommentRecord.ticket_id == TicketRecord.id,
        TicketCommentRecord.is_private.is_(False),
    ).correlate(TicketRecord).scalar_subquery()
    last_communication_at = func.coalesce(
        latest_public_comment,
        TicketRecord.external_conversation_updated_at,
        TicketRecord.external_created_at,
        TicketRecord.created_at,
    )
    if sort == "oldest":
        q = q.order_by(source_created_at.asc(), TicketRecord.id.asc())
    elif sort in {"priority", "queue"}:
        # SQLAlchemy's portable CASE expression keeps semantic priority order
        # across SQLite (tests) and PostgreSQL (production), while the
        # correlated config lookup makes administrator-defined priorities
        # participate in the same queue instead of falling to the bottom.
        q = q.order_by(
            _priority_weight_expression(),
            source_created_at.asc() if sort == "queue" else source_created_at.desc(),
            TicketRecord.id.asc(),
        )
    elif sort == "updated":
        q = q.order_by(last_communication_at.desc(), TicketRecord.id.asc())
    elif sort == "complexity":
        q = q.order_by(TicketRecord.complexity.desc(), source_created_at.desc(), TicketRecord.id.asc())
    else:
        q = q.order_by(source_created_at.desc(), TicketRecord.id.asc())

    # Fetch one extra row to signal whether another page exists without a
    # potentially expensive COUNT(*) over the filtered result set.
    page = q.offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    tickets = page[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()

    _enrich_tickets(db, tickets)
    direct: set[tuple[str, str, str]] = set()
    groups: dict[tuple[str, str, str], ExternalGroupRecord] = {}
    if (user.role or "").lower() == "agent":
        direct, groups = _agent_assignment_context(
            db,
            user,
            [ticket.id for ticket in tickets],
        )
    return [
        _ticket_for_request(
            request,
            ticket,
            redact_ai=(
                (user.role or "").lower() == "agent"
                and _agent_ticket_scope_from_context(user, ticket, direct, groups)[0] is None
            ),
        )
        for ticket in tickets
    ]


@app.get("/dashboard/summary")
async def dashboard_summary(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    """Return complete operational counts without downloading the ticket corpus."""
    _authorize_ticket_view(user)
    terminal = _terminal_status_names(db)
    normalized_status = portable_ascii_lower_expression(TicketRecord.status)
    active = normalized_status.notin_(terminal)
    critical = portable_ascii_lower_expression(TicketRecord.priority).in_(("p1", "urgent"))
    unassigned = and_(
        func.nullif(TicketRecord.assignee_id, "").is_(None),
        func.nullif(TicketRecord.external_assignee_id, "").is_(None),
    )
    total, active_count, p1_count, escalated_count, unassigned_count = db.query(
        func.count(TicketRecord.id),
        func.sum(case((active, 1), else_=0)),
        func.sum(case((and_(active, critical), 1), else_=0)),
        func.sum(case((and_(active, normalized_status == "escalated"), 1), else_=0)),
        func.sum(case((and_(active, unassigned), 1), else_=0)),
    ).one()
    total = int(total or 0)
    active_count = int(active_count or 0)
    return {
        "total_tickets": total,
        "active_tickets": active_count,
        "inactive_tickets": max(0, total - active_count),
        "p1_active": int(p1_count or 0),
        "escalated_active": int(escalated_count or 0),
        "unassigned_active": int(unassigned_count or 0),
    }


def _agent_conversation_subqueries(db: Session):
    conversation_at = func.coalesce(
        ExternalConversationRecord.provider_created_at,
        ExternalConversationRecord.provider_updated_at,
        ExternalConversationRecord.received_at,
    )
    base = (
        ExternalConversationRecord.ticket_id == TicketRecord.id,
        ExternalConversationRecord.is_private.is_(False),
        ExternalConversationRecord.deleted.is_(False),
        ExternalConversationRecord.public_tombstone.is_(False),
    )
    latest_incoming = db.query(func.max(conversation_at)).filter(
        *base,
        ExternalConversationRecord.incoming.is_(True),
    ).correlate(TicketRecord).scalar_subquery()
    latest_outgoing = db.query(func.max(conversation_at)).filter(
        *base,
        ExternalConversationRecord.incoming.is_(False),
    ).correlate(TicketRecord).scalar_subquery()
    requester_activity = func.coalesce(
        latest_incoming,
        TicketRecord.external_created_at,
        TicketRecord.created_at,
    )
    needs_reply = and_(
        requester_activity.isnot(None),
        or_(latest_outgoing.is_(None), requester_activity > latest_outgoing),
    )
    return requester_activity, latest_outgoing, needs_reply


def _agent_sla_deadline_expression(needs_reply):
    response_deadline = func.coalesce(
        TicketRecord.response_due_at,
        TicketRecord.external_fr_due_by,
    )
    resolution_deadline = func.coalesce(
        TicketRecord.resolution_due_at,
        TicketRecord.due_by,
        TicketRecord.external_due_by,
    )
    return case(
        (needs_reply, func.coalesce(response_deadline, resolution_deadline)),
        else_=resolution_deadline,
    )


_DEFAULT_PRIORITY_WEIGHTS = {
    "p1": 1,
    "urgent": 1,
    "p2": 5,
    "high": 5,
    "p3": 10,
    "medium": 10,
    "p4": 20,
    "low": 20,
}


def _priority_weight_expression():
    """Return the configured queue weight for the outer ticket row.

    The scalar lookup avoids an extra request-level query and preserves the
    ticket-list endpoint's bounded query count. Legacy aliases remain ordered
    sensibly when a deployment has not seeded configuration yet.
    """
    normalized_priority = portable_ascii_lower_expression(TicketRecord.priority)
    configured_weight = (
        select(TicketPriorityConfigRecord.weight)
        .where(TicketPriorityConfigRecord.name_key == normalized_priority)
        .limit(1)
        .scalar_subquery()
    )
    fallback_weight = case(
        _DEFAULT_PRIORITY_WEIGHTS,
        value=normalized_priority,
        else_=1_000,
    )
    return func.coalesce(configured_weight, fallback_weight)


def _priority_score_from_weight(weight: int) -> int:
    if weight <= 1:
        return 40
    if weight <= 5:
        return 24
    if weight <= 10:
        return 12
    return 4


def _priority_weights(db: Session) -> dict[str, int]:
    weights = dict(_DEFAULT_PRIORITY_WEIGHTS)
    for name_key, weight in db.query(
        TicketPriorityConfigRecord.name_key,
        TicketPriorityConfigRecord.weight,
    ).all():
        if name_key and weight is not None:
            weights[name_key] = int(weight)
    return weights


def _agent_next_best_score_expression(needs_reply, now: datetime):
    """Portable SQL approximation of the score shown in the reading pane."""
    deadline = _agent_sla_deadline_expression(needs_reply)
    priority_weight = _priority_weight_expression()
    priority_score = case(
        (priority_weight <= 1, 40),
        (priority_weight <= 5, 24),
        (priority_weight <= 10, 12),
        else_=4,
    )
    sla_eligible = sla_eligible_filter()
    sla_score = case(
        (and_(sla_eligible, deadline <= now), 35),
        (and_(sla_eligible, deadline <= now + timedelta(hours=1)), 28),
        (and_(sla_eligible, deadline <= now + timedelta(hours=4)), 18),
        (and_(sla_eligible, deadline <= now + timedelta(hours=24)), 8),
        else_=0,
    )
    risk_score = case(
        (TicketRecord.escalation_risk >= 90, 18),
        (TicketRecord.escalation_risk >= 75, 15),
        (TicketRecord.escalation_risk >= 60, 12),
        (TicketRecord.escalation_risk >= 50, 10),
        else_=0,
    )
    created_at = func.coalesce(
        TicketRecord.external_created_at,
        TicketRecord.created_at,
    )
    aging_score = case(
        (created_at <= now - timedelta(days=2), 6),
        else_=0,
    )
    return priority_score + case((needs_reply, 18), else_=0) + sla_score + risk_score + aging_score


def _agent_sla_deadline(ticket: TicketRecord, *, needs_reply: bool) -> Optional[datetime]:
    if ticket_is_sla_exempt(ticket):
        return None
    if needs_reply:
        return ticket.response_due_at or ticket.external_fr_due_by
    return (
        ticket.resolution_due_at
        or ticket.due_by
        or ticket.external_due_by
        or ticket.response_due_at
        or ticket.external_fr_due_by
    )


def _agent_next_best_score(
    ticket: TicketRecord,
    *,
    needs_reply: bool,
    now: datetime,
    priority_weights: Optional[dict[str, int]] = None,
) -> tuple[int, list[str], bool]:
    score = 0
    reasons: list[str] = []
    weights = priority_weights or _DEFAULT_PRIORITY_WEIGHTS
    # Match the SQL trim() contract exactly. Config names are migration- and
    # schema-constrained to portable ASCII without surrounding whitespace;
    # tabs or Unicode whitespace in provider-owned ticket values stay unknown
    # on both code paths instead of receiving different ranks.
    weight = weights.get(portable_ascii_lower(ticket.priority), 1_000)
    points = _priority_score_from_weight(weight)
    score += points
    if points >= 24:
        reasons.append(f"{ticket.priority} priority")
    if needs_reply:
        score += 18
        reasons.append("Requester is waiting for a reply")
    deadline = _agent_sla_deadline(ticket, needs_reply=needs_reply)
    sla_at_risk = False
    if deadline is not None:
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            score += 35
            sla_at_risk = True
            reasons.append("SLA is overdue")
        elif remaining <= 3600:
            score += 28
            sla_at_risk = True
            reasons.append("SLA is due within one hour")
        elif remaining <= 4 * 3600:
            score += 18
            sla_at_risk = True
            reasons.append("SLA is due within four hours")
        elif remaining <= 24 * 3600:
            score += 8
            reasons.append("SLA is due today")
    risk = max(0, min(100, ticket.escalation_risk or 0))
    if risk >= 50:
        score += min(20, risk // 5)
        reasons.append(f"{risk}% escalation risk")
    created_at = ticket.external_created_at or ticket.created_at
    if created_at and now - created_at >= timedelta(days=2):
        score += 6
        reasons.append("Aging ticket")
    return min(100, score), reasons[:4], sla_at_risk


def _agent_assignment_context(
    db: Session,
    user: UserRecord,
    ticket_ids: list[str],
) -> tuple[set[tuple[str, str, str]], dict[tuple[str, str, str], ExternalGroupRecord]]:
    """Build redaction context from joins scoped to the bounded ticket page."""
    direct = agent_workspace.linked_identity_keys_for_tickets(
        db,
        user.id,
        ticket_ids,
    )
    groups = {
        (
            group.binding_id,
            group.provider.lower(),
            group.external_id,
        ): group
        for group in agent_workspace.accessible_groups_for_tickets(
            db,
            user.id,
            ticket_ids,
        )
    }
    return direct, groups


def _agent_ticket_scope_from_context(
    user: UserRecord,
    ticket: TicketRecord,
    direct: set[tuple[str, str, str]],
    groups: dict[tuple[str, str, str], ExternalGroupRecord],
) -> tuple[Optional[str], Optional[ExternalGroupRecord]]:
    if ticket.assignee_id == user.id or (
        ticket.external_assignee_id
        and (
            ticket.binding_id,
            (ticket.external_source or "").lower(),
            ticket.external_assignee_id,
        ) in direct
    ):
        return "mine", None
    group = groups.get((
        ticket.binding_id,
        (ticket.external_source or "").lower(),
        ticket.external_group_id or "",
    ))
    return ("team", group) if group is not None else (None, None)


def _latest_agent_public_conversation_directions(
    db: Session,
    ticket_ids: list[str],
) -> dict[str, bool]:
    """Return only the newest public conversation direction for each ticket."""
    if not ticket_ids:
        return {}
    conversation_at = func.coalesce(
        ExternalConversationRecord.provider_created_at,
        ExternalConversationRecord.provider_updated_at,
        ExternalConversationRecord.received_at,
    )
    ranked = db.query(
        ExternalConversationRecord.ticket_id.label("ticket_id"),
        ExternalConversationRecord.incoming.label("incoming"),
        func.row_number().over(
            partition_by=ExternalConversationRecord.ticket_id,
            order_by=(
                conversation_at.desc(),
                ExternalConversationRecord.external_id.desc(),
                ExternalConversationRecord.id.desc(),
            ),
        ).label("conversation_rank"),
    ).filter(
        ExternalConversationRecord.ticket_id.in_(ticket_ids),
        ExternalConversationRecord.is_private.is_(False),
        ExternalConversationRecord.deleted.is_(False),
        ExternalConversationRecord.public_tombstone.is_(False),
    ).subquery()
    return {
        ticket_id: bool(incoming)
        for ticket_id, incoming in db.query(
            ranked.c.ticket_id,
            ranked.c.incoming,
        ).filter(ranked.c.conversation_rank == 1).all()
    }


def _agent_ticket_payloads(
    db: Session,
    user: UserRecord,
    tickets: list[TicketRecord],
    *,
    scope: str,
) -> list[AgentWorkspaceTicket]:
    if not tickets:
        return []
    _enrich_tickets(db, tickets)
    ticket_ids = [ticket.id for ticket in tickets]
    groups = {
        (
            group.binding_id,
            group.provider.lower(),
            group.external_id,
        ): group
        for group in (
            agent_workspace.accessible_groups_for_tickets(db, user.id, ticket_ids)
            if scope == "team"
            else []
        )
    }
    states = {
        row.ticket_id: row
        for row in db.query(AgentTicketStateRecord).filter(
            AgentTicketStateRecord.user_id == user.id,
            AgentTicketStateRecord.ticket_id.in_(ticket_ids),
        ).all()
    }
    latest_conversations = _latest_agent_public_conversation_directions(
        db,
        ticket_ids,
    )

    now = datetime.utcnow()
    priority_weights = _priority_weights(db)
    payloads: list[AgentWorkspaceTicket] = []
    for ticket in tickets:
        state = states.get(ticket.id)
        latest = latest_conversations.get(ticket.id)
        needs_reply = latest is None or latest
        score, reasons, sla_at_risk = _agent_next_best_score(
            ticket,
            needs_reply=needs_reply,
            now=now,
            priority_weights=priority_weights,
        )
        group = groups.get((
            ticket.binding_id,
            (ticket.external_source or "").lower(),
            ticket.external_group_id or "",
        )) if scope == "team" else None
        last_activity = getattr(ticket, "last_communication_at", None) or ticket.updated_at or ticket.created_at
        is_unread = bool(
            state is None
            or state.last_seen_at is None
            or (last_activity is not None and last_activity > state.last_seen_at)
        )
        base_ticket = Ticket.model_validate(ticket, from_attributes=True).model_dump()
        payloads.append(AgentWorkspaceTicket.model_validate({
            **base_ticket,
            "assignment_scope": scope,
            "team_id": group.id if group else None,
            "team_name": group.name if group else None,
            "is_unread": is_unread,
            "is_starred": bool(state and state.starred_at),
            "follow_up_at": state.follow_up_at if state else None,
            "needs_reply": needs_reply,
            "sla_at_risk": sla_at_risk,
            "next_best_score": score,
            "next_best_reasons": reasons,
        }))
    return payloads


@app.get("/agent-workspace/bootstrap", response_model=AgentWorkspaceBootstrap)
async def get_agent_workspace_bootstrap(
    response: Response,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_authenticated_role("admin", "supervisor", "agent")),
):
    identities = agent_workspace.linked_identities(db, user.id, limit=1)
    groups, teams_truncated = agent_workspace.accessible_groups_page(
        db,
        user.id,
        limit=agent_workspace.MAX_ACCESSIBLE_GROUPS,
    )
    response.headers["X-Teams-Limit"] = str(agent_workspace.MAX_ACCESSIBLE_GROUPS)
    response.headers["X-Teams-Truncated"] = str(teams_truncated).lower()
    mine_filter = agent_workspace.assignment_filter(db, user, scope="mine")
    team_filter = agent_workspace.assignment_filter(db, user, scope="team")
    _latest_incoming, _latest_outgoing, needs_reply = _agent_conversation_subqueries(db)
    now = datetime.utcnow()
    sla_deadline = _agent_sla_deadline_expression(needs_reply)
    active = active_ticket_filter(db)
    sla_eligible = sla_eligible_filter(_terminal_status_names(db))
    starred = select(1).select_from(AgentTicketStateRecord).where(
        AgentTicketStateRecord.ticket_id == TicketRecord.id,
        AgentTicketStateRecord.user_id == user.id,
        AgentTicketStateRecord.starred_at.isnot(None),
    ).correlate(TicketRecord).exists()
    aggregate = db.query(
        func.sum(case((and_(mine_filter, active), 1), else_=0)),
        func.sum(case((and_(mine_filter, active, needs_reply), 1), else_=0)),
        func.sum(case((and_(
            mine_filter,
            active,
            sla_eligible,
            sla_deadline.isnot(None),
            sla_deadline <= now + timedelta(hours=4),
        ), 1), else_=0)),
        func.sum(case((and_(mine_filter, active, starred), 1), else_=0)),
        func.sum(case((and_(team_filter, active), 1), else_=0)),
        func.sum(case((and_(
            team_filter,
            active,
            TicketRecord.external_assignee_id.is_(None),
        ), 1), else_=0)),
    ).one()
    counts = {
        "inbox": int(aggregate[0] or 0),
        "needs_reply": int(aggregate[1] or 0),
        "sla_at_risk": int(aggregate[2] or 0),
        "starred": int(aggregate[3] or 0),
        "team_inbox": int(aggregate[4] or 0),
        "team_unassigned": int(aggregate[5] or 0),
    }
    group_counts: dict[str, tuple[int, int]] = {}
    group_ids = [item.group.id for item in groups]
    if group_ids:
        group_rows = db.query(
            ExternalGroupRecord.id,
            func.count(TicketRecord.id),
            func.sum(case((and_(
                TicketRecord.id.isnot(None),
                TicketRecord.external_assignee_id.is_(None),
            ), 1), else_=0)),
        ).select_from(ExternalGroupRecord).outerjoin(
            TicketRecord,
            and_(
                TicketRecord.binding_id == ExternalGroupRecord.binding_id,
                TicketRecord.external_source == ExternalGroupRecord.provider,
                TicketRecord.external_group_id == ExternalGroupRecord.external_id,
                active,
            ),
        ).filter(
            ExternalGroupRecord.id.in_(group_ids)
        ).group_by(
            ExternalGroupRecord.id
        ).all()
        group_counts = {
            group_id: (int(ticket_count or 0), int(unassigned_count or 0))
            for group_id, ticket_count, unassigned_count in group_rows
        }
    team_payloads: list[AgentWorkspaceTeam] = []
    for item in groups:
        group = item.group
        ticket_count, unassigned_count = group_counts.get(group.id, (0, 0))
        team_payloads.append(AgentWorkspaceTeam(
            id=group.id,
            external_id=group.external_id,
            name=group.name,
            workspace_id=group.workspace_id,
            membership_kind=item.membership_kind,
            ticket_count=ticket_count,
            unassigned_count=unassigned_count,
        ))
    identity = identities[0] if identities else None
    return AgentWorkspaceBootstrap(
        identity=(AgentWorkspaceIdentity(
            link_id=identity.link.id,
            external_user_id=identity.external_user.id,
            external_id=identity.external_user.external_id,
            name=identity.external_user.name,
            email=identity.external_user.email,
            binding_id=identity.link.binding_id,
            provider=identity.link.provider,
        ) if identity else None),
        teams=team_payloads,
        teams_truncated=teams_truncated,
        counts=counts,
    )


@app.get("/agent-workspace/tickets", response_model=List[AgentWorkspaceTicket])
async def list_agent_workspace_tickets(
    response: Response,
    scope: str = Query(default="mine", pattern="^(mine|team)$"),
    team_id: Optional[str] = Query(default=None, max_length=36),
    ticket_id: Optional[str] = Query(
        default=None,
        min_length=1,
        max_length=255,
        pattern=r"^[^\x00]*$",
    ),
    folder: str = Query(
        default="inbox",
        pattern="^(inbox|needs_reply|sla_at_risk|starred|follow_up|closed|unassigned)$",
    ),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_authenticated_role("admin", "supervisor", "agent")),
):
    q = db.query(TicketRecord).filter(
        agent_workspace.assignment_filter(
            db, user, scope=scope, team_id=team_id
        )
    )
    _latest_incoming, _latest_outgoing, needs_reply = _agent_conversation_subqueries(db)
    now = datetime.utcnow()
    if folder == "closed":
        q = q.filter(terminal_ticket_filter(db))
    else:
        q = q.filter(active_ticket_filter(db))
    if folder == "needs_reply":
        q = q.filter(needs_reply)
    elif folder == "sla_at_risk":
        sla_deadline = _agent_sla_deadline_expression(needs_reply)
        q = q.filter(
            sla_eligible_filter(_terminal_status_names(db)),
            sla_deadline.isnot(None),
            sla_deadline <= now + timedelta(hours=4),
        )
    elif folder == "starred":
        q = q.join(
            AgentTicketStateRecord,
            and_(
                AgentTicketStateRecord.ticket_id == TicketRecord.id,
                AgentTicketStateRecord.user_id == user.id,
            ),
        ).filter(AgentTicketStateRecord.starred_at.isnot(None))
    elif folder == "follow_up":
        q = q.join(
            AgentTicketStateRecord,
            and_(
                AgentTicketStateRecord.ticket_id == TicketRecord.id,
                AgentTicketStateRecord.user_id == user.id,
            ),
        ).filter(
            AgentTicketStateRecord.follow_up_at.isnot(None),
            AgentTicketStateRecord.follow_up_at <= now,
        )
    elif folder == "unassigned":
        if scope != "team":
            raise HTTPException(status_code=422, detail="Unassigned is a team inbox folder")
        q = q.filter(TicketRecord.external_assignee_id.is_(None))
    if ticket_id:
        q = q.filter(TicketRecord.id == ticket_id)
    elif search:
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if escaped:
            pattern = f"%{escaped}%"
            q = q.filter(or_(
                TicketRecord.subject.ilike(pattern, escape="\\"),
                TicketRecord.description.ilike(pattern, escape="\\"),
                TicketRecord.external_requester_name.ilike(pattern, escape="\\"),
                TicketRecord.external_requester_email.ilike(pattern, escape="\\"),
                TicketRecord.external_id.ilike(pattern, escape="\\"),
            ))
    due_at = _agent_sla_deadline_expression(needs_reply)
    focus_score = _agent_next_best_score_expression(needs_reply, now)
    q = q.order_by(
        focus_score.desc(),
        due_at.is_(None),
        due_at.asc(),
        func.coalesce(TicketRecord.external_updated_at, TicketRecord.updated_at).desc(),
        TicketRecord.id,
    )
    page = q.offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    tickets = page[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    return _agent_ticket_payloads(db, user, tickets, scope=scope)


@app.put("/agent-workspace/tickets/{ticket_id}/state")
async def update_agent_ticket_state(
    ticket_id: str,
    payload: AgentTicketStateUpdate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_authenticated_role("admin", "supervisor", "agent")),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_view(user, ticket)
    state = db.query(AgentTicketStateRecord).filter(
        AgentTicketStateRecord.user_id == user.id,
        AgentTicketStateRecord.ticket_id == ticket_id,
    ).first()
    now = datetime.utcnow()
    if state is None:
        state = AgentTicketStateRecord(
            user_id=user.id,
            ticket_id=ticket_id,
            created_at=now,
            updated_at=now,
        )
        db.add(state)
    if payload.mark_seen:
        state.last_seen_at = now
    if payload.starred is not None:
        state.starred_at = now if payload.starred else None
    if payload.clear_follow_up:
        state.follow_up_at = None
    elif payload.follow_up_at is not None:
        state.follow_up_at = payload.follow_up_at.astimezone(timezone.utc).replace(tzinfo=None) if payload.follow_up_at.tzinfo else payload.follow_up_at
    state.updated_at = now
    db.commit()
    return {
        "ticket_id": ticket_id,
        "last_seen_at": state.last_seen_at,
        "starred_at": state.starred_at,
        "follow_up_at": state.follow_up_at,
    }


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
    _authorize_ticket_view(user, ticket)
    _enrich_tickets(db, [ticket])
    return _ticket_for_request(
        request,
        ticket,
        redact_ai=(
            (user.role or "").lower() == "agent"
            and not agent_workspace.can_work_ticket(db, user, ticket)
        ),
    )


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
    _authorize_ticket_analysis(user, ticket, db)
    _reserve_ai_request(db, user.id, "related_tickets")
    ticket, user = _lock_authorized_ticket_analysis(db, ticket_id, user)
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    query = " ".join(
        value.strip() for value in (ticket.subject or "", ticket.description or "")
        if value and value.strip()
    )[:1000]
    if not query:
        query = ticket.id[:1000]
    # Authorization has been serialized with assignment. Related-ticket
    # retrieval may invoke an embedding provider, so release the row lock
    # before crossing that boundary.
    db.commit()
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

    # Retrieval deliberately runs without locks. Before any result is exposed,
    # bind the response to the actor's current account and assignment again.
    ticket, user = _lock_authorized_ticket_analysis(db, ticket_id, user)
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    db.commit()

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


def _survey_response_ttl() -> timedelta:
    try:
        days = int(
            os.getenv(
                "SURVEY_RESPONSE_TOKEN_TTL_DAYS",
                str(SURVEY_RESPONSE_TOKEN_TTL_DAYS),
            )
        )
    except (TypeError, ValueError):
        days = SURVEY_RESPONSE_TOKEN_TTL_DAYS
    return timedelta(days=max(1, min(days, 90)))


def _normalized_http_origin(value: str) -> Optional[str]:
    candidate = (value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _survey_response_url(request: Request, token: str) -> str:
    configured = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if settings_module.is_production_mode():
        # Production survey capabilities may only be delivered to Tickety OPS Tower's
        # fixed public origin. Missing, alternate, or path-bearing config is a
        # hard failure rather than a Host-header-derived fallback.
        if configured != SURVEY_PRODUCTION_ORIGIN:
            raise HTTPException(
                status_code=503,
                detail="Survey response origin is not configured safely",
            )
        origin = SURVEY_PRODUCTION_ORIGIN
    else:
        origin = _normalized_http_origin(configured or str(request.base_url))
        if origin is None:
            raise HTTPException(
                status_code=503,
                detail="Survey response origin is not configured safely",
            )
    # URL fragments are never transmitted in the HTTP request target, keeping
    # bearer material out of ordinary proxy and access logs.
    return f"{origin}/portal/survey#token={urllib.parse.quote(token, safe='')}"


def _require_public_survey_origin(request: Request) -> None:
    if settings_module.is_production_mode():
        supplied = _normalized_http_origin(request.headers.get("origin", ""))
        allowed = supplied == SURVEY_PRODUCTION_ORIGIN
    else:
        allowed = _request_origin_allowed(request, require_explicit=True)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="Invalid request origin",
            headers={"Cache-Control": "no-store"},
        )


def _survey_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _survey_delivery_key(ticket_id: str, template_id: int, recipient_email: str) -> str:
    identity = json.dumps(
        [ticket_id, template_id, recipient_email],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _survey_for_token(db: Session, token: str) -> Optional[SurveyRecord]:
    # Preserve one public error surface for malformed, random, expired, and
    # undelivered capabilities. The dummy compare also avoids an obvious fast
    # path for malformed input.
    if not token or not 40 <= len(token) <= 128 or not re.fullmatch(
        r"[A-Za-z0-9_-]+", token
    ):
        hmac.compare_digest("0" * 64, _survey_token_digest("invalid"))
        return None
    digest = _survey_token_digest(token)
    survey = db.query(SurveyRecord).filter(
        SurveyRecord.response_token_hash == digest,
    ).first()
    if not survey or not survey.response_token_hash:
        hmac.compare_digest("0" * 64, digest)
        return None
    if not hmac.compare_digest(survey.response_token_hash, digest):
        return None
    if survey.delivery_status not in {"pending", "uncertain", "accepted"}:
        return None
    if survey.delivery_attempted_at is None:
        return None
    if survey.delivery_status == "accepted" and survey.sent_at is None:
        return None
    if (
        survey.response_expires_at is None
        or survey.response_expires_at <= datetime.utcnow()
    ):
        return None
    return survey


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
    normalized_priority = portable_ascii_lower(priority)
    configured = db.query(TicketPriorityConfigRecord).filter(
        TicketPriorityConfigRecord.name_key == normalized_priority
    ).first()
    if configured and configured.sla_hours:
        return int(configured.sla_hours)
    env_key = f"SLA_{normalized_priority.upper()}_HOURS"
    raw = os.getenv(env_key) if normalized_priority.isascii() else None
    if raw and raw.isdigit():
        return int(raw)
    defaults = {"p1": 4, "p2": 24, "p3": 72, "p4": 168}
    return defaults.get(normalized_priority, 72)


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
    amount: int = 1,
) -> int:
    values = {
        "actor_id": actor_id,
        "window_kind": window_kind,
        "window_start": window_start,
        "request_count": amount,
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
            row.request_count += amount
        else:
            row = AIRequestBucketRecord(**values)
            db.add(row)
        db.flush()
        return row.request_count
    statement = insert(AIRequestBucketRecord).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=["actor_id", "window_kind", "window_start"],
        set_={"request_count": AIRequestBucketRecord.request_count + amount},
    ).returning(AIRequestBucketRecord.request_count)
    return int(db.execute(statement).scalar_one())


def _reserve_ai_request(db: Session, actor_id: str, task: str) -> None:
    """Durable per-user provider-work budget shared by every API replica."""
    now = datetime.utcnow()
    if actor_id == "system-worker":
        # Background admission is already bounded by the worker batch size and
        # the provider-wide RPM/TPM/daily-token controls.  A separate durable
        # ceiling prevents a repair backlog from consuming the much smaller
        # human-user allowance for the rest of the day.
        per_minute = _bounded_env_int(
            "AI_SYSTEM_REQUESTS_PER_MINUTE", 10, 1, 120
        )
        per_day = _bounded_env_int(
            "AI_SYSTEM_REQUESTS_PER_DAY", 2_000, 1, 10_000
        )
    else:
        per_minute = _bounded_env_int("AI_USER_REQUESTS_PER_MINUTE", 10, 1, 120)
        per_day = _bounded_env_int("AI_USER_REQUESTS_PER_DAY", 200, 1, 10_000)
    minute_start = now.replace(second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    minute_count = _increment_request_bucket(db, actor_id, "minute", minute_start)
    day_count = _increment_request_bucket(db, actor_id, "day", day_start)
    background_observe = (
        actor_id == "system-worker"
        and (os.getenv("AI_BACKGROUND_LIMIT_MODE") or "observe").strip().lower()
        != "enforce"
    )
    if minute_count > per_minute and not background_observe:
        db.rollback()
        raise HTTPException(status_code=429, detail="ai_rate_limit_exceeded", headers={"Retry-After": "60"})
    if day_count > per_day and not background_observe:
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


def _reserve_email_request(db: Session, actor_id: str, recipient_count: int) -> None:
    """Durably bound SendGrid sends and recipients across API replicas."""
    now = datetime.utcnow()
    per_minute = _bounded_env_int("EMAIL_SENDS_PER_MINUTE", 5, 1, 60)
    recipients_per_day = _bounded_env_int(
        "EMAIL_RECIPIENTS_PER_DAY", 500, 1, 10_000
    )
    minute_count = _increment_request_bucket(
        db,
        actor_id,
        "email_send_minute",
        now.replace(second=0, microsecond=0),
    )
    day_count = _increment_request_bucket(
        db,
        actor_id,
        "email_recipient_day",
        now.replace(hour=0, minute=0, second=0, microsecond=0),
        amount=recipient_count,
    )
    if minute_count > per_minute or day_count > recipients_per_day:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="email_rate_limit_exceeded",
            headers={"Retry-After": "60" if minute_count > per_minute else "3600"},
        )
    # Failed provider requests still consume quota so repeated failures cannot
    # be used to evade the billable-delivery boundary.
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


def _reserve_survey_public_request(
    db: Session,
    action: str,
    *,
    token: Optional[str] = None,
) -> None:
    """Durably bound public CSAT traffic without retaining capability material.

    Invalid random capabilities consume only the low-cardinality global
    buckets. A digest-scoped bucket is created only after the capability has
    resolved to a real survey, preventing unauthenticated storage amplification.
    """
    if action not in {"lookup", "respond"}:
        raise ValueError("Unknown survey public action")
    now = datetime.utcnow()
    if token is None:
        limits = ((
            f"survey-{action}-global",
            f"survey_{action}_global_minute",
            f"survey_{action}_global_day",
            _bounded_env_int(
                f"SURVEY_{action.upper()}_GLOBAL_PER_MINUTE",
                600 if action == "lookup" else 100,
                1,
                10_000,
            ),
            _bounded_env_int(
                f"SURVEY_{action.upper()}_GLOBAL_PER_DAY",
                50_000 if action == "lookup" else 5_000,
                1,
                1_000_000,
            ),
        ),)
    else:
        candidate_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        limits = ((
            f"survey-{action}:" + candidate_digest[:32],
            f"survey_{action}_minute",
            f"survey_{action}_day",
            30 if action == "lookup" else 5,
            500 if action == "lookup" else 20,
        ),)
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
    # Persist before capability lookup so invalid and replayed requests consume
    # the same durable allowance as successful requests across API replicas.
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
    return shared_terminal_status_names(db)


def _is_terminal_status(db: Session, status: Optional[str]) -> bool:
    return shared_is_terminal_status(db, status)


def _require_demo_ticketing() -> None:
    """Keep production Tickety OPS Tower on the read-only sidecar boundary.

    Demo mode retains local ticket CRUD for the bundled showcase data. In a
    real deployment, Freshservice owns ticket lifecycle and Tickety OPS Tower stores
    only synchronized projections plus local intelligence.
    """
    if settings_module.is_production_mode():
        raise HTTPException(
            status_code=409,
            detail=(
                "Freshservice is the authoritative ticket system; "
                f"{PRODUCT_NAME} production ticket lifecycle is read-only"
            ),
        )


def _lock_ticket_record(db: Session, ticket_id: str) -> TicketRecord:
    """Serialize a local ticket mutation and refresh any waiting snapshot."""
    matched = db.query(TicketRecord).filter(
        TicketRecord.id == ticket_id
    ).update(
        {TicketRecord.updated_at: TicketRecord.updated_at},
        synchronize_session=False,
    )
    if matched != 1:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket = db.query(TicketRecord).filter(
        TicketRecord.id == ticket_id
    ).populate_existing().first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _lock_authorized_ticket_analysis(
    db: Session,
    ticket_id: str,
    user: UserRecord,
) -> tuple[TicketRecord, UserRecord]:
    """Bind an AI operation's authorization to the current ticket owner.

    Durable quota reservations commit before this point. The no-op ticket
    write serializes with assignment changes; refreshing and authorizing while
    that lock is held gives the subsequent analysis claim one unambiguous
    linearization point. The claim commit releases the lock before any LLM
    call, so provider latency never extends the critical section.
    """
    try:
        actor = _lock_user_record(db, user.id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise HTTPException(
            status_code=403,
            detail="Ticket analysis permission changed",
        ) from exc
    if (
        not actor.is_active
        or (actor.role or "").lower() not in _OPERATIONAL_USER_ROLES
    ):
        raise HTTPException(
            status_code=403,
            detail="Ticket analysis permission changed",
        )
    ticket = _lock_ticket_record(db, ticket_id)
    _authorize_ticket_analysis(actor, ticket, db)
    return ticket, actor


def _lock_active_service_reference(
    db: Session,
    service_id: str,
) -> ServiceItemRecord:
    """Lock a catalog reference and reject a concurrent deactivation."""
    if "\x00" in service_id:
        raise HTTPException(status_code=422, detail="Service ID must not contain NUL")
    matched = db.query(ServiceItemRecord).filter(
        ServiceItemRecord.id == service_id,
        ServiceItemRecord.is_active.is_(True),
    ).update(
        {
            ServiceItemRecord.is_active: ServiceItemRecord.is_active,
            ServiceItemRecord.updated_at: ServiceItemRecord.updated_at,
        },
        synchronize_session=False,
    )
    service = db.query(ServiceItemRecord).filter(
        ServiceItemRecord.id == service_id
    ).populate_existing().first()
    if not service:
        raise HTTPException(status_code=404, detail="Service item not found")
    if matched != 1 or not service.is_active:
        raise HTTPException(status_code=409, detail="Service item must be active")
    return service


def _lock_usable_asset_reference(
    db: Session,
    asset_id: str,
) -> AssetRecord:
    """Lock a CMDB reference and reject records retired from the catalog."""
    if "\x00" in asset_id:
        raise HTTPException(status_code=422, detail="Asset ID must not contain NUL")
    matched = db.query(AssetRecord).filter(
        AssetRecord.id == asset_id,
        portable_ascii_lower_expression(AssetRecord.status) != "retired",
    ).update(
        {
            AssetRecord.status: AssetRecord.status,
            AssetRecord.updated_at: AssetRecord.updated_at,
        },
        synchronize_session=False,
    )
    asset = db.query(AssetRecord).filter(
        AssetRecord.id == asset_id
    ).populate_existing().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if matched != 1 or portable_ascii_lower(asset.status) == "retired":
        raise HTTPException(status_code=409, detail="Asset is not usable")
    return asset


def _ticket_has_resolution_history(ticket: TicketRecord) -> bool:
    return bool(
        ticket.resolved_at is not None
        or ticket.resolved_by
        or int(ticket.points_awarded or 0) > 0
        or ticket.points_awarded_sent
    )


def _ticket_retained_dependency(
    db: Session,
    ticket_id: str,
) -> Optional[str]:
    """Return one retained FK table that makes ticket deletion unsafe."""
    for table in sorted(Base.metadata.tables.values(), key=lambda value: value.name):
        ticket_columns = [
            foreign_key.parent
            for foreign_key in table.foreign_keys
            if foreign_key.target_fullname == "tickets.id"
        ]
        for column in ticket_columns:
            if db.execute(
                select(1).select_from(table).where(column == ticket_id).limit(1)
            ).first():
                return table.name
    return None


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
    payload_changes = payload.model_dump(exclude_unset=True)
    supplied_changes = {
        field
        for field, value in payload_changes.items()
        if getattr(ticket, field, None) != value
    }
    _authorize_ticket_mutation(
        user,
        ticket,
        db=db,
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

    # Every reservation above is deliberately durable and may commit. Acquire
    # a changed assignee first (User -> Ticket is also the purge order), then
    # the mutation lock. Recompute and re-authorize from the winner's state so
    # a waiting PATCH cannot overwrite a stale snapshot.
    assignee_lock_acquired = False
    if (
        "assignee_id" in payload_changes
        and payload.assignee_id is not None
        and payload.assignee_id != ticket.assignee_id
    ):
        _lock_active_user_reference(
            db,
            payload.assignee_id,
            label="Ticket assignee",
        )
        assignee_lock_acquired = True
    ticket = _lock_ticket_record(db, ticket_id)
    if (
        "assignee_id" in payload_changes
        and payload.assignee_id is not None
        and payload.assignee_id != ticket.assignee_id
        and not assignee_lock_acquired
    ):
        raise HTTPException(
            status_code=409,
            detail="Ticket assignee changed while saving; retry the update",
        )
    supplied_changes = {
        field
        for field, value in payload_changes.items()
        if getattr(ticket, field, None) != value
    }
    _authorize_ticket_mutation(
        user,
        ticket,
        db=db,
        changed_fields=supplied_changes,
        requested_assignee_id=payload.assignee_id,
    )
    document_input_changed = any(
        field in payload_changes
        and payload_changes[field] is not None
        and getattr(ticket, field, None) != payload_changes[field]
        for field in document_fields
    )
    analysis_input_changed = any(
        field in payload_changes
        and payload_changes[field] is not None
        and getattr(ticket, field, None) != payload_changes[field]
        for field in {"subject", "description"}
    )
    resolution_input_changed = any(
        field in payload_changes
        and payload_changes[field] is not None
        and getattr(ticket, field, None) != payload_changes[field]
        for field in {"priority", "category"}
    )

    if _ticket_has_resolution_history(ticket):
        for lifecycle_field in ("status", "workflow_status"):
            proposed = payload_changes.get(lifecycle_field)
            if (
                proposed is not None
                and proposed != getattr(ticket, lifecycle_field)
                and not _is_terminal_status(db, proposed)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Resolved tickets require a dedicated audited reopen workflow",
                )

    proposed_type = payload_changes.get("ticket_type")
    service_request_protected_fields = {
        "ticket_type", "status", "workflow_status", "service_id",
    }
    if (
        payload.model_fields_set.intersection(service_request_protected_fields)
        and db.query(ServiceRequestRecord.id).filter(
            ServiceRequestRecord.ticket_id == ticket.id
        ).first()
    ):
        raise HTTPException(
            status_code=409,
            detail="Service request lifecycle fields require the dedicated workflow",
        )
    if (
        proposed_type is not None
        and proposed_type != ticket.ticket_type
        and portable_ascii_lower(proposed_type) != "incident"
        and db.query(ProblemTicketLinkRecord.id).filter(
            ProblemTicketLinkRecord.ticket_id == ticket.id
        ).first()
    ):
        raise HTTPException(
            status_code=409,
            detail="Tickets linked to a problem must remain incidents",
        )

    # Ticket -> Service -> Asset is the canonical reference-lock order. An
    # unchanged historical inactive/retired reference remains readable, while
    # a new value must still be usable after any concurrent status change.
    if (
        "service_id" in payload_changes
        and payload.service_id is not None
        and payload.service_id != ticket.service_id
    ):
        _lock_active_service_reference(db, payload.service_id)
    if (
        "asset_id" in payload_changes
        and payload.asset_id is not None
        and payload.asset_id != ticket.asset_id
    ):
        _lock_usable_asset_reference(db, payload.asset_id)

    actor_name = user.name
    # Track changes for audit log
    for field in [
        "subject", "description", "status", "workflow_status", "ai_review_state",
        "priority", "ticket_type", "impact", "urgency", "assignee_id", "service_id",
        "asset_id", "category", "tags", "response_due_at", "resolution_due_at", "due_by",
    ]:
        val = getattr(payload, field, None)
        supplied = val is not None or (
            field in {"service_id", "asset_id"}
            and field in payload.model_fields_set
        )
        if supplied:
            old = getattr(ticket, field, None)
            if old != val:
                db.add(TicketAuditLogRecord(
                    ticket_id=ticket.id, field=field,
                    old_value=str(old) if old else None,
                    new_value=str(val) if val is not None else None,
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
        mark_terminal_ai_not_applicable(ticket)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ticket references changed while saving",
        ) from exc
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
    if not db.query(TicketRecord.id).filter(TicketRecord.id == ticket_id).first():
        raise HTTPException(status_code=404, detail="Ticket not found")
    if _ticket_retained_dependency(db, ticket_id):
        raise HTTPException(
            status_code=409,
            detail="Ticket has retained history and cannot be deleted",
        )

    ticket = _lock_ticket_record(db, ticket_id)
    # Recheck after waiting for a concurrent ticket owner (notably service-
    # request creation) so a dependent committed while we waited returns 409.
    if _ticket_retained_dependency(db, ticket_id):
        raise HTTPException(
            status_code=409,
            detail="Ticket has retained history and cannot be deleted",
        )
    db.delete(ticket)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ticket gained retained history while deletion was pending",
        ) from exc
    # Search evidence is removed only after the relational delete succeeds;
    # failed FK/history checks must never erase the surviving ticket's index.
    ticket_vectors.delete_ticket_documents(db, ticket_id)
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
    _authorize_ticket_view(user, ticket)
    query = db.query(TicketCommentRecord).filter(
        TicketCommentRecord.ticket_id == ticket_id
    )
    if (user.role or "").lower() not in {"admin", "supervisor"}:
        # Private notes are supervisor material; agents never see them.
        query = query.filter(TicketCommentRecord.is_private.is_(False))
    comments = query.order_by(
        TicketCommentRecord.created_at.desc(), TicketCommentRecord.id.desc()
    ).offset(offset).limit(limit).all()
    _enrich_comments(db, ticket, comments)
    return list(reversed(comments))


@app.get("/tickets/{ticket_id}/attachments", response_model=List[TicketAttachment])
async def list_ticket_attachments(
    ticket_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_view(user, ticket)
    rows = db.query(ExternalAttachmentRecord).filter(
        ExternalAttachmentRecord.ticket_id == ticket_id,
        ExternalAttachmentRecord.storage_status != "superseded",
    ).order_by(
        ExternalAttachmentRecord.created_at.asc(),
        ExternalAttachmentRecord.id.asc(),
    ).all()
    if (user.role or "").lower() not in {"admin", "supervisor"}:
        private_owner_ids = {
            row.external_id for row in db.query(ExternalConversationRecord).filter(
                ExternalConversationRecord.ticket_id == ticket_id,
                ExternalConversationRecord.is_private.is_(True),
            ).all()
        }
        rows = [
            row for row in rows
            if row.owner_type != "conversation"
            or row.owner_external_id not in private_owner_ids
        ]
    return [
        TicketAttachment(
            id=row.id,
            ticket_id=row.ticket_id,
            owner_type=row.owner_type,
            owner_external_id=row.owner_external_id,
            external_id=row.external_id,
            name=row.file_name,
            content_type=row.content_type,
            size=row.declared_size,
            stored_size=row.stored_size,
            status=row.storage_status,
            created_at=row.created_at,
            stored_at=row.stored_at,
        )
        for row in rows
    ]


@app.get("/tickets/{ticket_id}/attachments/{attachment_id}")
async def download_ticket_attachment(
    ticket_id: str,
    attachment_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
):
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_view(user, ticket)
    row = db.query(ExternalAttachmentRecord).filter(
        ExternalAttachmentRecord.id == attachment_id,
        ExternalAttachmentRecord.ticket_id == ticket_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if row.owner_type == "conversation" and (user.role or "").lower() not in {
        "admin", "supervisor",
    }:
        private_owner = db.query(ExternalConversationRecord.id).filter(
            ExternalConversationRecord.ticket_id == ticket_id,
            ExternalConversationRecord.external_id == row.owner_external_id,
            ExternalConversationRecord.is_private.is_(True),
        ).first()
        if private_owner:
            raise HTTPException(status_code=404, detail="Attachment not found")
    if row.storage_status != "stored" or not row.blob_key:
        raise HTTPException(status_code=409, detail="Attachment copy is not ready")
    try:
        content = AzureBlobAttachmentStore().download(row.blob_key)
    except AttachmentStorageError as exc:
        raise HTTPException(status_code=503, detail="Attachment storage is unavailable") from exc
    except Exception as exc:
        print(f"[attachments] blob download failed kind={type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Attachment storage is unavailable") from exc
    content_type = (row.content_type or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", content_type):
        content_type = "application/octet-stream"
    inline_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    disposition = "inline" if content_type.lower() in inline_types else "attachment"
    fallback_name = re.sub(r"[^A-Za-z0-9._-]+", "_", row.file_name) or "attachment"
    encoded_name = urllib.parse.quote(row.file_name, safe="")
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f'{disposition}; filename="{fallback_name[:180]}"; '
                f"filename*=UTF-8''{encoded_name}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


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
    _authorize_ticket_mutation(user, ticket, db=db)

    # Admission records are intentionally durable and may commit the current
    # transaction. Finish every reservation before taking the ticket lock, so
    # no quota commit can release the serialization boundary underneath the
    # evidence write.
    _reserve_index_write_request(db, user.id)
    _reserve_embedding_request(
        db,
        user,
        "ticket_comment_embedding",
        eligible=(
            not payload.is_private
            or ticket_vectors.private_comment_indexing_enabled()
        ),
    )

    # A reservation may have waited while the ticket was reassigned. Refresh
    # under the same mutation lock used by PATCH/bulk assignment, then enforce
    # authorization and duplicate detection against the winning state.
    ticket = _lock_ticket_record(db, ticket_id)
    _authorize_ticket_mutation(user, ticket, db=db)
    _reject_duplicate_recent_comment(
        db,
        ticket_id=ticket_id,
        author_id=user.id,
        body=payload.body,
        is_private=payload.is_private,
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
    _authorize_ticket_analysis(user, ticket, db)
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
    if (
        payload.action == "close"
        and db.query(ServiceRequestRecord.id).filter(
            ServiceRequestRecord.ticket_id.in_(ticket_ids)
        ).first()
    ):
        raise HTTPException(
            status_code=409,
            detail="Service request tickets require the dedicated workflow",
        )

    if payload.action != "close" and not payload.value:
        raise HTTPException(status_code=422, detail="A value is required for this bulk action")
    if payload.action == "assign":
        assignee = db.query(UserRecord).filter(
            UserRecord.id == payload.value,
        ).first()
        if (
            not assignee
            or not assignee.is_active
            or (assignee.role or "").lower() not in _OPERATIONAL_USER_ROLES
        ):
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

    # Quota reservations above may commit. Reacquire every ticket in stable
    # order, then recheck the SR invariant after any competing creator exits.
    if payload.action == "assign" and payload.value:
        _lock_active_user_reference(
            db,
            payload.value,
            label="Ticket assignee",
        )
    tickets = [
        _lock_ticket_record(db, ticket_id)
        for ticket_id in sorted(ticket_ids)
    ]
    if (
        payload.action == "close"
        and db.query(ServiceRequestRecord.id).filter(
            ServiceRequestRecord.ticket_id.in_(ticket_ids)
        ).first()
    ):
        raise HTTPException(
            status_code=409,
            detail="Service request tickets require the dedicated workflow",
        )

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
    if any((
        _automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE"),
        _automation_enabled("AUTO_SUMMARIZE_ENABLED"),
        _automation_enabled("AUTO_ROUTE_ENABLED"),
        _automation_enabled("AUTO_RESOLVE_ENABLED"),
    )):
        # Manual creation can immediately invoke the LLM pipeline. Charge the
        # authenticated caller before persisting the ticket so this indirect
        # path cannot bypass the per-user AI request budget.
        _reserve_ai_request(db, user.id, "ticket_create_auto_processing")
    _reserve_embedding_request(db, user, "ticket_create_embedding")
    # Durable quota reservations above may commit, so acquire reference locks
    # only after them and hold User -> Service -> Asset through the commit.
    if (user.role or "").lower() == "agent":
        _lock_active_user_reference(db, user.id, label="Ticket assignee")
    if payload.service_id is not None:
        _lock_active_service_reference(db, payload.service_id)
    if payload.asset_id is not None:
        _lock_usable_asset_reference(db, payload.asset_id)
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
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ticket identity or references changed while saving",
        ) from exc
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
    terminal: bool = False,
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
    ticket.ai_error = merge_terminal_ai_policy_errors(ticket.ai_error, error_code)
    requested = set(artifacts)
    if ticket.ai_status == "queued":
        requested.update(
            item
            for item in (ticket.ai_requested_artifacts or "").split(",")
            if item
        )
    ticket.ai_requested_artifacts = ",".join(sorted(requested))
    if terminal or attempts >= max_attempts:
        ticket.ai_status = "dead_letter"
        ticket.ai_next_attempt_at = None
    else:
        ticket.ai_status = "queued"
        retry_at = datetime.utcnow() + timedelta(
            seconds=min(3600, 30 * (2 ** (attempts - 1)))
        )
        ticket.ai_next_attempt_at = max(
            value for value in (ticket.ai_next_attempt_at, retry_at) if value
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
    ticket.ai_error = merge_terminal_ai_policy_errors(
        ticket.ai_error,
        "provider_capacity",
    )
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
    if isinstance(exc, LLMContentFilteredError):
        return "content_filtered"
    if isinstance(exc, LLMProviderRejectedError):
        return "provider_rejected"
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
    if _is_terminal_status(db, ticket.status):
        mark_terminal_ai_not_applicable(ticket)
        db.commit()
        return
    if not force and not any((
        _automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE"),
        _automation_enabled("AUTO_SUMMARIZE_ENABLED"),
        _automation_enabled("AUTO_ROUTE_ENABLED"),
        _automation_enabled("AUTO_RESOLVE_ENABLED"),
    )):
        return
    requested = {
        item for item in (ticket.ai_requested_artifacts or "").split(",") if item
    }
    artifacts = requested
    if not artifacts:
        artifacts = set()
        stale = (ticket.ai_status or "").strip().lower() in {
            "stale", "legacy_stale", "provenance_unknown",
        }
        if (stale or not ticket.ai_reasoning) and _automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE"):
            artifacts.add("triage")
        if (stale or not ticket.summary) and _automation_enabled("AUTO_SUMMARIZE_ENABLED"):
            artifacts.add("summary")
        if (stale or not ticket.recommended_solution) and _automation_enabled("AUTO_RESOLVE_ENABLED"):
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
    ticket.escalation_risk = intel.escalation_risk(
        ticket,
        terminal_statuses=_terminal_status_names(db),
    )
    ticket.escalation_risk_backfilled_at = datetime.utcnow()

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


def _apply_ticket_routing(ticket: TicketRecord, route_data: Dict[str, Any]) -> None:
    """Persist a validated advisory resolver-group decision."""
    ticket.ai_suggested_team = route_data["primary_group"]
    ticket.ai_secondary_team = route_data["secondary_group"]
    ticket.ai_routing_confidence = route_data["confidence"]
    ticket.ai_business_context = route_data["business_context"]
    ticket.ai_routing_scope = route_data["scope"]
    ticket.ai_affected_service = route_data["affected_service"]
    ticket.ai_failure_domain = route_data["failure_domain"]
    ticket.ai_routing_reason = route_data["reason"]


def _routing_result_payload(ticket: TicketRecord) -> Optional[Dict[str, Any]]:
    """Project only complete, closed-set routing records."""
    if (
        ticket.ai_suggested_team not in intel.AI_RESOLVER_TEAMS
        or ticket.ai_routing_confidence is None
        or not ticket.ai_business_context
        or not ticket.ai_routing_scope
        or not ticket.ai_affected_service
        or not ticket.ai_failure_domain
        or not ticket.ai_routing_reason
    ):
        return None
    candidate = {
        "primary_group": ticket.ai_suggested_team,
        "secondary_group": ticket.ai_secondary_team,
        "confidence": ticket.ai_routing_confidence,
        "business_context": ticket.ai_business_context,
        "scope": ticket.ai_routing_scope,
        "affected_service": ticket.ai_affected_service,
        "failure_domain": ticket.ai_failure_domain,
        "reason": ticket.ai_routing_reason,
    }
    try:
        return ResolverRoutingAnalysis.model_validate(candidate).model_dump()
    except ValueError:
        return None


def _routing_payload_content_hash(route_data: Dict[str, Any]) -> str:
    serialized = json.dumps(
        route_data,
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _triage_result_payload(
    ticket: TicketRecord,
    analysis_data: Dict[str, Any],
    route_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ticket_id": ticket.id,
        "sentiment": analysis_data.get("sentiment", "Neutral"),
        "category": analysis_data.get("category", "Other"),
        "priority": analysis_data.get("priority", "P3"),
        "mood": analysis_data.get("mood", "neutral"),
        "complexity": analysis_data.get("complexity", 1),
        "action": analysis_data.get("action", "respond"),
        # Compatibility field for existing clients. It projects only a route
        # whose exact artifact provenance was checked by the caller.
        "recommended_team": route_data["primary_group"]
        if route_data is not None
        else intel.UNROUTED_REVIEW_TEAM,
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
        "freshservice_category": ticket.external_category or "",
        "freshservice_subcategory": ticket.external_subcategory or "",
        "freshservice_item_category": ticket.external_item_category or "",
        "routing_business_context": routing_business_context(
            ticket.external_requester_email or ticket.reporter
        ),
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
        "pipeline": _artifact_pipeline_version(artifact),
    }
    if artifact == "route":
        payload.update({
            "provider_category": ticket.external_category or "",
            "provider_subcategory": ticket.external_subcategory or "",
            "provider_item_category": ticket.external_item_category or "",
        })
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
            "public_thread": routing_public_thread(
                ticket.external_conversation_text or ""
            ),
            "routing_business_context": routing_business_context(
                ticket.external_requester_email or ticket.reporter
            ),
        })
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _artifact_is_current(db: Session, ticket: TicketRecord, artifact: str) -> bool:
    field_present = {
        "triage": bool(ticket.ai_reasoning),
        "summary": bool(ticket.summary),
        "route": _routing_result_payload(ticket) is not None,
        "resolution": bool(ticket.recommended_solution),
    }.get(artifact, False)
    if not field_present or ticket.ai_status in {"legacy_stale", "provenance_unknown", "stale"}:
        return False
    query = db.query(AIArtifactRecord).filter(
        AIArtifactRecord.ticket_id == ticket.id,
        AIArtifactRecord.artifact == artifact,
        AIArtifactRecord.input_hash == _artifact_input_hash(ticket, artifact),
        AIArtifactRecord.pipeline_version == _artifact_pipeline_version(artifact),
        AIArtifactRecord.model == _llm_cache_identity(),
        AIArtifactRecord.active.is_(True),
    )
    if artifact == "route":
        route_payload = _routing_result_payload(ticket)
        if route_payload is None or not ticket.ai_routing_input_hash:
            return False
        query = query.filter(
            AIArtifactRecord.input_hash == ticket.ai_routing_input_hash,
            AIArtifactRecord.content_hash
            == _routing_payload_content_hash(route_payload)
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
    retained_policy_errors = merge_terminal_ai_policy_errors(ticket.ai_error)
    changed = query.update(
        {
            TicketRecord.ai_status: "running",
            TicketRecord.ai_claim_id: claim_id,
            TicketRecord.ai_lease_expires_at: now + timedelta(seconds=lease_seconds),
            TicketRecord.ai_started_at: now,
            TicketRecord.ai_error: retained_policy_errors,
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
    current_route = (
        _routing_result_payload(ticket)
        if _artifact_is_current(db, ticket, "route")
        else None
    )
    return {
        "ticket_id": ticket.id,
        "triage": _triage_result_payload(ticket, triage_data, current_route),
        "summary": ticket.summary,
        "route": current_route,
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
    input_hash = _artifact_input_hash(ticket, artifact)
    if artifact == "route":
        # This persisted digest lets exact-provenance readers validate large
        # historical sets without materializing ticket bodies or transcripts.
        ticket.ai_routing_input_hash = input_hash
    serialized = json.dumps(content, sort_keys=True, default=str, ensure_ascii=False)
    db.add(AIArtifactRecord(
        ticket_id=ticket.id,
        artifact=artifact,
        input_hash=input_hash,
        pipeline_version=_artifact_pipeline_version(artifact),
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


def _release_analysis_claim_for_access_change(
    ticket: TicketRecord,
    db: Session,
) -> None:
    """Drop only the in-flight claim while preserving prior valid artifacts."""
    ticket.ai_status = (
        "completed"
        if ticket.ai_reasoning and ticket.summary and ticket.recommended_solution
        else "triage_completed"
        if ticket.ai_reasoning
        else None
    )
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_requested_artifacts = None
    ticket.ai_next_attempt_at = None
    ticket.ai_error = merge_terminal_ai_policy_errors(ticket.ai_error)
    db.commit()


def _ensure_analysis_input_current(
    ticket: TicketRecord,
    db: Session,
    source_hash: str,
    claim_id: str,
    *,
    analysis_actor_id: Optional[str] = None,
) -> TicketRecord:
    # Human-triggered work follows the same User -> Ticket order as assignment
    # and account lifecycle writes. This catches deactivation, role changes,
    # and reassignment while provider work was in flight without holding any
    # database lock across that provider call.
    actor: Optional[UserRecord] = None
    if analysis_actor_id:
        try:
            actor = _lock_user_record(db, analysis_actor_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            db.rollback()
            claimed_ticket = db.query(TicketRecord).filter(
                TicketRecord.id == ticket.id,
                TicketRecord.ai_claim_id == claim_id,
                TicketRecord.ai_status == "running",
            ).with_for_update().populate_existing().first()
            if claimed_ticket:
                _release_analysis_claim_for_access_change(claimed_ticket, db)
            raise HTTPException(
                status_code=409,
                detail="analysis_access_changed",
            ) from exc

    ticket = db.query(TicketRecord).filter(
        TicketRecord.id == ticket.id,
        TicketRecord.ai_claim_id == claim_id,
        TicketRecord.ai_status == "running",
    ).with_for_update().populate_existing().first()
    if not ticket:
        raise HTTPException(status_code=409, detail="analysis_claim_lost")
    if ticket.ai_claim_id != claim_id or ticket.ai_status != "running":
        raise HTTPException(status_code=409, detail="analysis_claim_lost")
    if actor is not None:
        try:
            if (
                not actor.is_active
                or (actor.role or "").lower() not in _OPERATIONAL_USER_ROLES
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Ticket analysis permission changed",
                )
            _authorize_ticket_analysis(actor, ticket, db)
        except HTTPException as exc:
            _release_analysis_claim_for_access_change(ticket, db)
            raise HTTPException(
                status_code=409,
                detail="analysis_access_changed",
            ) from exc
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
    analysis_actor_id: Optional[str] = None,
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
        persisted_artifacts = artifacts - {"refresh"}
        artifact_cached = bool(persisted_artifacts) and all(
            _artifact_is_current(db, ticket, artifact)
            for artifact in persisted_artifacts
        )
        if artifact_cached:
            cached = _cached_analysis_payload(ticket, db)
            # API callers may hold the authorization/assignment lock here.
            # Cached work crosses no provider boundary, so release it as soon
            # as the response has been assembled.
            db.commit()
            return cached
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
    successful_artifacts: set[str] = set()
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
    route = (
        _routing_result_payload(ticket)
        if _artifact_is_current(db, ticket, "route")
        else None
    )
    completed_before_triage: set[str] = set()
    route_preprocessed = False
    # Resolver routing has no dependency on the broader triage classification.
    # Persist it first when both were requested so a malformed/filtered triage
    # result cannot suppress an otherwise valid resolver recommendation.
    if "triage" in artifacts and "route" in artifacts:
        route_preprocessed = True
        await emit("route", "active")
        ticket_id = ticket.id
        try:
            db.expunge(ticket)
            db.close()
            route_result = await asyncio.wait_for(
                engine.route_ticket({
                    "subject": ticket.subject,
                    "description": ticket.description,
                    "public_thread": ticket.external_conversation_text or "",
                    "freshservice_category": ticket.external_category or "",
                    "freshservice_subcategory": ticket.external_subcategory or "",
                    "freshservice_item_category": ticket.external_item_category or "",
                    "requester_email": ticket.external_requester_email or ticket.reporter,
                }),
                timeout=_pipeline_remaining(pipeline_deadline),
            )
            ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            ticket = _ensure_analysis_input_current(
                ticket,
                db,
                source_hash,
                claim_id,
                analysis_actor_id=analysis_actor_id,
            )
            route = route_result
            _apply_ticket_routing(ticket, route)
            _record_ai_artifact(db, ticket, "route", route, source_hash)
            db.commit()
            db.refresh(ticket)
            completed_before_triage.add("route")
            successful_artifacts.add("route")
            await emit("route", "done")
        except Exception as exc:
            db.rollback()
            claim_terminal = (
                isinstance(exc, HTTPException)
                and exc.detail in {
                    "analysis_input_changed",
                    "analysis_claim_lost",
                    "analysis_access_changed",
                }
            )
            if claim_terminal:
                await emit("route", "error")
                raise
            ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            ticket = _ensure_analysis_input_current(
                ticket,
                db,
                source_hash,
                claim_id,
                analysis_actor_id=analysis_actor_id,
            )
            error_code = _analysis_step_error_code(exc)
            errors.append({"step": "route", "error": error_code})
            if isinstance(exc, LLMCapacityError):
                capacity_deferrals["route"] = exc.retry_after_seconds
            event = "deferred" if isinstance(exc, LLMCapacityError) else "failed"
            print(
                f"[analysis] artifact {event} ticket={ticket.id[:8]} "
                f"step=route code={error_code}"
            )
            await emit("route", "error")
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
                        "freshservice_category": ticket.external_category or "",
                        "freshservice_subcategory": ticket.external_subcategory or "",
                        "freshservice_item_category": ticket.external_item_category or "",
                    },
                    kb_info=_ticket_kb_context(ticket),
                ),
                timeout=_pipeline_remaining(pipeline_deadline),
            )
            ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            ticket = _ensure_analysis_input_current(
                ticket,
                db,
                source_hash,
                claim_id,
                analysis_actor_id=analysis_actor_id,
            )
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
            successful_artifacts.add("triage")
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
                and exc.detail in {
                    "analysis_input_changed",
                    "analysis_claim_lost",
                    "analysis_access_changed",
                }
            )
            if not claim_terminal:
                retry_artifacts = requested_artifacts - completed_before_triage
                error_code = _analysis_step_error_code(exc)
                error_signature = f"triage:{error_code}"
                event = "deferred" if isinstance(exc, LLMCapacityError) else "failed"
                print(
                    f"[analysis] artifact {event} ticket={ticket.id[:8]} "
                    f"step=triage code={error_code}"
                )
                if isinstance(exc, LLMContentFilteredError):
                    combined_errors = [*errors, {
                        "step": "triage",
                        "error": "content_filtered",
                    }]
                    filtered = db.query(TicketRecord).filter(
                        TicketRecord.id == ticket.id,
                        TicketRecord.ai_claim_id == claim_id,
                    ).with_for_update().first()
                    if filtered:
                        filtered.ai_status = (
                            "triage_completed" if filtered.ai_reasoning else "partial"
                        )
                        filtered.ai_error = merge_terminal_ai_policy_errors(
                            filtered.ai_error,
                            _analysis_error_signature(combined_errors),
                            cleared_artifacts=successful_artifacts,
                        )
                        filtered.ai_attempts = 0
                        filtered.ai_requested_artifacts = None
                        filtered.ai_next_attempt_at = None
                        filtered.ai_claim_id = None
                        filtered.ai_lease_expires_at = None
                        db.commit()
                    earlier_failures = {
                        error["step"] for error in errors
                        if error["step"] != "triage"
                    }
                    if earlier_failures:
                        earlier_errors = [
                            error for error in errors
                            if error["step"] in earlier_failures
                        ]
                        earlier_signature = _analysis_error_signature(earlier_errors)
                        earlier_codes = {error["error"] for error in earlier_errors}
                        if earlier_codes == {"content_filtered"}:
                            # The artifact-scoped terminal marker was persisted
                            # above; never redispatch policy-filtered content.
                            pass
                        elif earlier_failures.issubset(capacity_deferrals):
                            _defer_ai_capacity(
                                db,
                                ticket.id,
                                earlier_failures,
                                max(capacity_deferrals[step] for step in earlier_failures),
                            )
                        else:
                            _schedule_ai_retry(
                                db,
                                ticket.id,
                                earlier_failures,
                                earlier_signature,
                                terminal=earlier_codes.issubset({
                                    "invalid_input", "provider_rejected",
                                }),
                            )
                elif isinstance(exc, LLMCapacityError):
                    _defer_ai_capacity(
                        db,
                        ticket.id,
                        retry_artifacts,
                        exc.retry_after_seconds,
                        expected_claim_id=claim_id,
                    )
                else:
                    _schedule_ai_retry(
                        db,
                        ticket.id,
                        retry_artifacts,
                        error_signature,
                        expected_claim_id=claim_id,
                        terminal=isinstance(
                            exc, (LLMInvalidInputError, LLMProviderRejectedError)
                        ),
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
    if "route" in artifacts and not route_preprocessed:
        await emit("route", "active")
        tasks["route"] = asyncio.create_task(
            engine.route_ticket({
                "subject": ticket.subject,
                "description": ticket.description,
                "public_thread": ticket.external_conversation_text or "",
                "freshservice_category": ticket.external_category or "",
                "freshservice_subcategory": ticket.external_subcategory or "",
                "freshservice_item_category": ticket.external_item_category or "",
                "requester_email": ticket.external_requester_email or ticket.reporter,
            })
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
                terminal=isinstance(
                    exc, (LLMInvalidInputError, LLMProviderRejectedError)
                ),
            )
            raise
        task_results = dict(zip(tasks, results))
        ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket = _ensure_analysis_input_current(
            ticket,
            db,
            source_hash,
            claim_id,
            analysis_actor_id=analysis_actor_id,
        )
        if "summary" in task_results:
            result = task_results["summary"]
            if isinstance(result, Exception):
                error_code = _analysis_step_error_code(result)
                errors.append({"step": "summary", "error": error_code})
                if isinstance(result, LLMCapacityError):
                    capacity_deferrals["summary"] = result.retry_after_seconds
                event = "deferred" if isinstance(result, LLMCapacityError) else "failed"
                print(
                    f"[analysis] artifact {event} ticket={ticket.id[:8]} "
                    f"step=summary code={error_code}"
                )
                await emit("summary", "error")
            else:
                summary = result
                if summary:
                    ticket.summary = summary
                    _record_ai_artifact(db, ticket, "summary", summary, source_hash)
                    successful_artifacts.add("summary")
                await emit("summary", "done")
        if "resolution" in task_results:
            result = task_results["resolution"]
            if isinstance(result, Exception):
                error_code = _analysis_step_error_code(result)
                errors.append({"step": "resolution", "error": error_code})
                if isinstance(result, LLMCapacityError):
                    capacity_deferrals["resolution"] = result.retry_after_seconds
                event = "deferred" if isinstance(result, LLMCapacityError) else "failed"
                print(
                    f"[analysis] artifact {event} ticket={ticket.id[:8]} "
                    f"step=resolution code={error_code}"
                )
                await emit("resolution", "error")
            else:
                plan_dict = result
                ticket.recommended_solution = json.dumps(plan_dict)
                _record_ai_artifact(db, ticket, "resolution", plan_dict, source_hash)
                successful_artifacts.add("resolution")
                await emit("resolution", "done")
        if "route" in task_results:
            result = task_results["route"]
            if isinstance(result, Exception):
                error_code = _analysis_step_error_code(result)
                errors.append({"step": "route", "error": error_code})
                if isinstance(result, LLMCapacityError):
                    capacity_deferrals["route"] = result.retry_after_seconds
                event = "deferred" if isinstance(result, LLMCapacityError) else "failed"
                print(
                    f"[analysis] artifact {event} ticket={ticket.id[:8]} "
                    f"step=route code={error_code}"
                )
                await emit("route", "error")
            else:
                route = result
                _apply_ticket_routing(ticket, route)
                _record_ai_artifact(db, ticket, "route", route, source_hash)
                successful_artifacts.add("route")
                await emit("route", "done")
        db.commit()
        db.refresh(ticket)

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
    ticket = _ensure_analysis_input_current(
        ticket,
        db,
        source_hash,
        claim_id,
        analysis_actor_id=analysis_actor_id,
    )
    ticket.ai_source_hash = source_hash
    ticket.ai_pipeline_version = AI_PIPELINE_VERSION
    ticket.ai_model = _llm_cache_identity()
    complete = bool(ticket.ai_reasoning and ticket.summary and ticket.recommended_solution)
    ticket.ai_status = (
        "partial" if errors else "completed" if complete else "triage_completed"
    )
    error_signature = _analysis_error_signature(errors)
    ticket.ai_error = merge_terminal_ai_policy_errors(
        ticket.ai_error,
        error_signature or None,
        cleared_artifacts=successful_artifacts,
    )
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
        errors_by_artifact = {
            error["step"]: error["error"]
            for error in errors
            if error["step"] in failed_artifacts
        }
        content_filtered_artifacts = {
            artifact for artifact, code in errors_by_artifact.items()
            if code == "content_filtered"
        }
        terminal_artifacts = {
            artifact for artifact, code in errors_by_artifact.items()
            if code in {"invalid_input", "provider_rejected"}
        }
        capacity_artifacts = {
            artifact for artifact in failed_artifacts
            if artifact in capacity_deferrals
        }
        transient_artifacts = (
            failed_artifacts
            - content_filtered_artifacts
            - terminal_artifacts
            - capacity_artifacts
        )
        retryable_artifacts = capacity_artifacts | transient_artifacts
        if retryable_artifacts:
            # Artifact outcomes are independent: terminal policy/validation
            # failures remain recorded but are never included in a retry.
            if capacity_artifacts:
                _defer_ai_capacity(
                    db,
                    ticket.id,
                    capacity_artifacts,
                    max(
                        capacity_deferrals[artifact]
                        for artifact in capacity_artifacts
                    ),
                )
            if transient_artifacts:
                transient_signature = _analysis_error_signature([
                    error for error in errors
                    if error["step"] in transient_artifacts
                ])
                _schedule_ai_retry(
                    db,
                    ticket.id,
                    transient_artifacts,
                    transient_signature,
                )
        elif terminal_artifacts:
            terminal_signature = _analysis_error_signature([
                error for error in errors
                if error["step"] in terminal_artifacts
            ])
            _schedule_ai_retry(
                db,
                ticket.id,
                terminal_artifacts,
                terminal_signature,
                terminal=True,
            )
        elif failed_artifacts == content_filtered_artifacts:
            # A provider safety filter is an intentional terminal outcome, not
            # an unhealthy workflow or a reason to bypass policy with retries.
            # Keep any completed triage/routing useful and surface the bounded
            # diagnostic on the ticket without adding it to AI attention.
            filtered = db.query(TicketRecord).filter(
                TicketRecord.id == ticket.id
            ).with_for_update().first()
            if filtered:
                filtered.ai_status = (
                    "triage_completed" if filtered.ai_reasoning else "partial"
                )
                filtered.ai_error = merge_terminal_ai_policy_errors(
                    filtered.ai_error,
                    error_signature,
                    cleared_artifacts=successful_artifacts,
                )
                filtered.ai_attempts = 0
                filtered.ai_requested_artifacts = None
                filtered.ai_next_attempt_at = None
                filtered.ai_claim_id = None
                filtered.ai_lease_expires_at = None
                db.commit()

    if errors and len(requested_artifacts) == 1:
        if failed_artifacts and failed_artifacts.issubset(capacity_deferrals):
            exc = LLMCapacityError(
                "AI artifact generation deferred by provider capacity",
                max(capacity_deferrals.values()),
            )
        else:
            exc = LLMUnavailableError("AI artifact generation failed")
        setattr(exc, "analysis_claim_id", claim_id)
        raise exc

    return {
        "ticket_id": ticket.id,
        "triage": _triage_result_payload(ticket, analysis_data, route),
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
    _authorize_ticket_analysis(_user, ticket, db)
    _reserve_ai_request(db, _user.id, "triage")
    ticket, _user = _lock_authorized_ticket_analysis(db, ticket_id, _user)

    result = await _run_ticket_analysis(
        ticket,
        db,
        force=force,
        artifacts={"triage"},
        analysis_actor_id=_user.id,
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
    _authorize_ticket_analysis(_user, ticket, db)
    _reserve_ai_request(db, _user.id, "full_analysis")
    ticket, _user = _lock_authorized_ticket_analysis(db, ticket_id, _user)
    return await _run_ticket_analysis(
        ticket,
        db,
        force=force,
        analysis_actor_id=_user.id,
    )


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
    email = normalize_user_email(payload.email)
    matches = db.query(UserRecord).filter(
        UserRecord.email_key == email
    ).limit(2).all()
    user = matches[0] if len(matches) == 1 else None
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


def _sso_group_access(identity: sso_service.OidcIdentity, provider_type: str) -> str | None:
    allowed = sso_service.allowed_group_ids(provider_type)
    if not allowed:
        return None
    if identity.groups_overage:
        return "group_claim_overage"
    if not allowed.intersection(identity.groups):
        return "group_not_allowed"
    return None


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

    identity_email = normalize_user_email(identity.email)
    # Migration 0025 enforces both canonical equality and uniqueness in the
    # database, so SSO never falls back to an unkeyed or drifted email row.
    matching_users = db.query(UserRecord).filter(
        UserRecord.email_key == identity_email,
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
            id=f"u-{_uuid.uuid4().hex}",
            email=identity_email,
            email_key=identity_email,
            name=identity.name or identity.email,
            role="agent",
            is_active=True,
            password_hash="",
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            user = db.query(UserRecord).filter(
                UserRecord.email_key == identity_email,
                UserRecord.is_active.is_(True),
            ).first()
            if not user:
                raise PermissionError("identity_conflict")

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
    group_error = _sso_group_access(identity, config.provider_type)
    if group_error:
        return _sso_failure_response(group_error, next_path)
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
    # ranked by retrieval, and Tickety OPS Tower emits only a deterministic review step.
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


def _user_external_identity_link_payload(
    link: UserExternalIdentityLinkRecord,
    external_user: ExternalUserRecord,
) -> UserExternalIdentityLinkOut:
    return UserExternalIdentityLinkOut(
        id=link.id,
        user_id=link.user_id,
        external_user_id=link.external_user_id,
        binding_id=link.binding_id,
        provider=link.provider,
        external_id=external_user.external_id,
        external_name=external_user.name,
        external_email=external_user.email,
        created_by=link.created_by,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


@app.get(
    "/admin/agent-identity-links",
    response_model=List[UserExternalIdentityLinkOut],
)
async def list_agent_identity_links(
    user_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin")),
):
    query = db.query(
        UserExternalIdentityLinkRecord,
        ExternalUserRecord,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id == UserExternalIdentityLinkRecord.external_user_id,
    )
    if user_id:
        query = query.filter(UserExternalIdentityLinkRecord.user_id == user_id)
    rows = query.order_by(
        UserExternalIdentityLinkRecord.user_id,
        UserExternalIdentityLinkRecord.provider,
    ).all()
    return [
        _user_external_identity_link_payload(link, external_user)
        for link, external_user in rows
    ]


@app.put(
    "/admin/agent-identity-links/{user_id}",
    response_model=UserExternalIdentityLinkOut,
)
async def set_agent_identity_link(
    user_id: str,
    payload: UserExternalIdentityLinkUpdate,
    db: Session = Depends(get_db),
    actor: UserRecord = Depends(require_authenticated_role("admin")),
):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (user.role or "").lower() not in {"agent", "supervisor", "admin"}:
        raise HTTPException(status_code=422, detail="Only operational users can receive work identities")
    external_user = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.id == payload.external_user_id,
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
    ).first()
    if not external_user:
        raise HTTPException(status_code=404, detail="Active external agent not found")
    claimed = db.query(UserExternalIdentityLinkRecord).filter(
        UserExternalIdentityLinkRecord.external_user_id == external_user.id,
        UserExternalIdentityLinkRecord.user_id != user.id,
    ).first()
    if claimed:
        raise HTTPException(
            status_code=409,
            detail=f"That external agent is already linked to another {PRODUCT_NAME} user",
        )
    now = datetime.utcnow()
    link = db.query(UserExternalIdentityLinkRecord).filter(
        UserExternalIdentityLinkRecord.user_id == user.id,
        UserExternalIdentityLinkRecord.binding_id == external_user.binding_id,
        UserExternalIdentityLinkRecord.provider == external_user.provider,
    ).first()
    previous_external_user_id = link.external_user_id if link else None
    if link is None:
        link = UserExternalIdentityLinkRecord(
            user_id=user.id,
            external_user_id=external_user.id,
            binding_id=external_user.binding_id,
            provider=external_user.provider,
            created_by=actor.id,
            created_at=now,
            updated_at=now,
        )
        db.add(link)
    else:
        link.external_user_id = external_user.id
        link.updated_at = now
    db.add(UserExternalIdentityAuditRecord(
        user_id=user.id,
        external_user_id=external_user.id,
        binding_id=external_user.binding_id,
        provider=external_user.provider,
        action="linked" if previous_external_user_id is None else "relinked",
        actor_id=actor.id,
        details=json.dumps({
            "previous_external_user_id": previous_external_user_id,
            "external_user_id": external_user.id,
        }),
        created_at=now,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="External identity link conflicts with an existing mapping") from exc
    db.refresh(link)
    return _user_external_identity_link_payload(link, external_user)


@app.delete("/admin/agent-identity-links/{user_id}/{link_id}")
async def delete_agent_identity_link(
    user_id: str,
    link_id: int,
    db: Session = Depends(get_db),
    actor: UserRecord = Depends(require_authenticated_role("admin")),
):
    link = db.query(UserExternalIdentityLinkRecord).filter(
        UserExternalIdentityLinkRecord.id == link_id,
        UserExternalIdentityLinkRecord.user_id == user_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="External identity link not found")
    now = datetime.utcnow()
    db.add(UserExternalIdentityAuditRecord(
        user_id=link.user_id,
        external_user_id=link.external_user_id,
        binding_id=link.binding_id,
        provider=link.provider,
        action="unlinked",
        actor_id=actor.id,
        details=json.dumps({"external_user_id": link.external_user_id}),
        created_at=now,
    ))
    db.delete(link)
    db.commit()
    return {"status": "unlinked", "user_id": user_id, "link_id": link_id}


_ADMIN_MEMBERSHIP_LOCK_NAMESPACE = 0x5449434B  # "TICK"
_ADMIN_MEMBERSHIP_LOCK_KEY = 0x41444D4E  # "ADMN"


def _lock_admin_membership_invariant(db: Session) -> None:
    """Serialize changes that can alter the active-admin membership set.

    PostgreSQL row locks cannot protect a predicate such as "at least one
    active admin exists": two transactions can lock different users, observe
    each other, and both remove an admin.  A transaction-scoped advisory lock
    gives that invariant one shared serialization point.  SQLite already
    permits only one writer; the following user-record write acquires its
    database write lock.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
            {
                "namespace": _ADMIN_MEMBERSHIP_LOCK_NAMESPACE,
                "lock_key": _ADMIN_MEMBERSHIP_LOCK_KEY,
            },
        )


def _lock_user_record(db: Session, user_id: str) -> UserRecord:
    """Serialize account writes on SQLite and PostgreSQL with one contract."""
    matched = db.query(UserRecord).filter(UserRecord.id == user_id).update(
        {UserRecord.is_active: UserRecord.is_active},
        synchronize_session=False,
    )
    if matched != 1:
        raise HTTPException(status_code=404, detail="User not found")
    user = db.query(UserRecord).filter(
        UserRecord.id == user_id
    ).populate_existing().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _ensure_no_pending_change_approvals(db: Session, user_id: str) -> None:
    """Keep inactive accounts from stranding undecided CAB work.

    Callers already hold the User row. This deliberately performs a read only:
    taking a Change lock here would invert the established Change -> User order
    used by add/decide/purge. A concurrent add either commits first and is seen,
    or waits for this User lock and then rejects the inactive approver.
    """
    pending = db.query(ChangeApprovalRecord.id).filter(
        ChangeApprovalRecord.approver_id == user_id,
        or_(
            ChangeApprovalRecord.decision.is_(None),
            ChangeApprovalRecord.decision == "pending",
        ),
        ChangeApprovalRecord.decided_at.is_(None),
    ).first()
    if pending:
        raise HTTPException(
            status_code=409,
            detail="Reassign or decide pending change approvals before deactivation",
        )


@app.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    if payload.role == "admin" and _user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create admin users")
    if payload.role == "admin":
        _lock_admin_membership_invariant(db)
    email = normalize_user_email(payload.email)
    existing = db.query(UserRecord).filter(UserRecord.email_key == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already in use")
    import uuid as _uuid
    password = payload.password or secrets.token_urlsafe(12)
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = UserRecord(
        id=f"u-{_uuid.uuid4().hex}",
        name=payload.name,
        email=email,
        email_key=email,
        title=payload.title,
        role=payload.role,
        password_hash=_hash_password(password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already in use") from exc
    db.refresh(user)
    return user


@app.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    if payload.role is not None or payload.is_active is not None:
        _lock_admin_membership_invariant(db)
    user = _lock_user_record(db, user_id)
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
    removes_active_admin = (
        user.role == "admin"
        and user.is_active
        and (
            payload.is_active is False
            or (payload.role is not None and payload.role != "admin")
        )
    )
    if removes_active_admin:
        active_admins = db.query(UserRecord).filter(
            UserRecord.role == "admin",
            UserRecord.is_active.is_(True),
            UserRecord.id != user.id,
        ).count()
        if active_admins == 0:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
    if payload.is_active is False:
        _ensure_no_pending_change_approvals(db, user.id)
    if payload.email is not None:
        email = normalize_user_email(payload.email)
        existing = db.query(UserRecord).filter(
            UserRecord.email_key == email,
            UserRecord.id != user.id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = email
        user.email_key = email
    for field in ["name", "title", "role", "is_active"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(user, field, val.strip().lower() if field == "email" else val)
    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        user.password_hash = _hash_password(payload.password)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already in use") from exc
    db.refresh(user)
    return user


@app.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    _lock_admin_membership_invariant(db)
    user = _lock_user_record(db, user_id)
    if user.role == "admin":
        if _user.role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can deactivate admin users")
        if user.is_active:
            active_admins = db.query(UserRecord).filter(
                UserRecord.role == "admin",
                UserRecord.is_active.is_(True),
                UserRecord.id != user.id,
            ).count()
            if active_admins == 0:
                raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
    _ensure_no_pending_change_approvals(db, user.id)
    # Soft-delete: deactivate instead of removing (preserves ticket history)
    user.is_active = False
    db.commit()
    return {"status": "deactivated", "user_id": user_id}


@app.delete("/users/{user_id}/purge")
async def purge_user(
    user_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin")),
):
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_active:
        raise HTTPException(status_code=409, detail="Deactivate the user before purging the account")

    removed_owned_records = 0
    cleared_history_references = 0
    removed_pending_approvals = 0
    anonymized_decided_approvals = 0
    user_foreign_keys = [
        foreign_key
        for table in Base.metadata.sorted_tables
        for foreign_key in table.foreign_keys
        if foreign_key.target_fullname == "users.id"
    ]
    try:
        # Every change mutation takes the Change lock before touching its
        # approvals.  Account purge must use the same order or it can deadlock
        # with an approval decision (Approval -> Change versus Change ->
        # Approval).  Stable ordering also keeps two concurrent purges acyclic.
        affected_change_ids = {
            row[0]
            for row in db.query(ChangeApprovalRecord.change_id).filter(
                ChangeApprovalRecord.approver_id == user_id
            ).distinct().all()
        }
        affected_change_ids.update(
            row[0]
            for row in db.query(ChangeRecord.id).filter(or_(
                ChangeRecord.assigned_to == user_id,
                ChangeRecord.requested_by == user_id,
            )).all()
        )
        for change_id in sorted(affected_change_ids):
            db.query(ChangeRecord).filter(ChangeRecord.id == change_id).update(
                {ChangeRecord.updated_at: ChangeRecord.updated_at},
                synchronize_session=False,
            )

        # Serialize against a concurrent account reactivation only after the
        # complete Change lock set. Change assignment already uses
        # Change -> User through its foreign key, so this preserves one global
        # lock order while ensuring an account cannot become active between
        # the initial validation and deletion.
        user = _lock_user_record(db, user_id)
        if user.is_active:
            raise HTTPException(
                status_code=409,
                detail="Deactivate the user before purging the account",
            )

        # Undecided work cannot be completed after its approver disappears.
        # Decided rows remain as immutable, anonymized audit evidence.
        removed_pending_approvals = db.query(ChangeApprovalRecord).filter(
            ChangeApprovalRecord.approver_id == user_id,
            or_(
                ChangeApprovalRecord.decision.is_(None),
                ChangeApprovalRecord.decision == "pending",
            ),
            ChangeApprovalRecord.decided_at.is_(None),
        ).delete(synchronize_session=False)
        anonymized_decided_approvals = db.query(ChangeApprovalRecord).filter(
            ChangeApprovalRecord.approver_id == user_id,
        ).update(
            {ChangeApprovalRecord.approver_id: None},
            synchronize_session=False,
        )

        # Required references are account-owned records and cannot survive the
        # account. Nullable references are historical attribution and remain
        # available after their link to the purged identity is cleared.
        for foreign_key in user_foreign_keys:
            column = foreign_key.parent
            if not column.nullable:
                result = db.execute(column.table.delete().where(column == user_id))
                removed_owned_records += result.rowcount or 0
        for foreign_key in user_foreign_keys:
            column = foreign_key.parent
            if column.nullable:
                result = db.execute(
                    column.table.update().where(column == user_id).values({column.name: None})
                )
                cleared_history_references += result.rowcount or 0
        db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "status": "purged",
        "user_id": user_id,
        "removed_owned_records": removed_owned_records,
        "cleared_history_references": cleared_history_references,
        "removed_pending_approvals": int(removed_pending_approvals or 0),
        "anonymized_decided_approvals": int(anonymized_decided_approvals or 0),
    }


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
    normalized_status = (status or "published").strip().lower()
    if normalized_status not in {"all", "published", "draft", "archived"}:
        raise HTTPException(status_code=422, detail="Unsupported knowledge article status")
    if normalized_status != "published" and user.role not in {"admin", "supervisor"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    q = db.query(KbArticleRecord)
    if normalized_status != "all":
        q = q.filter(KbArticleRecord.status == normalized_status)
    if category:
        q = q.filter(KbArticleRecord.category == category)
    if search:
        escaped_search = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if escaped_search:
            pattern = f"%{escaped_search}%"
            q = q.filter(or_(
                KbArticleRecord.title.ilike(pattern, escape="\\"),
                KbArticleRecord.content.ilike(pattern, escape="\\"),
            ))
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
    status: str = Query(default="published", pattern="^(published|all)$"),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
):
    if status == "all" and user.role not in {"admin", "supervisor"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    query = db.query(KbArticleRecord.category).filter(
        KbArticleRecord.category.isnot(None)
    )
    if status == "published":
        query = query.filter(KbArticleRecord.status == "published")
    rows = query.distinct().order_by(KbArticleRecord.category.asc()).limit(200).all()
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
        id=f"kb-{_uuid.uuid4().hex}",
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
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Article identity or slug changed while saving",
        ) from exc
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
    _authorize_ticket_analysis(user, ticket, db)
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
async def list_status_config(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    _authorize_ticket_view(user)
    return db.query(TicketStatusConfigRecord).order_by(TicketStatusConfigRecord.sort_order).all()


@app.post("/config/statuses", response_model=TicketStatusConfig, status_code=201)
async def create_status_config(
    payload: TicketStatusConfigCreate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    existing = db.query(TicketStatusConfigRecord).filter(
        TicketStatusConfigRecord.name_key == payload.name.lower()
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Status already exists")
    rec = TicketStatusConfigRecord(
        **payload.model_dump(),
        name_key=payload.name.lower(),
    )
    db.add(rec)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Status already exists")
    db.refresh(rec)
    return rec


@app.delete("/config/statuses/{status_id}")
async def delete_status_config(
    status_id: int,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    rec = db.query(TicketStatusConfigRecord).filter(TicketStatusConfigRecord.id == status_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Status not found")
    db.delete(rec)
    db.commit()
    return {"status": "deleted"}


@app.get("/config/priorities", response_model=List[TicketPriorityConfig])
async def list_priority_config(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    _authorize_ticket_view(user)
    return db.query(TicketPriorityConfigRecord).order_by(TicketPriorityConfigRecord.sort_order).all()


@app.post("/config/priorities", response_model=TicketPriorityConfig, status_code=201)
async def create_priority_config(
    payload: TicketPriorityConfigCreate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    existing = db.query(TicketPriorityConfigRecord).filter(
        TicketPriorityConfigRecord.name_key == payload.name.lower()
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Priority already exists")
    rec = TicketPriorityConfigRecord(
        **payload.model_dump(),
        name_key=payload.name.lower(),
    )
    db.add(rec)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Priority already exists")
    db.refresh(rec)
    return rec


@app.delete("/config/priorities/{priority_id}")
async def delete_priority_config(
    priority_id: int,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    rec = db.query(TicketPriorityConfigRecord).filter(TicketPriorityConfigRecord.id == priority_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Priority not found")
    db.delete(rec)
    db.commit()
    return {"status": "deleted"}


# ── Notification config ────────────────────────────────────────

@app.get("/config/notifications", response_model=List[NotificationConfig])
async def list_notification_config(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    return db.query(NotificationConfigRecord).all()


@app.patch("/config/notifications/{event}", response_model=NotificationConfig)
async def update_notification_config(
    event: str,
    payload: NotificationConfigUpdate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
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

@dataclass(frozen=True)
class ReportFilters:
    start_at: datetime
    end_at: datetime
    date_field: str
    status: Optional[str]
    priority: Optional[str]
    category: Optional[str]
    assignee_id: Optional[str]
    source: Optional[str]
    ticket_type: Optional[str]
    resolution_state: Optional[str]
    sla_state: Optional[str]


def _report_filters(
    start_at: Optional[datetime] = Query(default=None),
    end_at: Optional[datetime] = Query(default=None),
    date_field: str = Query(default="created", pattern="^(created|resolved)$"),
    status: Optional[str] = Query(default=None, max_length=100),
    priority: Optional[str] = Query(default=None, max_length=100),
    category: Optional[str] = Query(default=None, max_length=100),
    assignee_id: Optional[str] = Query(default=None, max_length=255),
    source: Optional[str] = Query(default=None, max_length=100),
    ticket_type: Optional[str] = Query(default=None, max_length=100),
    resolution_state: Optional[str] = Query(
        default=None,
        pattern="^(open|resolved)$",
    ),
    sla_state: Optional[str] = Query(
        default=None,
        pattern="^(breached|within_sla|not_tracked)$",
    ),
) -> ReportFilters:
    """Normalize the shared report selection, bounded to 30 days by default."""
    # Keep full precision so records created earlier in the current second are
    # not excluded by a default end boundary rounded down to :00 microseconds.
    now = datetime.utcnow()

    def utc_naive(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    normalized_end = utc_naive(end_at) or now
    normalized_start = utc_naive(start_at) or (normalized_end - timedelta(days=30))
    if normalized_start >= normalized_end:
        raise HTTPException(
            status_code=422,
            detail="Report start_at must be earlier than end_at",
        )
    return ReportFilters(
        start_at=normalized_start,
        end_at=normalized_end,
        date_field=date_field,
        status=(status or "").strip() or None,
        priority=(priority or "").strip() or None,
        category=(category or "").strip() or None,
        assignee_id=(assignee_id or "").strip() or None,
        source=(source or "").strip() or None,
        ticket_type=(ticket_type or "").strip() or None,
        resolution_state=resolution_state,
        sla_state=sla_state,
    )


def _report_created_at_column():
    return func.coalesce(TicketRecord.external_created_at, TicketRecord.created_at)


def _report_resolved_at_column():
    return func.coalesce(TicketRecord.external_resolved_at, TicketRecord.resolved_at)


def _report_date_column(filters: ReportFilters):
    return (
        _report_resolved_at_column()
        if filters.date_field == "resolved"
        else _report_created_at_column()
    )


def _report_sla_deadline_column():
    return func.coalesce(
        TicketRecord.resolution_due_at,
        TicketRecord.external_due_by,
        TicketRecord.due_by,
    )


def _report_resolution_hours_expression(db: Session):
    created_at = _report_created_at_column()
    resolved_at = _report_resolved_at_column()
    if db.get_bind().dialect.name == "sqlite":
        return (func.julianday(resolved_at) - func.julianday(created_at)) * 24.0
    return extract("epoch", resolved_at - created_at) / 3600.0


def _sla_breached_condition(now: datetime, db: Session):
    deadline = _report_sla_deadline_column()
    resolved_at = _report_resolved_at_column()
    return and_(
        sla_eligible_filter(_terminal_status_names(db)),
        deadline.isnot(None),
        or_(
            and_(resolved_at.isnot(None), resolved_at > deadline),
            and_(resolved_at.is_(None), deadline < now),
        ),
    )


def _report_ticket_query(db: Session, filters: ReportFilters, user: UserRecord):
    date_column = _report_date_column(filters)
    query = db.query(TicketRecord).filter(
        date_column >= filters.start_at,
        date_column <= filters.end_at,
    )
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    if allowed_assignee_id is not None:
        query = query.filter(or_(
            TicketRecord.assignee_id.is_(None),
            TicketRecord.assignee_id == allowed_assignee_id,
        ))
    if filters.status:
        query = query.filter(TicketRecord.status == filters.status)
    if filters.priority:
        query = query.filter(TicketRecord.priority == filters.priority)
    if filters.category:
        query = query.filter(TicketRecord.category == filters.category)
    if filters.assignee_id == "__unassigned__":
        query = query.filter(
            func.nullif(TicketRecord.assignee_id, "").is_(None),
            func.nullif(TicketRecord.external_assignee_id, "").is_(None),
        )
    elif filters.assignee_id:
        query = query.filter(TicketRecord.assignee_id == filters.assignee_id)
    if filters.source:
        if filters.source.lower() == "tickety":
            query = query.filter(func.nullif(TicketRecord.external_source, "").is_(None))
        else:
            query = query.filter(
                func.lower(TicketRecord.external_source) == filters.source.lower()
            )
    if filters.ticket_type:
        query = query.filter(
            func.lower(TicketRecord.ticket_type) == filters.ticket_type.lower()
        )
    terminal = _terminal_status_names(db)
    normalized_status = portable_ascii_lower_expression(TicketRecord.status)
    if filters.resolution_state == "resolved":
        query = query.filter(normalized_status.in_(terminal))
    elif filters.resolution_state == "open":
        query = query.filter(normalized_status.notin_(terminal))
    if filters.sla_state:
        eligible = sla_eligible_filter(terminal)
        deadline = _report_sla_deadline_column()
        breached = _sla_breached_condition(datetime.utcnow(), db)
        if filters.sla_state == "breached":
            query = query.filter(breached)
        elif filters.sla_state == "within_sla":
            query = query.filter(eligible, deadline.isnot(None), ~breached)
        else:
            query = query.filter(or_(~eligible, deadline.is_(None)))
    return query


_REPORT_SERIES_ROW_LIMIT = 50_000
_REPORT_SERIES_GROUP_LIMIT = 100


def _report_group_expression(group_by: str):
    expressions = {
        "status": func.coalesce(func.nullif(TicketRecord.status, ""), "No status"),
        "priority": func.coalesce(func.nullif(TicketRecord.priority, ""), "No priority"),
        "category": func.coalesce(func.nullif(TicketRecord.category, ""), "Uncategorized"),
        "assignee": func.coalesce(
            func.nullif(UserRecord.name, ""),
            func.nullif(ExternalUserRecord.name, ""),
            func.nullif(TicketRecord.external_assignee_id, ""),
            "Unassigned",
        ),
        "source": func.coalesce(
            func.nullif(TicketRecord.external_source, ""),
            PRODUCT_NAME,
        ),
        "ticket_type": func.coalesce(
            func.nullif(TicketRecord.ticket_type, ""),
            "Unspecified",
        ),
    }
    return expressions[group_by]


def _report_series_query(
    db: Session,
    filters: ReportFilters,
    user: UserRecord,
    group_by: str,
):
    query = _report_ticket_query(db, filters, user)
    if group_by == "assignee":
        query = query.outerjoin(
            UserRecord,
            TicketRecord.assignee_id == UserRecord.id,
        ).outerjoin(
            ExternalUserRecord,
            and_(
                ExternalUserRecord.binding_id == TicketRecord.binding_id,
                ExternalUserRecord.provider == TicketRecord.external_source,
                ExternalUserRecord.external_id == TicketRecord.external_assignee_id,
                func.lower(ExternalUserRecord.user_type) == "agent",
            ),
        )
    return query, _report_group_expression(group_by)


@app.get("/reports/options")
async def report_options(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    """Return filter values visible inside the caller's ticket scope."""
    query = db.query(TicketRecord)
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    if allowed_assignee_id is not None:
        query = query.filter(or_(
            TicketRecord.assignee_id.is_(None),
            TicketRecord.assignee_id == allowed_assignee_id,
        ))

    def distinct_values(column):
        rows = query.with_entities(column).filter(
            column.isnot(None),
            column != "",
        ).distinct().order_by(column).all()
        return [row[0] for row in rows]

    sources = distinct_values(TicketRecord.external_source)
    if (
        PRODUCT_NAME not in sources
        and query.filter(func.nullif(TicketRecord.external_source, "").is_(None)).first()
    ):
        sources.insert(0, PRODUCT_NAME)
    assignees = query.join(
        UserRecord,
        TicketRecord.assignee_id == UserRecord.id,
    ).with_entities(
        UserRecord.id,
        UserRecord.name,
    ).distinct().order_by(UserRecord.name).all()
    has_unassigned = query.filter(
        func.nullif(TicketRecord.assignee_id, "").is_(None),
        func.nullif(TicketRecord.external_assignee_id, "").is_(None),
    ).first() is not None
    return {
        "statuses": distinct_values(TicketRecord.status),
        "priorities": distinct_values(TicketRecord.priority),
        "categories": distinct_values(TicketRecord.category),
        "sources": sources,
        "ticket_types": distinct_values(TicketRecord.ticket_type),
        "assignees": [{"id": row.id, "name": row.name} for row in assignees],
        "has_unassigned": has_unassigned,
    }


@app.get("/reports/series")
async def reports_series(
    metric: str = Query(
        default="ticket_count",
        pattern="^(ticket_count|avg_resolution_hours|sla_compliance)$",
    ),
    group_by: str = Query(
        default="status",
        pattern="^(status|priority|category|assignee|source|ticket_type)$",
    ),
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_authenticated_role(
        "admin", "supervisor", "agent"
    )),
):
    """Build a count, resolution, or SLA series for a selected dimension."""
    _reserve_analytics_request(db, user.id)
    query, group_expression = _report_series_query(
        db,
        filters,
        user,
        group_by,
    )

    if metric == "ticket_count":
        total_groups = int(query.with_entities(
            func.count(func.distinct(group_expression))
        ).scalar() or 0)
        rows = query.with_entities(
            group_expression.label("group_label"),
            func.count().label("sample_count"),
        ).group_by(group_expression).order_by(
            func.count().desc(),
            group_expression,
        ).limit(_REPORT_SERIES_GROUP_LIMIT).all()
        return {
            "metric": metric,
            "group_by": group_by,
            "labels": [str(row.group_label) for row in rows],
            "values": [int(row.sample_count) for row in rows],
            "counts": [int(row.sample_count) for row in rows],
            "unit": "tickets",
            "total_groups": total_groups,
            "truncated": total_groups > len(rows),
        }

    if metric == "avg_resolution_hours":
        resolved_query = query.filter(_report_resolved_at_column().isnot(None))
        total_groups = int(resolved_query.with_entities(
            func.count(func.distinct(group_expression))
        ).scalar() or 0)
        rows = resolved_query.with_entities(
            group_expression.label("group_label"),
            _report_created_at_column().label("report_created_at"),
            _report_resolved_at_column().label("report_resolved_at"),
        ).order_by(
            _report_date_column(filters).desc(),
            TicketRecord.id.asc(),
        ).limit(_REPORT_SERIES_ROW_LIMIT + 1).all()
        truncated_rows = len(rows) > _REPORT_SERIES_ROW_LIMIT
        grouped: Dict[str, List[float]] = {}
        for row in rows[:_REPORT_SERIES_ROW_LIMIT]:
            if not row.report_created_at or not row.report_resolved_at:
                continue
            duration = (
                row.report_resolved_at - row.report_created_at
            ).total_seconds() / 3600
            if duration < 0:
                continue
            grouped.setdefault(str(row.group_label), []).append(duration)
        ordered = sorted(
            grouped.items(),
            key=lambda item: (-sum(item[1]) / len(item[1]), item[0].lower()),
        )[:_REPORT_SERIES_GROUP_LIMIT]
        return {
            "metric": metric,
            "group_by": group_by,
            "labels": [label for label, _values in ordered],
            "values": [
                round(sum(values) / len(values), 1)
                for _label, values in ordered
            ],
            "counts": [len(values) for _label, values in ordered],
            "unit": "hours",
            "total_groups": total_groups,
            "truncated": truncated_rows or total_groups > len(ordered),
        }

    now = datetime.utcnow()
    eligible_query = query.filter(
        sla_eligible_filter(_terminal_status_names(db)),
        _report_sla_deadline_column().isnot(None),
    )
    total_groups = int(eligible_query.with_entities(
        func.count(func.distinct(group_expression))
    ).scalar() or 0)
    rows = eligible_query.with_entities(
        group_expression.label("group_label"),
        func.count().label("sample_count"),
        func.sum(case(
            (_sla_breached_condition(now, db), 1),
            else_=0,
        )).label("breached_count"),
    ).group_by(group_expression).all()
    compliance_rows = sorted(
        (
            (
                str(row.group_label),
                int(row.sample_count),
                int(row.breached_count or 0),
            )
            for row in rows
        ),
        key=lambda row: (
            -round((row[1] - row[2]) / row[1] * 100, 1),
            row[0].lower(),
        ),
    )[:_REPORT_SERIES_GROUP_LIMIT]
    return {
        "metric": metric,
        "group_by": group_by,
        "labels": [label for label, _total, _breached in compliance_rows],
        "values": [
            round((total - breached) / total * 100, 1)
            for _label, total, breached in compliance_rows
        ],
        "counts": [total for _label, total, _breached in compliance_rows],
        "unit": "percent",
        "total_groups": total_groups,
        "truncated": total_groups > len(compliance_rows),
    }


@app.get("/reports/summary", response_model=ReportSummary)
async def reports_summary(
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    now = datetime.utcnow()
    terminal = _terminal_status_names(db)
    query = _report_ticket_query(db, filters, user)
    normalized_status = portable_ascii_lower_expression(TicketRecord.status)
    total, open_t, resolved, breached, escalated = query.with_entities(
        func.count(TicketRecord.id),
        func.sum(case((normalized_status.notin_(terminal), 1), else_=0)),
        func.sum(case((normalized_status.in_(terminal), 1), else_=0)),
        func.sum(case((_sla_breached_condition(now, db), 1), else_=0)),
        func.sum(case((normalized_status == "escalated", 1), else_=0)),
    ).one()
    total = int(total or 0)
    open_t = int(open_t or 0)
    resolved = int(resolved or 0)
    breached = int(breached or 0)
    escalated = int(escalated or 0)

    created_at = _report_created_at_column()
    resolved_at = _report_resolved_at_column()
    avg_duration = query.with_entities(
        func.avg(_report_resolution_hours_expression(db))
    ).filter(
        created_at.isnot(None),
        resolved_at.isnot(None),
        resolved_at >= created_at,
    ).scalar()
    avg_hours = round(float(avg_duration), 1) if avg_duration is not None else 0.0

    escalation_rate = round(escalated / total * 100, 1) if total else 0.0
    filtered_ticket_ids = query.with_entities(TicketRecord.id).subquery()
    avg_rating = db.query(func.avg(SurveyResponseRecord.rating)).join(
        SurveyRecord,
        SurveyRecord.id == SurveyResponseRecord.survey_id,
    ).join(
        filtered_ticket_ids,
        filtered_ticket_ids.c.id == SurveyRecord.ticket_id,
    ).filter(
        SurveyRecord.delivery_status == "accepted",
    ).scalar()
    csat = round(float(avg_rating) / 5 * 100, 1) if avg_rating else 0.0

    return ReportSummary(
        total_tickets=total, open_tickets=open_t, resolved_tickets=resolved,
        breached_sla=breached, avg_resolution_hours=avg_hours,
        escalation_rate=escalation_rate, csat_proxy=csat,
    )


@app.get("/reports/volume")
async def reports_volume(
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    """Ticket volume grouped by day for the selected report period."""
    query = _report_ticket_query(db, filters, user)
    date_column = _report_date_column(filters)
    rows = query.with_entities(
        func.date(date_column).label("day"),
        func.count().label("count"),
    ).group_by(func.date(date_column)).order_by(func.date(date_column)).all()
    return {
        "days": [
            row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
            for row in rows
        ],
        "counts": [row.count for row in rows],
    }


@app.get("/reports/by-category")
async def reports_by_category(
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    _reserve_analytics_request(db, user.id)
    query = _report_ticket_query(db, filters, user).filter(TicketRecord.category.isnot(None))
    total_categories = int(query.with_entities(
        func.count(func.distinct(TicketRecord.category))
    ).scalar() or 0)
    rows = query.with_entities(
        TicketRecord.category, func.count().label("count")
    ).group_by(TicketRecord.category).order_by(func.count().desc()).limit(100).all()
    return {
        "categories": [r.category for r in rows],
        "counts": [r.count for r in rows],
        "total_categories": total_categories,
        "truncated": total_categories > len(rows),
    }


@app.get("/reports/by-status")
async def reports_by_status(
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    rows = _report_ticket_query(db, filters, user).with_entities(
        TicketRecord.status, func.count().label("count")
    ).group_by(TicketRecord.status).order_by(func.count().desc()).all()
    return {"statuses": [r.status for r in rows], "counts": [r.count for r in rows]}


@app.get("/reports/sla-compliance")
async def reports_sla_compliance(
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    """SLA compliance rate by priority for the selected tickets."""
    now = datetime.utcnow()
    query = _report_ticket_query(db, filters, user).filter(
        sla_eligible_filter(_terminal_status_names(db))
    )
    rows = query.with_entities(
        TicketRecord.priority,
        func.count(TicketRecord.id).label("total"),
        func.sum(case(
            (_sla_breached_condition(now, db), 1),
            else_=0,
        )).label("breached"),
    ).filter(
        TicketRecord.priority.isnot(None)
    ).group_by(
        TicketRecord.priority
    ).order_by(
        TicketRecord.priority
    ).all()
    result = {}
    for row in rows:
        total = int(row.total or 0)
        breached = int(row.breached or 0)
        compliance = round(((total - breached) / total * 100), 1) if total else 100.0
        result[row.priority] = {
            "total": total,
            "breached": breached,
            "compliance": compliance,
        }
    return result


@app.get("/reports/resolution-time")
async def reports_resolution_time(
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Avg resolution time by category for all matching resolved tickets."""
    _reserve_analytics_request(db, user.id)
    query = _report_ticket_query(db, filters, user).filter(
        _report_resolved_at_column().isnot(None),
        TicketRecord.category.isnot(None),
    )
    total_matching = query.count()
    created_at = _report_created_at_column()
    resolved_at = _report_resolved_at_column()
    valid_query = query.filter(
        created_at.isnot(None),
        resolved_at >= created_at,
    )
    analyzed_tickets = valid_query.count()
    total_categories = int(valid_query.with_entities(
        func.count(func.distinct(TicketRecord.category))
    ).scalar() or 0)
    average_hours = func.avg(_report_resolution_hours_expression(db))
    rows = valid_query.with_entities(
        TicketRecord.category,
        average_hours.label("avg_hours"),
    ).group_by(
        TicketRecord.category
    ).order_by(
        average_hours.desc(),
        TicketRecord.category,
    ).limit(_REPORT_SERIES_GROUP_LIMIT).all()
    return {
        "categories": [row.category for row in rows],
        "avg_hours": [round(float(row.avg_hours), 1) for row in rows],
        "total_matching_tickets": total_matching,
        "analyzed_tickets": analyzed_tickets,
        "truncated": total_categories > len(rows),
    }


# Report export

_REPORT_EXPORT_LIMIT = 50_000
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> str:
    text_value = "" if value is None else str(value)
    if text_value.lstrip().startswith(_CSV_FORMULA_PREFIXES):
        return f"'{text_value}"
    return text_value


@app.get("/reports/export")
async def export_report_csv(
    filters: ReportFilters = Depends(_report_filters),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    """Export ticket-level evidence for exactly the active report selection."""
    _reserve_analytics_request(db, user.id)
    query = _report_ticket_query(db, filters, user)
    rows = query.outerjoin(
        UserRecord,
        TicketRecord.assignee_id == UserRecord.id,
    ).with_entities(
        TicketRecord.id,
        TicketRecord.external_id,
        TicketRecord.subject,
        TicketRecord.status,
        TicketRecord.priority,
        TicketRecord.category,
        TicketRecord.external_source,
        UserRecord.name.label("assignee_name"),
        _report_created_at_column().label("report_created_at"),
        _report_resolved_at_column().label("report_resolved_at"),
        func.coalesce(
            TicketRecord.resolution_due_at,
            TicketRecord.external_due_by,
            TicketRecord.due_by,
        ).label("report_due_at"),
        case(
            (sla_eligible_filter(_terminal_status_names(db)), True),
            else_=False,
        ).label("report_sla_eligible"),
    ).order_by(
        _report_date_column(filters).desc(),
        TicketRecord.id.asc(),
    ).limit(_REPORT_EXPORT_LIMIT + 1).all()
    if len(rows) > _REPORT_EXPORT_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Report export exceeds {_REPORT_EXPORT_LIMIT:,} tickets; "
                "narrow the date range or add filters"
            ),
        )

    now = datetime.utcnow()

    def csv_lines():
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")

        def emit(values):
            writer.writerow([_csv_safe(value) for value in values])
            content = output.getvalue()
            output.seek(0)
            output.truncate(0)
            return content

        # The BOM keeps UTF-8 category and subject text intact in Excel.
        yield "\ufeff" + emit([
            "Ticket ID", "External ID", "Subject", "Status", "Priority",
            "Category", "Source", "Assignee", "Created at (UTC)",
            "Resolved at (UTC)", "Resolution hours", "SLA due at (UTC)",
            "SLA breached",
        ])
        for row in rows:
            resolution_hours = ""
            if row.report_created_at and row.report_resolved_at:
                resolution_hours = round(
                    (row.report_resolved_at - row.report_created_at).total_seconds() / 3600,
                    2,
                )
            sla_breached = bool(
                row.report_sla_eligible
                and row.report_due_at
                and (
                    (row.report_resolved_at and row.report_resolved_at > row.report_due_at)
                    or (not row.report_resolved_at and row.report_due_at < now)
                )
            )
            yield emit([
                row.id,
                row.external_id,
                row.subject,
                row.status,
                row.priority,
                row.category,
                row.external_source,
                row.assignee_name,
                row.report_created_at.isoformat() if row.report_created_at else "",
                row.report_resolved_at.isoformat() if row.report_resolved_at else "",
                resolution_hours,
                row.report_due_at.isoformat() if row.report_due_at else "",
                "Yes" if sla_breached else "No",
            ])

    filename = f"tickety-ticket-report-{now.strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        csv_lines(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Report-Rows": str(len(rows)),
        },
    )


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
    resolved_counts = db.query(
        TicketRecord.resolved_by.label("user_id"),
        func.count(TicketRecord.id).label("tickets_resolved"),
    ).filter(
        TicketRecord.resolved_by.isnot(None),
        TicketRecord.points_awarded > 0,
    ).group_by(TicketRecord.resolved_by).subquery()
    rows = db.query(
        UserRecord,
        func.coalesce(resolved_counts.c.tickets_resolved, 0),
    ).outerjoin(
        resolved_counts,
        resolved_counts.c.user_id == UserRecord.id,
    ).filter(
        UserRecord.is_active.is_(True),
    ).order_by(
        desc(UserRecord.impact_points),
        UserRecord.id,
    ).limit(500).all()
    result = []
    for i, (u, resolved_count) in enumerate(rows):
        result.append(UserSummary(
            id=u.id,
            name=u.name,
            avatar=u.avatar,
            title=u.title,
            impact_points=u.impact_points,
            tier=u.tier,
            momentum=u.momentum,
            tickets_resolved=int(resolved_count or 0),
            rank=i + 1,
        ))
    return result


@app.get("/recognitions/{user_id}", response_model=List[Recognition])
async def get_user_recognitions(
    user_id: str,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    if (user.role or "").lower() not in {"admin", "supervisor"} and user_id != user.id:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    target = db.query(UserRecord.id).filter(UserRecord.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
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
        raise HTTPException(status_code=404, detail=f"Ticket has not been synchronized to {PRODUCT_NAME}")
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


@app.get(
    "/admin/routing-catalog/recommendations",
    response_model=ResolverCatalogRecommendationResponse,
)
def get_routing_catalog_recommendations(
    response: Response,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Recommend resolver-code mappings without changing provider state."""
    response.headers["Cache-Control"] = "private, no-store"
    _reserve_analytics_request(db, user.id)
    now = datetime.utcnow()
    return resolver_catalog.recommend_resolver_catalog_mappings(
        db,
        generated_at=now,
        pipeline_version=AI_ROUTING_PIPELINE_VERSION,
        model=_llm_cache_identity(),
        allow_synthetic=(
            not settings_module.is_production_mode()
            and bool(getattr(engine.llm, "allow_synthetic", False))
        ),
        input_hash_for_ticket=lambda ticket: _artifact_input_hash(ticket, "route"),
    )


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
    preset: str = Query(
        "2_months",
        description="2_months, 3_months, or custom",
    ),
    start_date: Optional[str] = Query(
        None, description="Custom UTC start date in YYYY-MM-DD format"
    ),
    end_date: Optional[str] = Query(
        None, description="Custom inclusive UTC end date in YYYY-MM-DD format"
    ),
    binding_id: Optional[str] = Query(None, max_length=36),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin")),
):
    """Queue an explicit admin-only old-ticket range for bounded fetching."""
    selected = (preset or "").strip().lower()
    now = datetime.utcnow().replace(microsecond=0)
    if selected == "2_months":
        range_start = now - timedelta(days=60)
        range_end = now
    elif selected == "3_months":
        range_start = now - timedelta(days=90)
        range_end = now
    elif selected == "custom":
        if not start_date or not end_date:
            raise HTTPException(
                status_code=422,
                detail="custom old-ticket fetch requires start_date and end_date",
            )
        try:
            range_start = datetime.strptime(start_date, "%Y-%m-%d")
            # Treat the selected end date as inclusive.
            range_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="custom dates must use YYYY-MM-DD",
            ) from exc
        if range_end > now + timedelta(days=1):
            raise HTTPException(
                status_code=422,
                detail="custom end_date cannot be in the future",
            )
        if range_start >= range_end:
            raise HTTPException(
                status_code=422,
                detail="custom start_date must be on or before end_date",
            )
        if range_end - range_start > timedelta(days=366):
            raise HTTPException(
                status_code=422,
                detail="custom old-ticket range cannot exceed 366 days",
            )
    else:
        raise HTTPException(
            status_code=422,
            detail="preset must be 2_months, 3_months, or custom",
        )

    _reserve_ai_request(db, user.id, "itsm_fetch_old")
    adapter, effective_binding_id = _sync_adapter_for_binding(db, binding_id)
    try:
        result = queue_old_ticket_fetch(
            adapter,
            start_at=range_start,
            end_at=range_end,
            requested_by=user.id,
            binding_id=effective_binding_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if detail == "old_ticket_fetch_already_queued" else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    result.update({
        "preset": selected,
        "start_date": range_start.date().isoformat(),
        "end_date": (range_end - timedelta(microseconds=1)).date().isoformat(),
    })
    return {"status": "queued", "result": result}


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
        automatic_fetch_days=s.get("automatic_fetch_days", AUTOMATIC_FETCH_DAYS),
        last_status=s.get("last_status", "idle"),
        last_error="sync_failed" if s.get("last_error") else None,
        total_synced=s.get("total_synced", 0),
        recent_since_at=(
            datetime.fromisoformat(s["recent_since_at"])
            if s.get("recent_since_at") else None
        ),
        recent_cycle_started_at=(
            datetime.fromisoformat(s["recent_cycle_started_at"])
            if s.get("recent_cycle_started_at") else None
        ),
        recent_page=s.get("recent_page", 1),
        recent_workspace_index=s.get("recent_workspace_index", 0),
        recent_completed_at=(
            datetime.fromisoformat(s["recent_completed_at"])
            if s.get("recent_completed_at") else None
        ),
        history_page=s.get("history_page", 1),
        history_workspace_index=s.get("history_workspace_index", 0),
        history_complete=s.get("history_complete", False),
        history_processed=s.get("history_processed", 0),
        history_since_at=(
            datetime.fromisoformat(s["history_since_at"])
            if s.get("history_since_at") else None
        ),
        history_until_at=(
            datetime.fromisoformat(s["history_until_at"])
            if s.get("history_until_at") else None
        ),
        history_requested_at=(
            datetime.fromisoformat(s["history_requested_at"])
            if s.get("history_requested_at") else None
        ),
        conversations_processed=s.get("conversations_processed", 0),
        run_started_at=(
            datetime.fromisoformat(s["run_started_at"])
            if s.get("run_started_at") else None
        ),
        run_finished_at=(
            datetime.fromisoformat(s["run_finished_at"])
            if s.get("run_finished_at") else None
        ),
        next_retry_at=(
            datetime.fromisoformat(s["next_retry_at"])
            if s.get("next_retry_at") else None
        ),
        rate_limit_total=s.get("rate_limit_total"),
        rate_limit_remaining=s.get("rate_limit_remaining"),
        rate_limit_used=s.get("rate_limit_used"),
        last_batch_new=s.get("last_batch_new", 0),
        last_batch_updated=s.get("last_batch_updated", 0),
        last_batch_errors=s.get("last_batch_errors", 0),
        local_ticket_count=s.get("local_ticket_count", 0),
        sync_interval_seconds=s.get("sync_interval_seconds", 60),
        recent_pages_per_sync=s.get("recent_pages_per_sync", 2),
        history_pages_per_sync=s.get("history_pages_per_sync", 1),
        conversations_per_sync=s.get("conversations_per_sync", 1),
        attachments_per_sync=s.get("attachments_per_sync", 2),
        attachment_storage_configured=s.get("attachment_storage_configured", False),
        attachment_pending=s.get("attachment_pending", 0),
        attachment_stored=s.get("attachment_stored", 0),
        attachment_errors=s.get("attachment_errors", 0),
    )


# ── Settings ─────────────────────────────────────────────────

@app.post("/admin/sync/agents", deprecated=True)
@app.post("/admin/sync/external-users")
async def sync_external_user_directory(
    binding_id: Optional[str] = Query(None, max_length=36),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Refresh provider-owned profiles without changing Tickety OPS Tower accounts."""
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
    search: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
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
    if search:
        escaped_search = (
            search.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        if escaped_search:
            pattern = f"%{escaped_search}%"
            query = query.filter(or_(
                ExternalUserRecord.name.ilike(pattern, escape="\\"),
                ExternalUserRecord.email.ilike(pattern, escape="\\"),
                ExternalUserRecord.title.ilike(pattern, escape="\\"),
                ExternalUserRecord.external_id.ilike(pattern, escape="\\"),
            ))
    total = query.order_by(None).count()
    records = query.order_by(
        ExternalUserRecord.user_type, ExternalUserRecord.name, ExternalUserRecord.external_id
    ).offset(offset).limit(limit).all()
    return {
        "users": [_external_user_payload(record) for record in records],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(records) < total,
    }


@app.get("/admin/agents", deprecated=True)
async def list_external_agents(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    page = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
    ).order_by(
        ExternalUserRecord.name,
        ExternalUserRecord.id,
    ).offset(offset).limit(limit + 1).all()
    return {
        "agents": [_external_user_payload(record) for record in page[:limit]],
        "limit": limit,
        "offset": offset,
        "has_more": len(page) > limit,
    }


# ── SendGrid email ─────────────────────────────────────────────

def _email_directory(
    db: Session,
    audience: str,
    *,
    search: str,
    limit: int,
) -> tuple[list[EmailRecipient], bool]:
    """Return a bounded, source-separated recipient sample.

    Local and provider directories are each capped before materialization.
    Search is applied in SQL. The caller receives an explicit truncation bit
    because computing an exact cross-source, normalized-email cardinality
    would require scanning the entire provider directory on every keystroke.
    """
    by_email: dict[str, EmailRecipient] = {}
    sample_limit = limit + 1
    escaped_search = (
        search.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    pattern = f"%{escaped_search}%" if escaped_search else None

    def add_recipient(recipient: EmailRecipient) -> None:
        try:
            normalized = normalize_email_address(recipient.email)
        except ValueError:
            return
        recipient.email = normalized
        by_email.setdefault(normalized, recipient)

    local_users: list[UserRecord] = []
    local_truncated = False
    if audience == "agents":
        local_query = db.query(UserRecord).filter(
            UserRecord.is_active.is_(True),
            UserRecord.role.in_(("admin", "supervisor", "agent")),
            UserRecord.email.isnot(None),
        )
        if pattern:
            local_query = local_query.filter(or_(
                UserRecord.name.ilike(pattern, escape="\\"),
                UserRecord.email.ilike(pattern, escape="\\"),
                UserRecord.title.ilike(pattern, escape="\\"),
                UserRecord.role.ilike(pattern, escape="\\"),
            ))
        local_page = local_query.order_by(
            portable_ascii_lower_expression(UserRecord.name),
            UserRecord.id,
        ).limit(sample_limit).all()
        local_truncated = len(local_page) > limit
        local_users = local_page[:sample_limit]
        for record in local_users:
            add_recipient(EmailRecipient(
                id=f"local:{record.id}",
                name=record.name,
                email=record.email or "",
                audience="agents",
                source="tickety",
                title=record.title or record.role,
            ))

    external_type = "agent" if audience == "agents" else "requester"
    external_query = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.active.is_(True),
        ExternalUserRecord.user_type == external_type,
        ExternalUserRecord.email.isnot(None),
        func.length(func.trim(ExternalUserRecord.email)).between(3, 320),
        ExternalUserRecord.email.contains("@"),
    )
    if pattern:
        external_query = external_query.filter(or_(
            ExternalUserRecord.name.ilike(pattern, escape="\\"),
            ExternalUserRecord.email.ilike(pattern, escape="\\"),
            ExternalUserRecord.title.ilike(pattern, escape="\\"),
        ))
    external_page = external_query.order_by(
        portable_ascii_lower_expression(ExternalUserRecord.name),
        ExternalUserRecord.id,
    ).limit(sample_limit).all()
    external_truncated = len(external_page) > limit
    external_users = external_page[:sample_limit]
    for record in external_users:
        add_recipient(EmailRecipient(
            id=f"external:{record.id}",
            name=record.name,
            email=record.email or "",
            audience=audience,
            source=record.provider,
            title=record.title,
        ))
    recipients = sorted(
        by_email.values(),
        key=lambda recipient: (recipient.name.casefold(), recipient.email),
    )
    truncated = (
        local_truncated
        or external_truncated
        or len(recipients) > limit
    )
    return recipients[:limit], truncated


def _resolve_email_recipients(
    db: Session,
    *,
    audience: str,
    recipient_ids: list[str],
) -> list[EmailAddress]:
    local_ids: list[str] = []
    external_ids: list[str] = []
    for recipient_id in recipient_ids:
        prefix, separator, record_id = recipient_id.partition(":")
        if not separator or not record_id:
            raise HTTPException(status_code=422, detail="One or more recipients are unavailable")
        if prefix == "local" and audience == "agents":
            local_ids.append(record_id)
        elif prefix == "external":
            external_ids.append(record_id)
        else:
            raise HTTPException(status_code=422, detail="One or more recipients are unavailable")

    local_records = {
        record.id: record
        for record in db.query(UserRecord).filter(
            UserRecord.id.in_(local_ids or [""]),
            UserRecord.is_active.is_(True),
            UserRecord.role.in_(("admin", "supervisor", "agent")),
            UserRecord.email.isnot(None),
        ).all()
    }
    expected_external_type = "agent" if audience == "agents" else "requester"
    external_records = {
        record.id: record
        for record in db.query(ExternalUserRecord).filter(
            ExternalUserRecord.id.in_(external_ids or [""]),
            ExternalUserRecord.active.is_(True),
            ExternalUserRecord.user_type == expected_external_type,
            ExternalUserRecord.email.isnot(None),
        ).all()
    }

    recipients: list[EmailAddress] = []
    seen: set[str] = set()
    for recipient_id in recipient_ids:
        prefix, _, record_id = recipient_id.partition(":")
        record = local_records.get(record_id) if prefix == "local" else external_records.get(record_id)
        if not record:
            raise HTTPException(status_code=422, detail="One or more recipients are unavailable")
        try:
            normalized = normalize_email_address(record.email or "")
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="One or more recipients are unavailable",
            ) from None
        if normalized in seen:
            continue
        seen.add(normalized)
        recipients.append(EmailAddress(email=normalized, name=record.name))
    if not recipients:
        raise HTTPException(status_code=422, detail="No deliverable recipients were selected")
    return recipients


@app.get("/email/status", response_model=EmailProviderStatus)
async def email_provider_status(
    response: Response,
    _user: UserRecord = Depends(get_email_user),
):
    response.headers["Cache-Control"] = "no-store"
    return sendgrid_status()


@app.get("/email/recipients", response_model=EmailRecipientList)
async def list_email_recipients(
    response: Response,
    audience: str = Query(..., pattern="^(agents|users)$"),
    search: str = Query("", max_length=120),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_email_user),
):
    response.headers["Cache-Control"] = "no-store"
    recipients, truncated = _email_directory(
        db,
        audience,
        search=search,
        limit=limit,
    )
    return {
        "audience": audience,
        "recipients": recipients,
        # This is the number shown, not an expensive exact directory count.
        # `truncated` explicitly communicates that additional matches exist.
        "total": len(recipients),
        "truncated": truncated,
    }


@app.post("/email/send", response_model=EmailSendResponse, status_code=202)
async def send_email_message(
    payload: EmailSendRequest,
    user: UserRecord = Depends(get_email_user),
    db: Session = Depends(get_db),
):
    status = sendgrid_status()
    if not status["configured"]:
        raise HTTPException(status_code=503, detail="SendGrid is not configured")
    recipients = _resolve_email_recipients(
        db,
        audience=payload.audience,
        recipient_ids=payload.recipient_ids,
    )
    _reserve_email_request(db, user.id, len(recipients))
    delivery_body = f"{payload.body}\n\n—\nSent by {user.name} via {PRODUCT_NAME}."
    try:
        message_id = await send_sendgrid_email(
            recipients,
            subject=payload.subject,
            body=delivery_body,
        )
    except EmailConfigurationError:
        raise HTTPException(status_code=503, detail="SendGrid is not configured") from None
    except EmailDeliveryError as exc:
        print(
            "[email] sendgrid delivery rejected "
            f"status={exc.provider_status or 'network_error'} actor={user.id} "
            f"recipients={len(recipients)}"
        )
        raise HTTPException(status_code=502, detail="Email provider did not accept the message") from None
    return {
        "status": "accepted",
        "recipient_count": len(recipients),
        "message_id": message_id,
    }


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


_MAINTENANCE_WINDOW_LIMITS = {"days": 7, "weeks": 4}


def _maintenance_window(
    window_unit: str,
    window_value: Optional[int],
) -> tuple[str, int, int, datetime]:
    unit = (window_unit or "days").strip().lower()
    maximum = _MAINTENANCE_WINDOW_LIMITS.get(unit)
    if maximum is None:
        raise HTTPException(
            status_code=422,
            detail="window_unit must be days or weeks",
        )
    value = window_value if window_value is not None else (7 if unit == "days" else 1)
    if value < 1 or value > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"window_value must be between 1 and {maximum} for {unit}",
        )
    days = value if unit == "days" else value * 7
    return unit, value, days, datetime.utcnow() - timedelta(days=days)


@app.post("/admin/sync/triage-all")
async def triage_all_untriaged(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    limit: int = Query(default=100, ge=1, le=500),
    window_unit: str = Query(default="days"),
    window_value: Optional[int] = Query(default=None, ge=1),
):
    """Queue untriaged tickets only inside an explicit, bounded age window."""
    unit, value, window_days, cutoff = _maintenance_window(
        window_unit, window_value
    )
    _reserve_ai_request(db, user.id, "triage_all")
    untriaged = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        ticket_created_within_filter(cutoff),
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
        ticket.ai_claim_id = None
        ticket.ai_lease_expires_at = None
        ticket.ai_error = None
        ticket.ai_next_attempt_at = None
        ticket.ai_requested_artifacts = "triage"
    db.commit()
    return {
        "status": "queued",
        "found": len(untriaged),
        "queued": len(untriaged),
        "window_unit": unit,
        "window_value": value,
        "window_days": window_days,
        "cutoff_at": cutoff.isoformat(),
    }


@app.post("/admin/sync/repair")
async def repair_ai_gaps(
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
    limit: int = Query(default=100, ge=1, le=500),
    window_unit: str = Query(default="days"),
    window_value: Optional[int] = Query(default=None, ge=1),
):
    """Queue AI gap repairs only inside an explicit, bounded age window."""
    unit, value, window_days, cutoff = _maintenance_window(
        window_unit, window_value
    )
    _reserve_ai_request(db, user.id, "repair_ai_gaps")
    candidates = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        ticket_created_within_filter(cutoff),
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
        ticket.ai_claim_id = None
        ticket.ai_lease_expires_at = None
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
        "window_unit": unit,
        "window_value": value,
        "window_days": window_days,
        "cutoff_at": cutoff.isoformat(),
    }


@app.get("/admin/settings")
async def get_settings(_user: UserRecord = Depends(require_protected_ai_role("admin"))):
    return settings_module.get_settings()


_AI_TASK_STATUSES = {
    "queued",
    "running",
    "completed",
    "triage_completed",
    "partial",
    "stale",
    "legacy_stale",
    "provenance_unknown",
    "failed",
    "dead_letter",
    "paused",
    "not_applicable",
}
_AI_ATTENTION_STATUSES = {
    "partial",
    "stale",
    "legacy_stale",
    "provenance_unknown",
    "failed",
    "dead_letter",
    "paused",
}
_AI_ARTIFACT_NAMES = {"triage", "summary", "route", "resolution", "refresh"}
_AI_RETRY_CONTROL_STATUSES = {"queued", "paused"}
_AI_RETRY_QUEUE_CLEARED_ERROR = "operator_retry_queue_cleared"
_SAFE_OPERATIONAL_CODE = re.compile(
    r"^[a-z0-9_]+(?::[a-z0-9_]+)?(?:,[a-z0-9_]+(?::[a-z0-9_]+)?)*$"
)


def _safe_operational_code(value: Optional[str]) -> Optional[str]:
    """Expose stable status codes without returning legacy provider messages."""
    normalized = (value or "").strip().lower().replace("-", "_")
    if not normalized:
        return None
    if len(normalized) <= 256 and _SAFE_OPERATIONAL_CODE.fullmatch(normalized):
        return normalized
    return "legacy_error"


def _is_operator_cleared_retry(ticket: TicketRecord) -> bool:
    """Distinguish an intentional queue control from an analysis failure."""
    return (
        (ticket.ai_status or "").strip().lower().replace("-", "_") == "paused"
        and (ticket.ai_error or "").strip().lower() == _AI_RETRY_QUEUE_CLEARED_ERROR
    )


def _ai_task_lifecycle(
    ticket: TicketRecord,
    now: datetime,
    terminal_statuses: Optional[set[str]] = None,
) -> str:
    status = (ticket.ai_status or "").strip().lower().replace("-", "_")
    ticket_status = portable_ascii_lower(ticket.status)
    if (
        terminal_statuses
        and ticket_status in terminal_statuses
        and status not in {"completed", "triage_completed"}
    ):
        return "not_applicable"
    if status == "not_applicable":
        return "not_applicable"
    if not status:
        return "not_analyzed"
    if status == "queued":
        if ticket.ai_next_attempt_at and ticket.ai_next_attempt_at > now:
            return "retry_scheduled"
        return "queued"
    if status == "running":
        if not ticket.ai_lease_expires_at or ticket.ai_lease_expires_at < now:
            return "lease_expired"
        return "running"
    if status in {"completed", "triage_completed"}:
        return "completed"
    if status in {"stale", "legacy_stale", "provenance_unknown"}:
        return "stale"
    if status in {"partial", "failed", "dead_letter", "paused"}:
        return status
    return "unknown"


def _utc_naive_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _ai_attention_filter():
    """Exclude retries an administrator deliberately removed from the queue."""
    return or_(
        TicketRecord.ai_status.in_(tuple(_AI_ATTENTION_STATUSES - {"paused"})),
        and_(
            TicketRecord.ai_status == "paused",
            func.coalesce(TicketRecord.ai_error, "") != _AI_RETRY_QUEUE_CLEARED_ERROR,
        ),
    )


def _active_provider_cooldown_until(
    db: Session,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    current = now or datetime.utcnow()
    provider_name = getattr(engine.llm, "provider", None)
    if not provider_name:
        return None
    row = db.query(LLMProviderCooldownRecord.retry_at).filter(
        LLMProviderCooldownRecord.provider == provider_name,
        LLMProviderCooldownRecord.retry_at > current,
    ).first()
    return row[0] if row else None


def _audit_ai_retry_control(
    db: Session,
    ticket: TicketRecord,
    user: UserRecord,
    *,
    old_value: Optional[str],
    new_value: str,
) -> None:
    db.add(TicketAuditLogRecord(
        ticket_id=ticket.id,
        field="ai_retry_schedule",
        old_value=old_value,
        new_value=new_value,
        changed_by=user.name or user.id,
    ))


def _retry_control_ticket(
    db: Session,
    ticket_id: str,
) -> TicketRecord:
    ticket = db.query(TicketRecord).filter(
        TicketRecord.id == ticket_id
    ).with_for_update().first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if _is_terminal_status(db, ticket.status):
        raise HTTPException(
            status_code=409,
            detail="Historical tickets cannot be added to the AI retry queue",
        )
    status = (ticket.ai_status or "").strip().lower().replace("-", "_")
    if status not in _AI_RETRY_CONTROL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Only queued or paused AI retries can be changed",
        )
    requested = {
        artifact
        for artifact in (ticket.ai_requested_artifacts or "").split(",")
        if artifact in _AI_ARTIFACT_NAMES
    }
    if not requested:
        raise HTTPException(
            status_code=409,
            detail="AI task has no pending artifacts to retry",
        )
    ticket.ai_requested_artifacts = ",".join(sorted(requested))
    return ticket


@app.get("/admin/settings/ai-status", response_model=AIStatusResponse)
async def ai_task_status(
    view: str = Query(
        default="all",
        pattern="^(all|active|retry_scheduled|attention|completed|not_analyzed|not_applicable)$",
    ),
    search: str = Query(default="", max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    _user: UserRecord = Depends(require_protected_ai_role("admin")),
    db: Session = Depends(get_db),
):
    """Return bounded, prompt-free operational detail for durable AI work."""
    now = datetime.utcnow()
    terminal_statuses = _terminal_status_names(db)
    normalized_status = func.lower(func.coalesce(TicketRecord.ai_status, "not_analyzed"))
    active_ticket = active_ticket_filter(db)
    terminal_ticket = terminal_ticket_filter(db)
    status_rows = db.query(
        normalized_status,
        func.count(TicketRecord.id),
    ).group_by(normalized_status).all()
    status_counts = {str(status): int(count) for status, count in status_rows}

    queued_ready = db.query(func.count(TicketRecord.id)).filter(
        active_ticket,
        TicketRecord.ai_status == "queued",
        or_(
            TicketRecord.ai_next_attempt_at.is_(None),
            TicketRecord.ai_next_attempt_at <= now,
        ),
    ).scalar() or 0
    retry_scheduled = db.query(func.count(TicketRecord.id)).filter(
        active_ticket,
        TicketRecord.ai_status == "queued",
        TicketRecord.ai_next_attempt_at > now,
    ).scalar() or 0
    running_active = db.query(func.count(TicketRecord.id)).filter(
        active_ticket,
        TicketRecord.ai_status == "running",
        TicketRecord.ai_lease_expires_at >= now,
    ).scalar() or 0
    lease_expired = db.query(func.count(TicketRecord.id)).filter(
        active_ticket,
        TicketRecord.ai_status == "running",
        or_(
            TicketRecord.ai_lease_expires_at.is_(None),
            TicketRecord.ai_lease_expires_at < now,
        ),
    ).scalar() or 0
    oldest_queued_at = db.query(func.min(TicketRecord.updated_at)).filter(
        active_ticket,
        TicketRecord.ai_status == "queued"
    ).scalar()
    completed_count = sum(
        status_counts.get(status, 0)
        for status in ("completed", "triage_completed")
    )
    attention_rows = db.query(
        normalized_status,
        func.count(TicketRecord.id),
    ).filter(
        active_ticket,
        _ai_attention_filter(),
    ).group_by(normalized_status).all()
    attention_status_counts = {
        str(status): int(count) for status, count in attention_rows
    }
    attention_count = sum(attention_status_counts.values()) + int(lease_expired)
    active_not_analyzed = db.query(func.count(TicketRecord.id)).filter(
        active_ticket,
        TicketRecord.ai_status.is_(None),
    ).scalar() or 0
    active_queued = db.query(func.count(TicketRecord.id)).filter(
        active_ticket,
        TicketRecord.ai_status == "queued",
    ).scalar() or 0
    active_running = db.query(func.count(TicketRecord.id)).filter(
        active_ticket,
        TicketRecord.ai_status == "running",
    ).scalar() or 0
    not_applicable = db.query(func.count(TicketRecord.id)).filter(
        terminal_ticket,
        or_(
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_status.notin_(("completed", "triage_completed")),
        ),
    ).scalar() or 0

    task_query = db.query(TicketRecord)
    if view == "active":
        task_query = task_query.filter(
            active_ticket,
            TicketRecord.ai_status.in_(("queued", "running")),
        )
    elif view == "retry_scheduled":
        task_query = task_query.filter(
            active_ticket,
            TicketRecord.ai_status == "queued",
            TicketRecord.ai_next_attempt_at > now,
        )
    elif view == "attention":
        task_query = task_query.filter(active_ticket, or_(
            _ai_attention_filter(),
            and_(
                TicketRecord.ai_status == "running",
                or_(
                    TicketRecord.ai_lease_expires_at.is_(None),
                    TicketRecord.ai_lease_expires_at < now,
                ),
            ),
        ))
    elif view == "completed":
        task_query = task_query.filter(
            TicketRecord.ai_status.in_(("completed", "triage_completed"))
        )
    elif view == "not_analyzed":
        task_query = task_query.filter(active_ticket, TicketRecord.ai_status.is_(None))
    elif view == "not_applicable":
        task_query = task_query.filter(
            terminal_ticket,
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_(("completed", "triage_completed")),
            ),
        )

    escaped_search = (
        search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    if escaped_search:
        pattern = f"%{escaped_search}%"
        task_query = task_query.filter(or_(
            TicketRecord.subject.ilike(pattern, escape="\\"),
            TicketRecord.id.ilike(pattern, escape="\\"),
            TicketRecord.external_id.ilike(pattern, escape="\\"),
        ))
    total_tasks = task_query.count()
    task_order = case(
        {
            "dead_letter": 0,
            "failed": 1,
            "partial": 2,
            "running": 3,
            "queued": 4,
            "paused": 5,
            "stale": 6,
            "legacy_stale": 6,
            "provenance_unknown": 6,
            "triage_completed": 7,
            "completed": 7,
            "not_analyzed": 8,
        },
        value=normalized_status,
        else_=9,
    )
    if view == "retry_scheduled":
        task_query = task_query.order_by(
            TicketRecord.ai_next_attempt_at.asc(),
            TicketRecord.id.asc(),
        )
    else:
        task_query = task_query.order_by(
            task_order.asc(),
            TicketRecord.updated_at.desc(),
            TicketRecord.id.asc(),
        )
    task_rows = task_query.offset(offset).limit(limit).all()

    tasks = []
    for ticket in task_rows:
        status = (ticket.ai_status or "").strip().lower().replace("-", "_")
        requested_artifacts = sorted({
            artifact
            for artifact in (ticket.ai_requested_artifacts or "").split(",")
            if artifact in _AI_ARTIFACT_NAMES
        })
        tasks.append({
            "ticket_id": ticket.id,
            "subject": ticket.subject,
            "ticket_status": ticket.status or "Unknown",
            "priority": ticket.priority or "Unknown",
            "source": ticket.external_source or "local",
            "external_id": ticket.external_id,
            "ai_status": status if status in _AI_TASK_STATUSES else None,
            "lifecycle": _ai_task_lifecycle(ticket, now, terminal_statuses),
            "requested_artifacts": requested_artifacts,
            "attempts": int(ticket.ai_attempts or 0),
            "model": ticket.ai_model,
            "synthetic": bool(ticket.ai_synthetic),
            "started_at": ticket.ai_started_at,
            "generated_at": ticket.ai_generated_at,
            "next_attempt_at": ticket.ai_next_attempt_at,
            "lease_expires_at": ticket.ai_lease_expires_at,
            "error_code": (
                None
                if _is_operator_cleared_retry(ticket)
                else _safe_operational_code(ticket.ai_error)
            ),
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
        })

    calls_since = now - timedelta(days=1)
    call_summary = db.query(
        func.count(LLMCallRecord.id),
        func.coalesce(func.sum(case((LLMCallRecord.status == "success", 1), else_=0)), 0),
        func.coalesce(func.sum(case((LLMCallRecord.status.in_(("attempt_failed", "failed")), 1), else_=0)), 0),
        func.coalesce(func.sum(case((LLMCallRecord.status == "capacity_deferred", 1), else_=0)), 0),
        func.coalesce(func.sum(LLMCallRecord.total_tokens), 0),
        func.coalesce(func.avg(LLMCallRecord.latency_ms), 0),
        func.max(LLMCallRecord.created_at),
    ).filter(LLMCallRecord.created_at >= calls_since).one()
    # Capacity deferrals are represented by the aggregate and the single
    # provider cooldown below. Omitting each identical deferred attempt from
    # this execution feed prevents an exhausted budget from burying useful
    # success/failure telemetry.
    recent_call_rows = db.query(LLMCallRecord).filter(
        LLMCallRecord.status != "capacity_deferred"
    ).order_by(
        LLMCallRecord.created_at.desc(),
        LLMCallRecord.id.desc(),
    ).limit(20).all()
    provider_name = getattr(engine.llm, "provider", None)
    provider_cooldown = (
        db.query(LLMProviderCooldownRecord).filter(
            LLMProviderCooldownRecord.provider == provider_name,
            LLMProviderCooldownRecord.retry_at > now,
        ).first()
        if provider_name else None
    )

    automation = [
        {
            "key": key,
            "label": label,
            "enabled": settings_module.automation_enabled(key, legacy),
        }
        for key, label, legacy in (
            ("AUTO_TRIAGE_ENABLED", "Triage", "AUTO_TRIAGE"),
            ("AUTO_SUMMARIZE_ENABLED", "Summarization", None),
            ("AUTO_ROUTE_ENABLED", "Routing", None),
            ("AUTO_RESOLVE_ENABLED", "Resolution", None),
            ("AUTO_SYSTEMIC_ENABLED", "Systemic detection", None),
        )
    ]
    active_integration_bindings = db.query(func.count(IntegrationBindingRecord.id)).filter(
        IntegrationBindingRecord.state == "active"
    ).scalar() or 0
    automatic_ai_bindings = db.query(func.count(SyncStateRecord.id)).filter(
        SyncStateRecord.automatic_ai_enabled.is_(True)
    ).scalar() or 0

    return {
        "generated_at": now,
        "automation": automation,
        "active_integration_bindings": int(active_integration_bindings),
        "automatic_ai_bindings": int(automatic_ai_bindings),
        "active_routing_backlog_enabled": active_routing_backlog_enabled(),
        "queue": {
            "total_tickets": sum(status_counts.values()),
            "not_analyzed": int(active_not_analyzed),
            "not_applicable": int(not_applicable),
            "queued": int(active_queued),
            "queued_ready": int(queued_ready),
            "retry_scheduled": int(retry_scheduled),
            "running": int(active_running),
            "running_active": int(running_active),
            "lease_expired": int(lease_expired),
            "completed": completed_count,
            "partial": attention_status_counts.get("partial", 0),
            "stale": sum(
                attention_status_counts.get(status, 0)
                for status in ("stale", "legacy_stale", "provenance_unknown")
            ),
            "failed": attention_status_counts.get("failed", 0),
            "dead_letter": attention_status_counts.get("dead_letter", 0),
            "paused": attention_status_counts.get("paused", 0),
            "attention": attention_count,
            "oldest_queued_at": oldest_queued_at,
        },
        "view": view,
        "search": search.strip(),
        "tasks": tasks,
        "total_tasks": total_tasks,
        "limit": limit,
        "offset": offset,
        "provider_cooldown": (
            {
                "provider": provider_cooldown.provider,
                "reason": provider_cooldown.reason,
                "retry_at": provider_cooldown.retry_at,
            }
            if provider_cooldown else None
        ),
        "recent_calls": [
            {
                "id": call.id,
                "provider": call.provider,
                "model": call.model,
                "task": call.task,
                "status": call.status,
                "attempts": call.attempts,
                "latency_ms": call.latency_ms,
                "total_tokens": call.total_tokens,
                "synthetic": bool(call.synthetic),
                "error_code": _safe_operational_code(call.error_code),
                "http_status": call.http_status,
                "failure_kind": _safe_operational_code(call.failure_kind),
                "retry_after_seconds": call.retry_after_seconds,
                "dispatched": bool(call.dispatched),
                "estimated_tokens": int(call.estimated_tokens or 0),
                "created_at": call.created_at,
            }
            for call in recent_call_rows
        ],
        "calls_24h": {
            "calls": int(call_summary[0] or 0),
            "successful": int(call_summary[1] or 0),
            "failed_attempts": int(call_summary[2] or 0),
            "deferred": int(call_summary[3] or 0),
            "total_tokens": int(call_summary[4] or 0),
            "average_latency_ms": int(round(float(call_summary[5] or 0))),
            "last_call_at": call_summary[6],
        },
    }


@app.post(
    "/admin/settings/ai-status/retries/clear",
    response_model=AIRetryQueueActionResponse,
)
def clear_scheduled_ai_retries(
    user: UserRecord = Depends(require_protected_ai_role("admin")),
    db: Session = Depends(get_db),
):
    """Pause every delayed retry without deleting tickets or AI artifacts."""
    now = datetime.utcnow()
    tickets = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        TicketRecord.ai_status == "queued",
        TicketRecord.ai_next_attempt_at > now,
    ).with_for_update().all()
    for ticket in tickets:
        old_schedule = ticket.ai_next_attempt_at.isoformat() if ticket.ai_next_attempt_at else None
        _audit_ai_retry_control(
            db,
            ticket,
            user,
            old_value=f"scheduled:{old_schedule}" if old_schedule else "scheduled",
            new_value="paused:queue_cleared",
        )
        ticket.ai_status = "paused"
        ticket.ai_claim_id = None
        ticket.ai_lease_expires_at = None
        ticket.ai_next_attempt_at = None
        ticket.ai_error = _AI_RETRY_QUEUE_CLEARED_ERROR
    db.commit()
    return {
        "action": "clear",
        "affected": len(tickets),
        "dispatch_blocked_until": _active_provider_cooldown_until(db, now),
    }


@app.post(
    "/admin/settings/ai-status/retries/retry-now",
    response_model=AIRetryQueueActionResponse,
)
def retry_all_scheduled_ai_now(
    user: UserRecord = Depends(require_protected_ai_role("admin")),
    db: Session = Depends(get_db),
):
    """Make every delayed retry immediately eligible for a worker claim."""
    now = datetime.utcnow()
    tickets = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        TicketRecord.ai_status == "queued",
        TicketRecord.ai_next_attempt_at > now,
    ).with_for_update().all()
    for ticket in tickets:
        old_schedule = ticket.ai_next_attempt_at.isoformat() if ticket.ai_next_attempt_at else None
        _audit_ai_retry_control(
            db,
            ticket,
            user,
            old_value=f"scheduled:{old_schedule}" if old_schedule else "scheduled",
            new_value="ready",
        )
        ticket.ai_claim_id = None
        ticket.ai_lease_expires_at = None
        ticket.ai_next_attempt_at = None
        ticket.ai_error = None
    db.commit()
    return {
        "action": "retry_all_now",
        "affected": len(tickets),
        "dispatch_blocked_until": _active_provider_cooldown_until(db, now),
    }


@app.post(
    "/admin/settings/ai-status/{ticket_id}/retry-now",
    response_model=AIRetryQueueActionResponse,
)
def retry_scheduled_ai_task_now(
    ticket_id: str,
    user: UserRecord = Depends(require_protected_ai_role("admin")),
    db: Session = Depends(get_db),
):
    """Resume one scheduled or paused retry and make it immediately eligible."""
    now = datetime.utcnow()
    ticket = _retry_control_ticket(db, ticket_id)
    old_schedule = (
        f"scheduled:{ticket.ai_next_attempt_at.isoformat()}"
        if ticket.ai_next_attempt_at
        else (ticket.ai_status or "unknown")
    )
    _audit_ai_retry_control(
        db,
        ticket,
        user,
        old_value=old_schedule,
        new_value="ready",
    )
    ticket.ai_status = "queued"
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_next_attempt_at = None
    ticket.ai_error = None
    db.commit()
    return {
        "action": "retry_now",
        "affected": 1,
        "ticket_id": ticket.id,
        "dispatch_blocked_until": _active_provider_cooldown_until(db, now),
    }


@app.put(
    "/admin/settings/ai-status/{ticket_id}/retry-schedule",
    response_model=AIRetryQueueActionResponse,
)
def reschedule_ai_retry(
    ticket_id: str,
    payload: AIRetryScheduleRequest,
    user: UserRecord = Depends(require_protected_ai_role("admin")),
    db: Session = Depends(get_db),
):
    """Set one scheduled or paused retry to an explicit future UTC instant."""
    now = datetime.utcnow()
    scheduled_at = _utc_naive_datetime(payload.scheduled_at)
    if scheduled_at <= now:
        raise HTTPException(
            status_code=422,
            detail="scheduled_at must be in the future; use retry now for immediate work",
        )
    if scheduled_at > now + timedelta(days=365):
        raise HTTPException(
            status_code=422,
            detail="scheduled_at cannot be more than 365 days in the future",
        )
    ticket = _retry_control_ticket(db, ticket_id)
    old_schedule = (
        f"scheduled:{ticket.ai_next_attempt_at.isoformat()}"
        if ticket.ai_next_attempt_at
        else (ticket.ai_status or "unknown")
    )
    _audit_ai_retry_control(
        db,
        ticket,
        user,
        old_value=old_schedule,
        new_value=f"scheduled:{scheduled_at.isoformat()}",
    )
    ticket.ai_status = "queued"
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_next_attempt_at = scheduled_at
    ticket.ai_error = None
    db.commit()
    return {
        "action": "reschedule",
        "affected": 1,
        "ticket_id": ticket.id,
        "scheduled_at": scheduled_at,
        "dispatch_blocked_until": _active_provider_cooldown_until(db, now),
    }


def _diagnostic_text(value: Any) -> str:
    """Return bounded stored diagnostics while always removing deployment secrets."""
    return redact_text(
        str(value or "No durable diagnostic message was recorded"),
        configured_secret_values(),
    )[:4000]


def _diagnostic_severity(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized in {"failed", "dead_letter", "error", "lease_expired"}:
        return "error"
    if normalized in {
        "partial", "stale", "legacy_stale", "provenance_unknown",
        "paused", "queued", "attempt_failed", "throttled", "not_ready",
    }:
        return "warning"
    return "info"


@app.get(
    "/admin/settings/ai-status/{ticket_id}/diagnostics",
    response_model=OperationalDiagnosticsResponse,
)
async def ai_ticket_diagnostics(
    ticket_id: str,
    response: Response,
    _user: UserRecord = Depends(require_protected_ai_role("admin")),
    db: Session = Depends(get_db),
):
    """Reveal bounded stored task diagnostics only after an explicit admin read."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    response.headers["Cache-Control"] = "no-store"
    status = _ai_task_lifecycle(ticket, datetime.utcnow())
    entries = []
    operator_cleared_retry = _is_operator_cleared_retry(ticket)
    if ticket.ai_error and not operator_cleared_retry:
        entries.append({
            "severity": _diagnostic_severity(status),
            "source": "ticket.ai_error",
            "message": _diagnostic_text(ticket.ai_error),
            "timestamp": ticket.updated_at,
        })
    if status == "lease_expired":
        entries.append({
            "severity": "error",
            "source": "analysis_lease",
            "message": _diagnostic_text(
                f"Worker lease expired at {ticket.ai_lease_expires_at.isoformat() if ticket.ai_lease_expires_at else 'unknown'}"
            ),
            "timestamp": ticket.ai_lease_expires_at,
        })
    elif status == "retry_scheduled":
        entries.append({
            "severity": "warning",
            "source": "analysis_retry",
            "message": _diagnostic_text(
                f"Retry scheduled for {ticket.ai_next_attempt_at.isoformat() if ticket.ai_next_attempt_at else 'unknown'} after {ticket.ai_attempts or 0} attempt(s)"
            ),
            "timestamp": ticket.ai_next_attempt_at,
        })
    if not entries and not operator_cleared_retry and status in {
        "partial", "stale", "failed", "dead_letter", "paused", "unknown"
    }:
        entries.append({
            "severity": _diagnostic_severity(status),
            "source": "ticket.ai_status",
            "message": _diagnostic_text(ticket.ai_status),
            "timestamp": ticket.updated_at,
        })
    return {
        "area": "ai",
        "generated_at": datetime.utcnow(),
        "entries": entries,
        "truncated": False,
    }


@app.get(
    "/admin/settings/status/diagnostics",
    response_model=OperationalDiagnosticsResponse,
)
async def operational_status_diagnostics(
    response: Response,
    area: str = Query(
        ...,
        pattern="^(application|ai|sync|retrieval|oauth)$",
    ),
    _user: UserRecord = Depends(require_protected_ai_role("admin")),
    db: Session = Depends(get_db),
):
    """Reveal bounded durable diagnostics for one Admin Status area."""
    response.headers["Cache-Control"] = "no-store"
    entries: list[dict[str, Any]] = []
    truncated = False

    if area == "ai":
        now = datetime.utcnow()
        rows = db.query(TicketRecord).filter(
            active_ticket_filter(db),
            or_(
                _ai_attention_filter(),
                and_(
                    TicketRecord.ai_status == "running",
                    or_(
                        TicketRecord.ai_lease_expires_at.is_(None),
                        TicketRecord.ai_lease_expires_at < now,
                    ),
                ),
            ),
        ).order_by(TicketRecord.updated_at.desc(), TicketRecord.id.asc()).limit(51).all()
        truncated = len(rows) > 50
        for ticket in rows[:50]:
            lifecycle = _ai_task_lifecycle(ticket, now)
            entries.append({
                "severity": _diagnostic_severity(lifecycle),
                "source": f"ticket:{ticket.id}",
                "message": _diagnostic_text(ticket.ai_error or ticket.ai_status),
                "timestamp": ticket.updated_at,
            })
        remaining = max(0, 50 - len(entries))
        if remaining:
            calls_since = now - timedelta(days=1)
            latest_calls = db.query(
                LLMCallRecord.provider.label("provider"),
                LLMCallRecord.task.label("task"),
                func.max(LLMCallRecord.id).label("id"),
            ).filter(
                LLMCallRecord.created_at >= calls_since,
            )
            provider_name = getattr(engine.llm, "provider", None)
            if provider_name:
                latest_calls = latest_calls.filter(
                    LLMCallRecord.provider == provider_name
                )
            latest_calls = latest_calls.group_by(
                LLMCallRecord.provider,
                LLMCallRecord.task,
            ).subquery()
            call_rows = db.query(LLMCallRecord).join(
                latest_calls,
                LLMCallRecord.id == latest_calls.c.id,
            ).filter(
                LLMCallRecord.status.notin_(("success", "capacity_deferred"))
            ).order_by(
                LLMCallRecord.created_at.desc(), LLMCallRecord.id.desc()
            ).limit(remaining + 1).all()
            truncated = truncated or len(call_rows) > remaining
            for call in call_rows[:remaining]:
                entries.append({
                    "severity": _diagnostic_severity(call.status),
                    "source": f"llm:{call.provider}:{call.task}",
                    "message": _diagnostic_text(call.error_code or call.status),
                    "timestamp": call.created_at,
                })

    elif area == "sync":
        rows = db.query(SyncStateRecord).filter(or_(
            SyncStateRecord.last_error.isnot(None),
            SyncStateRecord.last_status.in_(("error", "throttled")),
        )).order_by(
            SyncStateRecord.run_finished_at.desc(), SyncStateRecord.id.desc()
        ).limit(51).all()
        truncated = len(rows) > 50
        for state in rows[:50]:
            message = state.last_error
            if not message and state.last_status == "throttled":
                message = (
                    "Provider throttled the sync lane"
                    + (
                        f"; next retry at {state.next_retry_at.isoformat()}"
                        if state.next_retry_at else ""
                    )
                )
            entries.append({
                "severity": _diagnostic_severity(state.last_status),
                "source": f"sync:{state.provider}:{state.binding_id}",
                "message": _diagnostic_text(message or state.last_status),
                "timestamp": state.run_finished_at,
            })
        remaining = max(0, 50 - len(entries))
        if remaining:
            attachment_rows = db.query(ExternalAttachmentRecord).filter(
                ExternalAttachmentRecord.storage_status == "error"
            ).order_by(
                ExternalAttachmentRecord.last_attempted_at.desc(),
                ExternalAttachmentRecord.id.asc(),
            ).limit(remaining + 1).all()
            truncated = truncated or len(attachment_rows) > remaining
            for attachment in attachment_rows[:remaining]:
                entries.append({
                    "severity": "error",
                    "source": f"attachment:{attachment.id}",
                    "message": _diagnostic_text(
                        attachment.last_error or "attachment_copy_failed"
                    ),
                    "timestamp": attachment.last_attempted_at,
                })

    elif area == "retrieval":
        from .rag.store_v2 import store_ready
        if store_ready(db):
            rows = db.execute(text("""
                SELECT key, value, updated_at
                FROM rag_v2_schema_meta
                WHERE key LIKE 'index_error:%'
                ORDER BY updated_at DESC, key ASC
                LIMIT 51
            """)).all()
            truncated = len(rows) > 50
            for row in rows[:50]:
                entries.append({
                    "severity": "error",
                    "source": str(row.key),
                    "message": _diagnostic_text(row.value),
                    "timestamp": row.updated_at,
                })

    elif area == "oauth":
        from .integrations.registry import get_adapter as _diagnostic_adapter
        adapter = _diagnostic_adapter()
        if adapter.oauth_configured and not adapter.oauth_access_token:
            entries.append({
                "severity": "warning",
                "source": "freshservice_oauth",
                "message": "OAuth client configuration is present, but no access token is available",
                "timestamp": None,
            })

    # Application dependency exceptions are intentionally not persisted in the
    # database. Returning an empty list truthfully indicates there is no durable
    # diagnostic record instead of inventing or exposing process internals.
    return {
        "area": area,
        "generated_at": datetime.utcnow(),
        "entries": entries,
        "truncated": truncated,
    }


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
_INTELLIGENCE_SLA_ROW_LIMIT = 5_000
_INTELLIGENCE_EVIDENCE_ROW_LIMIT = 100
_INTELLIGENCE_DEFAULT_WINDOW_DAYS = 30


def _intelligence_cutoff(now: datetime, window_days: int) -> datetime:
    return now - timedelta(days=window_days)


def _ticket_activity_expression():
    return intel._ticket_activity_expression()


def _ticket_created_expression():
    return func.coalesce(TicketRecord.external_created_at, TicketRecord.created_at)


def _ticket_resolved_expression():
    return func.coalesce(TicketRecord.external_resolved_at, TicketRecord.resolved_at)


def _intelligence_assignee_identities(
    db: Session,
    tickets: list[TicketRecord],
) -> dict[str, dict[str, Optional[str]]]:
    """Resolve stable assignee identities without crossing provider boundaries."""
    provider_keys = {
        (ticket.binding_id, ticket.external_source, ticket.external_assignee_id)
        for ticket in tickets
        if ticket.external_source and ticket.external_assignee_id
    }
    provider_profiles: dict[tuple[str, str, str], tuple[str, str]] = {}
    if provider_keys:
        binding_ids = {key[0] for key in provider_keys}
        providers = {key[1] for key in provider_keys}
        external_ids = {key[2] for key in provider_keys}
        profile_rows = db.query(
            ExternalUserRecord.id,
            ExternalUserRecord.binding_id,
            ExternalUserRecord.provider,
            ExternalUserRecord.external_id,
            ExternalUserRecord.name,
        ).filter(
            ExternalUserRecord.binding_id.in_(binding_ids),
            ExternalUserRecord.provider.in_(providers),
            ExternalUserRecord.external_id.in_(external_ids),
            ExternalUserRecord.active.is_(True),
            func.lower(ExternalUserRecord.user_type) == "agent",
        ).all()
        provider_profiles = {
            (binding_id, provider, external_id): (record_id, name)
            for record_id, binding_id, provider, external_id, name in profile_rows
            if (binding_id, provider, external_id) in provider_keys
        }

    local_ids = {
        ticket.assignee_id
        for ticket in tickets
        if ticket.assignee_id and not ticket.external_assignee_id
    }
    local_profiles = dict(
        db.query(UserRecord.id, UserRecord.name)
        .filter(UserRecord.id.in_(local_ids))
        .all()
    ) if local_ids else {}

    identities: dict[str, dict[str, Optional[str]]] = {}
    for ticket in tickets:
        if ticket.external_assignee_id:
            profile = provider_profiles.get((
                ticket.binding_id,
                ticket.external_source or "",
                ticket.external_assignee_id,
            ))
            if profile:
                identities[ticket.id] = {
                    "assignee_id": profile[0],
                    "assignee_name": profile[1],
                    "assignee_source": "provider",
                }
                continue
            # Do not expose a provider's raw identifier or silently resolve it
            # against a different binding/provider identity domain.
            identities[ticket.id] = {
                "assignee_id": None,
                "assignee_name": None,
                "assignee_source": None,
            }
            continue

        local_name = local_profiles.get(ticket.assignee_id)
        identities[ticket.id] = {
            "assignee_id": ticket.assignee_id if local_name is not None else None,
            "assignee_name": local_name,
            "assignee_source": "tickety" if local_name is not None else None,
        }
    return identities


def _sla_monitoring_ticket_query(db: Session, cutoff: datetime):
    return db.query(TicketRecord).filter(
        _ticket_activity_expression() >= cutoff,
        TicketRecord.portal_access_token_hash.is_(None),
    )


def _sla_monitoring_rows(
    db: Session,
    tickets: list[TicketRecord],
    *,
    now: datetime,
    terminal_statuses: set[str],
) -> list[Dict[str, Any]]:
    assignee_identities = _intelligence_assignee_identities(db, tickets)
    conversation_facts = intel.public_conversation_sla_facts(
        db, [ticket.id for ticket in tickets]
    )
    rows: list[Dict[str, Any]] = []
    for ticket in tickets:
        responded_at, has_public_conversation = conversation_facts.get(
            ticket.id, (None, False)
        )
        first_response = intel.first_response_sla_status(
            ticket,
            [],
            now=now,
            terminal_statuses=terminal_statuses,
            responded_at=responded_at,
            conversation_coverage=bool(
                has_public_conversation
                or ticket.external_conversations_synced_at
                or not ticket.external_source
            ),
        )
        first_response.update(assignee_identities[ticket.id])
        rows.append(first_response)
        resolution = intel.resolution_sla_monitor_status(
            ticket,
            now=now,
            terminal_statuses=terminal_statuses,
        )
        resolution.update(assignee_identities[ticket.id])
        rows.append(resolution)
    return rows


def _sla_monitoring_partitions(
    rows: list[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]]]:
    measured = [row for row in rows if row["status"] != "unmeasured"]
    reactive = [row for row in measured if row["status"] == "breached"]
    proactive = [row for row in measured if row["status"] == "approaching"]
    reactive.sort(key=lambda row: (
        -row["overdue_hours"], row["ticket_id"], row["metric"]
    ))
    proactive.sort(key=lambda row: (
        row["remaining_hours"], row["ticket_id"], row["metric"]
    ))
    return measured, reactive, proactive


def _unmapped_intelligence_assignee_filter():
    external_assignment = func.nullif(
        TicketRecord.external_assignee_id, ""
    ).isnot(None)
    no_external_assignment = func.nullif(
        TicketRecord.external_assignee_id, ""
    ).is_(None)
    provider_source_present = func.nullif(
        TicketRecord.external_source, ""
    ).isnot(None)
    provider_identity_exists = select(ExternalUserRecord.id).where(
        ExternalUserRecord.binding_id == TicketRecord.binding_id,
        ExternalUserRecord.provider == TicketRecord.external_source,
        ExternalUserRecord.external_id == TicketRecord.external_assignee_id,
        ExternalUserRecord.active.is_(True),
        func.lower(ExternalUserRecord.user_type) == "agent",
    ).exists()
    local_identity_exists = select(UserRecord.id).where(
        UserRecord.id == TicketRecord.assignee_id,
    ).exists()
    return or_(
        and_(
            external_assignment,
            or_(~provider_source_present, ~provider_identity_exists),
        ),
        and_(
            no_external_assignment,
            or_(
                func.nullif(TicketRecord.assignee_id, "").is_(None),
                ~local_identity_exists,
            ),
        ),
    )


def _ticket_is_unassigned(ticket: TicketRecord) -> bool:
    return not (ticket.assignee_id or ticket.external_assignee_id)


def _unassigned_ticket_filter():
    return and_(
        func.nullif(TicketRecord.assignee_id, "").is_(None),
        func.nullif(TicketRecord.external_assignee_id, "").is_(None),
    )


def _active_ticket_status_filter(db: Session):
    return active_ticket_filter(db)


def _open_ticket_query(db: Session, since: Optional[datetime] = None):
    query = db.query(TicketRecord).filter(_active_ticket_status_filter(db))
    if since is not None:
        query = query.filter(_ticket_activity_expression() >= since)
    return query


def _intelligence_candidate_order():
    return (
        _priority_weight_expression().asc(),
        _ticket_activity_expression().desc().nullslast(),
        TicketRecord.id.asc(),
    )


def _serialize_attention_ticket(
    ticket: TicketRecord,
    now: datetime,
    terminal_statuses: set[str],
) -> Dict[str, Any]:
    sla = intel.sla_status(ticket, now, terminal_statuses)
    risk = intel.escalation_risk(ticket, now, terminal_statuses)
    priority = (ticket.priority or "").strip() or "Unspecified"
    reasons: List[str] = []
    if sla["status"] == "breached":
        reasons.append("SLA breached")
    elif sla["status"] == "at_risk":
        reasons.append("SLA at risk")
    if priority.lower() in {"p1", "urgent"}:
        reasons.append("Critical priority")
    if risk >= 70:
        reasons.append("Escalation prone")
    if _ticket_is_unassigned(ticket):
        reasons.append("Unassigned")
    activity_at = intel._ticket_activity_at(ticket)
    dormant_hours = max(
        0.0,
        (now - activity_at).total_seconds() / 3600.0 if activity_at else 0.0,
    )
    if dormant_hours >= 7 * 24:
        reasons.append("No activity in 7+ days")
    return {
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "priority": priority,
        "status": ticket.status,
        "category": ticket.category,
        "assignee_id": ticket.assignee_id,
        "is_unassigned": _ticket_is_unassigned(ticket),
        "escalation_risk": risk,
        "priority_score": intel.prioritize_score(
            ticket, now, terminal_statuses
        ),
        "age_hours": round(
            intel._age_hours(ticket, now, terminal_statuses), 2
        ),
        "dormant_hours": round(dormant_hours, 2),
        "last_activity_at": activity_at.isoformat() if activity_at else None,
        "sla": sla,
        "reasons": reasons or ["Ranked operational work"],
    }


@app.get("/intelligence/overview")
async def intel_overview(
    window_days: int = Query(
        _INTELLIGENCE_DEFAULT_WINDOW_DAYS,
        ge=7,
        le=365,
        description="Operational activity window in days",
    ),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Decision-first operations cockpit with legacy backlog isolation."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    terminal_statuses = _terminal_status_names(db)
    cutoff = _intelligence_cutoff(now, window_days)
    all_open_query = _open_ticket_query(db)
    active_query = _open_ticket_query(db, cutoff)
    activity_expression = _ticket_activity_expression()
    active_condition = activity_expression >= cutoff
    stale_condition = or_(
        activity_expression < cutoff,
        activity_expression.is_(None),
    )
    critical_priority = func.lower(
        func.coalesce(TicketRecord.priority, "")
    ).in_(["p1", "urgent"])
    (
        total_open,
        active_open,
        p1_open,
        unassigned_open,
        stale_p1,
        stale_unassigned,
        latest_activity,
        oldest_stale_activity,
    ) = all_open_query.with_entities(
        func.count(TicketRecord.id),
        func.sum(case((active_condition, 1), else_=0)),
        func.sum(case((and_(active_condition, critical_priority), 1), else_=0)),
        func.sum(case((and_(active_condition, _unassigned_ticket_filter()), 1), else_=0)),
        func.sum(case((and_(stale_condition, critical_priority), 1), else_=0)),
        func.sum(case((and_(stale_condition, _unassigned_ticket_filter()), 1), else_=0)),
        func.max(case((active_condition, activity_expression), else_=None)),
        func.min(case((stale_condition, activity_expression), else_=None)),
    ).one()
    total_open = int(total_open or 0)
    active_open = int(active_open or 0)
    p1_open = int(p1_open or 0)
    unassigned_open = int(unassigned_open or 0)
    stale_p1 = int(stale_p1 or 0)
    stale_unassigned = int(stale_unassigned or 0)
    candidates = active_query.order_by(
        *_intelligence_candidate_order()
    ).limit(_INTELLIGENCE_ROW_LIMIT).all()
    unassigned_candidates = active_query.filter(
        _unassigned_ticket_filter()
    ).order_by(
        *_intelligence_candidate_order()
    ).limit(_INTELLIGENCE_EVIDENCE_ROW_LIMIT).all()

    attention = [
        _serialize_attention_ticket(ticket, now, terminal_statuses)
        for ticket in candidates
    ]
    unassigned_items = [
        _serialize_attention_ticket(ticket, now, terminal_statuses)
        for ticket in unassigned_candidates
    ]
    attention.sort(key=lambda item: (
        item["sla"]["status"] == "breached",
        item["priority"].lower() in {"p1", "urgent"},
        item["sla"]["status"] == "at_risk",
        item["escalation_risk"] >= 70,
        item["is_unassigned"],
        item["priority_score"],
    ), reverse=True)

    sla_breached = sum(item["sla"]["status"] == "breached" for item in attention)
    sla_at_risk = sum(item["sla"]["status"] == "at_risk" for item in attention)
    escalation_prone = sum(item["escalation_risk"] >= 70 for item in attention)
    stale_query = all_open_query.filter(stale_condition)
    stale_open = max(0, total_open - active_open)
    stale_candidates = stale_query.order_by(
        *_intelligence_candidate_order()[:1],
        _ticket_activity_expression().asc().nullsfirst(),
        TicketRecord.id.asc(),
    ).limit(8).all()
    stale_items = []
    for ticket in stale_candidates:
        activity_at = intel._ticket_activity_at(ticket)
        stale_items.append({
            "ticket_id": ticket.id,
            "subject": ticket.subject,
            "priority": ticket.priority or "Unspecified",
            "status": ticket.status,
            "is_unassigned": _ticket_is_unassigned(ticket),
            "last_activity_at": activity_at.isoformat() if activity_at else None,
            "dormant_days": round(
                max(0.0, (now - activity_at).total_seconds() / 86400.0), 1
            ) if activity_at else None,
        })

    created_in_window, resolved_in_window = db.query(
        func.sum(case((_ticket_created_expression() >= cutoff, 1), else_=0)),
        func.sum(case((_ticket_resolved_expression() >= cutoff, 1), else_=0)),
    ).one()
    created_in_window = int(created_in_window or 0)
    resolved_in_window = int(resolved_in_window or 0)

    age_bands = {"under_24h": 0, "one_to_three_days": 0, "four_to_seven_days": 0, "over_seven_days": 0}
    for item in attention:
        age_hours = item["age_hours"]
        if age_hours < 24:
            age_bands["under_24h"] += 1
        elif age_hours < 72:
            age_bands["one_to_three_days"] += 1
        elif age_hours < 168:
            age_bands["four_to_seven_days"] += 1
        else:
            age_bands["over_seven_days"] += 1

    posture = "critical" if sla_breached or p1_open else (
        "watch" if sla_at_risk or escalation_prone or unassigned_open else "healthy"
    )
    return {
        "generated_at": now.isoformat(),
        "posture": posture,
        "scope": {
            "window_days": window_days,
            "cutoff_at": cutoff.isoformat(),
            "activity_basis": "provider_updated_at_or_created_at",
            "total_open_tickets": total_open,
            "active_open_tickets": active_open,
            "excluded_stale_open_tickets": stale_open,
            "analyzed_tickets": len(candidates),
            "truncated": active_open > len(candidates),
        },
        "posture_metrics": {
            "p1_open": p1_open,
            "sla_breached": sla_breached,
            "sla_at_risk": sla_at_risk,
            "escalation_prone": escalation_prone,
            "unassigned_open": unassigned_open,
        },
        "flow": {
            "created": int(created_in_window),
            "resolved": int(resolved_in_window),
            "net_change": int(created_in_window) - int(resolved_in_window),
        },
        "age_bands": age_bands,
        "attention_queue": attention[:15],
        "unassigned_evidence": {
            "items": unassigned_items,
            "items_truncated": unassigned_open > len(unassigned_items),
        },
        "stale_backlog": {
            "count": stale_open,
            "p1_count": stale_p1,
            "unassigned_count": stale_unassigned,
            "oldest_activity_at": oldest_stale_activity.isoformat() if oldest_stale_activity else None,
            "items": stale_items,
        },
        "freshness": {
            "latest_ticket_activity_at": latest_activity.isoformat() if latest_activity else None,
        },
    }


@app.get("/intelligence/service-quality")
def intel_service_quality(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Alert-only routing, support-level, friction, and clarity signals."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    terminal_statuses = _terminal_status_names(db)
    cutoff = _intelligence_cutoff(now, window_days)
    query = _open_ticket_query(db, cutoff).filter(
        TicketRecord.portal_access_token_hash.is_(None)
    )
    total = query.count()
    tickets = query.order_by(*_intelligence_candidate_order()).limit(
        _INTELLIGENCE_ROW_LIMIT
    ).all()
    profile_group_keys = {
        (ticket.binding_id or "legacy", ticket.external_group_id)
        for ticket in tickets
        if ticket.external_group_id
    }
    profile_since = now - timedelta(days=365)
    profile_tickets, group_profiles_truncated = (
        intel.group_profile_ticket_candidates(
            db,
            since=profile_since,
            group_keys=profile_group_keys,
        )
    )
    current_profile_route_ids = _current_route_artifact_ticket_ids(
        db,
        profile_tickets,
    )
    profiles, group_profiles_truncated = intel.build_group_profiles(
        db,
        since=profile_since,
        group_keys=profile_group_keys,
        candidate_tickets=profile_tickets,
        candidates_truncated=group_profiles_truncated,
        trusted_route_ticket_ids=current_profile_route_ids,
    )
    current_route_ids = _current_route_artifact_ticket_ids(db, tickets)
    conversations, truncated_transcript_ticket_ids = (
        intel.bounded_public_conversations_for_tickets(
            db,
            [ticket.id for ticket in tickets],
        )
    )

    routing_alerts = []
    level_assessments = []
    friction_alerts = []
    clarification_alerts = []
    routing_profiled = 0
    assigned_level_profiled = 0
    level_distribution = {str(level): 0 for level in range(4)}
    for ticket in tickets:
        profile = profiles.get((ticket.binding_id or "legacy", ticket.external_group_id or ""))
        if profile and (
            profile.get("functional_samples", 0) >= intel._GROUP_PROFILE_MIN_SAMPLE
            and profile.get("functional_confidence", 0) >= intel._GROUP_PROFILE_MIN_CONFIDENCE
            and intel._recommended_team_for_signal(
                ticket,
                ai_evidence_current=ticket.id in current_route_ids,
            )[0]
        ):
            routing_profiled += 1
        route_alert = intel.routing_alert(
            ticket,
            profile,
            now=now,
            ai_evidence_current=ticket.id in current_route_ids,
        )
        if route_alert:
            routing_alerts.append(route_alert)

        assessment = intel.support_level_assessment(ticket, profile)
        level_distribution[str(assessment["recommended_level"])] += 1
        if assessment["inferred_from_group_history"]:
            assigned_level_profiled += 1
        level_assessments.append(assessment)

        thread = conversations.get(ticket.id, [])
        friction = intel.customer_friction_signal(
            ticket,
            thread,
            now=now,
            terminal_statuses=terminal_statuses,
            conversation_truncated=(
                ticket.id in truncated_transcript_ticket_ids
            ),
        )
        if friction["flagged"]:
            friction_alerts.append(friction)
        clarification = intel.clarification_assessment(ticket, thread)
        if clarification["flagged"]:
            clarification_alerts.append(clarification)

    severity_order = {"high": 0, "medium": 1, "low": 2}
    routing_alerts.sort(key=lambda row: (
        severity_order.get(row["severity"], 3), -row["dormant_hours"], row["ticket_id"]
    ))
    friction_alerts.sort(key=lambda row: (
        severity_order.get(row["severity"], 3), -row["current_unanswered_gap_hours"], row["ticket_id"]
    ))
    clarification_alerts.sort(key=lambda row: (row["detail_score"], row["ticket_id"]))
    level_assessments.sort(key=lambda row: (
        not row["mismatch"],
        0 if row["mismatch_direction"] == "under-tiered" else 1,
        -row["recommended_level"],
        row["ticket_id"],
    ))
    level_mismatches = sum(row["mismatch"] for row in level_assessments)
    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "alert_only": True,
        "scope": {
            "total_active_tickets": total,
            "analyzed_tickets": len(tickets),
            "truncated": total > len(tickets),
            "group_profile_period_days": 365,
            "group_profile_group_limit": intel.GROUP_PROFILE_GROUP_LIMIT,
            "group_profile_aggregate_limit": intel.GROUP_PROFILE_AGGREGATE_LIMIT,
            "group_profiles_truncated": group_profiles_truncated,
            "transcript_limit_per_ticket": intel.PUBLIC_CONVERSATION_SAMPLE_LIMIT,
            "transcript_truncated": bool(truncated_transcript_ticket_ids),
            "transcript_truncated_tickets": len(truncated_transcript_ticket_ids),
        },
        "summary": {
            "routing_mismatches": len(routing_alerts),
            "routing_profiled_tickets": routing_profiled,
            "level_mismatches": level_mismatches,
            "assigned_level_profiled_tickets": assigned_level_profiled,
            "customer_friction": len(friction_alerts),
            "clarification_needed": len(clarification_alerts),
        },
        "routing_alerts": routing_alerts[:100],
        "level_distribution": level_distribution,
        "level_assessments": level_assessments[:100],
        "friction_alerts": friction_alerts[:100],
        "clarification_alerts": clarification_alerts[:100],
        "items_truncated": any(len(items) > 100 for items in (
            routing_alerts, level_assessments, friction_alerts, clarification_alerts,
        )),
    }


@app.get("/intelligence/sla-monitoring")
def intel_sla_monitoring(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """First-response and resolution SLA dashboard, reactive and proactive."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    terminal_statuses = _terminal_status_names(db)
    cutoff = _intelligence_cutoff(now, window_days)
    query = _sla_monitoring_ticket_query(db, cutoff)
    total = query.count()
    tickets = query.order_by(
        _ticket_activity_expression().desc(), TicketRecord.id.asc()
    ).limit(_INTELLIGENCE_SLA_ROW_LIMIT).all()
    rows = _sla_monitoring_rows(
        db,
        tickets,
        now=now,
        terminal_statuses=terminal_statuses,
    )
    measured, reactive, proactive = _sla_monitoring_partitions(rows)
    assignee_buckets: dict[tuple[Optional[str], Optional[str]], Dict[str, Any]] = {}
    for row in reactive:
        key = (row["assignee_source"], row["assignee_id"])
        bucket = assignee_buckets.setdefault(key, {
            "assignee_id": row["assignee_id"],
            "assignee_name": row["assignee_name"],
            "assignee_source": row["assignee_source"],
            "ticket_ids": set(),
            "breached_clock_count": 0,
        })
        bucket["ticket_ids"].add(row["ticket_id"])
        bucket["breached_clock_count"] += 1
    by_assignee = [{
        "assignee_id": bucket["assignee_id"],
        "assignee_name": bucket["assignee_name"],
        "assignee_source": bucket["assignee_source"],
        "breached_ticket_count": len(bucket["ticket_ids"]),
        "breached_clock_count": bucket["breached_clock_count"],
    } for bucket in assignee_buckets.values()]
    by_assignee.sort(key=lambda row: (
        -row["breached_ticket_count"],
        -row["breached_clock_count"],
        (row["assignee_name"] or "").lower(),
        row["assignee_source"] or "",
        row["assignee_id"] or "",
    ))
    by_priority: Dict[str, Any] = {}
    for row in measured:
        priority = row["priority"]
        bucket = by_priority.setdefault(priority, {
            "first_response": {"breached": 0, "approaching": 0},
            "resolution": {"breached": 0, "approaching": 0},
        })
        if row["status"] in {"breached", "approaching"}:
            bucket[row["metric"]][row["status"]] += 1
    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "scope": {
            "total_tickets": total,
            "analyzed_tickets": len(tickets),
            "truncated": total > len(tickets),
            "measured_clocks": len(measured),
            "unmeasured_clocks": len(rows) - len(measured),
        },
        "summary": {
            "reactive_breaches": len(reactive),
            "active_breaches": sum(row["breach_state"] == "active" for row in reactive),
            "historical_breaches": sum(row["breach_state"] == "historical" for row in reactive),
            "approaching_breaches": len(proactive),
            "first_response_breaches": sum(row["metric"] == "first_response" for row in reactive),
            "resolution_breaches": sum(row["metric"] == "resolution" for row in reactive),
        },
        "by_priority": by_priority,
        "by_assignee": by_assignee,
        "reactive": reactive[:100],
        "proactive": proactive[:100],
        "items_truncated": len(reactive) > 100 or len(proactive) > 100,
    }


@app.get("/intelligence/sla-monitoring/assignee-evidence")
def intel_sla_assignee_evidence(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    assignee_source: Literal["provider", "tickety", "unmapped"] = Query(...),
    assignee_id: Optional[str] = Query(None, min_length=1, max_length=255),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Return bounded breached-clock evidence for one resolved assignee identity."""
    requested_id = assignee_id.strip() if assignee_id is not None else None
    if assignee_source in {"provider", "tickety"} and not requested_id:
        raise HTTPException(
            status_code=422,
            detail="assignee_id is required for mapped assignee sources",
        )
    if assignee_source == "unmapped" and assignee_id is not None:
        raise HTTPException(
            status_code=422,
            detail="assignee_id must be omitted for unmapped assignees",
        )

    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    cutoff = _intelligence_cutoff(now, window_days)
    terminal_statuses = _terminal_status_names(db)
    query = _sla_monitoring_ticket_query(db, cutoff)

    response_id: Optional[str] = None
    response_name: Optional[str] = None
    response_source: Optional[str] = None
    if assignee_source == "provider":
        profile = db.query(ExternalUserRecord).filter(
            ExternalUserRecord.id == requested_id,
            ExternalUserRecord.active.is_(True),
            func.lower(ExternalUserRecord.user_type) == "agent",
        ).first()
        if profile is None:
            raise HTTPException(status_code=404, detail="Assignee identity not found")
        response_id = profile.id
        response_name = profile.name
        response_source = "provider"
        query = query.filter(
            TicketRecord.binding_id == profile.binding_id,
            TicketRecord.external_source == profile.provider,
            TicketRecord.external_assignee_id == profile.external_id,
        )
    elif assignee_source == "tickety":
        local_profile = db.query(UserRecord).filter(
            UserRecord.id == requested_id,
        ).first()
        if local_profile is None:
            raise HTTPException(status_code=404, detail="Assignee identity not found")
        response_id = local_profile.id
        response_name = local_profile.name
        response_source = "tickety"
        query = query.filter(
            TicketRecord.assignee_id == local_profile.id,
            func.nullif(TicketRecord.external_assignee_id, "").is_(None),
        )
    else:
        query = query.filter(_unmapped_intelligence_assignee_filter())

    total = query.count()
    tickets = query.order_by(
        _ticket_activity_expression().desc(), TicketRecord.id.asc()
    ).limit(_INTELLIGENCE_SLA_ROW_LIMIT).all()
    rows = _sla_monitoring_rows(
        db,
        tickets,
        now=now,
        terminal_statuses=terminal_statuses,
    )
    _measured, reactive, _proactive = _sla_monitoring_partitions(rows)
    if assignee_source == "unmapped":
        matching = [
            row for row in reactive
            if row["assignee_id"] is None and row["assignee_source"] is None
        ]
    else:
        matching = [
            row for row in reactive
            if row["assignee_id"] == response_id
            and row["assignee_source"] == response_source
        ]

    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "assignee_id": response_id,
        "assignee_name": response_name,
        "assignee_source": response_source,
        "breached_ticket_count": len({row["ticket_id"] for row in matching}),
        "breached_clock_count": len(matching),
        "items": matching[:_INTELLIGENCE_EVIDENCE_ROW_LIMIT],
        "items_truncated": len(matching) > _INTELLIGENCE_EVIDENCE_ROW_LIMIT,
        "scope": {
            "total_tickets": total,
            "analyzed_tickets": len(tickets),
            "truncated": total > len(tickets),
        },
    }


def _serialize_intelligence_study(record: IntelligenceStudyRecord) -> Dict[str, Any]:
    result = json.loads(record.result_json)
    return {
        **result,
        "run_id": record.id,
        "created_at": record.created_at.isoformat(),
        "created_by": record.created_by,
    }


@app.get("/intelligence/level-zero-study")
def get_level_zero_study(
    months: int = Query(12, ge=6, le=12),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Return the latest stable Level Zero snapshot without rerunning it."""
    _reserve_analytics_request(db, _user.id)
    record = db.query(IntelligenceStudyRecord).filter(
        IntelligenceStudyRecord.study_type == "level_zero_opportunity",
        IntelligenceStudyRecord.period_months == months,
    ).order_by(
        IntelligenceStudyRecord.created_at.desc(),
        IntelligenceStudyRecord.id.desc(),
    ).first()
    return {"study": _serialize_intelligence_study(record) if record else None}


@app.post("/intelligence/level-zero-study")
def run_level_zero_study(
    months: int = Query(12, ge=6, le=12),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Deliberately run and persist a complete 6-12 month Level Zero study."""
    _reserve_analytics_request(db, user.id)
    record, _result = intel.create_level_zero_study_snapshot(
        db, months=months, created_by=user.id
    )
    return _serialize_intelligence_study(record)

@app.get("/intelligence/alerts")
async def intel_alerts(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Proactive Alert Agent: unified feed of cases needing attention now."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    result = intel.proactive_alerts(
        db, now=now, since=_intelligence_cutoff(now, window_days)
    )
    result["window_days"] = window_days
    return result


@app.get("/intelligence/prioritize")
async def intel_prioritize(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Prioritization Agent: open backlog ranked by composite urgency/impact/risk."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    terminal_statuses = _terminal_status_names(db)
    open_query = _open_ticket_query(db, _intelligence_cutoff(now, window_days))
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
            "age_hours": round(
                intel._age_hours(t, now, terminal_statuses), 2
            ),
            "score": intel.prioritize_score(t, now, terminal_statuses),
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "backlog_size": total_open,
        "analyzed_tickets": len(open_tickets),
        "truncated": total_open > len(open_tickets),
        "ranked": ranked,
    }


@app.get("/intelligence/sla")
async def intel_sla(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """SLA Agent: SLA clock state for every open ticket."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    terminal_statuses = _terminal_status_names(db)
    open_query = _open_ticket_query(
        db, _intelligence_cutoff(now, window_days)
    ).filter(sla_eligible_filter(terminal_statuses))
    total_open = open_query.count()
    candidates = open_query.order_by(
        *_intelligence_candidate_order()
    ).limit(_INTELLIGENCE_ROW_LIMIT).all()
    rows = [
        intel.sla_status(ticket, now, terminal_statuses)
        for ticket in candidates
    ]
    rows.sort(key=lambda r: r["remaining_hours"])
    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "count": total_open,
        "analyzed_tickets": len(candidates),
        "truncated": total_open > len(candidates),
        "items": rows,
    }


@app.get("/intelligence/trends")
async def intel_trends(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Text Analytics Agent: category/sentiment distribution + top terms."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    result = intel.trends(db, since=_intelligence_cutoff(now, window_days))
    result["generated_at"] = now.isoformat()
    result["window_days"] = window_days
    return result


@app.get("/intelligence/systemic")
async def intel_systemic(
    db: Session = Depends(get_db),
    min_cluster: int = Query(2, ge=2, le=20, description="Minimum tickets to flag as a systemic issue"),
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Systemic Issue Detection: cluster similar tickets and surface broad
    business‑impact patterns. Returns clusters ranked by impact score, each
    with shared keywords, sample tickets, and priority/risk stats."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    result = intel.systemic_issues(
        db,
        cluster_threshold=min_cluster,
        since=_intelligence_cutoff(now, window_days),
    )
    result["generated_at"] = now.isoformat()
    result["window_days"] = window_days
    return result


@app.get("/intelligence/workload")
async def agent_workload(
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Agent workload: open tickets per agent + resolution metrics."""
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    cutoff = _intelligence_cutoff(now, window_days)
    external_user_query = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.active.is_(True),
        func.lower(ExternalUserRecord.user_type) == "agent",
    )
    external_total = external_user_query.count()
    external_users = external_user_query.order_by(
        ExternalUserRecord.name.asc(),
        ExternalUserRecord.id.asc(),
    ).limit(_INTELLIGENCE_ROW_LIMIT).all()

    if external_users:
        total_users = external_total
        analyzed_users = len(external_users)
        users_truncated = external_total > len(external_users)
        external_ids = [user.external_id for user in external_users]
        internal_ids = [user.id for user in external_users]
        assignment_rows = db.query(
            TicketRecord.binding_id,
            TicketRecord.external_assignee_id,
            func.count(TicketRecord.id),
            func.sum(case((
                func.lower(func.coalesce(TicketRecord.priority, "")).in_(["p1", "urgent"]),
                1,
            ), else_=0)),
        ).filter(
            TicketRecord.external_assignee_id.isnot(None),
            TicketRecord.external_assignee_id != "",
            _ticket_activity_expression() >= cutoff,
            _active_ticket_status_filter(db),
        ).group_by(
            TicketRecord.binding_id,
            TicketRecord.external_assignee_id,
        ).all()
        open_counts = {
            (binding_id, external_id): int(count)
            for binding_id, external_id, count, _p1_count in assignment_rows
        }
        p1_counts = {
            (binding_id, external_id): int(p1_count or 0)
            for binding_id, external_id, _count, p1_count in assignment_rows
        }
        known_external_keys = {
            (user.binding_id, user.external_id) for user in external_users
        }
        total_open_assignments = sum(open_counts.values())
        unmapped_open_assignments = sum(
            count for key, count in open_counts.items()
            if key not in known_external_keys
        )
        resolved_counts = {
            (binding_id, external_id): int(count)
            for binding_id, external_id, count in db.query(
                TicketRecord.binding_id,
                TicketRecord.external_assignee_id,
                func.count(TicketRecord.id),
            ).filter(
                TicketRecord.external_assignee_id.in_(external_ids),
                _ticket_resolved_expression() >= cutoff,
            ).group_by(
                TicketRecord.binding_id,
                TicketRecord.external_assignee_id,
            ).all()
        }
        duration_query = db.query(
            TicketRecord.binding_id,
            TicketRecord.external_assignee_id,
            _ticket_resolved_expression(),
            _ticket_created_expression(),
        ).filter(
            TicketRecord.external_assignee_id.in_(external_ids),
            _ticket_resolved_expression().isnot(None),
            _ticket_created_expression().isnot(None),
            _ticket_resolved_expression() >= cutoff,
        )
        total_duration_rows = duration_query.count()
        resolved_rows = duration_query.order_by(
            _ticket_resolved_expression().desc()
        ).limit(5_000).all()
        duration_totals: dict[tuple[str, str], tuple[float, int]] = {}
        for binding_id, external_id, resolved_at, created_at in resolved_rows:
            key = (binding_id, external_id)
            total_seconds, count = duration_totals.get(key, (0.0, 0))
            duration_totals[key] = (
                total_seconds + max(0.0, (resolved_at - created_at).total_seconds()),
                count + 1,
            )
        group_names: dict[str, List[str]] = {}
        for external_user_id, group_name in db.query(
            ExternalGroupMembershipRecord.external_user_id,
            ExternalGroupRecord.name,
        ).join(
            ExternalGroupRecord,
            ExternalGroupRecord.id == ExternalGroupMembershipRecord.external_group_id,
        ).filter(
            ExternalGroupMembershipRecord.external_user_id.in_(internal_ids),
            ExternalGroupMembershipRecord.membership_kind == "member",
            ExternalGroupRecord.active.is_(True),
        ).order_by(ExternalGroupRecord.name.asc()).all():
            group_names.setdefault(external_user_id, []).append(group_name)

        result = []
        for user in external_users:
            key = (user.binding_id, user.external_id)
            open_count = open_counts.get(key, 0)
            total_seconds, duration_count = duration_totals.get(key, (0.0, 0))
            result.append({
                "user_id": user.id,
                "name": user.name,
                "title": user.title,
                "source": "provider",
                "group_names": group_names.get(user.id, []),
                "open_tickets": open_count,
                "p1_open_tickets": p1_counts.get(key, 0),
                "total_resolved": resolved_counts.get(key, 0),
                "avg_resolution_hours": round(
                    total_seconds / duration_count / 3600, 1
                ) if duration_count else 0.0,
                "impact_points": 0,
                "tier": 1,
                "load_status": "overloaded" if open_count >= 9 else (
                    "high" if open_count >= 6 else "balanced"
                ),
            })
        workforce_source = "provider"
    else:
        user_query = db.query(UserRecord).filter(
            UserRecord.is_active.is_(True),
            func.lower(func.coalesce(UserRecord.role, "agent")).in_(["agent", "supervisor"]),
        )
        total_users = user_query.count()
        users = user_query.order_by(
            UserRecord.tier.desc(),
            UserRecord.impact_points.desc(),
            UserRecord.id.asc(),
        ).limit(_INTELLIGENCE_ROW_LIMIT).all()
        analyzed_users = len(users)
        users_truncated = total_users > len(users)
        user_ids = [user.id for user in users]
        open_counts = dict(db.query(
            TicketRecord.assignee_id,
            func.count(TicketRecord.id),
        ).filter(
            TicketRecord.assignee_id.in_(user_ids),
            _ticket_activity_expression() >= cutoff,
            _active_ticket_status_filter(db),
        ).group_by(TicketRecord.assignee_id).all()) if user_ids else {}
        p1_counts = dict(db.query(
            TicketRecord.assignee_id,
            func.count(TicketRecord.id),
        ).filter(
            TicketRecord.assignee_id.in_(user_ids),
            _ticket_activity_expression() >= cutoff,
            _active_ticket_status_filter(db),
            func.lower(func.coalesce(TicketRecord.priority, "")).in_(["p1", "urgent"]),
        ).group_by(TicketRecord.assignee_id).all()) if user_ids else {}
        resolved_counts = dict(db.query(
            TicketRecord.resolved_by,
            func.count(TicketRecord.id),
        ).filter(
            TicketRecord.resolved_by.in_(user_ids),
            _ticket_resolved_expression() >= cutoff,
        ).group_by(TicketRecord.resolved_by).all()) if user_ids else {}
        duration_query = db.query(
            TicketRecord.resolved_by,
            _ticket_resolved_expression(),
            _ticket_created_expression(),
        ).filter(
            TicketRecord.resolved_by.in_(user_ids),
            _ticket_resolved_expression().isnot(None),
            _ticket_created_expression().isnot(None),
            _ticket_resolved_expression() >= cutoff,
        )
        total_duration_rows = duration_query.count() if user_ids else 0
        resolved_rows = duration_query.order_by(
            _ticket_resolved_expression().desc()
        ).limit(5_000).all() if user_ids else []
        duration_totals: dict[str, tuple[float, int]] = {}
        for resolved_by, resolved_at, created_at in resolved_rows:
            total_seconds, count = duration_totals.get(resolved_by, (0.0, 0))
            duration_totals[resolved_by] = (
                total_seconds + max(0.0, (resolved_at - created_at).total_seconds()),
                count + 1,
            )
        result = []
        for user in users:
            open_count = int(open_counts.get(user.id, 0))
            total_seconds, duration_count = duration_totals.get(user.id, (0.0, 0))
            result.append({
                "user_id": user.id,
                "name": user.name,
                "title": user.title,
                "source": "tickety",
                "group_names": [],
                "open_tickets": open_count,
                "p1_open_tickets": int(p1_counts.get(user.id, 0)),
                "total_resolved": int(resolved_counts.get(user.id, 0)),
                "avg_resolution_hours": round(
                    total_seconds / duration_count / 3600, 1
                ) if duration_count else 0.0,
                "impact_points": user.impact_points,
                "tier": user.tier,
                "load_status": "overloaded" if open_count >= 9 else (
                    "high" if open_count >= 6 else "balanced"
                ),
            })
        workforce_source = "tickety"
        total_open_assignments = sum(int(value) for value in open_counts.values())
        unmapped_open_assignments = 0

    result.sort(key=lambda row: (
        -row["open_tickets"], -row["p1_open_tickets"], row["name"].lower()
    ))
    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "workforce_source": workforce_source,
        "assigned_users": sum(row["open_tickets"] > 0 for row in result),
        "total_open_assignments": total_open_assignments,
        "unmapped_open_assignments": unmapped_open_assignments,
        "agents": result,
        "total_users": total_users,
        "analyzed_users": analyzed_users,
        "users_truncated": users_truncated,
        "duration_rows_analyzed": len(resolved_rows),
        "duration_rows_truncated": total_duration_rows > len(resolved_rows),
    }

@app.get("/intelligence/health/{reporter}")
async def intel_health(
    reporter: str,
    window_days: int = Query(_INTELLIGENCE_DEFAULT_WINDOW_DAYS, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_protected_ai_role("admin", "supervisor")),
):
    """Account Health Agent: per-reporter health score + churn-risk band."""
    if len(reporter) > 320:
        raise HTTPException(status_code=422, detail="Reporter identifier is too long")
    _reserve_analytics_request(db, _user.id)
    now = datetime.utcnow()
    result = intel.account_health(
        db, reporter, since=_intelligence_cutoff(now, window_days)
    )
    if result["health_score"] is None:
        raise HTTPException(
            status_code=404,
            detail="No tickets for that reporter in the selected activity window",
        )
    result["generated_at"] = now.isoformat()
    result["window_days"] = window_days
    return result


@app.get("/intelligence/route/{ticket_id}")
async def intel_route(
    ticket_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_protected_ai_user),
):
    """Return the current advisory resolver-group route without generating one."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(_user, ticket, db)
    route = _routing_result_payload(ticket)
    if route is None or not _artifact_is_current(db, ticket, "route"):
        raise HTTPException(status_code=409, detail="routing_not_analyzed")
    return route


@app.post(
    "/tickets/{ticket_id}/route",
    response_model=ResolverRoutingAnalysis,
)
async def ticket_route(
    ticket_id: str,
    force: bool = Query(False, description="Regenerate even if current routing is fresh"),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(get_protected_ai_user),
):
    """Generate an advisory resolver-group route; never assign a person or group."""
    ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _authorize_ticket_analysis(_user, ticket, db)
    _reserve_ai_request(db, _user.id, "route")
    ticket, _user = _lock_authorized_ticket_analysis(db, ticket_id, _user)
    result = await _run_ticket_analysis(
        ticket,
        db,
        force=force,
        artifacts={"route"},
        analysis_actor_id=_user.id,
    )
    route = result.get("route")
    if route is None:
        raise HTTPException(status_code=503, detail="routing_unavailable")
    return route


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
    _authorize_ticket_analysis(_user, ticket, db)
    _reserve_ai_request(db, _user.id, "summary")
    ticket, _user = _lock_authorized_ticket_analysis(db, ticket_id, _user)
    result = await _run_ticket_analysis(
        ticket,
        db,
        force=force,
        artifacts={"summary"},
        analysis_actor_id=_user.id,
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
    _authorize_ticket_analysis(_user, ticket, db)
    _reserve_ai_request(db, _user.id, "resolution")
    ticket, _user = _lock_authorized_ticket_analysis(db, ticket_id, _user)
    result = await _run_ticket_analysis(
        ticket,
        db,
        force=force,
        artifacts={"resolution"},
        analysis_actor_id=_user.id,
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
    ticket_id = ticket.id
    try:
        # Read the candidate without a lock, then acquire User -> Ticket. If an
        # assignment writer won in between, release and retry against the new
        # owner rather than introducing Ticket -> User lock inversion.
        locked_user: Optional[UserRecord] = None
        locked_ticket: Optional[TicketRecord] = None
        for _attempt in range(5):
            candidate = db.query(TicketRecord.assignee_id).filter(
                TicketRecord.id == ticket_id
            ).scalar()
            if not candidate:
                db.rollback()
                return
            try:
                locked_user = _lock_user_record(db, candidate)
                locked_ticket = _lock_ticket_record(db, ticket_id)
            except HTTPException as exc:
                db.rollback()
                if exc.status_code == 404:
                    locked_user = None
                    locked_ticket = None
                    continue
                raise
            if locked_ticket.assignee_id == locked_user.id:
                break
            db.rollback()
            locked_user = None
            locked_ticket = None
        if locked_user is None or locked_ticket is None:
            return

        user = locked_user
        ticket = locked_ticket
        terminal_names = _terminal_status_names(db)
        if ticket.external_status:
            is_terminal = portable_ascii_lower(ticket.external_status) in terminal_names
        else:
            is_terminal = (
                _is_terminal_status(db, ticket.status)
                or _is_terminal_status(db, ticket.workflow_status)
            )
        if not is_terminal or ticket.points_awarded_sent:
            db.rollback()
            return
        if (
            not user.is_active
            or (user.role or "").lower() not in _OPERATIONAL_USER_ROLES
        ):
            db.rollback()
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
        raise
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
            values = dict(
                user_id=user.id,
                recognition_key=key,
                ticket_id=ticket.id,
            )
            dialect = db.get_bind().dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            elif dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            else:
                if not db.query(RecognitionRecord.id).filter(
                    RecognitionRecord.user_id == user.id,
                    RecognitionRecord.recognition_key == key,
                ).first():
                    db.add(RecognitionRecord(**values))
                    unlocked.append(key)
                continue
            inserted = db.execute(
                insert(RecognitionRecord)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["user_id", "recognition_key"],
                )
                .returning(RecognitionRecord.recognition_key)
            ).scalar_one_or_none()
            if inserted:
                existing_keys.add(inserted)
                unlocked.append(inserted)

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

def _lock_active_user_reference(
    db: Session,
    user_id: Optional[str],
    *,
    label: str,
) -> None:
    if not user_id:
        return
    if "\x00" in user_id:
        raise HTTPException(status_code=422, detail=f"{label} must not contain NUL")
    try:
        user = _lock_user_record(db, user_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise HTTPException(status_code=404, detail=f"{label} not found") from exc
    if not user.is_active:
        raise HTTPException(status_code=409, detail=f"{label} must be active")
    if (user.role or "").lower() not in _OPERATIONAL_USER_ROLES:
        raise HTTPException(
            status_code=409,
            detail=f"{label} must have a supported operational role",
        )

@app.get("/projects", response_model=List[Project])
async def list_projects(
    response: Response,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
):
    page = db.query(ProjectRecord).order_by(
        ProjectRecord.name,
        ProjectRecord.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    projects = page[:limit]

    lead_ids = {project.lead_id for project in projects if project.lead_id}
    lead_names = dict(
        db.query(UserRecord.id, UserRecord.name).filter(
            UserRecord.id.in_(lead_ids)
        ).all()
    ) if lead_ids else {}
    for project in projects:
        project.__dict__["lead_name"] = lead_names.get(project.lead_id)

    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    return projects


@app.post("/projects", response_model=Project, status_code=201)
async def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    _lock_active_user_reference(db, payload.lead_id, label="Project lead")
    existing = db.query(ProjectRecord).filter(ProjectRecord.key == payload.key.upper()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project key already exists")
    project = ProjectRecord(
        id=f"proj-{_uuid.uuid4().hex}",
        name=payload.name,
        key=payload.key.upper(),
        description=payload.description,
        lead_id=payload.lead_id,
    )
    db.add(project)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Project key or lead changed while saving",
        ) from exc
    db.refresh(project)
    return project


@app.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(ProjectRecord).filter(ProjectRecord.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if "lead_id" in payload.model_fields_set:
        _lock_active_user_reference(db, payload.lead_id, label="Project lead")
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field == "description" and value is None:
            value = ""
        setattr(project, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Project references changed while saving",
        ) from exc
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

_SERVICE_CATEGORY_OPTION_LIMIT = 100
_SERVICE_CATEGORY_HEADER_BUDGET = 6_000


def _literal_list_search_pattern(value: Optional[str]) -> Optional[str]:
    """Return a bounded literal ILIKE pattern for list endpoints."""
    normalized = (value or "").strip()
    if not normalized:
        return None
    if "\x00" in normalized:
        raise HTTPException(status_code=422, detail="Search must not contain NUL")
    escaped = (
        normalized
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _service_category_options(
    db: Session,
) -> tuple[list[str], bool]:
    """Return header-safe active category options with explicit truncation."""
    rows = db.query(ServiceItemRecord.category).filter(
        ServiceItemRecord.is_active.is_(True),
        ServiceItemRecord.category.isnot(None),
        func.trim(ServiceItemRecord.category) != "",
    ).distinct().order_by(
        ServiceItemRecord.category.asc(),
    ).limit(
        _SERVICE_CATEGORY_OPTION_LIMIT + 1
    ).all()
    truncated = len(rows) > _SERVICE_CATEGORY_OPTION_LIMIT
    options: list[str] = []
    for (category,) in rows[:_SERVICE_CATEGORY_OPTION_LIMIT]:
        value = str(category)
        if "\x00" in value:
            truncated = True
            continue
        encoded = json.dumps(
            [*options, value],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if len(encoded.encode("ascii")) > _SERVICE_CATEGORY_HEADER_BUDGET:
            truncated = True
            break
        options.append(value)
    return options, truncated


@app.get("/services", response_model=List[ServiceItem])
async def list_services(
    response: Response,
    db: Session = Depends(get_db),
    category: Optional[str] = Query(
        default=None,
        max_length=255,
        pattern=r"^[^\x00]*$",
    ),
    search: Optional[str] = Query(
        default=None,
        max_length=200,
        pattern=r"^[^\x00]*$",
    ),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
):
    q = db.query(ServiceItemRecord)
    if category not in (None, ""):
        q = q.filter(ServiceItemRecord.category == category)
    if is_active is not None:
        q = q.filter(ServiceItemRecord.is_active.is_(is_active))
    search_pattern = _literal_list_search_pattern(search)
    if search_pattern:
        q = q.filter(or_(
            ServiceItemRecord.id.ilike(search_pattern, escape="\\"),
            ServiceItemRecord.name.ilike(search_pattern, escape="\\"),
            ServiceItemRecord.description.ilike(search_pattern, escape="\\"),
            ServiceItemRecord.category.ilike(search_pattern, escape="\\"),
            ServiceItemRecord.pricing.ilike(search_pattern, escape="\\"),
        ))

    page = q.order_by(
        func.coalesce(ServiceItemRecord.category, "").asc(),
        ServiceItemRecord.name.asc(),
        ServiceItemRecord.id.asc(),
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    services = page[:limit]

    active_category = case((and_(
        ServiceItemRecord.is_active.is_(True),
        ServiceItemRecord.category.isnot(None),
        func.trim(ServiceItemRecord.category) != "",
    ), ServiceItemRecord.category), else_=None)
    total, active, category_count = db.query(
        func.count(ServiceItemRecord.id),
        func.sum(case((ServiceItemRecord.is_active.is_(True), 1), else_=0)),
        func.count(func.distinct(active_category)),
    ).one()
    category_options, category_options_truncated = _service_category_options(db)

    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    response.headers["X-Service-Total"] = str(int(total or 0))
    response.headers["X-Service-Active"] = str(int(active or 0))
    response.headers["X-Service-Category-Count"] = str(int(category_count or 0))
    response.headers["X-Service-Category-Options"] = json.dumps(
        category_options,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    response.headers["X-Service-Category-Options-Truncated"] = str(
        category_options_truncated
    ).lower()
    return services


@app.post("/services", response_model=ServiceItem, status_code=201)
async def create_service(payload: ServiceItemCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    item = ServiceItemRecord(id=f"svc-{_uuid.uuid4().hex}", **payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Service item identity changed while saving",
        ) from exc
    db.refresh(item)
    return item


@app.patch("/services/{service_id}", response_model=ServiceItem)
async def update_service(
    service_id: str,
    payload: ServiceItemUpdate,
    db: Session = Depends(get_db),
):
    item = db.query(ServiceItemRecord).filter(ServiceItemRecord.id == service_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Service item not found")
    if "name" in payload.model_fields_set and payload.name is None:
        raise HTTPException(status_code=422, detail="Service name cannot be null")
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field == "description" and value is None:
            value = ""
        setattr(item, field, value)
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
async def list_service_requests(
    response: Response,
    db: Session = Depends(get_db),
    search: Optional[str] = Query(
        default=None,
        max_length=200,
        pattern=r"^[^\x00]*$",
    ),
    service_item_id: Optional[str] = Query(
        default=None,
        max_length=255,
        pattern=r"^[^\x00]*$",
    ),
    approval_status: Optional[str] = Query(
        default=None,
        max_length=32,
        pattern=r"^(not_required|pending|approved|rejected)?$",
    ),
    fulfillment_status: Optional[str] = Query(
        default=None,
        max_length=32,
        pattern=r"^(pending|fulfilled|cancelled)?$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
):
    q = db.query(ServiceRequestRecord)
    if service_item_id not in (None, ""):
        q = q.filter(ServiceRequestRecord.service_item_id == service_item_id)
    if approval_status:
        q = q.filter(ServiceRequestRecord.approval_status == approval_status)
    if fulfillment_status:
        q = q.filter(ServiceRequestRecord.fulfillment_status == fulfillment_status)
    search_pattern = _literal_list_search_pattern(search)
    if search_pattern:
        q = q.outerjoin(
            ServiceItemRecord,
            ServiceItemRecord.id == ServiceRequestRecord.service_item_id,
        ).filter(or_(
            ServiceRequestRecord.id.ilike(search_pattern, escape="\\"),
            ServiceRequestRecord.ticket_id.ilike(search_pattern, escape="\\"),
            ServiceRequestRecord.justification.ilike(search_pattern, escape="\\"),
            ServiceRequestRecord.delivery_notes.ilike(search_pattern, escape="\\"),
            ServiceItemRecord.name.ilike(search_pattern, escape="\\"),
        ))

    page = q.order_by(
        ServiceRequestRecord.created_at.desc().nullslast(),
        ServiceRequestRecord.id.asc(),
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    reqs = page[:limit]
    service_ids = {request.service_item_id for request in reqs if request.service_item_id}
    service_names = {
        service.id: service.name
        for service in db.query(ServiceItemRecord).filter(ServiceItemRecord.id.in_(service_ids)).all()
    } if service_ids else {}
    for request in reqs:
        request.__dict__["service_name"] = service_names.get(request.service_item_id)

    normalized_fulfillment = func.lower(func.trim(func.coalesce(
        ServiceRequestRecord.fulfillment_status, ""
    )))
    normalized_approval = func.lower(func.trim(func.coalesce(
        ServiceRequestRecord.approval_status, ""
    )))
    total, open_count, pending, pending_approval, awaiting_fulfillment = db.query(
        func.count(ServiceRequestRecord.id),
        func.sum(case((
            normalized_fulfillment.notin_(("fulfilled", "cancelled")), 1
        ), else_=0)),
        func.sum(case((normalized_fulfillment == "pending", 1), else_=0)),
        func.sum(case((normalized_approval == "pending", 1), else_=0)),
        func.sum(case((and_(
            normalized_fulfillment == "pending",
            normalized_approval.in_(("approved", "not_required")),
        ), 1), else_=0)),
    ).one()

    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    response.headers["X-Service-Request-Total"] = str(int(total or 0))
    response.headers["X-Service-Request-Open"] = str(int(open_count or 0))
    response.headers["X-Service-Request-Pending"] = str(int(pending or 0))
    response.headers["X-Service-Request-Pending-Approval"] = str(
        int(pending_approval or 0)
    )
    response.headers["X-Service-Request-Awaiting-Fulfillment"] = str(
        int(awaiting_fulfillment or 0)
    )
    return reqs


@app.post("/service-requests", response_model=ServiceRequest, status_code=201)
async def create_service_request(payload: ServiceRequestCreate, db: Session = Depends(get_db)):
    _require_demo_ticketing()
    import uuid as _uuid

    # A request does not exist yet, so creation cannot begin with the
    # ServiceRequest -> Ticket lock order used by decisions.  Locking the
    # ticket first serializes all competing creates for that ticket; the
    # existing-request read happens only after the waiting transaction has
    # refreshed the ticket row.
    matched_ticket = db.query(TicketRecord).filter(
        TicketRecord.id == payload.ticket_id
    ).update(
        {TicketRecord.updated_at: TicketRecord.updated_at},
        synchronize_session=False,
    )
    if matched_ticket != 1:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket = db.query(TicketRecord).filter(
        TicketRecord.id == payload.ticket_id
    ).populate_existing().first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if (
        _is_terminal_status(db, ticket.status)
        or _is_terminal_status(db, ticket.workflow_status)
        or _ticket_has_resolution_history(ticket)
    ):
        raise HTTPException(
            status_code=409,
            detail="Resolved tickets cannot be converted to service requests",
        )
    if db.query(ProblemTicketLinkRecord.id).filter(
        ProblemTicketLinkRecord.ticket_id == ticket.id
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Problem-linked incidents cannot become service requests",
        )

    existing = db.query(ServiceRequestRecord.id).filter(
        ServiceRequestRecord.ticket_id == payload.ticket_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ticket already has a service request")

    # The conditional no-op UPDATE both locks the catalog row until commit and
    # re-evaluates ``is_active`` after a concurrent deactivation commits.
    matched_service = db.query(ServiceItemRecord).filter(
        ServiceItemRecord.id == payload.service_item_id,
        ServiceItemRecord.is_active.is_(True),
    ).update(
        {
            ServiceItemRecord.is_active: ServiceItemRecord.is_active,
            ServiceItemRecord.updated_at: ServiceItemRecord.updated_at,
        },
        synchronize_session=False,
    )
    if matched_service != 1:
        raise HTTPException(status_code=404, detail="Service item not found")
    service = db.query(ServiceItemRecord).filter(
        ServiceItemRecord.id == payload.service_item_id
    ).populate_existing().first()
    if not service or not service.is_active:
        raise HTTPException(status_code=404, detail="Service item not found")

    requested_at = datetime.utcnow()
    approval_status = "pending" if service.approval_required else "not_required"
    sr = ServiceRequestRecord(
        id=f"sr-{_uuid.uuid4().hex}",
        approval_status=approval_status,
        fulfillment_status="pending",
        created_at=requested_at,
        **payload.model_dump(),
    )
    ticket.ticket_type = "request"
    ticket.service_id = service.id
    ticket.workflow_status = "Pending Approval" if service.approval_required else "Pending Fulfillment"
    ticket.status = ticket.workflow_status
    if service.sla_hours:
        ticket.resolution_due_at = requested_at + timedelta(hours=service.sla_hours)
        ticket.due_by = ticket.resolution_due_at
    db.add(sr)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ticket already has a service request or references changed while saving",
        ) from exc
    db.refresh(sr)
    return sr


def _lock_service_request(
    db: Session,
    request_id: str,
) -> ServiceRequestRecord:
    """Serialize a request write before its linked ticket is touched.

    A no-op UPDATE obtains a PostgreSQL row lock and SQLite's database write
    lock. Re-reading with ``populate_existing`` prevents a waiting transaction
    from deciding against stale identity-map state after the winner commits.
    """
    matched = db.query(ServiceRequestRecord).filter(
        ServiceRequestRecord.id == request_id
    ).update(
        {ServiceRequestRecord.quantity: ServiceRequestRecord.quantity},
        synchronize_session=False,
    )
    if matched != 1:
        raise HTTPException(status_code=404, detail="Service request not found")
    request_record = db.query(ServiceRequestRecord).filter(
        ServiceRequestRecord.id == request_id
    ).populate_existing().first()
    if not request_record:
        raise HTTPException(status_code=404, detail="Service request not found")
    return request_record


def _lock_service_request_ticket(
    db: Session,
    ticket_id: str,
) -> TicketRecord:
    """Lock the linked ticket after its service request, preserving lock order."""
    matched = db.query(TicketRecord).filter(
        TicketRecord.id == ticket_id
    ).update(
        {TicketRecord.updated_at: TicketRecord.updated_at},
        synchronize_session=False,
    )
    if matched != 1:
        raise HTTPException(
            status_code=409,
            detail="Service request is missing its linked ticket",
        )
    ticket = db.query(TicketRecord).filter(
        TicketRecord.id == ticket_id
    ).populate_existing().first()
    if not ticket:
        raise HTTPException(
            status_code=409,
            detail="Service request is missing its linked ticket",
        )
    return ticket


def _lock_service_request_actor(
    db: Session,
    actor_id: str,
) -> UserRecord:
    """Keep the decision actor valid for the whole request transaction.

    User -> ServiceRequest -> Ticket matches account purge/deactivation order
    and prevents an approval audit field from referencing a concurrently
    removed or demoted account.
    """
    actor = _lock_user_record(db, actor_id)
    if (
        not actor.is_active
        or (actor.role or "").lower() not in {"admin", "supervisor"}
    ):
        raise HTTPException(
            status_code=409,
            detail="Service request decision actor is no longer authorized",
        )
    return actor


@app.patch("/service-requests/{request_id}/approval", response_model=ServiceRequest)
async def decide_service_request_approval(
    request_id: str,
    payload: ServiceRequestApprovalDecision,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    _require_demo_ticketing()
    user = _lock_service_request_actor(db, user.id)
    sr = _lock_service_request(db, request_id)
    ticket = _lock_service_request_ticket(db, sr.ticket_id)
    if (
        _ticket_has_resolution_history(ticket)
        or _is_terminal_status(db, ticket.status)
        or _is_terminal_status(db, ticket.workflow_status)
    ):
        raise HTTPException(
            status_code=409,
            detail="Linked ticket lifecycle is already terminal",
        )
    if sr.approval_status == "not_required":
        raise HTTPException(status_code=400, detail="Approval is not required for this request")
    if sr.approval_status != "pending":
        raise HTTPException(status_code=409, detail="Service request approval already decided")
    if sr.fulfillment_status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Service request fulfillment already decided",
        )
    sr.approval_status = payload.decision
    sr.approved_by = user.id
    sr.approved_at = datetime.utcnow()
    if payload.comment:
        sr.delivery_notes = payload.comment
    if payload.decision == "approved":
        sr.fulfillment_status = "pending"
        ticket.workflow_status = "Pending Fulfillment"
        ticket.status = ticket.workflow_status
        ticket.resolved_at = None
    else:
        sr.fulfillment_status = "cancelled"
        ticket.workflow_status = "Request Rejected"
        ticket.status = "Cancelled"
        ticket.resolved_at = None
        mark_terminal_ai_not_applicable(ticket)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Service request references changed while saving",
        ) from exc
    db.refresh(sr)
    return sr


@app.patch("/service-requests/{request_id}/fulfillment", response_model=ServiceRequest)
async def update_service_request_fulfillment(
    request_id: str,
    payload: ServiceRequestFulfillmentUpdate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    _require_demo_ticketing()
    user = _lock_service_request_actor(db, user.id)
    sr = _lock_service_request(db, request_id)
    ticket = _lock_service_request_ticket(db, sr.ticket_id)
    if (
        _ticket_has_resolution_history(ticket)
        or _is_terminal_status(db, ticket.status)
        or _is_terminal_status(db, ticket.workflow_status)
    ):
        raise HTTPException(
            status_code=409,
            detail="Linked ticket lifecycle is already terminal",
        )
    if sr.fulfillment_status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Service request fulfillment already decided",
        )
    if sr.approval_status == "pending":
        raise HTTPException(status_code=400, detail="Service request must be approved before fulfillment")
    if sr.approval_status == "rejected":
        raise HTTPException(status_code=400, detail="Rejected service requests cannot be fulfilled")
    if sr.approval_status not in {"approved", "not_required"}:
        raise HTTPException(
            status_code=409,
            detail="Service request approval state is invalid",
        )
    sr.fulfillment_status = payload.status
    sr.delivery_notes = payload.delivery_notes or sr.delivery_notes
    if payload.status == "fulfilled":
        sr.fulfilled_by = user.id
        sr.fulfilled_at = datetime.utcnow()
        ticket.workflow_status = "Resolved"
        ticket.status = "Resolved"
        ticket.resolved_at = ticket.resolved_at or datetime.utcnow()
        mark_terminal_ai_not_applicable(ticket)
    else:
        ticket.workflow_status = "Request Cancelled"
        ticket.status = "Cancelled"
        ticket.resolved_at = None
        mark_terminal_ai_not_applicable(ticket)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Service request references changed while saving",
        ) from exc
    db.refresh(sr)
    return sr


# ── Problem Management ─────────────────────────────────────────

_PROBLEM_INVESTIGATING_STATUSES = ("Under Investigation", "Investigating")


def _lock_problem(db: Session, problem_id: str) -> ProblemRecord:
    matched = db.query(ProblemRecord).filter(
        ProblemRecord.id == problem_id
    ).update(
        {ProblemRecord.updated_at: ProblemRecord.updated_at},
        synchronize_session=False,
    )
    if matched != 1:
        raise HTTPException(status_code=404, detail="Problem not found")
    problem = db.query(ProblemRecord).filter(
        ProblemRecord.id == problem_id
    ).populate_existing().first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem

@app.get("/problems", response_model=List[Problem])
async def list_problems(
    response: Response,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
    status: Optional[str] = Query(default=None, max_length=32, pattern=r"^[^\x00]*$"),
    search: Optional[str] = Query(default=None, max_length=200, pattern=r"^[^\x00]*$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
):
    assigned_user = aliased(UserRecord)
    q = db.query(ProblemRecord).outerjoin(
        assigned_user,
        assigned_user.id == ProblemRecord.assigned_to,
    )
    if status:
        if status == "Under Investigation":
            q = q.filter(ProblemRecord.status.in_(_PROBLEM_INVESTIGATING_STATUSES))
        else:
            q = q.filter(ProblemRecord.status == status)
    normalized_search = (search or "").strip()
    if normalized_search:
        escaped_search = (
            normalized_search
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        q = q.filter(or_(
            ProblemRecord.id.ilike(pattern, escape="\\"),
            ProblemRecord.title.ilike(pattern, escape="\\"),
            ProblemRecord.description.ilike(pattern, escape="\\"),
            ProblemRecord.category.ilike(pattern, escape="\\"),
            assigned_user.name.ilike(pattern, escape="\\"),
        ))

    page = q.order_by(
        desc(ProblemRecord.created_at),
        ProblemRecord.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    problems = page[:limit]
    problem_ids = [problem.id for problem in problems]
    owner_ids = {problem.assigned_to for problem in problems if problem.assigned_to}
    owner_names = dict(
        db.query(UserRecord.id, UserRecord.name).filter(
            UserRecord.id.in_(owner_ids)
        ).all()
    ) if owner_ids else {}
    linked_counts = dict(
        db.query(
            ProblemTicketLinkRecord.problem_id,
            func.count(ProblemTicketLinkRecord.id),
        ).filter(
            ProblemTicketLinkRecord.problem_id.in_(problem_ids)
        ).group_by(
            ProblemTicketLinkRecord.problem_id
        ).all()
    ) if problem_ids else {}
    for problem in problems:
        problem.__dict__["assigned_name"] = owner_names.get(problem.assigned_to)
        problem.__dict__["linked_tickets_count"] = int(linked_counts.get(problem.id, 0))

    total, investigating, known_errors = db.query(
        func.count(ProblemRecord.id),
        func.sum(case((
            ProblemRecord.status.in_(_PROBLEM_INVESTIGATING_STATUSES), 1
        ), else_=0)),
        func.sum(case((ProblemRecord.status == "Known Error", 1), else_=0)),
    ).one()
    linked_total = int(db.query(func.count(ProblemTicketLinkRecord.id)).scalar() or 0)
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    response.headers["X-Problem-Total"] = str(int(total or 0))
    response.headers["X-Problem-Investigating"] = str(int(investigating or 0))
    response.headers["X-Problem-Known-Errors"] = str(int(known_errors or 0))
    response.headers["X-Problem-Linked-Tickets"] = str(linked_total)
    return problems


@app.get("/problems/{problem_id}", response_model=Problem)
async def get_problem(
    problem_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
):
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
    _lock_active_user_reference(db, payload.assigned_to, label="Problem assignee")
    problem = ProblemRecord(id=f"prob-{_uuid.uuid4().hex}", **payload.model_dump())
    db.add(problem)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Problem references changed while saving",
        ) from exc
    db.refresh(problem)
    return problem


@app.patch("/problems/{problem_id}", response_model=Problem)
async def update_problem(problem_id: str, payload: ProblemUpdate, db: Session = Depends(get_db)):
    if "assigned_to" in payload.model_fields_set:
        _lock_active_user_reference(db, payload.assigned_to, label="Problem assignee")
    problem = _lock_problem(db, problem_id)
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field == "description" and value is None:
            value = ""
        setattr(problem, field, value)
    if problem.status in ("Resolved", "Closed"):
        if not problem.root_cause:
            raise HTTPException(status_code=400, detail="Root cause is required before closing a problem")
        if not (problem.resolution or problem.workaround):
            raise HTTPException(status_code=400, detail="Resolution or workaround is required before closing a problem")
    if "status" in payload.model_fields_set:
        if problem.status in ("Resolved", "Closed"):
            problem.closed_at = problem.closed_at or datetime.utcnow()
        else:
            problem.closed_at = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Problem references changed while saving",
        ) from exc
    db.refresh(problem)
    return problem


@app.delete("/problems/{problem_id}")
async def delete_problem(problem_id: str, db: Session = Depends(get_db)):
    problem = _lock_problem(db, problem_id)
    db.query(ProblemTicketLinkRecord).filter(ProblemTicketLinkRecord.problem_id == problem_id).delete()
    db.delete(problem)
    db.commit()
    return {"status": "deleted"}


@app.post("/problems/{problem_id}/link/{ticket_id}", status_code=201)
async def link_ticket_to_problem(problem_id: str, ticket_id: str, db: Session = Depends(get_db)):
    _lock_problem(db, problem_id)
    ticket = _lock_ticket_record(db, ticket_id)
    if portable_ascii_lower(ticket.ticket_type) != "incident":
        raise HTTPException(
            status_code=409,
            detail="Only incident tickets can be linked as problem evidence",
        )
    existing = db.query(ProblemTicketLinkRecord).filter(
        ProblemTicketLinkRecord.problem_id == problem_id, ProblemTicketLinkRecord.ticket_id == ticket_id
    ).first()
    if existing:
        return {"status": "exists"}
    db.add(ProblemTicketLinkRecord(problem_id=problem_id, ticket_id=ticket_id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raced = db.query(ProblemTicketLinkRecord.id).filter(
            ProblemTicketLinkRecord.problem_id == problem_id,
            ProblemTicketLinkRecord.ticket_id == ticket_id,
        ).first()
        if raced:
            return {"status": "exists"}
        raise HTTPException(
            status_code=409,
            detail="Problem or ticket changed while linking",
        ) from exc
    return {"status": "linked"}


@app.delete("/problems/{problem_id}/link/{ticket_id}")
async def unlink_ticket_from_problem(problem_id: str, ticket_id: str, db: Session = Depends(get_db)):
    _lock_problem(db, problem_id)
    _lock_ticket_record(db, ticket_id)
    db.query(ProblemTicketLinkRecord).filter(
        ProblemTicketLinkRecord.problem_id == problem_id, ProblemTicketLinkRecord.ticket_id == ticket_id
    ).delete()
    db.commit()
    return {"status": "unlinked"}


@app.get("/problems/{problem_id}/tickets", response_model=List[Ticket])
async def get_problem_tickets(
    problem_id: str,
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    allowed_assignee_id = _ticket_scope_assignee_id(user)
    if not db.query(ProblemRecord.id).filter(ProblemRecord.id == problem_id).first():
        raise HTTPException(status_code=404, detail="Problem not found")
    query = db.query(TicketRecord).join(
        ProblemTicketLinkRecord,
        ProblemTicketLinkRecord.ticket_id == TicketRecord.id,
    ).filter(ProblemTicketLinkRecord.problem_id == problem_id)
    if allowed_assignee_id is not None:
        query = query.filter(or_(
            TicketRecord.assignee_id.is_(None),
            TicketRecord.assignee_id == allowed_assignee_id,
        ))
    page = query.order_by(
        TicketRecord.created_at.desc(),
        TicketRecord.id.asc(),
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    tickets = page[:limit]
    direct: set[tuple[str, str, str]] = set()
    groups: dict[tuple[str, str, str], ExternalGroupRecord] = {}
    if (user.role or "").lower() == "agent":
        direct, groups = _agent_assignment_context(
            db,
            user,
            [ticket.id for ticket in tickets],
        )
    return [
        _ticket_for_request(
            request,
            ticket,
            redact_ai=(
                (user.role or "").lower() == "agent"
                and _agent_ticket_scope_from_context(
                    user, ticket, direct, groups
                )[0] is None
            ),
        )
        for ticket in tickets
    ]


# ── Change Management ──────────────────────────────────────────

_CHANGE_STATUSES = {
    "Draft", "Submitted", "CAB Review", "Approved", "In Progress",
    "Completed", "Rejected", "Cancelled",
}
_CHANGE_APPROVAL_REQUIRED_STATUSES = {"Approved", "In Progress", "Completed"}
_CHANGE_APPROVAL_OPEN_STATUSES = {"Draft", "Submitted", "CAB Review"}
_CHANGE_TERMINAL_STATUSES = {"Completed", "Rejected", "Cancelled"}
_CHANGE_TRANSITIONS = {
    "Draft": {"Submitted", "Cancelled"},
    "Submitted": {"CAB Review", "Cancelled"},
    "CAB Review": {"Approved", "Cancelled"},
    "Approved": {"In Progress", "Cancelled"},
    "In Progress": {"Completed", "Cancelled"},
    "Completed": set(),
    "Rejected": set(),
    "Cancelled": set(),
}


def _lock_change(db: Session, change_id: str) -> ChangeRecord:
    """Serialize every write to one change before touching its approvals.

    PostgreSQL row locks and SQLite's write lock both apply to an UPDATE, while
    SQLite ignores SELECT FOR UPDATE. Assigning the timestamp to itself keeps
    the audit value stable and gives both supported databases the same lock
    order: change first, then approvals.
    """
    matched = db.query(ChangeRecord).filter(ChangeRecord.id == change_id).update(
        {ChangeRecord.updated_at: ChangeRecord.updated_at},
        synchronize_session=False,
    )
    if matched != 1:
        raise HTTPException(status_code=404, detail="Change not found")
    change = db.query(ChangeRecord).filter(
        ChangeRecord.id == change_id
    ).populate_existing().first()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


def _change_approval_summary(db: Session, change_id: str) -> tuple[int, int, int]:
    approved, rejected, pending = db.query(
        func.sum(case((ChangeApprovalRecord.decision == "approved", 1), else_=0)),
        func.sum(case((ChangeApprovalRecord.decision == "rejected", 1), else_=0)),
        func.sum(case((or_(
            ChangeApprovalRecord.decision.is_(None),
            ChangeApprovalRecord.decision == "pending",
        ), 1), else_=0)),
    ).filter(ChangeApprovalRecord.change_id == change_id).one()
    return int(approved or 0), int(rejected or 0), int(pending or 0)


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
    if not (change.rollback_plan or "").strip():
        raise HTTPException(status_code=400, detail="Rollback plan is required")
    if not (change.test_plan or "").strip():
        raise HTTPException(status_code=400, detail="Test plan is required")


def _ensure_change_transition_allowed(db: Session, change: ChangeRecord, target_status: Optional[str]):
    if not target_status or target_status == change.status:
        return
    _validate_change_status(target_status)
    if change.status in _CHANGE_TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Terminal changes cannot be reopened through the generic editor",
        )
    approved, rejected, pending = _change_approval_summary(db, change.id)
    if rejected and target_status in _CHANGE_APPROVAL_REQUIRED_STATUSES:
        raise HTTPException(status_code=400, detail="Rejected changes cannot move forward")
    if target_status in _CHANGE_APPROVAL_REQUIRED_STATUSES and approved == 0:
        raise HTTPException(status_code=400, detail="At least one CAB approval is required")
    if target_status in _CHANGE_APPROVAL_REQUIRED_STATUSES and pending:
        raise HTTPException(status_code=400, detail="All CAB approvals must be decided")
    if target_status in _CHANGE_APPROVAL_REQUIRED_STATUSES:
        _ensure_change_ready_for_execution(change)
    if target_status not in _CHANGE_TRANSITIONS.get(change.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Change cannot transition from {change.status} to {target_status}",
        )


def _lock_change_user_references(
    db: Session,
    *,
    requester_id: Optional[str] = None,
    assigned_to: Optional[str] = None,
) -> None:
    """Lock and validate user references before persisting a change record."""
    requested_ids = {
        user_id
        for user_id in (requester_id, assigned_to)
        if user_id
    }
    locked_users: dict[str, UserRecord] = {}
    for user_id in sorted(requested_ids):
        try:
            locked_users[user_id] = _lock_user_record(db, user_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            label = "Assigned user" if user_id == assigned_to else "Requesting user"
            raise HTTPException(status_code=404, detail=f"{label} not found") from exc

    if requester_id and not locked_users[requester_id].is_active:
        raise HTTPException(status_code=409, detail="Requesting user is no longer active")
    if assigned_to and not locked_users[assigned_to].is_active:
        raise HTTPException(status_code=409, detail="Assigned user must be active")


@app.get("/changes", response_model=List[ChangeRecordOut])
async def list_changes(
    response: Response,
    db: Session = Depends(get_db),
    status: Optional[str] = Query(default=None, max_length=32, pattern=r"^[^\x00]*$"),
    search: Optional[str] = Query(default=None, max_length=200, pattern=r"^[^\x00]*$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
):
    assigned_user = aliased(UserRecord)
    q = db.query(ChangeRecord).outerjoin(
        assigned_user,
        assigned_user.id == ChangeRecord.assigned_to,
    )
    if status:
        q = q.filter(ChangeRecord.status == status)
    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        q = q.filter(or_(
            ChangeRecord.id.ilike(pattern),
            ChangeRecord.title.ilike(pattern),
            ChangeRecord.description.ilike(pattern),
            ChangeRecord.change_type.ilike(pattern),
            assigned_user.name.ilike(pattern),
        ))
    page = q.order_by(
        desc(ChangeRecord.created_at),
        ChangeRecord.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    changes = page[:limit]

    user_ids = {
        user_id
        for change in changes
        for user_id in (change.requested_by, change.assigned_to)
        if user_id
    }
    user_names = dict(
        db.query(UserRecord.id, UserRecord.name).filter(
            UserRecord.id.in_(user_ids)
        ).all()
    ) if user_ids else {}
    for change in changes:
        change.__dict__["requested_name"] = user_names.get(change.requested_by)
        change.__dict__["assigned_name"] = user_names.get(change.assigned_to)

    awaiting_review, in_progress, high_risk = db.query(
        func.sum(case((ChangeRecord.status.in_({"Submitted", "CAB Review"}), 1), else_=0)),
        func.sum(case((ChangeRecord.status == "In Progress", 1), else_=0)),
        func.sum(case((and_(
            ChangeRecord.risk_level == "High",
            ChangeRecord.status.notin_({"Completed", "Cancelled"}),
        ), 1), else_=0)),
    ).one()
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    response.headers["X-Change-Awaiting-Review"] = str(int(awaiting_review or 0))
    response.headers["X-Change-In-Progress"] = str(int(in_progress or 0))
    response.headers["X-Change-High-Risk"] = str(int(high_risk or 0))
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
    _lock_change_user_references(
        db,
        requester_id=user.id,
        assigned_to=payload.assigned_to,
    )
    change = ChangeRecord(
        id=f"chg-{_uuid.uuid4().hex}",
        requested_by=user.id,
        **payload.model_dump(),
    )
    db.add(change)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Change references changed while saving",
        ) from exc
    db.refresh(change)
    return change


@app.patch("/changes/{change_id}", response_model=ChangeRecordOut)
async def update_change(
    change_id: str,
    payload: ChangeUpdate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    change = _lock_change(db, change_id)
    if change.status != "Completed" and change.completed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Change completion metadata is inconsistent; repair it before editing",
        )
    if change.status in _CHANGE_TERMINAL_STATUSES and (
        payload.model_fields_set - {"status"}
        or (payload.status is not None and payload.status != change.status)
    ):
        raise HTTPException(
            status_code=409,
            detail="Terminal changes are immutable; use a dedicated audited workflow",
        )
    for field in ["title", "description", "status", "change_type", "priority", "risk_level",
                   "impact", "rollback_plan", "test_plan", "scheduled_start", "scheduled_end",
                   ]:
        if field not in payload.model_fields_set or field == "status":
            continue
        value = getattr(payload, field)
        if field == "description" and value is None:
            value = ""
        setattr(change, field, value)
    if "assigned_to" in payload.model_fields_set:
        _lock_change_user_references(db, assigned_to=payload.assigned_to)
        change.assigned_to = payload.assigned_to
    _validate_change_window(change.scheduled_start, change.scheduled_end)
    _ensure_change_transition_allowed(db, change, payload.status)
    if payload.status is not None:
        change.status = payload.status
    if payload.status and payload.status == "Completed" and not change.completed_at:
        change.completed_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Change references changed while saving",
        ) from exc
    db.refresh(change)
    return change


@app.delete("/changes/{change_id}")
async def delete_change(
    change_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    change = _lock_change(db, change_id)
    if change.status != "Draft":
        raise HTTPException(
            status_code=409,
            detail="Only untouched draft changes can be deleted",
        )
    if db.query(ChangeApprovalRecord.id).filter(
        ChangeApprovalRecord.change_id == change_id
    ).first() or db.query(ChangeTicketLinkRecord.id).filter(
        ChangeTicketLinkRecord.change_id == change_id
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Changes with approval or ticket history cannot be deleted",
        )
    db.delete(change)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Change history was added while deletion was in progress",
        ) from exc
    return {"status": "deleted"}


@app.get("/changes/{change_id}/approvals", response_model=List[ChangeApprovalOut])
async def get_change_approvals(
    change_id: str,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
):
    if not db.query(ChangeRecord.id).filter(ChangeRecord.id == change_id).first():
        raise HTTPException(status_code=404, detail="Change not found")
    page = db.query(ChangeApprovalRecord).filter(
        ChangeApprovalRecord.change_id == change_id,
    ).order_by(
        ChangeApprovalRecord.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    approvals = page[:limit]

    approver_ids = {
        approval.approver_id for approval in approvals if approval.approver_id
    }
    approver_names = dict(
        db.query(UserRecord.id, UserRecord.name).filter(
            UserRecord.id.in_(approver_ids),
        ).all()
    ) if approver_ids else {}
    for approval in approvals:
        approval.__dict__["approver_name"] = approver_names.get(approval.approver_id)

    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    return approvals


@app.post("/changes/{change_id}/approvals", response_model=ChangeApprovalOut, status_code=201)
async def add_change_approval(
    change_id: str,
    payload: ChangeApprovalCreate,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor")),
):
    change = _lock_change(db, change_id)
    if change.status not in _CHANGE_APPROVAL_OPEN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Approvals can only be added before change execution",
        )
    _lock_active_user_reference(db, payload.approver_id, label="Approver")
    if change.requested_by and change.requested_by == payload.approver_id:
        raise HTTPException(status_code=400, detail="Requester cannot approve their own change")
    existing = db.query(ChangeApprovalRecord).filter(
        ChangeApprovalRecord.change_id == change_id, ChangeApprovalRecord.approver_id == payload.approver_id
    ).first()
    if existing:
        return existing
    approval = ChangeApprovalRecord(change_id=change_id, approver_id=payload.approver_id)
    db.add(approval)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = db.query(ChangeApprovalRecord).filter(
            ChangeApprovalRecord.change_id == change_id,
            ChangeApprovalRecord.approver_id == payload.approver_id,
        ).first()
        if raced:
            return raced
        raise HTTPException(status_code=409, detail="Approval could not be added")
    db.refresh(approval)
    return approval


@app.patch("/changes/{change_id}/approvals/{approver_id}")
async def decide_approval(
    change_id: str,
    approver_id: str,
    payload: Optional[ChangeApprovalDecision] = None,
    decision: Optional[str] = Query(default=None, max_length=16),
    comment: Optional[str] = Query(
        default=None,
        max_length=5_000,
        pattern=r"^[^\x00]*$",
    ),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_authenticated_user),
):
    change = _lock_change(db, change_id)
    _lock_active_user_reference(db, user.id, label="Decision actor")
    if change.status not in _CHANGE_APPROVAL_OPEN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="This change is no longer open for approval decisions",
        )
    approval = db.query(ChangeApprovalRecord).filter(
        ChangeApprovalRecord.change_id == change_id,
        ChangeApprovalRecord.approver_id == approver_id,
    ).first()
    if not approval and approver_id.isdigit():
        approval = db.query(ChangeApprovalRecord).filter(
            ChangeApprovalRecord.change_id == change_id,
            ChangeApprovalRecord.id == int(approver_id),
        ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if user.role != "admin" and approval.approver_id != user.id:
        raise HTTPException(status_code=403, detail="Only the assigned approver or an admin can decide")
    if change.requested_by == user.id:
        raise HTTPException(status_code=400, detail="Requester cannot approve their own change")
    if approval.decision in {"approved", "rejected"} or approval.decided_at is not None:
        raise HTTPException(status_code=409, detail="Approval already decided")
    selected_decision = payload.decision if payload else decision
    selected_comment = payload.comment if payload else (comment or "").strip()
    if selected_decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Decision must be approved or rejected")
    decided_at = datetime.utcnow()
    updated = db.query(ChangeApprovalRecord).filter(
        ChangeApprovalRecord.id == approval.id,
        or_(
            ChangeApprovalRecord.decision.is_(None),
            ChangeApprovalRecord.decision == "pending",
        ),
        ChangeApprovalRecord.decided_at.is_(None),
    ).update(
        {
            ChangeApprovalRecord.decision: selected_decision,
            ChangeApprovalRecord.comment: selected_comment,
            ChangeApprovalRecord.decided_at: decided_at,
        },
        synchronize_session=False,
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Approval already decided")
    db.expire(approval)
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
    response: Response,
    asset_type: Optional[str] = Query(
        default=None,
        max_length=100,
        pattern=r"^[^\x00]*$",
    ),
    status: Optional[str] = Query(
        default=None,
        max_length=100,
        pattern=r"^[^\x00]*$",
    ),
    search: Optional[str] = Query(
        default=None,
        max_length=200,
        pattern=r"^[^\x00]*$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
):
    q = db.query(AssetRecord)
    normalized_type = (asset_type or "").strip()
    normalized_status = (status or "").strip()
    if normalized_type:
        q = q.filter(AssetRecord.asset_type == normalized_type)
    if normalized_status:
        q = q.filter(AssetRecord.status == normalized_status)
    normalized_search = (search or "").strip()
    if normalized_search:
        escaped_search = (
            normalized_search
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        q = q.filter(or_(
            AssetRecord.name.ilike(pattern, escape="\\"),
            AssetRecord.asset_tag.ilike(pattern, escape="\\"),
            AssetRecord.vendor.ilike(pattern, escape="\\"),
            AssetRecord.model.ilike(pattern, escape="\\"),
            AssetRecord.location.ilike(pattern, escape="\\"),
        ))

    page = q.order_by(
        AssetRecord.asset_type,
        AssetRecord.name,
        AssetRecord.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(page) > limit
    assets = page[:limit]

    owner_ids = {asset.owner_id for asset in assets if asset.owner_id}
    owner_names = dict(
        db.query(UserRecord.id, UserRecord.name).filter(
            UserRecord.id.in_(owner_ids)
        ).all()
    ) if owner_ids else {}
    for asset in assets:
        asset.__dict__["owner_name"] = owner_names.get(asset.owner_id)

    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    return assets


@app.get("/assets/stats")
async def asset_stats(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
):
    total = db.query(AssetRecord).count()
    by_type = {}
    for row in db.query(AssetRecord.asset_type, func.count()).group_by(AssetRecord.asset_type).all():
        by_type[row[0]] = row[1]
    return {"total": total, "by_type": by_type}


@app.get("/assets/{asset_id}", response_model=Asset)
async def get_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_role("admin", "supervisor", "agent")),
):
    asset = db.query(AssetRecord).filter(AssetRecord.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.owner_id:
        u = db.query(UserRecord).filter(UserRecord.id == asset.owner_id).first()
        asset.__dict__["owner_name"] = u.name if u else None
    return asset


def _validate_asset_date_range(
    purchase_date: Optional[datetime],
    warranty_expiry: Optional[datetime],
) -> None:
    if (
        purchase_date is not None
        and warranty_expiry is not None
        and warranty_expiry < purchase_date
    ):
        raise HTTPException(
            status_code=422,
            detail="Warranty expiry cannot precede purchase date",
        )


def _lock_asset_record(db: Session, asset_id: str) -> AssetRecord:
    matched = db.query(AssetRecord).filter(
        AssetRecord.id == asset_id
    ).update(
        {AssetRecord.updated_at: AssetRecord.updated_at},
        synchronize_session=False,
    )
    if matched != 1:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset = db.query(AssetRecord).filter(
        AssetRecord.id == asset_id
    ).populate_existing().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@app.post("/assets", response_model=Asset, status_code=201)
async def create_asset(payload: AssetCreate, db: Session = Depends(get_db)):
    import uuid as _uuid
    _validate_asset_date_range(payload.purchase_date, payload.warranty_expiry)
    _lock_active_user_reference(db, payload.owner_id, label="Asset owner")
    asset = AssetRecord(id=f"ast-{_uuid.uuid4().hex}", **payload.model_dump())
    db.add(asset)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Asset tag already exists or its owner changed while saving",
        ) from exc
    db.refresh(asset)
    return asset


@app.patch("/assets/{asset_id}", response_model=Asset)
async def update_asset(asset_id: str, payload: AssetUpdate, db: Session = Depends(get_db)):
    asset = db.query(AssetRecord).filter(AssetRecord.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if "owner_id" in payload.model_fields_set:
        _lock_active_user_reference(db, payload.owner_id, label="Asset owner")
    asset = _lock_asset_record(db, asset_id)
    purchase_date = (
        payload.purchase_date
        if "purchase_date" in payload.model_fields_set
        else asset.purchase_date
    )
    warranty_expiry = (
        payload.warranty_expiry
        if "warranty_expiry" in payload.model_fields_set
        else asset.warranty_expiry
    )
    _validate_asset_date_range(purchase_date, warranty_expiry)
    for field in payload.model_fields_set:
        setattr(asset, field, getattr(payload, field))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Asset tag already exists or its owner changed while saving",
        ) from exc
    db.refresh(asset)
    return asset


@app.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.query(AssetRecord).filter(AssetRecord.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    # CMDB history is referenced by ticket.asset_id without a database-level
    # foreign key. Retire records instead of creating dangling identifiers and
    # erasing the configuration history behind existing tickets.
    asset.status = "Retired"
    db.commit()
    return {"status": "retired"}


# ── Surveys / CSAT ─────────────────────────────────────────────

@app.get("/surveys/templates", response_model=List[SurveyTemplate])
async def list_survey_templates(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    return db.query(SurveyTemplateRecord).order_by(
        SurveyTemplateRecord.name,
        SurveyTemplateRecord.id,
    ).limit(500).all()


@app.get("/surveys", response_model=List[SurveyOut])
async def list_surveys(
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    rows = db.query(SurveyRecord, TicketRecord.subject).outerjoin(
        TicketRecord,
        TicketRecord.id == SurveyRecord.ticket_id,
    ).order_by(
        desc(SurveyRecord.created_at),
        SurveyRecord.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    surveys = []
    for survey, ticket_subject in rows[:limit]:
        survey.__dict__["ticket_subject"] = ticket_subject
        surveys.append(survey)
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    return surveys


@app.get("/surveys/eligible-tickets", response_model=List[Ticket])
async def list_survey_eligible_tickets(
    request: Request,
    response: Response,
    search: Optional[str] = Query(
        default=None,
        max_length=200,
        pattern=r"^[^\x00]*$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(
        require_authenticated_role("admin", "supervisor")
    ),
):
    """Return every terminal ticket through a searchable, bounded page.

    Survey selection must not infer eligibility from a recent general-ticket
    page: a valid older resolution could otherwise become impossible to find.
    """
    query = db.query(TicketRecord).filter(terminal_ticket_filter(db))
    normalized_search = (search or "").strip()
    if normalized_search:
        escaped = (
            normalized_search.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        query = query.filter(or_(
            TicketRecord.id.ilike(pattern, escape="\\"),
            TicketRecord.external_id.ilike(pattern, escape="\\"),
            TicketRecord.subject.ilike(pattern, escape="\\"),
            TicketRecord.external_requester_name.ilike(pattern, escape="\\"),
            TicketRecord.external_requester_email.ilike(pattern, escape="\\"),
            TicketRecord.reporter.ilike(pattern, escape="\\"),
        ))
    rows = query.order_by(
        func.coalesce(
            TicketRecord.external_updated_at,
            TicketRecord.updated_at,
            TicketRecord.created_at,
        ).desc(),
        TicketRecord.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    return [_ticket_for_request(request, ticket) for ticket in rows[:limit]]


@app.post("/surveys/send", response_model=SurveyOut, status_code=202)
async def send_survey(
    payload: SurveySend,
    request: Request,
    user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    if not sendgrid_status()["configured"]:
        raise HTTPException(status_code=503, detail="SendGrid is not configured")

    template = db.query(SurveyTemplateRecord).filter(
        SurveyTemplateRecord.id == payload.template_id,
        SurveyTemplateRecord.is_active.is_(True),
    ).first()
    if not template:
        raise HTTPException(status_code=422, detail="An active survey template is required")
    question = (template.question or "").strip()
    if not question or len(question) > 5_000 or "\x00" in question:
        raise HTTPException(status_code=422, detail="Survey template question is invalid")

    ticket = db.query(TicketRecord).filter(TicketRecord.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not _is_terminal_status(db, ticket.status):
        raise HTTPException(
            status_code=409,
            detail="Surveys can only be sent for resolved or closed tickets",
        )

    raw_recipient_email = ticket.external_requester_email or ticket.reporter
    try:
        recipient_email = normalize_email_address(raw_recipient_email or "")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Ticket requester does not have a deliverable email address",
        ) from None
    try:
        recipient_name = normalize_sender_name(
            ticket.external_requester_name or "Requester"
        ) or "Requester"
    except ValueError:
        recipient_name = "Requester"

    attempted_at = datetime.utcnow()
    delivery_key = _survey_delivery_key(
        payload.ticket_id,
        payload.template_id,
        recipient_email,
    )
    # An expired capability no longer blocks a deliberate new delivery. The
    # unique key remains database-enforced across concurrent requests.
    db.query(SurveyRecord).filter(
        SurveyRecord.active_delivery_key == delivery_key,
        SurveyRecord.response_expires_at <= attempted_at,
    ).update(
        {SurveyRecord.active_delivery_key: None},
        synchronize_session=False,
    )
    db.commit()
    active_delivery = db.query(SurveyRecord.id).filter(
        SurveyRecord.active_delivery_key == delivery_key,
    ).first()
    if active_delivery:
        raise HTTPException(
            status_code=409,
            detail="An active survey delivery already exists for this ticket and template",
        )

    response_token = secrets.token_urlsafe(SURVEY_RESPONSE_TOKEN_BYTES)
    response_url = _survey_response_url(request, response_token)
    expires_at = attempted_at + _survey_response_ttl()
    _reserve_email_request(db, user.id, 1)

    survey = SurveyRecord(
        id=f"srv-{secrets.token_hex(16)}",
        ticket_id=payload.ticket_id,
        template_id=payload.template_id,
        response_token_hash=_survey_token_digest(response_token),
        active_delivery_key=delivery_key,
        response_expires_at=expires_at,
        question_snapshot=question,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        delivery_status="pending",
        delivery_attempted_at=attempted_at,
        sent_by=user.id,
        created_at=attempted_at,
    )
    db.add(survey)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.query(SurveyRecord.id).filter(
            SurveyRecord.active_delivery_key == delivery_key,
        ).first():
            raise HTTPException(
                status_code=409,
                detail="An active survey delivery already exists for this ticket and template",
            ) from None
        raise HTTPException(
            status_code=503,
            detail="Survey delivery could not be initialized",
        ) from None

    delivery_body = (
        f"Hello {recipient_name},\n\n"
        f"{question}\n\n"
        f"Share your feedback: {response_url}\n\n"
        f"This one-time link expires on {expires_at.strftime('%Y-%m-%d')} UTC."
    )
    try:
        message_id = await send_sendgrid_email(
            [EmailAddress(email=recipient_email, name=recipient_name)],
            subject=f"How was your {PRODUCT_NAME} support experience?",
            body=delivery_body,
        )
    except EmailConfigurationError:
        survey.delivery_status = "failed"
        survey.active_delivery_key = None
        survey.delivery_error = "configuration_error"
        db.commit()
        raise HTTPException(status_code=503, detail="SendGrid is not configured") from None
    except EmailDeliveryError as exc:
        # A provider HTTP rejection is definitive and safe to retry. A network
        # failure is ambiguous: the provider may have accepted the request
        # before the connection failed, so keep the capability usable and
        # block automatic duplicate delivery until it is reconciled.
        survey.delivery_status = (
            "failed" if exc.provider_status is not None else "uncertain"
        )
        if exc.provider_status is not None:
            survey.active_delivery_key = None
        survey.delivery_error = (
            f"provider_{exc.provider_status}"
            if exc.provider_status is not None
            else "delivery_outcome_unknown"
        )
        db.commit()
        raise HTTPException(
            status_code=502,
            detail=(
                "Email provider did not accept the survey message"
                if exc.provider_status is not None
                else "Survey delivery outcome is unknown; do not resend automatically"
            ),
        ) from None

    survey.delivery_status = "accepted"
    survey.delivery_message_id = message_id[:255] if message_id else None
    survey.sent_at = datetime.utcnow()
    try:
        db.commit()
    except SQLAlchemyError:
        # The already-committed pending row keeps the emailed capability valid
        # if persistence fails after SendGrid returns 202. The active-delivery
        # guard prevents a blind retry from sending a duplicate message.
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Provider accepted delivery; status reconciliation is pending",
        ) from None
    db.refresh(survey)
    survey.__dict__["ticket_subject"] = ticket.subject
    return survey


@app.post("/portal/survey/lookup", response_model=SurveyPortalQuestion)
async def lookup_public_survey(
    payload: SurveyPortalLookupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    _require_public_survey_origin(request)
    _reserve_survey_public_request(db, "lookup")
    survey = _survey_for_token(db, payload.token)
    if not survey or not survey.question_snapshot:
        raise HTTPException(
            status_code=404,
            detail="Survey link is invalid or expired",
            headers={"Cache-Control": "no-store"},
        )
    _reserve_survey_public_request(db, "lookup", token=payload.token)
    if survey.responded_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Survey has already been submitted",
            headers={"Cache-Control": "no-store"},
        )
    return {
        "question": survey.question_snapshot,
        "expires_at": survey.response_expires_at,
    }


@app.post(
    "/portal/survey/respond",
    response_model=SurveyPortalSubmitted,
    status_code=201,
)
async def respond_public_survey(
    payload: SurveyPortalResponseRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    _require_public_survey_origin(request)
    _reserve_survey_public_request(db, "respond")
    survey = _survey_for_token(db, payload.token)
    if not survey:
        raise HTTPException(
            status_code=404,
            detail="Survey link is invalid or expired",
            headers={"Cache-Control": "no-store"},
        )
    _reserve_survey_public_request(db, "respond", token=payload.token)
    if survey.responded_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Survey has already been submitted",
            headers={"Cache-Control": "no-store"},
        )

    submitted_at = datetime.utcnow()
    digest = _survey_token_digest(payload.token)
    updated = db.query(SurveyRecord).filter(
        SurveyRecord.id == survey.id,
        SurveyRecord.response_token_hash == digest,
        SurveyRecord.delivery_status.in_(("pending", "uncertain", "accepted")),
        SurveyRecord.delivery_attempted_at.isnot(None),
        or_(
            SurveyRecord.delivery_status != "accepted",
            SurveyRecord.sent_at.isnot(None),
        ),
        SurveyRecord.response_expires_at > submitted_at,
        SurveyRecord.responded_at.is_(None),
    ).update(
        {
            SurveyRecord.responded_at: submitted_at,
            # A valid one-time response is stronger delivery evidence than a
            # missing provider acknowledgement. Promote crash-window pending
            # or network-uncertain deliveries so CSAT is not silently omitted.
            SurveyRecord.delivery_status: "accepted",
            SurveyRecord.sent_at: func.coalesce(
                SurveyRecord.sent_at,
                SurveyRecord.delivery_attempted_at,
                submitted_at,
            ),
            SurveyRecord.delivery_error: None,
        },
        synchronize_session=False,
    )
    if updated != 1:
        db.rollback()
        current = db.query(SurveyRecord).filter(
            SurveyRecord.id == survey.id,
            SurveyRecord.response_token_hash == digest,
        ).first()
        if current is None or current.responded_at is None:
            raise HTTPException(
                status_code=404,
                detail="Survey link is invalid or expired",
                headers={"Cache-Control": "no-store"},
            )
        raise HTTPException(
            status_code=409,
            detail="Survey has already been submitted",
            headers={"Cache-Control": "no-store"},
        )
    db.add(SurveyResponseRecord(
        survey_id=survey.id,
        rating=payload.rating,
        comment=payload.comment or None,
        submitted_at=submitted_at,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Survey has already been submitted",
            headers={"Cache-Control": "no-store"},
        ) from None
    return {"status": "submitted"}


@app.post("/surveys/{survey_id}/respond", status_code=410)
async def respond_survey_legacy_route(
    survey_id: str,
    _payload: SurveyResponseCreate,
    _user: UserRecord = Depends(
        require_authenticated_role("admin", "supervisor")
    ),
):
    # Never accept a guessable database ID as a public response capability.
    raise HTTPException(
        status_code=410,
        detail="Legacy survey response route is disabled",
    )


@app.get("/surveys/stats")
async def survey_stats(
    db: Session = Depends(get_db),
    _user: UserRecord = Depends(require_authenticated_role("admin", "supervisor")),
):
    accepted_filter = SurveyRecord.delivery_status == "accepted"
    total = db.query(SurveyRecord).filter(accepted_filter).count()
    responded = db.query(SurveyRecord).filter(
        accepted_filter,
        SurveyRecord.responded_at.isnot(None),
    ).count()
    accepted_responses = db.query(SurveyResponseRecord).join(
        SurveyRecord,
        SurveyRecord.id == SurveyResponseRecord.survey_id,
    ).filter(accepted_filter)
    responses = accepted_responses.with_entities(
        SurveyResponseRecord.rating,
        func.count(),
    ).group_by(SurveyResponseRecord.rating).all()
    avg_rating = accepted_responses.with_entities(
        func.avg(SurveyResponseRecord.rating)
    ).scalar() or 0
    return {
        "total_sent": total, "responded": responded, "response_rate": round(responded / total * 100, 1) if total else 0,
        "avg_rating": round(avg_rating, 1),
        "distribution": {str(r): c for r, c in responses},
    }


# ── Time Tracking ──────────────────────────────────────────────

def _time_entry_scope_filters(
    db: Session,
    user: UserRecord,
    *,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
) -> list[Any]:
    """Return fail-closed worklog predicates for the caller's reporting scope.

    Agents may only read their own entries, including through a ticket-specific
    URL. Supervisors and admins retain the existing all-users default and may
    explicitly narrow a report to one user or one provider team.
    """
    role = (user.role or "").lower()
    if role == "agent":
        if user_id is not None or team_id is not None:
            raise HTTPException(
                status_code=403,
                detail="Only admins and supervisors can select another time reporting scope",
            )
        return [TimeEntryRecord.user_id == user.id]
    if role not in {"admin", "supervisor"}:
        raise HTTPException(status_code=403, detail="Insufficient time entry permissions")

    filters: list[Any] = []
    if user_id is not None:
        target_user = db.query(UserRecord.id).filter(UserRecord.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        filters.append(TimeEntryRecord.user_id == user_id)
    if team_id is not None:
        group = db.query(ExternalGroupRecord).filter(ExternalGroupRecord.id == team_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Team not found")
        team_ticket_ids = db.query(TicketRecord.id).filter(
            TicketRecord.binding_id == group.binding_id,
            func.lower(TicketRecord.external_source) == group.provider.lower(),
            TicketRecord.external_group_id == group.external_id,
        )
        filters.append(TimeEntryRecord.ticket_id.in_(team_ticket_ids))
    return filters


def _normalize_optional_query_id(
    value: Optional[str],
    *,
    label: str,
) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{label} must not be blank")
    return normalized


def _enrich_time_entries(db: Session, entries: list[TimeEntryRecord]) -> None:
    user_ids = {entry.user_id for entry in entries if entry.user_id}
    user_names = dict(
        db.query(UserRecord.id, UserRecord.name)
        .filter(UserRecord.id.in_(user_ids))
        .all()
    ) if user_ids else {}
    for entry in entries:
        entry.__dict__["user_name"] = user_names.get(entry.user_id)


@app.get("/time-entries", response_model=List[TimeEntry])
async def list_time_entries(
    response: Response,
    db: Session = Depends(get_db),
    ticket_id: Optional[str] = Query(default=None, min_length=1, max_length=255, pattern=r"^[^\x00]*$"),
    user_id: Optional[str] = Query(default=None, min_length=1, max_length=255, pattern=r"^[^\x00]*$"),
    team_id: Optional[str] = Query(default=None, min_length=1, max_length=36, pattern=r"^[^\x00]*$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: UserRecord = Depends(get_current_user),
):
    ticket_id = _normalize_optional_query_id(ticket_id, label="Ticket ID")
    user_id = _normalize_optional_query_id(user_id, label="User ID")
    team_id = _normalize_optional_query_id(team_id, label="Team ID")
    q = db.query(TimeEntryRecord).filter(
        *_time_entry_scope_filters(db, user, user_id=user_id, team_id=team_id)
    )
    if ticket_id:
        q = q.filter(TimeEntryRecord.ticket_id == ticket_id)
    page = (
        q.order_by(desc(TimeEntryRecord.entry_date), desc(TimeEntryRecord.id))
        .offset(offset)
        .limit(limit + 1)
        .all()
    )
    has_more = len(page) > limit
    entries = page[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    _enrich_time_entries(db, entries)
    return entries


@app.post("/time-entries", response_model=TimeEntry, status_code=201)
async def create_time_entry(
    payload: TimeEntryCreate,
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    # Time entries are retained evidence. Serialize with reassignment and
    # refresh before authorizing so an agent cannot write against a ticket
    # that moved queues while this request was waiting.
    ticket = _lock_ticket_record(db, payload.ticket_id)
    _authorize_ticket_mutation(user, ticket, db=db)
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
async def ticket_time_entries(
    response: Response,
    ticket_id: str = Path(..., min_length=1, max_length=255, pattern=r"^[^\x00]*$"),
    db: Session = Depends(get_db),
    user_id: Optional[str] = Query(default=None, min_length=1, max_length=255, pattern=r"^[^\x00]*$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: UserRecord = Depends(get_current_user),
):
    ticket_id = _normalize_optional_query_id(ticket_id, label="Ticket ID") or ""
    user_id = _normalize_optional_query_id(user_id, label="User ID")
    page = (
        db.query(TimeEntryRecord)
        .filter(
            TimeEntryRecord.ticket_id == ticket_id,
            *_time_entry_scope_filters(db, user, user_id=user_id),
        )
        .order_by(desc(TimeEntryRecord.entry_date), desc(TimeEntryRecord.id))
        .offset(offset)
        .limit(limit + 1)
        .all()
    )
    has_more = len(page) > limit
    entries = page[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Page-Offset"] = str(offset)
    response.headers["X-Has-More"] = str(has_more).lower()
    _enrich_time_entries(db, entries)
    return entries


def _utc_bounds_for_local_day(
    time_zone_name: str,
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    try:
        local_zone = ZoneInfo(time_zone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Unknown time zone") from exc

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_day = current.astimezone(local_zone).date()
    local_start = datetime.combine(local_day, datetime.min.time(), tzinfo=local_zone)
    local_end = datetime.combine(
        local_day + timedelta(days=1),
        datetime.min.time(),
        tzinfo=local_zone,
    )
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


@app.get("/time-entries/summary")
async def time_summary(
    time_zone: str = Query("UTC", min_length=1, max_length=64, pattern=r"^[^\x00]*$"),
    ticket_id: Optional[str] = Query(default=None, min_length=1, max_length=255, pattern=r"^[^\x00]*$"),
    user_id: Optional[str] = Query(default=None, min_length=1, max_length=255, pattern=r"^[^\x00]*$"),
    team_id: Optional[str] = Query(default=None, min_length=1, max_length=36, pattern=r"^[^\x00]*$"),
    db: Session = Depends(get_db),
    user: UserRecord = Depends(get_current_user),
):
    time_zone = time_zone.strip()
    if not time_zone:
        raise HTTPException(status_code=422, detail="Time zone must not be blank")
    ticket_id = _normalize_optional_query_id(ticket_id, label="Ticket ID")
    user_id = _normalize_optional_query_id(user_id, label="User ID")
    team_id = _normalize_optional_query_id(team_id, label="Team ID")
    try:
        today_start, tomorrow_start = _utc_bounds_for_local_day(time_zone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown time zone") from exc
    scope_filters = _time_entry_scope_filters(
        db, user, user_id=user_id, team_id=team_id
    )
    if ticket_id:
        scope_filters.append(TimeEntryRecord.ticket_id == ticket_id)
    total_minutes = db.query(func.sum(TimeEntryRecord.minutes)).filter(
        *scope_filters
    ).scalar() or 0
    ticket_count = db.query(
        func.count(func.distinct(TimeEntryRecord.ticket_id))
    ).filter(*scope_filters).scalar() or 0
    today_minutes = db.query(func.sum(TimeEntryRecord.minutes)).filter(
        *scope_filters,
        TimeEntryRecord.entry_date >= today_start,
        TimeEntryRecord.entry_date < tomorrow_start,
    ).scalar() or 0
    total_hours = round(total_minutes / 60, 1)
    return {
        "total_hours": total_hours,
        "today_hours": round(today_minutes / 60, 1),
        "ticket_count": ticket_count,
        "average_hours_per_ticket": round(total_minutes / 60 / ticket_count, 1)
        if ticket_count else 0,
    }


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
                _authorize_ticket_analysis(ws_user, ticket, db)
            except HTTPException:
                await ws.send_json({"type": "error", "message": "Insufficient ticket analysis permission"})
                await ws.close(code=1008)
                return
        _reserve_ai_request(db, ws_user.id if ws_user else "demo-websocket", "full_analysis")

        steps = [
            {"step": "reading", "label": "Reading ticket details...", "status": "done"},
            {"step": "triage", "label": "Triaging sentiment, category, priority...", "status": "pending"},
            {"step": "summary", "label": "Generating case summary...", "status": "pending"},
            {"step": "route", "label": "Recommending resolver group...", "status": "pending"},
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

        ticket, ws_user = _lock_authorized_ticket_analysis(db, ticket_id, ws_user)
        result = await _run_ticket_analysis(
            ticket,
            db,
            progress=report_progress,
            analysis_actor_id=ws_user.id,
        )

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
