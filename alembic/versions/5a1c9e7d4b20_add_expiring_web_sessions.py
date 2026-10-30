"""add expiring web sessions

Revision ID: 5a1c9e7d4b20
Revises: 0e826f792ac7
Create Date: 2026-10-27 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5a1c9e7d4b20"
down_revision: Union[str, Sequence[str], None] = "0e826f792ac7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_sessions",
        sa.Column("session_id_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "session_id_hash ~ '^[0-9a-f]{64}$'",
            name="ck_web_sessions_session_id_hash_sha256_format",
        ),
        sa.PrimaryKeyConstraint("session_id_hash", name="pk_web_sessions"),
    )
    op.create_index("ix_web_sessions_expires_at", "web_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_web_sessions_expires_at", table_name="web_sessions")
    op.drop_table("web_sessions")
