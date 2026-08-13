"""Add private append-only department replies and weak-reply signals."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_department_replies"
down_revision = "0018_issue_cluster_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "department_replies",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "complaint_id",
            uuid,
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("submitted_by", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_text_hash", sa.String(length=64), nullable=True),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("classification_reason", sa.String(length=120), nullable=False),
        sa.Column(
            "classification_policy_version", sa.String(length=120), nullable=False
        ),
        sa.Column(
            "proof_claim_id",
            uuid,
            sa.ForeignKey("closure_proof_claims.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("received_at", timestamp, nullable=False),
    )
    op.create_index(
        "uq_department_replies_complaint_idempotency",
        "department_replies",
        ["complaint_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_department_replies_complaint_text_hash",
        "department_replies",
        ["complaint_id", "response_text_hash"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_department_reply_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'department_replies are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER department_replies_append_only
        BEFORE UPDATE OR DELETE ON department_replies
        FOR EACH ROW EXECUTE FUNCTION prevent_department_reply_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS department_replies_append_only ON department_replies"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_department_reply_mutation()")
    op.drop_index(
        "ix_department_replies_complaint_text_hash", table_name="department_replies"
    )
    op.drop_index(
        "uq_department_replies_complaint_idempotency", table_name="department_replies"
    )
    op.drop_table("department_replies")
