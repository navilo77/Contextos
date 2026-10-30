from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, Project, ProjectRevision
from app.db.repositories.errors import (
    IdempotencyConflictError,
    ProjectNotFoundError,
    RepositoryInputError,
    RevisionConflictError,
)
from app.db.repositories.transactions import require_explicit_transaction

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CANONICAL_REQUEST_BYTES = 1_000_000


def canonical_request_hash(payload: Mapping[str, Any]) -> str:
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RepositoryInputError("Idempotency payload must be finite JSON data.") from exc
    if not canonical or len(canonical) > _MAX_CANONICAL_REQUEST_BYTES:
        raise RepositoryInputError(
            f"Canonical idempotency payload exceeds {_MAX_CANONICAL_REQUEST_BYTES} bytes."
        )
    return hashlib.sha256(canonical).hexdigest()


def _validate_idempotency_inputs(idempotency_key: str, request_hash: str) -> None:
    if not idempotency_key or len(idempotency_key) > 128:
        raise RepositoryInputError("Idempotency key must contain between 1 and 128 characters.")
    if not _SHA256_PATTERN.fullmatch(request_hash):
        raise RepositoryInputError("Request hash must be a lowercase SHA-256 digest.")


async def _find_idempotent_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    idempotency_key: str,
    request_hash: str,
) -> AgentRun | None:
    result = await session.execute(
        select(AgentRun).where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.project_id == project_id,
            AgentRun.idempotency_key == idempotency_key,
        )
    )
    run = result.scalar_one_or_none()
    if run is not None and run.request_hash != request_hash:
        raise IdempotencyConflictError(
            "Idempotency key is already associated with a different request."
        )
    return run


async def create_or_get_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    idempotency_key: str,
    request_hash: str,
    prompt_version: str,
    template_pack_version: str,
    consent_id: UUID | None = None,
) -> tuple[AgentRun, bool]:
    require_explicit_transaction(session)
    _validate_idempotency_inputs(idempotency_key, request_hash)

    existing = await _find_idempotent_run(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if existing is not None:
        return existing, False

    project_result = await session.execute(
        select(Project)
        .where(
            Project.workspace_id == workspace_id,
            Project.id == project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise ProjectNotFoundError("Project not found in the requested workspace.")

    # Serialize same-project retries, then recheck after acquiring the lock.
    existing = await _find_idempotent_run(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if existing is not None:
        return existing, False

    revision_result = await session.execute(
        select(ProjectRevision).where(
            ProjectRevision.workspace_id == workspace_id,
            ProjectRevision.project_id == project_id,
            ProjectRevision.id == revision_id,
        )
    )
    project_revision = revision_result.scalar_one_or_none()
    if project_revision is None:
        raise ProjectNotFoundError("Project revision not found in the requested project.")
    if project_revision.revision_number != project.current_revision:
        raise RevisionConflictError(
            project_revision.revision_number,
            project.current_revision,
        )

    run = AgentRun(
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        consent_id=consent_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        prompt_version=prompt_version,
        template_pack_version=template_pack_version,
    )
    session.add(run)
    await session.flush()
    return run, True
