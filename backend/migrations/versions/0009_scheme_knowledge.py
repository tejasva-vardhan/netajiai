"""Add reviewed, source-cited scheme knowledge records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_scheme_knowledge"
down_revision = "0008_routing_activation_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "scheme_records",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scheme_key", sa.String(length=120), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("eligibility_summary", sa.JSON(), nullable=False),
        sa.Column("search_terms", sa.String(length=1_000), nullable=False),
        sa.Column("effective_from", timestamp, nullable=True),
        sa.Column("effective_until", timestamp, nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint(
            "scheme_key",
            "language",
            "version",
            name="uq_scheme_records_key_language_version",
        ),
    )
    op.create_index(
        "ix_scheme_records_jurisdiction_code",
        "scheme_records",
        ["jurisdiction_code"],
    )
    op.create_index(
        "ix_scheme_records_review_status",
        "scheme_records",
        ["review_status"],
    )
    op.create_index(
        "ix_scheme_records_review_validity",
        "scheme_records",
        ["review_status", "effective_from", "effective_until"],
    )
    op.create_table(
        "scheme_sources",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "scheme_id",
            uuid,
            sa.ForeignKey("scheme_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("publisher", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=2_000), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column("retrieved_at", timestamp, nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.UniqueConstraint(
            "scheme_id", "document_hash", name="uq_scheme_sources_scheme_hash"
        ),
    )
    op.create_index("ix_scheme_sources_scheme_id", "scheme_sources", ["scheme_id"])
    op.create_index("ix_scheme_sources_review_status", "scheme_sources", ["review_status"])


def downgrade() -> None:
    op.drop_index("ix_scheme_sources_review_status", table_name="scheme_sources")
    op.drop_index("ix_scheme_sources_scheme_id", table_name="scheme_sources")
    op.drop_table("scheme_sources")
    op.drop_index("ix_scheme_records_review_validity", table_name="scheme_records")
    op.drop_index("ix_scheme_records_review_status", table_name="scheme_records")
    op.drop_index("ix_scheme_records_jurisdiction_code", table_name="scheme_records")
    op.drop_table("scheme_records")
