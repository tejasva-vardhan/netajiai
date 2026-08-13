"""Persist the immutable SLA timing snapshot selected at complaint intake."""

from alembic import op
import sqlalchemy as sa


revision = "0022_sla_snapshots"
down_revision = "0021_silence_event_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column(
            "sla_policy_version",
            sa.String(length=120),
            nullable=False,
            server_default="synthetic-sla.v1",
        ),
    )
    op.add_column(
        "complaints",
        sa.Column(
            "response_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="259200",
        ),
    )
    op.add_column(
        "complaints",
        sa.Column(
            "post_escalation_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="2592000",
        ),
    )
    op.alter_column("complaints", "sla_policy_version", server_default=None)
    op.alter_column("complaints", "response_timeout_seconds", server_default=None)
    op.alter_column(
        "complaints", "post_escalation_timeout_seconds", server_default=None
    )


def downgrade() -> None:
    op.drop_column("complaints", "post_escalation_timeout_seconds")
    op.drop_column("complaints", "response_timeout_seconds")
    op.drop_column("complaints", "sla_policy_version")
