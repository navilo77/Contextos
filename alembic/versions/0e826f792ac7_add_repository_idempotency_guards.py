"""add repository idempotency guards

Revision ID: 0e826f792ac7
Revises: 42a4101154f1
Create Date: 2026-10-27 02:40:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0e826f792ac7"
down_revision: Union[str, Sequence[str], None] = "42a4101154f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_agent_runs_request_hash_sha256_format",
        "agent_runs",
        "request_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_agent_runs_idempotency_key_length",
        "agent_runs",
        "length(idempotency_key) BETWEEN 1 AND 128",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_runs_idempotency_key_length", "agent_runs", type_="check")
    op.drop_constraint("ck_agent_runs_request_hash_sha256_format", "agent_runs", type_="check")
