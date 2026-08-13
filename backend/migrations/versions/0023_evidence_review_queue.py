"""Add durable media review state and append-only reviewer decisions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_evidence_review_queue"
down_revision = "0022_sla_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.add_column("evidence_assets", sa.Column("reviewed_by", sa.String(length=255), nullable=True))
    op.add_column("evidence_assets", sa.Column("reviewed_at", timestamp, nullable=True))
    op.add_column(
        "evidence_assets",
        sa.Column("review_idempotency_key", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_evidence_assets_review_status_received",
        "evidence_assets",
        ["status", "server_received_at", "id"],
    )
    op.create_table(
        "evidence_review_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "evidence_asset_id",
            uuid,
            sa.ForeignKey("evidence_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", timestamp, nullable=False),
    )
    op.create_index(
        "uq_evidence_review_events_asset_idempotency",
        "evidence_review_events",
        ["evidence_asset_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_evidence_review_events_asset_occurred",
        "evidence_review_events",
        ["evidence_asset_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_evidence_review_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'evidence_review_events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER evidence_review_events_append_only
        BEFORE UPDATE OR DELETE ON evidence_review_events
        FOR EACH ROW EXECUTE FUNCTION prevent_evidence_review_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS evidence_review_events_append_only ON evidence_review_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_evidence_review_event_mutation()")
    op.drop_index("ix_evidence_review_events_asset_occurred", table_name="evidence_review_events")
    op.drop_index("uq_evidence_review_events_asset_idempotency", table_name="evidence_review_events")
    op.drop_table("evidence_review_events")
    op.drop_index("ix_evidence_assets_review_status_received", table_name="evidence_assets")
    op.drop_column("evidence_assets", "review_idempotency_key")
    op.drop_column("evidence_assets", "reviewed_at")
    op.drop_column("evidence_assets", "reviewed_by")
