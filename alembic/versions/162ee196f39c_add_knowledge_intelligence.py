"""add knowledge intelligence

Revision ID: 162ee196f39c
Revises: 7962844f451e
Create Date: 2026-10-30 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '162ee196f39c'
down_revision = '7962844f451e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'knowledge_sources',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('original_reference', sa.String(length=1024), nullable=True),
        sa.Column('content_text', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('provenance', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("source_type IN ('text','markdown','pdf','url','existing_document','research_reference')", name='knowledge_source_type'),
        sa.CheckConstraint("status IN ('ingested','extracted','reviewed','archived')", name='knowledge_source_status'),
        sa.CheckConstraint('length(content_text) BETWEEN 1 AND 200000', name='knowledge_source_content_length'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id'], ['projects.workspace_id', 'projects.id'], ondelete='CASCADE', name='fk_knowledge_sources_project'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'project_id', 'id', name='uq_knowledge_sources_scope_id'),
    )

    op.create_table(
        'knowledge_claims',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=False),
        sa.Column('claim_text', sa.Text(), nullable=False),
        sa.Column('claim_type', sa.String(length=32), nullable=False),
        sa.Column('source_location', sa.String(length=512), nullable=True),
        sa.Column('source_excerpt', sa.Text(), nullable=True),
        sa.Column('extraction_method', sa.String(length=32), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('review_status', sa.String(length=16), nullable=False),
        sa.Column('reviewed_by', sa.String(length=64), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("claim_type IN ('fact','assumption','requirement','constraint','risk','recommendation','observation')", name='knowledge_claim_type'),
        sa.CheckConstraint("review_status IN ('unreviewed','supported','contradicted','unverified','accepted','rejected','outdated')", name='knowledge_claim_review_status'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id'], ['projects.workspace_id', 'projects.id'], ondelete='CASCADE', name='fk_knowledge_claims_project'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'source_id'], ['knowledge_sources.workspace_id', 'knowledge_sources.project_id', 'knowledge_sources.id'], ondelete='RESTRICT', name='fk_knowledge_claims_source'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'project_id', 'id', name='uq_knowledge_claims_scope_id'),
    )

    op.create_table(
        'knowledge_evidence',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('claim_id', sa.UUID(), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=False),
        sa.Column('relationship_type', sa.String(length=16), nullable=False),
        sa.Column('relevant_excerpt', sa.Text(), nullable=True),
        sa.Column('source_location', sa.String(length=512), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('extraction_method', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("relationship_type IN ('supporting','contradicting','contextual','unresolved')", name='knowledge_evidence_relationship'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id'], ['projects.workspace_id', 'projects.id'], ondelete='CASCADE', name='fk_knowledge_evidence_project'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'claim_id'], ['knowledge_claims.workspace_id', 'knowledge_claims.project_id', 'knowledge_claims.id'], ondelete='CASCADE', name='fk_knowledge_evidence_claim'),
        sa.ForeignKeyConstraint(['workspace_id', 'project_id', 'source_id'], ['knowledge_sources.workspace_id', 'knowledge_sources.project_id', 'knowledge_sources.id'], ondelete='RESTRICT', name='fk_knowledge_evidence_source'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'project_id', 'id', name='uq_knowledge_evidence_scope_id'),
    )


def downgrade() -> None:
    op.drop_table('knowledge_evidence')
    op.drop_table('knowledge_claims')
    op.drop_table('knowledge_sources')
