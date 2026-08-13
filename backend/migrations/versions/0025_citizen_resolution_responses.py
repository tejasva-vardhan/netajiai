"""Persist explicit citizen closure outcomes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_citizen_resolution"
down_revision = "0024_postgis_location_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "citizen_resolution_responses",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "complaint_id",
            uuid,
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_id",
            uuid,
            sa.ForeignKey("workflow_signal_receipts.signal_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
    )
    op.create_index(
        "uq_citizen_resolution_responses_complaint_idempotency",
        "citizen_resolution_responses",
        ["complaint_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_citizen_resolution_responses_complaint_created",
        "citizen_resolution_responses",
        ["complaint_id", "created_at"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_citizen_resolution_response_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'citizen_resolution_responses are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER citizen_resolution_responses_append_only
        BEFORE UPDATE OR DELETE ON citizen_resolution_responses
        FOR EACH ROW EXECUTE FUNCTION prevent_citizen_resolution_response_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS citizen_resolution_responses_append_only ON citizen_resolution_responses"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_citizen_resolution_response_mutation()"
    )
    op.drop_index(
        "ix_citizen_resolution_responses_complaint_created",
        table_name="citizen_resolution_responses",
    )
    op.drop_index(
        "uq_citizen_resolution_responses_complaint_idempotency",
        table_name="citizen_resolution_responses",
    )
    op.drop_table("citizen_resolution_responses")
