"""Record the reviewer identity for approved scheme facts and sources."""

from alembic import op
import sqlalchemy as sa


revision = "0012_scheme_reviewers"
down_revision = "0011_multipart_cleanup_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheme_records", sa.Column("reviewed_by", sa.String(length=255), nullable=True))
    op.add_column("scheme_sources", sa.Column("reviewed_by", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("scheme_sources", "reviewed_by")
    op.drop_column("scheme_records", "reviewed_by")
