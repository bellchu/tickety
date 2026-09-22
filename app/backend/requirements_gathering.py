"""Private, source-backed requirement gathering with explicit human validation."""
from datetime import datetime
import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.orm import Session, defer

from .database import (
    get_db, UserRecord, RequirementWorkspaceRecord, RequirementSourceRecord,
    BusinessRequirementRecord, RequirementDecisionRecord, RequirementHistoryRecord,
)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Detail = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
Criterion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_nul(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("NUL characters are not supported")
        if isinstance(value, list) and any(isinstance(item, str) and "\x00" in item for item in value):
            raise ValueError("NUL characters are not supported")
        return value


class WorkspaceCreate(InputModel):
    title: Title
    objective: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]
    request_type: Literal["approved_project", "enhancement"] = "approved_project"


class SourceCreate(InputModel):
    title: Title
    kind: Literal["document", "email", "sop", "transcript"]
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=100000)]


class GatherInput(InputModel):
    excerpt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=12000)]


class FilePreviewInput(InputModel):
    content_base64: Annotated[str, StringConstraints(min_length=1, max_length=533336)]


class RequirementInput(InputModel):
    source_id: Annotated[str, StringConstraints(min_length=1, max_length=36)]
    title: Title
    actor: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    action: Detail = ""
    benefit: Detail = ""
    evidence_quote: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]
    acceptance_criteria: list[Criterion] = Field(default_factory=list, max_length=20)
    priority: Literal["must", "should", "could", "wont"] = "should"


class RequirementUpdate(RequirementInput):
    revision: int = Field(ge=1, strict=True)


class RevisionInput(InputModel):
    revision: int = Field(ge=1, strict=True)


class ValidationInput(RevisionInput):
    reviewer_role: Literal["Product Owner", "Business Stakeholder", "Technical Business Analyst", "DTL"]
    validation_note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]


class DecisionInput(InputModel):
    requirement_id: Annotated[str, StringConstraints(min_length=1, max_length=36)] | None = None
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]
    owner_role: Title
    blocking: bool = Field(default=True, strict=True)


class DecisionResolution(InputModel):
    resolution: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]


class AssistanceInput(RevisionInput):
    mode: Literal["review", "story"]


def quality_issues(row: BusinessRequirementRecord) -> list[str]:
    issues = []
    for field, label in (("actor", "stakeholder or user role"), ("action", "required capability"), ("benefit", "business outcome")):
        if not getattr(row, field, "").strip():
            issues.append(f"Add the {label}.")
    criteria = json.loads(row.acceptance_json)
    if not criteria:
        issues.append("Add at least one testable acceptance criterion.")
    text = " ".join([row.action, *criteria])
    if re.search(r"\b(asap|user.friendly|fast|easy|seamless|appropriate|etc)\b", text, re.I):
        issues.append("Replace vague terms with an observable condition or measurable target.")
    if len({item.casefold() for item in criteria}) != len(criteria):
        issues.append("Remove duplicate acceptance criteria.")
    return issues


def ensure_delivery_scope(row):
    if row.priority == "wont":
        raise HTTPException(409, "This requirement is outside the current scope. Change its priority before sign-off or story preparation.")


def invalidate_agreement(row):
    row.status, row.validated_by, row.validated_at, row.story_json = "draft", None, None, None
    row.reviewer_role, row.validation_note = None, None
    row.revision += 1
    row.updated_at = datetime.utcnow()


def requirement_out(row):
    return {
        **{field: getattr(row, field) for field in (
            "id", "workspace_id", "source_id", "title", "actor", "action", "benefit",
            "evidence_quote", "priority", "status", "revision", "validated_by",
            "validated_at", "created_at", "updated_at", "reviewer_role", "validation_note",
        )},
        "reference": f"REQ-{row.number:03d}",
        "acceptance_criteria": json.loads(row.acceptance_json),
        "quality_issues": quality_issues(row),
        "story": json.loads(row.story_json) if row.story_json else None,
    }


def record_history(db, row, user, action, before=None):
    if action == "created":
        db.flush()  # Materialize database defaults for the initial snapshot.
    db.add(RequirementHistoryRecord(
        id=str(uuid4()), requirement_id=row.id, actor_id=user.id, action=action,
        revision=row.revision, before_json=json.dumps(before, default=str) if before else None,
        after_json=json.dumps(requirement_out(row), default=str),
    ))


def create_router(require_user, require_ai_user, get_llm, reserve_ai):
    router = APIRouter(prefix="/requirements", tags=["Requirement gathering"])

    def workspace(db, workspace_id, user, *, lock=False):
        query = db.query(RequirementWorkspaceRecord).filter_by(id=workspace_id)
        if user.role.lower() != "admin":
            query = query.filter_by(owner_id=user.id)
        row = (query.with_for_update() if lock else query).first()
        if row is None:
            raise HTTPException(404, "Requirement workspace not found")
        return row

    def requirement(db, workspace_id, requirement_id, user, revision):
        workspace(db, workspace_id, user, lock=True)
        row = db.query(BusinessRequirementRecord).filter_by(id=requirement_id, workspace_id=workspace_id).with_for_update().first()
        if row is None:
            raise HTTPException(404, "Requirement not found")
        if row.revision != revision:
            raise HTTPException(409, "This requirement changed. Refresh before saving or validating.")
        return row

    def check_source(db, workspace_id, data):
        source = db.query(RequirementSourceRecord).filter_by(id=data.source_id, workspace_id=workspace_id).first()
        if source is None:
            raise HTTPException(422, "Choose a source from this workspace")
        if data.evidence_quote not in source.content:
            raise HTTPException(422, "Evidence must be an exact excerpt from the selected source")

    @router.get("")
    def list_workspaces(offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        query = db.query(RequirementWorkspaceRecord)
        if user.role.lower() != "admin":
            query = query.filter_by(owner_id=user.id)
        total = query.count()
        rows = query.order_by(RequirementWorkspaceRecord.created_at.desc(), RequirementWorkspaceRecord.id).offset(offset).limit(limit).all()
        return {"items": rows, "total": total, "offset": offset, "limit": limit}

    @router.post("", status_code=201)
    def create_workspace(data: WorkspaceCreate, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        row = RequirementWorkspaceRecord(id=str(uuid4()), owner_id=user.id, **data.model_dump())
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @router.get("/{workspace_id}")
    def get_workspace(workspace_id: str, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        row = workspace(db, workspace_id, user)
        sources = db.query(RequirementSourceRecord).options(defer(RequirementSourceRecord.content)).filter_by(workspace_id=row.id).order_by(RequirementSourceRecord.created_at, RequirementSourceRecord.id).all()
        requirements = db.query(BusinessRequirementRecord).filter_by(workspace_id=row.id).order_by(BusinessRequirementRecord.created_at, BusinessRequirementRecord.id).all()
        return {"workspace": row, "sources": [{field: getattr(source, field) for field in ("id", "title", "kind", "content_sha256", "created_at")} for source in sources], "requirements": [requirement_out(item) for item in requirements], "decisions": db.query(RequirementDecisionRecord).filter_by(workspace_id=row.id).order_by(RequirementDecisionRecord.created_at, RequirementDecisionRecord.id).all()}

    def unresolved_decisions(db, workspace_id, requirement_id):
        return db.query(RequirementDecisionRecord).filter(
            RequirementDecisionRecord.workspace_id == workspace_id,
            RequirementDecisionRecord.status == "open",
            RequirementDecisionRecord.blocking.is_(True),
            (RequirementDecisionRecord.requirement_id.is_(None)) | (RequirementDecisionRecord.requirement_id == requirement_id),
        ).count()

    @router.post("/{workspace_id}/decisions", status_code=201)
    def add_decision(workspace_id: str, data: DecisionInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        workspace(db, workspace_id, user, lock=True)
        affected = db.query(BusinessRequirementRecord).filter_by(workspace_id=workspace_id)
        if data.requirement_id:
            affected = affected.filter_by(id=data.requirement_id)
            if affected.first() is None:
                raise HTTPException(422, "Choose a requirement from this workspace")
        if db.query(RequirementDecisionRecord).filter_by(workspace_id=workspace_id).count() >= 200:
            raise HTTPException(409, "This workspace already has 200 decision records")
        row = RequirementDecisionRecord(id=str(uuid4()), workspace_id=workspace_id, created_by=user.id, **data.model_dump())
        db.add(row)
        if data.blocking:
            for item in affected.with_for_update().all():
                before = requirement_out(item)
                invalidate_agreement(item)
                record_history(db, item, user, "blocked", before)
        db.commit()
        db.refresh(row)
        return row

    @router.post("/{workspace_id}/decisions/{decision_id}/resolve")
    def resolve_decision(workspace_id: str, decision_id: str, data: DecisionResolution, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        workspace(db, workspace_id, user, lock=True)
        row = db.query(RequirementDecisionRecord).filter_by(workspace_id=workspace_id, id=decision_id).with_for_update().first()
        if row is None:
            raise HTTPException(404, "Decision record not found")
        if row.status != "open":
            raise HTTPException(409, "This decision has already been recorded. Raise a new question if circumstances change.")
        row.status, row.resolution, row.resolved_by, row.resolved_at = "resolved", data.resolution, user.id, datetime.utcnow()
        db.commit()
        db.refresh(row)
        return row

    @router.post("/{workspace_id}/pdf-preview")
    def pdf_preview(workspace_id: str, data: FilePreviewInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        from .requirement_pdf import preview_pdf
        workspace(db, workspace_id, user)
        db.rollback()  # Do not hold a database transaction while the parser runs.
        try:
            return preview_pdf(data.content_base64)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/{workspace_id}/docx-preview")
    def docx_preview(workspace_id: str, data: FilePreviewInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        from .requirement_docx import preview_docx
        workspace(db, workspace_id, user)
        try:
            return preview_docx(data.content_base64)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/{workspace_id}/email-preview")
    def email_preview(workspace_id: str, data: FilePreviewInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        from .requirement_email import preview_email
        workspace(db, workspace_id, user)
        try:
            return preview_email(data.content_base64)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/{workspace_id}/sources", status_code=201)
    def add_source(workspace_id: str, data: SourceCreate, response: Response, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        workspace(db, workspace_id, user, lock=True)
        digest = hashlib.sha256(data.content.encode()).hexdigest()
        existing = db.query(RequirementSourceRecord).filter_by(workspace_id=workspace_id, content_sha256=digest).order_by(RequirementSourceRecord.created_at, RequirementSourceRecord.id).all()
        for source in existing:
            if source.content == data.content:
                response.status_code = 200
                return {**{field: getattr(source, field) for field in ("id", "workspace_id", "title", "kind", "content", "content_sha256", "created_at")}, "reused": True}
        if db.query(RequirementSourceRecord).filter_by(workspace_id=workspace_id).count() >= 50:
            raise HTTPException(409, "This workspace already has 50 sources. Create another workspace.")
        row = RequirementSourceRecord(id=str(uuid4()), workspace_id=workspace_id, content_sha256=digest, **data.model_dump())
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @router.get("/{workspace_id}/sources/{source_id}")
    def get_source(workspace_id: str, source_id: str, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        workspace(db, workspace_id, user)
        row = db.query(RequirementSourceRecord).filter_by(id=source_id, workspace_id=workspace_id).first()
        if row is None:
            raise HTTPException(404, "Source not found")
        return row

    @router.post("/{workspace_id}/items", status_code=201)
    def add_requirement(workspace_id: str, data: RequirementInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        workspace(db, workspace_id, user, lock=True)
        check_source(db, workspace_id, data)
        count = db.query(BusinessRequirementRecord).filter_by(workspace_id=workspace_id).count()
        if count >= 200:
            raise HTTPException(409, "This workspace already has 200 requirements. Create another workspace.")
        values = data.model_dump(exclude={"acceptance_criteria"})
        row = BusinessRequirementRecord(id=str(uuid4()), workspace_id=workspace_id, number=count + 1, acceptance_json=json.dumps(data.acceptance_criteria), **values)
        db.add(row)
        record_history(db, row, user, "created")
        db.commit()
        db.refresh(row)
        return requirement_out(row)

    @router.put("/{workspace_id}/items/{requirement_id}")
    def update_requirement(workspace_id: str, requirement_id: str, data: RequirementUpdate, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        row = requirement(db, workspace_id, requirement_id, user, data.revision)
        check_source(db, workspace_id, data)
        before = requirement_out(row)
        for key, value in data.model_dump(exclude={"acceptance_criteria", "revision"}).items():
            setattr(row, key, value)
        row.acceptance_json = json.dumps(data.acceptance_criteria)
        invalidate_agreement(row)
        record_history(db, row, user, "edited", before)
        db.commit()
        return requirement_out(row)

    @router.post("/{workspace_id}/items/{requirement_id}/validate")
    def validate_requirement(workspace_id: str, requirement_id: str, data: ValidationInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        row = requirement(db, workspace_id, requirement_id, user, data.revision)
        ensure_delivery_scope(row)
        if row.status != "draft":
            raise HTTPException(409, "This requirement is already signed off. Edit it to start a new review.")
        if unresolved_decisions(db, workspace_id, row.id):
            raise HTTPException(409, "Resolve the blocking business questions before sign-off")
        issues = quality_issues(row)
        if issues:
            raise HTTPException(422, " ".join(issues))
        before = requirement_out(row)
        row.status, row.validated_by, row.validated_at = "validated", user.id, datetime.utcnow()
        row.reviewer_role, row.validation_note = data.reviewer_role, data.validation_note
        row.revision += 1
        row.updated_at = datetime.utcnow()
        record_history(db, row, user, "signed_off", before)
        db.commit()
        return requirement_out(row)

    @router.post("/{workspace_id}/items/{requirement_id}/story")
    def create_story(workspace_id: str, requirement_id: str, data: RevisionInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        row = requirement(db, workspace_id, requirement_id, user, data.revision)
        ensure_delivery_scope(row)
        if row.status != "validated" or not row.validated_at:
            raise HTTPException(409, "Validate the requirement before creating its user story")
        if unresolved_decisions(db, workspace_id, row.id):
            raise HTTPException(409, "Resolve the blocking business questions before preparing delivery")
        if row.story_json is None:
            before = requirement_out(row)
            row.story_json = json.dumps({
                "title": row.title,
                "statement": f"As a {row.actor}, I want to {row.action}, so that {row.benefit}.",
                "acceptance_criteria": json.loads(row.acceptance_json),
                "requirement_id": row.id, "source_id": row.source_id,
                "reference": f"US-{row.number:03d}", "requirement_reference": f"REQ-{row.number:03d}",
                "validated_revision": row.revision, "priority": row.priority,
            })
            row.revision += 1
            row.updated_at = datetime.utcnow()
            record_history(db, row, user, "story_created", before)
            db.commit()
        return requirement_out(row)

    @router.get("/{workspace_id}/items/{requirement_id}/history")
    def requirement_history(workspace_id: str, requirement_id: str, offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: UserRecord = Depends(require_user)):
        workspace(db, workspace_id, user)
        if not db.query(BusinessRequirementRecord).filter_by(id=requirement_id, workspace_id=workspace_id).first():
            raise HTTPException(404, "Requirement not found")
        query = db.query(RequirementHistoryRecord).filter_by(requirement_id=requirement_id)
        total = query.count()
        rows = query.order_by(RequirementHistoryRecord.revision.desc()).offset(offset).limit(10).all()
        return {"total": total, "items": [{
            "id": row.id, "actor_id": row.actor_id, "action": row.action,
            "revision": row.revision, "created_at": row.created_at,
            "before": json.loads(row.before_json) if row.before_json else None,
            "after": json.loads(row.after_json),
        } for row in rows]}

    @router.post("/{workspace_id}/sources/{source_id}/gather")
    async def gather_requirements(workspace_id: str, source_id: str, data: GatherInput | None = None, db: Session = Depends(get_db), user: UserRecord = Depends(require_ai_user)):
        from .requirements_ai import gather, prepare_prompt

        initiative = workspace(db, workspace_id, user)
        source = db.query(RequirementSourceRecord).filter_by(id=source_id, workspace_id=workspace_id).first()
        if source is None:
            raise HTTPException(404, "Source not found")
        llm = get_llm()
        original_content = source.content
        selected_content = data.excerpt if data else original_content
        if data and selected_content not in original_content:
            raise HTTPException(422, "Choose an exact passage from the saved source")
        prompt = prepare_prompt(llm, objective=initiative.objective, source_title=source.title, content=selected_content)
        reserve_ai(db, user.id, "requirements_gather")
        suggestions = await gather(llm, prompt, original_content)
        return {**suggestions, "source_id": source_id, "model": llm.model_name, "scope": "excerpt" if data else "source"}

    @router.post("/{workspace_id}/items/{requirement_id}/assist")
    async def assist_requirement(workspace_id: str, requirement_id: str, data: AssistanceInput, db: Session = Depends(get_db), user: UserRecord = Depends(require_ai_user)):
        from .requirements_ai import prepare_prompt, suggest, ReviewSuggestions, StorySuggestions

        row = requirement(db, workspace_id, requirement_id, user, data.revision)
        if data.mode == "story":
            ensure_delivery_scope(row)
        if data.mode == "story" and row.status != "validated":
            raise HTTPException(409, "Sign off the requirement before requesting story refinement")
        llm = get_llm()
        prompt = prepare_prompt(llm, requirement=json.dumps({
            "title": row.title, "actor": row.actor, "action": row.action,
            "benefit": row.benefit, "evidence_quote": row.evidence_quote,
            "acceptance_criteria": json.loads(row.acceptance_json),
        }, ensure_ascii=False))
        # Release the row lock before any provider work. Suggestions cannot write
        # data, and applying a suggestion still requires the captured revision.
        db.rollback()
        reserve_ai(db, user.id, f"requirements_{data.mode}")
        if data.mode == "review":
            result = await suggest(llm, prompt, ReviewSuggestions,
                "Review this requirement for ambiguity, testability, missing context, unsupported claims and scope. Return findings and stakeholder questions only. Never declare it approved or signed off.")
        else:
            result = await suggest(llm, prompt, StorySuggestions,
                "Suggest a clearer user role, capability, outcome and testable acceptance criteria for this signed-off requirement. Preserve its scope and evidence. Mark every proposed new condition as an assumption. A human must review any changes before new sign-off.")
        return {"suggestions": result, "base_revision": data.revision, "mode": data.mode, "model": llm.model_name,
                "input_truncated": any(value for key, value in json.loads(prompt).items() if key.endswith("_truncated"))}

    return router
