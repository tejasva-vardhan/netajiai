"""Persist complaint evidence links and request fingerprints.

Revision ID: 0013_complaint_evidence
Revises: 0012_scheme_reviewers
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_complaint_evidence"
down_revision = "0012_scheme_reviewers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column(
            "creation_request_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.add_column(
        "evidence_assets",
        sa.Column(
            "creation_request_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.create_table(
        "complaint_evidence",
        sa.Column("complaint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["complaint_id"], ["complaints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_asset_id"], ["evidence_assets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("complaint_id", "evidence_asset_id"),
    )
    op.create_index(
        "ix_complaint_evidence_asset", "complaint_evidence", ["evidence_asset_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_complaint_evidence_asset", table_name="complaint_evidence")
    op.drop_table("complaint_evidence")
    op.drop_column("evidence_assets", "creation_request_fingerprint")
    op.drop_column("complaints", "creation_request_fingerprint")
