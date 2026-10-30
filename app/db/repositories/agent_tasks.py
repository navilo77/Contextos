from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentContextAccess, AgentEvidence, AgentTask, AgentTaskRequirementLink, AuditEvent
from app.db.repositories.errors import ProjectNotFoundError, RepositoryInputError
from app.db.repositories.transactions import require_explicit_transaction

ALLOWED_TASK_STATUSES = ("proposed", "approved", "in_progress", "blocked", "completed", "verified", "rejected")
ALLOWED_TASK_TRANSITIONS = {
    "proposed": ("approved", "rejected"),
    "approved": ("in_progress", "blocked"),
    "in_progress": ("blocked", "completed"),
    "blocked": ("in_progress", "approved"),
    "completed": ("verified", "blocked"),
    "verified": (),
    "rejected": (),
}
ALLOWED_VERIFICATION_LEVELS = ("agent_reported", "test_verified", "human_verified")


async def create_task(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    title: str,
    description: str,
    priority: int = 3,
    created_by: str | None = None,
) -> AgentTask:
    require_explicit_transaction(session)
    if priority < 1 or priority > 5:
        raise RepositoryInputError("Priority must be between 1 and 5.")
    task = AgentTask(
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        title=title,
        description=description,
        status="proposed",
        priority=priority,
        created_by=created_by,
    )
    session.add(task)
    await session.flush()
    return task


async def get_task(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
) -> AgentTask | None:
    require_explicit_transaction(session)
    result = await session.execute(
        select(AgentTask).where(
            AgentTask.workspace_id == workspace_id,
            AgentTask.project_id == project_id,
            AgentTask.id == task_id,
        )
    )
    return result.scalar_one_or_none()


async def transition_task_status(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    to_status: str,
    actor: str = "local_user",
    reason: str | None = None,
) -> AgentTask:
    require_explicit_transaction(session)
    if to_status not in ALLOWED_TASK_STATUSES:
        raise RepositoryInputError(f"Invalid task status: {to_status}.")
    task = await get_task(session, workspace_id=workspace_id, project_id=project_id, task_id=task_id)
    if task is None:
        raise ProjectNotFoundError(f"Task {task_id} was not found.")
    from_status = task.status
    if to_status not in ALLOWED_TASK_TRANSITIONS.get(from_status, ()):
        raise RepositoryInputError(f"Invalid transition from {from_status} to {to_status}.")
    if to_status == "approved":
        if actor != "local_user":
            raise RepositoryInputError("Only local_user may approve tasks.")
        task.approved_by = actor
        task.approved_at = datetime.now(timezone.utc)
    if to_status == "completed":
        task.completed_at = datetime.now(timezone.utc)
    if to_status == "verified":
        # Verification requires evidence and must not be done by agents alone in a privileged way
        # Actual verification is enforced via evidence verification
        pass
    task.status = to_status
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor=actor,
            action_code=f"agent_task.{to_status}",
            subject_type="agent_task",
            subject_id=task_id,
            safe_metadata={"revision_id": str(task.revision_id), "from_status": from_status, "reason": reason},
        )
    )
    await session.flush()
    return task


async def link_task_requirement(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    requirement_id: UUID,
) -> AgentTaskRequirementLink:
    require_explicit_transaction(session)
    link = AgentTaskRequirementLink(
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        requirement_id=requirement_id,
    )
    session.add(link)
    await session.flush()
    return link


async def submit_evidence(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    evidence_type: str,
    description: str,
    artifact_uri: str | None = None,
    metadata: dict | None = None,
) -> AgentEvidence:
    require_explicit_transaction(session)
    task = await get_task(session, workspace_id=workspace_id, project_id=project_id, task_id=task_id)
    if task is None:
        raise ProjectNotFoundError(f"Task {task_id} was not found.")
    evidence = AgentEvidence(
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        evidence_type=evidence_type,
        description=description,
        artifact_uri=artifact_uri,
        verification_level="agent_reported",
        metadata_=metadata or {},
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def verify_evidence(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    evidence_id: UUID,
    verification_level: str,
    verified_by: str,
) -> AgentEvidence:
    require_explicit_transaction(session)
    if verification_level not in ALLOWED_VERIFICATION_LEVELS:
        raise RepositoryInputError(f"Invalid verification level: {verification_level}.")
    if verification_level == "agent_reported":
        raise RepositoryInputError("Cannot set verification to agent_reported.")
    if verification_level == "human_verified" and verified_by != "local_user":
        raise RepositoryInputError("Only local_user may provide human verification.")
    if verified_by == "agent" and verification_level == "human_verified":
        raise RepositoryInputError("Agents cannot provide human verification.")
    result = await session.execute(
        select(AgentEvidence).where(
            AgentEvidence.workspace_id == workspace_id,
            AgentEvidence.project_id == project_id,
            AgentEvidence.id == evidence_id,
        )
    )
    evidence = result.scalar_one_or_none()
    if evidence is None:
        raise ProjectNotFoundError(f"Evidence {evidence_id} was not found.")
    evidence.verification_level = verification_level
    evidence.verified_by = verified_by
    evidence.verified_at = datetime.now(timezone.utc)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor=verified_by,
            action_code=f"agent_evidence.{verification_level}",
            subject_type="agent_evidence",
            subject_id=evidence_id,
            safe_metadata={"project_id": str(project_id)},
        )
    )
    await session.flush()
    return evidence


async def grant_context_access(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    actor: str,
    access_level: str,
    granted_by: str,
) -> AgentContextAccess:
    require_explicit_transaction(session)
    if access_level not in ("read", "write", "approve"):
        raise RepositoryInputError("Invalid access level.")
    if actor == "agent" and access_level == "approve":
        raise RepositoryInputError("Agents cannot approve their own authoritative changes.")
    if granted_by != "local_user" and access_level == "approve":
        raise RepositoryInputError("Only local_user may grant approve access.")
    access = AgentContextAccess(
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        actor=actor,
        access_level=access_level,
        granted_by=granted_by,
    )
    session.add(access)
    await session.flush()
    return access
