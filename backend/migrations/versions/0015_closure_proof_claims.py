"""Persist redacted, idempotent proof claims for reported fixes.

Revision ID: 0015_closure_proof_claims
Revises: 0014_escalation_policy_state
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_closure_proof_claims"
down_revision = "0014_escalation_policy_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "closure_proof_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("complaint_id", sa.Uuid(), nullable=False),
        sa.Column("proof_type", sa.String(length=40), nullable=False),
        sa.Column("proof_reference_hash", sa.String(length=64), nullable=False),
        sa.Column("submitted_by", sa.String(length=255), nullable=False),
        sa.Column("verifier", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_closure_proof_claims_complaint_id",
        "closure_proof_claims",
        ["complaint_id"],
    )
    op.create_index(
        "ix_closure_proof_claims_status",
        "closure_proof_claims",
        ["status"],
    )
    op.create_index(
        "uq_closure_proof_claims_complaint_idempotency",
        "closure_proof_claims",
        ["complaint_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_closure_proof_claims_complaint_reference",
        "closure_proof_claims",
        ["complaint_id", "proof_reference_hash"],
        unique=True,
    )
    op.create_index(
        "ix_closure_proof_claims_complaint_status",
        "closure_proof_claims",
        ["complaint_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_closure_proof_claims_complaint_status",
        table_name="closure_proof_claims",
    )
    op.drop_index(
        "uq_closure_proof_claims_complaint_reference",
        table_name="closure_proof_claims",
    )
    op.drop_index(
        "uq_closure_proof_claims_complaint_idempotency",
        table_name="closure_proof_claims",
    )
    op.drop_index("ix_closure_proof_claims_status", table_name="closure_proof_claims")
    op.drop_index(
        "ix_closure_proof_claims_complaint_id",
        table_name="closure_proof_claims",
    )
    op.drop_table("closure_proof_claims")
