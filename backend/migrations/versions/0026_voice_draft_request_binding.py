"""Remove transcript-derived voice-draft response persistence.

Revision ID: 0026_voice_draft_request_binding
Revises: 0025_citizen_resolution
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_voice_draft_request_binding"
down_revision = "0025_citizen_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows contain only retry snapshots; the API no longer needs them
    # and dropping the column removes any previously retained transcript text.
    op.drop_column("voice_draft_requests", "response_payload")


def downgrade() -> None:
    # The erased payload cannot be reconstructed. Keep the downgrade schema
    # compatible for operators who need to roll back application code.
    op.add_column(
        "voice_draft_requests",
        sa.Column("response_payload", sa.JSON(), nullable=True),
    )
