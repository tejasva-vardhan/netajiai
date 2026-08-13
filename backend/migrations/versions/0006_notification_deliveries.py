"""Add idempotent notification delivery receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_notification_deliveries"
down_revision = "0005_identity_auth_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "notification_deliveries",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "complaint_id",
            uuid,
            sa.ForeignKey("complaints.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("destination_ref_hash", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("template_key", sa.String(length=120), nullable=False),
        sa.Column("template_version", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("provider_receipt", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.Column("sent_at", timestamp, nullable=True),
    )
    op.create_index(
        "ix_notification_deliveries_complaint_id",
        "notification_deliveries",
        ["complaint_id"],
    )
    op.create_index(
        "ix_notification_deliveries_status",
        "notification_deliveries",
        ["status"],
    )
    op.create_index(
        "ix_notification_deliveries_complaint_status",
        "notification_deliveries",
        ["complaint_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_complaint_status",
        table_name="notification_deliveries",
    )
    op.drop_index("ix_notification_deliveries_status", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_complaint_id", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
