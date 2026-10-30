from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WebSession(Base):
    __tablename__ = "web_sessions"
    session_id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=func.cast(func.literal_column("'{}'::jsonb"), JSONB))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Workspace(Base, Timestamped):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("slug", name="uq_workspaces_slug"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Project(Base, Timestamped):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_slug"),
        UniqueConstraint("workspace_id", "id", name="uq_projects_workspace_id"),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT", name="fk_projects_workspace"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProjectRevision(Base, Timestamped):
    __tablename__ = "project_revisions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "id", name="uq_project_revisions_scope_id"),
        UniqueConstraint("workspace_id", "project_id", "revision_number", name="uq_project_revisions_scope_number"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    profile: Mapped[str] = mapped_column(String(16), nullable=False)
    intake_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    template_pack_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_revisions_project",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "profile IN ('compact', 'detailed')", name="ck_project_revisions_profile"
        ),
        CheckConstraint(
            "revision_number > 0", name="ck_project_revisions_revision_number_positive"
        ),
    )


class ProjectSource(Base, Timestamped):
    __tablename__ = "project_sources"
    __table_args__ = (UniqueConstraint("workspace_id", "project_id", "id", name="uq_project_sources_scope_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    safe_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_sources_project",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source_kind IN ('idea', 'answer', 'user_edit')",
            name="ck_project_sources_source_kind",
        ),
        CheckConstraint(
            "length(content) BETWEEN 1 AND 20000", name="ck_project_sources_content_length"
        ),
    )


class AuditEvent(Base, Timestamped):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_workspace_created", "workspace_id", sa.literal_column("created_at DESC"), "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    action_code: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=func.cast(func.literal_column("'{}'::jsonb"), JSONB))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint("actor IN ('local_user', 'system')", name="ck_audit_events_actor"),
        ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_audit_events_workspace", ondelete="RESTRICT"
        ),
    )


class ProjectRevisionSource(Base):
    __tablename__ = "project_revision_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_revision_sources_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "source_id"],
            ["project_sources.workspace_id", "project_sources.project_id", "project_sources.id"],
            name="fk_revision_sources_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "project_id", 
            "revision_id",
            "source_id",
            name="pk_project_revision_sources",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class ProjectDocument(Base, Timestamped):
    __tablename__ = "project_documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "id", name="uq_project_documents_scope_id"),
        UniqueConstraint("workspace_id", "project_id", "path", "document_revision", name="uq_project_documents_path_revision"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    document_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_format: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_project_documents_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.project_id", "agent_runs.id"],
            name="fk_project_documents_run",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "content_format IN ('markdown', 'json')",
            name="ck_project_documents_content_format",
        ),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_project_documents_sha256_format"
        ),
        CheckConstraint(
            "document_revision > 0", name="ck_project_documents_document_revision_positive"
        ),
    )


class RunEvent(Base, Timestamped):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_events_sequence"),
        Index("ix_run_events_project_created", "workspace_id", "project_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_run_events_sequence_positive"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.project_id", "agent_runs.id"],
            name="fk_run_events_run",
            ondelete="CASCADE",
        ),
    )


class AgentRun(Base, Timestamped):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "id", name="uq_agent_runs_scope_id"),
        UniqueConstraint("graph_thread_id", name="uq_agent_runs_graph_thread"),
        UniqueConstraint("workspace_id", "project_id", "idempotency_key", name="uq_agent_runs_idempotency"),
        Index("ix_agent_runs_project_created", "workspace_id", "project_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    consent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retryable: Mapped[bool | None] = mapped_column(nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    template_pack_version: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_user', 'blocked', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_agent_runs_attempt_count_nonnegative"
        ),
        CheckConstraint(
            "length(request_hash) = 64", name="ck_agent_runs_request_hash_length"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "consent_id"],
            ["provider_consents.workspace_id", "provider_consents.project_id", "provider_consents.id"],
            name="fk_agent_runs_consent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_agent_runs_revision",
            ondelete="CASCADE",
        ),
    )


class ValidationReport(Base, Timestamped):
    __tablename__ = "validation_reports"
    __table_args__ = (UniqueConstraint("workspace_id", "project_id", "id", name="uq_validation_reports_scope_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    validator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    checked_documents: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('passed', 'failed')", name="ck_validation_reports_status"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_validation_reports_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.project_id", "agent_runs.id"],
            name="fk_validation_reports_run",
            ondelete="CASCADE",
        ),
    )


class ValidationFinding(Base):
    __tablename__ = "validation_findings"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    requirement_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    rule_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_detail: Mapped[str] = mapped_column(String(1000), nullable=False)
    resolved: Mapped[bool] = mapped_column(nullable=False)
    
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low', 'info')",
            name="ck_validation_findings_severity",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "document_id"],
            ["project_documents.workspace_id", "project_documents.project_id", "project_documents.id"],
            name="fk_validation_findings_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "report_id"],
            ["validation_reports.workspace_id", "validation_reports.project_id", "validation_reports.id"],
            name="fk_validation_findings_report",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.project_id", "requirements.id"],
            name="fk_validation_findings_requirement",
            ondelete="CASCADE",
        ),
    )


class Export(Base, Timestamped):
    __tablename__ = "exports"
    __table_args__ = (UniqueConstraint("workspace_id", "project_id", "id", name="uq_exports_scope_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    validation_report_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    zip_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint("status IN ('ready', 'revoked')", name="ck_exports_status"),
        CheckConstraint(
            "zip_sha256 ~ '^[0-9a-f]{64}$'", name="ck_exports_zip_sha256_format"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_exports_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "validation_report_id"],
            ["validation_reports.workspace_id", "validation_reports.project_id", "validation_reports.id"],
            name="fk_exports_validation_report",
            ondelete="CASCADE",
        ),
    )


class ExportDocument(Base):
    __tablename__ = "export_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "document_id"],
            ["project_documents.workspace_id", "project_documents.project_id", "project_documents.id"],
            name="fk_export_documents_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "export_id"],
            ["exports.workspace_id", "exports.project_id", "exports.id"],
            name="fk_export_documents_export",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "project_id",
            "export_id",
            "document_id",
            name="pk_export_documents",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    export_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class Facts(Base, Timestamped):
    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("workspace_id", "project_id", "id", name="uq_facts_scope_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    classification: Mapped[str] = mapped_column(String(24), nullable=False)
    statement: Mapped[str] = mapped_column(Text(), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('confirmed', 'unconfirmed')", name="ck_facts_approval_status"
        ),
        CheckConstraint(
            "classification IN ('confirmed_fact', 'assumption', 'constraint', 'exclusion')",
            name="ck_facts_classification",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_facts_revision",
            ondelete="CASCADE",
        ),
    )


class Decision(Base, Timestamped):
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("workspace_id", "project_id", "id", name="uq_decisions_scope_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    statement: Mapped[str] = mapped_column(Text(), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "status = 'proposed' OR decided_at IS NOT NULL",
            name="ck_decisions_decision_timestamp",
        ),
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'undecided')",
            name="ck_decisions_status",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_decisions_revision",
            ondelete="CASCADE",
        ),
    )


class ClarificationQuestion(Base, Timestamped):
    __tablename__ = "clarification_questions"
    __table_args__ = (UniqueConstraint("workspace_id", "project_id", "id", name="uq_clarification_questions_scope_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    impact: Mapped[str] = mapped_column(String(500), nullable=False)
    blocking: Mapped[bool] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'answered', 'unknown', 'deferred')",
            name="ck_clarification_questions_status",
        ),
        CheckConstraint(
            "priority BETWEEN 1 AND 5", name="ck_clarification_questions_priority"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_clarification_questions_revision",
            ondelete="CASCADE",
        ),
    )


class Requirement(Base, Timestamped):
    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "id", name="uq_requirements_scope_id"),
        UniqueConstraint("workspace_id", "project_id", "revision_id", "requirement_key", name="uq_requirements_revision_key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text(), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'deferred')", name="ck_requirements_status"
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_requirements_priority"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_requirements_revision",
            ondelete="CASCADE",
        ),
    )


class RequirementDependency(Base):
    __tablename__ = "requirement_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "source_requirement_id"],
            ["requirements.workspace_id", "requirements.project_id", "requirements.id"],
            name="fk_requirement_dependencies_source",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "target_requirement_id"],
            ["requirements.workspace_id", "requirements.project_id", "requirements.id"],
            name="fk_requirement_dependencies_target",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source_requirement_id <> target_requirement_id",
            name="ck_requirement_dependencies_not_self_referential",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "project_id",
            "source_requirement_id",
            "target_requirement_id",
            name="pk_requirement_dependencies",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_requirement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_requirement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class AcceptanceCriterion(Base, Timestamped):
    __tablename__ = "acceptance_criteria"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "requirement_id", "ordinal", name="uq_acceptance_criteria_requirement_ordinal"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.project_id", "requirements.id"],
            name="fk_acceptance_criteria_requirement",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requirement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    statement: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint("ordinal > 0", name="ck_acceptance_criteria_ordinal_positive"),
    )


class RequirementSource(Base):
    __tablename__ = "requirement_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.project_id", "requirements.id"],
            name="fk_requirement_sources_requirement",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "source_id"],
            ["project_sources.workspace_id", "project_sources.project_id", "project_sources.id"],
            name="fk_requirement_sources_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "project_id",
            "requirement_id",
            "source_id",
            name="pk_requirement_sources",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requirement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class RequirementDecisionSource(Base):
    __tablename__ = "requirement_decision_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "decision_id"],
            ["decisions.workspace_id", "decisions.project_id", "decisions.id"],
            name="fk_requirement_decision_sources_decision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.project_id", "requirements.id"],
            name="fk_requirement_decision_sources_requirement",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "project_id",
            "requirement_id",
            "decision_id",
            name="pk_requirement_decision_sources",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requirement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class FactSource(Base):
    __tablename__ = "fact_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "fact_id"],
            ["facts.workspace_id", "facts.project_id", "facts.id"],
            name="fk_fact_sources_fact",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "source_id"],
            ["project_sources.workspace_id", "project_sources.project_id", "project_sources.id"],
            name="fk_fact_sources_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "project_id", "fact_id", "source_id", name="pk_fact_sources"
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    fact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class DecisionSource(Base):
    __tablename__ = "decision_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "decision_id"],
            ["decisions.workspace_id", "decisions.project_id", "decisions.id"],
            name="fk_decision_sources_decision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "source_id"],
            ["project_sources.workspace_id", "project_sources.project_id", "project_sources.id"],
            name="fk_decision_sources_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "project_id", "decision_id", "source_id", name="pk_decision_sources"
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class ClarificationAnswer(Base, Timestamped):
    __tablename__ = "clarification_answers"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    question_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    answer_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "(answer_state = 'answered' AND source_id IS NOT NULL) OR (answer_state <> 'answered' AND source_id IS NULL)",
            name="ck_clarification_answers_answer_source_required",
        ),
        CheckConstraint(
            "answer_state IN ('answered', 'unknown', 'deferred')",
            name="ck_clarification_answers_answer_state",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "question_id"],
            ["clarification_questions.workspace_id", "clarification_questions.project_id", "clarification_questions.id"],
            name="fk_clarification_answers_question",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "source_id"],
            ["project_sources.workspace_id", "project_sources.project_id", "project_sources.id"],
            name="fk_clarification_answers_source",
            ondelete="CASCADE",
        ),
    )


class ProviderConsent(Base, Timestamped):
    __tablename__ = "provider_consents"
    __table_args__ = (UniqueConstraint("workspace_id", "project_id", "id", name="uq_provider_consents_scope_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(128), nullable=False)
    disclosure_version: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "destination = 'generativelanguage.googleapis.com'",
            name="ck_provider_consents_destination_fixed",
        ),
        CheckConstraint(
            "provider_id = 'google_gemini'", name="ck_provider_consents_provider_allowed"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_provider_consents_revision",
            ondelete="CASCADE",
        ),
    )


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(128), nullable=False)
    credentials_encrypted: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provider_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=True)
    
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('gemini')", name="ck_providers_provider_type_allowed"
        ),
        CheckConstraint(
            "provider_id = 'google_gemini'", name="ck_providers_provider_id_allowed"
        ),
        CheckConstraint(
            "destination = 'generativelanguage.googleapis.com'",
            name="ck_providers_destination_fixed",
        ),
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_providers_approval_status",
        ),
    )


class TemplatePackVersion(Base):
    __tablename__ = "template_pack_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_template_pack_versions_version"),)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "id", name="uq_requirements_scope_id"),
        UniqueConstraint("workspace_id", "project_id", "revision_id", "requirement_key", name="uq_requirements_revision_key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text(), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'deferred')", name="ck_requirements_status"
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_requirements_priority"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "revision_id"],
            ["project_revisions.workspace_id", "project_revisions.project_id", "project_revisions.id"],
            name="fk_requirements_revision",
            ondelete="CASCADE",
        ),
    )
