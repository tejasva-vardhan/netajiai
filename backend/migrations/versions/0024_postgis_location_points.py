"""Add a PostGIS point representation for captured locations.

Revision ID: 0024_postgis_location_points
Revises: 0023_evidence_review_queue
"""

from alembic import op


revision = "0024_postgis_location_points"
down_revision = "0023_evidence_review_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute(
        """
        ALTER TABLE location_samples
        ADD COLUMN location_geog geography(POINT, 4326)
        GENERATED ALWAYS AS (
            ST_SetSRID(
                ST_MakePoint(
                    longitude::double precision,
                    latitude::double precision
                ),
                4326
            )::geography
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_location_samples_location_geog
        ON location_samples
        USING GIST (location_geog)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_location_samples_location_geog")
    op.execute("ALTER TABLE location_samples DROP COLUMN IF EXISTS location_geog")
