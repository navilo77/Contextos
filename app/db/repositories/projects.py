from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditEvent,
    Project,
    ProjectRevision,
    ProjectRevisionSource,
    ProjectSource,
)
from app.db.repositories.errors import (
    ProjectNotFoundError,
    RepositoryInputError,
    RevisionConflictError,
)
from app.db.repositories.inputs import RevisionInput, SourceInput
from app.db.repositories.transactions import require_explicit_transaction

_MAX_PAGE_SIZE = 100


def _validate_sources(sources: Sequence[SourceInput]) -> None:
    allowed_sources = {"idea", "answer", "user_edit"}
    allowed_roles = {"idea", "answer", "edit", "evidence"}
    for source in sources:
        if source.source_kind not in allowed_sources or source.source_role not in allowed_roles:
            raise RepositoryInputError("Source kind or revision role is not supported.")
        if not source.content or len(source.content) > 20_000:
            raise RepositoryInputError(
                "Source content must contain between 1 and 20000 characters."
            )


async def _add_revision_sources(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    sources: Sequence[SourceInput],
) -> None:
    links: list[ProjectRevisionSource] = []
    for source in sources:
        source_id = uuid4()
        session.add(
            ProjectSource(
                id=source_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source_kind=source.source_kind,
                content=source.content,
                safe_label=source.safe_label,
            )
        )
        links.append(
            ProjectRevisionSource(
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision_id,
                source_id=source_id,
                source_role=source.source_role,
            )
        )
    await session.flush()
    if links:
        session.add_all(links)


async def create_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    name: str,
    slug: str,
    revision: RevisionInput,
    sources: Sequence[SourceInput] = (),
) -> tuple[Project, ProjectRevision]:
    require_explicit_transaction(session)
    _validate_sources(sources)
    project = Project(
        workspace_id=workspace_id,
        name=name,
        slug=slug,
        current_revision=1,
    )
    session.add(project)
    await session.flush()

    project_revision = ProjectRevision(
        workspace_id=workspace_id,
        project_id=project.id,
        revision_number=1,
        language=revision.language,
        profile=revision.profile,
        intake_snapshot=revision.intake_snapshot,
        schema_version=revision.schema_version,
        template_pack_version=revision.template_pack_version,
    )
    session.add(project_revision)
    await session.flush()
    await _add_revision_sources(
        session,
        workspace_id=workspace_id,
        project_id=project.id,
        revision_id=project_revision.id,
        sources=sources,
    )
    await session.flush()
    return project, project_revision


async def get_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
) -> Project | None:
    require_explicit_transaction(session)
    result = await session.execute(
        select(Project).where(
            Project.workspace_id == workspace_id,
            Project.id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def list_projects(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Project, ...]:
    require_explicit_transaction(session)
    if not 1 <= limit <= _MAX_PAGE_SIZE or offset < 0:
        raise RepositoryInputError(
            f"Limit must be 1..{_MAX_PAGE_SIZE}; offset must be non-negative."
        )
    result = await session.execute(
        select(Project)
        .where(Project.workspace_id == workspace_id)
        .order_by(Project.updated_at.desc(), Project.id)
        .limit(limit)
        .offset(offset)
    )
    return tuple(result.scalars().all())


async def list_project_page(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int = 0,
    cursor: tuple[datetime, UUID] | None = None,
) -> tuple[tuple[Project, ...], bool]:
    require_explicit_transaction(session)
    if not 1 <= limit <= _MAX_PAGE_SIZE or offset < 0:
        raise RepositoryInputError(
            f"Limit must be 1..{_MAX_PAGE_SIZE}; offset must be non-negative."
        )
    if cursor is not None and offset:
        raise RepositoryInputError("Cursor pagination cannot be combined with a non-zero offset.")

    statement = select(Project).where(Project.workspace_id == workspace_id)
    if cursor is not None:
        updated_at, project_id = cursor
        statement = statement.where(
            or_(
                Project.updated_at < updated_at,
                and_(Project.updated_at == updated_at, Project.id > project_id),
            )
        )
    elif offset:
        statement = statement.offset(offset)
    result = await session.execute(
        statement.order_by(Project.updated_at.desc(), Project.id).limit(limit + 1)
    )
    rows = tuple(result.scalars().all())
    return rows[:limit], len(rows) > limit


async def get_project_revision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
) -> ProjectRevision | None:
    require_explicit_transaction(session)
    result = await session.execute(
        select(ProjectRevision).where(
            ProjectRevision.workspace_id == workspace_id,
            ProjectRevision.project_id == project_id,
            ProjectRevision.id == revision_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
) -> bool:
    require_explicit_transaction(session)
    result = await session.execute(
        select(Project)
        .where(
            Project.workspace_id == workspace_id,
            Project.id == project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    project = result.scalar_one_or_none()
    if project is None:
        return False

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor="local_user",
            action_code="project.deleted",
            subject_type="project",
            subject_id=project_id,
            safe_metadata={},
        )
    )
    await session.delete(project)
    await session.flush()
    return True


async def create_project_revision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    expected_revision: int,
    revision: RevisionInput,
    sources: Sequence[SourceInput] = (),
    name: str | None = None,
) -> ProjectRevision:
    require_explicit_transaction(session)
    _validate_sources(sources)
    result = await session.execute(
        select(Project)
        .where(
            Project.workspace_id == workspace_id,
            Project.id == project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise ProjectNotFoundError("Project not found in the requested workspace.")
    if project.current_revision != expected_revision:
        raise RevisionConflictError(expected_revision, project.current_revision)

    if name is not None:
        project.name = name
    next_revision_number = project.current_revision + 1
    project_revision = ProjectRevision(
        workspace_id=workspace_id,
        project_id=project_id,
        revision_number=next_revision_number,
        language=revision.language,
        profile=revision.profile,
        intake_snapshot=revision.intake_snapshot,
        schema_version=revision.schema_version,
        template_pack_version=revision.template_pack_version,
    )
    session.add(project_revision)
    await session.flush()
    await _add_revision_sources(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=project_revision.id,
        sources=sources,
    )
    project.current_revision = next_revision_number
    await session.flush()
    return project_revision
