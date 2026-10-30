from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.v1.projects import _get_db, _get_workspace_id
from app.db.repositories import agent_tasks

router = APIRouter()


class SubmitEvidenceRequest(BaseModel):
    evidence_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    artifact_uri: str | None = None
    metadata: dict | None = None


@router.post("/projects/{project_id}/agent-tasks/{task_id}/evidence")
async def submit_agent_evidence(
    project_id: UUID,
    task_id: UUID,
    body: SubmitEvidenceRequest,
    db=Depends(_get_db),
    workspace_id=Depends(_get_workspace_id),
):
    async with db.begin():
        try:
            ev = await agent_tasks.submit_evidence(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=task_id,
                evidence_type=body.evidence_type,
                description=body.description,
                artifact_uri=body.artifact_uri,
                metadata=body.metadata,
            )
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request") from exc
    return {"id": str(ev.id), "verification_level": ev.verification_level}


class VerifyEvidenceRequest(BaseModel):
    verification_level: str
    verified_by: str


@router.post("/projects/{project_id}/agent-evidence/{evidence_id}/verify")
async def verify_agent_evidence(
    project_id: UUID,
    evidence_id: UUID,
    body: VerifyEvidenceRequest,
    db=Depends(_get_db),
    workspace_id=Depends(_get_workspace_id),
):
    async with db.begin():
        try:
            ev = await agent_tasks.verify_evidence(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                evidence_id=evidence_id,
                verification_level=body.verification_level,
                verified_by=body.verified_by,
            )
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request") from exc
    return {"id": str(ev.id), "verification_level": ev.verification_level, "verified_by": ev.verified_by}
