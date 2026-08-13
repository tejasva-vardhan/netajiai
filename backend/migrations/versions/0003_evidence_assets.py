"""Add durable evidence and location metadata.

Revision ID: 0003_evidence_assets
Revises: 0002_submission_idempotency
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_evidence_assets"
down_revision = "0002_submission_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "location_samples",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("citizen_id", sa.String(length=255), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("accuracy_m", sa.Numeric(8, 2), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("captured_at", timestamp, nullable=False),
        sa.Column("server_received_at", timestamp, nullable=False),
    )
    op.create_index("ix_location_samples_citizen_id", "location_samples", ["citizen_id"])

    op.create_table(
        "evidence_assets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("citizen_id", sa.String(length=255), nullable=False),
        sa.Column("creation_idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("client_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("capture_source", sa.String(length=40), nullable=False),
        sa.Column("capture_attestation_hash", sa.String(length=64), nullable=False),
        sa.Column("device_captured_at", timestamp, nullable=False),
        sa.Column("server_received_at", timestamp, nullable=False),
        sa.Column("uploaded_at", timestamp, nullable=True),
        sa.Column("verified_at", timestamp, nullable=True),
        sa.Column("rejection_reason", sa.String(length=255), nullable=True),
        sa.Column("verification_signals", sa.JSON(), nullable=False),
        sa.Column(
            "location_sample_id",
            uuid,
            sa.ForeignKey("location_samples.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint(
            "citizen_id",
            "creation_idempotency_key",
            name="uq_evidence_assets_citizen_creation_idempotency",
        ),
    )
    op.create_index("ix_evidence_assets_citizen_id", "evidence_assets", ["citizen_id"])
    op.create_index("ix_evidence_assets_status", "evidence_assets", ["status"])
    op.create_index(
        "ix_evidence_assets_location_sample_id", "evidence_assets", ["location_sample_id"]
    )
    op.create_index(
        "ix_evidence_assets_citizen_status",
        "evidence_assets",
        ["citizen_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_assets_citizen_status", table_name="evidence_assets")
    op.drop_index("ix_evidence_assets_location_sample_id", table_name="evidence_assets")
    op.drop_index("ix_evidence_assets_status", table_name="evidence_assets")
    op.drop_index("ix_evidence_assets_citizen_id", table_name="evidence_assets")
    op.drop_table("evidence_assets")
    op.drop_index("ix_location_samples_citizen_id", table_name="location_samples")
    op.drop_table("location_samples")
