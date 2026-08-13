"""Persist deadline expirations before deterministic escalation."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_silence_events"
down_revision = "0019_department_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "silence_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "complaint_id",
            uuid,
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.String(length=255), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("deadline_at", timestamp, nullable=False),
        sa.Column("observed_at", timestamp, nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("escalation_count", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "uq_silence_events_complaint_idempotency",
        "silence_events",
        ["complaint_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_silence_events_complaint_observed",
        "silence_events",
        ["complaint_id", "observed_at"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_silence_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'silence_events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER silence_events_append_only
        BEFORE UPDATE OR DELETE ON silence_events
        FOR EACH ROW EXECUTE FUNCTION prevent_silence_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS silence_events_append_only ON silence_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_silence_event_mutation()")
    op.drop_index(
        "ix_silence_events_complaint_observed", table_name="silence_events"
    )
    op.drop_index(
        "uq_silence_events_complaint_idempotency", table_name="silence_events"
    )
    op.drop_table("silence_events")
