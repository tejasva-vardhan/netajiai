"""Persist the bounded escalation level and disclosure-review eligibility.

Revision ID: 0014_escalation_policy_state
Revises: 0013_complaint_evidence
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_escalation_policy_state"
down_revision = "0013_complaint_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "complaints",
        sa.Column(
            "public_disclosure_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("complaints", "public_disclosure_eligible")
    op.drop_column("complaints", "escalation_level")
