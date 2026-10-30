"""add agent runtime tables

Revision ID: 7962844f451e
Revises: 5a1c9e7d4b20
Create Date: 2026-10-30 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '7962844f451e'
down_revision = '5a1c9e7d4b20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agent_tasks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('revision_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('priority', sa.SmallInteger(), nullable=False),
        sa.Column('assigned_to', sa.String(length=64), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('approved_by', sa.String(length=64), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('proposed','approved','in_progress','blocked','completed','verified','rejected')", name='agent_task_status'),
        sa.CheckConstraint('priority BETWEEN 1 AND 5', name='agent_task_priority'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'revision_id'], ['project_revisions.workspace_id', 'project_revisions.project_id', 'project_revisions.id'], ondelete='RESTRICT', name='fk_agent_tasks_revision'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'project_id', 'id', name='uq_agent_tasks_scope_id'),
    )
    op.create_index('ix_agent_tasks_project_status', 'agent_tasks', ['workspace_id', 'project_id', 'status'], unique=False)

    op.create_table(
        'agent_task_requirements',
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('requirement_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'task_id'], ['agent_tasks.workspace_id', 'agent_tasks.project_id', 'agent_tasks.id'], ondelete='CASCADE', name='fk_agent_task_req_task'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'requirement_id'], ['requirements.workspace_id', 'requirements.project_id', 'requirements.id'], ondelete='CASCADE', name='fk_agent_task_req_requirement'),
        sa.PrimaryKeyConstraint('workspace_id', 'project_id', 'task_id', 'requirement_id'),
    )

    op.create_table(
        'agent_evidence',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('evidence_type', sa.String(length=32), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('artifact_uri', sa.String(length=512), nullable=True),
        sa.Column('verification_level', sa.String(length=32), nullable=False),
        sa.Column('verified_by', sa.String(length=64), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("verification_level IN ('agent_reported','test_verified','human_verified')", name='agent_evidence_verification_level'),
        sa.CheckConstraint("verification_level = 'agent_reported' OR verified_by IS NOT NULL", name='agent_evidence_verifier'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'task_id'], ['agent_tasks.workspace_id', 'agent_tasks.project_id', 'agent_tasks.id'], ondelete='CASCADE', name='fk_agent_evidence_task'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'project_id', 'id', name='uq_agent_evidence_scope_id'),
    )
    op.create_index('ix_agent_evidence_task', 'agent_evidence', ['workspace_id', 'project_id', 'task_id'], unique=False)

    op.create_table(
        'agent_context_access',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('revision_id', sa.UUID(), nullable=False),
        sa.Column('actor', sa.String(length=64), nullable=False),
        sa.Column('access_level', sa.String(length=16), nullable=False),
        sa.Column('granted_by', sa.String(length=64), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("access_level IN ('read','write','approve')", name='agent_context_access_level'),
        sa.CheckConstraint("actor != 'agent' OR access_level != 'approve'", name='agent_no_self_approve'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'revision_id'], ['project_revisions.workspace_id', 'project_revisions.project_id', 'project_revisions.id'], ondelete='CASCADE', name='fk_agent_context_access_revision'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'project_id', 'id', name='uq_agent_context_access_scope_id'),
    )


def downgrade() -> None:
    op.drop_table('agent_context_access')
    op.drop_table('agent_evidence')
    op.drop_table('agent_task_requirements')
    op.drop_table('agent_tasks')
