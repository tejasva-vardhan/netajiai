"""Record the lifecycle status observed when a silence deadline breaches."""

from alembic import op
import sqlalchemy as sa


revision = "0021_silence_event_status"
down_revision = "0020_silence_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "silence_events",
        sa.Column(
            "status",
            sa.String(length=64),
            nullable=False,
            server_default="awaiting_response",
        ),
    )
    op.alter_column("silence_events", "status", server_default=None)


def downgrade() -> None:
    op.drop_column("silence_events", "status")
