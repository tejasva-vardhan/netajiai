"""Add durable idempotency receipts for workflow signals."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_workflow_signal_receipts"
down_revision = "0006_notification_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "workflow_signal_receipts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "complaint_id",
            uuid,
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_id", uuid, nullable=False, unique=True),
        sa.Column("signal_kind", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint(
            "complaint_id",
            "idempotency_key",
            name="uq_workflow_signal_receipts_complaint_idempotency",
        ),
    )
    op.create_index(
        "ix_workflow_signal_receipts_complaint_id",
        "workflow_signal_receipts",
        ["complaint_id"],
    )
    op.create_index(
        "ix_workflow_signal_receipts_status",
        "workflow_signal_receipts",
        ["status"],
    )
    op.create_index(
        "ix_workflow_signal_receipts_complaint_status",
        "workflow_signal_receipts",
        ["complaint_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_signal_receipts_complaint_status",
        table_name="workflow_signal_receipts",
    )
    op.drop_index("ix_workflow_signal_receipts_status", table_name="workflow_signal_receipts")
    op.drop_index("ix_workflow_signal_receipts_complaint_id", table_name="workflow_signal_receipts")
    op.drop_table("workflow_signal_receipts")
