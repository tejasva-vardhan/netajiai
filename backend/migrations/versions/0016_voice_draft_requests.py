"""Persist structured voice-draft responses for safe retries.

Revision ID: 0016_voice_draft_requests
Revises: 0015_closure_proof_claims
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_voice_draft_requests"
down_revision = "0015_closure_proof_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_draft_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("citizen_id", sa.String(length=255), nullable=False),
        sa.Column("audio_asset_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["audio_asset_id"], ["evidence_assets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voice_draft_requests_citizen_id",
        "voice_draft_requests",
        ["citizen_id"],
    )
    op.create_index(
        "ix_voice_draft_requests_audio_asset_id",
        "voice_draft_requests",
        ["audio_asset_id"],
    )
    op.create_index(
        "uq_voice_draft_requests_citizen_idempotency",
        "voice_draft_requests",
        ["citizen_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_voice_draft_requests_citizen_created",
        "voice_draft_requests",
        ["citizen_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_draft_requests_citizen_created",
        table_name="voice_draft_requests",
    )
    op.drop_index(
        "uq_voice_draft_requests_citizen_idempotency",
        table_name="voice_draft_requests",
    )
    op.drop_index(
        "ix_voice_draft_requests_audio_asset_id",
        table_name="voice_draft_requests",
    )
    op.drop_index(
        "ix_voice_draft_requests_citizen_id",
        table_name="voice_draft_requests",
    )
    op.drop_table("voice_draft_requests")
