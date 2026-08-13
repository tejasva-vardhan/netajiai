"""Add retry-safe claims for abandoned multipart-upload cleanup."""

from alembic import op
import sqlalchemy as sa


revision = "0011_multipart_cleanup_claims"
down_revision = "0010_resumable_evidence_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evidence_assets",
        sa.Column("multipart_cleanup_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "evidence_assets",
        sa.Column(
            "multipart_cleanup_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "evidence_assets",
        sa.Column("multipart_cleanup_last_error", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_evidence_assets_multipart_cleanup",
        "evidence_assets",
        ["status", "upload_mode", "created_at", "multipart_cleanup_claimed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_assets_multipart_cleanup", table_name="evidence_assets")
    op.drop_column("evidence_assets", "multipart_cleanup_last_error")
    op.drop_column("evidence_assets", "multipart_cleanup_attempts")
    op.drop_column("evidence_assets", "multipart_cleanup_claimed_at")
