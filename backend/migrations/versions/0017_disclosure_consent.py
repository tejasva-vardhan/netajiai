"""Persist the citizen's one-time disclosure choice."""

from alembic import op
import sqlalchemy as sa


revision = "0017_disclosure_consent"
down_revision = "0016_voice_draft_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column("disclosure_consent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "complaints",
        sa.Column("disclosure_policy_version", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("complaints", "disclosure_policy_version")
    op.drop_column("complaints", "disclosure_consent_at")
