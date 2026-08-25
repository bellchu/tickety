import os
import secrets
from datetime import datetime
from pathlib import Path
from sqlalchemy import (
    create_engine, Column, String, Text, Integer, DateTime, Boolean, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://tickety:tickety@localhost:5432/tickety",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TicketRecord(Base):
    __tablename__ = "tickets"

    id = Column(String, primary_key=True, index=True)
    subject = Column(String, nullable=False)
    description = Column(Text, default="")
    reporter = Column(String, default="")
    status = Column(String, default="New")
    priority = Column(String, default="Medium")
    sentiment = Column(String, nullable=True)
    category = Column(String, nullable=True)
    mood = Column(String, nullable=True)
    complexity = Column(Integer, default=1)
    ai_reasoning = Column(Text, nullable=True)
    suggested_response = Column(Text, nullable=True)
    ai_source_hash = Column(String(64), nullable=True, index=True)
    ai_pipeline_version = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    ai_status = Column(String, nullable=True, index=True)
    ai_claim_id = Column(String(36), nullable=True, index=True)
    ai_lease_expires_at = Column(DateTime, nullable=True, index=True)
    ai_attempts = Column(Integer, nullable=False, default=0)
    ai_next_attempt_at = Column(DateTime, nullable=True, index=True)
    ai_requested_artifacts = Column(String, nullable=True)
    ai_started_at = Column(DateTime, nullable=True)
    ai_generated_at = Column(DateTime, nullable=True)
    ai_error = Column(String, nullable=True)
    ai_synthetic = Column(Boolean, nullable=False, default=False)
    ai_suggested_priority = Column(String, nullable=True)
    ai_suggested_category = Column(String, nullable=True)
    ai_suggested_team = Column(String, nullable=True)

    # Standalone ticketing fields
    ticket_type = Column(String, default="incident")  # incident | request
    impact = Column(String, nullable=True)
    urgency = Column(String, nullable=True)
    workflow_status = Column(String, default="New")
    ai_review_state = Column(String, nullable=True)
    assignee_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    service_id = Column(String, nullable=True)
    asset_id = Column(String, nullable=True)
    response_due_at = Column(DateTime, nullable=True)
    resolution_due_at = Column(DateTime, nullable=True)
    due_by = Column(DateTime, nullable=True)
    sla_paused_at = Column(DateTime, nullable=True)
    sla_paused_seconds = Column(Integer, default=0)
    tags = Column(Text, nullable=True)  # comma-separated tags

    # Public requester tracking capability. Only the SHA-256 digest is stored;
    # the bearer token itself is returned once when a portal ticket is created.
    portal_access_token_hash = Column(String(64), nullable=True, unique=True, index=True)
    portal_access_expires_at = Column(DateTime, nullable=True)

    # ITSM external linkage
    binding_id = Column(String(36), nullable=False, default="legacy", index=True)
    external_source = Column(String, nullable=True)
    external_id = Column(String, nullable=True, index=True)
    external_url = Column(String, nullable=True)
    external_status = Column(String, nullable=True)
    external_status_code = Column(String(64), nullable=True)
    external_priority_code = Column(String(64), nullable=True)
    external_ticket_type_raw = Column(String(255), nullable=True)
    external_source_context_hash = Column(String(64), nullable=True)
    external_assignee_id = Column(String, nullable=True)
    external_requester_id = Column(String(255), nullable=True, index=True)
    external_requester_name = Column(String(255), nullable=True)
    external_requester_email = Column(String(320), nullable=True)
    external_requester_title = Column(String(255), nullable=True)
    external_group_id = Column(String, nullable=True)
    external_category = Column(String, nullable=True)
    external_subcategory = Column(String, nullable=True)
    external_item_category = Column(String, nullable=True)
    external_workspace_id = Column(String, nullable=True)
    external_updated_at = Column(DateTime, nullable=True)
    external_conversation_text = Column(Text, nullable=True)
    external_description_html = Column(Text, nullable=True)
    external_conversation_updated_at = Column(DateTime, nullable=True)
    external_conversations_synced_at = Column(DateTime, nullable=True, index=True)
    external_created_at = Column(DateTime, nullable=True)
    external_resolved_at = Column(DateTime, nullable=True)
    external_due_by = Column(DateTime, nullable=True)
    external_fr_due_by = Column(DateTime, nullable=True)

    # Resolution tracking (populated when external status -> Closed)
    resolved_by = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    points_awarded = Column(Integer, default=0)
    points_awarded_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # SupportLogic-style intelligence fields
    escalation_risk = Column(Integer, default=0)
    summary = Column(Text, nullable=True)
    recommended_solution = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "external_source", "external_id",
            name="uix_binding_external_ticket",
        ),
    )


class AIUsageEventRecord(Base):
    __tablename__ = "ai_usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(String, nullable=False, index=True)
    task = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AIRequestBucketRecord(Base):
    __tablename__ = "ai_request_buckets"

    actor_id = Column(String, primary_key=True)
    window_kind = Column(String, primary_key=True)
    window_start = Column(DateTime, primary_key=True)
    request_count = Column(Integer, nullable=False, default=0)


class LLMCallRecord(Base):
    __tablename__ = "llm_call_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False)
    task = Column(String, nullable=False)
    status = Column(String, nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=1)
    latency_ms = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    synthetic = Column(Boolean, nullable=False, default=False)
    error_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class LLMProviderLeaseRecord(Base):
    __tablename__ = "llm_provider_leases"

    provider = Column(String, primary_key=True)
    slot = Column(Integer, primary_key=True)
    owner_id = Column(String(64), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)


class AIArtifactRecord(Base):
    __tablename__ = "ai_artifact_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    artifact = Column(String, nullable=False, index=True)
    input_hash = Column(String(64), nullable=False, index=True)
    pipeline_version = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    synthetic = Column(Boolean, nullable=False, default=False)
    content_hash = Column(String(64), nullable=False)
    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserRecord(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    avatar = Column(String, nullable=True)
    title = Column(String, nullable=True)
    impact_points = Column(Integer, default=0)
    tier = Column(Integer, default=1)
    momentum = Column(Integer, default=0)
    last_action_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Authentication / authorization
    role = Column(String, default="agent")  # admin | supervisor | agent
    password_hash = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)


class RecognitionRecord(Base):
    __tablename__ = "recognitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    recognition_key = Column(String, nullable=False)
    unlocked_at = Column(DateTime, default=datetime.utcnow)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "recognition_key", name="uix_user_recognition"),)


class ExternalUserRecord(Base):
    """Read-only projection of a user owned by an external ITSM provider.

    This table intentionally has no foreign key or mapping to ``users``.
    Tickety accounts and provider identities are separate security domains.
    """
    __tablename__ = "external_users"

    id = Column(String(36), primary_key=True)
    binding_id = Column(String(36), nullable=False, default="legacy", index=True)
    provider = Column(String(64), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    user_type = Column(String(32), nullable=False, default="agent", index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(320), nullable=True)
    title = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    profile_json = Column(Text, nullable=False, default="{}")
    source_updated_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "provider", "user_type", "external_id",
            name="uix_external_user_identity",
        ),
        Index(
            "ix_external_users_lookup",
            "binding_id", "provider", "external_id",
        ),
    )


class SyncStateRecord(Base):
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    binding_id = Column(String(36), nullable=False, default="legacy", index=True)
    provider = Column(String, nullable=False)
    # Automatic discovery advances only inside the fixed recent window.
    last_synced_at = Column(DateTime, nullable=True)
    automatic_ai_enabled = Column(Boolean, nullable=False, default=False, index=True)
    automatic_ai_generation = Column(Integer, nullable=True)
    automatic_ai_cutover_at = Column(DateTime, nullable=True)
    automatic_ai_enabled_at = Column(DateTime, nullable=True)
    automatic_ai_enabled_by = Column(String(255), nullable=True)
    automatic_ai_paused_at = Column(DateTime, nullable=True)
    automatic_ai_paused_by = Column(String(255), nullable=True)
    last_status = Column(String, default="idle")
    last_error = Column(Text, nullable=True)
    total_synced = Column(Integer, default=0)
    # Durable priority and background lanes for large Freshservice accounts.
    recent_since_at = Column(DateTime, nullable=True)
    recent_cycle_started_at = Column(DateTime, nullable=True)
    recent_page = Column(Integer, nullable=False, default=1)
    recent_workspace_index = Column(Integer, nullable=False, default=0)
    recent_completed_at = Column(DateTime, nullable=True)
    history_page = Column(Integer, nullable=False, default=1)
    history_workspace_index = Column(Integer, nullable=False, default=0)
    history_complete = Column(Boolean, nullable=False, default=False)
    history_processed = Column(Integer, nullable=False, default=0)
    history_since_at = Column(DateTime, nullable=True)
    history_until_at = Column(DateTime, nullable=True)
    history_requested_at = Column(DateTime, nullable=True)
    history_requested_by = Column(String(255), nullable=True)
    conversations_processed = Column(Integer, nullable=False, default=0)
    # A durable lease prevents overlapping scheduled and manual provider calls
    # and can be reclaimed after an interrupted worker run.
    run_token = Column(String(36), nullable=True, index=True)
    run_started_at = Column(DateTime, nullable=True)
    run_finished_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    rate_limit_total = Column(Integer, nullable=True)
    rate_limit_remaining = Column(Integer, nullable=True)
    rate_limit_used = Column(Integer, nullable=True)
    last_batch_new = Column(Integer, nullable=False, default=0)
    last_batch_updated = Column(Integer, nullable=False, default=0)
    last_batch_errors = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "provider", name="uix_sync_state_binding_provider"
        ),
        CheckConstraint(
            "automatic_ai_enabled = FALSE OR "
            "(automatic_ai_generation IS NOT NULL AND "
            "automatic_ai_cutover_at IS NOT NULL AND "
            "automatic_ai_enabled_at IS NOT NULL)",
            name="ck_sync_state_automatic_ai_boundary",
        ),
    )


class IntegrationBindingRecord(Base):
    """Immutable account boundary for one external ITSM installation."""
    __tablename__ = "integration_bindings"

    id = Column(String(36), primary_key=True)
    provider = Column(String(64), nullable=False, index=True)
    environment = Column(String(16), nullable=False, index=True)
    state = Column(String(16), nullable=False, default="draft", index=True)
    canonical_account_host = Column(String(255), nullable=False)
    installation_id = Column(String(255), nullable=True)
    workspace_ids = Column(Text, nullable=False, default="[]")
    product_variant = Column(String(32), nullable=True)
    credential_reference = Column(String(255), nullable=False, default="env://freshservice")
    capability_version = Column(Integer, nullable=False, default=1)
    validation_evidence = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    activated_by = Column(String, ForeignKey("users.id"), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "provider", "environment", "canonical_account_host", "installation_id",
            name="uix_integration_binding_installation",
        ),
        Index(
            "ix_integration_binding_lookup",
            "provider", "environment", "state",
        ),
    )


class IntegrationCapabilityRecord(Base):
    __tablename__ = "integration_capabilities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    binding_id = Column(
        String(36), ForeignKey("integration_bindings.id"), nullable=False, index=True
    )
    capability = Column(String(96), nullable=False)
    status = Column(String(16), nullable=False)
    details = Column(Text, nullable=True)
    checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "capability", name="uix_binding_capability"
        ),
    )


class IntegrationBootstrapRecord(Base):
    """One-time, hashed embedded-session bootstrap code."""
    __tablename__ = "integration_bootstrap_codes"

    code_hash = Column(String(64), primary_key=True)
    binding_id = Column(
        String(36), ForeignKey("integration_bindings.id"), nullable=False, index=True
    )
    external_user_id = Column(String(255), nullable=True)
    workspace_id = Column(String(255), nullable=True)
    audience = Column(String(255), nullable=False)
    context_json = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    redeemed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class IntegrationSessionRecord(Base):
    """Short-lived bearer session issued to an embedded Freshworks app."""
    __tablename__ = "integration_sessions"

    token_hash = Column(String(64), primary_key=True)
    binding_id = Column(
        String(36), ForeignKey("integration_bindings.id"), nullable=False, index=True
    )
    external_user_id = Column(String(255), nullable=False)
    workspace_id = Column(String(255), nullable=True)
    external_ticket_id = Column(String(255), nullable=True)
    audience = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)


class IntegrationAuditRecord(Base):
    __tablename__ = "integration_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    binding_id = Column(
        String(36), ForeignKey("integration_bindings.id"), nullable=False, index=True
    )
    action = Column(String(96), nullable=False, index=True)
    actor_id = Column(String, ForeignKey("users.id"), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ProviderOperationRecord(Base):
    __tablename__ = "provider_operations"

    id = Column(String(36), primary_key=True)
    binding_id = Column(
        String(36), ForeignKey("integration_bindings.id"), nullable=False, index=True
    )
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True, index=True)
    operation = Column(String(96), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    expected_external_version = Column(String(128), nullable=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    request_digest = Column(String(64), nullable=False)
    response_reference = Column(Text, nullable=True)
    error_code = Column(String(96), nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "idempotency_key", name="uix_binding_idempotency_key"
        ),
    )


class ProviderConflictRecord(Base):
    __tablename__ = "provider_conflicts"

    id = Column(String(36), primary_key=True)
    operation_id = Column(
        String(36), ForeignKey("provider_operations.id"), nullable=False, index=True
    )
    binding_id = Column(
        String(36), ForeignKey("integration_bindings.id"), nullable=False, index=True
    )
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True, index=True)
    field = Column(String(96), nullable=False)
    provider_snapshot = Column(Text, nullable=False)
    tickety_snapshot = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="open", index=True)
    resolved_by = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SettingsRecord(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TicketCommentRecord(Base):
    """Conversation thread on a ticket — public replies and private notes."""
    __tablename__ = "ticket_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    author_id = Column(String, ForeignKey("users.id"), nullable=True)
    author_name = Column(String, default="System")
    author_email = Column(String(320), nullable=True)
    body = Column(Text, nullable=False)
    is_private = Column(Boolean, default=False)  # True = internal note, False = public reply
    created_at = Column(DateTime, default=datetime.utcnow)
    external_source = Column(String(64), nullable=True)
    external_id = Column(String(255), nullable=True)
    external_author_id = Column(String(255), nullable=True)
    external_updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "ticket_id", "external_source", "external_id",
            name="uix_ticket_external_comment",
        ),
    )


class ExternalConversationRecord(Base):
    """Binding-scoped provider conversation projection."""

    __tablename__ = "external_conversations"

    id = Column(String(36), primary_key=True)
    binding_id = Column(String(36), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    provider_ticket_id = Column(String(255), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    body_hash = Column(String(64), nullable=False)
    is_private = Column(Boolean, nullable=False, default=False, index=True)
    incoming = Column(Boolean, nullable=False, default=False)
    source = Column(Integer, nullable=True)
    author_external_id = Column(String(255), nullable=True)
    author_name = Column(String(255), nullable=True)
    author_email = Column(String(320), nullable=True)
    provider_created_at = Column(DateTime, nullable=True)
    provider_updated_at = Column(DateTime, nullable=True)
    deleted = Column(Boolean, nullable=False, default=False, index=True)
    public_tombstone = Column(Boolean, nullable=False, default=False, index=True)
    revision_hash = Column(String(64), nullable=False, index=True)
    projection_version = Column(String(32), nullable=False, default="freshservice-v1")
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "provider", "provider_ticket_id", "external_id",
            name="uix_external_conversation_identity",
        ),
        Index(
            "ix_external_conversations_ticket_current",
            "binding_id", "provider", "provider_ticket_id", "deleted", "is_private",
        ),
    )


class ExternalAttachmentRecord(Base):
    """Lossless provider attachment metadata and private object-store state."""

    __tablename__ = "external_attachments"

    id = Column(String(36), primary_key=True)
    binding_id = Column(String(36), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    provider_ticket_id = Column(String(255), nullable=False, index=True)
    owner_type = Column(String(32), nullable=False)
    owner_external_id = Column(String(255), nullable=False)
    external_id = Column(String(255), nullable=False)
    file_name = Column(String(1024), nullable=False)
    content_type = Column(String(255), nullable=True)
    declared_size = Column(Integer, nullable=True)
    source_url = Column(Text, nullable=True)
    blob_key = Column(Text, nullable=True)
    content_sha256 = Column(String(64), nullable=True, index=True)
    stored_size = Column(Integer, nullable=True)
    storage_status = Column(String(32), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(255), nullable=True)
    last_attempted_at = Column(DateTime, nullable=True)
    stored_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "provider", "provider_ticket_id", "owner_type",
            "owner_external_id", "external_id",
            name="uix_external_attachment_identity",
        ),
        Index(
            "ix_external_attachments_ticket_status",
            "ticket_id", "storage_status",
        ),
        CheckConstraint(
            "owner_type IN ('ticket', 'conversation')",
            name="ck_external_attachment_owner_type",
        ),
    )


class ExternalActivityRecord(Base):
    """Append-only eligibility evidence for an authoritative provider revision."""

    __tablename__ = "external_activity_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    binding_id = Column(String(36), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    entity_type = Column(String(32), nullable=False)
    external_id = Column(String(255), nullable=False)
    revision_hash = Column(String(64), nullable=False)
    activity_at = Column(DateTime, nullable=True, index=True)
    acquisition_mode = Column(String(32), nullable=False)
    automatic_ai_generation = Column(Integer, nullable=True)
    automatic_ai_eligible = Column(Boolean, nullable=False, default=False, index=True)
    eligibility_reason = Column(String(96), nullable=False)
    affected_artifacts = Column(String(255), nullable=True)
    projected_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "provider", "ticket_id", "entity_type", "external_id",
            "revision_hash",
            name="uix_external_activity_revision",
        ),
        CheckConstraint(
            "automatic_ai_eligible = FALSE OR "
            "(activity_at IS NOT NULL AND automatic_ai_generation IS NOT NULL)",
            name="ck_external_activity_eligible_evidence",
        ),
    )


class ExternalTicketContextRecord(Base):
    """Provider workflow and assignment context, separate from local/AI state."""

    __tablename__ = "external_ticket_context"

    id = Column(String(36), primary_key=True)
    binding_id = Column(String(36), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    provider_ticket_id = Column(String(255), nullable=False)
    status_raw = Column(String(64), nullable=True)
    status_mapped = Column(String(120), nullable=True)
    priority_raw = Column(String(64), nullable=True)
    priority_mapped = Column(String(120), nullable=True)
    ticket_type_raw = Column(String(255), nullable=True)
    ticket_type_mapped = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)
    subcategory = Column(String(255), nullable=True)
    item_category = Column(String(255), nullable=True)
    group_external_id = Column(String(255), nullable=True)
    responder_external_id = Column(String(255), nullable=True)
    requester_external_id = Column(String(255), nullable=True)
    workspace_external_id = Column(String(255), nullable=True)
    provider_created_at = Column(DateTime, nullable=True)
    provider_updated_at = Column(DateTime, nullable=True)
    provider_resolved_at = Column(DateTime, nullable=True)
    provider_due_at = Column(DateTime, nullable=True)
    source_context_hash = Column(String(64), nullable=False)
    projection_version = Column(String(32), nullable=False, default="freshservice-v1")
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "binding_id", "provider", "provider_ticket_id",
            name="uix_external_ticket_context_identity",
        ),
    )


class TicketCategoryRecord(Base):
    """Predefined categories for ticket classification."""
    __tablename__ = "ticket_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, default="")
    color = Column(String, default="slate")  # UI color tag
    created_at = Column(DateTime, default=datetime.utcnow)


class TicketAuditLogRecord(Base):
    """Audit trail — every change to a ticket is recorded."""
    __tablename__ = "ticket_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    field = Column(String, nullable=False)  # which field changed
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_by = Column(String, default="System")
    changed_at = Column(DateTime, default=datetime.utcnow)


class SessionRecord(Base):
    """Login sessions — cookie-based auth."""
    __tablename__ = "sessions"

    token = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)


class SsoIdentityRecord(Base):
    """Stable OIDC subject linked to a local Tickety account.

    Email is retained only as an audit/display value. Authentication resolves
    the immutable issuer + subject pair so renamed or recycled email addresses
    cannot silently inherit an existing account.
    """

    __tablename__ = "sso_identities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(32), nullable=False)
    issuer = Column(String(512), nullable=False)
    subject = Column(String(512), nullable=False)
    email_at_link = Column(String(320), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uix_sso_identity_subject"),
        UniqueConstraint("user_id", "issuer", name="uix_sso_identity_user_issuer"),
    )


class SsoTransactionRecord(Base):
    """Single-use, database-backed OIDC authorization transaction."""

    __tablename__ = "sso_transactions"

    state_hash = Column(String(64), primary_key=True)
    nonce = Column(String(128), nullable=False)
    code_verifier = Column(String(128), nullable=False)
    next_path = Column(String(2048), nullable=False, default="/")
    provider = Column(String(32), nullable=False)
    discovery_url = Column(String(2048), nullable=False)
    redirect_uri = Column(String(2048), nullable=False)
    client_id = Column(String(512), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)


class KbArticleRecord(Base):
    """Knowledge Base articles."""
    __tablename__ = "kb_articles"

    id = Column(String, primary_key=True)  # uuid
    title = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=False, unique=True)
    content = Column(Text, default="")
    category = Column(String, nullable=True, index=True)  # e.g. Network, Software
    tags = Column(Text, nullable=True)  # comma-separated
    author_id = Column(String, ForeignKey("users.id"), nullable=True)
    reviewer_id = Column(String, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="draft")  # draft | published | archived
    version = Column(Integer, default=1)
    published_at = Column(DateTime, nullable=True)
    review_due_at = Column(DateTime, nullable=True)
    views = Column(Integer, default=0)
    helpful = Column(Integer, default=0)
    not_helpful = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_kb_status_cat", "status", "category"),)


class TicketLinkRecord(Base):
    """Links between tickets and KB articles (resolution references)."""
    __tablename__ = "ticket_kb_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    kb_article_id = Column(String, ForeignKey("kb_articles.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, default="System")


class TicketStatusConfigRecord(Base):
    """Custom ticket statuses — admin configurable."""
    __tablename__ = "ticket_status_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    label = Column(String, nullable=False)
    color = Column(String, default="slate")
    is_open = Column(Boolean, default=True)  # True = counts as "open" state
    is_terminal = Column(Boolean, default=False)  # True = closed/resolved
    sort_order = Column(Integer, default=0)


class TicketPriorityConfigRecord(Base):
    """Custom ticket priorities — admin configurable."""
    __tablename__ = "ticket_priority_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    label = Column(String, nullable=False)
    color = Column(String, default="slate")
    sla_hours = Column(Integer, nullable=True)  # override global SLA per priority
    weight = Column(Integer, default=10)  # sort weight (lower = higher priority)
    sort_order = Column(Integer, default=0)


class NotificationConfigRecord(Base):
    """Per-event notification settings — what triggers alerts."""
    __tablename__ = "notification_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event = Column(String, nullable=False, unique=True)  # sla_breach, escalation, new_ticket, etc.
    label = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    channels = Column(Text, default="in_app")  # comma-sep: in_app,email,webhook
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectRecord(Base):
    """Organisational workspaces — group tickets/assets/users into projects."""
    __tablename__ = "projects"

    id = Column(String, primary_key=True)  # uuid
    name = Column(String, nullable=False)
    key = Column(String, nullable=False, unique=True)  # short code e.g. "IT-SUPPORT"
    description = Column(Text, default="")
    lead_id = Column(String, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="active")  # active | archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Service Catalog ────────────────────────────────────────────

class ServiceItemRecord(Base):
    """Service catalog item that end-users can request."""
    __tablename__ = "service_items"

    id = Column(String, primary_key=True)  # uuid
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    category = Column(String, nullable=True, index=True)  # e.g. Hardware, Software, Access
    pricing = Column(String, nullable=True)  # free / cost estimate
    sla_hours = Column(Integer, nullable=True)  # fulfilment SLA
    approval_required = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ServiceRequestRecord(Base):
    """A request for a service item, linked to a ticket."""
    __tablename__ = "service_requests"

    id = Column(String, primary_key=True)  # uuid
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True, unique=True)
    service_item_id = Column(String, ForeignKey("service_items.id"), nullable=True)
    quantity = Column(Integer, default=1)
    justification = Column(Text, default="")
    approval_status = Column(String, default="not_required")  # not_required | pending | approved | rejected
    fulfillment_status = Column(String, default="pending")  # pending | fulfilled | cancelled
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    delivery_notes = Column(Text, nullable=True)
    fulfilled_by = Column(String, ForeignKey("users.id"), nullable=True)
    fulfilled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Problem Management ─────────────────────────────────────────

class ProblemRecord(Base):
    """ITIL Problem — the root cause of one or more incidents."""
    __tablename__ = "problems"

    id = Column(String, primary_key=True)  # uuid
    title = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    status = Column(String, default="New")  # New, Investigating, Root Cause Found, Resolved, Closed
    priority = Column(String, default="P2")
    category = Column(String, nullable=True)
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)
    root_cause = Column(Text, nullable=True)
    workaround = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
    impact_scope = Column(String, nullable=True)  # affected services, users
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProblemTicketLinkRecord(Base):
    """Links tickets (incidents) to their parent problem."""
    __tablename__ = "problem_ticket_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    linked_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("problem_id", "ticket_id", name="uix_problem_ticket"),)


# ── Change Management ──────────────────────────────────────────

class ChangeRecord(Base):
    """ITIL Change — a planned modification to IT services."""
    __tablename__ = "changes"

    id = Column(String, primary_key=True)  # uuid
    title = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    change_type = Column(String, default="Normal")  # Normal | Standard | Emergency
    status = Column(String, default="Draft")  # Draft, Submitted, CAB Review, Approved, In Progress, Completed, Rejected
    priority = Column(String, default="P2")
    risk_level = Column(String, default="Medium")  # Low, Medium, High
    impact = Column(String, nullable=True)
    rollback_plan = Column(Text, nullable=True)
    test_plan = Column(Text, nullable=True)
    scheduled_start = Column(DateTime, nullable=True)
    scheduled_end = Column(DateTime, nullable=True)
    requested_by = Column(String, ForeignKey("users.id"), nullable=True)
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChangeApprovalRecord(Base):
    """CAB / individual approvals for a change request."""
    __tablename__ = "change_approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    change_id = Column(String, ForeignKey("changes.id"), nullable=False, index=True)
    approver_id = Column(String, ForeignKey("users.id"), nullable=False)
    decision = Column(String, nullable=True)  # approved | rejected | pending
    comment = Column(Text, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("change_id", "approver_id", name="uix_change_approver"),)


class ChangeTicketLinkRecord(Base):
    """Links changes to the tickets they resolve."""
    __tablename__ = "change_ticket_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    change_id = Column(String, ForeignKey("changes.id"), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)


# ── Asset / CMDB ───────────────────────────────────────────────

class AssetRecord(Base):
    """Configuration item — hardware, software, licence, or service."""
    __tablename__ = "assets"

    id = Column(String, primary_key=True)  # uuid
    name = Column(String, nullable=False, index=True)
    asset_type = Column(String, nullable=False)  # Hardware, Software, License, Network, Facility
    asset_tag = Column(String, nullable=True, unique=True)  # scannable tag / serial
    status = Column(String, default="In Use")  # In Use, Available, Retired, Broken, Lost
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    location = Column(String, nullable=True)  # office, floor, rack
    vendor = Column(String, nullable=True)
    model = Column(String, nullable=True)
    purchase_date = Column(DateTime, nullable=True)
    warranty_expiry = Column(DateTime, nullable=True)
    cost = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Surveys / CSAT ──────────────────────────────────────────────

class SurveyTemplateRecord(Base):
    """Reusable survey template for post-resolution CSAT."""
    __tablename__ = "survey_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    question = Column(Text, nullable=False)  # e.g. "How satisfied were you with the resolution?"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SurveyRecord(Base):
    """A survey sent (or to be sent) for a resolved ticket."""
    __tablename__ = "surveys"

    id = Column(String, primary_key=True)  # uuid
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("survey_templates.id"), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SurveyResponseRecord(Base):
    """A submitted response for a sent survey."""
    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)


# ── Time Tracking ──────────────────────────────────────────────

class TimeEntryRecord(Base):
    """Time spent working on a ticket by an agent."""
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    description = Column(Text, default="")
    minutes = Column(Integer, nullable=False)
    entry_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


from sqlalchemy import inspect as _sa_inspect


def _ensure_ticket_search_documents():
    """Create the optional pgvector-backed search document table.

    The app can run without pgvector installed; retrieval will fall back to
    keyword scans until the extension is available.
    """
    if engine.dialect.name != "postgresql":
        print("[vectors] pgvector disabled: database is not PostgreSQL")
        return

    try:
        dimensions = int(os.getenv("TICKET_EMBEDDING_DIMENSIONS", "1536") or "1536")
    except ValueError:
        dimensions = 1536
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            conn.exec_driver_sql(
                f"""
                CREATE TABLE IF NOT EXISTS ticket_search_documents (
                    id BIGSERIAL PRIMARY KEY,
                    source_type VARCHAR NOT NULL,
                    source_id VARCHAR NOT NULL,
                    ticket_id VARCHAR,
                    title TEXT DEFAULT '',
                    body TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{{}}',
                    content_hash VARCHAR NOT NULL,
                    embedding vector({dimensions}),
                    embedding_model VARCHAR,
                    embedded_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (source_type, source_id)
                )
                """
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_ticket_search_documents_ticket_id "
                "ON ticket_search_documents (ticket_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_ticket_search_documents_source "
                "ON ticket_search_documents (source_type, source_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_ticket_search_documents_fts "
                "ON ticket_search_documents USING GIN ("
                "to_tsvector('simple'::regconfig, "
                "COALESCE(title, '') || ' ' || LEFT(COALESCE(body, ''), 20000))"
                ")"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_ticket_search_documents_embedding "
                "ON ticket_search_documents USING hnsw (embedding vector_cosine_ops)"
            )
    except Exception as e:
        print(f"[vectors] pgvector table unavailable kind={type(e).__name__}")


def _ensure_columns():
    """Legacy bootstrap support for non-production demo/development databases.

    Base.metadata.create_all() only creates *missing tables*, not missing
    columns on existing tables. Production schema changes are exclusively
    managed by Alembic and must never call this helper.
    """
    insp = _sa_inspect(engine)
    if not insp.has_table("tickets"):
        return  # nothing to migrate yet; create_all will build the full table

    # ── tickets table additions ──
    existing = {c["name"] for c in insp.get_columns("tickets")}
    additions = {
        "escalation_risk": "INTEGER DEFAULT 0",
        "summary": "TEXT",
        "recommended_solution": "TEXT",
        "ai_source_hash": "VARCHAR(64)",
        "ai_pipeline_version": "VARCHAR",
        "ai_model": "VARCHAR",
        "ai_status": "VARCHAR",
        "ai_claim_id": "VARCHAR(36)",
        "ai_lease_expires_at": "TIMESTAMP",
        "ai_attempts": "INTEGER DEFAULT 0",
        "ai_next_attempt_at": "TIMESTAMP",
        "ai_requested_artifacts": "VARCHAR",
        "ai_started_at": "TIMESTAMP",
        "ai_generated_at": "TIMESTAMP",
        "ai_error": "VARCHAR",
        "ai_synthetic": "BOOLEAN DEFAULT 0",
        "ai_suggested_priority": "VARCHAR",
        "ai_suggested_category": "VARCHAR",
        "ai_suggested_team": "VARCHAR",
        "ticket_type": "VARCHAR DEFAULT 'incident'",
        "impact": "VARCHAR",
        "urgency": "VARCHAR",
        "workflow_status": "VARCHAR DEFAULT 'New'",
        "ai_review_state": "VARCHAR",
        "assignee_id": "VARCHAR",
        "service_id": "VARCHAR",
        "asset_id": "VARCHAR",
        "response_due_at": "TIMESTAMP",
        "resolution_due_at": "TIMESTAMP",
        "due_by": "TIMESTAMP",
        "sla_paused_at": "TIMESTAMP",
        "sla_paused_seconds": "INTEGER DEFAULT 0",
        "tags": "TEXT",
        # Legacy demo/development compatibility; revision 0002 owns these in
        # production databases.
        "portal_access_token_hash": "VARCHAR(64)",
        "portal_access_expires_at": "TIMESTAMP",
        "external_workspace_id": "VARCHAR",
        "external_status_code": "VARCHAR(64)",
        "external_priority_code": "VARCHAR(64)",
        "external_ticket_type_raw": "VARCHAR(255)",
        "external_source_context_hash": "VARCHAR(64)",
        "external_group_id": "VARCHAR",
        "external_category": "VARCHAR",
        "external_subcategory": "VARCHAR",
        "external_item_category": "VARCHAR",
        "external_created_at": "TIMESTAMP",
        "external_resolved_at": "TIMESTAMP",
        "external_due_by": "TIMESTAMP",
        "external_fr_due_by": "TIMESTAMP",
        "external_conversation_text": "TEXT",
        "external_conversation_updated_at": "TIMESTAMP",
        "external_conversations_synced_at": "TIMESTAMP",
    }
    with engine.begin() as conn:
        for col, ddl in additions.items():
            if col not in existing:
                conn.exec_driver_sql(
                    f'ALTER TABLE tickets ADD COLUMN IF NOT EXISTS {col} {ddl}'
                )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_tickets_portal_access_token_hash "
            "ON tickets (portal_access_token_hash)"
        )

    if insp.has_table("sync_state"):
        sync_cols = {c["name"] for c in insp.get_columns("sync_state")}
        sync_additions = {
            "automatic_ai_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
            "automatic_ai_generation": "INTEGER",
            "automatic_ai_cutover_at": "TIMESTAMP",
            "automatic_ai_enabled_at": "TIMESTAMP",
            "automatic_ai_enabled_by": "VARCHAR(255)",
            "automatic_ai_paused_at": "TIMESTAMP",
            "automatic_ai_paused_by": "VARCHAR(255)",
            "recent_since_at": "TIMESTAMP",
            "recent_cycle_started_at": "TIMESTAMP",
            "recent_page": "INTEGER NOT NULL DEFAULT 1",
            "recent_workspace_index": "INTEGER NOT NULL DEFAULT 0",
            "recent_completed_at": "TIMESTAMP",
            "history_page": "INTEGER NOT NULL DEFAULT 1",
            "history_workspace_index": "INTEGER NOT NULL DEFAULT 0",
            "history_complete": "BOOLEAN NOT NULL DEFAULT FALSE",
            "history_processed": "INTEGER NOT NULL DEFAULT 0",
            "history_since_at": "TIMESTAMP",
            "history_until_at": "TIMESTAMP",
            "history_requested_at": "TIMESTAMP",
            "history_requested_by": "VARCHAR(255)",
            "conversations_processed": "INTEGER NOT NULL DEFAULT 0",
            "run_token": "VARCHAR(36)",
            "run_started_at": "TIMESTAMP",
            "run_finished_at": "TIMESTAMP",
            "next_retry_at": "TIMESTAMP",
            "rate_limit_total": "INTEGER",
            "rate_limit_remaining": "INTEGER",
            "rate_limit_used": "INTEGER",
            "last_batch_new": "INTEGER NOT NULL DEFAULT 0",
            "last_batch_updated": "INTEGER NOT NULL DEFAULT 0",
            "last_batch_errors": "INTEGER NOT NULL DEFAULT 0",
        }
        with engine.begin() as conn:
            for col, ddl in sync_additions.items():
                if col in sync_cols:
                    continue
                conn.exec_driver_sql(
                    f"ALTER TABLE sync_state ADD COLUMN IF NOT EXISTS {col} {ddl}"
                )

    if insp.has_table("ticket_comments"):
        comment_cols = {c["name"] for c in insp.get_columns("ticket_comments")}
        comment_additions = {
            "external_source": "VARCHAR(64)",
            "external_id": "VARCHAR(255)",
            "external_author_id": "VARCHAR(255)",
            "external_updated_at": "TIMESTAMP",
        }
        with engine.begin() as conn:
            for col, ddl in comment_additions.items():
                if col not in comment_cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE ticket_comments ADD COLUMN IF NOT EXISTS {col} {ddl}'
                    )
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uix_ticket_external_comment "
                "ON ticket_comments (ticket_id, external_source, external_id)"
            )

    # ── users table additions (auth/roles) ──
    if insp.has_table("users"):
        user_cols = {c["name"] for c in insp.get_columns("users")}
        user_additions = {
            "role": "VARCHAR DEFAULT 'agent'",
            "password_hash": "VARCHAR",
            "is_active": "BOOLEAN DEFAULT TRUE",
            "last_login_at": "TIMESTAMP",
        }
        with engine.begin() as conn:
            for col, ddl in user_additions.items():
                if col not in user_cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {ddl}'
                    )

    # ── service request workflow additions ──
    if insp.has_table("service_requests"):
        sr_cols = {c["name"] for c in insp.get_columns("service_requests")}
        sr_additions = {
            "approval_status": "VARCHAR DEFAULT 'not_required'",
            "fulfillment_status": "VARCHAR DEFAULT 'pending'",
            "approved_by": "VARCHAR",
            "approved_at": "TIMESTAMP",
            "delivery_notes": "TEXT",
            "fulfilled_by": "VARCHAR",
            "fulfilled_at": "TIMESTAMP",
        }
        with engine.begin() as conn:
            for col, ddl in sr_additions.items():
                if col not in sr_cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS {col} {ddl}'
                    )

    # ── knowledge governance additions ──
    if insp.has_table("kb_articles"):
        kb_cols = {c["name"] for c in insp.get_columns("kb_articles")}
        kb_additions = {
            "reviewer_id": "VARCHAR",
            "version": "INTEGER DEFAULT 1",
            "published_at": "TIMESTAMP",
            "review_due_at": "TIMESTAMP",
        }
        with engine.begin() as conn:
            for col, ddl in kb_additions.items():
                if col not in kb_cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE kb_articles ADD COLUMN IF NOT EXISTS {col} {ddl}'
                    )


def verify_database_schema() -> None:
    """Fail closed unless the production database is at the Alembic head."""
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        expected_heads = set(script.get_heads())
        with engine.connect() as connection:
            current_heads = set(MigrationContext.configure(connection).get_current_heads())
        if not expected_heads or current_heads != expected_heads:
            raise RuntimeError
    except Exception:
        raise RuntimeError(
            "Database schema is not at the required migration revision; run `alembic upgrade head`."
        ) from None


def init_db():
    if (os.getenv("APP_MODE") or "production").strip().lower() == "production":
        # Production startup is verification-only. DDL belongs to the explicit
        # migration job so replicas never race schema changes.
        verify_database_schema()
        return
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _ensure_ticket_search_documents()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
