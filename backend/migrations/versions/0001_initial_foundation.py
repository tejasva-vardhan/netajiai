"""Initial complaint, event, outbox, and session foundation.

Revision ID: 0001_initial_foundation
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "complaints",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("citizen_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("issue_type", sa.String(length=80), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("jurisdiction_code", sa.String(length=120), nullable=True),
        sa.Column(
            "execution_zone_state",
            sa.String(length=64),
            nullable=False,
            server_default="mapping_in_progress",
        ),
        sa.Column(
            "disclosure_mode",
            sa.String(length=32),
            nullable=False,
            server_default="verified_citizen",
        ),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index("ix_complaints_citizen_id", "complaints", ["citizen_id"])
    op.create_index("ix_complaints_status", "complaints", ["status"])
    op.create_index("ix_complaints_jurisdiction_code", "complaints", ["jurisdiction_code"])

    op.create_table(
        "complaint_events",
        sa.Column("event_id", uuid, primary_key=True),
        sa.Column(
            "complaint_id",
            uuid,
            sa.ForeignKey("complaints.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("from_status", sa.String(length=64), nullable=True),
        sa.Column("to_status", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", timestamp, nullable=False),
        sa.UniqueConstraint(
            "complaint_id",
            "idempotency_key",
            name="uq_complaint_events_idempotency",
        ),
    )
    op.create_index(
        "ix_complaint_events_correlation_id", "complaint_events", ["correlation_id"]
    )
    op.create_index(
        "ix_complaint_events_complaint_occurred",
        "complaint_events",
        ["complaint_id", "occurred_at"],
    )

    op.create_table(
        "outbox_messages",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "event_id",
            uuid,
            sa.ForeignKey("complaint_events.event_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("message_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("available_at", timestamp, nullable=False),
        sa.Column("published_at", timestamp, nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
    )
    op.create_index("ix_outbox_messages_message_key", "outbox_messages", ["message_key"])

    op.create_table(
        "sessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("citizen_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index("ix_sessions_citizen_id", "sessions", ["citizen_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_complaint_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'complaint_events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER complaint_events_append_only
        BEFORE UPDATE OR DELETE ON complaint_events
        FOR EACH ROW EXECUTE FUNCTION prevent_complaint_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS complaint_events_append_only ON complaint_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_complaint_event_mutation()")
    op.drop_index("ix_sessions_citizen_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_outbox_messages_message_key", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index("ix_complaint_events_complaint_occurred", table_name="complaint_events")
    op.drop_index("ix_complaint_events_correlation_id", table_name="complaint_events")
    op.drop_table("complaint_events")
    op.drop_index("ix_complaints_jurisdiction_code", table_name="complaints")
    op.drop_index("ix_complaints_status", table_name="complaints")
    op.drop_index("ix_complaints_citizen_id", table_name="complaints")
    op.drop_table("complaints")
