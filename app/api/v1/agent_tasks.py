from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.v1.projects import _get_db, _get_workspace_id
from app.db.repositories import agent_tasks

router = APIRouter()


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    priority: int = Field(default=3, ge=1, le=5)
    created_by: str | None = None


class TaskResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    revision_id: UUID
    title: str
    description: str
    status: str
    priority: int


@router.post("/projects/{project_id}/revisions/{revision_id}/agent-tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_task(
    project_id: UUID,
    revision_id: UUID,
    body: CreateTaskRequest,
    db=Depends(_get_db),
    workspace_id=Depends(_get_workspace_id),
):
    async with db.begin():
        try:
            task = await agent_tasks.create_task(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                revision_id=revision_id,
                title=body.title,
                description=body.description,
                priority=body.priority,
                created_by=body.created_by,
            )
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request") from exc
    return TaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        revision_id=task.revision_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
    )


class TransitionRequest(BaseModel):
    status: str
    actor: str = "local_user"
    reason: str | None = None


@router.post("/projects/{project_id}/agent-tasks/{task_id}/transition")
async def transition_agent_task(
    project_id: UUID,
    task_id: UUID,
    body: TransitionRequest,
    db=Depends(_get_db),
    workspace_id=Depends(_get_workspace_id),
):
    async with db.begin():
        try:
            task = await agent_tasks.transition_task_status(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=task_id,
                to_status=body.status,
                actor=body.actor,
                reason=body.reason,
            )
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request") from exc
    return {"id": str(task.id), "status": task.status}
