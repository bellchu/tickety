import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text, Integer, DateTime, Boolean, Float,
    ForeignKey, UniqueConstraint,
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

    # ITSM external linkage
    external_source = Column(String, nullable=True)
    external_id = Column(String, nullable=True, index=True)
    external_url = Column(String, nullable=True)
    external_status = Column(String, nullable=True)
    external_assignee_id = Column(String, nullable=True)
    external_updated_at = Column(DateTime, nullable=True)

    # Resolution tracking (populated when external status -> Closed)
    resolved_by = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    points_awarded = Column(Integer, default=0)
    points_awarded_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # SupportLogic-style intelligence fields
    escalation_risk = Column(Integer, default=0)  # 0-100, predicted escalation risk
    summary = Column(Text, nullable=True)        # AI-generated case summary
    recommended_solution = Column(Text, nullable=True)  # AI resolution steps for the engineer

    __table_args__ = (UniqueConstraint("external_source", "external_id", name="uix_external_ticket"),)


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


class RecognitionRecord(Base):
    __tablename__ = "recognitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    recognition_key = Column(String, nullable=False)
    unlocked_at = Column(DateTime, default=datetime.utcnow)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "recognition_key", name="uix_user_recognition"),)


class UserMappingRecord(Base):
    __tablename__ = "user_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tickety_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    external_source = Column(String, nullable=False)
    external_assignee_id = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "external_source", "external_assignee_id",
            name="uix_external_assignee",
        ),
    )


class SyncStateRecord(Base):
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False, unique=True)
    last_synced_at = Column(DateTime, default=datetime.utcnow)
    last_status = Column(String, default="idle")
    last_error = Column(Text, nullable=True)
    total_synced = Column(Integer, default=0)


class SettingsRecord(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


from sqlalchemy import inspect as _sa_inspect


def _ensure_columns():
    """Idempotently add columns introduced after the initial schema.

    Base.metadata.create_all() only creates *missing tables*, not missing
    columns on existing tables, so for already-deployed Postgres instances we
    ALTER TABLE ... ADD COLUMN IF NOT EXISTS for any new field.
    """
    insp = _sa_inspect(engine)
    if not insp.has_table("tickets"):
        return  # nothing to migrate yet; create_all will build the full table

    existing = {c["name"] for c in insp.get_columns("tickets")}
    additions = {
        "escalation_risk": "INTEGER DEFAULT 0",
        "summary": "TEXT",
        "recommended_solution": "TEXT",
    }
    with engine.begin() as conn:
        for col, ddl in additions.items():
            if col not in existing:
                conn.exec_driver_sql(
                    f'ALTER TABLE tickets ADD COLUMN IF NOT EXISTS {col} {ddl}'
                )


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()