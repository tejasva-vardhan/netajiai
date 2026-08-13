"""Add minimal, consent-scoped identity verification records.

Revision ID: 0004_identity_verifications
Revises: 0003_evidence_assets
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_identity_verifications"
down_revision = "0003_evidence_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "identity_verifications",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("subject_ref", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("reference_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("consent_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("verified_claims", sa.JSON(), nullable=False),
        sa.Column("verified_at", timestamp, nullable=True),
        sa.Column("expires_at", timestamp, nullable=True),
        sa.Column("retention_until", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index("ix_identity_verifications_subject_ref", "identity_verifications", ["subject_ref"])
    op.create_index("ix_identity_verifications_status", "identity_verifications", ["status"])
    op.create_index(
        "ix_identity_verifications_subject_status",
        "identity_verifications",
        ["subject_ref", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_identity_verifications_subject_status", table_name="identity_verifications")
    op.drop_index("ix_identity_verifications_status", table_name="identity_verifications")
    op.drop_index("ix_identity_verifications_subject_ref", table_name="identity_verifications")
    op.drop_table("identity_verifications")
