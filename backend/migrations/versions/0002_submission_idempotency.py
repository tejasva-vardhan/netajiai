"""Add citizen-scoped idempotency for complaint creation.

Revision ID: 0002_submission_idempotency
Revises: 0001_initial_foundation
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_submission_idempotency"
down_revision = "0001_initial_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column("creation_idempotency_key", sa.String(length=255), nullable=True),
    )
    op.execute(
        """
        UPDATE complaints
        SET creation_idempotency_key = 'migration:' || id::text
        WHERE creation_idempotency_key IS NULL
        """
    )
    op.alter_column(
        "complaints",
        "creation_idempotency_key",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.create_index(
        "uq_complaints_citizen_creation_idempotency",
        "complaints",
        ["citizen_id", "creation_idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_complaints_citizen_creation_idempotency", table_name="complaints"
    )
    op.drop_column("complaints", "creation_idempotency_key")
