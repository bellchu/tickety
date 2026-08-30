import os
import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import case, func, or_, text

from .database import (
    AIArtifactRecord,
    ExternalAttachmentRecord,
    SessionLocal,
    SyncStateRecord,
    TicketRecord,
)
from .ai_eligibility import (
    active_ticket_filter,
    mark_terminal_ai_not_applicable,
    terminal_status_names,
)
from .ai_state import automatic_ai_policy_eligible_filter
from .attachment_storage import attachment_storage_configured
from .integrations.sync import (
    AUTOMATIC_FETCH_DAYS,
    AUTOMATIC_AI_LOOKBACK_DAYS,
    BACKGROUND_HISTORY_SCAN_VERSION,
    PROVIDER_TIMESTAMP_REPAIR_VERSION,
    PROVIDER_TIMESTAMP_REPAIR_DAYS,
    active_routing_backlog_enabled,
    freshservice_sync_limits,
    queue_active_routing_backlog,
    queue_recent_automatic_ai,
    sync_tickets_from_external,
)
from .integrations.registry import configured_provider, get_adapter
from .integrations.bindings import expire_due_bindings, get_active_binding
from .llm_manager import (
    LLMCapacityError,
    defer_provider_capacity,
    provider_capacity_retry_after,
)
from . import settings as settings_module
from . import directory_service

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()

_PROCESS_ROLE_ENV = "TICKETY_PROCESS_ROLE"
_SCHEDULER_ENABLED_ENV = "TICKETY_SCHEDULER_ENABLED"
_VALID_PROCESS_ROLES = {"api", "worker", "all"}


def _refresh_admin_settings() -> None:
    """Pick up portal-approved settings without restarting the worker."""
    try:
        settings_module.refresh_settings_from_db()
    except Exception as exc:
        print(f"[settings] worker refresh error kind={type(exc).__name__}")


def process_role() -> str:
    """Return this process's explicit runtime role.

    Production defaults to an API-only process so adding API replicas can
    never multiply scheduled jobs. Demo mode retains the historical combined
    API + scheduler process unless a role is explicitly configured.
    """
    configured = os.getenv(_PROCESS_ROLE_ENV, "").strip().lower()
    if configured:
        if configured not in _VALID_PROCESS_ROLES:
            raise ValueError(
                f"{_PROCESS_ROLE_ENV} must be one of: "
                f"{', '.join(sorted(_VALID_PROCESS_ROLES))}"
            )
        return configured
    return "all" if settings_module.is_demo_mode() else "api"


def scheduler_enabled_for_process() -> bool:
    """Whether this process may own scheduled jobs.

    The optional enable flag is a kill switch, not a way to turn an API role
    into a worker. This keeps a mistaken boolean on replicated API processes from
    reintroducing duplicate schedulers.
    """
    role = process_role()
    configured = os.getenv(_SCHEDULER_ENABLED_ENV)
    if configured is not None:
        normalized = configured.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized not in {"1", "true", "yes", "on"}:
            raise ValueError(
                f"{_SCHEDULER_ENABLED_ENV} must be a boolean value"
            )
    return role in {"worker", "all"}


def _bounded_interval(env_name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        configured = default
    return max(minimum, min(configured, maximum))


async def _process_ai_candidates(
    candidates: list[tuple[str, Optional[str]]],
) -> Optional[LLMCapacityError]:
    """Process ticket pipelines concurrently with one session per ticket."""
    if not candidates:
        return None
    from .main import _artifact_is_current, _auto_process

    probe = SessionLocal()
    try:
        # SQLite test/dev databases commonly use a single shared connection;
        # production Postgres gets real concurrent ticket pipelines.
        concurrency = 1 if probe.bind.dialect.name == "sqlite" else _bounded_interval(
            "AI_BACKGROUND_CONCURRENCY", 4, 1, 16
        )
    finally:
        probe.close()
    semaphore = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    async def process_one(
        ticket_id: str,
        requested_artifact: Optional[str],
    ) -> Optional[LLMCapacityError]:
        async with semaphore:
            if stop.is_set():
                return None
            db = SessionLocal()
            try:
                ticket = db.query(TicketRecord).filter(
                    TicketRecord.id == ticket_id,
                    active_ticket_filter(db),
                ).with_for_update().first()
                now = datetime.utcnow()
                live_claim = bool(
                    ticket
                    and ticket.ai_status == "running"
                    and ticket.ai_lease_expires_at
                    and ticket.ai_lease_expires_at >= now
                )
                retry_due = bool(
                    ticket
                    and (
                        ticket.ai_next_attempt_at is None
                        or ticket.ai_next_attempt_at <= now
                    )
                )
                if (
                    not ticket
                    or live_claim
                    or not retry_due
                    or ticket.ai_status in {"dead_letter", "failed"}
                ):
                    db.rollback()
                    return None
                if requested_artifact:
                    if requested_artifact == "summary":
                        missing = ticket.summary is None
                    elif requested_artifact == "route":
                        missing = not _artifact_is_current(db, ticket, "route")
                    else:
                        missing = ticket.recommended_solution is None
                    if not missing or ticket.ai_status == "queued":
                        db.rollback()
                        return None
                    ticket.ai_requested_artifacts = requested_artifact
                    ticket.ai_status = "queued"
                force = ticket.ai_status in {"queued", "running"}
                db.commit()
                db.refresh(ticket)
                await _auto_process(ticket, db, force=force)
                return None
            except LLMCapacityError as exc:
                db.rollback()
                stop.set()
                return exc
            except Exception as exc:
                db.rollback()
                print(f"[auto-triage] error kind={type(exc).__name__}")
                return None
            finally:
                db.close()

    results = await asyncio.gather(*(
        process_one(ticket_id, artifact)
        for ticket_id, artifact in candidates
    ))
    return next((result for result in results if result is not None), None)


def _backfill_escalation_risk(db) -> int:
    """Backfill one bounded page without treating a valid zero as missing."""
    if db.get_bind().dialect.name == "postgresql":
        # Risk enrichment is optional background maintenance. Never let a
        # blocked row or statement consume a scheduler thread indefinitely.
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '30s'"))
    risk_batch_size = _bounded_interval(
        "AI_RISK_BACKFILL_PER_SWEEP", 25, 1, 100
    )
    no_risk = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        TicketRecord.ai_reasoning.isnot(None),
        TicketRecord.escalation_risk_backfilled_at.is_(None),
    ).order_by(
        TicketRecord.updated_at.asc(),
        TicketRecord.id.asc(),
    ).limit(risk_batch_size).all()
    if not no_risk:
        return 0

    from . import intelligence as intel

    terminals = terminal_status_names(db)
    completed_at = datetime.utcnow()
    updated = 0
    for ticket in no_risk:
        try:
            ticket.escalation_risk = intel.escalation_risk(
                ticket,
                terminal_statuses=terminals,
            )
            ticket.escalation_risk_backfilled_at = completed_at
            updated += 1
        except Exception as exc:
            print(f"[auto-triage] risk error kind={type(exc).__name__}")
    if not updated:
        return 0
    try:
        db.commit()
    except Exception as exc:
        print(
            "[auto-triage] risk batch commit error "
            f"kind={type(exc).__name__}"
        )
        db.rollback()
        return 0
    return updated


def _risk_backfill_job() -> None:
    """Run optional risk enrichment outside the newest-ticket AI lane."""
    db = SessionLocal()
    try:
        _backfill_escalation_risk(db)
    except Exception as exc:
        db.rollback()
        print(f"[risk-backfill] error kind={type(exc).__name__}")
    finally:
        db.close()


def _queue_integration_ai_backlog(db, batch_size: int):
    """Queue only the bounded four-week automatic lane, newest first.

    Older provider tickets require an explicit administrator batch. Keeping
    that boundary here prevents an optional historical backlog from consuming
    every worker slot ahead of newly created tickets.
    """
    from .main import (
        AI_ROUTING_PIPELINE_VERSION,
        _llm_cache_identity,
        engine as main_engine,
    )

    artifact_identity = {
        "expected_pipeline_version": AI_ROUTING_PIPELINE_VERSION,
        "expected_model": _llm_cache_identity(),
        "allow_synthetic_artifacts": bool(
            getattr(main_engine.llm, "allow_synthetic", False)
        ),
    }
    recent = queue_recent_automatic_ai(
        db,
        batch_size=batch_size,
        **artifact_identity,
    )
    routing_backlog = {
        "enabled": active_routing_backlog_enabled(),
        "queued": 0,
    }
    return artifact_identity, routing_backlog, recent


@dataclass(frozen=True)
class _AISweep:
    candidates: list[tuple[str, Optional[str]]]
    queued: int
    untriaged: int
    no_summary: int
    no_resolution: int
    no_route: int
    terminal_cleaned: int


def _load_ai_sweep(
    db,
    *,
    batch_size: int,
    auto_triage: bool,
    auto_summary: bool,
    auto_route: bool,
    auto_resolution: bool,
    artifact_identity: Optional[dict],
) -> _AISweep:
    """Select one bounded, priority-ordered ticket sweep."""
    internal_automatic_source = or_(
        TicketRecord.external_source.is_(None),
        TicketRecord.external_source.in_(["manual", "standalone"]),
    )
    priority_order = case(
        (func.upper(TicketRecord.priority) == "P1", 0),
        (func.upper(TicketRecord.priority) == "P2", 1),
        (func.upper(TicketRecord.priority) == "P3", 2),
        (func.upper(TicketRecord.priority) == "P4", 3),
        else_=4,
    )

    created_order = func.coalesce(
        TicketRecord.external_created_at,
        TicketRecord.created_at,
    )

    terminal_pending = db.query(TicketRecord).filter(
        TicketRecord.ai_status.in_(("queued", "running")),
        ~active_ticket_filter(db),
    ).order_by(
        TicketRecord.updated_at.asc(),
        TicketRecord.id.asc(),
    ).limit(batch_size).all()
    for ticket in terminal_pending:
        mark_terminal_ai_not_applicable(ticket)
    if terminal_pending:
        db.commit()

    sweep_now = datetime.utcnow()
    queued = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        or_(
            TicketRecord.ai_status == "queued",
            (
                (TicketRecord.ai_status == "running")
                & or_(
                    TicketRecord.ai_lease_expires_at.is_(None),
                    TicketRecord.ai_lease_expires_at < sweep_now,
                )
            ),
        ),
        or_(
            TicketRecord.ai_next_attempt_at.is_(None),
            TicketRecord.ai_next_attempt_at <= sweep_now,
        ),
    ).order_by(
        created_order.desc(),
        priority_order.asc(),
        TicketRecord.ai_next_attempt_at.asc(),
        TicketRecord.updated_at.desc(),
        TicketRecord.id.asc(),
    ).limit(batch_size).all()
    remaining = max(0, batch_size - len(queued))

    untriaged = (
        db.query(TicketRecord).filter(
            active_ticket_filter(db),
            automatic_ai_policy_eligible_filter({"triage"}),
            internal_automatic_source,
            or_(
                TicketRecord.ai_reasoning.is_(None),
                TicketRecord.ai_status.in_((
                    "stale", "legacy_stale", "provenance_unknown",
                )),
            ),
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_([
                    "dead_letter", "failed", "paused", "running", "queued",
                ]),
            ),
        ).order_by(
            created_order.desc(),
            priority_order.asc(),
            TicketRecord.id.asc(),
        ).limit(remaining).all()
        if auto_triage and remaining else []
    )
    triage_candidate_ids = list(dict.fromkeys(
        ticket.id for ticket in [*queued, *untriaged]
    ))
    selected_ids = set(triage_candidate_ids)
    remaining = max(0, batch_size - len(selected_ids))

    summary_query = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        automatic_ai_policy_eligible_filter({"summary"}),
        internal_automatic_source,
        TicketRecord.ai_reasoning.isnot(None),
        TicketRecord.summary.is_(None),
        or_(
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_status.notin_([
                "dead_letter", "failed", "paused", "running", "queued",
            ]),
        ),
        or_(
            TicketRecord.ai_next_attempt_at.is_(None),
            TicketRecord.ai_next_attempt_at <= sweep_now,
        ),
    ).order_by(
        created_order.desc(),
        priority_order.asc(),
        TicketRecord.updated_at.desc(),
        TicketRecord.id.asc(),
    )
    if selected_ids:
        summary_query = summary_query.filter(TicketRecord.id.notin_(selected_ids))
    no_summary = (
        summary_query.limit(remaining).all()
        if auto_summary and remaining else []
    )
    no_summary_ids = [ticket.id for ticket in no_summary]
    selected_ids.update(no_summary_ids)
    remaining = max(0, batch_size - len(selected_ids))

    resolution_query = db.query(TicketRecord).filter(
        active_ticket_filter(db),
        automatic_ai_policy_eligible_filter({"resolution"}),
        internal_automatic_source,
        TicketRecord.ai_reasoning.isnot(None),
        TicketRecord.summary.isnot(None),
        TicketRecord.recommended_solution.is_(None),
        or_(
            TicketRecord.ai_status.is_(None),
            TicketRecord.ai_status.notin_([
                "dead_letter", "failed", "paused", "running", "queued",
            ]),
        ),
        or_(
            TicketRecord.ai_next_attempt_at.is_(None),
            TicketRecord.ai_next_attempt_at <= sweep_now,
        ),
    ).order_by(
        created_order.desc(),
        priority_order.asc(),
        TicketRecord.updated_at.desc(),
        TicketRecord.id.asc(),
    )
    if selected_ids:
        resolution_query = resolution_query.filter(
            TicketRecord.id.notin_(selected_ids)
        )
    no_resolution = (
        resolution_query.limit(remaining).all()
        if auto_resolution and remaining else []
    )
    no_resolution_ids = [ticket.id for ticket in no_resolution]
    selected_ids.update(no_resolution_ids)
    remaining = max(0, batch_size - len(selected_ids))

    no_route = []
    if auto_route and remaining and artifact_identity is not None:
        current_route_artifact = db.query(AIArtifactRecord.id).filter(
            AIArtifactRecord.ticket_id == TicketRecord.id,
            AIArtifactRecord.artifact == "route",
            AIArtifactRecord.pipeline_version
            == artifact_identity["expected_pipeline_version"],
            AIArtifactRecord.model == artifact_identity["expected_model"],
            AIArtifactRecord.input_hash == TicketRecord.ai_routing_input_hash,
            AIArtifactRecord.active.is_(True),
        )
        if not artifact_identity["allow_synthetic_artifacts"]:
            current_route_artifact = current_route_artifact.filter(
                AIArtifactRecord.synthetic.is_(False)
            )
        route_query = db.query(TicketRecord).filter(
            active_ticket_filter(db),
            automatic_ai_policy_eligible_filter({"route"}),
            internal_automatic_source,
            or_(
                TicketRecord.ai_suggested_team.is_(None),
                TicketRecord.ai_routing_confidence.is_(None),
                TicketRecord.ai_routing_scope.is_(None),
                TicketRecord.ai_affected_service.is_(None),
                TicketRecord.ai_failure_domain.is_(None),
                TicketRecord.ai_routing_reason.is_(None),
                TicketRecord.ai_routing_input_hash.is_(None),
                TicketRecord.ai_status.in_((
                    "stale", "legacy_stale", "provenance_unknown",
                )),
                ~current_route_artifact.exists(),
            ),
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_([
                    "dead_letter", "failed", "paused", "running", "queued",
                ]),
            ),
        ).order_by(
            created_order.desc(),
            priority_order.asc(),
            TicketRecord.updated_at.desc(),
            TicketRecord.id.asc(),
        )
        if selected_ids:
            route_query = route_query.filter(TicketRecord.id.notin_(selected_ids))
        no_route = route_query.limit(remaining).all()
    no_route_ids = [ticket.id for ticket in no_route]

    return _AISweep(
        candidates=[
            *((ticket_id, None) for ticket_id in triage_candidate_ids),
            *((ticket_id, "summary") for ticket_id in no_summary_ids),
            *((ticket_id, "resolution") for ticket_id in no_resolution_ids),
            *((ticket_id, "route") for ticket_id in no_route_ids),
        ],
        queued=len(queued),
        untriaged=len(untriaged),
        no_summary=len(no_summary),
        no_resolution=len(no_resolution),
        no_route=len(no_route),
        terminal_cleaned=len(terminal_pending),
    )


def _auto_triage_job():
    """Admit prioritized ticket pipelines and process them concurrently.

    Each ticket retains one durable claim while its missing triage, summary,
    route, and resolution artifacts run. Provider concurrency adapts
    independently, so the sweep size is a fairness bound rather than a hard
    provider-rate ceiling.
    """
    _refresh_admin_settings()
    db = None
    try:
        db = SessionLocal()
        # A provider-wide cooldown stops admission before tickets are selected
        # or mutated. This turns one capacity response into one durable pause
        # instead of creating a retry warning for every ticket in the backlog.
        if provider_capacity_retry_after(db=db) > 0:
            return
        batch_size = _bounded_interval(
            "AI_BACKGROUND_TICKETS_PER_SWEEP", 5, 1, 25
        )
        auto_triage = settings_module.automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE")
        auto_summary = settings_module.automation_enabled("AUTO_SUMMARIZE_ENABLED")
        auto_route = settings_module.automation_enabled("AUTO_ROUTE_ENABLED")
        auto_resolution = settings_module.automation_enabled("AUTO_RESOLVE_ENABLED")
        artifact_identity = None
        try:
            artifact_identity, routing_backlog, recent = (
                _queue_integration_ai_backlog(db, batch_size)
            )
        except Exception as exc:
            db.rollback()
            # The routing provenance identity is useful only when the
            # integration scanners completed their schema-backed setup. Do
            # not let a missing/unavailable integration table cascade into the
            # independent internal triage lane through a route-artifact query.
            artifact_identity = None
            routing_backlog = {"enabled": False, "queued": 0}
            recent = {
                "lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
                "queued": 0,
            }
            print(
                "[auto-triage] recent lookback unavailable "
                f"kind={type(exc).__name__}"
            )
        sweep = _load_ai_sweep(
            db,
            batch_size=batch_size,
            auto_triage=auto_triage,
            auto_summary=auto_summary,
            auto_route=auto_route,
            auto_resolution=auto_resolution,
            artifact_identity=artifact_identity,
        )
        if (
            routing_backlog["queued"]
            or recent["queued"]
            or sweep.candidates
            or sweep.terminal_cleaned
        ):
            print(
                f"[auto-triage] routing_backlog={routing_backlog['queued']}, "
                f"recent={recent['queued']}, {sweep.queued} queued, "
                f"{sweep.untriaged} untriaged, "
                f"{sweep.no_route} no-route, {sweep.no_summary} no-summary, "
                f"{sweep.no_resolution} no-plan, "
                f"{sweep.terminal_cleaned} terminal-cleaned"
            )
        # End the read-only selection transaction before long provider calls;
        # every candidate owns a separate short-lived session and claim.
        db.rollback()
        capacity_error = asyncio.run(_process_ai_candidates(sweep.candidates))
        if capacity_error:
            print(
                "[auto-triage] deferred "
                f"reason={capacity_error.reason}"
            )
            # A dispatched provider 429 already persisted its precise cooldown
            # inside LLMManager. Only legacy/local callers need this fallback.
            if capacity_error.reason == "provider_capacity":
                defer_provider_capacity(capacity_error.retry_after_seconds)
            return

    except Exception as e:
        print(f"[auto-triage] job error kind={type(e).__name__}")
    finally:
        if db is not None:
            db.close()


def _sync_job():
    _refresh_admin_settings()
    provider = configured_provider()
    if provider in ("standalone", "none", ""):
        # An activated binding is authoritative over the legacy provider env.
        db = SessionLocal()
        try:
            expire_due_bindings(db)
            binding = get_active_binding(db)
        finally:
            db.close()
        if binding is None:
            return  # No external sync in standalone mode
    else:
        db = SessionLocal()
        try:
            expire_due_bindings(db)
            binding = get_active_binding(db, provider)
        finally:
            db.close()
    try:
        adapter = get_adapter(binding=binding) if binding else get_adapter()
        result = sync_tickets_from_external(
            adapter,
            binding_id=binding.id if binding else "legacy",
        )
        print(f"[sync_worker] {adapter.provider_name}: {result}")
    except Exception as e:
        print(f"[sync_worker] error kind={type(e).__name__}")


def _directory_sync_job():
    _refresh_admin_settings()
    if not settings_module.get_bool("DIRECTORY_SYNC_ENABLED"):
        return
    provider = configured_provider()
    db = SessionLocal()
    try:
        expire_due_bindings(db)
        binding = (
            get_active_binding(db)
            if provider in ("standalone", "none", "")
            else get_active_binding(db, provider)
        )
    finally:
        db.close()
    if provider in ("standalone", "none", "") and binding is None:
        return
    try:
        adapter = get_adapter(binding=binding) if binding else get_adapter()
        result = asyncio.run(directory_service.run_directory_sync(
            adapter,
            binding_id=binding.id if binding else "legacy",
        ))
        print(
            f"[directory_sync_worker] {adapter.provider_name}: "
            f"status={result.get('status', 'unknown')}"
        )
    except Exception as exc:
        print(f"[directory_sync_worker] error kind={type(exc).__name__}")


def start_sync_worker() -> bool:
    """Start the process-local scheduler once when this role owns jobs."""
    global _scheduler
    if not scheduler_enabled_for_process():
        return False
    with _lock:
        if _scheduler is not None:
            return False
        sync_interval = _bounded_interval("SYNC_INTERVAL_SECONDS", 60, 10, 86_400)
        triage_interval = _bounded_interval("AUTO_TRIAGE_INTERVAL_SECONDS", 30, 10, 86_400)
        risk_interval = _bounded_interval(
            "AI_RISK_BACKFILL_INTERVAL_SECONDS", 60, 10, 86_400
        )
        scheduler = BackgroundScheduler(daemon=True)
        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "replace_existing": True,
        }
        scheduler.add_job(
            _sync_job,
            "interval",
            seconds=sync_interval,
            id="sync_job",
            misfire_grace_time=sync_interval,
            next_run_time=datetime.now(),
            **job_defaults,
        )
        scheduler.add_job(
            _auto_triage_job,
            "interval",
            seconds=triage_interval,
            id="auto_triage_job",
            misfire_grace_time=triage_interval,
            next_run_time=datetime.now(),
            **job_defaults,
        )
        scheduler.add_job(
            _risk_backfill_job,
            "interval",
            seconds=risk_interval,
            id="risk_backfill_job",
            misfire_grace_time=risk_interval,
            next_run_time=datetime.now(),
            **job_defaults,
        )
        directory_interval = settings_module.get_int(
            "DIRECTORY_SYNC_INTERVAL_SECONDS",
            default=21_600,
            minimum=900,
            maximum=604_800,
        )
        if settings_module.get_bool("DIRECTORY_SYNC_ENABLED"):
            scheduler.add_job(
                _directory_sync_job,
                "interval",
                seconds=directory_interval,
                id="directory_sync_job",
                misfire_grace_time=directory_interval,
                next_run_time=datetime.now(),
                **job_defaults,
            )
        try:
            scheduler.start()
        except Exception:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
            raise
        _scheduler = scheduler
        print(
            f"[sync_worker] started role={process_role()}, "
            f"sync every {sync_interval}s, auto-triage every {triage_interval}s, "
            f"risk backfill every {risk_interval}s, "
            f"directory sync "
            f"{'every ' + str(directory_interval) + 's' if settings_module.get_bool('DIRECTORY_SYNC_ENABLED') else 'disabled'}"
        )
        return True


def stop_sync_worker(wait: bool = True) -> bool:
    """Stop the process-local scheduler once and optionally drain jobs."""
    global _scheduler
    with _lock:
        if _scheduler is None:
            return False
        scheduler = _scheduler
        _scheduler = None
        scheduler.shutdown(wait=wait)
        return True


def get_sync_status() -> dict:
    db = SessionLocal()
    try:
        expire_due_bindings(db)
        active_binding = get_active_binding(db)
        current_provider = configured_provider()
        binding_id = "legacy"
        if active_binding:
            current_provider = active_binding.provider
            binding_id = active_binding.id
        state = db.query(SyncStateRecord).filter(
            SyncStateRecord.binding_id == binding_id,
            SyncStateRecord.provider == current_provider
        ).first()
        local_ticket_count = int(db.query(func.count(TicketRecord.id)).filter(
            TicketRecord.binding_id == binding_id,
            TicketRecord.external_source == current_provider,
        ).scalar() or 0)
        limits = freshservice_sync_limits()
        attachment_counts = dict(db.query(
            ExternalAttachmentRecord.storage_status,
            func.count(ExternalAttachmentRecord.id),
        ).filter(
            ExternalAttachmentRecord.binding_id == binding_id,
            ExternalAttachmentRecord.provider == current_provider,
        ).group_by(ExternalAttachmentRecord.storage_status).all())
        operational = {
            "local_ticket_count": local_ticket_count,
            "sync_interval_seconds": _bounded_interval(
                "SYNC_INTERVAL_SECONDS", 60, 10, 86_400
            ),
            "recent_pages_per_sync": limits["recent_pages"],
            "history_pages_per_sync": limits["history_pages"],
            "conversations_per_sync": limits["conversations"],
            "attachments_per_sync": limits["attachments"],
            "attachment_storage_configured": attachment_storage_configured(),
            "attachment_pending": int(
                attachment_counts.get("pending", 0)
                + attachment_counts.get("waiting_storage", 0)
            ),
            "attachment_stored": int(attachment_counts.get("stored", 0)),
            "attachment_errors": int(attachment_counts.get("error", 0)),
        }
        if not state:
            return {"provider": current_provider, "binding_id": binding_id,
                    "last_synced_at": None, "last_synced": 0,
                    "automatic_ai_enabled": False,
                    "automatic_ai_generation": None,
                    "automatic_ai_cutover_at": None,
                    "automatic_ai_enabled_at": None,
                    "automatic_ai_paused_at": None,
                    "automatic_ai_lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
                    "automatic_fetch_days": AUTOMATIC_FETCH_DAYS,
                    "last_status": "idle", "last_error": None, "total_synced": 0,
                    "recent_since_at": None, "recent_cycle_started_at": None,
                    "recent_page": 1, "recent_workspace_index": 0,
                    "recent_completed_at": None,
                    "provider_timestamp_repair_pending": False,
                    "provider_timestamp_repair_days": (
                        PROVIDER_TIMESTAMP_REPAIR_DAYS
                    ),
                    "provider_timestamp_repair_processed": 0,
                    "background_history_page": 1,
                    "background_history_workspace_index": 0,
                    "background_history_complete": False,
                    "background_history_processed": 0,
                    "background_history_started_at": None,
                    "background_history_through_at": None,
                    "history_page": 1,
                    "history_workspace_index": 0, "history_complete": False,
                    "history_processed": 0, "history_since_at": None,
                    "history_until_at": None, "history_requested_at": None,
                    "conversations_processed": 0,
                    "run_started_at": None, "run_finished_at": None,
                    "next_retry_at": None, "rate_limit_total": None,
                    "rate_limit_remaining": None, "rate_limit_used": None,
                    "last_batch_new": 0, "last_batch_updated": 0,
                    "last_batch_errors": 0, **operational}
        provider_timestamp_repair_pending = (
            current_provider == "freshservice"
            and (state.provider_timestamp_repair_version or 0)
            < PROVIDER_TIMESTAMP_REPAIR_VERSION
        )
        background_history_scan_current = (
            (state.background_history_scan_version or 0)
            >= BACKGROUND_HISTORY_SCAN_VERSION
        )
        return {
            "provider": current_provider,
            "binding_id": binding_id,
            "last_synced_at": state.last_synced_at.isoformat() if state.last_synced_at else None,
            "automatic_ai_enabled": state.automatic_ai_enabled,
            "automatic_ai_generation": state.automatic_ai_generation,
            "automatic_ai_cutover_at": (
                state.automatic_ai_cutover_at.isoformat()
                if state.automatic_ai_cutover_at else None
            ),
            "automatic_ai_enabled_at": (
                state.automatic_ai_enabled_at.isoformat()
                if state.automatic_ai_enabled_at else None
            ),
            "automatic_ai_paused_at": (
                state.automatic_ai_paused_at.isoformat()
                if state.automatic_ai_paused_at else None
            ),
            "automatic_ai_lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
            "automatic_fetch_days": AUTOMATIC_FETCH_DAYS,
            "last_status": state.last_status or "idle",
            "last_error": state.last_error,
            "total_synced": state.total_synced or 0,
            "recent_since_at": (
                state.recent_since_at.isoformat() if state.recent_since_at else None
            ),
            "recent_cycle_started_at": (
                state.recent_cycle_started_at.isoformat()
                if state.recent_cycle_started_at else None
            ),
            "recent_page": state.recent_page or 1,
            "recent_workspace_index": state.recent_workspace_index or 0,
            "recent_completed_at": (
                state.recent_completed_at.isoformat()
                if state.recent_completed_at else None
            ),
            "provider_timestamp_repair_pending": (
                provider_timestamp_repair_pending
            ),
            "provider_timestamp_repair_days": PROVIDER_TIMESTAMP_REPAIR_DAYS,
            "provider_timestamp_repair_processed": (
                state.provider_timestamp_repair_processed or 0
            ),
            "background_history_page": state.background_history_page or 1,
            "background_history_workspace_index": (
                state.background_history_workspace_index or 0
            ),
            "background_history_complete": bool(
                background_history_scan_current
                and state.background_history_complete
            ),
            "background_history_processed": (
                state.background_history_processed or 0
            ),
            "background_history_started_at": (
                state.background_history_started_at.isoformat()
                if state.background_history_started_at else None
            ),
            "background_history_through_at": (
                state.background_history_through_at.isoformat()
                if state.background_history_through_at else None
            ),
            "history_page": state.history_page or 1,
            "history_workspace_index": state.history_workspace_index or 0,
            "history_complete": bool(state.history_complete),
            "history_processed": state.history_processed or 0,
            "history_since_at": (
                state.history_since_at.isoformat() if state.history_since_at else None
            ),
            "history_until_at": (
                state.history_until_at.isoformat() if state.history_until_at else None
            ),
            "history_requested_at": (
                state.history_requested_at.isoformat()
                if state.history_requested_at else None
            ),
            "conversations_processed": state.conversations_processed or 0,
            "run_started_at": (
                state.run_started_at.isoformat() if state.run_started_at else None
            ),
            "run_finished_at": (
                state.run_finished_at.isoformat() if state.run_finished_at else None
            ),
            "next_retry_at": (
                state.next_retry_at.isoformat() if state.next_retry_at else None
            ),
            "rate_limit_total": state.rate_limit_total,
            "rate_limit_remaining": state.rate_limit_remaining,
            "rate_limit_used": state.rate_limit_used,
            "last_batch_new": state.last_batch_new or 0,
            "last_batch_updated": state.last_batch_updated or 0,
            "last_batch_errors": state.last_batch_errors or 0,
            **operational,
        }
    finally:
        db.close()
