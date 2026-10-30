from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import ProviderConfigurationError
from app.db.models import (
    AcceptanceCriterion,
    AgentRun,
    AuditEvent,
    ClarificationAnswer,
    ClarificationQuestion,
    Decision,
    Export,
    ExportDocument,
    Fact,
    FactSource,
    Project,
    ProjectDocument,
    ProjectRevision,
    ProjectRevisionSource,
    ProjectSource,
    ProviderConsent,
    Requirement,
    RequirementSource,
    RunEvent,
    ValidationFinding,
    ValidationReport,
    Workspace,
)
from app.db.repositories import (
    IdempotencyConflictError,
    ProjectNotFoundError,
    RepositoryInputError,
    RevisionConflictError,
    RevisionInput,
    SourceInput,
    canonical_request_hash,
    create_or_get_run,
    create_project,
    create_project_revision,
    delete_project,
    get_project,
    list_project_page,
    set_decision_status,
)
from app.models import ClarificationResult, GeneratedDocuments, Statement
from app.modules.document_generation.requirements import RequirementDraft, parse_requirements
from app.services.package_builder import PackageValidationError, build_verified_archive
from app.services.provider import ProviderError

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
logger = logging.getLogger(__name__)
AI_DISCLOSURE_VERSION = "local-ai-v1"

ProjectName = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]
IdeaText = Annotated[str, StringConstraints(min_length=1, max_length=20_000, strip_whitespace=True)]
AudienceText = Annotated[str, StringConstraints(max_length=1_000, strip_whitespace=True)]
PlatformText = Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]
ConstraintsText = Annotated[str, StringConstraints(max_length=2_000, strip_whitespace=True)]
TechnologyText = Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]
LanguageText = Annotated[str, StringConstraints(min_length=2, max_length=32, strip_whitespace=True)]


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    idea: IdeaText
    audience: AudienceText = ""
    platform: PlatformText = ""
    constraints: ConstraintsText = ""
    technology: TechnologyText = ""
    language: LanguageText = "English"
    profile: Literal["compact", "detailed"] = "compact"


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    name: ProjectName | None = None
    idea: IdeaText | None = None
    audience: AudienceText | None = None
    platform: PlatformText | None = None
    constraints: ConstraintsText | None = None
    technology: TechnologyText | None = None
    language: LanguageText | None = None
    profile: Literal["compact", "detailed"] | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> ProjectUpdateRequest:
        updated_fields = self.model_fields_set - {"expected_revision"}
        if not updated_fields:
            raise ValueError("At least one project field must be updated.")
        if any(getattr(self, field) is None for field in updated_fields):
            raise ValueError("Project update fields cannot be null.")
        return self


class ProjectResource(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    current_revision: int


class ProjectCreatedResponse(BaseModel):
    project: ProjectResource
    revision_id: UUID


class ProjectListResponse(BaseModel):
    items: list[ProjectResource]
    limit: int
    offset: int
    next_cursor: str | None = None


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent: bool


class ClarificationQuestionResource(BaseModel):
    id: UUID
    question: str
    impact: str
    blocking: bool
    status: str
    answer_state: str | None = None
    answer: str | None = None


class ClarificationResponse(BaseModel):
    project_id: UUID
    revision_id: UUID
    consent_id: UUID | None
    questions: list[ClarificationQuestionResource]


class ClarificationAnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: UUID
    answer_state: Literal["answered", "unknown", "deferred"]
    answer: (
        Annotated[str, StringConstraints(min_length=1, max_length=2_000, strip_whitespace=True)]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_answer_state(self) -> ClarificationAnswerInput:
        if self.answer_state == "answered" and self.answer is None:
            raise ValueError("An answer is required when answer_state is 'answered'.")
        if self.answer_state != "answered" and self.answer is not None:
            raise ValueError("Answer text is only allowed when answer_state is 'answered'.")
        return self


class ClarificationAnswersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: Annotated[list[ClarificationAnswerInput], Field(min_length=1, max_length=6)]


class GenerateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent: bool


class ProjectDocumentSummary(BaseModel):
    id: UUID
    path: str
    document_kind: str
    sha256: str


class GenerateProjectResponse(BaseModel):
    project_id: UUID
    revision_id: UUID
    run_id: UUID
    status: str
    documents: list[ProjectDocumentSummary]


class ReviewAndValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    document_ids: Annotated[list[UUID], Field(min_length=1, max_length=64)]


class ValidationResponse(BaseModel):
    id: UUID
    status: str
    checked_document_count: int
    finding_count: int


class ExportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_report_id: UUID
    confirm: bool


class ExportResponse(BaseModel):
    id: UUID
    status: str
    zip_sha256: str
    download_path: str


class ProjectWorkflowSnapshot(BaseModel):
    project_id: UUID
    revision_id: UUID
    clarification: ClarificationResponse
    documents: list[ProjectDocumentSummary]
    validation: ValidationResponse | None
    exports: list[ExportResponse]


class DecisionApprovalRequest(BaseModel):
    """Explicitly authorized decision approval or rejection.

    This request is the only path to change a proposed decision to accepted
    or rejected. AI output and Coding Agent calls cannot use this endpoint
    implicitly; the user action must include this body.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool
    reason: Annotated[str, StringConstraints(max_length=2_000, strip_whitespace=True)] | None = None


class DecisionResource(BaseModel):
    id: UUID
    statement: str
    rationale: str | None
    status: str
    decided_by: str | None
    decided_at: datetime | None


class DecisionListResponse(BaseModel):
    decisions: list[DecisionResource]


def _project_resource(project: Project) -> ProjectResource:
    return ProjectResource(
        id=project.id,
        name=project.name,
        slug=project.slug,
        status=project.status,
        current_revision=project.current_revision,
    )


def _encode_project_cursor(project: Project) -> str:
    payload = json.dumps(
        {
            "version": 1,
            "updated_at": project.updated_at.isoformat(),
            "id": str(project.id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_project_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        encoded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.b64decode(encoded, altchars=b"-_", validate=True).decode("utf-8")
        )
        if (
            not isinstance(payload, dict)
            or set(payload) != {"version", "updated_at", "id"}
            or payload["version"] != 1
            or not isinstance(payload["updated_at"], str)
            or not isinstance(payload["id"], str)
        ):
            raise ValueError("Invalid project cursor.")
        updated_at = datetime.fromisoformat(payload["updated_at"])
        if updated_at.utcoffset() is None:
            raise ValueError("Invalid project cursor timestamp.")
        return updated_at, UUID(payload["id"])
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError("Invalid project cursor.") from exc


def _clarification_response(
    *,
    project_id: UUID,
    revision_id: UUID,
    consent_id: UUID | None,
    questions: list[ClarificationQuestion],
    latest_answers: dict[UUID, tuple[str, str | None]] | None = None,
) -> ClarificationResponse:
    answer_map = latest_answers or {}
    return ClarificationResponse(
        project_id=project_id,
        revision_id=revision_id,
        consent_id=consent_id,
        questions=[
            ClarificationQuestionResource(
                id=question.id,
                question=question.question,
                impact=question.impact,
                blocking=question.blocking,
                status=question.status,
                answer_state=answer_map.get(question.id, (None, None))[0],
                answer=answer_map.get(question.id, (None, None))[1],
            )
            for question in questions
        ],
    )


async def _latest_clarification_answers(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    questions: list[ClarificationQuestion],
) -> dict[UUID, tuple[str, str | None]]:
    if not questions:
        return {}
    rows = await session.execute(
        select(ClarificationAnswer, ProjectSource.content)
        .outerjoin(
            ProjectSource,
            (ProjectSource.workspace_id == ClarificationAnswer.workspace_id)
            & (ProjectSource.project_id == ClarificationAnswer.project_id)
            & (ProjectSource.id == ClarificationAnswer.source_id),
        )
        .where(
            ClarificationAnswer.workspace_id == workspace_id,
            ClarificationAnswer.project_id == project_id,
            ClarificationAnswer.question_id.in_([question.id for question in questions]),
        )
        .order_by(ClarificationAnswer.created_at, ClarificationAnswer.id)
    )
    latest: dict[UUID, tuple[str, str | None]] = {}
    for answer_record, content in rows:
        latest[answer_record.question_id] = (answer_record.answer_state, content)
    return latest


def _fact_source_ids(
    statement: Statement,
    source_records: list[tuple[UUID, str | None, str]],
) -> list[UUID]:
    input_source_labels = {
        "User-provided idea": "User-provided idea",
        "User-provided audience": "Intended audience",
        "User-provided platform": "Preferred platform",
        "User-provided constraints": "User constraints",
        "User-provided technology preference": "Preferred technology",
    }
    source_label = input_source_labels.get(statement.source)
    if source_label is not None:
        matches = [
            source_id
            for source_id, safe_label, content in source_records
            if safe_label == source_label and content == statement.text
        ]
        # Explicit match only; do not fall back heuristically
        if matches:
            return matches
        return []
    if statement.source == "User clarification answer":
        matches = [
            source_id
            for source_id, safe_label, content in source_records
            if safe_label == "Clarification answer" and statement.text.endswith(f": {content}")
        ]
        if matches:
            return matches
        return []
    # For non-user sources with unknown provenance, do not silently link to arbitrary sources
    return []


async def _persist_normalized_generation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    generated: GeneratedDocuments,
    requirements: tuple[RequirementDraft, ...],
    source_records: list[tuple[UUID, str | None, str]],
) -> None:
    fact_rows: list[Fact] = []
    fact_source_rows: list[FactSource] = []
    fact_groups = (
        (generated.facts, "confirmed_fact", "confirmed"),
        (generated.assumptions, "assumption", "unconfirmed"),
        (generated.constraints, "constraint", "unconfirmed"),
        (generated.exclusions, "exclusion", "unconfirmed"),
    )
    for statements, classification, approval_status in fact_groups:
        for statement in statements:
            fact_id = uuid4()
            fact_rows.append(
                Fact(
                    id=fact_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    revision_id=revision_id,
                    classification=classification,
                    statement=statement.text,
                    approval_status=approval_status,
                )
            )
            fact_source_rows.extend(
                FactSource(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    fact_id=fact_id,
                    source_id=source_id,
                )
                for source_id in _fact_source_ids(statement, source_records)
            )
    session.add_all(fact_rows)
    await session.flush()
    session.add_all(fact_source_rows)
    await session.flush()

    decisions = [
        Decision(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            revision_id=revision_id,
            statement=proposal.text,
            rationale=None,
            status="proposed",
        )
        for proposal in generated.accepted_proposals
    ]
    session.add_all(decisions)
    await session.flush()

    requirement_rows = [
        Requirement(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            revision_id=revision_id,
            requirement_key=requirement.key,
            statement=requirement.statement,
            status="draft",
        )
        for requirement in requirements
    ]
    session.add_all(requirement_rows)
    await session.flush()

    # Link requirements to all revision sources (explicit provenance).
    requirement_source_rows = []
    if source_records:
        source_ids = [source_id for source_id, _safe_label, _content in source_records]
        for requirement_row in requirement_rows:
            for source_id in source_ids:
                requirement_source_rows.append(
                    RequirementSource(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        requirement_id=requirement_row.id,
                        source_id=source_id,
                    )
                )
    if requirement_source_rows:
        session.add_all(requirement_source_rows)
        await session.flush()

    criteria = [
        AcceptanceCriterion(
            workspace_id=workspace_id,
            project_id=project_id,
            requirement_id=requirement_row.id,
            ordinal=ordinal,
            statement=criterion,
        )
        for requirement, requirement_row in zip(requirements, requirement_rows, strict=True)
        for ordinal, criterion in enumerate(requirement.acceptance_criteria, start=1)
    ]
    session.add_all(criteria)
    await session.flush()


def _database_session_factory(
    request: Request,
) -> async_sessionmaker[AsyncSession]:
    factory = request.app.state.database_session_factory
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_unavailable",
                "message": "PostgreSQL is not configured for project persistence.",
            },
        )
    return cast(async_sessionmaker[AsyncSession], factory)


async def _local_workspace_id(session: AsyncSession) -> UUID:
    workspace_id = (
        await session.execute(select(Workspace.id).where(Workspace.mode == "local"))
    ).scalar_one_or_none()
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_not_initialized",
                "message": "Run the documented database migrations before using project storage.",
            },
        )
    return workspace_id


@router.post("", response_model=ProjectCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    payload: ProjectCreateRequest,
    request: Request,
) -> ProjectCreatedResponse:
    factory = _database_session_factory(request)
    suffix = uuid4().hex[:12]
    slug_base = re.sub(r"[^a-z0-9]+", "-", payload.name.casefold()).strip("-")
    slug = f"{(slug_base or 'project')[:48]}-{suffix}"
    sources = [
        SourceInput("idea", payload.idea, "idea", "User-provided idea"),
        *(
            SourceInput("user_edit", value, "evidence", label)
            for value, label in (
                (payload.audience, "Intended audience"),
                (payload.platform, "Preferred platform"),
                (payload.constraints, "User constraints"),
                (payload.technology, "Preferred technology"),
            )
            if value
        ),
    ]
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project, revision = await create_project(
            session,
            workspace_id=workspace_id,
            name=payload.name,
            slug=slug,
            revision=RevisionInput(
                language=payload.language,
                profile=payload.profile,
                intake_snapshot={
                    "language": payload.language,
                    "profile": payload.profile,
                },
                schema_version="1.0",
                template_pack_version="1.0",
            ),
            sources=sources,
        )
        return ProjectCreatedResponse(
            project=_project_resource(project),
            revision_id=revision.id,
        )


@router.patch(
    "/{project_id}",
    response_model=ProjectCreatedResponse,
)
async def update_project_endpoint(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    request: Request,
) -> ProjectCreatedResponse:
    factory = _database_session_factory(request)
    intake_labels = {
        "idea": "User-provided idea",
        "audience": "Intended audience",
        "platform": "Preferred platform",
        "constraints": "User constraints",
        "technology": "Preferred technology",
    }
    label_fields = {label: field for field, label in intake_labels.items()}

    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        if project.current_revision != payload.expected_revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "revision_conflict",
                    "message": "Reload the project and apply your changes to the latest revision.",
                },
            )
        current_revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if current_revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )

        current_values = dict.fromkeys(intake_labels, "")
        current_sources: dict[str, tuple[UUID, str, str]] = {}
        source_rows = await session.execute(
            select(
                ProjectSource.id,
                ProjectSource.safe_label,
                ProjectSource.content,
                ProjectRevisionSource.source_role,
            )
            .join(
                ProjectRevisionSource,
                (ProjectRevisionSource.workspace_id == ProjectSource.workspace_id)
                & (ProjectRevisionSource.project_id == ProjectSource.project_id)
                & (ProjectRevisionSource.source_id == ProjectSource.id),
            )
            .where(
                ProjectRevisionSource.workspace_id == workspace_id,
                ProjectRevisionSource.project_id == project_id,
                ProjectRevisionSource.revision_id == current_revision.id,
            )
        )
        for source_id, safe_label, content, source_role in source_rows:
            field_name = label_fields.get(safe_label or "")
            if field_name is not None:
                current_values[field_name] = content
                current_sources[field_name] = (source_id, content, source_role)
        if not current_values["idea"]:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_idea_missing",
                    "message": "The stored project idea is unavailable.",
                },
            )

        update_values = payload.model_dump(
            exclude={"expected_revision", "name", "language", "profile"},
            exclude_unset=True,
        )
        updated_values = {**current_values, **update_values}
        if not updated_values["idea"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "project_idea_required",
                    "message": "A project revision must include an idea.",
                },
            )
        updated_sources: list[SourceInput] = []
        reused_sources: list[tuple[UUID, str]] = []
        for field_name, safe_label in intake_labels.items():
            content = updated_values[field_name]
            if not content:
                continue
            existing_source = current_sources.get(field_name)
            if existing_source is not None and existing_source[1] == content:
                reused_sources.append((existing_source[0], existing_source[2]))
            else:
                updated_sources.append(
                    SourceInput(
                        source_kind="user_edit",
                        content=content,
                        source_role="edit",
                        safe_label=safe_label,
                    )
                )

        language = payload.language if payload.language is not None else current_revision.language
        profile = payload.profile if payload.profile is not None else current_revision.profile
        try:
            revision = await create_project_revision(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                expected_revision=payload.expected_revision,
                revision=RevisionInput(
                    language=language,
                    profile=profile,
                    intake_snapshot={"language": language, "profile": profile},
                    schema_version=current_revision.schema_version,
                    template_pack_version=current_revision.template_pack_version,
                ),
                sources=updated_sources,
                name=payload.name,
            )
        except RevisionConflictError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "revision_conflict",
                    "message": "Reload the project and apply your changes to the latest revision.",
                },
            ) from None
        except ProjectNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            ) from None
        session.add_all(
            ProjectRevisionSource(
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision.id,
                source_id=source_id,
                source_role=source_role,
            )
            for source_id, source_role in reused_sources
        )
        await session.flush()
        return ProjectCreatedResponse(
            project=_project_resource(project),
            revision_id=revision.id,
        )


@router.get("", response_model=ProjectListResponse)
async def list_projects_endpoint(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
) -> ProjectListResponse:
    if cursor is not None and offset:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_pagination",
                "message": "A cursor cannot be combined with a non-zero offset.",
            },
        )
    try:
        decoded_cursor = _decode_project_cursor(cursor) if cursor is not None else None
    except ValueError:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_cursor",
                "message": "The project page cursor is invalid.",
            },
        ) from None

    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        projects, has_more = await list_project_page(
            session,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
            cursor=decoded_cursor,
        )
        return ProjectListResponse(
            items=[_project_resource(project) for project in projects],
            limit=limit,
            offset=offset,
            next_cursor=_encode_project_cursor(projects[-1]) if has_more else None,
        )


@router.post(
    "/{project_id}/clarifications",
    response_model=ClarificationResponse,
)
async def clarify_project_endpoint(
    project_id: UUID,
    payload: ClarificationRequest,
    request: Request,
) -> ClarificationResponse:
    if not payload.consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "provider_consent_required",
                "message": (
                    "Affirmative consent is required before project content is sent "
                    "to Google Gemini."
                ),
            },
        )

    factory = _database_session_factory(request)
    intake: dict[str, str] = {}
    existing_questions: list[ClarificationQuestion] = []
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        existing_questions = list(
            (
                await session.execute(
                    select(ClarificationQuestion)
                    .where(
                        ClarificationQuestion.workspace_id == workspace_id,
                        ClarificationQuestion.project_id == project_id,
                        ClarificationQuestion.revision_id == revision.id,
                    )
                    .order_by(ClarificationQuestion.priority, ClarificationQuestion.id)
                )
            ).scalars()
        )
        consent = (
            (
                await session.execute(
                    select(ProviderConsent)
                    .where(
                        ProviderConsent.workspace_id == workspace_id,
                        ProviderConsent.project_id == project_id,
                        ProviderConsent.revision_id == revision.id,
                        ProviderConsent.disclosure_version == AI_DISCLOSURE_VERSION,
                    )
                    .order_by(ProviderConsent.granted_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if existing_questions and consent is not None:
            latest_answers = await _latest_clarification_answers(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                questions=existing_questions,
            )
            return _clarification_response(
                project_id=project_id,
                revision_id=revision.id,
                consent_id=consent.id,
                questions=existing_questions,
                latest_answers=latest_answers,
            )

        intake = {
            "idea": "",
            "audience": "",
            "platform": "",
            "constraints": "",
            "technology": "",
            "language": revision.language,
            "profile": revision.profile,
        }
        source_rows = await session.execute(
            select(ProjectSource.safe_label, ProjectSource.content)
            .join(
                ProjectRevisionSource,
                (ProjectRevisionSource.workspace_id == ProjectSource.workspace_id)
                & (ProjectRevisionSource.project_id == ProjectSource.project_id)
                & (ProjectRevisionSource.source_id == ProjectSource.id),
            )
            .where(
                ProjectRevisionSource.workspace_id == workspace_id,
                ProjectRevisionSource.project_id == project_id,
                ProjectRevisionSource.revision_id == revision.id,
            )
        )
        source_fields = {
            "User-provided idea": "idea",
            "Intended audience": "audience",
            "Preferred platform": "platform",
            "User constraints": "constraints",
            "Preferred technology": "technology",
        }
        for safe_label, content in source_rows:
            field_name = source_fields.get(safe_label or "")
            if field_name is not None:
                intake[field_name] = content
        if not intake["idea"]:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_idea_missing",
                    "message": "The stored project idea is unavailable.",
                },
            )

    async with factory() as session, session.begin():
        consent = ProviderConsent(
            workspace_id=workspace_id,
            project_id=project_id,
            revision_id=revision.id,
            disclosure_version=AI_DISCLOSURE_VERSION,
        )
        session.add(consent)
        await session.flush()
        consent_id = consent.id

    try:
        # Integrate bounded Information Gain Loop when available
        try:
            discovery = request.app.state.discovery_service
            if hasattr(discovery, "run_clarification_loop"):
                loop_round = await discovery.run_clarification_loop(intake, {})
                # Map loop round questions to ClarificationResult for compatibility
                from app.models import ClarificationResult as _CR, FollowUpQuestion as _FQ

                clarification_result = _CR(
                    questions=[
                        _FQ(question=q.question, impact=q.impact, blocking=q.blocking)
                        for q in loop_round.questions
                    ]
                )
            else:
                clarification_result = await discovery.clarify(intake)
        except Exception:
            clarification_result = await request.app.state.discovery_service.clarify(intake)
    except ProviderConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "provider_not_configured",
                "message": "Configure Google AI Studio Gemini before requesting clarifications.",
            },
        ) from None
    except ProviderError as exc:
        logger.warning("Clarification provider failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "provider_request_failed",
                "message": "Google Gemini could not complete the clarification request.",
            },
        ) from None

    async with factory() as session, session.begin():
        current_project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if current_project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        if current_project.current_revision != revision.revision_number:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "revision_conflict",
                    "message": "The project changed while clarifications were being generated.",
                },
            )
        questions = [
            ClarificationQuestion(
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision.id,
                question=item.question,
                impact=item.impact,
                blocking=item.blocking,
            )
            for item in clarification_result.questions
        ]
        for priority, question in enumerate(questions, start=1):
            question.priority = priority
        session.add_all(questions)
        await session.flush()
        return _clarification_response(
            project_id=project_id,
            revision_id=revision.id,
            consent_id=consent_id,
            questions=questions,
        )


@router.get(
    "/{project_id}/clarifications",
    response_model=ClarificationResponse,
)
async def get_clarifications_endpoint(
    project_id: UUID,
    request: Request,
) -> ClarificationResponse:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        questions = list(
            (
                await session.execute(
                    select(ClarificationQuestion)
                    .where(
                        ClarificationQuestion.workspace_id == workspace_id,
                        ClarificationQuestion.project_id == project_id,
                        ClarificationQuestion.revision_id == revision.id,
                    )
                    .order_by(ClarificationQuestion.priority, ClarificationQuestion.id)
                )
            ).scalars()
        )
        consent = (
            (
                await session.execute(
                    select(ProviderConsent)
                    .where(
                        ProviderConsent.workspace_id == workspace_id,
                        ProviderConsent.project_id == project_id,
                        ProviderConsent.revision_id == revision.id,
                        ProviderConsent.disclosure_version == AI_DISCLOSURE_VERSION,
                    )
                    .order_by(ProviderConsent.granted_at.desc())
                )
            )
            .scalars()
            .first()
        )
        latest_answers = await _latest_clarification_answers(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            questions=questions,
        )
        return _clarification_response(
            project_id=project_id,
            revision_id=revision.id,
            consent_id=consent.id if consent is not None else None,
            questions=questions,
            latest_answers=latest_answers,
        )


@router.put(
    "/{project_id}/clarifications/answers",
    response_model=ClarificationResponse,
)
async def save_clarification_answers_endpoint(
    project_id: UUID,
    payload: ClarificationAnswersRequest,
    request: Request,
) -> ClarificationResponse:
    requested_ids = [answer.question_id for answer in payload.answers]
    if len(set(requested_ids)) != len(requested_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "duplicate_question",
                "message": "Each clarification question may appear only once per submission.",
            },
        )
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        questions = list(
            (
                await session.execute(
                    select(ClarificationQuestion)
                    .where(
                        ClarificationQuestion.workspace_id == workspace_id,
                        ClarificationQuestion.project_id == project_id,
                        ClarificationQuestion.revision_id == revision.id,
                    )
                    .order_by(ClarificationQuestion.priority, ClarificationQuestion.id)
                )
            ).scalars()
        )
        question_map = {question.id: question for question in questions}
        if not set(requested_ids).issubset(question_map):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more clarification questions were not found.",
            )
        consent = (
            (
                await session.execute(
                    select(ProviderConsent)
                    .where(
                        ProviderConsent.workspace_id == workspace_id,
                        ProviderConsent.project_id == project_id,
                        ProviderConsent.revision_id == revision.id,
                        ProviderConsent.disclosure_version == AI_DISCLOSURE_VERSION,
                    )
                    .order_by(ProviderConsent.granted_at.desc())
                )
            )
            .scalars()
            .first()
        )
        source_links: list[ProjectRevisionSource] = []
        answer_records: list[ClarificationAnswer] = []
        for answer_input in payload.answers:
            question = question_map[answer_input.question_id]
            source_id: UUID | None = None
            if answer_input.answer_state == "answered":
                source_id = uuid4()
                session.add(
                    ProjectSource(
                        id=source_id,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        source_kind="answer",
                        content=answer_input.answer or "",
                        safe_label="Clarification answer",
                    )
                )
                source_links.append(
                    ProjectRevisionSource(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        revision_id=revision.id,
                        source_id=source_id,
                        source_role="answer",
                    )
                )
            answer_records.append(
                ClarificationAnswer(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    question_id=question.id,
                    source_id=source_id,
                    answer_state=answer_input.answer_state,
                )
            )
            question.status = answer_input.answer_state
        await session.flush()
        session.add_all(source_links)
        await session.flush()
        session.add_all(answer_records)
        await session.flush()
        latest_answers = await _latest_clarification_answers(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            questions=questions,
        )
        return _clarification_response(
            project_id=project_id,
            revision_id=revision.id,
            consent_id=consent.id if consent is not None else None,
            questions=questions,
            latest_answers=latest_answers,
        )


@router.post(
    "/{project_id}/generate",
    response_model=GenerateProjectResponse,
)
async def generate_project_endpoint(
    project_id: UUID,
    payload: GenerateProjectRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
) -> GenerateProjectResponse:
    if not payload.consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "provider_consent_required",
                "message": (
                    "Affirmative consent is required before project content is sent "
                    "to Google Gemini."
                ),
            },
        )

    factory = _database_session_factory(request)
    intake: dict[str, str] = {}
    answers: dict[str, str] = {}
    answer_payload: list[dict[str, str]] = []
    source_records: list[tuple[UUID, str | None, str]] = []
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        questions = list(
            (
                await session.execute(
                    select(ClarificationQuestion)
                    .where(
                        ClarificationQuestion.workspace_id == workspace_id,
                        ClarificationQuestion.project_id == project_id,
                        ClarificationQuestion.revision_id == revision.id,
                    )
                    .order_by(ClarificationQuestion.priority, ClarificationQuestion.id)
                )
            ).scalars()
        )
        latest_answers = await _latest_clarification_answers(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            questions=questions,
        )
        unanswered = [question for question in questions if question.id not in latest_answers]
        if unanswered:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "clarification_answers_required",
                    "message": "Answer or mark each clarification question as unknown first.",
                },
            )
        intake = {
            "idea": "",
            "audience": "",
            "platform": "",
            "constraints": "",
            "technology": "",
            "language": revision.language,
            "profile": revision.profile,
        }
        source_rows = await session.execute(
            select(ProjectSource.id, ProjectSource.safe_label, ProjectSource.content)
            .join(
                ProjectRevisionSource,
                (ProjectRevisionSource.workspace_id == ProjectSource.workspace_id)
                & (ProjectRevisionSource.project_id == ProjectSource.project_id)
                & (ProjectRevisionSource.source_id == ProjectSource.id),
            )
            .where(
                ProjectRevisionSource.workspace_id == workspace_id,
                ProjectRevisionSource.project_id == project_id,
                ProjectRevisionSource.revision_id == revision.id,
            )
        )
        source_fields = {
            "User-provided idea": "idea",
            "Intended audience": "audience",
            "Preferred platform": "platform",
            "User constraints": "constraints",
            "Preferred technology": "technology",
        }
        for source_id, safe_label, content in source_rows:
            source_records.append((source_id, safe_label, content))
            field_name = source_fields.get(safe_label or "")
            if field_name is not None:
                intake[field_name] = content
        if not intake["idea"]:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_idea_missing",
                    "message": "The stored project idea is unavailable.",
                },
            )
        for question in questions:
            answer_state, answer_text = latest_answers[question.id]
            answers[question.question] = (
                answer_text if answer_state == "answered" and answer_text else "Not decided yet."
            )
            answer_payload.append(
                {
                    "question_id": str(question.id),
                    "answer_state": answer_state,
                    "answer": answer_text or "",
                }
            )
        revision_id = revision.id
        request_hash = canonical_request_hash(
            {"revision_id": str(revision_id), "answers": answer_payload}
        )

    run_id: UUID
    replay_response: GenerateProjectResponse | None = None
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        consent = ProviderConsent(
            workspace_id=workspace_id,
            project_id=project_id,
            revision_id=revision_id,
            disclosure_version=AI_DISCLOSURE_VERSION,
        )
        session.add(consent)
        await session.flush()
        try:
            run, created = await create_or_get_run(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                prompt_version="gemini-prompts-v1",
                template_pack_version="1.0",
                consent_id=consent.id,
            )
        except IdempotencyConflictError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "idempotency_conflict",
                    "message": "This idempotency key was already used for a different request.",
                },
            ) from None
        run_id = run.id
        if not created:
            await session.delete(consent)
            await session.flush()
            if run.status not in ("awaiting_user", "completed"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "run_in_progress",
                        "message": "This generation request is already in progress or failed.",
                    },
                )
            existing_documents = list(
                (
                    await session.execute(
                        select(ProjectDocument)
                        .where(
                            ProjectDocument.workspace_id == workspace_id,
                            ProjectDocument.project_id == project_id,
                            ProjectDocument.revision_id == revision_id,
                            ProjectDocument.run_id == run.id,
                        )
                        .order_by(ProjectDocument.path)
                    )
                ).scalars()
            )
            replay_response = GenerateProjectResponse(
                project_id=project_id,
                revision_id=revision_id,
                run_id=run.id,
                status=run.status,
                documents=[
                    ProjectDocumentSummary(
                        id=document.id,
                        path=document.path,
                        document_kind=document.document_kind,
                        sha256=document.sha256,
                    )
                    for document in existing_documents
                ],
            )
        else:
            existing_document_count = await session.scalar(
                select(func.count())
                .select_from(ProjectDocument)
                .where(
                    ProjectDocument.workspace_id == workspace_id,
                    ProjectDocument.project_id == project_id,
                    ProjectDocument.revision_id == revision_id,
                )
            )
            if existing_document_count:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "revision_already_generated",
                        "message": "Create a new project revision before generating another package.",
                    },
                )
            now = datetime.now(timezone.utc)
            run.status = "running"
            run.attempt_count += 1
            run.started_at = now
            session.add_all(
                [
                    RunEvent(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        run_id=run.id,
                        sequence=1,
                        event_type="workflow.queued",
                        payload={},
                    ),
                    RunEvent(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        run_id=run.id,
                        sequence=2,
                        event_type="workflow.started",
                        payload={"attempt": run.attempt_count},
                    ),
                ]
            )
    if replay_response is not None:
        return replay_response

    try:
        generated_package = await request.app.state.generation_service.generate_package(
            intake,
            answers,
        )
    except ProviderConfigurationError:
        await _mark_generation_failed(
            factory, workspace_id, project_id, run_id, "provider_not_configured"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "provider_not_configured",
                "message": "Configure Google AI Studio Gemini before generating project documents.",
            },
        ) from None
    except ProviderError as exc:
        logger.warning("Project generation provider failed: %s", type(exc).__name__)
        await _mark_generation_failed(
            factory, workspace_id, project_id, run_id, "provider_request_failed"
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "provider_request_failed",
                "message": "Google Gemini could not complete project document generation.",
            },
        ) from None
    except PackageValidationError:
        await _mark_generation_failed(
            factory, workspace_id, project_id, run_id, "package_validation_failed"
        )
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={
                "code": "package_validation_failed",
                "message": "Generated documents did not pass package validation.",
            },
        ) from None
    except (ValueError, TypeError, KeyError, OSError):
        await _mark_generation_failed(
            factory, workspace_id, project_id, run_id, "generation_failed"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "generation_failed",
                "message": "Project document generation failed. No package was published.",
            },
        ) from None

    try:
        requirement_drafts = parse_requirements(generated_package.documents.requirements)
        if not requirement_drafts:
            raise ValueError("No stable requirement identifiers were generated.")
    except ValueError:
        await _mark_generation_failed(
            factory, workspace_id, project_id, run_id, "requirements_structure_invalid"
        )
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={
                "code": "requirements_structure_invalid",
                "message": (
                    "Generated requirements must include unique REQ-* identifiers "
                    "and at least one requirement."
                ),
            },
        ) from None

    document_summaries: list[ProjectDocumentSummary] = []
    try:
        async with factory() as session, session.begin():
            run = (
                await session.execute(
                    select(AgentRun).where(
                        AgentRun.workspace_id == workspace_id,
                        AgentRun.project_id == project_id,
                        AgentRun.id == run_id,
                    )
                )
            ).scalar_one()
            await _persist_normalized_generation(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision_id,
                generated=generated_package.documents,
                requirements=requirement_drafts,
                source_records=source_records,
            )
            document_revisions = dict(
                (
                    await session.execute(
                        select(
                            ProjectDocument.path,
                            func.max(ProjectDocument.document_revision),
                        )
                        .where(
                            ProjectDocument.workspace_id == workspace_id,
                            ProjectDocument.project_id == project_id,
                        )
                        .group_by(ProjectDocument.path)
                    )
                ).all()
            )
            for path, content in sorted(generated_package.files.items()):
                text_content = content.decode("utf-8")
                digest = hashlib.sha256(content).hexdigest()
                document_kind = path.rsplit("/", maxsplit=1)[-1].rsplit(".", maxsplit=1)[0][:64]
                document = ProjectDocument(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    project_id=project_id,
                    revision_id=revision_id,
                    run_id=run_id,
                    path=path,
                    document_kind=document_kind,
                    document_revision=document_revisions.get(path, 0) + 1,
                    content_format="json" if path.endswith(".json") else "markdown",
                    content=text_content,
                    sha256=digest,
                )
                session.add(document)
                document_summaries.append(
                    ProjectDocumentSummary(
                        id=document.id,
                        path=path,
                        document_kind=document_kind,
                        sha256=digest,
                    )
                )
            await session.flush()
            run.status = "awaiting_user"
            session.add(
                RunEvent(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    run_id=run_id,
                    sequence=3,
                    event_type="documents.ready_for_review",
                    payload={"document_count": len(document_summaries)},
                )
            )
            return GenerateProjectResponse(
                project_id=project_id,
                revision_id=revision_id,
                run_id=run_id,
                status=run.status,
                documents=document_summaries,
            )
    except SQLAlchemyError:
        try:
            await _mark_generation_failed(
                factory,
                workspace_id,
                project_id,
                run_id,
                "document_persistence_failed",
            )
        except SQLAlchemyError:
            logger.error("Could not record failed generation after a database error.")
        raise


async def _mark_generation_failed(
    factory: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    project_id: UUID,
    run_id: UUID,
    error_code: str,
) -> None:
    async with factory() as session, session.begin():
        run = (
            await session.execute(
                select(AgentRun)
                .where(
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.project_id == project_id,
                    AgentRun.id == run_id,
                )
                .with_for_update()
            )
        ).scalar_one()
        run.status = "failed"
        run.safe_error_code = error_code
        run.retryable = True
        run.completed_at = datetime.now(timezone.utc)
        session.add(
            RunEvent(
                workspace_id=workspace_id,
                project_id=project_id,
                run_id=run_id,
                sequence=3,
                event_type="workflow.failed",
                payload={"error_code": error_code},
            )
        )


@router.get(
    "/{project_id}/documents",
    response_model=list[ProjectDocumentSummary],
)
async def list_project_documents_endpoint(
    project_id: UUID,
    request: Request,
) -> list[ProjectDocumentSummary]:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision_id = (
            await session.execute(
                select(ProjectRevision.id).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision_id is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        documents = (
            await session.execute(
                select(ProjectDocument)
                .where(
                    ProjectDocument.workspace_id == workspace_id,
                    ProjectDocument.project_id == project_id,
                    ProjectDocument.revision_id == revision_id,
                )
                .order_by(ProjectDocument.path)
            )
        ).scalars()
        return [
            ProjectDocumentSummary(
                id=document.id,
                path=document.path,
                document_kind=document.document_kind,
                sha256=document.sha256,
            )
            for document in documents
        ]


@router.get(
    "/{project_id}/documents/{document_id}",
)
async def get_project_document_endpoint(
    project_id: UUID,
    document_id: UUID,
    request: Request,
) -> dict[str, str]:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        document = (
            await session.execute(
                select(ProjectDocument).where(
                    ProjectDocument.workspace_id == workspace_id,
                    ProjectDocument.project_id == project_id,
                    ProjectDocument.id == document_id,
                )
            )
        ).scalar_one_or_none()
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project document not found.",
            )
        return {
            "id": str(document.id),
            "path": document.path,
            "content_format": document.content_format,
            "content": document.content,
            "sha256": document.sha256,
        }


@router.post(
    "/{project_id}/validate",
    response_model=ValidationResponse,
)
async def validate_project_documents_endpoint(
    project_id: UUID,
    payload: ReviewAndValidateRequest,
    request: Request,
) -> ValidationResponse:
    if not payload.approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "review_approval_required",
                "message": "Review and explicitly approve the complete document set before validation.",
            },
        )
    if len(set(payload.document_ids)) != len(payload.document_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "duplicate_document",
                "message": "Each document may be approved only once.",
            },
        )
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        documents = list(
            (
                await session.execute(
                    select(ProjectDocument)
                    .where(
                        ProjectDocument.workspace_id == workspace_id,
                        ProjectDocument.project_id == project_id,
                        ProjectDocument.revision_id == revision.id,
                    )
                    .order_by(ProjectDocument.path)
                )
            ).scalars()
        )
        if not documents or set(payload.document_ids) != {document.id for document in documents}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "complete_document_review_required",
                    "message": "Review and approve every current document before validation.",
                },
            )
        run = (
            (
                await session.execute(
                    select(AgentRun)
                    .where(
                        AgentRun.workspace_id == workspace_id,
                        AgentRun.project_id == project_id,
                        AgentRun.revision_id == revision.id,
                        AgentRun.status == "awaiting_user",
                    )
                    .order_by(AgentRun.created_at.desc(), AgentRun.id)
                )
            )
            .scalars()
            .first()
        )
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "generation_not_reviewable",
                    "message": "No generated run is awaiting review for this revision.",
                },
            )
        files = {document.path: document.content.encode("utf-8") for document in documents}
        hash_errors = [
            document
            for document in documents
            if hashlib.sha256(files[document.path]).hexdigest() != document.sha256
        ]
        errors = (
            ["Stored document integrity check failed."]
            if hash_errors
            else request.app.state.generation_service.validate_package_files(
                files, revision.profile
            )
        )
        report_id = uuid4()
        report_status = "failed" if errors else "passed"
        report = ValidationReport(
            id=report_id,
            workspace_id=workspace_id,
            project_id=project_id,
            revision_id=revision.id,
            run_id=run.id,
            validator_version="package-validator-v1",
            status=report_status,
            checked_documents=[
                {"id": str(document.id), "sha256": document.sha256} for document in documents
            ],
        )
        session.add(report)
        await session.flush()
        if errors:
            session.add(
                ValidationFinding(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    revision_id=revision.id,
                    report_id=report.id,
                    rule_code="package_validation",
                    severity="high",
                    safe_detail="One or more package integrity checks failed.",
                )
            )
        max_sequence = await session.scalar(
            select(func.max(RunEvent.sequence)).where(
                RunEvent.workspace_id == workspace_id,
                RunEvent.project_id == project_id,
                RunEvent.run_id == run.id,
            )
        )
        session.add_all(
            [
                AuditEvent(
                    workspace_id=workspace_id,
                    actor="local_user",
                    action_code="documents.reviewed",
                    subject_type="run",
                    subject_id=run.id,
                    safe_metadata={
                        "document_count": len(documents),
                        "validation_status": report_status,
                    },
                ),
                RunEvent(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    run_id=run.id,
                    sequence=(max_sequence or 0) + 1,
                    event_type="documents.reviewed",
                    payload={
                        "document_count": len(documents),
                        "validation_status": report_status,
                    },
                ),
            ]
        )
        await session.flush()
        return ValidationResponse(
            id=report.id,
            status=report.status,
            checked_document_count=len(documents),
            finding_count=1 if errors else 0,
        )


@router.post(
    "/{project_id}/exports",
    response_model=ExportResponse,
)
async def create_project_export_endpoint(
    project_id: UUID,
    payload: ExportCreateRequest,
    request: Request,
) -> ExportResponse:
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "export_confirmation_required",
                "message": "Explicitly confirm creation of the validated project ZIP.",
            },
        )
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        report = (
            await session.execute(
                select(ValidationReport).where(
                    ValidationReport.workspace_id == workspace_id,
                    ValidationReport.project_id == project_id,
                    ValidationReport.id == payload.validation_report_id,
                )
            )
        ).scalar_one_or_none()
        if revision is None or report is None or report.revision_id != revision.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validation report not found for the current project revision.",
            )
        if report.status != "passed" or report.run_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "successful_validation_required",
                    "message": "Only a passed validation report can authorize an export.",
                },
            )
        prior_export = (
            await session.execute(
                select(Export).where(
                    Export.workspace_id == workspace_id,
                    Export.project_id == project_id,
                    Export.revision_id == revision.id,
                    Export.validation_report_id == report.id,
                    Export.status == "ready",
                )
            )
        ).scalar_one_or_none()
        if prior_export is not None:
            return ExportResponse(
                id=prior_export.id,
                status=prior_export.status,
                zip_sha256=prior_export.zip_sha256,
                download_path=f"/api/v1/projects/{project_id}/exports/{prior_export.id}",
            )
        run = (
            await session.execute(
                select(AgentRun)
                .where(
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.project_id == project_id,
                    AgentRun.id == report.run_id,
                    AgentRun.status == "awaiting_user",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "generation_not_exportable",
                    "message": "The generated run is not awaiting validated export.",
                },
            )
        documents = list(
            (
                await session.execute(
                    select(ProjectDocument)
                    .where(
                        ProjectDocument.workspace_id == workspace_id,
                        ProjectDocument.project_id == project_id,
                        ProjectDocument.revision_id == revision.id,
                    )
                    .order_by(ProjectDocument.path)
                )
            ).scalars()
        )
        checked = {
            entry["id"]: entry["sha256"]
            for entry in report.checked_documents
            if "id" in entry and "sha256" in entry
        }
        if len(checked) != len(documents) or any(
            checked.get(str(document.id)) != document.sha256 for document in documents
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "validation_is_stale",
                    "message": "The current documents do not match the validated document set.",
                },
            )
        files = {document.path: document.content.encode("utf-8") for document in documents}
        archive_errors = request.app.state.generation_service.validate_package_files(
            files,
            revision.profile,
        )
        if archive_errors:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "package_validation_failed",
                    "message": "The stored documents no longer pass package validation.",
                },
            )
        try:
            package_manifest = json.loads(files["manifest.json"])
        except (KeyError, json.JSONDecodeError):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "package_manifest_invalid",
                    "message": "The package manifest is missing or invalid.",
                },
            ) from None
        archive_slug = package_manifest.get("project_slug")
        if not isinstance(archive_slug, str):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "package_manifest_invalid",
                    "message": "The package manifest does not contain a valid project slug.",
                },
            )
        try:
            archive = build_verified_archive(archive_slug, files)
        except PackageValidationError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "archive_verification_failed",
                    "message": "The project ZIP could not be verified and was not exported.",
                },
            ) from None
        export_id = uuid4()
        zip_digest = hashlib.sha256(archive).hexdigest()
        export = Export(
            id=export_id,
            workspace_id=workspace_id,
            project_id=project_id,
            revision_id=revision.id,
            validation_report_id=report.id,
            manifest={
                "format_version": "1.0",
                "project_slug": archive_slug,
                "documents": [
                    {
                        "id": str(document.id),
                        "path": document.path,
                        "sha256": document.sha256,
                    }
                    for document in documents
                ],
            },
            zip_sha256=zip_digest,
        )
        session.add(export)
        await session.flush()
        session.add_all(
            [
                ExportDocument(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    revision_id=revision.id,
                    export_id=export.id,
                    document_id=document.id,
                )
                for document in documents
            ]
        )
        max_sequence = await session.scalar(
            select(func.max(RunEvent.sequence)).where(
                RunEvent.workspace_id == workspace_id,
                RunEvent.project_id == project_id,
                RunEvent.run_id == run.id,
            )
        )
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        session.add_all(
            [
                RunEvent(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    run_id=run.id,
                    sequence=(max_sequence or 0) + 1,
                    event_type="export.ready",
                    payload={"export_id": str(export.id)},
                ),
                AuditEvent(
                    workspace_id=workspace_id,
                    actor="local_user",
                    action_code="export.created",
                    subject_type="export",
                    subject_id=export.id,
                    safe_metadata={"document_count": len(documents)},
                ),
            ]
        )
        await session.flush()
        return ExportResponse(
            id=export.id,
            status=export.status,
            zip_sha256=export.zip_sha256,
            download_path=f"/api/v1/projects/{project_id}/exports/{export.id}",
        )


@router.get(
    "/{project_id}/exports/{export_id}",
)
async def download_project_export_endpoint(
    project_id: UUID,
    export_id: UUID,
    request: Request,
) -> Response:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        result = await session.execute(
            select(Export, ProjectRevision.profile)
            .join(
                ProjectRevision,
                (ProjectRevision.workspace_id == Export.workspace_id)
                & (ProjectRevision.project_id == Export.project_id)
                & (ProjectRevision.id == Export.revision_id),
            )
            .where(
                Export.workspace_id == workspace_id,
                Export.project_id == project_id,
                Export.id == export_id,
                Export.status == "ready",
            )
        )
        export_row = result.one_or_none()
        if export_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found.")
        export, profile = export_row
        project_slug = export.manifest.get("project_slug")
        if not isinstance(project_slug, str):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "export_integrity_failed",
                    "message": "The stored export metadata is incomplete.",
                },
            )
        linked_documents = (
            (
                await session.execute(
                    select(ProjectDocument)
                    .join(
                        ExportDocument,
                        (ExportDocument.workspace_id == ProjectDocument.workspace_id)
                        & (ExportDocument.project_id == ProjectDocument.project_id)
                        & (ExportDocument.revision_id == ProjectDocument.revision_id)
                        & (ExportDocument.document_id == ProjectDocument.id),
                    )
                    .where(
                        ExportDocument.workspace_id == workspace_id,
                        ExportDocument.project_id == project_id,
                        ExportDocument.revision_id == export.revision_id,
                        ExportDocument.export_id == export.id,
                    )
                    .order_by(ProjectDocument.path)
                )
            )
            .scalars()
            .all()
        )
        manifest_documents = export.manifest.get("documents", [])
        if len(linked_documents) != len(manifest_documents):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "export_integrity_failed",
                    "message": "The stored export metadata is incomplete.",
                },
            )
        manifest_by_id = {
            item.get("id"): item
            for item in manifest_documents
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        files: dict[str, bytes] = {}
        for document in linked_documents:
            expected = manifest_by_id.get(str(document.id))
            content = document.content.encode("utf-8")
            if (
                expected is None
                or expected.get("path") != document.path
                or expected.get("sha256") != document.sha256
                or hashlib.sha256(content).hexdigest() != document.sha256
            ):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "export_integrity_failed",
                        "message": "The stored export failed its document integrity check.",
                    },
                )
            files[document.path] = content
        validation_errors = request.app.state.generation_service.validate_package_files(
            files,
            profile,
        )
        if validation_errors:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "export_integrity_failed",
                    "message": "The stored export no longer passes package validation.",
                },
            )
        try:
            archive = build_verified_archive(project_slug, files)
        except PackageValidationError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "export_integrity_failed",
                    "message": "The stored export ZIP could not be reconstructed safely.",
                },
            ) from None
        if hashlib.sha256(archive).hexdigest() != export.zip_sha256:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "export_integrity_failed",
                    "message": "The reconstructed ZIP does not match the verified export hash.",
                },
            )
        return Response(
            content=archive,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_slug}.zip"'},
        )


@router.get("/{project_id}", response_model=ProjectCreatedResponse)
async def get_project_endpoint(project_id: UUID, request: Request) -> ProjectCreatedResponse:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision.id).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        return ProjectCreatedResponse(
            project=_project_resource(project),
            revision_id=revision,
        )


@router.get("/{project_id}/workflow", response_model=ProjectWorkflowSnapshot)
async def get_project_workflow_endpoint(
    project_id: UUID,
    request: Request,
) -> ProjectWorkflowSnapshot:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )

        questions = list(
            (
                await session.execute(
                    select(ClarificationQuestion)
                    .where(
                        ClarificationQuestion.workspace_id == workspace_id,
                        ClarificationQuestion.project_id == project_id,
                        ClarificationQuestion.revision_id == revision.id,
                    )
                    .order_by(ClarificationQuestion.created_at, ClarificationQuestion.id)
                )
            ).scalars()
        )
        consent = (
            await session.execute(
                select(ProviderConsent)
                .where(
                    ProviderConsent.workspace_id == workspace_id,
                    ProviderConsent.project_id == project_id,
                    ProviderConsent.revision_id == revision.id,
                    ProviderConsent.disclosure_version == AI_DISCLOSURE_VERSION,
                )
                .order_by(ProviderConsent.granted_at.desc(), ProviderConsent.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_answers = await _latest_clarification_answers(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            questions=questions,
        )
        documents = list(
            (
                await session.execute(
                    select(ProjectDocument)
                    .where(
                        ProjectDocument.workspace_id == workspace_id,
                        ProjectDocument.project_id == project_id,
                        ProjectDocument.revision_id == revision.id,
                    )
                    .order_by(ProjectDocument.path)
                )
            ).scalars()
        )
        validation = (
            await session.execute(
                select(ValidationReport)
                .where(
                    ValidationReport.workspace_id == workspace_id,
                    ValidationReport.project_id == project_id,
                    ValidationReport.revision_id == revision.id,
                )
                .order_by(ValidationReport.created_at.desc(), ValidationReport.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        finding_count = (
            await session.scalar(
                select(func.count(ValidationFinding.id)).where(
                    ValidationFinding.workspace_id == workspace_id,
                    ValidationFinding.project_id == project_id,
                    ValidationFinding.revision_id == revision.id,
                    ValidationFinding.report_id == validation.id,
                )
            )
            if validation is not None
            else 0
        )
        exports = (
            await session.execute(
                select(Export)
                .where(
                    Export.workspace_id == workspace_id,
                    Export.project_id == project_id,
                    Export.revision_id == revision.id,
                )
                .order_by(Export.created_at.desc(), Export.id.desc())
                .limit(50)
            )
        ).scalars()
        return ProjectWorkflowSnapshot(
            project_id=project_id,
            revision_id=revision.id,
            clarification=_clarification_response(
                project_id=project_id,
                revision_id=revision.id,
                consent_id=consent.id if consent is not None else None,
                questions=questions,
                latest_answers=latest_answers,
            ),
            documents=[
                ProjectDocumentSummary(
                    id=document.id,
                    path=document.path,
                    document_kind=document.document_kind,
                    sha256=document.sha256,
                )
                for document in documents
            ],
            validation=(
                ValidationResponse(
                    id=validation.id,
                    status=validation.status,
                    checked_document_count=len(validation.checked_documents),
                    finding_count=finding_count or 0,
                )
                if validation is not None
                else None
            ),
            exports=[
                ExportResponse(
                    id=export.id,
                    status=export.status,
                    zip_sha256=export.zip_sha256,
                    download_path=f"/api/v1/projects/{project_id}/exports/{export.id}",
                )
                for export in exports
            ],
        )


@router.get("/{project_id}/decisions", response_model=DecisionListResponse)
async def list_decisions_endpoint(project_id: UUID, request: Request) -> DecisionListResponse:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        rows = (
            await session.execute(
                select(Decision)
                .where(
                    Decision.workspace_id == workspace_id,
                    Decision.project_id == project_id,
                    Decision.revision_id == revision.id,
                )
                .order_by(Decision.id)
            )
        ).scalars()
        return DecisionListResponse(
            decisions=[
                DecisionResource(
                    id=decision.id,
                    statement=decision.statement,
                    rationale=decision.rationale,
                    status=decision.status,
                    decided_by=decision.decided_by,
                    decided_at=decision.decided_at,
                )
                for decision in rows
            ]
        )


@router.post("/{project_id}/decisions/{decision_id}/accept", response_model=DecisionResource)
async def accept_decision_endpoint(
    project_id: UUID, decision_id: UUID, request: Request, body: DecisionApprovalRequest
) -> DecisionResource:
    if not body.approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "decision_approval_required",
                "message": "Explicit approval is required to accept a decision.",
            },
        )
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision.id).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        try:
            decision = await set_decision_status(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision,
                decision_id=decision_id,
                status="accepted",
                actor="local_user",
                reason=body.reason,
            )
        except RepositoryInputError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "decision_state_conflict", "message": str(exc)},
            ) from exc
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return DecisionResource(
            id=decision.id,
            statement=decision.statement,
            rationale=decision.rationale,
            status=decision.status,
            decided_by=decision.decided_by,
            decided_at=decision.decided_at,
        )


@router.post("/{project_id}/decisions/{decision_id}/reject", response_model=DecisionResource)
async def reject_decision_endpoint(
    project_id: UUID, decision_id: UUID, request: Request, body: DecisionApprovalRequest
) -> DecisionResource:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        project = await get_project(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        revision = (
            await session.execute(
                select(ProjectRevision.id).where(
                    ProjectRevision.workspace_id == workspace_id,
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.revision_number == project.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "project_revision_missing",
                    "message": "The stored project revision is unavailable.",
                },
            )
        try:
            decision = await set_decision_status(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision,
                decision_id=decision_id,
                status="rejected",
                actor="local_user",
                reason=body.reason,
            )
        except RepositoryInputError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "decision_state_conflict", "message": str(exc)},
            ) from exc
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return DecisionResource(
            id=decision.id,
            statement=decision.statement,
            rationale=decision.rationale,
            status=decision.status,
            decided_by=decision.decided_by,
            decided_at=decision.decided_at,
        )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(project_id: UUID, request: Request) -> Response:
    factory = _database_session_factory(request)
    async with factory() as session, session.begin():
        workspace_id = await _local_workspace_id(session)
        deleted = await delete_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
