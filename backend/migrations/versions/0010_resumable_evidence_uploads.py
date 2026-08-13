"""Add durable multipart upload sessions and part receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_resumable_evidence_uploads"
down_revision = "0009_scheme_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.add_column(
        "evidence_assets",
        sa.Column("upload_mode", sa.String(length=16), nullable=False, server_default="single"),
    )
    op.add_column("evidence_assets", sa.Column("multipart_upload_id", sa.String(length=255), nullable=True))
    op.add_column("evidence_assets", sa.Column("part_size", sa.Integer(), nullable=True))
    op.add_column("evidence_assets", sa.Column("part_count", sa.Integer(), nullable=True))
    op.create_index("ix_evidence_assets_multipart_upload_id", "evidence_assets", ["multipart_upload_id"])
    op.create_table(
        "evidence_upload_parts",
        sa.Column("evidence_asset_id", uuid, nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(["evidence_asset_id"], ["evidence_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evidence_asset_id", "part_number"),
    )


def downgrade() -> None:
    op.drop_table("evidence_upload_parts")
    op.drop_index("ix_evidence_assets_multipart_upload_id", table_name="evidence_assets")
    op.drop_column("evidence_assets", "part_count")
    op.drop_column("evidence_assets", "part_size")
    op.drop_column("evidence_assets", "multipart_upload_id")
    op.drop_column("evidence_assets", "upload_mode")
