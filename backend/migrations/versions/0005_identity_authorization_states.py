"""Add durable encrypted OAuth state for DigiLocker authorization."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_identity_auth_state"
down_revision = "0004_identity_verifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "identity_authorization_states",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("subject_ref", sa.String(length=255), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("nonce_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2_000), nullable=False),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("consumed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
    )
    op.create_index(
        "ix_identity_authorization_states_expiry",
        "identity_authorization_states",
        ["expires_at"],
    )
    op.create_index(
        "ix_identity_authorization_states_subject",
        "identity_authorization_states",
        ["subject_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_identity_authorization_states_subject", table_name="identity_authorization_states")
    op.drop_index("ix_identity_authorization_states_expiry", table_name="identity_authorization_states")
    op.drop_table("identity_authorization_states")
