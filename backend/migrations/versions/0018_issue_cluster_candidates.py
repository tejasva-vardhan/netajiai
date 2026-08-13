"""Add deterministic non-destructive issue-cluster candidates."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_issue_cluster_candidates"
down_revision = "0017_disclosure_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "issue_clusters",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("cluster_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("issue_type", sa.String(length=80), nullable=False),
        sa.Column("window_start", timestamp, nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="candidate"
        ),
        sa.Column("supporter_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index(
        "ix_issue_clusters_issue_window",
        "issue_clusters",
        ["issue_type", "window_start"],
    )

    op.add_column(
        "complaints",
        sa.Column("issue_cluster_id", uuid, nullable=True),
    )
    op.add_column(
        "complaints",
        sa.Column("issue_cluster_supporter_count", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_complaints_issue_cluster_id",
        "complaints",
        ["issue_cluster_id"],
    )
    op.create_foreign_key(
        "fk_complaints_issue_cluster_id",
        "complaints",
        "issue_clusters",
        ["issue_cluster_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "issue_cluster_members",
        sa.Column(
            "complaint_id",
            uuid,
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "cluster_id",
            uuid,
            sa.ForeignKey("issue_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supporter_ref_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
    )
    op.create_index(
        "ix_issue_cluster_members_cluster_id",
        "issue_cluster_members",
        ["cluster_id"],
    )
    op.create_index(
        "ix_issue_cluster_members_cluster_supporter",
        "issue_cluster_members",
        ["cluster_id", "supporter_ref_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_issue_cluster_members_cluster_supporter", table_name="issue_cluster_members"
    )
    op.drop_index("ix_issue_cluster_members_cluster_id", table_name="issue_cluster_members")
    op.drop_table("issue_cluster_members")
    op.drop_constraint(
        "fk_complaints_issue_cluster_id", "complaints", type_="foreignkey"
    )
    op.drop_index("ix_complaints_issue_cluster_id", table_name="complaints")
    op.drop_column("complaints", "issue_cluster_supporter_count")
    op.drop_column("complaints", "issue_cluster_id")
    op.drop_index("ix_issue_clusters_issue_window", table_name="issue_clusters")
    op.drop_table("issue_clusters")
