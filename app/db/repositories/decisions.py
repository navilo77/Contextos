from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent, Decision
from app.db.repositories.errors import ProjectNotFoundError, RepositoryInputError
from app.db.repositories.transactions import require_explicit_transaction

# Only the local human user may approve or reject a decision. The actor set is
# intentionally tiny and checked explicitly so that no other caller -- including
# any external Coding Agent -- can invoke an approval transition.
ALLOWED_DECISION_ACTORS = ("local_user",)
ALLOWED_DECISION_STATUSES = ("accepted", "rejected")


async def get_decision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    decision_id: UUID,
) -> Decision | None:
    require_explicit_transaction(session)
    result = await session.execute(
        select(Decision).where(
            Decision.workspace_id == workspace_id,
            Decision.project_id == project_id,
            Decision.revision_id == revision_id,
            Decision.id == decision_id,
        )
    )
    return result.scalar_one_or_none()


async def set_decision_status(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    decision_id: UUID,
    status: str,
    actor: str = "local_user",
    reason: str | None = None,
) -> Decision:
    """Approve or reject a proposed decision.

    Authorization is enforced here, at the persistence boundary:
    - the actor must be an explicitly allowed decision actor;
    - the decision must currently be in 'proposed' state, so an already
      accepted or rejected decision cannot be re-approved by any caller;
    - the state transition and its audit record are written in the same
      caller-owned transaction, so they are consistent or neither is applied.

    This function never creates a decision and never bypasses the proposed
    state. It is the only path to 'accepted' or 'rejected'.
    """
    if actor not in ALLOWED_DECISION_ACTORS:
        raise RepositoryInputError(
            f"Decision actor must be one of {ALLOWED_DECISION_ACTORS}."
        )
    if status not in ALLOWED_DECISION_STATUSES:
        raise RepositoryInputError(
            f"Decision status must be one of {ALLOWED_DECISION_STATUSES}."
        )
    require_explicit_transaction(session)

    decision = await get_decision(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        decision_id=decision_id,
    )
    if decision is None:
        raise ProjectNotFoundError(f"Decision {decision_id} was not found.")
    if decision.status != "proposed":
        raise RepositoryInputError(
            f"Decision {decision_id} is already '{decision.status}' and can no "
            "longer be approved or rejected. Only 'proposed' decisions can change state."
        )

    previous_status = decision.status
    now = datetime.now(timezone.utc)
    decision.status = status
    decision.decided_by = actor
    decision.decided_at = now

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor=actor,
            action_code=f"decision.{status}",
            subject_type="decision",
            subject_id=decision_id,
            safe_metadata={
                "revision_id": str(revision_id),
                "previous_status": previous_status,
                "reason": reason,
            },
        )
    )
    await session.flush()
    return decision