"""Persist the server-owned routing snapshot used for activation."""

from alembic import op
import sqlalchemy as sa


revision = "0008_routing_activation_metadata"
down_revision = "0007_workflow_signal_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column("routing_snapshot_ref", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "complaints",
        sa.Column("routing_reason_code", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("complaints", "routing_reason_code")
    op.drop_column("complaints", "routing_snapshot_ref")
